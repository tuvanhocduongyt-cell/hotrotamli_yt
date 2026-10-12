# utils/ocr.py
import pytesseract
from PIL import Image

def extract_text_from_image(image_path):
    try:
        with Image.open(image_path) as image:
            text = pytesseract.image_to_string(image, lang='eng+vie')
        return text
    except Exception as e:
        print(f"[OCR ERROR] {e}")
        return "" # Trả về rỗng để AI Vision tự xử lý tiếp