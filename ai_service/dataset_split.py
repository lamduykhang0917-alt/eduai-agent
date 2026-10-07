import json
import os
import random

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
INTENTS_FILE = os.path.join(DATASET_DIR, "intents.json")
SPLITS_DIR = os.path.join(DATASET_DIR, "splits")

SAMPLES_FILE = os.path.join(DATASET_DIR, "intent_samples.json")  # 60 câu/nhãn, bổ sung cho intents.json

TRAIN_RATIO = 0.7
VAL_RATIO = 0.15
TEST_RATIO = 0.15
SEED = 42


def load_samples():
    with open(INTENTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    samples, seen = [], set()
    for intent in data["intents"]:
        tag = intent["tag"]
        for pattern in intent["patterns"]:
            samples.append({"text": pattern, "intent": tag})
            seen.add(pattern.strip().lower())
    if os.path.exists(SAMPLES_FILE):
        with open(SAMPLES_FILE, "r", encoding="utf-8") as f:
            extra = json.load(f)
        for tag, texts in extra.items():
            for text in texts:
                if text.strip().lower() not in seen:
                    seen.add(text.strip().lower())
                    samples.append({"text": text, "intent": tag})
    return samples


def group_by_intent(samples):
    grouped = {}
    for s in samples:
        grouped.setdefault(s["intent"], []).append(s)
    return grouped


def split_samples(samples):
    random.Random(SEED).shuffle(samples)
    n = len(samples)
    n_train = max(1, round(n * TRAIN_RATIO))
    n_val = max(1, round(n * VAL_RATIO)) if n - n_train > 1 else 0
    n_test = n - n_train - n_val
    if n_test < 0:
        n_test = 0
        n_val = n - n_train
    train = samples[:n_train]
    val = samples[n_train:n_train + n_val]
    test = samples[n_train + n_val:n_train + n_val + n_test]
    return train, val, test


def build_splits():
    samples = load_samples()
    grouped = group_by_intent(samples)

    train_all, val_all, test_all = [], [], []
    summary = {}

    for tag, items in grouped.items():
        train, val, test = split_samples(items)
        train_all.extend(train)
        val_all.extend(val)
        test_all.extend(test)
        summary[tag] = {
            "train": len(train),
            "val": len(val),
            "test": len(test),
            "total": len(items),
        }

    random.Random(SEED).shuffle(train_all)
    random.Random(SEED + 1).shuffle(val_all)
    random.Random(SEED + 2).shuffle(test_all)

    os.makedirs(SPLITS_DIR, exist_ok=True)

    with open(os.path.join(SPLITS_DIR, "train.json"), "w", encoding="utf-8") as f:
        json.dump(train_all, f, ensure_ascii=False, indent=2)
    with open(os.path.join(SPLITS_DIR, "val.json"), "w", encoding="utf-8") as f:
        json.dump(val_all, f, ensure_ascii=False, indent=2)
    with open(os.path.join(SPLITS_DIR, "test.json"), "w", encoding="utf-8") as f:
        json.dump(test_all, f, ensure_ascii=False, indent=2)
    with open(os.path.join(SPLITS_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return {
        "train": len(train_all),
        "val": len(val_all),
        "test": len(test_all),
        "total": len(samples),
        "summary": summary,
    }


if __name__ == "__main__":
    result = build_splits()
    print(json.dumps(result, ensure_ascii=False, indent=2))
