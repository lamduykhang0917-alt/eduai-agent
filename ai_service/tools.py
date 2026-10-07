"""
tools.py
Bộ công cụ (tools) mà AI Agent của EduAI được phép gọi.

NGUYÊN TẮC AN TOÀN
  - `user_id` luôn do backend lấy từ token đăng nhập và truyền vào; LLM không bao giờ
    được chọn user_id, nên Agent không thể đọc/ghi dữ liệu của sinh viên khác.
  - Công cụ ghi dữ liệu quan trọng/khó hoàn tác (nộp bài, xóa ghi chú) nằm trong
    CONFIRMATION_REQUIRED: Agent chỉ đề xuất, sinh viên bấm xác nhận thì mới thực thi.
  - Kết quả công cụ là DỮ LIỆU, không phải chỉ thị; system prompt dặn Agent không làm
    theo các câu lệnh nằm trong nội dung tài liệu.

CÁCH THÊM CÔNG CỤ MỚI: viết một hàm nhận (args, user_id) và gắn @tool(...). Công cụ tự
xuất hiện trong TOOL_DEFINITIONS và trang cấu hình Agent của admin.
"""

import os
import random
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config
from . import rag

DB_PATH = os.path.join(config.BASE_DIR, "backend", "eduai.db")


class ToolError(Exception):
    """Lỗi có thể giải thích cho sinh viên / để Agent tự sửa tham số và gọi lại."""


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ đăng ký công cụ
REGISTRY = {}          # name -> {"fn", "label", "confirm", "definition"}


def tool(name, label, description, properties=None, required=(), confirm=False):
    def wrap(fn):
        REGISTRY[name] = {
            "fn": fn, "label": label, "confirm": confirm,
            "definition": {
                "name": name, "description": description,
                "parameters": {"type": "object", "properties": properties or {}, "required": list(required)},
            },
        }
        return fn
    return wrap


# ------------------------------------------------------------------ tiện ích
def _int(value, default, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _text(value, max_len):
    return str(value or "").strip()[:max_len]


def _course_row(conn, name):
    """Tìm môn theo tên/mã (không phân biệt hoa thường, cho phép gõ một phần tên)."""
    name = _text(name, 120)
    if not name:
        return None
    rows = conn.execute("SELECT id, code, name FROM courses WHERE status = 'active'").fetchall()
    low = name.lower()
    for r in rows:
        if low in (r["name"].lower(), r["code"].lower()):
            return r
    matches = [r for r in rows if low in r["name"].lower() or r["name"].lower() in low]
    if len(matches) == 1:
        return matches[0]
    names = ", ".join(r["name"] for r in rows)
    raise ToolError(f"Không xác định được môn học '{name}'. Các môn hiện có: {names}")


def _chapter_row(conn, course_id, chapter):
    chapter = _text(chapter, 200)
    if not chapter:
        return None
    rows = conn.execute("SELECT id, name FROM chapters WHERE course_id = ?", (course_id,)).fetchall()
    low = chapter.lower()
    for r in rows:
        if r["name"].lower() == low:
            return r
    m = re.search(r"\d+", chapter)
    if m:  # "chương 2" → chương có số 2 trong tên
        pat = re.compile(r"(chương|chuong|chapter|bài|bai)\s*0*%d(?!\d)" % int(m.group()), re.IGNORECASE)
        for r in rows:
            if pat.search(r["name"]):
                return r
    matches = [r for r in rows if low in r["name"].lower()]
    if len(matches) >= 1:
        return matches[0]
    raise ToolError("Không tìm thấy chương '%s'. Các chương của môn này: %s"
                    % (chapter, "; ".join(r["name"] for r in rows) or "(chưa có)"))


def _clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n].rstrip() + "…"


# ------------------------------------------------------------------ 1. Môn học & tài liệu
@tool("list_courses", "Xem danh sách môn học",
      "Liệt kê các môn học đang có (mã môn, tên môn, số chương, số tài liệu). Nếu truyền `course` thì "
      "liệt kê thêm tên các chương của môn đó. Dùng khi cần biết tên môn/chương chính xác.",
      {"course": {"type": "string", "description": "Tên môn học để xem các chương (tùy chọn)"}})
