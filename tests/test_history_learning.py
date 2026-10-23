"""Offline behavioral checks; no real student data or paid API calls."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ['DATA_BACKEND'] = 'json'
import app as web
from utils.data_store import DataStore
from utils.gemini_api import _FakeResponse
from utils import gemini_api as api
from utils.history_learning import CRITERIA
from utils.history_sources import HistorySources


def feedback(score=1):
    return {'criteria': [dict(key=k, score=score, level='Chưa rõ', comment='Cần dẫn căn cứ từ trang PDF 28.') for k, _ in CRITERIA],
            'strengths': 'Đã nêu nhận định.', 'improvements': 'Cần xem xét phản bác.',
            'rewrite_hint': 'Bằng chứng nào có thể làm em thay đổi kết luận?'}


class LearningFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DataStore(backend='json', root=self.temp.name)
        self.task = dict(id='task1', title='Đánh giá nhận định lịch sử', mode='task', lesson='4',
                         situation='Một nhận định cần kiểm chứng.', objective='Xét nhiều góc nhìn.',
                         instructions='Dùng SGK làm căn cứ.', sources=[dict(book='sgk', page=28, label='SGK · PDF 28')])
        self.store.save_document('learning_tasks.json', {'task1': self.task})
        self.store.save_document('learning_events.json', [])
        self.enterContext(patch.object(web, 'storage', self.store))
        self.enterContext(patch.object(HistorySources, 'parts', return_value=['Ảnh trang SGK gốc']))
        self.client = web.app.test_client()
        self.client.get('/learning')
        self.login('student1')

    def login(self, user, role='student'):
        with self.client.session_transaction() as session:
            session['exam_username'] = user
            session['exam_role'] = role
            session['learning_csrf'] = 'test-csrf'

    def post(self, path, body):
        return self.client.post(path, json=body, headers={'X-Learning-CSRF': 'test-csrf'})

    def records(self):
        return self.store.load_document('learning_events.json', [])

    def analyze(self, text, score=1, **extra):
        with patch.object(web, 'generate_with_retry', return_value=_FakeResponse(json.dumps(feedback(score)))):
            return self.post('/api/learning/task/task1/analyze', dict(text=text, **extra))

    def test_revision_retains_both_writings_and_compares_same_task(self):
        first = self.analyze('Bài viết lần đầu.').get_json()
        second = self.analyze('Bài đã bổ sung bằng chứng và phản bác.', 1.5).get_json()
        self.assertEqual(second['delta'], 2)
        attempts = [e for e in self.records() if e['event'] == 'attempt']
        self.assertEqual(attempts[1]['previous_id'], first['attempt_id'])
        self.assertEqual(attempts[0]['text'], 'Bài viết lần đầu.')
        page = self.client.get('/learning/portfolio')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Bài đã bổ sung', page.get_data(as_text=True))
        self.assertIn('+2.00', page.get_data(as_text=True))

    def test_ai_failure_preserves_attempt_and_retry_does_not_duplicate(self):
        with patch.object(web, 'generate_with_retry', side_effect=RuntimeError('quota')):
            result = self.post('/api/learning/task/task1/analyze', {'text': 'Bài cần lưu dù AI lỗi.'})
        self.assertEqual(result.status_code, 502)
        attempt_id = result.get_json()['attempt_id']
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.analyze('Bài cần lưu dù AI lỗi.', retry_id=attempt_id).status_code, 200)
        self.assertEqual(sum(e['event'] == 'attempt' for e in self.records()), 1)

    def test_invalid_ai_scores_are_not_recorded_as_feedback(self):
        invalid = feedback()
        invalid['criteria'][0]['score'] = 100
        with patch.object(web, 'generate_with_retry', return_value=_FakeResponse(json.dumps(invalid))):
            response = self.post('/api/learning/task/task1/analyze', {'text': 'Bài có căn cứ.'})
        self.assertEqual(response.status_code, 502)
        self.assertFalse(any(e['event'] == 'feedback' for e in self.records()))

    def test_numeric_strings_from_provider_are_normalized_but_not_out_of_range(self):
        result = feedback()
        result['criteria'][0]['score'] = '1,5'
        with patch.object(web, 'generate_with_retry', return_value=_FakeResponse(json.dumps(result))):
            response = self.post('/api/learning/task/task1/analyze', {'text': 'Bài có căn cứ.'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['feedback']['score'], 4.5)

    def test_portfolio_privacy_and_teacher_review_visible_to_owner(self):
        attempt_id = self.analyze('Nội dung riêng học sinh một.').get_json()['attempt_id']
        self.login('student2')
        self.assertNotIn('Nội dung riêng', self.client.get('/learning/portfolio').get_data(as_text=True))
        self.assertEqual(self.analyze('Nội dung riêng học sinh một.', retry_id=attempt_id).status_code, 400)
        self.login('teacher1', 'teacher')
        self.assertEqual(self.post('/api/learning/review/' + attempt_id, {'comment': 'Đã tiến bộ ở cách kiểm chứng.'}).status_code, 200)
        self.login('student1')
        self.assertIn('Đã tiến bộ', self.client.get('/learning/portfolio').get_data(as_text=True))

    def test_draft_reload_and_html_content_is_escaped(self):
        text = '<script>alert(1)</script> Bài viết thử.'
        self.assertEqual(self.post('/api/learning/task/task1/draft', {'text': text}).status_code, 200)
        page = self.client.get('/learning/task/task1')
        self.assertEqual(page.status_code, 200)
        self.assertIn('&lt;script&gt;', page.get_data(as_text=True))
        self.assertNotIn('<script>alert(1)</script>', page.get_data(as_text=True))

    def test_auth_csrf_and_teacher_only_generation(self):
        self.assertEqual(self.client.post('/api/learning/task/task1/draft', json={'text': 'test'}).status_code, 403)
        self.assertEqual(self.post('/api/learning/tasks', {'lesson': '4', 'mode': 'task'}).status_code, 403)
        with self.client.session_transaction() as session:
            session.pop('exam_username')
        self.assertEqual(self.post('/api/learning/task/task1/draft', {'text': 'test'}).status_code, 401)

    def test_generated_task_rejects_fabricated_source_pages(self):
        self.login('teacher1', 'teacher')
        generated = dict(title='Tiêu đề', situation='Tình huống', objective='Mục tiêu', instructions='Hướng dẫn', source_pages=[999])
        with patch.object(HistorySources, 'lesson_refs', return_value=[dict(book='sgk', page=28)]), \
                patch.object(web, 'generate_with_retry', return_value=_FakeResponse(json.dumps(generated))):
            response = self.post('/api/learning/tasks', {'lesson': '4', 'mode': 'task'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(len(self.store.load_document('learning_tasks.json')), 1)

    def test_task_and_prompt_generation_and_guided_chat(self):
        self.login('teacher1', 'teacher')
        generated = dict(title='Tiêu đề', situation='Tình huống', objective='Mục tiêu', instructions='Hướng dẫn', source_pages=[28])
        for mode in ('task', 'prompt'):
            with patch.object(HistorySources, 'lesson_refs', return_value=[dict(book='sgk', page=28)]), \
                    patch.object(web, 'generate_with_retry', return_value=_FakeResponse(json.dumps(generated))):
                response = self.post('/api/learning/tasks', {'lesson': '4', 'mode': mode})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.client.get(response.get_json()['url']).status_code, 200)
        self.login('student1')
        with patch.object(web, 'generate_with_retry', return_value=_FakeResponse('Em hãy tìm căn cứ trong SGK.')):
            response = self.post('/api/learning/task/task1/ask', {'text': '', 'question': 'Kiểm chứng thế nào?'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.records()[-1]['event'], 'chat')


class CloudLearningFlow(LearningFlow):
    """The same behavior must hold with atomic cloud append and version checks."""
    def setUp(self):
        super().setUp()
        from test_supabase_storage import MemorySupabase
        client = MemorySupabase()
        client.seed('learning_tasks.json', {'task1': self.task})
        client.seed('learning_events.json', [])
        self.store = DataStore(backend='supabase', client=client, root=self.temp.name)
        self.enterContext(patch.object(web, 'storage', self.store))


class ModelFallback(unittest.TestCase):
    def test_capacity_failure_uses_configured_model_and_retains_model_metadata(self):
        with patch.object(api, 'GEMINI_KEYS', ['synthetic']), patch.object(api, 'OPENROUTER_KEYS', []), \
                patch.object(api, 'GEMINI_MODEL', 'primary'), patch.object(api, 'GEMINI_FALLBACK_MODELS', ['secondary']), \
                patch.object(api, '_generate_with_gemini', side_effect=[
                    RuntimeError('Gemini API error 503: unavailable'), _FakeResponse('OK', model='secondary')]) as generate:
            result = api.generate_with_retry('question', max_retries=1)
        self.assertEqual(result.model, 'secondary')
        self.assertEqual([call.kwargs['model'] for call in generate.call_args_list], ['primary', 'secondary'])

    def test_daily_quota_does_not_trigger_model_fallback(self):
        with patch.object(api, 'GEMINI_KEYS', ['synthetic']), patch.object(api, 'OPENROUTER_KEYS', []), \
                patch.object(api, 'GEMINI_FALLBACK_MODELS', ['secondary']), \
                patch.object(api, '_generate_with_gemini', side_effect=RuntimeError('Gemini API error 429: daily quota')) as generate:
            with self.assertRaises(RuntimeError):
                api.generate_with_retry('question', max_retries=1)
        self.assertEqual(generate.call_count, 1)


if __name__ == '__main__':
    unittest.main()
