import gzip
import json
import os
import secrets
import sys

from .core.database import init_db, get_db
from .core.security import hash_password

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from ai_service import config as ai_config  # noqa: E402
from ai_service.rag import _term_freq  # noqa: E402

CONTENT_MARKER = "dataset/source_documents/%"

COURSES = [
    ("AI101", "Trí tuệ nhân tạo", "Nhập môn AI: tìm kiếm, học máy, mạng nơ-ron."),
    ("DB101", "Cơ sở dữ liệu", "Thiết kế CSDL quan hệ, đại số quan hệ, SQL, ràng buộc toàn vẹn."),
    ("DSA101", "Cấu trúc dữ liệu và giải thuật", "Độ phức tạp, sắp xếp, cây, đồ thị, bảng băm."),
    ("PY101", "Lập trình Python", "Cú pháp Python, OOP, xử lý dữ liệu."),
    ("SA101", "Phân tích thiết kế hệ thống", "Use case, sơ đồ lớp, phân tích yêu cầu."),
    ("OOP101", "Lập trình hướng đối tượng", "Lớp, đối tượng, bốn tính chất OOP, phương thức."),
    ("HQT101", "Hệ quản trị cơ sở dữ liệu", "Kiến trúc SQL Server, khai thác, bảo mật, transaction."),
    ("NET101", "Lập trình .NET", "ADO.NET, Windows Forms, kết nối và thao tác dữ liệu."),
    ("TRR101", "Toán rời rạc", "Logic mệnh đề, đại số Boole, tổ hợp, chia hết, đồng dư."),
]

CHAPTERS = {
    "Trí tuệ nhân tạo": ["Tìm kiếm trong không gian trạng thái", "Học máy cơ bản", "Mạng nơ-ron"],
    "Cơ sở dữ liệu": ["Tổng quan về cơ sở dữ liệu", "Các mô hình dữ liệu quan hệ", "Đại số quan hệ", "Ngôn ngữ truy vấn SQL", "Ràng buộc toàn vẹn"],
    "Cấu trúc dữ liệu và giải thuật": ["Giới thiệu", "Sắp xếp", "Cây", "Đồ thị", "Bảng băm"],
    "Lập trình Python": ["Cú pháp cơ bản", "Lập trình hướng đối tượng", "Xử lý dữ liệu với Pandas"],
    "Phân tích thiết kế hệ thống": ["Thu thập yêu cầu", "Use case Diagram", "Class Diagram"],
    "Lập trình hướng đối tượng": ["Giới thiệu lập trình hướng đối tượng", "4 tính chất của OOP", "Phương thức"],
    "Hệ quản trị cơ sở dữ liệu": ["Tổng quan về hệ quản trị CSDL", "Xây dựng - Quản lý - Khai thác CSDL", "Truy vấn nâng cao", "Ràng buộc dữ liệu", "Bảo mật và An toàn dữ liệu", "Transaction"],
    "Lập trình .NET": ["Giới thiệu .NET Framework", "Windows Forms", "ADO.NET", "Kết nối đến Data Source", "Lấy dữ liệu theo cách Connected", "Sắp xếp - Tìm kiếm - Lọc dữ liệu", "Truy vấn có tham số và Stored Procedure", "Cập nhật dữ liệu"],
    "Toán rời rạc": ["Đại số mệnh đề", "Đại số Boole", "Bài toán đếm", "Lý thuyết chia", "Lý thuyết đồng dư"],
}