def list_courses(args, user_id):
    with _connect() as conn:
        if args.get("course"):
            c = _course_row(conn, args["course"])
            chapters = [r["name"] for r in conn.execute(
                "SELECT name FROM chapters WHERE course_id = ? ORDER BY order_index, id", (c["id"],))]
            return {"course": c["name"], "code": c["code"], "chapters": chapters}
        rows = conn.execute(
            "SELECT c.code, c.name, "
            "(SELECT COUNT(*) FROM chapters ch WHERE ch.course_id = c.id) AS chapters, "
            "(SELECT COUNT(*) FROM documents d WHERE d.course_id = c.id AND d.status = 'active') AS documents "
            "FROM courses c WHERE c.status = 'active' ORDER BY c.name").fetchall()
        return {"courses": [dict(r) for r in rows]}


@tool("search_documents", "Tra cứu tài liệu",
      "Tìm các đoạn nội dung liên quan trong tài liệu/giáo trình và knowledge base theo câu hỏi hoặc chủ đề. "
      "Dùng khi sinh viên hỏi kiến thức, cần giải thích khái niệm, hoặc cần căn cứ để tóm tắt.",
      {"query": {"type": "string", "description": "Câu hỏi hoặc chủ đề cần tìm"},
       "course": {"type": "string", "description": "Tên môn học để lọc (tùy chọn)"}},
      ["query"])
def search_documents(args, user_id):
    query = _text(args.get("query"), 300)
    if not query:
        raise ToolError("Thiếu nội dung cần tìm.")
    course = None
    if args.get("course"):
        with _connect() as conn:
            course = _course_row(conn, args["course"])["name"]
    results = rag.search(query, course=course, top_k=4)
    if not results:
        return {"found": False, "message": "Không tìm thấy nội dung phù hợp trong tài liệu."}
    return {"found": True, "results": [
        {"document": r["document_title"], "course": r["course"], "chapter": r["chapter"],
         "page": r["page"], "content": _clip(r["content"], 700)} for r in results]}


@tool("summarize_document", "Tóm tắt tài liệu / chương",
      "Lấy các ý chính của một tài liệu hoặc một chương để tóm tắt. Truyền `title` (tên tài liệu/chương) "
      "hoặc `course` + `chapter_number`.",
      {"title": {"type": "string", "description": "Tên tài liệu hoặc chương"},
       "course": {"type": "string", "description": "Tên môn học"},
       "chapter_number": {"type": "integer", "description": "Số thứ tự chương"}})
def summarize_document(args, user_id):
    course = None
    if args.get("course"):
        with _connect() as conn:
            course = _course_row(conn, args["course"])["name"]
    chapter_no = _int(args.get("chapter_number"), 0, 0, 99) or None
    outline = rag.document_outline(args.get("title"), max_points=10, course_name=course, chapter_no=chapter_no)
    if not outline or not outline["points"]:
        return {"found": False, "message": "Không tìm thấy tài liệu phù hợp để tóm tắt."}
    return {"found": True, **outline}


# ------------------------------------------------------------------ 2. Quiz
def _bank(conn, course_id=None, chapter_id=None, difficulty=None):
    query = ("SELECT q.id, q.content, q.difficulty, q.explanation, q.chapter_id FROM questions q "
             "JOIN courses c ON c.id = q.course_id AND c.status = 'active' WHERE 1=1")
    params = []
    for col, val in (("q.course_id", course_id), ("q.chapter_id", chapter_id), ("q.difficulty", difficulty)):
        if val:
            query += f" AND {col} = ?"
            params.append(val)
    rows = [dict(r) for r in conn.execute(query, params)]
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    options = {}
    for a in conn.execute(
            f"SELECT question_id, option_key, option_text, is_correct FROM answers "
            f"WHERE question_id IN ({','.join('?' * len(ids))}) ORDER BY option_key", ids):
        options.setdefault(a["question_id"], []).append(a)
    result = []
    for r in rows:
        opts = options.get(r["id"], [])
        if len(opts) < 2 or not any(o["is_correct"] for o in opts):
            continue
        r["options"] = {o["option_key"]: o["option_text"] for o in opts}
        result.append(r)
    return result


def _quiz_questions(conn, quiz_id):
    return [dict(r) for r in conn.execute(
        "SELECT i.position AS number, q.id, q.content FROM quiz_items i "
        "JOIN questions q ON q.id = i.question_id WHERE i.quiz_id = ? ORDER BY i.position", (quiz_id,))]


def _quiz_with_options(conn, quiz_id):
    qs = _quiz_questions(conn, quiz_id)
    for q in qs:
        q["options"] = {a["option_key"]: a["option_text"] for a in conn.execute(
            "SELECT option_key, option_text FROM answers WHERE question_id = ? ORDER BY option_key", (q["id"],))}
    return qs


