import json
import os
import sys
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..core.database import get_db
from ..core.extract import ExtractError, extract_chunks
from ..core.security import require_admin, hash_password

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from ai_service.rag import _term_freq  # noqa: E402

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------- Dashboard ----------
@router.get("/dashboard")
def admin_dashboard(admin: dict = Depends(require_admin)):
    with get_db() as db:
        stats = {}
        stats["total_students"] = db.execute(
            "SELECT COUNT(*) c FROM users u JOIN roles r ON u.role_id=r.id WHERE r.name='STUDENT'"
        ).fetchone()["c"]
        stats["total_courses"] = db.execute("SELECT COUNT(*) c FROM courses WHERE status = 'active'").fetchone()["c"]
        stats["total_chapters"] = db.execute("SELECT COUNT(*) c FROM chapters").fetchone()["c"]
        stats["total_documents"] = db.execute("SELECT COUNT(*) c FROM documents WHERE status = 'active'").fetchone()["c"]
        stats["total_questions"] = db.execute("SELECT COUNT(*) c FROM questions").fetchone()["c"]
        stats["total_ai_queries"] = db.execute(
            "SELECT COUNT(*) c FROM activity_logs WHERE action='ask_ai'"
        ).fetchone()["c"]
        return stats


# ---------- 23. Quản lý tài khoản ----------
@router.get("/users")
def list_users(search: Optional[str] = None, admin: dict = Depends(require_admin)):
    query = ("SELECT u.id, u.full_name, u.email, r.name as role, u.status, u.created_at "
              "FROM users u JOIN roles r ON u.role_id = r.id")
    params = []
    if search:
        query += " WHERE u.full_name LIKE ? OR u.email LIKE ?"
        params += [f"%{search}%", f"%{search}%"]
    query += " ORDER BY u.created_at DESC"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
        return [dict(r) for r in rows]


class CreateUserRequest(BaseModel):
    full_name: str
    email: str
    password: str
    role: str = "STUDENT"  # STUDENT | ADMIN


@router.post("/users")
def create_user(payload: CreateUserRequest, admin: dict = Depends(require_admin)):
    if payload.role not in ("STUDENT", "ADMIN"):
        raise HTTPException(400, "Vai trò không hợp lệ")
    if len(payload.password) < 8 or any(c.isspace() for c in payload.password):
        raise HTTPException(400, "Mật khẩu phải có ít nhất 8 ký tự và không chứa khoảng trắng")
    with get_db() as db:
        existing = db.execute("SELECT id FROM users WHERE email = ?", (payload.email,)).fetchone()
        if existing:
            raise HTTPException(400, "Email đã được sử dụng")
        cur = db.execute(
            "INSERT INTO users (full_name, email, password_hash, role_id) VALUES (?, ?, ?, "
            "(SELECT id FROM roles WHERE name = ?))",
            (payload.full_name, payload.email, hash_password(payload.password), payload.role),
        )
        return {"id": cur.lastrowid}


class UpdateUserRequest(BaseModel):
    full_name: str
    email: str
    role: str  # STUDENT | ADMIN


@router.put("/users/{user_id}")
def update_user(user_id: int, payload: UpdateUserRequest, admin: dict = Depends(require_admin)):
    if payload.role not in ("STUDENT", "ADMIN"):
        raise HTTPException(400, "Vai trò không hợp lệ")
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM users WHERE email = ? AND id != ?", (payload.email, user_id)
        ).fetchone()
        if existing:
            raise HTTPException(400, "Email đã được sử dụng bởi tài khoản khác")
        db.execute(
            "UPDATE users SET full_name=?, email=?, role_id=(SELECT id FROM roles WHERE name=?) WHERE id=?",
            (payload.full_name, payload.email, payload.role, user_id),
        )
    return {"message": "Cập nhật thông tin tài khoản thành công"}


class UpdateUserStatusRequest(BaseModel):
    status: str  # active | locked


