from fastapi import APIRouter, Depends

from ..core.database import get_db
from ..core.security import get_current_user

router = APIRouter(tags=["results-progress-recommendations"])


@router.get("/api/results")
def get_results(user: dict = Depends(get_current_user)):
    with get_db() as db:
        rows = db.execute(
            "SELECT r.*, q.difficulty, c.name as course_name FROM quiz_results r "
            "JOIN quizzes q ON r.quiz_id = q.id "
            "LEFT JOIN courses c ON q.course_id = c.id "
            "WHERE r.user_id = ? ORDER BY r.submitted_at DESC",
            (user["id"],),
        ).fetchall()
        return [dict(r) for r in rows]


@router.get("/api/progress")
def get_progress(user: dict = Depends(get_current_user)):
    with get_db() as db:
        rows = db.execute(
            "SELECT p.*, c.name as course_name FROM learning_progress p "
            "JOIN courses c ON p.course_id = c.id WHERE p.user_id = ?",
            (user["id"],),
        ).fetchall()

        total_quizzes = db.execute(
            "SELECT COUNT(*) c FROM quiz_results WHERE user_id = ?", (user["id"],)
        ).fetchone()["c"]
        avg_score = db.execute(
            "SELECT AVG(score) a FROM quiz_results WHERE user_id = ?", (user["id"],)
        ).fetchone()["a"]

        return {
            "by_course": [dict(r) for r in rows],
            "total_quizzes_completed": total_quizzes,
            "average_score": round(avg_score, 2) if avg_score else 0,
        }


@router.get("/api/activity/recent")
def get_recent_activity(user: dict = Depends(get_current_user)):
    with get_db() as db:
        rows = db.execute(
            "SELECT action, detail, created_at FROM activity_logs "
            "WHERE user_id = ? AND action != 'login' AND action != 'logout' "
            "ORDER BY created_at DESC LIMIT 8",
            (user["id"],),
        ).fetchall()
        return [dict(r) for r in rows]


@router.get("/api/recommendations")
def get_recommendations(user: dict = Depends(get_current_user)):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM recommendations WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
            (user["id"],),
        ).fetchall()

        if rows:
            return [dict(r) for r in rows]

        # Đề xuất mặc định khi chưa có dữ liệu cá nhân hóa đủ (mục 20)
        wrong_topics = db.execute(
            "SELECT q.chapter_id, COUNT(*) c FROM quiz_answers qa "
            "JOIN questions q ON qa.question_id = q.id "
            "JOIN quiz_results r ON qa.quiz_result_id = r.id "
            "WHERE r.user_id = ? AND qa.is_correct = 0 "
            "GROUP BY q.chapter_id ORDER BY c DESC LIMIT 1",
            (user["id"],),
        ).fetchone()

        if wrong_topics:
            return [{
                "content": "Bạn nên ôn lại các câu hỏi đã làm sai gần đây trước khi tiếp tục chương mới.",
                "reason": "Dựa trên kết quả bài kiểm tra gần nhất",
            }]

        return [{
            "content": "Hãy bắt đầu với môn Trí tuệ nhân tạo - chương Tìm kiếm trong không gian trạng thái.",
            "reason": "Đề xuất khởi đầu cho sinh viên mới",
        }]