def _own_quiz(conn, quiz_id, user_id):
    row = conn.execute("SELECT * FROM quizzes WHERE id = ? AND user_id = ?", (quiz_id, user_id)).fetchone()
    if row is None:
        raise ToolError("Không tìm thấy bài kiểm tra này của bạn.")
    return row


def create_quiz(conn, user_id, course_id, chapter_id, num, difficulty):
    """Chọn ngẫu nhiên câu hỏi từ ngân hàng, lưu bài kiểm tra + danh sách câu hỏi, trả về (quiz_id, câu hỏi)."""
    diff = difficulty if difficulty in ("basic", "medium", "advanced") else None
    bank = _bank(conn, course_id, chapter_id, diff)
    if not bank:
        raise ToolError("Ngân hàng câu hỏi chưa có câu nào phù hợp với lựa chọn này.")
    selected = random.sample(bank, min(num, len(bank)))
    cur = conn.execute(
        "INSERT INTO quizzes (user_id, course_id, chapter_id, num_questions, difficulty) VALUES (?, ?, ?, ?, ?)",
        (user_id, course_id, chapter_id, len(selected), diff or "mixed"))
    quiz_id = cur.lastrowid
    for pos, q in enumerate(selected, 1):
        conn.execute("INSERT INTO quiz_items (quiz_id, position, question_id) VALUES (?, ?, ?)", (quiz_id, pos, q["id"]))
    return quiz_id, [{"number": i, "id": q["id"], "content": q["content"], "options": q["options"]}
                     for i, q in enumerate(selected, 1)], len(bank)


@tool("generate_quiz", "Tạo bài kiểm tra",
      "Tạo bài kiểm tra/câu hỏi ôn tập trắc nghiệm A/B/C/D từ ngân hàng câu hỏi theo môn, chương, độ khó. "
      "Bài quiz sẽ được hiển thị cho sinh viên làm ngay trong khung chat; KHÔNG chép lại câu hỏi vào câu trả lời.",
      {"course": {"type": "string", "description": "Tên môn học (bỏ trống = tất cả môn)"},
       "chapter": {"type": "string", "description": "Tên hoặc số chương (tùy chọn)"},
       "num_questions": {"type": "integer", "description": "Số câu, 1–20 (mặc định 5)"},
       "difficulty": {"type": "string", "enum": ["basic", "medium", "advanced"],
                      "description": "basic = cơ bản, medium = trung bình, advanced = nâng cao"}})
def generate_quiz(args, user_id):
    num = _int(args.get("num_questions"), 5, 1, 20)
    with _connect() as conn:
        course = _course_row(conn, args["course"]) if args.get("course") else None
        chapter = None
        if args.get("chapter"):
            if course is None:
                raise ToolError("Cần cho biết môn học khi chọn chương.")
            chapter = _chapter_row(conn, course["id"], args["chapter"])
        quiz_id, questions, available = create_quiz(
            conn, user_id, course["id"] if course else None, chapter["id"] if chapter else None,
            num, args.get("difficulty"))
        conn.execute("INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'generate_quiz', ?)",
                     (user_id, f"agent quiz_id={quiz_id} n={len(questions)}"))
    return {
        "quiz_id": quiz_id, "num_questions": len(questions), "available_in_bank": available,
        "course": course["name"] if course else "Tất cả môn", "chapter": chapter["name"] if chapter else None,
        "note": "Giao diện đã hiển thị bài quiz cho sinh viên làm; hãy báo ngắn gọn và mời sinh viên làm bài.",
        "_ui": {"type": "quiz", "quiz_id": quiz_id,
                "title": "Bài ôn tập " + (course["name"] if course else "tất cả môn")},
    }


@tool("get_quiz", "Xem lại bài kiểm tra",
      "Lấy danh sách câu hỏi (kèm đáp án A/B/C/D, chưa có đáp án đúng) của một bài kiểm tra đã tạo.",
      {"quiz_id": {"type": "integer"}}, ["quiz_id"])
def get_quiz(args, user_id):
    quiz_id = _int(args.get("quiz_id"), 0, 0, 10**9)
    with _connect() as conn:
        _own_quiz(conn, quiz_id, user_id)
        return {"quiz_id": quiz_id, "questions": _quiz_with_options(conn, quiz_id)}


