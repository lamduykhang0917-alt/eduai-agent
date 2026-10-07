from fastapi import APIRouter, Depends, HTTPException

from ..core.database import get_db
from ..core.security import get_current_user

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.get("")
def list_courses(user: dict = Depends(get_current_user)):
    with get_db() as db:
        rows = db.execute("SELECT * FROM courses WHERE status = 'active'").fetchall()
        result = []
        for r in rows:
            course = dict(r)
            chapters = db.execute(
                "SELECT COUNT(*) c FROM chapters WHERE course_id = ?", (course["id"],)
            ).fetchone()["c"]
            docs = db.execute(
                "SELECT COUNT(*) c FROM documents WHERE course_id = ? AND status = 'active'", (course["id"],)
            ).fetchone()["c"]
            progress = db.execute(
                "SELECT percent_complete FROM learning_progress WHERE user_id = ? AND course_id = ?",
                (user["id"], course["id"]),
            ).fetchone()
            course["chapter_count"] = chapters
            course["document_count"] = docs
            course["progress"] = progress["percent_complete"] if progress else 0
            result.append(course)
        return result


@router.get("/{course_id}")
def get_course(course_id: int, user: dict = Depends(get_current_user)):
    with get_db() as db:
        course = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        if course is None:
            raise HTTPException(404, "Không tìm thấy môn học")
        chapters = db.execute(
            "SELECT * FROM chapters WHERE course_id = ? ORDER BY order_index", (course_id,)
        ).fetchall()
        documents = db.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM document_chunks dc WHERE dc.document_id = d.id) AS chunk_count "
            "FROM documents d WHERE d.course_id = ? AND d.status = 'active' ORDER BY d.id", (course_id,)
        ).fetchall()
        documents = [dict(d) for d in documents]
        chapter_list = []
        for c in chapters:
            item = dict(c)
            item["document_ids"] = [d["id"] for d in documents if d["chapter_id"] == c["id"]]
            chapter_list.append(item)
        return {
            "course": dict(course),
            "chapters": chapter_list,
            "documents": documents,
        }
