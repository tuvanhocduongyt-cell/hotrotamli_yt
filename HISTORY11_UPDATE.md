# Cập nhật theo thư mục capnhat

## Các giai đoạn

1. Dữ liệu: nhập danh sách giáo viên/học sinh vào backend hiện hành, sao lưu trước khi ghi; chuẩn bị nguồn SGK và chuyên đề.
2. Prompt phản biện: tình huống riêng, mục tiêu, hướng dẫn 4 bước, phân tích theo tiêu chí, gợi ý viết lại.
3. Nhiệm vụ học tập: danh sách thẻ bài, trang làm bài, nguồn SGK, lưu nháp, nộp bài, hỏi AI để gợi mở.
4. Hồ sơ: giữ nguyên từng lần viết và nhận xét, so sánh cùng bài, lưu trao đổi AI và nhận xét giáo viên; kiểm tra hồi quy và trình duyệt.

## Sử dụng

- Đăng nhập tại `/login_exam`, sau đó mở `/learning` hoặc các liên kết trên trang giáo viên/học sinh.
- Giáo viên chọn bài SGK và trọng tâm để tạo nhiệm vụ hoặc tình huống prompt bằng AI.
- Học sinh mở bài, đọc trang nguồn, viết bài, lưu nháp hoặc nộp để nhận xét; sửa rồi nộp tiếp để lưu thêm một phiên bản.
- `/learning/portfolio` hiển thị bài viết, điểm từng tiêu chí, nhận xét, các lượt hỏi AI và góp ý của giáo viên. Học sinh chỉ xem hồ sơ của mình; giáo viên xem và lọc theo tài khoản.
- Điểm AI là gợi ý, không phải kết luận tự động về sự tiến bộ. Đọc cùng nội dung bài viết và đánh giá giáo viên.

## Nguồn và AI

Hai PDF trong `capnhat` được giữ nguyên tại `data/history11/`, kiểm tra SHA-256 trong `index.json`. Chỉ mục gồm 164 trang. Máy chuẩn bị chỉ có bộ OCR tiếng Anh, vì vậy văn bản OCR có thể sai dấu và **chỉ dùng để tìm kiếm**. Mô-đun mới chọn trang SGK theo từng bài đã đối chiếu trực tiếp ảnh scan; AI nhận **ảnh trang sách gốc**, không dùng OCR để chấm. Học sinh mở được đúng ảnh nguồn qua liên kết trang PDF.

Ngày 24/10/2026 theo múi giờ Việt Nam, model cấu hình trước đó `gemini-3.8-flash` trả 503/hết thời gian chờ trong kiểm tra thực tế. Cấu hình local chuyển sang `gemini-3.5-flash`, dự phòng `gemini-3.1-flash-lite` khi lỗi dịch vụ/kết nối. Các model này đã tạo được nhiệm vụ từ ảnh SGK. Model thực tế được lưu cùng nhiệm vụ/nhận xét mới. Không chuyển model để né quota hoặc lỗi xác thực.

Mỗi lần nộp được lưu **trước** khi gọi AI. Nếu AI lỗi, bài còn nguyên, hiển thị chờ nhận xét và cho phép chấm lại cùng lần nộp. JSON sai cấu trúc, điểm ngoài 0–2,5 mỗi tiêu chí hoặc trang nguồn ngoài tài liệu đã gửi không được lưu như kết quả thành công.

Phần nguồn SGK trực tiếp và rubric mới áp dụng cho hai mô-đun mới. Các màn hình thi/chấm ảnh cũ vẫn sử dụng luồng hiện có; không được coi các luồng cũ đã có cơ chế dẫn nguồn này.

## Chuẩn bị trên môi trường khác

```powershell
.\venv\Scripts\python -m pip install -r requirements.txt
.\venv\Scripts\python scripts/init_learning.py
.\venv\Scripts\python scripts/import_experiment_accounts.py
# Xem thống kê trước; --apply mới ghi và sao lưu.
.\venv\Scripts\python scripts/import_experiment_accounts.py --apply
```

Nguồn đã được chuẩn bị, không cần chạy OCR lại. Nếu cần đưa nguồn sẵn có lên Supabase:

```powershell
@'
from pathlib import Path
from utils.data_store import DataStore
store = DataStore()
for path in Path('data/history11').iterdir():
    store.write_asset(path, path.read_bytes())
'@ | .\venv\Scripts\python -
```

`scripts/prepare_history11.py --upload` chỉ dùng khi cần tạo lại chỉ mục trên Windows, có hướng dẫn các gói WinRT ở đầu file. `scripts/seed_history_learning.py` tạo 3 nhiệm vụ và 3 tình huống ban đầu bằng Gemini thật; giữ các cặp bài/loại đã có. Bản nguồn và các tài liệu mới đã được khởi tạo trên Supabase của môi trường hiện tại. Không tự xóa hay ghi đè tài khoản khác.

## Kiểm tra

Kết quả ngày 24/10/2026: 59 bài kiểm tra cục bộ đạt, 1 bài live cũ bỏ qua theo cấu hình. Kiểm tra trình duyệt đạt các luồng lưu nháp/tải lại, nộp bài, prompt, hồ sơ và 4 trang trên màn hình điện thoại; không có lỗi JavaScript. Kiểm tra Gemini thật đạt phân tích prompt, hai lần viết tự luận, hỏi AI và xem hồ sơ, dùng dữ liệu giả trong thư mục tạm. Đăng nhập thật cả hai vai trò và mở trang nguồn trên backend Supabase cũng đã kiểm tra thành công.

```powershell
$env:PYTHONIOENCODING='utf-8'
.\venv\Scripts\python -m unittest discover -s tests -v
```

Kiểm tra giao diện với dữ liệu giả và AI giả lập (cài riêng `playwright`, chạy `python -m playwright install chromium` trước):

```powershell
.\venv\Scripts\python scripts/check_learning_browser.py
```

Kiểm tra Gemini thật với bài viết giả và vùng lưu tạm, sử dụng quota; không tạo bài nộp trong Supabase thật:

```powershell
.\venv\Scripts\python scripts/check_history_learning_live.py
```

Ảnh kiểm tra và báo cáo phản hồi nằm trong `.data-cache/`, không đưa lên Git. Khởi động lại server sau khi thay `.env`. Khi đưa code lên Render, cập nhật hai biến `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS` trong Environment; `.env` local không tự cập nhật Render.
