// Risk-First Advisory — Case Workbench (Phase 2 Workflow)
// 15 secciones: KYC → AI analysis → approval → preferences → filter →
// proposal → override → selection → report → final summary → audit trail →
// audit verify → AI logs → compliance snapshot.
// Depends on common.js + case-dashboard.js (cd* helpers).

// ═════════════════════════════════════════════════════════════════════════
// CASE WORKBENCH — PROFILE STEPS  (prefijo cw-* / cw* para evitar colisiones)
// ═════════════════════════════════════════════════════════════════════════
//
// Cubre solo KYC → AI Profile Analysis → Profile Approval.
// Reusa el token del Case Dashboard (cdToken()) y los helpers
// cdApiFetch / cdParseResponse / cdNullIfBlank. Auto-refresca el summary
// después de cada POST exitoso.
// ═════════════════════════════════════════════════════════════════════════

// ── State: cache del último summary cargado (para autocompletar inputs) ─
let cwLastSummary = null;

// ── Helpers de render (compactos, en línea con cd*) ─────────────────────

function cwClearResult(elId) {
  const target = el(elId);
  if (target) target.innerHTML = "";
}

function cwRenderJson(elId, data, prefixHtml = "") {
  const target = el(elId);
  if (!target) return;
  // Executive summary (prefixHtml) on top; raw JSON folded into <details> below.
  target.innerHTML = prefixHtml + rfaJsonDetails(data, "Raw JSON response");
}

function cwRenderError(elId, msgHtml) {
  const target = el(elId);
  if (!target) return;
  target.innerHTML = `<div class="msg msg-error">${msgHtml}</div>`;
}

function cwRenderSuccess(elId, msgHtml, data) {
  const target = el(elId);
  if (!target) return;
  const head = `<div class="msg msg-success">${msgHtml}</div>`;
  const body = data !== undefined
    ? `<div style="margin-top:10px;">${rfaJsonDetails(data, "Raw JSON response")}</div>`
    : "";
  target.innerHTML = head + body;
}

function cwRenderLoading(elId, msg = "Loading…") {
  const target = el(elId);
  if (target) target.innerHTML = `<div class="msg msg-info"><span class="spinner"></span>${msg}</div>`;
}

// ── 1. Workbench case_id + summary ─────────────────────────────────────

function cwGetCaseId() {
  return (el("cw-case-id").value || "").trim();
}

function cwPullFromDashboard() {
  // Tomar el case_id seleccionado en la sección 7 del Case Dashboard.
  const dashCase = (el("cd-summary-case-id").value || "").trim();
  if (!dashCase) {
    cwRenderError("cw-summary-result",
      "<strong>Dashboard sin case_id seleccionado.</strong> Crear/seleccionar un case en la card de arriba primero.");
    return;
  }
  el("cw-case-id").value = dashCase;
  cwLoadSummary();
}

function cwSummaryHighlights(s) {
  if (!s || typeof s !== "object") return "";
  const c   = s.case || {};
  const p   = s.progress || {};
  const a   = s.audit || {};
  const kyc = s.latest_kyc || null;
  const an  = s.latest_ai_profile_analysis || null;
  const ap  = s.current_profile_approval || null;

  const row = (k, v) => `<tr><td style="padding:4px 10px;font-weight:600;color:#4a5568;font-size:12px;">${escapeHTML(k)}</td><td style="padding:4px 10px;font-size:12px;">${v}</td></tr>`;
  const flagPill = (v) => v ? '<span class="pill pill-green">yes</span>' : '<span class="pill pill-grey">no</span>';
  const statusBadge = (st) => st ? `<span class="pill pill-blue">${escapeHTML(st)}</span>` : "—";
  const intactBadge = (v) => v ? '<span class="pill pill-green">intact</span>' : '<span class="pill pill-red">broken</span>';

  return `
    <div style="border:1px solid #dde2ea;border-radius:6px;padding:10px;margin-bottom:10px;background:#fafbfd;">
      <div style="font-weight:600;color:#2d3748;margin-bottom:8px;">Workbench overview</div>
      <table style="width:100%;border-collapse:collapse;">
        ${row("case_id",                 `<code>${escapeHTML(c.case_id || "—")}</code>`)}
        ${row("status",                  statusBadge(c.status))}
        ${row("completion_ratio",        `<strong>${(p.completion_ratio !== undefined ? p.completion_ratio : "—")}</strong>`)}
        ${row("next_recommended_action", `<code>${escapeHTML(p.next_recommended_action || "—")}</code>`)}
        ${row("has_kyc",                 flagPill(p.has_kyc))}
        ${row("has_ai_profile_analysis", flagPill(p.has_ai_profile_analysis))}
        ${row("has_profile_approval",    flagPill(p.has_profile_approval))}
        ${row("latest_kyc.kyc_submission_id",
              kyc && kyc.kyc_submission_id ? `<code>${escapeHTML(kyc.kyc_submission_id)}</code>` : "—")}
        ${row("latest_ai_profile_analysis.analysis_id",
              an && an.analysis_id ? `<code>${escapeHTML(an.analysis_id)}</code>` : "—")}
        ${row("latest_ai_profile_analysis.preliminary_profile",
              an && an.preliminary_profile ? `<code>${escapeHTML(an.preliminary_profile)}</code>` : "—")}
        ${row("current_profile_approval.approval_id",
              ap && ap.approval_id ? `<code>${escapeHTML(ap.approval_id)}</code>` : "—")}
        ${row("current_profile_approval.approved_profile",
              ap && ap.approved_profile ? `<code>${escapeHTML(ap.approved_profile)}</code>` : "—")}
        ${row("audit.is_intact",         intactBadge(a.is_intact))}
      </table>
    </div>
  `;
}

// Prellena los inputs downstream con los IDs derivados del summary.
// Implementación completa para los dos tramos del workflow:
//   1) profile steps  (KYC → analysis → approval)
//   2) portfolio/report steps  (preferences → filter → proposal → override
//                               → selection → report)
// Helpers auxiliares (cwGetCurrentProposalCandidates / cwFind*Variant) y
// los renderers de hints se definen más abajo y son hoisted por declaración.
function cwAutofillFromSummary(s) {
  if (!s || typeof s !== "object") return;
  cwLastSummary = s;

  // ── Profile steps autofill ────────────────────────────────────────────
  const kyc = s.latest_kyc || null;
  const an  = s.latest_ai_profile_analysis || null;
  if (kyc && kyc.kyc_submission_id) {
    // El input del análisis es opcional; lo dejamos vacío para que el
    // backend use el current. Sí ofrecemos el ID al usuario en el panel
    // de approval por trazabilidad.
    el("cw-pa-kyc-id").value = kyc.kyc_submission_id;
  }
  if (an && an.analysis_id) {
    el("cw-pa-analysis-id").value = an.analysis_id;
  }
  if (an && an.preliminary_profile) {
    // Sincronizar el dropdown de proposed_profile si el valor coincide
    // con una opción válida.
    const sel = el("cw-pa-proposed");
    const opts = Array.from(sel.options).map(o => o.value);
    if (opts.includes(an.preliminary_profile)) {
      sel.value = an.preliminary_profile;
    }
  }

  // ── Portfolio/report steps autofill ───────────────────────────────────
  // Propagar IDs current a inputs downstream cuando corresponde.
  const cp = s.current_investment_preferences;
  if (cp && cp.preference_id)        el("cw-uf-pref-id").value = cp.preference_id;
  const cf = s.current_universe_filter;
  if (cf && cf.filter_run_id)        el("cw-pp-filter-id").value = cf.filter_run_id;
  const ca = s.current_profile_approval;
  if (ca && ca.approval_id)          el("cw-pp-approval-id").value = ca.approval_id;
  const pp = s.current_portfolio_proposal;
  if (pp && pp.proposal_id) {
    el("cw-ovr-proposal-id").value = pp.proposal_id;
    el("cw-sel-proposal-id").value = pp.proposal_id;
  }
  const co = s.current_override_approval;
  if (co && co.override_approval_id) el("cw-sel-ovr-id").value = co.override_approval_id;
  if (co && co.candidate_variant)    el("cw-ovr-variant").value = co.candidate_variant;
  const cs = s.current_portfolio_selection;
  if (cs && cs.selection_id)         el("cw-rep-selection-id").value = cs.selection_id;

  // Hints + variant preselection del proposal (DOM-specific render).
  if (pp) {
    cwRenderOverrideHint(pp, co);
    cwRenderSelectionHint(pp, co);
  }
}

