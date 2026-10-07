"""
classifier.py
Phân loại intent (Intent Classification) cho câu hỏi của sinh viên.

Có 2 classifier:

1. KeywordIntentClassifier (ĐANG DÙNG MẶC ĐỊNH)
   - Dataset-driven: so khớp câu hỏi đã tiền xử lý với các "patterns" khai
     báo trong dataset/intents.json bằng độ tương đồng từ (token overlap).
   - Cho phép toàn bộ hệ thống Chatbot chạy được ngay khi chưa có checkpoint
     PhoBERT đã fine-tune, đúng theo mục 47 của spec (không bịa rằng đã
     tích hợp PhoBERT khi chưa thực sự có model/dataset huấn luyện).

2. PhoBERTIntentClassifier (SẴN SÀNG ĐỂ BẬT KHI CÓ MODEL)
   - Khung xử lý dùng transformers.AutoModelForSequenceClassification.
   - Chỉ hoạt động khi config.USE_PHOBERT = True và đã có checkpoint hợp lệ
     tại config.MODEL_PATH. Import torch/transformers được thực hiện lazy
     (bên trong hàm) để phần còn lại của hệ thống không bị lỗi nếu chưa
     cài các thư viện này.
"""

import json

from . import config
from .preprocessing import preprocess


class IntentResult:
    def __init__(self, tag: str, confidence: float):
        self.tag = tag
        self.confidence = confidence

    def to_dict(self):
        return {"intent": self.tag, "confidence": round(self.confidence, 3)}


class KeywordIntentClassifier:
    """Bộ phân loại intent dựa trên dataset/intents.json (token overlap)."""

    def __init__(self, intents_path: str = config.INTENTS_FILE):
        with open(intents_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.intents = data.get("intents", [])

    def _score(self, question_tokens: set, pattern: str) -> float:
        pattern_tokens = set(preprocess(pattern).split())
        if not pattern_tokens:
            return 0.0
        overlap = question_tokens & pattern_tokens
        return len(overlap) / len(pattern_tokens)

    def predict(self, question: str) -> IntentResult:
        processed = preprocess(question)
        question_tokens = set(processed.split())

        best_tag = "unknown"
        best_score = 0.0

        for intent in self.intents:
            for pattern in intent.get("patterns", []):
                score = self._score(question_tokens, pattern)
                if score > best_score:
                    best_score = score
                    best_tag = intent["tag"]

        if best_score < config.CONFIDENCE_THRESHOLD:
            return IntentResult("unknown", best_score)
        return IntentResult(best_tag, best_score)


class PhoBERTIntentClassifier:
    """
    Bộ phân loại intent dùng PhoBERT đã fine-tune.
    CHƯA có checkpoint thật -> chỉ kích hoạt khi config.USE_PHOBERT = True.
    """

    def __init__(self, model_path: str = config.MODEL_PATH,
                 tokenizer_path: str = config.TOKENIZER_PATH):
        try:
            import torch  # noqa: F401
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
        except ImportError as e:
            raise RuntimeError(
                "Chưa cài torch/transformers. Chạy: pip install torch transformers"
            ) from e

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_path)
        self.model.eval()
        # id2label phải khớp với các tag trong dataset/intents.json khi fine-tune
        self.id2label = self.model.config.id2label

    def predict(self, question: str) -> IntentResult:
        processed = preprocess(question, for_classifier=False)
        inputs = self.tokenizer(
            processed,
            return_tensors="pt",
            truncation=True,
            max_length=config.MAX_SEQ_LENGTH,
        )
        with self.torch.no_grad():
            outputs = self.model(**inputs)
            probs = self.torch.softmax(outputs.logits, dim=-1)[0]
            confidence, idx = self.torch.max(probs, dim=-1)

        tag = self.id2label[int(idx)]
        conf = float(confidence)
        if conf < config.CONFIDENCE_THRESHOLD:
            return IntentResult("unknown", conf)
        return IntentResult(tag, conf)


def get_classifier():
    """Factory: trả về classifier đang được cấu hình để dùng (config.USE_PHOBERT)."""
    if config.USE_PHOBERT:
        return PhoBERTIntentClassifier()
    return KeywordIntentClassifier()
