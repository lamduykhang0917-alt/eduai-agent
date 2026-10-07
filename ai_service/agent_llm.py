"""
agent_llm.py
Lớp gọi LLM có hỗ trợ TOOL CALLING (function calling) cho AI Agent của Đồ án 2.

Agent không phụ thuộc một nhà cung cấp cụ thể: hàm `complete()` nhận hội thoại ở một
định dạng trung lập, tự chuyển sang định dạng của Claude / Gemini / Groq, gọi API, rồi
trả kết quả về cùng một dạng. Nhà cung cấp nào lỗi thì chuyển sang nhà kế tiếp
(cùng thứ tự ưu tiên với llm_client.available_providers()).

ĐỊNH DẠNG TRUNG LẬP
  Công cụ:   {"name", "description", "parameters": <JSON Schema>}
  Hội thoại: {"role": "user", "content": str}
             {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args"}]}
             {"role": "tool", "tool_call_id", "name", "content": str(JSON)}
  Kết quả:   {"text": str, "tool_calls": [...], "provider": str, "raw": {...}}
"""

import json
import time
import uuid

import requests

from . import config
from .llm_client import LLMError, RETRYABLE, available_providers


def _merge_same_role(messages: list) -> list:
    """Gộp các lượt user liên tiếp (API của các nhà cung cấp yêu cầu xen kẽ vai trò)."""
    merged = []
    for m in messages:
        if merged and m["role"] == "user" and merged[-1]["role"] == "user":
            merged[-1] = {"role": "user", "content": merged[-1]["content"] + "\n" + m["content"]}
        else:
            merged.append(dict(m))
    return merged


def _post(url: str, headers: dict, payload: dict, name: str, timeout: int = 45) -> dict:
    """POST kèm thử lại 1 lần với các lỗi tạm thời (quá tải, hết lượt)."""
    last = "Không rõ nguyên nhân"
    for attempt in range(2):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as e:
            last = f"Không thể kết nối tới {name}: {e}"
        else:
            if resp.status_code == 200:
                return resp.json()
            last = f"{name} trả về lỗi ({resp.status_code}): {resp.text[:300]}"
            if resp.status_code not in RETRYABLE:
                raise LLMError(last)
        if attempt == 0:
            time.sleep(1.2)
    raise LLMError(last)


# ---------------------------------------------------------------- Claude
def _claude_messages(messages: list) -> list:
    out = []
    for m in _merge_same_role(messages):
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls", []):
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["args"]})
            out.append({"role": "assistant", "content": blocks or m.get("content", "")})
        else:  # tool → khối tool_result nằm trong lượt user; các kết quả liên tiếp gộp chung 1 lượt
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def _call_claude(system, messages, tools):
    if not config.ANTHROPIC_API_KEY:
        raise LLMError("Chưa cấu hình ANTHROPIC_API_KEY.")
    data = _post(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
         "content-type": "application/json"},
        {"model": config.ANTHROPIC_MODEL, "max_tokens": 1500, "system": system,
         "messages": _claude_messages(messages),
         "tools": [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                   for t in tools]},
        "Claude API",
    )
    blocks = data.get("content", [])
    return {
        "text": "\n".join(b["text"] for b in blocks if b.get("type") == "text").strip(),
        "tool_calls": [{"id": b["id"], "name": b["name"], "args": b.get("input", {})}
                       for b in blocks if b.get("type") == "tool_use"],
    }


