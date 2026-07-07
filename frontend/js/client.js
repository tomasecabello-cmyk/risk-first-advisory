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
      `tu asesor la va a revisar antes de presentarte opciones.` +
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

// init del wizard
document.addEventListener("DOMContentLoaded", function () {
  if (document.getElementById("client-wizard-progress")) clientWizardShow(1);
});
