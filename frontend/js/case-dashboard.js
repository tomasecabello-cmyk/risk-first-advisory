// Risk-First Advisory — Case Dashboard (Phase 2)
// Entity CRUD: firms/advisors/clients/cases + summary + quick seed.
// Depends on common.js. cd* helpers (cdToken, cdAuthHeaders, cdApiFetch,
// cdNullIfBlank, cdParseResponse) are also reused by case-workbench.js,
// so this file MUST load before case-workbench.js.

// ═════════════════════════════════════════════════════════════════════════
// CASE DASHBOARD — PHASE 2  (prefijo cd-* para evitar colisiones)
// ═════════════════════════════════════════════════════════════════════════
//
// Reusa helpers existentes: el(), formatJSON(), apiError(), escapeHTML().
// Endpoints: /auth/me, /firms, /advisors, /clients, /cases,
//            /cases/{id}/summary.
// No usa los endpoints workflow case-scoped (KYC, analysis, approval, etc.)
// — esos quedan para Case Workbench en Fase 3.
// ═════════════════════════════════════════════════════════════════════════

// ── helpers ────────────────────────────────────────────────────────────

function cdToken() {
  return (el("cd-token").value || "").trim();
}

function cdAuthHeaders(includeContentType = false) {
  const token = cdToken();
  const headers = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (includeContentType) headers["Content-Type"] = "application/json";
  return headers;
}

function cdClearResult(elId) {
  const target = el(elId);
  if (target) target.innerHTML = "";
}

function cdRenderJson(elId, data, prefixHtml = "") {
  const target = el(elId);
  if (!target) return;
  target.innerHTML = prefixHtml + `<pre class="json-block">${escapeHTML(formatJSON(data))}</pre>`;
}

function cdRenderError(elId, msgHtml) {
  const target = el(elId);
  if (!target) return;
  target.innerHTML = `<div class="msg msg-error">${msgHtml}</div>`;
}

function cdRenderSuccess(elId, msgHtml, data) {
  const target = el(elId);
  if (!target) return;
  const head = `<div class="msg msg-success">${msgHtml}</div>`;
  const body = data !== undefined
    ? `<pre class="json-block" style="margin-top:8px;">${escapeHTML(formatJSON(data))}</pre>`
    : "";
  target.innerHTML = head + body;
}

function cdRenderLoading(elId, msg = "Loading…") {
  const target = el(elId);
  if (target) target.innerHTML = `<div class="msg msg-info"><span class="spinner"></span>${msg}</div>`;
}

// Parsea response: si !ok, devuelve {ok:false, status, detail, json}; si ok, {ok:true, json}.
async function cdParseResponse(r) {
  let json = null;
  try { json = await r.json(); } catch (_) { /* not json */ }
  if (!r.ok) {
    const detail = json && (json.detail || json.message)
      ? (typeof json.detail === "string" ? json.detail : JSON.stringify(json.detail))
      : `HTTP ${r.status}`;
    return { ok: false, status: r.status, detail, json };
  }
  return { ok: true, status: r.status, json };
}

function cdNullIfBlank(v) {
  const s = (v || "").trim();
  return s.length > 0 ? s : null;
}

// Wrapper genérico de fetch que centraliza el manejo de errores de red.
async function cdApiFetch(path, options = {}) {
  try {
    const r = await fetch(`${API}${path}`, options);
    return await cdParseResponse(r);
  } catch (err) {
    return { ok: false, status: 0, detail: err.message || String(err), networkError: true, err };
  }
}

// ── 1. Auth ────────────────────────────────────────────────────────────

