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

    # 2. Split by "Câu [Số]"
    raw_parts = re.split(r'(?i)Câu\s+(\d+)[\.:]', main_text)
    
    processed_mc = []
    processed_tf = []
    
    for i in range(1, len(raw_parts), 2):
        q_num = int(raw_parts[i])
        block = raw_parts[i+1].strip()
        
        # DEBUG: Log content around a known TF question (e.g. Câu 1 in Part II)
        # Note: In a split, the "Part II" header might be in raw_parts[i-1] or at start of raw_parts[i+1]
        
        # RELAXED DETECT TYPE
        # MCQ: A. B. C. D. (Allow any whitespace/newlines)
        is_mcq = all(re.search(fr'(?i){letter}[\.\)]', block) for letter in ['A', 'B', 'C', 'D'])
        # TF: a) b) c) d) (Allow any whitespace/newlines)
        # Use re.DOTALL and \s* to be safe
        is_tf = all(re.search(fr'(?i){letter}[\)\.]', block) for letter in ['a', 'b', 'c', 'd'])

        if is_mcq:
            processed_mc.append(q_num)
        elif is_tf:
            processed_tf.append(q_num)
        else:
            # Fallback for multi-line TFs
            if re.search(r'(?i)a[\)\.]', block) and re.search(r'(?i)b[\)\.]', block) and \
               re.search(r'(?i)c[\)\.]', block) and re.search(r'(?i)d[\)\.]', block):
                processed_tf.append(q_num)
            
    return {"mc_nums": processed_mc, "tf_nums": processed_tf}

if __name__ == "__main__":
    with open("mau_de_dump.txt", "r", encoding="utf-8") as f:
        text = f.read()
    result = parse_docx_strictly(text)
    print(json.dumps(result, indent=2))
