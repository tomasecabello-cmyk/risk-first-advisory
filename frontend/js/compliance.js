/* ============================================================================
 * compliance.js — vista de compliance: bandeja de casos + snapshot de auditoría.
 * Reusa los paneles cw* de case-workbench.js (cwLoadAuditEvents, cwVerifyAudit,
 * cwLoadAiLogs, cwRefreshComplianceSnapshot) y los helpers cd* de
 * case-dashboard.js (cdApiFetch, cdAuthHeaders, cdToken). El token por defecto
 * es dev-compliance-token (input #cd-token en la página).
 * ==========================================================================*/

const COMPLIANCE_FIRM_ID = "firm_demo_local";

let _complianceClientNames = {};

async function complianceLoadBandeja() {
  const box = document.getElementById("compliance-bandeja");
  if (!box) return;
  box.innerHTML = `<div style="opacity:.7;font-size:13px;">Cargando clientes…</div>`;

  const cliRes = await cdApiFetch("/clients", { headers: cdAuthHeaders() });
  _complianceClientNames = {};
  if (cliRes.ok && cliRes.json && Array.isArray(cliRes.json.clients)) {
    cliRes.json.clients.forEach(c => {
      _complianceClientNames[c.client_id] = { name: c.display_name || c.client_id, ref: c.external_ref || "" };
    });
  }

  const res = await cdApiFetch(`/firms/${encodeURIComponent(COMPLIANCE_FIRM_ID)}/cases`, {
    headers: cdAuthHeaders(),
  });
  if (!res.ok) {
    box.innerHTML = `<div class="msg msg-error">No se pudo cargar la lista. ${escapeHTML(res.detail || "")} (HTTP ${res.status})</div>`;
    return;
  }
  const cases = (res.json && res.json.cases) || [];
  box.innerHTML = complianceRenderGrouped(cases);
}

function complianceRenderGrouped(cases) {
  if (!cases.length) return `<div class="msg msg-info">No hay casos todavía.</div>`;
  const byClient = {};
  cases.forEach(c => { const cid = c.client_id || "—"; (byClient[cid] = byClient[cid] || []).push(c); });
  const selected = (el("cw-case-id") && el("cw-case-id").value.trim()) || null;

  const groups = Object.keys(byClient).map(cid => {
    const list = byClient[cid].sort((a, b) =>
      String(b.created_at_utc || b.case_id).localeCompare(String(a.created_at_utc || a.case_id)));
    return { cid, list, latest: list[0] };
  }).sort((a, b) =>
    String(b.latest.created_at_utc || b.latest.case_id).localeCompare(String(a.latest.created_at_utc || a.latest.case_id)));

  return groups.map(g => {
    const meta = _complianceClientNames[g.cid] || { name: g.cid, ref: "" };
    const n = g.list.length;
    const refTag = meta.ref ? ` · <span class="b-id">#${escapeHTML(meta.ref)}</span>` : "";
    const historyId = `cmp-hist-${g.cid.replace(/[^a-zA-Z0-9_]/g, "")}`;
    const rows = g.list.map((c, i) => {
      const hl = (c.case_id === selected) ? " is-selected" : "";
      const indent = i === 0 ? "" : "margin-left:20px;";
      return `<div class="bandeja-row${hl}" style="${indent}${i > 0 ? "" : ""}" onclick="complianceSelectCase('${escapeHTML(c.case_id)}')">` +
        `<div style="flex:1;min-width:200px;">` +
          (i === 0 ? `<div class="b-title">${escapeHTML(meta.name)}${refTag}</div>` : "") +
          `<span class="b-id">${escapeHTML(c.case_id)}</span>` +
        `</div>` +
        `<div class="b-meta">${escapeHTML(c.created_at_utc || "").slice(0, 16).replace("T", " ")}</div>` +
        complianceStage(c) +
      `</div>`;
    });
    const head = rows[0];
    const rest = rows.slice(1).join("");
    const toggle = n > 1
      ? `<div style="margin:4px 0 0 20px;"><button type="button" class="btn-secondary btn-sm" onclick="complianceToggleHistory('${historyId}')">▸ ${n - 1} caso(s) anterior(es)</button></div>`
      : "";
    return `<div style="margin-bottom:6px;">${head}${toggle}` +
      `<div id="${historyId}" class="bandeja-history" style="display:none;margin-top:4px;">${rest}</div></div>`;
  }).join("");
}

function complianceToggleHistory(id) {
  const box = document.getElementById(id);
  if (box) box.style.display = (box.style.display === "none") ? "grid" : "none";
}

function complianceStage(c) {
  if (c.current_portfolio_selection_id) return `<span class="pill pill-green">cartera elegida</span>`;
  if (c.current_approved_profile_id) return `<span class="pill pill-blue">perfil aprobado</span>`;
  if (c.current_kyc_submission_id) return `<span class="pill pill-orange">en revisión</span>`;
  return `<span class="pill pill-grey">nuevo</span>`;
}

function complianceSelectCase(caseId) {
  const input = el("cw-case-id");
  if (input) input.value = caseId;
  // marcar la fila seleccionada
  document.querySelectorAll("#compliance-bandeja .bandeja-row").forEach(r => {
    r.classList.toggle("is-selected", r.textContent.indexOf(caseId) >= 0);
  });
  complianceRunAll();
}

// cargar los tres paneles + el snapshot para el caso elegido
function complianceRunAll() {
  const caseId = el("cw-case-id") && el("cw-case-id").value.trim();
  if (!caseId) return;
  cwRefreshComplianceSnapshot();
  cwVerifyAudit();
  cwLoadAuditEvents();
  cwLoadAiLogs();
  const anchor = document.getElementById("cw-compliance-result");
  if (anchor && anchor.scrollIntoView) anchor.scrollIntoView({ behavior: "smooth", block: "start" });
}

document.addEventListener("DOMContentLoaded", () => {
  // preseleccionar el último caso creado (p.ej. por la vista Cliente)
  try {
    const last = localStorage.getItem("rfaLastCaseId");
    if (last && el("cw-case-id") && !el("cw-case-id").value) el("cw-case-id").value = last;
  } catch (e) { /* noop */ }
  complianceLoadBandeja();
});