# ---------------------------------------------------------------- Gemini
def _gemini_contents(messages: list) -> list:
    contents = []
    for m in _merge_same_role(messages):
        if m["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        elif m["role"] == "assistant":
            raw = (m.get("raw") or {}).get("gemini_parts")
            if raw:  # giữ nguyên các phần Gemini trả về (kể cả thoughtSignature mà Gemini 3 yêu cầu gửi lại)
                parts = raw
            else:
                parts = [{"text": m["content"]}] if m.get("content") else []
                parts += [{"functionCall": {"name": tc["name"], "args": tc["args"]}}
                          for tc in m.get("tool_calls", [])]
            contents.append({"role": "model", "parts": parts or [{"text": " "}]})
        else:
            part = {"functionResponse": {"name": m["name"], "response": {"result": json.loads(m["content"])}}}
            if contents and contents[-1]["role"] == "user" and contents[-1]["parts"] \
                    and "functionResponse" in contents[-1]["parts"][0]:
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
    return contents


def _call_gemini(system, messages, tools):
    if not config.GEMINI_API_KEY:
        raise LLMError("Chưa cấu hình GEMINI_API_KEY.")
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": _gemini_contents(messages),
        "tools": [{"functionDeclarations": [
            {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
            if t["parameters"].get("properties") else
            {"name": t["name"], "description": t["description"]}  # Gemini không nhận schema rỗng
            for t in tools]}],
    }
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}"
           f":generateContent?key={config.GEMINI_API_KEY}")
    data = _post(url, {"content-type": "application/json"}, payload, "Gemini API")
    try:
        parts = data["candidates"][0]["content"].get("parts", [])
    except (KeyError, IndexError, TypeError):
        raise LLMError("Gemini API trả về dữ liệu không đúng định dạng mong đợi")
    return {
        "text": "\n".join(p["text"] for p in parts if "text" in p and not p.get("thought")).strip(),
        "tool_calls": [{"id": "call_" + uuid.uuid4().hex[:10], "name": p["functionCall"]["name"],
                        "args": p["functionCall"].get("args", {})} for p in parts if "functionCall" in p],
        "raw": {"gemini_parts": parts},
    }


# ---------------------------------------------------------------- Groq (định dạng OpenAI)
def _groq_messages(system: str, messages: list) -> list:
    out = [{"role": "system", "content": system}]
    for m in _merge_same_role(messages):
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant", "content": m.get("content") or None,
                "tool_calls": [{"id": tc["id"], "type": "function",
                                "function": {"name": tc["name"], "arguments": json.dumps(tc["args"], ensure_ascii=False)}}
                               for tc in m["tool_calls"]],
            })
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def _call_groq(system, messages, tools):
    if not config.GROQ_API_KEY:
        raise LLMError("Chưa cấu hình GROQ_API_KEY.")
    data = _post(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {config.GROQ_API_KEY}", "Content-Type": "application/json"},
        {"model": config.GROQ_MODEL, "max_tokens": 1500, "temperature": 0.2,
         "messages": _groq_messages(system, messages),
         "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                      "parameters": t["parameters"]}} for t in tools]},
        "Groq API",
    )
    try:
        msg = data["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            args = tc["function"].get("arguments") or "{}"
            calls.append({"id": tc["id"], "name": tc["function"]["name"],
                          "args": json.loads(args) if isinstance(args, str) else args})
    except (KeyError, IndexError, TypeError, ValueError):
        raise LLMError("Groq API trả về dữ liệu không đúng định dạng mong đợi")
    return {"text": (msg.get("content") or "").strip(), "tool_calls": calls}


_CALLERS = {"claude": _call_claude, "gemini": _call_gemini, "groq": _call_groq}


def complete(system: str, messages: list, tools: list) -> dict:
    """Gọi LLM với danh sách công cụ; thử lần lượt các nhà cung cấp khả dụng."""
    providers = available_providers()
    if not providers:
        raise LLMError("Chưa cấu hình API key (ANTHROPIC_API_KEY, GEMINI_API_KEY hoặc GROQ_API_KEY) cho AI Agent.")
    errors = []
    for name in providers:
        try:
            result = _CALLERS[name](system, messages, tools)
            if not result["text"] and not result["tool_calls"]:
                raise LLMError("trả về nội dung rỗng")
            result["provider"] = name
            result.setdefault("raw", {})
            return result
        except LLMError as e:
            errors.append(f"{name}: {e}")
    raise LLMError(" | ".join(errors))
