// Risk-First Advisory — legacy demo handlers
// Cards: health, workflow demo, live portfolio, AI profile, AI follow-up,
// AI universe filter, AI filtered portfolio, advisor decisions Phase-1,
// persisted workflows. Depends on common.js helpers.

// ── 1. health ────────────────────────────────────────────────

async function checkHealth() {
  const out = el("health-result");
  out.className = "msg msg-info";
  out.textContent = "Checking…";
  out.classList.remove("hidden");

  try {
    const r = await fetch(`${API}/health`);
    const data = await r.json();
    if (r.ok) {
      out.className = "msg msg-success";
      out.innerHTML = `<strong>OK</strong> — ${JSON.stringify(data)}`;
    } else {
      out.className = "msg msg-error";
      out.innerHTML = `<strong>HTTP ${r.status}</strong> — ${JSON.stringify(data)}`;
    }
  } catch (err) {
    out.className = "";
    out.innerHTML = apiError(err);
  }
}

// ── 2. run workflow ──────────────────────────────────────────

function buildPayload() {
  const v = id => el(id).value.trim();
  const n = id => parseFloat(el(id).value) || 0;

  const kyc = {
    risk_tolerance_score:      parseInt(el("f-risk_tolerance_score").value),
    risk_capacity_score:       parseInt(el("f-risk_capacity_score").value),
    liquidity_need_score:      parseInt(el("f-liquidity_need_score").value),
    investment_horizon_years:  parseInt(el("f-investment_horizon_years").value),
    investment_experience:     v("f-investment_experience"),
    income_stability:          v("f-income_stability"),
    net_worth:                 n("f-net_worth"),
    liquid_net_worth:          n("f-liquid_net_worth"),
    max_acceptable_drawdown_pct: parseFloat(el("f-max_acceptable_drawdown_pct").value),
  };

  // optional fields — only include if non-empty
  const drep = el("f-declared_return_expectation_pct").value.trim();
  if (drep !== "") kyc.declared_return_expectation_pct = parseFloat(drep);

  const openFields = [
    ["open_investment_goal", "f-open_investment_goal"],
    ["open_risk_reaction",   "f-open_risk_reaction"],
    ["open_past_experience", "f-open_past_experience"],
    ["open_concerns",        "f-open_concerns"],
  ];
  for (const [field, id] of openFields) {
    const val = el(id).value.trim();
    if (val) kyc[field] = val;
  }

  return {
    client_id:  v("f-client_id"),
    advisor_id: v("f-advisor_id"),
    kyc_data:   kyc,
    financial_goal: {
      initial_amount:      n("f-initial_amount"),
      target_amount:       n("f-target_amount"),
      horizon_years:       parseInt(el("f-goal_horizon_years").value),
      annual_contribution: n("f-annual_contribution"),
    },
  };
}

