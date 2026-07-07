/* ============================================================================
 * advisor.js — vista del asesor: bandeja de casos + decisión approve/modify/reject.
 * Reusa el motor de investor-demo.js (idemoApi, idemoState, idemoSetStep,
 * idemoStepResult, idemoApproveProfile, builders) SIN redefinir nada de él.
 * ==========================================================================*/

const ADVISOR_FIRM_ID = (typeof IDEMO_FIRM_ID !== "undefined") ? IDEMO_FIRM_ID : "firm_demo_local";
const ADVISOR_PROFILES = [
  "conservador", "moderado-defensivo", "moderado", "moderado-agresivo", "agresivo",
];

// ── Bandeja de casos, AGRUPADA POR CLIENTE ─────────────────────────────────
// En vez de una lista plana de casos (se acumulan decenas en la demo), se
// agrupa por cliente: una fila por cliente con su caso más reciente + un
// desplegable con el historial. Así el asesor ve su cartera de clientes.
let _advisorClientNames = {};

async function advisorLoadBandeja() {
  const box = document.getElementById("advisor-bandeja");
  if (!box) return;
  box.innerHTML = `<div style="opacity:.7;font-size:13px;">Cargando clientes…</div>`;

  // nombres de clientes (client_id -> display_name / external_ref)
  const cliRes = await idemoApi("GET", "/clients");
  _advisorClientNames = {};
  if (cliRes.ok && cliRes.json && Array.isArray(cliRes.json.clients)) {
    cliRes.json.clients.forEach(c => {
      _advisorClientNames[c.client_id] = { name: c.display_name || c.client_id, ref: c.external_ref || "" };
    });
  }

  const res = await idemoApi("GET", `/firms/${encodeURIComponent(ADVISOR_FIRM_ID)}/cases`);
  if (!res.ok) {
    box.innerHTML = `<div class="msg msg-error">No se pudo cargar la bandeja. ${escapeHTML(res.detail || "")} (HTTP ${res.status})</div>`;
    return;
  }
  const cases = (res.json && res.json.cases) || [];
  box.innerHTML = advisorRenderGrouped(cases);
}

// agrupa cases por client_id y devuelve el HTML (una fila por cliente)
function advisorRenderGrouped(cases) {
  if (!cases.length) {
    return `<div class="msg msg-info">No hay casos todavía. Cargá un perfil abajo, o pedile a un cliente que complete su perfil en la vista Cliente.</div>`;
  }
  const byClient = {};
  cases.forEach(c => {
    const cid = c.client_id || "—";
    (byClient[cid] = byClient[cid] || []).push(c);
  });
  const lastCaseId = (() => { try { return localStorage.getItem("rfaLastCaseId"); } catch (e) { return null; } })();

  // orden de clientes: por el caso más reciente de cada uno
  const groups = Object.keys(byClient).map(cid => {
    const list = byClient[cid].sort((a, b) =>
      String(b.created_at_utc || b.case_id).localeCompare(String(a.created_at_utc || a.case_id)));
    return { cid, list, latest: list[0] };
  }).sort((a, b) =>
    String(b.latest.created_at_utc || b.latest.case_id).localeCompare(String(a.latest.created_at_utc || a.latest.case_id)));

  return groups.map(g => {
    const meta = _advisorClientNames[g.cid] || { name: g.cid, ref: "" };
    const n = g.list.length;
    const latest = g.latest;
    const hl = (latest.case_id === lastCaseId) ? " is-selected" : "";
    const refTag = meta.ref ? ` · <span class="b-id">#${escapeHTML(meta.ref)}</span>` : "";
    const historyId = `adv-hist-${g.cid.replace(/[^a-zA-Z0-9_]/g, "")}`;
    const historyRows = n > 1 ? g.list.slice(1).map(c =>
      `<div class="bandeja-row" style="margin-left:20px;" onclick='advisorOpenCase(${JSON.stringify(JSON.stringify(c))})'>` +
        `<div style="flex:1;min-width:200px;"><span class="b-id">${escapeHTML(c.case_id)}</span></div>` +
        `<div class="b-meta">${escapeHTML(c.created_at_utc || "").slice(0, 16).replace("T", " ")}</div>` +
        advisorStageLabel(c) +
      `</div>`).join("") : "";
    const toggle = n > 1
      ? `<button type="button" class="btn-secondary btn-sm" onclick="event.stopPropagation();advisorToggleHistory('${historyId}')">▸ ${n - 1} caso(s) anterior(es)</button>`
      : "";
    return (
      `<div style="margin-bottom:6px;">` +
        `<div class="bandeja-row${hl}" onclick='advisorOpenCase(${JSON.stringify(JSON.stringify(latest))})'>` +
          `<div style="flex:1;min-width:220px;">` +
            `<div class="b-title">${escapeHTML(meta.name)}${refTag}</div>` +
            `<div class="b-id">último: ${escapeHTML(latest.case_id)}</div>` +
          `</div>` +
          `<div class="b-meta">${escapeHTML(latest.created_at_utc || "").slice(0, 16).replace("T", " ")}</div>` +
          advisorStageLabel(latest) +
          (n > 1 ? `<span class="pill pill-grey">${n} casos</span>` : "") +
        `</div>` +
        (toggle ? `<div style="margin:4px 0 0 20px;">${toggle}</div>` : "") +
        `<div id="${historyId}" class="bandeja-history" style="display:none;margin-top:4px;">${historyRows}</div>` +
      `</div>`
    );
  }).join("");
}