DOCUMENTS = [
    ("Cơ sở dữ liệu", "Tổng quan về cơ sở dữ liệu", "CSDL_Chuong1.pdf", "pdf"),
    ("Cơ sở dữ liệu", "Các mô hình dữ liệu quan hệ", "CSDL_Chuong2.pdf", "pdf"),
    ("Cơ sở dữ liệu", "Đại số quan hệ", "CSDL_Chuong3.pdf", "pdf"),
    ("Cơ sở dữ liệu", "Ngôn ngữ truy vấn SQL", "CSDL_Chuong4.pdf", "pdf"),
    ("Cơ sở dữ liệu", "Ràng buộc toàn vẹn", "CSDL_Chuong5.pdf", "pdf"),
    ("Hệ quản trị cơ sở dữ liệu", "Tổng quan về hệ quản trị CSDL", "Ch1_Tong quan HQTCSDL.pdf", "pdf"),
    ("Hệ quản trị cơ sở dữ liệu", "Xây dựng - Quản lý - Khai thác CSDL", "Chuong2_Xay dung_Quan li_Khai thac CSDL.pdf", "pdf"),
    ("Hệ quản trị cơ sở dữ liệu", "Truy vấn nâng cao", "Chuong3_Truy van nang cao.pdf", "pdf"),
    ("Hệ quản trị cơ sở dữ liệu", "Ràng buộc dữ liệu", "Chuong4_Rang buoc toan ven.pdf", "pdf"),
    ("Hệ quản trị cơ sở dữ liệu", "Bảo mật và An toàn dữ liệu", "Chuong5_Bao mat va An toan du lieu - VIEW-TRIGGER.pdf", "pdf"),
    ("Hệ quản trị cơ sở dữ liệu", "Bảo mật và An toàn dữ liệu", "Chuong6_An toan bao mat 2.pdf", "pdf"),
    ("Hệ quản trị cơ sở dữ liệu", "Transaction", "Chuong7_Transaction.pdf", "pdf"),
    ("Cấu trúc dữ liệu và giải thuật", "Giới thiệu", "GiaiThuat_GioiThieu.pptx", "pptx"),
    ("Cấu trúc dữ liệu và giải thuật", "Giới thiệu", "GiaiThuat_C1.pptx", "pptx"),
    ("Cấu trúc dữ liệu và giải thuật", "Sắp xếp", "GiaiThuat_C2.pptx", "pptx"),
    ("Cấu trúc dữ liệu và giải thuật", "Cây", "GiaiThuat_C3.pptx", "pptx"),
    ("Cấu trúc dữ liệu và giải thuật", "Đồ thị", "GiaiThuat_C4.pptx", "pptx"),
    ("Cấu trúc dữ liệu và giải thuật", "Bảng băm", "GiaiThuat_C5.odp", "odp"),
    ("Lập trình hướng đối tượng", "Phương thức", "Chuong-03.Phuong-thuc.pdf", "pdf"),
    ("Lập trình hướng đối tượng", "4 tính chất của OOP", "Object-Oriented Programming - 4 pillars of OOP.pdf", "pdf"),
    ("Lập trình hướng đối tượng", "Giới thiệu lập trình hướng đối tượng", "Object Oriented Programming in Python.pdf", "pdf"),
    ("Lập trình hướng đối tượng", "Giới thiệu lập trình hướng đối tượng", "Object Oriented Programming - tai lieu tham khao.pdf", "pdf"),
    ("Lập trình hướng đối tượng", "Giới thiệu lập trình hướng đối tượng", "Object-Oriented Programming in Python - Launch School.pdf", "pdf"),
    ("Lập trình hướng đối tượng", "Phương thức", "Bai tap OOP.docx", "docx"),
    ("Lập trình .NET", "ADO.NET", "Chuong 1 - ADO.NET.pptx", "pptx"),
    ("Lập trình .NET", "ADO.NET", "Chuong 2 - Ung dung CSDL va ADO.NET.pptx", "pptx"),
    ("Lập trình .NET", "Windows Forms", "Chuong 2 - Windows Forms.pdf", "pdf"),
    ("Lập trình .NET", "Kết nối đến Data Source", "Chuong 3 - Ket noi den Data Source.pptx", "pptx"),
    ("Lập trình .NET", "Lấy dữ liệu theo cách Connected", "Chuong 4 - Lay du lieu theo cach Connected.pptx", "pptx"),
    ("Lập trình .NET", "Sắp xếp - Tìm kiếm - Lọc dữ liệu", "Chuong 6 - Sap xep - Tim kiem - Loc du lieu.pptx", "pptx"),
    ("Lập trình .NET", "Truy vấn có tham số và Stored Procedure", "Chuong 7 - Truy van co tham so - Stored procedures.pptx", "pptx"),
    ("Lập trình .NET", "Cập nhật dữ liệu", "Chuong 8 - Cap nhat du lieu.pptx", "pptx"),
    ("Toán rời rạc", "Đại số mệnh đề", "Giao trinh Toan roi rac 2025.pdf", "pdf"),
]

