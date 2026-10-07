#!/usr/bin/env bash
# Khởi động backend EduAI.
# - Có LITESTREAM_BUCKET (và đã cài Litestream): khôi phục DB từ bản sao lưu, chạy seed,
#   rồi chạy web kèm sao lưu liên tục => tài khoản/lịch sử không mất khi Render khởi động lại.
# - Không có: chạy như cũ (dữ liệu chỉ lưu tạm trên ổ đĩa của Render).
set -e
cd "$(dirname "$0")"

export DB_PATH="$(python -c 'from app.core.database import DB_PATH; print(DB_PATH)')"
CONFIG="${LITESTREAM_CONFIG:-litestream.yml}"
RUN_APP="uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"

if [ -n "$LITESTREAM_BUCKET" ] && [ -x ./bin/litestream ]; then
  # Region của Backblaze nằm trong endpoint, ví dụ s3.us-west-004.backblazeb2.com -> us-west-004
  if [ -z "$LITESTREAM_REGION" ]; then
    export LITESTREAM_REGION="$(echo "$LITESTREAM_ENDPOINT" | sed -E 's#^(https?://)?s3\.([^.]+)\..*#\2#')"
  fi

  echo "[start] Khôi phục dữ liệu từ bản sao lưu (nếu có)..."
  # Nếu khôi phục lỗi (sai khóa, mất mạng...) thì DỪNG, không tạo DB trống để tránh ghi đè bản sao lưu cũ.
  ./bin/litestream restore -config "$CONFIG" -if-db-not-exists -if-replica-exists "$DB_PATH"

  python -m app.seed
  echo "[start] Chạy web kèm sao lưu liên tục."
  exec ./bin/litestream replicate -config "$CONFIG" -exec "$RUN_APP"
else
  echo "[start] CHƯA bật lưu vĩnh viễn (thiếu LITESTREAM_BUCKET hoặc Litestream): dữ liệu sẽ mất khi server khởi động lại."
  python -m app.seed
  exec $RUN_APP
fi
