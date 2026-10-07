"""
security.py
- Băm mật khẩu bằng bcrypt (không lưu plain text - mục 42).
- Sinh/kiểm tra JWT token cho Authentication.
- get_current_user để bảo vệ endpoint và kiểm tra role (Backend kiểm tra
  quyền thật sự, không chỉ ẩn menu ở Frontend - mục 33).
"""

import os
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext

from .database import get_db

SECRET_KEY = os.environ.get("EDUAI_SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


REMEMBER_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # "Ghi nhớ đăng nhập": 30 ngày


def create_access_token(data: dict, remember: bool = False) -> str:
    to_encode = data.copy()
    minutes = REMEMBER_TOKEN_EXPIRE_MINUTES if remember else ACCESS_TOKEN_EXPIRE_MINUTES
    expire = datetime.utcnow() + timedelta(minutes=minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                             detail="Token không hợp lệ hoặc đã hết hạn")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    with get_db() as db:
        row = db.execute(
            "SELECT u.id, u.full_name, u.email, r.name as role, u.status, "
            "u.date_of_birth, u.gender, u.major, u.student_code, u.phone, "
            "u.address, u.created_at "
            "FROM users u JOIN roles r ON u.role_id = r.id WHERE u.id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Người dùng không tồn tại")
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="Tài khoản đã bị khóa")
    return dict(row)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "ADMIN":
        raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin")
    return user
