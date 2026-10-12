"""JSON-compatible persistence backed by Supabase PostgreSQL and private Storage.

DATA_BACKEND=json is the explicit pre-migration mode. Supabase failures never fall
back to local files. Runtime cloud credentials stay on the Flask server.
"""
import copy
import hashlib
import io
import json
import mimetypes
import os
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import MutableMapping
from contextvars import ContextVar
from pathlib import Path

from dotenv import load_dotenv
from flask import g, has_request_context

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env', encoding='utf-8-sig')
_versions = ContextVar('document_versions', default=None)
_local_lock = threading.RLock()


class StorageError(RuntimeError):
    pass


class ConcurrentWriteError(StorageError):
    pass


def _atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix='.write-')
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SupabaseClient:
    def __init__(self, url=None, key=None, bucket=None):
        self.url = (url or os.getenv('SUPABASE_URL', '')).rstrip('/')
        self.key = key or os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SECRET_KEY')
        self.bucket = bucket or os.getenv('SUPABASE_STORAGE_BUCKET', 'yt-private-data')
        parsed = urllib.parse.urlsplit(self.url)
        if parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment or not self.key:
            raise StorageError('Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SECRET_KEY).')

    def request(self, method, path, *, payload=None, body=None, headers=None, raw=False):
        request_headers = {'apikey': self.key, 'Authorization': 'Bearer ' + self.key}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
            request_headers['Content-Type'] = 'application/json'
        request_headers.update(headers or {})
        request = urllib.request.Request(self.url + path, data=body, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                content = response.read()
                return content if raw else (json.loads(content) if content else None)
        except urllib.error.HTTPError as error:
            try:
                code = json.loads(error.read()).get('code', '')
            except (ValueError, AttributeError):
                code = ''
            if code in ('40001', 'PT409'):
                raise ConcurrentWriteError('Dữ liệu vừa được cập nhật ở nơi khác. Hãy tải lại trước khi lưu.') from None
            # Response bodies can contain user data; do not propagate them into logs.
            raise StorageError(f'Supabase request failed (HTTP {error.code}).') from None
        except (urllib.error.URLError, TimeoutError) as error:
            raise StorageError('Cannot reach Supabase; no local fallback was used.') from None

    def get_document(self, name):
        query = urllib.parse.urlencode({'name': 'eq.' + name, 'select': 'payload,version'})
        rows = self.request('GET', '/rest/v1/yt_documents?' + query)
        return rows[0] if rows else None

    def save_document(self, name, data, expected_version):
        return self.request('POST', '/rest/v1/rpc/yt_save_document', payload={
            'p_name': name, 'p_payload': data, 'p_expected_version': expected_version})

    def append_document(self, name, item):
        return self.request('POST', '/rest/v1/rpc/yt_append_document', payload={'p_name': name, 'p_item': item})

    def asset_metadata(self, path):
        query = urllib.parse.urlencode({'path': 'eq.' + path, 'select': '*'})
        rows = self.request('GET', '/rest/v1/yt_assets?' + query)
        return rows[0] if rows else None

    def list_assets(self, prefix):
        paths = []
        offset = 0
        while True:
            query = urllib.parse.urlencode({'path': 'like.' + prefix.rstrip('/') + '/*', 'select': 'path',
                                           'order': 'path', 'offset': offset, 'limit': 500})
            rows = self.request('GET', '/rest/v1/yt_assets?' + query)
            paths.extend(row['path'] for row in rows)
            if len(rows) < 500:
                return paths
            offset += len(rows)

    def object_url(self, key):
        return '/storage/v1/object/' + urllib.parse.quote(self.bucket, safe='') + '/' + urllib.parse.quote(key, safe='/')

    def put_asset(self, path, content, *, overwrite=True):
        digest = hashlib.sha256(content).hexdigest()
        previous = self.asset_metadata(path)
        if previous and previous['sha256'] == digest:
            return previous
        if previous and not overwrite:
            raise StorageError(f'Refusing to overwrite a different remote asset: {path}')
        # ASCII, content-addressed keys support original Unicode filenames without collisions.
        object_key = hashlib.sha256(path.encode('utf-8')).hexdigest() + '/' + digest
        content_type = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        self.request('POST', self.object_url(object_key), body=content,
                     headers={'Content-Type': content_type, 'x-upsert': 'true'}, raw=True)
        metadata = {'path': path, 'object_key': object_key, 'sha256': digest,
                    'size_bytes': len(content), 'content_type': content_type}
        self.request('POST', '/rest/v1/yt_assets?on_conflict=path', payload=metadata,
                     headers={'Prefer': 'resolution=merge-duplicates,return=minimal'})
        return metadata

    def read_asset(self, path):
        metadata = self.asset_metadata(path)
        if metadata is None:
            raise FileNotFoundError(path)
        content = self.request('GET', self.object_url(metadata['object_key']), raw=True)
        if hashlib.sha256(content).hexdigest() != metadata['sha256']:
            raise StorageError('Supabase asset checksum mismatch.')
        return content

    def delete_asset(self, path):
        metadata = self.asset_metadata(path)
        if metadata:
            self.request('DELETE', '/storage/v1/object/' + urllib.parse.quote(self.bucket, safe=''),
                         payload={'prefixes': [metadata['object_key']]})
            query = urllib.parse.urlencode({'path': 'eq.' + path})
            self.request('DELETE', '/rest/v1/yt_assets?' + query)


class DataStore:
    def __init__(self, backend=None, client=None, root=ROOT):
        self.backend = backend or os.getenv('DATA_BACKEND', 'json')
        if self.backend not in ('json', 'supabase'):
            raise StorageError('DATA_BACKEND must be json or supabase.')
        self.root = Path(root).resolve()
        self.client = client or (SupabaseClient() if self.backend == 'supabase' else None)

    def local_path(self, path):
        path = Path(str(path).replace('\\', '/'))
        return path if path.is_absolute() else self.root / path

    def key(self, path):
        resolved = self.local_path(path).resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError:
            raise StorageError('Asset/document path is outside the application directory.') from None
        return relative.as_posix()

    def versions(self):
        if has_request_context():
            if not hasattr(g, '_document_versions'):
                g._document_versions = {}
            return g._document_versions
        versions = dict(_versions.get() or {})
        _versions.set(versions)
        return versions

    def load_document(self, path, default=None):
        if self.backend == 'json':
            local = self.local_path(path)
            if not local.exists():
                return copy.deepcopy(default)
            return json.loads(local.read_text(encoding='utf-8-sig'))
        name = self.key(path)
        row = self.client.get_document(name)
        self.versions()[name] = row['version'] if row else 0
        if row is None:
            if name == 'drafts.json':
                return copy.deepcopy(default)
            raise StorageError(f'Document is not migrated to Supabase: {name}')
        return copy.deepcopy(row['payload'])

    def save_document(self, path, data):
        if self.backend == 'json':
            with _local_lock:
                _atomic_write(self.local_path(path), json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'))
            return
        name = self.key(path)
        versions = self.versions()
        if name not in versions:
            raise StorageError('Load a document before saving it to prevent overwriting concurrent changes.')
        versions[name] = self.client.save_document(name, data, versions[name])

    def append_document(self, path, item):
        if self.backend == 'supabase':
            name = self.key(path)
            index = self.client.append_document(name, item)
            self.versions().pop(name, None)
            return index
        with _local_lock:
            data = self.load_document(path, [])
            data.append(item)
            self.save_document(path, data)
            return len(data) - 1

    def read_asset(self, path):
        if self.backend == 'json':
            return self.local_path(path).read_bytes()
        return self.client.read_asset(self.key(path))

    def read_text(self, path):
        return self.read_asset(path).decode('utf-8-sig')

    def list_assets(self, folder):
        if self.backend == 'json':
            directory = self.local_path(folder)
            return [str(path) for path in sorted(directory.rglob('*')) if path.is_file()] if directory.exists() else []
        return self.client.list_assets(self.key(folder))

    def write_asset(self, path, content):
        if self.backend == 'supabase':
            self.client.put_asset(self.key(path), content)
        else:
            _atomic_write(self.local_path(path), content)

    def save_upload(self, upload, path):
        content = upload.read()
        self.write_asset(path, content)
        # A local working copy is needed for OCR/Word/PIL in the current request.
        if self.backend == 'supabase':
            _atomic_write(self.local_path(path), content)

    def local_asset(self, path):
        if self.backend == 'json':
            return str(self.local_path(path))
        content = self.read_asset(path)
        key = self.key(path)
        cache = self.root / '.data-cache' / hashlib.sha256(key.encode()).hexdigest() / Path(key).name
        _atomic_write(cache, content)
        return str(cache)

    def asset_exists(self, path):
        if self.backend == 'json':
            return self.local_path(path).is_file()
        return self.client.asset_metadata(self.key(path)) is not None

    def delete_asset(self, path):
        if self.backend == 'supabase':
            self.client.delete_asset(self.key(path))
        local = self.local_path(path)
        if local.exists():
            local.unlink()


class DocumentMapping(MutableMapping):
    """Persist temporary exam drafts as well, across workers and restarts."""
    def __init__(self, store, path):
        self.store, self.path = store, path

    def __getitem__(self, key):
        return self.store.load_document(self.path, {})[key]

    def __setitem__(self, key, value):
        data = self.store.load_document(self.path, {})
        data[key] = value
        self.store.save_document(self.path, data)

    def __delitem__(self, key):
        data = self.store.load_document(self.path, {})
        del data[key]
        self.store.save_document(self.path, data)

    def __iter__(self):
        return iter(self.store.load_document(self.path, {}))

    def __len__(self):
        return len(self.store.load_document(self.path, {}))