def grade_and_save(user_id, quiz_id, answers, duration_seconds=0):
    """Chấm điểm và lưu kết quả (dùng chung cho API nộp bài của web và tool của Agent).

    `answers`: [{"question_id": int, "selected_option": "A"}]. Câu không trả lời tính là sai."""
    with _connect() as conn:
        _own_quiz(conn, quiz_id, user_id)
        if conn.execute("SELECT 1 FROM quiz_results WHERE quiz_id = ?", (quiz_id,)).fetchone():
            raise ToolError("Bài kiểm tra này đã được nộp trước đó.")
        items = [r["question_id"] for r in conn.execute(
            "SELECT question_id FROM quiz_items WHERE quiz_id = ? ORDER BY position", (quiz_id,))]
        chosen = {}
        for a in answers:
            try:
                qid = int(a.get("question_id"))
            except (TypeError, ValueError):
                continue
            opt = str(a.get("selected_option") or "").strip().upper()[:1]
            if opt and (not items or qid in items):
                chosen[qid] = opt
        qids = items or list(chosen)
        if not qids:
            raise ToolError("Chưa có câu trả lời nào để chấm.")

        marks = ",".join("?" * len(qids))
        info = {r["id"]: dict(r) for r in conn.execute(
            f"SELECT q.id, q.content, q.explanation, q.course_id, c.name AS course, ch.name AS chapter "
            f"FROM questions q LEFT JOIN courses c ON c.id = q.course_id "
            f"LEFT JOIN chapters ch ON ch.id = q.chapter_id WHERE q.id IN ({marks})", qids)}
        correct_key = {r["question_id"]: r["option_key"] for r in conn.execute(
            f"SELECT question_id, option_key FROM answers WHERE is_correct = 1 AND question_id IN ({marks})", qids)}

        details, correct_count = [], 0
        for qid in qids:
            if qid not in info:
                continue
            selected = chosen.get(qid)
            ok = selected is not None and selected == correct_key.get(qid)
            correct_count += ok
            details.append({"question_id": qid, "content": info[qid]["content"], "selected_option": selected,
                            "correct_option": correct_key.get(qid), "is_correct": ok,
                            "explanation": info[qid]["explanation"] or "", "course": info[qid]["course"],
                            "chapter": info[qid]["chapter"]})
        total = len(details)
        score = round(correct_count / total * 10, 2) if total else 0

        cur = conn.execute(
            "INSERT INTO quiz_results (quiz_id, user_id, score, correct_count, total_count, duration_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?)", (quiz_id, user_id, score, correct_count, total, max(0, int(duration_seconds or 0))))
        result_id = cur.lastrowid
        for d in details:
            conn.execute("INSERT INTO quiz_answers (quiz_result_id, question_id, selected_option, is_correct) "
                         "VALUES (?, ?, ?, ?)", (result_id, d["question_id"], d["selected_option"], d["is_correct"]))
        _refresh_progress(conn, user_id, {info[d["question_id"]]["course_id"] for d in details
                                          if info[d["question_id"]]["course_id"]})
        conn.execute("INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'submit_quiz', ?)",
                     (user_id, f"quiz_id={quiz_id} score={score}"))
    return {"result_id": result_id, "score": score, "correct_count": correct_count,
            "total_count": total, "details": details}


def _refresh_progress(conn, user_id, course_ids):
    """Tiến độ môn = % số câu hỏi khác nhau của môn mà sinh viên đã trả lời ĐÚNG ít nhất một lần."""
    for cid in course_ids:
        total = conn.execute("SELECT COUNT(*) FROM questions WHERE course_id = ?", (cid,)).fetchone()[0]
        mastered = conn.execute(
            "SELECT COUNT(DISTINCT qa.question_id) FROM quiz_answers qa "
            "JOIN quiz_results r ON r.id = qa.quiz_result_id JOIN questions q ON q.id = qa.question_id "
            "WHERE r.user_id = ? AND q.course_id = ? AND qa.is_correct = 1", (user_id, cid)).fetchone()[0]
        percent = round(min(100.0, mastered / total * 100), 1) if total else 0
        if conn.execute("SELECT 1 FROM learning_progress WHERE user_id = ? AND course_id = ?", (user_id, cid)).fetchone():
            conn.execute("UPDATE learning_progress SET percent_complete = ?, updated_at = CURRENT_TIMESTAMP "
                         "WHERE user_id = ? AND course_id = ?", (percent, user_id, cid))
        else:
            conn.execute("INSERT INTO learning_progress (user_id, course_id, percent_complete) VALUES (?, ?, ?)",
                         (user_id, cid, percent))


