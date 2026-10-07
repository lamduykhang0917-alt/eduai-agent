/* ============================================================
   EduAI — API client dùng chung cho toàn bộ frontend
   ============================================================ */

const API_BASE = window.EDUAI_API_BASE || "const API_BASE = window.EDUAI_API_BASE || "https://eduai-agent-backend-xxxx.onrender.com";

const Api = {
  // "Ghi nhớ đăng nhập" bật: lưu lâu dài (localStorage). Tắt: chỉ giữ đến khi đóng trình duyệt (sessionStorage).
  token() {
    return sessionStorage.getItem("eduai_token") || localStorage.getItem("eduai_token");
  },
  setToken(token, remember = true) {
    this.clearToken();
    (remember ? localStorage : sessionStorage).setItem("eduai_token", token);
  },
  clearToken() {
    localStorage.removeItem("eduai_token");
    sessionStorage.removeItem("eduai_token");
  },
  async request(path, { method = "GET", body = null, auth = true } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (auth && this.token()) headers["Authorization"] = `Bearer ${this.token()}`;

    // Server miễn phí có thể vừa thức dậy hoặc vừa khởi động lại: tự gửi lại khi lỗi kết nối.
    let res;
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        res = await fetch(`${API_BASE}${path}`, {
          method,
          headers,
          body: body ? JSON.stringify(body) : undefined,
        });
        break;
      } catch (err) {
        if (attempt === 3) {
          throw new Error("Không kết nối được máy chủ. Vui lòng thử lại sau ít phút.");
        }
        await new Promise((resolve) => setTimeout(resolve, 4000));
      }
    }

    if (res.status === 401) {
      this.clearToken();
      window.location.href = "login.html";
      return;
    }

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || "Đã xảy ra lỗi. Vui lòng thử lại.");
    }
    return data;
  },

  login(email, password, remember = false) {
    return this.request("/api/auth/login", { method: "POST", body: { email, password, remember }, auth: false });
  },
  forgotPassword(email) {
    return this.request("/api/auth/forgot-password", { method: "POST", body: { email }, auth: false });
  },
  resetPassword(token, new_password) {
    return this.request("/api/auth/reset-password", { method: "POST", body: { token, new_password }, auth: false });
  },
  register(full_name, email, password, confirm_password) {
    return this.request("/api/auth/register", {
      method: "POST",
      body: { full_name, email, password, confirm_password },
      auth: false,
    });
  },
  me() { return this.request("/api/auth/me"); },
  updateProfile(data) { return this.request("/api/auth/me", { method: "PUT", body: data }); },

  chat(message, session_id = null, course = null, level = "basic") {
    return this.request("/api/chat", { method: "POST", body: { message, session_id, course, level } });
  },
  chatSessions() { return this.request("/api/chat/history"); },
  deleteChat(id) { return this.request(`/api/chat/history/${id}`, { method: "DELETE" }); },
  deleteAllChats() { return this.request("/api/chat/history", { method: "DELETE" }); },
  chatMessages(session_id) { return this.request(`/api/chat/history?session_id=${session_id}`); },

  agentChat(message, session_id = null, course = null) {
    return this.request("/api/agent/chat", { method: "POST", body: { message, session_id, course } });
  },
  // Hành động chờ xác nhận được lưu ở server; client chỉ gửi task_id + đồng ý/hủy
  agentConfirm(task_id, approve) {
    return this.request("/api/agent/confirm", { method: "POST", body: { task_id, approve } });
  },
  agentTasks() { return this.request("/api/agent/tasks"); },
  agentQuiz(quiz_id) { return this.request(`/api/agent/quiz/${quiz_id}`); },
  studyPlan() { return this.request("/api/agent/plan"); },
  setTaskDone(task_id, done) {
    return this.request(`/api/agent/plan/tasks/${task_id}`, { method: "PATCH", body: { done } });
  },
  notes() { return this.request("/api/agent/notes"); },
  addNote(title, content, course = null) {
    return this.request("/api/agent/notes", { method: "POST", body: { title, content, course } });
  },
  deleteNote(id) { return this.request(`/api/agent/notes/${id}`, { method: "DELETE" }); },

  courses() { return this.request("/api/courses"); },
  course(id) { return this.request(`/api/courses/${id}`); },
  documents(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.request(`/api/documents${qs ? "?" + qs : ""}`);
  },

  quizMeta() { return this.request("/api/quizzes/meta"); },
  documentContent(id) { return this.request(`/api/documents/${id}/content`); },
  generateQuiz(course, num_questions, difficulty, chapter) {
    return this.request("/api/quizzes/generate", {
      method: "POST",
      body: { course, num_questions, difficulty, chapter },
    });
  },
  submitQuiz(quiz_id, answers, duration_seconds) {
    return this.request("/api/quizzes/submit", { method: "POST", body: { quiz_id, answers, duration_seconds } });
  },
  results() { return this.request("/api/results"); },
  progress() { return this.request("/api/progress"); },
  recentActivity() { return this.request("/api/activity/recent"); },
  recommendations() { return this.request("/api/recommendations"); },
};

