"""
export_content_pack.py
Xuất nội dung tài liệu đã nạp (môn học, chương, tài liệu, các đoạn văn bản) ra file nén
dataset/content_pack.json.gz để đưa lên GitHub. Khi backend khởi động trên máy chủ mới
(Render), seed.py tự nạp gói này nên chatbot và trang Tài liệu có nội dung thật mà không
cần mang theo 260 MB file PDF/PPTX gốc.

Chạy (sau khi đã chạy ingest_documents):  python -m ai_service.export_content_pack
"""
import gzip
import json
import os
import sqlite3

from . import config

DB_PATH = os.path.join(config.BASE_DIR, "backend", "eduai.db")
PACK_PATH = os.path.join(config.DATASET_DIR, "content_pack.json.gz")


def export() -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    courses = conn.execute(
        "SELECT DISTINCT c.id, c.code, c.name, c.description FROM courses c "
        "JOIN documents d ON d.course_id = c.id "
        "WHERE EXISTS (SELECT 1 FROM document_chunks dc WHERE dc.document_id = d.id) ORDER BY c.id"
    ).fetchall()
    pack = {"version": 1, "courses": []}
    n_docs = n_chunks = 0
    for c in courses:
        chapters = conn.execute(
            "SELECT id, name, order_index FROM chapters WHERE course_id = ? ORDER BY order_index", (c["id"],)
        ).fetchall()
        chapter_name = {ch["id"]: ch["name"] for ch in chapters}
        docs = []
        for d in conn.execute(
            "SELECT id, title, file_type, file_path, chapter_id FROM documents "
            "WHERE course_id = ? AND status = 'active' ORDER BY id", (c["id"],)
        ).fetchall():
            chunks = conn.execute(
                "SELECT page_hint, content FROM document_chunks WHERE document_id = ? ORDER BY chunk_index",
                (d["id"],),
            ).fetchall()
            if not chunks:
                continue
            docs.append({
                "title": d["title"], "file_type": d["file_type"], "file_path": d["file_path"],
                "chapter": chapter_name.get(d["chapter_id"]),
                "chunks": [[ch["page_hint"], ch["content"]] for ch in chunks],
            })
            n_docs += 1
            n_chunks += len(chunks)
        pack["courses"].append({
            "code": c["code"], "name": c["name"], "description": c["description"],
            "chapters": [{"name": ch["name"], "order_index": ch["order_index"]} for ch in chapters],
            "documents": docs,
        })
    conn.close()
    with gzip.open(PACK_PATH, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(pack, f, ensure_ascii=False, separators=(",", ":"))
    return {"courses": len(pack["courses"]), "documents": n_docs, "chunks": n_chunks,
            "size_mb": round(os.path.getsize(PACK_PATH) / 1_048_576, 2)}


if __name__ == "__main__":
    print(json.dumps(export(), ensure_ascii=False, indent=2))
