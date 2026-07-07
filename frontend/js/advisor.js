/* ============================================================================
 * advisor.js — vista del asesor: bandeja de casos + decisión approve/modify/reject.
 * Reusa el motor de investor-demo.js (idemoApi, idemoState, idemoSetStep,
 * idemoStepResult, idemoApproveProfile, builders) SIN redefinir nada de él.
 * ==========================================================================*/

const ADVISOR_FIRM_ID = (typeof IDEMO_FIRM_ID !== "undefined") ? IDEMO_FIRM_ID : "firm_demo_local";
const ADVISOR_PROFILES = [
  "conservador", "moderado-defensivo", "moderado", "moderado-agresivo", "agresivo",
];

// ── Bandeja de casos ────────────────────────────────────────────────────────
async function advisorLoadBandeja() {
  const box = document.getElementById("advisor-bandeja");
  if (!box) return;
  box.innerHTML = `<div style="opacity:.7;font-size:13px;">Cargando casos…</div>`;
  const res = await idemoApi("GET", `/firms/${encodeURIComponent(ADVISOR_FIRM_ID)}/cases`);
  if (!res.ok) {
    box.innerHTML = `<div class="msg msg-error">No se pudo cargar la bandeja. ${escapeHTML(res.detail || "")} (HTTP ${res.status})</div>`;
    return;
  }
  const cases = (res.json && res.json.cases) || [];
  // más nuevos primero (por created_at_utc; fallback por case_id)
  cases.sort((a, b) => String(b.created_at_utc || b.case_id).localeCompare(String(a.created_at_utc || a.case_id)));
  const lastCaseId = (() => { try { return localStorage.getItem("rfaLastCaseId"); } catch (e) { return null; } })();
  const top = cases.slice(0, 30);
  if (!top.length) {
    box.innerHTML = `<div class="msg msg-info">No hay casos todavía. Cargá un perfil abajo, o pedile a un cliente que complete su perfil en la vista Cliente.</div>`;
    return;
  }
  box.innerHTML = top.map(c => {
    const stage = advisorStageLabel(c);
    const highlight = (c.case_id === lastCaseId) ? " is-selected" : "";
    return (
      `<div class="bandeja-row${highlight}" onclick='advisorOpenCase(${JSON.stringify(JSON.stringify(c))})'>` +
        `<div style="flex:1;min-width:220px;">` +
          `<div class="b-title">${escapeHTML(c.title || "(sin título)")}</div>` +
          `<div class="b-id">${escapeHTML(c.case_id)}</div>` +
        `</div>` +
        `<div class="b-meta">${escapeHTML(c.created_at_utc || "").slice(0, 16).replace("T", " ")}</div>` +
        stage +
      `</div>`
    );
  }).join("");
}

function advisorStageLabel(c) {
  if (c.current_portfolio_selection_id) return `<span class="pill pill-green">cartera elegida</span>`;
  if (c.current_approved_profile_id) return `<span class="pill pill-blue">perfil aprobado</span>`;
  if (c.current_kyc_submission_id) return `<span class="pill pill-orange">esperando revisión</span>`;
  return `<span class="pill pill-grey">nuevo</span>`;
}