function requireAuth() {
  if (!Api.token()) {
    window.location.href = "login.html";
  }
}

function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ============================================================
   Giao diện theo môn học: mỗi môn có biểu tượng + màu riêng để dễ nhận ra.
   ============================================================ */
const COURSE_THEMES = [
  { key: /trí tuệ nhân tạo/i,            icon: "🤖", from: "#4f46e5", to: "#7c3aed" },
  { key: /máy học/i,                      icon: "🧠", from: "#7c3aed", to: "#c026d3" },
  { key: /ngôn ngữ tự nhiên/i,            icon: "💬", from: "#0891b2", to: "#2563eb" },
  { key: /python/i,                       icon: "🐍", from: "#059669", to: "#0d9488" },
  { key: /quản trị cơ sở dữ liệu/i,       icon: "🛡️", from: "#2563eb", to: "#1d4ed8" },
  { key: /cơ sở dữ liệu/i,                icon: "🗄️", from: "#0284c7", to: "#2563eb" },
  { key: /cấu trúc dữ liệu/i,             icon: "🌳", from: "#16a34a", to: "#65a30d" },
  { key: /hướng đối tượng/i,              icon: "🧩", from: "#ea580c", to: "#f59e0b" },
  { key: /\.net/i,                        icon: "🖥️", from: "#4338ca", to: "#2563eb" },
  { key: /toán rời rạc/i,                 icon: "🔢", from: "#db2777", to: "#e11d48" },
  { key: /phân tích thiết kế/i,           icon: "📐", from: "#d97706", to: "#ea580c" },
  { key: /mạng máy tính/i,                icon: "🌐", from: "#0891b2", to: "#0d9488" },
  { key: /đồ họa/i,                       icon: "🎨", from: "#c026d3", to: "#db2777" },
  { key: /xử lý ảnh/i,                    icon: "🖼️", from: "#9333ea", to: "#6366f1" },
  { key: /tương tác người máy/i,          icon: "👆", from: "#e11d48", to: "#f97316" },
  { key: /điện toán đám mây/i,            icon: "☁️", from: "#0ea5e9", to: "#6366f1" },
  { key: /kiến trúc máy tính/i,           icon: "🔧", from: "#475569", to: "#334155" },
  { key: /kỹ thuật lập trình/i,           icon: "⌨️", from: "#0f766e", to: "#16a34a" },
  { key: /nhập môn/i,                     icon: "🎓", from: "#2563eb", to: "#7c3aed" },
];
function courseTheme(name) {
  const t = COURSE_THEMES.find((x) => x.key.test(name || ""));
  return t || { icon: "📘", from: "#2563eb", to: "#4f46e5" };
}
function courseCover(name) {
  const t = courseTheme(name);
  return `background: linear-gradient(135deg, ${t.from}, ${t.to});`;
}
// Vòng tiến độ tròn (SVG), percent 0-100.
function progressRing(percent, size = 64) {
  const color = "#6366f1";   // giao diện Đồ án 2: một màu chàm cho mọi vòng tiến độ
  const r = (size - 8) / 2, c = 2 * Math.PI * r, pct = Math.max(0, Math.min(100, percent || 0));
  return `<svg class="ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="#e6e9f1" stroke-width="5"/>
    ${pct > 0 ? `<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${color}" stroke-width="5" stroke-linecap="round"
      stroke-dasharray="${(c * pct / 100).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 ${size / 2} ${size / 2})"/>` : ""}
    <text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" font-size="${size * 0.24}" font-weight="700" fill="#111833">${Math.round(pct)}%</text></svg>`;
}
function greetingByTime() {
  const h = new Date().getHours();
  return h < 11 ? "Chào buổi sáng" : h < 14 ? "Chào buổi trưa" : h < 18 ? "Chào buổi chiều" : "Chào buổi tối";
}

