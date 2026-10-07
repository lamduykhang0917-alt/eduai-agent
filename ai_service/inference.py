"""
inference.py
Luồng xử lý chính của AI Chatbot.

Có 2 chế độ (xem config.LLM_PROVIDER):

1. "claude" / "gemini" (MẶC ĐỊNH) — Chatbot trả lời TỰ DO bất kỳ câu hỏi nào
   bằng cách gọi thẳng API của Claude/Gemini, không giới hạn trong dataset.
   Nếu chưa cấu hình API key hoặc gọi API lỗi (mất mạng, hết quota...), hệ
   thống TỰ ĐỘNG rơi về chế độ "dataset" bên dưới cho câu hỏi đó, kèm ghi chú
   rõ trong câu trả lời, để chatbot không bao giờ "im lặng" hoàn toàn.

2. "dataset" — chế độ cũ: preprocessing -> phân loại ý định (intent) ->
   tìm kiếm trong knowledge base/dataset -> sinh câu trả lời. Chỉ trả lời được
   các câu hỏi đã có trong dataset; nếu độ tin cậy thấp sẽ báo "chưa tìm thấy
   thông tin phù hợp" thay vì đoán bừa.

Đây là điểm tích hợp duy nhất mà router /api/chat gọi tới — router không cần
biết chatbot đang chạy chế độ nào.
"""

import json
import re
from typing import Optional

from . import config
from . import llm_client
from . import rag
from .classifier import get_classifier

_classifier = None
_knowledge_base = None


