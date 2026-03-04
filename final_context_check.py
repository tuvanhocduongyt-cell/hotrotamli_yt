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
    parts_raw = re.split(r'(?i)\n\s*(?:Phần|PHẦN)\s+([I|V|X|L|C]+|\d+)[\s\.\:]', "\n" + main_text)
    
    processed_mc = []
    processed_tf = []
    
    current_sticky_context = ""
    sticky_until = 0
    context_pattern = r'(?i)(Đọc\s+đoạn\s+tư\s+liệu\s+.*?trả\s+lời\s+.*?(?:câu\s+|câu\s+hỏi\s+)(?:từ\s+)?(\d+)\s+đến\s+(\d+).*)'

    work_list = []
    if parts_raw[0].strip():
        work_list.append(("I", parts_raw[0].strip()))
    for i in range(1, len(parts_raw), 2):
        work_list.append((parts_raw[i].upper(), parts_raw[i+1].strip()))

    for part_label, part_content in work_list:
        raw_qs = re.split(r'(?i)\n\s*Câu\s+(\d+)[\.:]', "\n" + part_content)
        
        # initial context
        initial_context_match = re.search(context_pattern, raw_qs[0], re.DOTALL)
        if initial_context_match:
            current_sticky_context = initial_context_match.group(1).strip()
            sticky_until = int(initial_context_match.group(3))

        for j in range(1, len(raw_qs), 2):
            q_num = int(raw_qs[j])
            block = raw_qs[j+1].strip()
            if not block: continue

            # handle context
            context_match = re.search(context_pattern, block, re.DOTALL)
            if context_match:
                next_context = context_match.group(1).strip()
                next_until = int(context_match.group(3))
                block = block[:context_match.start()].strip()
                current_sticky_context = next_context
                sticky_until = next_until

            prefix = f"({current_sticky_context})\n\n" if (current_sticky_context and q_num <= sticky_until) else ""
            if q_num > sticky_until: current_sticky_context = "" # Reset

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

            if q_type == "MCQ" and q_num in [22, 23, 24]:
                processed_mc.append({
                    "num": q_num,
                    "has_context": "Đọc đoạn tư liệu" in prefix
                })
            
    return {"mc_context_check": processed_mc}

if __name__ == "__main__":
    with open("mau_de_dump.txt", "r", encoding="utf-8") as f:
        text = f.read()
    result = parse_docx_strictly(text)
    print(json.dumps(result, indent=2))
