// MAM-AI clinician-feedback demo — chat UI

const $ = (id) => document.getElementById(id);
let SESSION_ID = crypto.randomUUID();
let history = [];          // [{role, content}]
let busy = false;
let META = null;

const SUGGESTIONS = [
  "How do I manage postpartum haemorrhage?",
  "Steps for newborn resuscitation",
  "Blood pressure thresholds for pre-eclampsia",
  "A 2-year-old is choking — what do I do?",
];

// ---------- disclaimer gate ----------
$("agree-box").addEventListener("change", (e) => { $("enter-btn").disabled = !e.target.checked; });
$("enter-btn").addEventListener("click", () => {
  $("gate").classList.add("hidden");
  $("app").classList.remove("hidden");
  $("input").focus();
});

// ---------- meta / caveats ----------
async function loadMeta() {
  try {
    META = await (await fetch("/api/meta")).json();
    $("stack-meta").textContent = `${META.generator} · ${META.retriever}`;
    $("caveat-banner").textContent = "⚠ " + META.caveats.join("  ·  ");
    $("gate-fidelity").textContent =
      `Mirrors: ${META.stack}. Generator: ${META.generator}. Corpus: ${META.corpus}.`;
  } catch (_) {}
}

// ---------- suggestions ----------
function renderSuggestions() {
  const box = $("suggestions");
  box.innerHTML = "";
  SUGGESTIONS.forEach((s) => {
    const c = document.createElement("button");
    c.className = "chip"; c.textContent = s;
    c.onclick = () => { $("input").value = s; send(); };
    box.appendChild(c);
  });
}

// ---------- rendering ----------
function renderMarkdown(text) {
  if (window.marked) return marked.parse(text);
  // fallback: escape + paragraphs
  const esc = text.replace(/[&<>]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[m]));
  return esc.replace(/\n/g, "<br>");
}

