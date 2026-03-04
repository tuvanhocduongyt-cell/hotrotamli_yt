import mammoth
import os
import sys

# Đảm bảo output có thể in được tiếng Việt
sys.stdout.reconfigure(encoding='utf-8')

file_path = r"c:\Kho Lưu Trữ 1\hotrotamli_yt\11.docx"
if os.path.exists(file_path):
    with open(file_path, "rb") as docx_file:
        result = mammoth.extract_raw_text(docx_file)
        print(result.value[:5000])
else:
    print(f"File not found: {file_path}")
