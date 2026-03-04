import re
import json

def parse_docx_strictly(text):
    text = text.replace('\r\n', '\n')
    
    # 1. Detect Footer (Answer Key) FIRST to stay away from it
    # file mau_de.docx uses "ĐÁP ÁN:PHẦN I:"
    footer_match = re.search(r'(?i)\n\s*ĐÁP\s*ÁN\s*[:\-]', text)
    if footer_match:
        main_text = text[:footer_match.start()].strip()
    else:
        main_text = text

    # 2. Split by "Câu [Số]"
    # Use capturing group to keep the number
    raw_parts = re.split(r'(?i)Câu\s+(\d+)[\.:]', main_text)
    
    # Check if we got any parts
    print(f"Total raw_parts: {len(raw_parts)}")
    
    processed_mc = []
    processed_tf = []
    
    context_pattern = r'(?i)(Đọc\s+đoạn\s+tư\s+liệu\s+.*?trả\s+lời\s+.*?(?:câu\s+|câu\s+hỏi\s+)(?:từ\s+)?(\d+)\s+đến\s+(\d+).*)'
    current_sticky_context = ""
    sticky_until = 0

    # Initial context check
    initial_context_match = re.search(context_pattern, raw_parts[0], re.DOTALL)
    if initial_context_match:
        current_sticky_context = initial_context_match.group(1).strip()
        sticky_until = int(initial_context_match.group(3))

    for i in range(1, len(raw_parts), 2):
        q_num = int(raw_parts[i])
        block = raw_parts[i+1].strip()
        
        # Check for shared context instruction
        context_match = re.search(context_pattern, block, re.DOTALL)
        if context_match:
            next_context = context_match.group(1).strip()
            next_until = int(context_match.group(3))
            block = block[:context_match.start()].strip()
            current_sticky_context = next_context
            sticky_until = next_until

        prefix = ""
        if q_num <= sticky_until:
            prefix = f"({current_sticky_context})\n\n"
        else:
            if q_num > sticky_until: current_sticky_context = ""

        # DETECT TYPE
        # MCQ: A. B. C. D.
        is_mcq = all(re.search(fr'(?i){letter}[\.\)]', block) for letter in ['A', 'B', 'C', 'D'])
        # TF: a) b) c) d)
        is_tf = all(re.search(fr'(?i){letter}[\)\.]', block) for letter in ['a', 'b', 'c', 'd'])

        if is_mcq:
            processed_mc.append(q_num)
        elif is_tf:
            processed_tf.append(q_num)
            
    return {"mc_nums": processed_mc, "tf_nums": processed_tf}

if __name__ == "__main__":
    with open("mau_de_dump.txt", "r", encoding="utf-8") as f:
        text = f.read()
    result = parse_docx_strictly(text)
    print(json.dumps(result, indent=2))
