import mammoth
import io

def read_docx_to_txt(file_path, output_path):
    with open(file_path, "rb") as docx_file:
        result = mammoth.extract_raw_text(docx_file)
        text = result.value
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
    return text

if __name__ == "__main__":
    read_docx_to_txt("mau_de.docx", "mau_de_dump.txt")
    print("Done dumping to mau_de_dump.txt")