// Đổi giờ UTC của server ("2026-10-06 13:35:06") sang giờ máy người dùng.
function parseServerTime(s) {
  if (!s) return null;
  const d = new Date(String(s).replace(" ", "T") + (String(s).includes("Z") ? "" : "Z"));
  return isNaN(d) ? null : d;
}
function formatServerTime(s) {
  const d = parseServerTime(s);
  if (!d) return s || "";
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
// Đầu ngày theo giờ máy -> chuỗi UTC "YYYY-MM-DD HH:MM:SS" để gửi cho server.
function toServerTime(date) {
  return date.toISOString().slice(0, 19).replace("T", " ");
}

// Chặn sai vai trò: admin vào trang sinh viên (và ngược lại) thì chuyển về đúng trang của mình.
async function requireRole(role) {
  requireAuth();
  try {
    const me = await Api.me();
    if (me && me.role !== role) {
      window.location.href = me.role === "ADMIN" ? "admin-dashboard.html" : "dashboard.html";
    }
    return me;
  } catch (e) { return null; }
}

function logout() {
  showConfirmModal({
    title: "Đăng xuất",
    message: "Bạn có muốn đăng xuất không?",
    confirmText: "Đăng xuất",
    cancelText: "Hủy",
    onConfirm: () => {
      Api.request("/api/auth/logout", { method: "POST" }).finally(() => {
        Api.clearToken();
        window.location.href = "../index.html";   // về trang giới thiệu (landing)
      });
    },
  });
}

function showConfirmModal({ title, message, confirmText = "Xác nhận", cancelText = "Hủy", onConfirm }) {
  const existing = document.getElementById("eduai-confirm-modal");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.id = "eduai-confirm-modal";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(17,24,39,0.45);display:flex;align-items:center;justify-content:center;z-index:9999;";
  overlay.innerHTML = `
    <div style="background:#ffffff;border-radius:14px;padding:24px;width:100%;max-width:360px;box-shadow:0 4px 12px rgba(16,24,40,.15);font-family:'Inter',-apple-system,sans-serif;">
      <h3 style="margin:0 0 8px;font-size:17px;color:#111827;">${title}</h3>
      <p style="margin:0 0 22px;font-size:14px;color:#6b7280;line-height:1.5;">${message}</p>
      <div style="display:flex;gap:8px;justify-content:flex-end;">
        <button id="eduai-confirm-cancel" style="padding:10px 16px;border-radius:8px;border:1px solid #e5e7eb;background:#ffffff;color:#111827;font-size:14px;font-weight:600;cursor:pointer;">${cancelText}</button>
        <button id="eduai-confirm-ok" style="padding:10px 16px;border-radius:8px;border:none;background:linear-gradient(135deg,#4f46e5,#2563eb);color:#ffffff;font-size:14px;font-weight:600;cursor:pointer;">${confirmText}</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  document.getElementById("eduai-confirm-cancel").onclick = close;
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  document.getElementById("eduai-confirm-ok").onclick = () => { close(); onConfirm(); };
}

function toggleSidebar() {
  document.querySelector(".app-shell").classList.toggle("sidebar-open");
}

function initials(name) {
  return (name || "").split(" ").filter(Boolean).slice(-2).map(w => w[0]).join("").toUpperCase();
}

/* ============================================================
   Avatar góc trên bên phải + Modal hồ sơ cá nhân
   Tự động chèn vào mọi trang có .topbar hoặc .chat-header, không cần
   sửa từng file HTML — chỉ cần trang đó có nạp api.js và người dùng đã
   đăng nhập.
   ============================================================ */

const GENDER_OPTIONS = ["Nam", "Nữ", "Khác"];

function formatDate(isoDate) {
  if (!isoDate) return "Chưa cập nhật";
  const [y, m, d] = isoDate.split("-");
  return `${d}/${m}/${y}`;
}

async function initTopbarAvatar() {
  if (!Api.token()) return;
  const host = document.querySelector(".topbar") || document.querySelector(".chat-header") || document.querySelector(".topnav-inner");
  if (!host || document.getElementById("eduai-avatar-btn")) return;

  let me;
  try {
    me = await Api.me();
  } catch (e) {
    return; // token hết hạn... Api.request đã tự chuyển về login rồi
  }

  const btn = document.createElement("button");
  btn.id = "eduai-avatar-btn";
  btn.title = "Xem hồ sơ cá nhân";
  btn.style.cssText = "width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#4f46e5,#2563eb);color:white;border:none;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:13px;cursor:pointer;flex-shrink:0;";
  btn.textContent = initials(me.full_name) || "?";
  btn.onclick = () => openProfileModal(me);

  host.appendChild(btn);
}

function fieldRow(label, value) {
  return `
    <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f3f4f6; font-size:14px;">
      <span style="color:#6b7280;">${label}</span>
      <span style="color:#111827; font-weight:500; text-align:right;">${value || "Chưa cập nhật"}</span>
    </div>`;
}

function openProfileModal(user) {
  const existing = document.getElementById("eduai-profile-modal");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.id = "eduai-profile-modal";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(17,24,39,0.45);display:flex;align-items:center;justify-content:center;z-index:9999;font-family:'Inter',-apple-system,sans-serif;";

  const isStudent = user.role === "STUDENT";

  overlay.innerHTML = `
    <div style="background:#fff;border-radius:16px;padding:0;width:100%;max-width:420px;max-height:88vh;overflow-y:auto;box-shadow:0 4px 20px rgba(16,24,40,.2);">
      <div style="padding:24px 24px 16px; text-align:center; border-bottom:1px solid #f3f4f6;">
        <div style="width:64px;height:64px;border-radius:50%;background:linear-gradient(135deg,#4f46e5,#2563eb);color:white;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:22px;margin:0 auto 12px;">${initials(user.full_name) || "?"}</div>
        <h3 style="margin:0 0 4px; font-size:18px; color:#111827;">${user.full_name}</h3>
        <span style="display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:600; background:${isStudent ? "#eff6ff" : "#fffbeb"}; color:${isStudent ? "#2563eb" : "#d97706"};">${isStudent ? "Sinh viên" : "Admin"}</span>
      </div>

      <div id="eduai-profile-view" style="padding:8px 24px 20px;">
        ${fieldRow("Email", user.email)}
        ${fieldRow("Ngày sinh", formatDate(user.date_of_birth))}
        ${fieldRow("Giới tính", user.gender)}
        ${isStudent ? fieldRow("Ngành học", user.major) : ""}
        ${isStudent ? fieldRow("MSSV", user.student_code) : ""}
        ${fieldRow("Số điện thoại", user.phone)}
        ${fieldRow("Địa chỉ", user.address)}

        <div style="display:flex; gap:8px; justify-content:flex-end; margin-top:20px;">
          <button id="eduai-profile-close" style="padding:10px 16px;border-radius:8px;border:1px solid #e5e7eb;background:#fff;color:#111827;font-size:14px;font-weight:600;cursor:pointer;">Đóng</button>
          <button id="eduai-profile-edit" style="padding:10px 16px;border-radius:8px;border:none;background:linear-gradient(135deg,#4f46e5,#2563eb);color:#fff;font-size:14px;font-weight:600;cursor:pointer;">✏️ Chỉnh sửa thông tin</button>
        </div>
      </div>

      <form id="eduai-profile-form" style="display:none; padding:8px 24px 24px;">
        <div style="margin-bottom:12px;"><label style="font-size:13px;font-weight:600;display:block;margin-bottom:4px;">Họ tên</label>
          <input id="pf-full-name" value="${user.full_name || ""}" style="width:100%;padding:9px 12px;border:1px solid #e5e7eb;border-radius:8px;font-size:14px;box-sizing:border-box;"></div>
        <div style="margin-bottom:12px;"><label style="font-size:13px;font-weight:600;display:block;margin-bottom:4px;">Ngày sinh</label>
          <input id="pf-dob" type="date" value="${user.date_of_birth || ""}" style="width:100%;padding:9px 12px;border:1px solid #e5e7eb;border-radius:8px;font-size:14px;box-sizing:border-box;"></div>
        <div style="margin-bottom:12px;"><label style="font-size:13px;font-weight:600;display:block;margin-bottom:4px;">Giới tính</label>
          <select id="pf-gender" style="width:100%;padding:9px 12px;border:1px solid #e5e7eb;border-radius:8px;font-size:14px;box-sizing:border-box;">
            <option value="">-- Chọn --</option>
            ${GENDER_OPTIONS.map(g => `<option value="${g}" ${user.gender === g ? "selected" : ""}>${g}</option>`).join("")}
          </select></div>
        ${isStudent ? `
        <div style="margin-bottom:12px;"><label style="font-size:13px;font-weight:600;display:block;margin-bottom:4px;">Ngành học</label>
          <input id="pf-major" value="${user.major || ""}" placeholder="Ví dụ: Kinh tế, Y khoa, Công nghệ thông tin" style="width:100%;padding:9px 12px;border:1px solid #e5e7eb;border-radius:8px;font-size:14px;box-sizing:border-box;"></div>
        <div style="margin-bottom:12px;"><label style="font-size:13px;font-weight:600;display:block;margin-bottom:4px;">MSSV</label>
          <input id="pf-student-code" value="${user.student_code || ""}" style="width:100%;padding:9px 12px;border:1px solid #e5e7eb;border-radius:8px;font-size:14px;box-sizing:border-box;"></div>
        ` : ""}
        <div style="margin-bottom:12px;"><label style="font-size:13px;font-weight:600;display:block;margin-bottom:4px;">Số điện thoại</label>
          <input id="pf-phone" value="${user.phone || ""}" style="width:100%;padding:9px 12px;border:1px solid #e5e7eb;border-radius:8px;font-size:14px;box-sizing:border-box;"></div>
        <div style="margin-bottom:16px;"><label style="font-size:13px;font-weight:600;display:block;margin-bottom:4px;">Địa chỉ</label>
          <input id="pf-address" value="${user.address || ""}" style="width:100%;padding:9px 12px;border:1px solid #e5e7eb;border-radius:8px;font-size:14px;box-sizing:border-box;"></div>

        <div id="eduai-profile-error" style="display:none;background:#fef2f2;border:1px solid #fecaca;color:#dc2626;border-radius:8px;padding:10px 12px;font-size:13px;margin-bottom:14px;"></div>

        <div style="display:flex; gap:8px; justify-content:flex-end;">
          <button type="button" id="eduai-profile-cancel" style="padding:10px 16px;border-radius:8px;border:1px solid #e5e7eb;background:#fff;color:#111827;font-size:14px;font-weight:600;cursor:pointer;">Hủy</button>
          <button type="submit" id="eduai-profile-save" style="padding:10px 16px;border-radius:8px;border:none;background:linear-gradient(135deg,#4f46e5,#2563eb);color:#fff;font-size:14px;font-weight:600;cursor:pointer;">Lưu thay đổi</button>
        </div>
      </form>
    </div>`;
  document.body.appendChild(overlay);

  const viewEl = document.getElementById("eduai-profile-view");
  const formEl = document.getElementById("eduai-profile-form");
  const close = () => overlay.remove();

  document.getElementById("eduai-profile-close").onclick = close;
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

  document.getElementById("eduai-profile-edit").onclick = () => {
    viewEl.style.display = "none";
    formEl.style.display = "block";
  };
  document.getElementById("eduai-profile-cancel").onclick = () => {
    formEl.style.display = "none";
    viewEl.style.display = "block";
  };

  formEl.onsubmit = async (e) => {
    e.preventDefault();
    const errorBox = document.getElementById("eduai-profile-error");
    errorBox.style.display = "none";
    const saveBtn = document.getElementById("eduai-profile-save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Đang lưu...";

    const payload = {
      full_name: document.getElementById("pf-full-name").value.trim(),
      date_of_birth: document.getElementById("pf-dob").value || null,
      gender: document.getElementById("pf-gender").value || null,
      phone: document.getElementById("pf-phone").value || null,
      address: document.getElementById("pf-address").value || null,
    };
    if (isStudent) {
      payload.major = document.getElementById("pf-major").value || null;
      payload.student_code = document.getElementById("pf-student-code").value || null;
    }

    try {
      const updated = await Api.updateProfile(payload);
      close();
      openProfileModal(updated); // mở lại modal ở chế độ xem với dữ liệu mới
      // cập nhật lại avatar góc trên nếu tên thay đổi
      const btn = document.getElementById("eduai-avatar-btn");
      if (btn) btn.textContent = initials(updated.full_name) || "?";
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.style.display = "block";
      saveBtn.disabled = false;
      saveBtn.textContent = "Lưu thay đổi";
    }
  };
}

document.addEventListener("DOMContentLoaded", initTopbarAvatar);

document.addEventListener("DOMContentLoaded", () => {
  const inner = document.querySelector(".topnav-inner");
  if (!inner || inner.querySelector(".nav-burger")) return;
  const b = document.createElement("button");
  b.className = "nav-burger"; b.setAttribute("aria-label", "Mở menu"); b.textContent = "☰";
  b.onclick = toggleSidebar;
  inner.appendChild(b);
});