@tool("submit_quiz", "Nộp bài kiểm tra",
      "Nộp và chấm điểm một bài kiểm tra bằng các lựa chọn mà sinh viên đã nói trong chat. Đây là hành động ghi "
      "kết quả học tập nên hệ thống sẽ hỏi sinh viên xác nhận trước khi thực thi. Cần quiz_id và danh sách "
      "{number: số thứ tự câu, option: A/B/C/D}.",
      {"quiz_id": {"type": "integer"},
       "answers": {"type": "array", "description": "Danh sách đáp án đã chọn",
                   "items": {"type": "object", "properties": {
                       "number": {"type": "integer", "description": "Số thứ tự câu trong bài (bắt đầu từ 1)"},
                       "option": {"type": "string", "description": "A, B, C hoặc D"}},
                       "required": ["number", "option"]}}},
      ["quiz_id", "answers"], confirm=True)
def submit_quiz(args, user_id):
    quiz_id = _int(args.get("quiz_id"), 0, 0, 10**9)
    with _connect() as conn:
        _own_quiz(conn, quiz_id, user_id)
        by_number = {q["number"]: q["id"] for q in _quiz_questions(conn, quiz_id)}
    answers = []
    for a in args.get("answers") or []:
        qid = by_number.get(_int(a.get("number"), -1, -1, 10**6))
        if qid:
            answers.append({"question_id": qid, "selected_option": a.get("option")})
    return grade_and_save(user_id, quiz_id, answers)


# ------------------------------------------------------------------ 3. Kết quả & phân tích
@tool("get_quiz_history", "Xem lịch sử làm bài",
      "Lấy các bài kiểm tra gần đây của sinh viên (môn, điểm, số câu đúng, thời điểm).",
      {"limit": {"type": "integer", "description": "Số bài, 1–10 (mặc định 5)"}})
def get_quiz_history(args, user_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT r.id AS result_id, r.quiz_id, r.score, r.correct_count, r.total_count, r.submitted_at, "
            "COALESCE(c.name, 'Tất cả môn') AS course FROM quiz_results r JOIN quizzes z ON z.id = r.quiz_id "
            "LEFT JOIN courses c ON c.id = z.course_id WHERE r.user_id = ? ORDER BY r.submitted_at DESC, r.id DESC LIMIT ?",
            (user_id, _int(args.get("limit"), 5, 1, 10))).fetchall()
    return {"results": [dict(r) for r in rows]} if rows else {"results": [], "message": "Bạn chưa làm bài kiểm tra nào."}


@tool("analyze_result", "Phân tích kết quả bài làm",
      "Phân tích một lần làm bài: các câu sai, đáp án đúng, giải thích, chương liên quan. Không truyền "
      "result_id thì lấy bài làm gần nhất.",
      {"result_id": {"type": "integer"}})
def analyze_result(args, user_id):
    with _connect() as conn:
        if args.get("result_id"):
            r = conn.execute("SELECT * FROM quiz_results WHERE id = ? AND user_id = ?",
                             (_int(args["result_id"], 0, 0, 10**9), user_id)).fetchone()
        else:
            r = conn.execute("SELECT * FROM quiz_results WHERE user_id = ? ORDER BY submitted_at DESC, id DESC LIMIT 1",
                             (user_id,)).fetchone()
        if r is None:
            raise ToolError("Chưa có kết quả bài làm nào để phân tích.")
        rows = conn.execute(
            "SELECT q.content, qa.selected_option, qa.is_correct, q.explanation, ch.name AS chapter, c.name AS course, "
            "(SELECT option_key FROM answers a WHERE a.question_id = q.id AND a.is_correct = 1) AS correct_option "
            "FROM quiz_answers qa JOIN questions q ON q.id = qa.question_id "
            "LEFT JOIN chapters ch ON ch.id = q.chapter_id LEFT JOIN courses c ON c.id = q.course_id "
            "WHERE qa.quiz_result_id = ?", (r["id"],)).fetchall()
    wrong = [{"question": _clip(x["content"], 300), "you_chose": x["selected_option"] or "(bỏ trống)",
              "correct": x["correct_option"], "explanation": _clip(x["explanation"], 300),
              "chapter": x["chapter"], "course": x["course"]} for x in rows if not x["is_correct"]]
    return {"result_id": r["id"], "score": r["score"], "correct": r["correct_count"], "total": r["total_count"],
            "wrong_questions": wrong}


