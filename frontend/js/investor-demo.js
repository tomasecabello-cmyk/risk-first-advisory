// ═════════════════════════════════════════════════════════════════════════
// INVESTOR-FACING DEMO  (Fase 3.6 — advisor-friendly entry)
// ═════════════════════════════════════════════════════════════════════════
//
// Flujo simple, en español, para mostrar la demo a un profesor / asesor no
// técnico SIN exponer Dashboard / firms / advisors / clients / IDs internos.
//
// La UI vive en `#card-investor-demo` (frontend/index.html). Este script
// implementa los 8 pasos del flujo: preparar caso → KYC → análisis IA →
// aprobación → propuesta → selección → reporte → auditoría.
//
// Internamente reusa endpoints existentes y los helpers `escapeHTML`,
// `formatJSON`, `cwRenderHoldingsTable`, `cwNormalizeHoldings` ya cargados
// por common.js + case-workbench.js. No depende de IDs externos: usa el
// snapshot del seed (firm/advisor/client demo) y crea un caso fresco por
// intento.
//
// Tokens del fallback dev del backend. Para tokens custom, usar el
// Dashboard técnico (modo avanzado) más abajo.
const IDEMO_ADVISOR_TOKEN    = "dev-advisor-token";
const IDEMO_COMPLIANCE_TOKEN = "dev-compliance-token";

// IDs estables del seed (creados por `python scripts/bootstrap_local_demo.py`).
const IDEMO_FIRM_ID    = "firm_demo_local";
const IDEMO_ADVISOR_ID = "advisor_demo_local";
const IDEMO_CLIENT_ID  = "client_demo_local";

// Lista canónica de pasos para el progress checklist.
const IDEMO_STEPS = [
  { key: "prepare", label: "Preparar caso demo" },
  { key: "kyc",     label: "Enviar perfil / KYC" },
  { key: "ai",      label: "Analizar perfil con IA" },
  { key: "approve", label: "Aprobar perfil como asesor" },
  { key: "propose", label: "Generar propuesta de cartera" },
  { key: "select",  label: "Seleccionar cartera sugerida" },
  { key: "report",  label: "Generar reporte" },
  { key: "audit",   label: "Verificar auditoría" },
];

// ── State (window-scoped; se reinicia con idemoReset) ────────────────
window.idemoState = window.idemoState || {
  caseId:             null,
  kycSubmissionId:    null,
  aiAnalysisId:       null,
  aiProposedProfile:  null,
  aiSkipped:          false,        // true si el AI step se saltó por falta de OPENAI_API_KEY
  approvalId:         null,
  approvedProfile:    null,
  preferenceId:       null,
  filterRunId:        null,
  proposalId:         null,
  candidates:         [],
  selectionId:        null,
  selectedVariant:    null,
  selectedCandidate:  null,
  reportId:           null,
  reportMarkdown:     null,
  auditIntact:        null,
  auditTotalEvents:   null,
  // status del checklist: {pending,active,done,error,skipped}
  stepStatus:         {},
};

function idemoReset() {
  Object.assign(window.idemoState, {
    caseId: null, kycSubmissionId: null, aiAnalysisId: null,
    aiProposedProfile: null, aiSkipped: false,
    approvalId: null, approvedProfile: null,
    preferenceId: null, filterRunId: null,
    proposalId: null, candidates: [],
    selectionId: null, selectedVariant: null, selectedCandidate: null,
    reportId: null, reportMarkdown: null,
    auditIntact: null, auditTotalEvents: null,
    stepStatus: {},
  });
  // Limpiar paneles
  const ids = [
    "idemo-status", "idemo-portfolio-result", "idemo-selection-result",
    "idemo-report-result", "idemo-audit-result",
  ];
  for (const id of ids) {
    const node = document.getElementById(id);
    if (node) node.innerHTML = "";
  }
  for (const id of ["idemo-portfolio-block", "idemo-selection-block", "idemo-report-block", "idemo-audit-block"]) {
    const node = document.getElementById(id);
    if (node) node.style.display = "none";
  }
  idemoRenderProgress();
  idemoStatus("ok", "Estado limpio. Listo para empezar.");
}

// ── Helpers de HTTP ───────────────────────────────────────────────────

function idemoHeaders(token, withContent) {
  const h = { "Authorization": `Bearer ${token}` };
  if (withContent) h["Content-Type"] = "application/json";
  return h;
}