def _load_knowledge_base():
    global _knowledge_base
    if _knowledge_base is None:
        with open(config.KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            _knowledge_base = json.load(f).get("knowledge_base", [])
    return _knowledge_base


def _get_classifier():
    global _classifier
    if _classifier is None:
        _classifier = get_classifier()
    return _classifier


def _search_knowledge(question: str, course: Optional[str] = None) -> Optional[dict]:
    """Tìm bản ghi phù hợp nhất trong knowledge base theo từ khóa.

    Kết quả được gắn thêm hai chỉ số: "_score" (điểm từ khóa) và "_coverage" (tỉ lệ từ trong câu hỏi
    xuất hiện trong bản ghi) để biết bản ghi có thật sự trả lời đúng câu hỏi hay chỉ trùng một từ khóa."""
    kb = _load_knowledge_base()
    lowered = question.lower()

    best_item = None
    best_score = 0

    for item in kb:
        if course and item.get("course") != course:
            continue
        keyword_hits = sum(1 for kw in item.get("keywords", []) if kw in lowered)
        topic_hits = 1 if item.get("topic", "").lower() in lowered else 0
        score = keyword_hits * 2 + topic_hits
        if score > best_score:
            best_score = score
            best_item = item

    if best_item is None:
        return None
    q_tokens = set(rag._tokenize(question))
    # Chỉ so với "danh tính" của bản ghi (chủ đề, từ khóa, câu hỏi mẫu) — không so với phần giải thích dài,
    # vì phần đó chứa nhiều từ phổ biến khiến mọi câu hỏi đều trông như "khớp".
    text = " ".join([best_item.get("topic", ""), " ".join(best_item.get("keywords", [])), best_item.get("question", "")])
    item_tokens = set(rag._tokenize(text))
    coverage = len(q_tokens & item_tokens) / len(q_tokens) if q_tokens else 0.0
    return dict(best_item, _score=best_score, _coverage=coverage)


NO_ANSWER_MESSAGE = (
    "Xin lỗi, tôi chưa tìm thấy thông tin phù hợp với câu hỏi này. "
    "Bạn có thể diễn đạt câu hỏi rõ hơn hoặc chọn môn học liên quan."
)

# Ngưỡng điểm tương đồng tối thiểu để chấp nhận một đoạn tài liệu làm câu trả lời.
RAG_MIN_SCORE = 0.25

_GREET_WORDS = {"hi", "hello", "helo", "hey", "alo", "chào", "chao", "hii", "hí", "xin"}
_BYE_WORDS = {"bye", "goodbye", "tạm biệt", "tam biet", "cảm ơn", "cám ơn", "cam on", "thanks", "thank"}

# Intent chỉ dẫn sang tính năng khác của hệ thống (không cần tra tài liệu).
_FEATURE_REPLIES = {
    "generate_quiz": "Bạn có thể tạo câu hỏi ôn tập ở mục **Ôn tập & Kiểm tra** trên thanh menu: chọn môn học, số câu và độ khó rồi bấm *Tạo câu hỏi*.",
    "exam": "Bạn có thể làm bài kiểm tra ở mục **Ôn tập & Kiểm tra** trên thanh menu: chọn môn học, số câu và độ khó rồi bấm *Tạo câu hỏi*.",
    "result": "Kết quả các bài kiểm tra của bạn nằm ở mục **Tiến độ học tập**; sau mỗi lần nộp bài bạn cũng thấy chi tiết từng câu và lời giải thích.",
    "learning_progress": "Bạn xem tiến độ theo từng môn, điểm theo thời gian và số bài đã làm ở mục **Tiến độ học tập** trên thanh menu.",
    "learning_recommendation": "Hệ thống gợi ý nội dung cần ôn dựa trên các câu bạn làm sai. Bạn xem ở **Dashboard** (mục Đề xuất học tập) hoặc làm thêm bài ở **Ôn tập & Kiểm tra**.",
}


def _normalize(text: str) -> list:
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


def _quick_intent(question: str):
    """Nhận diện chào hỏi / tạm biệt kể cả khi gõ sai chính tả nhẹ (vd: 'Helo')."""
    words = _normalize(question)
    if not words or len(words) > 4:
        return None
    text = " ".join(words)
    if words[0] in _GREET_WORDS and (len(words) <= 3):
        return "greeting"
    if text in _BYE_WORDS or words[0] in {"bye", "goodbye", "thanks"} or text.startswith(("tạm biệt", "cảm ơn", "cám ơn")):
        return "goodbye"
    return None


def _format_excerpt(text: str, limit: int = 700) -> str:
    """Làm sạch đoạn trích từ tài liệu: bỏ dòng quá ngắn, gộp khoảng trắng, cắt gọn theo câu/từ."""
    lines = []
    for raw in text.splitlines():
        line = rag.clean_slide_line(raw)
        if len(line) >= 4 and not line.isdigit():
            lines.append(line)
    body = " ".join(lines) if lines else " ".join(text.split())
    if len(body) > limit:
        body = body[:limit]
        cut = max(body.rfind(". "), body.rfind("; "))
        body = (body[:cut + 1] if cut > limit * 0.5 else body.rsplit(" ", 1)[0]) + " …"
    return body


def _document_answer(question: str, course: Optional[str]) -> Optional[dict]:
    """Trả lời bằng cách tra cứu trong nội dung tài liệu môn học (RAG theo từ khóa)."""
    try:
        hits = rag.search(question, course=course, top_k=3)
    except Exception:
        return None
    hits = [h for h in hits if h["score"] >= RAG_MIN_SCORE]
    if not hits:
        return None

    best = hits[0]
    excerpt = _format_excerpt(best["content"])
    if len(excerpt) < 220:
        # Đoạn tìm được quá ngắn (thường là tiêu đề slide) -> ghép thêm các đoạn liền sau trong cùng tài liệu.
        more = rag.following_chunks(best["document_id"], best["chunk_index"], 2)
        excerpt = _format_excerpt("\n".join([best["content"]] + more), 700)
    lines = [f"Theo tài liệu **{best['document_title']}**"
             + (f" (trang {best['page']})" if best.get("page") else "")
             + f", môn *{best['course']}*:", "", excerpt]
    seen = {best["chunk_id"]}
    extra = [h for h in hits[1:] if h["chunk_id"] not in seen and h["score"] >= max(RAG_MIN_SCORE, best["score"] * 0.6)]
    if extra:
        h = extra[0]
        lines += ["", f"**Xem thêm** — {h['document_title']}" + (f" (trang {h['page']})" if h.get("page") else "") + ":",
                  "", _format_excerpt(h["content"], 400)]
    return {
        "answer": "\n".join(lines),
        "source": {"id": f"doc{best['document_id']}", "course": best["course"],
                   "chapter": best.get("chapter") or "", "topic": best["document_title"]},
        "score": best["score"],
    }


def _summary_of_document(question: str, course: Optional[str] = None) -> Optional[dict]:
    """Xử lý yêu cầu tóm tắt một tài liệu/chương cụ thể:
    'Tóm tắt tài liệu: <tên file>', 'Tóm tắt nội dung: <tên chương>', 'Tóm tắt chương 2 môn <tên môn>'."""
    outline = None
    m = re.match(r"\s*tóm tắt (?:tài liệu|nội dung)\s*:\s*(.+)$", question, flags=re.IGNORECASE)
    if m:
        outline = rag.document_outline(m.group(1))
    else:
        m = re.search(r"tóm tắt\s+(?:nội dung\s+)?(?:chương|chuong|chapter|bài)\s*(\d+)", question, flags=re.IGNORECASE)
        if m:
            lowered = question.lower()
            course_name = next((c for c in rag.course_names() if c.lower() in lowered), None) or course
            if course_name:
                outline = rag.document_outline(course_name=course_name, chapter_no=int(m.group(1)))
    if outline is None:
        return None
    if not outline["points"]:
        answer = f"Tài liệu **{outline['title']}** chưa có nội dung văn bản để tóm tắt."
    else:
        bullets = "\n".join(f"- {p}" for p in outline["points"])
        answer = (f"**Các ý chính của {outline['title']}** (môn *{outline['course']}*):\n\n{bullets}\n\n"
                  "Bạn có thể hỏi cụ thể hơn về một nội dung bên trên để mình trích đoạn chi tiết.")
    return {"answer": answer, "source": {"id": "doc", "course": outline["course"], "chapter": "", "topic": outline["title"]}}


def _dataset_driven_response(question: str, course: Optional[str], level: str) -> dict:
    """Chế độ dùng nội dung có sẵn: intent -> knowledge base -> tài liệu môn học (RAG)."""
    def reply(intent, confidence, answer, source=None, clarify=False):
        return {"intent": intent, "confidence": confidence, "answer": answer,
                "source": source, "needs_clarification": clarify}

    quick = _quick_intent(question)
    if quick == "greeting":
        return reply("greeting", 1.0, "Xin chào! Tôi có thể giúp gì cho việc học của bạn hôm nay?")
    if quick == "goodbye":
        return reply("goodbye", 1.0, "Tạm biệt! Chúc bạn học tập hiệu quả. Hẹn gặp lại bạn!")

    summary = _summary_of_document(question, course)
    if summary:
        return reply("summary", 1.0, summary["answer"], summary["source"])

    intent = _get_classifier().predict(question)
    if intent.tag in _FEATURE_REPLIES and intent.confidence >= 0.6:
        return reply(intent.tag, intent.confidence, _FEATURE_REPLIES[intent.tag])

    item = _search_knowledge(question, course=course)
    strong_kb = item is not None and (item["_score"] >= 3 or item["_coverage"] >= 0.75)
    doc = None if strong_kb else _document_answer(question, course)

    if strong_kb or (doc is None and item is not None and item["_coverage"] >= 0.4):
        if intent.tag == "summary":
            answer = f"Tóm tắt về \"{item['topic']}\": {item['answer_basic']}"
        elif intent.tag == "explanation" or level == "advanced":
            answer = item["answer_detailed"] + " Ví dụ: " + item.get("example", "")
        else:
            answer = item["answer_basic"]
        return reply(intent.tag, intent.confidence, answer,
                     {"id": item["id"], "course": item["course"], "chapter": item["chapter"], "topic": item["topic"]})

    if doc:
        return reply(intent.tag if intent.tag != "unknown" else "knowledge_question",
                     min(0.99, max(intent.confidence, doc["score"])), doc["answer"], doc["source"])

    if intent.tag == "greeting":
        return reply("greeting", intent.confidence, "Xin chào! Tôi có thể giúp gì cho việc học của bạn hôm nay?")
    if intent.tag == "goodbye":
        return reply("goodbye", intent.confidence, "Tạm biệt! Chúc bạn học tập hiệu quả. Hẹn gặp lại bạn!")
    return reply("unknown", intent.confidence, NO_ANSWER_MESSAGE, clarify=True)


def _retrieval_query(question: str, history) -> str:
    """Câu hỏi nối tiếp ngắn ('giải thích kỹ hơn', 'cho ví dụ') không đủ từ khóa để tra tài liệu:
    ghép thêm câu hỏi trước của sinh viên."""
    generic = {"giải", "thích", "kỹ", "hơn", "đi", "ví", "dụ", "thêm", "chi", "tiết", "cho", "hãy", "nữa",
               "rõ", "làm", "sao", "tại", "vì", "sao", "đơn", "giản", "ngắn", "gọn", "tóm", "tắt", "lại", "nói"}
    if history and len([t for t in rag._tokenize(question) if t not in generic]) < 2:
        previous = [h["content"] for h in history if h.get("role") == "user"]
        if previous:
            return previous[-1] + " " + question
    return question


def _build_context(question: str, course: Optional[str]) -> tuple:
    """Gom nội dung tham khảo cho LLM: mục kiến thức khớp + vài đoạn tài liệu liên quan nhất.
    Trả về (văn bản ngữ cảnh, nguồn chính để hiện dưới câu trả lời)."""
    parts, source = [], None
    item = _search_knowledge(question, course=course)
    if item is not None and (item["_score"] >= 3 or item["_coverage"] >= 0.75):
        parts.append(f"[Kiến thức: {item['topic']} — môn {item['course']}]\n{item['answer_detailed']}")
        source = {"id": item["id"], "course": item["course"], "chapter": item["chapter"], "topic": item["topic"]}
    try:
        hits = [h for h in rag.search(question, course=course, top_k=4) if h["score"] >= 0.15]
    except Exception:
        hits = []
    for h in hits:
        page = f", trang {h['page']}" if h.get("page") else ""
        parts.append(f"[Tài liệu: {h['document_title']}{page} — môn {h['course']}]\n{_format_excerpt(h['content'], 900)}")
    if hits and source is None:
        source = {"id": f"doc{hits[0]['document_id']}", "course": hits[0]["course"],
                  "chapter": hits[0].get("chapter") or "", "topic": hits[0]["document_title"]}
    return "\n\n".join(parts)[:6000], source


def _llm_driven_response(question: str, course: Optional[str], course_list=None, history=None) -> dict:
    """Chế độ gọi AI: truy xuất tài liệu liên quan (RAG) rồi nhờ Claude/Gemini diễn đạt câu trả lời."""
    context, source = _build_context(_retrieval_query(question, history), course)
    answer = llm_client.ask_llm(question, course=course, course_list=course_list,
                                context=context or None, history=history)
    return {
        "intent": "llm_rag_chat" if context else "llm_free_chat",
        "confidence": 1.0,
        "answer": answer,
        "source": source,
        "needs_clarification": False,
    }


def generate_response(question: str, course: Optional[str] = None,
                       level: str = "basic", course_list=None, history=None) -> dict:
    """
    Trả về dict:
      {
        "intent": str,
        "confidence": float,
        "answer": str,
        "source": Optional[dict],   # nguồn (mục kiến thức hoặc tài liệu) dùng để trả lời
        "needs_clarification": bool
      }
    Chế độ "auto"/"claude"/"gemini": chào hỏi trả lời ngay; còn lại gọi AI kèm tài liệu liên quan.
    AI lỗi hoặc chưa cấu hình key -> tự dùng nội dung có sẵn (dataset), người dùng luôn nhận được câu trả lời.
    """
    if config.LLM_PROVIDER in ("auto", "claude", "gemini") and llm_client.available_providers():
        if _quick_intent(question):
            return _dataset_driven_response(question, course, level)
        try:
            return _llm_driven_response(question, course, course_list, history)
        except llm_client.LLMError as e:
            fallback = _dataset_driven_response(question, course, level)
            reason = str(e)
            if any(code in reason for code in ("503", "529", "UNAVAILABLE", "429", "overloaded")):
                reason = "dịch vụ AI đang quá tải"
            elif len(reason) > 120:
                reason = reason[:120].replace("\n", " ") + "..."
            fallback["answer"] = (
                f"*(Chưa gọi được AI: {reason}. Mình trả lời tạm từ tài liệu có sẵn.)*\n\n" + fallback["answer"]
            )
            return fallback

    return _dataset_driven_response(question, course, level)
