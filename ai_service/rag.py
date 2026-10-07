import json
import math
import os
import re
import sqlite3
from collections import Counter
from contextlib import contextmanager

from . import config
from .preprocessing import clean_text, STOPWORDS

DB_PATH = os.path.join(config.BASE_DIR, "backend", "eduai.db")


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _tokenize(text: str) -> list:
    cleaned = clean_text(text)
    return [t for t in cleaned.split() if t not in STOPWORDS and len(t) > 1]


def _term_freq(text: str) -> Counter:
    return Counter(_tokenize(text))


def _load_knowledge_items():
    with open(config.KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("knowledge_base", [])


def _chunk_text(item: dict) -> list:
    basic = item.get("answer_basic", "").strip()
    detail = item.get("answer_detailed", "").strip()
    example = item.get("example", "").strip()
    chunks = []
    if basic:
        chunks.append(f"{item.get('topic', '')}: {basic}")
    if detail:
        tail = f" {example}" if example else ""
        chunks.append(f"{item.get('topic', '')}: {detail}{tail}")
    return chunks


def _find_document_id(conn, course_name: str, chapter_name: str):
    row = conn.execute(
        "SELECT d.id FROM documents d "
        "JOIN courses c ON d.course_id = c.id "
        "LEFT JOIN chapters ch ON d.chapter_id = ch.id "
        "WHERE c.name = ? AND (ch.name = ? OR d.chapter_id IS NULL) "
        "ORDER BY (ch.name = ?) DESC LIMIT 1",
        (course_name, chapter_name, chapter_name),
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "SELECT d.id FROM documents d JOIN courses c ON d.course_id = c.id "
        "WHERE c.name = ? LIMIT 1",
        (course_name,),
    ).fetchone()
    if row:
        return row["id"]
    return _create_knowledge_document(conn, course_name, chapter_name)


def _create_knowledge_document(conn, course_name: str, chapter_name: str):
    course_row = conn.execute("SELECT id FROM courses WHERE name = ?", (course_name,)).fetchone()
    if course_row is None:
        return None
    course_id = course_row["id"]
    chapter_row = conn.execute(
        "SELECT id FROM chapters WHERE course_id = ? AND name = ?", (course_id, chapter_name)
    ).fetchone()
    chapter_id = chapter_row["id"] if chapter_row else None
    title = f"Nội dung tổng hợp tri thức: {chapter_name}" if chapter_name else f"Nội dung tổng hợp tri thức: {course_name}"
    existing = conn.execute(
        "SELECT id FROM documents WHERE course_id = ? AND title = ?", (course_id, title)
    ).fetchone()
    if existing:
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO documents (course_id, chapter_id, title, file_type, file_path, status) "
        "VALUES (?, ?, ?, 'dataset', '', 'active')",
        (course_id, chapter_id, title),
    )
    return cur.lastrowid


def build_index() -> dict:
    items = _load_knowledge_items()
    inserted = 0
    skipped = 0
    with _connect() as conn:
        conn.execute("DELETE FROM document_chunks WHERE page_hint LIKE 'kb%' OR page_hint = '' OR page_hint IS NULL")
        for item in items:
            document_id = _find_document_id(conn, item.get("course", ""), item.get("chapter", ""))
            if document_id is None:
                skipped += 1
                continue
            for idx, chunk_content in enumerate(_chunk_text(item)):
                tf = _term_freq(chunk_content)
                conn.execute(
                    "INSERT INTO document_chunks (document_id, content, chunk_index, "
                    "vector_embedding, page_hint) VALUES (?, ?, ?, ?, ?)",
                    (document_id, chunk_content, idx, json.dumps(tf), item.get("id", "")),
                )
                inserted += 1
    return {"chunks_indexed": inserted, "knowledge_items_skipped": skipped,
            "total_knowledge_items": len(items)}