def _weakness(conn, user_id, course_id=None):
    query = ("SELECT c.name AS course, ch.name AS chapter, COUNT(*) AS attempts, SUM(qa.is_correct) AS num_right "
             "FROM quiz_answers qa JOIN quiz_results r ON r.id = qa.quiz_result_id "
             "JOIN questions q ON q.id = qa.question_id LEFT JOIN courses c ON c.id = q.course_id "
             "LEFT JOIN chapters ch ON ch.id = q.chapter_id WHERE r.user_id = ?")
    params = [user_id]
    if course_id:
        query += " AND q.course_id = ?"
        params.append(course_id)
    query += " GROUP BY c.name, ch.name HAVING COUNT(*) >= 2"
    rows = [dict(r, accuracy=round((r["num_right"] or 0) / r["attempts"] * 100)) for r in conn.execute(query, params)]
    rows.sort(key=lambda r: (r["accuracy"], -r["attempts"]))
    return rows


@tool("analyze_weakness", "Phân tích điểm yếu",
      "Tìm các môn/chương sinh viên làm sai nhiều nhất dựa trên toàn bộ lịch sử làm bài (độ chính xác theo chương).",
      {"course": {"type": "string", "description": "Chỉ phân tích một môn (tùy chọn)"}})
def analyze_weakness(args, user_id):
    with _connect() as conn:
        course = _course_row(conn, args["course"]) if args.get("course") else None
        rows = _weakness(conn, user_id, course["id"] if course else None)
    if not rows:
        return {"found": False, "message": "Chưa đủ dữ liệu (cần làm thêm bài kiểm tra, mỗi chương ít nhất 2 câu)."}
    return {"found": True, "weakest": rows[:5], "strongest": [r for r in rows[::-1] if r["accuracy"] >= 70][:3]}


@tool("get_progress", "Xem tiến độ học tập",
      "Lấy tiến độ học tập: % hoàn thành từng môn, số bài đã làm, điểm trung bình, số ngày học, số tài liệu đã xem.")
def get_progress(args, user_id):
    with _connect() as conn:
        by_course = [dict(r) for r in conn.execute(
            "SELECT c.name AS course_name, p.percent_complete FROM learning_progress p "
            "JOIN courses c ON c.id = p.course_id WHERE p.user_id = ? ORDER BY p.percent_complete DESC", (user_id,))]
        total, avg = conn.execute("SELECT COUNT(*), AVG(score) FROM quiz_results WHERE user_id = ?", (user_id,)).fetchone()
        days = conn.execute("SELECT COUNT(DISTINCT date(created_at)) FROM activity_logs WHERE user_id = ? "
                            "AND action NOT IN ('login','logout')", (user_id,)).fetchone()[0]
        docs = conn.execute("SELECT COUNT(DISTINCT detail) FROM activity_logs WHERE user_id = ? "
                            "AND action = 'view_document'", (user_id,)).fetchone()[0]
    return {"by_course": by_course, "quizzes_completed": total, "average_score": round(avg, 2) if avg else 0,
            "study_days": days, "documents_viewed": docs}


@tool("get_recommendation", "Gợi ý nội dung nên học",
      "Gợi ý nên học/ôn gì tiếp theo, dựa trên điểm yếu theo chương, tiến độ các môn và các gợi ý đã lưu.")
def get_recommendation(args, user_id):
    with _connect() as conn:
        weak = [w for w in _weakness(conn, user_id) if w["accuracy"] < 70][:3]
        low = conn.execute(
            "SELECT c.name, p.percent_complete FROM learning_progress p JOIN courses c ON c.id = p.course_id "
            "WHERE p.user_id = ? ORDER BY p.percent_complete LIMIT 2", (user_id,)).fetchall()
        saved = [dict(r) for r in conn.execute(
            "SELECT content, reason FROM recommendations WHERE user_id = ? ORDER BY created_at DESC LIMIT 3", (user_id,))]
    items = [{"content": f"Ôn lại {w['chapter'] or 'nội dung'} môn {w['course']} (đúng {w['accuracy']}% trong "
                         f"{w['attempts']} câu đã làm).", "reason": "Điểm yếu từ lịch sử làm bài"} for w in weak]
    items += [{"content": f"Tăng tiến độ môn {r['name']} (hiện {r['percent_complete']}%).",
               "reason": "Môn có tiến độ thấp nhất"} for r in low]
    items += saved
    if not items:
        items = [{"content": "Hãy làm một bài kiểm tra ngắn ở môn bạn đang học để hệ thống đánh giá trình độ.",
                  "reason": "Chưa có dữ liệu học tập"}]
    return {"recommendations": items[:6]}


