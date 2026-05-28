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
    weights = candidate.get("weights") or {}
    lines = [
        "## Métricas del portfolio",
        "",
        f"- **Retorno esperado anual**: {_pct(candidate.get('expected_return_annual'))}",
        f"- **Volatilidad anual**: {_pct(candidate.get('volatility_annual'))}",
        f"- **Risk score**: {_decimal(candidate.get('risk_score'))}",
        f"- **Cantidad de instrumentos**: {len(weights) if isinstance(weights, dict) else 0}",
        f"- **Constraints satisfied**: {bool(candidate.get('constraints_satisfied'))}",
    ]
    return "\n".join(lines)


def _section_weights(candidate: dict[str, Any]) -> str:
    weights = candidate.get("weights") or {}
    lines = ["## Distribución de pesos", ""]
    if not isinstance(weights, dict) or not weights:
        lines.append("_No hay pesos definidos para esta variante._")
        return "\n".join(lines)
    lines.append("| Ticker | Peso |")
    lines.append("|--------|------|")
    # Orden determinístico: por peso desc, ticker asc como tiebreaker.
    sorted_items = sorted(
        weights.items(),
        key=lambda kv: (-float(kv[1] or 0.0), kv[0]),
    )
    for ticker, weight in sorted_items:
        lines.append(f"| `{ticker}` | {_pct(weight)} |")
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

        sections = [
            _section_title(case_data.get("case_id", "n/a")),
            "",
            _section_meta(case_data, generated_at),
            "",
            _section_approved_profile(approval_data),
            "",
            _section_selection(selection_data, candidate),
            "",
            _section_metrics(candidate),
            "",
            _section_weights(candidate),
            "",
            _section_override(selection_data, override_data),
            "",
            _section_disclaimers(),
            "",
        ]
        markdown = "\n".join(sections)

        weights = candidate.get("weights") or {}
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
            "asset_count":            len(weights) if isinstance(weights, dict) else 0,
            "generated_at_utc":       generated_at,
        }
        return markdown, metadata
