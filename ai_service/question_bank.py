"""Ngân hàng câu hỏi gốc từ các file dataset (quiz.json, quiz_extra.json, knowledge.json).
Chỉ dùng để nạp vào database một lần (seed); sau đó database là nguồn dữ liệu chính
để admin có thể xem/sửa/xóa câu hỏi."""

import json
import os
import random

from . import config as ai_config


def _read_questions(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("questions", [])


def _questions_from_knowledge():
    """Sinh câu hỏi trắc nghiệm từ knowledge base: câu hỏi = trường "question",
    đáp án đúng = "answer_basic", 3 đáp án nhiễu lấy từ các mục kiến thức khác.
    Vị trí đáp án đúng được cố định theo id nên không đổi giữa các lần gọi."""
    try:
        with open(ai_config.KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            kb = json.load(f).get("knowledge_base", [])
    except OSError:
        return []

    def short(text, limit=200):
        text = " ".join(text.split())
        return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."

    result = []
    for idx, item in enumerate(kb):
        if not item.get("question") or not item.get("answer_basic"):
            continue
        rng = random.Random(item["id"])
        others = [o for o in kb if o["id"] != item["id"] and o.get("answer_basic")]
        same_course = [o for o in others if o.get("course") == item.get("course")]
        rng.shuffle(same_course)
        rest = [o for o in others if o not in same_course]
        rng.shuffle(rest)
        distractors = [short(o["answer_basic"]) for o in (same_course + rest)[:3]]
        if len(distractors) < 3:
            continue
        options = distractors
        pos = rng.randrange(4)
        options.insert(pos, short(item["answer_basic"]))
        result.append({
            "id": f"kbq_{item['id']}",
            "course": item["course"],
            "chapter": item.get("chapter", ""),
            "difficulty": "basic",
            "content": item["question"],
            "options": dict(zip("ABCD", options)),
            "correct_answer": "ABCD"[pos],
            "explanation": short(item.get("answer_detailed") or item["answer_basic"], 320),
        })
    return result



def load_pack_questions():
    """Các gói câu hỏi bổ sung dataset/qpack_*.json -> {tên gói: [câu hỏi]} (mỗi gói nạp vào DB một lần)."""
    import glob
    base = os.path.dirname(ai_config.QUIZ_FILE)
    return {os.path.basename(p)[:-5]: _read_questions(p) for p in sorted(glob.glob(os.path.join(base, "qpack_*.json")))}


def load_all_questions():
    """quiz.json (gốc) + quiz_extra.json (bổ sung) + câu hỏi sinh từ knowledge base."""
    return _read_questions(ai_config.QUIZ_FILE) + _read_questions(ai_config.QUIZ_EXTRA_FILE) + _questions_from_knowledge()
