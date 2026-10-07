# Triển khai EduAI lên Internet (link cố định, không cần chạy máy local)

Hướng dẫn này giúp bạn có **1 đường link duy nhất** để đăng nhập vào EduAI mọi lúc,
mọi nơi, không cần mở terminal hay bật máy tính chạy `uvicorn`/`http.server` nữa.

Cách làm: Backend deploy lên **Render** (miễn phí), Frontend deploy lên **Netlify**
(miễn phí, kéo-thả không cần biết code).

---

## Bước 1 — Đưa code lên GitHub (nếu chưa có)

1. Tạo tài khoản tại https://github.com (miễn phí).
2. Tạo repository mới, đặt tên `eduai`.
3. Upload toàn bộ thư mục `eduai/` (đã giải nén) lên repo đó — có thể dùng nút
   "Add file → Upload files" trên giao diện web GitHub, kéo-thả cả thư mục vào.

## Bước 2 — Deploy Backend lên Render

1. Vào https://render.com → Đăng ký/đăng nhập (dùng tài khoản GitHub cho nhanh).
2. Chọn **New +** → **Blueprint**.
3. Chọn repo `eduai` vừa tạo. Render sẽ tự đọc file `render.yaml` đã có sẵn trong
   project (mình đã chuẩn bị sẵn, không cần tự điền build command/start command).
4. Nhấn **Apply** / **Create**. Đợi vài phút để Render cài đặt và khởi động.
5. Sau khi xong, Render cấp cho bạn một link dạng:
   `https://eduai-backend-xxxx.onrender.com`
   → Mở link đó + `/health` (ví dụ `https://eduai-backend-xxxx.onrender.com/health`)
   để kiểm tra thấy `{"status":"ok"}` là backend đã chạy thành công trên Internet.

**Lưu ý về gói miễn phí của Render:**
- Nếu không có ai truy cập trong ~15 phút, server sẽ "ngủ"; lần truy cập đầu tiên
  sau đó sẽ mất khoảng 30–50 giây để "thức dậy" — đây là bình thường, không phải lỗi.
- Gói miễn phí không có ổ đĩa lưu trữ lâu dài, nên dữ liệu (tài khoản mới tạo, kết
  quả bài kiểm tra...) có thể bị reset về dữ liệu demo ban đầu mỗi khi Render khởi
  động lại server (redeploy, hoặc sau thời gian dài không hoạt động). Với mục đích
  demo/chấm điểm đồ án thì không ảnh hưởng gì. Để lưu dữ liệu vĩnh viễn mà vẫn miễn
  phí, làm theo phần **"Lưu dữ liệu vĩnh viễn (miễn phí) với Backblaze B2"** ở cuối file.

## Bước 3 — Trỏ Frontend về Backend vừa deploy

1. Mở file `frontend/js/api.js` trong repo (sửa trực tiếp trên GitHub cũng được:
   vào file → nút bút chì "Edit").
2. Tìm dòng:
   ```js
   const API_BASE = window.EDUAI_API_BASE || "http://localhost:8000";
   ```
   Đổi thành đúng link Render ở Bước 2:
   ```js
   const API_BASE = window.EDUAI_API_BASE || "https://eduai-backend-xxxx.onrender.com";
   ```
3. Lưu (Commit changes) trên GitHub.

## Bước 4 — Deploy Frontend lên Netlify (kéo-thả, không cần git)

1. Vào https://app.netlify.com/drop
2. Kéo toàn bộ thư mục `frontend/` (đã sửa API_BASE ở Bước 3, tải lại về máy nếu
   sửa trên GitHub) vào ô thả file trên trang đó.
3. Netlify tự động cấp ngay một link dạng: `https://random-name-xxxx.netlify.app`
4. Mở link đó + `/pages/login.html`, ví dụ:
   `https://random-name-xxxx.netlify.app/pages/login.html`
   → Đây chính là link bạn cần — **bấm vào là đăng nhập được ngay, không cần chạy
   gì trên máy cả.**

(Muốn link đẹp hơn: trong Netlify → Site settings → Change site name, đổi thành
tên bạn muốn, ví dụ `eduai-chatbot.netlify.app`.)

---

## Tóm tắt link cuối cùng

- Link chia sẻ cho người khác (giảng viên, bạn bè...):
  `https://<tên-site-của-bạn>.netlify.app/pages/login.html`
- Sinh viên tự đăng ký ở trang đăng ký. Admin: đặt biến môi trường `EDUAI_ADMIN_PASSWORD` trên
  Render (Environment) trước khi deploy; đặt thêm `EDUAI_SECRET_KEY` là một chuỗi ngẫu nhiên dài.

Từ giờ, ai bấm vào link Netlify đó đều dùng được ngay — máy tính của bạn có tắt
cũng không ảnh hưởng, vì cả backend (Render) và frontend (Netlify) đều chạy trên
server của họ, không phải máy bạn.

---

## Lưu dữ liệu vĩnh viễn (miễn phí) với Backblaze B2

Backend dùng SQLite nên file dữ liệu nằm trên ổ đĩa tạm của Render. Dùng **Litestream** để
sao lưu liên tục file này lên Backblaze B2 (miễn phí 10 GB) và tự khôi phục mỗi lần server
khởi động. Kết quả: tài khoản đăng ký, lịch sử chat, kết quả bài làm **không mất** khi
Render ngủ/khởi động lại/deploy lại. Các file liên quan: `render.yaml`,
`backend/start.sh`, `backend/litestream.yml`, `backend/install_litestream.sh`.

### 1. Tạo kho lưu trữ trên Backblaze
1. Đăng ký tại https://www.backblaze.com/sign-up/cloud-storage (chọn B2 Cloud Storage).
2. Vào **Buckets → Create a Bucket**: đặt tên (ví dụ `eduai-backup-<tên-bạn>`), chọn **Private**,
   các mục còn lại để mặc định. Tạo xong, ghi lại **Endpoint** (dạng `s3.us-west-004.backblazeb2.com`)
   ở trang chi tiết bucket.
3. Vào **Application Keys → Add a New Application Key**: chọn bucket vừa tạo, quyền **Read and Write**.
   Bấm tạo và **copy ngay** `keyID` và `applicationKey` (chỉ hiện một lần).

### 2. Thêm biến môi trường trên Render (Environment)
| Key | Value |
|---|---|
| `LITESTREAM_BUCKET` | tên bucket |
| `LITESTREAM_ENDPOINT` | `https://s3.us-west-004.backblazeb2.com` (đúng endpoint của bạn) |
| `LITESTREAM_ACCESS_KEY_ID` | `keyID` |
| `LITESTREAM_SECRET_ACCESS_KEY` | `applicationKey` |

Vùng (region) được tự suy ra từ endpoint. Nếu cần có thể thêm `LITESTREAM_REGION` (ví dụ `us-west-004`).

### 3. Deploy lại
Đẩy các file mới lên GitHub rồi đồng bộ Blueprint (hoặc Manual Deploy). Trong **Logs** phải thấy:
`[start] Khôi phục dữ liệu từ bản sao lưu (nếu có)...` rồi `[start] Chạy web kèm sao lưu liên tục.`
Nếu thấy `CHƯA bật lưu vĩnh viễn` nghĩa là thiếu biến `LITESTREAM_BUCKET` hoặc chưa cài được Litestream.

Lưu ý: nếu khôi phục lỗi (sai khóa, sai endpoint...), server cố ý **dừng** và ghi lỗi vào Logs để
không tạo dữ liệu trống đè lên bản sao lưu. Sửa biến môi trường rồi deploy lại.
