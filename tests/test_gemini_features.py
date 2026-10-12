"""Run offline: python -m unittest discover -s tests -v
Run with real Gemini: set RUN_GEMINI_LIVE=1 before the same command.
All user/exam fixtures are synthetic; uploads stay in a temporary directory.
"""
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
os.environ['DATA_BACKEND'] = 'json'
import app as web
from utils import gemini_api as api

LIVE = os.getenv('RUN_GEMINI_LIVE') == '1'
QUESTION = 'Chiến thắng Điện Biên Phủ diễn ra năm nào?'
MC = {'question': QUESTION, 'options': ['A. 1954', 'B. 1945', 'C. 1975', 'D. 1930'], 'answer': 'A'}
TF = {'question': 'Về chiến thắng Điện Biên Phủ năm 1954',
      'statements': ['Diễn ra năm 1954', 'Diễn ra năm 1945', 'Ở Việt Nam', 'Ở châu Âu'],
      'answers': [True, False, True, False]}
EXAM = {'essay_question': QUESTION, 'grading_criteria': 'Nêu đúng năm 1954 được 3 điểm.'}


class Features(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = web.app.test_client()
        self.enterContext(patch.dict(web.app.config, TESTING=True, UPLOAD_FOLDER=self.temp.name))
        self.enterContext(patch.object(web, 'load_user_data', return_value={'nickname': 'Học sinh kiểm thử'}))
        self.enterContext(patch.object(web.texttospeech, 'TextToSpeechClient', side_effect=RuntimeError('TTS excluded from Gemini tests')))
        self.enterContext(patch.object(api, 'OPENROUTER_KEYS', []))
        self.calls = []
        original = api.generate_with_retry

        def generate(prompt, **kwargs):
            self.calls.append(kwargs)
            if LIVE:
                # The configured free-tier project allows five requests per minute.
                time.sleep(13)
                return original(prompt, **kwargs)
            if kwargs.get('response_mime_type') == 'application/json':
                result = dict(MC, score=3, strengths='Đúng năm.', weaknesses='Không.',
                              missing_knowledge='Không.', improvement_areas='Ôn tập.',
                              suggestions='Ôn tập.', analysis='Đúng năm.',
                              ke_hoach_on_tap='Ôn các mốc thời gian.', cac_chu_de_lien_quan='Lịch sử Việt Nam.',
                              statements=TF['statements'], answers=TF['answers'])
                return api._FakeResponse(json.dumps(result, ensure_ascii=False))
            return api._FakeResponse('Chiến thắng Điện Biên Phủ diễn ra năm 1954.')

        self.enterContext(patch.object(web, 'generate_with_retry', side_effect=generate))
        self.image_path = Path(self.temp.name) / 'synthetic.png'
        image = Image.new('RGBA', (900, 160), 'white')
        ImageDraw.Draw(image).text((25, 40), 'Dien Bien Phu: 1954.', fill='black', font_size=36)
        image.save(self.image_path)

    def assert_reply(self, response):
        self.assertEqual(response.status_code, 200)
        reply = response.get_json()['reply']
        self.assertTrue(reply.strip())
        self.assertNotIn('Xin lỗi', reply)
        self.assertGreater(len(self.calls), 0)

    def test_history_chat(self):
        self.assert_reply(self.client.post('/chat', json={'message': QUESTION}))

    def test_history_stream(self):
        response = self.client.post('/chat_stream', json={'message': QUESTION})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith('data: ')]
        self.assertFalse(any('error' in event for event in events), events)
        self.assertTrue(any(event.get('text') for event in events))
        self.assertTrue(events[-1].get('done'))

    def test_tam_an(self):
        self.assert_reply(self.client.post('/chat_tam_an', json={'message': 'Mình hơi lo trước kỳ thi, cho mình một lời khuyên ngắn.'}))

    def test_psychology_topics(self):
        for topic in ('tam_li', 'stress', 'nghe_nghiep'):
            with self.subTest(topic=topic):
                response = self.client.post('/tro_chuyen_tam_li_cung_tro_ly_ai_pham_hang?topic='+topic,
                                            data={'user_input': 'Cho mình một lời khuyên ngắn về việc học.'})
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('hiện tại trợ lý chưa thể', response.get_data(as_text=True))
        self.assertEqual(len(self.calls), 3)

    def test_legacy_exam_feedback(self):
        with patch.object(web, 'load_exam', return_value={'multiple_choice': [MC], 'true_false': []}):
            response = self.client.post('/submit/synthetic', data={'mc_0': 'B'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Lỗi khi gọi AI', response.get_data(as_text=True))
        self.assertEqual(len(self.calls), 1)

    def test_image_uploads(self):
        for route in ('/upload_image', '/upload_image2', '/upload_image3'):
            with self.subTest(route=route):
                response = self.client.post(route, data={'image': (io.BytesIO(self.image_path.read_bytes()), 'test.png')})
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('Lỗi khi xử lý ảnh', response.get_data(as_text=True))
        self.assertEqual(len(self.calls), 3)

    def assert_grade(self, result, keys):
        self.assertIsInstance(result, dict)
        self.assertTrue(set(keys).issubset(result), result)
        self.assertGreaterEqual(float(result['score']), 0)
        self.assertLessEqual(float(result['score']), 3)
        self.assertEqual(self.calls[-1].get('response_mime_type'), 'application/json')

    def test_essay_text_and_image(self):
        for image in (None, str(self.image_path)):
            with self.subTest(image=bool(image)):
                self.assert_grade(web.auto_grade_essay_with_ai(EXAM, 'Năm 1954.', image),
                                  ['score', 'strengths', 'weaknesses', 'missing_knowledge', 'improvement_areas', 'suggestions'])

    def test_mixed_essay_text_and_image(self):
        for image in (None, str(self.image_path)):
            with self.subTest(image=bool(image)):
                self.assert_grade(web.auto_grade_mixed_essay_with_ai(QUESTION, EXAM['grading_criteria'], 'Năm 1954.', image),
                                  ['score', 'analysis', 'suggestions', 'max_score'])

    def test_error_analysis(self):
        for fn, errors in [(web.analyze_wrong_answers, [{'question': MC, 'user_answer': 'B'}]),
                           (web.analyze_truefalse_errors, [{'question': TF, 'user_answers': [False, False, True, False]}])]:
            with self.subTest(function=fn.__name__):
                result = fn({}, errors)
                self.assertIsInstance(result, dict)
                self.assertTrue(result['ke_hoach_on_tap'])
                self.assertTrue(result['cac_chu_de_lien_quan'])

    def test_repair_mc_and_tf(self):
        for kind, question, field in [('MCQ', MC, 'options'), ('TF', TF, 'statements')]:
            with self.subTest(kind=kind):
                result = web.repair_question_with_ai(json.dumps(question, ensure_ascii=False), kind)
                self.assertIsInstance(result, dict)
                self.assertEqual(len(result[field]), 4)


class Provider(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(api, 'GEMINI_KEYS', ['test-key']))
        self.enterContext(patch.object(api, '_gemini_counter', 0))
        self.enterContext(patch.dict(api._gemini_cooldowns, {}, clear=True))
        self.enterContext(patch.object(api._time, 'monotonic', return_value=1000))

    def test_comma_separated_key_settings(self):
        for name in ('GEMINI_API_KEY', 'GEMINI_API_KEYS', 'GOOGLE_API_KEY'):
            with self.subTest(name=name), patch.dict(os.environ, {name: ' key1, key2,,key1, key3 '}, clear=True):
                self.assertEqual(api._load_gemini_keys(), ['key1', 'key2', 'key3'])

    def test_exhausted_key_switches_immediately_and_stays_on_working_key(self):
        body = {'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '39414s'}]}}
        error = api.urllib.error.HTTPError('https://example.test', 429, 'Daily quota', {}, io.BytesIO(json.dumps(body).encode()))
        result = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': 'OK'}]}}]}
        with patch.object(api, 'GEMINI_KEYS', ['first', 'second']), \
             patch.object(api.urllib.request, 'urlopen', side_effect=[error, self.response(result), self.response(result)]) as call, \
             patch.object(api._time, 'sleep') as sleep:
            self.assertEqual(api._generate_with_gemini('test').text, 'OK')
            self.assertEqual(api._generate_with_gemini('test again').text, 'OK')
            self.assertEqual([c.args[0].get_header('X-goog-api-key') for c in call.call_args_list], ['first', 'second', 'second'])
            sleep.assert_not_called()

    def test_all_keys_exhausted_are_not_retried_until_reset(self):
        body = {'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '39414s'}]}}
        def quota_error(*args, **kwargs):
            raise api.urllib.error.HTTPError('https://example.test', 429, 'Daily quota', {}, io.BytesIO(json.dumps(body).encode()))
        with patch.object(api, 'GEMINI_KEYS', ['first', 'second']), \
             patch.object(api.urllib.request, 'urlopen', side_effect=quota_error) as call, \
             patch.object(api._time, 'sleep') as sleep:
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    api._generate_with_gemini('test')
            self.assertEqual(call.call_count, 2)
            sleep.assert_not_called()

    def test_tam_an_language_retry(self):
        with patch.object(web, 'load_user_data', return_value={}), \
             patch.object(web, 'contains_english', return_value=True), \
             patch.object(web, 'generate_with_retry', side_effect=[
                 api._FakeResponse('Try to relax.'), api._FakeResponse('Bạn hãy nghỉ ngơi một chút.')]) as generate, \
             patch.object(web.texttospeech, 'TextToSpeechClient', side_effect=RuntimeError('TTS excluded')):
            response = web.app.test_client().post('/chat_tam_an', json={'message': 'Mình đang lo.'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['reply'], 'Bạn hãy nghỉ ngơi một chút.')
        self.assertEqual(generate.call_count, 2)

    def test_rgba_and_palette_images(self):
        for mode in ('RGBA', 'P', 'RGB', 'L'):
            parts = api._build_gemini_parts([Image.new(mode, (10, 10)), 'Read this'])
            self.assertEqual(parts[0]['inline_data']['mime_type'], 'image/jpeg')
            self.assertTrue(parts[0]['inline_data']['data'])

    def response(self, data):
        return io.BytesIO(json.dumps(data).encode())

    def test_structured_request_and_thought_filter(self):
        result = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [
            {'text': 'private reasoning', 'thought': True}, {'text': '{"score":3}'}]}}]}
        with patch.object(api.urllib.request, 'urlopen', return_value=self.response(result)) as call:
            reply = api._generate_with_gemini('Grade', response_mime_type='application/json')
        self.assertEqual(json.loads(reply.text), {'score': 3})
        config = json.loads(call.call_args.args[0].data)['generationConfig']
        self.assertEqual(config['responseMimeType'], 'application/json')
        self.assertGreater(config['maxOutputTokens'], 2048)

    def test_truncated_and_blocked_responses_fail(self):
        for result in [{'candidates': [{'finishReason': 'MAX_TOKENS', 'content': {'parts': [{'text': '{"score":'}]}}]},
                       {'promptFeedback': {'blockReason': 'SAFETY'}}]:
            with patch.object(api.urllib.request, 'urlopen', return_value=self.response(result)):
                with self.assertRaises(RuntimeError):
                    api._generate_with_gemini('test')

    def test_retry_and_redaction(self):
        body = {'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '12s'}]}}
        error = api.urllib.error.HTTPError('https://example.test', 429, 'Quota', {}, io.BytesIO(json.dumps(body).encode()))
        result = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': 'OK'}]}}]}
        with patch.object(api.urllib.request, 'urlopen', side_effect=[error, self.response(result)]) as call, patch.object(api._time, 'sleep') as sleep:
            self.assertEqual(api._generate_with_gemini('test', max_retries=2).text, 'OK')
            self.assertEqual(call.call_count, 2)
            sleep.assert_called_once_with(13)
        error = api.urllib.error.HTTPError('https://example.test', 400, 'Bad request', {}, io.BytesIO(b'secret-test'))
        with patch.object(api, 'GEMINI_KEYS', ['secret-test']), patch.object(api.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                api._generate_with_gemini('test', max_retries=1)
            self.assertNotIn('secret-test', str(caught.exception))
        body['error']['details'][0]['retryDelay'] = '39414s'
        error = api.urllib.error.HTTPError('https://example.test', 429, 'Daily quota', {}, io.BytesIO(json.dumps(body).encode()))
        with patch.object(api.urllib.request, 'urlopen', side_effect=error) as call, patch.object(api._time, 'sleep') as sleep:
            with self.assertRaises(RuntimeError):
                api._generate_with_gemini('test')
            self.assertEqual(call.call_count, 1)
            sleep.assert_not_called()
        with patch.object(api, 'GEMINI_KEYS', ['timeout-first', 'timeout-second']), \
             patch.object(api.urllib.request, 'urlopen', side_effect=[TimeoutError(), self.response(result)]) as call, \
             patch.object(api._time, 'sleep') as sleep:
            self.assertEqual(api._generate_with_gemini('test').text, 'OK')
            self.assertEqual([c.args[0].get_header('X-goog-api-key') for c in call.call_args_list], ['timeout-first', 'timeout-second'])
            sleep.assert_not_called()

    def test_legacy_helper_uses_shared_provider(self):
        with patch.object(api, 'generate_with_retry', return_value=api._FakeResponse('OK')) as call:
            self.assertEqual(api.analyze_text_with_openrouter('test'), 'OK')
            call.assert_called_once_with('test')


if __name__ == '__main__':
    unittest.main()
