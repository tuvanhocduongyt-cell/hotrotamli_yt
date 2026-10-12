import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ['DATA_BACKEND'] = 'json'
import app as web
from PIL import Image
from docx import Document
from utils.data_store import DataStore, DocumentMapping, SupabaseClient, StorageError, ConcurrentWriteError
from scripts.migrate_supabase import inventory, make_manifest, snapshot, migrate, verify


class MemorySupabase:
    """Isolated cloud substitute: intentionally no local-file fallback."""
    def __init__(self):
        self.documents = {}
        self.assets = {}

    def seed(self, name, data):
        self.documents[name] = {'payload': copy.deepcopy(data), 'version': 1}

    def get_document(self, name):
        return copy.deepcopy(self.documents.get(name))

    def save_document(self, name, data, expected_version):
        actual = self.documents.get(name, {}).get('version', 0)
        if actual != expected_version:
            raise ConcurrentWriteError('Conflict')
        self.documents[name] = {'payload': copy.deepcopy(data), 'version': actual + 1}
        return actual + 1

    def append_document(self, name, item):
        row = self.documents[name]
        row['payload'].append(copy.deepcopy(item))
        row['version'] += 1
        return len(row['payload']) - 1

    def put_asset(self, name, content, overwrite=True):
        if name in self.assets and self.assets[name] != content and not overwrite:
            raise StorageError('Conflict')
        self.assets[name] = content
        return self.asset_metadata(name)

    def asset_metadata(self, name):
        content = self.assets.get(name)
        return None if content is None else {'path': name, 'sha256': hashlib.sha256(content).hexdigest()}

    def read_asset(self, name):
        if name not in self.assets:
            raise FileNotFoundError(name)
        return self.assets[name]

    def list_assets(self, prefix):
        return [name for name in sorted(self.assets) if name.startswith(prefix + '/')]

    def delete_asset(self, name):
        self.assets.pop(name, None)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = MemorySupabase()
        self.store = DataStore('supabase', client=self.remote, root=self.root)

    def test_cloud_data_is_authoritative_and_local_json_is_untouched(self):
        local = self.root / 'users.json'
        local.write_text('{"local":true}', encoding='utf-8')
        self.remote.seed('users.json', {'cloud': {'logs': []}})
        with web.app.test_request_context():
            data = self.store.load_document('users.json', {})
            self.assertEqual(list(data), ['cloud'])
            data['cloud']['logs'].append('entry')
            self.store.save_document('users.json', data)
        self.assertEqual(self.remote.documents['users.json']['payload'], data)
        self.assertEqual(local.read_text(), '{"local":true}')

    def test_concurrent_changes_are_rejected_instead_of_lost(self):
        self.remote.seed('users.json', {})
        with web.app.test_request_context():
            data = self.store.load_document('users.json', {})
            self.remote.save_document('users.json', {'another_request': True}, 1)
            data['stale_request'] = True
            with self.assertRaises(ConcurrentWriteError):
                self.store.save_document('users.json', data)
        self.assertEqual(self.remote.documents['users.json']['payload'], {'another_request': True})

    def test_atomic_append_keeps_original_submission_indexes(self):
        self.remote.seed('exam_submissions.json', [{'student': 'first'}])
        with web.app.test_request_context():
            self.store.load_document('exam_submissions.json', [])
            self.remote.append_document('exam_submissions.json', {'student': 'concurrent'})
            index = self.store.append_document('exam_submissions.json', {'student': 'last'})
        self.assertEqual(index, 2)
        self.assertEqual([s['student'] for s in self.remote.documents['exam_submissions.json']['payload']],
                         ['first', 'concurrent', 'last'])

    def test_missing_or_unavailable_cloud_never_falls_back(self):
        (self.root / 'users.json').write_text('{"local":true}')
        with self.assertRaises(StorageError):
            self.store.load_document('users.json', {})
        with patch.object(self.remote, 'get_document', side_effect=StorageError('Unavailable')):
            with self.assertRaises(StorageError):
                self.store.load_document('users.json', {})

    def test_private_asset_round_trip_and_path_validation(self):
        self.store.write_asset('uploads/ảnh.png', b'image-content')
        self.assertEqual(self.store.read_asset('uploads\\ảnh.png'), b'image-content')
        cached = Path(self.store.local_asset('uploads/ảnh.png'))
        self.assertEqual(cached.read_bytes(), b'image-content')
        self.assertFalse((self.root / 'uploads' / 'ảnh.png').exists())
        with self.assertRaises(StorageError):
            self.store.read_asset('../outside.txt')
        self.store.delete_asset('uploads/ảnh.png')
        self.assertFalse(self.store.asset_exists('uploads/ảnh.png'))

    def test_drafts_survive_new_store_instances(self):
        drafts = DocumentMapping(self.store, 'drafts.json')
        drafts['token'] = {'title': 'Đề mới'}
        new_store = DataStore('supabase', client=self.remote, root=self.root)
        self.assertEqual(DocumentMapping(new_store, 'drafts.json')['token'], {'title': 'Đề mới'})

    def test_http_client_redacts_errors_and_maps_write_conflicts(self):
        client = SupabaseClient('https://example.supabase.co', 'server-secret')
        error = urllib.error.HTTPError('https://example.supabase.co', 401, 'Unauthorized', {}, io.BytesIO(b'{"message":"server-secret"}'))
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(StorageError) as caught:
                client.get_document('users.json')
        self.assertNotIn('server-secret', str(caught.exception))
        for code in ('40001', 'PT409'):
            with self.subTest(code=code):
                error = urllib.error.HTTPError('https://example.supabase.co', 409, 'Conflict', {}, io.BytesIO(json.dumps({'code': code}).encode()))
                with patch('urllib.request.urlopen', side_effect=error):
                    with self.assertRaises(ConcurrentWriteError):
                        client.save_document('users.json', {}, 1)

    def test_migration_is_repeatable_and_preserves_json_and_file_bytes(self):
        (self.root / 'users.json').write_text('{"student":{"logs":["tâm lý"]}}', encoding='utf-8')
        (self.root / '.env').write_text('SECRET=do-not-back-up')
        (self.root / 'uploads').mkdir()
        (self.root / 'uploads' / 'ảnh.bin').write_bytes(bytes(range(256)))
        documents, assets, checksums, missing = inventory(self.root)
        self.assertEqual(missing, [])
        manifest = make_manifest(documents, assets, checksums, missing)
        archive = self.root / 'backup.zip'
        snapshot(self.root, archive, manifest)
        with zipfile.ZipFile(archive) as backup:
            self.assertNotIn('.env', backup.namelist())
            self.assertEqual(backup.read('uploads/ảnh.bin'), bytes(range(256)))
        migrate(self.remote, documents, assets)
        versions = {name: row['version'] for name, row in self.remote.documents.items()}
        migrate(self.remote, documents, assets)
        self.assertEqual(versions, {name: row['version'] for name, row in self.remote.documents.items()})
        verify(self.remote, documents, assets)
        self.remote.seed('users.json', {'different': True})
        with self.assertRaises(StorageError):
            migrate(self.remote, documents, assets)
        self.assertEqual(self.remote.documents['users.json']['payload'], {'different': True})

    def test_missing_source_images_are_reported(self):
        (self.root / 'exam_submissions.json').write_text('[{"image_path":"uploads/missing.png"}]')
        self.assertEqual(inventory(self.root)[3], ['uploads/missing.png'])


class CloudRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = MemorySupabase()
        self.store = DataStore('supabase', client=self.remote, root=self.root)
        self.enterContext(patch.object(web, 'storage', self.store))
        self.enterContext(patch.object(web, 'TEMP_EXAMS', DocumentMapping(self.store, 'drafts.json')))
        self.enterContext(patch.dict(web.app.config, TESTING=True, UPLOAD_FOLDER=str(self.root / 'uploads')))
        for name, data in [('users.json', {}), ('scores.json', []), ('chat_feedback.json', []),
                           ('exams_data.json', {}), ('exam_submissions.json', []), ('materials_data.json', []),
                           ('students_exam.json', {}), ('teachers_exam.json', {})]:
            self.remote.seed(name, data)
        self.client = web.app.test_client()

    def login(self, role='student'):
        with self.client.session_transaction() as session:
            session['exam_username'] = 'synthetic-student'
            session['exam_role'] = role

    def test_registration_journal_feedback_and_game_scores_use_cloud(self):
        response = self.client.post('/register', data={'username': 'synthetic', 'password': 'test-only'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('synthetic', self.remote.documents['users.json']['payload'])
        self.client.post('/login', data={'username': 'synthetic', 'password': 'test-only'})
        response = self.client.post('/emotion_journal', data={'emotion': 'Vui', 'note': 'Test'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.remote.documents['users.json']['payload']['synthetic']['logs']), 1)
        response = self.client.post('/chat_feedback', json={'rating': 'Hài lòng', 'bot': 'tam_li'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.remote.documents['chat_feedback.json']['payload']), 1)
        with self.client.session_transaction() as session:
            session['nickname'], session['bai'] = 'Synthetic', 'bai_1'
        self.assertEqual(self.client.post('/submit_score', json={'score': 8}).status_code, 200)
        self.assertEqual(self.remote.documents['scores.json']['payload'][0]['score'], 8)
        self.assertEqual(self.client.get('/leaderboard').status_code, 200)
        self.assertEqual(list(self.root.glob('*.json')), [])

    def test_uploaded_submission_and_image_remain_available_without_local_copy(self):
        self.login()
        self.remote.seed('exams_data.json', {'test': {'type': 'essay', 'title': 'Synthetic', 'grade': '10',
                         'essay_question': 'Question', 'grading_criteria': 'Criteria'}})
        image = io.BytesIO()
        Image.new('RGB', (10, 10), 'white').save(image, format='PNG')
        image.seek(0)
        with patch.object(web, 'auto_grade_essay_with_ai', return_value={'score': 2, 'strengths': 'Good'}):
            response = self.client.post('/do_exam/test', data={'essay_image': (image, 'test.png')}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        submission = self.remote.documents['exam_submissions.json']['payload'][0]
        self.assertEqual(submission['score'], 2)
        filename = Path(submission['image_path']).name
        Path(submission['image_path']).unlink()
        response = self.client.get('/uploads/' + filename)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[:8], b'\x89PNG\r\n\x1a\n')

    def test_material_upload_and_download_use_storage(self):
        self.login('teacher')
        response = self.client.post('/upload_material', data={'title': 'PDF', 'grade': '10',
            'material_type': 'file', 'material_file': (io.BytesIO(b'%PDF-test'), 'test.pdf')})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.remote.documents['materials_data.json']['payload']), 1)
        (self.root / 'uploads' / 'test.pdf').unlink()
        response = self.client.get('/download_material/test.pdf')
        self.assertEqual(response.data, b'%PDF-test')

    def test_word_exam_draft_is_saved_in_cloud(self):
        self.login('teacher')
        document = Document()
        document.add_paragraph('Câu 1. Một câu hỏi? A. Một B. Hai C. Ba D. Bốn')
        buffer = io.BytesIO()
        document.save(buffer)
        buffer.seek(0)
        parsed = {'multiple_choice': [{'question': 'Test', 'options': ['A', 'B', 'C', 'D'], 'answer': 'A'}],
                  'true_false': [], 'essay': []}
        with patch.object(web, 'generate_exam_from_text', return_value=parsed):
            response = self.client.post('/create_exam', data={'action': 'create', 'exam_type': 'multiple_choice',
                'grade': '10', 'title': 'Test', 'word_file': (buffer, 'test.docx')})
        self.assertEqual(response.status_code, 302)
        self.assertIn('preview_exam', response.location)
        self.assertEqual(len(self.remote.documents['drafts.json']['payload']), 1)
        self.assertIn('uploads/test.docx', self.remote.assets)

    def test_cloud_failure_returns_error_without_writing_local_data(self):
        with patch.object(self.remote, 'get_document', side_effect=StorageError('Unavailable')):
            response = self.client.post('/register', data={'username': 'synthetic', 'password': 'test-only'})
        self.assertEqual(response.status_code, 503)
        self.assertFalse((self.root / 'users.json').exists())

    def test_draft_is_not_deleted_when_exam_save_fails(self):
        self.login('teacher')
        draft = {'title': 'Draft', 'type': 'multiple_choice', 'duration': 60, 'grade': '10',
                 'questions': {'multiple_choice': []}, 'general_grading_criteria': ''}
        self.remote.seed('drafts.json', {'token': draft})
        with patch.object(web, 'save_exams_data', side_effect=StorageError('Unavailable')):
            response = self.client.post('/create_exam', data={'action': 'save', 'token': 'token'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.remote.documents['drafts.json']['payload']['token'], draft)
