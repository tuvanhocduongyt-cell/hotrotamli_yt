# Kết quả chuyển dữ liệu Supabase

Hoàn tất ngày 13/10/2026 (giờ Việt Nam), project `szfhraqvttqjxfzdkimk`.

- Nguồn: dữ liệu trong bản checkout GitHub, theo lựa chọn của chủ dự án; không lấy dữ liệu mới trên Render.
- Đã chuyển 12 nhóm JSON vào PostgreSQL và 83 tệp (18.416.672 byte) vào bucket riêng tư `yt-private-data`.
- Đã đọc lại và đối chiếu toàn bộ JSON, SHA256 của từng tệp; dữ liệu nguồn không thay đổi trong lúc chuyển.
- Bản sao lưu trước chuyển nằm trong `.migration-backups/before-supabase-*.zip`; kết quả đối chiếu tại `.migration-backups/verified.json`. Các tệp này và `.env` được Git bỏ qua.
- Đã bật `DATA_BACKEND=supabase` trong `.env` local và khởi động lại Flask.

## Kiểm tra

- Supabase thật: tạo/đọc document, thêm phần tử nguyên tử, từ chối ghi phiên bản cũ, tải lên/đọc/xóa tệp riêng tư đều đạt. Dữ liệu thử đã được xóa.
- Sửa mã lỗi xung đột thành `PT409` để PostgREST trả HTTP 409 ngay, tránh chờ thử lại lỗi serialization `40001`.
- 39 kiểm thử tự động: 38 đạt, 1 bỏ qua (bài kiểm tra Gemini thật yêu cầu bật riêng).
- Flask dùng Supabase thật: trang chủ, danh sách đề, bảng xếp hạng, đăng nhập, dashboard giáo viên/học sinh, thống kê, xem bài nộp đều trả HTTP 200.
- Tệp upload phục vụ qua Flask khớp nội dung trên Supabase Storage.

## Render

## Bổ sung từ datatm ngày 13/10/2026

- Supabase có đủ 14 bài làm thật, khớp `datatm/hotrotamli_yt/exam_submissions.json`; giữ nguyên bài làm, điểm và phản hồi chấm từ nguồn, không tạo bài nộp hoặc tài khoản mới.
- Bổ sung 190 phản hồi, tổng cộng 966; cập nhật ngày tạo của 9 đề theo nguồn.
- Theo yêu cầu của chủ dự án, sửa ngày tạo đề `20260331082131` từ `2029-09-25 08:21:31` thành `2026-10-10 08:21:31`. Đây là chỉnh sửa ngày hiển thị được yêu cầu, không phải ngày lịch sử đã xác minh.
- Giữ tổng số 43 đề và 86 tài khoản học sinh. 83 tệp của nguồn đã có trên Supabase, checksum khớp.
- Đã đọc lại đủ 12 nhóm dữ liệu và đối chiếu với bản nhập dự kiến. Bản sao trước cập nhật, nguồn và kết quả nằm trong `.migration-backups/datatm-20261012T172842748226Z/`.

## Trạng thái triển khai

Chưa triển khai mã mới hoặc cập nhật Environment trên Render. Để website Render dùng cùng dữ liệu, triển khai mã hiện tại và cấu hình các biến trong phần Render của `SUPABASE_SETUP.md`. Không đưa `.env` lên Git.
