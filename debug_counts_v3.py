import re
import json

def parse_docx_strictly(text):
    text = text.replace('\r\n', '\n')
    
    # 1. Detect Footer (Answer Key) FIRST
    footer_match = re.search(r'(?i)\n\s*ĐÁP\s*ÁN\s*[:\-]', text)
    if footer_match:
        main_text = text[:footer_match.start()].strip()
    else:
        main_text = text

    raw_parts = re.split(r'(?i)Câu\s+(\d+)[\.:]', main_text)
    
    processed_mc = []
    processed_tf = []
    
    for i in range(1, len(raw_parts), 2):
        q_num = int(raw_parts[i])
        block = raw_parts[i+1].strip()
        
        # STRICTOR DETECTION
        # MCQ: Must find A. B. C. D. as separate markers
        # We look for markers that look like they define an option
        mc_markers = re.findall(r'(?i)\n\s*([A-D][\.\)])', "\n" + block)
        letters_found = set(m.upper().replace(')', '.') for m in mc_markers)
        is_mcq = all(f"{L}." in letters_found for L in ['A', 'B', 'C', 'D'])

        # TF: Must find a) b) c) d)
        tf_markers = re.findall(r'(?i)\n\s*([a-d][\)\.])', "\n" + block)
        small_letters_found = set(m.lower().replace('.', ')') for m in tf_markers)
        is_tf = all(f"{L})" in small_letters_found for L in ['a', 'b', 'c', 'd'])

        if is_mcq:
            processed_mc.append(q_num)
        elif is_tf:
            processed_tf.append(q_num)
        else:
            # Last resort: search for markers anywhere
            if all(re.search(fr'(?i){letter}[\.\)]', block) for letter in ['A', 'B', 'C', 'D']):
                 processed_mc.append(q_num)
            elif all(re.search(fr'(?i){letter}[\)\.]', block) for letter in ['a', 'b', 'c', 'd']):
                 processed_tf.append(q_num)
            
    return {"mc_nums": processed_mc, "tf_nums": processed_tf}

if __name__ == "__main__":
    with open("mau_de_dump.txt", "r", encoding="utf-8") as f:
        text = f.read()
    result = parse_docx_strictly(text)
    print(json.dumps(result, indent=2))
