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
    overrideApprovalId: null,
    stepStatus: {},
  });
  // Limpiar inline result panels y resetear pill+data-state de cada step card.
  for (const s of IDEMO_STEPS) {
    const result = document.getElementById(`idemo-step-${s.key}-result`);
    if (result) result.innerHTML = "";
    const pill = document.getElementById(`idemo-step-${s.key}-pill`);
    if (pill) pill.innerHTML = '<span class="pill pill-grey">pendiente</span>';
    const card = document.getElementById(`idemo-step-${s.key}`);
    if (card) card.setAttribute("data-state", "pending");
  }
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

// ── Per-step state + inline rendering ─────────────────────────────────
// Cada step tiene su propia card con id="idemo-step-{key}", su pill
// id="idemo-step-{key}-pill" y su panel inline id="idemo-step-{key}-result".
// El estado vive en data-state del wrapper para que CSS lo coloree solo.

function idemoStepState(key) {
  return window.idemoState.stepStatus[key] || "pending";
}

function idemoSetStep(key, status) {
  window.idemoState.stepStatus[key] = status;
  // Pintar el wrapper (color del borde left vía data-state)
  const card = document.getElementById(`idemo-step-${key}`);
  if (card) card.setAttribute("data-state", status);
  // Pintar la pill
  const pill = document.getElementById(`idemo-step-${key}-pill`);
  if (pill) {
    let html;
    if (status === "done")         html = '<span class="pill pill-green">listo</span>';
    else if (status === "active")  html = '<span class="pill pill-blue">en curso…</span>';
    else if (status === "error")   html = '<span class="pill pill-red">error</span>';
    else if (status === "skipped") html = '<span class="pill pill-orange">saltado</span>';
    else                           html = '<span class="pill pill-grey">pendiente</span>';
    pill.innerHTML = html;
  }
  // Auto-scroll suave a la step que se acaba de poner activa, para que el
  // visitante vea el spinner sin tener que scrollear manualmente.
  if (status === "active" && card) {
    card.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

// Render inline en el panel de resultado de un paso.
// kind: ok | info | warn | error
function idemoStepResult(key, kind, html) {
  const target = document.getElementById(`idemo-step-${key}-result`);
  if (!target) return;
  const cls = kind === "ok" ? "msg-success"
    : kind === "warn"  ? "msg-info"   // info-tinted, no rojo
    : kind === "error" ? "msg-error"
    : "msg-info";
  target.innerHTML = `<div class="msg ${cls}">${html}</div>`;
}

// Mismo que idemoStepResult pero permite agregar HTML extra (tablas, cards)
// debajo del banner. Reutilizado por proposal/selection/report/audit.
function idemoStepResultRich(key, kind, bannerHtml, extraHtml) {
  const target = document.getElementById(`idemo-step-${key}-result`);
  if (!target) return;
  const cls = kind === "ok" ? "msg-success"
    : kind === "warn"  ? "msg-info"
    : kind === "error" ? "msg-error"
    : "msg-info";
  target.innerHTML = `<div class="msg ${cls}">${bannerHtml}</div>${extraHtml || ""}`;
}

// Compat shim: investor-demo.js previo usaba idemoStatus/idemoRenderProgress.
// Los dejamos como no-ops para no romper si quedó alguna referencia colgada
// (el modo guiado, por ejemplo, llamaba a idemoStatus al inicio).
function idemoRenderProgress() { /* no-op: las pills viven por step ahora */ }
function idemoStatus(/* kind, html */) { /* no-op: cada step renderea inline */ }

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
      idemoStepResult("prepare", "error",
        `<strong>Falta el seed demo.</strong> Corré <code>python scripts/bootstrap_local_demo.py</code> en la terminal y volvé a intentar.` +
        `<br><span style="font-size:11px;opacity:.8;">Detalle: ${escapeHTML(res.detail)}</span>`);
    } else if (res.networkError) {
      idemoStepResult("prepare", "error",
        `<strong>El backend no responde.</strong> Levantá uvicorn: <code>python -m uvicorn risk_first_advisory.api_layer.main:app --reload</code>`);
    } else {
      idemoStepResult("prepare", "error",
        `<strong>No se pudo crear el caso.</strong> ${escapeHTML(res.detail || "")}` +
        `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    }
    return false;
  }
  window.idemoState.caseId = res.json.case_id;
  idemoSetStep("prepare", "done");
  idemoStepResult("prepare", "ok",
    `<strong>Caso creado.</strong> Título: "${escapeHTML(title)}" · cliente del seed <code>${escapeHTML(IDEMO_CLIENT_ID)}</code>. ` +
    `ID interno del caso: <code>${escapeHTML(res.json.case_id)}</code>. ` +
    `Cualquier decisión que el asesor tome a partir de acá queda atada a este caso.`);
  return true;
}

// ── STEP 2 — enviar KYC ────────────────────────────────────────────────

async function idemoSubmitKyc() {
  if (!window.idemoState.caseId) {
    idemoStepResult("kyc", "warn", "Primero hacé clic en <strong>1. Preparar caso del inversor</strong>.");
    return false;
  }
  idemoSetStep("kyc", "active");
  const payload = idemoBuildKycPayload();
  const res = await idemoApi("POST", `/cases/${encodeURIComponent(window.idemoState.caseId)}/kyc`, payload);
  if (!res.ok) {
    idemoSetStep("kyc", "error");
    idemoStepResult("kyc", "error",
      `<strong>No se pudo enviar el KYC.</strong> ${escapeHTML(res.detail || "")}` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.kycSubmissionId = res.json.kyc_submission_id;
  idemoSetStep("kyc", "done");
  idemoStepResult("kyc", "ok",
    `<strong>KYC enviado.</strong> Perfil del inversor guardado en el caso como <em>submission</em> versión ` +
    `<strong>${res.json.version}</strong>. ` +
    `Cada nuevo envío incrementaría esta versión y quedaría en el audit trail (no se pisa el anterior).`);
  return true;
}

// ── STEP 3 — análisis de perfil con IA ────────────────────────────────

// Card Risk Gap: flag de inconsistencia declarado-vs-respuestas.
// Guard: si no hay risk_gap (respuesta vieja / null), devuelve "" y no se renderiza.
// Jerarquía: comparación primero, honesty line como caption, preguntas como cierre.
// Tono: el escenario aporta info; no se culpa al cliente. Sin rojo ni ⚠.
function idemoRiskGapCardHTML(rg) {
  if (!rg || !rg.gap_level) return "";
  const levelLabel = { low: "Bajo", medium: "Medio", high: "Alto" }[rg.gap_level] || rg.gap_level;
  // Semántica de color: neutral/ámbar, nunca rojo (no es un error del asesor).
  const levelColor = { low: "#3a7", medium: "#c90", high: "#c60" }[rg.gap_level] || "#888";
  const aligned = rg.gap_level === "low";
  const stress = rg.stress_signal
    ? `<div style="margin:6px 0;"><span style="opacity:.7;">Señal del cliente:</span> ${escapeHTML(rg.stress_signal)}</div>`
    : "";
  const questions = Array.isArray(rg.confirmation_questions) && rg.confirmation_questions.length
    ? `<div style="margin-top:10px;"><strong>Tus próximas preguntas para el cliente</strong><ul style="margin:4px 0 0 0;">` +
      rg.confirmation_questions.map((q) => `<li>${escapeHTML(q)}</li>`).join("") + `</ul></div>`
    : "";
  return (
    `<div class="idemo-riskgap" style="margin-top:12px;border:1px solid #ddd;border-left:4px solid ${levelColor};border-radius:6px;padding:12px;background:#fafafa;">` +
      `<div style="font-weight:600;">Risk Gap` +
        ` <span style="font-weight:500;color:${levelColor};">· inconsistencia ${escapeHTML(levelLabel)}</span></div>` +
      `<div style="font-size:11px;opacity:.75;margin:2px 0 8px 0;">La IA marca una inconsistencia. Vos confirmás el perfil con el cliente. Esto NO es una medición del perfil conductual.</div>` +
      `<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:6px;">` +
        `<div><span style="opacity:.7;">Declarado:</span> <code>${escapeHTML(rg.declared_profile || "—")}</code></div>` +
        (aligned
          ? `<div style="color:#3a7;">Sin inconsistencia que confirmar</div>`
          : `<div style="color:${levelColor};">Revisar con el cliente</div>`) +
      `</div>` +
      stress +
      `<div style="margin:6px 0;font-size:13px;">${escapeHTML(rg.gap_explanation || "")}</div>` +
      questions +
    `</div>`
  );
}

async function idemoRunAiProfile() {
  if (!window.idemoState.caseId || !window.idemoState.kycSubmissionId) {
    idemoStepResult("ai", "warn", "Primero ejecutá los pasos 1 (preparar caso) y 2 (enviar KYC).");
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
      idemoStepResult("ai", "warn",
        `<strong>Paso saltado — OpenAI no configurado.</strong> ` +
        `La demo local no tiene <code>OPENAI_API_KEY</code>. ` +
        `Podés seguir con la demo (vamos a usar "moderado" como perfil sugerido para el paso 4), ` +
        `o configurar la clave y reiniciar el backend para probar el análisis real. ` +
        `Para ver el <strong>Risk Gap</strong> sin clave: arrancá el backend con <code>RFA_DEMO_MODE=1</code> ` +
        `(cliente determinístico). Alternativa: el smoke check ` +
        `(<code>python scripts/run_case_workflow_smoke_check.py</code>) usa un mock determinístico de OpenAI.`);
      return true;  // No bloqueamos el flujo.
    }
    idemoSetStep("ai", "error");
    idemoStepResult("ai", "error",
      `<strong>El análisis de la IA falló.</strong> ${escapeHTML(res.detail || "")}` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.aiAnalysisId = res.json.analysis_id;
  window.idemoState.aiProposedProfile = res.json.preliminary_profile || "moderado";
  idemoSetStep("ai", "done");
  // Las contradicciones / follow-ups del analisis case-scoped viven en .result,
  // no top-level (eso es el schema legacy). Leer mal contaba siempre 0.
  const aiResult = res.json.result || {};
  const contraN = Array.isArray(aiResult.contradictions) ? aiResult.contradictions.length : 0;
  const fuN = Array.isArray(aiResult.follow_up_questions) ? aiResult.follow_up_questions.length : 0;
  idemoStepResult("ai", "ok",
    `<strong>Análisis listo.</strong> Perfil preliminar sugerido por la IA: ` +
    `<code>${escapeHTML(window.idemoState.aiProposedProfile)}</code> · ` +
    `${contraN} contradicción(es) detectada(s) · ${fuN} pregunta(s) de seguimiento. ` +
    `<em>Recordá: la IA propone, el asesor decide en el paso 4.</em>` +
    idemoRiskGapCardHTML(res.json.risk_gap));
  return true;
}

// ── STEP 4 — aprobar perfil como asesor ───────────────────────────────

async function idemoApproveProfile() {
  if (!window.idemoState.caseId || !window.idemoState.kycSubmissionId) {
    idemoStepResult("approve", "warn", "Primero ejecutá los pasos 1 (preparar caso) y 2 (KYC).");
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
    idemoStepResult("approve", "error",
      `<strong>No se pudo aprobar el perfil.</strong> ${escapeHTML(res.detail || "")}` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.approvalId = res.json.approval_id;
  window.idemoState.approvedProfile = res.json.approved_profile;
  idemoSetStep("approve", "done");
  idemoStepResult("approve", "ok",
    `<strong>Perfil aprobado por el asesor.</strong> ` +
    `Perfil aprobado: <code>${escapeHTML(res.json.approved_profile || "—")}</code> · ` +
    `decisión <code>${escapeHTML(res.json.decision)}</code>. ` +
    `Esta firma queda registrada en la cadena de auditoría y conduce todo lo de abajo.`);
  return true;
}

// ── STEP 5 — generar propuesta de cartera ─────────────────────────────
// Internamente: investment-preferences → universe-filter → portfolio-proposal.

async function idemoGenerateProposal() {
  if (!window.idemoState.caseId || !window.idemoState.approvalId) {
    idemoStepResult("propose", "warn", "Primero ejecutá los pasos 1–4 (caso, KYC, análisis IA y aprobación del perfil).");
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
    idemoStepResult("propose", "error",
      `<strong>No se pudo registrar las preferencias.</strong> ${escapeHTML(r1.detail || "")}` +
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
    idemoStepResult("propose", "error",
      `<strong>No se pudo filtrar el universo.</strong> ${escapeHTML(r2.detail || "")}` +
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
    idemoStepResult("propose", "error",
      `<strong>No se pudo generar la propuesta.</strong> ${escapeHTML(r3.detail || "")}` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${r3.status}</span>`);
    return false;
  }
  window.idemoState.proposalId = r3.json.proposal_id;
  window.idemoState.candidates = Array.isArray(r3.json.candidates) ? r3.json.candidates : [];

  if (r3.json.status !== "completed") {
    idemoSetStep("propose", "error");
    idemoStepResult("propose", "error",
      `<strong>La propuesta no está completa.</strong> Estado: <code>${escapeHTML(r3.json.status)}</code>. ` +
      `Avisos: ${(r3.json.warnings || []).map(escapeHTML).join("; ") || "—"}.`);
    return false;
  }
  idemoSetStep("propose", "done");

  // Render inline (banner + tabla comparativa + cards por variante con holdings).
  const banner = `<strong>Propuesta generada.</strong> Universo filtrado: ` +
    `<strong>${eligibleN}</strong> instrumentos elegibles (${excludedN} excluidos). ` +
    `Variantes propuestas: <strong>${window.idemoState.candidates.length}</strong>.`;
  idemoStepResultRich("propose", "ok", banner,
    idemoBuildPortfolioComparisonHtml(window.idemoState.candidates));
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

async function idemoSelectPortfolio(chosenVariant) {
  if (!window.idemoState.proposalId) {
    idemoStepResult("select", "warn", "Primero generá la propuesta (paso 5).");
    return false;
  }
  if (!window.idemoState.candidates.length) {
    idemoStepResult("select", "error", "No hay variantes para seleccionar.");
    return false;
  }
  idemoSetStep("select", "active");

  // La selección es una DECISIÓN del asesor. Si se pasó una variante explícita
  // (botón "Seleccionar" de la tabla), se usa esa; si no, fallback al auto-pick.
  let candidate, requiresOverride;
  if (chosenVariant) {
    candidate = window.idemoState.candidates.find(c => c.variant === chosenVariant);
    if (!candidate) {
      idemoSetStep("select", "error");
      idemoStepResult("select", "error", `Variante no encontrada: <code>${escapeHTML(chosenVariant)}</code>.`);
      return false;
    }
    requiresOverride = !!(candidate.metadata && candidate.metadata.requires_advisor_override);
  } else {
    ({ candidate, requiresOverride } = idemoPickPreferredVariant(window.idemoState.candidates));
  }
  const variant = candidate.variant;

  // Override = decisión REAL: si la variante excede el presupuesto aprobado,
  // exigimos confirmación explícita del asesor. No se firma solo.
  let overrideId = null;
  if (requiresOverride) {
    const firma = window.confirm(
      `La variante ${variant} EXCEDE el presupuesto de riesgo aprobado.\n\n` +
      `Como asesor, ¿firmás el override para seleccionarla igual?\n` +
      `La firma queda registrada en la cadena de auditoría.`);
    if (!firma) {
      idemoSetStep("select", "pending");
      idemoStepResult("select", "warn",
        `<strong>Selección cancelada.</strong> No firmaste el override de <code>${escapeHTML(variant)}</code>. ` +
        `Elegí otra variante (una "dentro del presupuesto") o volvé a tocar Seleccionar y firmá el override.`);
      return false;
    }
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
      idemoStepResult("select", "error",
        `<strong>No se pudo firmar el override.</strong> ${escapeHTML(rO.detail || "")}` +
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
    idemoStepResult("select", "error",
      `<strong>No se pudo seleccionar la cartera.</strong> ${escapeHTML(res.detail || "")}` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.selectionId = res.json.selection_id;
  window.idemoState.selectedVariant = res.json.selected_variant;
  window.idemoState.selectedCandidate = res.json.selected_candidate;
  idemoSetStep("select", "done");
  const banner = `<strong>Cartera seleccionada por el asesor.</strong> ` +
    `Variante final: <code>${escapeHTML(variant)}</code>` +
    (requiresOverride
      ? ` <span class="pill pill-orange">con firma de override</span> — el sistema exigió la firma porque la variante excede el presupuesto aprobado`
      : ` <span class="pill pill-green">dentro del presupuesto de riesgo</span>`) + ".";
  idemoStepResultRich("select", "ok", banner, idemoBuildSelectedPortfolioHtml(res.json));
  // El asesor ya decidió la cartera. El reporte y la auditoría no son decisiones
  // humanas: se generan automáticamente a partir de lo que el asesor firmó.
  if (typeof idemoGenerateReport === "function") { await idemoGenerateReport(); }
  if (typeof idemoVerifyAudit === "function") { await idemoVerifyAudit(); }
  return true;
}

// ── STEP 7 — generar reporte ──────────────────────────────────────────

async function idemoGenerateReport() {
  if (!window.idemoState.selectionId) {
    idemoStepResult("report", "warn", "Primero seleccioná la cartera (paso 6).");
    return false;
  }
  idemoSetStep("report", "active");
  const res = await idemoApi("POST",
    `/cases/${encodeURIComponent(window.idemoState.caseId)}/reports`,
    { report_type: "portfolio_recommendation", status: "draft" });
  if (!res.ok) {
    idemoSetStep("report", "error");
    idemoStepResult("report", "error",
      `<strong>No se pudo generar el reporte.</strong> ${escapeHTML(res.detail || "")}` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.reportId = res.json.report_id;
  window.idemoState.reportMarkdown = res.json.markdown || "";
  idemoSetStep("report", "done");
  const banner = `<strong>Reporte listo para revisión del asesor.</strong> ` +
    `<code>${escapeHTML(res.json.report_id)}</code> · ` +
    `versión <strong>${res.json.version}</strong> · estado <code>${escapeHTML(res.json.status)}</code>. ` +
    `Incluye la composición exacta de la cartera y la tabla comparativa de variantes.`;
  idemoStepResultRich("report", "ok", banner, idemoBuildReportPreviewHtml(res.json));
  return true;
}

// ── STEP 8 — verificar auditoría (usa token de compliance) ────────────

async function idemoVerifyAudit() {
  if (!window.idemoState.caseId) {
    idemoStepResult("audit", "warn", "Primero preparar el caso (paso 1).");
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
    idemoStepResult("audit", "error",
      `<strong>No se pudo verificar la auditoría.</strong> ${escapeHTML(res.detail || "")}` +
      `<br><span style="font-size:11px;opacity:.8;">HTTP ${res.status}</span>`);
    return false;
  }
  window.idemoState.auditIntact = !!res.json.is_intact;
  window.idemoState.auditTotalEvents = res.json.total_events;
  idemoSetStep("audit", res.json.is_intact ? "done" : "error");
  const intactPill = res.json.is_intact
    ? '<span class="pill pill-green">cadena intacta</span>'
    : '<span class="pill pill-red">cadena rota</span>';
  const banner = res.json.is_intact
    ? `${intactPill} · Las <strong>${res.json.total_events || 0}</strong> decisiones del caso quedaron registradas y la cadena SHA-256 verifica correctamente. Compliance puede pedir el snapshot completo en Modo técnico.`
    : `${intactPill} · La cadena se rompió en el evento ${res.json.first_broken_sequence}. Mensaje: ${escapeHTML(res.json.message || "—")}.`;
  idemoStepResultRich("audit", res.json.is_intact ? "ok" : "error", banner, idemoBuildAuditExtraHtml(res.json));
  return true;
}

// ── DEMO GUIADA: corre 1–8 en cadena ──────────────────────────────────

async function idemoRunGuidedDemo() {
  const btn = document.getElementById("idemo-btn-guided");
  if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>Corriendo demo guiada…`; }
  try {
    idemoReset();
    idemoStatus("info", "<strong>Demo guiada en curso…</strong> Cada paso queda registrado en la cadena de auditoría.");

    // La guiada corre hasta la PROPUESTA. La selección de cartera es una decisión
    // del asesor: se detiene acá y el asesor elige una variante con el botón
    // "Seleccionar" (y firma el override si la variante excede el presupuesto).
    // Al elegir, idemoSelectPortfolio encadena reporte + auditoría.
    const seq = [
      idemoPrepareCase,
      idemoSubmitKyc,
      idemoRunAiProfile,    // si falla por OpenAI, queda 'skipped' y devuelve true para continuar
      idemoApproveProfile,
      idemoGenerateProposal,
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
    idemoStatus("info",
      `<strong>Tu decisión, asesor.</strong> La IA propuso y el sistema controló el riesgo. ` +
      `Ahora <strong>elegí la cartera</strong> con el botón <em>Seleccionar</em> en la variante que quieras (tabla comparativa, paso 5). ` +
      `Si elegís una que <strong>excede el presupuesto</strong>, el sistema te va a exigir firmar el override. ` +
      `Al elegir, se generan el reporte y la auditoría solos.`);
    // Llevar la vista a la propuesta para que el asesor vea las variantes + botones.
    var prop = document.getElementById("idemo-step-propose");
    if (prop) prop.scrollIntoView({ behavior: "smooth", block: "start" });
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = "▶ Ejecutar demo guiada (8 pasos)"; }
  }
}

// ── Builders: cada uno devuelve HTML para inyectar inline en el step ──

function idemoBuildPortfolioComparisonHtml(candidates) {
  if (!candidates.length) {
    return `<div class="msg msg-info" style="margin-top:10px;">Sin variantes generadas.</div>`;
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
    const btnLabel = meta.requires_advisor_override ? "Seleccionar (override)" : "Seleccionar";
    return `<tr>
      <td style="padding:10px 12px;"><strong>${escapeHTML(c.variant || "?")}</strong></td>
      <td style="padding:10px 12px;font-variant-numeric:tabular-nums;text-align:right;">${c.expected_return_annual !== undefined ? (c.expected_return_annual * 100).toFixed(2) + "%" : "—"}</td>
      <td style="padding:10px 12px;font-variant-numeric:tabular-nums;text-align:right;">${c.volatility_annual !== undefined ? (c.volatility_annual * 100).toFixed(2) + "%" : "—"}</td>
      <td style="padding:10px 12px;text-align:right;font-variant-numeric:tabular-nums;">${n}</td>
      <td style="padding:10px 12px;">${ovr}</td>
      <td style="padding:10px 12px;text-align:right;">
        <button class="btn-primary" style="padding:6px 12px;font-size:12px;white-space:nowrap;" onclick="idemoSelectPortfolio('${escapeHTML(c.variant || "")}')">${btnLabel}</button>
      </td>
    </tr>`;
  }).join("");
  const compareTable = `
    <div style="margin-top:12px;font-size:12px;color:var(--rf-text-muted);font-weight:600;">Tabla comparativa</div>
    <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;margin-top:6px;margin-bottom:14px;">
      <thead><tr style="background:#f4f6fa;">
        <th style="padding:10px 12px;font-size:11px;text-align:left;">Variante</th>
        <th style="padding:10px 12px;font-size:11px;text-align:right;">Retorno esperado</th>
        <th style="padding:10px 12px;font-size:11px;text-align:right;">Volatilidad</th>
        <th style="padding:10px 12px;font-size:11px;text-align:right;"># Instrumentos</th>
        <th style="padding:10px 12px;font-size:11px;text-align:left;">Presupuesto de riesgo</th>
        <th style="padding:10px 12px;font-size:11px;text-align:right;">Acción del asesor</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;

  // Cards detalladas por variante (reusa cwRenderCandidateCard del Workbench)
  const cardsHeader = `<div style="font-size:12px;color:var(--rf-text-muted);font-weight:600;margin-bottom:6px;">Composición por variante (instrumentos + pesos)</div>`;
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

  return compareTable + cardsHeader + cards;
}

function idemoBuildSelectedPortfolioHtml(selectionResp) {
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

  return `
    <div class="portfolio-card" style="margin-top:12px;">
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

function idemoBuildReportPreviewHtml(reportResp) {
  const md = reportResp.markdown || "";
  const hasComp = md.includes("Composición de la cartera seleccionada");
  const hasVar = md.includes("Comparación de variantes generadas");
  const pills = [
    `<span class="pill pill-blue">${md.length} caracteres</span>`,
    hasComp ? '<span class="pill pill-green">incluye composición</span>' : "",
    hasVar ? '<span class="pill pill-violet">incluye comparación de variantes</span>' : "",
  ].filter(Boolean).join(" ");

  return `
    <div style="margin-top:10px;font-size:12px;color:var(--rf-text-muted);">${pills}</div>
    <details open style="margin-top:10px;">
      <summary style="cursor:pointer;font-size:12px;color:var(--rf-navy-700);font-weight:600;">
        Vista previa del reporte (Markdown)
      </summary>
      <pre style="background:#fff;border:1px solid #dde2ea;border-radius:8px;padding:14px;margin-top:6px;font-size:11.5px;line-height:1.5;max-height:420px;overflow:auto;white-space:pre-wrap;font-family:ui-monospace,'JetBrains Mono',Menlo,Consolas,monospace;">${escapeHTML(md)}</pre>
    </details>
    ${(typeof rfaJsonDetails === "function") ? rfaJsonDetails(reportResp.metadata || {}, "Metadata del reporte (técnico)") : ""}
  `;
}

function idemoBuildAuditExtraHtml(verifyResp) {
  return (typeof rfaJsonDetails === "function")
    ? rfaJsonDetails(verifyResp, "Detalles técnicos · respuesta de la verificación")
    : "";
}

// ── Init: render checklist al cargar ──────────────────────────────────

(function () {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", idemoRenderProgress);
  } else {
    idemoRenderProgress();
  }
})();
