# Kết quả đánh giá KeywordIntentClassifier (số liệu thật)

Chạy lại bằng (từ thư mục `eduai/`):
`python -m ai_service.dataset_split` rồi `python -m ai_service.evaluate`

Dữ liệu: `intents.json` (46 mẫu) + `intent_samples.json` (720 câu, 60 câu/nhãn), bỏ trùng
=> 758 mẫu, 12 nhãn, chia 70/15/15 theo từng nhãn (seed 42): Train 532, Val 113, Test 113.
Classifier chỉ được xây từ Train + Val; Test được giữ lại và chỉ dùng để đo.

| Model | Accuracy | Precision (macro) | Recall (macro) | F1-score (macro) |
|---|---|---|---|---|
| KeywordIntentClassifier | 72.57% | 80.09% | 72.59% | 74.86% |
| PhoBERTIntentClassifier | Chưa thực hiện (chưa fine-tune) | — | — | — |

Chi tiết từng nhãn và ma trận nhầm lẫn: `eval_report.json`.
Lỗi chủ yếu: câu chào/tạm biệt ngắn bị đưa về unknown (độ tin cậy thấp), và các nhãn gần nghĩa
bị nhầm (result↔exam, learning_recommendation→summary/greeting, document_search→knowledge_question).
Cả 12 câu mẫu câu ngắn dùng chung từ khóa là điểm yếu của phương pháp so khớp từ khóa,
là cơ sở để thử PhoBERT ở giai đoạn sau.
