"""Real Gemini smoke check, with synthetic writings and isolated persistence.

Run after seed_history_learning.py; consumes API quota. No production submissions
are created. Saves full responses under ignored .data-cache for manual review.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ['DATA_BACKEND'] = 'json'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as web
from utils.data_store import DataStore
from utils.gemini_api import GEMINI_MODEL


def run():
    tasks = json.loads((ROOT / 'learning_tasks.json').read_text('utf-8'))
    selected = {mode: next(t for t in tasks.values() if t['mode'] == mode and t['lesson'] == '4')
                for mode in ('task', 'prompt')}
    report = {'model': GEMINI_MODEL, 'results': []}
    output = ROOT / '.data-cache/history-learning-live.json'
    output.parent.mkdir(exist_ok=True)
    original_generate = web.generate_with_retry

    def traced_generate(*args, **kwargs):
        response = original_generate(*args, **kwargs)
        report.setdefault('raw_responses', []).append(dict(model=response.model, text=response.text))
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        return response
    with tempfile.TemporaryDirectory() as directory:
        store = DataStore(backend='json', root=directory)
        shutil.copytree(ROOT / 'data/history11', Path(directory) / 'data/history11')
        store.save_document('learning_tasks.json', tasks)
        store.save_document('learning_events.json', [])
        with patch.object(web, 'storage', store), patch.object(web, 'generate_with_retry', side_effect=traced_generate):
            client = web.app.test_client()
            with client.session_transaction() as session:
                session.update(exam_username='synthetic_live_student', exam_role='student', learning_csrf='live-check')
            headers = {'X-Learning-CSRF': 'live-check'}
            writings = [
                ('prompt', 'Bạn hãy đóng vai nhà nghiên cứu lịch sử, đối chiếu nhận định với SGK Lịch sử 11. '
                 'Chỉ rõ bằng chứng và trang nguồn, tìm điểm chưa chắc chắn, xem xét ý kiến phản bác '
                 'rồi điều chỉnh kết luận theo mức độ chắc chắn. Không bịa nguồn khi chưa có căn cứ.'),
                ('task', 'Em cho rằng cải cách – mở cửa của Trung Quốc có thành tựu kinh tế, '
                 'nhưng em chưa đủ căn cứ để nói rằng mọi vấn đề xã hội đều được giải quyết.'),
                ('task', 'Nhận định chỉ có thành tựu kinh tế là chưa đầy đủ. Theo SGK trang PDF 28–29, '
                 'Trung Quốc còn đạt thành tựu khoa học – công nghệ, văn hóa và giáo dục. '
                 'Căn cứ về cải cách giáo dục cho thấy cần đánh giá trên nhiều lĩnh vực. '
                 'Tuy nhiên, không thể suy từ các thành tựu đó rằng mọi vấn đề xã hội đã được giải quyết: '
                 'SGK vẫn đề cập những vấn đề đặt ra. Vì vậy em kết luận công cuộc cải cách – mở cửa '
                 'có nhiều thành tựu nhưng cần phân biệt thành tựu với giới hạn; chỉ các trang này '
                 'chưa đủ để lượng hóa tất cả thành tựu và thách thức.'),
            ]
            for mode, writing in writings:
                task = selected[mode]
                response = client.post('/api/learning/task/' + task['id'] + '/analyze', json={'text': writing}, headers=headers)
                data = response.get_json()
                report['results'].append(dict(mode=mode, status=response.status_code, result=data))
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
                print(mode, 'status', response.status_code, 'score', data.get('feedback', {}).get('score'), flush=True)
                if response.status_code != 200:
                    raise RuntimeError('Live grading failed: ' + str(data.get('error')))
            task = selected['task']
            response = client.post('/api/learning/task/' + task['id'] + '/ask',
                                   json=dict(text=writings[-1][1], question='Em cần kiểm chứng điều gì trước khi kết luận?'), headers=headers)
            report['chat'] = dict(status=response.status_code, result=response.get_json())
            if response.status_code != 200:
                raise RuntimeError('Live guided chat failed')
            page = client.get('/learning/portfolio')
            assert page.status_code == 200
            assert len([e for e in store.load_document('learning_events.json') if e['event'] == 'attempt']) == 3
    output = ROOT / '.data-cache/history-learning-live.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print('Live passed: prompt, essay, revision, guided chat and portfolio; synthetic data only.', flush=True)


if __name__ == '__main__':
    run()
