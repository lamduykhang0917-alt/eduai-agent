# EduAI — Hệ thống AI Chatbot hỗ trợ học tập cho sinh viên

Hệ thống AI Chatbot hỗ trợ học tập cho sinh viên (Agent), dùng cho mọi ngành, mọi môn học. Web Application + Backend API + PhoBERT (AI Service) + Dataset + Database.

## ⚠️ Trạng thái dataset / PhoBERT (đọc trước)

- Hệ thống **chưa có dataset huấn luyện thật** và **chưa có checkpoint PhoBERT đã fine-tune** —
  vì bạn chưa cung cấp file nào. Toàn bộ dữ liệu trong `dataset/*.json` hiện là **dữ liệu demo**
  do mình soạn (thực tế, tiếng Việt, không phải Lorem ipsum) để hệ thống chạy được ngay.
- Chatbot hiện chạy bằng `KeywordIntentClassifier` (dataset-driven, so khớp từ khóa) thay cho
  PhoBERT thật. Khung `PhoBERTIntentClassifier` đã được viết sẵn trong `ai_service/classifier.py`,
  chỉ cần bật `USE_PHOBERT = True` trong `ai_service/config.py` và cung cấp checkpoint đã fine-tune
  khi bạn có dataset huấn luyện thật.

## Cấu trúc thư mục

```
eduai/
├── backend/            FastAPI — REST API (auth, chat, courses, documents, quizzes, admin...)
│   ├── app/
│   │   ├── main.py     Entry point
│   │   ├── seed.py     Khởi tạo DB + dữ liệu demo
│   │   ├── core/        database.py, security.py
│   │   └── routers/     auth, chat, courses, documents, quiz, results, admin
│   └── requirements.txt
├── ai_service/          Module PhoBERT riêng biệt
│   ├── config.py        Cấu hình (USE_PHOBERT, đường dẫn model/dataset, ngưỡng confidence)
│   ├── preprocessing.py Tiền xử lý tiếng Việt
│   ├── classifier.py    KeywordIntentClassifier (đang dùng) + PhoBERTIntentClassifier (sẵn sàng)
│   └── inference.py     Luồng sinh câu trả lời chính (được /api/chat gọi)
├── dataset/              intents.json, knowledge.json, quiz.json (dữ liệu demo — cần thay bằng dataset thật)
├── database/schema.sql   Toàn bộ schema (users, courses, chapters, documents, questions, quiz_results, chat_messages, activity_logs, ai_configs...)
└── frontend/             HTML/CSS/JS thuần (không cần build)
    ├── pages/            login, register, dashboard, courses, chatbot, quiz, admin...
    ├── css/style.css     Design system (Blue/Indigo, Inter, card radius 12-16px)
    └── js/api.js         API client dùng chung
```

## 📚 Dataset tài liệu thật (mới thêm — `dataset/source_documents/`)

Đã nạp bộ tài liệu PDF/PPTX thật của bạn (137 file, ~260MB) vào hệ thống:

- File gốc được giữ nguyên tại `dataset/source_documents/<MÔN>/<file>.pdf|pptx` (không sửa nội dung).
- `ai_service/extract_text.py` — trích xuất text từ PDF (pdfplumber) và PPTX (python-pptx), dùng
  đúng cấu hình cắt margin header/footer theo từng môn mà bạn đã định nghĩa trong `tool.py` gốc.
- `ai_service/ingest_documents.py` — script nạp dữ liệu: tạo/khớp môn học + chương + tài liệu
  trong DB, chunk nội dung từng trang/slide, nạp vào `document_chunks` để RAG dùng. Chạy lại khi
  cần cập nhật: `python -m ai_service.ingest_documents` (idempotent — chạy nhiều lần không tạo
  trùng, tự xóa chunk cũ trước khi nạp lại).
- Kết quả: từ 9 môn demo ban đầu lên **19 môn học**, **120 tài liệu thật**, **~6100 đoạn tri thức
  (chunks)** cho RAG — thay vì chỉ dựa vào `dataset/knowledge.json` (37 mục soạn tay) như trước.
- 7 môn đã có trong Đồ án 1 (Cơ sở dữ liệu, Hệ quản trị CSDL, Cấu trúc dữ liệu & giải thuật,
  Lập trình .NET, Lập trình hướng đối tượng, Trí tuệ nhân tạo) được **thay chương/tài liệu giữ chỗ
  cũ (chưa có file) bằng chương/tài liệu thật** từ dataset bạn gửi.
