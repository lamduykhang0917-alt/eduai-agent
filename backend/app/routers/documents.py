from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from ..core.database import get_db
from ..core.security import get_current_user

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("")
def list_documents(course_id: Optional[int] = None, chapter_id: Optional[int] = None,
                    search: Optional[str] = None, user: dict = Depends(get_current_user)):
    query = ("SELECT d.*, (SELECT COUNT(*) FROM document_chunks dc WHERE dc.document_id = d.id) AS chunk_count "
             "FROM documents d WHERE d.status = 'active'")
    params = []
    if course_id:
        query += " AND d.course_id = ?"
        params.append(course_id)
    if chapter_id:
        query += " AND d.chapter_id = ?"
        params.append(chapter_id)
    if search:
        query += " AND d.title LIKE ?"
        params.append(f"%{search}%")

    with get_db() as db:
        rows = db.execute(query, params).fetchall()
        return [dict(r) for r in rows]


@router.get("/{document_id}")
def get_document(document_id: int, user: dict = Depends(get_current_user)):
    with get_db() as db:
        row = db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Không tìm thấy tài liệu")
        db.execute(
            "INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'view_document', ?)",
            (user["id"], row["title"]),
        )
        return dict(row)


@router.get("/{document_id}/content")
def get_document_content(document_id: int, user: dict = Depends(get_current_user)):
    """Nội dung văn bản của tài liệu, chia theo trang/slide, để xem ngay trên web."""
    with get_db() as db:
        doc = db.execute(
            "SELECT d.id, d.title, d.file_type, d.updated_at, d.course_id, c.name AS course_name, "
            "ch.name AS chapter_name FROM documents d "
            "JOIN courses c ON d.course_id = c.id LEFT JOIN chapters ch ON d.chapter_id = ch.id "
            "WHERE d.id = ? AND d.status = 'active'",
            (document_id,),
        ).fetchone()
        if doc is None:
            raise HTTPException(404, "Không tìm thấy tài liệu")
        chunks = db.execute(
            "SELECT content, page_hint FROM document_chunks WHERE document_id = ? ORDER BY chunk_index",
            (document_id,),
        ).fetchall()
        db.execute(
            "INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'view_document', ?)",
            (user["id"], doc["title"]),
        )

    pages = []
    for ch in chunks:
        hint = ch["page_hint"] or ""
        page = int(hint.rsplit(":p", 1)[1]) if ":p" in hint and hint.rsplit(":p", 1)[1].isdigit() else None
        if pages and pages[-1]["page"] == page and page is not None:
            pages[-1]["text"] += "\n" + ch["content"]
        else:
            pages.append({"page": page, "text": ch["content"]})
    return {"document": dict(doc), "pages": pages}
