# Kết quả kiểm tra Gemini — 12/10/2026

**Cập nhật mới nhất:** cả **4/4 khóa** đã tạo câu trả lời thành công với `gemini-3.8-flash`.
Đã đổi cấu hình local sang model này. Các ca trước bị quota chặn đã được kiểm tra thành công,
gồm luồng nộp ảnh → chấm → lưu điểm → hiển thị kết quả. Một ca tâm lý bị timeout ở lượt đầu và đã đạt khi chạy lại riêng.
Các mục bên dưới lưu cả kết quả đợt đầu và đợt kiểm tra lại để phân biệt rõ nguyên nhân lỗi.

Dự án được clone trực tiếp vào `F:\cong_viec\kho_1\nguyenhoai`.
Giữ nguyên `.env` của người dùng; khóa không được ghi vào mã nguồn hoặc báo cáo.
Model của đợt kiểm tra ban đầu: `gemini-2.5-flash`; model hiện tại: `gemini-3.8-flash`.

## Kết quả đợt đầu, trước khi bổ sung khóa

- Kết nối Gemini thật thành công, nhận được `GEMINI_OK`.
- Bộ kiểm tra hồi quy cục bộ: **16/16 bài test đạt**. Chế độ này giả lập câu trả lời AI.
- Gọi API thật xác nhận thành công các nhóm bên dưới; **chưa thể xác nhận toàn bộ** vì hết quota ngày.
- `pip check` không phát hiện xung đột dependency; `git diff --check` đạt.
- Web local khởi động thành công, trang chủ trả HTTP 200 tại http://127.0.0.1:5000.

| Chức năng | Kết quả gọi Gemini thật |
| --- | --- |
| Chat Lịch sử `/chat` | Đạt |
| Chat SSE `/chat_stream` | Đạt, có nội dung và sự kiện hoàn tất |
| Ba trang `/upload_image`, `/upload_image2`, `/upload_image3` | Cả ba đạt với ảnh PNG RGBA |
| Chấm tự luận bằng chữ và ảnh | Cả hai đạt, JSON có điểm và nhận xét |
| Phân tích lỗi trắc nghiệm và đúng/sai | Cả hai đạt, JSON có kế hoạch ôn tập |
| Nhận xét bài thi `/submit` | Chưa xác nhận thành công: bị quota chặn |
| Chấm tự luận đề hỗn hợp bằng chữ và ảnh | Chưa xác nhận thành công: bị quota chặn |
| Tư vấn tâm lý, stress, nghề nghiệp | Chưa xác nhận thành công: gặp 429/503 |
| Sửa câu hỏi MCQ/TF bằng AI | Chưa xác nhận đủ cả hai nhánh: nhánh TF bị chặn |
| Chat Tâm An | Chưa xác nhận thành công: bị quota chặn |

Toàn bộ nhóm trong bảng đều có test cục bộ đạt. Các hàm chấm đề mới được gọi trực tiếp với dữ liệu giả lập;
không khẳng định đã kiểm thử toàn bộ thao tác giao diện, đăng nhập, lưu/nộp đề trên trình duyệt.
Test không dùng dữ liệu cá nhân thật và không sửa các file dữ liệu đề thi/học sinh hiện có.

## Lỗi tìm thấy và thay đổi

1. `utils/gemini_api.py` còn yêu cầu OpenRouter dù `.env` chỉ có Gemini. Đã gom bộ gọi AI dùng chung và giữ alias cho hàm cũ.
2. Ảnh RGBA gây `cannot write mode RGBA as JPEG`. Đã chuyển RGB trước khi mã hóa; kiểm tra thêm ảnh palette và grayscale.
3. File ảnh mở không đóng làm Windows giữ khóa file. Đã đóng file sau khi đọc, cả trong OCR và các luồng chấm ảnh.
4. Retry cũ chỉ chờ một giây. Đã đọc `RetryInfo.retryDelay` của Google, thử lại với 429/500/502/503/504;
   nếu phải chờ quá 60 giây, trả lỗi ngay thay vì giữ request hàng giờ. Kiểm tra giả lập cả quota phút và quota ngày.
5. Các hàm cần JSON đã bật `responseMimeType=application/json`; tăng giới hạn đầu ra từ 2048 lên 8192 token,
   loại phần suy luận và phát hiện phản hồi bị cắt/chặn trước khi đưa vào parser. Đây là cải thiện phòng lỗi;
   chưa quan sát lỗi cắt JSON trong các lời gọi thật đã thành công.
6. Nạp `.env` theo vị trí dự án, hỗ trợ UTF-8 BOM; không in phần đuôi khóa khi retry.

## Trở ngại bên ngoài mã nguồn

Google trả HTTP 429 với các quota của dự án này:

- `GenerateRequestsPerMinutePerProjectPerModel-FreeTier`: **5 yêu cầu/phút**.
- `GenerateRequestsPerDayPerProjectPerModel-FreeTier`: **20 yêu cầu/ngày**.

Đợt chạy lại đã gặp hết quota ngày, Google yêu cầu chờ khoảng 11 giờ tại thời điểm phản hồi.
Đã dừng lượt test live còn lại. Việc đổi sang khóa khác trong cùng dự án có thể vẫn dùng chung quota.
Cần chờ quota đặt lại, dùng dự án khác còn hạn mức, hoặc điều chỉnh gói/hạn mức phía Google để kiểm tra tiếp.
Chưa thay khóa, model hay bật thanh toán.

Máy chưa cài Tesseract; các ca ảnh thành công nhờ Gemini Vision đọc trực tiếp.
Máy cũng chưa có Google Cloud Application Default Credentials cho Text-to-Speech.
TTS là dịch vụ riêng, được loại khỏi test Gemini; muốn có giọng đọc cần cấu hình riêng dịch vụ đó.