def _cosine(vec_a: dict, idf_a_terms: set, vec_b: dict) -> float:
    common = set(vec_a) & set(vec_b)
    if not common:
        return 0.0
    dot = sum(vec_a[t] * vec_b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


_CORPUS_CACHE = {}


def _load_corpus(conn, course):
    """Nạp (và nhớ) toàn bộ chunk + IDF theo môn; tự nạp lại khi bảng document_chunks thay đổi."""
    sig = conn.execute("SELECT COUNT(*) c, COALESCE(MAX(id), 0) m FROM document_chunks").fetchone()
    key = (sig["c"], sig["m"])
    hit = _CORPUS_CACHE.get(course)
    if hit and hit["key"] == key:
        return hit

    sql = (
        "SELECT dc.id, dc.content, dc.vector_embedding, dc.page_hint, "
        "dc.chunk_index, d.id as document_id, d.title as document_title, c.name as course_name, ch.name as chapter_name "
        "FROM document_chunks dc "
        "JOIN documents d ON dc.document_id = d.id "
        "JOIN courses c ON d.course_id = c.id "
        "LEFT JOIN chapters ch ON d.chapter_id = ch.id"
    )
    params = []
    if course:
        sql += " WHERE c.name = ?"
        params.append(course)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    doc_freq = Counter()
    for row in rows:
        row["tf"] = json.loads(row["vector_embedding"]) if row["vector_embedding"] else {}
        row.pop("vector_embedding", None)
        for term in row["tf"]:
            doc_freq[term] += 1
    n_docs = len(rows)
    idf = {term: math.log((1 + n_docs) / (1 + df)) + 1 for term, df in doc_freq.items()}
    for row in rows:
        row["vec"] = {term: freq * idf.get(term, 0) for term, freq in row["tf"].items()}
        row["norm"] = math.sqrt(sum(v * v for v in row["vec"].values()))
    entry = {"key": key, "rows": rows, "idf": idf, "n": n_docs}
    _CORPUS_CACHE[course] = entry
    return entry


def _page_of(page_hint: str):
    """page_hint dạng 'doc:MON/ten_file.pdf:p12' -> 12."""
    if page_hint and ":p" in page_hint:
        tail = page_hint.rsplit(":p", 1)[1]
        if tail.isdigit():
            return int(tail)
    return None


def search(query: str, course: str = None, top_k: int = 3) -> list:
    with _connect() as conn:
        corpus = _load_corpus(conn, course)
    rows, idf, n_docs = corpus["rows"], corpus["idf"], corpus["n"]
    if not rows:
        return []

    query_tf = _term_freq(query)
    query_vec = {term: freq * idf.get(term, math.log(1 + n_docs) + 1) for term, freq in query_tf.items()}
    q_norm = math.sqrt(sum(v * v for v in query_vec.values()))
    if q_norm == 0:
        return []

    scored = []
    for row in rows:
        if row["norm"] == 0:
            continue
        common = set(query_vec) & set(row["vec"])
        if not common:
            continue
        dot = sum(query_vec[t] * row["vec"][t] for t in common)
        scored.append((dot / (q_norm * row["norm"]), row))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, row in scored[:top_k]:
        results.append({
            "chunk_id": row["id"],
            "document_id": row["document_id"],
            "chunk_index": row["chunk_index"],
            "content": row["content"],
            "document_title": row["document_title"],
            "course": row["course_name"],
            "chapter": row["chapter_name"],
            "page": _page_of(row["page_hint"]),
            "score": round(score, 4),
        })
    return results


def following_chunks(document_id: int, chunk_index: int, n: int = 2) -> list:
    """Các chunk liền sau một chunk trong cùng tài liệu (để ghép thêm ngữ cảnh khi đoạn tìm được quá ngắn)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT content FROM document_chunks WHERE document_id = ? AND chunk_index > ? "
            "ORDER BY chunk_index LIMIT ?", (document_id, chunk_index, n),
        ).fetchall()
    return [r["content"] for r in rows]


_BULLET_JUNK = re.compile(r"^(?:[•◦❖➢➔→✓✔§Øð\-–·*]+\s*|v(?=[A-ZÀ-Ỹ]))+")


def clean_slide_line(line: str) -> str:
    """Bỏ ký tự đầu dòng/font lạ thường gặp khi trích chữ từ slide (vd: 'vMô hình' -> 'Mô hình')."""
    return _BULLET_JUNK.sub("", " ".join(line.split())).strip()


def _find_document(conn, title_query: str = None, course_name: str = None, chapter_no: int = None):
    """Tìm tài liệu theo tên file, tên chương, hoặc 'chương N' của một môn."""
    docs = conn.execute(
        "SELECT d.id, d.title, c.name AS course_name, ch.name AS chapter_name FROM documents d "
        "JOIN courses c ON d.course_id = c.id LEFT JOIN chapters ch ON d.chapter_id = ch.id "
        "WHERE d.status = 'active' AND EXISTS (SELECT 1 FROM document_chunks dc WHERE dc.document_id = d.id)"
    ).fetchall()
    if title_query:
        needle = title_query.strip().lower()
        for d in docs:
            if d["title"].lower() == needle or (d["chapter_name"] or "").lower() == needle:
                return d
        for d in docs:
            if needle and (needle in d["title"].lower() or needle in (d["chapter_name"] or "").lower()):
                return d
    if course_name and chapter_no:
        pattern = re.compile(r"(chuong|chương|chapter|ch|bai|bài)[\s_\-.]*0*%d(?!\d)" % chapter_no, re.IGNORECASE)
        for d in docs:
            if d["course_name"].lower() == course_name.lower() and pattern.search(d["title"]):
                return d
    return None


def document_outline(title_query: str = None, max_points: int = 8, course_name: str = None, chapter_no: int = None):
    """Lấy các ý chính (dòng đầu của chunk, rải đều) của một tài liệu/chương."""
    with _connect() as conn:
        doc = _find_document(conn, title_query, course_name, chapter_no)
        if doc is None:
            return None
        chunks = conn.execute(
            "SELECT content FROM document_chunks WHERE document_id = ? ORDER BY chunk_index", (doc["id"],)
        ).fetchall()
    step = max(1, len(chunks) // max_points)
    points = []
    for ch in chunks[::step][:max_points]:
        for line in ch["content"].splitlines():
            line = clean_slide_line(line).lstrip("0123456789. )").strip()
            letters = sum(ch2.isalpha() for ch2 in line)
            if len(line) >= 15 and letters >= 10 and line not in points:
                points.append(line[:160])
                break
    return {"title": doc["title"], "course": doc["course_name"], "points": points, "chunks": len(chunks)}


def course_names() -> list:
    with _connect() as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM courses WHERE status = 'active'").fetchall()]


def index_stats() -> dict:
    with _connect() as conn:
        total_chunks = conn.execute("SELECT COUNT(*) c FROM document_chunks").fetchone()["c"]
        total_documents = conn.execute(
            "SELECT COUNT(DISTINCT document_id) c FROM document_chunks"
        ).fetchone()["c"]
    return {"total_chunks": total_chunks, "documents_indexed": total_documents}
