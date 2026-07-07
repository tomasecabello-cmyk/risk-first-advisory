/* ============================================================================
 * compliance.js — vista de compliance: bandeja de casos + snapshot de auditoría.
 * Reusa los paneles cw* de case-workbench.js (cwLoadAuditEvents, cwVerifyAudit,
 * cwLoadAiLogs, cwRefreshComplianceSnapshot) y los helpers cd* de
 * case-dashboard.js (cdApiFetch, cdAuthHeaders, cdToken). El token por defecto
 * es dev-compliance-token (input #cd-token en la página).
 * ==========================================================================*/

const COMPLIANCE_FIRM_ID = "firm_demo_local";

async function complianceLoadBandeja() {
  const box = document.getElementById("compliance-bandeja");
  if (!box) return;
  box.innerHTML = `<div style="opacity:.7;font-size:13px;">Cargando casos…</div>`;
  const res = await cdApiFetch(`/firms/${encodeURIComponent(COMPLIANCE_FIRM_ID)}/cases`, {
    headers: cdAuthHeaders(),
  });
  if (!res.ok) {
    box.innerHTML = `<div class="msg msg-error">No se pudo cargar la lista. ${escapeHTML(res.detail || "")} (HTTP ${res.status})</div>`;
    return;
  }
  const cases = (res.json && res.json.cases) || [];
  cases.sort((a, b) => String(b.created_at_utc || b.case_id).localeCompare(String(a.created_at_utc || a.case_id)));
  const selected = (el("cw-case-id") && el("cw-case-id").value.trim()) || null;
  const top = cases.slice(0, 30);
  if (!top.length) {
    box.innerHTML = `<div class="msg msg-info">No hay casos todavía.</div>`;
    return;
  }
  box.innerHTML = top.map(c => {
    const stage = complianceStage(c);
    const hl = (c.case_id === selected) ? " is-selected" : "";
    return (
      `<div class="bandeja-row${hl}" onclick="complianceSelectCase('${escapeHTML(c.case_id)}')">` +
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
