# Chuyển dữ liệu GitHub sang Supabase

Nguồn được chọn là dữ liệu trong bản GitHub đã clone. Dữ liệu chỉ phát sinh trên Render sau bản GitHub này không nằm trong nguồn chuyển.

## Setup ngắn nhất

1. Vào https://supabase.com/dashboard → **New project**, đặt tên, mật khẩu database và chọn khu vực gần Việt Nam (ví dụ Singapore).
2. Mở **SQL Editor → New query**, dán toàn bộ [supabase/schema.sql](supabase/schema.sql), bấm **Run**.
3. Trong phần Connect/Settings của project, lấy **Project URL** và **service_role key** hoặc **secret key phía server**.
   Thêm vào `.env` trên máy:

   ```dotenv
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=your-server-key
   DATA_BACKEND=json
   ```

   Không dùng anon/publishable key. Không cần Supabase CLI, database URL hoặc mật khẩu database cho bộ chuyển này.
4. Dừng server local để dữ liệu không thay đổi trong lúc chuyển, rồi chạy từ thư mục dự án:

   ```powershell
   .\venv\Scripts\python scripts\migrate_supabase.py --plan
   .\venv\Scripts\python scripts\migrate_supabase.py --apply --activate
   ```

5. Khi lệnh báo `verified: true`, `.env` được tự đặt `DATA_BACKEND=supabase`. Khởi động lại ứng dụng.

Nếu quá trình chuyển bị gián đoạn, chạy lại cùng lệnh: dữ liệu đã trùng khớp được giữ nguyên.
Nếu trên Supabase đã có dữ liệu khác nội dung, script dừng và không ghi đè.
Script chỉ bật backend Supabase sau khi tải lại từng file để đối chiếu SHA-256 và so sánh từng nhóm JSON.

## Dữ liệu được chuyển

- Tất cả JSON ở thư mục gốc: tài khoản, nhật ký cảm xúc, học sinh, giáo viên, đề thi, bài nộp,
  kết quả chấm/nhận xét, tài liệu, câu hỏi trò chơi, bảng điểm, phản hồi và JSON kiểm tra có sẵn.
- Nội dung tham khảo TXT, tài liệu DOCX/PDF ở thư mục gốc (trừ `requirements.txt`).
- Toàn bộ file trong `uploads/`, `data/`, `static/replies/`.
- Bản nháp đề thi mới cũng được lưu bền vững trong `drafts.json` trên database.

PostgreSQL lưu bảng `yt_documents`: mỗi nhóm dữ liệu là một hàng JSONB có tên gốc.
Cách này giữ nguyên tên đăng nhập, ID đề thi, thứ tự bài nộp và cấu trúc nhận xét AI,
nên không cần đặt lại tài khoản hay đổi các liên kết `/view_submission/<index>` trong dữ liệu nguồn.
Ứng dụng vẫn dùng cơ chế đăng nhập hiện có, chưa chuyển sang Supabase Auth.

File nằm trong bucket private `yt-private-data`; bảng `yt_assets` lưu đường dẫn gốc, mã SHA-256 và vị trí object.
Tên object dùng mã băm để hỗ trợ cả tên file tiếng Việt. Khóa Supabase chỉ sử dụng ở Flask phía server.
RLS bật trên hai bảng; anon/authenticated không được cấp quyền đọc dữ liệu ứng dụng.

Sau khi bật Supabase, ứng dụng đọc/ghi database và Storage, không tự rơi về dữ liệu JSON local khi mất kết nối.
Ghi đồng thời được kiểm tra phiên bản; bài nộp và phản hồi được thêm bằng thao tác atomic trong database.
Ảnh/Word có thể có bản làm việc tạm local phục vụ OCR/chấm AI; bản bền vững vẫn nằm ở Storage.

Mã nguồn, template, font, ảnh/âm thanh trang trí của giao diện vẫn được triển khai cùng ứng dụng.
Link video/tài liệu Google Drive được giữ nguyên trong dữ liệu; không tải bản sao nội dung từ website bên ngoài.

## Sao lưu, kiểm chứng và quay lại

- `.migration-backups/before-supabase-*.zip`: bản sao đầy đủ dữ liệu nguồn, không chứa `.env`.
- `.migration-backups/plan.json`: danh sách file, số lượng và checksum.
- `.migration-backups/verified.json`: chỉ được ghi khi đối chiếu thành công.
- Các file nguồn không bị xóa. Backup, cache, `.env` được Git bỏ qua.

Chạy lại đối chiếu với dữ liệu gốc (trước khi có thay đổi nghiệp vụ mới trên Supabase):

```powershell
.\venv\Scripts\python scripts\migrate_supabase.py --verify
```

Trước khi bắt đầu sử dụng Supabase thật, có thể quay lại bằng `DATA_BACKEND=json` và khởi động lại.
Sau khi đã có dữ liệu mới trên Supabase, không quay lại bản JSON cũ nếu chưa xuất dữ liệu mới về — hai bản lúc đó có thể khác nhau.

## Render

Sau khi di chuyển và kiểm tra xong, đưa code mới lên Render và đặt các biến sau trong **Environment**:

```dotenv
DATA_BACKEND=supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-server-key
SUPABASE_STORAGE_BUCKET=yt-private-data
GEMINI_MODEL=gemini-3.8-flash
GEMINI_API_KEY=key1,key2
```

Không đưa `.env` vào Git. Việc triển khai Render chưa được thực hiện chỉ bằng việc chạy lệnh chuyển dữ liệu trên máy.
