"""
Case-scoped Markdown report generator (Phase 2 Commit 15).

Genera un reporte Markdown determinístico para presentar al cliente la
selección final de portfolio de un AdvisoryCase. Reutilizable desde el
endpoint `POST /cases/{case_id}/reports`.

Diseño:
    - Input: dicts plain (no domain objects). Esto desacopla el generator
      de los repositories y schemas API. El endpoint arma el contexto
      desde las repos y se lo pasa al generator.
    - Output: string Markdown (no MarkdownReport dataclass para no
      acoplar a la layer legacy).
    - Sin dependencias externas (solo stdlib).

Limitaciones documentadas:
    - No es advisory final automatizado — solo presentación; el advisor
      sigue siendo responsable.
    - Datos de mercado pueden ser proxy / demo según el universe fuente.
    - No reemplaza al asesor humano.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Helpers de formato
# ─────────────────────────────────────────────────────────────────────────────


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pct(value: Any) -> str:
    """Formatea numérico como porcentaje con 2 decimales; "n/a" si no aplica."""
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "n/a"
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{float(value) * 100.0:.2f}%"


def _decimal(value: Any, places: int = 4) -> str:
    if value is None or isinstance(value, bool):
        return "n/a"
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{float(value):.{places}f}"


def _safe_str(value: Any, default: str = "n/a") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value if value.strip() else default
    return str(value)


# ─────────────────────────────────────────────────────────────────────────────
# Disclaimers (estables, requeridos)
# ─────────────────────────────────────────────────────────────────────────────

_DISCLAIMERS: list[str] = [
    "Este reporte NO constituye una recomendación automática de inversión.",
    "Requiere revisión y validación del asesor humano antes de presentarse al cliente.",
    "Los datos de mercado pueden ser proxy o demo según el universo fuente; verificar antes de operar.",
    "La IA NO aprueba la recomendación final. La responsabilidad última es del asesor humano.",
]


# ─────────────────────────────────────────────────────────────────────────────
# Secciones
# ─────────────────────────────────────────────────────────────────────────────


def _section_title(case_id: str) -> str:
    return f"# Reporte de Recomendación de Portfolio — Case `{case_id}`"


def _section_meta(case_data: dict[str, Any], generated_at: str) -> str:
    lines = [
        "## Metadata",
        "",
        f"- **Case ID**: `{case_data.get('case_id', 'n/a')}`",
        f"- **Generado (UTC)**: {generated_at}",
        f"- **Estado del caso**: `{_safe_str(case_data.get('status'))}`",
        f"- **Título del caso**: {_safe_str(case_data.get('title'))}",
    ]
    return "\n".join(lines)


def _section_approved_profile(approval_data: dict[str, Any] | None) -> str:
    lines = ["## Perfil aprobado", ""]
    if approval_data is None:
        lines.append("_No hay perfil aprobado vigente para este caso._")
        return "\n".join(lines)
    lines.extend([
        f"- **Decision**: `{_safe_str(approval_data.get('decision'))}`",
        f"- **Perfil propuesto**: `{_safe_str(approval_data.get('proposed_profile'))}`",
        f"- **Perfil aprobado**: `{_safe_str(approval_data.get('approved_profile'))}`",
        f"- **Rationale**: {_safe_str(approval_data.get('rationale'))}",
        f"- **Advisor**: `{_safe_str(approval_data.get('advisor_id'))}`",
    ])
    return "\n".join(lines)


def _section_selection(
    selection_data: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    lines = [
        "## Variante seleccionada",
        "",
        f"- **Variant**: `{_safe_str(selection_data.get('selected_variant'))}`",
        f"- **Objective**: `{_safe_str(candidate.get('objective'))}`",
        f"- **Rationale**: {_safe_str(selection_data.get('rationale'))}",
        f"- **Selection ID**: `{_safe_str(selection_data.get('selection_id'))}`",
    ]
    return "\n".join(lines)


def _section_metrics(candidate: dict[str, Any]) -> str:
    n_instruments = candidate.get("holdings_count")
    if not isinstance(n_instruments, int):
        n_instruments = len(_normalize_holdings(candidate))
    lines = [
        "## Métricas del portfolio",
        "",
        f"- **Retorno esperado anual**: {_pct(candidate.get('expected_return_annual'))}",
        f"- **Volatilidad anual**: {_pct(candidate.get('volatility_annual'))}",
        f"- **Risk score**: {_decimal(candidate.get('risk_score'))}",
        f"- **Cantidad de instrumentos**: {n_instruments}",
        f"- **Constraints satisfied**: {bool(candidate.get('constraints_satisfied'))}",
    ]
    div = candidate.get("diversification")
    if isinstance(div, dict) and div.get("diversification_score") is not None:
        score = round(float(div["diversification_score"]))
        band = _safe_str(div.get("concentration_band"))
        eff = div.get("effective_holdings")
        eff_str = f", equivalente diversificado ~{float(eff):.1f}" if isinstance(eff, (int, float)) else ""
        lines.append(
            f"- **Diversificación**: {score}/100 (concentración {band}{eff_str})"
        )
        by_class = div.get("by_asset_class")
        if isinstance(by_class, dict) and by_class:
            reparto = ", ".join(
                f"{k} {round(float(v) * 100)}%" for k, v in by_class.items()
            )
            lines.append(f"- **Reparto por clase de activo**: {reparto}")
        flags = div.get("flags") or []
        if flags:
            lines.append(f"- **Alertas de concentración**: {', '.join(str(f) for f in flags)}")
    return "\n".join(lines)


def _normalize_holdings(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Devuelve una lista normalizada `[{ticker, name, instrument_type, currency,
    weight, rationale}, ...]` a partir del candidate. Soporta tres formas:

      1. `holdings`: list[dict]  — formato Phase 3.6 (preferido, enriquecido).
      2. `weights`: list[{"ticker","weight"}]  — formato del proposal (sin metadata).
      3. `weights`: {ticker: weight}  — formato legacy / dict plano.

    Esto hace al report tolerante a candidates antiguos o mockeados sin perder
    info cuando viene enriquecida.
    """
    holdings_raw = candidate.get("holdings")
    if isinstance(holdings_raw, list) and holdings_raw:
        out: list[dict[str, Any]] = []
        for h in holdings_raw:
            if not isinstance(h, dict):
                continue
            out.append({
                "ticker":          h.get("ticker") or h.get("instrument_id"),
                "name":            h.get("name"),
                "instrument_type": h.get("instrument_type"),
                "currency":        h.get("currency"),
                "weight":          h.get("weight"),
                "rationale":       h.get("rationale"),
            })
        return out
    weights = candidate.get("weights")
    if isinstance(weights, list) and weights:
        out_w: list[dict[str, Any]] = []
        for w in weights:
            if not isinstance(w, dict):
                continue
            out_w.append({
                "ticker":          w.get("ticker"),
                "name":            None,
                "instrument_type": None,
                "currency":        None,
                "weight":          w.get("weight"),
                "rationale":       None,
            })
        return out_w
    if isinstance(weights, dict) and weights:
        return [
            {
                "ticker":          t,
                "name":            None,
                "instrument_type": None,
                "currency":        None,
                "weight":          w,
                "rationale":       None,
            }
            for t, w in weights.items()
        ]
    return []


