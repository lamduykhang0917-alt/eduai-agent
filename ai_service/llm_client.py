"""
llm_client.py
Gọi API của nhà cung cấp LLM bên ngoài (Claude hoặc Gemini) để chatbot diễn đạt câu trả lời
tự nhiên, dựa trên tài liệu môn học (RAG) và lịch sử hội thoại.

Điểm tích hợp DUY NHẤT cần sửa nếu muốn đổi nhà cung cấp AI khác (OpenAI, DeepSeek...):
viết thêm 1 hàm call_xxx() tương tự rồi thêm vào PROVIDERS, không cần sửa inference.py
hay bất kỳ router nào khác.
"""

import os
import time

import requests
from . import config


class LLMError(Exception):
    """Raised khi gọi LLM thất bại (thiếu API key, lỗi mạng, lỗi từ nhà cung cấp...)."""
    pass


RETRYABLE = {429, 500, 502, 503, 504, 529}


def _build_system_prompt(course: str = None, course_list=None, has_context: bool = False) -> str:
    system = config.LLM_SYSTEM_PROMPT
    if course_list:
        joined = ", ".join(course_list)
        system += (
            f" Hệ thống có sẵn tài liệu cho các môn: {joined}. Với các môn này hãy ưu tiên dùng tài liệu; "
            "với mọi môn/ngành khác vẫn trả lời bằng kiến thức chung và nói rõ đó là kiến thức bổ sung."
        )
    if course:
        system += f" Sinh viên đang học môn: {course}."
    if has_context:
        system += (
            " Câu hỏi đi kèm phần TÀI LIỆU THAM KHẢO trích từ giáo trình/slide của môn học. "
            "Hãy ưu tiên dùng thông tin trong tài liệu đó làm căn cứ chính, diễn đạt lại cho dễ hiểu "
            "(có thể dùng Markdown: danh sách, in đậm, khối code) và nêu tên tài liệu khi trích dẫn. "
            "Nếu tài liệu không đủ để trả lời, hãy bổ sung bằng kiến thức chung và nói rõ phần nào "
            "là kiến thức bổ sung ngoài tài liệu."
        )
    return system


def _compose_user_message(question: str, context: str = None) -> str:
    if not context:
        return question
    return f"TÀI LIỆU THAM KHẢO:\n{context}\n\n---\nCÂU HỎI CỦA SINH VIÊN: {question}"


def _merge_history(history, user_message: str, assistant_role: str) -> list:
    """Ghép lịch sử + câu hỏi mới thành danh sách lượt thoại xen kẽ user/assistant (API yêu cầu xen kẽ)."""
    turns = []
    for h in (history or []):
        role = "user" if h.get("role") == "user" else assistant_role
        text = (h.get("content") or "").strip()
        if not text:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["text"] += "\n" + text
        else:
            turns.append({"role": role, "text": text})
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    if turns and turns[-1]["role"] == "user":
        turns[-1]["text"] += "\n" + user_message
    else:
        turns.append({"role": "user", "text": user_message})
    return turns


def call_claude(question: str, course=None, course_list=None, context=None, history=None) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise LLMError("Chưa cấu hình ANTHROPIC_API_KEY.")

    turns = _merge_history(history, _compose_user_message(question, context), "assistant")
    payload = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": 1200,
        "system": _build_system_prompt(course, course_list, bool(context)),
        "messages": [{"role": t["role"], "content": t["text"]} for t in turns],
    }
    headers = {
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    last_error = "Không rõ nguyên nhân"
    for attempt in range(1, 3):
        try:
            resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=40)
        except requests.RequestException as e:
            last_error = f"Không thể kết nối tới Claude API: {e}"
        else:
            if resp.status_code == 200:
                data = resp.json()
                answer = "\n".join(b["text"] for b in data.get("content", []) if b.get("type") == "text").strip()
                if not answer:
                    raise LLMError("Claude API trả về nội dung rỗng")
                return answer
            last_error = f"Claude API trả về lỗi ({resp.status_code}): {resp.text[:300]}"
            if resp.status_code not in RETRYABLE:
                raise LLMError(last_error)
        if attempt < 2:
            time.sleep(1.5)
    raise LLMError(last_error)


