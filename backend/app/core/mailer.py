"""
mailer.py
Gửi email giao dịch (quên mật khẩu) qua Brevo bằng HTTPS API.
Không dùng SMTP vì Render bản miễn phí chặn các cổng SMTP.

Cấu hình bằng biến môi trường (nhập ở mục Environment của Render, KHÔNG ghi vào code):
  BREVO_API_KEY       khóa API của Brevo
  MAIL_SENDER_EMAIL   địa chỉ người gửi đã xác thực trong Brevo
  MAIL_SENDER_NAME    tên hiển thị (mặc định "EduAI")
"""
import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger("eduai.mailer")
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def mail_configured() -> bool:
    return bool(os.environ.get("BREVO_API_KEY") and os.environ.get("MAIL_SENDER_EMAIL"))


def send_email(to_email: str, to_name: str, subject: str, html: str) -> bool:
    """Trả về True nếu gửi thành công. Không bao giờ ném lỗi ra ngoài."""
    if not mail_configured():
        log.warning("Chưa cấu hình BREVO_API_KEY/MAIL_SENDER_EMAIL: bỏ qua gửi email.")
        return False
    body = {
        "sender": {"name": os.environ.get("MAIL_SENDER_NAME", "EduAI"),
                   "email": os.environ["MAIL_SENDER_EMAIL"]},
        "to": [{"email": to_email, "name": to_name or to_email}],
        "subject": subject,
        "htmlContent": html,
    }
    req = urllib.request.Request(
        BREVO_URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"api-key": os.environ["BREVO_API_KEY"], "content-type": "application/json",
                 "accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        log.error("Brevo trả lỗi %s: %s", e.code, e.read()[:200])
    except Exception as e:  # mất mạng, hết thời gian chờ...
        log.error("Không gửi được email: %s", e)
    return False
