import json
import os
import tempfile

from .classifier import KeywordIntentClassifier
from . import config

DATASET_DIR = os.path.join(config.BASE_DIR, "dataset")
SPLITS_DIR = os.path.join(DATASET_DIR, "splits")
TRAIN_FILE = os.path.join(SPLITS_DIR, "train.json")
VAL_FILE = os.path.join(SPLITS_DIR, "val.json")
TEST_FILE = os.path.join(SPLITS_DIR, "test.json")
REPORT_FILE = os.path.join(SPLITS_DIR, "eval_report.json")


def load_samples(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_train_only_classifier():
    train_samples = load_samples(TRAIN_FILE) + load_samples(VAL_FILE)
    by_intent = {}
    for sample in train_samples:
        by_intent.setdefault(sample["intent"], []).append(sample["text"])

    original = json.load(open(config.INTENTS_FILE, "r", encoding="utf-8"))
    tag_to_meta = {intent["tag"]: intent for intent in original.get("intents", [])}

    intents_data = {"intents": []}
    for tag, patterns in by_intent.items():
        meta = tag_to_meta.get(tag, {})
        intents_data["intents"].append({
            "tag": tag,
            "patterns": patterns,
            "description": meta.get("description", ""),
        })

    fd, tmp_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(intents_data, f, ensure_ascii=False)

    classifier = KeywordIntentClassifier(intents_path=tmp_path)
    os.remove(tmp_path)
    return classifier


def confusion_matrix(samples, predictions, row_labels, col_labels):
    matrix = {t: {p: 0 for p in col_labels} for t in row_labels}
    for sample, pred in zip(samples, predictions):
        true_tag = sample["intent"]
        matrix[true_tag][pred] += 1
    return matrix


def precision_recall_f1(matrix, labels):
    per_label = {}
    for label in labels:
        tp = matrix[label][label]
        fp = sum(matrix[other][label] for other in labels if other != label)
        # FN gồm cả các câu bị dự đoán thành "unknown" (cột thừa ngoài danh sách nhãn)
        fn = sum(count for pred, count in matrix[label].items() if pred != label)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        per_label[label] = {"precision": precision, "recall": recall, "f1": f1}
    return per_label


def macro_average(per_label):
    n = len(per_label)
    if n == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    return {
        "precision": sum(v["precision"] for v in per_label.values()) / n,
        "recall": sum(v["recall"] for v in per_label.values()) / n,
        "f1": sum(v["f1"] for v in per_label.values()) / n,
    }


def run_evaluation():
    samples = load_samples(TEST_FILE)
    classifier = build_train_only_classifier()
    true_labels = {s["intent"] for s in samples}

    predictions = []
    correct = 0
    details = []
    for sample in samples:
        result = classifier.predict(sample["text"])
        predictions.append(result.tag)
        is_correct = result.tag == sample["intent"]
        if is_correct:
            correct += 1
        details.append({
            "text": sample["text"],
            "true_intent": sample["intent"],
            "predicted_intent": result.tag,
            "confidence": round(result.confidence, 3),
            "correct": is_correct,
        })

    labels = sorted(true_labels)
    col_labels = sorted(true_labels | {"unknown"})
    accuracy = correct / len(samples) if samples else 0.0
    matrix = confusion_matrix(samples, predictions, labels, col_labels)
    per_label = precision_recall_f1(matrix, labels)
    macro = macro_average(per_label)

    report = {
        "model": "KeywordIntentClassifier",
        "evaluation_method": "classifier trained on train+val split patterns only, evaluated on held-out test split",
        "test_set_size": len(samples),
        "accuracy": round(accuracy, 4),
        "precision_macro": round(macro["precision"], 4),
        "recall_macro": round(macro["recall"], 4),
        "f1_macro": round(macro["f1"], 4),
        "per_label": {k: {m: round(v, 4) for m, v in val.items()} for k, val in per_label.items()},
        "confusion_matrix": matrix,
        "labels": labels,
        "details": details,
    }

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report


if __name__ == "__main__":
    report = run_evaluation()
    print(f"Accuracy: {report['accuracy'] * 100:.2f}%")
    print(f"Precision (macro): {report['precision_macro'] * 100:.2f}%")
    print(f"Recall (macro): {report['recall_macro'] * 100:.2f}%")
    print(f"F1-score (macro): {report['f1_macro'] * 100:.2f}%")
    print(f"Test set size: {report['test_set_size']}")
    print(f"Report saved to: {REPORT_FILE}")