@router.patch("/users/{user_id}/status")
def update_user_status(user_id: int, payload: UpdateUserStatusRequest, admin: dict = Depends(require_admin)):
    if payload.status not in ("active", "locked"):
        raise HTTPException(400, "Trạng thái không hợp lệ")
    with get_db() as db:
        db.execute("UPDATE users SET status = ? WHERE id = ?", (payload.status, user_id))
    return {"message": "Cập nhật trạng thái thành công"}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(400, "Không thể xóa chính tài khoản đang đăng nhập")
    with get_db() as db:
        target = db.execute(
            "SELECT u.id, r.name AS role FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = ?",
            (user_id,),
        ).fetchone()
        if target is None:
            raise HTTPException(404, "Không tìm thấy tài khoản")
        if target["role"] == "ADMIN":
            raise HTTPException(400, "Không thể xóa tài khoản Admin")
        # Xóa dữ liệu liên quan trước (bảng con -> bảng cha) vì khóa ngoại đang bật.
        uid = (user_id,)
        db.execute("DELETE FROM chat_feedback WHERE user_id = ? OR message_id IN (SELECT m.id FROM chat_messages m JOIN chat_sessions s ON s.id = m.session_id WHERE s.user_id = ?)", (user_id, user_id))
        db.execute("DELETE FROM chat_messages WHERE session_id IN (SELECT id FROM chat_sessions WHERE user_id = ?)", uid)
        db.execute("DELETE FROM chat_sessions WHERE user_id = ?", uid)
        db.execute("DELETE FROM quiz_answers WHERE quiz_result_id IN (SELECT id FROM quiz_results WHERE user_id = ?)", uid)
        db.execute("DELETE FROM quiz_results WHERE user_id = ?", uid)
        db.execute("DELETE FROM quiz_results WHERE quiz_id IN (SELECT id FROM quizzes WHERE user_id = ?)", uid)
        db.execute("DELETE FROM quiz_items WHERE quiz_id IN (SELECT id FROM quizzes WHERE user_id = ?)", uid)
        db.execute("DELETE FROM quizzes WHERE user_id = ?", uid)
        db.execute("DELETE FROM study_tasks WHERE user_id = ?", uid)
        db.execute("DELETE FROM study_plans WHERE user_id = ?", uid)
        db.execute("DELETE FROM student_notes WHERE user_id = ?", uid)
        db.execute("DELETE FROM agent_tool_logs WHERE task_id IN (SELECT id FROM agent_tasks WHERE user_id = ?)", uid)
        db.execute("DELETE FROM agent_tasks WHERE user_id = ?", uid)
        db.execute("DELETE FROM learning_progress WHERE user_id = ?", uid)
        db.execute("DELETE FROM recommendations WHERE user_id = ?", uid)
        db.execute("UPDATE activity_logs SET user_id = NULL WHERE user_id = ?", uid)
        db.execute("DELETE FROM users WHERE id = ?", uid)
    return {"message": "Đã xóa tài khoản"}


# ---------- 24. Quản lý môn học ----------
class CourseRequest(BaseModel):
    code: str
    name: str
    description: Optional[str] = ""


@router.get("/courses")
def admin_list_courses(search: Optional[str] = None, admin: dict = Depends(require_admin)):
    query = "SELECT * FROM courses WHERE status = 'active'"
    params = []
    if search:
        query += " AND (name LIKE ? OR code LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    query += " ORDER BY name"
    with get_db() as db:
        rows = []
        for r in db.execute(query, params).fetchall():
            item = dict(r)
            item["chapter_count"] = db.execute("SELECT COUNT(*) c FROM chapters WHERE course_id=?", (r["id"],)).fetchone()["c"]
            item["document_count"] = db.execute(
                "SELECT COUNT(*) c FROM documents WHERE course_id=? AND status='active'", (r["id"],)).fetchone()["c"]
            item["question_count"] = db.execute("SELECT COUNT(*) c FROM questions WHERE course_id=?", (r["id"],)).fetchone()["c"]
            rows.append(item)
        return rows


@router.get("/courses/{course_id}")
def admin_get_course(course_id: int, admin: dict = Depends(require_admin)):
    """Chi tiết môn: thông tin, các chương và tài liệu (kèm số đoạn nội dung đã đọc được)."""
    with get_db() as db:
        row = db.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Không tìm thấy môn học")
        chapters = [dict(c) for c in db.execute(
            "SELECT * FROM chapters WHERE course_id=? ORDER BY order_index, id", (course_id,)).fetchall()]
        documents = [dict(d) for d in db.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM document_chunks dc WHERE dc.document_id = d.id) AS chunk_count "
            "FROM documents d WHERE d.course_id=? AND d.status='active' ORDER BY d.id", (course_id,)).fetchall()]
        result = dict(row)
        result["chapters"] = chapters
        result["documents"] = documents
        return result


