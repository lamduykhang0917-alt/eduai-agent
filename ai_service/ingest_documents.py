import json
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager

from . import config
from . import extract_text
from .rag import _term_freq

DB_PATH = os.path.join(config.BASE_DIR, "backend", "eduai.db")
SOURCE_DIR = os.path.join(config.BASE_DIR, "dataset", "source_documents")

MAX_CHUNK_CHARS = 1100

SUBJECT_META = {
    "ADO.NET": {"course_name": "Lập trình .NET", "rebuild": True},
    "CAU_TRUC_DU_LIEU": {"course_name": "Cấu trúc dữ liệu và giải thuật", "rebuild": True},
    "GIAI_THUAT": {"course_name": "Cấu trúc dữ liệu và giải thuật", "rebuild": False},
    "CO_SO_DU_LIEU": {"course_name": "Cơ sở dữ liệu", "rebuild": True},
    "HE_QUAN_TRI_CO_SO_DU_LIEU": {"course_name": "Hệ quản trị cơ sở dữ liệu", "rebuild": True},
    "LAP_TRINH_HUONG_DOI_TUONG": {"course_name": "Lập trình hướng đối tượng", "rebuild": True},
    "TRI_TUE_NHAN_TAO": {"course_name": "Trí tuệ nhân tạo", "rebuild": True},
    "DIEN_TOAN_DAM_MAY": {
        "course_name": "Điện toán đám mây", "rebuild": False, "new_course": True,
        "code": "CLOUD101",
        "description": "Nền tảng điện toán đám mây: mô hình dịch vụ, ảo hóa, triển khai ứng dụng trên cloud.",
    },
    "DO_HOA_MAY_TINH": {
        "course_name": "Đồ họa máy tính", "rebuild": False, "new_course": True,
        "code": "CG101",
        "description": "Đồ họa máy tính 2D/3D: thuật toán nền tảng, dựng hình, hiển thị đối tượng.",
    },
    "KIEN_TRUC_MAY_TINH": {
        "course_name": "Kiến trúc máy tính", "rebuild": False, "new_course": True,
        "code": "COA101",
        "description": "Tổ chức và kiến trúc máy tính: CPU, bộ nhớ, thiết bị lưu trữ, hiệu năng hệ thống.",
    },
    "KY_THUAT_LAP_TRINH": {
        "course_name": "Kỹ thuật lập trình", "rebuild": False, "new_course": True,
        "code": "KTLT101",
        "description": "Kỹ thuật lập trình nền tảng: cấu trúc chương trình, phong cách code, xử lý lỗi.",
    },
    "MANG_MAY_TINH": {
        "course_name": "Mạng máy tính", "rebuild": False, "new_course": True,
        "code": "MMT101",
        "description": "Mạng máy tính: mô hình phân lớp, định tuyến, tầng giao vận/ứng dụng, an toàn mạng.",
    },
    "MAY_HOC": {
        "course_name": "Máy học", "rebuild": False, "new_course": True,
        "code": "ML101",
        "description": "Máy học: các thuật toán học có giám sát/không giám sát, đánh giá mô hình.",
    },
    "NHAP_MON_KHMT": {
        "course_name": "Nhập môn Khoa học máy tính", "rebuild": False, "new_course": True,
        "code": "KHMT101",
        "description": "Nhập môn ngành Khoa học máy tính: kiến trúc Von Neumann, Internet, các lĩnh vực KHMT.",
    },
    "TUONG_TAC_NGUOI_MAY": {
        "course_name": "Tương tác người máy", "rebuild": False, "new_course": True,
        "code": "HCI101",
        "description": "Tương tác người - máy (HCI): nguyên lý thiết kế giao diện, tổ chức tương tác, usability.",
    },
    "XU_LI_ANH": {
        "course_name": "Xử lý ảnh", "rebuild": False, "new_course": True,
        "code": "XLA101",
        "description": "Xử lý ảnh số: biểu diễn ảnh, các phép xử lý cơ bản, phát hiện biên, nén ảnh.",
    },
    "XU_LI_NGON_NGU_TU_NHIEN": {
        "course_name": "Xử lý ngôn ngữ tự nhiên", "rebuild": False, "new_course": True,
        "code": "NLP101",
        "description": "Xử lý ngôn ngữ tự nhiên: các bài toán và kỹ thuật NLP cơ bản.",
    },
}

REROUTE_FILES = {
    "Slide Bai giang Phan tich Thiet ke HTTT.pdf": "Phân tích thiết kế hệ thống",
}


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _clean_title(filename: str) -> str:
    name = os.path.splitext(filename)[0]
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name or filename


