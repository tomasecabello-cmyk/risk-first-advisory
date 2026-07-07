/* ============================================================================
 * client.js — vista del cliente: completa su perfil y ve la primera lectura.
 * Reusa el motor de investor-demo.js (idemoPrepareCase, idemoSubmitKyc, idemoApi,
 * builders) SIN redefinir nada. Los helpers de paso de investor-demo.js hacen
 * no-op cuando el DOM de los 8 pasos no existe (están null-guardeados), así que
 * es seguro reusarlos acá.
 * ==========================================================================*/

// ── Wizard: navegación paso a paso ─────────────────────────────────────────
const CLIENT_WIZARD_STEPS = 4;
let clientWizardStep = 1;

function clientWizardShow(n) {
  clientWizardStep = Math.max(1, Math.min(CLIENT_WIZARD_STEPS, n));
  document.querySelectorAll(".wizard-step").forEach(s => {
    s.classList.toggle("is-active", Number(s.getAttribute("data-step")) === clientWizardStep);
  });
  // progreso: nodos y barras
  document.querySelectorAll(".wizard-progress .wz-node").forEach(node => {
    const i = Number(node.getAttribute("data-node"));
    node.classList.toggle("is-active", i === clientWizardStep);
    node.classList.toggle("is-done", i < clientWizardStep);
  });
  document.querySelectorAll(".wizard-progress .wz-bar").forEach(bar => {
    bar.classList.toggle("is-done", Number(bar.getAttribute("data-bar")) < clientWizardStep);
  });
  // botones
  const back = document.getElementById("client-back-btn");
  const next = document.getElementById("client-next-btn");
  const submit = document.getElementById("client-submit-btn");
  if (back) back.style.visibility = clientWizardStep === 1 ? "hidden" : "visible";
  const last = clientWizardStep === CLIENT_WIZARD_STEPS;
  if (next) next.style.display = last ? "none" : "inline-flex";
  if (submit) submit.style.display = last ? "inline-flex" : "none";
  // scroll suave al inicio de la card
  const card = document.querySelector(".card-hero .card-body");
  if (card && card.scrollIntoView) card.scrollIntoView({ behavior: "smooth", block: "start" });
}

function clientWizardNext() { clientWizardShow(clientWizardStep + 1); }
function clientWizardBack() { clientWizardShow(clientWizardStep - 1); }

