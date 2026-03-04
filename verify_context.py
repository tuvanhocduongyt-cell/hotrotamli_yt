import re
import json

def parse_docx_strictly(text):
    text = text.replace('\r\n', '\n')
    
    # Simple footer split (for test)
    footer_match = re.search(r'(?i)\n\s*ĐÁP\s*ÁN\s*[:\-]', text)
    if footer_match:
        main_text = text[:footer_match.start()].strip()
    else:
        main_text = text

    raw_parts = re.split(r'(?i)Câu\s+(\d+)[\.:]', main_text)
    processed_mc = []
    
    current_sticky_context = ""
    sticky_until = 0

    # Pattern linh hoạt: Đọc... trả lời... câu/câu hỏi (từ) N đến M
    context_pattern = r'(?i)(Đọc\s+đoạn\s+tư\s+liệu\s+.*?trả\s+lời\s+.*?(?:câu\s+|câu\s+hỏi\s+)(?:từ\s+)?(\d+)\s+đến\s+(\d+).*)'

    # Initial context check
    initial_context_match = re.search(context_pattern, raw_parts[0], re.DOTALL)
    if initial_context_match:
        current_sticky_context = initial_context_match.group(1).strip()
        sticky_until = int(initial_context_match.group(3))

    for i in range(1, len(raw_parts), 2):
        q_num = int(raw_parts[i])
        block = raw_parts[i+1].strip()
        if not block: continue

        # Context detection in middle of text
        context_match = re.search(context_pattern, block, re.DOTALL)
        if context_match:
            next_context = context_match.group(1).strip()
            next_until = int(context_match.group(3))
            block = block[:context_match.start()].strip()
            current_sticky_context = next_context
            sticky_until = next_until

        if q_num <= sticky_until:
            prefix = f"({current_sticky_context})\n\n" if current_sticky_context else ""
        else:
            prefix = ""
            if q_num > sticky_until:
                current_sticky_context = ""

        if all(re.search(fr'(?i){letter}[\.\)]', block) for letter in ['A', 'B', 'C', 'D']):
            parts = re.split(r'(?i)([A-D][\.\)])', block)
            question_text = prefix + parts[0].strip()
            processed_mc.append({
                "num": q_num, 
                "q": question_text[:200] + "...",
                "has_context": "Đọc đoạn tư liệu" in question_text
            })
            
    return processed_mc

if __name__ == "__main__":
    test_text = """
Đọc đoạn tư liệu sau đây và trả lời các câu hỏi từ 22 đến 24
	“Với thắng lợi của hai cuộc chiến tranh bảo vệ Tổ quốc, Việt Nam đã bảo vệ được chủ quyền dân tộc và toàn vẹn lãnh thổ, tạo điều kiện để tiếp tục sự nghiệp xây dựng chủ nghĩa xã hội trên phạm vi cả nước. Đồng thời, Việt Nam cũng làm tròn nghĩa vụ quốc tế với nhân dân Campuchia và nhân dân Lào, tích cực góp phần bảo vệ độc lập dân tộc và hòa bình ở Đông Dương và Đông Nam Á”
      	 (Trần Đức Cường - CB, Lịch sử Việt Nam, tập 14 từ năm 1975 đến năm 1986, Nxb Khoa học xã hội, Hà Nội, 2017, tr.358)
Câu 22. Thắng lợi trong hai cuộc chiến tranh bảo vệ Tổ quốc của nhân dân Việt Nam (1975-1979) đã góp phần
		A. bảo vệ hòa bình ở Đông Nam Á.			B. xóa đói, giảm nghèo trên cả nước.
		C. xóa bỏ chế độ phân biệt chủng tộc.			D. cổ vũ phong trào chống đế quốc.
Câu 23. Một trong những nhiệm vụ chiến lược của Việt Nam trong giai đoạn 1975-1986 là
		A. khởi nghĩa giành chính quyền.			B. xóa bỏ mọi tàn dư phong kiến.
		C. tiến hành cải cách ruộng đất.			D. đấu tranh bảo vệ Tổ quốc.
Câu 24. Các cuộc chiến tranh bảo vệ Tổ quốc của nhân dân Việt Nam (1975-1986) không có ý nghĩa nào sau đây?
			A. Bảo vệ vững chắc độc lập dân tộc.			B. Duy trì hòa bình trên toàn thế giới.
			C. Khẳng định tinh thần đoàn kết dân tộc.		D. Để lại nhiều bài học kinh nghiệm.
"""
    result = parse_docx_strictly(test_text)
    with open("verify_context_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print("Done dumping to verify_context_result.json")