# ------------------------------------------------------------------ 4. Kế hoạch học tập
def _valid_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ToolError(f"Ngày '{value}' không hợp lệ, cần dạng YYYY-MM-DD.")


@tool("create_study_plan", "Lập kế hoạch học tập",
      "Lưu một kế hoạch học tập gồm danh sách việc cần làm (kèm hạn). Kế hoạch cũ đang hoạt động sẽ được lưu trữ. "
      "Chỉ gọi sau khi đã biết mục tiêu và thời gian của sinh viên.",
      {"title": {"type": "string"}, "goal": {"type": "string", "description": "Mục tiêu của kế hoạch"},
       "tasks": {"type": "array", "description": "Tối đa 20 việc",
                 "items": {"type": "object", "properties": {
                     "title": {"type": "string"}, "course": {"type": "string", "description": "Tên môn (tùy chọn)"},
                     "due_date": {"type": "string", "description": "YYYY-MM-DD"}}, "required": ["title"]}}},
      ["title", "tasks"])
def create_study_plan(args, user_id):
    tasks = [t for t in (args.get("tasks") or []) if _text(t.get("title"), 200)][:20]
    if not tasks:
        raise ToolError("Kế hoạch cần có ít nhất một việc.")
    with _connect() as conn:
        rows = []
        for t in tasks:
            course = _course_row(conn, t["course"]) if t.get("course") else None
            rows.append((_text(t["title"], 200), course["id"] if course else None, _valid_date(t.get("due_date"))))
        conn.execute("UPDATE study_plans SET status = 'archived' WHERE user_id = ? AND status = 'active'", (user_id,))
        plan_id = conn.execute("INSERT INTO study_plans (user_id, title, goal) VALUES (?, ?, ?)",
                               (user_id, _text(args.get("title"), 150) or "Kế hoạch học tập", _text(args.get("goal"), 300))).lastrowid
        for title, cid, due in rows:
            conn.execute("INSERT INTO study_tasks (plan_id, user_id, title, course_id, due_date) VALUES (?, ?, ?, ?, ?)",
                         (plan_id, user_id, title, cid, due))
        conn.execute("INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'study_plan', ?)",
                     (user_id, _text(args.get("title"), 100)))
    return {"plan_id": plan_id, "tasks_created": len(rows), "message": "Đã lưu kế hoạch, xem tại trang Kế hoạch & Ghi chú."}


@tool("get_study_plan", "Xem kế hoạch học tập",
      "Xem kế hoạch học tập đang hoạt động và trạng thái từng việc (đã xong/chưa, hạn).")