async function cdCheckAuth() {
  cdRenderLoading("cd-auth-result", "Calling GET /auth/me…");
  const headers = cdAuthHeaders();
  if (!headers["Authorization"]) {
    cdRenderError("cd-auth-result", "<strong>Token vacío.</strong> Ingresar un Bearer token primero.");
    return;
  }
  const res = await cdApiFetch("/auth/me", { headers });
  if (!res.ok) {
    if (res.networkError) {
      el("cd-auth-result").innerHTML = apiError(res.err);
    } else {
      cdRenderError("cd-auth-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    }
    return;
  }
  const id = res.json && res.json.advisor_id ? res.json.advisor_id : "(unknown)";
  const roles = res.json && Array.isArray(res.json.roles) ? res.json.roles.join(", ") : "—";
  const firm = res.json && res.json.firm_id ? res.json.firm_id : "—";
  cdRenderSuccess(
    "cd-auth-result",
    `<strong>OK</strong> — advisor_id <code>${escapeHTML(id)}</code> · roles <code>${escapeHTML(roles)}</code> · firm_id <code>${escapeHTML(firm)}</code>`,
    res.json,
  );
}

// ── 2. Firms ───────────────────────────────────────────────────────────

async function cdCreateFirm() {
  const body = {
    display_name: (el("cd-firm-name").value || "").trim(),
    country:      (el("cd-firm-country").value || "").trim(),
  };
  const fid = cdNullIfBlank(el("cd-firm-id").value);
  if (fid) body.firm_id = fid;

  cdRenderLoading("cd-firms-result", "Creating firm…");
  const res = await cdApiFetch("/firms", {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 409) {
      cdRenderError("cd-firms-result",
        `<strong>409 duplicate</strong>: ${escapeHTML(res.detail)}. Probar otro <code>firm_id</code> o usar List Firms para reusar el existente.`);
      return;
    }
    if (res.status === 403) {
      cdRenderError("cd-firms-result", `<strong>403 forbidden:</strong> el token actual no tiene rol <code>admin</code>.`);
      return;
    }
    if (res.networkError) { el("cd-firms-result").innerHTML = apiError(res.err); return; }
    cdRenderError("cd-firms-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const firmId = res.json && res.json.firm_id ? res.json.firm_id : "(unknown)";
  // Propagar a inputs downstream
  if (firmId !== "(unknown)") {
    el("cd-advisor-firm-id").value = firmId;
    el("cd-client-firm-id").value  = firmId;
    el("cd-case-firm-id").value    = firmId;
  }
  cdRenderSuccess("cd-firms-result", `Firm creada: <code>${escapeHTML(firmId)}</code>`, res.json);
}

async function cdListFirms() {
  cdRenderLoading("cd-firms-result", "Loading firms…");
  const res = await cdApiFetch("/firms", { headers: cdAuthHeaders() });
  if (!res.ok) {
    if (res.networkError) { el("cd-firms-result").innerHTML = apiError(res.err); return; }
    cdRenderError("cd-firms-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const count = (res.json && typeof res.json.count === "number") ? res.json.count : "?";
  cdRenderSuccess("cd-firms-result", `<strong>${count}</strong> firms encontradas`, res.json);
}

// ── 3. Advisors ────────────────────────────────────────────────────────

function cdParseRolesCSV(raw) {
  return (raw || "")
    .split(",")
    .map(s => s.trim())
    .filter(s => s.length > 0);
}

async function cdCreateAdvisor() {
  const firmId = cdNullIfBlank(el("cd-advisor-firm-id").value);
  if (!firmId) {
    cdRenderError("cd-advisors-result", "<strong>firm_id requerido.</strong>");
    return;
  }
  const roles = cdParseRolesCSV(el("cd-advisor-roles").value);
  if (roles.length === 0) {
    cdRenderError("cd-advisors-result", "<strong>roles requerido</strong> (CSV; e.g. <code>advisor</code>).");
    return;
  }
  const body = {
    firm_id:      firmId,
    display_name: (el("cd-advisor-name").value || "").trim(),
    email:        (el("cd-advisor-email").value || "").trim(),
    roles:        roles,
  };
  const aid = cdNullIfBlank(el("cd-advisor-id").value);
  if (aid) body.advisor_id = aid;

  cdRenderLoading("cd-advisors-result", "Creating advisor…");
  const res = await cdApiFetch("/advisors", {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 409) {
      cdRenderError("cd-advisors-result",
        `<strong>409 duplicate</strong>: ${escapeHTML(res.detail)}. Probar otro <code>advisor_id</code> o usar List Advisors.`);
      return;
    }
    if (res.status === 422) {
      cdRenderError("cd-advisors-result",
        `<strong>422 validation</strong>: ${escapeHTML(res.detail)}. Verificar que <code>firm_id</code> existe.`);
      return;
    }
    if (res.status === 403) {
      cdRenderError("cd-advisors-result", `<strong>403 forbidden:</strong> requiere rol <code>admin</code>.`);
      return;
    }
    if (res.networkError) { el("cd-advisors-result").innerHTML = apiError(res.err); return; }
    cdRenderError("cd-advisors-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const advisorId = res.json && res.json.advisor_id ? res.json.advisor_id : "(unknown)";
  if (advisorId !== "(unknown)") {
    el("cd-client-advisor-id").value = advisorId;
    el("cd-case-advisor-id").value   = advisorId;
  }
  cdRenderSuccess("cd-advisors-result", `Advisor creado: <code>${escapeHTML(advisorId)}</code>`, res.json);
}

async function cdListAdvisors() {
  cdRenderLoading("cd-advisors-result", "Loading advisors…");
  const res = await cdApiFetch("/advisors", { headers: cdAuthHeaders() });
  if (!res.ok) {
    if (res.networkError) { el("cd-advisors-result").innerHTML = apiError(res.err); return; }
    cdRenderError("cd-advisors-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const count = (res.json && typeof res.json.count === "number") ? res.json.count : "?";
  cdRenderSuccess("cd-advisors-result", `<strong>${count}</strong> advisors encontrados`, res.json);
}

// ── 4. Clients ─────────────────────────────────────────────────────────

async function cdCreateClient() {
  const firmId    = cdNullIfBlank(el("cd-client-firm-id").value);
  const advisorId = cdNullIfBlank(el("cd-client-advisor-id").value);
  if (!firmId || !advisorId) {
    cdRenderError("cd-clients-result", "<strong>firm_id y primary_advisor_id son requeridos.</strong>");
    return;
  }
  const body = {
    firm_id:            firmId,
    primary_advisor_id: advisorId,
    display_name:       (el("cd-client-name").value || "").trim(),
  };
  const cid = cdNullIfBlank(el("cd-client-id").value);
  if (cid) body.client_id = cid;

  cdRenderLoading("cd-clients-result", "Creating client…");
  const res = await cdApiFetch("/clients", {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 409) {
      cdRenderError("cd-clients-result",
        `<strong>409 duplicate</strong>: ${escapeHTML(res.detail)}.`);
      return;
    }
    if (res.status === 422) {
      cdRenderError("cd-clients-result",
        `<strong>422 validation</strong>: ${escapeHTML(res.detail)}. Verificar que <code>firm_id</code> y <code>primary_advisor_id</code> existen y pertenecen a la misma firm.`);
      return;
    }
    if (res.status === 403) {
      cdRenderError("cd-clients-result", `<strong>403 forbidden:</strong> requiere rol <code>admin</code> o <code>advisor</code>.`);
      return;
    }
    if (res.networkError) { el("cd-clients-result").innerHTML = apiError(res.err); return; }
    cdRenderError("cd-clients-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const clientId = res.json && res.json.client_id ? res.json.client_id : "(unknown)";
  if (clientId !== "(unknown)") {
    el("cd-case-client-id").value = clientId;
  }
  cdRenderSuccess("cd-clients-result", `Client creado: <code>${escapeHTML(clientId)}</code>`, res.json);
}

async function cdListClients() {
  cdRenderLoading("cd-clients-result", "Loading clients…");
  const res = await cdApiFetch("/clients", { headers: cdAuthHeaders() });
  if (!res.ok) {
    if (res.networkError) { el("cd-clients-result").innerHTML = apiError(res.err); return; }
    cdRenderError("cd-clients-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const count = (res.json && typeof res.json.count === "number") ? res.json.count : "?";
  cdRenderSuccess("cd-clients-result", `<strong>${count}</strong> clients encontrados`, res.json);
}

// ── 5. Cases ───────────────────────────────────────────────────────────

async function cdCreateCase() {
  const firmId    = cdNullIfBlank(el("cd-case-firm-id").value);
  const clientId  = cdNullIfBlank(el("cd-case-client-id").value);
  const advisorId = cdNullIfBlank(el("cd-case-advisor-id").value);
  if (!firmId || !clientId || !advisorId) {
    cdRenderError("cd-cases-result",
      "<strong>firm_id, client_id y lead_advisor_id son requeridos.</strong>");
    return;
  }
  const body = {
    firm_id:         firmId,
    client_id:       clientId,
    lead_advisor_id: advisorId,
    title:           (el("cd-case-title").value || "").trim() || "Untitled case",
  };

  cdRenderLoading("cd-cases-result", "Creating case…");
  const res = await cdApiFetch("/cases", {
    method: "POST",
    headers: cdAuthHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 422) {
      cdRenderError("cd-cases-result",
        `<strong>422 validation</strong>: ${escapeHTML(res.detail)}. Verificar que firm/client/advisor existen y son consistentes (cross-firm).`);
      return;
    }
    if (res.status === 403) {
      cdRenderError("cd-cases-result", `<strong>403 forbidden:</strong> requiere rol <code>admin</code> o <code>advisor</code>.`);
      return;
    }
    if (res.networkError) { el("cd-cases-result").innerHTML = apiError(res.err); return; }
    cdRenderError("cd-cases-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const caseId = res.json && res.json.case_id ? res.json.case_id : "(unknown)";
  if (caseId !== "(unknown)") {
    el("cd-summary-case-id").value = caseId;
  }
  cdRenderSuccess("cd-cases-result",
    `Case creado: <code>${escapeHTML(caseId)}</code> — listo para <strong>Load Summary</strong>.`,
    res.json);
}

async function cdListCases() {
  cdRenderLoading("cd-cases-result", "Loading cases…");
  const res = await cdApiFetch("/cases", { headers: cdAuthHeaders() });
  if (!res.ok) {
    if (res.networkError) { el("cd-cases-result").innerHTML = apiError(res.err); return; }
    cdRenderError("cd-cases-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const count = (res.json && typeof res.json.count === "number") ? res.json.count : "?";
  cdRenderSuccess("cd-cases-result", `<strong>${count}</strong> cases encontrados`, res.json);
}

// ── 6. Quick demo seed ─────────────────────────────────────────────────

async function cdSeedDemo() {
  cdRenderLoading("cd-seed-result", "Seeding demo data…");
  const headers = cdAuthHeaders(true);
  if (!headers["Authorization"]) {
    cdRenderError("cd-seed-result", "<strong>Token vacío.</strong>");
    return;
  }
  const log = [];
  const tag = (lvl, msg) => log.push(`[${lvl}] ${msg}`);

  // Helpers internos: lookup-or-create por entidad.
  // 1. firm
  let firmId = null;
  {
    const body = { display_name: "Firm Demo Local", country: "AR", firm_id: "firm_demo_local" };
    const r = await cdApiFetch("/firms", { method: "POST", headers, body: JSON.stringify(body) });
    if (r.ok) {
      firmId = r.json.firm_id;
      tag("OK", `firm creado: ${firmId}`);
    } else if (r.status === 409) {
      firmId = body.firm_id;
      tag("WARN", `firm ya existía (409): ${firmId} — reusando`);
    } else if (r.status === 403) {
      cdRenderError("cd-seed-result", "<strong>403:</strong> seed requiere rol <code>admin</code>.");
      return;
    } else {
      cdRenderError("cd-seed-result", `firm: HTTP ${r.status} — ${escapeHTML(r.detail || "?")}`);
      return;
    }
  }

  // 2. advisor
  let advisorId = null;
  {
    const body = {
      firm_id:      firmId,
      advisor_id:   "advisor_demo_local",
      display_name: "Advisor Demo Local",
      email:        "advisor@demo.local",
      roles:        ["advisor"],
    };
    const r = await cdApiFetch("/advisors", { method: "POST", headers, body: JSON.stringify(body) });
    if (r.ok) {
      advisorId = r.json.advisor_id;
      tag("OK", `advisor creado: ${advisorId}`);
    } else if (r.status === 409) {
      advisorId = body.advisor_id;
      tag("WARN", `advisor ya existía (409): ${advisorId} — reusando`);
    } else {
      cdRenderError("cd-seed-result", `advisor: HTTP ${r.status} — ${escapeHTML(r.detail || "?")}`);
      return;
    }
  }

  // 3. client
  let clientId = null;
  {
    const body = {
      firm_id:            firmId,
      primary_advisor_id: advisorId,
      client_id:          "client_demo_local",
      display_name:       "Client Demo Local",
    };
    const r = await cdApiFetch("/clients", { method: "POST", headers, body: JSON.stringify(body) });
    if (r.ok) {
      clientId = r.json.client_id;
      tag("OK", `client creado: ${clientId}`);
    } else if (r.status === 409) {
      clientId = body.client_id;
      tag("WARN", `client ya existía (409): ${clientId} — reusando`);
    } else {
      cdRenderError("cd-seed-result", `client: HTTP ${r.status} — ${escapeHTML(r.detail || "?")}`);
      return;
    }
  }

  // 4. case (sin case_id explícito; el backend genera uno auto-incremental).
  let caseId = null;
  {
    const body = {
      firm_id:         firmId,
      client_id:       clientId,
      lead_advisor_id: advisorId,
      title:           "Demo advisory case",
    };
    const r = await cdApiFetch("/cases", { method: "POST", headers, body: JSON.stringify(body) });
    if (r.ok) {
      caseId = r.json.case_id;
      tag("OK", `case creado: ${caseId}`);
    } else {
      cdRenderError("cd-seed-result", `case: HTTP ${r.status} — ${escapeHTML(r.detail || "?")}`);
      return;
    }
  }

  // Propagar a inputs downstream
  el("cd-firm-id").value           = firmId;
  el("cd-advisor-firm-id").value   = firmId;
  el("cd-advisor-id").value        = advisorId;
  el("cd-client-firm-id").value    = firmId;
  el("cd-client-advisor-id").value = advisorId;
  el("cd-client-id").value         = clientId;
  el("cd-case-firm-id").value      = firmId;
  el("cd-case-client-id").value    = clientId;
  el("cd-case-advisor-id").value   = advisorId;
  el("cd-summary-case-id").value   = caseId;

  cdRenderSuccess("cd-seed-result",
    `Seed completo. <strong>case_id:</strong> <code>${escapeHTML(caseId)}</code> — abrir <em>Load Summary</em>.`,
    { firm_id: firmId, advisor_id: advisorId, client_id: clientId, case_id: caseId, log });
}

// ── 7. Case Summary ────────────────────────────────────────────────────

function cdSummaryHighlights(s) {
  if (!s || typeof s !== "object") return "";
  const c   = s.case || {};
  const p   = s.progress || {};
  const a   = s.audit || {};
  const ai  = s.ai || {};
  const rep = s.current_report || null;

  const row = (k, v) => `<tr><td style="padding:4px 10px;font-weight:600;color:#4a5568;font-size:12px;">${escapeHTML(k)}</td><td style="padding:4px 10px;font-size:12px;">${v}</td></tr>`;
  const flagPill = (v) => v ? '<span class="pill pill-green">yes</span>' : '<span class="pill pill-grey">no</span>';
  const statusBadge = (st) => st ? `<span class="pill pill-blue">${escapeHTML(st)}</span>` : "—";
  const intactBadge = (v) => v ? '<span class="pill pill-green">intact</span>' : '<span class="pill pill-red">broken</span>';

  return `
    <div style="border:1px solid #dde2ea;border-radius:6px;padding:10px;margin-bottom:10px;background:#fafbfd;">
      <div style="font-weight:600;color:#2d3748;margin-bottom:8px;">Case overview</div>
      <table style="width:100%;border-collapse:collapse;">
        ${row("case_id",                `<code>${escapeHTML(c.case_id || "—")}</code>`)}
        ${row("status",                 statusBadge(c.status))}
        ${row("client_id",              `<code>${escapeHTML(c.client_id || "—")}</code>`)}
        ${row("lead_advisor_id",        `<code>${escapeHTML(c.lead_advisor_id || "—")}</code>`)}
        ${row("completion_ratio",       `<strong>${(p.completion_ratio !== undefined ? p.completion_ratio : "—")}</strong>`)}
        ${row("next_recommended_action", `<code>${escapeHTML(p.next_recommended_action || "—")}</code>`)}
        ${row("has_kyc",                flagPill(p.has_kyc))}
        ${row("has_ai_profile_analysis", flagPill(p.has_ai_profile_analysis))}
        ${row("has_profile_approval",   flagPill(p.has_profile_approval))}
        ${row("has_investment_preferences", flagPill(p.has_investment_preferences))}
        ${row("has_universe_filter",    flagPill(p.has_universe_filter))}
        ${row("has_portfolio_proposal", flagPill(p.has_portfolio_proposal))}
        ${row("has_override_approval",  flagPill(p.has_override_approval))}
        ${row("has_portfolio_selection", flagPill(p.has_portfolio_selection))}
        ${row("has_report",             flagPill(p.has_report))}
        ${row("audit.is_intact",        intactBadge(a.is_intact))}
        ${row("audit.total_events",     `<code>${a.total_events !== undefined ? a.total_events : "—"}</code>`)}
        ${row("ai.ai_logs_count",       `<code>${ai.ai_logs_count !== undefined ? ai.ai_logs_count : "—"}</code>`)}
        ${row("current_report.report_id", rep && rep.report_id ? `<code>${escapeHTML(rep.report_id)}</code>` : "—")}
      </table>
    </div>
  `;
}

async function cdLoadSummary() {
  const caseId = cdNullIfBlank(el("cd-summary-case-id").value);
  if (!caseId) {
    cdRenderError("cd-summary-result", "<strong>case_id requerido.</strong>");
    return;
  }
  cdRenderLoading("cd-summary-result", `Loading summary for ${escapeHTML(caseId)}…`);
  const res = await cdApiFetch(`/cases/${encodeURIComponent(caseId)}/summary`, {
    headers: cdAuthHeaders(),
  });
  if (!res.ok) {
    if (res.status === 404) {
      cdRenderError("cd-summary-result", `<strong>404:</strong> case <code>${escapeHTML(caseId)}</code> no encontrado.`);
      return;
    }
    if (res.networkError) { el("cd-summary-result").innerHTML = apiError(res.err); return; }
    cdRenderError("cd-summary-result", `<strong>HTTP ${res.status}:</strong> ${escapeHTML(res.detail)}`);
    return;
  }
  const highlights = cdSummaryHighlights(res.json);
  cdRenderJson("cd-summary-result", res.json, highlights);
}


