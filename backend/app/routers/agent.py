import json
import os
import sys
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from ai_service import agent as ai_agent  # noqa: E402
from ai_service import llm_client  # noqa: E402
from ai_service import rag as ai_rag  # noqa: E402
from ai_service import tools as ai_tools  # noqa: E402
from ai_service.inference import generate_response  # noqa: E402

from ..core.database import get_db
from ..core.security import get_current_user, require_admin

router = APIRouter(prefix="/api/agent", tags=["agent"])
admin_router = APIRouter(prefix="/api/admin/agent", tags=["admin-agent"])

# Giới hạn tần suất: bảo vệ hạn mức API miễn phí khỏi việc gọi dồn dập (mỗi người dùng).
RATE_LIMIT = 20
RATE_WINDOW_SECONDS = 300
_recent_calls = defaultdict(deque)


def _check_rate_limit(user_id: int):
    now, calls = time.time(), _recent_calls[user_id]
    while calls and now - calls[0] > RATE_WINDOW_SECONDS:
        calls.popleft()
    if len(calls) >= RATE_LIMIT:
        raise HTTPException(429, "Bạn gửi yêu cầu cho Agent quá nhanh, vui lòng thử lại sau vài phút.")
    calls.append(now)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: Optional[int] = None
    course: Optional[str] = None


class AgentConfirmRequest(BaseModel):
    task_id: int
    approve: bool


def _load_history(session_id: int, limit: int = 8) -> list:
    with get_db() as db:
        rows = db.execute(
            "SELECT sender, content FROM chat_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [{"role": "assistant" if r["sender"] == "ai" else "user", "content": r["content"]}
            for r in reversed(rows)]