- 10 môn mới được thêm vì có tài liệu thật nhưng chưa từng có trong hệ thống: Điện toán đám mây,
  Đồ họa máy tính, Kiến trúc máy tính, Kỹ thuật lập trình, Mạng máy tính, Máy học, Nhập môn
  Khoa học máy tính, Tương tác người máy, Xử lý ảnh, Xử lý ngôn ngữ tự nhiên.
- Chạy `python -m app.seed` lại thì vẫn seed đúng dữ liệu demo cũ; sau đó chạy
  `python -m ai_service.ingest_documents` (từ thư mục `eduai/`) để nạp lại dataset thật nếu bạn
  tạo DB mới từ đầu. Admin cũng có thể gọi `POST /api/admin/agent/rag/reindex` để reindex lại
  phần `knowledge.json` (không ảnh hưởng tới chunk từ tài liệu thật).

## 🤖 Đồ án 2 — AI Agent (mới thêm, xây trên nền Đồ án 1)

Đã xây dựng thật trên codebase này (không phải mockup):

- `ai_service/rag.py` — RAG: chunk nội dung `dataset/knowledge.json`, lưu vào bảng
  `document_chunks` (đã có sẵn ở Đồ án 1, nay dùng thật), truy vấn bằng TF-IDF + cosine
  similarity (thuần Python, không gọi mạng). **Lưu ý trung thực**: đây là kỹ thuật retrieval
  dựa trên từ khóa có trọng số thật (không bịa), dùng thay cho embedding ngữ nghĩa bằng
  mạng nơ-ron vì sandbox hiện tại chặn mạng tới huggingface.co — nếu bạn chạy ở máy có mạng
  và muốn nâng cấp lên embedding thật, nói rõ để mình đổi (ví dụ `sentence-transformers`).
- `ai_service/tools.py` — Tool Registry: 5 tool (`search_documents`, `generate_quiz`,
  `submit_quiz`, `get_progress`, `get_recommendation`) bọc lại đúng logic nghiệp vụ đã có,
  `submit_quiz` luôn bị đánh dấu cần xác nhận trước khi thực thi.
- `ai_service/agent.py` — Agent orchestration: vòng lặp ReAct gọi Claude API
  (`messages` + `tools`), tối đa 5 bước/lượt, ghi log từng lần gọi tool vào
  `agent_tool_logs`, tạo `agent_tasks` theo từng yêu cầu, chặn lại (awaiting_confirmation)
  trước khi thực thi `submit_quiz` cho đến khi sinh viên xác nhận qua `/api/agent/confirm`.
- `backend/app/routers/agent.py` — API mới: `POST /api/agent/chat`, `POST /api/agent/confirm`,
  `GET /api/agent/tasks`, `GET /api/agent/tasks/{id}/logs` (sinh viên); `GET/POST
  /api/admin/agent/*` cho logs, tasks, prompt templates, thống kê RAG, reindex, cấu hình (admin).
- Bảng DB mới (trong `database/schema.sql`, tự migrate khi khởi động):
  `agent_tasks`, `agent_tool_logs`, `chat_feedback`, `prompt_templates`, cùng 2 cột mới
  (`vector_embedding`, `page_hint`) trong `document_chunks`.

**Cần bạn cấu hình để Agent thật sự trả lời được**: đặt `ANTHROPIC_API_KEY` trong
`backend/.env` (Agent hiện chỉ gọi Claude API cho vòng lặp tool-calling, chưa nối Gemini vào
Agent — nếu bạn muốn thêm, nói rõ). Nếu chưa có key, `/api/agent/chat` trả về lỗi rõ ràng
(`status: "failed"`), không im lặng và không bịa câu trả lời. Đã kiểm thử end-to-end bằng
cách giả lập (mock) phản hồi của Claude API để xác nhận đúng: vòng lặp gọi tool, ghi log,
cơ chế xác nhận `submit_quiz`, và không có gì trong Đồ án 1 (chat, courses, quiz, progress...)
bị ảnh hưởng.

## 🌐 Muốn có 1 link cố định, không cần chạy máy local?

Xem hướng dẫn deploy miễn phí (Render + Netlify) trong file **[DEPLOY.md](./DEPLOY.md)** —
chỉ cần làm 1 lần, sau đó có link cố định để bấm vào là dùng được ngay, không cần mở
terminal hay bật máy tính nữa.

## Chạy trên máy (local) — dành cho dev/test

### 1. Backend
```bash
cd backend
pip install -r requirements.txt
python -m app.seed              # khởi tạo DB + tài khoản/dữ liệu demo (chạy 1 lần)
uvicorn app.main:app --reload --port 8000
```
API docs (Swagger): http://localhost:8000/docs

### 2. Frontend
```bash
cd frontend
python -m http.server 8080
```
Mở: http://localhost:8080/pages/login.html

