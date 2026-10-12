# Hỗ trợ tâm lý và học tập

## Chạy trên Windows

```powershell
python -m venv venv
.\venv\Scripts\python -m pip install -r requirements.txt
.\venv\Scripts\python -m flask --app app run --host 127.0.0.1 --port 5000
```

Mở http://127.0.0.1:5000. File `.env` đặt cùng thư mục với `app.py`:

```dotenv
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-3.8-flash
```

Một hoặc nhiều khóa đều có thể đặt trong cùng biến:

```dotenv
GEMINI_API_KEY=key1,key2,key3
```

Ứng dụng dùng khóa hiện tại đến khi gặp lỗi quota, rồi chuyển ngay sang khóa tiếp theo.
Khóa hết quota được tạm bỏ qua theo thời gian Google báo; không chờ hết quota ngày của khóa 1 mới thử khóa 2.
Nếu mọi khóa đều tạm giới hạn, ứng dụng chỉ chờ tối đa 60 giây mỗi lần; nếu cần chờ lâu hơn thì trả lỗi.
Khóa bị từ chối xác thực/quyền truy cập cũng được bỏ qua để thử khóa khác.
Các khóa cùng Google Cloud project có thể dùng chung quota. Trạng thái tạm bỏ qua được giữ trong từng tiến trình server.

Ứng dụng cũng nhận `GOOGLE_API_KEY` hoặc `GEMINI_API_KEYS` với cùng cách phân tách bằng dấu phẩy.
Nếu đặt nhiều tên biến, ưu tiên `GEMINI_API_KEYS`, rồi `GEMINI_API_KEY`, rồi `GOOGLE_API_KEY`.
Khởi động lại server sau khi sửa `.env`; trên Render cần cập nhật Environment và khởi động/deploy lại dịch vụ.
Ngày 12/10/2026, các khóa mới trả 404 với `gemini-2.5-flash`: Google thông báo model này không còn cấp cho người dùng mới.
`gemini-3.8-flash` đã được kiểm tra tạo câu trả lời thành công với cả bốn khóa trong cấu hình local.
Gemini được ưu tiên; OpenRouter chỉ dùng dự phòng nếu cấu hình riêng khóa OpenRouter.
Không đưa `.env` lên Git; file này đã có trong `.gitignore`.

## Chuyển dữ liệu sang Supabase

Hướng dẫn setup bằng Dashboard và hai biến môi trường: [SUPABASE_SETUP.md](SUPABASE_SETUP.md).
Chạy [supabase/schema.sql](supabase/schema.sql) trong SQL Editor, sau đó dùng
`scripts/migrate_supabase.py --apply --activate` để sao lưu, chuyển và đối chiếu dữ liệu.
Khi chưa chuyển xong, ứng dụng vẫn dùng `DATA_BACKEND=json`; script chỉ bật Supabase sau khi xác minh thành công.

## Kiểm tra Gemini

Kiểm tra hồi quy cục bộ, không gọi API:

```powershell
Remove-Item Env:RUN_GEMINI_LIVE -ErrorAction SilentlyContinue
.\venv\Scripts\python -m unittest discover -s tests -v
```

Kiểm tra với Gemini thật, sử dụng hạn mức API của khóa trong `.env`:

```powershell
$env:RUN_GEMINI_LIVE='1'
.\venv\Scripts\python -u -m unittest discover -s tests -v
Remove-Item Env:RUN_GEMINI_LIVE
```

Bộ test dùng dữ liệu học sinh/đề thi giả lập, ảnh PNG tạo tại chỗ và thư mục upload tạm.
Các bài test chức năng gọi Gemini thật khi bật chế độ live; các bài test lỗi nhà cung cấp vẫn giả lập HTTP để kiểm tra retry, phản hồi bị cắt và che khóa.
OpenRouter bị tắt trong test để kết quả thành công phải đến từ Gemini.
Giãn cách 13 giây trước mỗi lời gọi live để phù hợp giới hạn 5 yêu cầu/phút đã quan sát ở dự án này.

Phạm vi: chat Lịch sử và SSE, ba chủ đề tư vấn, Tâm An, nhận xét bài thi,
ba trang chấm ảnh, chấm tự luận bằng chữ/ảnh, chấm tự luận đề hỗn hợp bằng chữ/ảnh,
phân tích sai trắc nghiệm/đúng-sai, sửa cấu trúc câu hỏi trắc nghiệm/đúng-sai.
Các hàm chấm và phân tích đề mới được kiểm tra trực tiếp; bộ test không tự động thao tác toàn bộ giao diện trình duyệt.

`tests/test_submission_flow.py` kiểm tra thêm luồng nộp ảnh → xoay khóa → lưu bài → hiển thị kết quả,
và luồng hết tất cả quota vẫn lưu bài với trạng thái chưa chấm xong.
Chạy riêng luồng nộp ảnh với Gemini thật sau khi có khóa còn quota:

```powershell
$env:RUN_GEMINI_FLOW_LIVE='1'
.\venv\Scripts\python -m unittest discover -s tests -p test_submission_flow.py -k live -v
Remove-Item Env:RUN_GEMINI_FLOW_LIVE
```

Google Cloud Text-to-Speech là dịch vụ riêng, không hoạt động chỉ với `GEMINI_API_KEY`.
Bộ test không gọi TTS. Nếu thiếu thông tin xác thực Google Cloud, chat vẫn trả chữ và không có âm thanh.
Tesseract là OCR tùy chọn: nếu chưa cài, ứng dụng vẫn gửi ảnh trực tiếp cho Gemini Vision.

Các script `test_parser.py` và `test_bac_split.py` cũ chỉ in kết quả kiểm tra thủ công,
không có assertion và không xác nhận Gemini hoạt động.