def _section_holdings(candidate: dict[str, Any]) -> str:
    """
    Composición de la cartera seleccionada. Tabla con `Instrumento | Tipo |
    Moneda | Peso | Motivo`. Orden determinístico (peso desc, ticker asc).
    """
    holdings = _normalize_holdings(candidate)
    lines = ["## Composición de la cartera seleccionada", ""]
    if not holdings:
        lines.append("_No hay holdings definidas para esta variante._")
        return "\n".join(lines)
    sorted_h = sorted(
        holdings,
        key=lambda h: (-float(h.get("weight") or 0.0), h.get("ticker") or ""),
    )
    lines.append(f"_Total: {len(sorted_h)} instrumento(s)._")
    lines.append("")
    lines.append("| Instrumento | Tipo | Moneda | Peso | Motivo |")
    lines.append("|---|---|---|---:|---|")
    for h in sorted_h:
        ticker = h.get("ticker") or "?"
        name = h.get("name") or ""
        label = f"`{ticker}`" + (f" — {name}" if name else "")
        itype = h.get("instrument_type") or "—"
        curr = h.get("currency") or "—"
        weight = _pct(h.get("weight"))
        rationale = h.get("rationale") or "—"
        # Markdown table-friendly: replace pipes inside the cell text.
        safe_name = label.replace("|", "\\|")
        safe_rat = rationale.replace("|", "\\|")
        lines.append(f"| {safe_name} | {itype} | {curr} | {weight} | {safe_rat} |")
    return "\n".join(lines)