function addUserMsg(text) {
  $("empty-state")?.remove();
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="bubble"></div>`;
  el.querySelector(".bubble").textContent = text;
  $("chat").appendChild(el);
  scroll();
}

function addBotMsg() {
  const el = document.createElement("div");
  el.className = "msg bot";
  el.innerHTML = `<div style="width:100%">
      <div class="context-box hidden"></div>
      <div class="bubble cursor-blink"></div>
    </div>`;
  $("chat").appendChild(el);
  scroll();
  return el;
}

function renderCitations(box, citations) {
  if (!citations || !citations.length) {
    box.remove();
    return;
  }
  box.classList.remove("hidden");
  let body = "";
  citations.forEach((c) => {
    const src = c.source || "unknown";
    body += `<div class="cit">
      <div><span class="cit-src">[${c.n}] ${src}</span>
        <span class="cit-meta"> · p.${c.page} · sim ${c.score}</span></div>
      <div class="cit-meta">${escapeHtml(c.snippet)}</div>
    </div>`;
  });
  box.innerHTML =
    `<div class="context-head">Retrieved context — ${citations.length} guideline chunk(s) <span>▸</span></div>
     <div class="context-body">${body}</div>`;
  box.querySelector(".context-head").onclick = () => box.classList.toggle("open");
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[m]));
}

function scroll() { const c = $("chat"); c.scrollTop = c.scrollHeight; }

// ---------- feedback widget ----------
function addFeedback(parent, messageId) {
  const fb = document.createElement("div");
  fb.className = "feedback";
  const ISSUES = ["Refused / deflected", "Incomplete", "Wrong / unsafe",
                  "Not for a clinician", "Ignores local resources", "Citation wrong"];
  fb.innerHTML = `
    <div class="fb-row">
      <span class="fb-label">Was this useful?</span>
      <span class="stars">${[1,2,3,4,5].map((n)=>`<span class="star" data-n="${n}">★</span>`).join("")}</span>
    </div>
    <div class="fb-row">${ISSUES.map((t)=>`<button class="tag" data-tag="${t}">${t}</button>`).join("")}</div>
    <div class="fb-row"><textarea class="fb-comment" rows="2" placeholder="What would a clinician want instead? (optional)"></textarea></div>
    <div class="fb-row"><button class="fb-submit">Submit feedback</button></div>`;
  parent.appendChild(fb);

  let rating = 0;
  const issues = new Set();
  fb.querySelectorAll(".star").forEach((s) => {
    s.onclick = () => {
      rating = +s.dataset.n;
      fb.querySelectorAll(".star").forEach((x) => x.classList.toggle("on", +x.dataset.n <= rating));
    };
  });
  fb.querySelectorAll(".tag").forEach((t) => {
    t.onclick = () => { t.classList.toggle("on"); issues.has(t.dataset.tag) ? issues.delete(t.dataset.tag) : issues.add(t.dataset.tag); };
  });
  fb.querySelector(".fb-submit").onclick = async () => {
    const comment = fb.querySelector(".fb-comment").value.trim();
    await fetch("/api/feedback", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message_id: messageId, session_id: SESSION_ID,
        rating: rating || null, helpful: rating ? rating >= 3 : null,
        issues: [...issues], comment: comment || null,
      }),
    });
    fb.innerHTML = `<span class="fb-done">✓ Thank you — feedback recorded.</span>`;
  };
}

// ---------- send / stream ----------
async function send() {
  const input = $("input");
  const text = input.value.trim();
  if (!text || busy) return;
  busy = true; $("send-btn").disabled = true;
  input.value = ""; input.style.height = "auto";

  addUserMsg(text);
  history.push({ role: "user", content: text });

  const botEl = addBotMsg();
  const ctxBox = botEl.querySelector(".context-box");
  const bubble = botEl.querySelector(".bubble");
  let acc = "";
  let messageId = null;

  try {
    const resp = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history, session_id: SESSION_ID }),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const events = buf.split("\n\n");
      buf = events.pop();
      for (const evt of events) {
        const m = parseSSE(evt);
        if (!m) continue;
        if (m.event === "context") {
          messageId = m.data.message_id;
          SESSION_ID = m.data.session_id || SESSION_ID;
          renderCitations(ctxBox, m.data.citations);
        } else if (m.event === "token") {
          acc += m.data.t;
          bubble.innerHTML = renderMarkdown(acc);
          scroll();
        } else if (m.event === "error") {
          bubble.classList.remove("cursor-blink");
          bubble.innerHTML = `<em style="color:#b91c1c">${escapeHtml(m.data.message)}</em>`;
        } else if (m.event === "done") {
          messageId = m.data.message_id || messageId;
        }
      }
    }
  } catch (e) {
    bubble.innerHTML = `<em style="color:#b91c1c">Connection error: ${escapeHtml(String(e))}</em>`;
  }

  bubble.classList.remove("cursor-blink");
  bubble.innerHTML = renderMarkdown(acc);
  history.push({ role: "assistant", content: acc });
  if (messageId) addFeedback(botEl.querySelector("div"), messageId);

  busy = false; $("send-btn").disabled = false; $("input").focus();
}

function parseSSE(block) {
  let event = "message", data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return null;
  try { return { event, data: JSON.parse(data) }; } catch (_) { return null; }
}

// ---------- input handlers ----------
$("send-btn").addEventListener("click", send);
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
$("input").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
});
$("reset-btn").addEventListener("click", () => {
  history = []; SESSION_ID = crypto.randomUUID();
  $("chat").innerHTML = `<div class="empty-state" id="empty-state">
      <h2>Ask a clinical question</h2>
      <p>e.g. management of postpartum haemorrhage, neonatal resuscitation steps, pre-eclampsia thresholds.</p>
      <div class="suggestions" id="suggestions"></div></div>`;
  renderSuggestions();
});

loadMeta();
renderSuggestions();