function advisorToggleHistory(id) {
  const box = document.getElementById(id);
  if (box) box.style.display = (box.style.display === "none") ? "grid" : "none";
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

  // mostrar la card de revisión (respuestas + informe) y poblarla
  const reviewCard = document.getElementById("advisor-review-card");
  if (reviewCard) reviewCard.style.display = "";
  advisorRenderClientAnswers(c.case_id);
  advisorLoadNotes(c.case_id);

  advisorSetDecision("approve");
  const card = document.getElementById("idemo-step-approve");
  if (card && card.scrollIntoView) card.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ── Respuestas crudas del cliente (KYC + cuestionario mapeado) ─────────────
let _advisorQuestionnaire = null;

async function advisorRenderClientAnswers(caseId) {
  const box = document.getElementById("advisor-client-answers");
  if (!box) return;
  box.innerHTML = `<div class="sub">Cargando respuestas…</div>`;

  // cuestionario (textos de los ítems) — cacheado
  if (!_advisorQuestionnaire) {
    const q = await idemoApi("GET", "/kyc/tolerance-questionnaire");
    _advisorQuestionnaire = (q.ok && q.json && q.json.items) ? q.json.items : [];
  }
  // KYC vigente del caso
  const k = await idemoApi("GET", `/cases/${encodeURIComponent(caseId)}/kyc`);
  const subs = (k.ok && k.json && (k.json.submissions || k.json.kyc_submissions)) || [];
  const payload = subs.length ? (subs[subs.length - 1].payload || {}) : ((k.ok && k.json && k.json.payload) || {});

  // datos clave
  const fin = [
    ["Edad", payload.age], ["Horizonte (años)", payload.investment_horizon_years],
    ["Ingreso anual USD", payload.annual_income_usd], ["Patrimonio líquido USD", payload.liquid_net_worth],
    ["Objetivo", payload.investment_objective], ["Experiencia", payload.investment_experience],
    ["Estabilidad ingreso", payload.income_stability], ["Dependientes", payload.dependents_count],
  ].filter(([, v]) => v !== undefined && v !== null && v !== "");
  const finHtml = fin.map(([k2, v]) =>
    `<div><span style="opacity:.65;">${escapeHTML(k2)}:</span> <strong>${escapeHTML(String(v))}</strong></div>`).join("");

  // cuestionario: qN -> letra elegida -> texto de la opción
  const answers = payload.tolerance_answers || {};
  let qHtml = "";
  if (Object.keys(answers).length && _advisorQuestionnaire.length) {
    qHtml = _advisorQuestionnaire.map(item => {
      const chosen = answers[item.id];
      if (!chosen) return "";
      const opt = (item.options || []).find(o => o.key === chosen);
      const txt = opt ? opt.text : `(${chosen})`;
      return `<div style="margin:6px 0;padding:8px 10px;background:var(--rf-bg-subtle,#fafbfc);border-radius:6px;">` +
        `<div style="font-size:12px;opacity:.7;">${escapeHTML(item.text)}</div>` +
        `<div style="font-weight:600;">→ ${escapeHTML(txt)}</div></div>`;
    }).join("");
  } else {
    qHtml = `<div class="sub">Este KYC no trae respuestas del cuestionario (o es un perfil legacy con score directo).</div>`;
  }

  // preguntas abiertas
  const open = [
    ["Objetivo (texto libre)", payload.open_investment_goal || payload.open_goal],
    ["Reacción a una caída del 30%", payload.open_risk_reaction],
    ["Experiencia (texto libre)", payload.open_experience],
    ["Preocupaciones / restricciones", payload.open_concerns],
  ].filter(([, v]) => v);
  const openHtml = open.map(([k2, v]) =>
    `<div style="margin:6px 0;"><span style="opacity:.65;">${escapeHTML(k2)}:</span> ${escapeHTML(String(v))}</div>`).join("");

  box.innerHTML =
    `<div style="display:flex;gap:20px;flex-wrap:wrap;font-size:13px;margin-bottom:12px;">${finHtml}</div>` +
    `<div class="section-label" style="margin:8px 0;">Cuestionario de tolerancia (respuestas)</div>${qHtml}` +
    (openHtml ? `<div class="section-label" style="margin:14px 0 6px;">Respuestas abiertas</div><div style="font-size:13px;">${openHtml}</div>` : "");
}

// ── Informe del asesor: editable, guardado como evento auditado (versionado) ─
async function advisorSaveNote() {
  const caseId = window.idemoState.caseId;
  const ta = document.getElementById("advisor-report-text");
  const status = document.getElementById("advisor-report-status");
  if (!caseId) { if (status) status.textContent = "Abrí un caso primero."; return; }
  const text = (ta && ta.value.trim()) || "";
  if (!text) { if (status) status.textContent = "El informe no puede estar vacío."; return; }
  if (status) status.textContent = "Guardando…";

  // versión = notas previas + 1
  const prev = await advisorFetchNotes(caseId);
  const version = prev.length + 1;
  const res = await idemoApi("POST", `/cases/${encodeURIComponent(caseId)}/audit-events`, {
    event_type: "advisor_note",
    actor_role: "advisor",
    payload: { text, version, at: new Date().toISOString() },
  });
  if (!res.ok) {
    if (status) status.textContent = `No se pudo guardar (HTTP ${res.status}).`;
    return;
  }
  if (status) status.innerHTML = `<span style="color:var(--rf-emerald-700);">✓ Informe v${version} guardado y auditado.</span>`;
  advisorLoadNotes(caseId);
}

async function advisorFetchNotes(caseId) {
  const a = await idemoApi("GET", `/cases/${encodeURIComponent(caseId)}/audit`);
  const evs = (a.ok && a.json && (a.json.events || a.json.audit_events)) || [];
  return evs.filter(e => e.event_type === "advisor_note");
}

async function advisorLoadNotes(caseId) {
  const box = document.getElementById("advisor-report-history");
  if (!box) return;
  const notes = await advisorFetchNotes(caseId);
  if (!notes.length) { box.innerHTML = ""; return; }
  // la última al textarea (para seguir editando), el historial abajo
  const ta = document.getElementById("advisor-report-text");
  const last = notes[notes.length - 1];
  if (ta && !ta.value.trim()) ta.value = (last.payload && last.payload.text) || "";
  const rows = notes.slice().reverse().map(n => {
    const p = n.payload || {};
    const when = (p.at || n.created_at_utc || "").slice(0, 16).replace("T", " ");
    return `<div style="border-left:3px solid var(--rf-violet-700);padding:8px 12px;margin:6px 0;background:var(--rf-bg-subtle,#fafbfc);border-radius:0 6px 6px 0;">` +
      `<div style="font-size:11px;opacity:.65;">Versión ${escapeHTML(String(p.version || "?"))} · ${escapeHTML(when)} · auditado</div>` +
      `<div style="font-size:13px;margin-top:2px;white-space:pre-wrap;">${escapeHTML(p.text || "")}</div></div>`;
  }).join("");
  box.innerHTML = `<div class="section-label" style="margin:8px 0;">Historial del informe (auditado, append-only)</div>${rows}`;
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