def _section_variants_comparison(
    proposal_data: dict[str, Any] | None,
    selected_variant: str | None,
) -> str:
    """
    Tabla comparativa de las variantes generadas por el optimizador (DEFENSIVE
    / BALANCED / GROWTH). Útil para el asesor / profesor: muestra de un vistazo
    el trade-off de retorno-volatilidad y por qué la variante elegida es
    razonable. Se omite si no hay proposal_data o si no tiene candidates.
    """
    if not proposal_data:
        return ""
    candidates = proposal_data.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        return ""
    lines = ["## Comparación de variantes generadas", ""]
    lines.append("| Variante | E[ret] anual | Volatilidad | Override | # Instr. | Top holdings |")
    lines.append("|---|---:|---:|---|---:|---|")
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        variant = cand.get("variant") or "?"
        marker = "**" if variant == selected_variant else ""
        meta = cand.get("metadata") or {}
        requires_ovr = bool(meta.get("requires_advisor_override"))
        ovr_label = "⚠ Sí" if requires_ovr else "No"
        holdings = _normalize_holdings(cand)
        n = len(holdings)
        top = sorted(
            holdings,
            key=lambda h: (-float(h.get("weight") or 0.0), h.get("ticker") or ""),
        )[:3]
        top_label = ", ".join(
            f"`{h.get('ticker') or '?'}` {_pct(h.get('weight'))}"
            for h in top
        ) if top else "—"
        e_ret = _pct(cand.get("expected_return_annual"))
        vol = _pct(cand.get("volatility_annual"))
        lines.append(
            f"| {marker}{variant}{marker} | {e_ret} | {vol} | {ovr_label} | {n} | {top_label} |"
        )
    return "\n".join(lines)


def _section_override(
    selection_data: dict[str, Any],
    override_data: dict[str, Any] | None,
) -> str:
    override_id = selection_data.get("override_approval_id")
    lines = ["## Override approval", ""]
    if override_id is None:
        lines.append("_La variante seleccionada no requirió advisor override._")
        return "\n".join(lines)
    if override_data is None:
        lines.append(
            f"_Override referenciado (`{override_id}`) pero no se pudo cargar el detalle._"
        )
        return "\n".join(lines)
    lines.extend([
        f"- **Override Approval ID**: `{override_data.get('override_approval_id')}`",
        f"- **Candidate variant**: `{_safe_str(override_data.get('candidate_variant'))}`",
        f"- **Decision**: `{_safe_str(override_data.get('decision'))}`",
        f"- **Rationale**: {_safe_str(override_data.get('rationale'))}",
        f"- **Advisor**: `{_safe_str(override_data.get('advisor_id'))}`",
    ])
    reason_codes = override_data.get("reason_codes") or []
    if reason_codes:
        lines.append("- **Reason codes**:")
        for rc in reason_codes:
            lines.append(f"  - `{rc}`")
    exceeded = override_data.get("exceeded_constraints") or []
    if exceeded:
        lines.append("- **Exceeded constraints**:")
        for ec in exceeded:
            lines.append(f"  - `{ec}`")
    return "\n".join(lines)


