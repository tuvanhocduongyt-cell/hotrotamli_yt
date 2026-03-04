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

    # 2. Split into Parts (Phần I, Phần II, etc.)
    # Use re.split on headings like "Phần I", "Phần II"
    parts_raw = re.split(r'(?i)Phần\s+([I|V|X|L|C]+)[\.:\s]', "\n" + main_text)
    # parts_raw[0] is preamble
    # parts_raw[1] is "I", parts_raw[2] is content of Part I
    # parts_raw[3] is "II", parts_raw[4] is content of Part II

    all_questions = [] # list of (part_label, q_num, block)
    
    # If no parts found, treat whole as Part I
    if len(parts_raw) < 3:
        raw_qs = re.split(r'(?i)Câu\s+(\d+)[\.:]', main_text)
        for j in range(1, len(raw_qs), 2):
            all_questions.append(("I", int(raw_qs[j]), raw_qs[j+1]))
    else:
        for i in range(1, len(parts_raw), 2):
            part_label = parts_raw[i].upper()
            part_content = parts_raw[i+1]
            raw_qs = re.split(r'(?i)Câu\s+(\d+)[\.:]', part_content)
            for j in range(1, len(raw_qs), 2):
                all_questions.append((part_label, int(raw_qs[j]), raw_qs[j+1]))

    processed_mc = []
    processed_tf = []
    
    for part_label, q_num, block in all_questions:
        # If in Part I, assume MCQ (unless markers say otherwise)
        # If in Part II, assume TF (unless markers say otherwise)
        
        has_mc_markers = all(re.search(fr'(?i){letter}[\.\)]', block) for letter in ['A', 'B', 'C', 'D'])
        has_tf_markers = all(re.search(fr'(?i){letter}[\)\.]', block) for letter in ['a', 'b', 'c', 'd'])

        if part_label == "I":
            if has_mc_markers or not has_tf_markers:
                processed_mc.append(f"{part_label}-{q_num}")
            else:
                processed_tf.append(f"{part_label}-{q_num}")
        elif part_label == "II":
             if has_tf_markers or not has_mc_markers:
                 processed_tf.append(f"{part_label}-{q_num}")
             else:
                 processed_mc.append(f"{part_label}-{q_num}")
        else:
            # Other parts default to essay if no markers
            if has_mc_markers: processed_mc.append(f"{part_label}-{q_num}")
            elif has_tf_markers: processed_tf.append(f"{part_label}-{q_num}")
            
    return {"mc": processed_mc, "tf": processed_tf}

if __name__ == "__main__":
    with open("mau_de_dump.txt", "r", encoding="utf-8") as f:
        text = f.read()
    result = parse_docx_strictly(text)
    print(json.dumps(result, indent=2))
