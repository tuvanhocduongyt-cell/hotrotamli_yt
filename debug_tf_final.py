import re

with open("mau_de_dump.txt", "r", encoding="utf-8") as f:
    text = f.read()

tf_match = re.search(r'(?i)Phần\s*II.*?(?=$)', text, re.DOTALL)
if tf_match:
    ans_text = tf_match.group(0)
    with open("debug_raw.txt", "w", encoding="utf-8") as f:
        f.write(ans_text)
    print("TF Section written to debug_raw.txt")
    
    # Simple search for Câu and then any Đ/S
    pairs = re.findall(r'(?i)Câu\s*(\d+)[\s\n]+([^\n]+)', ans_text)
    print(f"Basic regex found {len(pairs)} pairs.")
    for n, val in pairs[:2]:
        print(f"Num: {n}, Val: {val.strip()}")
