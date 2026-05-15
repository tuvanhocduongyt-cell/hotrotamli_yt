# utils/ocr.py
import pytesseract
from PIL import Image

def extract_text_from_image(image_path):
    try:
        image = Image.open(image_path)
        text = pytesseract.image_to_string(image, lang='eng+vie')
        return text
    except Exception as e:
        print(f"[OCR ERROR] {e}")
        return "" # Trả về rỗng để AI Vision tự xử lý tiếp