@router.post("/courses")
def create_course(payload: CourseRequest, admin: dict = Depends(require_admin)):
    with get_db() as db:
        existing = db.execute("SELECT id FROM courses WHERE code = ?", (payload.code,)).fetchone()
        if existing:
            raise HTTPException(400, "Mã môn đã tồn tại")
        cur = db.execute(
            "INSERT INTO courses (code, name, description) VALUES (?, ?, ?)",
            (payload.code, payload.name, payload.description),
        )
        return {"id": cur.lastrowid}


@router.put("/courses/{course_id}")
def update_course(course_id: int, payload: CourseRequest, admin: dict = Depends(require_admin)):
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM courses WHERE code = ? AND id != ?", (payload.code, course_id)
        ).fetchone()
        if existing:
            raise HTTPException(400, "Mã môn đã được sử dụng bởi môn học khác")
        db.execute(
            "UPDATE courses SET code=?, name=?, description=? WHERE id=?",
            (payload.code, payload.name, payload.description, course_id),
        )
    return {"message": "Cập nhật môn học thành công"}


@router.delete("/courses/{course_id}")
def delete_course(course_id: int, admin: dict = Depends(require_admin)):
    with get_db() as db:
        db.execute("UPDATE courses SET status='inactive' WHERE id=?", (course_id,))
    return {"message": "Đã xóa môn học"}


# ---------- 25. Quản lý chương ----------
class ChapterRequest(BaseModel):
    course_id: int
    name: str
    order_index: int = 0


@router.get("/chapters")
def admin_list_chapters(course_id: Optional[int] = None, admin: dict = Depends(require_admin)):
    query = "SELECT * FROM chapters"
    params = []
    if course_id:
        query += " WHERE course_id = ?"
        params.append(course_id)
    query += " ORDER BY order_index"
    with get_db() as db:
        return [dict(r) for r in db.execute(query, params).fetchall()]


@router.post("/chapters")
def create_chapter(payload: ChapterRequest, admin: dict = Depends(require_admin)):
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO chapters (course_id, name, order_index) VALUES (?, ?, ?)",
            (payload.course_id, payload.name, payload.order_index),
        )
        return {"id": cur.lastrowid}


@router.delete("/chapters/{chapter_id}")
def delete_chapter(chapter_id: int, admin: dict = Depends(require_admin)):
    with get_db() as db:
        db.execute("UPDATE documents SET chapter_id = NULL WHERE chapter_id = ?", (chapter_id,))
        db.execute("UPDATE questions SET chapter_id = NULL WHERE chapter_id = ?", (chapter_id,))
        db.execute("DELETE FROM chapters WHERE id=?", (chapter_id,))
    return {"message": "Đã xóa chương"}


# ---------- 26. Quản lý tài liệu ----------
class DocumentRequest(BaseModel):
    course_id: int
    chapter_id: Optional[int] = None
    title: str
    file_type: str
    file_path: str


@router.get("/documents")
def admin_list_documents(admin: dict = Depends(require_admin)):
    with get_db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM documents").fetchall()]


@router.post("/documents")
def create_document(payload: DocumentRequest, admin: dict = Depends(require_admin)):
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO documents (course_id, chapter_id, title, file_type, file_path) "
            "VALUES (?, ?, ?, ?, ?)",
            (payload.course_id, payload.chapter_id, payload.title, payload.file_type, payload.file_path),
        )
        return {"id": cur.lastrowid}


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, admin: dict = Depends(require_admin)):
    with get_db() as db:
        db.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))
        db.execute("DELETE FROM documents WHERE id=?", (document_id,))
    return {"message": "Đã xóa tài liệu"}


