"""
MarkdownReportGenerator — convierte AdvisoryWorkflowResult en un informe Markdown.

Política de diseño:
    - No recalcula nada: solo formatea lo que ya existe en el resultado.
    - No importa pandas, numpy, ni genera HTML/PDF.
    - El informe es determinista dado el mismo AdvisoryWorkflowResult.
    - Usa math.isnan() para gap de FeasibilityReport (puede ser NaN).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# MarkdownReport
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MarkdownReport:
    """
    Contenedor inmutable de un informe Markdown ya generado.

    Validaciones en __post_init__:
        - title, content, client_id, generated_at_utc no pueden estar vacíos.
        - notes debe ser una lista.
    """

    title: str
    content: str
    client_id: str
    generated_at_utc: str
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for attr in ("title", "content", "client_id", "generated_at_utc"):
            val = getattr(self, attr)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"{attr} no puede estar vacío.")
        if not isinstance(self.notes, list):
            raise ValueError("notes debe ser una lista.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "client_id": self.client_id,
            "generated_at_utc": self.generated_at_utc,
            "notes": list(self.notes),
        }

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.content, encoding="utf-8")
        return target


# ─────────────────────────────────────────────────────────────────────────────
# MarkdownReportGenerator
# ─────────────────────────────────────────────────────────────────────────────


class MarkdownReportGenerator:
    DEFAULT_DISCLAIMER = (
        "This report is for advisory support only. "
        "It does not constitute a guarantee of performance. "
        "Final suitability and implementation decisions remain under advisor supervision."
    )

    def generate_from_workflow_result(
        self,
        result: Any,
        disclaimer: str | None = None,
    ) -> MarkdownReport:
        """
        Genera un MarkdownReport a partir de un AdvisoryWorkflowResult.

        No recalcula ni modifica el resultado. Solo formatea.
        """
        disc = disclaimer if disclaimer is not None else self.DEFAULT_DISCLAIMER
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        sections: list[str] = [
            _section_title(result),
            _section_client(result),
            _section_workflow_status(result),
            _section_approved_profile(result),
            _section_goal_feasibility(result),
            _section_risk_budget(result),
            _section_universe_summary(result),
            _section_portfolio_feasibility(result),
            _section_candidate_portfolios(result),
            _section_warnings_and_reason_codes(result),
            _section_audit_trail(result),
            _section_disclaimer(disc),
        ]

        content = "\n\n".join(s for s in sections if s)

        notes: list[str] = []
        if not result.is_completed:
            notes.append(f"Workflow blocked: {result.status.value}")

        return MarkdownReport(
            title="Risk-First Advisory Report",
            content=content,
            client_id=result.client_id,
            generated_at_utc=generated_at,
            notes=notes,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Secciones privadas
# ─────────────────────────────────────────────────────────────────────────────


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _section_title(result: Any) -> str:
    return "# Risk-First Advisory Report"


def _section_client(result: Any) -> str:
    lines = ["## Client", "", f"- **Client ID:** {result.client_id}"]
    m1 = result.m1_result
    if m1 is not None:
        advisor_id = getattr(m1, "advisor_id", None)
        session_id = getattr(m1, "session_id", None)
        if advisor_id:
            lines.append(f"- **Advisor ID:** {advisor_id}")
        if session_id:
            lines.append(f"- **Session ID:** {session_id}")
    return "\n".join(lines)


def _section_workflow_status(result: Any) -> str:
    lines = [
        "## Workflow Status",
        "",
        f"- **Status:** `{result.status.value}`",
        f"- **Completed:** {'Yes' if result.is_completed else 'No'}",
    ]
    if result.has_warnings:
        lines.append(f"- **Warnings:** {len(result.warnings)}")
    return "\n".join(lines)


def _section_approved_profile(result: Any) -> str:
    lines = [
        "## Approved Profile",
        "",
        f"- **Profile:** {result.approved_profile_name}",
    ]
    comment = getattr(result, "advisor_comment", "")
    if comment and comment.strip():
        lines.append(f"- **Advisor comment:** {comment.strip()}")

    m1 = result.m1_result
    if m1 is not None:
        prelim_initial = getattr(m1, "preliminary_profile_initial", None)
        prelim_revised = getattr(m1, "preliminary_profile_revised", None)
        modified = getattr(m1, "advisor_modified_profile", False)
        fu_rounds = getattr(m1, "follow_up_rounds_executed", 0)

        if prelim_initial is not None:
            lines.append(
                f"- **AI initial proposal:** {getattr(prelim_initial, 'profile_name', 'N/A')}"
            )
        if prelim_revised is not None:
            lines.append(
                f"- **AI revised proposal:** {getattr(prelim_revised, 'profile_name', 'N/A')}"
            )
        lines.append(f"- **Advisor modified:** {'Yes' if modified else 'No'}")
        lines.append(f"- **Follow-up rounds:** {fu_rounds}")

    return "\n".join(lines)


def _section_goal_feasibility(result: Any) -> str:
    fr = result.goal_feasibility_result
    if fr is None:
        return "\n".join(["## Goal Feasibility", "", "Not evaluated."])

    gap = getattr(fr, "gap", None)
    if gap is not None and not math.isnan(gap):
        gap_str = _pct(gap)
    else:
        gap_str = "N/A"

    required = getattr(fr, "required_return_annual", None)
    achievable = getattr(fr, "achievable_return_annual", None)
    status = getattr(fr, "status", None)
    reason = getattr(fr, "reason", "")
    block = getattr(fr, "block_portfolio_generation", False)
    suggested = getattr(fr, "suggested_actions", [])
    disclaimer = getattr(fr, "disclaimer", "")

    lines = [
        "## Goal Feasibility",
        "",
        f"- **Status:** {status.value if status is not None else 'N/A'}",
        f"- **Required return:** {_pct(required) if required is not None else 'N/A'}",
        f"- **Achievable return:** {_pct(achievable) if achievable is not None else 'N/A'}",
        f"- **Gap:** {gap_str}",
        f"- **Blocks portfolio generation:** {'Yes' if block else 'No'}",
        f"- **Reason:** {reason}",
    ]
    if suggested:
        lines.append("")
        lines.append("**Suggested actions:**")
        for action in suggested:
            lines.append(f"  - {action}")
    if disclaimer:
        lines.append("")
        lines.append(f"*{disclaimer}*")
    return "\n".join(lines)


def _section_risk_budget(result: Any) -> str:
    rb = result.risk_budget
    if rb is None:
        return "\n".join(["## Risk Budget", "", "Not computed."])

    lines = [
        "## Risk Budget",
        "",
        f"- **Profile:** {getattr(rb, 'profile_name', 'N/A')}",
        f"- **Target volatility:** {_pct(rb.target_volatility)}",
        f"- **Max volatility:** {_pct(rb.max_volatility)}",
        f"- **Max drawdown:** {_pct(rb.max_drawdown)}",
        f"- **Min liquidity:** {_pct(rb.min_liquidity)}",
        f"- **Max equity:** {_pct(rb.max_equity)}",
        f"- **Max high yield:** {_pct(rb.max_high_yield)}",
        f"- **Max single asset:** {_pct(rb.max_single_asset)}",
        f"- **Max sector exposure:** {_pct(rb.max_sector_exposure)}",
        f"- **Max duration:** {rb.max_duration:.1f} years",
        f"- **Complex products allowed:** {'Yes' if rb.complex_products_allowed else 'No'}",
        f"- **Preferred currency:** {rb.preferred_currency}",
    ]
    if rb.notes:
        lines.append("")
        lines.append("**Notes:**")
        for note in rb.notes:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def _section_universe_summary(result: Any) -> str:
    gov = result.governance_passed_tickers
    suit = result.suitability_passed_tickers
    esg_blocked = result.esg_blocked_tickers
    dq_failed = result.data_quality_failed_tickers
    final = result.final_optimizer_tickers

    lines = [
        "## Universe Summary",
        "",
        f"| Stage | Tickers |",
        f"|---|---|",
        f"| Governance passed | {len(gov)} ({', '.join(gov) or 'none'}) |",
        f"| Suitability passed | {len(suit)} ({', '.join(suit) or 'none'}) |",
        f"| ESG blocked | {len(esg_blocked)} ({', '.join(esg_blocked) or 'none'}) |",
        f"| Data quality failed | {len(dq_failed)} ({', '.join(dq_failed) or 'none'}) |",
        f"| **Final optimizer universe** | **{len(final)} ({', '.join(final) or 'none'})** |",
    ]
    return "\n".join(lines)


def _section_portfolio_feasibility(result: Any) -> str:
    pfr = result.portfolio_feasibility_result
    if pfr is None:
        return "\n".join(["## Portfolio Feasibility", "", "Not evaluated."])

    status = getattr(pfr, "status", None)
    min_vol = getattr(pfr, "min_achievable_volatility", None)

    lines = [
        "## Portfolio Feasibility",
        "",
        f"- **Status:** {status.value if status is not None else 'N/A'}",
        f"- **Is feasible:** {'Yes' if pfr.is_feasible else 'No'}",
        f"- **Asset count:** {pfr.asset_count}",
        f"- **Required min single-asset cap:** {_pct(pfr.required_min_single_asset_cap)}",
        f"- **Actual max single asset:** {_pct(pfr.actual_max_single_asset)}",
        (
            f"- **Min achievable volatility:** {_pct(min_vol)}"
            if min_vol is not None
            else "- **Min achievable volatility:** N/A"
        ),
        f"- **Max allowed volatility:** {_pct(pfr.max_allowed_volatility)}",
    ]
    if pfr.failed_checks:
        lines.append("")
        lines.append("**Failed checks:**")
        for fc in pfr.failed_checks:
            lines.append(f"  - {fc}")
    if pfr.warnings:
        lines.append("")
        lines.append("**Warnings:**")
        for w in pfr.warnings:
            lines.append(f"  - {w}")
    if pfr.suggested_actions:
        lines.append("")
        lines.append("**Suggested actions:**")
        for action in pfr.suggested_actions:
            lines.append(f"  - {action}")
    return "\n".join(lines)


def _format_variant_metadata(meta: Any) -> list[str]:
    """Formatea la metadata de una variante de portfolio en líneas Markdown.

    Si meta es None (variante sin metadata explícita), muestra valores default
    seguros sin romper el reporte.
    """
    lines = ["**Variant Metadata:**"]
    if meta is None:
        lines.append("  - risk_budget_exceeded: false")
        lines.append("  - requires_advisor_override: false")
        lines.append("  - exceeded_constraints: None")
        lines.append("  - reason_codes: None")
        lines.append("  - notes: None")
        return lines

    exceeded = getattr(meta, "risk_budget_exceeded", False)
    override = getattr(meta, "requires_advisor_override", False)
    constraints = getattr(meta, "exceeded_constraints", []) or []
    reason_codes = getattr(meta, "reason_codes", []) or []
    notes = getattr(meta, "notes", []) or []

    lines.append(f"  - risk_budget_exceeded: {'true' if exceeded else 'false'}")
    lines.append(f"  - requires_advisor_override: {'true' if override else 'false'}")

    if constraints:
        lines.append("  - exceeded_constraints:")
        for c in constraints:
            lines.append(f"    - {c}")
    else:
        lines.append("  - exceeded_constraints: None")

    if reason_codes:
        lines.append("  - reason_codes:")
        for rc in reason_codes:
            lines.append(f"    - {rc}")
    else:
        lines.append("  - reason_codes: None")

    if notes:
        lines.append("  - notes:")
        for note in notes:
            lines.append(f"    - {note}")
    else:
        lines.append("  - notes: None")

    return lines


def _section_candidate_portfolios(result: Any) -> str:
    from risk_first_advisory.portfolio_layer.generation import PortfolioVariant

    cs = result.candidate_set
    if cs is None:
        return "\n".join(["## Candidate Portfolios", "", "No portfolios generated."])

    lines = ["## Candidate Portfolios", ""]
    selected = getattr(cs, "selected_variant", None)
    lines.append(f"- **Generated variants:** {cs.count}")
    if selected is not None:
        lines.append(f"- **Selected variant:** {selected.value}")
    lines.append("")

    metadata_map: dict = getattr(cs, "metadata", {}) or {}
    canonical_order = [PortfolioVariant.DEFENSIVE, PortfolioVariant.BALANCED, PortfolioVariant.GROWTH]
    for variant in canonical_order:
        portfolio = cs.candidates.get(variant)
        if portfolio is None:
            continue
        marker = " *(selected)*" if variant == selected else ""
        lines.append(f"### {variant.value}{marker}")
        lines.append("")
        lines.append(f"- **Objective:** {portfolio.objective.value}")
        lines.append(f"- **Expected return:** {_pct(portfolio.expected_return_annual)}")
        lines.append(f"- **Volatility:** {_pct(portfolio.volatility_annual)}")
        lines.append(f"- **Risk score:** {portfolio.risk_score:.4f}")
        lines.append(f"- **Constraints satisfied:** {'Yes' if portfolio.constraints_satisfied else 'No'}")

        if portfolio.weights:
            lines.append("")
            lines.append("**Weights (descending):**")
            sorted_weights = sorted(
                portfolio.weights.items(), key=lambda kv: kv[1], reverse=True
            )
            for ticker, w in sorted_weights:
                lines.append(f"  - {ticker}: {_pct(w)}")

        lines.append("")
        meta = metadata_map.get(variant)
        lines.extend(_format_variant_metadata(meta))
        lines.append("")

    if cs.reason_codes:
        lines.append("**Reason codes:**")
        for rc in cs.reason_codes:
            lines.append(f"  - {rc}")
        lines.append("")
    if cs.notes:
        lines.append("**Notes:**")
        for note in cs.notes:
            lines.append(f"  - {note}")

    return "\n".join(lines)


def _section_warnings_and_reason_codes(result: Any) -> str:
    lines = ["## Warnings and Reason Codes", ""]

    if result.reason_codes:
        lines.append("**Reason codes:**")
        for rc in result.reason_codes:
            lines.append(f"  - {rc}")
        lines.append("")

    if result.warnings:
        lines.append("**Warnings:**")
        for w in result.warnings:
            lines.append(f"  - {w}")
        lines.append("")

    if result.notes:
        lines.append("**Notes:**")
        for note in result.notes:
            lines.append(f"  - {note}")

    if not result.reason_codes and not result.warnings and not result.notes:
        lines.append("No warnings or reason codes.")

    return "\n".join(lines)


def _section_audit_trail(result: Any) -> str:
    m1 = result.m1_result
    audit = getattr(m1, "audit", None) if m1 is not None else None

    if audit is None:
        return "\n".join(["## Audit Trail", "", "No audit trail available."])

    event_types = list(audit.event_types()) if hasattr(audit, "event_types") else []
    is_closed = getattr(audit, "is_closed", None)
    session_id = getattr(m1, "session_id", None)

    lines = [
        "## Audit Trail",
        "",
        f"- **Session ID:** {session_id or 'N/A'}",
        f"- **Closed:** {'Yes' if is_closed else 'No'}",
        f"- **Events ({len(event_types)}):**",
    ]
    for i, evt in enumerate(event_types, 1):
        lines.append(f"  {i}. `{evt}`")

    return "\n".join(lines)


def _section_disclaimer(disclaimer: str) -> str:
    return "\n".join(["## Disclaimer", "", f"*{disclaimer}*"])
