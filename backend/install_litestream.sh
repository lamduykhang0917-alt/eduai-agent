#!/usr/bin/env bash
# Tải Litestream (công cụ sao lưu SQLite liên tục lên kho lưu trữ S3/Backblaze B2).
# Chạy lúc build trên Render. Nếu tải lỗi thì chỉ cảnh báo: web vẫn chạy, nhưng dữ liệu
# sẽ không được lưu vĩnh viễn.
VERSION=0.3.13
cd "$(dirname "$0")"
mkdir -p bin
if curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/v${VERSION}/litestream-v${VERSION}-linux-amd64.tar.gz" \
    | tar -xz -C bin litestream; then
  chmod +x bin/litestream
  ./bin/litestream version
else
  echo "[install_litestream] CẢNH BÁO: không tải được Litestream, dữ liệu sẽ không được lưu vĩnh viễn."
  rm -f bin/litestream
fi
exit 0