def _section_risk_gap(analysis_data: dict[str, Any] | None) -> str:
    """
    Sección Risk Gap — flag de inconsistencia declarado-vs-respuestas.

    Se deriva del `result` del último análisis IA (las contradicciones que
    analyze_kyc ya produce). Condicional: si no hay analysis_data o no hay
    perfil declarado, devuelve "" y el reporte no la incluye (backward-compat).

    NO es una medición del perfil conductual. Ver docs/METHODOLOGY_NOTES.md.
    """
    if not analysis_data:
        return ""
    # Import local para no acoplar la reporting layer al ai_layer en import-time.
    from risk_first_advisory.ai_layer.risk_gap import derive_risk_gap

    result = analysis_data.get("result")
    if not isinstance(result, dict):
        return ""
    gap = derive_risk_gap(result)
    if gap is None:
        return ""

    lines = ["## Risk Gap — perfil declarado vs respuestas del cliente", ""]
    lines.append(
        "_La IA marca una inconsistencia. El asesor confirma el perfil con el "
        "cliente. Esto NO es una medición del perfil conductual._"
    )
    lines.append("")
    lines.append(f"- **Perfil declarado**: `{_safe_str(gap.get('declared_profile'))}`")
    lines.append(f"- **Nivel de inconsistencia (gap)**: `{_safe_str(gap.get('gap_level'))}`")
    stress = _safe_str(gap.get("stress_signal"), default="")
    if stress:
        lines.append(f"- **Señal del cliente**: {stress}")
    lines.append(f"- **Lectura**: {_safe_str(gap.get('gap_explanation'))}")
    # Las preguntas solo son una ACCIÓN pendiente si hay inconsistencia. Con el
    # perfil alineado (gap bajo) no hay nada que confirmar → no se listan (evita
    # que parezca que falta un paso).
    questions = gap.get("confirmation_questions") or []
    if questions and _safe_str(gap.get("gap_level")) != "low":
        lines.append("- **Preguntas para confirmar con el cliente** (hay inconsistencia a revisar):")
        for q in questions:
            lines.append(f"  - {_safe_str(q)}")
    return "\n".join(lines)


def _section_executive_summary(
    case_data: dict[str, Any],
    approval_data: dict[str, Any] | None,
    selection_data: dict[str, Any],
    candidate: dict[str, Any],
    override_data: dict[str, Any] | None,
    capacity_data: dict[str, Any] | None,
) -> str:
    """
    Párrafo legible que sintetiza el caso para un asesor/cliente, ANTES de las
    tablas. Sin tablas ni IDs: perfil, capacidad, cartera recomendada, override.
    100% derivado de los inputs (determinístico).
    """
    title = _safe_str(case_data.get("title"), default="el cliente")
    profile = _safe_str((approval_data or {}).get("approved_profile"))
    variant = _safe_str(selection_data.get("selected_variant"))
    objective = _safe_str(candidate.get("objective"))
    eret = _pct(candidate.get("expected_return_annual"))
    vol = _pct(candidate.get("volatility_annual"))
    n = candidate.get("holdings_count")
    if not isinstance(n, int):
        n = len(_normalize_holdings(candidate))

    parts = [f"Para **{title}** se aprobó un perfil de riesgo **{profile}**."]

    cg = (capacity_data or {}).get("capacity_gap")
    if isinstance(cg, dict):
        if cg.get("exceeds_capacity"):
            parts.append(
                f"El cliente busca asumir más riesgo (**{_safe_str(cg.get('desired_profile'))}**) "
                f"del que su situación financiera soporta (**{_safe_str(cg.get('capacity_ceiling'))}**); "
                "la diferencia se aprobó con override firmado del asesor."
            )
        else:
            parts.append(
                "Ese perfil está **dentro de la capacidad financiera** del cliente; "
                "no requirió override."
            )

    rec = (
        f"Se recomienda la cartera **{variant}** (objetivo {objective}): retorno esperado "
        f"anual **{eret}**, volatilidad **{vol}**, {n} instrumento(s)."
    )
    div = candidate.get("diversification")
    if isinstance(div, dict) and div.get("diversification_score") is not None:
        rec += (
            f" Diversificación {round(float(div['diversification_score']))}/100 "
            f"(concentración {_safe_str(div.get('concentration_band'))})."
        )
    parts.append(rec)

    if override_data is not None:
        parts.append(
            "Esta selección **excede el presupuesto de riesgo aprobado y fue firmada con "
            "override del asesor**, registrado en la cadena de auditoría."
        )

    return "## Resumen ejecutivo\n\n" + " ".join(parts)


