import os
import random
import sys
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from ai_service import tools as ai_tools  # noqa: E402

from ..core.database import get_db
from ..core.security import get_current_user

router = APIRouter(prefix="/api/quizzes", tags=["quizzes"])


def _db_questions(db, course=None, chapter=None, difficulty=None):
    """Đọc câu hỏi từ database (nguồn chính, admin có thể thêm/sửa/xóa)."""
    query = ("SELECT q.id, q.content, q.difficulty, q.explanation, c.name AS course, ch.name AS chapter "
             "FROM questions q JOIN courses c ON c.id = q.course_id AND c.status = 'active' "
             "LEFT JOIN chapters ch ON ch.id = q.chapter_id WHERE 1=1")
    params = []
    if course:
        query += " AND c.name = ?"
        params.append(course)
    if chapter:
        query += " AND ch.name = ?"
        params.append(chapter)
    if difficulty:
        query += " AND q.difficulty = ?"
        params.append(difficulty)
    rows = [dict(r) for r in db.execute(query, params).fetchall()]
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    options = {}
    for a in db.execute(
        f"SELECT question_id, option_key, option_text, is_correct FROM answers "
        f"WHERE question_id IN ({','.join('?' * len(ids))}) ORDER BY option_key", ids
    ).fetchall():
        options.setdefault(a["question_id"], []).append(a)
    result = []
    for r in rows:
        opts = options.get(r["id"], [])
        correct = next((o["option_key"] for o in opts if o["is_correct"]), None)
        if len(opts) < 2 or correct is None:
            continue  # câu hỏi chưa đủ đáp án thì không đưa vào bài kiểm tra
        r["options"] = {o["option_key"]: o["option_text"] for o in opts}
        r["correct_answer"] = correct
        r["explanation"] = r["explanation"] or ""
        result.append(r)
    return result


ALL_COURSES = "__all__"
HARD = ("medium", "advanced")


def _split_levels(bank):
    easy = [q for q in bank if q["difficulty"] == "basic"]
    hard = [q for q in bank if q["difficulty"] in HARD]
    return easy, hard


class GenerateQuizRequest(BaseModel):
    course: Optional[str] = None  # bỏ trống hoặc "__all__" = tất cả môn học
    chapter: Optional[str] = None
    num_questions: int = 5
    difficulty: Optional[str] = None
    # level1 (đơn giản) | level2 (khó) | level3 (trộn dễ-khó) | basic | medium | advanced


class SubmitQuizRequest(BaseModel):
    quiz_id: int
    answers: List[dict]  # [{"question_id": "q001", "selected_option": "B"}]
    duration_seconds: Optional[int] = 0


@router.get("")
def list_quizzes(user: dict = Depends(get_current_user)):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM quizzes WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)
        ).fetchall()
        return [dict(r) for r in rows]


@router.get("/meta")
def quiz_meta(user: dict = Depends(get_current_user)):
    """Số câu hỏi có sẵn theo môn và độ khó, để giao diện chỉ cho chọn những gì thực sự có."""
    meta = {}
    with get_db() as db:
        bank = _db_questions(db)

    def add(key, q):
        m = meta.setdefault(key, {"total": 0, "basic": 0, "medium": 0, "advanced": 0})
        m["total"] += 1
        if q["difficulty"] in m:
            m[q["difficulty"]] += 1

    for q in bank:
        add(q["course"], q)
        add(ALL_COURSES, q)
    for m in meta.values():
        m["level1"] = m["basic"]
        m["level2"] = m["medium"] + m["advanced"]
        m["level3"] = m["total"]
    return meta


@router.post("/generate")
def generate_quiz(payload: GenerateQuizRequest, user: dict = Depends(get_current_user)):
    with get_db() as db:
        course = None if payload.course in (None, "", ALL_COURSES) else payload.course
        diff = payload.difficulty
        legacy = diff if diff in ("basic", "medium", "advanced") else None
        filtered = _db_questions(db, course, payload.chapter, legacy)

    easy, hard = _split_levels(filtered)
    if diff == "level1":
        filtered = easy
    elif diff == "level2":
        filtered = hard
    if not filtered:
        raise HTTPException(404, "Chưa có câu hỏi phù hợp cho lựa chọn này trong ngân hàng câu hỏi")

    wanted = max(1, min(payload.num_questions, 50))
    if diff == "level3" and easy and hard:
        # Mức 3: trộn lẫn câu dễ và khó, thứ tự lộn xộn
        n = min(wanted, len(filtered))
        n_easy = min(len(easy), n // 2)
        n_hard = min(len(hard), n - n_easy)
        n_easy = min(len(easy), n - n_hard)
        selected = random.sample(easy, n_easy) + random.sample(hard, n_hard)
        random.shuffle(selected)
    else:
        selected = random.sample(filtered, min(wanted, len(filtered)))

    with get_db() as db:
        course_row = db.execute("SELECT id FROM courses WHERE name = ?", (course or "",)).fetchone()
        course_id = course_row["id"] if course_row else None
        cur = db.execute(
            "INSERT INTO quizzes (user_id, course_id, num_questions, difficulty) VALUES (?, ?, ?, ?)",
            (user["id"], course_id, len(selected), payload.difficulty or "mixed"),
        )
        quiz_id = cur.lastrowid
        for position, q in enumerate(selected, 1):
            db.execute("INSERT INTO quiz_items (quiz_id, position, question_id) VALUES (?, ?, ?)",
                       (quiz_id, position, q["id"]))

    return {
        "quiz_id": quiz_id,
        "requested": wanted,
        "available": len(filtered),
        "questions": [
            {
                "id": q["id"],
                "content": q["content"],
                "options": q["options"],
            }
            for q in selected
        ],
    }


@router.post("/submit")
def submit_quiz(payload: SubmitQuizRequest, user: dict = Depends(get_current_user)):
    try:
        return ai_tools.grade_and_save(user["id"], payload.quiz_id, payload.answers, payload.duration_seconds)
    except ai_tools.ToolError as e:
        raise HTTPException(400, str(e))