async function runWorkflow(evt) {
  evt.preventDefault();
  const out = el("workflow-result");
  out.innerHTML = "";
  out.classList.remove("hidden");
  setButtonLoading("btn-run", true);

  let payload;
  try { payload = buildPayload(); } catch (e) {
    out.innerHTML = `<div class="msg msg-error">${e.message}</div>`;
    setButtonLoading("btn-run", false);
    return;
  }

  try {
    const r = await fetch(`${API}/workflow/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    let data;
    try { data = await r.json(); } catch (_) { data = null; }

    if (!r.ok) {
      let errHtml = `<div class="msg msg-error"><strong>HTTP ${r.status}</strong>`;
      if (data) {
        if (r.status === 422 && data.detail) {
          errHtml += `<br><br><strong>Validation errors:</strong><ul style="margin-top:6px;padding-left:18px;">`;
          const detail = Array.isArray(data.detail) ? data.detail : [data.detail];
          for (const d of detail) {
            const loc = d.loc ? d.loc.join(" → ") : "";
            errHtml += `<li>${loc ? `<code>${loc}</code>: ` : ""}${d.msg}</li>`;
          }
          errHtml += `</ul>`;
        } else {
          errHtml += `<pre style="margin-top:8px;font-size:12px;">${formatJSON(data)}</pre>`;
        }
      }
      errHtml += `</div>`;
      out.innerHTML = errHtml;
      setButtonLoading("btn-run", false);
      return;
    }

    out.innerHTML = renderWorkflowResult(data);

  } catch (err) {
    out.innerHTML = apiError(err);
  } finally {
    setButtonLoading("btn-run", false);
  }
}

function renderWorkflowResult(data) {
  const records = data.records || {};

  const tickers = data.final_optimizer_tickers || [];
  const reasonCodes = data.reason_codes || [];
  const warnings = data.warnings || [];

  return `
    <div class="result-box">
      <div class="result-summary">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
          <strong style="font-size:15px;">Result</strong>
          ${statusPill(data.status)}
        </div>
        <div class="summary-grid">
          <div class="summary-item">
            <label>client_id</label>
            <div class="value">${data.client_id ?? "—"}</div>
          </div>
          <div class="summary-item">
            <label>approved_profile_name</label>
            <div class="value">${data.approved_profile_name ?? "—"}</div>
          </div>
          <div class="summary-item">
            <label>has_portfolios</label>
            <div class="value">${boolPill(data.has_portfolios)}</div>
          </div>
          <div class="summary-item">
            <label>portfolio_feasibility_status</label>
            <div class="value">${statusPill(data.portfolio_feasibility_status)}</div>
          </div>
          <div class="summary-item">
            <label>candidate_count</label>
            <div class="value">${data.candidate_count ?? "—"}</div>
          </div>
          <div class="summary-item">
            <label>workflow_record_id</label>
            <div class="value" style="font-family:monospace;font-size:12px;">${records.workflow_record_id ?? "—"}</div>
          </div>
          <div class="summary-item">
            <label>audit_record_id</label>
            <div class="value" style="font-family:monospace;font-size:12px;">${records.audit_record_id ?? "—"}</div>
          </div>
          <div class="summary-item">
            <label>report_record_id</label>
            <div class="value" style="font-family:monospace;font-size:12px;">${records.report_record_id ?? "—"}</div>
          </div>
          <div class="summary-item" style="grid-column:1/-1;">
            <label>report_path</label>
            <div class="value" style="font-family:monospace;font-size:11px;word-break:break-all;">${data.report_path ?? "—"}</div>
          </div>
          <div class="summary-item" style="grid-column:1/-1;">
            <label>final_optimizer_tickers (${tickers.length})</label>
            <div class="value">${chips(tickers)}</div>
          </div>
          <div class="summary-item" style="grid-column:1/-1;">
            <label>reason_codes (${reasonCodes.length})</label>
            <div class="value">${chips(reasonCodes, "chip chip-err")}</div>
          </div>
          <div class="summary-item" style="grid-column:1/-1;">
            <label>warnings (${warnings.length})</label>
            <div class="value">${chips(warnings, "chip chip-warn")}</div>
          </div>
        </div>
      </div>

      <details>
        <summary>Full JSON response</summary>
        <pre class="json-block">${escapeHTML(formatJSON(data))}</pre>
      </details>
    </div>
  `;
}

function clearWorkflowResult() {
  const out = el("workflow-result");
  out.innerHTML = "";
  out.classList.add("hidden");
}

function escapeHTML(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ── 3. persisted workflows ───────────────────────────────────

async function loadWorkflows() {
  const out = el("workflows-result");
  out.innerHTML = `<div class="msg msg-info">Loading…</div>`;

  const clientId = el("filter-client_id").value.trim();
  const url = clientId
    ? `${API}/workflow?client_id=${encodeURIComponent(clientId)}`
    : `${API}/workflow`;

  try {
    const r = await fetch(url);
    const data = await r.json();

    if (!r.ok) {
      out.innerHTML = `<div class="msg msg-error"><strong>HTTP ${r.status}</strong> — ${JSON.stringify(data)}</div>`;
      return;
    }

    const records = data.records || [];
    if (!records.length) {
      out.innerHTML = `<div class="msg msg-info">No workflows found${clientId ? ` for client <strong>${clientId}</strong>` : ""}.</div>`;
      return;
    }

    let rows = records.map(rec => {
      const payload = rec.payload || {};
      const meta    = rec.metadata || {};
      const status  = payload.status ?? "—";
      const client  = meta.client_id ?? payload.client_id ?? "—";
      const created = rec.created_at_utc ?? "—";
      return `<tr>
        <td class="mono">${rec.record_id ?? "—"}</td>
        <td>${client}</td>
        <td>${statusPill(status)}</td>
        <td style="font-size:12px;color:#718096;">${created}</td>
      </tr>`;
    }).join("");

    out.innerHTML = `
      <div class="msg msg-success" style="margin-bottom:10px;">
        Loaded <strong>${records.length}</strong> workflow${records.length !== 1 ? "s" : ""}
        ${clientId ? ` for client <strong>${clientId}</strong>` : ""}.
      </div>
      <div class="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>record_id</th>
              <th>client_id</th>
              <th>status</th>
              <th>created_at_utc</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <details style="margin-top:10px;">
        <summary>Full JSON response</summary>
        <pre class="json-block">${escapeHTML(formatJSON(data))}</pre>
      </details>
    `;

  } catch (err) {
    out.innerHTML = apiError(err);
  }
}

function clearWorkflowsTable() {
  el("workflows-result").innerHTML = "";
}

// ── 3. live portfolio demo ───────────────────────────────────

function setLiveButtonLoading(loading) {
  const btn = el("btn-live");
  if (!btn) return;
  btn.disabled = loading;
  btn.innerHTML = loading
    ? `<span class="spinner"></span>Downloading & generating…`
    : "Run Live Portfolio";
}

async function runLivePortfolio() {
  const out = el("live-result");
  out.innerHTML = `<div class="msg msg-info" style="margin-top:16px;">
    <span class="spinner" style="border-color:rgba(30,64,175,0.3);border-top-color:#1e40af;"></span>
    Downloading market data and generating portfolios…
  </div>`;
  out.classList.remove("hidden");
  setLiveButtonLoading(true);

  const payload = {
    profile:  el("lp-profile").value,
    period:   el("lp-period").value,
    interval: el("lp-interval").value.split(" ")[0],   // strip "(daily)" suffix
  };

  try {
    const r = await fetch(`${API}/live/portfolio-demo`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    let data;
    try { data = await r.json(); } catch (_) { data = null; }

    if (!r.ok) {
      let errHtml = `<div class="msg msg-error" style="margin-top:16px;"><strong>HTTP ${r.status}</strong>`;
      if (data) {
        if (r.status === 422 && data.detail) {
          errHtml += `<br><strong>Detail:</strong> ${typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail)}`;
        } else {
          errHtml += `<pre style="margin-top:8px;font-size:12px;">${escapeHTML(formatJSON(data))}</pre>`;
        }
      }
      errHtml += `</div>`;
      out.innerHTML = errHtml;
      return;
    }

    out.innerHTML = renderLivePortfolioResult(data);

  } catch (err) {
    out.innerHTML = `<div style="margin-top:16px;">${apiError(err)}</div>`;
  } finally {
    setLiveButtonLoading(false);
  }
}

function clearLivePortfolioResult() {
  const out = el("live-result");
  out.innerHTML = "";
  out.classList.add("hidden");
  setLiveButtonLoading(false);
}

function pct(v) {
  return (v * 100).toFixed(2) + "%";
}

function liveStatusPill(status) {
  if (status === "completed")        return `<span class="pill pill-green">completed</span>`;
  if (status === "insufficient_data") return `<span class="pill pill-orange">insufficient_data</span>`;
  if (status === "infeasible")       return `<span class="pill pill-red">infeasible</span>`;
  return `<span class="pill pill-grey">${status}</span>`;
}

function renderLivePortfolioResult(data) {
  const status = data.status ?? "—";
  const candidates = data.candidates ?? [];
  const dqWarnings = data.dq_warnings ?? [];

  // ── summary section ──────────────────────────────────────
  let summaryHtml = `
    <div class="result-summary">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
        <strong style="font-size:15px;">Result</strong>
        ${liveStatusPill(status)}
      </div>

      ${(status === "insufficient_data" || status === "infeasible") ? `
        <div class="live-status-box ${status === "infeasible" ? "status-infeasible" : "status-insufficient"}" style="margin-bottom:10px;">
          <div class="status-title">${status === "infeasible" ? "⚠ No feasible portfolio" : "⚠ Insufficient market data"}</div>
          <div class="status-msg">${escapeHTML(data.message ?? "")}</div>
        </div>
      ` : ""}

      <div class="summary-grid">
        <div class="summary-item">
          <label>profile</label>
          <div class="value"><strong>${data.profile ?? "—"}</strong></div>
        </div>
        <div class="summary-item">
          <label>period / interval</label>
          <div class="value">${data.period ?? "—"} · ${data.interval ?? "—"}</div>
        </div>
        <div class="summary-item">
          <label>total_tickers</label>
          <div class="value">${data.total_tickers ?? "—"}</div>
        </div>
        <div class="summary-item">
          <label>usable_snapshots</label>
          <div class="value">${data.usable_snapshots ?? "—"}</div>
        </div>
        <div class="summary-item">
          <label>failed_or_missing</label>
          <div class="value">${data.failed_or_missing ?? "—"}</div>
        </div>
        <div class="summary-item">
          <label>candidate_count</label>
          <div class="value"><strong>${data.candidate_count ?? 0}</strong></div>
        </div>
        ${status === "completed" ? `
        <div class="summary-item" style="grid-column:1/-1;">
          <label>message</label>
          <div class="value" style="color:#166534;">${escapeHTML(data.message ?? "")}</div>
        </div>` : ""}
        <div class="summary-item" style="grid-column:1/-1;">
          <label>dq_warnings (${dqWarnings.length})</label>
          <div class="value">
            ${dqWarnings.length
              ? `<div class="list-chips">${dqWarnings.map(w => `<span class="chip chip-warn">${escapeHTML(w)}</span>`).join("")}</div>`
              : `<span style="color:#a0aec0;font-size:12px;">none</span>`
            }
          </div>
        </div>
      </div>
    </div>
  `;

  // ── candidate portfolios ─────────────────────────────────
  let candidatesHtml = "";
  if (candidates.length > 0) {
    candidatesHtml = `
      <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
        <div style="font-size:13px;font-weight:700;color:#1a2744;margin-bottom:12px;">
          Candidate Portfolios
        </div>
        ${candidates.map(renderPortfolioCandidate).join("")}
      </div>
    `;
  }

  // ── json collapsible ─────────────────────────────────────
  const jsonHtml = `
    <details>
      <summary>Full JSON response</summary>
      <pre class="json-block">${escapeHTML(formatJSON(data))}</pre>
    </details>
  `;

  return `<div class="result-box" style="margin-top:20px;">${summaryHtml}${candidatesHtml}${jsonHtml}</div>`;
}

// ── 4. AI profile demo ──────────────────────────────────────

function setAIButtonLoading(loading) {
  const btn = el("btn-ai");
  if (!btn) return;
  btn.disabled = loading;
  btn.innerHTML = loading
    ? `<span class="spinner"></span>Calling OpenAI profile analysis…`
    : "Analyze KYC with AI";
}

function buildAIProfilePayload() {
  const v  = id => el(id).value.trim();
  const n  = id => parseFloat(el(id).value) || 0;
  const ni = id => parseInt(el(id).value);

  const kyc = {
    risk_tolerance_score:        ni("ai-risk_tolerance_score"),
    risk_capacity_score:         ni("ai-risk_capacity_score"),
    liquidity_need_score:        ni("ai-liquidity_need_score"),
    investment_horizon_years:    ni("ai-investment_horizon_years"),
    max_acceptable_drawdown_pct: parseFloat(el("ai-max_acceptable_drawdown_pct").value),
    investment_experience:       v("ai-investment_experience"),
    income_stability:            v("ai-income_stability"),
    net_worth:                   n("ai-net_worth"),
    liquid_net_worth:            n("ai-liquid_net_worth"),
  };

  const drep = el("ai-declared_return_expectation_pct").value.trim();
  if (drep !== "") kyc.declared_return_expectation_pct = parseFloat(drep);

  const openFields = [
    ["open_investment_goal", "ai-open_investment_goal"],
    ["open_risk_reaction",   "ai-open_risk_reaction"],
    ["open_past_experience", "ai-open_past_experience"],
    ["open_concerns",        "ai-open_concerns"],
  ];
  for (const [field, id] of openFields) {
    const val = el(id).value.trim();
    if (val) kyc[field] = val;
  }

  return { client_id: v("ai-client_id"), kyc_payload: kyc };
}

async function runAIProfile() {
  const out       = el("ai-result");
  const fuOut     = el("ai-followup-result");
  out.innerHTML   = `<div class="msg msg-info" style="margin-top:16px;">
    <span class="spinner" style="border-color:rgba(30,64,175,0.3);border-top-color:#1e40af;"></span>
    Calling OpenAI profile analysis…
  </div>`;
  out.classList.remove("hidden");
  // Clear any previous follow-up result
  fuOut.innerHTML = "";
  fuOut.classList.add("hidden");
  lastAIProfileRequestPayload = null;
  lastAIProfileResponse       = null;
  setAIButtonLoading(true);

  let payload;
  try { payload = buildAIProfilePayload(); } catch (e) {
    out.innerHTML = `<div class="msg msg-error" style="margin-top:16px;">${e.message}</div>`;
    setAIButtonLoading(false);
    return;
  }

  try {
    const r = await fetch(`${API}/ai/profile-demo`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
    });

    let data;
    try { data = await r.json(); } catch (_) { data = null; }

    if (!r.ok) {
      let errHtml = `<div class="msg msg-error" style="margin-top:16px;">`;

      if (r.status === 400) {
        errHtml += `<strong>⚠ OPENAI_API_KEY is not configured in the backend terminal.</strong><br>
          <span style="font-size:12px;">Set the environment variable before starting uvicorn:</span>
          <div style="margin-top:8px;padding:7px 10px;background:#fee2e2;border-radius:4px;font-family:'Menlo','Consolas',monospace;font-size:11px;color:#991b1b;">
            $env:OPENAI_API_KEY="your_key_here"<br>
            uvicorn risk_first_advisory.api_layer.main:app --reload
          </div>`;
      } else if (r.status === 502) {
        errHtml += `<strong>AI profile analysis failed.</strong> Check backend logs or API key.<br>
          <span style="font-size:12px;color:#718096;">${data && data.detail ? escapeHTML(String(data.detail)) : ""}</span>`;
      } else if (r.status === 422 && data && data.detail) {
        errHtml += `<strong>HTTP 422 — Validation errors:</strong><ul style="margin-top:6px;padding-left:18px;">`;
        const detail = Array.isArray(data.detail) ? data.detail : [data.detail];
        for (const d of detail) {
          const loc = d.loc ? d.loc.join(" → ") : "";
          errHtml += `<li>${loc ? `<code>${loc}</code>: ` : ""}${escapeHTML(d.msg)}</li>`;
        }
        errHtml += `</ul>`;
      } else {
        errHtml += `<strong>HTTP ${r.status}</strong>`;
        if (data) errHtml += `<pre style="margin-top:8px;font-size:12px;">${escapeHTML(formatJSON(data))}</pre>`;
      }

      errHtml += `</div>`;
      out.innerHTML = errHtml;
      return;
    }

    // Store state for follow-up round
    lastAIProfileRequestPayload = payload;
    lastAIProfileResponse       = data;
    out.innerHTML = renderAIProfileResult(data);

  } catch (err) {
    if (err.name === "TypeError" && err.message.includes("fetch")) {
      out.innerHTML = `<div class="msg msg-error" style="margin-top:16px;">
        <strong>API not reachable.</strong> Start uvicorn first:<br>
        <code style="font-size:12px;">uvicorn risk_first_advisory.api_layer.main:app --reload</code>
      </div>`;
    } else {
      out.innerHTML = `<div style="margin-top:16px;">${apiError(err)}</div>`;
    }
  } finally {
    setAIButtonLoading(false);
  }
}

function clearAIProfileResult() {
  const out   = el("ai-result");
  const fuOut = el("ai-followup-result");
  out.innerHTML   = "";
  out.classList.add("hidden");
  fuOut.innerHTML = "";
  fuOut.classList.add("hidden");
  lastAIProfileRequestPayload = null;
  lastAIProfileResponse       = null;
  setAIButtonLoading(false);
}

function copyProfileToLiveDemo(profile, msgElId = "ai-copy-profile-msg") {
  const select  = el("lp-profile");
  const msgEl   = el(msgElId);

  // Check the profile exists as an <option> in the Live Portfolio selector.
  const available = Array.from(select.options).map(o => o.value);
  if (!available.includes(profile)) {
    if (msgEl) {
      Object.assign(msgEl.style, {
        display: "block",
        background: "#fef2f2",
        border: "1px solid #fca5a5",
        color: "#991b1b",
      });
      msgEl.textContent = `Profile not available in Live Portfolio Demo: "${profile}"`;
    }
    return;
  }

  // Copy the profile into the selector.
  select.value = profile;

  if (msgEl) {
    Object.assign(msgEl.style, {
      display: "block",
      background: "#f0fdf4",
      border: "1px solid #86efac",
      color: "#166534",
    });
    msgEl.innerHTML = `Profile copied to Live Portfolio Demo: <strong>${escapeHTML(profile)}</strong>`;
    setTimeout(() => { if (msgEl) msgEl.style.display = "none"; }, 5000);
  }

  // Scroll smoothly to the Live Portfolio Demo section.
  const card = el("card-live-portfolio");
  if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
}

function severityPill(sev) {
  const s = String(sev ?? "").toLowerCase();
  if (s === "high")   return `<span class="pill pill-red"   style="font-size:10px;">HIGH</span>`;
  if (s === "medium") return `<span class="pill pill-orange" style="font-size:10px;">MED</span>`;
  return `<span class="pill pill-grey" style="font-size:10px;">LOW</span>`;
}

function severityClass(sev) {
  const s = String(sev ?? "").toLowerCase();
  if (s === "high")   return "contradiction-card severity-high";
  if (s === "medium") return "contradiction-card severity-medium";
  return "contradiction-card severity-low";
}

function renderAIProfileResult(data) {
  const contradictions = data.contradictions        ?? [];
  const followUps      = data.follow_up_questions   ?? [];
  const advisorNotes   = data.advisor_notes         ?? [];
  const confidence     = typeof data.confidence === "number" ? data.confidence : 0;
  const confidencePct  = Math.round(confidence * 100);

  // ── profile summary ──────────────────────────────────
  const summaryHtml = `
    <div class="result-summary">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
        <strong style="font-size:15px;">AI Preliminary Profile</strong>
        <span class="pill pill-blue" style="font-size:12px;padding:3px 10px;">${escapeHTML(data.preliminary_profile ?? "—")}</span>
      </div>
      <div class="summary-grid">
        <div class="summary-item">
          <label>client_id</label>
          <div class="value">${escapeHTML(data.client_id ?? "—")}</div>
        </div>
        <div class="summary-item">
          <label>preliminary_profile</label>
          <div class="value"><strong>${escapeHTML(data.preliminary_profile ?? "—")}</strong></div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;">
          <label>confidence</label>
          <div class="value">
            <div style="display:flex;align-items:center;gap:12px;margin-top:4px;">
              <span style="font-size:17px;font-weight:700;color:#1a2744;min-width:46px;">${confidencePct}%</span>
              <div class="confidence-bar-track">
                <div class="confidence-bar-fill" style="width:${confidencePct}%;"></div>
              </div>
            </div>
          </div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;padding-top:4px;">
          <button class="btn-secondary btn-sm"
                  onclick="copyProfileToLiveDemo('${data.preliminary_profile}')">
            ↓ Use this profile in Live Portfolio Demo
          </button>
          <div id="ai-copy-profile-msg"
               style="display:none;margin-top:8px;padding:7px 12px;border-radius:4px;font-size:12px;"></div>
        </div>
      </div>
    </div>
  `;

  // ── contradictions ────────────────────────────────────
  const contradictionsHtml = contradictions.length > 0 ? `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title">Contradictions (${contradictions.length})</div>
      ${contradictions.map(c => `
        <div class="${severityClass(c.severity)}">
          <div class="contradiction-header">
            ${severityPill(c.severity)}
            <span class="contradiction-field">${escapeHTML(c.field ?? "")}</span>
          </div>
          <div class="contradiction-explanation">${escapeHTML(c.explanation ?? "")}</div>
        </div>
      `).join("")}
    </div>
  ` : `
    <div style="padding:12px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title">Contradictions</div>
      <span style="color:#a0aec0;font-size:12px;">None detected.</span>
    </div>
  `;

  // ── follow-up questions ──────────────────────────────
  const followUpHtml = followUps.length > 0 ? `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title">Follow-up Questions (${followUps.length})</div>
      <ol class="numbered-list">
        ${followUps.map(q => `<li>${escapeHTML(q)}</li>`).join("")}
      </ol>
    </div>
  ` : "";

  // ── follow-up answer form (only if there are follow-up questions) ────
  const followupFormHtml = followUps.length > 0 ? `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;background:#f8faff;">
      <div class="ai-section-title" style="margin-bottom:12px;">Answer Follow-up Questions</div>
      ${followUps.map((q, i) => `
        <div style="margin-bottom:14px;">
          <label style="display:block;font-size:12px;font-weight:600;color:#374151;margin-bottom:4px;">
            ${i + 1}. ${escapeHTML(q)}
          </label>
          <textarea
            id="fu-answer-${i}"
            rows="2"
            placeholder="Your answer…"
            style="width:100%;padding:7px 10px;border:1px solid #d1d5db;border-radius:5px;font-size:13px;font-family:inherit;resize:vertical;background:#fff;"
          ></textarea>
        </div>
      `).join("")}
      <div id="fu-validation-msg" style="display:none;margin-bottom:8px;padding:7px 10px;background:#fef2f2;border:1px solid #fca5a5;border-radius:4px;color:#991b1b;font-size:12px;"></div>
      <button class="btn-primary btn-sm" onclick="submitFollowUpAnswers()">
        Submit Follow-up Answers
      </button>
    </div>
  ` : "";

  // ── advisor notes ────────────────────────────────────
  const advisorNotesHtml = advisorNotes.length > 0 ? `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title">Advisor Notes (${advisorNotes.length})</div>
      <ol class="numbered-list">
        ${advisorNotes.map(n => `<li>${escapeHTML(n)}</li>`).join("")}
      </ol>
    </div>
  ` : "";

  // ── json collapsible ─────────────────────────────────
  const jsonHtml = `
    <details>
      <summary>Full JSON response</summary>
      <pre class="json-block">${escapeHTML(formatJSON(data))}</pre>
    </details>
  `;

  return `<div class="result-box" style="margin-top:20px;">${summaryHtml}${contradictionsHtml}${followUpHtml}${followupFormHtml}${advisorNotesHtml}${jsonHtml}</div>`;
}

// ── 4b. AI profile follow-up ────────────────────────────────

async function submitFollowUpAnswers() {
  if (!lastAIProfileRequestPayload || !lastAIProfileResponse) {
    return; // should not happen if the form is visible
  }

  // Collect follow-up questions from the stored first-round response
  const followUps = lastAIProfileResponse.follow_up_questions ?? [];

  // Validate: all answers must be non-empty
  const validationMsgEl = el("fu-validation-msg");
  const answers = [];
  let hasEmpty = false;
  for (let i = 0; i < followUps.length; i++) {
    const textarea = el(`fu-answer-${i}`);
    const answer   = textarea ? textarea.value.trim() : "";
    if (!answer) { hasEmpty = true; }
    answers.push({ question: followUps[i], answer });
  }
  if (hasEmpty) {
    if (validationMsgEl) {
      validationMsgEl.style.display = "block";
      validationMsgEl.textContent   = "All answers are required before submitting.";
    }
    return;
  }
  if (validationMsgEl) validationMsgEl.style.display = "none";

  // Build the follow-up request payload
  const followupPayload = {
    client_id:            lastAIProfileRequestPayload.client_id,
    original_kyc_payload: lastAIProfileRequestPayload.kyc_payload,
    previous_analysis:    lastAIProfileResponse,
    follow_up_answers:    answers,
  };

  // Show spinner in the follow-up result area
  const fuOut = el("ai-followup-result");
  fuOut.innerHTML = `<div class="msg msg-info" style="margin-top:16px;">
    <span class="spinner" style="border-color:rgba(30,64,175,0.3);border-top-color:#1e40af;"></span>
    Calling OpenAI follow-up analysis…
  </div>`;
  fuOut.classList.remove("hidden");

  try {
    const r = await fetch(`${API}/ai/profile-follow-up`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(followupPayload),
    });

    let data;
    try { data = await r.json(); } catch (_) { data = null; }

    if (!r.ok) {
      let errHtml = `<div class="msg msg-error" style="margin-top:16px;">`;

      if (r.status === 400) {
        errHtml += `<strong>⚠ OPENAI_API_KEY is not configured in the backend terminal.</strong><br>
          <span style="font-size:12px;">Set the environment variable before starting uvicorn.</span>`;
      } else if (r.status === 502) {
        errHtml += `<strong>AI follow-up analysis failed.</strong> Check backend logs or API key.<br>
          <span style="font-size:12px;color:#718096;">${data && data.detail ? escapeHTML(String(data.detail)) : ""}</span>`;
      } else if (r.status === 422 && data && data.detail) {
        errHtml += `<strong>HTTP 422 — Validation errors:</strong><ul style="margin-top:6px;padding-left:18px;">`;
        const detail = Array.isArray(data.detail) ? data.detail : [data.detail];
        for (const d of detail) {
          const loc = d.loc ? d.loc.join(" → ") : "";
          errHtml += `<li>${loc ? `<code>${loc}</code>: ` : ""}${escapeHTML(d.msg)}</li>`;
        }
        errHtml += `</ul>`;
      } else {
        errHtml += `<strong>HTTP ${r.status}</strong>`;
        if (data) errHtml += `<pre style="margin-top:8px;font-size:12px;">${escapeHTML(formatJSON(data))}</pre>`;
      }

      errHtml += `</div>`;
      fuOut.innerHTML = errHtml;
      return;
    }

    fuOut.innerHTML = renderFollowUpResult(data);

  } catch (err) {
    if (err.name === "TypeError" && err.message.includes("fetch")) {
      fuOut.innerHTML = `<div class="msg msg-error" style="margin-top:16px;">
        <strong>API not reachable.</strong> Start uvicorn first:<br>
        <code style="font-size:12px;">uvicorn risk_first_advisory.api_layer.main:app --reload</code>
      </div>`;
    } else {
      fuOut.innerHTML = `<div style="margin-top:16px;">${apiError(err)}</div>`;
    }
  }
}

function renderFollowUpResult(data) {
  const remaining    = data.remaining_contradictions ?? [];
  const advisorNotes = data.advisor_notes            ?? [];
  const confidence   = typeof data.confidence === "number" ? data.confidence : 0;
  const confidencePct = Math.round(confidence * 100);

  // ── summary ──────────────────────────────────────────
  const summaryHtml = `
    <div class="result-summary">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap;">
        <strong style="font-size:15px;">AI Revised Profile</strong>
        <span class="pill pill-green" style="font-size:12px;padding:3px 10px;">${escapeHTML(data.revised_profile ?? "—")}</span>
        <span class="pill pill-grey"  style="font-size:11px;padding:2px 8px;">second round</span>
      </div>
      <div class="summary-grid">
        <div class="summary-item">
          <label>client_id</label>
          <div class="value">${escapeHTML(data.client_id ?? "—")}</div>
        </div>
        <div class="summary-item">
          <label>revised_profile</label>
          <div class="value"><strong>${escapeHTML(data.revised_profile ?? "—")}</strong></div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;">
          <label>confidence</label>
          <div class="value">
            <div style="display:flex;align-items:center;gap:12px;margin-top:4px;">
              <span style="font-size:17px;font-weight:700;color:#1a2744;min-width:46px;">${confidencePct}%</span>
              <div class="confidence-bar-track">
                <div class="confidence-bar-fill" style="width:${confidencePct}%;"></div>
              </div>
            </div>
          </div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;padding-top:4px;">
          <button class="btn-secondary btn-sm"
                  onclick="copyProfileToLiveDemo('${escapeHTML(data.revised_profile ?? "")}', 'ai-copy-revised-profile-msg')">
            ↓ Use revised profile in Live Portfolio Demo
          </button>
          <div id="ai-copy-revised-profile-msg"
               style="display:none;margin-top:8px;padding:7px 12px;border-radius:4px;font-size:12px;"></div>
        </div>
      </div>
    </div>
  `;

  // ── profile change reason ────────────────────────────
  const changeReasonHtml = data.profile_change_reason ? `
    <div style="padding:14px 20px;border-bottom:1px solid #86efac;">
      <div class="ai-section-title">Profile Change Reason</div>
      <div style="margin-top:8px;padding:10px 14px;background:#f0fdf4;border:1px solid #86efac;border-radius:6px;color:#166534;font-size:13px;line-height:1.5;">
        ${escapeHTML(data.profile_change_reason)}
      </div>
    </div>
  ` : "";

  // ── remaining contradictions ─────────────────────────
  const remainingHtml = remaining.length > 0 ? `
    <div style="padding:16px 20px;border-bottom:1px solid #86efac;">
      <div class="ai-section-title">Remaining Contradictions (${remaining.length})</div>
      ${remaining.map(c => `
        <div class="${severityClass(c.severity)}">
          <div class="contradiction-header">
            ${severityPill(c.severity)}
            <span class="contradiction-field">${escapeHTML(c.field ?? "")}</span>
          </div>
          <div class="contradiction-explanation">${escapeHTML(c.explanation ?? "")}</div>
        </div>
      `).join("")}
    </div>
  ` : `
    <div style="padding:12px 20px;border-bottom:1px solid #86efac;">
      <div class="ai-section-title">Remaining Contradictions</div>
      <span style="color:#a0aec0;font-size:12px;">None remaining — all contradictions resolved.</span>
    </div>
  `;

  // ── advisor notes ────────────────────────────────────
  const advisorNotesHtml = advisorNotes.length > 0 ? `
    <div style="padding:16px 20px;border-bottom:1px solid #86efac;">
      <div class="ai-section-title">Advisor Notes (${advisorNotes.length})</div>
      <ol class="numbered-list">
        ${advisorNotes.map(n => `<li>${escapeHTML(n)}</li>`).join("")}
      </ol>
    </div>
  ` : "";

  // ── json collapsible ─────────────────────────────────
  const jsonHtml = `
    <details>
      <summary>Full JSON response</summary>
      <pre class="json-block">${escapeHTML(formatJSON(data))}</pre>
    </details>
  `;

  return `<div class="result-box" style="margin-top:20px;border-color:#86efac;">${summaryHtml}${changeReasonHtml}${remainingHtml}${advisorNotesHtml}${jsonHtml}</div>`;
}

// ── 5. AI universe filter demo ──────────────────────────────────

function setAIFilterButtonLoading(loading) {
  const btn = el("btn-aif");
  if (!btn) return;
  btn.disabled = loading;
  btn.innerHTML = loading
    ? `<span class="spinner"></span>Calling OpenAI and filtering instrument universe…`
    : "Filter Universe with AI";
}

async function runAIUniverseFilter() {
  const out = el("aif-result");
  out.innerHTML = `<div class="msg msg-info" style="margin-top:16px;">
    <span class="spinner" style="border-color:rgba(30,64,175,0.3);border-top-color:#1e40af;"></span>
    Calling OpenAI and filtering instrument universe…
  </div>`;
  out.classList.remove("hidden");
  setAIFilterButtonLoading(true);

  const clientId = el("aif-client_id").value.trim();
  const prefs    = el("aif-preferences").value.trim();

  if (!clientId || !prefs) {
    out.innerHTML = `<div class="msg msg-error" style="margin-top:16px;">
      <strong>client_id</strong> and <strong>natural_language_preferences</strong> are required.
    </div>`;
    setAIFilterButtonLoading(false);
    return;
  }

  const payload = {
    client_id: clientId,
    natural_language_preferences: prefs,
    kyc_context: null,
    previous_profile_analysis: null,
  };

  try {
    const r = await fetch(`${API}/ai/filter-universe-demo`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
    });

    let data;
    try { data = await r.json(); } catch (_) { data = null; }

    if (!r.ok) {
      let errHtml = `<div class="msg msg-error" style="margin-top:16px;">`;

      if (r.status === 400) {
        errHtml += `<strong>⚠ OPENAI_API_KEY is not configured in the backend terminal.</strong><br>
          <span style="font-size:12px;">Set the environment variable before starting uvicorn:</span>
          <div style="margin-top:8px;padding:7px 10px;background:#fee2e2;border-radius:4px;font-family:'Menlo','Consolas',monospace;font-size:11px;color:#991b1b;">
            $env:OPENAI_API_KEY="your_key_here"<br>
            uvicorn risk_first_advisory.api_layer.main:app --reload
          </div>`;
      } else if (r.status === 502) {
        errHtml += `<strong>AI universe filtering failed.</strong> Check backend logs or API key.<br>
          <span style="font-size:12px;color:#718096;">${data && data.detail ? escapeHTML(String(data.detail)) : ""}</span>`;
      } else if (r.status === 500) {
        errHtml += `<strong>HTTP 500</strong> — Instrument universe fixture not found on the server.`;
      } else if (r.status === 422 && data && data.detail) {
        errHtml += `<strong>HTTP 422 — Validation errors:</strong><ul style="margin-top:6px;padding-left:18px;">`;
        const detail = Array.isArray(data.detail) ? data.detail : [{ msg: String(data.detail) }];
        for (const d of detail) {
          const loc = d.loc ? d.loc.join(" → ") : "";
          errHtml += `<li>${loc ? `<code>${loc}</code>: ` : ""}${escapeHTML(d.msg ?? String(d))}</li>`;
        }
        errHtml += `</ul>`;
      } else {
        errHtml += `<strong>HTTP ${r.status}</strong>`;
        if (data) errHtml += `<pre style="margin-top:8px;font-size:12px;">${escapeHTML(formatJSON(data))}</pre>`;
      }

      errHtml += `</div>`;
      out.innerHTML = errHtml;
      return;
    }

    out.innerHTML = renderAIUniverseFilterResult(data);

  } catch (err) {
    if (err.name === "TypeError" && err.message.includes("fetch")) {
      out.innerHTML = `<div class="msg msg-error" style="margin-top:16px;">
        <strong>API not reachable.</strong> Start uvicorn first:<br>
        <code style="font-size:12px;">uvicorn risk_first_advisory.api_layer.main:app --reload</code>
      </div>`;
    } else {
      out.innerHTML = `<div style="margin-top:16px;">${apiError(err)}</div>`;
    }
  } finally {
    setAIFilterButtonLoading(false);
  }
}

function clearAIUniverseFilterResult() {
  const out = el("aif-result");
  out.innerHTML = "";
  out.classList.add("hidden");
  setAIFilterButtonLoading(false);
}

function nullOrDash(v) {
  if (v === null || v === undefined) return '<span style="color:#a0aec0;">—</span>';
  return escapeHTML(String(v));
}

function boolNullPill(v) {
  if (v === true)  return '<span class="pill pill-green">true</span>';
  if (v === false) return '<span class="pill pill-grey">false</span>';
  return '<span style="color:#a0aec0;">—</span>';
}

function renderAIUniverseFilterResult(data) {
  const prefs      = data.preferences         ?? {};
  const eligible   = data.eligible_instruments ?? [];
  const exclusions = data.exclusions           ?? [];
  const filters    = data.applied_filters      ?? [];
  const warnings   = data.warnings             ?? [];
  const confidence    = typeof prefs.confidence === "number" ? prefs.confidence : 0;
  const confidencePct = Math.round(confidence * 100);

  // ── 1. Summary ─────────────────────────────────────────────
  const summaryHtml = `
    <div class="result-summary">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap;">
        <strong style="font-size:15px;">AI Universe Filter Result</strong>
        <span class="pill pill-green" style="font-size:11px;">${data.eligible_count ?? 0} eligible</span>
        <span class="pill pill-red"   style="font-size:11px;">${data.excluded_count ?? 0} excluded</span>
      </div>
      <div class="summary-grid">
        <div class="summary-item">
          <label>client_id</label>
          <div class="value">${escapeHTML(data.client_id ?? "—")}</div>
        </div>
        <div class="summary-item">
          <label>confidence</label>
          <div class="value">
            <div style="display:flex;align-items:center;gap:10px;margin-top:2px;">
              <span style="font-size:15px;font-weight:700;color:#1a2744;min-width:42px;">${confidencePct}%</span>
              <div class="confidence-bar-track">
                <div class="confidence-bar-fill" style="width:${confidencePct}%;"></div>
              </div>
            </div>
          </div>
        </div>
        <div class="summary-item">
          <label>entity</label>
          <div class="value">${nullOrDash(prefs.entity)}</div>
        </div>
        <div class="summary-item">
          <label>currency</label>
          <div class="value">${nullOrDash(prefs.currency)}</div>
        </div>
        <div class="summary-item">
          <label>country</label>
          <div class="value">${nullOrDash(prefs.country)}</div>
        </div>
        <div class="summary-item">
          <label>hard_dollar_only</label>
          <div class="value">${boolNullPill(prefs.hard_dollar_only)}</div>
        </div>
      </div>
    </div>
  `;

  // ── 2. Preferences Detected ─────────────────────────────────
  const prefsHtml = `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title">Preferences Detected by AI</div>
      <div class="summary-grid" style="margin-top:10px;">
        <div class="summary-item">
          <label>allowed_instrument_types</label>
          <div class="value">${chips(prefs.allowed_instrument_types)}</div>
        </div>
        <div class="summary-item">
          <label>excluded_instrument_types</label>
          <div class="value">${chips(prefs.excluded_instrument_types)}</div>
        </div>
        <div class="summary-item">
          <label>avoid_sectors</label>
          <div class="value">${chips(prefs.avoid_sectors, "chip chip-warn")}</div>
        </div>
        <div class="summary-item">
          <label>prefer_sectors</label>
          <div class="value">${chips(prefs.prefer_sectors)}</div>
        </div>
        <div class="summary-item">
          <label>avoid_issuers</label>
          <div class="value">${chips(prefs.avoid_issuers, "chip chip-warn")}</div>
        </div>
        <div class="summary-item">
          <label>prefer_issuers</label>
          <div class="value">${chips(prefs.prefer_issuers)}</div>
        </div>
        <div class="summary-item">
          <label>min_liquidity_score</label>
          <div class="value">${nullOrDash(prefs.min_liquidity_score)}</div>
        </div>
        <div class="summary-item">
          <label>max_maturity_year</label>
          <div class="value">${nullOrDash(prefs.max_maturity_year)}</div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;">
          <label>hard_constraints</label>
          <div class="value">${chips(prefs.hard_constraints)}</div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;">
          <label>soft_preferences</label>
          <div class="value">${chips(prefs.soft_preferences)}</div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;">
          <label>unparsed_preferences</label>
          <div class="value">${chips(prefs.unparsed_preferences, "chip chip-warn")}</div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;">
          <label>advisor_notes</label>
          <div class="value">
            ${(prefs.advisor_notes && prefs.advisor_notes.length)
              ? `<ol class="numbered-list">${prefs.advisor_notes.map(n => `<li>${escapeHTML(n)}</li>`).join("")}</ol>`
              : `<span style="color:#a0aec0;font-size:12px;">none</span>`}
          </div>
        </div>
      </div>
    </div>
  `;

  // ── 3. Applied Filters ──────────────────────────────────────
  const filtersHtml = `
    <div style="padding:14px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title">Applied Filters (${filters.length})</div>
      <div style="margin-top:8px;">
        ${filters.length
          ? `<div class="list-chips">${filters.map(f => `<span class="chip">${escapeHTML(f)}</span>`).join("")}</div>`
          : `<span style="color:#a0aec0;font-size:12px;">None — no active filter criteria extracted.</span>`}
      </div>
    </div>
  `;

  // ── 4. Warnings ─────────────────────────────────────────────
  const warningsHtml = `
    <div style="padding:14px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title">Warnings (${warnings.length})</div>
      <div style="margin-top:8px;">
        ${warnings.length
          ? `<div class="list-chips">${warnings.map(w => `<span class="chip chip-warn">${escapeHTML(w)}</span>`).join("")}</div>`
          : `<span style="color:#a0aec0;font-size:12px;">None</span>`}
      </div>
    </div>
  `;

  // ── 5. Eligible Instruments table ───────────────────────────
  const eligibleHtml = `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title" style="color:#065f46;">
        ✓ Eligible Instruments (${eligible.length})
      </div>
      ${eligible.length === 0
        ? `<div class="msg msg-error" style="margin-top:10px;">No instruments pass all active filters.</div>`
        : `<div class="tbl-wrap" style="margin-top:10px;">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th><th>Name</th><th>Issuer</th><th>Type</th>
                  <th>Asset Class</th><th>CCY</th><th>Country</th><th>Sector</th>
                  <th>Hard $</th><th>Maturity</th><th>YTM</th><th>Dur.</th>
                  <th>Liq.</th><th>Rating</th>
                </tr>
              </thead>
              <tbody>
                ${eligible.map(inst => `
                  <tr style="background:#f0fdf4;">
                    <td class="mono" style="color:#065f46;font-weight:700;">${escapeHTML(inst.ticker)}</td>
                    <td>${escapeHTML(inst.name ?? "")}</td>
                    <td>${escapeHTML(inst.issuer ?? "")}</td>
                    <td><span class="chip">${escapeHTML(inst.instrument_type ?? "")}</span></td>
                    <td>${escapeHTML(inst.asset_class ?? "")}</td>
                    <td class="mono">${escapeHTML(inst.currency ?? "")}</td>
                    <td>${escapeHTML(inst.country ?? "")}</td>
                    <td>${escapeHTML(inst.sector ?? "")}</td>
                    <td>${inst.hard_dollar
                          ? '<span class="pill pill-green" style="font-size:10px;">yes</span>'
                          : '<span class="pill pill-grey"  style="font-size:10px;">no</span>'}</td>
                    <td class="mono" style="font-size:12px;">${inst.maturity_date ? escapeHTML(inst.maturity_date) : "—"}</td>
                    <td>${inst.ytm      != null ? inst.ytm.toFixed(2) + "%" : "—"}</td>
                    <td>${inst.duration != null ? inst.duration.toFixed(1)  : "—"}</td>
                    <td>${inst.liquidity_score != null ? inst.liquidity_score.toFixed(2) : "—"}</td>
                    <td>${inst.rating ? `<span class="chip">${escapeHTML(inst.rating)}</span>` : "—"}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>`}
    </div>
  `;

  // ── 6. Exclusions table ─────────────────────────────────────
  const exclusionsHtml = `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title" style="color:#991b1b;">
        ✕ Excluded Instruments (${exclusions.length})
      </div>
      ${exclusions.length === 0
        ? `<span style="color:#a0aec0;font-size:12px;margin-top:8px;display:block;">None excluded.</span>`
        : `<div class="tbl-wrap" style="margin-top:10px;">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Exclusion Reasons</th>
                </tr>
              </thead>
              <tbody>
                ${exclusions.map(exc => `
                  <tr>
                    <td class="mono" style="color:#991b1b;font-weight:700;white-space:nowrap;">${escapeHTML(exc.ticker)}</td>
                    <td>
                      <div class="list-chips">
                        ${(exc.reasons ?? []).map(r =>
                          `<span class="chip chip-err">${escapeHTML(r)}</span>`
                        ).join("")}
                      </div>
                    </td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>`}
    </div>
  `;

  // ── 7. Full JSON ────────────────────────────────────────────
  const jsonHtml = `
    <details>
      <summary>Full JSON response</summary>
      <pre class="json-block">${escapeHTML(formatJSON(data))}</pre>
    </details>
  `;

  return `<div class="result-box" style="margin-top:20px;">${summaryHtml}${prefsHtml}${filtersHtml}${warningsHtml}${eligibleHtml}${exclusionsHtml}${jsonHtml}</div>`;
}

// ── 6. AI filtered portfolio demo ───────────────────────────

function setAIFPButtonLoading(loading) {
  const btn = el("btn-aifp");
  if (!btn) return;
  btn.disabled = loading;
  btn.innerHTML = loading
    ? `<span class="spinner"></span>Calling OpenAI and generating portfolios…`
    : "Generate AI Filtered Portfolio";
}

async function runAIFilteredPortfolio() {
  const out = el("aifp-result");
  out.innerHTML = `<div class="msg msg-info" style="margin-top:16px;">
    <span class="spinner" style="border-color:rgba(30,64,175,0.3);border-top-color:#1e40af;"></span>
    Calling OpenAI, filtering universe and generating portfolios…
  </div>`;
  out.classList.remove("hidden");
  setAIFPButtonLoading(true);

  const clientId = el("aifp-client_id").value.trim();
  const prefs    = el("aifp-preferences").value.trim();
  const profile  = el("aifp-profile").value;

  if (!clientId || !prefs) {
    out.innerHTML = `<div class="msg msg-error" style="margin-top:16px;">
      <strong>client_id</strong> and <strong>natural_language_preferences</strong> are required.
    </div>`;
    setAIFPButtonLoading(false);
    return;
  }

  const payload = {
    client_id:                    clientId,
    profile:                      profile,
    natural_language_preferences: prefs,
    kyc_context:                  null,
    previous_profile_analysis:    null,
  };

  try {
    const r = await fetch(`${API}/ai/filtered-portfolio-demo`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
    });

    let data;
    try { data = await r.json(); } catch (_) { data = null; }

    if (!r.ok) {
      let errHtml = `<div class="msg msg-error" style="margin-top:16px;">`;

      if (r.status === 400) {
        errHtml += `<strong>⚠ OPENAI_API_KEY is not configured in the backend terminal.</strong><br>
          <span style="font-size:12px;">Set the environment variable before starting uvicorn:</span>
          <div style="margin-top:8px;padding:7px 10px;background:#fee2e2;border-radius:4px;font-family:'Menlo','Consolas',monospace;font-size:11px;color:#991b1b;">
            $env:OPENAI_API_KEY="your_key_here"<br>
            uvicorn risk_first_advisory.api_layer.main:app --reload
          </div>`;
      } else if (r.status === 502) {
        errHtml += `<strong>AI preferences extraction failed.</strong> Check backend logs or API key.<br>
          <span style="font-size:12px;color:#718096;">${data && data.detail ? escapeHTML(String(data.detail)) : ""}</span>`;
      } else if (r.status === 422 && data && data.detail) {
        errHtml += `<strong>HTTP 422 — Validation errors:</strong><ul style="margin-top:6px;padding-left:18px;">`;
        const detail = Array.isArray(data.detail) ? data.detail : [{ msg: String(data.detail) }];
        for (const d of detail) {
          const loc = d.loc ? d.loc.join(" → ") : "";
          errHtml += `<li>${loc ? `<code>${loc}</code>: ` : ""}${escapeHTML(d.msg ?? String(d))}</li>`;
        }
        errHtml += `</ul>`;
      } else {
        errHtml += `<strong>HTTP ${r.status}</strong>`;
        if (data) errHtml += `<pre style="margin-top:8px;font-size:12px;">${escapeHTML(formatJSON(data))}</pre>`;
      }

      errHtml += `</div>`;
      out.innerHTML = errHtml;
      return;
    }

    // Capture record_id so advisor helper buttons can chain off it.
    if (data && typeof data.record_id === "string") {
      lastAIFilteredPortfolioRecordId = data.record_id;
    }
    out.innerHTML = renderAIFilteredPortfolioResult(data);

  } catch (err) {
    if (err.name === "TypeError" && err.message.includes("fetch")) {
      out.innerHTML = `<div class="msg msg-error" style="margin-top:16px;">
        <strong>API not reachable.</strong> Start uvicorn first:<br>
        <code style="font-size:12px;">uvicorn risk_first_advisory.api_layer.main:app --reload</code>
      </div>`;
    } else {
      out.innerHTML = `<div style="margin-top:16px;">${apiError(err)}</div>`;
    }
  } finally {
    setAIFPButtonLoading(false);
  }
}

function clearAIFilteredPortfolioResult() {
  const out = el("aifp-result");
  out.innerHTML = "";
  out.classList.add("hidden");
  setAIFPButtonLoading(false);
}

function renderAIFilteredPortfolioResult(data) {
  const status     = data.status               ?? "—";
  const prefs      = data.preferences          ?? {};
  const eligible   = data.eligible_instruments ?? [];
  const exclusions = data.exclusions           ?? [];
  const filters    = data.applied_filters      ?? [];
  const warnings   = data.warnings             ?? [];
  const snapshots  = data.snapshots            ?? [];
  const candidates = data.candidates           ?? [];
  const confidence    = typeof prefs.confidence === "number" ? prefs.confidence : 0;
  const confidencePct = Math.round(confidence * 100);

  const isBlocked = status.startsWith("blocked_") || status === "infeasible";

  // ── 1. Summary ───────────────────────────────────────────────
  const summaryHtml = `
    <div class="result-summary">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap;">
        <strong style="font-size:15px;">AI Filtered Portfolio Result</strong>
        ${statusPill(status)}
      </div>

      ${isBlocked ? `
        <div class="live-status-box ${status === "infeasible" ? "status-infeasible" : "status-insufficient"}" style="margin-bottom:10px;">
          <div class="status-title">
            ${status === "infeasible" ? "⚠ No feasible portfolio" : "⚠ Portfolio generation blocked"}
          </div>
          <div class="status-msg">${escapeHTML(data.message ?? "")}</div>
        </div>
      ` : ""}

      <div class="summary-grid">
        <div class="summary-item">
          <label>client_id</label>
          <div class="value">${escapeHTML(data.client_id ?? "—")}</div>
        </div>
        <div class="summary-item">
          <label>profile</label>
          <div class="value"><strong>${escapeHTML(data.profile ?? "—")}</strong></div>
        </div>
        <div class="summary-item">
          <label>eligible_count</label>
          <div class="value"><span class="pill pill-green" style="font-size:11px;">${data.eligible_count ?? 0}</span></div>
        </div>
        <div class="summary-item">
          <label>excluded_count</label>
          <div class="value"><span class="pill pill-red" style="font-size:11px;">${data.excluded_count ?? 0}</span></div>
        </div>
        <div class="summary-item">
          <label>snapshot_count</label>
          <div class="value">${data.snapshot_count ?? 0}</div>
        </div>
        <div class="summary-item">
          <label>candidate_count</label>
          <div class="value"><strong>${data.candidate_count ?? 0}</strong></div>
        </div>
        <div class="summary-item">
          <label>AI confidence</label>
          <div class="value">
            <div style="display:flex;align-items:center;gap:10px;margin-top:2px;">
              <span style="font-size:14px;font-weight:700;color:#1a2744;min-width:42px;">${confidencePct}%</span>
              <div class="confidence-bar-track">
                <div class="confidence-bar-fill" style="width:${confidencePct}%;"></div>
              </div>
            </div>
          </div>
        </div>
        ${status === "completed" ? `
        <div class="summary-item" style="grid-column:1/-1;">
          <label>message</label>
          <div class="value" style="color:#166534;">${escapeHTML(data.message ?? "")}</div>
        </div>` : ""}
        ${data.record_id ? `
        <div class="summary-item">
          <label>record_id</label>
          <div class="value mono" style="font-size:11px;">${escapeHTML(data.record_id)}</div>
        </div>` : ""}
        ${data.report_record_id ? `
        <div class="summary-item">
          <label>report_record_id</label>
          <div class="value mono" style="font-size:11px;">${escapeHTML(data.report_record_id)}</div>
        </div>` : ""}
      </div>
    </div>
  `;

  // ── 2. Preferences Detected ──────────────────────────────────
  const prefsHtml = `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title">Preferences Detected by AI</div>
      <div class="summary-grid" style="margin-top:10px;">
        <div class="summary-item">
          <label>entity</label>
          <div class="value">${nullOrDash(prefs.entity)}</div>
        </div>
        <div class="summary-item">
          <label>currency</label>
          <div class="value">${nullOrDash(prefs.currency)}</div>
        </div>
        <div class="summary-item">
          <label>country</label>
          <div class="value">${nullOrDash(prefs.country)}</div>
        </div>
        <div class="summary-item">
          <label>hard_dollar_only</label>
          <div class="value">${boolNullPill(prefs.hard_dollar_only)}</div>
        </div>
        <div class="summary-item">
          <label>min_liquidity_score</label>
          <div class="value">${nullOrDash(prefs.min_liquidity_score)}</div>
        </div>
        <div class="summary-item">
          <label>max_maturity_year</label>
          <div class="value">${nullOrDash(prefs.max_maturity_year)}</div>
        </div>
        <div class="summary-item">
          <label>allowed_instrument_types</label>
          <div class="value">${chips(prefs.allowed_instrument_types)}</div>
        </div>
        <div class="summary-item">
          <label>excluded_instrument_types</label>
          <div class="value">${chips(prefs.excluded_instrument_types)}</div>
        </div>
        <div class="summary-item">
          <label>avoid_sectors</label>
          <div class="value">${chips(prefs.avoid_sectors, "chip chip-warn")}</div>
        </div>
        <div class="summary-item">
          <label>prefer_sectors</label>
          <div class="value">${chips(prefs.prefer_sectors)}</div>
        </div>
        <div class="summary-item">
          <label>avoid_issuers</label>
          <div class="value">${chips(prefs.avoid_issuers, "chip chip-warn")}</div>
        </div>
        <div class="summary-item">
          <label>prefer_issuers</label>
          <div class="value">${chips(prefs.prefer_issuers)}</div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;">
          <label>hard_constraints</label>
          <div class="value">${chips(prefs.hard_constraints)}</div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;">
          <label>soft_preferences</label>
          <div class="value">${chips(prefs.soft_preferences)}</div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;">
          <label>unparsed_preferences</label>
          <div class="value">${chips(prefs.unparsed_preferences, "chip chip-warn")}</div>
        </div>
        <div class="summary-item" style="grid-column:1/-1;">
          <label>advisor_notes</label>
          <div class="value">
            ${(prefs.advisor_notes && prefs.advisor_notes.length)
              ? `<ol class="numbered-list">${prefs.advisor_notes.map(n => `<li>${escapeHTML(n)}</li>`).join("")}</ol>`
              : `<span style="color:#a0aec0;font-size:12px;">none</span>`}
          </div>
        </div>
      </div>
    </div>
  `;

  // ── 3. Applied Filters + Warnings ────────────────────────────
  const filtersHtml = `
    <div style="padding:14px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title">Applied Filters (${filters.length})</div>
      <div style="margin-top:8px;">
        ${filters.length
          ? `<div class="list-chips">${filters.map(f => `<span class="chip">${escapeHTML(f)}</span>`).join("")}</div>`
          : `<span style="color:#a0aec0;font-size:12px;">None — no active filter criteria extracted.</span>`}
      </div>
      ${warnings.length ? `
        <div style="margin-top:12px;">
          <div class="ai-section-title">Warnings (${warnings.length})</div>
          <div style="margin-top:8px;">
            <div class="list-chips">${warnings.map(w => `<span class="chip chip-warn">${escapeHTML(w)}</span>`).join("")}</div>
          </div>
        </div>
      ` : ""}
    </div>
  `;

  // ── 4. Eligible Instruments table ────────────────────────────
  const eligibleHtml = `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title" style="color:#065f46;">
        ✓ Eligible Instruments (${eligible.length})
      </div>
      ${eligible.length === 0
        ? `<div class="msg msg-error" style="margin-top:10px;">No instruments pass all active filters.</div>`
        : `<div class="tbl-wrap" style="margin-top:10px;">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th><th>Name</th><th>Issuer</th><th>Type</th>
                  <th>CCY</th><th>Country</th><th>Sector</th>
                  <th>Hard $</th><th>Maturity</th><th>YTM</th><th>Dur.</th>
                  <th>Liq.</th><th>Rating</th>
                </tr>
              </thead>
              <tbody>
                ${eligible.map(inst => `
                  <tr style="background:#f0fdf4;">
                    <td class="mono" style="color:#065f46;font-weight:700;">${escapeHTML(inst.ticker)}</td>
                    <td>${escapeHTML(inst.name ?? "")}</td>
                    <td>${escapeHTML(inst.issuer ?? "")}</td>
                    <td><span class="chip">${escapeHTML(inst.instrument_type ?? "")}</span></td>
                    <td class="mono">${escapeHTML(inst.currency ?? "")}</td>
                    <td>${escapeHTML(inst.country ?? "")}</td>
                    <td>${escapeHTML(inst.sector ?? "")}</td>
                    <td>${inst.hard_dollar
                          ? '<span class="pill pill-green" style="font-size:10px;">yes</span>'
                          : '<span class="pill pill-grey"  style="font-size:10px;">no</span>'}</td>
                    <td class="mono" style="font-size:12px;">${inst.maturity_date ? escapeHTML(inst.maturity_date) : "—"}</td>
                    <td>${inst.ytm      != null ? inst.ytm.toFixed(2) + "%" : "—"}</td>
                    <td>${inst.duration != null ? inst.duration.toFixed(1)  : "—"}</td>
                    <td>${inst.liquidity_score != null ? inst.liquidity_score.toFixed(2) : "—"}</td>
                    <td>${inst.rating ? `<span class="chip">${escapeHTML(inst.rating)}</span>` : "—"}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>`}
    </div>
  `;

  // ── 5. Market Data Snapshots table ───────────────────────────
  const snapshotsHtml = `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title">Market Data Snapshots (${snapshots.length} usable)</div>
      ${snapshots.length === 0
        ? `<div class="msg msg-info" style="margin-top:10px;">No usable snapshots — instruments with missing return data are excluded from portfolio generation.</div>`
        : `<div class="tbl-wrap" style="margin-top:10px;">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Exp. Return (ann.)</th>
                  <th>Volatility (ann.)</th>
                  <th>Duration</th>
                  <th>Liquidity</th>
                </tr>
              </thead>
              <tbody>
                ${snapshots.map(s => `
                  <tr>
                    <td class="mono" style="font-weight:700;">${escapeHTML(s.ticker)}</td>
                    <td>${pct(s.expected_return_annual)}</td>
                    <td>${pct(s.volatility_annual)}</td>
                    <td>${s.duration != null ? s.duration.toFixed(1) : "—"}</td>
                    <td>${s.liquidity_score != null ? s.liquidity_score.toFixed(2) : "—"}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>`}
    </div>
  `;

  // ── 6. Candidate Portfolios ──────────────────────────────────
  const candidatesHtml = candidates.length > 0 ? `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title">Candidate Portfolios (${candidates.length})</div>
      <div style="margin-top:12px;">
        ${candidates.map(renderPortfolioCandidate).join("")}
      </div>
    </div>
  ` : "";

  // ── 7. Exclusions table ─────────────────────────────────────
  const exclusionsHtml = `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div class="ai-section-title" style="color:#991b1b;">
        ✕ Excluded Instruments (${exclusions.length})
      </div>
      ${exclusions.length === 0
        ? `<span style="color:#a0aec0;font-size:12px;margin-top:8px;display:block;">None excluded.</span>`
        : `<div class="tbl-wrap" style="margin-top:10px;">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Exclusion Reasons</th>
                </tr>
              </thead>
              <tbody>
                ${exclusions.map(exc => `
                  <tr>
                    <td class="mono" style="color:#991b1b;font-weight:700;white-space:nowrap;">${escapeHTML(exc.ticker)}</td>
                    <td>
                      <div class="list-chips">
                        ${(exc.reasons ?? []).map(r =>
                          `<span class="chip chip-err">${escapeHTML(r)}</span>`
                        ).join("")}
                      </div>
                    </td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>`}
    </div>
  `;

  // ── 8. Markdown Report ───────────────────────────────────────
  // Auditable Markdown report generated server-side by
  // AIFilteredPortfolioReportGenerator. Shown verbatim with a
  // "Copy Markdown Report" button.
  const reportMd = typeof data.report_markdown === "string" ? data.report_markdown : "";
  const reportHtml = reportMd ? `
    <div style="padding:16px 20px;border-bottom:1px solid #dde2ea;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:8px;">
        <div class="ai-section-title" style="margin:0;">Markdown Report (for advisor review)</div>
        <button class="btn-secondary"
                type="button"
                id="aifp-copy-md-btn"
                onclick="copyAIFilteredPortfolioMarkdown()">
          Copy Markdown Report
        </button>
      </div>
      <div id="aifp-copy-md-msg" style="font-size:12px;margin-bottom:8px;min-height:18px;"></div>
      <details>
        <summary style="font-size:12px;">Show Markdown source (${reportMd.length} chars)</summary>
        <pre id="aifp-md-source"
             class="json-block"
             style="white-space:pre-wrap;word-break:break-word;max-height:480px;overflow:auto;">${escapeHTML(reportMd)}</pre>
      </details>
    </div>
  ` : "";

  // ── 9. Full JSON ─────────────────────────────────────────────
  const jsonHtml = `
    <details>
      <summary>Full JSON response</summary>
      <pre class="json-block">${escapeHTML(formatJSON(data))}</pre>
    </details>
  `;

  return `<div class="result-box" style="margin-top:20px;">${summaryHtml}${prefsHtml}${filtersHtml}${eligibleHtml}${snapshotsHtml}${candidatesHtml}${exclusionsHtml}${reportHtml}${jsonHtml}</div>`;
}

// ── Copy Markdown Report button handler ─────────────────────
function copyAIFilteredPortfolioMarkdown() {
  const pre = el("aifp-md-source");
  const msg = el("aifp-copy-md-msg");
  if (!pre) {
    if (msg) {
      msg.style.color = "#991b1b";
      msg.textContent = "No Markdown report to copy.";
    }
    return;
  }
  const text = pre.textContent || "";
  if (!text.trim()) {
    if (msg) {
      msg.style.color = "#991b1b";
      msg.textContent = "Markdown report is empty.";
    }
    return;
  }
  const onSuccess = () => {
    if (msg) {
      msg.style.color = "#166534";
      msg.textContent = "✓ Markdown report copied to clipboard.";
    }
  };
  const onFailure = (err) => {
    if (msg) {
      msg.style.color = "#991b1b";
      msg.textContent = "Copy failed: " + (err && err.message ? err.message : String(err));
    }
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(onSuccess).catch(onFailure);
  } else {
    // Fallback for older browsers / non-secure contexts.
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      if (ok) onSuccess(); else onFailure(new Error("execCommand returned false"));
    } catch (err) {
      onFailure(err);
    }
  }
}

// ── 7. portfolio candidate renderer ─────────────────────────

function renderPortfolioCandidate(c) {
  const meta = c.metadata ?? {};
  const weights = c.weights ?? [];
  const needsOverride = meta.requires_advisor_override === true;
  const exceededConstraints = meta.exceeded_constraints ?? [];
  const metaReasonCodes = meta.reason_codes ?? [];
  const metaNotes = meta.notes ?? [];

  // header pill colors per variant
  const variantPillClass = {
    DEFENSIVE: "pill-blue",
    BALANCED:  "pill-green",
    GROWTH:    "pill-orange",
  }[c.variant] ?? "pill-grey";

  // ── override warning banner ──────────────────────────────
  const overrideBanner = needsOverride ? `
    <div class="override-banner">
      <div class="override-title">
        <span>⚠</span> Advisor Override Required
      </div>
      <div style="margin-bottom:5px;">
        <strong>Exceeded constraints:</strong>
        ${exceededConstraints.length
          ? exceededConstraints.map(x => `<span class="chip chip-warn" style="margin-left:4px;">${escapeHTML(x)}</span>`).join("")
          : "<em>none listed</em>"}
      </div>
      <div>
        <strong>Reason codes:</strong>
        ${metaReasonCodes.length
          ? metaReasonCodes.map(x => `<span class="chip chip-err" style="margin-left:4px;">${escapeHTML(x)}</span>`).join("")
          : "<em>none</em>"}
      </div>
      ${metaNotes.length ? `<div style="margin-top:5px;color:#78350f;font-size:11px;">${escapeHTML(metaNotes.join(" · "))}</div>` : ""}
    </div>
  ` : "";

  // ── weights list ─────────────────────────────────────────
  const weightsHtml = weights.length ? `
    <div style="margin-top:10px;">
      <div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;">
        Weights (${weights.length} assets)
      </div>
      ${weights.map(w => {
        const barPct = Math.round(w.weight * 100 * 2);  // scale ×2 for visual
        return `
          <div class="weight-row">
            <span class="weight-ticker">${escapeHTML(w.ticker)}</span>
            <span class="weight-pct">${pct(w.weight)}</span>
            <div class="weight-bar-track">
              <div class="weight-bar-fill" style="width:${Math.min(barPct, 100)}%;"></div>
            </div>
          </div>
        `;
      }).join("")}
    </div>
  ` : `<div style="color:#a0aec0;font-size:12px;margin-top:8px;">No weights available.</div>`;

  // ── metadata collapsible ─────────────────────────────────
  const metaHtml = `
    <details style="margin-top:10px;">
      <summary style="font-size:12px;">Variant metadata</summary>
      <div style="padding:10px 0 0 4px;">
        <div style="display:flex;gap:12px;flex-wrap:wrap;font-size:12px;margin-bottom:6px;">
          <span><strong>risk_budget_exceeded:</strong> ${boolPill(meta.risk_budget_exceeded)}</span>
          <span><strong>requires_advisor_override:</strong> ${boolPill(meta.requires_advisor_override)}</span>
        </div>
        ${exceededConstraints.length ? `<div style="margin-bottom:4px;font-size:12px;"><strong>exceeded_constraints:</strong> ${chips(exceededConstraints, "chip chip-warn")}</div>` : ""}
        ${metaReasonCodes.length ? `<div style="margin-bottom:4px;font-size:12px;"><strong>reason_codes:</strong> ${chips(metaReasonCodes, "chip chip-err")}</div>` : ""}
        ${metaNotes.length ? `<div style="font-size:12px;"><strong>notes:</strong> ${chips(metaNotes)}</div>` : ""}
      </div>
    </details>
  `;

  return `
    <div class="portfolio-card${needsOverride ? ' style="border-color:#fcd34d;"' : ''}">
      <div class="portfolio-card-header">
        <span class="variant-name">${escapeHTML(c.variant)}</span>
        <span class="pill ${variantPillClass}" style="font-size:10px;">${escapeHTML(c.objective)}</span>
        ${needsOverride ? `<span class="pill pill-orange" style="font-size:10px;">⚠ override required</span>` : `<span class="pill pill-green" style="font-size:10px;">✓ within budget</span>`}
      </div>
      <div class="portfolio-card-body">
        ${overrideBanner}
        <div class="metrics-grid">
          <div class="metric-item">
            <label>Expected Return</label>
            <div class="metric-value">${pct(c.expected_return_annual)}</div>
          </div>
          <div class="metric-item">
            <label>Volatility</label>
            <div class="metric-value">${pct(c.volatility_annual)}</div>
          </div>
          <div class="metric-item">
            <label>Risk Score</label>
            <div class="metric-value">${c.risk_score.toFixed(4)}</div>
          </div>
          <div class="metric-item">
            <label>Constraints OK</label>
            <div class="metric-value">${boolPill(c.constraints_satisfied)}</div>
          </div>
        </div>
        ${weightsHtml}
        ${metaHtml}
      </div>
    </div>
  `;
}

// ── 8. advisor decisions demo (Phase 1) ─────────────────────
//
// Wires four small flows on top of the auth scaffold:
//   - Section 1: GET  /auth/me
//   - Section 2: POST /advisor/profile-approval
//   - Section 3: POST /advisor/override-approval
//   - Section 4: POST /advisor/portfolio-selection
//
// The advisor token lives in a single shared input (#adv-token) and is
// applied to all four flows via getAdvisorAuthHeaders(). Demo tokens are
// intentionally not validated client-side — the backend returns 401 on
// unknown tokens with a generic detail, and we surface a generic UI
// message that does NOT echo the token.

// Chained-state globals: set after a successful submission so that the
// "Use last ..." helper buttons can populate downstream forms.
let lastAIFilteredPortfolioRecordId   = null;
let lastProfileApprovalRecordId       = null;
let lastOverrideApprovalRecordId      = null;
let lastPortfolioSelectionRecordId    = null;

// ── Shared helpers ───────────────────────────────────────────

function getAdvisorToken() {
  const inp = el("adv-token");
  if (!inp) return "";
  return inp.value.trim();
}

function getAdvisorAuthHeaders() {
  const token = getAdvisorToken();
  if (!token) return null;
  return {
    "Authorization": `Bearer ${token}`,
    "Content-Type":  "application/json",
  };
}

// Convert one-textarea-per-line input into a list[str] for the backend.
// Drops empty lines so a trailing newline doesn't produce ["", ...].
function linesToStringList(textareaId) {
  const raw = (el(textareaId)?.value ?? "").trim();
  if (!raw) return [];
  return raw.split(/\r?\n/).map(s => s.trim()).filter(s => s.length > 0);
}

function nullIfBlank(value) {
  if (value === null || value === undefined) return null;
  const v = String(value).trim();
  return v.length === 0 ? null : v;
}

// Render a generic key/value summary box for any advisor response.
// `fields` is an array of {label, value, mono?} entries.
function renderAdvisorResultBox(title, status, fields, raw) {
  const rows = fields.map(f => `
    <div class="summary-item">
      <label>${escapeHTML(f.label)}</label>
      <div class="value${f.mono ? " mono" : ""}" style="${f.mono ? "font-size:11px;" : ""}">
        ${f.html ? f.value : escapeHTML(String(f.value ?? "—"))}
      </div>
    </div>
  `).join("");

  return `
    <div class="result-box">
      <div class="result-summary">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap;">
          <strong style="font-size:14px;">${escapeHTML(title)}</strong>
          ${statusPill(status)}
        </div>
        <div class="summary-grid">${rows}</div>
      </div>
      <details style="padding:10px 20px;">
        <summary style="font-size:12px;">Full JSON response</summary>
        <pre class="json-block">${escapeHTML(formatJSON(raw))}</pre>
      </details>
    </div>
  `;
}

// Centralized error renderer for the four advisor endpoints. Never echoes
// the token. 401 always shows the same generic message regardless of why.
function renderAdvisorError(status, data) {
  if (status === 401) {
    return `<div class="msg msg-error">
      <strong>Invalid or missing advisor token.</strong><br>
      <span style="font-size:12px;">Check the value in the "Advisor token" field above.</span>
    </div>`;
  }
  if (status === 422) {
    return `<div class="msg msg-error">
      <strong>HTTP 422 — Validation error.</strong>
      <pre class="json-block" style="margin-top:6px;font-size:11px;">${escapeHTML(formatJSON(data ?? {}))}</pre>
    </div>`;
  }
  if (status === 500) {
    const detail = (data && data.detail) ? String(data.detail) : "Internal server error.";
    return `<div class="msg msg-error">
      <strong>HTTP 500.</strong> ${escapeHTML(detail)}
    </div>`;
  }
  return `<div class="msg msg-error">
    <strong>HTTP ${status}</strong>
    ${data ? `<pre class="json-block" style="margin-top:6px;font-size:11px;">${escapeHTML(formatJSON(data))}</pre>` : ""}
  </div>`;
}

// ── Helper buttons: fill from chained-state globals ──────────

function fillLastAIFPRecordId(inputId, msgId) {
  const msg = el(msgId);
  if (!lastAIFilteredPortfolioRecordId) {
    if (msg) {
      msg.style.color = "#991b1b";
      msg.textContent = "✕ No AI Filtered Portfolio record yet. Run the demo above first.";
    }
    return;
  }
  el(inputId).value = lastAIFilteredPortfolioRecordId;
  if (msg) {
    msg.style.color = "#166534";
    msg.textContent = `✓ filled with ${lastAIFilteredPortfolioRecordId}`;
  }
}

function fillLastOverrideRecordId(inputId, msgId) {
  const msg = el(msgId);
  if (!lastOverrideApprovalRecordId) {
    if (msg) {
      msg.style.color = "#991b1b";
      msg.textContent = "✕ No override approval record yet. Submit section 3 first.";
    }
    return;
  }
  el(inputId).value = lastOverrideApprovalRecordId;
  if (msg) {
    msg.style.color = "#166534";
    msg.textContent = `✓ filled with ${lastOverrideApprovalRecordId}`;
  }
}

// ── Section 1: Advisor auth check ────────────────────────────

async function checkAdvisorAuth() {
  const out = el("adv-auth-result");
  const headers = getAdvisorAuthHeaders();
  if (!headers) {
    out.innerHTML = `<div class="msg msg-error">
      <strong>Advisor token is empty.</strong> Provide a value above.
    </div>`;
    return;
  }
  out.innerHTML = `<div class="msg msg-info"><span class="spinner"></span>Checking advisor identity…</div>`;
  try {
    const r = await fetch(`${API}/auth/me`, { headers });
    let data;
    try { data = await r.json(); } catch (_) { data = null; }

    if (!r.ok) {
      out.innerHTML = renderAdvisorError(r.status, data);
      return;
    }

    const rolesHtml = (Array.isArray(data.roles) && data.roles.length)
      ? `<div class="list-chips">${data.roles.map(role => `<span class="chip">${escapeHTML(role)}</span>`).join("")}</div>`
      : `<span style="color:#a0aec0;font-size:12px;">none</span>`;

    out.innerHTML = renderAdvisorResultBox(
      "Advisor identity",
      "ok",
      [
        { label: "advisor_id",    value: data.advisor_id,    mono: true },
        { label: "display_name",  value: data.display_name },
        { label: "firm_id",       value: data.firm_id ?? "—" },
        { label: "roles",         value: rolesHtml, html: true },
      ],
      data,
    );
  } catch (err) {
    out.innerHTML = apiError(err);
  }
}

function clearAdvisorAuthResult() {
  el("adv-auth-result").innerHTML = "";
}

// ── Section 2: Profile approval ──────────────────────────────

async function submitProfileApproval() {
  const out = el("adv-prof-result");
  const headers = getAdvisorAuthHeaders();
  if (!headers) {
    out.innerHTML = `<div class="msg msg-error">
      <strong>Advisor token is empty.</strong> Provide a value above.
    </div>`;
    return;
  }

  const approvedRaw = (el("adv-prof-approved")?.value ?? "").trim();
  const body = {
    client_id:         (el("adv-prof-client_id").value || "").trim(),
    proposed_profile:  el("adv-prof-proposed").value,
    decision:          el("adv-prof-decision").value,
    approved_profile:  approvedRaw.length ? approvedRaw : null,
    rationale:         (el("adv-prof-rationale").value || "").trim(),
    source:            (el("adv-prof-source").value || "").trim() || "manual",
    related_record_id: nullIfBlank(el("adv-prof-related").value),
  };

  out.innerHTML = `<div class="msg msg-info"><span class="spinner"></span>Submitting profile approval…</div>`;
  try {
    const r = await fetch(`${API}/advisor/profile-approval`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    let data;
    try { data = await r.json(); } catch (_) { data = null; }

    if (!r.ok) {
      out.innerHTML = renderAdvisorError(r.status, data);
      return;
    }

    lastProfileApprovalRecordId = data.record_id ?? null;

    out.innerHTML = renderAdvisorResultBox(
      "Profile approval — recorded",
      data.status ?? "recorded",
      [
        { label: "record_id",        value: data.record_id,        mono: true },
        { label: "advisor_id",       value: data.advisor_id,       mono: true },
        { label: "decision",         value: data.decision },
        { label: "proposed_profile", value: data.proposed_profile },
        { label: "approved_profile", value: data.approved_profile ?? "—" },
        { label: "created_at_utc",   value: data.created_at_utc,   mono: true },
      ],
      data,
    );
  } catch (err) {
    out.innerHTML = apiError(err);
  }
}

function clearProfileApprovalResult() {
  el("adv-prof-result").innerHTML = "";
}

// ── Section 3: Override approval ─────────────────────────────

async function submitOverrideApproval() {
  const out = el("adv-ovr-result");
  const headers = getAdvisorAuthHeaders();
  if (!headers) {
    out.innerHTML = `<div class="msg msg-error">
      <strong>Advisor token is empty.</strong> Provide a value above.
    </div>`;
    return;
  }

  const body = {
    client_id:            (el("adv-ovr-client_id").value || "").trim(),
    related_record_id:    nullIfBlank(el("adv-ovr-related").value),
    candidate_variant:    el("adv-ovr-variant").value,
    decision:             el("adv-ovr-decision").value,
    reason_codes:         linesToStringList("adv-ovr-reasons"),
    exceeded_constraints: linesToStringList("adv-ovr-exceeded"),
    rationale:            (el("adv-ovr-rationale").value || "").trim(),
    source:               (el("adv-ovr-source").value || "").trim() || "manual",
  };

  out.innerHTML = `<div class="msg msg-info"><span class="spinner"></span>Submitting override approval…</div>`;
  try {
    const r = await fetch(`${API}/advisor/override-approval`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    let data;
    try { data = await r.json(); } catch (_) { data = null; }

    if (!r.ok) {
      out.innerHTML = renderAdvisorError(r.status, data);
      return;
    }

    lastOverrideApprovalRecordId = data.record_id ?? null;

    const reasonsHtml    = chips(data.reason_codes, "chip chip-err");
    const exceededHtml   = chips(data.exceeded_constraints, "chip chip-warn");

    out.innerHTML = renderAdvisorResultBox(
      "Override approval — recorded",
      data.status ?? "recorded",
      [
        { label: "record_id",            value: data.record_id,        mono: true },
        { label: "advisor_id",           value: data.advisor_id,       mono: true },
        { label: "candidate_variant",    value: data.candidate_variant },
        { label: "decision",             value: data.decision },
        { label: "reason_codes",         value: reasonsHtml,           html: true },
        { label: "exceeded_constraints", value: exceededHtml,          html: true },
        { label: "created_at_utc",       value: data.created_at_utc,   mono: true },
      ],
      data,
    );
  } catch (err) {
    out.innerHTML = apiError(err);
  }
}

function clearOverrideApprovalResult() {
  el("adv-ovr-result").innerHTML = "";
}

// ── Section 4: Portfolio selection ───────────────────────────

async function submitPortfolioSelection() {
  const out = el("adv-sel-result");
  const headers = getAdvisorAuthHeaders();
  if (!headers) {
    out.innerHTML = `<div class="msg msg-error">
      <strong>Advisor token is empty.</strong> Provide a value above.
    </div>`;
    return;
  }

  const body = {
    client_id:                   (el("adv-sel-client_id").value || "").trim(),
    related_record_id:           nullIfBlank(el("adv-sel-related").value),
    selected_variant:            el("adv-sel-variant").value,
    rationale:                   (el("adv-sel-rationale").value || "").trim(),
    override_approval_record_id: nullIfBlank(el("adv-sel-override").value),
    source:                      (el("adv-sel-source").value || "").trim() || "manual",
  };

  out.innerHTML = `<div class="msg msg-info"><span class="spinner"></span>Submitting portfolio selection…</div>`;
  try {
    const r = await fetch(`${API}/advisor/portfolio-selection`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    let data;
    try { data = await r.json(); } catch (_) { data = null; }

    if (!r.ok) {
      out.innerHTML = renderAdvisorError(r.status, data);
      return;
    }

    lastPortfolioSelectionRecordId = data.record_id ?? null;

    const warningsHtml = (Array.isArray(data.warnings) && data.warnings.length)
      ? `<div class="list-chips">${data.warnings.map(w => `<span class="chip chip-warn">${escapeHTML(w)}</span>`).join("")}</div>`
      : `<span style="color:#a0aec0;font-size:12px;">none</span>`;

    out.innerHTML = renderAdvisorResultBox(
      "Portfolio selection — recorded",
      data.status ?? "recorded",
      [
        { label: "record_id",         value: data.record_id,        mono: true },
        { label: "advisor_id",        value: data.advisor_id,       mono: true },
        { label: "selected_variant",  value: data.selected_variant },
        { label: "warnings",          value: warningsHtml,          html: true },
        { label: "created_at_utc",    value: data.created_at_utc,   mono: true },
        { label: "status",            value: data.status },
      ],
      data,
    );
  } catch (err) {
    out.innerHTML = apiError(err);
  }
}

function clearPortfolioSelectionResult() {
  el("adv-sel-result").innerHTML = "";
}


