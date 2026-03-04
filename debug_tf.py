import re

with open("mau_de_dump.txt", "r", encoding="utf-8") as f:
    text = f.read()

tf_match = re.search(r'(?i)Phần\s*II.*?(?=$)', text, re.DOTALL)
if tf_match:
    ans_text = tf_match.group(0)
    print("--- TF SECTION START ---")
    print(repr(ans_text[:200]))
    print("--- TF SECTION END ---")
    
    # Try a very simple findall
    câu_thứ = re.findall(r'(?i)Câu\s*(\d+)', ans_text)
    print(f"Numbers found: {câu_thứ}")
    
    # Try to find what follows Câu 1
    after_c1 = re.search(r'(?i)Câu\s*1\s*(.*?)Câu\s*2', ans_text, re.DOTALL)
    if after_c1:
        print(f"Content after Câu 1: {repr(after_c1.group(1))}")
