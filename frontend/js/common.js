// Risk-First Advisory — common helpers
// Loaded first; everything else (legacy demo / dashboard / workbench)
// depends on these globals. Classic script, no modules.

const API = "http://127.0.0.1:8000";

// ── AI profile follow-up global state ────────────────────────
let lastAIProfileRequestPayload = null;
let lastAIProfileResponse       = null;

// ── utilities ────────────────────────────────────────────────

function el(id) { return document.getElementById(id); }

function formatJSON(obj) {
  return JSON.stringify(obj, null, 2);
}

function statusPill(status) {
  if (!status) return '<span class="pill pill-grey">—</span>';
  const s = String(status).toLowerCase();
  if (s.includes("completed") && !s.includes("warn")) return `<span class="pill pill-green">${status}</span>`;
  if (s.includes("warn")) return `<span class="pill pill-orange">${status}</span>`;
  if (s.includes("blocked")) return `<span class="pill pill-red">${status}</span>`;
  if (s === "ok") return `<span class="pill pill-green">${status}</span>`;
  return `<span class="pill pill-blue">${status}</span>`;
}

function boolPill(v) {
  if (v === true)  return '<span class="pill pill-green">yes</span>';
  if (v === false) return '<span class="pill pill-grey">no</span>';
  return '<span class="pill pill-grey">—</span>';
}

function chips(arr, cls = "chip") {
  if (!arr || !arr.length) return '<span style="color:#a0aec0;font-size:12px;">none</span>';
  return `<div class="list-chips">${arr.map(x => `<span class="${cls}">${x}</span>`).join("")}</div>`;
}

function apiError(err) {
  if (err.name === "TypeError" && err.message.includes("fetch")) {
    return `<div class="msg msg-error">
      <strong>API not reachable.</strong> Start uvicorn first:<br>
      <code style="font-size:12px;">uvicorn risk_first_advisory.api_layer.main:app --reload</code><br><br>
      If you're opening this file via <code>file://</code>, the browser may also block requests due to CORS.
      Serve the frontend instead:<br>
      <code style="font-size:12px;">python -m http.server 5500 -d frontend</code>
      then open <code>http://127.0.0.1:5500</code>
    </div>`;
  }
  return `<div class="msg msg-error"><strong>Error:</strong> ${err.message}</div>`;
}

function setButtonLoading(btnId, loading) {
  const btn = el(btnId);
  if (!btn) return;
  btn.disabled = loading;
  btn.innerHTML = loading
    ? `<span class="spinner"></span>Running…`
    : "Run Workflow";
}

// ── tiny JSON details wrapper (used by cw*/cd* renderers) ─────────────
// Renders a `<details>` collapsible with the raw JSON inside a <pre>.
// Keeps executive summaries above the fold; technical JSON below.
// `escapeHTML` is defined in legacy-demo.js and loaded by the time these
// run, so we reference it lazily.
function rfaJsonDetails(data, label) {
  const heading = label || "Raw JSON response";
  const safeJson = (typeof escapeHTML === "function")
    ? escapeHTML(formatJSON(data))
    : formatJSON(data).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
  return `<details><summary>${heading}</summary><pre class="json-block">${safeJson}</pre></details>`;
}