def _section_capacity(capacity_data: dict[str, Any] | None) -> str:
    """
    Capacidad vs. tolerancia (el diferencial del producto): cuánto QUIERE asumir
    el cliente vs cuánto PUEDE soportar su situación financiera. Condicional: si
    no hay capacity_data, devuelve "" (backward-compat).
    """
    det = (capacity_data or {}).get("deterministic")
    if not isinstance(det, dict):
        return ""
    cg = (capacity_data or {}).get("capacity_gap") or {}

    def _0_100(v: Any) -> str:
        try:
            return f"{round(float(v) * 100)}/100"
        except (TypeError, ValueError):
            return "n/a"

    lines = ["## Capacidad vs. tolerancia", ""]
    lines.append(
        "_La capacidad financiera acota la tolerancia: el riesgo efectivo es el mínimo "
        "entre lo que el cliente quiere y lo que su situación soporta. No se asigna más "
        "riesgo del que puede afrontar, por más que lo declare._"
    )
    lines.append("")
    lines.append(f"- **Tolerancia declarada (quiere)**: {_0_100(det.get('willingness'))}")
    lines.append(f"- **Capacidad financiera (puede)**: {_0_100(det.get('ability'))}")
    lines.append(
        f"- **Riesgo efectivo = mínimo de ambos**: {_decimal(det.get('score'), 1)}/100 "
        f"→ perfil `{_safe_str(det.get('profile'))}`"
    )
    lines.append(f"- **Dimensión que limita**: `{_safe_str(det.get('binding_dimension'))}`")
    explanation = _safe_str(cg.get("explanation"), default="")
    if explanation:
        lines.append(f"- **Lectura**: {explanation}")
    return "\n".join(lines)


def _section_risk_number(
    candidate: dict[str, Any],
    risk_number_data: dict[str, Any] | None,
) -> str:
    """
    Risk Number 0-100 (docs/RISK_NUMBER_DESIGN.md): número del cliente
    (recomputado del KYC vigente, mismo patrón que capacity_data) + número
    de la cartera SELECCIONADA, leído del snapshot ya persistido en el
    candidate (`risk_number`/`risk_alignment`) — el generator NO recalcula
    (I-013/I-020). Tolerante: sin cliente ni cartera, se omite; con solo uno
    de los dos, el otro se marca "no disponible" (proposal legacy).
    """
    client = (risk_number_data or {}).get("client")
    portfolio_rn = candidate.get("risk_number")
    alignment = candidate.get("risk_alignment")

    if not isinstance(client, dict) and not isinstance(portfolio_rn, dict):
        return ""

    lines = ["## Risk Number", ""]
    lines.append(
        "_Escala propia 0-100 (bandas de 20 = los 5 perfiles), ancla en riesgo "
        "de downside (CVaR). Señal informativa: el override formal sigue "
        "gobernado por profile-approval y metadata.requires_advisor_override._"
    )
    lines.append("")
    if isinstance(client, dict):
        lines.append(
            f"- **Número del cliente (operativo)**: {_decimal(client.get('number'), 0)}/100 "
            f"(«{_safe_str(client.get('band'))}»)"
        )
        lines.append(
            f"- **Tolerancia declarada**: {_decimal(client.get('tolerance_number'), 0)}/100 · "
            f"**Techo de capacidad**: {_decimal(client.get('capacity_ceiling_number'), 0)}/100 "
            f"(«{_safe_str(client.get('capacity_ceiling_band'))}»)"
        )
        if client.get("inconsistent"):
            lines.append(
                "- **Atención**: el cuestionario y la pregunta de trade-off "
                "divergen — confirmar el número con el cliente antes de usarlo."
            )
    else:
        lines.append("- **Número del cliente**: no disponible (sin KYC vigente para este caso).")

    if isinstance(portfolio_rn, dict):
        lines.append(
            f"- **Número de la cartera seleccionada**: "
            f"{_decimal(portfolio_rn.get('number'), 0)}/100 («{_safe_str(portfolio_rn.get('band'))}»)"
        )
    else:
        lines.append(
            "- **Número de la cartera seleccionada**: no disponible "
            "(proposal generado antes de esta funcionalidad, o sin datos de mercado)."
        )

    if isinstance(alignment, dict):
        lines.append(f"- **Alineación cliente ↔ cartera**: `{_safe_str(alignment.get('status'))}`")
        lines.append(f"- **Lectura**: {_safe_str(alignment.get('explanation'))}")

    return "\n".join(lines)


