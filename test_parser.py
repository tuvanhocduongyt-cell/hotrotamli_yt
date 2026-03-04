import re
import sys

# Đảm bảo output có thể in được tiếng Việt
sys.stdout.reconfigure(encoding='utf-8')

def parse_exam_text(text):
    # Split into sections (Part I, Part II etc.)
    # For simplicity, we can just split by "Câu \d+"
    
    questions = re.split(r'Câu \d+[\.:]', text)
    processed_questions = []
    
    for q_text in questions[1:]:
        q_text = q_text.strip()
        if not q_text: continue
        
        # Check if it's Multiple Choice (contains A., B., C., D.)
        if all(re.search(fr'{letter}[\.\)]', q_text) for letter in ['A', 'B', 'C', 'D']):
            # It's MC
            match = re.split(r'[A-D][\.\)]', q_text)
            q_body = match[0].strip()
            options = [opt.strip() for opt in match[1:] if opt.strip()]
            
            processed_questions.append({
                'type': 'MC',
                'question': q_body,
                'options': options
            })
        
        # Check if it's True/False (contains a), b), c), d))
        elif all(re.search(fr'{letter}[\)\.]', q_text) for letter in ['a', 'b', 'c', 'd']):
            # It's TF
            match = re.split(r'[a-d][\.\)]', q_text)
            q_body = match[0].strip()
            statements = [stmt.strip() for stmt in match[1:] if stmt.strip()]
            
            processed_questions.append({
                'type': 'TF',
                'question': q_body,
                'statements': statements
            })
            
    return processed_questions

# Sample test from Step 234/239
sample_text = """
Câu 22. Tháng 6 năm 1925, Nguyễn Ái Quốc thành lập tổ chức cách mạng nào tại Quảng Châu (Trung Quốc)?
	A. Hội Việt Nam Cách mạng Thanh niên.	B. Cộng sản đoàn.
	C. Hội Liên hiệp thuộc địa.	D. Đảng Cộng Sản Việt Nam.

Câu 1. Cho đoạn tư liệu sau đây:
“Ngày 5-6-1911, trên con tàu Admiral Latouche-Tréville, từ cảng Sài Gòn, Nguyễn Tất Thành đã rời Tổ quốc, bắt đầu cuộc hành trình tìm con đường giải phóng dân tộc, giải phóng đất nước. Trên suốt chặng đường bôn ba, gian khổ ấy, chàng thanh niên Việt Nam yêu nước Nguyễn Tất Thành, nhà hoạt động quốc tế xuất sắc Nguyễn Ái Quốc đã đến với chủ nghĩa Mác - Lê-nin, tìm ra con đường giải phóng cho dân tộc. Người đã rút ra kết luận: “Muốn cứu nước và giải phóng dân tộc không có con đường nào khác con đường cách mạng vô sản”. Tiếp thu và vận dụng sáng tạo chủ nghĩa Mác - Lê-nin, Người đã  dần xây dựng được một hệ thống lý luận về cách mạng giải phóng dân tộc phù hợp với thực tiễn Việt Nam và tích cực chuẩn bị mọi mặt cho sự ra đời của một chính đảng cách mạng ở Việt Nam”.
(Theo báo Tạp chí Cộng sản: https://tapchicongsan.org.vn/phong-su-anh-tap-chi congsan//asset_publisher/RnEb4bkC9pdc/content/chu-tich-ho-chi-minh-vi-dai-song-mai-trong-su-nghiep-cua-chung-ta).
	a) Quá trình chuyển biến tư tưởng của Nguyễn Ái Quốc là: từ chủ nghĩa yêu nước đến với chủ nghĩa Mác – Lê nin.
	b) Điểm tương đồng trong hoạt động cứu nước của Nguyễn Ái Quốc với các bậc tiền bối đi trước đều là nhận thức được hạn chế của khuynh hướng tư sản.
	c) Năm 1911, Nguyễn Ái Quốc bắt đầu thực hiện quá trình ra đi tìm đường cứu nước giải phóng đồng bào.
	d) Nguyễn Ái Quốc đã tiến hành đồng thời việc xây dựng hệ thống lý luận giải phóng dân tộc với việc chuẩn bị điều kiện cho sự thành lập các tổ chức Đảng Cộng sản ở Việt Nam.
"""

results = parse_exam_text(sample_text)
for i, res in enumerate(results):
    print(f"Q{i+1} Type: {res['type']}")
    print(f"Content: {res['question'][:50]}...")
    if res['type'] == 'MC':
        print(f"Options: {len(res['options'])}")
    else:
        print(f"Statements: {len(res['statements'])}")
    print("-" * 20)
