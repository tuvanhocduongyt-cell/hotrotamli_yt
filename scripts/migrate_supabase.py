"""Snapshot, migrate and verify GitHub JSON/files without overwriting cloud data.

Run from the repository root:
  venv/Scripts/python scripts/migrate_supabase.py --plan
  venv/Scripts/python scripts/migrate_supabase.py --apply --activate

Run supabase/schema.sql in the dashboard first. No database password is required.
"""
import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import set_key
from utils.data_store import SupabaseClient, StorageError


def digest(content):
    return hashlib.sha256(content).hexdigest()


def document_digest(payload):
    return digest(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def inventory(source):
    source = Path(source).resolve()
    files = set()
    for pattern in ('*.json', '*.txt', '*.docx', '*.pdf'):
        files.update(path for path in source.glob(pattern) if path.name != 'requirements.txt')
    for folder in ('uploads', 'data', 'static/replies'):
        files.update(path for path in (source / folder).rglob('*') if path.is_file())
    files = sorted(files)
    documents, assets, checksums = {}, {}, {}
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise StorageError('Refusing a data file that points outside the source directory.')
        name = path.relative_to(source).as_posix()
        content = path.read_bytes()
        checksums[name] = digest(content)
        if path.parent == source and path.suffix == '.json':
            payload = json.loads(content.decode('utf-8-sig'))
            document_digest(payload)  # Reject non-JSON NaN/Infinity before any uploads.
            documents[name] = payload
        else:
            assets[name] = content
    documents.setdefault('drafts.json', {})
    references = set()
    for submission in documents.get('exam_submissions.json', []):
        if submission.get('image_path'):
            references.add(submission['image_path'].replace('\\', '/'))
        for answer in submission.get('answers', {}).get('essay', []):
            if isinstance(answer, dict) and answer.get('image_path'):
                references.add(answer['image_path'].replace('\\', '/'))
    for material in documents.get('materials_data.json', []):
        if isinstance(material, dict) and material.get('type') == 'file' and material.get('filename'):
            references.add('uploads/' + material['filename'])
    missing = sorted(path for path in references if path not in assets)
    return documents, assets, checksums, missing


def make_manifest(documents, assets, checksums, missing):
    return {
        'source': 'GitHub checkout/local data',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'documents': {name: {'sha256': document_digest(data), 'type': type(data).__name__,
                             'items': len(data) if isinstance(data, (list, dict)) else None}
                      for name, data in documents.items()},
        'assets': {name: {'sha256': digest(data), 'bytes': len(data)} for name, data in assets.items()},
        'source_file_checksums': checksums,
        'missing_referenced_files': missing,
    }


def snapshot(source, destination, manifest):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, expected in manifest['source_file_checksums'].items():
            content = (source / name).read_bytes()
            if digest(content) != expected:
                raise StorageError('Source changed while taking the backup; rerun migration.')
            archive.writestr(name, content)
        archive.writestr('_migration_manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))


def verify(client, documents, assets):
    for name, expected in documents.items():
        row = client.get_document(name)
        if row is None or row['payload'] != expected:
            raise StorageError(f'Document verification failed: {name}')
    for index, (name, expected) in enumerate(assets.items(), 1):
        if digest(client.read_asset(name)) != digest(expected):
            raise StorageError(f'Asset verification failed: {name}')
        if index % 10 == 0 or index == len(assets):
            print(f'Verified file contents: {index}/{len(assets)}', flush=True)


def migrate(client, documents, assets):
    # Preflight *all* names to avoid a partially applied overwrite if a target conflicts.
    for name, payload in documents.items():
        row = client.get_document(name)
        if row is not None and row['payload'] != payload:
            raise StorageError(f'Remote document differs; nothing will overwrite it: {name}')
    for name, content in assets.items():
        metadata = client.asset_metadata(name)
        if metadata and metadata['sha256'] != digest(content):
            raise StorageError(f'Remote asset differs; nothing will overwrite it: {name}')
    for name, payload in documents.items():
        row = client.get_document(name)
        if row is None:
            client.save_document(name, payload, 0)
    print(f'Documents copied: {len(documents)}', flush=True)
    for index, (name, content) in enumerate(assets.items(), 1):
        client.put_asset(name, content, overwrite=False)
        if index % 10 == 0 or index == len(assets):
            print(f'Files copied: {index}/{len(assets)}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--plan', action='store_true')
    action.add_argument('--apply', action='store_true')
    action.add_argument('--verify', action='store_true')
    parser.add_argument('--activate', action='store_true', help='Enable DATA_BACKEND=supabase only after successful copy and verification.')
    parser.add_argument('--source', type=Path, default=ROOT)
    args = parser.parse_args()
    if args.activate and not args.apply:
        parser.error('--activate requires --apply')
    source = args.source.resolve()
    documents, assets, checksums, missing = inventory(source)
    manifest = make_manifest(documents, assets, checksums, missing)
    output = ROOT / '.migration-backups'
    output.mkdir(exist_ok=True)
    (output / 'plan.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Source documents: {len(documents)}; files: {len(assets)}; file bytes: {sum(map(len, assets.values()))}', flush=True)
    print(f'Missing referenced files in source: {len(missing)}', flush=True)
    if args.plan:
        return
    if missing:
        raise StorageError('Some referenced files are missing from the source. See .migration-backups/plan.json before activation.')
    client = SupabaseClient()
    # Schema and bucket checks happen before uploads or writes.
    client.request('GET', '/rest/v1/yt_documents?select=name&limit=1')
    bucket = client.request('GET', '/storage/v1/bucket/' + client.bucket)
    if bucket.get('public') is not False:
        raise StorageError('The migration bucket must be private.')
    if args.apply:
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        snapshot(source, output / f'before-supabase-{timestamp}.zip', manifest)
        print('Local backup created; original files are preserved.', flush=True)
        migrate(client, documents, assets)
    verify(client, documents, assets)
    if inventory(source)[2] != checksums:
        raise StorageError('Source changed during migration; backend was not activated.')
    summary = {'verified': True, 'documents': len(documents), 'files': len(assets),
               'file_bytes': sum(map(len, assets.values())), 'source': str(source),
               'verified_at': datetime.now(timezone.utc).isoformat()}
    (output / 'verified.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    if args.activate:
        set_key(str(ROOT / '.env'), 'DATA_BACKEND', 'supabase', quote_mode='never', encoding='utf-8-sig')
        print('DATA_BACKEND=supabase activated. Restart the application.', flush=True)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (StorageError, OSError, ValueError) as error:
        print(f'Migration stopped: {error}', file=sys.stderr)
        sys.exit(1)