def _section_disclaimers() -> str:
    lines = ["## Disclaimers", ""]
    for d in _DISCLAIMERS:
        lines.append(f"- {d}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Generator
# ─────────────────────────────────────────────────────────────────────────────


class CaseMarkdownReportGenerator:
    """
    Genera un Markdown determinístico para el case-scoped report.

    Uso:
        gen = CaseMarkdownReportGenerator()
        out = gen.generate(
            case_data=...,
            selection_data=...,
            proposal_data=...,
            approval_data=...,        # opcional
            override_data=...,        # opcional (None si selection no usó override)
        )

    Política:
        - Sin side-effects (no IO, no DB).
        - Output 100% derivado de los inputs → determinístico salvo el
          timestamp `generated_at`, que el caller puede inyectar para tests.
    """

    def generate(
        self,
        *,
        case_data: dict[str, Any],
        selection_data: dict[str, Any],
        proposal_data: dict[str, Any] | None = None,
        approval_data: dict[str, Any] | None = None,
        override_data: dict[str, Any] | None = None,
        analysis_data: dict[str, Any] | None = None,
        capacity_data: dict[str, Any] | None = None,
        risk_number_data: dict[str, Any] | None = None,
        generated_at_utc: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """
        Devuelve (markdown, metadata_dict).

        metadata_dict captura los IDs y atributos clave para que el endpoint
        los persista en `case_reports.metadata_json` sin tener que volver
        a derivarlos.
        """
        generated_at = generated_at_utc or _now_iso_utc()
        candidate = dict(selection_data.get("selected_candidate") or {})

        variants_section = _section_variants_comparison(
            proposal_data, selection_data.get("selected_variant")
        )
        sections: list[str] = [
            _section_title(case_data.get("case_id", "n/a")),
            "",
            _section_executive_summary(
                case_data, approval_data, selection_data, candidate,
                override_data, capacity_data,
            ),
            "",
            _section_meta(case_data, generated_at),
            "",
            _section_approved_profile(approval_data),
            "",
        ]
        capacity_section = _section_capacity(capacity_data)
        if capacity_section:
            sections.extend([capacity_section, ""])
        risk_number_section = _section_risk_number(candidate, risk_number_data)
        if risk_number_section:
            sections.extend([risk_number_section, ""])
        risk_gap_section = _section_risk_gap(analysis_data)
        if risk_gap_section:
            sections.extend([risk_gap_section, ""])
        sections.extend([
            _section_selection(selection_data, candidate),
            "",
            _section_metrics(candidate),
            "",
            _section_holdings(candidate),
            "",
        ])
        if variants_section:
            sections.extend([variants_section, ""])
        sections.extend([
            _section_override(selection_data, override_data),
            "",
            _section_disclaimers(),
            "",
        ])
        markdown = "\n".join(sections)

        holdings = _normalize_holdings(candidate)
        metadata: dict[str, Any] = {
            "case_id":                case_data.get("case_id"),
            "case_status":            case_data.get("status"),
            "selection_id":           selection_data.get("selection_id"),
            "proposal_id":            selection_data.get("proposal_id"),
            "override_approval_id":   selection_data.get("override_approval_id"),
            "approval_id":            approval_data.get("approval_id") if approval_data else None,
            "approved_profile":       approval_data.get("approved_profile") if approval_data else None,
            "selected_variant":       selection_data.get("selected_variant"),
            "expected_return_annual": candidate.get("expected_return_annual"),
            "volatility_annual":      candidate.get("volatility_annual"),
            "asset_count":            len(holdings),
            "holdings_summary":       [
                {"ticker": h.get("ticker"), "weight": h.get("weight")}
                for h in holdings
            ],
            "generated_at_utc":       generated_at,
        }
        return markdown, metadata
