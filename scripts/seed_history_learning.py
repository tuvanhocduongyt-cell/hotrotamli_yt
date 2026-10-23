"""Create a small initial set through the real teacher API, grounded in SGK scans.

Uses Gemini quota. Existing lesson/mode combinations are preserved.
"""
import json
import sys
from pathlib import Path
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as web
from scripts.import_experiment_accounts import experiment_password


def run():
    workbook = openpyxl.load_workbook(next((ROOT / 'capnhat').glob('*gv*.xlsx')), read_only=True, data_only=True)
    teacher = str(list(workbook.active.values)[1][3]).strip()
    workbook.close()
    client = web.app.test_client()
    login = client.post('/login_exam', data=dict(username=teacher, password=experiment_password(), role='teacher'))
    if login.status_code != 302:
        raise RuntimeError('Teacher login failed')
    if client.get('/learning').status_code != 200:
        raise RuntimeError('Learning page unavailable')
    with client.session_transaction() as session:
        csrf = session['learning_csrf']
    for mode, lesson, focus in [
        ('task', '4', 'Đánh giá thành tựu cải cách – mở cửa của Trung Quốc. Phân biệt thành tựu với hạn chế; không suy diễn số liệu ngoài SGK.'),
        ('task', '10', 'Đánh giá ý nghĩa và giới hạn của cải cách Lê Thánh Tông qua bằng chứng.'),
        ('task', '11', 'Phân tích cải cách hành chính của Minh Mạng từ hai góc nhìn.'),
        ('prompt', '4', 'Kiểm chứng một nhận định tuyệt đối hóa thành tựu cải cách – mở cửa của Trung Quốc.'),
        ('prompt', '7', 'Kiểm chứng nhận định chỉ có một nguyên nhân dẫn đến thắng lợi trong chiến tranh bảo vệ Tổ quốc.'),
        ('prompt', '9', 'Phản biện nhận định tuyệt đối hóa kết quả cuộc cải cách của Hồ Quý Ly.'),
    ]:
        existing = web.storage.load_document('learning_tasks.json', {})
        if any(t['mode'] == mode and t['lesson'] == lesson for t in existing.values()):
            print('Kept', mode, lesson, flush=True)
            continue
        response = client.post('/api/learning/tasks', json=dict(mode=mode, lesson=lesson, focus=focus),
                               headers={'X-Learning-CSRF': csrf})
        if response.status_code != 200:
            print('Failed', mode, lesson, response.get_json(), flush=True)
            raise RuntimeError('Task generation failed; previously saved tasks are preserved')
        data = response.get_json()['task']
        print('Created', mode, lesson, data['title'], 'source PDF pages', [s['page'] for s in data['sources']], flush=True)
    if web.storage.backend == 'supabase':
        (ROOT / 'learning_tasks.json').write_text(json.dumps(
            web.storage.load_document('learning_tasks.json', {}), ensure_ascii=False, indent=2), 'utf-8')


if __name__ == '__main__':
    run()