STUDENTS = [
    ("Nguyễn Văn An", "an.nguyen@student.edu.vn", "2004-03-15", "Nam",
     "Khoa học máy tính", "2212345", "0901234567", "Cần Thơ"),
    ("Trần Thị Bích", "bich.tran@student.edu.vn", "2003-11-02", "Nữ",
     "Công nghệ thông tin", "2212346", "0912345678", "Vĩnh Long"),
    ("Lê Hoàng Nam", "nam.le@student.edu.vn", "2004-07-20", "Nam",
     "Khoa học máy tính", "2212347", "0923456789", "Hậu Giang"),
]


def _course_has_imported_content(db, course_id) -> bool:
    row = db.execute(
        "SELECT 1 FROM documents WHERE course_id = ? AND file_path LIKE ? LIMIT 1", (course_id, CONTENT_MARKER)
    ).fetchone()
    return row is not None


def import_content_pack(db) -> dict:
    """Nạp gói nội dung tài liệu thật (dataset/content_pack.json.gz) vào database, đúng một lần.
    Đã nạp rồi (còn tài liệu mang đường dẫn dataset/source_documents) thì bỏ qua."""
    pack_path = os.path.join(ai_config.DATASET_DIR, "content_pack.json.gz")
    if not os.path.exists(pack_path):
        return {"skipped": "chưa có content_pack.json.gz"}
    if db.execute("SELECT 1 FROM documents WHERE file_path LIKE ? LIMIT 1", (CONTENT_MARKER,)).fetchone():
        return {"skipped": "đã nạp trước đó"}

    with gzip.open(pack_path, "rt", encoding="utf-8") as f:
        pack = json.load(f)

    n_docs = n_chunks = 0
    for c in pack["courses"]:
        row = db.execute("SELECT id FROM courses WHERE name = ?", (c["name"],)).fetchone()
        if row:
            course_id = row["id"]
            # Bỏ chương/tài liệu giữ chỗ do seed tạo trước đó (chưa có nội dung) để thay bằng nội dung thật.
            db.execute("DELETE FROM document_chunks WHERE document_id IN (SELECT id FROM documents WHERE course_id = ?)", (course_id,))
            db.execute("DELETE FROM documents WHERE course_id = ?", (course_id,))
            db.execute("DELETE FROM chapters WHERE course_id = ?", (course_id,))
        else:
            course_id = db.execute(
                "INSERT INTO courses (code, name, description, status) VALUES (?, ?, ?, 'active')",
                (c["code"], c["name"], c["description"]),
            ).lastrowid

        chapter_ids = {}
        for ch in c["chapters"]:
            chapter_ids[ch["name"]] = db.execute(
                "INSERT INTO chapters (course_id, name, order_index) VALUES (?, ?, ?)",
                (course_id, ch["name"], ch["order_index"]),
            ).lastrowid
        for d in c["documents"]:
            doc_id = db.execute(
                "INSERT INTO documents (course_id, chapter_id, title, file_type, file_path, status) "
                "VALUES (?, ?, ?, ?, ?, 'active')",
                (course_id, chapter_ids.get(d["chapter"]), d["title"], d["file_type"], d["file_path"]),
            ).lastrowid
            n_docs += 1
            for idx, (page_hint, content) in enumerate(d["chunks"]):
                db.execute(
                    "INSERT INTO document_chunks (document_id, content, chunk_index, vector_embedding, page_hint) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (doc_id, content, idx, json.dumps(_term_freq(content)), page_hint),
                )
                n_chunks += 1
    return {"documents": n_docs, "chunks": n_chunks}


def _flag(db, key) -> bool:
    return db.execute("SELECT 1 FROM ai_configs WHERE key = ?", (key,)).fetchone() is not None


def _set_flag(db, key):
    db.execute("INSERT OR IGNORE INTO ai_configs (key, value) VALUES (?, '1')", (key,))


