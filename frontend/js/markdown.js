/* ============================================================
   EduAI — bộ định dạng Markdown nhỏ cho câu trả lời của AI
   An toàn: luôn escape HTML trước, chỉ sinh ra một số thẻ cố định.
   Hỗ trợ: tiêu đề, đậm/nghiêng, code (inline + khối), danh sách,
   bảng, đường kẻ ngang và công thức LaTeX đơn giản ($...$).
   ============================================================ */

function mdEscape(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Chuyển công thức LaTeX thường gặp thành chữ dễ đọc (không cần thư viện ngoài)
function mdLatexToText(expr) {
  let s = expr;
  const map = {
    "\\to": "→", "\\rightarrow": "→", "\\leftarrow": "←", "\\Rightarrow": "⇒",
    "\\cdot": "·", "\\times": "×", "\\leq": "≤", "\\le": "≤", "\\geq": "≥", "\\ge": "≥",
    "\\neq": "≠", "\\ne": "≠", "\\infty": "∞", "\\sum": "Σ", "\\in": "∈", "\\forall": "∀",
    "\\exists": "∃", "\\land": "∧", "\\lor": "∨", "\\neg": "¬", "\\cup": "∪", "\\cap": "∩",
    "\\subseteq": "⊆", "\\subset": "⊂", "\\emptyset": "∅", "\\approx": "≈", "\\pm": "±",
    "\\alpha": "α", "\\beta": "β", "\\gamma": "γ", "\\delta": "δ", "\\theta": "θ",
    "\\lambda": "λ", "\\mu": "μ", "\\pi": "π", "\\sigma": "σ", "\\omega": "ω",
    "\\log": "log", "\\ln": "ln", "\\min": "min", "\\max": "max", "\\lceil": "⌈", "\\rceil": "⌉",
    "\\lfloor": "⌊", "\\rfloor": "⌋", "\\ldots": "…", "\\dots": "…", "\\quad": " ", "\\,": " ",
  };
  s = s.replace(/\\text\{([^}]*)\}/g, "$1");
  s = s.replace(/\\mathbf\{([^}]*)\}/g, "$1").replace(/\\mathrm\{([^}]*)\}/g, "$1");
  s = s.replace(/\\frac\{([^}]*)\}\{([^}]*)\}/g, "($1)/($2)");
  s = s.replace(/\\sqrt\{([^}]*)\}/g, "√($1)");
  const keys = Object.keys(map).sort((a, b) => b.length - a.length);
  for (const k of keys) s = s.split(k).join(map[k]);
  s = s.replace(/\^\{([^}]*)\}/g, "<sup>$1</sup>").replace(/\^([A-Za-z0-9])/g, "<sup>$1</sup>");
  s = s.replace(/_\{([^}]*)\}/g, "<sub>$1</sub>").replace(/_([A-Za-z0-9])/g, "<sub>$1</sub>");
  s = s.replace(/[{}]/g, "");
  return `<span class="md-math">${s}</span>`;
}

function mdInline(text) {
  // text đã được escape. Tách code inline trước để không bị định dạng chồng.
  const codes = [];
  text = text.replace(/`([^`]+)`/g, (_, c) => {
    codes.push(c);
    return `\u0000C${codes.length - 1}\u0000`;
  });
  const maths = [];
  const keepMath = (_, m) => {
    maths.push(mdLatexToText(m));
    return `\u0000M${maths.length - 1}\u0000`;
  };
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, keepMath)
             .replace(/\\\[([\s\S]+?)\\\]/g, keepMath)
             .replace(/\\\(([\s\S]+?)\\\)/g, keepMath)
             .replace(/\$([^$\n]+?)\$/g, keepMath);
  text = text.replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>")
             .replace(/__([^_\n]+?)__/g, "<strong>$1</strong>")
             .replace(/(^|[^*\w])\*([^*\n]+?)\*(?!\*)/g, "$1<em>$2</em>");
  text = text.replace(/\u0000M(\d+)\u0000/g, (_, i) => maths[+i]);
  text = text.replace(/\u0000C(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
  return text;
}

function mdSplitRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function renderMarkdown(src) {
  if (!src) return "";
  // 1) Tách khối code ``` ... ``` ra trước
  const blocks = [];
  let text = String(src).replace(/\r\n/g, "\n").replace(/```([a-zA-Z0-9_+-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    blocks.push(`<pre class="md-code"><code>${mdEscape(code.replace(/\n$/, ""))}</code></pre>`);
    return `\u0000B${blocks.length - 1}\u0000`;
  });

  // 2) Escape HTML cho phần còn lại
  text = mdEscape(text);

  // Một số model dồn tiêu đề/bảng/mục vào cùng một dòng: tách lại cho dễ đọc
  text = text.replace(/([^\n#])\s+(#{2,4}\s)/g, "$1\n\n$2");
  text = text.replace(/\s+---\s+(?=#{1,4}\s)/g, "\n\n---\n\n");

  const lines = text.split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) { i++; continue; }

    const blockMatch = trimmed.match(/^\u0000B(\d+)\u0000$/);
    if (blockMatch) { out.push(blocks[+blockMatch[1]]); i++; continue; }

    // Đường kẻ ngang
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) { out.push("<hr>"); i++; continue; }

    // Tiêu đề
    const h = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      const level = Math.min(h[1].length + 2, 6); // h1 -> h3 ... cho vừa khung chat
      out.push(`<h${level} class="md-h">${mdInline(h[2])}</h${level}>`);
      i++; continue;
    }

    // Bảng: dòng tiêu đề + dòng phân cách |---|---|
    if (trimmed.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      const header = mdSplitRow(trimmed);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
        rows.push(mdSplitRow(lines[i]));
        i++;
      }
      const th = header.map((c) => `<th>${mdInline(c)}</th>`).join("");
      const tr = rows.map((r) => `<tr>${r.map((c) => `<td>${mdInline(c)}</td>`).join("")}</tr>`).join("");
      out.push(`<div class="md-table-wrap"><table class="md-table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`);
      continue;
    }

    // Danh sách (không thứ tự / có thứ tự)
    if (/^([*-]|\d+[.)])\s+/.test(trimmed)) {
      const ordered = /^\d+[.)]\s+/.test(trimmed);
      const items = [];
      while (
        i < lines.length &&
        /^\s*([*-]|\d+[.)])\s+/.test(lines[i]) &&
        /^\s*\d+[.)]\s+/.test(lines[i]) === ordered
      ) {
        items.push(lines[i].trim().replace(/^([*-]|\d+[.)])\s+/, ""));
        i++;
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag} class="md-list">${items.map((it) => `<li>${mdInline(it)}</li>`).join("")}</${tag}>`);
      continue;
    }

    // Đoạn văn: gom các dòng liên tiếp
    const para = [];
    while (
      i < lines.length && lines[i].trim() &&
      !/^(#{1,6})\s+/.test(lines[i].trim()) &&
      !/^([*-]|\d+[.)])\s+/.test(lines[i].trim()) &&
      !/^\u0000B\d+\u0000$/.test(lines[i].trim())
    ) {
      para.push(lines[i].trim());
      i++;
    }
    out.push(`<p>${mdInline(para.join("<br>"))}</p>`);
  }
  return out.join("");
}

if (typeof module !== "undefined") {
  module.exports = { renderMarkdown, mdLatexToText };
}
