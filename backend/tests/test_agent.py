"""
Kiểm thử AI Agent (Đồ án 2). Chạy từ thư mục backend:   python -m tests.test_agent

- Chạy trên BẢN SAO của database, không đụng dữ liệu thật.
- LLM được thay bằng một "LLM giả" có kịch bản, nên không cần API key, không tốn lượt gọi.
  Phần này kiểm tra: vòng lặp Agent, từng công cụ, bước xác nhận, phân quyền, giới hạn tần suất.
- Định dạng gọi API thật của Claude / Gemini / Groq được kiểm tra bằng request giả (mock).
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, ROOT)

# ---- dùng bản sao DB
_tmp = tempfile.mkdtemp()
TEST_DB = os.path.join(_tmp, "test.db")
shutil.copy(os.path.join(ROOT, "backend", "eduai.db"), TEST_DB)

from ai_service import agent, agent_llm, config, llm_client, rag, tools  # noqa: E402

# Không bao giờ gọi API thật khi test (kể cả khi máy có .env chứa key): xóa key + chặn mạng.
config.ANTHROPIC_API_KEY = config.GEMINI_API_KEY = config.GROQ_API_KEY = ""
import requests as _rq  # noqa: E402


def _no_network(*a, **k):
    raise AssertionError("Test không được gọi mạng thật")


_rq.post = _no_network
from app.core import database  # noqa: E402

for mod in (tools, rag, database):
    mod.DB_PATH = TEST_DB
database.init_db()  # áp dụng bảng/cột mới lên bản sao DB cũ (giống khi server khởi động)

from fastapi.testclient import TestClient  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import agent as agent_router  # noqa: E402

client = TestClient(app)
passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed += 1
        print(f"  FAIL {name} {extra}")


def register(name, email):
    r = client.post("/api/auth/register", json={"full_name": name, "email": email,
                                                "password": "Matkhau123", "confirm_password": "Matkhau123"})
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/login", json={"email": email, "password": "Matkhau123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


# ---- LLM giả: mỗi kịch bản là một hàng đợi các phản hồi {"text":..., "tool_calls":[...]}
SCRIPT, SEEN_SYSTEM = [], []


def fake_complete(system, messages, tool_defs):
    SEEN_SYSTEM.append(system)
    if not SCRIPT:
        return {"text": "(hết kịch bản)", "tool_calls": [], "provider": "fake", "raw": {}}
    step = SCRIPT.pop(0)
    calls = [{"id": f"c{i}", "name": n, "args": a} for i, (n, a) in enumerate(step.get("calls", []))]
    return {"text": step.get("text", ""), "tool_calls": calls, "provider": "fake", "raw": {}}


def uid(email):
    with tools._connect() as c:
        return c.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]


def say(*steps):
    SCRIPT.clear()
    SCRIPT.extend(steps)


def chat(h, msg, session_id=None):
    return client.post("/api/agent/chat", json={"message": msg, "session_id": session_id}, headers=h)


REAL_COMPLETE = agent_llm.complete
agent_llm.complete = fake_complete
agent_router._recent_calls.clear()

print("== Khởi tạo")
_r = client.post("/api/auth/register", json={"full_name": "Lê Thị Hoa", "email": "hoa.space@student.vn",
                                              "password": "K 12345678", "confirm_password": "K 12345678"})
check("đăng ký bị từ chối khi mật khẩu có khoảng trắng", _r.status_code == 400 and "khoảng trắng" in _r.text, _r.text)
_sp = agent.build_system_prompt("An", None)
check("prompt Agent không giới hạn môn/ngành", "mọi ngành" in _sp and "kiến thức chung" in _sp)
check("llm_client không ép chỉ trả lời trong danh sách môn", "kiến thức chung" in llm_client._build_system_prompt(None, ["Toán"]))
check("17 công cụ đã đăng ký", len(tools.TOOL_DEFINITIONS) == 17, len(tools.TOOL_DEFINITIONS))
check("submit_quiz & delete_note cần xác nhận", tools.CONFIRMATION_REQUIRED == {"submit_quiz", "delete_note"})
for t in tools.TOOL_DEFINITIONS:  # schema hợp lệ cho cả Gemini (không có default/additionalProperties)
    blob = json.dumps(t["parameters"])
    assert "additionalProperties" not in blob and '"default"' not in blob, t["name"]
check("schema công cụ tương thích Gemini", True)

A = register("Nguyễn Văn An", "an.test@student.edu.vn")
B = register("Trần Thị Bích", "bich.test@student.edu.vn")

print("== Vòng lặp Agent + công cụ tra cứu")
say({"calls": [("list_courses", {})]}, {"text": "Hệ thống có 20 môn học."})
r = chat(A, "Có những môn nào?").json()
check("Agent trả lời sau khi gọi công cụ", r["status"] == "completed" and "20 môn" in r["answer"], r)
check("có bước công cụ hiển thị", r["steps"] and r["steps"][0]["label"] == "Xem danh sách môn học")
sid = r["session_id"]

say({"calls": [("search_documents", {"query": "thuật toán Dijkstra là gì", "course": "Trí tuệ nhân tạo"})]},
    {"text": "Dijkstra tìm đường đi ngắn nhất."})
r = chat(A, "Dijkstra là gì?", sid).json()
check("search_documents chạy (RAG)", r["steps"][0]["success"], r["steps"])

say({"calls": [("generate_quiz", {"course": "Môn không tồn tại"})]}, {"text": "Mình không thấy môn đó."})
r = chat(A, "Tạo quiz môn lạ").json()
check("lỗi tool được báo, Agent không sập", r["steps"][0]["success"] is False and r["status"] == "completed", r)
check("thông báo lỗi liệt kê các môn hợp lệ", "Các môn hiện có" in (r["steps"][0]["error"] or ""))

print("== Quiz trong chat")
say({"calls": [("generate_quiz", {"course": "Trí tuệ nhân tạo", "num_questions": 5, "difficulty": "basic"})]},
    {"text": "Mình đã tạo bài quiz 5 câu."})
r = chat(A, "Tạo 5 câu ôn tập AI mức cơ bản").json()
quiz_ui = [u for u in r["ui"] if u["type"] == "quiz"]
check("trả về thẻ quiz", len(quiz_ui) == 1, r["ui"])
qid = quiz_ui[0]["quiz_id"]
q = client.get(f"/api/agent/quiz/{qid}", headers=A).json()
check("quiz có 5 câu, mỗi câu ≥ 2 đáp án", len(q["questions"]) == 5 and all(len(x["options"]) >= 2 for x in q["questions"]))
check("KHÔNG lộ đáp án đúng trước khi nộp", "correct_option" not in json.dumps(q) and q["result"] is None)
check("người khác không xem được quiz này", client.get(f"/api/agent/quiz/{qid}", headers=B).status_code == 404)

hist = client.get("/api/chat/history", params={"session_id": r["session_id"]}, headers=A).json()
check("lịch sử chat lưu bước + thẻ quiz (meta)", any(m.get("meta") and "quiz" in m["meta"] for m in hist))

print("== Nộp bài qua API web (dùng chung hàm chấm với Agent)")
ans = [{"question_id": x["id"], "selected_option": "A"} for x in q["questions"]]
res = client.post("/api/quizzes/submit", json={"quiz_id": qid, "answers": ans, "duration_seconds": 40}, headers=A)
check("nộp bài thành công", res.status_code == 200, res.text)
body = res.json()
check("điểm = đúng/tổng*10", abs(body["score"] - round(body["correct_count"] / 5 * 10, 2)) < 0.01 and body["total_count"] == 5)
check("chi tiết có giải thích + đáp án đúng", all("correct_option" in d and "explanation" in d for d in body["details"]))
check("nộp lần 2 bị từ chối", client.post("/api/quizzes/submit", json={"quiz_id": qid, "answers": ans}, headers=A).status_code == 400)
check("người khác không nộp được bài của A", client.post("/api/quizzes/submit", json={"quiz_id": qid, "answers": ans}, headers=B).status_code == 400)
with tools._connect() as c:
    n_ans = c.execute("SELECT COUNT(*) FROM quiz_answers WHERE quiz_result_id = ?", (body["result_id"],)).fetchone()[0]
check("quiz_answers được lưu (trước đây không lưu)", n_ans == 5, n_ans)
prog = client.get("/api/progress", headers=A).json()
check("tiến độ môn được cập nhật sau khi nộp bài", prog["by_course"] and prog["by_course"][0]["percent_complete"] >= 0 and prog["total_quizzes_completed"] == 1, prog)
q2 = client.get(f"/api/agent/quiz/{qid}", headers=A).json()
check("thẻ quiz sau khi nộp có kết quả", q2["result"] and len(q2["result"]["details"]) == 5)

print("== Nộp bài bằng Agent (cần xác nhận)")
say({"calls": [("generate_quiz", {"course": "Trí tuệ nhân tạo", "num_questions": 3})]}, {"text": "Đã tạo quiz."})
r = chat(A, "Tạo 3 câu").json()
qid2 = [u for u in r["ui"] if u["type"] == "quiz"][0]["quiz_id"]
say({"calls": [("submit_quiz", {"quiz_id": qid2, "answers": [{"number": 1, "option": "A"}, {"number": 2, "option": "B"}, {"number": 3, "option": "C"}]})]})
r = chat(A, "Nộp bài giúp mình: 1A 2B 3C").json()
check("Agent dừng chờ xác nhận, chưa nộp", r["status"] == "awaiting_confirmation" and r["pending_action"]["tool"] == "submit_quiz", r)
check("mô tả hành động dễ hiểu", "3/3" in r["pending_action"]["description"], r["pending_action"])
with tools._connect() as c:
    check("chưa có kết quả nào được ghi", c.execute("SELECT COUNT(*) FROM quiz_results WHERE quiz_id = ?", (qid2,)).fetchone()[0] == 0)
tid = r["task_id"]
check("người khác không xác nhận được task của A", client.post("/api/agent/confirm", json={"task_id": tid, "approve": True}, headers=B).status_code == 400)
c1 = client.post("/api/agent/confirm", json={"task_id": tid, "approve": True}, headers=A).json()
check("xác nhận → đã nộp, có điểm", c1["status"] == "completed" and "điểm" in c1["answer"] and c1["follow_ups"], c1)
check("xác nhận lần 2 bị từ chối (không nộp trùng)", client.post("/api/agent/confirm", json={"task_id": tid, "approve": True}, headers=A).status_code == 400)

say({"calls": [("generate_quiz", {"course": "Cơ sở dữ liệu", "num_questions": 2})]}, {"text": "ok"})
q3 = [u for u in chat(A, "Tạo quiz CSDL").json()["ui"]][0]["quiz_id"]
say({"calls": [("submit_quiz", {"quiz_id": q3, "answers": [{"number": 1, "option": "A"}]})]})
r = chat(A, "Nộp").json()
c2 = client.post("/api/agent/confirm", json={"task_id": r["task_id"], "approve": False}, headers=A).json()
check("hủy → không nộp", c2["status"] == "cancelled")
with tools._connect() as c:
    check("quiz bị hủy vẫn chưa có kết quả", c.execute("SELECT COUNT(*) FROM quiz_results WHERE quiz_id = ?", (q3,)).fetchone()[0] == 0)

print("== Phân tích điểm yếu / kết quả / gợi ý")
for _ in range(2):  # làm thêm vài bài để đủ dữ liệu cho phân tích theo chương
    say({"calls": [("generate_quiz", {"course": "Trí tuệ nhân tạo", "num_questions": 10})]}, {"text": "ok"})
    qq = chat(A, "Tạo quiz 10 câu").json()["ui"][0]["quiz_id"]
    qs = client.get(f"/api/agent/quiz/{qq}", headers=A).json()["questions"]
    client.post("/api/quizzes/submit", json={"quiz_id": qq, "answers": [{"question_id": x["id"], "selected_option": "A"} for x in qs]}, headers=A)
say({"calls": [("analyze_weakness", {}), ("analyze_result", {}), ("get_recommendation", {}),
               ("get_progress", {}), ("get_quiz_history", {"limit": 3})]}, {"text": "Phân tích xong."})
r = chat(A, "Phân tích điểm yếu của mình").json()
check("5 công cụ phân tích chạy song song, không lỗi", len(r["steps"]) == 5 and all(s["success"] for s in r["steps"]), r["steps"])
uidA, uidB = uid("an.test@student.edu.vn"), uid("bich.test@student.edu.vn")
w = tools.analyze_weakness({}, uidA)
check("analyze_weakness trả điểm yếu theo chương", w["found"] and w["weakest"][0]["accuracy"] <= w["weakest"][-1]["accuracy"], w)
check("sinh viên mới (B) chưa có dữ liệu → thông báo rõ", tools.analyze_weakness({}, uidB)["found"] is False)
try:
    tools.analyze_result({}, uidB)
    check("B không phân tích được bài của A", False)
except tools.ToolError:
    check("B không phân tích được bài của A", True)

print("== Kế hoạch học tập")
plan = {"title": "Ôn thi giữa kỳ AI", "goal": "Đạt 8 điểm", "tasks": [
    {"title": "Ôn BFS/DFS", "course": "Trí tuệ nhân tạo", "due_date": "2026-10-12"},
    {"title": "Làm 10 câu Dijkstra", "due_date": "2026-10-14"}]}
say({"calls": [("create_study_plan", plan)]}, {"text": "Đã lưu kế hoạch."})
r = chat(A, "Lập kế hoạch ôn thi").json()
check("tạo kế hoạch", r["steps"][0]["success"], r["steps"])
p = client.get("/api/agent/plan", headers=A).json()
check("kế hoạch có 2 việc", p["found"] and p["total"] == 2, p)
tid1 = p["tasks"][0]["task_id"]
check("đánh dấu xong việc", client.patch(f"/api/agent/plan/tasks/{tid1}", json={"done": True}, headers=A).status_code == 200)
check("B không sửa được việc của A", client.patch(f"/api/agent/plan/tasks/{tid1}", json={"done": False}, headers=B).status_code == 404)
check("B không thấy kế hoạch của A", client.get("/api/agent/plan", headers=B).json()["found"] is False)
try:
    tools.create_study_plan({"title": "x", "tasks": [{"title": "a", "due_date": "ngày mai"}]}, uidA)
    check("từ chối ngày sai định dạng", False)
except tools.ToolError:
    check("từ chối ngày sai định dạng", True)
before = tools.get_study_plan({}, uidA)["plan"]["id"]
tools.create_study_plan({"title": "Kế hoạch mới", "tasks": [{"title": "việc"}]}, uidA)
with tools._connect() as c:
    act = c.execute("SELECT COUNT(*) FROM study_plans WHERE user_id = ? AND status = 'active'", (uidA,)).fetchone()[0]
check("kế hoạch cũ được lưu trữ, chỉ 1 kế hoạch hoạt động", act == 1)

print("== Ghi chú")
say({"calls": [("save_note", {"title": "BFS vs DFS", "content": "BFS dùng hàng đợi...", "course": "Trí tuệ nhân tạo"})]}, {"text": "Đã lưu."})
chat(A, "Lưu ghi chú")
notes = client.get("/api/agent/notes", headers=A).json()
check("ghi chú được lưu", len(notes) == 1 and notes[0]["course"] == "Trí tuệ nhân tạo")
nid = notes[0]["id"]
check("B không thấy ghi chú của A", client.get("/api/agent/notes", headers=B).json() == [])
check("B không xóa được ghi chú của A (API)", client.delete(f"/api/agent/notes/{nid}", headers=B).status_code == 404)
say({"calls": [("list_notes", {"keyword": "BFS"})]}, {"text": "Có 1 ghi chú."})
check("list_notes theo từ khóa", chat(A, "Tìm ghi chú BFS").json()["steps"][0]["success"])
say({"calls": [("delete_note", {"note_id": nid})]})
r = chat(A, "Xóa ghi chú BFS").json()
check("xóa ghi chú cần xác nhận", r["status"] == "awaiting_confirmation" and "BFS vs DFS" in r["pending_action"]["description"], r)
check("chưa xóa khi chưa xác nhận", len(client.get("/api/agent/notes", headers=A).json()) == 1)
client.post("/api/agent/confirm", json={"task_id": r["task_id"], "approve": True}, headers=A)
check("xác nhận → đã xóa", client.get("/api/agent/notes", headers=A).json() == [])
say({"calls": [("delete_note", {"note_id": 999999})]})
r = chat(B, "Xóa ghi chú").json()
c3 = client.post("/api/agent/confirm", json={"task_id": r["task_id"], "approve": True}, headers=B).json()
check("xóa ghi chú không tồn tại → báo lỗi rõ", c3["status"] == "failed")

print("== Bảo mật / độ bền")
check("không có token → 401/403", client.post("/api/agent/chat", json={"message": "hi"}).status_code in (401, 403))
check("tin nhắn rỗng → 422", chat(A, "").status_code == 422)
check("tin nhắn quá dài → 422", chat(A, "x" * 2001).status_code == 422)
check("B không ghi vào phiên chat của A", chat(B, "hello", sid).status_code == 404)

SCRIPT.clear()
for _ in range(agent.MAX_STEPS + 2):
    SCRIPT.append({"calls": [("get_progress", {})]})
r = chat(A, "lặp mãi").json()
check("vòng lặp vô hạn bị chặn bởi MAX_STEPS", r["status"] == "failed" and len(r["steps"]) == agent.MAX_STEPS, r["status"])

import ai_service.agent_llm as al  # noqa: E402


def broken(*a, **k):
    raise llm_client.LLMError("hết hạn mức")


agent_llm.complete = broken
r = chat(A, "Xin chào").json()
check("Agent lỗi → tự rơi về Chatbot thường", r["status"] == "fallback" and r["answer"] and r["fallback"], r)
agent_llm.complete = fake_complete

agent_router._recent_calls.clear()
codes = [chat(B, "hi").status_code for _ in range(agent_router.RATE_LIMIT + 1)]
check("giới hạn tần suất → 429 ở lần vượt", codes[-1] == 429 and 429 not in codes[:-1], codes[-3:])
agent_router._recent_calls.clear()

print("== Admin & prompt")
with tools._connect() as c:
    c.execute("INSERT INTO users (full_name,email,password_hash,role_id) VALUES ('Admin Test','adm.test@eduai.vn',?,2)", (hash_password("Admin12345"),))
H = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "adm.test@eduai.vn", "password": "Admin12345"}).json()["access_token"]}
cfg = client.get("/api/admin/agent/config", headers=H).json()
check("admin xem cấu hình agent (17 tool)", len(cfg["tools"]) == 17 and cfg["tools"][0]["label"], cfg.get("tools", [None])[0])
check("sinh viên không vào được cấu hình admin", client.get("/api/admin/agent/config", headers=A).status_code == 403)
check("admin thấy nhật ký tool", len(client.get("/api/admin/agent/logs", headers=H).json()) > 10)
client.post("/api/admin/agent/prompts", json={"name": "agent_system", "content": "Bạn là bot thử nghiệm cho {student}, hôm nay {today}. Môn: {courses}."}, headers=H)
say({"text": "ok"})
chat(A, "chào")
check("prompt do admin chỉnh được dùng, thay đủ biến", "bot thử nghiệm cho Nguyễn Văn An" in SEEN_SYSTEM[-1] and "Trí tuệ nhân tạo" in SEEN_SYSTEM[-1] and "{today}" not in SEEN_SYSTEM[-1], SEEN_SYSTEM[-1][:200])
check("admin xóa user → xóa luôn dữ liệu agent (không lỗi FK)", client.delete(f"/api/admin/users/{uidA}", headers=H).status_code == 200)

# =========================================================== adapter 3 nhà cung cấp
print("== Định dạng gọi API thật (mock requests)")
agent_llm.complete = REAL_COMPLETE
TOOLS = [{"name": "get_progress", "description": "d", "parameters": {"type": "object", "properties": {}, "required": []}},
         {"name": "search_documents", "description": "d", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}]
HISTORY = [
    {"role": "user", "content": "Tiến độ của mình?"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "name": "get_progress", "args": {}}], "raw": {"gemini_parts": [{"functionCall": {"name": "get_progress", "args": {}}, "thoughtSignature": "SIG"}]}},
    {"role": "tool", "tool_call_id": "t1", "name": "get_progress", "content": json.dumps({"avg": 7.5})},
]
captured = {}


class FakeResp:
    status_code = 200

    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def fake_post_factory(data):
    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, body=json)
        return FakeResp(data)
    return fake_post


import requests  # noqa: E402

orig_post = requests.post  # bản chặn mạng
config.ANTHROPIC_API_KEY, config.GEMINI_API_KEY, config.GROQ_API_KEY = "k1", "k2", "k3"

# Claude
requests.post = fake_post_factory({"content": [{"type": "text", "text": "Bạn đạt 7.5"}, {"type": "tool_use", "id": "tu_9", "name": "search_documents", "input": {"query": "bfs"}}]})
llm_client.config.LLM_PROVIDER = "claude"
out = al._call_claude("SYS", HISTORY, TOOLS)
msgs = captured["body"]["messages"]
check("Claude: tool_use + tool_result đúng cấu trúc", msgs[1]["content"][0]["type"] == "tool_use" and msgs[2]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": json.dumps({"avg": 7.5})})
check("Claude: tools dùng input_schema", "input_schema" in captured["body"]["tools"][0] and captured["body"]["system"] == "SYS")
check("Claude: parse tool_use + text", out["tool_calls"] == [{"id": "tu_9", "name": "search_documents", "args": {"query": "bfs"}}] and out["text"] == "Bạn đạt 7.5")

# Gemini
requests.post = fake_post_factory({"candidates": [{"content": {"parts": [{"functionCall": {"name": "search_documents", "args": {"query": "dfs"}}, "thoughtSignature": "S2"}]}}]})
out = al._call_gemini("SYS", HISTORY, TOOLS)
contents = captured["body"]["contents"]
check("Gemini: giữ nguyên thoughtSignature khi gửi lại functionCall", contents[1]["parts"][0].get("thoughtSignature") == "SIG" and contents[1]["role"] == "model")
check("Gemini: functionResponse trong lượt user", contents[2]["role"] == "user" and contents[2]["parts"][0]["functionResponse"]["name"] == "get_progress")
decls = captured["body"]["tools"][0]["functionDeclarations"]
check("Gemini: tool không tham số bỏ schema rỗng", "parameters" not in decls[0] and "parameters" in decls[1])
check("Gemini: parse functionCall + giữ raw parts", out["tool_calls"][0]["args"] == {"query": "dfs"} and out["raw"]["gemini_parts"][0]["thoughtSignature"] == "S2")

# Groq
requests.post = fake_post_factory({"choices": [{"message": {"content": None, "tool_calls": [{"id": "g1", "function": {"name": "search_documents", "arguments": "{\"query\": \"hàng đợi\"}"}}]}}]})
out = al._call_groq("SYS", HISTORY, TOOLS)
gm = captured["body"]["messages"]
check("Groq: system + assistant.tool_calls + role=tool", gm[0]["role"] == "system" and gm[2]["tool_calls"][0]["function"]["arguments"] == "{}" and gm[3] == {"role": "tool", "tool_call_id": "t1", "content": json.dumps({"avg": 7.5})})
check("Groq: parse arguments JSON (tiếng Việt)", out["tool_calls"][0]["args"] == {"query": "hàng đợi"})

# chuyển nhà cung cấp khi lỗi
calls = []


def flaky(url, headers=None, json=None, timeout=None):
    calls.append(url)
    if "anthropic" in url:
        r = FakeResp({}); r.status_code = 400; r.text = "credit balance too low"; return r
    if "googleapis" in url:
        r = FakeResp({}); r.status_code = 429; r.text = "quota"; return r
    return FakeResp({"choices": [{"message": {"content": "Groq trả lời"}}]})


requests.post = flaky
llm_client.config.LLM_PROVIDER = "auto"
orig_sleep = al.time.sleep
al.time.sleep = lambda s: None
out = agent_llm.complete("SYS", [{"role": "user", "content": "hi"}], TOOLS)
al.time.sleep = orig_sleep
check("Claude hết credit, Gemini hết quota → tự chuyển sang Groq", out["provider"] == "groq" and out["text"] == "Groq trả lời", calls)
requests.post = orig_post

config.ANTHROPIC_API_KEY = config.GEMINI_API_KEY = config.GROQ_API_KEY = ""
try:
    agent_llm.complete("S", [{"role": "user", "content": "hi"}], TOOLS)
    check("không có key nào → báo lỗi rõ", False)
except llm_client.LLMError as e:
    check("không có key nào → báo lỗi rõ", "API key" in str(e))

print(f"\nKết quả: {passed} đạt, {failed} lỗi")
shutil.rmtree(_tmp, ignore_errors=True)
sys.exit(1 if failed else 0)