def import_authored_documents(db) -> int:
    """Tài liệu do EduAI biên soạn (dataset/authored_documents.json), ví dụ giáo trình Lập trình Python.
    Chạy mỗi lần khởi động nhưng bỏ qua tài liệu đã có (trùng môn + tên)."""
    path = os.path.join(ai_config.DATASET_DIR, "authored_documents.json")
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        docs = json.load(f).get("documents", [])
    added = 0
    for d in docs:
        course = db.execute("SELECT id FROM courses WHERE name = ?", (d["course"],)).fetchone()
        if not course:
            continue
        if db.execute("SELECT 1 FROM documents WHERE course_id = ? AND title = ?", (course["id"], d["title"])).fetchone():
            continue
        chapter = db.execute("SELECT id FROM chapters WHERE course_id = ? AND name = ?", (course["id"], d["chapter"])).fetchone()
        if chapter:
            chapter_id = chapter["id"]
        else:
            order = db.execute("SELECT COALESCE(MAX(order_index), -1) + 1 AS n FROM chapters WHERE course_id = ?", (course["id"],)).fetchone()["n"]
            chapter_id = db.execute("INSERT INTO chapters (course_id, name, order_index) VALUES (?, ?, ?)",
                                    (course["id"], d["chapter"], order)).lastrowid
        doc_id = db.execute(
            "INSERT INTO documents (course_id, chapter_id, title, file_type, file_path, status) VALUES (?, ?, ?, ?, ?, 'active')",
            (course["id"], chapter_id, d["title"], d["file_type"], d["file_path"]),
        ).lastrowid
        for idx, (page_hint, content) in enumerate(d["chunks"]):
            db.execute(
                "INSERT INTO document_chunks (document_id, content, chunk_index, vector_embedding, page_hint) VALUES (?, ?, ?, ?, ?)",
                (doc_id, content, idx, json.dumps(_term_freq(content)), page_hint),
            )
        added += 1
    return added


def _insert_question(db, q) -> bool:
    course = db.execute("SELECT id FROM courses WHERE name = ?", (q["course"],)).fetchone()
    if not course:
        return False
    if db.execute("SELECT 1 FROM questions WHERE course_id = ? AND content = ?", (course["id"], q["content"])).fetchone():
        return False
    chapter = db.execute("SELECT id FROM chapters WHERE course_id = ? AND name = ?", (course["id"], q.get("chapter"))).fetchone()
    qid = db.execute(
        "INSERT INTO questions (course_id, chapter_id, content, difficulty, explanation) VALUES (?, ?, ?, ?, ?)",
        (course["id"], chapter["id"] if chapter else None, q["content"], q["difficulty"], q.get("explanation", "")),
    ).lastrowid
    for key, text in q["options"].items():
        db.execute(
            "INSERT INTO answers (question_id, option_key, option_text, is_correct) VALUES (?, ?, ?, ?)",
            (qid, key, text, 1 if key == q["correct_answer"] else 0),
        )
    return True


def import_question_bank(db) -> int:
    """Nạp ngân hàng câu hỏi vào database. Mỗi nguồn (bộ gốc, từng gói qpack_N) chỉ nạp đúng một lần;
    sau đó admin tự quản lý trong database nên câu đã xóa sẽ không xuất hiện lại."""
    from ai_service.question_bank import load_all_questions, load_pack_questions
    n = 0
    if not _flag(db, "question_bank_imported"):
        n += sum(_insert_question(db, q) for q in load_all_questions())
        _set_flag(db, "question_bank_imported")
    for name, questions in load_pack_questions().items():
        if _flag(db, f"question_pack_{name}"):
            continue
        n += sum(_insert_question(db, q) for q in questions)
        _set_flag(db, f"question_pack_{name}")
    return n


