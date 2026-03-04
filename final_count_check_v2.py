import re
import json

def parse_docx_strictly(text):
    text = text.replace('\r\n', '\n')
    
    # Global Answer Stubs
    mc_global_answers = {}
    tf_global_answers = {}
    
    # 1. Detect Footer (Answer Key) FIRST
    footer_match = re.search(r'(?i)\n\s*ĐÁP\s*ÁN\s*[:\-]', text)
    if footer_match:
        main_text = text[:footer_match.start()].strip()
    else:
        main_text = text

    # 4. Tách văn bản thành các Phần
    # Pattern: Phần [Số La Mã] hoặc [Số thường] ở đầu dòng
    parts_raw = re.split(r'(?i)\n\s*(?:Phần|PHẦN)\s+([I|V|X|L|C]+|\d+)[\s\.\:]', "\n" + main_text)
    
    processed_mc = []
    processed_tf = []
    
    work_list = []
    if parts_raw[0].strip():
        work_list.append(("I", parts_raw[0].strip()))
    for i in range(1, len(parts_raw), 2):
        work_list.append((parts_raw[i].upper(), parts_raw[i+1].strip()))

    for part_label, part_content in work_list:
        # Tách câu hỏi: Câu X ở ĐẦU DÒNG
        raw_qs = re.split(r'(?i)\n\s*Câu\s+(\d+)[\.:]', "\n" + part_content)
        
        for j in range(1, len(raw_qs), 2):
            q_num = int(raw_qs[j])
            block = raw_qs[j+1].strip()
            if not block: continue

            # PHÂN LOẠI
            has_mc_markers = all(re.search(fr'\n\s*{L}[\.\)]', "\n" + block) for L in ['A', 'B', 'C', 'D'])
            has_tf_markers = all(re.search(fr'\n\s*{l}[\)\.]', "\n" + block) for l in ['a', 'b', 'c', 'd'])

            q_type = "ESSAY"
            if part_label == "I": 
                q_type = "MCQ"
                if has_tf_markers and not has_mc_markers: q_type = "TF"
            elif part_label == "II": 
                q_type = "TF"
                if has_mc_markers and not has_tf_markers: q_type = "MCQ"
            
            if has_mc_markers: q_type = "MCQ"
            elif has_tf_markers: q_type = "TF"

            if q_type == "MCQ":
                processed_mc.append(f"{part_label}-{q_num}")
            elif q_type == "TF":
                processed_tf.append(f"{part_label}-{q_num}")
            
    return {"mc": processed_mc, "tf": processed_tf}

if __name__ == "__main__":
    with open("mau_de_dump.txt", "r", encoding="utf-8") as f:
        text = f.read()
    result = parse_docx_strictly(text)
    print(json.dumps(result, indent=2))
