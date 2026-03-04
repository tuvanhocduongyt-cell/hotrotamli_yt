import re

def test_split():
    content_block = '... miền Bắc. Cùng một lúc ... a) Option A b) Option B'
    
    # OLD regex: re.split(r'([a-d][\)\.])', content_block)
    # NEW regex: re.split(r'(?:\s+|^)([a-d][\)\.])', content_block)
    
    parts = re.split(r'(?:\s+|^)([a-d][\)\.])', content_block)
    print(f"Parts: {parts}")
    
    # Check if 'Bắc.' was split
    found_split_in_bac = any('miền Bắ' in p for p in parts)
    print(f"Split in 'Bắc.': {found_split_in_bac}")
    
    # Check if a) and b) were found
    has_a = "a)" in parts or any("a)" in str(p) for p in parts)
    has_b = "b)" in parts or any("b)" in str(p) for p in parts)
    print(f"Found a): {has_a}")
    print(f"Found b): {has_b}")

if __name__ == "__main__":
    test_split()
