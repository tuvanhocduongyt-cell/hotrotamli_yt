import os
import io
import json
import re
import random
import base64
import string
import csv
import openpyxl
from PIL import Image
from datetime import datetime
from flask import send_file, send_from_directory, Response, stream_with_context
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, current_app

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from dotenv import load_dotenv
import google.generativeai as genai
import PyPDF2
import pytz

from google.cloud import texttospeech
from utils.ocr import extract_text_from_image
from utils.gemini_api import analyze_text_with_gemini
from datetime import datetime, timezone

from docx import Document
import mammoth

datetime.now(timezone.utc)

app = Flask(__name__)
app.secret_key = "phuonganh2403"

vn_timezone = pytz.timezone('Asia/Ho_Chi_Minh')
timestamp = datetime.now(vn_timezone).strftime("%Y-%m-%d %H:%M:%S")

load_dotenv()  # Load từ file .env

# API key handling (support multiple categories and rotation)
# use GOOGLE_API_KEYS_LICHSU for history-exam/chat features (two keys as requested)
# use GOOGLE_API_KEYS_GENERAL or fallback GOOGLE_API_KEYS for everything else

lic_keys_env = os.getenv("GOOGLE_API_KEYS_LICHSU")
general_keys_env = os.getenv("GOOGLE_API_KEYS_GENERAL")
all_keys_env = os.getenv("GOOGLE_API_KEYS")
single = os.getenv("GOOGLE_API_KEY")

LICHSU_KEYS = [k.strip() for k in lic_keys_env.split(",")] if lic_keys_env else []
GENERAL_KEYS = [k.strip() for k in general_keys_env.split(",")] if general_keys_env else []
if all_keys_env:
    GENERAL_KEYS.extend([k.strip() for k in all_keys_env.split(",") if k.strip()])
if single:
    GENERAL_KEYS.append(single)

# make sure at least one key exists in general list
if not GENERAL_KEYS and not LICHSU_KEYS:
    raise ValueError("Không tìm thấy khóa API trong GOOGLE_API_KEYS*, GOOGLE_API_KEYS hoặc GOOGLE_API_KEY")

# helper to pick key based on feature

def get_api_key(feature=None):
    if feature == 'lichsu' and LICHSU_KEYS:
        return random.choice(LICHSU_KEYS)
    # fall back to general list
    return random.choice(GENERAL_KEYS)

# build a new model instance each time after configuring with a chosen key
# optionally pass feature string to select proper key pool

def get_model(feature=None):
    key = get_api_key(feature)
    genai.configure(api_key=key)
    return genai.GenerativeModel("models/gemini-2.5-flash")

app.config['UPLOAD_FOLDER'] = 'uploads'

# temporary server-side storage for exams pending preview/save
# key is a UUID token, value is exam data dict
TEMP_EXAMS = {}

def load_context(topic):
    file_map = {
        "tam_li": "data_tam_li.txt",
        "stress": "stress.txt",
        "nghe_nghiep": "nghe_nghiep.txt"
    }
    file_path = file_map.get(topic, "data_tam_li.txt")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Không tìm thấy dữ liệu phù hợp."
#// 
def build_prompt(topic, context_data, user_input, is_first_message=False):
    context_summary = context_data[:1500] if context_data else ""
    
    if topic == "tam_li":
        intro = "Chào bạn, tôi là trợ lý AI Tâm An chuyên về lĩnh vực tâm lí.\n\n" if is_first_message else ""
        return (
            f"tôi là trợ lý AI Tâm An chuyên về lĩnh vực tâm lí.\n"
            f"Dữ liệu tham khảo:\n{context_summary}\n\n"
            f"QUY TẮC:\n"
            f"- Ưu tiên dùng dữ liệu trên nếu liên quan\n"
            f"- Nếu không có trong dữ liệu, dùng kiến thức chung của bạn để trả lời\n"
            f"- KHÔNG BAO GIỜ nói 'xin lỗi, không có dữ liệu' hay 'nằm ngoài phạm vi'\n"
            f"- Trả lời tự nhiên, thân thiện như một cuộc hội thoại bình thường\n"
            f"- Câu đầu tiên: giới thiệu. Từ câu 2 trở đi: không cần giới thiệu lại\n\n"
            f"{intro}Câu hỏi: {user_input}\n"
            f"Trả lời:"
        )
    elif topic == "stress":
        intro = "Chào bạn, tôi là trợ lý AI Tâm An, chuyên hỗ trợ tâm lý và stress.\n\n" if is_first_message else ""
        return (
            f"Bạn là trợ lý AI giúp học sinh vượt qua căng thẳng.\n"
            f"Dữ liệu tham khảo:\n{context_summary}\n\n"
            f"QUY TẮC:\n"
            f"- Trả lời với giọng điệu trấn an, đồng cảm\n"
            f"- Dùng dữ liệu nếu có, không thì dùng kiến thức chung\n"
            f"- KHÔNG nói 'xin lỗi, không biết'\n"
            f"- Trò chuyện tự nhiên, không rập khuôn\n\n"
            f"{intro}Câu hỏi: {user_input}\n"
            f"Trả lời:"
        )
    elif topic == "nghe_nghiep":
        intro = "Chào bạn, tôi là trợ lý AI của cô Tâm An, chuyên tư vấn định hướng nghề nghiệp.\n\n" if is_first_message else ""
        return (
            f"Bạn là trợ lý AI tư vấn nghề nghiệp cho học sinh.\n"
            f"Dữ liệu tham khảo:\n{context_summary}\n\n"
            f"QUY TẮC:\n"
            f"- Khích lệ, giúp học sinh khám phá bản thân\n"
            f"- Dùng dữ liệu nếu có, không thì đưa ra lời khuyên từ kiến thức chung\n"
            f"- KHÔNG từ chối trả lời\n"
            f"- Trò chuyện tự nhiên\n\n"
            f"{intro}Câu hỏi: {user_input}\n"
            f"Trả lời:"
        )
    else:
        intro = "Chào bạn, tôi là trợ lý AI của cô Tâm An.\n\n" if is_first_message else ""
        return (
            f"Bạn là trợ lý AI thân thiện.\n"
            f"Dữ liệu tham khảo:\n{context_summary}\n\n"
            f"QUY TẮC:\n"
            f"- Trả lời tự nhiên, thân thiện\n"
            f"- Dùng cả dữ liệu và kiến thức chung\n"
            f"- KHÔNG từ chối hay xin lỗi khi không có dữ liệu\n\n"
            f"{intro}Câu hỏi: {user_input}\n"
            f"Trả lời:"
        )
##################
@app.route("/tro_chuyen_tam_li_cung_tro_ly_ai_pham_hang", methods=["GET", "POST"])
def tam_li_chat():
    topic = request.args.get("topic", "tam_li")
    context_data = load_context(topic)
    response_text = ""
    
    if request.method == "POST":
        user_input = request.form.get("user_input")
        if user_input:
            is_first = session.get(f'first_message_{topic}', True)
            
            prompt = build_prompt(topic, context_data, user_input, is_first_message=is_first)
            response = get_model().generate_content(prompt)
            response_text = response.text
            
            # ✅ LOẠI BỎ MARKDOWN
            response_text = response_text.replace('###', '')
            response_text = response_text.replace('***', '')
            response_text = response_text.replace('**', '')
            response_text = response_text.replace('* ', '')
            response_text = response_text.replace('- ', '')
            response_text = response_text.replace('• ', '')
            
            # ✅ XỬ LÝ XUỐNG DÒNG CHO CÁC SỐ THỨ TỰ
            import re
            # Thêm 2 dòng trống trước các số thứ tự (1., 2., 3., 4., etc.)
            response_text = re.sub(r'(\d+\.)', r'\n\n\1', response_text)
            
            # ✅ LOẠI BỎ DÒNG TRỐNG THỪA
            # Loại bỏ dòng trống ở đầu văn bản
            response_text = response_text.lstrip()
            # Giảm dòng trống thừa (3+ dòng → 2 dòng)
            response_text = re.sub(r'\n{3,}', '\n\n', response_text)
            
            # ✅ XỬ LÝ XUỐNG DÒNG SAU DẤU CHẤM HỎI
            # Thêm dòng mới sau câu hỏi nếu câu tiếp theo bắt đầu bằng số hoặc chữ in hoa
            response_text = re.sub(r'\?\s+(\d+\.|\w)', r'?\n\n\1', response_text)
            
            session[f'first_message_{topic}'] = False
    
    return render_template("tam_li.html", response=response_text, topic=topic)
    ##########################3
def read_pdf(file_path):
    text = ""
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() + "\n"
    except Exception as e:
        print(f"Lỗi đọc PDF {file_path}: {e}")
    return text

custom_data = ""

if os.path.exists("data.txt"):
    with open("data.txt", "r", encoding="utf-8") as f:
        custom_data += f.read() + "\n"
        
pdf_folder = "data"
if os.path.exists(pdf_folder):
    for file_name in os.listdir(pdf_folder):
        if file_name.lower().endswith(".pdf"):
            file_path = os.path.join(pdf_folder, file_name)
            custom_data += read_pdf(file_path) + "\n"

docs_list = [
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D21",
        "link": "https://drive.google.com/file/d/1qIS83JH_9OpTk_tR9bwhl61F_EETPaFk/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D22",
        "link": "https://drive.google.com/file/d/1dxNrWXjxLlO97ZAAb-E-s56n6peCYrqp/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D23",
        "link": "https://drive.google.com/file/d/16jaAmn-87QN7kiYzB7dIcF0fjRGpPLJg/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D24",
        "link": "https://drive.google.com/file/d/1p8GQ5aHna5H8q0ujq26tK7uqjT5v3P-1/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D25",
        "link": "https://drive.google.com/file/d/1IUtEbTVS4-mRmyBEV6gbDGjHxJHAtgSf/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D26",
        "link": "https://drive.google.com/file/d/1CXVEz6NPRusUaVJE3HRTOBm6neYbcmge/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D27",
        "link": "https://drive.google.com/file/d/1NlCO6a7kTCortwWU0BC2Yme3sTH4xBOV/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT 28",
        "link": "https://drive.google.com/file/d/1M7FLkTU4P35ljfghkjvuDEHV1k5ZrTv3/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D29",
        "link": "https://drive.google.com/file/d/1Ob-hF8P1_itOvZoKWk0JUNzpLxQTGHdZ/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D30",
        "link": "https://drive.google.com/file/d/16_xfgmEqr_HSF2rD0jLZOj00CTDiSfDQ/view?usp=sharing"
    },
    {
        "title": "Tài liệu ôn thi",
        "link": "https://drive.google.com/file/d/1N23yjH5L4f5ySms8Q3dlXllB9YmG5Lt2/view?usp=drive_link"
    },
    {
        "title": "Kiến thức trọng tâm",
        "link": "https://drive.google.com/file/d/1NPZIZkZ0q9PEY1JdV9zjSvtJD_0ykEo2/view?usp=drive_link"
    }
]

@app.route('/')
def menu():
    return render_template('menu.html')

@app.route('/stress_test', methods=['GET', 'POST'])
def stress_test():
    if request.method == 'POST':
        answers = {int(k): int(v) for k, v in request.form.items()}
        group_D = [3, 5, 10, 13, 16, 17, 21]  
        group_A = [2, 4, 7, 9, 15, 19, 20]    
        group_S = [1, 6, 8, 11, 12, 14, 18]

        score_D = sum(answers[q] for q in group_D) * 2
        score_A = sum(answers[q] for q in group_A) * 2
        score_S = sum(answers[q] for q in group_S) * 2

        def classify_D(score):
            if score <= 9: return "Bình thường"
            elif score <= 13: return "Nhẹ"
            elif score <= 20: return "Vừa"
            elif score <= 27: return "Nặng"
            else: return "Rất nặng"

        def classify_A(score):
            if score <= 7: return "Bình thường"
            elif score <= 9: return "Nhẹ"
            elif score <= 14: return "Vừa"
            elif score <= 19: return "Nặng"
            else: return "Rất nặng"

        def classify_S(score):
            if score <= 14: return "Bình thường"
            elif score <= 18: return "Nhẹ"
            elif score <= 25: return "Vừa"
            elif score <= 33: return "Nặng"
            else: return "Rất nặng"

        return render_template(
            'stress_result.html',
            score_D=score_D, score_A=score_A, score_S=score_S,
            level_D=classify_D(score_D),
            level_A=classify_A(score_A),
            level_S=classify_S(score_S)
        )

    questions = [
        "Tôi thấy khó mà thoải mái được",
        "Tôi bị khô miệng",
        "Tôi dường như chẳng có chút cảm xúc tích cực nào",
        "Tôi bị rối loạn nhịp thở (thở gấp, khó thở dù chẳng làm việc gì nặng)",
        "Tôi thấy khó bắt tay vào công việc",
        "Tôi có xu hướng phản ứng thái quá với mọi tình huống",
        "Tôi bị ra mồ hôi (chẳng hạn như mồ hôi tay...)",
        "Tôi thấy mình đang suy nghĩ quá nhiều",
        "Tôi lo lắng về những tình huống có thể làm tôi hoảng sợ hoặc biến tôi thành trò cười",
        "Tôi thấy mình chẳng có gì để mong đợi cả",
        "Tôi thấy bản thân dễ bị kích động",
        "Tôi thấy khó thư giãn được",
        "Tôi cảm thấy chán nản, thất vọng",
        "Tôi không chấp nhận được việc có cái gì đó xen vào cản trở việc tôi đang làm",
        "Tôi thấy mình gần như hoảng loạn",
        "Tôi không thấy hứng thú với bất kỳ việc gì nữa",
        "Tôi cảm thấy mình chẳng đáng làm người",
        "Tôi thấy mình khá dễ phát ý, tự ái",
        "Tôi nghe thấy rõ tiếng nhịp tim dù chẳng làm việc gì",
        "Tôi hay sợ vô cớ",
        "Tôi thấy cuộc sống vô nghĩa"
    ]
    return render_template('stress_test.html', questions=questions)