def call_gemini(question: str, course=None, course_list=None, context=None, history=None) -> str:
    if not config.GEMINI_API_KEY:
        raise LLMError("Chưa cấu hình GEMINI_API_KEY.")

    turns = _merge_history(history, _compose_user_message(question, context), "model")
    payload = {
        "system_instruction": {"parts": [{"text": _build_system_prompt(course, course_list, bool(context))}]},
        "contents": [{"role": t["role"], "parts": [{"text": t["text"]}]} for t in turns],
    }

    # Gemini hay báo quá tải tạm thời (503/429): tự thử lại vài lần, và nếu có cấu hình
    # GEMINI_FALLBACK_MODEL thì thử thêm model dự phòng trước khi báo lỗi.
    models = [config.GEMINI_MODEL]
    fallback = os.environ.get("GEMINI_FALLBACK_MODEL", "").strip()
    if fallback and fallback != config.GEMINI_MODEL:
        models.append(fallback)

    attempts_per_model = 2
    last_error = "Không rõ nguyên nhân"
    resp = None

    for model in models:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={config.GEMINI_API_KEY}"
        )
        for attempt in range(1, attempts_per_model + 1):
            try:
                resp = requests.post(url, json=payload, timeout=30)
            except requests.RequestException as e:
                last_error = f"Không thể kết nối tới Gemini API: {e}"
                resp = None
            else:
                if resp.status_code == 200:
                    break
                last_error = f"Gemini API trả về lỗi ({resp.status_code}): {resp.text[:300]}"
                if resp.status_code not in RETRYABLE:
                    raise LLMError(last_error)
                resp = None
            if attempt < attempts_per_model:
                time.sleep(1.0)
        if resp is not None:
            break

    if resp is None:
        raise LLMError(last_error)

    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError):
        raise LLMError("Gemini API trả về dữ liệu không đúng định dạng mong đợi")


def call_groq(question: str, course=None, course_list=None, context=None, history=None) -> str:
    """Groq dùng giao diện tương thích OpenAI (chat/completions)."""
    if not config.GROQ_API_KEY:
        raise LLMError("Chưa cấu hình GROQ_API_KEY.")

    turns = _merge_history(history, _compose_user_message(question, context), "assistant")
    payload = {
        "model": config.GROQ_MODEL,
        "max_tokens": 1200,
        "temperature": 0.3,
        "messages": [{"role": "system", "content": _build_system_prompt(course, course_list, bool(context))}]
                    + [{"role": t["role"], "content": t["text"]} for t in turns],
    }
    headers = {"Authorization": f"Bearer {config.GROQ_API_KEY}", "Content-Type": "application/json"}

    last_error = "Không rõ nguyên nhân"
    for attempt in range(1, 3):
        try:
            resp = requests.post("https://api.groq.com/openai/v1/chat/completions",
                                 headers=headers, json=payload, timeout=30)
        except requests.RequestException as e:
            last_error = f"Không thể kết nối tới Groq API: {e}"
        else:
            if resp.status_code == 200:
                try:
                    answer = resp.json()["choices"][0]["message"]["content"].strip()
                except (KeyError, IndexError, TypeError, AttributeError):
                    raise LLMError("Groq API trả về dữ liệu không đúng định dạng mong đợi")
                if not answer:
                    raise LLMError("Groq API trả về nội dung rỗng")
                return answer
            last_error = f"Groq API trả về lỗi ({resp.status_code}): {resp.text[:300]}"
            if resp.status_code not in RETRYABLE:
                raise LLMError(last_error)
        if attempt < 2:
            time.sleep(1.0)
    raise LLMError(last_error)


PROVIDERS = {"claude": call_claude, "gemini": call_gemini, "groq": call_groq}


def available_providers() -> list:
    """Danh sách nhà cung cấp sẽ được thử (theo thứ tự), dựa trên LLM_PROVIDER và API key đã cấu hình."""
    keys = {"claude": bool(config.ANTHROPIC_API_KEY), "gemini": bool(config.GEMINI_API_KEY),
            "groq": bool(config.GROQ_API_KEY)}
    if config.LLM_PROVIDER == "auto":
        return [name for name in ("claude", "gemini", "groq") if keys[name]]
    if config.LLM_PROVIDER in PROVIDERS:
        return [config.LLM_PROVIDER] if keys[config.LLM_PROVIDER] else []
    return []


def ask_llm(question: str, course=None, course_list=None, context=None, history=None) -> str:
    """Điểm gọi chung — thử lần lượt các nhà cung cấp khả dụng, nhà nào lỗi thì chuyển sang nhà kế tiếp."""
    providers = available_providers()
    if not providers:
        raise LLMError("Chưa cấu hình API key cho Claude hoặc Gemini.")
    errors = []
    for name in providers:
        try:
            return PROVIDERS[name](question, course, course_list, context, history)
        except LLMError as e:
            errors.append(f"{name}: {e}")
    raise LLMError(" | ".join(errors))
