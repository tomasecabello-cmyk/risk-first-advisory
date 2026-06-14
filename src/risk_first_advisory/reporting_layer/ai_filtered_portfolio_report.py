"""
AIFilteredPortfolioReportGenerator — convierte un dict con la forma de
AIFilteredPortfolioResponse en un informe Markdown auditable para el asesor.

Política de diseño:
    - No recalcula nada: solo formatea lo que está en el payload.
    - No escribe archivos a disco.
    - No llama a OpenAI ni al portfolio engine.
    - No depende de FastAPI ni de Pydantic.
    - Determinístico: mismo payload → mismo string.
    - Input : dict con forma equivalente a AIFilteredPortfolioResponse,
              más la clave opcional 'natural_language_preferences'.
    - Output: str Markdown puro.

Secciones del reporte:
    1. Executive Summary
    2. Natural Language Preferences
    3. AI Extracted Preferences
    4. Applied Universe Filters
    5. Eligible Instruments
    6. Exclusions
    7. Portfolio-Ready Snapshots
    8. Candidate Portfolios
    9. Advisor Override
    10. Limitations and Disclaimers
"""

from __future__ import annotations

from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Helpers de formateo (privados)
# ─────────────────────────────────────────────────────────────────────────────


def _pct(value: Any) -> str:
    """Formatea un valor decimal como porcentaje con 2 decimales. None → '—'."""
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _null(value: Any) -> str:
    """Convierte None en '—', cualquier otro valor en str."""
    if value is None:
        return "—"
    return str(value)