def _chunk_page(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 1 > max_chars:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def _get_or_create_course(conn, course_name: str, meta: dict) -> int:
    row = conn.execute("SELECT id FROM courses WHERE name = ?", (course_name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO courses (code, name, description, status) VALUES (?, ?, ?, 'active')",
        (meta["code"], course_name, meta["description"]),
    )
    return cur.lastrowid


def _clear_course_content(conn, course_id: int):
    conn.execute(
        "DELETE FROM document_chunks WHERE document_id IN "
        "(SELECT id FROM documents WHERE course_id = ?)",
        (course_id,),
    )
    conn.execute("DELETE FROM documents WHERE course_id = ?", (course_id,))
    conn.execute("DELETE FROM chapters WHERE course_id = ?", (course_id,))


def _insert_chapter(conn, course_id: int, name: str, order_index: int) -> int:
    existing = conn.execute(
        "SELECT id FROM chapters WHERE course_id = ? AND name = ?", (course_id, name)
    ).fetchone()
    if existing:
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO chapters (course_id, name, order_index) VALUES (?, ?, ?)",
        (course_id, name, order_index),
    )
    return cur.lastrowid


def run_ingest(log=print) -> dict:
    stats = {"courses_created": 0, "documents_created": 0, "chunks_created": 0,
             "files_failed": [], "started_at": time.time()}

    with _connect() as conn:
        conn.execute("DELETE FROM document_chunks WHERE page_hint LIKE 'doc:%'")
        rebuilt_courses = set()
        for subject, meta in SUBJECT_META.items():
            if not meta.get("rebuild"):
                continue
            row = conn.execute("SELECT id FROM courses WHERE name = ?", (meta["course_name"],)).fetchone()
            if row and row["id"] not in rebuilt_courses:
                _clear_course_content(conn, row["id"])
                rebuilt_courses.add(row["id"])

        subjects_processed = {}
        for subject, meta in sorted(SUBJECT_META.items()):
            subject_dir = os.path.join(SOURCE_DIR, subject)
            if not os.path.isdir(subject_dir):
                continue

            course_id = subjects_processed.get(meta["course_name"])
            if course_id is None:
                is_new = meta.get("new_course", False)
                before = conn.execute("SELECT id FROM courses WHERE name = ?", (meta["course_name"],)).fetchone()
                course_id = _get_or_create_course(conn, meta["course_name"], meta)
                if is_new and before is None:
                    stats["courses_created"] += 1
                subjects_processed[meta["course_name"]] = course_id

            files = sorted(f for f in os.listdir(subject_dir) if f.lower().endswith((".pdf", ".pptx")))
            chapter_order = conn.execute(
                "SELECT COALESCE(MAX(order_index), -1) m FROM chapters WHERE course_id = ?", (course_id,)
            ).fetchone()["m"] + 1

            for file_name in files:
                target_course_id = course_id
                if file_name in REROUTE_FILES:
                    reroute_row = conn.execute(
                        "SELECT id FROM courses WHERE name = ?", (REROUTE_FILES[file_name],)
                    ).fetchone()
                    if reroute_row:
                        target_course_id = reroute_row["id"]

                title = _clean_title(file_name)
                file_path = os.path.join("dataset", "source_documents", subject, file_name)
                file_type = os.path.splitext(file_name)[1].lstrip(".").lower()

                chapter_id = None
                if target_course_id == course_id:
                    chapter_id = _insert_chapter(conn, course_id, title, chapter_order)
                    chapter_order += 1

                existing_doc = conn.execute(
                    "SELECT id FROM documents WHERE course_id = ? AND title = ?",
                    (target_course_id, file_name),
                ).fetchone()
                if existing_doc:
                    document_id = existing_doc["id"]
                    conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
                else:
                    cur = conn.execute(
                        "INSERT INTO documents (course_id, chapter_id, title, file_type, file_path, status) "
                        "VALUES (?, ?, ?, ?, ?, 'active')",
                        (target_course_id, chapter_id, file_name, file_type, file_path),
                    )
                    document_id = cur.lastrowid
                    stats["documents_created"] += 1

                full_path = os.path.join(config.BASE_DIR, file_path)
                try:
                    pages = extract_text.extract_file_pages(full_path, subject)
                except Exception as e:
                    stats["files_failed"].append({"file": file_name, "error": str(e)})
                    log(f"  LỖI {file_name}: {e}")
                    continue

                chunk_idx = 0
                for page_num, page_text in enumerate(pages, start=1):
                    for sub_chunk in _chunk_page(page_text):
                        tf = _term_freq(sub_chunk)
                        if not tf:
                            continue
                        conn.execute(
                            "INSERT INTO document_chunks (document_id, content, chunk_index, "
                            "vector_embedding, page_hint) VALUES (?, ?, ?, ?, ?)",
                            (document_id, sub_chunk, chunk_idx, json.dumps(tf),
                             f"doc:{subject}/{file_name}:p{page_num}"),
                        )
                        chunk_idx += 1
                stats["chunks_created"] += chunk_idx
                log(f"  [{subject}] {file_name}: {len(pages)} trang -> {chunk_idx} chunk")
        conn.commit()

    stats["elapsed_seconds"] = round(time.time() - stats["started_at"], 1)
    return stats


if __name__ == "__main__":
    result = run_ingest()
    print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