def _ensure_session(session_id: Optional[int], user_id: int, title: str) -> int:
    with get_db() as db:
        if session_id is None:
            return db.execute(
                "INSERT INTO chat_sessions (user_id, course_id, title) VALUES (?, NULL, ?)",
                (user_id, title[:40]),
            ).lastrowid
        owner = db.execute("SELECT user_id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        if owner is None or owner["user_id"] != user_id:
            raise HTTPException(404, "Không tìm thấy cuộc trò chuyện")
        return session_id


def _save_message(session_id: int, sender: str, content: str, meta: dict = None):
    with get_db() as db:
        db.execute(
            "INSERT INTO chat_messages (session_id, sender, content, meta) VALUES (?, ?, ?, ?)",
            (session_id, sender, content, json.dumps(meta, ensure_ascii=False) if meta else None),
        )


def _fallback_chat(message: str, course: Optional[str], history: list, reason: str) -> dict:
    """Agent chưa dùng được (chưa có API key / hết lượt): trả lời bằng Chatbot thường để sinh viên không bị bỏ dở."""
    with get_db() as db:
        course_list = [r["name"] for r in db.execute("SELECT name FROM courses WHERE status = 'active'")]
    result = generate_response(message, course=course, level="basic", course_list=course_list, history=history[-6:])
    return {"task_id": None, "status": "fallback", "answer": result["answer"], "steps": [], "ui": [],
            "fallback": True, "notice": "Agent tạm thời không khả dụng nên mình trả lời ở chế độ Chatbot thường. " + reason}


@router.post("/chat")
def agent_chat(payload: AgentChatRequest, user: dict = Depends(get_current_user)):
    message = payload.message.strip()
    if not message:
        raise HTTPException(400, "Vui lòng nhập câu hỏi")
    _check_rate_limit(user["id"])

    session_id = _ensure_session(payload.session_id, user["id"], message)
    history = _load_history(session_id)
    _save_message(session_id, "user", message)

    try:
        result = ai_agent.run_agent(message, user["id"], course=payload.course, history=history,
                                    student_name=user.get("full_name"))
    except llm_client.LLMError as e:
        result = _fallback_chat(message, payload.course, history, f"(Chi tiết: {str(e)[:160]})")

    _save_message(session_id, "ai", result["answer"], {
        "steps": [{"label": s["label"], "success": s["success"]} for s in result.get("steps", [])],
        "ui": result.get("ui", []),
    } if (result.get("steps") or result.get("ui")) else None)
    with get_db() as db:
        db.execute("INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'agent_chat', ?)",
                   (user["id"], message[:100]))
    return {"session_id": session_id, **result}


@router.post("/confirm")
def agent_confirm(payload: AgentConfirmRequest, user: dict = Depends(get_current_user)):
    try:
        return ai_agent.confirm_action(payload.task_id, user["id"], payload.approve)
    except ai_tools.ToolError as e:
        raise HTTPException(400, str(e))


# ---------- Bài kiểm tra hiển thị trong khung chat ----------
@router.get("/quiz/{quiz_id}")
def agent_quiz(quiz_id: int, user: dict = Depends(get_current_user)):
    """Dữ liệu để vẽ lại thẻ quiz: câu hỏi + (nếu đã nộp) kết quả và giải thích từng câu."""
    with ai_tools._connect() as conn:
        try:
            ai_tools._own_quiz(conn, quiz_id, user["id"])
        except ai_tools.ToolError:
            raise HTTPException(404, "Không tìm thấy bài kiểm tra")
        questions = ai_tools._quiz_with_options(conn, quiz_id)
        res = conn.execute("SELECT id, score, correct_count, total_count FROM quiz_results WHERE quiz_id = ?",
                           (quiz_id,)).fetchone()
        result = None
        if res:
            details = conn.execute(
                "SELECT qa.question_id, qa.selected_option, qa.is_correct, q.explanation, "
                "(SELECT option_key FROM answers a WHERE a.question_id = q.id AND a.is_correct = 1) AS correct_option "
                "FROM quiz_answers qa JOIN questions q ON q.id = qa.question_id WHERE qa.quiz_result_id = ?",
                (res["id"],)).fetchall()
            result = {**dict(res), "details": [dict(d) for d in details]}
    return {"quiz_id": quiz_id, "questions": questions, "result": result}


# ---------- Kế hoạch học tập & ghi chú (xem/sửa trực tiếp trên trang web) ----------
class NoteRequest(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    content: str = Field(min_length=1, max_length=6000)
    course: Optional[str] = None


class TaskDoneRequest(BaseModel):
    done: bool


@router.get("/plan")
def get_plan(user: dict = Depends(get_current_user)):
    return ai_tools.get_study_plan({}, user["id"])


@router.patch("/plan/tasks/{task_id}")
def set_task_done(task_id: int, payload: TaskDoneRequest, user: dict = Depends(get_current_user)):
    try:
        return ai_tools.update_study_task({"task_id": task_id, "done": payload.done}, user["id"])
    except ai_tools.ToolError as e:
        raise HTTPException(404, str(e))


@router.get("/notes")
def get_notes(user: dict = Depends(get_current_user)):
    with get_db() as db:
        rows = db.execute(
            "SELECT n.id, n.title, n.content, n.created_at, c.name AS course FROM student_notes n "
            "LEFT JOIN courses c ON c.id = n.course_id WHERE n.user_id = ? ORDER BY n.id DESC", (user["id"],)
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/notes")
def add_note(payload: NoteRequest, user: dict = Depends(get_current_user)):
    try:
        return ai_tools.save_note(payload.model_dump(), user["id"])
    except ai_tools.ToolError as e:
        raise HTTPException(400, str(e))


@router.delete("/notes/{note_id}")
def remove_note(note_id: int, user: dict = Depends(get_current_user)):
    try:
        return ai_tools.delete_note({"note_id": note_id}, user["id"])
    except ai_tools.ToolError as e:
        raise HTTPException(404, str(e))


# ---------- Nhật ký task của sinh viên ----------
@router.get("/tasks")
def agent_tasks(user: dict = Depends(get_current_user)):
    with get_db() as db:
        rows = db.execute(
            "SELECT id, request_text, status, created_at, completed_at FROM agent_tasks "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT 50", (user["id"],)).fetchall()
        return [dict(r) for r in rows]


@router.get("/tasks/{task_id}/logs")
def agent_task_logs(task_id: int, user: dict = Depends(get_current_user)):
    with get_db() as db:
        if db.execute("SELECT id FROM agent_tasks WHERE id = ? AND user_id = ?", (task_id, user["id"])).fetchone() is None:
            raise HTTPException(404, "Không tìm thấy task")
        rows = db.execute(
            "SELECT tool_name, arguments, result, success, created_at FROM agent_tool_logs "
            "WHERE task_id = ? ORDER BY created_at", (task_id,)).fetchall()
        return [dict(r) for r in rows]


# ---------- Admin ----------
@admin_router.get("/logs")
def admin_agent_logs(tool_name: Optional[str] = None, admin: dict = Depends(require_admin)):
    query = (
        "SELECT l.id, l.tool_name, l.arguments, l.result, l.success, l.created_at, "
        "t.user_id, u.full_name, t.request_text FROM agent_tool_logs l "
        "JOIN agent_tasks t ON l.task_id = t.id JOIN users u ON t.user_id = u.id"
    )
    params = []
    if tool_name:
        query += " WHERE l.tool_name = ?"
        params.append(tool_name)
    query += " ORDER BY l.created_at DESC LIMIT 200"
    with get_db() as db:
        return [dict(r) for r in db.execute(query, params).fetchall()]


@admin_router.get("/tasks")
def admin_agent_tasks(status: Optional[str] = None, admin: dict = Depends(require_admin)):
    query = (
        "SELECT t.id, t.request_text, t.status, t.created_at, t.completed_at, "
        "u.full_name, u.email FROM agent_tasks t JOIN users u ON t.user_id = u.id"
    )
    params = []
    if status:
        query += " WHERE t.status = ?"
        params.append(status)
    query += " ORDER BY t.created_at DESC LIMIT 200"
    with get_db() as db:
        return [dict(r) for r in db.execute(query, params).fetchall()]


class PromptTemplateRequest(BaseModel):
    name: str
    content: str


@admin_router.get("/prompts")
def list_prompts(admin: dict = Depends(require_admin)):
    with get_db() as db:
        rows = db.execute("SELECT * FROM prompt_templates ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


@admin_router.get("/prompts/default")
def default_prompt(admin: dict = Depends(require_admin)):
    """Prompt mặc định của Agent (sửa bằng cách lưu một prompt tên `agent_system`)."""
    return {"name": "agent_system", "content": ai_agent.DEFAULT_SYSTEM_PROMPT}


@admin_router.post("/prompts")
def upsert_prompt(payload: PromptTemplateRequest, admin: dict = Depends(require_admin)):
    with get_db() as db:
        existing = db.execute("SELECT id, version FROM prompt_templates WHERE name = ?", (payload.name,)).fetchone()
        if existing:
            db.execute(
                "UPDATE prompt_templates SET content = ?, version = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (payload.content, existing["version"] + 1, existing["id"]))
            return {"id": existing["id"], "message": "Đã cập nhật prompt"}
        cur = db.execute("INSERT INTO prompt_templates (name, content) VALUES (?, ?)", (payload.name, payload.content))
        return {"id": cur.lastrowid, "message": "Đã tạo prompt mới"}


@admin_router.get("/rag/stats")
def rag_stats(admin: dict = Depends(require_admin)):
    return ai_rag.index_stats()


@admin_router.post("/rag/reindex")
def rag_reindex(admin: dict = Depends(require_admin)):
    return ai_rag.build_index()


@admin_router.get("/config")
def agent_config(admin: dict = Depends(require_admin)):
    from ai_service import config as ai_config
    return {
        "max_steps": ai_agent.MAX_STEPS,
        "tools": [{"name": t["name"], "label": ai_tools.label(t["name"]), "description": t["description"],
                   "needs_confirmation": t["name"] in ai_tools.CONFIRMATION_REQUIRED}
                  for t in ai_tools.TOOL_DEFINITIONS],
        "confirmation_required_tools": sorted(ai_tools.CONFIRMATION_REQUIRED),
        "llm_provider": ai_config.LLM_PROVIDER,
        "providers_ready": llm_client.available_providers(),
        "rag_index": ai_rag.index_stats(),
    }