// ── Abrir un caso de la bandeja y continuar la revisión ─────────────────────
async function advisorOpenCase(rowJson) {
  let c;
  try { c = JSON.parse(rowJson); } catch (e) { return; }
  window.idemoState.caseId = c.case_id;
  window.idemoState.kycSubmissionId = c.current_kyc_submission_id || null;
  window.idemoState.approvalId = c.current_approved_profile_id || null;

  // marcar visualmente prepare + kyc como hechos (vienen del cliente)
  if (window.idemoState.kycSubmissionId) {
    idemoSetStep("prepare", "done");
    idemoStepResult("prepare", "ok", `<strong>Caso abierto desde la bandeja.</strong> <code>${escapeHTML(c.case_id)}</code>`);
    idemoSetStep("kyc", "done");
    idemoStepResult("kyc", "ok", `KYC recibido del cliente (<code>${escapeHTML(c.current_kyc_submission_id)}</code>).`);
  }

  // traer el último análisis (para el perfil propuesto); las cards ricas se ven
  // al re-analizar (paso 3), porque el GET no las deriva.
  const an = await idemoApi("GET", `/cases/${encodeURIComponent(c.case_id)}/ai/profile-analysis`);
  let proposed = null, analysisId = null;
  if (an.ok && an.json && Array.isArray(an.json.analyses) && an.json.analyses.length) {
    const last = an.json.analyses[an.json.analyses.length - 1];
    proposed = last.preliminary_profile || null;
    analysisId = last.analysis_id || null;
  }
  window.idemoState.aiProposedProfile = proposed || "moderado";
  window.idemoState.aiAnalysisId = analysisId;

  const pill = document.getElementById("advisor-open-case-pill");
  if (pill) pill.textContent = `caso abierto: ${c.case_id}`;

  idemoSetStep("ai", proposed ? "done" : "pending");
  idemoStepResult("ai", proposed ? "ok" : "warn",
    proposed
      ? `<strong>Perfil propuesto por la IA:</strong> <code>${escapeHTML(proposed)}</code>. ` +
        `Para ver el detalle (Risk Number, Risk Gap, capacidad) volvé a correr <em>"Analizar perfil con IA"</em>.`
      : `Este caso todavía no tiene análisis. Corré <em>"Analizar perfil con IA"</em>.`);

  advisorSetDecision("approve");
  const card = document.getElementById("idemo-step-approve");
  if (card && card.scrollIntoView) card.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ── Segmento de decisión approve / modify / reject ──────────────────────────
function advisorSetDecision(dec) {
  const seg = document.getElementById("advisor-decision-seg");
  if (seg) {
    seg.querySelectorAll("button").forEach(b => {
      b.classList.toggle("is-active", b.getAttribute("data-dec") === dec);
    });
  }
  const panel = document.getElementById("advisor-decision-panel");
  if (!panel) return;
  const rationale = `<div class="field" style="margin-top:8px;"><label>Justificación (queda en la auditoría)</label>` +
    `<textarea id="advisor-rationale" rows="2">${advisorDefaultRationale(dec)}</textarea></div>`;
  if (dec === "approve") {
    panel.innerHTML = rationale +
      `<div class="actions" style="margin-top:8px;"><button class="btn-primary" onclick="advisorSubmitDecision('approve')">Aprobar perfil propuesto</button></div>`;
  } else if (dec === "modify") {
    const opts = ADVISOR_PROFILES.map(p =>
      `<option value="${p}"${p === (window.idemoState.aiProposedProfile) ? " disabled" : ""}>${p}</option>`).join("");
    panel.innerHTML =
      `<div class="field"><label>Perfil que aprueba el asesor <span class="hint">debe diferir del propuesto (${escapeHTML(window.idemoState.aiProposedProfile || "—")})</span></label>` +
      `<select id="advisor-modify-profile">${opts}</select></div>` +
      rationale +
      `<div class="actions" style="margin-top:8px;"><button class="btn-primary" onclick="advisorSubmitDecision('modify')">Aprobar con modificación</button></div>`;
  } else {
    panel.innerHTML = rationale +
      `<div class="actions" style="margin-top:8px;"><button class="btn-primary" style="background:var(--rf-rose-600);" onclick="advisorSubmitDecision('reject')">Rechazar perfil</button></div>` +
      `<div class="sub" style="margin-top:6px;">Al rechazar, el caso vuelve al cliente para un nuevo KYC. No se generan carteras (I-017).</div>`;
  }
}

function advisorDefaultRationale(dec) {
  const name = (typeof idemoStr === "function") ? idemoStr("idemo-name", "el inversor") : "el inversor";
  if (dec === "approve") return `El asesor revisó el perfil de ${name} y aprueba el perfil propuesto.`;
  if (dec === "modify") return `El asesor ajusta el perfil de ${name} tras revisar el análisis y la capacidad.`;
  return `El asesor rechaza el perfil: hay que revisar el KYC con el cliente antes de avanzar.`;
}

async function advisorSubmitDecision(dec) {
  if (!window.idemoState.caseId) {
    idemoStepResult("approve", "warn", "Abrí un caso de la bandeja o preparalo abajo primero.");
    return;
  }
  if (dec === "approve") { await idemoApproveProfile(); return; }

  const rationaleEl = document.getElementById("advisor-rationale");
  const rationale = (rationaleEl && rationaleEl.value.trim()) || "";
  if (!rationale) { idemoStepResult("approve", "warn", "La justificación no puede quedar vacía."); return; }

  idemoSetStep("approve", "active");
  const body = { decision: dec, rationale, source: "manual" };
  if (window.idemoState.aiAnalysisId) body.ai_profile_analysis_id = window.idemoState.aiAnalysisId;

  if (dec === "modify") {
    const sel = document.getElementById("advisor-modify-profile");
    const profile = sel && sel.value;
    if (!profile) { idemoStepResult("approve", "warn", "Elegí un perfil para la modificación."); return; }
    body.approved_profile = profile;
  }

  const res = await idemoApi("POST",
    `/cases/${encodeURIComponent(window.idemoState.caseId)}/profile-approval`, body);
  if (!res.ok) {
    idemoSetStep("approve", "error");
    idemoStepResult("approve", "error",
      `<strong>No se pudo registrar la decisión.</strong> ${escapeHTML(res.detail || "")} (HTTP ${res.status})`);
    return;
  }

  if (dec === "reject") {
    // I-017: rechazo NO deja perfil aprobado; no habilitar propuesta.
    window.idemoState.approvalId = null;
    idemoSetStep("approve", "done");
    idemoStepResult("approve", "ok",
      `<strong>Perfil rechazado.</strong> El caso vuelve al cliente para un nuevo KYC. ` +
      `No se generan carteras hasta que haya un perfil aprobado. La decisión queda en la auditoría.`);
    return;
  }

  // modify → hay perfil aprobado, se puede seguir
  window.idemoState.approvalId = res.json.approval_id;
  window.idemoState.approvedProfile = res.json.approved_profile;
  idemoSetStep("approve", "done");
  idemoStepResult("approve", "ok",
    `<strong>Perfil aprobado con modificación.</strong> Perfil final: ` +
    `<code>${escapeHTML(res.json.approved_profile || "—")}</code> · decisión <code>${escapeHTML(res.json.decision)}</code>. ` +
    `Ya podés generar la propuesta de cartera (paso 5).`);
}

// cargar la bandeja al abrir la página
document.addEventListener("DOMContentLoaded", advisorLoadBandeja);
