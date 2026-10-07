"""
database.py
Kết nối SQLite dùng cho prototype (dễ chạy demo, không cần cài server DB).
Để chuyển sang MySQL/PostgreSQL: thay hàm get_db() bằng driver tương ứng
(ví dụ psycopg2 / pymysql) và cập nhật DATABASE_URL; các router giữ nguyên
vì chỉ dùng SQL thuần qua hàm execute/query bên dưới.
"""

import os
import sqlite3
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DB_PATH = os.path.join(BASE_DIR, "backend", "eduai.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "database", "schema.sql")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    _run_migrations(conn)
    conn.close()


# Các cột mới thêm vào bảng users sau khi schema.sql gốc đã được tạo (hồ sơ cá
# nhân). "CREATE TABLE IF NOT EXISTS" trong schema.sql không tự thêm cột mới
# vào bảng đã tồn tại, nên cần migration nhẹ này để nâng cấp database cũ mà
# không làm mất dữ liệu người dùng đã có.
_USER_PROFILE_COLUMNS = {
    "date_of_birth": "TEXT",
    "gender": "TEXT",
    "major": "TEXT",
    "student_code": "TEXT",
    "phone": "TEXT",
    "address": "TEXT",
}

# Cột mới cho document_chunks sau khi schema.sql gốc đã tạo bảng này ở Đồ án 1
# (cùng lý do với _USER_PROFILE_COLUMNS — Đồ án 2 thêm RAG dựa trên TF-IDF).
_DOCUMENT_CHUNK_COLUMNS = {
    "vector_embedding": "TEXT",
    "page_hint": "TEXT",
}


# Đồ án 2 (nâng cấp Agent): hành động đang chờ xác nhận được lưu phía server.
_AGENT_TASK_COLUMNS = {
    "pending_action": "TEXT",
}
_CHAT_MESSAGE_COLUMNS = {
    "meta": "TEXT",
}


def _add_missing_columns(conn, table, columns):
    existing_cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col, col_type in columns.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")


def _run_migrations(conn):
    _add_missing_columns(conn, "users", _USER_PROFILE_COLUMNS)
    _add_missing_columns(conn, "document_chunks", _DOCUMENT_CHUNK_COLUMNS)
    _add_missing_columns(conn, "agent_tasks", _AGENT_TASK_COLUMNS)
    _add_missing_columns(conn, "chat_messages", _CHAT_MESSAGE_COLUMNS)
    conn.commit()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