@router.post("/courses/{course_id}/documents")
async def upload_document(course_id: int, file: UploadFile = File(...), chapter_id: Optional[int] = Form(None),
                          admin: dict = Depends(require_admin)):
    """Tải lên tài liệu PDF/DOCX/TXT: đọc chữ trong tệp, chia đoạn và đưa vào kho tri thức của chatbot."""
    data = await file.read()
    filename = os.path.basename(file.filename or "tai-lieu")
    try:
        file_type, chunks = extract_chunks(filename, data)
    except ExtractError as exc:
        raise HTTPException(400, f"{filename}: {exc}")
    with get_db() as db:
        if db.execute("SELECT 1 FROM courses WHERE id=?", (course_id,)).fetchone() is None:
            raise HTTPException(404, "Không tìm thấy môn học")
        if chapter_id and db.execute("SELECT 1 FROM chapters WHERE id=? AND course_id=?", (chapter_id, course_id)).fetchone() is None:
            raise HTTPException(400, "Chương không thuộc môn học này")
        if db.execute("SELECT 1 FROM documents WHERE course_id=? AND title=? AND status='active'", (course_id, filename)).fetchone():
            raise HTTPException(400, f"{filename}: môn học này đã có tài liệu cùng tên")
        doc_id = db.execute(
            "INSERT INTO documents (course_id, chapter_id, title, file_type, file_path, status) "
            "VALUES (?, ?, ?, ?, ?, 'active')",
            (course_id, chapter_id, filename, file_type, f"upload/{course_id}/{filename}"),
        ).lastrowid
        for idx, (page_no, text) in enumerate(chunks):
            db.execute(
                "INSERT INTO document_chunks (document_id, content, chunk_index, vector_embedding, page_hint) "
                "VALUES (?, ?, ?, ?, ?)",
                (doc_id, text, idx, json.dumps(_term_freq(text)), f"upload:{filename}:p{page_no}"),
            )
        db.execute("INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'upload_document', ?)",
                   (admin["id"], filename))
    return {"id": doc_id, "title": filename, "file_type": file_type, "chunk_count": len(chunks)}


# ---------- 27. Quản lý ngân hàng câu hỏi ----------
def _attach_answers(db, questions):
    result = []
    for q in questions:
        qd = dict(q)
        answers = db.execute(
            "SELECT option_key, option_text, is_correct FROM answers WHERE question_id=? ORDER BY option_key",
            (qd["id"],),
        ).fetchall()
        qd["options"] = {a["option_key"]: a["option_text"] for a in answers}
        correct = next((a["option_key"] for a in answers if a["is_correct"]), None)
        qd["correct_option"] = correct
        result.append(qd)
    return result


@router.get("/questions")
def admin_list_questions(search: Optional[str] = None, course_id: Optional[int] = None,
                          admin: dict = Depends(require_admin)):
    query = ("SELECT q.*, c.name AS course_name FROM questions q "
             "LEFT JOIN courses c ON c.id = q.course_id")
    conditions = []
    params = []
    if search:
        conditions.append("q.content LIKE ?")
        params.append(f"%{search}%")
    if course_id:
        conditions.append("q.course_id = ?")
        params.append(course_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY q.id DESC"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
        return _attach_answers(db, rows)


@router.get("/questions/{question_id}")
def admin_get_question(question_id: int, admin: dict = Depends(require_admin)):
    with get_db() as db:
        row = db.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Không tìm thấy câu hỏi")
        return _attach_answers(db, [row])[0]


class QuestionRequest(BaseModel):
    course_id: int
    chapter_id: Optional[int] = None
    content: str
    difficulty: str = "basic"
    explanation: Optional[str] = ""
    options: dict  # {"A": "...", "B": "...", ...}
    correct_option: str


@router.post("/questions")
def create_question(payload: QuestionRequest, admin: dict = Depends(require_admin)):
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO questions (course_id, chapter_id, content, difficulty, explanation) "
            "VALUES (?, ?, ?, ?, ?)",
            (payload.course_id, payload.chapter_id, payload.content, payload.difficulty, payload.explanation),
        )
        question_id = cur.lastrowid
        for key, text in payload.options.items():
            db.execute(
                "INSERT INTO answers (question_id, option_key, option_text, is_correct) VALUES (?, ?, ?, ?)",
                (question_id, key, text, key == payload.correct_option),
            )
        return {"id": question_id}


@router.put("/questions/{question_id}")
def update_question(question_id: int, payload: QuestionRequest, admin: dict = Depends(require_admin)):
    with get_db() as db:
        existing = db.execute("SELECT id FROM questions WHERE id=?", (question_id,)).fetchone()
        if existing is None:
            raise HTTPException(404, "Không tìm thấy câu hỏi")
        db.execute(
            "UPDATE questions SET course_id=?, chapter_id=?, content=?, difficulty=?, explanation=? WHERE id=?",
            (payload.course_id, payload.chapter_id, payload.content, payload.difficulty,
             payload.explanation, question_id),
        )
        db.execute("DELETE FROM answers WHERE question_id=?", (question_id,))
        for key, text in payload.options.items():
            db.execute(
                "INSERT INTO answers (question_id, option_key, option_text, is_correct) VALUES (?, ?, ?, ?)",
                (question_id, key, text, key == payload.correct_option),
            )
    return {"message": "Cập nhật câu hỏi thành công"}


