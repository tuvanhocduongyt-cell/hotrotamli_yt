import google.generativeai as genai

# Cấu hình API key (thay bằng key của bạn)
genai.configure(api_key="AIzaSyCviosQe-qIKt_MhseTVXO7GEYzmCkVSmE")

def analyze_text_with_gemini(text):
    model = genai.GenerativeModel("models/gemini-1.5-flash")
    response = model.generate_content(f"Đây là bài làm của học sinh:\n{text}\nHãy nhận xét và đề xuất cải thiện.")
    return response.text