async function idemoApi(method, path, body, token) {
  // Reusa el patrón de cdApiFetch / cwApiFetch para uniformidad de errores.
  const tok = token || IDEMO_ADVISOR_TOKEN;
  try {
    const opts = {
      method,
      headers: idemoHeaders(tok, body !== undefined && body !== null),
    };
    if (body !== undefined && body !== null) {
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(`${API}${path}`, opts);
    let json = null;
    try { json = await r.json(); } catch (_) { /* not json */ }
    if (!r.ok) {
      const detail = (json && (json.detail || json.message))
        ? (typeof json.detail === "string" ? json.detail : JSON.stringify(json.detail))
        : `HTTP ${r.status}`;
      return { ok: false, status: r.status, detail, json };
    }
    return { ok: true, status: r.status, json };
  } catch (err) {
    return { ok: false, status: 0, networkError: true, err, detail: err.message };
  }
}

// ── Form readers ──────────────────────────────────────────────────────

function idemoInt(id, fallback) {
  const v = parseInt(document.getElementById(id).value, 10);
  return Number.isFinite(v) ? v : fallback;
}
function idemoNumber(id, fallback) {
  const v = parseFloat(document.getElementById(id).value);
  return Number.isFinite(v) ? v : fallback;
}
function idemoStr(id, fallback) {
  const v = (document.getElementById(id).value || "").trim();
  return v || (fallback || "");
}

function idemoBuildKycPayload() {
  // Mapeos:
  //   liquidity_need (baja/media/alta) → liquidity_need_score (3/5/8)
  //   risk_tolerance (1-10) → risk_capacity_score = min(risk+1, 10)
  //   risk_tolerance → max_acceptable_drawdown_pct ≈ risk * 3
  const liqMap = { baja: 3, media: 5, alta: 8 };
  const risk = idemoInt("idemo-risk", 6);
  const liquidNeed = liqMap[idemoStr("idemo-liquidity", "media")] || 5;
  const liquidNW = idemoNumber("idemo-liquid", 150000);

  return {
    age:                          idemoInt("idemo-age", 42),
    risk_tolerance_score:         risk,
    risk_capacity_score:          Math.min(risk + 1, 10),
    liquidity_need_score:         liquidNeed,
    investment_horizon_years:     idemoInt("idemo-horizon", 10),
    investment_experience:        idemoStr("idemo-experience", "moderada"),
    income_stability:             "stable",
    net_worth:                    liquidNW * 2,  // estimación razonable
    liquid_net_worth:             liquidNW,
    max_acceptable_drawdown_pct:  Math.min(Math.max(risk * 3, 5), 50),
    jurisdiction:                 idemoStr("idemo-jurisdiction", "AR"),
    preferred_currency:           idemoStr("idemo-currency", "USD"),
    investment_objective:         idemoStr("idemo-objective", "balanced"),
    annual_income_usd:            idemoNumber("idemo-income", 80000),
    open_investment_goal:         idemoStr("idemo-open-goal", "") || null,
    open_risk_reaction:           idemoStr("idemo-open-reaction", "") || null,
    open_past_experience:         idemoStr("idemo-open-experience", "") || null,
    open_concerns:                idemoStr("idemo-open-concerns", "") || null,
  };
}

function idemoBuildPrefsPayload() {
  const types = idemoStr("idemo-pref-types", "")
    .split(",").map(s => s.trim()).filter(Boolean);
  const hardDollar = idemoStr("idemo-pref-hard", "true") === "true";
  const structured = {
    allowed_instrument_types: types.length ? types
      : ["CORPORATE_BOND", "SOVEREIGN_BOND", "ETF", "STOCK", "CEDEAR", "MUTUAL_FUND", "MONEY_MARKET"],
  };
  if (hardDollar) {
    structured.require_hard_dollar = true;
  }
  return { source: "manual", structured_preferences: structured };
}

// ── Progress checklist + status ───────────────────────────────────────

function idemoStepState(key) {
  return window.idemoState.stepStatus[key] || "pending";
}
function idemoSetStep(key, status) {
  window.idemoState.stepStatus[key] = status;
  idemoRenderProgress();
}

function idemoRenderProgress() {
  const target = document.getElementById("idemo-progress");
  if (!target) return;
  const rows = IDEMO_STEPS.map((s, idx) => {
    const st = idemoStepState(s.key);
    let pill;
    if (st === "done") pill = '<span class="pill pill-green">listo</span>';
    else if (st === "active") pill = '<span class="pill pill-blue">en curso…</span>';
    else if (st === "error") pill = '<span class="pill pill-red">error</span>';
    else if (st === "skipped") pill = '<span class="pill pill-orange">saltado</span>';
    else pill = '<span class="pill pill-grey">pendiente</span>';
    return `<div class="idemo-step-row" data-state="${st}">
      <div class="idemo-step-circle">${idx + 1}</div>
      <div class="idemo-step-text">${escapeHTML(s.label)}</div>
      <div class="idemo-step-pill">${pill}</div>
    </div>`;
  }).join("");
  target.innerHTML = rows;
}

function idemoStatus(kind, html) {
  // kind: ok | info | warn | error
  const target = document.getElementById("idemo-status");
  if (!target) return;
  const cls = kind === "ok" ? "msg-success"
    : kind === "warn" ? "msg-error"   // amber-ish: reuse error styling (border) + custom inline
    : kind === "error" ? "msg-error"
    : "msg-info";
  target.innerHTML = `<div class="msg ${cls}">${html}</div>`;
}

function idemoExtractTimestamp() {
  // ISO-ish short timestamp para nombrar el case sin colisionar.
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\..*/, "");
}