> Frontend gọi API tại `http://localhost:8000` (khai báo trong `js/api.js`, biến `API_BASE`).
> Nếu backend chạy ở địa chỉ khác, đặt `window.EDUAI_API_BASE = "..."` trước khi load `api.js`.

## Tài khoản

Sinh viên tự đăng ký trên trang đăng ký. Tài khoản Admin (`admin@eduai.vn`) được tạo khi chạy
`python -m app.seed`; mật khẩu lấy từ biến môi trường `EDUAI_ADMIN_PASSWORD`, nếu không đặt thì
sinh ngẫu nhiên và in ra terminal một lần duy nhất. Không ghi mật khẩu vào repo.

## Đã kiểm thử qua API thật

- Đăng ký / đăng nhập / phân quyền (Student bị chặn 403 khỏi route `/api/admin/*`)
- Chatbot: nhận diện đúng intent (`knowledge_question`, `explanation`, `greeting`...) và trả lời từ knowledge base
- Tạo đề ôn tập từ ngân hàng câu hỏi, nộp bài, chấm điểm
- Dashboard tiến độ học tập, đề xuất học tập
- Admin dashboard, cấu hình AI, quản lý môn học/tài khoản

## Bước tiếp theo khi bạn có dataset/PhoBERT thật

1. Gửi dataset thật (đúng hoặc gần với cấu trúc `dataset/*.json` hiện tại, hoặc cấu trúc khác — mình
   sẽ viết lớp xử lý tương thích, **không tự ý xóa/sửa dữ liệu gốc**).
2. Nếu đã có checkpoint PhoBERT fine-tune: đặt vào `ai_service/model/` + `ai_service/tokenizer/`,
   bật `USE_PHOBERT = True` trong `ai_service/config.py`.
3. Nếu chưa fine-tune: mình có thể viết thêm script huấn luyện PhoBERT trên dataset intent của bạn
   (`vinai/phobert-base` + `AutoModelForSequenceClassification`) — nói rõ nếu bạn muốn bước này.

---

## Đồ án 2 — Nâng cấp AI Agent

Từ Chatbot (Đồ án 1) nâng lên **AI Agent một tác tử + nhiều công cụ** (tool calling). Agent luôn bật ở trang Hỏi AI (không có nút bật/tắt); chỉ khi chưa có API key LLM nào dùng được thì hệ thống tự lùi về Chatbot dataset như Đồ án 1. Chatbot không giới hạn môn học: môn có tài liệu thì dẫn nguồn, môn khác trả lời bằng kiến thức chung và nói rõ.

**Luồng:** Sinh viên hỏi → Agent (LLM) tự chọn công cụ → backend thực thi (luôn gắn `user_id` từ token) → kết quả đưa lại cho LLM → lặp tối đa 6 bước → trả lời. Việc ghi dữ liệu quan trọng (nộp bài, xóa ghi chú) dừng lại chờ sinh viên bấm **Xác nhận**; hành động chờ được lưu ở server nên client không sửa được tham số.

**17 công cụ** (`ai_service/tools.py`): xem môn/chương, tra cứu tài liệu (RAG), tóm tắt tài liệu, tạo quiz, xem quiz, nộp quiz*, lịch sử làm bài, phân tích kết quả, phân tích điểm yếu theo chương, tiến độ, gợi ý học tiếp, lập kế hoạch học, xem kế hoạch, đánh dấu việc xong, lưu/xem/xóa* ghi chú (*cần xác nhận). Thêm công cụ mới chỉ cần viết một hàm gắn `@tool(...)`.

**Nhà cung cấp AI** (`ai_service/agent_llm.py`): Claude, Gemini, Groq — dùng cùng một định dạng nội bộ, nhà nào lỗi/hết hạn mức thì tự chuyển sang nhà kế tiếp; không có key nào hoặc lỗi hết thì tự rơi về Chatbot thường.

**Mới ở giao diện:** thẻ quiz làm bài ngay trong chat (chấm điểm + giải thích), các bước Agent đã dùng, thẻ xác nhận, trang *Kế hoạch & Ghi chú* (sinh viên), trang *Agent* (admin: công cụ, nhật ký gọi tool, chỉnh prompt hệ thống).

**Sửa kèm theo:** nộp bài giờ lưu `quiz_answers` và cập nhật `learning_progress` (trước đây không); chặn nộp trùng / nộp bài của người khác; chặn ghi vào phiên chat của người khác.

**Kiểm thử:** `cd backend && python -m tests.test_agent` (71 kiểm tra, không cần API key, không gọi mạng, chạy trên bản sao DB).

**Triển khai:** không cần biến môi trường mới — dùng lại `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY`. Bảng mới tự tạo khi server khởi động.
