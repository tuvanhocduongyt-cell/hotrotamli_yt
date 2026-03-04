import re
import json

def parse_docx_strictly(text):
    text = text.replace('\r\n', '\n')
    mc_global_answers = {}
    tf_global_answers = {}
    
    # 1. Tìm vùng đáp án trắc nghiệm
    mc_match = re.search(r'(?i)ĐÁP\s+ÁN\s*[:\-]\s*PHẦN\s*I.*?(?=Phần\s*II|-------|$)', text, re.DOTALL)
    if mc_match:
        ans_text = mc_match.group(0)
        numbers = re.findall(r'\b(\d+)\b', ans_text)
        letters = re.findall(r'\b([A-D])\b', ans_text.upper())
        if len(numbers) == len(letters):
            for n, l in zip(numbers, letters):
                mc_global_answers[int(n)] = l
        
    # 2. Tìm vùng đáp án Đúng/Sai
    tf_match = re.search(r'(?i)Phần\s*II.*?(?=$)', text, re.DOTALL)
    if tf_match:
        ans_text = tf_match.group(0)
        # Regex cực kỳ linh hoạt: Tìm "Câu X", theo sau là bất kỳ thứ gì cho đến khi gặp Đ/S hoặc Câu tiếp theo
        # Thực tế mau_de_dump.txt: "Câu 1\n\nS, Đ, Đ, Đ"
        tf_pairs = re.findall(r'(?i)Câu\s*(\d+)\s*\n+([^C]+)', ans_text)
             
        for n, val_str in tf_pairs:
            vals = []
            matches = re.findall(r'(?i)([đs]|\b[tf]\b)', val_str)
            for m in matches:
                m = m.lower()
                if m in ['đ', 't']: vals.append(True)
                elif m in ['s', 'f']: vals.append(False)
            if len(vals) >= 4:
                tf_global_answers[int(n)] = vals[:4]

    footer_search = re.search(r'(?i)\n\s*ĐÁP\s*ÁN\s*[:\-]', text)
    if footer_search:
        main_text = text[:footer_search.start()].strip()
    else:
        main_text = text

    raw_parts = re.split(r'(?i)Câu\s+(\d+)[\.:]', main_text)
    processed_mc = []
    processed_tf = []
    
    for i in range(1, len(raw_parts), 2):
        q_num = int(raw_parts[i])
        block = raw_parts[i+1].strip()
        if not block: continue
        
        if all(re.search(fr'(?i){letter}[\.\)]', block) for letter in ['A', 'B', 'C', 'D']):
            ans = mc_global_answers.get(q_num, "A")
            processed_mc.append({"num": q_num, "ans": ans})
        elif all(re.search(fr'(?i){letter}[\)\.]', block) for letter in ['a', 'b', 'c', 'd']):
            ans = tf_global_answers.get(q_num, [True, True, True, True])
            processed_tf.append({"num": q_num, "ans": ans})
            
    return {"mc_count": len(processed_mc), "tf_count": len(processed_tf), "tf_sample": processed_tf[0] if processed_tf else None}

if __name__ == "__main__":
    with open("mau_de_dump.txt", "r", encoding="utf-8") as f:
        text = f.read()
    result = parse_docx_strictly(text)
    print(json.dumps(result, indent=2))