def run():
    init_db()
    admin_password = os.environ.get("EDUAI_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
    student_password = os.environ.get("EDUAI_DEMO_STUDENT_PASSWORD") or secrets.token_urlsafe(12)
    with get_db() as db:
        existing_admin = db.execute("SELECT id FROM users WHERE email = ?", ("admin@eduai.vn",)).fetchone()
        # Đã có admin tức là database cũ: coi như đã seed demo, KHÔNG tạo lại sinh viên demo
        # (nếu không, tài khoản admin vừa xóa sẽ xuất hiện lại sau mỗi lần server khởi động).
        fresh_database = existing_admin is None
        if fresh_database:
            db.execute(
                "INSERT INTO users (full_name, email, password_hash, role_id) VALUES (?, ?, ?, "
                "(SELECT id FROM roles WHERE name='ADMIN'))",
                ("Quản trị viên", "admin@eduai.vn", hash_password(admin_password)),
            )
        if fresh_database and not _flag(db, "demo_users_seeded"):
            for name, email, dob, gender, major, code, phone, address in STUDENTS:
                if not db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
                    db.execute(
                        "INSERT INTO users (full_name, email, password_hash, role_id, "
                        "date_of_birth, gender, major, student_code, phone, address) VALUES "
                        "(?, ?, ?, (SELECT id FROM roles WHERE name='STUDENT'), ?, ?, ?, ?, ?, ?)",
                        (name, email, hash_password(student_password), dob, gender, major, code, phone, address),
                    )
        _set_flag(db, "demo_users_seeded")

        course_ids = {}
        chapter_ids = {}

        for code, name, desc in COURSES:
            existing = db.execute("SELECT id FROM courses WHERE code = ?", (code,)).fetchone()
            if not existing:
                cur = db.execute(
                    "INSERT INTO courses (code, name, description) VALUES (?, ?, ?)",
                    (code, name, desc),
                )
                course_id = cur.lastrowid
            else:
                course_id = existing["id"]
            course_ids[name] = course_id

        stats = import_content_pack(db)
        print(f"Nội dung tài liệu: {stats}")

        for name, course_id in course_ids.items():
            if _course_has_imported_content(db, course_id):
                continue  # môn đã có chương/tài liệu thật, không thêm lại dữ liệu giữ chỗ
            for idx, chapter_name in enumerate(CHAPTERS.get(name, [])):
                exists = db.execute(
                    "SELECT id FROM chapters WHERE course_id=? AND name=?", (course_id, chapter_name)
                ).fetchone()
                if not exists:
                    cur = db.execute(
                        "INSERT INTO chapters (course_id, name, order_index) VALUES (?, ?, ?)",
                        (course_id, chapter_name, idx),
                    )
                    chapter_ids[(name, chapter_name)] = cur.lastrowid
                else:
                    chapter_ids[(name, chapter_name)] = exists["id"]

        for course_name, chapter_name, title, file_type in DOCUMENTS:
            course_id = course_ids.get(course_name)
            chapter_id = chapter_ids.get((course_name, chapter_name))
            if course_id is None or _course_has_imported_content(db, course_id):
                continue
            exists = db.execute(
                "SELECT id FROM documents WHERE course_id=? AND title=?", (course_id, title)
            ).fetchone()
            if not exists:
                db.execute(
                    "INSERT INTO documents (course_id, chapter_id, title, file_type, file_path) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (course_id, chapter_id, title, file_type, ""),
                )

        print(f"Tài liệu biên soạn thêm: {import_authored_documents(db)}")
        print(f"Câu hỏi nạp vào database: {import_question_bank(db)}")

        student = db.execute("SELECT id FROM users WHERE email=?", (STUDENTS[0][1],)).fetchone() if fresh_database else None
        progress_demo = [
            ("Trí tuệ nhân tạo", 75),
            ("Cơ sở dữ liệu", 62),
            ("Lập trình Python", 84),
            ("Cấu trúc dữ liệu và giải thuật", 40),
            ("Lập trình hướng đối tượng", 55),
            ("Hệ quản trị cơ sở dữ liệu", 30),
            ("Lập trình .NET", 20),
            ("Toán rời rạc", 45),
        ]
        for course_name, percent in progress_demo:
            course = db.execute("SELECT id FROM courses WHERE name=?", (course_name,)).fetchone()
            if course and student:
                exists = db.execute(
                    "SELECT id FROM learning_progress WHERE user_id=? AND course_id=?",
                    (student["id"], course["id"]),
                ).fetchone()
                if not exists:
                    db.execute(
                        "INSERT INTO learning_progress (user_id, course_id, percent_complete) VALUES (?, ?, ?)",
                        (student["id"], course["id"], percent),
                    )

    print("Seed dữ liệu demo hoàn tất.")
    if fresh_database and not os.environ.get("EDUAI_ADMIN_PASSWORD"):
        print(f"Admin: admin@eduai.vn / {admin_password}  (mật khẩu ngẫu nhiên, chỉ hiện lần này)")
    if fresh_database and not os.environ.get("EDUAI_DEMO_STUDENT_PASSWORD"):
        print(f"Sinh viên demo: an.nguyen@student.edu.vn / {student_password}")


if __name__ == "__main__":
    run()
