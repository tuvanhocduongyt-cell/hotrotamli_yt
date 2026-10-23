"""Import the provided experiment accounts; snapshot changed documents first.

Default is a read-only plan. --apply writes to the configured backend.
Existing accounts with different names are rejected, not overwritten.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils.data_store import DataStore


def experiment_password():
    password = os.getenv('EXPERIMENT_PASSWORD')
    if not password:
        note = ROOT / 'capnhat/ghichu.txt'
        content = note.read_text('utf-8-sig') if note.exists() else ''
        match = re.search(r'mk chung[^\n]*?\blà\s+(\S+)', content, re.IGNORECASE)
        password = match.group(1) if match else None
    if not password:
        raise RuntimeError('Set EXPERIMENT_PASSWORD or provide the original local note.')
    return password


def run(apply=False):
    store = DataStore()
    password = experiment_password()
    changes = []
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    for pattern, name, role in [('*gv*.xlsx', 'teachers_exam.json', 'teacher'),
                                 ('*hs*.xlsx', 'students_exam.json', 'student')]:
        path = next((ROOT / 'capnhat').glob(pattern))
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows = list(workbook.active.values)[1:]
        original = store.load_document(name, {})
        updated = dict(original)
        seen = set()
        for row in rows:
            account = row[3] if role == 'teacher' else row[5]
            if account is None:
                continue
            account = str(account).strip()
            if account in seen:
                raise ValueError('Duplicate account in spreadsheet')
            seen.add(account)
            fullname = str(row[2] if role == 'teacher' else row[3]).strip()
            existing = updated.get(account, {})
            if existing and existing.get('fullname') != fullname:
                raise ValueError('An account belongs to a different person; import aborted')
            record = dict(existing, fullname=fullname, password=password, school=str(row[0] if role == 'teacher' else row[1]).strip())
            record.setdefault('created_at', datetime.now(timezone.utc).isoformat())
            if role == 'teacher':
                record['subject'] = str(row[1]).strip()
            else:
                birth = row[4]
                birth = birth.date().isoformat() if isinstance(birth, datetime) else str(birth or '').strip()
                record.update(grade_level='11', class_name=str(row[2]).strip(),
                              student_id=existing.get('student_id', account), date_of_birth=birth)
            updated[account] = record
        workbook.close()
        print(role, 'provided:', len(seen), 'new:', sum(a not in original for a in seen),
              'changed:', sum(original.get(a) != updated[a] for a in seen))
        changes.append((name, original, updated))
    if apply:
        backup = ROOT / '.migration-backups' / ('experiment-' + stamp)
        backup.mkdir(parents=True)
        for name, original, updated in changes:
            (backup / name).write_text(json.dumps(original, ensure_ascii=False), 'utf-8')
        for name, original, updated in changes:
            if original != updated:
                store.save_document(name, updated)
            if store.load_document(name) != updated:
                raise RuntimeError('Import verification failed')
        print('Applied and verified; backup:', backup.relative_to(ROOT))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    run(parser.parse_args().apply)
