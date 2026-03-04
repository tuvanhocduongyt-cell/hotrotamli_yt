import mammoth

def read_docx_raw(file_path):
    with open(file_path, "rb") as docx_file:
        result = mammoth.extract_raw_text(docx_file)
        text = result.value
        return text

if __name__ == "__main__":
    content = read_docx_raw("mau_de.docx")
    print("--- CONTENT START ---")
    print(content)
    print("--- CONTENT END ---")
