"""
config.py
Cấu hình cho AI Service của EduAI.

CHẾ ĐỘ TRẢ LỜI (LLM_PROVIDER) — quyết định chatbot lấy câu trả lời từ đâu:
  - "claude"  : gọi Anthropic Claude API để trả lời TỰ DO bất kỳ câu hỏi nào
                (không giới hạn trong dataset). Cần biến môi trường ANTHROPIC_API_KEY.
  - "gemini"  : gọi Google Gemini API để trả lời TỰ DO bất kỳ câu hỏi nào.
                Cần biến môi trường GEMINI_API_KEY.
  - "dataset" : chế độ cũ — dùng KeywordIntentClassifier + knowledge base nội bộ,
                chỉ trả lời được các câu hỏi có trong dataset. Không cần API key,
                chạy hoàn toàn offline.

Mặc định là "claude". Nếu chưa cấu hình API key tương ứng, hệ thống sẽ TỰ ĐỘNG
chuyển sang chế độ "dataset" cho từng câu hỏi (xem inference.py) để chatbot vẫn
trả lời được thay vì báo lỗi, đồng thời nhắc rõ trong câu trả lời rằng cần cấu
hình API key.

CÁCH LẤY API KEY:
  - Claude:  https://console.anthropic.com/  → Settings → API Keys
  - Gemini:  https://aistudio.google.com/apikey

CÁCH CẤU HÌNH (không hard-code key vào code vì lý do bảo mật):
  - Chạy local: đặt biến môi trường trước khi chạy uvicorn, ví dụ (macOS/Linux):
        export ANTHROPIC_API_KEY="sk-ant-..."
        uvicorn app.main:app --reload --port 8000
    Hoặc tạo file backend/.env với nội dung:
        ANTHROPIC_API_KEY=sk-ant-...
  - Deploy trên Render: vào Dashboard → Environment → Add Environment Variable.

---
PHẦN PHOBERT (giữ lại, không xóa): nếu muốn quay về hướng tiếp cận PhoBERT theo
đúng yêu cầu ban đầu của đồ án (đề tài Khoa học máy tính, dùng PhoBERT xử lý
tiếng Việt thay vì gọi LLM ngoài), đặt LLM_PROVIDER = "dataset" và USE_PHOBERT =
True khi đã có checkpoint đã fine-tune — xem chi tiết trong classifier.py.
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Nạp file backend/.env theo ĐƯỜNG DẪN TUYỆT ĐỐI (không phụ thuộc thư mục đang
# đứng khi chạy lệnh) để tránh trường hợp chạy uvicorn từ thư mục khác khiến
# .env không được đọc.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, "backend", ".env"))
except ImportError:
    pass  # python-dotenv chưa cài — vẫn hoạt động bình thường nếu dùng biến môi trường hệ thống

# ==== Dataset paths (có thể thay bằng dataset thật của người dùng) ====
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
INTENTS_FILE = os.path.join(DATASET_DIR, "intents.json")
KNOWLEDGE_FILE = os.path.join(DATASET_DIR, "knowledge.json")
QUIZ_FILE = os.path.join(DATASET_DIR, "quiz.json")
QUIZ_EXTRA_FILE = os.path.join(DATASET_DIR, "quiz_extra.json")  # câu hỏi bổ sung (không sửa quiz.json gốc)

# ==== Chế độ trả lời của chatbot ====
# "auto"    : tự chọn — thử lần lượt Claude (nếu có ANTHROPIC_API_KEY), Gemini (GEMINI_API_KEY), Groq (GROQ_API_KEY),
#             lỗi/hết lượt thì tự chuyển sang nhà cung cấp kế tiếp, cuối cùng rơi về nội dung có sẵn (khuyên dùng)
# "claude" | "gemini" | "groq": chỉ dùng đúng nhà cung cấp đó (lỗi thì rơi về nội dung có sẵn)
# "dataset" : chỉ dùng nội dung có sẵn (knowledge base + tài liệu môn học), không gọi AI ngoài
LLM_PROVIDER = os.environ.get("EDUAI_LLM_PROVIDER", "auto")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# Groq: miễn phí, rất nhanh, dùng làm dự phòng khi Claude/Gemini lỗi hoặc quá tải. Key tạo tại console.groq.com
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# gemini-3.1-flash-lite: bản ổn định (GA) hiện hành tại thời điểm viết code này,
# chưa có lịch ngừng hỗ trợ. Nếu Google ra bản mới hơn, chỉ cần đổi giá trị này
# (hoặc đặt biến môi trường GEMINI_MODEL) — không cần sửa code nơi khác.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

LLM_SYSTEM_PROMPT = (
    "Bạn là EduAI, trợ lý AI hỗ trợ học tập cho sinh viên mọi ngành, mọi môn học. "
    "Hãy trả lời bằng tiếng Việt, ngắn gọn, chính xác, dễ hiểu, có ví dụ minh họa "
    "khi phù hợp. Nếu câu hỏi mơ hồ, hãy hỏi lại để làm rõ thay vì đoán bừa."
)

# ==== PhoBERT model config (dùng khi LLM_PROVIDER="dataset" và USE_PHOBERT=True) ====
USE_PHOBERT = False
PHOBERT_PRETRAINED = "vinai/phobert-base"   # base model dùng để fine-tune
MODEL_PATH = os.path.join(BASE_DIR, "ai_service", "model")  # checkpoint đã fine-tune
TOKENIZER_PATH = os.path.join(BASE_DIR, "ai_service", "tokenizer")
MAX_SEQ_LENGTH = 128

# ==== Ngưỡng tin cậy (chỉ áp dụng cho chế độ "dataset") ====
# Nếu confidence của model/matcher thấp hơn ngưỡng này -> trả lời "chưa tìm thấy
# thông tin phù hợp" thay vì đoán bừa (theo mục 41 của spec).
CONFIDENCE_THRESHOLD = 0.35