async function clientSubmitProfile() {
  const btn = document.getElementById("client-submit-btn");
  const out = document.getElementById("client-result");
  if (!out) return;
  if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>Enviando…`; }
  out.innerHTML = "";

  try {
    // 1. Preparar el caso (crea el contenedor; setea idemoState.caseId).
    const okPrep = await idemoPrepareCase();
    if (!okPrep || !window.idemoState.caseId) {
      out.innerHTML = clientError("No se pudo iniciar tu caso. ¿Está el backend corriendo? Probá de nuevo.");
      return;
    }
    // 2. Enviar el KYC (arma el payload desde el formulario; setea kycSubmissionId).
    const okKyc = await idemoSubmitKyc();
    if (!okKyc) {
      out.innerHTML = clientError("No se pudo enviar tu perfil. Revisá los campos y probá de nuevo.");
      return;
    }
    // 3. Analizar el perfil (control propio del render para encuadrarlo al cliente).
    const caseId = window.idemoState.caseId;
    const res = await idemoApi("POST",
      `/cases/${encodeURIComponent(caseId)}/ai/profile-analysis`, { analysis_type: "initial" });

    // Guardar el puntero para que el asesor lo encuentre en su bandeja.
    try {
      localStorage.setItem("rfaLastCaseId", caseId);
      const name = clientName();
      const prev = JSON.parse(localStorage.getItem("rfaDemoCases") || "[]");
      prev.unshift({ caseId, name, ts: new Date().toISOString() });
      localStorage.setItem("rfaDemoCases", JSON.stringify(prev.slice(0, 20)));
    } catch (e) { /* localStorage puede fallar en algunos navegadores; no es crítico */ }

    if (!res.ok) {
      // Sin OpenAI/clave el análisis puede no estar disponible; el perfil igual quedó registrado.
      out.innerHTML = clientSent(caseId) + clientError(
        "Tu perfil quedó registrado, pero el análisis automático no está disponible en esta demo. " +
        "Tu asesor lo va a revisar igual. " +
        `<span style="opacity:.7;">(HTTP ${res.status})</span>`);
      return;
    }

    const j = res.json || {};
    out.innerHTML =
      clientSent(caseId) +
      (typeof idemoRiskNumberCardHTML === "function" ? idemoRiskNumberCardHTML(j.risk_number) : "") +
      (typeof idemoCapacityGapCardHTML === "function" ? idemoCapacityGapCardHTML(j.capacity_gap) : "") +
      clientRiskGapInfo(j.risk_gap) +
      clientClosing();

    const anchor = document.getElementById("client-result");
    if (anchor && anchor.scrollIntoView) anchor.scrollIntoView({ behavior: "smooth", block: "start" });
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = "Enviar mi perfil →"; }
  }
}

function clientName() {
  const el = document.getElementById("idemo-name");
  return (el && el.value.trim()) || "Inversor demo";
}

function clientSent(caseId) {
  return (
    `<div class="msg msg-success" style="margin-bottom:12px;">` +
      `<strong>¡Perfil enviado!</strong> Lo registramos como tu caso ` +
      `<code>${escapeHTML(caseId)}</code>. Abajo tenés tu primera lectura de riesgo — ` +
      `ahora quedás <strong>esperando a tu asesor</strong>: él la revisa antes de presentarte opciones.` +
      `<div style="margin-top:10px;">` +
        `<button class="btn-secondary" onclick="clientOpenCaseView()">Ver el estado de mi caso →</button>` +
      `</div>` +
    `</div>`
  );
}

// Risk Gap encuadrado para el cliente: informativo, sin controles de re-análisis
// (repreguntar es acción del asesor). Solo se muestra si hay inconsistencia real.
function clientRiskGapInfo(rg) {
  if (!rg || !rg.gap_level || rg.gap_level === "low") return "";
  const q = Array.isArray(rg.confirmation_questions) ? rg.confirmation_questions : [];
  const items = q.map(t => `<li>${escapeHTML(t)}</li>`).join("");
  return (
    `<div style="margin-top:12px;border:1px solid #ddd;border-left:4px solid #c90;border-radius:6px;padding:14px;background:#fffdf7;">` +
      `<div style="font-weight:600;">Encontramos algo para conversar con tu asesor</div>` +
      `<div style="font-size:13px;margin:8px 0;">${escapeHTML(rg.gap_explanation || "")}</div>` +
      (items ? `<div style="font-size:12px;opacity:.8;margin-bottom:4px;">Tu asesor probablemente te pregunte:</div><ul style="margin:0 0 0 18px;font-size:13px;">${items}</ul>` : "") +
      `<div style="font-size:12px;opacity:.75;margin-top:8px;">Esto no es un error ni una nota en tu contra: es una señal para que la cartera coincida de verdad con lo que tolerás.</div>` +
    `</div>`
  );
}

function clientClosing() {
  return (
    `<div class="msg msg-info" style="margin-top:14px;">` +
      `<strong>¿Y ahora?</strong> Tu asesor revisa este perfil, repregunta si hace falta, y te ` +
      `presenta opciones de cartera alineadas con tu número de riesgo. No se genera ninguna ` +
      `cartera sin la firma de tu asesor.` +
    `</div>`
  );
}

function clientError(msg) {
  return `<div class="msg msg-error">${msg}</div>`;
}

// ── Vista read-only del caso ────────────────────────────────────────────────
// El cliente ve QUÉ decidió su asesor (cartera elegida, variantes consideradas,
// reporte final) sin poder accionar nada: los builders idemo* se reusan por
// carga y los <button> que traen (acciones del asesor) se remueven del DOM.

function clientCaseId() {
  try { return localStorage.getItem("rfaLastCaseId") || null; } catch (e) { return null; }
}

// next_recommended_action del backend → copy encuadrado al cliente.
const CLIENT_WAITING_COPY = {
  submit_kyc:                    "Todavía no recibimos tu perfil completo. Completá el formulario de arriba.",
  run_ai_profile_analysis:       "Tu perfil quedó registrado y está en cola para la primera lectura de riesgo.",
  approve_profile:               "Tu asesor está revisando tu perfil de riesgo.",
  record_investment_preferences: "Tu asesor está relevando tus preferencias de inversión.",
  run_universe_filter:           "Tu asesor está definiendo el universo de instrumentos apto para tu perfil.",
  generate_portfolio_proposal:   "Tu asesor está preparando opciones de cartera alineadas con tu perfil.",
  review_override:               "Tu asesor está evaluando las opciones de cartera (una requiere su firma extra).",
  select_portfolio:              "Tu asesor está eligiendo entre las opciones de cartera generadas.",
  generate_report:               "Tu asesor ya eligió una cartera y está preparando tu reporte.",
  ready_for_review:              "Tu caso está completo: cartera elegida y reporte generado.",
  closed:                        "Tu caso está cerrado. Hablá con tu asesor si querés retomarlo.",
};

function clientWaitingBlock(progress) {
  const action = (progress && progress.next_recommended_action) || "";
  const copy = CLIENT_WAITING_COPY[action] || "Tu asesor está trabajando en tu caso.";
  const ratio = (progress && typeof progress.completion_ratio === "number")
    ? Math.round(progress.completion_ratio * 100) : null;
  const pct = ratio === null ? "" :
    `<div style="font-size:12px;opacity:.75;margin-top:6px;">Avance del caso: <strong>${ratio}%</strong></div>`;
  return (
    `<div class="msg msg-info" style="margin-top:12px;">` +
      `<strong>Esperando a tu asesor.</strong> ${escapeHTML(copy)}${pct}` +
      `<div style="font-size:12px;opacity:.75;margin-top:6px;">Ninguna cartera se genera ni se elige sin la firma de tu asesor.</div>` +
    `</div>`
  );
}

// Última nota del asesor (AuditEvent event_type="advisor_note", mismo patrón
// que advisorFetchNotes en advisor.js — ese archivo no se carga en esta página).
async function clientFetchAdvisorNote(caseId) {
  const res = await idemoApi("GET", `/cases/${encodeURIComponent(caseId)}/audit`);
  if (!res.ok || !res.json) return null;
  const evs = res.json.events || res.json.audit_events || [];
  const notes = evs.filter(e => e.event_type === "advisor_note");
  return notes.length ? notes[notes.length - 1] : null;
}

function clientAdvisorNoteBlock(note) {
  if (!note || !note.payload || !note.payload.text) return "";
  const p = note.payload;
  const when = (p.at || note.created_at_utc || "").slice(0, 16).replace("T", " ");
  return (
    `<div class="section-label" style="margin:16px 0 4px;">Comentario de tu asesor</div>` +
    `<div style="border-left:3px solid var(--rf-violet-700,#7c5cbf);padding:10px 14px;background:var(--rf-bg-subtle,#fafbfc);border-radius:0 6px 6px 0;">` +
      `<div style="font-size:13px;white-space:pre-wrap;">${escapeHTML(p.text)}</div>` +
      (when ? `<div style="font-size:11px;opacity:.65;margin-top:6px;">${escapeHTML(when)} · quedó auditado</div>` : "") +
    `</div>`
  );
}

function clientOpenCaseView() {
  const card = document.getElementById("client-case-card");
  if (card) card.style.display = "";
  clientLoadCase();
  if (card && card.scrollIntoView) card.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function clientLoadCase() {
  const view = document.getElementById("client-case-view");
  if (!view) return;
  const caseId = clientCaseId();
  if (!caseId) {
    view.innerHTML = clientError(
      "No encontramos un caso tuyo en este navegador. Completá y enviá tu perfil primero.");
    return;
  }
  view.innerHTML = `<div style="opacity:.7;font-size:13px;"><span class="spinner"></span>Consultando tu caso…</div>`;

  const res = await idemoApi("GET", `/cases/${encodeURIComponent(caseId)}/summary`);
  if (!res.ok) {
    view.innerHTML = clientError(
      res.status === 404
        ? "Tu caso ya no está disponible en esta demo (la base local pudo haberse reiniciado)."
        : "No pudimos consultar tu caso. ¿Está el backend corriendo? Probá de nuevo.");
    return;
  }

  const s = res.json || {};
  const sel = s.current_portfolio_selection || null;
  const prop = s.current_portfolio_proposal || null;
  const rep = s.current_report || null;
  const note = await clientFetchAdvisorNote(caseId);

  let html =
    `<div style="font-size:12px;opacity:.7;margin-top:4px;">Caso <code>${escapeHTML(caseId)}</code></div>`;

  if (!sel) {
    html += clientWaitingBlock(s.progress);
  } else {
    html += `<div class="section-label" style="margin:14px 0 4px;">La cartera que eligió tu asesor</div>`;
    if (typeof idemoBuildSelectedPortfolioHtml === "function") {
      html += idemoBuildSelectedPortfolioHtml(sel);
    }
    const candidates = (prop && Array.isArray(prop.candidates)) ? prop.candidates : [];
    if (candidates.length && typeof idemoBuildPortfolioComparisonHtml === "function") {
      html +=
        `<details style="margin-top:12px;">` +
          `<summary style="cursor:pointer;font-size:12px;font-weight:600;">Las variantes que consideró tu asesor</summary>` +
          idemoBuildPortfolioComparisonHtml(candidates) +
        `</details>`;
    }
  }

  html += clientAdvisorNoteBlock(note);

  if (rep) {
    html += `<div class="section-label" style="margin:16px 0 4px;">Tu reporte</div>`;
    if (typeof idemoBuildReportPreviewHtml === "function") {
      html += idemoBuildReportPreviewHtml(rep);
    }
  } else if (sel) {
    html += `<div style="font-size:12px;opacity:.75;margin-top:12px;">El reporte final todavía no fue generado por tu asesor.</div>`;
  }

  view.innerHTML = html;
  // Read-only: los builders reusados traen botones de acción del asesor
  // ("Seleccionar", etc.) — acá el cliente no decide nada, se remueven.
  view.querySelectorAll("button").forEach(b => b.remove());
}

// init del wizard + banner de caso en curso
document.addEventListener("DOMContentLoaded", function () {
  if (document.getElementById("client-wizard-progress")) clientWizardShow(1);
  const banner = document.getElementById("client-case-banner");
  if (banner && clientCaseId()) banner.style.display = "flex";
});