questions_holland = [
    {"text": "Tôi thích sửa chữa máy móc, thiết bị.", "type": "R"},
    {"text": "Tôi thích nghiên cứu, tìm hiểu hiện tượng tự nhiên.", "type": "I"},
    {"text": "Tôi thích vẽ, viết hoặc sáng tạo nghệ thuật.", "type": "A"},
    {"text": "Tôi thích làm việc nhóm và giúp đỡ người khác.", "type": "S"},
    {"text": "Tôi thích thuyết phục và lãnh đạo người khác.", "type": "E"},
    {"text": "Tôi thích làm việc với số liệu, giấy tờ và sắp xếp hồ sơ.", "type": "C"},
    {"text": "Tôi thích làm việc ngoài trời.", "type": "R"},
    {"text": "Tôi tò mò về cách mọi thứ hoạt động.", "type": "I"},
    {"text": "Tôi yêu thích âm nhạc, hội họa hoặc sân khấu.", "type": "A"},
    {"text": "Tôi dễ dàng kết bạn và trò chuyện với người lạ.", "type": "S"},
    {"text": "Tôi thích điều hành dự án hoặc quản lý một nhóm.", "type": "E"},
    {"text": "Tôi thích nhập dữ liệu hoặc làm việc hành chính.", "type": "C"},
    {"text": "Tôi thích vận hành máy móc hoặc công cụ.", "type": "R"},
    {"text": "Tôi thích giải quyết các bài toán hoặc vấn đề phức tạp.", "type": "I"},
    {"text": "Tôi thích thiết kế hoặc tạo ra sản phẩm sáng tạo.", "type": "A"},
    {"text": "Tôi thích giúp đỡ người khác giải quyết vấn đề cá nhân.", "type": "S"},
    {"text": "Tôi thích bán hàng hoặc tiếp thị sản phẩm.", "type": "E"},
    {"text": "Tôi thích theo dõi và lưu trữ hồ sơ cẩn thận.", "type": "C"},
    {"text": "Tôi thích sửa chữa xe cộ hoặc đồ điện tử.", "type": "R"},
    {"text": "Tôi thích tìm hiểu về khoa học hoặc công nghệ mới.", "type": "I"},
    {"text": "Tôi thích viết truyện, thơ hoặc kịch bản.", "type": "A"},
    {"text": "Tôi thích giảng dạy hoặc huấn luyện người khác.", "type": "S"},
    {"text": "Tôi thích lập kế hoạch kinh doanh.", "type": "E"},
    {"text": "Tôi thích quản lý dữ liệu và hồ sơ.", "type": "C"},
    {"text": "Tôi thích làm công việc xây dựng hoặc sửa chữa nhà cửa.", "type": "R"},
    {"text": "Tôi thích thực hiện thí nghiệm.", "type": "I"},
    {"text": "Tôi thích sáng tác nhạc hoặc viết lời bài hát.", "type": "A"},
    {"text": "Tôi thích làm công tác xã hội hoặc tình nguyện.", "type": "S"},
    {"text": "Tôi thích lãnh đạo chiến dịch hoặc dự án.", "type": "E"},
    {"text": "Tôi thích lập bảng tính hoặc tài liệu thống kê.", "type": "C"},
    {"text": "Tôi thích đi bộ đường dài hoặc các hoạt động ngoài trời.", "type": "R"},
    {"text": "Tôi thích phân tích dữ liệu hoặc nghiên cứu thị trường.", "type": "I"},
    {"text": "Tôi thích chụp ảnh hoặc quay phim.", "type": "A"},
    {"text": "Tôi thích chăm sóc sức khỏe cho người khác.", "type": "S"},
    {"text": "Tôi thích phát triển chiến lược tiếp thị.", "type": "E"},
    {"text": "Tôi thích thực hiện công việc kế toán hoặc tài chính.", "type": "C"},
    {"text": "Tôi thích lắp ráp hoặc tháo rời thiết bị.", "type": "R"},
    {"text": "Tôi thích đọc sách khoa học hoặc tài liệu chuyên môn.", "type": "I"},
    {"text": "Tôi thích tham gia vào các hoạt động nghệ thuật cộng đồng.", "type": "A"},
    {"text": "Tôi thích hỗ trợ tâm lý cho người gặp khó khăn.", "type": "S"},
    {"text": "Tôi thích đàm phán hợp đồng hoặc thỏa thuận.", "type": "E"},
    {"text": "Tôi thích kiểm tra lỗi trong dữ liệu.", "type": "C"},
    {"text": "Tôi thích chế tạo hoặc lắp ráp thủ công.", "type": "R"},
    {"text": "Tôi thích đặt câu hỏi và tìm hiểu nguyên nhân sự việc.", "type": "I"},
    {"text": "Tôi thích làm đồ thủ công mỹ nghệ.", "type": "A"},
    {"text": "Tôi thích tổ chức các sự kiện cộng đồng.", "type": "S"},
    {"text": "Tôi thích khởi nghiệp kinh doanh.", "type": "E"},
    {"text": "Tôi thích làm việc theo quy trình rõ ràng.", "type": "C"},
    {"text": "Tôi thích sử dụng công cụ hoặc máy móc nặng.", "type": "R"},
    {"text": "Tôi thích nghiên cứu công nghệ mới.", "type": "I"},
    {"text": "Tôi thích biểu diễn trước khán giả.", "type": "A"},
    {"text": "Tôi thích đào tạo và phát triển kỹ năng cho người khác.", "type": "S"},
    {"text": "Tôi thích thuyết phục người khác mua sản phẩm.", "type": "E"},
    {"text": "Tôi thích sắp xếp và phân loại tài liệu.", "type": "C"},
    {"text": "Tôi thích sửa chữa các thiết bị điện gia dụng.", "type": "R"},
    {"text": "Tôi thích khám phá và nghiên cứu những điều mới lạ.", "type": "I"},
    {"text": "Tôi thích viết kịch bản hoặc đạo diễn phim.", "type": "A"},
    {"text": "Tôi thích hỗ trợ người khuyết tật.", "type": "S"},
    {"text": "Tôi thích quản lý nhân sự.", "type": "E"},
    {"text": "Tôi thích theo dõi sổ sách và ngân sách.", "type": "C"}
]

holland_types = {
    "R": {
        "name": "Realistic (Kỹ thuật, thực tế)",
        "desc": "Thích làm việc tay chân, máy móc, kỹ thuật, ngoài trời.",
        "jobs": [
            "Kỹ sư cơ khí",
            "Thợ điện",
            "Kỹ thuật viên ô tô",
            "Công nhân xây dựng",
            "Kỹ sư nông nghiệp"
        ]
    },
    "I": {
        "name": "Investigative (Nghiên cứu)",
        "desc": "Thích phân tích, tìm tòi, khám phá, làm việc khoa học.",
        "jobs": [
            "Nhà khoa học",
            "Bác sĩ",
            "Kỹ sư phần mềm",
            "Nhà nghiên cứu y sinh",
            "Chuyên gia dữ liệu"
        ]
    },
    "A": {
        "name": "Artistic (Nghệ thuật)",
        "desc": "Thích sáng tạo, tự do, nghệ thuật, biểu diễn.",
        "jobs": [
            "Họa sĩ",
            "Nhà thiết kế đồ họa",
            "Nhạc sĩ",
            "Đạo diễn",
            "Nhiếp ảnh gia"
        ]
    },
    "S": {
        "name": "Social (Xã hội)",
        "desc": "Thích giúp đỡ, giao tiếp, dạy học, hỗ trợ cộng đồng.",
        "jobs": [
            "Giáo viên",
            "Nhân viên xã hội",
            "Nhà tâm lý học",
            "Điều dưỡng",
            "Hướng dẫn viên du lịch"
        ]
    },
    "E": {
        "name": "Enterprising (Quản lý, kinh doanh)",
        "desc": "Thích lãnh đạo, kinh doanh, thuyết phục, mạo hiểm.",
        "jobs": [
            "Doanh nhân",
            "Nhà quản lý dự án",
            "Chuyên viên marketing",
            "Luật sư",
            "Nhân viên bán hàng"
        ]
    },
    "C": {
        "name": "Conventional (Hành chính)",
        "desc": "Thích công việc văn phòng, chi tiết, tuân thủ quy trình.",
        "jobs": [
            "Nhân viên kế toán",
            "Thư ký",
            "Nhân viên nhập liệu",
            "Nhân viên hành chính",
            "Chuyên viên tài chính"
        ]
    }
}

@app.route("/relax/<mode>")
def relax_page(mode):
    valid_modes = ["menu", "music", "yoga", "meditation", "breathing"]
    if mode not in valid_modes:
        return "Trang không tồn tại", 404
    return render_template(f"relax_{mode}.html")

@app.route("/holland", methods=["GET", "POST"])
def holland_test():
    if request.method == "POST":
        scores = {key: 0 for key in holland_types.keys()}
        for idx in range(1, len(questions_holland) + 1):
            ans = request.form.get(str(idx))
            if ans and ans.isdigit():
                scores[questions_holland[idx - 1]["type"]] += int(ans) - 1
        sorted_types = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        top3_details = [
            {
                "code": t[0],
                "name": holland_types[t[0]]["name"],
                "desc": holland_types[t[0]]["desc"],
                "jobs": holland_types[t[0]]["jobs"],
                "score": t[1]
            }
            for t in sorted_types[:3]
        ]

        return render_template(
            "holland_result.html",
            top3_details=top3_details
        )

    return render_template("holland.html", questions=questions_holland)

USERS_FILE = 'users.json'
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        users = load_users()

        if username in users and users[username]['password'] == password:
            session['username'] = username
            return redirect(url_for('emotion_journal'))
        else:
            return render_template('login.html', message="Sai tên đăng nhập hoặc mật khẩu")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        users = load_users()

        if username in users:
            return render_template('register.html', message="Tên đăng nhập đã tồn tại")
        if len(users) >= 20:
            return render_template('register.html', message="Đã đủ 20 tài khoản test")

        users[username] = {"password": password, "logs": []}
        save_users(users)
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/emotion_journal', methods=['GET', 'POST'])
def emotion_journal():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    users = load_users()
    history = users.get(username, {}).get('logs', [])

    music_videos = {
        "Giảm căng thẳng": "https://www.youtube.com/embed/e8fFEmMW5EI&t",
        "Piano": "https://www.youtube.com/embed/tVQ_uDRs_7U",
        "Bình yên": "https://www.youtube.com/embed/MLQZOGJeBLA"
    }

    tz_vn = pytz.timezone('Asia/Ho_Chi_Minh')

    if request.method == 'POST':
        emotion = request.form.get('emotion')
        note = request.form.get('note', '').strip()
        activities = request.form.getlist('activities')
        
        timestamp = datetime.now(tz_vn).strftime("%d/%m/%Y %H:%M:%S")

        new_entry = {
            'datetime': timestamp,
            'emotion': emotion,
            'note': note,
            'activities': activities
        }
        history.append(new_entry)
        users[username]['logs'] = history
        save_users(users)

        message = "Ghi lại cảm xúc thành công!"
        return render_template('emotion_journal.html',
                               message=message,
                               history=history,
                               music_videos=music_videos)

    return render_template('emotion_journal.html',
                           history=history,
                           music_videos=music_videos)

@app.route('/export_pdf')
def export_pdf():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    users = load_users()
    history = users.get(username, {}).get('logs', [])

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()

    font_path = os.path.join('fonts', 'Roboto-VariableFont_wdth,wght.ttf')
    pdfmetrics.registerFont(TTFont('Roboto', font_path))

    for style_name in styles.byName:
        styles[style_name].fontName = 'Roboto'

    elements = []
    elements.append(Paragraph(f"📔 Nhật ký cảm xúc của {username}", styles['Title']))
    elements.append(Spacer(1, 20))

    if not history:
        elements.append(Paragraph("Không có dữ liệu cảm xúc.", styles['Normal']))
    else:
        for i, entry in enumerate(history, start=1):
            elements.append(Paragraph(f"<b>#{i}</b> - {entry['datetime']}", styles['Heading3']))
            elements.append(Paragraph(f"Cảm xúc: {entry['emotion']}", styles['Normal']))
            elements.append(Paragraph(f"Hoạt động: {', '.join(entry['activities'])}", styles['Normal']))
            elements.append(Paragraph(f"Ghi chú: {entry['note']}", styles['Normal']))
            elements.append(Spacer(1, 10))

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f"nhat_ky_cam_xuc_{username}.pdf",
                     mimetype='application/pdf')

@app.route("/")
def main_menu():
    return render_template("menu.html")

@app.route("/docs")
def docs():
    return render_template("docs.html", docs=docs_list)

@app.route("/chatbot")
def chatbot_page():
    return render_template("index.html")

