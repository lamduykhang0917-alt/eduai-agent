# Fine-tune PhoBERT thật (hướng dẫn chạy trên máy của bạn)

Lưu ý quan trọng: môi trường sandbox hiện tại của tôi **không thể tải checkpoint
`vinai/phobert-base` từ huggingface.co** (bị chặn bởi allowlist mạng của sandbox,
chỉ cho phép pypi/npm/github). Vì vậy tôi không thể tự chạy việc huấn luyện này ở
đây và báo số liệu — làm vậy sẽ là bịa số liệu, trái với nguyên tắc ở mục 47 của
spec dự án. Tôi đã viết đầy đủ script huấn luyện thật (`train_classifier.py`) và
đã kiểm tra logic vòng lặp train/eval chạy đúng (dùng model giả nhỏ để dry-run,
không liên quan số liệu thật). Bạn chạy trên máy có Internet, script sẽ tự tải
đúng checkpoint PhoBERT thật và huấn luyện/đánh giá thật.

## Bước 1 — Cài thêm thư viện

```bash
cd backend
pip install torch==2.3.1 transformers==4.42.3
```

(Hoặc copy 2 dòng `torch`/`transformers` đang bị comment trong `backend/requirements.txt`
rồi `pip install -r requirements.txt`.)

## Bước 2 — Chạy huấn luyện

```bash
cd ..          # về thư mục eduai/
python -m ai_service.train_classifier
```

Script sẽ:
1. Tải `vinai/phobert-base` từ HuggingFace (lần đầu mất vài phút, cần Internet).
2. Fine-tune trên `dataset/splits/train.json` + `val.json` (8 epoch, AdamW).
3. Đánh giá thật trên `dataset/splits/test.json` (dữ liệu giữ lại, chưa huấn luyện).
4. Lưu checkpoint vào `ai_service/model/` và `ai_service/tokenizer/`.
5. Lưu số liệu thật (Accuracy/Precision/Recall/F1 + confusion matrix) vào
   `dataset/splits/eval_report_phobert.json`.

## Bước 3 — Kích hoạt PhoBERT trong hệ thống

Mở `ai_service/config.py`, đổi:

```python
LLM_PROVIDER = os.environ.get("EDUAI_LLM_PROVIDER", "claude")
```

thành (hoặc đặt biến môi trường `EDUAI_LLM_PROVIDER=dataset`):

```python
LLM_PROVIDER = os.environ.get("EDUAI_LLM_PROVIDER", "dataset")
```

và đổi:

```python
USE_PHOBERT = False
```

thành:

```python
USE_PHOBERT = True
```

Khởi động lại `uvicorn` — chatbot sẽ dùng `PhoBERTIntentClassifier` (checkpoint
vừa fine-tune ở Bước 2) thay cho `KeywordIntentClassifier`.

## Vì sao dataset nhỏ vẫn nên fine-tune?

`dataset/intents.json` hiện chỉ có vài câu mẫu/intent — không đủ để PhoBERT đạt
độ chính xác cao, nhưng script vẫn chạy đúng kỹ thuật fine-tuning thật (không
phải giả lập), và số liệu Accuracy/Precision/Recall/F1 ra từ Bước 2 là số liệu
thật để điền vào Chương 5 báo cáo — dù thấp, vẫn trung thực hơn số liệu ví dụ cũ
(93%) mà báo cáo đang để placeholder. Muốn tăng độ chính xác thật: bổ sung thêm
nhiều câu mẫu/pattern vào `dataset/intents.json` cho mỗi intent rồi chạy lại
`python -m ai_service.dataset_split` để chia lại train/val/test, sau đó chạy lại
Bước 2.
