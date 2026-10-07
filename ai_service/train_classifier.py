import json
import os

from . import config

TRAIN_FILE = os.path.join(config.DATASET_DIR, "splits", "train.json")
VAL_FILE = os.path.join(config.DATASET_DIR, "splits", "val.json")
TEST_FILE = os.path.join(config.DATASET_DIR, "splits", "test.json")
REPORT_FILE = os.path.join(config.DATASET_DIR, "splits", "eval_report_phobert.json")


def load_samples(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_label_maps(samples):
    labels = sorted({s["intent"] for s in samples})
    label2id = {label: i for i, label in enumerate(labels)}
    id2label = {i: label for label, i in label2id.items()}
    return label2id, id2label


class IntentDataset:
    def __init__(self, samples, tokenizer, label2id, max_length):
        self.samples = samples
        self.tokenizer = tokenizer
        self.label2id = label2id
        self.max_length = max_length

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        import torch
        sample = self.samples[idx]
        encoded = self.tokenizer(
            sample["text"],
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
            return_tensors="pt",
        )
        item = {k: v.squeeze(0) for k, v in encoded.items()}
        item["labels"] = torch.tensor(self.label2id[sample["intent"]], dtype=torch.long)
        return item


def run_training(epochs=8, batch_size=8, learning_rate=5e-5):
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoTokenizer, AutoModelForSequenceClassification

    train_samples = load_samples(TRAIN_FILE) + load_samples(VAL_FILE)
    test_samples = load_samples(TEST_FILE)
    label2id, id2label = build_label_maps(train_samples + test_samples)

    tokenizer = AutoTokenizer.from_pretrained(config.PHOBERT_PRETRAINED)
    model = AutoModelForSequenceClassification.from_pretrained(
        config.PHOBERT_PRETRAINED,
        num_labels=len(label2id),
        id2label=id2label,
        label2id=label2id,
    )

    train_dataset = IntentDataset(train_samples, tokenizer, label2id, config.MAX_SEQ_LENGTH)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)

    model.train()
    for epoch in range(epochs):
        total_loss = 0.0
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            optimizer.zero_grad()
            outputs = model(**batch)
            loss = outputs.loss
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        print(f"epoch {epoch + 1}/{epochs} - loss {total_loss / len(train_loader):.4f}")

    os.makedirs(config.MODEL_PATH, exist_ok=True)
    os.makedirs(config.TOKENIZER_PATH, exist_ok=True)
    model.save_pretrained(config.MODEL_PATH)
    tokenizer.save_pretrained(config.TOKENIZER_PATH)

    report = evaluate_model(model, tokenizer, test_samples, label2id, id2label, device)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


def evaluate_model(model, tokenizer, test_samples, label2id, id2label, device):
    import torch

    model.eval()
    labels = sorted(label2id.keys())
    matrix = {t: {p: 0 for p in labels} for t in labels}
    correct = 0
    details = []

    with torch.no_grad():
        for sample in test_samples:
            inputs = tokenizer(
                sample["text"],
                truncation=True,
                padding="max_length",
                max_length=config.MAX_SEQ_LENGTH,
                return_tensors="pt",
            ).to(device)
            logits = model(**inputs).logits
            pred_id = int(torch.argmax(logits, dim=-1)[0])
            pred_label = id2label[pred_id]
            true_label = sample["intent"]
            matrix[true_label][pred_label] += 1
            is_correct = pred_label == true_label
            if is_correct:
                correct += 1
            details.append({
                "text": sample["text"],
                "true_intent": true_label,
                "predicted_intent": pred_label,
                "correct": is_correct,
            })

    per_label = {}
    for label in labels:
        tp = matrix[label][label]
        fp = sum(matrix[other][label] for other in labels if other != label)
        fn = sum(matrix[label][other] for other in labels if other != label)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        per_label[label] = {"precision": precision, "recall": recall, "f1": f1}

    n = len(per_label) or 1
    macro = {
        "precision": sum(v["precision"] for v in per_label.values()) / n,
        "recall": sum(v["recall"] for v in per_label.values()) / n,
        "f1": sum(v["f1"] for v in per_label.values()) / n,
    }
    accuracy = correct / len(test_samples) if test_samples else 0.0

    return {
        "model": "PhoBERTIntentClassifier",
        "base_checkpoint": config.PHOBERT_PRETRAINED,
        "test_set_size": len(test_samples),
        "accuracy": round(accuracy, 4),
        "precision_macro": round(macro["precision"], 4),
        "recall_macro": round(macro["recall"], 4),
        "f1_macro": round(macro["f1"], 4),
        "per_label": {k: {m: round(v, 4) for m, v in val.items()} for k, val in per_label.items()},
        "confusion_matrix": matrix,
        "labels": labels,
        "details": details,
    }


if __name__ == "__main__":
    report = run_training()
    print(f"Accuracy: {report['accuracy'] * 100:.2f}%")
    print(f"Precision (macro): {report['precision_macro'] * 100:.2f}%")
    print(f"Recall (macro): {report['recall_macro'] * 100:.2f}%")
    print(f"F1-score (macro): {report['f1_macro'] * 100:.2f}%")
    print(f"Checkpoint saved to: {config.MODEL_PATH}")
    print(f"Report saved to: {REPORT_FILE}")