@app.route("/chat_stream", methods=["POST"])
def chat_stream():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    
    if not user_message:
        return jsonify({"error": "Không có tin nhắn"}), 400
    
    def generate():
        try:
            if 'chat_history' not in session:
                session['chat_history'] = []
            
            chat_history = session['chat_history']
            
            is_first = len(chat_history) == 0
            intro = "Chào bạn, tôi là trợ lý AI của cô Phạm Hằng về lịch sử.\n\n" if is_first else ""
            
            context = ""
            if len(chat_history) > 0:
                recent_history = chat_history[-6:]
                context = "Lịch sử hội thoại:\n"
                for i in range(0, len(recent_history), 2):
                    if i+1 < len(recent_history):
                        context += f"Người dùng: {recent_history[i]}\nTrợ lý: {recent_history[i+1]}\n"
                context += "\n"
            
            prompt = f"""
Bạn là trợ lý AI thông minh của cô Phạm Hằng chuyên về lịch sử.
Dữ liệu tham khảo (ưu tiên nếu liên quan):
{custom_data[:1500]}

{context}

QUY TẮC QUAN TRỌNG:
- Ưu tiên dùng dữ liệu trên nếu câu hỏi liên quan
- Nếu không có trong dữ liệu, TỰ TIN trả lời bằng kiến thức tổng quát của bạn
- TUYỆT ĐỐI KHÔNG nói "xin lỗi, không có dữ liệu" hay "nằm ngoài phạm vi kiến thức"
- Trả lời tự nhiên, thân thiện như một cuộc trò chuyện thực tế
- Nếu hỏi tiếp về câu trước, hãy dựa vào lịch sử hội thoại để trả lời liền mạch
- Nếu họ dùng tiếng Việt thì trả lời bằng tiếng Việt
- Chỉ giới thiệu ở câu đầu tiên, từ câu 2 trở đi trò chuyện bình thường
- KHÔNG dùng markdown format (###, ***, **, -, •)
- Trả lời dạng văn xuôi tự nhiên, KHÔNG dùng bullet points
- Nếu cần liệt kê, viết thành câu văn: "Có 3 điều quan trọng: thứ nhất..., thứ hai..., thứ ba..."

{intro}Câu hỏi hiện tại: {user_message}
Trả lời:
"""
            
            response = get_model('lichsu').generate_content(
                prompt,
                stream=True,
                generation_config={
                    "temperature": 0.7,
                    "top_p": 0.95,
                    "max_output_tokens": 1024,
                }
            )
            
            chat_history.append(user_message)
            full_response = ""
            
            for chunk in response:
                if chunk.text:
                    clean_text = chunk.text
                    clean_text = clean_text.replace('###', '')
                    clean_text = clean_text.replace('***', '')
                    clean_text = clean_text.replace('**', '')
                    clean_text = clean_text.replace('* ', '')
                    clean_text = clean_text.replace('- ', '')
                    clean_text = clean_text.replace('• ', '')
                    
                    full_response += clean_text
                    data = json.dumps({"text": clean_text}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
            
            chat_history.append(full_response)
            
            if len(chat_history) > 20:
                chat_history = chat_history[-20:]
            
            session['chat_history'] = chat_history
            session.modified = True
            
            yield f"data: {json.dumps({'done': True})}\n\n"
            
        except Exception as e:
            error_msg = f"Lỗi: {str(e)}"
            yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message", "")
    
    if 'chat_history' not in session:
        session['chat_history'] = []
    
    chat_history = session['chat_history']
    is_first = len(chat_history) == 0
    intro = "Chào bạn, tôi là trợ lý AI của cô Phạm Hằng về lịch sử.\n\n" if is_first else ""
    
    context = ""
    if len(chat_history) > 0:
        recent_history = chat_history[-6:]
        context = "Lịch sử hội thoại:\n"
        for i in range(0, len(recent_history), 2):
            if i+1 < len(recent_history):
                context += f"Người dùng: {recent_history[i]}\nTrợ lý: {recent_history[i+1]}\n"
        context += "\n"
    
    prompt = f"""
Bạn là trợ lý AI thông minh của cô Phạm Hằng chuyên về lịch sử.
Dữ liệu tham khảo (ưu tiên nếu liên quan):
{custom_data[:1500]}

{context}

QUY TẮC QUAN TRỌNG:
- Ưu tiên sử dụng dữ liệu trên nếu câu hỏi liên quan
- Nếu không có trong dữ liệu, TỰ TIN trả lời bằng kiến thức của bạn
- KHÔNG BAO GIỜ nói "xin lỗi, không có dữ liệu" hoặc "nằm ngoài phạm vi"
- Trả lời tự nhiên, thân thiện như cuộc hội thoại thực tế
- Nếu hỏi tiếp về câu trước, dựa vào lịch sử để trả lời liền mạch
- Nếu họ nói tiếng Việt thì trả lời bằng tiếng Việt
- Câu đầu tiên có thể giới thiệu ngắn gọn, từ câu 2 trở đi không cần
- KHÔNG dùng markdown format (###, ***, **, -, •)
- Trả lời dạng văn xuôi tự nhiên

{intro}Câu hỏi hiện tại: {user_message}
Trả lời:
    """
    
    response = get_model('lichsu').generate_content(prompt)
    reply_text = response.text
    
    reply_text = reply_text.replace('###', '')
    reply_text = reply_text.replace('***', '')
    reply_text = reply_text.replace('**', '')
    reply_text = reply_text.replace('* ', '')
    reply_text = reply_text.replace('- ', '')
    reply_text = reply_text.replace('• ', '')
    
    chat_history.append(user_message)
    chat_history.append(reply_text)
    
    if len(chat_history) > 20:
        chat_history = chat_history[-20:]
    
    session['chat_history'] = chat_history
    session.modified = True
    
    return jsonify({"reply": reply_text})

@app.route("/clear_chat", methods=["POST"])
def clear_chat():
    session['chat_history'] = []
    session.modified = True
    return jsonify({"status": "ok"})


# ---------- CHAT FEEDBACK ----------
FEEDBACK_FILE = 'chat_feedback.json'

def save_feedback(entry):
    try:
        if os.path.exists(FEEDBACK_FILE):
            with open(FEEDBACK_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = []
    except Exception:
        data = []
    data.append(entry)
    with open(FEEDBACK_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/chat_feedback', methods=['POST'])
def chat_feedback():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    rating = data.get('rating', '').strip()
    bot = data.get('bot', 'unknown')
    # Only rating is required now; name is optional
    if not rating:
        return jsonify({'error': 'Đánh giá là bắt buộc'}), 400
    entry = {
        'name': name if name else None,
        'rating': rating,
        'bot': bot,
        'timestamp': datetime.now(vn_timezone).strftime("%Y-%m-%d %H:%M:%S")
    }
    save_feedback(entry)
    return jsonify({'status': 'ok'})

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "static", "replies")
os.makedirs(AUDIO_DIR, exist_ok=True)

def load_user_data():
    try:
        with open("data.txt", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""
###############################################
def random_filename(prefix="reply", ext="mp3", n=8):
    s = "".join(random.choices(string.ascii_lowercase + string.digits, k=n))
    return f"{prefix}_{s}.{ext}"

def contains_english(text):
    return bool(re.search(r'[A-Za-z]', text))

@app.route("/replies/<path:filename>")
def serve_reply_audio(filename):
    return send_from_directory(AUDIO_DIR, filename, as_attachment=False)

@app.route("/chat_tam_an", methods=["POST"])
def chat_tam_an():
    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Không có message"}), 400

    user_data = load_user_data()
    prompt = f"""Dưới đây là dữ liệu cá nhân của người dùng:
{json.dumps(user_data, ensure_ascii=False, indent=2)}

QUY TẮC BẮT BUỘC:
- Chỉ trả lời bằng tiếng Việt, không dùng từ/cụm từ tiếng Anh.
- Nếu mô hình dự định dùng từ tiếng Anh, hãy thay bằng từ tiếng Việt tương đương.
- Giọng thân thiện, tự nhiên như một người bạn.
- Câu trả lời ngắn gọn, dưới 3 câu.
- KHÔNG sử dụng markdown (**, ##, ###) trong câu trả lời.

Người dùng hỏi: {user_message}
"""
    try:
        resp = get_model().generate_content(prompt)
        text_reply = resp.text.strip()
        
        # Format lại response: loại bỏ markdown
        text_reply = text_reply.replace('**', '')
        text_reply = text_reply.replace('##', '')
        text_reply = text_reply.replace('###', '')
        
    except Exception as e:
        print("Lỗi khi gọi Gemini:", e)
        text_reply = "Xin lỗi, hiện tại tôi không thể trả lời ngay. Bạn thử lại sau nhé."

    if contains_english(text_reply):
        try:
            follow_prompt = prompt + "\n\nBạn đã sử dụng từ tiếng Anh, hãy trả lời lại hoàn toàn bằng tiếng Việt."
            resp2 = get_model().generate_content(follow_prompt)
            text_reply = resp2.text.strip()
            
            # Format lại lần nữa sau khi retry
            text_reply = text_reply.replace('**', '')
            text_reply = text_reply.replace('##', '')
            text_reply = text_reply.replace('###', '')
            
        except Exception as e:
            print("Lỗi follow-up Gemini:", e)

    audio_filename = None
    try:
        tts_client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text_reply)
        voice = texttospeech.VoiceSelectionParams(
            language_code="vi-VN",
            name="vi-VN-Wavenet-A",
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0,
            pitch=0.0
        )

        tts_response = tts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )

        audio_filename = random_filename()
        audio_path = os.path.join(AUDIO_DIR, audio_filename)
        with open(audio_path, "wb") as f:
            f.write(tts_response.audio_content)
    except Exception as e:
        print("Lỗi Google TTS:", e)
        audio_filename = None

    result = {"reply": text_reply}
    if audio_filename:
        result["audio_url"] = f"/replies/{audio_filename}"
    else:
        result["audio_url"] = None

    return jsonify(result)
####################################################
def load_exam(de_id):
    with open('exam_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get(de_id)
###########################################################3
@app.route('/index_td')
def index_td():
    return render_template('index_tn.html')
#########################################################
@app.route('/exam/<de_id>')
def exam(de_id):
    questions = load_exam(de_id)
    if not questions:
        return "Không tìm thấy đề thi."

    video_url = questions.get("video")
    return render_template('exam.html', questions=questions, de_id=de_id, video_url=video_url)

@app.route('/submit/<de_id>', methods=['GET', 'POST'])
def submit(de_id):
    if request.method != 'POST':
        return redirect(url_for('exam', de_id=de_id))

    questions = load_exam(de_id)
    if not questions:
        return "Không tìm thấy đề thi."

    correct_count = 0
    total_questions = 0
    feedback = []
    results = []

    for i, q in enumerate(questions.get("multiple_choice", [])):
        user_answer = request.form.get(f"mc_{i}")
        correct = q["answer"]
        total_questions += 1
        if user_answer and user_answer.strip().lower() == correct.strip().lower():
            correct_count += 1
            results.append({"status": "Đúng", "note": ""})
        else:
            msg = f"Câu {i+1} sai. Đáp án đúng là: {correct}"
            results.append({"status": "Sai", "note": msg})
            feedback.append(msg)

    for i, tf in enumerate(questions.get("true_false", [])):
        for j, correct_tf in enumerate(tf["answers"]):
            user_tf_raw = request.form.get(f"tf_{i}_{j}", "").lower()
            user_tf = user_tf_raw == "true"
            total_questions += 1
            if user_tf == correct_tf:
                correct_count += 1
                results.append({"status": "Đúng", "note": ""})
            else:
                msg = f"Câu {i+1+len(questions['multiple_choice'])}, ý {j+1} sai."
                results.append({"status": "Sai", "note": msg})
                feedback.append(msg)

    score = correct_count
    summary = f"Học sinh làm đúng {correct_count} / {total_questions} câu."
    try:
        prompt = (
            f"{summary}\n\n"
            "Dưới đây là danh sách các lỗi học sinh mắc phải:\n"
            + "\n".join(feedback) + "\n\n"
            "Bạn là giáo viên lịch sử. Hãy:\n"
            "1. Nhận xét tổng thể bài làm\n"
            "2. Phân tích từng lỗi sai (nêu lý do sai, giải thích kiến thức liên quan)\n"
            "3. Đề xuất ít nhất 3 dạng bài tập cụ thể để học sinh luyện tập đúng phần bị sai"
        )
        response = get_model('lichsu').generate_content([prompt])
        ai_feedback = response.text
        
        # Format lại response: thay thế markdown bằng HTML
        ai_feedback = ai_feedback.replace('**', '')
        ai_feedback = ai_feedback.replace('##', '')
        ai_feedback = ai_feedback.replace('###', '')
        ai_feedback = ai_feedback.replace('\n', '<br>')
        
    except Exception as e:
        ai_feedback = f"⚠ Lỗi khi gọi AI: {str(e)}"
    
    return render_template(
        'result.html',
        score=score,
        feedback=feedback,
        ai_feedback=ai_feedback,
        total_questions=total_questions,
        results=results
    )

# TIÊU CHÍ CHẤM ĐIỂM từ file data_2.txt
RUBRIC_CRITERIA = """
HỆ THỐNG TIÊU CHÍ CHẤM ĐIỂM (10 điểm):

Câu 1 (1,5 điểm):
- Năng lực: Trình bày được nội dung chính về đặc điểm của các lực lượng cách mạng và vai trò của nghị quyết (0,5 điểm)  
- Kể tên các nhân vật lịch sử, sự kiện và phản ánh năng lực phân tích (0,25 điểm)
- Mức độ đầy đủ về các vấn đề liên quan đến nội dung câu hỏi (0,25 điểm)
- Trong thời đại ngày nay, phân tích vai trò của các lực lượng và ý nghĩa trong bối cảnh hiện tại (0,25 điểm)
- Công xót người dân về việc phát triển và xây dựng lực lượng cách mạng (0,25 điểm)

Câu 2 (1,5 điểm):
- Em hãy nêu khái niệm và vai trò của lực lượng dân tộc trong sự nghiệp cách mạng (0,5 điểm)
- Năng lực phân tích bối cảnh lịch sử và vai trò của ngoại lực (0,5 điểm)
- Viết mạch lạc, có luận cứ về vai trò của các yếu tố trong phong trào cách mạng (0,5 điểm)
"""


def generate_grading_prompt():
    """Tạo prompt chấm điểm dựa trên rubric"""
    
    prompt = f"""Bạn là giáo viên Lịch sử chấm bài. Hãy phân tích bài làm trong ảnh theo TIÊU CHÍ SAU:

{RUBRIC_CRITERIA}

YÊU CẦU CHẤM BÀI:
1. Đọc kỹ bài làm của học sinh trong ảnh
2. Chấm điểm CHI TIẾT cho TỪNG TIÊU CHÍ theo đúng thang điểm
3. Phân tích theo format BẮT BUỘC:

📊 TỔNG ĐIỂM: [X/3]

📝 ĐIỂM CHI TIẾT:

**CÂU 1 ([X]/1.5 điểm):**
- Tiêu chí 1 (0.5đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 2 (0.25đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 3 (0.25đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 4 (0.25đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 5 (0.25đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]

**CÂU 2 ([X]/1.5 điểm):**
- Tiêu chí 1 (0.5đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 2 (0.5đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 3 (0.5đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]



❌ LỖI SAI CẦN SỬA (nếu có):
- "Trích nguyên văn lỗi trong bài" → Sửa: [giải thích đúng]
- "Trích nguyên văn lỗi khác" → Sửa: [giải thích đúng]

💡 GỢI Ý CẢI THIỆN:
[1-2 câu ngắn gọn để học sinh cải thiện bài làm]

LƯU Ý QUAN TRỌNG:
- Phải TRÍCH NGUYÊN VĂN câu/đoạn sai trong bài làm (đặt trong dấu ngoặc kép)
- Chỉ ra lỗi CỤ THỂ: sai sự kiện, sai năm tháng, sai khái niệm, thiếu logic, thiếu độ sâu...
- Chấm điểm CÔNG BẰNG theo đúng thang điểm từng tiêu chí
- Tối đa 200 từ, ngắn gọn súc tích"""

    return prompt


@app.route('/upload_image', methods=['GET', 'POST'])
def upload_image():
    ai_feedback = None

    if request.method == 'POST':
        image = request.files.get('image')
        if not image or image.filename == '':
            return render_template('upload_image.html', feedback="⚠ Không có ảnh được chọn.")

        image_path = os.path.join(app.config['UPLOAD_FOLDER'], image.filename)
        image.save(image_path)

        try:
            img = Image.open(image_path)
            
            # SỬ DỤNG PROMPT MỚI với rubric chi tiết
            prompt = generate_grading_prompt()

            # Gọi model AI (thay 'model' bằng model của bạn)
            response = get_model('lichsu').generate_content([img, prompt])
            ai_feedback = response.text
            
            # Format lại response để hiển thị đẹp
            ai_feedback = format_feedback_html(ai_feedback)
            
        except Exception as e:
            ai_feedback = f"⚠ Lỗi khi xử lý ảnh: {str(e)}"

    return render_template('upload_image.html', feedback=ai_feedback)


def format_feedback_html(text):
    """Format feedback thành HTML đẹp"""
    
    # Thay thế markdown bold
    text = text.replace('**', '<strong>').replace('**', '</strong>')
    
    # Thêm màu sắc cho các phần
    text = text.replace('📊 TỔNG ĐIỂM:', '<div class="total-score">📊 TỔNG ĐIỂM:')
    text = text.replace('📝 ĐIỂM CHI TIẾT:', '</div><div class="details">📝 ĐIỂM CHI TIẾT:')
    text = text.replace('✅ ĐIỂM MẠNH', '</div><div class="strengths">✅ ĐIỂM MẠNH')
    text = text.replace('❌ LỖI SAI', '</div><div class="errors">❌ LỖI SAI')
    text = text.replace('💡 GỢI Ý', '</div><div class="suggestions">💡 GỢI Ý')
    
    # Xuống dòng
    text = text.replace('\n', '<br>')
    
    text += '</div>'  # Đóng div cuối cùng
    
    return text

    ##########################################

@app.route("/tam_an")
def tam_an():
    return render_template("chat_tam_an.html")

@app.route("/home")
def home():
    return render_template("menu.html")

@app.route("/enter_nickname")
def enter_nickname():
    return render_template("nickname.html")

@app.route("/start_game", methods=["POST"])
def start_game():
    nickname = request.form["nickname"]
    bai = request.form["bai"]
    session["nickname"] = nickname
    session["bai"] = bai
    return redirect("/game")

@app.route("/game")
def game():
    return render_template("game.html")

@app.route("/get_questions")
def get_questions_quiz():
    import random
    bai = session.get("bai", "bai_1")
    with open("questions.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get(bai, [])
    random.shuffle(questions)
    for q in questions:
        random.shuffle(q["options"])
    return jsonify(questions[:20])

@app.route("/submit_score", methods=["POST"])
def submit_score():
    nickname = session.get("nickname")
    bai = session.get("bai")
    score = request.json["score"]

    if not nickname:
        return jsonify({"status": "error", "message": "No nickname found"})
    if not bai:
        return jsonify({"status": "error", "message": "No bai found"})

    if not os.path.exists("scores.json"):
        with open("scores.json", "w", encoding="utf-8") as f:
            json.dump([], f)

    with open("scores.json", "r+", encoding="utf-8") as f:
        scores = json.load(f)
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        existing = next((s for s in scores if s["nickname"] == nickname and s.get("bai") == bai), None)

        if existing:
            if score > existing["score"]:
                existing["score"] = score
                existing["time"] = now
        else:
            scores.append({
                "nickname": nickname,
                "score": score,
                "time": now,
                "bai": bai
            })
        filtered = [s for s in scores if s.get("bai") == bai]
        top50 = sorted(filtered, key=lambda x: x["score"], reverse=True)[:50]
        others = [s for s in scores if s.get("bai") != bai]
        final_scores = others + top50

        f.seek(0)
        json.dump(final_scores, f, ensure_ascii=False, indent=2)
        f.truncate()

    return jsonify({"status": "ok"})

@app.route("/leaderboard")
def leaderboard():
    bai = session.get("bai")

    if not bai:
        bai = "bai_1"

    if not os.path.exists("scores.json"):
        top5 = []
    else:
        with open("scores.json", "r", encoding="utf-8") as f:
            scores = json.load(f)

        filtered = [s for s in scores if s.get("bai") == bai]
        top5 = sorted(filtered, key=lambda x: x["score"], reverse=True)[:5]

    return render_template("leaderboard.html", players=top5, bai=bai)

###############
@app.route('/dich-vu-y-te')
def dich_vu():
    """Route hiển thị danh sách các cơ sở y tế tại Hà Nội"""
    
    # Dữ liệu các cơ sở y tế
    co_so_y_te = [
        {
            'ten': 'Công ty CP Tham vấn, Nghiên cứu và Tâm lý học Cuộc sống - SHARE',
            'dia_chi': '31 Ngõ 84 Trần Quang Diệu, Quang Trung, Đống Đa, Hà Nội',
            'dien_thoai': '024 22116989',
            'website': 'tuvantamly.com.vn',
            'loai': 'Tư vấn tâm lý'
        },
        {
            'ten': 'Bệnh viện Tâm thần ban ngày Mai Hương',
            'dia_chi': '4 Hồng Mai, Bạch Mai, Hai Bà Trưng, Hà Nội',
            'dien_thoai': '024 3627 5762',
            'website': 'http://www.maihuong.gov.vn/',
            'loai': 'Bệnh viện tâm thần'
        },
        {
            'ten': 'Bệnh viện Tâm thần Hà Nội',
            'dia_chi': 'Ngõ 467 Nguyễn Văn Linh, Sài Đồng, Long Biên, Hà Nội',
            'dien_thoai': '024 3827 6534',
            'website': '',
            'loai': 'Bệnh viện tâm thần'
        },
        {
            'ten': 'Bệnh viện Tâm thần Trung ương I',
            'dia_chi': 'Hòa Bình - Thượng Tín - Hà Nội',
            'dien_thoai': '02433.853.227',
            'website': '',
            'loai': 'Bệnh viện tâm thần'
        },
        {
            'ten': 'Khoa Tâm thần - Bệnh viện Quân Y 103',
            'dia_chi': '261 Phùng Hưng - Hà Đông - Hà Nội',
            'dien_thoai': '',
            'website': '',
            'loai': 'Khoa tâm thần'
        },
        {
            'ten': 'Khoa Tâm bệnh học và Liệu pháp tâm lý, Bệnh viện Việt Pháp Hà Nội',
            'dia_chi': '1 Phương Mai, Phương Mai, Đống Đa, Hà Nội',
            'dien_thoai': '024 3577 1100',
            'website': '',
            'loai': 'Khoa tâm thần'
        },
        {
            'ten': 'Khoa Tâm thần - Bệnh viện Nhi trung ương',
            'dia_chi': '18/879 đường La Thành, Láng Thượng, quận Đống Đa, Hà Nội',
            'dien_thoai': '024 6273 8965 hoặc 024 6273 8964',
            'website': '',
            'loai': 'Khoa tâm thần'
        }
    ]
    
    return render_template('dichvu.html', co_so_y_te=co_so_y_te)
######
# Thêm vào sau phần load_dotenv()
EXAM_TEACHERS_FILE = 'teachers_exam.json'
EXAM_STUDENTS_FILE = 'students_exam.json'
EXAMS_DATA_FILE = 'exams_data.json'
EXAM_SUBMISSIONS_FILE = 'exam_submissions.json'
MATERIALS_DATA_FILE = 'materials_data.json'

# Các hàm helper cho exam system
def load_exam_teachers():
    if not os.path.exists(EXAM_TEACHERS_FILE):
        return {}
    with open(EXAM_TEACHERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_exam_teachers(data):
    with open(EXAM_TEACHERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_exam_students():
    if not os.path.exists(EXAM_STUDENTS_FILE):
        return {}
    with open(EXAM_STUDENTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_exam_students(data):
    with open(EXAM_STUDENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_exams_data():
    if not os.path.exists(EXAMS_DATA_FILE):
        return {}
    with open(EXAMS_DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_exams_data(data):
    with open(EXAMS_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_exam_submissions():
    if not os.path.exists(EXAM_SUBMISSIONS_FILE):
        return []
    with open(EXAM_SUBMISSIONS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_exam_submissions(data):
    with open(EXAM_SUBMISSIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_materials_data():
    if not os.path.exists(MATERIALS_DATA_FILE):
        return []
    with open(MATERIALS_DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        # Đảm bảo luôn trả về list
        if isinstance(data, dict):
            return []
        return data if isinstance(data, list) else []


def save_materials_data(data):
    with open(MATERIALS_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def read_word_file(file_path):
    try:
        with open(file_path, "rb") as docx_file:
            result = mammoth.extract_raw_text(docx_file)
            return result.value
    except Exception as e:
        print(f"Loi doc file Word: {e}")
        return ""
###########
def auto_grade_essay_with_ai(exam, essay_answer, image_path=None):
    """Tự động chấm bài tự luận bằng AI"""
    try:
        if image_path:
            img = Image.open(image_path)
            
            prompt = f"""
Ban la giao vien lich su cham bai thi tu luan.

De bai: {exam.get('essay_question', '')}

Tieu chi cham: {exam.get('grading_criteria', 'Cham theo noi dung va logic')}

Hay cham diem bai lam cua hoc sinh trong anh theo thang diem 10.

Phan tich chi tiet:
1. Diem manh cua bai lam
2. Diem yeu can cai thien
3. Cac kien thuc con thieu
4. Goi y cu the de cai thien

Tra ve JSON (KHONG DUNG DAU # VA **):
{{
  "score": <diem so>,
  "strengths": "<diem manh>",
  "weaknesses": "<diem yeu>",
  "missing_knowledge": "<kien thuc thieu>",
  "improvement_areas": "<dang bai can cai thien>",
  "suggestions": "<loi khuyen cu the>"
}}

Chi tra ve JSON, khong them bat ky ky tu nao khac.
"""
            response = get_model('lichsu').generate_content([img, prompt])
        else:
            prompt = f"""
Ban la giao vien lich su cham bai thi tu luan.

De bai: {exam.get('essay_question', '')}

Tieu chi cham: {exam.get('grading_criteria', 'Cham theo noi dung va logic')}

Bai lam cua hoc sinh: {essay_answer}

Hay cham diem theo thang diem 10 va phan tich chi tiet.

Phan tich chi tiet:
1. Diem manh cua bai lam
2. Diem yeu can cai thien
3. Cac kien thuc con thieu
4. Goi y cu the de cai thien

Tra ve JSON (KHONG DUNG DAU # VA **):
{{
  "score": <diem so>,
  "strengths": "<diem manh>",
  "weaknesses": "<diem yeu>",
  "missing_knowledge": "<kien thuc thieu>",
  "improvement_areas": "<dang bai can cai thien>",
  "suggestions": "<loi khuyen cu the>"
}}

Chi tra ve JSON.
"""
            response = get_model().generate_content(prompt)
        
        text = response.text.strip()
        text = text.replace('```json', '').replace('```', '').strip()
        result = json.loads(text)
        return result
        
    except Exception as e:
        print(f"Loi cham AI: {e}")
        return None


def auto_grade_mixed_essay_with_ai(question, grading_criteria, essay_answer, image_path=None, max_score=3):
    """
    Chấm từng câu tự luận trong đề hỗn hợp
    
    Args:
        question: Câu hỏi
        grading_criteria: Tiêu chí chấm
        essay_answer: Bài làm của học sinh
        image_path: Đường dẫn ảnh (nếu có)
        max_score: Điểm tối đa cho câu này ⭐ THÊM THAM SỐ NÀY
    """
    try:
        if image_path:
            img = Image.open(image_path)
            
            prompt = f"""
Ban la giao vien lich su cham bai.

Cau hoi: {question}

Tieu chi: {grading_criteria}

Hay cham diem bai lam trong anh theo thang diem {max_score}.
                                                ^^^^^^^^^^^ ⭐ THAY ĐỔI

Tra ve JSON (KHONG DUNG # VA **):
{{
  "score": <diem so tren {max_score}, lam tron 2 chu so thap phan>,
  "analysis": "<phan tich bai lam>",
  "suggestions": "<loi khuyen cu the>"
}}

Chi tra ve JSON.
"""
            response = get_model().generate_content([img, prompt])
        else:
            prompt = f"""
Ban la giao vien lich su cham bai.

Cau hoi: {question}

Bai lam: {essay_answer}

Tieu chi: {grading_criteria}

Hay cham diem theo thang diem {max_score}.
                              ^^^^^^^^^^^ ⭐ THAY ĐỔI

Tra ve JSON (KHONG DUNG # VA **):
{{
  "score": <diem so tren {max_score}, lam tron 2 chu so thap phan>,
  "analysis": "<phan tich bai lam>",
  "suggestions": "<loi khuyen cu the>"
}}

Chi tra ve JSON.
"""
            response = get_model().generate_content(prompt)
        
        text = response.text.strip()
        text = text.replace('```json', '').replace('```', '').strip()
        result = json.loads(text)
        
        # ⭐ THÊM VALIDATION ĐỂ ĐẢM BẢO ĐIỂM KHÔNG VƯỢT QUÁ
        score = float(result.get('score', 0))
        result['score'] = round(min(max(score, 0), max_score), 2)  # Cap trong [0, max_score]
        result['max_score'] = max_score  # ⭐ Lưu lại điểm tối đa
        
        return result
        
    except Exception as e:
        print(f"Loi cham AI: {e}")
        return None

# CẬP NHẬT HÀM GENERATE EXAM
def validate_exam_questions(exam_data, num_multiple, num_truefalse, num_essay=0):
    """
    ✅ KIỂM TRA xem AI tạo được đủ câu hỏi không
    Trả về: (True/False, số MC, số TF, số Essay, thông báo lỗi)
    """
    if not exam_data:
        return False, 0, 0, 0, "AI không tạo được đề thi"
    
    mc_list = exam_data.get('multiple_choice', [])
    tf_list = exam_data.get('true_false', [])
    essay_list = exam_data.get('essay', [])
    
    mc_count = len(mc_list)
    tf_count = len(tf_list)
    essay_count = len(essay_list)
    
    errors = []
    
    # Kiểm tra số lượng
    if mc_count < num_multiple:
        errors.append(f"❌ Trắc nghiệm: cần {num_multiple}, chỉ có {mc_count}")
    if tf_count < num_truefalse:
        errors.append(f"❌ Đúng/Sai: cần {num_truefalse}, chỉ có {tf_count}")
    if num_essay > 0 and essay_count < num_essay:
        errors.append(f"❌ Tự luận: cần {num_essay}, chỉ có {essay_count}")
    
    # Kiểm tra rỗng
    for i, q in enumerate(mc_list):
        if not q.get('question') or not q.get('answer'):
            errors.append(f"❌ MC câu {i+1}: thiếu question hoặc answer")
    
    for i, q in enumerate(tf_list):
        if not q.get('question') or not q.get('statements') or not q.get('answers'):
            errors.append(f"❌ TF câu {i+1}: thiếu dữ liệu")
    
    is_valid = len(errors) == 0
    error_msg = " | ".join(errors) if errors else ""
    
    return is_valid, mc_count, tf_count, essay_count, error_msg


def generate_exam_from_text_local(text_content, num_multiple, num_truefalse, num_essay=0):
    """Rule-based fallback generation without calling AI API."""
    # split into sentences
    sentences = [s.strip() for s in re.split(r'(?<=[\.\?!])\s+', text_content) if s.strip()]
    mc = []
    tf = []
    # helper to pick year from sentence
    for s in sentences:
        years = re.findall(r"\b(19|20)\d{2}\b", s)
        if years and len(mc) < num_multiple:
            year = years[0]
            # build options: include year plus nearby variants
            opts = [year]
            for d in (-10, -5, 5, 10):
                opts.append(str(int(year) + d))
            random.shuffle(opts)
            mc.append({
                "question": f"Năm nào được nhắc tới trong câu: '{s}'?",
                "options": [f"{chr(65+i)}. {opt}" for i,opt in enumerate(opts[:4])],
                "answer": opts[:4].index(year)
            })
        if 'không' in s.lower() and len(tf) < num_truefalse:
            # create a trivial TF by asking if sentence contains một từ cụ thể
            stmt = s
            tf.append({
                "question": f"Câu sau đúng hay sai? {s}",
                "statements": [s, "Câu khác", "Câu khác nữa", "Khác"],
                "answers": [True, False, False, False]
            })
    return {"multiple_choice": mc[:num_multiple], "true_false": tf[:num_truefalse], "essay": []}


def parse_docx_strictly(text):
    """
    Thuật toán tách đề thi chính xác 100% dựa trên các quy luật cố định (Câu X, A/B/C/D, a/b/c/d).
    Hỗ trợ cả Đáp án đi kèm câu hỏi và Bảng đáp án tổng hợp ở cuối file.
    """
    # 1. Chuẩn hóa xuống dòng để dễ xử lý
    text = text.replace('\r\n', '\n')
    
    # 2. Cô lập văn bản chính (Main Content) và Đáp án (Footer)
    footer_match = re.search(r'(?i)\n\s*ĐÁP\s*ÁN\s*[:\-]', text)
    if not footer_match:
        # Fallback tìm "PHẦN I:" ở cuối file (vùng đáp án)
        footer_match = re.search(r'(?i)\n\s*PHẦN\s*I\s*[I|V|X\d]*\s*[:\-]', text)
        if not (footer_match and footer_match.start() > len(text) * 0.7):
            footer_match = None

    # 3. Xử lý Bảng đáp án tổng hợp (nếu có)
    mc_global_answers = {}
    tf_global_answers = {}
    
    # Vùng tìm kiếm đáp án (Footer)
    search_zone = text[footer_match.start():] if footer_match else text[int(len(text)*0.6):]

    # Tìm vùng đáp án trắc nghiệm Phần I
    mc_section = re.search(r'(?i)PHẦN\s*I.*?(?=Phần\s*II|-------|$)', search_zone, re.DOTALL)
    if mc_section:
        ans_text = mc_section.group(0)
        # Tìm các cặp số và chữ cái (ví dụ: 1 B, 2 A...)
        # Lưu ý: file mau_de.docx có format số ở trên, chữ ở dưới trong bảng, mammoth dump ra dính chùm hoặc cách xa
        # Ta quét toàn bộ số và chữ cái độc lập trong vùng này
        numbers = re.findall(r'\b(\d+)\b', ans_text)
        letters = re.findall(r'\b([A-D])\b', ans_text.upper())
        # Nếu số lượng khớp, ghép cặp
        if len(numbers) == len(letters):
            for n, l in zip(numbers, letters):
                mc_global_answers[int(n)] = l
        else:
            # Fallback: Nếu không khớp, thử tìm các cụm dính nhau kiểu "1.A" hoặc "1 A"
            pairs = re.findall(r'(\d+)[\s\.]*([A-D])', ans_text.upper())
            for n, l in pairs:
                mc_global_answers[int(n)] = l

    # Tìm vùng đáp án Đúng/Sai Phần II
    tf_section = re.search(r'(?i)PHẦN\s*II.*?(?=$)', search_zone, re.DOTALL)
    if tf_section:
        ans_text = tf_section.group(0)
        # Lấy từng khối của Câu 1, Câu 2... trong vùng đáp án
        tf_pairs = re.findall(r'(?i)Câu\s*(\d+)\s*[:\.\n\s]*(.*?)(?=Câu\s*\d+|Phần|-------|$)', ans_text, re.DOTALL)
             
        for n, val_block in tf_pairs:
            vals = []
            # Tìm theo định dạng dòng có marker: a) Đúng ...
            lines = [l.strip() for l in val_block.split('\n') if l.strip()]
            for line in lines:
                # Phải có marker [a-d] ở đầu dòng (ví dụ: a) Đúng)
                m = re.match(r'(?i)([a-d])[\s\.\)]+\s*([đs]|đúng|sai)\b', line)
                if m:
                    val = m.group(2).lower()
                    if val.startswith('đ'): vals.append(True)
                    else: vals.append(False)
            
            # Nếu không tìm thấy theo dòng có marker, tìm tự do (ví dụ: Đ, S, Đ, Đ hoặc S, Đ, Đ, Đ)
            if not vals:
                # Tìm tất cả cụm từ đ/s/đúng/sai đứng độc lập hoặc cách nhau bởi dấu phẩy/khoảng trắng
                matches = re.findall(r'(?i)\b([đs]|đúng|sai)\b', val_block)
                for m in matches:
                    m = m.lower()
                    if m.startswith('đ'): vals.append(True)
                    else: vals.append(False)
                    
            if len(vals) >= 4:
                tf_global_answers[int(n)] = vals[:4]

    # 4. Tách đề thi thành các phần nội dung chính
    main_text = text[:footer_match.start()].strip() if footer_match else text
    # Pattern: Phần [Số La Mã] hoặc [Số thường] ở đầu dòng
    parts_raw = re.split(r'(?i)\n\s*(?:Phần|PHẦN)\s+([I|V|X|L|C]+|\d+)[\s\.\:]', "\n" + main_text)
    
    processed_mc = []
    processed_tf = []
    processed_essay = []
    
    current_sticky_context = ""
    sticky_start = 0
    sticky_until = 0
    # Capture cả câu bắt đầu và câu kết thúc
    context_pattern = r'(?i)(Đọc\s+đoạn\s+tư\s+liệu\s+.*?trả\s+lời\s+.*?(?:câu\s+|câu\s+hỏi\s+)(?:từ\s+)?(\d+)\s+đến\s+(\d+).*)'

    # parse_docx_strictly iterate through parts
    work_list = []
    # Nếu parts_raw[0] chứa nội dung (không có Phần I heading ở đầu), nó là Phần I
    if parts_raw[0].strip():
        work_list.append(("I", parts_raw[0].strip()))
    
    for i in range(1, len(parts_raw), 2):
        work_list.append((parts_raw[i].upper(), parts_raw[i+1].strip()))

    for part_label, part_content in work_list:
        # RESET context khi sang Phần mới
        current_sticky_context = ""
        sticky_start = 0
        sticky_until = 0
        
        # Tách câu hỏi: Câu X ở ĐẦU DÒNG
        raw_qs = re.split(r'(?i)\n\s*Câu\s+(\d+)[\.:]', "\n" + part_content)
        
        # Check context ở đoạn mở đầu phần
        initial_context_match = re.search(context_pattern, raw_qs[0], re.DOTALL)
        if initial_context_match:
            current_sticky_context = initial_context_match.group(1).strip()
            sticky_start = int(initial_context_match.group(2))
            sticky_until = int(initial_context_match.group(3))

        for j in range(1, len(raw_qs), 2):
            q_num = int(raw_qs[j])
            block = raw_qs[j+1].strip()
            if not block: continue

            # Kiểm tra context giữa chừng
            context_match = re.search(context_pattern, block, re.DOTALL)
            if context_match:
                next_context = context_match.group(1).strip()
                next_start = int(context_match.group(2))
                next_until = int(context_match.group(3))
                block = block[:context_match.start()].strip()
                current_sticky_context = next_context
                sticky_start = next_start
                sticky_until = next_until

            # CHỈ GẮN NẾU q_num nằm trong khoảng [sticky_start, sticky_until]
            prefix = ""
            if current_sticky_context and sticky_start <= q_num <= sticky_until:
                prefix = f"({current_sticky_context})\n\n"
            
            # Reset nếu đã đi qua phạm vi
            if q_num > sticky_until:
                current_sticky_context = ""
                sticky_start = 0
                sticky_until = 0

            # Xử lý Đáp án inline
            ans_match = re.search(r'(?i)Đáp\s+án\s*[:\-]\s*(.*)', block)
            ans_text = ans_match.group(1).strip() if ans_match else ""
            content_block = re.split(r'(?i)Đáp\s+án\s*[:\-]', block)[0].strip()
            
            # PHÂN LOẠI CÂU HỎI THEO DẤU HIỆU VÀ PHẦN
            # MCQ: A. B. C. D. (Phải là chữ HOA, có dấu cách phía trước hoặc đầu dòng)
            has_mc_markers = all(re.search(fr'(?:\s+|^){L}[\.\)]', content_block) for L in ['A', 'B', 'C', 'D'])
            # TF: a) b) c) d) (Phải là chữ thường, có dấu cách phía trước hoặc đầu dòng)
            has_tf_markers = all(re.search(fr'(?:\s+|^){l}[\)\.]', content_block) for l in ['a', 'b', 'c', 'd'])

            # Ưu tiên tuyệt đối cho loại câu hỏi theo Phần
            q_type = "ESSAY"
            if part_label == "I": 
                q_type = "MCQ"
                # Nếu có dấu hiệu TF quá rõ ràng thì ghi đè
                if has_tf_markers and not has_mc_markers: q_type = "TF"
            elif part_label == "II": 
                q_type = "TF"
                # Nếu có dấu hiệu MCQ quá rõ ràng thì ghi đè
                if has_mc_markers and not has_tf_markers: q_type = "MCQ"
            else:
                if has_mc_markers: q_type = "MCQ"
                elif has_tf_markers: q_type = "TF"

            if q_type == "MCQ":
                # Tách option (Case sensitive markers, yêu cầu có khoảng trắng phía trước)
                parts = re.split(r'(?:\s+|^)([A-D][\.\)])', content_block)
                question_text = prefix + parts[0].strip()
                options = []
                markers_found = []
                for k in range(1, len(parts), 2):
                    marker_raw = parts[k].upper().replace(')', '.')
                    markers_found.append(marker_raw[0]) # Lấy chữ cái A, B, C, D
                    opt_content = parts[k+1].strip()
                    options.append(f"{marker_raw} {opt_content}")
                
                # Kiểm tra xem có đúng thứ tự A, B, C, D không
                is_standard = (len(options) == 4 and "".join(markers_found) == "ABCD")
                
                current_answer = "A"
                if ans_text:
                    letter_match = re.search(r'[A-D]', ans_text.upper())
                    if letter_match: current_answer = letter_match.group(0)
                elif q_num in mc_global_answers:
                    current_answer = mc_global_answers[q_num]
                
                q_obj = {
                    "question": question_text,
                    "options": options[:4] if len(options) >= 4 else options,
                    "answer": current_answer,
                    "_is_standard": is_standard,
                    "_raw_block": content_block
                }
                processed_mc.append(q_obj)

            elif q_type == "TF":
                # Tách (Case sensitive markers lowercase, yêu cầu có khoảng trắng phía trước để tránh nhầm "miền Bắc.")
                parts = re.split(r'(?:\s+|^)([a-d][\)\.])', content_block)
                question_text = prefix + parts[0].strip()
                statements = []
                markers_found = []
                for k in range(1, len(parts), 2):
                    marker_raw = parts[k].lower().replace('.', ')')
                    markers_found.append(marker_raw[0])
                    stmt_content = parts[k+1].strip()
                    statements.append(f"{marker_raw} {stmt_content}")
                
                is_standard = (len(statements) == 4 and "".join(markers_found) == "abcd")
                
                # Mặc định, nếu không có đáp án thì để None để AI xử lý ở bước Repair
                answers = [None, None, None, None] 
                
                if ans_text:
                    line_text = ans_text.lower()
                    new_ans = []
                    for m in ['a', 'b', 'c', 'd']:
                        if re.search(fr'{m}[\-\s:]*(đ|đúng)', line_text): new_ans.append(True)
                        elif re.search(fr'{m}[\-\s:]*(s|sai)', line_text): new_ans.append(False)
                    if len(new_ans) == 4: answers = new_ans
                elif q_num in tf_global_answers:
                    answers = tf_global_answers[q_num]

                # Nếu vẫn chưa có đáp án, ta sẽ dùng AI để suy luận
                if None in answers:
                    is_standard = False # Buộc qua bước AI Repair
                    
                processed_tf.append({
                    "question": question_text,
                    "statements": statements[:4] if len(statements) >= 4 else statements,
                    "answers": [a if a is not None else True for a in answers],
                    "_is_standard": is_standard,
                    "_raw_block": content_block
                })
            else:
                # Nếu là Tự luận nhưng trông có vẻ giống MCQ/TF bị lỗi, ta có thể đánh dấu để AI xử lý sau
                # Ở đây ta tạm thời cứ để là Tự luận
                processed_essay.append({
                    "question": prefix + content_block,
                    "grading_criteria": "Giáo viên tự chấm."
                })
            
    # BƯỚC CUỐI: TỰ ĐỘNG SỬA NHỮNG CÂU BỊ LỖI (Hybrid)
    final_mc = []
    for q in processed_mc:
        if not q.get('_is_standard'):
            repaired = repair_question_with_ai(q.get('_raw_block', q['question']), "MCQ")
            if repaired: 
                # Giữ lời dẫn prefix nếu AI làm mất
                if "Đọc đoạn tư liệu" in q['question'] and "Đọc đoạn tư liệu" not in repaired['question']:
                    repaired['question'] = q['question'].split(')\n\n')[0] + ")\n\n" + repaired['question']
                final_mc.append(repaired)
            else: final_mc.append(q)
        else:
            final_mc.append(q)
            
    final_tf = []
    for q in processed_tf:
        if not q.get('_is_standard'):
            repaired = repair_question_with_ai(q.get('_raw_block', q['question']), "TF")
            if repaired: 
                if "Đọc đoạn tư liệu" in q['question'] and "Đọc đoạn tư liệu" not in repaired['question']:
                    repaired['question'] = q['question'].split(')\n\n')[0] + ")\n\n" + repaired['question']
                final_tf.append(repaired)
            else: final_tf.append(q)
        else:
            final_tf.append(q)

    return {
        "multiple_choice": final_mc,
        "true_false": final_tf,
        "essay": processed_essay
    }

def repair_question_with_ai(block_text, q_type):
    """
    Sử dụng Gemini để sửa một block câu hỏi bị lỗi cấu trúc.
    """
    model = get_model()
    if not model: return None
    
    prompt = f"""
Bạn là chuyên gia bóc tách đề thi. Tôi có một câu hỏi bị lỗi định dạng khi bóc tách bằng thuật toán.
Hãy bóc tách câu hỏi này sang định dạng JSON chính xác.

Loại câu hỏi: {q_type} (MCQ: Trắc nghiệm, TF: Đúng/Sai)

Nội dung thô:
{block_text}

JSON Format:
Cho MCQ: {{"question": "...", "options": ["A. ...", "B. ...", "C. ...", "D. ..."], "answer": "..."}}
Cho TF: {{"question": "...", "statements": ["a) ...", "b) ...", "c) ...", "d) ..."], "answers": [true, false, true, true]}}

LƯU Ý: 
- Chỉ trả về JSON, không giải thích gì thêm. 
- Không tự bịa thêm thông tin. 
- Nếu là TF, trả về đủ 4 statements.
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        import json
        return json.loads(text)
    except:
        return None



def generate_exam_from_text(text_content, num_multiple=0, num_truefalse=0, num_essay=0, attempt=1, use_api=True):
    """
    Hàm này bóc tách TOÀN BỘ nội dung từ file Word bằng thuật toán Strict Parser.
    Số lượng câu hỏi sẽ phụ thuộc hoàn toàn vào nội dung file.
    """
    try:
        strict_data = parse_docx_strictly(text_content)
        return strict_data
    except Exception as e:
        print(f"❌ Lỗi xử lý đề thi: {e}")
        return None


# Routes cho exam system

@app.route('/login_exam', methods=['GET', 'POST'])
def login_exam():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        role = request.form.get('role')
        
        if role == 'teacher':
            teachers = load_exam_teachers()
            if username in teachers and teachers[username]['password'] == password:
                session['exam_username'] = username
                session['exam_role'] = 'teacher'
                # XÓA return_to vì giáo viên không cần
                session.pop('return_to', None)
                return redirect(url_for('dashboard_teacher'))
            else:
                return render_template('login_exam.html', message="Sai ten dang nhap hoac mat khau")
        else:
            students = load_exam_students()
            if username in students and students[username]['password'] == password:
                session['exam_username'] = username
                session['exam_role'] = 'student'
                
                # KIỂM TRA CÓ URL TRỞ VỀ KHÔNG
                return_to = session.pop('return_to', None)
                if return_to:
                    return redirect(return_to)
                else:
                    return redirect(url_for('dashboard_student'))
            else:
                return render_template('login_exam.html', message="Sai ten dang nhap hoac mat khau")
    
    return render_template('login_exam.html')

@app.route('/register_exam', methods=['GET', 'POST'])
def register_exam():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        fullname = request.form.get('fullname').strip()
        school = request.form.get('school', '').strip()
        grade_level = request.form.get('grade_level', '').strip()
        class_name = request.form.get('class_name', '').strip()
        
        students = load_exam_students()
        
        if username in students:
            return render_template('register_exam.html', message="Ten dang nhap da ton tai")
        
        # Tạo mã học sinh tự động (HS + năm + 4 số ngẫu nhiên)
        import random
        from datetime import datetime
        year = datetime.now(vn_timezone).year
        student_id = f"HS{year}{random.randint(1000, 9999)}"
        
        students[username] = {
            "password": password,
            "fullname": fullname,
            "school": school,
            "grade_level": grade_level,
            "class_name": class_name,
            "student_id": student_id,
            "created_at": datetime.now(vn_timezone).strftime("%Y-%m-%d %H:%M:%S")
        }
        save_exam_students(students)
        return redirect(url_for('login_exam'))
    
    return render_template('register_exam.html')

#############
@app.route('/upload_material', methods=['POST'])
def upload_material():
    if 'exam_username' not in session or session.get('exam_role') != 'teacher':
        return redirect(url_for('login_exam'))
    
    title = request.form.get('title')
    description = request.form.get('description')
    material_type = request.form.get('material_type')  # 'file' hoặc 'video'
    grade = request.form.get('grade')  # '10', '11', hoặc '12'
    
    materials = load_materials_data()
    
    # Đảm bảo materials là list
    if not isinstance(materials, list):
        materials = []
    
    if material_type == 'file':
        file = request.files.get('material_file')
        
        if file and file.filename:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            materials.append({
                'id': len(materials) + 1,
                'title': title,
                'description': description,
                'type': 'file',
                'filename': filename,
                'grade': grade,
                'uploaded_by': session['exam_username'],
                'uploaded_at': datetime.now(vn_timezone).strftime("%Y-%m-%d %H:%M:%S")
            })
    
    elif material_type == 'video':
        video_link = request.form.get('video_link', '').strip()
        
        if video_link:
            # Xử lý link Google Drive để lấy ID
            drive_id = extract_drive_id(video_link)
            
            materials.append({
                'id': len(materials) + 1,
                'title': title,
                'description': description,
                'type': 'video',
                'video_link': video_link,
                'drive_id': drive_id,
                'grade': grade,
                'uploaded_by': session['exam_username'],
                'uploaded_at': datetime.now(vn_timezone).strftime("%Y-%m-%d %H:%M:%S")
            })
    
    save_materials_data(materials)
    return redirect(url_for('dashboard_teacher'))

# Hàm trích xuất ID từ link Google Drive
def extract_drive_id(link):
    """
    Trích xuất ID từ các dạng link Google Drive:
    - https://drive.google.com/file/d/FILE_ID/view
    - https://drive.google.com/open?id=FILE_ID
    """
    import re
    
    # Dạng /file/d/FILE_ID/
    match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', link)
    if match:
        return match.group(1)
    
    # Dạng ?id=FILE_ID
    match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', link)
    if match:
        return match.group(1)
    
    # Nếu không match, trả về link gốc
    return link

# Route xem tài liệu theo lớp
@app.route('/materials/<grade>')
def view_materials_by_grade(grade):
    if 'exam_username' not in session:
        return redirect(url_for('login_exam'))
    
    if grade not in ['10', '11', '12', 'all']:
        return "Lớp không hợp lệ", 400
    
    materials = load_materials_data()
    
    if grade == 'all':
        filtered_materials = materials
    else:
        filtered_materials = [m for m in materials if m.get('grade') == grade]
    
    return render_template('materials_list.html', 
                         materials=filtered_materials, 
                         grade=grade)

# Route xóa tài liệu (chỉ giáo viên)
@app.route('/delete_material/<int:material_id>', methods=['POST'])
def delete_material(material_id):
    if 'exam_username' not in session or session.get('exam_role') != 'teacher':
        return redirect(url_for('login_exam'))
    
    materials = load_materials_data()
    
    # Đảm bảo materials là list
    if not isinstance(materials, list):
        materials = []
    
    # Tìm và xóa tài liệu
    materials = [m for m in materials if m.get('id') != material_id]
    
    # Cập nhật lại ID
    for idx, material in enumerate(materials):
        material['id'] = idx + 1
    
    save_materials_data(materials)
    return redirect(url_for('dashboard_teacher'))


# Route xóa đề thi (chỉ giáo viên)
@app.route('/delete_exam/<exam_id>', methods=['POST'])
def delete_exam(exam_id):
    if 'exam_username' not in session or session.get('exam_role') != 'teacher':
        return redirect(url_for('login_exam'))
    
    exams = load_exams_data()
    if exam_id in exams:
        exams.pop(exam_id)
        save_exams_data(exams)
    return redirect(url_for('dashboard_teacher'))

# Cập nhật route dashboard_teacher
@app.route('/dashboard_teacher')
def dashboard_teacher():
    if 'exam_username' not in session or session.get('exam_role') != 'teacher':
        return redirect(url_for('login_exam'))
    
    exams = load_exams_data()
    materials = load_materials_data()
    all_submissions = load_exam_submissions()
    
    # Gắn thêm index gốc cho mỗi submission
    submissions = []
    for i, s in enumerate(all_submissions):
        s_with_index = s.copy()
        s_with_index['original_index'] = i
        submissions.append(s_with_index)
    
    # Phân loại tài liệu theo lớp
    materials_by_grade = {
        '10': [m for m in materials if m.get('grade') == '10'],
        '11': [m for m in materials if m.get('grade') == '11'],
        '12': [m for m in materials if m.get('grade') == '12']
    }

    # load chatbot feedback statistics
    feedback_list = []
    try:
        if os.path.exists(FEEDBACK_FILE):
            with open(FEEDBACK_FILE, 'r', encoding='utf-8') as f:
                feedback_list = json.load(f)
    except Exception:
        feedback_list = []

    # compute counts per bot and rating
    feedback_stats = {}
    for entry in feedback_list:
        bot = entry.get('bot','unknown')
        rating = entry.get('rating','')
        feedback_stats.setdefault(bot, {})
        feedback_stats[bot].setdefault(rating, 0)
        feedback_stats[bot][rating] += 1

    return render_template('dashboard_teacher.html', 
                         exams=exams, 
                         materials=materials,
                         materials_by_grade=materials_by_grade,
                         submissions=submissions,
                         feedback_stats=feedback_stats)

# Export scores for a given exam to CSV (opened with Excel)
@app.route('/export_scores/<exam_id>')
def export_scores(exam_id):
    if 'exam_username' not in session or session.get('exam_role') != 'teacher':
        return redirect(url_for('login_exam'))
    submissions = load_exam_submissions()
    # filter submissions belonging to this exam
    rows = [s for s in submissions if s.get('exam_id') == exam_id]
    if not rows:
        flash('Không có bài nộp nào cho đề này.', 'warning')
        return redirect(url_for('dashboard_teacher'))
    # create Excel workbook in memory
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Điểm"
    # header row
    ws.append(['Mã học sinh', 'Tên đầy đủ', 'Trường', 'Khối', 'Lớp', 'Điểm', 'Tên đăng nhập'])
    students = load_exam_students()
    for s in rows:
        user = s.get('student', '')
        student_info = students.get(user, {})
        fullname = student_info.get('fullname', '')
        student_id = student_info.get('student_id', 'N/A')
        school = student_info.get('school', 'N/A')
        grade = student_info.get('grade_level', 'N/A')
        class_name = student_info.get('class_name', 'N/A')
        score = s.get('score', '')
        ws.append([student_id, fullname, school, grade, class_name, score, user])
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    exams = load_exams_data()
    title = exams.get(exam_id, {}).get('title', exam_id)
    fname = f"scores_{exam_id}.xlsx"
    return send_file(out, as_attachment=True,
                     download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# Cập nhật route dashboard_student
@app.route('/dashboard_student')
def dashboard_student():
    if 'exam_username' not in session or session.get('exam_role') != 'student':
        return redirect(url_for('login_exam'))
    
    username = session['exam_username']
    exams = load_exams_data()
    materials = load_materials_data()
    all_submissions = load_exam_submissions()
    
    # Lấy bài của mình kèm theo index gốc
    my_submissions = []
    for i, s in enumerate(all_submissions):
        if s.get('student') == username:
            s_with_index = s.copy()
            s_with_index['original_index'] = i
            my_submissions.append(s_with_index)
    
    # Phân loại tài liệu theo lớp
    materials_by_grade = {
        '10': [m for m in materials if m.get('grade') == '10'],
        '11': [m for m in materials if m.get('grade') == '11'],
        '12': [m for m in materials if m.get('grade') == '12']
    }
    
    return render_template('dashboard_student.html', 
                         exams=exams, 
                         materials=materials,
                         materials_by_grade=materials_by_grade,
                         my_submissions=my_submissions)
#######################

@app.route('/create_exam', methods=['GET', 'POST'])
def create_exam():
    if 'exam_username' not in session or session.get('exam_role') != 'teacher':
        return redirect(url_for('login_exam'))
    
    if request.method == 'POST':
        action = request.form.get('action', 'create')
        exam_type = request.form.get('exam_type')
        grade = request.form.get('grade')
        general_grading_criteria = request.form.get('general_grading_criteria', '').strip()
        exam_title = request.form.get('title')
        exam_duration = int(request.form.get('duration', 60))
        
        # ========================
        # BƯỚC 1: TẠO ĐỀ TỪ AI
        # ========================
        if action == 'create' and exam_type in ['multiple_choice', 'mixed']:
            word_file = request.files.get('word_file')
            if not word_file or not word_file.filename.endswith('.docx'):
                flash("❌ Vui lòng chọn file Word (.docx)", "error")
                return render_template('create_exam.html')
            
            # Lưu temp file
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(word_file.filename))
            word_file.save(file_path)
            text_content = read_word_file(file_path)
            
            if not text_content:
                flash("❌ Không thể đọc file Word. Vui lòng kiểm tra file.", "error")
                return render_template('create_exam.html')
            
            # Thuật toán bóc tách 100% nội dung (Không giới hạn số câu)
            exam_data = generate_exam_from_text(text_content)
            
            if not exam_data:
                flash("❌ AI không thể tạo đề thi. Vui lòng thử lại.", "error")
                return render_template('create_exam.html')
            
            # Lấy số lượng thực tế sau bóc tách
            mc_count = len(exam_data.get('multiple_choice', []))
            tf_count = len(exam_data.get('true_false', []))
            essay_count = len(exam_data.get('essay', []))
            is_valid = (mc_count + tf_count + essay_count) > 0
            error_msg = "" if is_valid else "Không tìm thấy câu hỏi nào trong file."
            
            # tạo token và lưu vào TEMP_EXAMS thay vì session
            import uuid
            token = str(uuid.uuid4())
            TEMP_EXAMS[token] = {
                'type': exam_type,
                'title': exam_title,
                'duration': exam_duration,
                'grade': grade,
                'questions': exam_data,
                'is_valid': is_valid,
                'error_msg': error_msg,
                'mc_count': mc_count,
                'tf_count': tf_count,
                'essay_count': essay_count,
                'required_mc': mc_count,
                'required_tf': tf_count,
                'required_essay': essay_count,
                'general_grading_criteria': general_grading_criteria
            }
            
            # redirect to preview with token param
            return redirect(url_for('preview_exam', token=token))
        
        # ========================
        # BƯỚC 3: HÀM CONFIRM LƯU
        # ========================
        elif action == 'save':
            token = request.form.get('token')
            if not token or token not in TEMP_EXAMS:
                flash("❌ Dữ liệu tạm thời không hợp lệ. Vui lòng tạo lại đề.", "error")
                return redirect(url_for('create_exam'))
            temp_data = TEMP_EXAMS.pop(token)
            exam_id = datetime.now(vn_timezone).strftime("%Y%m%d%H%M%S")
            
            exams = load_exams_data()
            exams[exam_id] = {
                'id': exam_id,
                'title': temp_data['title'],
                'type': temp_data['type'],
                'duration': temp_data['duration'],
                'created_by': session['exam_username'],
                'created_at': datetime.now(vn_timezone).strftime("%Y-%m-%d %H:%M:%S"),
                'questions': temp_data['questions'],
                'total_score': 10,
                'grade': temp_data['grade'],
                'tf_grading_method': 'deduction',
                'general_grading_criteria': temp_data['general_grading_criteria']
            }
            save_exams_data(exams)
            
            flash(f"✅ Tạo đề thi thành công! ({temp_data['mc_count']} trắc nghiệm + {temp_data['tf_count']} đúng/sai)", "success")
            return redirect(url_for('dashboard_teacher'))
        
        # Đề thi pure essay (không cần AI)
        elif exam_type == 'essay':
            essay_question = request.form.get('essay_question')
            grading_criteria = request.form.get('grading_criteria')
            
            exam_id = datetime.now(vn_timezone).strftime("%Y%m%d%H%M%S")
            exams = load_exams_data()
            exams[exam_id] = {
                'id': exam_id,
                'title': exam_title,
                'type': 'essay',
                'duration': exam_duration,
                'created_by': session['exam_username'],
                'created_at': datetime.now(vn_timezone).strftime("%Y-%m-%d %H:%M:%S"),
                'essay_question': essay_question,
                'grading_criteria': grading_criteria,
                'total_score': 10,
                'grade': grade,
                'general_grading_criteria': general_grading_criteria
            }
            save_exams_data(exams)
            
            flash("✅ Tạo đề thi thành công!", "success")
            return redirect(url_for('dashboard_teacher'))
    
    return render_template('create_exam.html')


# ========================
# ROUTE XEM TRƯỚC ĐỀ THI
# ========================
@app.route('/preview_exam')
def preview_exam():
    """Xem trước đề thi được tạo từ AI.
    Yêu cầu param `token` được trả về sau khi generate.
    """
    if 'exam_username' not in session or session.get('exam_role') != 'teacher':
        return redirect(url_for('login_exam'))
    
    token = request.args.get('token')
    if not token or token not in TEMP_EXAMS:
        flash("❌ Không có dữ liệu đề thi. Vui lòng tạo lại.", "error")
        return redirect(url_for('create_exam'))
    
    temp_data = TEMP_EXAMS[token]
    
    # nếu giáo viên nhấn lưu thì xử lý ở route khác, nhưng có thể reuse token
    return render_template('preview_exam.html', 
                         exam=temp_data,
                         is_valid=temp_data['is_valid'],
                         error_msg=temp_data['error_msg'],
                         token=token)

############## sửa
def analyze_wrong_answers(exam, mc_wrong):
    """AI đưa ra kế hoạch ôn tập và chủ đề liên quan"""
    try:
        if not mc_wrong:
            return None
        
        errors_text = ""
        for idx, item in enumerate(mc_wrong):
            q = item['question']
            errors_text += f"\nCau {idx + 1}: {q['question']}\n"
            errors_text += f"  Dap an dung: {q['answer']}\n"
            errors_text += f"  Hoc sinh chon: {item['user_answer']}\n"
        
        prompt = f"""
Ban la giao vien lich su, hay phan tich cac loi sai cua hoc sinh trong de thi trac nghiem.

Cac loi sai:
{errors_text}

Hay dua ra:
1. KE HOACH ON TAP: Lap so do tu duy hoac bang bieu tong hop cac su kien lich su lon, bao gom: ten su kien, thoi gian, dia diem, nhan vat lanh dao, nguyen nhan (sau xa, truc tiep), dien bien chinh, ket qua, y nghia, tinh chat, va han che. Danh thoi gian on tap va phan biet ro rang cac khai niem de nham lan. Tap trung vao chi tiet: Luyen tap ghi nho cac chi tiet nhu nien dai, ten goi cu the cua cac khoi lien minh, quoc gia lien quan den su kien. Doc hieu sau: Doc ky cac cau hoi trac nghiem, phan tich tung lua chon de tim ra dap an toi uu nhat, tranh chon dap an dung nhung chua du hoac chua phai la 'nhat'. Luyen tap giai de: Thuc hanh lam nhieu bai tap trac nghiem, sau do tu cham va phan tich ly luong cac loi sai, ghi lai ly do sai de tranh lap lai.

2. CAC CHU DE LIEN QUAN: Chu nghia de quoc va su phan chia the gioi cuoi the ky XIX - dau the ky XX. Chien tranh the gioi thu nhat (1914-1918): Nguyen nhan, dien bien, ket qua, tinh chat, tac dong. Cach mang thang Muoi Nga (1917) va cong cuoc xay dung chu nghia xa hoi o Lien Xo nhung nam 1920-1930. Phong trao giai phong dan toc o chau A, chau Phi, My Latinh dau the ky XX (dien hinh: Duy tan Minh Tri o Nhat Ban, Cach mang Tan Hoi o Trung Quoc, phong trao o An Do, Dong Nam A).

Tra ve JSON (KHONG DUNG # VA **):
{{
  "ke_hoach_on_tap": "<Ke hoach on tap cu the>",
  "cac_chu_de_lien_quan": "<Cac chu de can on them>"
}}

Chi tra ve JSON.
"""
        
        response = get_model().generate_content(prompt)
        text = response.text.strip()
        text = text.replace('```json', '').replace('```', '').strip()
        result = json.loads(text)
        return result
        
    except Exception as e:
        print(f"Loi phan tich: {e}")
        return None


def analyze_truefalse_errors(exam, tf_errors):
    """AI đưa ra kế hoạch ôn tập và chủ đề liên quan cho câu đúng/sai"""
    try:
        if not tf_errors:
            return None
        
        errors_text = ""
        for idx, item in enumerate(tf_errors):
            tf = item['question']
            errors_text += f"\nCau {idx + 1}: {tf['question']}\n"
            for j, stmt in enumerate(tf['statements']):
                correct = "DUNG" if tf['answers'][j] else "SAI"
                user = "DUNG" if item['user_answers'][j] else "SAI"
                if tf['answers'][j] != item['user_answers'][j]:
                    errors_text += f"  Y {j+1}: {stmt}\n"
                    errors_text += f"    Dap an dung: {correct}\n"
                    errors_text += f"    Hoc sinh chon: {user}\n"
        
        prompt = f"""
Ban la giao vien lich su, hay phan tich cac loi sai cua hoc sinh trong cau dung/sai.

Cac loi sai:
{errors_text}

Hay dua ra:
1. KE HOACH ON TAP: Lap so do tu duy hoac bang bieu tong hop cac su kien lich su lon, bao gom: ten su kien, thoi gian, dia diem, nhan vat lanh dao, nguyen nhan (sau xa, truc tiep), dien bien chinh, ket qua, y nghia, tinh chat, va han che. Danh thoi gian on tap va phan biet ro rang cac khai niem de nham lan. Tap trung vao chi tiet: Luyen tap ghi nho cac chi tiet nhu nien dai, ten goi cu the cua cac khoi lien minh, quoc gia lien quan den su kien. Doc hieu sau: Doc ky cac cau hoi trac nghiem, phan tich tung lua chon de tim ra dap an toi uu nhat, tranh chon dap an dung nhung chua du hoac chua phai la 'nhat'. Luyen tap giai de: Thuc hanh lam nhieu bai tap trac nghiem, sau do tu cham va phan tich ly luong cac loi sai, ghi lai ly do sai de tranh lap lai.

2. CAC CHU DE LIEN QUAN: Chu nghia de quoc va su phan chia the gioi cuoi the ky XIX - dau the ky XX. Chien tranh the gioi thu nhat (1914-1918): Nguyen nhan, dien bien, ket qua, tinh chat, tac dong. Cach mang thang Muoi Nga (1917) va cong cuoc xay dung chu nghia xa hoi o Lien Xo nhung nam 1920-1930. Phong trao giai phong dan toc o chau A, chau Phi, My Latinh dau the ky XX (dien hinh: Duy tan Minh Tri o Nhat Ban, Cach mang Tan Hoi o Trung Quoc, phong trao o An Do, Dong Nam A).

Tra ve JSON (KHONG DUNG # VA **):
{{
  "ke_hoach_on_tap": "<Ke hoach on tap cu the>",
  "cac_chu_de_lien_quan": "<Cac chu de can on them>"
}}

Chi tra ve JSON.
"""
        
        response = get_model().generate_content(prompt)
        text = response.text.strip()
        text = text.replace('```json', '').replace('```', '').strip()
        result = json.loads(text)
        return result
        
    except Exception as e:
        print(f"Loi phan tich TF: {e}")
        return None

# CẬP NHẬT ROUTE do_exam
# ROUTE LÀM BÀI THI
@app.route('/do_exam/<exam_id>', methods=['GET', 'POST'])
def do_exam(exam_id):
    if 'exam_username' not in session or session.get('exam_role') != 'student':
        return redirect(url_for('login_exam'))
    
    exams = load_exams_data()
    exam = exams.get(exam_id)
    
    if not exam:
        return "Khong tim thay de thi", 404
    
    if request.method == 'POST':
        username = session['exam_username']
        submissions = load_exam_submissions()
        
        if not isinstance(submissions, list):
            submissions = []
        
        # ============================================
        # ĐỀ THI TRẮC NGHIỆM HOẶC HỖN HỢP
        # ============================================
        if exam['type'] == 'multiple_choice' or exam['type'] == 'mixed':
            score = 0
            answers = {}
            
            mc_questions = exam['questions'].get('multiple_choice', [])
            tf_questions = exam['questions'].get('true_false', [])
            essay_questions = exam['questions'].get('essay', [])
            
            # DANH SÁCH CÂU SAI
            mc_wrong = []
            tf_errors = []
            
            # PHÂN BỔ ĐIỂM
            if exam['type'] == 'mixed':
                mc_total = 4
                tf_total = 3
                essay_total = 3
            else:
                mc_total = 6
                tf_total = 4
                essay_total = 0
            
            # ============================================
            # CHẤM TRẮC NGHIỆM
            # ============================================
            if mc_questions:
                score_per_mc = mc_total / len(mc_questions)
                for i, q in enumerate(mc_questions):
                    user_answer = request.form.get(f'mc_{i}')
                    answers[f'mc_{i}'] = user_answer
                    if user_answer == q['answer']:
                        score += score_per_mc
                    else:
                        mc_wrong.append({
                            'question': q,
                            'user_answer': user_answer if user_answer else 'Khong tra loi'
                        })
            
            # ============================================
            # CHẤM ĐÚNG/SAI
            # ============================================
            grading_method = exam.get('tf_grading_method', 'deduction')
            
            if tf_questions:
                score_per_tf = tf_total / len(tf_questions)
                
                for i, tf in enumerate(tf_questions):
                    user_answers = []
                    correct_count = 0
                    wrong_count = 0
                    has_error = False
                    
                    for j in range(4):
                        user_tf = request.form.get(f'tf_{i}_{j}') == 'true'
                        user_answers.append(user_tf)
                        if user_tf == tf['answers'][j]:
                            correct_count += 1
                        else:
                            wrong_count += 1
                            has_error = True
                    
                    answers[f'tf_{i}'] = user_answers
                    
                    if has_error:
                        tf_errors.append({
                            'question': tf,
                            'user_answers': user_answers
                        })
                    
                    # CHẤM ĐIỂM THEO PHƯƠNG PHÁP
                    if grading_method == 'deduction':
                        if wrong_count == 0:
                            score += score_per_tf
                        elif wrong_count == 1:
                            score += score_per_tf * 0.75  # ⭐ FIXED: Trừ 25%
                        elif wrong_count == 2:
                            score += score_per_tf * 0.5   # ⭐ FIXED: Trừ 50%
                        elif wrong_count == 3:
                            score += score_per_tf * 0.25  # ⭐ FIXED: Trừ 75%
                        # Sai 4 ý = 0 điểm
                    else:  # proportional
                        score += (correct_count / 4) * score_per_tf  # ⭐ FIXED
            
            # ============================================
            # PHÂN TÍCH AI CHO CÂU SAI (TRẮC NGHIỆM & ĐÚNG/SAI)
            # ============================================
            mc_feedback = None
            tf_feedback = None
            
            if mc_wrong:
                mc_feedback = analyze_wrong_answers(exam, mc_wrong)
                if not mc_feedback:
                    mc_feedback = {
                        'ke_hoach_on_tap': 'Hệ thống AI tạm thời không khả dụng. Vui lòng liên hệ giáo viên.',
                        'cac_chu_de_lien_quan': ''
                    }
            
            if tf_errors:
                tf_feedback = analyze_truefalse_errors(exam, tf_errors)
                if not tf_feedback:
                    tf_feedback = {
                        'ke_hoach_on_tap': 'Hệ thống AI tạm thời không khả dụng. Vui lòng liên hệ giáo viên.',
                        'cac_chu_de_lien_quan': ''
                    }
            
            # ============================================
            # XỬ LÝ TỰ LUẬN - CHẤM AI NGAY
            # ============================================
            essay_ai_feedback = []
            if essay_questions and exam['type'] == 'mixed':
                essay_answers = []
                total_essay_score = 0
                
                # ⭐ TÍNH ĐIỂM TỐI ĐA CHO MỖI CÂU TỰ LUẬN
                score_per_essay = essay_total / len(essay_questions)
                
                for i, eq in enumerate(essay_questions):
                    essay_answer = request.form.get(f'essay_{i}', '').strip()
                    image_file = request.files.get(f'essay_image_{i}')
                    
                    image_path = None
                    if image_file and image_file.filename:
                        import time
                        timestamp = int(time.time())
                        image_filename = secure_filename(f"{exam_id}_{username}_{i}_{timestamp}_{image_file.filename}")
                        image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
                        image_file.save(image_path)
                    
                    essay_answers.append({
                        'text': essay_answer,
                        'image_path': image_path
                    })
                    
                    # ⭐ TRUYỀN max_score VÀO HÀM AI
                    ai_result = auto_grade_mixed_essay_with_ai(
                        eq['question'],
                        eq.get('grading_criteria', 'Cham theo noi dung'),
                        essay_answer,
                        image_path,
                        max_score=score_per_essay  # ⭐ ĐIỂM TỐI ĐA CHO CÂU NÀY
                    )
                    
                    if ai_result:
                        essay_ai_feedback.append(ai_result)
                        total_essay_score += ai_result['score']
                    else:
                        essay_ai_feedback.append({
                            'score': 0,
                            'max_score': score_per_essay,
                            'analysis': 'AI không thể chấm được bài',
                            'suggestions': 'Cần giáo viên xem xét và chấm lại'
                        })
                
                answers['essay'] = essay_answers
                score += total_essay_score
            
            # ============================================
            # LƯU BÀI NỘP
            # ============================================
            submission = {
                'exam_id': exam_id,
                'student': username,
                'submitted_at': datetime.now(vn_timezone).strftime("%Y-%m-%d %H:%M:%S"),
                'answers': answers,
                'score': round(score, 2),
                'type': exam['type'],
                'ai_graded': True,
                'essay_ai_feedback': essay_ai_feedback if essay_questions else None,
                'mc_ai_feedback': mc_feedback,
                'tf_ai_feedback': tf_feedback,
                'teacher_adjusted': False,
                'teacher_score': None,
                'teacher_comment': None
            }
        
        # ============================================
        # ĐỀ THI TỰ LUẬN THUẦN
        # ============================================
        elif exam['type'] == 'essay':
            essay_answer = request.form.get('essay_answer', '').strip()
            image_file = request.files.get('essay_image')
            
            image_path = None
            if image_file and image_file.filename:
                import time
                timestamp = int(time.time())
                image_filename = secure_filename(f"{exam_id}_{username}_{timestamp}_{image_file.filename}")
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
                image_file.save(image_path)
            
            ai_feedback = auto_grade_essay_with_ai(exam, essay_answer, image_path)
            
            submission = {
                'exam_id': exam_id,
                'student': username,
                'submitted_at': datetime.now(vn_timezone).strftime("%Y-%m-%d %H:%M:%S"),
                'essay_answer': essay_answer,
                'image_path': image_path,
                'score': ai_feedback['score'] if ai_feedback else None,
                'type': 'essay',
                'ai_graded': True,
                'ai_feedback': ai_feedback,
                'teacher_adjusted': False,
                'teacher_score': None,
                'teacher_comment': None
            }
        
        # ============================================
        # LƯU VÀ CHUYỂN HƯỚNG
        # ============================================
        submissions.append(submission)
        save_exam_submissions(submissions)
        
        return redirect(url_for('view_submission', submission_index=len(submissions)-1))
    
    # GET REQUEST - HIỂN THỊ ĐỀ THI
    return render_template('do_exam.html', exam=exam, exam_id=exam_id)

@app.route('/adjust_score/<int:submission_index>', methods=['POST'])
def adjust_score(submission_index):
    """Giáo viên điều chỉnh điểm AI"""
    if 'exam_username' not in session or session.get('exam_role') != 'teacher':
        flash("Bạn cần đăng nhập với quyền giáo viên", "error")
        return redirect(url_for('login_exam'))
    
    submissions = load_exam_submissions()
    
    if submission_index >= len(submissions):
        flash("Không tìm thấy bài nộp", "error")
        return redirect(url_for('dashboard_teacher'))
    
    submission = submissions[submission_index]
    
    # Lấy điểm và nhận xét từ giáo viên
    teacher_score = request.form.get('teacher_score')
    teacher_comment = request.form.get('teacher_comment', '').strip()
    
    # LOGGING
    print(f"[ADJUST SCORE] Index: {submission_index}")
    print(f"[ADJUST SCORE] Submission type: {submission.get('type')}")
    print(f"[ADJUST SCORE] AI score: {submission.get('score')}")
    print(f"[ADJUST SCORE] New teacher score: {teacher_score}")
    print(f"[ADJUST SCORE] Comment: {teacher_comment[:50] if teacher_comment else 'None'}")
    
    if teacher_score:
        # LƯU ĐIỂM AI GỐC (nếu chưa có)
        if 'original_ai_score' not in submissions[submission_index]:
            submissions[submission_index]['original_ai_score'] = submission.get('score')
        
        # CẬP NHẬT ĐIỂM VÀ NHẬN XÉT
        submissions[submission_index]['teacher_score'] = float(teacher_score)
        submissions[submission_index]['teacher_adjusted'] = True
        submissions[submission_index]['teacher_comment'] = teacher_comment
        submissions[submission_index]['score'] = float(teacher_score)  # Điểm chính thức
        submissions[submission_index]['adjusted_at'] = datetime.now(vn_timezone).strftime("%Y-%m-%d %H:%M:%S")
        
        # LƯU VÀO FILE
        save_exam_submissions(submissions)
        
        print(f"[ADJUST SCORE] ✓ Saved successfully!")
        print(f"[ADJUST SCORE] Final score: {submissions[submission_index]['score']}")
        
        flash(f"✓ Đã điều chỉnh điểm thành công! Điểm mới: {teacher_score}/10", "success")
    else:
        flash("⚠️ Vui lòng nhập điểm hợp lệ", "warning")
    
    # REDIRECT VỀ DASHBOARD_TEACHER THAY VÌ VIEW_SUBMISSION
    # Tránh vòng lặp redirect hoặc cache
    return redirect(url_for('dashboard_teacher'))

####

@app.route('/download_material/<filename>')
def download_material(filename):
    if 'exam_username' not in session:
        return redirect(url_for('login_exam'))
    
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/exam_statistics')
def exam_statistics():
    if 'exam_username' not in session or session.get('exam_role') != 'teacher':
        return redirect(url_for('login_exam'))
    
    submissions = load_exam_submissions()
    students = load_exam_students()
    exams = load_exams_data()
    
    stats = {}
    for student_username in students.keys():
        student_submissions = [s for s in submissions if s['student'] == student_username]
        
        total_exams = len(exams)
        completed_exams = len(student_submissions)
        completion_rate = (completed_exams / total_exams * 100) if total_exams > 0 else 0
        
        scores = [s['score'] for s in student_submissions if s['score'] is not None]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        stats[student_username] = {
            'fullname': students[student_username]['fullname'],
            'completed': completed_exams,
            'total': total_exams,
            'completion_rate': round(completion_rate, 1),
            'avg_score': round(avg_score, 2),
            'submissions': student_submissions
        }
    
    return render_template('exam_statistics.html', stats=stats, exams=exams)

############
# THAY THẾ ROUTE adjust_score VÀ view_submission HIỆN TẠI
@app.route('/view_submission/<int:submission_index>')
def view_submission(submission_index):
    if 'exam_username' not in session:
        return redirect(url_for('login_exam'))
    
    submissions = load_exam_submissions()
    
    if submission_index >= len(submissions):
        flash("Không tìm thấy bài nộp", "error")
        return redirect(url_for('dashboard_teacher'))
    
    submission = submissions[submission_index]
    
    # Kiểm tra quyền xem
    if session.get('exam_role') == 'student' and submission['student'] != session['exam_username']:
        flash("Bạn không có quyền xem bài này", "error")
        return redirect(url_for('dashboard_student'))
    
    exams = load_exams_data()
    exam = exams.get(submission['exam_id'])
    
    if not exam:
        flash("Không tìm thấy đề thi", "error")
        return redirect(url_for('dashboard_teacher'))
    
    # ========== CHUẨN HÓA CẤU TRÚC EXAM ==========
    print(f"[DEBUG] exam type: {type(exam)}")
    print(f"[DEBUG] exam keys: {exam.keys()}")
    print(f"[DEBUG] exam data: {exam}")
    
    # Nếu exam không có 'questions', tạo từ cấu trúc cũ
    if 'questions' not in exam:
        print("[INFO] Converting old exam structure to new format")
        
        # Đây là đề tự luận thuần
        if exam.get('type') == 'essay' and 'essay_question' in exam:
            exam['questions'] = {
                'multiple_choice': [],
                'true_false': [],
                'essay': [{
                    'question': exam['essay_question']
                }]
            }
        # Đây là đề trắc nghiệm/hỗn hợp cũ (nếu có)
        else:
            exam['questions'] = {
                'multiple_choice': exam.get('multiple_choice', []),
                'true_false': exam.get('true_false', []),
                'essay': exam.get('essay', [])
            }
    
    # Đảm bảo các sub-keys tồn tại
    if 'multiple_choice' not in exam['questions']:
        exam['questions']['multiple_choice'] = []
    if 'true_false' not in exam['questions']:
        exam['questions']['true_false'] = []
    if 'essay' not in exam['questions']:
        exam['questions']['essay'] = []
    
    # LƯU ĐIỂM AI GỐC (nếu chưa có)
    if 'original_ai_score' not in submission:
        submission['original_ai_score'] = submission.get('score')
    
    # LOGGING
    print(f"[VIEW SUBMISSION] Index: {submission_index}")
    print(f"[VIEW SUBMISSION] Type: {submission.get('type')}")
    print(f"[VIEW SUBMISSION] Score: {submission.get('score')}")
    print(f"[VIEW SUBMISSION] Teacher adjusted: {submission.get('teacher_adjusted')}")
    print(f"[VIEW SUBMISSION] Questions structure: MC={len(exam['questions']['multiple_choice'])}, TF={len(exam['questions']['true_false'])}, Essay={len(exam['questions']['essay'])}")
    
    return render_template('view_submission.html', 
                         submission=submission, 
                         exam=exam,
                         submission_index=submission_index)

##########################

@app.route('/logout_exam')
def logout_exam():
    session.pop('exam_username', None)
    session.pop('exam_role', None)
    return redirect(url_for('login_exam'))
#####
@app.template_filter('enumerate')
def enumerate_filter(iterable, start=0):
    return enumerate(iterable, start)
###
if __name__ == '__main__':
    app.run(debug=True, threaded=True)