Lệnh cài đặt, chạy ứng dụng và chạy lại test nằm trong [README.md](README.md).
Hai script parser cũ chỉ in kết quả, không có assertion; không được tính là test tự động đạt.

## Bổ sung: xoay khóa và màn hình kết quả bài nộp

- Nhận danh sách phân tách bằng dấu phẩy ngay trong `GEMINI_API_KEY`, ngoài `GEMINI_API_KEYS` và `GOOGLE_API_KEY`.
- Giữ khóa đang dùng; khi bị quota, chuyển ngay sang khóa còn sẵn sàng và nhớ thời gian tạm bỏ qua khóa lỗi trong tiến trình.
  Quota ngày của khóa 1 không ngăn thử khóa 2. Nếu tất cả khóa đều hết quota lâu, dừng ngay thay vì chờ hàng giờ.
- Sửa trạng thái sai trong ảnh người dùng: bài tự luận gọi AI thất bại không còn lưu `ai_graded=True`.
  Bài cũ có `score=None` nhưng `ai_graded=True` cũng được hiển thị “Chưa chấm xong”.
- Với đề hỗn hợp chưa chấm được một câu tự luận, điểm tổng để trống và giữ điểm phần đã chấm riêng;
  không coi lỗi AI là điểm 0 chính thức.
- Bảng giáo viên hiển thị cả bài chưa chấm; học sinh vẫn mở được chi tiết bài đã nộp khi điểm chưa có.
- Đã kiểm tra qua Flask test client, lưu dữ liệu trong thư mục tạm: nộp ảnh → HTTP 429 khóa 1 → khóa 2 trả kết quả
  → lưu điểm → trang chi tiết. Đồng thời kiểm tra hết cả hai khóa, trạng thái bài cũ và bảng giáo viên/học sinh.
- Sau bổ sung: **23 bài test cục bộ đạt**, **1 test nộp ảnh gọi API thật được bỏ qua** do chưa bật chế độ live.
  Đây là kết quả trước khi người dùng thêm khóa; kết quả gọi API thật sau đó nằm ở mục cuối.

Các thay đổi hiện ở máy local, chưa được triển khai lên Render và chưa chấm lại bài số 14 trên website.

## Xác minh bốn khóa vừa bổ sung — 12/10/2026

Đã kiểm tra từng khóa độc lập, không dùng khóa khác làm dự phòng trong bước xác minh này.
Số thứ tự khóa là thứ tự trong `.env`; không ghi khóa vào báo cáo.

| Khóa | `gemini-2.5-flash` | `gemini-3.8-flash` |
| --- | --- | --- |
| 1 | HTTP 429, hết quota ngày | Tạo câu trả lời thành công sau khi thử lại lỗi 503 |
| 2 | HTTP 404, model không còn cấp cho người dùng mới | Tạo câu trả lời thành công sau khi thử lại lỗi 503 |
| 3 | HTTP 404, model không còn cấp cho người dùng mới | Tạo câu trả lời thành công |
| 4 | HTTP 404, model không còn cấp cho người dùng mới | Tạo câu trả lời thành công |

API danh sách model của cả bốn khóa trả HTTP 200. Phản hồi lỗi của Google cho khóa 2–4 ghi rõ
`gemini-2.5-flash` không còn cấp cho người dùng mới và đề xuất `gemini-3.8-flash`.
Đã cập nhật `GEMINI_MODEL=gemini-3.8-flash` trong `.env`, giữ nguyên bốn khóa,
đồng thời cập nhật model mặc định và hướng dẫn chạy. Server local đã khởi động lại với cấu hình mới.
Thành công tại thời điểm kiểm tra không loại trừ lỗi 503 tạm thời hoặc quota phát sinh về sau.

### Kiểm tra chức năng sau khi đổi model

| Chức năng trước đó chưa xác nhận | Kết quả mới với API thật |
| --- | --- |
| Nhận xét bài thi `/submit` | Đạt |
| Tự luận đề hỗn hợp bằng chữ và ảnh | Cả hai đạt |
| Tư vấn tâm lý, stress, nghề nghiệp | Cả ba đạt; tâm lý đạt khi chạy lại sau timeout |
| Sửa cấu trúc câu hỏi MCQ và TF | Cả hai đạt |
| Chat Tâm An | Đạt, cả nhánh yêu cầu trả lời lại bằng tiếng Việt; TTS vẫn được loại khỏi test |
| Nộp ảnh qua `/do_exam` rồi mở `/view_submission` | Đạt: ảnh được đọc, lưu điểm 3/3, hiển thị nhận xét |

Lượt chạy sáu nhóm test ban đầu có năm nhóm đạt và một nhóm có ca tâm lý timeout.
Sau bổ sung retry cho lỗi kết nối/timeout, ca tâm lý chạy lại trả HTTP 200 và nhận được câu trả lời Gemini.
Test chỉ dùng đề/học sinh giả lập và thư mục tạm.

Đã quan sát xoay khóa thật khi Google trả 503: khóa 1 → khóa 2 thành công, khóa 2 → khóa 3 thành công,
và khóa 3 → khóa 4 thành công. Nhánh hết quota ngày → chuyển khóa được kiểm tra hồi quy bằng HTTP giả lập;
không cố tiêu hết quota của các khóa mới để tạo lỗi thật.

Chưa triển khai lên Render. Cần đưa các thay đổi lên dịch vụ và đặt `GEMINI_MODEL=gemini-3.8-flash`,
cùng danh sách khóa tương ứng trong Environment của Render để website đang chạy nhận cấu hình mới.