async function cwLoadSummary(silent = false) {
  const caseId = cwGetCaseId();
  if (!caseId) {
    if (!silent) {
      cwRenderError("cw-summary-result", "<strong>case_id requerido.</strong>");
    }
    return null;
  }
  if (!silent) {
    cwRenderLoading("cw-summary-result", `Loading summary for ${escapeHTML(caseId)}…`);
  }
  const res = await cdApiFetch(`/cases/${encodeURIComponent(caseId)}/summary`, {
    headers: cdAuthHeaders(),
  });
  if (!res.ok) {
    if (!silent) {
      if (res.status === 404) {
        cwRenderError("cw-summary-result",
          `<strong>404:</strong> case <code>${escapeHTML(caseId)}</code> no encontrado.`);
      } else if (res.status === 401) {
        cwRenderError("cw-summary-result",
          `<strong>401:</strong> token inválido o ausente — verificar input del Case Dashboard.`);
      } else if (res.networkError) {
        el("cw-summary-result").innerHTML = apiError(res.err);
      } else {
        cwRenderError("cw-summary-result",
          `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
      }
    }
    return null;
  }
  if (!silent) {
    const highlights = cwSummaryHighlights(res.json);
    cwRenderJson("cw-summary-result", res.json, highlights);
  }
  cwAutofillFromSummary(res.json);
  return res.json;
}

// ── 2. KYC submission ──────────────────────────────────────────────────

function cwNumber(elId, fallback = 0) {
  const v = parseFloat(el(elId).value);
  return Number.isFinite(v) ? v : fallback;
}

function cwInt(elId, fallback = 0) {
  const v = parseInt(el(elId).value, 10);
  return Number.isFinite(v) ? v : fallback;
}

function cwBuildKycPayload() {
  return {
    age:                         cwInt("cw-kyc-age", 40),
    risk_tolerance_score:        cwInt("cw-kyc-rtol", 6),
    risk_capacity_score:         cwInt("cw-kyc-rcap", 7),
    liquidity_need_score:        cwInt("cw-kyc-lneed", 3),
    investment_horizon_years:    cwInt("cw-kyc-horizon", 10),
    investment_experience:       el("cw-kyc-experience").value,
    income_stability:            el("cw-kyc-income-stab").value,
    net_worth:                   cwNumber("cw-kyc-net-worth", 0),
    liquid_net_worth:            cwNumber("cw-kyc-liquid", 0),
    max_acceptable_drawdown_pct: cwNumber("cw-kyc-drawdown", 20),
    jurisdiction:                (el("cw-kyc-jurisdiction").value || "").trim(),
    preferred_currency:          (el("cw-kyc-currency").value || "").trim(),
    investment_objective:        el("cw-kyc-objective").value,
    annual_income_usd:           cwNumber("cw-kyc-income", 0),
    open_investment_goal:        (el("cw-kyc-goal").value || "").trim() || null,
    open_risk_reaction:          (el("cw-kyc-risk-reaction").value || "").trim() || null,
    open_past_experience:        (el("cw-kyc-past").value || "").trim() || null,
    open_concerns:               (el("cw-kyc-concerns").value || "").trim() || null,
  };
}

async function cwSubmitKYC() {
  const caseId = cwGetCaseId();
  if (!caseId) {
    cwRenderError("cw-kyc-result", "<strong>case_id requerido</strong> (sección 1).");
    return;
  }
  const body = cwBuildKycPayload();
  cwRenderLoading("cw-kyc-result", "Submitting KYC…");
  const res = await cdApiFetch(`/cases/${encodeURIComponent(caseId)}/kyc`, {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 404) {
      cwRenderError("cw-kyc-result", `<strong>404:</strong> case <code>${escapeHTML(caseId)}</code> no encontrado.`);
      return;
    }
    if (res.status === 409) {
      cwRenderError("cw-kyc-result", `<strong>409:</strong> ${escapeHTML(res.detail)}. ¿El case está CLOSED?`);
      return;
    }
    if (res.status === 422) {
      cwRenderError("cw-kyc-result",
        `<strong>422 validation</strong>: ${escapeHTML(res.detail)}. Verificar rangos de scores / horizon / drawdown.`);
      return;
    }
    if (res.status === 403) {
      cwRenderError("cw-kyc-result", `<strong>403:</strong> requiere rol <code>admin</code> o <code>advisor</code>.`);
      return;
    }
    if (res.networkError) { el("cw-kyc-result").innerHTML = apiError(res.err); return; }
    cwRenderError("cw-kyc-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const subId  = res.json && res.json.kyc_submission_id ? res.json.kyc_submission_id : "(unknown)";
  const ver    = res.json && res.json.version !== undefined ? res.json.version : "?";
  cwRenderSuccess("cw-kyc-result",
    `KYC submitted: <code>${escapeHTML(subId)}</code> (version ${ver}). Refreshing summary…`,
    res.json);
  await cwRefreshAfterPost();
}

// ── 3. AI Profile Analysis ─────────────────────────────────────────────

async function cwRunAnalysis() {
  const caseId = cwGetCaseId();
  if (!caseId) {
    cwRenderError("cw-ai-result", "<strong>case_id requerido</strong> (sección 1).");
    return;
  }
  const body = {
    analysis_type: el("cw-ai-type").value,
  };
  const kycId = cdNullIfBlank(el("cw-ai-kyc-id").value);
  if (kycId) body.kyc_submission_id = kycId;

  cwRenderLoading("cw-ai-result", "Running AI profile analysis…");
  const res = await cdApiFetch(`/cases/${encodeURIComponent(caseId)}/ai/profile-analysis`, {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 400) {
      cwRenderError("cw-ai-result",
        `<strong>400:</strong> ${escapeHTML(res.detail)}. Probablemente <code>OPENAI_API_KEY</code> no está configurada en el backend.`);
      return;
    }
    if (res.status === 404) {
      cwRenderError("cw-ai-result", `<strong>404:</strong> case <code>${escapeHTML(caseId)}</code> no encontrado.`);
      return;
    }
    if (res.status === 409) {
      cwRenderError("cw-ai-result",
        `<strong>409:</strong> ${escapeHTML(res.detail)}. El case no tiene KYC submission todavía — submitir KYC primero.`);
      return;
    }
    if (res.status === 422) {
      cwRenderError("cw-ai-result",
        `<strong>422</strong>: ${escapeHTML(res.detail)}. Verificar <code>kyc_submission_id</code> (¿es de otro case?) o <code>analysis_type</code> (<code>follow_up</code> no implementado).`);
      return;
    }
    if (res.status === 502) {
      cwRenderError("cw-ai-result",
        `<strong>502:</strong> ${escapeHTML(res.detail)}. La llamada IA falló; ver <code>/admin/ai-logs</code> para el log <code>api_error</code>.`);
      return;
    }
    if (res.status === 403) {
      cwRenderError("cw-ai-result", `<strong>403:</strong> requiere rol <code>admin</code> o <code>advisor</code>.`);
      return;
    }
    if (res.networkError) { el("cw-ai-result").innerHTML = apiError(res.err); return; }
    cwRenderError("cw-ai-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const j = res.json || {};
  const aId   = j.analysis_id || "(unknown)";
  const prof  = j.preliminary_profile || "—";
  const conf  = j.confidence !== undefined ? j.confidence : "—";
  const logId = j.ai_request_log_id || "—";
  cwRenderSuccess("cw-ai-result",
    `Analysis OK: <code>${escapeHTML(aId)}</code> · preliminary_profile <code>${escapeHTML(prof)}</code> · confidence <code>${escapeHTML(String(conf))}</code> · ai_request_log_id <code>${escapeHTML(logId)}</code>. Refreshing summary…`,
    j);
  await cwRefreshAfterPost();
}

// ── 4. Advisor Profile Approval ────────────────────────────────────────

async function cwSubmitApproval() {
  const caseId = cwGetCaseId();
  if (!caseId) {
    cwRenderError("cw-pa-result", "<strong>case_id requerido</strong> (sección 1).");
    return;
  }
  const decision = el("cw-pa-decision").value;
  const proposed = cdNullIfBlank(el("cw-pa-proposed").value);
  const approved = cdNullIfBlank(el("cw-pa-approved").value);
  const rationale = (el("cw-pa-rationale").value || "").trim();
  if (!rationale) {
    cwRenderError("cw-pa-result", "<strong>rationale requerido</strong> (no puede estar vacío).");
    return;
  }

  const body = {
    decision: decision,
    rationale: rationale,
    source: (el("cw-pa-source").value || "").trim() || "manual",
  };
  if (proposed) body.proposed_profile = proposed;
  if (approved) body.approved_profile = approved;
  const aId = cdNullIfBlank(el("cw-pa-analysis-id").value);
  if (aId) body.ai_profile_analysis_id = aId;
  const kId = cdNullIfBlank(el("cw-pa-kyc-id").value);
  if (kId) body.kyc_submission_id = kId;

  cwRenderLoading("cw-pa-result", "Submitting profile approval…");
  const res = await cdApiFetch(`/cases/${encodeURIComponent(caseId)}/profile-approval`, {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 404) {
      cwRenderError("cw-pa-result", `<strong>404:</strong> case <code>${escapeHTML(caseId)}</code> no encontrado.`);
      return;
    }
    if (res.status === 409) {
      cwRenderError("cw-pa-result", `<strong>409:</strong> ${escapeHTML(res.detail)}. ¿El case está CLOSED?`);
      return;
    }
    if (res.status === 422) {
      cwRenderError("cw-pa-result",
        `<strong>422 validation</strong>: ${escapeHTML(res.detail)}. Verificar coherencia decision/approved_profile (approve→ igual o vacío; modify→ requerido; reject→ vacío).`);
      return;
    }
    if (res.status === 403) {
      cwRenderError("cw-pa-result", `<strong>403:</strong> requiere rol <code>admin</code> o <code>advisor</code>.`);
      return;
    }
    if (res.networkError) { el("cw-pa-result").innerHTML = apiError(res.err); return; }
    cwRenderError("cw-pa-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const j = res.json || {};
  const apprId  = j.approval_id || "(unknown)";
  const dec     = j.decision || "—";
  const approvedOut = j.approved_profile || "—";
  cwRenderSuccess("cw-pa-result",
    `Approval OK: <code>${escapeHTML(apprId)}</code> · decision <code>${escapeHTML(dec)}</code> · approved_profile <code>${escapeHTML(approvedOut)}</code>. Refreshing summary…`,
    j);
  await cwRefreshAfterPost();
}


// ═════════════════════════════════════════════════════════════════════════
// CASE WORKBENCH — PORTFOLIO/REPORT STEPS (sections 5–11)
// Mismo prefijo cw* / cw-* (la misma card). Reusa cwLoadSummary, cwGetCaseId,
// cdApiFetch, cdAuthHeaders, cdNullIfBlank.
// ═════════════════════════════════════════════════════════════════════════

// ── Helpers comunes (extensión) ────────────────────────────────────────

function cwParseCSV(raw) {
  return (raw || "")
    .split(",")
    .map(s => s.trim())
    .filter(s => s.length > 0);
}

function cwParseJsonTextarea(elId, fallback = null) {
  const raw = (el(elId).value || "").trim();
  if (!raw) return { ok: true, value: fallback };
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return { ok: false, error: "must be a JSON object (dict), not an array or primitive" };
    }
    return { ok: true, value: parsed };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// Refresh común post-POST: una sola request al backend; re-renderiza
// cualquier panel visible (summary y/o final) reusando el JSON cacheado.
async function cwRefreshAfterPost() {
  const s = await cwLoadSummary(true);
  if (s && el("cw-summary-result").innerHTML.length > 0) {
    cwRenderJson("cw-summary-result", s, cwSummaryHighlights(s));
  }
  if (el("cw-final-result").innerHTML.length > 0) {
    cwRenderFinalSummary(s || cwLastSummary);
  }
}

// Encuentra candidates en cwLastSummary.current_portfolio_proposal
function cwGetCurrentProposalCandidates() {
  if (!cwLastSummary) return [];
  const p = cwLastSummary.current_portfolio_proposal;
  if (!p || !Array.isArray(p.candidates)) return [];
  return p.candidates;
}

function cwFindOverrideRequiredVariant() {
  for (const c of cwGetCurrentProposalCandidates()) {
    const meta = c && c.metadata;
    if (meta && meta.requires_advisor_override === true) {
      return c.variant;
    }
  }
  return null;
}

function cwFindNonOverrideVariant() {
  for (const c of cwGetCurrentProposalCandidates()) {
    const meta = c && c.metadata;
    if (meta && meta.requires_advisor_override === false) {
      return c.variant;
    }
  }
  return null;
}

// Centralizar render genérico de error HTTP por panel
function cwRenderHttpError(elId, res, ctx = "") {
  if (res.networkError) { el(elId).innerHTML = apiError(res.err); return; }
  const tag = `<strong>HTTP ${res.status}${ctx ? " ("+ctx+")" : ""}:</strong> `;
  cwRenderError(elId, tag + escapeHTML(res.detail || "?"));
}

// ── Hint renderers (override + selection panels) ───────────────────────
// Llamados desde cwAutofillFromSummary cuando hay current_portfolio_proposal.
// Mutan los `cw-{ovr,sel}-hint` panels y preseleccionan el variant del input.
function cwRenderOverrideHint(proposal, currentOverride) {
  const overrideVariant = cwFindOverrideRequiredVariant();
  const hint = el("cw-ovr-hint");
  hint.style.display = "block";
  if (overrideVariant !== null) {
    hint.innerHTML = `<strong>${escapeHTML(overrideVariant)}</strong> en current proposal requiere advisor override.`;
    el("cw-ovr-variant").value = overrideVariant;
  } else {
    hint.innerHTML = `<em>No override-required candidate detected in current proposal.</em> El submit fallará 422 a menos que la situación cambie; usar solo si insistís.`;
  }
}

function cwRenderSelectionHint(proposal, currentOverride) {
  // Preselección:
  //   1) si hay current override approved → su variant + su id
  //   2) si hay candidate sin override → BALANCED si existe, sino el primero sin override
  //   3) si solo hay candidates con override → el de override (advisor debe aprobar primero)
  const co = currentOverride;
  const overrideVariant = cwFindOverrideRequiredVariant();
  const nonOverrideVariant = cwFindNonOverrideVariant();
  const hint = el("cw-sel-hint");

  if (co && co.decision === "approve" && co.candidate_variant) {
    el("cw-sel-variant").value = co.candidate_variant;
    hint.style.display = "block";
    hint.innerHTML = `Current approved override exists for <strong>${escapeHTML(co.candidate_variant)}</strong> — preseleccionando.`;
    return;
  }
  if (nonOverrideVariant !== null) {
    const variants = cwGetCurrentProposalCandidates().map(c => c.variant);
    const prefer = variants.includes("BALANCED") ? "BALANCED" : nonOverrideVariant;
    el("cw-sel-variant").value = prefer;
    hint.style.display = "block";
    hint.innerHTML = `Preselected <strong>${escapeHTML(prefer)}</strong> (no override requerido).`;
    return;
  }
  if (overrideVariant !== null) {
    el("cw-sel-variant").value = overrideVariant;
    hint.style.display = "block";
    hint.innerHTML = `<strong>${escapeHTML(overrideVariant)}</strong> requiere override — aprobar primero en sección 8.`;
  }
}

// ── 5. Investment Preferences ──────────────────────────────────────────

async function cwSubmitPreferences() {
  const caseId = cwGetCaseId();
  if (!caseId) {
    cwRenderError("cw-pref-result", "<strong>case_id requerido</strong> (sección 1).");
    return;
  }
  const structuredParse = cwParseJsonTextarea("cw-pref-structured", null);
  if (!structuredParse.ok) {
    cwRenderError("cw-pref-result",
      `<strong>structured_preferences JSON inválido:</strong> ${escapeHTML(structuredParse.error)}`);
    return;
  }
  const nlp = cdNullIfBlank(el("cw-pref-nlp").value);
  if (structuredParse.value === null && !nlp) {
    cwRenderError("cw-pref-result",
      "<strong>Debe proveerse al menos uno</strong>: structured_preferences (JSON) o natural_language_preferences (texto).");
    return;
  }
  const body = { source: el("cw-pref-source").value };
  if (structuredParse.value) body.structured_preferences = structuredParse.value;
  if (nlp) body.natural_language_preferences = nlp;

  cwRenderLoading("cw-pref-result", "Submitting investment preferences…");
  const res = await cdApiFetch(`/cases/${encodeURIComponent(caseId)}/investment-preferences`, {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 404) { cwRenderError("cw-pref-result", `<strong>404:</strong> case no encontrado.`); return; }
    if (res.status === 409) { cwRenderError("cw-pref-result", `<strong>409:</strong> ${escapeHTML(res.detail)}. ¿Case CLOSED?`); return; }
    if (res.status === 422) { cwRenderError("cw-pref-result", `<strong>422:</strong> ${escapeHTML(res.detail)}.`); return; }
    if (res.status === 502) { cwRenderError("cw-pref-result", `<strong>502 IA:</strong> ${escapeHTML(res.detail)}. ¿NLP path sin OPENAI_API_KEY?`); return; }
    cwRenderHttpError("cw-pref-result", res);
    return;
  }
  const j = res.json || {};
  const pid = j.preference_id || "(unknown)";
  const src = j.source || "—";
  const aiLog = j.ai_request_log_id ? ` · ai_request_log_id <code>${escapeHTML(j.ai_request_log_id)}</code>` : "";
  cwRenderSuccess("cw-pref-result",
    `Preferences OK: <code>${escapeHTML(pid)}</code> · source <code>${escapeHTML(src)}</code>${aiLog}. Refreshing summary…`,
    j);
  await cwRefreshAfterPost();
}

// ── 6. Universe Filter ─────────────────────────────────────────────────

async function cwRunUniverseFilter() {
  const caseId = cwGetCaseId();
  if (!caseId) {
    cwRenderError("cw-uf-result", "<strong>case_id requerido</strong> (sección 1).");
    return;
  }
  const body = {
    source_universe: (el("cw-uf-source").value || "").trim() || "sample_instrument_universe.csv",
  };
  const pid = cdNullIfBlank(el("cw-uf-pref-id").value);
  if (pid) body.preference_id = pid;

  cwRenderLoading("cw-uf-result", "Running universe filter…");
  const res = await cdApiFetch(`/cases/${encodeURIComponent(caseId)}/universe-filter`, {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 404) { cwRenderError("cw-uf-result", `<strong>404:</strong> case no encontrado.`); return; }
    if (res.status === 409) { cwRenderError("cw-uf-result", `<strong>409:</strong> ${escapeHTML(res.detail)}. ¿Falta investment_preferences? Submit preferences (sección 5) primero.`); return; }
    if (res.status === 422) { cwRenderError("cw-uf-result", `<strong>422:</strong> ${escapeHTML(res.detail)}. ¿preference_id de otro case o inválido?`); return; }
    cwRenderHttpError("cw-uf-result", res);
    return;
  }
  const j = res.json || {};
  const eligibles = Array.isArray(j.eligible_instruments) ? j.eligible_instruments : [];
  const top5 = eligibles.slice(0, 5).map(i => `<code>${escapeHTML(i.ticker || "?")}</code>`).join(", ") || "<em>none</em>";
  const applied = Array.isArray(j.applied_filters) ? j.applied_filters : [];
  const warnings = Array.isArray(j.warnings) ? j.warnings : [];
  const head = `
    <div class="msg msg-success">
      Filter OK: <code>${escapeHTML(j.filter_run_id || "?")}</code> ·
      eligible <strong>${j.eligible_count}</strong> · excluded <strong>${j.excluded_count}</strong> · total <strong>${j.total_count}</strong>
    </div>
    <div style="margin-top:8px;font-size:12px;color:#4a5568;">
      <div><strong>Top 5 eligible:</strong> ${top5}</div>
      <div style="margin-top:4px;"><strong>applied_filters (${applied.length}):</strong> ${applied.map(f => `<code>${escapeHTML(f)}</code>`).join(" ") || "<em>none</em>"}</div>
      <div style="margin-top:4px;"><strong>warnings (${warnings.length}):</strong> ${warnings.map(w => `<code>${escapeHTML(w)}</code>`).join(" ") || "<em>none</em>"}</div>
    </div>
    <details style="margin-top:8px;"><summary style="cursor:pointer;font-size:12px;color:#2e4a8a;">Full JSON</summary>
    <pre class="json-block">${escapeHTML(formatJSON(j))}</pre></details>
  `;
  el("cw-uf-result").innerHTML = head;
  await cwRefreshAfterPost();
}

// ── 7. Portfolio Proposal ──────────────────────────────────────────────

async function cwGenerateProposal() {
  const caseId = cwGetCaseId();
  if (!caseId) {
    cwRenderError("cw-pp-result", "<strong>case_id requerido</strong> (sección 1).");
    return;
  }
  const body = {
    variant_policy: (el("cw-pp-policy").value || "").trim() || "standard",
  };
  const fid = cdNullIfBlank(el("cw-pp-filter-id").value);
  if (fid) body.filter_run_id = fid;
  const aid = cdNullIfBlank(el("cw-pp-approval-id").value);
  if (aid) body.approved_profile_id = aid;

  cwRenderLoading("cw-pp-result", "Generating portfolio proposal…");
  const res = await cdApiFetch(`/cases/${encodeURIComponent(caseId)}/portfolio-proposal`, {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 404) { cwRenderError("cw-pp-result", `<strong>404:</strong> case no encontrado.`); return; }
    if (res.status === 409) { cwRenderError("cw-pp-result", `<strong>409:</strong> ${escapeHTML(res.detail)}. ¿Falta filter run o approved profile? Completar pasos previos.`); return; }
    if (res.status === 422) { cwRenderError("cw-pp-result", `<strong>422:</strong> ${escapeHTML(res.detail)}.`); return; }
    cwRenderHttpError("cw-pp-result", res);
    return;
  }
  const j = res.json || {};
  const cands = Array.isArray(j.candidates) ? j.candidates : [];
  const warnings = Array.isArray(j.warnings) ? j.warnings : [];
  const candRows = cands.map(c => {
    const m = c.metadata || {};
    const overrideBadge = m.requires_advisor_override
      ? '<span class="pill pill-orange">override</span>'
      : '<span class="pill pill-green">within budget</span>';
    const rc = Array.isArray(c.reason_codes) && c.reason_codes.length
      ? c.reason_codes.map(r => `<code>${escapeHTML(r)}</code>`).join(" ")
      : "<em>—</em>";
    return `<tr>
      <td style="padding:4px 8px;font-size:12px;"><code>${escapeHTML(c.variant || "?")}</code></td>
      <td style="padding:4px 8px;font-size:12px;">${overrideBadge}</td>
      <td style="padding:4px 8px;font-size:12px;text-align:right;">${c.expected_return_annual !== undefined ? (c.expected_return_annual * 100).toFixed(2) + "%" : "—"}</td>
      <td style="padding:4px 8px;font-size:12px;text-align:right;">${c.volatility_annual !== undefined ? (c.volatility_annual * 100).toFixed(2) + "%" : "—"}</td>
      <td style="padding:4px 8px;font-size:12px;">${rc}</td>
    </tr>`;
  }).join("");
  const head = `
    <div class="msg msg-success">
      Proposal OK: <code>${escapeHTML(j.proposal_id || "?")}</code> ·
      status <code>${escapeHTML(j.status || "?")}</code> ·
      profile <code>${escapeHTML(j.profile_name || "?")}</code> ·
      candidates <strong>${cands.length}</strong>
    </div>
    <table style="width:100%;border-collapse:collapse;margin-top:8px;border:1px solid #dde2ea;">
      <thead><tr style="background:#f4f6fa;">
        <th style="padding:6px 8px;font-size:11px;text-align:left;">variant</th>
        <th style="padding:6px 8px;font-size:11px;text-align:left;">budget</th>
        <th style="padding:6px 8px;font-size:11px;text-align:right;">E[ret] anual</th>
        <th style="padding:6px 8px;font-size:11px;text-align:right;">vol anual</th>
        <th style="padding:6px 8px;font-size:11px;text-align:left;">reason_codes</th>
      </tr></thead>
      <tbody>${candRows || `<tr><td colspan="5" style="padding:8px;font-size:12px;color:#a0aec0;">No candidates.</td></tr>`}</tbody>
    </table>
    ${warnings.length ? `<div style="margin-top:6px;font-size:11px;color:#92400e;"><strong>warnings:</strong> ${warnings.map(w => escapeHTML(w)).join("; ")}</div>` : ""}
    <details style="margin-top:8px;"><summary style="cursor:pointer;font-size:12px;color:#2e4a8a;">Full JSON</summary>
    <pre class="json-block">${escapeHTML(formatJSON(j))}</pre></details>
  `;
  el("cw-pp-result").innerHTML = head;
  await cwRefreshAfterPost();
}

// ── 8. Override Approval ───────────────────────────────────────────────

async function cwSubmitOverride() {
  const caseId = cwGetCaseId();
  if (!caseId) {
    cwRenderError("cw-ovr-result", "<strong>case_id requerido</strong> (sección 1).");
    return;
  }
  const rationale = (el("cw-ovr-rationale").value || "").trim();
  if (!rationale) {
    cwRenderError("cw-ovr-result", "<strong>rationale requerido</strong>.");
    return;
  }
  const body = {
    candidate_variant:    el("cw-ovr-variant").value,
    decision:             el("cw-ovr-decision").value,
    reason_codes:         cwParseCSV(el("cw-ovr-reasons").value),
    exceeded_constraints: cwParseCSV(el("cw-ovr-exceeded").value),
    rationale:            rationale,
    source:               (el("cw-ovr-source").value || "").trim() || "manual",
  };
  const pid = cdNullIfBlank(el("cw-ovr-proposal-id").value);
  if (pid) body.proposal_id = pid;

  cwRenderLoading("cw-ovr-result", "Submitting override approval…");
  const res = await cdApiFetch(`/cases/${encodeURIComponent(caseId)}/override-approval`, {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 404) { cwRenderError("cw-ovr-result", `<strong>404:</strong> case no encontrado.`); return; }
    if (res.status === 409) { cwRenderError("cw-ovr-result", `<strong>409:</strong> ${escapeHTML(res.detail)}. ¿Case CLOSED o proposal sin candidates (status != completed)?`); return; }
    if (res.status === 422) { cwRenderError("cw-ovr-result", `<strong>422:</strong> ${escapeHTML(res.detail)}. Posibles causas: variant no existe en proposal, variant NO requiere override, proposal de otro case.`); return; }
    cwRenderHttpError("cw-ovr-result", res);
    return;
  }
  const j = res.json || {};
  cwRenderSuccess("cw-ovr-result",
    `Override OK: <code>${escapeHTML(j.override_approval_id || "?")}</code> · decision <code>${escapeHTML(j.decision || "?")}</code> · variant <code>${escapeHTML(j.candidate_variant || "?")}</code> · is_current <strong>${j.is_current}</strong>. Refreshing summary…`,
    j);
  await cwRefreshAfterPost();
}

// ── 9. Portfolio Selection ─────────────────────────────────────────────

async function cwSubmitSelection() {
  const caseId = cwGetCaseId();
  if (!caseId) {
    cwRenderError("cw-sel-result", "<strong>case_id requerido</strong> (sección 1).");
    return;
  }
  const rationale = (el("cw-sel-rationale").value || "").trim();
  if (!rationale) {
    cwRenderError("cw-sel-result", "<strong>rationale requerido</strong>.");
    return;
  }
  const body = {
    selected_variant: el("cw-sel-variant").value,
    rationale:        rationale,
    source:           (el("cw-sel-source").value || "").trim() || "manual",
  };
  const pid = cdNullIfBlank(el("cw-sel-proposal-id").value);
  if (pid) body.proposal_id = pid;
  const oid = cdNullIfBlank(el("cw-sel-ovr-id").value);
  if (oid) body.override_approval_id = oid;

  cwRenderLoading("cw-sel-result", "Submitting portfolio selection…");
  const res = await cdApiFetch(`/cases/${encodeURIComponent(caseId)}/portfolio-selection`, {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 404) { cwRenderError("cw-sel-result", `<strong>404:</strong> case no encontrado.`); return; }
    if (res.status === 409) {
      cwRenderError("cw-sel-result",
        `<strong>409:</strong> ${escapeHTML(res.detail)}. Causa típica: variant requiere override aprobado y no se provee, o override existente tiene decision=reject. Aprobar override en sección 8 y reintentar.`);
      return;
    }
    if (res.status === 422) {
      cwRenderError("cw-sel-result",
        `<strong>422:</strong> ${escapeHTML(res.detail)}. Posibles causas: variant no existe en proposal, variant no requiere override pero se pasa override_approval_id, override de otro case/proposal/variant.`);
      return;
    }
    cwRenderHttpError("cw-sel-result", res);
    return;
  }
  const j = res.json || {};
  const cand = j.selected_candidate || {};
  const candSummary = cand && cand.expected_return_annual !== undefined
    ? ` · E[ret] <strong>${(cand.expected_return_annual * 100).toFixed(2)}%</strong> · vol <strong>${cand.volatility_annual !== undefined ? (cand.volatility_annual * 100).toFixed(2) + "%" : "—"}</strong>`
    : "";
  cwRenderSuccess("cw-sel-result",
    `Selection OK: <code>${escapeHTML(j.selection_id || "?")}</code> · variant <code>${escapeHTML(j.selected_variant || "?")}</code> · override_approval_id <code>${escapeHTML(j.override_approval_id || "null")}</code>${candSummary}. Case status debería ser PORTFOLIO_SELECTED tras refresh.`,
    j);
  await cwRefreshAfterPost();
}

// ── 10. Report Generation ──────────────────────────────────────────────

async function cwGenerateReport() {
  const caseId = cwGetCaseId();
  if (!caseId) {
    cwRenderError("cw-rep-result", "<strong>case_id requerido</strong> (sección 1).");
    return;
  }
  const body = {
    report_type: el("cw-rep-type").value,
    status:      el("cw-rep-status").value,
  };
  const sid = cdNullIfBlank(el("cw-rep-selection-id").value);
  if (sid) body.portfolio_selection_id = sid;

  cwRenderLoading("cw-rep-result", "Generating report…");
  const res = await cdApiFetch(`/cases/${encodeURIComponent(caseId)}/reports`, {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 404) { cwRenderError("cw-rep-result", `<strong>404:</strong> case no encontrado.`); return; }
    if (res.status === 409) {
      cwRenderError("cw-rep-result",
        `<strong>409:</strong> ${escapeHTML(res.detail)}. Probable: case sin portfolio selection — completar sección 9 primero.`);
      return;
    }
    if (res.status === 422) { cwRenderError("cw-rep-result", `<strong>422:</strong> ${escapeHTML(res.detail)}.`); return; }
    cwRenderHttpError("cw-rep-result", res);
    return;
  }
  const j = res.json || {};
  const md = j.markdown || "";
  const meta = j.metadata || {};
  cwRenderSuccess("cw-rep-result",
    `Report OK: <code>${escapeHTML(j.report_id || "?")}</code> · version <strong>${j.version}</strong> · status <code>${escapeHTML(j.status || "?")}</code> · type <code>${escapeHTML(j.report_type || "?")}</code>`);
  el("cw-rep-result").insertAdjacentHTML("beforeend", `
    <div style="margin-top:8px;">
      <details open>
        <summary style="cursor:pointer;font-size:12px;color:#2e4a8a;font-weight:600;">Markdown preview (${md.length} chars)</summary>
        <pre style="background:#fff;border:1px solid #dde2ea;border-radius:4px;padding:10px;margin-top:6px;font-size:11px;line-height:1.4;max-height:340px;overflow:auto;white-space:pre-wrap;">${escapeHTML(md)}</pre>
      </details>
      <details style="margin-top:6px;">
        <summary style="cursor:pointer;font-size:12px;color:#2e4a8a;">metadata</summary>
        <pre class="json-block">${escapeHTML(formatJSON(meta))}</pre>
      </details>
    </div>
  `);
  await cwRefreshAfterPost();
}

// ── 11. Compact final summary ──────────────────────────────────────────

function cwRenderFinalSummary(s) {
  if (!s) {
    el("cw-final-result").innerHTML =
      `<div class="msg msg-info">Refresh summary first (clic en el botón).</div>`;
    return;
  }
  const p   = s.progress || {};
  const a   = s.audit || {};
  const rep = s.current_report || null;
  const sel = s.current_portfolio_selection || null;
  const c   = s.case || {};

  const row = (k, v) => `<tr><td style="padding:4px 10px;font-weight:600;color:#4a5568;font-size:12px;">${escapeHTML(k)}</td><td style="padding:4px 10px;font-size:12px;">${v}</td></tr>`;
  const flagPill = (v) => v ? '<span class="pill pill-green">yes</span>' : '<span class="pill pill-grey">no</span>';
  const intactBadge = (v) => v ? '<span class="pill pill-green">intact</span>' : '<span class="pill pill-red">broken</span>';

  el("cw-final-result").innerHTML = `
    <div style="border:1px solid #dde2ea;border-radius:6px;padding:10px;background:#fafbfd;">
      <div style="font-weight:600;color:#2d3748;margin-bottom:8px;">Final state · case <code>${escapeHTML(c.case_id || "—")}</code> (${escapeHTML(c.status || "—")})</div>
      <table style="width:100%;border-collapse:collapse;">
        ${row("next_recommended_action", `<code>${escapeHTML(p.next_recommended_action || "—")}</code>`)}
        ${row("completion_ratio",        `<strong>${p.completion_ratio !== undefined ? p.completion_ratio : "—"}</strong>`)}
        ${row("has_investment_preferences", flagPill(p.has_investment_preferences))}
        ${row("has_universe_filter",       flagPill(p.has_universe_filter))}
        ${row("has_portfolio_proposal",    flagPill(p.has_portfolio_proposal))}
        ${row("has_override_approval",     flagPill(p.has_override_approval))}
        ${row("has_portfolio_selection",   flagPill(p.has_portfolio_selection))}
        ${row("has_report",                flagPill(p.has_report))}
        ${row("audit.is_intact",           intactBadge(a.is_intact))}
        ${row("current_report.report_id",  rep && rep.report_id ? `<code>${escapeHTML(rep.report_id)}</code> (v${rep.version})` : "—")}
        ${row("current_portfolio_selection.selected_variant",
              sel && sel.selected_variant ? `<code>${escapeHTML(sel.selected_variant)}</code>` : "—")}
      </table>
    </div>
  `;
}

async function cwLoadFinalSummary() {
  cwRenderFinalSummary((await cwLoadSummary(true)) || cwLastSummary || null);
}


// ═════════════════════════════════════════════════════════════════════════
// CASE WORKBENCH — AUDIT & AI LOGS PANELS (sections 12–15)
// GET /cases/{id}/audit            → any rol válido
// GET /cases/{id}/audit/verify     → admin, compliance
// GET /cases/{id}/ai-logs          → admin, compliance
// ═════════════════════════════════════════════════════════════════════════

// ── Helpers comunes ────────────────────────────────────────────────────

function cwShortHash(h) {
  if (!h || typeof h !== "string") return "—";
  if (h.length <= 12) return h;
  return `${h.slice(0, 6)}…${h.slice(-4)}`;
}

// Wrapper común para GETs de paneles compliance: handlea 401/403/404 con
// mensajes consistentes; devuelve el JSON parseado o null si hubo error.
async function cwComplianceGet(elId, path, role403Hint) {
  const caseId = cwGetCaseId();
  if (!caseId) {
    cwRenderError(elId, "<strong>case_id requerido</strong> (sección 1).");
    return null;
  }
  cwRenderLoading(elId, `Loading ${escapeHTML(path)}…`);
  const res = await cdApiFetch(path.replace("{case_id}", encodeURIComponent(caseId)), {
    headers: cdAuthHeaders(),
  });
  if (!res.ok) {
    if (res.status === 401) {
      cwRenderError(elId, `<strong>401:</strong> token inválido o ausente — verificar input del Case Dashboard.`);
    } else if (res.status === 403) {
      cwRenderError(elId, `<strong>403:</strong> ${escapeHTML(role403Hint)}.`);
    } else if (res.status === 404) {
      cwRenderError(elId, `<strong>404:</strong> case <code>${escapeHTML(caseId)}</code> no encontrado.`);
    } else {
      cwRenderHttpError(elId, res);
    }
    return null;
  }
  return res.json;
}

// ── 12. Audit Trail ───────────────────────────────────────────────────

function cwRenderAuditEvents(elId, j) {
  if (!j) return;
  const events = Array.isArray(j.events) ? j.events : [];
  if (!events.length) {
    el(elId).innerHTML = `<div class="msg msg-info">No audit events for this case yet.</div>`;
    return;
  }
  const rows = events.map(e => `
    <tr>
      <td style="padding:4px 8px;font-size:11px;text-align:right;"><strong>${e.sequence}</strong></td>
      <td style="padding:4px 8px;font-size:11px;"><code>${escapeHTML(e.event_type || "?")}</code></td>
      <td style="padding:4px 8px;font-size:11px;"><span class="pill pill-blue">${escapeHTML(e.actor_role || "—")}</span></td>
      <td style="padding:4px 8px;font-size:11px;"><code>${escapeHTML(e.actor_advisor_id || "—")}</code></td>
      <td style="padding:4px 8px;font-size:11px;color:#4a5568;">${escapeHTML(e.created_at_utc || "—")}</td>
      <td style="padding:4px 8px;font-size:10px;font-family:monospace;color:#718096;" title="${escapeHTML(e.previous_hash || "null")}">${cwShortHash(e.previous_hash)}</td>
      <td style="padding:4px 8px;font-size:10px;font-family:monospace;color:#4a5568;" title="${escapeHTML(e.payload_hash || "")}">${cwShortHash(e.payload_hash)}</td>
      <td style="padding:4px 8px;font-size:10px;font-family:monospace;color:#2d3748;" title="${escapeHTML(e.event_hash || "")}">${cwShortHash(e.event_hash)}</td>
    </tr>
  `).join("");
  el(elId).innerHTML = `
    <div class="msg msg-success">Loaded <strong>${j.count}</strong> audit event(s).</div>
    <div style="overflow-x:auto;margin-top:8px;">
      <table style="width:100%;border-collapse:collapse;border:1px solid #dde2ea;">
        <thead><tr style="background:#f4f6fa;">
          <th style="padding:6px 8px;font-size:11px;text-align:right;">seq</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;">event_type</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;">actor_role</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;">actor_advisor_id</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;">created_at_utc</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;" title="previous_hash">prev_hash</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;" title="payload_hash">payload_hash</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;" title="event_hash">event_hash</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <details style="margin-top:8px;"><summary style="cursor:pointer;font-size:12px;color:#2e4a8a;">Full JSON</summary>
    <pre class="json-block">${escapeHTML(formatJSON(j))}</pre></details>
  `;
}

async function cwLoadAuditEvents() {
  const j = await cwComplianceGet("cw-audit-result", "/cases/{case_id}/audit",
    "este rol no debería estar restringido para GET /audit; verificar token y backend");
  cwRenderAuditEvents("cw-audit-result", j);
}

// ── 13. Audit Verification ────────────────────────────────────────────

function cwRenderAuditVerify(elId, j) {
  if (!j) return;
  const intact = j.is_intact === true;
  const badge = intact
    ? '<span class="pill pill-green">INTACT</span>'
    : '<span class="pill pill-red">BROKEN</span>';
  const broken = j.first_broken_sequence !== null && j.first_broken_sequence !== undefined
    ? `<code>${escapeHTML(String(j.first_broken_sequence))}</code>`
    : "<em>none</em>";
  const msgClass = intact ? "msg-success" : "msg-error";
  el(elId).innerHTML = `
    <div class="msg ${msgClass}">
      ${badge} · total_events <strong>${j.total_events}</strong> · first_broken_sequence ${broken}
    </div>
    <div style="margin-top:8px;font-size:12px;color:#4a5568;">
      <strong>message:</strong> ${escapeHTML(j.message || "—")}
      ${j.checked_at_utc ? `<br><strong>checked_at_utc:</strong> <code>${escapeHTML(j.checked_at_utc)}</code>` : ""}
    </div>
    <details style="margin-top:8px;"><summary style="cursor:pointer;font-size:12px;color:#2e4a8a;">Full JSON</summary>
    <pre class="json-block">${escapeHTML(formatJSON(j))}</pre></details>
  `;
}

async function cwVerifyAudit() {
  const j = await cwComplianceGet("cw-verify-result", "/cases/{case_id}/audit/verify",
    "requiere rol <code>admin</code> o <code>compliance</code>");
  cwRenderAuditVerify("cw-verify-result", j);
}

// ── 14. AI Request Logs ───────────────────────────────────────────────

function cwValidationPill(status) {
  if (status === "parsed_ok") return '<span class="pill pill-green">parsed_ok</span>';
  if (status === "api_error" || status === "parse_error" || status === "validation_error") {
    return `<span class="pill pill-red">${escapeHTML(status)}</span>`;
  }
  return `<span class="pill pill-grey">${escapeHTML(status || "—")}</span>`;
}

function cwRenderAiLogs(elId, j) {
  if (!j) return;
  const logs = Array.isArray(j.logs) ? j.logs : [];
  if (!logs.length) {
    el(elId).innerHTML = `<div class="msg msg-info">No AI logs for this case yet.</div>`;
    return;
  }
  const rows = logs.map(g => `
    <tr>
      <td style="padding:4px 8px;font-size:11px;"><code>${escapeHTML(g.request_id || "?")}</code></td>
      <td style="padding:4px 8px;font-size:11px;"><code>${escapeHTML(g.endpoint || "—")}</code></td>
      <td style="padding:4px 8px;font-size:11px;"><code>${escapeHTML(g.model || "—")}</code></td>
      <td style="padding:4px 8px;font-size:11px;"><code>${escapeHTML(g.prompt_version || "—")}</code></td>
      <td style="padding:4px 8px;font-size:11px;">${cwValidationPill(g.validation_status)}</td>
      <td style="padding:4px 8px;font-size:11px;text-align:right;">${g.latency_ms !== null && g.latency_ms !== undefined ? g.latency_ms + " ms" : "—"}</td>
      <td style="padding:4px 8px;font-size:11px;color:#4a5568;">${escapeHTML(g.created_at_utc || "—")}</td>
      <td style="padding:4px 8px;font-size:11px;color:#991b1b;">${escapeHTML(g.error_message || "—")}</td>
    </tr>
  `).join("");
  const latest = logs[logs.length - 1];
  el(elId).innerHTML = `
    <div class="msg msg-success">
      Loaded <strong>${j.count}</strong> AI log(s). Latest: <code>${escapeHTML(latest.request_id || "?")}</code>
      · ${cwValidationPill(latest.validation_status)}
    </div>
    <div style="overflow-x:auto;margin-top:8px;">
      <table style="width:100%;border-collapse:collapse;border:1px solid #dde2ea;">
        <thead><tr style="background:#f4f6fa;">
          <th style="padding:6px 8px;font-size:11px;text-align:left;">request_id</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;">endpoint</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;">model</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;">prompt_version</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;">status</th>
          <th style="padding:6px 8px;font-size:11px;text-align:right;">latency</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;">created_at_utc</th>
          <th style="padding:6px 8px;font-size:11px;text-align:left;">error</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <details style="margin-top:8px;"><summary style="cursor:pointer;font-size:12px;color:#2e4a8a;font-weight:600;">Latest log — input_redacted + raw_response</summary>
    <div style="margin-top:6px;font-size:11px;color:#4a5568;">
      <div><strong>input_redacted</strong> (sanitizado por backend):</div>
      <pre class="json-block">${escapeHTML(formatJSON(latest.input_redacted || {}))}</pre>
      <div style="margin-top:6px;"><strong>raw_response</strong> <span style="color:#92400e;">⚠ no necesariamente redactado — revisar antes de exportar</span>:</div>
      <pre class="json-block">${escapeHTML(formatJSON(latest.raw_response || null))}</pre>
    </div></details>
    <details style="margin-top:6px;"><summary style="cursor:pointer;font-size:12px;color:#2e4a8a;">Full JSON (all logs)</summary>
    <pre class="json-block">${escapeHTML(formatJSON(j))}</pre></details>
  `;
}

async function cwLoadAiLogs() {
  const j = await cwComplianceGet("cw-logs-result", "/cases/{case_id}/ai-logs",
    "requiere rol <code>admin</code> o <code>compliance</code>");
  cwRenderAiLogs("cw-logs-result", j);
}

// ── 15. Compliance Snapshot ───────────────────────────────────────────

function cwRenderComplianceSnapshot(parts) {
  // parts = { summary, verify, logs, errors: {summary?, verify?, logs?} }
  const s = parts.summary;
  const v = parts.verify;
  const l = parts.logs;
  const err = parts.errors || {};

  const row = (k, v) => `<tr><td style="padding:4px 10px;font-weight:600;color:#4a5568;font-size:12px;">${escapeHTML(k)}</td><td style="padding:4px 10px;font-size:12px;">${v}</td></tr>`;
  const intactBadge = (x) => x === true ? '<span class="pill pill-green">intact</span>'
                            : x === false ? '<span class="pill pill-red">broken</span>'
                            : '<span class="pill pill-grey">—</span>';

  const c   = (s && s.case) || {};
  const p   = (s && s.progress) || {};
  const ai  = (s && s.ai) || {};
  const rep = s && s.current_report;
  const sel = s && s.current_portfolio_selection;
  const app = s && s.current_profile_approval;
  const ovr = s && s.current_override_approval;

  // verify can come from /audit/verify (preferred) o fallback summary.audit
  let auditIntact, auditTotal, auditMsg;
  if (v) {
    auditIntact = v.is_intact;
    auditTotal  = v.total_events;
    auditMsg    = v.message;
  } else if (s && s.audit) {
    auditIntact = s.audit.is_intact;
    auditTotal  = s.audit.total_events;
    auditMsg    = s.audit.message;
  }

  // latest validation_status: prefer /ai-logs (last entry), fallback summary.ai
  let latestValidation = null;
  if (l && Array.isArray(l.logs) && l.logs.length) {
    latestValidation = l.logs[l.logs.length - 1].validation_status;
  } else if (ai.latest_validation_status) {
    latestValidation = ai.latest_validation_status;
  }
  const logsCount = (l && typeof l.count === "number") ? l.count : (ai.ai_logs_count || 0);

  const part = (label, kind) => {
    if (err[kind]) return `<span class="pill pill-grey" style="font-size:10px;">${label}: ${escapeHTML(err[kind])}</span>`;
    return `<span class="pill pill-green" style="font-size:10px;">${label}: ok</span>`;
  };

  el("cw-compliance-result").innerHTML = `
    <div style="margin-bottom:8px;">
      ${part("summary", "summary")}
      ${part("audit/verify", "verify")}
      ${part("ai-logs", "logs")}
    </div>
    <div style="border:1px solid #dde2ea;border-radius:6px;padding:10px;background:#fafbfd;">
      <div style="font-weight:600;color:#2d3748;margin-bottom:8px;">Compliance snapshot · case <code>${escapeHTML(c.case_id || "—")}</code></div>
      <table style="width:100%;border-collapse:collapse;">
        ${row("case status",              `<code>${escapeHTML(c.status || "—")}</code>`)}
        ${row("completion_ratio",         `<strong>${p.completion_ratio !== undefined ? p.completion_ratio : "—"}</strong>`)}
        ${row("next_recommended_action",  `<code>${escapeHTML(p.next_recommended_action || "—")}</code>`)}
        ${row("audit.is_intact",          intactBadge(auditIntact))}
        ${row("audit.total_events",       auditTotal !== undefined && auditTotal !== null ? `<strong>${auditTotal}</strong>` : "—")}
        ${row("audit.message",            escapeHTML(auditMsg || "—"))}
        ${row("ai.ai_logs_count",         `<strong>${logsCount}</strong>`)}
        ${row("ai.latest_validation_status",
              latestValidation ? cwValidationPill(latestValidation) : "—")}
        ${row("current_profile_approval.decision",
              app && app.decision ? `<code>${escapeHTML(app.decision)}</code>` : "—")}
        ${row("current_override_approval.decision",
              ovr && ovr.decision ? `<code>${escapeHTML(ovr.decision)}</code>` : "—")}
        ${row("current_portfolio_selection.selected_variant",
              sel && sel.selected_variant ? `<code>${escapeHTML(sel.selected_variant)}</code>` : "—")}
        ${row("current_report.report_id",
              rep && rep.report_id ? `<code>${escapeHTML(rep.report_id)}</code> (v${rep.version})` : "—")}
      </table>
    </div>
  `;
}

// Lanza summary + audit/verify + ai-logs en paralelo y rinde un panel
// combinado. Cualquier sub-request que falle se reporta como "skipped (HTTP X)"
// en el header sin abortar las otras.
async function cwRefreshComplianceSnapshot() {
  const caseId = cwGetCaseId();
  if (!caseId) {
    cwRenderError("cw-compliance-result", "<strong>case_id requerido</strong> (sección 1).");
    return;
  }
  cwRenderLoading("cw-compliance-result", "Loading summary + audit/verify + ai-logs…");
  const headers = cdAuthHeaders();
  const enc = encodeURIComponent(caseId);
  const [sRes, vRes, lRes] = await Promise.all([
    cdApiFetch(`/cases/${enc}/summary`, { headers }),
    cdApiFetch(`/cases/${enc}/audit/verify`, { headers }),
    cdApiFetch(`/cases/${enc}/ai-logs`, { headers }),
  ]);
  const parts = { summary: null, verify: null, logs: null, errors: {} };
  if (sRes.ok)  parts.summary = sRes.json;
  else          parts.errors.summary = `HTTP ${sRes.status}`;
  if (vRes.ok)  parts.verify = vRes.json;
  else          parts.errors.verify = `HTTP ${vRes.status}`;
  if (lRes.ok)  parts.logs = lRes.json;
  else          parts.errors.logs = `HTTP ${lRes.status}`;

  // Si todo falló por 404 (summary), case probablemente no existe.
  if (!parts.summary && sRes.status === 404) {
    cwRenderError("cw-compliance-result",
      `<strong>404:</strong> case <code>${escapeHTML(caseId)}</code> no encontrado.`);
    return;
  }
  // Mantener cwLastSummary actualizado si vino el summary.
  if (parts.summary) cwAutofillFromSummary(parts.summary);
  cwRenderComplianceSnapshot(parts);
}

