"""Optional browser smoke check. Install playwright and its Chromium first.

Uses isolated synthetic data and a fake AI response, never production accounts.
Screenshots are saved to .data-cache/learning-*.png.
"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

os.environ['DATA_BACKEND'] = 'json'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as web
from utils.data_store import DataStore
from utils.history_learning import CRITERIA
from utils.history_sources import HistorySources
from utils.gemini_api import _FakeResponse


def run():
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server
    output = ROOT / '.data-cache'
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        store = DataStore(backend='json', root=temporary)
        tasks = {}
        for task_id, title, lesson, mode in [
            ('china', 'Đánh giá thành tựu cải cách – mở cửa của Trung Quốc', '4', 'task'),
            ('lethanh', 'Cải cách Lê Thánh Tông: thành tựu và giới hạn', '10', 'task'),
            ('minhmang', 'Nhìn từ hai phía: cải cách hành chính của Minh Mạng', '11', 'task'),
            ('prompt', 'Kiểm chứng một nhận định của AI về lịch sử', '4', 'prompt'),
        ]:
            tasks[task_id] = dict(id=task_id, title=title, lesson=lesson, mode=mode,
                                 objective='Đối chiếu căn cứ và cân nhắc góc nhìn khác trước khi kết luận.',
                                 situation='Một ý kiến cho rằng: “Cải cách – mở cửa chỉ đem lại thành tựu kinh tế.” '
                                 'Em hãy kiểm chứng nhận định này bằng các lĩnh vực được trình bày trong SGK, '
                                 'xem xét khả năng phản bác và nêu kết luận có điều kiện.',
                                 instructions='Dẫn căn cứ từ SGK. Phân biệt thông tin trong sách với suy luận của em.',
                                 sources=[dict(book='sgk', page=28, label='SGK Lịch sử 11 · trang PDF 28')])
        store.save_document('learning_tasks.json', tasks)
        store.save_document('learning_events.json', [])
        response = dict(criteria=[dict(key=k, level='Chưa rõ', score=1.5,
                                      comment='Em đã đặt vấn đề nhưng cần chỉ rõ căn cứ từ trang PDF 28.') for k, _ in CRITERIA],
                        strengths='Đã xác định nhận định cần kiểm chứng.',
                        improvements='Bổ sung góc nhìn khác và giới hạn của kết luận.',
                        rewrite_hint='Nếu chỉ xem xét thành tựu kinh tế, em sẽ bỏ qua bằng chứng nào?')
        with patch.object(web, 'storage', store), patch.object(HistorySources, 'parts', return_value=['source']), \
                patch.object(web, 'generate_with_retry', return_value=_FakeResponse(json.dumps(response, ensure_ascii=False))):
            server = make_server('127.0.0.1', 0, web.app, threaded=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context(viewport=dict(width=1440, height=1100), device_scale_factor=1)
                    cookie = web.app.session_interface.get_signing_serializer(web.app).dumps(
                        dict(exam_username='hocsinh_kiemthu', exam_role='student'))
                    context.add_cookies([dict(name=web.app.config['SESSION_COOKIE_NAME'], value=cookie,
                                              domain='127.0.0.1', path='/')])
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    base = 'http://127.0.0.1:' + str(server.server_port)
                    page.goto(base + '/learning')
                    page.screenshot(path=str(output / 'learning-home.png'), full_page=True)
                    page.get_by_role('link', name='Đánh giá thành tựu').click()
                    page.locator('#writing').fill('Em cần kiểm chứng nhận định, dẫn nguồn từ SGK và xem xét góc nhìn khác trước khi kết luận.')
                    page.locator('#save-draft').click()
                    page.get_by_text('Đã lưu bản nháp.', exact=True).wait_for()
                    page.reload()
                    assert 'kiểm chứng' in page.locator('#writing').input_value()
                    page.locator('#analyze').click()
                    page.get_by_text('Đã lưu bài và nhận xét trong hồ sơ.', exact=False).wait_for()
                    assert page.locator('#score-value').inner_text() == '6'
                    page.screenshot(path=str(output / 'learning-work.png'), full_page=True)
                    page.goto(base + '/learning/task/prompt')
                    page.locator('#writing').fill('Đóng vai nhà nghiên cứu, hãy kiểm chứng căn cứ và phản biện, điều chỉnh kết luận.')
                    assert page.locator('#structure-checks .found').count() == 4
                    page.locator('#analyze').click()
                    page.get_by_text('Đã lưu bài và nhận xét trong hồ sơ.', exact=False).wait_for()
                    page.screenshot(path=str(output / 'learning-prompt.png'), full_page=True)
                    page.goto(base + '/learning/portfolio')
                    page.get_by_text('Lần 1', exact=False).first.wait_for()
                    page.screenshot(path=str(output / 'learning-portfolio.png'), full_page=True)
                    page.set_viewport_size(dict(width=390, height=844))
                    for name, path in [('home', '/learning'), ('work', '/learning/task/china'), ('prompt', '/learning/task/prompt'), ('portfolio', '/learning/portfolio')]:
                        page.goto(base + path)
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), name + ' overflows'
                        page.screenshot(path=str(output / ('learning-mobile-' + name + '.png')), full_page=True)
                    assert not errors, errors
                    browser.close()
                print('Browser passed: draft reload, submission, prompt checks, portfolio, 4 mobile pages; no JS errors.')
            finally:
                server.shutdown()


if __name__ == '__main__':
    run()