def get_study_plan(args, user_id):
    with _connect() as conn:
        plan = conn.execute("SELECT id, title, goal, created_at FROM study_plans WHERE user_id = ? AND status = 'active' "
                            "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if plan is None:
            return {"found": False, "message": "Bạn chưa có kế hoạch học tập."}
        tasks = [dict(r) for r in conn.execute(
            "SELECT t.id AS task_id, t.title, c.name AS course, t.due_date, t.done FROM study_tasks t "
            "LEFT JOIN courses c ON c.id = t.course_id WHERE t.plan_id = ? ORDER BY t.done, t.due_date, t.id", (plan["id"],))]
    return {"found": True, "plan": dict(plan), "tasks": tasks,
            "done": sum(1 for t in tasks if t["done"]), "total": len(tasks)}


@tool("update_study_task", "Đánh dấu việc trong kế hoạch",
      "Đánh dấu một việc trong kế hoạch là đã xong hoặc chưa xong.",
      {"task_id": {"type": "integer"}, "done": {"type": "boolean"}}, ["task_id", "done"])
def update_study_task(args, user_id):
    done = args.get("done") in (True, "true", "True", 1)
    with _connect() as conn:
        cur = conn.execute("UPDATE study_tasks SET done = ?, completed_at = CASE WHEN ? THEN CURRENT_TIMESTAMP END "
                           "WHERE id = ? AND user_id = ?", (done, done, _int(args.get("task_id"), 0, 0, 10**9), user_id))
        if cur.rowcount == 0:
            raise ToolError("Không tìm thấy việc này trong kế hoạch của bạn.")
    return {"task_id": args["task_id"], "done": done}


# ------------------------------------------------------------------ 5. Ghi chú
@tool("save_note", "Lưu ghi chú",
      "Lưu một ghi chú học tập (ví dụ tóm tắt, công thức, ý chính) vào sổ ghi chú của sinh viên.",
      {"title": {"type": "string"}, "content": {"type": "string", "description": "Nội dung (Markdown)"},
       "course": {"type": "string", "description": "Tên môn (tùy chọn)"}}, ["title", "content"])
def save_note(args, user_id):
    title, content = _text(args.get("title"), 150), _text(args.get("content"), 6000)
    if not title or not content:
        raise ToolError("Ghi chú cần có tiêu đề và nội dung.")
    with _connect() as conn:
        course = _course_row(conn, args["course"]) if args.get("course") else None
        note_id = conn.execute("INSERT INTO student_notes (user_id, course_id, title, content) VALUES (?, ?, ?, ?)",
                               (user_id, course["id"] if course else None, title, content)).lastrowid
    return {"note_id": note_id, "message": "Đã lưu ghi chú."}


@tool("list_notes", "Xem ghi chú",
      "Liệt kê/tìm ghi chú của sinh viên theo môn hoặc từ khóa.",
      {"course": {"type": "string"}, "keyword": {"type": "string"}})
def list_notes(args, user_id):
    query = ("SELECT n.id AS note_id, n.title, n.content, c.name AS course, n.created_at FROM student_notes n "
             "LEFT JOIN courses c ON c.id = n.course_id WHERE n.user_id = ?")
    params = [user_id]
    with _connect() as conn:
        if args.get("course"):
            query += " AND n.course_id = ?"
            params.append(_course_row(conn, args["course"])["id"])
        if args.get("keyword"):
            query += " AND (n.title LIKE ? OR n.content LIKE ?)"
            params += [f"%{_text(args['keyword'], 80)}%"] * 2
        rows = conn.execute(query + " ORDER BY n.id DESC LIMIT 10", params).fetchall()
    return {"notes": [dict(r, content=_clip(r["content"], 400)) for r in rows]}


@tool("delete_note", "Xóa ghi chú",
      "Xóa một ghi chú của sinh viên. Hành động không hoàn tác được nên cần sinh viên xác nhận.",
      {"note_id": {"type": "integer"}}, ["note_id"], confirm=True)
def delete_note(args, user_id):
    with _connect() as conn:
        cur = conn.execute("DELETE FROM student_notes WHERE id = ? AND user_id = ?",
                           (_int(args.get("note_id"), 0, 0, 10**9), user_id))
        if cur.rowcount == 0:
            raise ToolError("Không tìm thấy ghi chú này của bạn.")
    return {"deleted": True}


# ------------------------------------------------------------------ giao diện công khai cho agent.py
TOOL_DEFINITIONS = [t["definition"] for t in REGISTRY.values()]
CONFIRMATION_REQUIRED = {name for name, t in REGISTRY.items() if t["confirm"]}


def label(name: str) -> str:
    return REGISTRY[name]["label"] if name in REGISTRY else name


def describe_action(name: str, args: dict, user_id: int) -> str:
    """Mô tả dễ hiểu hành động đang chờ xác nhận (hiển thị trong hộp thoại xác nhận)."""
    try:
        with _connect() as conn:
            if name == "submit_quiz":
                n = len(args.get("answers") or [])
                total = conn.execute("SELECT COUNT(*) FROM quiz_items WHERE quiz_id = ?",
                                     (_int(args.get("quiz_id"), 0, 0, 10**9),)).fetchone()[0]
                return f"Nộp bài kiểm tra #{args.get('quiz_id')} với {n}/{total or n} câu đã trả lời. Sau khi nộp không thể làm lại bài này."
            if name == "delete_note":
                row = conn.execute("SELECT title FROM student_notes WHERE id = ? AND user_id = ?",
                                   (_int(args.get("note_id"), 0, 0, 10**9), user_id)).fetchone()
                return f"Xóa ghi chú “{row['title']}”. Không thể khôi phục." if row else "Xóa một ghi chú."
    except sqlite3.Error:
        pass
    return f"Thực hiện: {label(name)}"


def execute(name: str, arguments: dict, user_id: int) -> dict:
    entry = REGISTRY.get(name)
    if entry is None:
        raise ToolError(f"Công cụ không tồn tại: {name}")
    if not isinstance(arguments, dict):
        raise ToolError("Tham số không hợp lệ.")
    return entry["fn"](arguments, user_id)