def _bool_str(value: Any) -> str:
    """bool → 'true'/'false', None → '—', otros → str."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _list_str(lst: Any) -> str:
    """list → items unidos con ', ', vacío/None → 'None'."""
    if not lst:
        return "None"
    return ", ".join(str(x) for x in lst)


def _escape_pipe(s: str) -> str:
    """Escapa el carácter '|' para que no rompa tablas Markdown."""
    return s.replace("|", "\\|")


def _cell(value: Any) -> str:
    """
    Convierte value a str, maneja None → '—' y escapa pipes.
    Usado para contenido de celdas en tablas Markdown.
    """
    if value is None:
        return "—"
    return _escape_pipe(str(value))


def _table_row(*cells: Any) -> str:
    """Construye una fila de tabla Markdown a partir de sus celdas."""
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


# ─────────────────────────────────────────────────────────────────────────────
# Secciones privadas del reporte
# ─────────────────────────────────────────────────────────────────────────────


def _section_title() -> str:
    return "# Risk-First Advisory — AI Filtered Portfolio Report"


def _section_executive_summary(payload: dict) -> str:
    lines = [
        "## 1. Executive Summary",
        "",
        "| Field | Value |",
        "|---|---|",
        _table_row("Client ID", payload.get("client_id", "—")),
        _table_row("Profile", payload.get("profile", "—")),
        _table_row("Status", payload.get("status", "—")),
        _table_row("Message", payload.get("message", "—")),
        _table_row("Eligible instruments", payload.get("eligible_count", "—")),
        _table_row("Excluded instruments", payload.get("excluded_count", "—")),
        _table_row("Portfolio-ready snapshots", payload.get("snapshot_count", "—")),
        _table_row("Candidate portfolios", payload.get("candidate_count", "—")),
    ]
    return "\n".join(lines)


def _section_natural_language_preferences(payload: dict) -> str:
    lines = ["## 2. Natural Language Preferences", ""]
    nlp = payload.get("natural_language_preferences")
    if nlp and str(nlp).strip():
        lines.append(f"> {_escape_pipe(str(nlp).strip())}")
    else:
        lines.append("Not provided in payload.")
    return "\n".join(lines)


def _section_ai_extracted_preferences(payload: dict) -> str:
    prefs = payload.get("preferences") or {}
    lines = [
        "## 3. AI Extracted Preferences",
        "",
        "| Field | Value |",
        "|---|---|",
        _table_row(
            "allowed_instrument_types",
            _list_str(prefs.get("allowed_instrument_types")),
        ),
        _table_row(
            "excluded_instrument_types",
            _list_str(prefs.get("excluded_instrument_types")),
        ),
        _table_row("currency", _null(prefs.get("currency"))),
        _table_row("country", _null(prefs.get("country"))),
        _table_row("entity", _null(prefs.get("entity"))),
        _table_row("hard_dollar_only", _bool_str(prefs.get("hard_dollar_only"))),
        _table_row("avoid_sectors", _list_str(prefs.get("avoid_sectors"))),
        _table_row("prefer_sectors", _list_str(prefs.get("prefer_sectors"))),
        _table_row("avoid_issuers", _list_str(prefs.get("avoid_issuers"))),
        _table_row("prefer_issuers", _list_str(prefs.get("prefer_issuers"))),
        _table_row("min_liquidity_score", _null(prefs.get("min_liquidity_score"))),
        _table_row("max_maturity_year", _null(prefs.get("max_maturity_year"))),
        _table_row("hard_constraints", _list_str(prefs.get("hard_constraints"))),
        _table_row("soft_preferences", _list_str(prefs.get("soft_preferences"))),
        _table_row(
            "unparsed_preferences", _list_str(prefs.get("unparsed_preferences"))
        ),
        _table_row("confidence", _null(prefs.get("confidence"))),
        _table_row("advisor_notes", _list_str(prefs.get("advisor_notes"))),
    ]
    return "\n".join(lines)


def _section_applied_filters(payload: dict) -> str:
    lines = ["## 4. Applied Universe Filters", ""]
    filters = payload.get("applied_filters") or []
    if filters:
        for f in filters:
            lines.append(f"- `{_escape_pipe(str(f))}`")
    else:
        lines.append("- None.")

    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("**Warnings:**")
        for w in warnings:
            lines.append(f"- {_escape_pipe(str(w))}")

    return "\n".join(lines)


def _section_eligible_instruments(payload: dict) -> str:
    instruments = payload.get("eligible_instruments") or []
    lines = [
        "## 5. Eligible Instruments",
        "",
    ]
    if not instruments:
        lines.append("No eligible instruments.")
        return "\n".join(lines)

    lines += [
        "| Ticker | Issuer | Type | Currency | Country | Sector | YTM | Duration | Liquidity | Rating |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for inst in instruments:
        ytm = inst.get("ytm")
        ytm_str = f"{ytm:.4f}" if ytm is not None else "—"
        dur = inst.get("duration")
        dur_str = f"{float(dur):.2f}" if dur is not None else "—"
        liq = inst.get("liquidity_score")
        liq_str = f"{float(liq):.2f}" if liq is not None else "—"
        lines.append(
            _table_row(
                inst.get("ticker"),
                inst.get("issuer"),
                inst.get("instrument_type"),
                inst.get("currency"),
                inst.get("country"),
                inst.get("sector"),
                ytm_str,
                dur_str,
                liq_str,
                inst.get("rating"),
            )
        )
    return "\n".join(lines)


def _section_exclusions(payload: dict) -> str:
    exclusions = payload.get("exclusions") or []
    lines = ["## 6. Exclusions", ""]
    if not exclusions:
        lines.append("No exclusions.")
        return "\n".join(lines)

    lines += [
        "| Ticker | Reasons |",
        "|---|---|",
    ]
    for exc in exclusions:
        ticker = exc.get("ticker", "—")
        reasons = exc.get("reasons") or []
        reasons_str = "; ".join(_escape_pipe(str(r)) for r in reasons) or "—"
        lines.append(f"| {_cell(ticker)} | {reasons_str} |")
    return "\n".join(lines)


def _section_snapshots(payload: dict) -> str:
    snapshots = payload.get("snapshots") or []
    lines = ["## 7. Portfolio-Ready Snapshots", ""]
    if not snapshots:
        lines.append("No snapshots available.")
        return "\n".join(lines)

    lines += [
        "| Ticker | Expected Return | Volatility | Duration | Liquidity Score |",
        "|---|---|---|---|---|",
    ]
    for s in snapshots:
        ret = s.get("expected_return_annual")
        vol = s.get("volatility_annual")
        dur = s.get("duration")
        liq = s.get("liquidity_score")
        lines.append(
            _table_row(
                s.get("ticker"),
                _pct(ret),
                _pct(vol),
                f"{float(dur):.2f}" if dur is not None else "—",
                f"{float(liq):.2f}" if liq is not None else "—",
            )
        )
    return "\n".join(lines)


def _section_candidate_portfolios(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    lines = ["## 8. Candidate Portfolios", ""]
    if not candidates:
        lines.append("No candidate portfolios generated.")
        return "\n".join(lines)

    for cand in candidates:
        variant = _null(cand.get("variant"))
        objective = _null(cand.get("objective"))
        ret = cand.get("expected_return_annual")
        vol = cand.get("volatility_annual")
        risk_score = cand.get("risk_score")
        constraints_ok = cand.get("constraints_satisfied")

        lines.append(f"### {variant}")
        lines.append("")
        lines.append(f"- **Objective:** {objective}")
        lines.append(f"- **Expected return:** {_pct(ret)}")
        lines.append(f"- **Volatility:** {_pct(vol)}")
        lines.append(
            f"- **Risk score:** "
            f"{f'{float(risk_score):.4f}' if risk_score is not None else '—'}"
        )
        lines.append(
            f"- **Constraints satisfied:** {_bool_str(constraints_ok)}"
        )

        # Metadata
        meta = cand.get("metadata") or {}
        lines.append("")
        lines.append("**Variant Metadata:**")
        lines.append(
            f"  - risk_budget_exceeded: {_bool_str(meta.get('risk_budget_exceeded'))}"
        )
        lines.append(
            f"  - requires_advisor_override: {_bool_str(meta.get('requires_advisor_override'))}"
        )
        exc_constraints = meta.get("exceeded_constraints") or []
        if exc_constraints:
            lines.append(
                f"  - exceeded_constraints: {_list_str(exc_constraints)}"
            )
        else:
            lines.append("  - exceeded_constraints: None")
        rc_list = meta.get("reason_codes") or []
        if rc_list:
            lines.append(f"  - reason_codes: {_list_str(rc_list)}")
        else:
            lines.append("  - reason_codes: None")

        # Weights
        weights = cand.get("weights") or []
        if weights:
            lines.append("")
            lines.append("**Weights:**")
            lines.append("")
            lines.append("| Ticker | Weight |")
            lines.append("|---|---|")
            for w in weights:
                ticker = w.get("ticker", "—")
                weight = w.get("weight")
                lines.append(
                    _table_row(
                        ticker,
                        _pct(weight),
                    )
                )

        lines.append("")

    return "\n".join(lines)


def _section_advisor_override(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    override_candidates = [
        c for c in candidates
        if (c.get("metadata") or {}).get("requires_advisor_override") is True
    ]

    lines = ["## 9. Advisor Override", ""]
    if not override_candidates:
        lines.append("No advisor override required.")
        return "\n".join(lines)

    lines.append("⚠ **Advisor Override Required**")
    lines.append("")
    for cand in override_candidates:
        variant = _null(cand.get("variant"))
        meta = cand.get("metadata") or {}
        exc_constraints = meta.get("exceeded_constraints") or []
        rc_list = meta.get("reason_codes") or []
        lines.append(f"- **Variant:** {variant}")
        lines.append(
            f"  - exceeded_constraints: {_list_str(exc_constraints)}"
        )
        lines.append(f"  - reason_codes: {_list_str(rc_list)}")

    return "\n".join(lines)


def _section_disclaimers() -> str:
    lines = [
        "## 10. Limitations and Disclaimers",
        "",
        "- This report is generated for advisor review.",
        "- The AI does not approve the final profile.",
        "- The AI does not recommend products directly.",
        "- The instrument universe is filtered deterministically.",
        "- Market data may be proxy/demo data depending on source.",
        "- The advisor must review suitability before presenting any portfolio to the client.",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# AIFilteredPortfolioReportGenerator
# ─────────────────────────────────────────────────────────────────────────────


class AIFilteredPortfolioReportGenerator:
    """
    Genera un informe Markdown a partir de un payload dict equivalente a
    AIFilteredPortfolioResponse (más la clave opcional
    'natural_language_preferences').

    Uso:
        report_str = AIFilteredPortfolioReportGenerator().generate(payload)

    No escribe archivos a disco. No llama a la IA. No llama al optimizador.
    Determinístico: mismo payload → mismo string.
    """

    def generate(self, payload: dict[str, Any]) -> str:
        """
        Convierte el payload en un string Markdown estructurado y auditable.

        Args:
            payload: dict con forma equivalente a AIFilteredPortfolioResponse,
                     más la clave opcional 'natural_language_preferences'.

        Returns:
            str Markdown con 10 secciones fijas.
        """
        sections = [
            _section_title(),
            _section_executive_summary(payload),
            _section_natural_language_preferences(payload),
            _section_ai_extracted_preferences(payload),
            _section_applied_filters(payload),
            _section_eligible_instruments(payload),
            _section_exclusions(payload),
            _section_snapshots(payload),
            _section_candidate_portfolios(payload),
            _section_advisor_override(payload),
            _section_disclaimers(),
        ]
        return "\n\n".join(s for s in sections if s)
