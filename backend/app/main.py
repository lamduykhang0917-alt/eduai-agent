"""
main.py — EduAI Backend entrypoint

Chạy:
    cd backend
    pip install -r requirements.txt
    python -m app.seed   # khởi tạo DB + dữ liệu demo (chạy 1 lần)
    uvicorn app.main:app --reload --port 8000

Sau khi chạy, xem API docs tại: http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import auth, chat, courses, documents, quiz, results, admin, agent
from .core.database import init_db

app = FastAPI(
    title="EduAI API",
    description="API cho hệ thống AI Chatbot hỗ trợ học tập cho sinh viên",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo/đồ án — production nên giới hạn origin cụ thể
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    # Chạy migration mỗi lần khởi động server (an toàn, không xóa dữ liệu cũ)
    # để các cột hồ sơ cá nhân mới luôn tồn tại kể cả với database cũ chưa
    # từng chạy "python -m app.seed" lại từ khi có tính năng này.
    init_db()


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(courses.router)
app.include_router(documents.router)
app.include_router(quiz.router)
app.include_router(results.router)
app.include_router(admin.router)
app.include_router(agent.router)
app.include_router(agent.admin_router)


@app.get("/")
def root():
    return {"message": "EduAI API đang hoạt động", "docs": "/docs"}


@app.get("/api/public/stats")
def public_stats():
    """Số liệu công khai cho trang giới thiệu (landing), không cần đăng nhập."""
    import json
    from .core.database import get_db
    from ai_service import config as ai_config
    with get_db() as db:
        courses = [dict(r) for r in db.execute(
            "SELECT c.code, c.name, c.description, "
            "(SELECT COUNT(*) FROM documents d WHERE d.course_id=c.id AND d.status='active') AS document_count, "
            "(SELECT COUNT(*) FROM chapters h WHERE h.course_id=c.id) AS chapter_count FROM courses c WHERE c.status='active' "
            "ORDER BY (SELECT COUNT(*) FROM documents d WHERE d.course_id=c.id AND d.status='active') DESC, c.name").fetchall()]
        documents = db.execute("SELECT COUNT(*) c FROM documents WHERE status='active'").fetchone()["c"]
        questions = db.execute("SELECT COUNT(*) c FROM questions").fetchone()["c"]
    try:
        with open(ai_config.INTENTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        intents = len(data.get("intents", []))
    except (OSError, ValueError):
        intents = 0
    return {"courses": len(courses), "course_list": courses, "documents": documents,
            "questions": questions, "intents": intents}


@app.get("/health")
def health():
    return {"status": "ok"}
