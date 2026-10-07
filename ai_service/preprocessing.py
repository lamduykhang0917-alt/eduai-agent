"""
preprocessing.py
Tiền xử lý câu hỏi tiếng Việt trước khi đưa vào PhoBERT / bộ phân loại.

Khi tích hợp PhoBERT thật, bước tách từ tiếng Việt (word segmentation) nên
dùng thư viện VnCoreNLP hoặc underthesea trước khi tokenize bằng PhoBERT
tokenizer (PhoBERT được huấn luyện trên dữ liệu đã tách từ, ví dụ:
"học_sinh" thay vì "học sinh"). Phần này để trống hàm segment_words() làm
điểm nối, không tự ý cài thêm thư viện ngoài phạm vi khi chưa được yêu cầu.
"""

import re
import unicodedata

# Các từ dừng (stopword) tiếng Việt phổ biến trong câu hỏi học tập.
# LƯU Ý: không loại "là", "gì", "sao" vì đây là các từ mang tín hiệu intent
# quan trọng (vd: "... là gì", "vì sao ...") — loại chúng sẽ làm pattern
# matching của các intent knowledge_question/explanation không còn khớp được.
STOPWORDS = {
    "của", "và", "các", "một", "những", "cho", "tôi",
    "bạn", "hãy", "giúp", "có", "thể", "này", "đó", "ạ", "nhé", "vậy",
}


def normalize_unicode(text: str) -> str:
    """Chuẩn hóa Unicode (NFC) để tránh lỗi so khớp do dấu tổ hợp khác nhau."""
    return unicodedata.normalize("NFC", text)


def clean_text(text: str) -> str:
    """Loại bỏ ký tự thừa, khoảng trắng dư, đưa về chữ thường."""
    text = normalize_unicode(text)
    text = text.lower().strip()
    text = re.sub(r"[^\w\sÀ-ỹ]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def remove_stopwords(text: str) -> str:
    tokens = [t for t in text.split() if t not in STOPWORDS]
    return " ".join(tokens) if tokens else text


def segment_words(text: str) -> str:
    """
    Điểm nối để tách từ tiếng Việt bằng VnCoreNLP/underthesea khi tích hợp
    PhoBERT thật. Hiện tại trả về nguyên văn (chưa tách từ) vì hệ thống
    đang chạy ở chế độ dataset-driven matching, không cần tách từ.
    """
    return text


def preprocess(text: str, for_classifier: bool = True) -> str:
    """
    Pipeline tiền xử lý đầy đủ cho một câu hỏi của sinh viên.
    for_classifier=True: áp dụng loại bỏ stopword (dùng cho keyword matching).
    """
    text = clean_text(text)
    if for_classifier:
        text = remove_stopwords(text)
    return text