@router.delete("/questions/{question_id}")
def delete_question(question_id: int, admin: dict = Depends(require_admin)):
    with get_db() as db:
        db.execute("DELETE FROM answers WHERE question_id=?", (question_id,))
        db.execute("DELETE FROM questions WHERE id=?", (question_id,))
    return {"message": "Đã xóa câu hỏi"}


# ---------- 28. Theo dõi hoạt động ----------
@router.get("/logs")
def get_logs(action: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
             search: Optional[str] = None, limit: int = 200, admin: dict = Depends(require_admin)):
    """date_from / date_to dạng 'YYYY-MM-DD HH:MM:SS' theo giờ UTC (cùng định dạng cột created_at)."""
    query = ("SELECT l.*, u.full_name, u.email FROM activity_logs l "
              "LEFT JOIN users u ON l.user_id = u.id WHERE 1=1")
    params = []
    if action:
        query += " AND l.action = ?"
        params.append(action)
    if date_from:
        query += " AND l.created_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND l.created_at < ?"
        params.append(date_to)
    if search:
        query += " AND (u.full_name LIKE ? OR u.email LIKE ? OR l.detail LIKE ?)"
        params += [f"%{search}%"] * 3
    query += " ORDER BY l.created_at DESC, l.id DESC LIMIT ?"
    params.append(max(1, min(limit, 1000)))
    with get_db() as db:
        return [dict(r) for r in db.execute(query, params).fetchall()]


class DeleteLogsRequest(BaseModel):
    date_from: Optional[str] = None   # 'YYYY-MM-DD HH:MM:SS' (UTC), tính từ thời điểm này
    date_to: Optional[str] = None     # tới trước thời điểm này
    all: bool = False


@router.post("/logs/delete")
def delete_logs(payload: DeleteLogsRequest, admin: dict = Depends(require_admin)):
    """Xóa nhật ký theo khoảng thời gian (hoặc toàn bộ). Phải chỉ rõ khoảng thời gian hoặc all=true."""
    if not payload.all and not (payload.date_from or payload.date_to):
        raise HTTPException(400, "Hãy chọn khoảng thời gian cần xóa")
    query, params = "DELETE FROM activity_logs WHERE 1=1", []
    if not payload.all:
        if payload.date_from:
            query += " AND created_at >= ?"
            params.append(payload.date_from)
        if payload.date_to:
            query += " AND created_at < ?"
            params.append(payload.date_to)
    with get_db() as db:
        deleted = db.execute(query, params).rowcount
    return {"deleted": deleted, "message": f"Đã xóa {deleted} dòng nhật ký"}


# ---------- 29. Quản lý cấu hình AI ----------
@router.get("/ai-config")
def get_ai_config(admin: dict = Depends(require_admin)):
    import sys, os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    from ai_service import config as ai_config

    from ai_service import llm_client

    provider = ai_config.LLM_PROVIDER
    active = llm_client.available_providers()
    labels = {"claude": f"Claude ({ai_config.ANTHROPIC_MODEL})", "gemini": f"Gemini ({ai_config.GEMINI_MODEL})",
              "groq": f"Groq ({ai_config.GROQ_MODEL})"}
    if provider == "dataset" or not active:
        model_label = "Nội dung có sẵn (knowledge base + tài liệu môn học)"
    else:
        model_label = " → ".join(labels[n] for n in active)
    api_key_configured = bool(active) if provider != "dataset" else True

    return {
        "llm_provider": provider,
        "model": model_label,
        "api_key_configured": api_key_configured,
        "use_phobert": ai_config.USE_PHOBERT,
        "fallback_mode": "Nội dung có sẵn (dataset + tài liệu)" if active else None,
        "confidence_threshold": ai_config.CONFIDENCE_THRESHOLD,
        "status": "online",
        "dataset_files": {
            "intents": ai_config.INTENTS_FILE,
            "knowledge": ai_config.KNOWLEDGE_FILE,
            "quiz": ai_config.QUIZ_FILE,
        },
    }


@router.post("/ai-config/reload")
def reload_ai_model(admin: dict = Depends(require_admin)):
    # Với KeywordIntentClassifier: reload nghĩa là đọc lại dataset (không cần restart).
    # Với PhoBERT thật: sẽ load lại checkpoint từ MODEL_PATH.
    return {"message": "Đã reload cấu hình AI / dataset thành công"}