// ── STEP 1 — preparar caso demo ───────────────────────────────────────

async function idemoPrepareCase() {
  idemoSetStep("prepare", "active");
  const investorName = idemoStr("idemo-name", "Inversor demo");
  const title = `Demo perfil inversor — ${investorName}`;
  const body = {
    firm_id:         IDEMO_FIRM_ID,
    client_id:       IDEMO_CLIENT_ID,
    lead_advisor_id: IDEMO_ADVISOR_ID,
    title:           title,
  };
  const res = await idemoApi("POST", "/cases", body);
  if (!res.ok) {
    idemoSetStep("prepare", "error");
    if (res.status === 422 && /not found/i.test(res.detail || "")) {
      idemoStatus("error",
        `<strong>Falta el seed demo.</strong> Corré <code>python scripts/bootstrap_local_demo.py</code> en la terminal y volvé a intentar. ` +
        `<br><span style="font-size:11px;opacity:.8;">Detalle: ${escapeHTML(res.detail)}</span>`);
    } else if (res.networkError) {
      idemoStatus("error",
        `<strong>El backend no responde.</strong> Levantá uvicorn: <code>python -m uvicorn risk_first_advisory.api_layer.main:app --reload</code>`);
    } else {
      idemoStatus("error",
        `<strong>No se pudo crear el caso.</strong> ${escapeHTML(res.detail || "")} ` +
        `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    }
    return false;
  }
  window.idemoState.caseId = res.json.case_id;
  idemoSetStep("prepare", "done");
  idemoStatus("ok",
    `<strong>Caso demo listo</strong> · "${escapeHTML(title)}" creado para ` +
    `el cliente <code>${escapeHTML(IDEMO_CLIENT_ID)}</code>. Internamente: ` +
    `<code>${escapeHTML(res.json.case_id)}</code>.`);
  return true;
}

// ── STEP 2 — enviar KYC ────────────────────────────────────────────────

async function idemoSubmitKyc() {
  if (!window.idemoState.caseId) {
    idemoStatus("warn", "Primero hacé clic en <strong>1. Preparar caso demo</strong>.");
    return false;
  }
  idemoSetStep("kyc", "active");
  const payload = idemoBuildKycPayload();
  const res = await idemoApi("POST", `/cases/${encodeURIComponent(window.idemoState.caseId)}/kyc`, payload);
  if (!res.ok) {
    idemoSetStep("kyc", "error");
    idemoStatus("error",
      `<strong>No se pudo enviar el KYC.</strong> ${escapeHTML(res.detail || "")} ` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.kycSubmissionId = res.json.kyc_submission_id;
  idemoSetStep("kyc", "done");
  idemoStatus("ok",
    `<strong>KYC enviado</strong> · perfil del inversor cargado en el caso. ` +
    `Versión <strong>${res.json.version}</strong>.`);
  return true;
}

// ── STEP 3 — análisis de perfil con IA ────────────────────────────────

async function idemoRunAiProfile() {
  if (!window.idemoState.caseId) {
    idemoStatus("warn", "Primero preparar caso + KYC.");
    return false;
  }
  if (!window.idemoState.kycSubmissionId) {
    idemoStatus("warn", "Primero hacé clic en <strong>2. Enviar perfil / KYC</strong>.");
    return false;
  }
  idemoSetStep("ai", "active");
  const res = await idemoApi(
    "POST",
    `/cases/${encodeURIComponent(window.idemoState.caseId)}/ai/profile-analysis`,
    { analysis_type: "initial" },
  );
  if (!res.ok) {
    // Detección de "OpenAI no configurado" (HTTP 400 típico) → saltar amigablemente.
    const isOpenAiMissing = res.status === 400 && /openai/i.test(res.detail || "");
    if (isOpenAiMissing || res.status === 400) {
      window.idemoState.aiSkipped = true;
      window.idemoState.aiProposedProfile = "moderado";  // default razonable
      idemoSetStep("ai", "skipped");
      idemoStatus("info",
        `<strong>Paso saltado — OpenAI no configurado.</strong> ` +
        `La demo local no tiene <code>OPENAI_API_KEY</code>. ` +
        `Podés seguir con la demo (se usará "moderado" como perfil sugerido), ` +
        `o configurar la clave y reiniciar el backend para probar el análisis real. ` +
        `Alternativa: el smoke check (<code>python scripts/run_case_workflow_smoke_check.py</code>) usa un mock determinístico de OpenAI.`);
      return true;  // No bloqueamos el flujo guiado.
    }
    idemoSetStep("ai", "error");
    idemoStatus("error",
      `<strong>El análisis IA falló.</strong> ${escapeHTML(res.detail || "")} ` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.aiAnalysisId = res.json.analysis_id;
  window.idemoState.aiProposedProfile = res.json.preliminary_profile || "moderado";
  idemoSetStep("ai", "done");
  const contraN = Array.isArray(res.json.contradictions) ? res.json.contradictions.length : 0;
  const fuN = Array.isArray(res.json.follow_up_questions) ? res.json.follow_up_questions.length : 0;
  idemoStatus("ok",
    `<strong>Análisis IA listo.</strong> Perfil preliminar sugerido por la IA: ` +
    `<code>${escapeHTML(window.idemoState.aiProposedProfile)}</code> · ` +
    `${contraN} contradicción(es) detectada(s) · ${fuN} pregunta(s) de seguimiento. ` +
    `<em>Recordá: la IA propone, el asesor decide en el paso 4.</em>`);
  return true;
}

// ── STEP 4 — aprobar perfil como asesor ───────────────────────────────

async function idemoApproveProfile() {
  if (!window.idemoState.caseId || !window.idemoState.kycSubmissionId) {
    idemoStatus("warn", "Primero preparar caso + KYC.");
    return false;
  }
  idemoSetStep("approve", "active");
  const investorName = idemoStr("idemo-name", "Inversor demo");
  const body = {
    decision:  "approve",
    rationale: `El asesor revisó el perfil del inversor "${investorName}" y aprueba el perfil propuesto para esta demo.`,
    source:    "manual",
  };
  // Si tenemos analysis_id, dejamos que el backend derive el proposed_profile.
  // Si no (caso AI saltado), forzamos proposed_profile explícito.
  if (window.idemoState.aiAnalysisId) {
    body.ai_profile_analysis_id = window.idemoState.aiAnalysisId;
  } else {
    body.proposed_profile = window.idemoState.aiProposedProfile || "moderado";
  }
  const res = await idemoApi("POST", `/cases/${encodeURIComponent(window.idemoState.caseId)}/profile-approval`, body);
  if (!res.ok) {
    idemoSetStep("approve", "error");
    idemoStatus("error",
      `<strong>No se pudo aprobar el perfil.</strong> ${escapeHTML(res.detail || "")} ` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.approvalId = res.json.approval_id;
  window.idemoState.approvedProfile = res.json.approved_profile;
  idemoSetStep("approve", "done");
  idemoStatus("ok",
    `<strong>Perfil aprobado por el asesor.</strong> ` +
    `Perfil aprobado: <code>${escapeHTML(res.json.approved_profile || "—")}</code>. ` +
    `Decisión: <code>${escapeHTML(res.json.decision)}</code>. ` +
    `Esta decisión queda en la cadena de auditoría.`);
  return true;
}

// ── STEP 5 — generar propuesta de cartera ─────────────────────────────
// Internamente: investment-preferences → universe-filter → portfolio-proposal.

async function idemoGenerateProposal() {
  if (!window.idemoState.caseId || !window.idemoState.approvalId) {
    idemoStatus("warn", "Primero ejecutar pasos 1–4 (caso + KYC + perfil aprobado).");
    return false;
  }
  idemoSetStep("propose", "active");

  // 5a. Preferencias
  const prefsBody = idemoBuildPrefsPayload();
  const r1 = await idemoApi("POST",
    `/cases/${encodeURIComponent(window.idemoState.caseId)}/investment-preferences`,
    prefsBody);
  if (!r1.ok) {
    idemoSetStep("propose", "error");
    idemoStatus("error",
      `<strong>No se pudo registrar las preferencias.</strong> ${escapeHTML(r1.detail || "")} ` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${r1.status}</span>`);
    return false;
  }
  window.idemoState.preferenceId = r1.json.preference_id;

  // 5b. Filtro del universo
  const r2 = await idemoApi("POST",
    `/cases/${encodeURIComponent(window.idemoState.caseId)}/universe-filter`,
    { source_universe: "sample_instrument_universe.csv" });
  if (!r2.ok) {
    idemoSetStep("propose", "error");
    idemoStatus("error",
      `<strong>No se pudo filtrar el universo.</strong> ${escapeHTML(r2.detail || "")} ` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${r2.status}</span>`);
    return false;
  }
  window.idemoState.filterRunId = r2.json.filter_run_id;
  const eligibleN = r2.json.eligible_count;
  const excludedN = r2.json.excluded_count;

  // 5c. Propuesta
  const r3 = await idemoApi("POST",
    `/cases/${encodeURIComponent(window.idemoState.caseId)}/portfolio-proposal`,
    { variant_policy: "standard" });
  if (!r3.ok) {
    idemoSetStep("propose", "error");
    idemoStatus("error",
      `<strong>No se pudo generar la propuesta.</strong> ${escapeHTML(r3.detail || "")} ` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${r3.status}</span>`);
    return false;
  }
  window.idemoState.proposalId = r3.json.proposal_id;
  window.idemoState.candidates = Array.isArray(r3.json.candidates) ? r3.json.candidates : [];

  if (r3.json.status !== "completed") {
    idemoSetStep("propose", "error");
    idemoStatus("error",
      `<strong>La propuesta no está completa.</strong> Estado: <code>${escapeHTML(r3.json.status)}</code>. ` +
      `Avisos: ${(r3.json.warnings || []).map(escapeHTML).join("; ") || "—"}.`);
    return false;
  }
  idemoSetStep("propose", "done");
  idemoStatus("ok",
    `<strong>Propuesta de cartera generada.</strong> ` +
    `Universo filtrado: <strong>${eligibleN}</strong> instrumentos elegibles (${excludedN} excluidos). ` +
    `Variantes propuestas: <strong>${window.idemoState.candidates.length}</strong>.`);
  idemoRenderPortfolioComparison(window.idemoState.candidates);
  return true;
}

// ── STEP 6 — seleccionar cartera ──────────────────────────────────────
// Estrategia: preferimos un candidate que NO requiera override (más simple
// para la demo guiada). Si solo hay candidates con override, también lo
// soportamos firmando el override automáticamente con un rationale demo.

function idemoPickPreferredVariant(candidates) {
  // 1) sin override + variant=BALANCED preferido
  for (const v of ["BALANCED", "DEFENSIVE", "GROWTH"]) {
    const c = candidates.find(c => c.variant === v && !(c.metadata && c.metadata.requires_advisor_override));
    if (c) return { candidate: c, requiresOverride: false };
  }
  // 2) cualquiera sin override
  const free = candidates.find(c => !(c.metadata && c.metadata.requires_advisor_override));
  if (free) return { candidate: free, requiresOverride: false };
  // 3) el primero (requiere override)
  return { candidate: candidates[0], requiresOverride: true };
}

async function idemoSelectPortfolio() {
  if (!window.idemoState.proposalId) {
    idemoStatus("warn", "Primero generá la propuesta (paso 5).");
    return false;
  }
  if (!window.idemoState.candidates.length) {
    idemoStatus("error", "No hay variantes para seleccionar.");
    return false;
  }
  idemoSetStep("select", "active");
  const { candidate, requiresOverride } = idemoPickPreferredVariant(window.idemoState.candidates);
  const variant = candidate.variant;

  // Si requiere override, firmamos primero con un rationale demo.
  let overrideId = null;
  if (requiresOverride) {
    const meta = candidate.metadata || {};
    const ovrBody = {
      candidate_variant:    variant,
      decision:             "approve",
      reason_codes:         (meta.reason_codes && meta.reason_codes.length)
                              ? meta.reason_codes
                              : ["PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"],
      exceeded_constraints: (meta.exceeded_constraints && meta.exceeded_constraints.length)
                              ? meta.exceeded_constraints
                              : ["max_volatility"],
      rationale:            `Demo: el asesor firma el override de la variante ${variant} para esta demostración.`,
      source:               "manual",
    };
    const rO = await idemoApi("POST",
      `/cases/${encodeURIComponent(window.idemoState.caseId)}/override-approval`,
      ovrBody);
    if (!rO.ok) {
      idemoSetStep("select", "error");
      idemoStatus("error",
        `<strong>No se pudo firmar el override.</strong> ${escapeHTML(rO.detail || "")} ` +
        `<br><span style="font-size:11px;opacity:.8;">HTTP ${rO.status}</span>`);
      return false;
    }
    overrideId = rO.json.override_approval_id;
    window.idemoState.overrideApprovalId = overrideId;
  }

  const selBody = {
    selected_variant: variant,
    rationale:        `El asesor selecciona la variante ${variant} como recomendación final para el cliente.`,
    source:           "manual",
  };
  if (overrideId) selBody.override_approval_id = overrideId;

  const res = await idemoApi("POST",
    `/cases/${encodeURIComponent(window.idemoState.caseId)}/portfolio-selection`,
    selBody);
  if (!res.ok) {
    idemoSetStep("select", "error");
    idemoStatus("error",
      `<strong>No se pudo seleccionar la cartera.</strong> ${escapeHTML(res.detail || "")} ` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.selectionId = res.json.selection_id;
  window.idemoState.selectedVariant = res.json.selected_variant;
  window.idemoState.selectedCandidate = res.json.selected_candidate;
  idemoSetStep("select", "done");
  idemoStatus("ok",
    `<strong>Cartera seleccionada por el asesor.</strong> ` +
    `Variante final: <code>${escapeHTML(variant)}</code>` +
    (requiresOverride ? ` <span class="pill pill-orange">con firma de override</span>` : "") + ".");
  idemoRenderSelectedPortfolio(res.json);
  return true;
}

// ── STEP 7 — generar reporte ──────────────────────────────────────────

async function idemoGenerateReport() {
  if (!window.idemoState.selectionId) {
    idemoStatus("warn", "Primero seleccioná la cartera (paso 6).");
    return false;
  }
  idemoSetStep("report", "active");
  const res = await idemoApi("POST",
    `/cases/${encodeURIComponent(window.idemoState.caseId)}/reports`,
    { report_type: "portfolio_recommendation", status: "draft" });
  if (!res.ok) {
    idemoSetStep("report", "error");
    idemoStatus("error",
      `<strong>No se pudo generar el reporte.</strong> ${escapeHTML(res.detail || "")} ` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.reportId = res.json.report_id;
  window.idemoState.reportMarkdown = res.json.markdown || "";
  idemoSetStep("report", "done");
  idemoStatus("ok",
    `<strong>Reporte generado.</strong> ` +
    `<code>${escapeHTML(res.json.report_id)}</code> · ` +
    `versión <strong>${res.json.version}</strong> · estado <code>${escapeHTML(res.json.status)}</code>. ` +
    `El reporte incluye la composición exacta de la cartera y la tabla comparativa de variantes.`);
  idemoRenderReportPreview(res.json);
  return true;
}

// ── STEP 8 — verificar auditoría (usa token de compliance) ────────────

async function idemoVerifyAudit() {
  if (!window.idemoState.caseId) {
    idemoStatus("warn", "Primero preparar el caso (paso 1).");
    return false;
  }
  idemoSetStep("audit", "active");
  const res = await idemoApi(
    "GET",
    `/cases/${encodeURIComponent(window.idemoState.caseId)}/audit/verify`,
    null,
    IDEMO_COMPLIANCE_TOKEN,
  );
  if (!res.ok) {
    idemoSetStep("audit", "error");
    idemoStatus("error",
      `<strong>No se pudo verificar la auditoría.</strong> ${escapeHTML(res.detail || "")} ` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.auditIntact = !!res.json.is_intact;
  window.idemoState.auditTotalEvents = res.json.total_events;
  idemoSetStep("audit", "done");
  idemoStatus("ok",
    `<strong>Auditoría verificada.</strong> ` +
    (res.json.is_intact
      ? `Cadena <strong>intacta</strong> sobre ${res.json.total_events} evento(s).`
      : `Cadena <strong>rota</strong> en el evento ${res.json.first_broken_sequence}.`));
  idemoRenderAudit(res.json);
  return true;
}

// ── DEMO GUIADA: corre 1–8 en cadena ──────────────────────────────────

async function idemoRunGuidedDemo() {
  const btn = document.getElementById("idemo-btn-guided");
  if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>Corriendo demo guiada…`; }
  try {
    idemoReset();
    idemoStatus("info", "<strong>Demo guiada en curso…</strong> Cada paso queda registrado en la cadena de auditoría.");

    const seq = [
      idemoPrepareCase,
      idemoSubmitKyc,
      idemoRunAiProfile,    // si falla por OpenAI, queda 'skipped' y devuelve true para continuar
      idemoApproveProfile,
      idemoGenerateProposal,
      idemoSelectPortfolio,
      idemoGenerateReport,
      idemoVerifyAudit,
    ];

    for (const step of seq) {
      // Pequeña pausa para que el visitante vea el progress pintándose.
      await new Promise(r => setTimeout(r, 120));
      const ok = await step();
      if (!ok) {
        idemoStatus("error",
          `<strong>La demo guiada se detuvo.</strong> Revisá el mensaje del último paso y volvé a intentar manualmente desde el botón correspondiente. ` +
          `El resto del flujo queda disponible: solo hay que hacer clic en los pasos siguientes.`);
        return;
      }
    }
    idemoStatus("ok",
      `<strong>Demo guiada completa.</strong> El caso recorrió los 8 pasos del workflow: ` +
      `perfil → análisis → aprobación → propuesta → selección → reporte → auditoría. ` +
      `Para ver detalles técnicos, abrí el <a href="#case-workbench">Workbench paso a paso</a>.`);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = "▶ Ejecutar demo guiada (8 pasos)"; }
  }
}

// ── Renderers ─────────────────────────────────────────────────────────

function idemoRenderPortfolioComparison(candidates) {
  const block = document.getElementById("idemo-portfolio-block");
  const target = document.getElementById("idemo-portfolio-result");
  if (!block || !target) return;
  block.style.display = "block";

  if (!candidates.length) {
    target.innerHTML = `<div class="msg msg-info">Sin variantes generadas.</div>`;
    return;
  }

  // Tabla compacta de comparación
  const rows = candidates.map(c => {
    const meta = c.metadata || {};
    const ovr = meta.requires_advisor_override
      ? '<span class="pill pill-orange">requiere override</span>'
      : '<span class="pill pill-green">dentro del presupuesto</span>';
    const n = (typeof c.holdings_count === "number") ? c.holdings_count
      : (Array.isArray(c.holdings) ? c.holdings.length
        : (Array.isArray(c.weights) ? c.weights.length : 0));
    return `<tr>
      <td style="padding:10px 12px;"><strong>${escapeHTML(c.variant || "?")}</strong></td>
      <td style="padding:10px 12px;font-variant-numeric:tabular-nums;text-align:right;">${c.expected_return_annual !== undefined ? (c.expected_return_annual * 100).toFixed(2) + "%" : "—"}</td>
      <td style="padding:10px 12px;font-variant-numeric:tabular-nums;text-align:right;">${c.volatility_annual !== undefined ? (c.volatility_annual * 100).toFixed(2) + "%" : "—"}</td>
      <td style="padding:10px 12px;text-align:right;font-variant-numeric:tabular-nums;">${n}</td>
      <td style="padding:10px 12px;">${ovr}</td>
    </tr>`;
  }).join("");
  const compareTable = `
    <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;margin-bottom:14px;">
      <thead><tr style="background:#f4f6fa;">
        <th style="padding:10px 12px;font-size:11px;text-align:left;">Variante</th>
        <th style="padding:10px 12px;font-size:11px;text-align:right;">Retorno esperado</th>
        <th style="padding:10px 12px;font-size:11px;text-align:right;">Volatilidad</th>
        <th style="padding:10px 12px;font-size:11px;text-align:right;"># Instrumentos</th>
        <th style="padding:10px 12px;font-size:11px;text-align:left;">Presupuesto de riesgo</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;

  // Cards detalladas por variante (reusa cwRenderCandidateCard del Workbench)
  const cards = candidates.map(c => {
    if (typeof cwRenderCandidateCard === "function") {
      return cwRenderCandidateCard(c);
    }
    // Fallback simple si el renderer del Workbench no está cargado.
    const holdings = (typeof cwNormalizeHoldings === "function")
      ? cwNormalizeHoldings(c) : [];
    const table = (typeof cwRenderHoldingsTable === "function")
      ? cwRenderHoldingsTable(holdings, true)
      : `<pre class="json-block">${escapeHTML(formatJSON(c.holdings || c.weights || []))}</pre>`;
    return `<div class="portfolio-card"><div class="portfolio-card-header"><span class="variant-name">${escapeHTML(c.variant || "?")}</span></div><div class="portfolio-card-body">${table}</div></div>`;
  }).join("");

  target.innerHTML = compareTable + cards;
}

function idemoRenderSelectedPortfolio(selectionResp) {
  const block = document.getElementById("idemo-selection-block");
  const target = document.getElementById("idemo-selection-result");
  if (!block || !target) return;
  block.style.display = "block";

  const cand = selectionResp.selected_candidate || {};
  const meta = cand.metadata || {};
  const ovr = meta.requires_advisor_override
    ? '<span class="pill pill-orange">firmado con override</span>'
    : '<span class="pill pill-green">dentro del presupuesto de riesgo</span>';
  const holdings = (typeof cwNormalizeHoldings === "function")
    ? cwNormalizeHoldings(cand) : [];
  const table = (typeof cwRenderHoldingsTable === "function")
    ? cwRenderHoldingsTable(holdings, true)
    : `<pre class="json-block">${escapeHTML(formatJSON(holdings))}</pre>`;
  const eret = (cand.expected_return_annual !== undefined)
    ? (cand.expected_return_annual * 100).toFixed(2) + "%" : "—";
  const vol = (cand.volatility_annual !== undefined)
    ? (cand.volatility_annual * 100).toFixed(2) + "%" : "—";

  target.innerHTML = `
    <div class="portfolio-card">
      <div class="portfolio-card-header">
        <span class="variant-name">${escapeHTML(selectionResp.selected_variant || "?")}</span>
        ${ovr}
        <span style="margin-left:auto;font-size:11px;color:var(--rf-text-muted);">
          Retorno esperado <strong>${eret}</strong> · Volatilidad <strong>${vol}</strong> · ${holdings.length} instrumento(s)
        </span>
      </div>
      <div class="portfolio-card-body">
        ${table}
      </div>
    </div>`;
}

function idemoRenderReportPreview(reportResp) {
  const block = document.getElementById("idemo-report-block");
  const target = document.getElementById("idemo-report-result");
  if (!block || !target) return;
  block.style.display = "block";

  const md = reportResp.markdown || "";
  const hasComp = md.includes("Composición de la cartera seleccionada");
  const hasVar = md.includes("Comparación de variantes generadas");
  const pills = [
    `<span class="pill pill-blue">${md.length} caracteres</span>`,
    hasComp ? '<span class="pill pill-green">incluye composición</span>' : "",
    hasVar ? '<span class="pill pill-violet">incluye comparación de variantes</span>' : "",
  ].filter(Boolean).join(" ");

  target.innerHTML = `
    <div class="msg msg-success" style="margin-bottom:10px;">
      <strong>Reporte listo para revisión del asesor.</strong> ${pills}
    </div>
    <details open>
      <summary style="cursor:pointer;font-size:12px;color:var(--rf-navy-700);font-weight:600;">
        Vista previa del reporte (Markdown)
      </summary>
      <pre style="background:#fff;border:1px solid #dde2ea;border-radius:8px;padding:14px;margin-top:6px;font-size:11.5px;line-height:1.5;max-height:420px;overflow:auto;white-space:pre-wrap;font-family:ui-monospace,'JetBrains Mono',Menlo,Consolas,monospace;">${escapeHTML(md)}</pre>
    </details>
    ${(typeof rfaJsonDetails === "function") ? rfaJsonDetails(reportResp.metadata || {}, "Metadata del reporte (técnico)") : ""}
  `;
}

function idemoRenderAudit(verifyResp) {
  const block = document.getElementById("idemo-audit-block");
  const target = document.getElementById("idemo-audit-result");
  if (!block || !target) return;
  block.style.display = "block";

  const intact = !!verifyResp.is_intact;
  const pill = intact
    ? '<span class="pill pill-green">cadena intacta</span>'
    : '<span class="pill pill-red">cadena rota</span>';
  const detail = intact
    ? `Las <strong>${verifyResp.total_events || 0}</strong> decisiones del caso quedaron registradas y la cadena SHA-256 verifica correctamente. ` +
      `Compliance puede pedir la <a href="#audit-anchor">snapshot completa de auditoría</a> en el Workbench.`
    : `<strong>Atención:</strong> la cadena se rompió en el evento ${verifyResp.first_broken_sequence}. ` +
      `Mensaje: ${escapeHTML(verifyResp.message || "—")}.`;

  target.innerHTML = `
    <div class="msg ${intact ? 'msg-success' : 'msg-error'}">
      ${pill} · ${detail}
    </div>
    ${(typeof rfaJsonDetails === "function") ? rfaJsonDetails(verifyResp, "Detalles técnicos · respuesta de la verificación") : ""}
  `;
}

// ── Init: render checklist al cargar ──────────────────────────────────

(function () {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", idemoRenderProgress);
  } else {
    idemoRenderProgress();
  }
})();
