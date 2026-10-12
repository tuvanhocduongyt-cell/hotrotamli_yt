"""Exercise submission persistence and result pages with synthetic exams only."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
os.environ['DATA_BACKEND'] = 'json'
import app as web
from utils import gemini_api as api


class SubmissionFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.exams_file = root / 'exams.json'
        self.submissions_file = root / 'submissions.json'
        self.exam = {'title': 'Đề kiểm thử', 'type': 'essay', 'grade': '10',
                     'essay_question': 'Chiến thắng Điện Biên Phủ diễn ra năm nào?',
                     'grading_criteria': 'Trả lời năm 1954 được 3 điểm.'}
        self.exams_file.write_text(json.dumps({'test': self.exam}), encoding='utf-8')
        self.submissions_file.write_text('[]', encoding='utf-8')
        self.enterContext(patch.object(web, 'EXAMS_DATA_FILE', str(self.exams_file)))
        self.enterContext(patch.object(web, 'EXAM_SUBMISSIONS_FILE', str(self.submissions_file)))
        self.enterContext(patch.dict(web.app.config, TESTING=True, UPLOAD_FOLDER=str(root)))
        self.enterContext(patch.object(api, 'OPENROUTER_KEYS', []))
        self.enterContext(patch.dict(api._gemini_cooldowns, {}, clear=True))
        self.enterContext(patch.object(api, '_gemini_counter', 0))
        self.client = web.app.test_client()
        with self.client.session_transaction() as session:
            session['exam_username'] = 'synthetic-student'
            session['exam_role'] = 'student'

    def image(self):
        image = Image.new('RGBA', (900, 160), 'white')
        ImageDraw.Draw(image).text((25, 40), 'Dien Bien Phu: 1954.', fill='black', font_size=36)
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer, 'synthetic.png'

    def response(self, score=3):
        grade = {'score': score, 'strengths': 'Đúng năm.', 'weaknesses': '',
                 'missing_knowledge': '', 'improvement_areas': '', 'suggestions': 'Tiếp tục ôn tập.'}
        return io.BytesIO(json.dumps({'candidates': [{'finishReason': 'STOP', 'content': {
            'parts': [{'text': json.dumps(grade)}]}}]}).encode())

    def quota_error(self):
        body = {'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '39414s'}]}}
        return api.urllib.error.HTTPError('https://example.test', 429, 'Daily quota', {}, io.BytesIO(json.dumps(body).encode()))

    def saved_submission(self):
        return json.loads(self.submissions_file.read_text(encoding='utf-8'))[0]

    def test_image_submission_rotates_key_and_displays_saved_grade(self):
        with patch.object(api, 'GEMINI_KEYS', ['first', 'second']), \
             patch.object(api.urllib.request, 'urlopen', side_effect=[self.quota_error(), self.response()]) as call, \
             patch.object(api._time, 'sleep') as sleep:
            response = self.client.post('/do_exam/test', data={'essay_image': self.image()}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('AI đã chấm', response.get_data(as_text=True))
        self.assertIn('Đúng năm.', response.get_data(as_text=True))
        saved = self.saved_submission()
        self.assertEqual(saved['score'], 3)
        self.assertTrue(saved['ai_graded'])
        self.assertTrue(Path(saved['image_path']).exists())
        self.assertEqual([c.args[0].get_header('X-goog-api-key') for c in call.call_args_list], ['first', 'second'])
        self.assertIn('inline_data', json.loads(call.call_args.args[0].data)['contents'][0]['parts'][0])
        sleep.assert_not_called()

    def test_failed_submission_is_saved_and_not_claimed_as_graded(self):
        with patch.object(api, 'GEMINI_KEYS', ['first', 'second']), \
             patch.object(api.urllib.request, 'urlopen', side_effect=[self.quota_error(), self.quota_error()]):
            response = self.client.post('/do_exam/test', data={'essay_image': self.image()}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        saved = self.saved_submission()
        self.assertIsNone(saved['score'])
        self.assertFalse(saved['ai_graded'])
        self.assertTrue(Path(saved['image_path']).exists())
        self.assertIn('Bài đã nộp, chưa chấm xong', response.get_data(as_text=True))
        self.assertNotIn('AI đã chấm', response.get_data(as_text=True))

    def test_old_inconsistent_submission_shows_pending_for_student_and_teacher(self):
        old = {'exam_id': 'test', 'student': 'synthetic-student', 'type': 'essay',
               'score': None, 'ai_graded': True, 'essay_answer': '', 'ai_feedback': None}
        self.submissions_file.write_text(json.dumps([old]), encoding='utf-8')
        for role in ('student', 'teacher'):
            with self.subTest(role=role):
                with self.client.session_transaction() as session:
                    session['exam_role'] = role
                response = self.client.get('/view_submission/0')
                self.assertEqual(response.status_code, 200)
                self.assertIn('Bài đã nộp, chưa chấm xong', response.get_data(as_text=True))
                self.assertNotIn('AI đã chấm', response.get_data(as_text=True))
                with patch.object(web, 'load_materials_data', return_value=[]), \
                     patch.object(web, 'FEEDBACK_FILE', str(Path(self.temp.name) / 'missing-feedback.json')):
                    dashboard = self.client.get('/dashboard_' + role)
                self.assertEqual(dashboard.status_code, 200)
                self.assertIn('/view_submission/0', dashboard.get_data(as_text=True))
                self.assertNotIn('AI đã chấm', dashboard.get_data(as_text=True))

    def test_mixed_essay_failure_does_not_become_zero_final_score(self):
        self.exam.update(type='mixed', questions={'multiple_choice': [], 'true_false': [],
                         'essay': [{'question': 'Năm diễn ra chiến thắng Điện Biên Phủ?'}]})
        self.exams_file.write_text(json.dumps({'test': self.exam}), encoding='utf-8')
        with patch.object(web, 'auto_grade_mixed_essay_with_ai', return_value=None):
            response = self.client.post('/do_exam/test', data={'essay_0': '1954'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        saved = self.saved_submission()
        self.assertIsNone(saved['score'])
        self.assertIsNone(saved['essay_ai_feedback'][0]['score'])
        self.assertFalse(saved['ai_graded'])
        self.assertNotIn('AI đã chấm', response.get_data(as_text=True))

    @unittest.skipUnless(os.getenv('RUN_GEMINI_FLOW_LIVE') == '1', 'Live submission test is opt-in')
    def test_live_image_submission(self):
        response = self.client.post('/do_exam/test', data={'essay_image': self.image()}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        saved = self.saved_submission()
        self.assertTrue(saved['ai_graded'], 'Gemini did not finish grading')
        self.assertIsInstance(saved['score'], (int, float))
        self.assertTrue(saved['ai_feedback'])
        self.assertIn('AI đã chấm', response.get_data(as_text=True))
