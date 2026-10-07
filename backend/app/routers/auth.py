import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel, EmailStr

from ..core.database import get_db
from ..core.mailer import send_email
from ..core.security import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember: bool = False


def _validate_password(password: str):
    if re.search(r"\s", password):
        raise HTTPException(400, "Mật khẩu không được chứa khoảng trắng")
    if len(password) < 8:
        raise HTTPException(400, "Mật khẩu phải có ít nhất 8 ký tự")
    if not re.search(r"[A-Z]", password) or not re.search(r"[0-9]", password):
        raise HTTPException(400, "Mật khẩu phải chứa ít nhất 1 chữ hoa và 1 chữ số")


@router.post("/register")
def register(payload: RegisterRequest):
    if payload.password != payload.confirm_password:
        raise HTTPException(400, "Xác nhận mật khẩu không khớp")
    _validate_password(payload.password)

    with get_db() as db:
        existing = db.execute("SELECT id FROM users WHERE email = ?", (payload.email,)).fetchone()
        if existing:
            raise HTTPException(400, "Email đã được sử dụng")

        cur = db.execute(
            "INSERT INTO users (full_name, email, password_hash, role_id) VALUES (?, ?, ?, "
            "(SELECT id FROM roles WHERE name = 'STUDENT'))",
            (payload.full_name, payload.email, hash_password(payload.password)),
        )
        user_id = cur.lastrowid

    token = create_access_token({"sub": str(user_id)})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/login")
def login(payload: LoginRequest):
    with get_db() as db:
        row = db.execute(
            "SELECT u.id, u.password_hash, u.status, r.name as role "
            "FROM users u JOIN roles r ON u.role_id = r.id WHERE u.email = ?",
            (payload.email,),
        ).fetchone()

    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(401, "Email hoặc mật khẩu không đúng")
    if row["status"] != "active":
        raise HTTPException(403, "Tài khoản đã bị khóa")

    with get_db() as db:
        db.execute("INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'login', '')",
                   (row["id"],))

    token = create_access_token({"sub": str(row["id"])}, remember=payload.remember)
    return {"access_token": token, "token_type": "bearer", "role": row["role"]}


@router.post("/logout")
def logout(user: dict = Depends(get_current_user)):
    with get_db() as db:
        db.execute("INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'logout', '')",
                   (user["id"],))
    return {"message": "Đăng xuất thành công"}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return user


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    date_of_birth: Optional[str] = None  # định dạng YYYY-MM-DD
    gender: Optional[str] = None
    major: Optional[str] = None
    student_code: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


@router.put("/me")
def update_me(payload: UpdateProfileRequest, user: dict = Depends(get_current_user)):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "Không có thông tin nào để cập nhật")

    if "full_name" in fields and not fields["full_name"].strip():
        raise HTTPException(400, "Họ tên không được để trống")

    set_clause = ", ".join(f"{col} = ?" for col in fields.keys())
    values = list(fields.values()) + [user["id"]]

    with get_db() as db:
        db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        db.execute(
            "INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'update_profile', '')",
            (user["id"],),
        )
        row = db.execute(
            "SELECT u.id, u.full_name, u.email, r.name as role, u.status, "
            "u.date_of_birth, u.gender, u.major, u.student_code, u.phone, "
            "u.address, u.created_at "
            "FROM users u JOIN roles r ON u.role_id = r.id WHERE u.id = ?",
            (user["id"],),
        ).fetchone()

    return dict(row)


# ---------------------------------------------------------------------------
# Quên mật khẩu: gửi email chứa liên kết đặt lại (dùng một lần, hết hạn sau 30 phút)
# ---------------------------------------------------------------------------
RESET_TOKEN_MINUTES = 30
RESET_COOLDOWN_SECONDS = 60
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://brilliant-bubblegum-850509.netlify.app").rstrip("/")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _send_reset_email(email: str, name: str, token: str):
    link = f"{FRONTEND_URL}/pages/reset-password.html?token={token}"
    html = (
        f"<div style='font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#0f172a'>"
        f"<h2 style='color:#2563eb'>EduAI</h2>"
        f"<p>Xin chào {name or email},</p>"
        f"<p>Chúng tôi nhận được yêu cầu đặt lại mật khẩu cho tài khoản này. "
        f"Bấm nút bên dưới để đặt mật khẩu mới (liên kết dùng một lần, hết hạn sau {RESET_TOKEN_MINUTES} phút).</p>"
        f"<p><a href='{link}' style='display:inline-block;background:#2563eb;color:#fff;padding:12px 22px;"
        f"border-radius:10px;text-decoration:none;font-weight:600'>Đặt lại mật khẩu</a></p>"
        f"<p style='font-size:13px;color:#64748b'>Nếu nút không bấm được, hãy sao chép liên kết này vào trình duyệt:<br>{link}</p>"
        f"<p style='font-size:13px;color:#64748b'>Nếu bạn không yêu cầu, hãy bỏ qua email này; mật khẩu của bạn không thay đổi.</p>"
        f"</div>"
    )
    send_email(email, name, "EduAI: đặt lại mật khẩu", html)


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, background: BackgroundTasks):
    # Luôn trả cùng một thông báo để không lộ email nào đã đăng ký.
    generic = {"message": "Nếu email đã đăng ký, chúng tôi đã gửi liên kết đặt lại mật khẩu. Vui lòng kiểm tra hộp thư (cả thư rác)."}
    with get_db() as db:
        user = db.execute("SELECT id, full_name, status FROM users WHERE email = ?", (payload.email,)).fetchone()
        if user is None or user["status"] != "active":
            return generic
        recent = db.execute(
            "SELECT 1 FROM password_resets WHERE user_id = ? AND created_at > ?",
            (user["id"], (datetime.utcnow() - timedelta(seconds=RESET_COOLDOWN_SECONDS)).strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchone()
        if recent:
            return generic
        token = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user["id"], _hash_token(token),
             (datetime.utcnow() + timedelta(minutes=RESET_TOKEN_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")),
        )
        db.execute("INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'forgot_password', '')", (user["id"],))
    background.add_task(_send_reset_email, payload.email, user["full_name"], token)
    return generic


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest):
    _validate_password(payload.new_password)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as db:
        row = db.execute(
            "SELECT id, user_id FROM password_resets WHERE token_hash = ? AND used = 0 AND expires_at > ?",
            (_hash_token(payload.token), now),
        ).fetchone()
        if row is None:
            raise HTTPException(400, "Liên kết không hợp lệ hoặc đã hết hạn. Vui lòng yêu cầu lại.")
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                   (hash_password(payload.new_password), row["user_id"]))
        db.execute("UPDATE password_resets SET used = 1 WHERE user_id = ?", (row["user_id"],))
        db.execute("INSERT INTO activity_logs (user_id, action, detail) VALUES (?, 'reset_password', '')", (row["user_id"],))
    return {"message": "Đặt lại mật khẩu thành công. Bạn có thể đăng nhập bằng mật khẩu mới."}
