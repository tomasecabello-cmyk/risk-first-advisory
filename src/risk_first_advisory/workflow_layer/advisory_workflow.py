"""
AdvisoryWorkflowCoordinator — fachada productiva del flujo de asesoría.

INVARIANTE CENTRAL: este es el flujo del negocio. UIs (consola, FastAPI,
notebook, report generator, batch jobs) DEBEN consumir este coordinator;
NO deben reimplementar el orden de capas ni los criterios de filtrado.

Diferencias vs. scripts/run_demo.py:
    - El demo runner aplica un "demo adjustment" (relajación local de
      max_single_asset / max_volatility) cuando el RiskBudget aprobado es
      infeasible con el universo final. ESO ES SOLO DEL DEMO.
    - Este workflow productivo NUNCA relaja el RiskBudget aprobado. Si el
      RB original es infactible, devuelve BLOCKED_BY_PORTFOLIO_FEASIBILITY
      con diagnóstico legible y deja que la capa humana decida (uno de los
      4 caminos tipificados de infeasibility resolution).

Estados terminales:
    COMPLETED                      flujo completo con portfolios, sin warnings.
    COMPLETED_WITH_WARNINGS        idem pero con al menos un warning declarado.
    BLOCKED_BY_GOAL_FEASIBILITY    GoalFeasibilityEngine bloqueó la generación.
    BLOCKED_BY_EMPTY_UNIVERSE      Tras filtros, no quedó ningún instrumento.
    BLOCKED_BY_PORTFOLIO_FEASIBILITY  Pre-check o generación rechazó el RB.
    FAILED                         Error inesperado durante el flujo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from risk_first_advisory.data_layer.covariance import (
    CovarianceEngine,
    CovarianceMatrix,
)
from risk_first_advisory.data_layer.data_quality import (
    DataQualityGate,
    DataQualityStatus,
)
from risk_first_advisory.data_layer.market_data import MockMarketDataProvider
from risk_first_advisory.data_layer.return_estimator import (
    ReturnEstimate,
    ReturnEstimator,
)
from risk_first_advisory.engine import RiskFirstSuitabilityEngine
from risk_first_advisory.kyc.models import FinancialGoal, KYCData
from risk_first_advisory.models.risk_budget import RiskBudget
from risk_first_advisory.portfolio_layer.feasibility import (
    PortfolioFeasibilityChecker,
    PortfolioFeasibilityResult,
    PortfolioFeasibilityStatus,
)
from risk_first_advisory.portfolio_layer.generation import (
    PortfolioCandidateSet,
    PortfolioGenerationCoordinator,
)
from risk_first_advisory.rules_layer.esg_compliance import (
    ESGComplianceChecker,
    ESGComplianceStatus,
    ESGMetadataStore,
)
from risk_first_advisory.rules_layer.goal_feasibility import (
    GoalFeasibilityEngine,
)
from risk_first_advisory.rules_layer.instrument_suitability import (
    InstrumentSuitabilityMatrix,
    InstrumentSuitabilityStatus,
)
from risk_first_advisory.rules_layer.product_governance import (
    ApprovedProductUniverse,
    ProductGovernanceRecord,
)
from risk_first_advisory.rules_layer.risk_budget_builder import RiskBudgetBuilder

# ─────────────────────────────────────────────────────────────────────────
# Reason codes del workflow
# ─────────────────────────────────────────────────────────────────────────

RC_GOAL_FEASIBILITY_BLOCKED = "GOAL_FEASIBILITY_BLOCKED"
RC_PORTFOLIO_EMPTY_FINAL_UNIVERSE = "PORTFOLIO_EMPTY_FINAL_UNIVERSE"
RC_PORTFOLIO_GENERATION_BLOCKED = "PORTFOLIO_GENERATION_BLOCKED"
RC_ESG_BLOCKED = "ESG_BLOCKED"
RC_DATA_MISSING = "DATA_MISSING"
RC_DATA_QUALITY_FAILED = "DATA_QUALITY_FAILED"
RC_SUITABILITY_LIMITED = "SUITABILITY_LIMITED"
RC_ESG_WARNING = "ESG_WARNING"
RC_PORTFOLIO_FEASIBILITY_WARNING = "PORTFOLIO_FEASIBILITY_WARNING"


# ─────────────────────────────────────────────────────────────────────────
# Mapeo de instrument_type del universo → matriz de suitability.
# Idéntico al usado en el demo: m1_universe.yaml usa `equity_etf_sector`,
# la matriz usa `sector_equity`.
# ─────────────────────────────────────────────────────────────────────────

_SUITABILITY_TYPE_ALIASES: dict[str, str] = {
    "equity_etf_sector": "sector_equity",
}


def _suitability_type_for(rec: ProductGovernanceRecord) -> str:
    return _SUITABILITY_TYPE_ALIASES.get(rec.instrument_type, rec.instrument_type)


# ─────────────────────────────────────────────────────────────────────────
# Enum de estado terminal
# ─────────────────────────────────────────────────────────────────────────


class AdvisoryWorkflowStatus(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    BLOCKED_BY_GOAL_FEASIBILITY = "blocked_by_goal_feasibility"
    BLOCKED_BY_PORTFOLIO_FEASIBILITY = "blocked_by_portfolio_feasibility"
    BLOCKED_BY_EMPTY_UNIVERSE = "blocked_by_empty_universe"
    FAILED = "failed"


# ─────────────────────────────────────────────────────────────────────────
# Resultado del workflow
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class AdvisoryWorkflowResult:
    """
    Snapshot completo del flujo de asesoría para un cliente.

    Campos opcionales (None permitido) reflejan las etapas que pudieron
    haberse omitido por bloqueos tempranos:
        - covariance_matrix: None si universo final está vacío.
        - portfolio_feasibility_result: None si universo final está vacío
          o si Goal Feasibility ya bloqueó antes.
        - candidate_set: None en cualquier ruta bloqueada (Goal, universo
          vacío, Portfolio Feasibility infactible, falla del generator).
    """

    status: AdvisoryWorkflowStatus
    client_id: str
    approved_profile_name: str
    advisor_comment: str
    m1_result: Any
    goal_feasibility_result: Any
    risk_budget: RiskBudget | None
    governance_passed_tickers: list[str]
    suitability_passed_tickers: list[str]
    esg_blocked_tickers: list[str]
    data_quality_failed_tickers: list[str]
    final_optimizer_tickers: list[str]
    return_estimates: list[ReturnEstimate]
    covariance_matrix: CovarianceMatrix | None
    portfolio_feasibility_result: PortfolioFeasibilityResult | None
    candidate_set: PortfolioCandidateSet | None
    reason_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.status, AdvisoryWorkflowStatus):
            raise ValueError(
                f"status debe ser AdvisoryWorkflowStatus. Recibido: "
                f"{type(self.status).__name__}."
            )
        if not self.client_id or not self.client_id.strip():
            raise ValueError("client_id no puede estar vacío.")

        if self.status != AdvisoryWorkflowStatus.FAILED:
            if not self.approved_profile_name or not self.approved_profile_name.strip():
                raise ValueError(
                    "approved_profile_name no puede estar vacío salvo en status FAILED."
                )

        for attr in (
            "governance_passed_tickers",
            "suitability_passed_tickers",
            "esg_blocked_tickers",
            "data_quality_failed_tickers",
            "final_optimizer_tickers",
            "return_estimates",
            "reason_codes",
            "warnings",
            "notes",
        ):
            if not isinstance(getattr(self, attr), list):
                raise ValueError(f"{attr} debe ser una lista.")

    @property
    def is_completed(self) -> bool:
        return self.status in (
            AdvisoryWorkflowStatus.COMPLETED,
            AdvisoryWorkflowStatus.COMPLETED_WITH_WARNINGS,
        )

    @property
    def has_portfolios(self) -> bool:
        return self.candidate_set is not None and self.candidate_set.count > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def to_dict(self) -> dict[str, Any]:
        """
        Representación JSON-serializable del resultado.

        Política: solo emite primitivos. Los objetos complejos
        (m1_result, candidate_set, etc.) se serializan vía sus propios
        to_dict() cuando existen, o se reducen a un descriptor mínimo.
        """
        return {
            "status": self.status.value,
            "client_id": self.client_id,
            "approved_profile_name": self.approved_profile_name,
            "advisor_comment": self.advisor_comment,
            "m1_result": _m1_result_to_dict(self.m1_result),
            "goal_feasibility_result": (
                self.goal_feasibility_result.to_dict()
                if self.goal_feasibility_result is not None
                else None
            ),
            "risk_budget": (
                self.risk_budget.to_dict() if self.risk_budget is not None else None
            ),
            "governance_passed_tickers": list(self.governance_passed_tickers),
            "suitability_passed_tickers": list(self.suitability_passed_tickers),
            "esg_blocked_tickers": list(self.esg_blocked_tickers),
            "data_quality_failed_tickers": list(self.data_quality_failed_tickers),
            "final_optimizer_tickers": list(self.final_optimizer_tickers),
            "return_estimates": [e.to_dict() for e in self.return_estimates],
            "covariance_matrix": (
                self.covariance_matrix.to_dict()
                if self.covariance_matrix is not None
                else None
            ),
            "portfolio_feasibility_result": (
                self.portfolio_feasibility_result.to_dict()
                if self.portfolio_feasibility_result is not None
                else None
            ),
            "candidate_set": (
                self.candidate_set.to_dict()
                if self.candidate_set is not None
                else None
            ),
            "reason_codes": list(self.reason_codes),
            "warnings": list(self.warnings),
            "notes": list(self.notes),
            "is_completed": self.is_completed,
            "has_portfolios": self.has_portfolios,
            "has_warnings": self.has_warnings,
        }


def _m1_result_to_dict(m1_result: Any) -> dict[str, Any] | None:
    """
    Reduce M1SessionResult a un dict JSON-serializable.

    No requiere que M1SessionResult tenga to_dict propio: extraemos solo
    los campos primitivos relevantes para auditoría.
    """
    if m1_result is None:
        return None
    out: dict[str, Any] = {
        "session_id": getattr(m1_result, "session_id", None),
        "client_id": getattr(m1_result, "client_id", None),
        "advisor_id": getattr(m1_result, "advisor_id", None),
        "follow_up_rounds_executed": getattr(
            m1_result, "follow_up_rounds_executed", 0
        ),
        "advisor_modified_profile": getattr(
            m1_result, "advisor_modified_profile", False
        ),
    }
    prelim_initial = getattr(m1_result, "preliminary_profile_initial", None)
    if prelim_initial is not None:
        out["preliminary_profile_initial"] = getattr(
            prelim_initial, "profile_name", None
        )
    prelim_revised = getattr(m1_result, "preliminary_profile_revised", None)
    if prelim_revised is not None:
        out["preliminary_profile_revised"] = getattr(
            prelim_revised, "profile_name", None
        )
    approved = getattr(m1_result, "approved_profile", None)
    if approved is not None:
        out["approved_profile"] = {
            "profile_name": getattr(approved, "profile_name", None),
            "original_profile": getattr(approved, "original_profile", None),
            "is_modified": getattr(approved, "is_modified", None),
            "advisor_comment": getattr(approved, "advisor_comment", ""),
        }
    audit = getattr(m1_result, "audit", None)
    if audit is not None and hasattr(audit, "event_types"):
        out["audit_event_types"] = list(audit.event_types())
        out["audit_closed"] = getattr(audit, "is_closed", None)
    return out


# ─────────────────────────────────────────────────────────────────────────
# Coordinator
# ─────────────────────────────────────────────────────────────────────────


class AdvisoryWorkflowCoordinator:
    """
    Orquesta el flujo completo de asesoría productivamente.

    Componentes internos por defecto (todos inyectables vía __init__):
        - RiskFirstSuitabilityEngine: ejecuta el flujo M1 (KYC → asesor).
        - GoalFeasibilityEngine
        - RiskBudgetBuilder
        - ESGComplianceChecker
        - DataQualityGate
        - ReturnEstimator
        - CovarianceEngine
        - PortfolioFeasibilityChecker
        - PortfolioGenerationCoordinator

    No tiene estado entre llamadas: cada `run(...)` es independiente y
    construye un AdvisoryWorkflowResult nuevo.
    """

    def __init__(
        self,
        goal_feasibility_engine: GoalFeasibilityEngine | None = None,
        risk_budget_builder: RiskBudgetBuilder | None = None,
        esg_checker: ESGComplianceChecker | None = None,
        data_quality_gate: DataQualityGate | None = None,
        return_estimator: ReturnEstimator | None = None,
        covariance_engine: CovarianceEngine | None = None,
        portfolio_feasibility_checker: PortfolioFeasibilityChecker | None = None,
        portfolio_generation_coordinator: PortfolioGenerationCoordinator | None = None,
    ) -> None:
        self._goal_engine = goal_feasibility_engine or GoalFeasibilityEngine()
        self._rb_builder = risk_budget_builder or RiskBudgetBuilder()
        self._esg_checker = esg_checker or ESGComplianceChecker()
        self._dq_gate = data_quality_gate or DataQualityGate()
        self._return_estimator = return_estimator or ReturnEstimator()
        self._covariance_engine = covariance_engine or CovarianceEngine()
        self._portfolio_feasibility_checker = (
            portfolio_feasibility_checker or PortfolioFeasibilityChecker()
        )
        self._portfolio_coordinator = (
            portfolio_generation_coordinator or PortfolioGenerationCoordinator()
        )

    # ── Método principal ───────────────────────────────────────────────────

    def run(
        self,
        kyc_data: KYCData,
        financial_goal: FinancialGoal,
        client_id: str,
        advisor_id: str,
        ai_client: Any,
        advisor_interface: Any,
        product_universe: ApprovedProductUniverse,
        suitability_matrix: InstrumentSuitabilityMatrix,
        esg_metadata_store: ESGMetadataStore,
        market_data_provider: MockMarketDataProvider,
    ) -> AdvisoryWorkflowResult:
        """Ejecuta el flujo completo y devuelve un AdvisoryWorkflowResult."""

        # ── A. M1: KYC → IA → asesor ──────────────────────────────────
        engine = RiskFirstSuitabilityEngine(
            ai_client=ai_client,
            advisor_interface=advisor_interface,
        )
        m1_result = engine.run_m1(
            kyc=kyc_data,
            financial_goal=financial_goal,
            client_id=client_id,
            advisor_id=advisor_id,
        )
        approved_profile_name = m1_result.approved_profile.profile_name
        advisor_comment = m1_result.approved_profile.advisor_comment

        reason_codes: list[str] = []
        warnings: list[str] = []
        notes: list[str] = []

        # ── B. Goal feasibility ───────────────────────────────────────
        feasibility_report = self._goal_engine.evaluate(
            financial_goal, approved_profile_name
        )

        if feasibility_report.block_portfolio_generation:
            reason_codes.append(RC_GOAL_FEASIBILITY_BLOCKED)
            notes.append(
                f"GoalFeasibilityEngine bloqueó la generación: "
                f"{feasibility_report.reason}"
            )
            for action in feasibility_report.suggested_actions:
                notes.append(f"Sugerencia: {action}")
            return AdvisoryWorkflowResult(
                status=AdvisoryWorkflowStatus.BLOCKED_BY_GOAL_FEASIBILITY,
                client_id=client_id,
                approved_profile_name=approved_profile_name,
                advisor_comment=advisor_comment,
                m1_result=m1_result,
                goal_feasibility_result=feasibility_report,
                risk_budget=None,
                governance_passed_tickers=[],
                suitability_passed_tickers=[],
                esg_blocked_tickers=[],
                data_quality_failed_tickers=[],
                final_optimizer_tickers=[],
                return_estimates=[],
                covariance_matrix=None,
                portfolio_feasibility_result=None,
                candidate_set=None,
                reason_codes=reason_codes,
                warnings=warnings,
                notes=notes,
            )

        # ── C. Risk budget ────────────────────────────────────────────
        risk_budget = self._rb_builder.build(
            approved_profile_name, kyc_data, financial_goal
        )

        # ── D, E, F, G. Pipeline de filtrado ──────────────────────────
        (
            governance_passed_tickers,
            suitability_passed_tickers,
            esg_blocked_tickers,
            data_quality_failed_tickers,
            final_optimizer_tickers,
            esg_by_ticker,
            dq_by_ticker,
        ) = self._filter_pipeline(
            profile_name=approved_profile_name,
            esg_profile=kyc_data.esg_profile,
            product_universe=product_universe,
            suitability_matrix=suitability_matrix,
            esg_metadata_store=esg_metadata_store,
            market_data_provider=market_data_provider,
            reason_codes=reason_codes,
            warnings=warnings,
            notes=notes,
        )

        # ── H. Universo final vacío ───────────────────────────────────
        if not final_optimizer_tickers:
            reason_codes.append(RC_PORTFOLIO_EMPTY_FINAL_UNIVERSE)
            notes.append(
                "El universo final está vacío tras governance, suitability, "
                "ESG y data quality. No hay instrumentos para optimizar."
            )
            return AdvisoryWorkflowResult(
                status=AdvisoryWorkflowStatus.BLOCKED_BY_EMPTY_UNIVERSE,
                client_id=client_id,
                approved_profile_name=approved_profile_name,
                advisor_comment=advisor_comment,
                m1_result=m1_result,
                goal_feasibility_result=feasibility_report,
                risk_budget=risk_budget,
                governance_passed_tickers=governance_passed_tickers,
                suitability_passed_tickers=suitability_passed_tickers,
                esg_blocked_tickers=esg_blocked_tickers,
                data_quality_failed_tickers=data_quality_failed_tickers,
                final_optimizer_tickers=[],
                return_estimates=[],
                covariance_matrix=None,
                portfolio_feasibility_result=None,
                candidate_set=None,
                reason_codes=reason_codes,
                warnings=warnings,
                notes=notes,
            )

        # ── I. Return estimates ───────────────────────────────────────
        snapshots = [
            market_data_provider.get_snapshot(t) for t in final_optimizer_tickers
        ]
        # Filtramos None defensivamente (no debería haber: el filter ya validó).
        snapshots = [s for s in snapshots if s is not None]

        return_estimates = self._return_estimator.estimate_many(
            snapshots=snapshots,
            esg_results_by_ticker={t: esg_by_ticker[t] for t in final_optimizer_tickers},
            data_quality_results_by_ticker={
                t: dq_by_ticker[t] for t in final_optimizer_tickers
            },
        )

        # ── J. Covariance matrix ──────────────────────────────────────
        covariance_matrix = self._covariance_engine.build(snapshots)

        # ── K. Portfolio feasibility pre-check ────────────────────────
        portfolio_feasibility = self._portfolio_feasibility_checker.evaluate(
            return_estimates=return_estimates,
            covariance_matrix=covariance_matrix,
            risk_budget=risk_budget,
        )

        if portfolio_feasibility.status == PortfolioFeasibilityStatus.WARNING:
            warnings.append(
                "Portfolio feasibility con warnings: "
                f"{portfolio_feasibility.warnings}"
            )
            reason_codes.append(RC_PORTFOLIO_FEASIBILITY_WARNING)

        if not portfolio_feasibility.is_feasible:
            reason_codes.append(RC_PORTFOLIO_GENERATION_BLOCKED)
            notes.append(
                "El RiskBudget aprobado no es factible con el universo final. "
                "Política productiva: el workflow NO relaja max_single_asset "
                "ni max_volatility automáticamente."
            )
            for fc in portfolio_feasibility.failed_checks:
                notes.append(f"failed_check: {fc}")
            for action in portfolio_feasibility.suggested_actions:
                notes.append(f"Sugerencia: {action}")
            return AdvisoryWorkflowResult(
                status=AdvisoryWorkflowStatus.BLOCKED_BY_PORTFOLIO_FEASIBILITY,
                client_id=client_id,
                approved_profile_name=approved_profile_name,
                advisor_comment=advisor_comment,
                m1_result=m1_result,
                goal_feasibility_result=feasibility_report,
                risk_budget=risk_budget,
                governance_passed_tickers=governance_passed_tickers,
                suitability_passed_tickers=suitability_passed_tickers,
                esg_blocked_tickers=esg_blocked_tickers,
                data_quality_failed_tickers=data_quality_failed_tickers,
                final_optimizer_tickers=final_optimizer_tickers,
                return_estimates=return_estimates,
                covariance_matrix=covariance_matrix,
                portfolio_feasibility_result=portfolio_feasibility,
                candidate_set=None,
                reason_codes=reason_codes,
                warnings=warnings,
                notes=notes,
            )

        # ── L. Portfolio generation ───────────────────────────────────
        try:
            candidate_set = self._portfolio_coordinator.generate(
                client_id=client_id,
                approved_profile_name=approved_profile_name,
                return_estimates=return_estimates,
                covariance_matrix=covariance_matrix,
                risk_budget=risk_budget,
            )
        except ValueError as exc:
            # Caso borde: el pre-check pasó (status FEASIBLE o WARNING) pero el
            # coordinator igualmente no logró ninguna variante. Casi siempre
            # significa que DEFENSIVE derivó un sub-budget interno infactible
            # y BALANCED/GROWTH fallaron en el solver. Política productiva:
            # NO relajar; reportar y dejar al asesor.
            reason_codes.append(RC_PORTFOLIO_GENERATION_BLOCKED)
            notes.append(
                f"PortfolioGenerationCoordinator no logró ninguna variante: {exc}"
            )
            return AdvisoryWorkflowResult(
                status=AdvisoryWorkflowStatus.BLOCKED_BY_PORTFOLIO_FEASIBILITY,
                client_id=client_id,
                approved_profile_name=approved_profile_name,
                advisor_comment=advisor_comment,
                m1_result=m1_result,
                goal_feasibility_result=feasibility_report,
                risk_budget=risk_budget,
                governance_passed_tickers=governance_passed_tickers,
                suitability_passed_tickers=suitability_passed_tickers,
                esg_blocked_tickers=esg_blocked_tickers,
                data_quality_failed_tickers=data_quality_failed_tickers,
                final_optimizer_tickers=final_optimizer_tickers,
                return_estimates=return_estimates,
                covariance_matrix=covariance_matrix,
                portfolio_feasibility_result=portfolio_feasibility,
                candidate_set=None,
                reason_codes=reason_codes,
                warnings=warnings,
                notes=notes,
            )

        # Propagar reason_codes del candidate set (variantes infactibles del
        # coordinator, p. ej. DEFENSIVE omitida por sub-budget interno).
        for rc in candidate_set.reason_codes:
            if rc not in reason_codes:
                reason_codes.append(rc)

        # Estado final
        status = (
            AdvisoryWorkflowStatus.COMPLETED_WITH_WARNINGS
            if warnings
            else AdvisoryWorkflowStatus.COMPLETED
        )

        return AdvisoryWorkflowResult(
            status=status,
            client_id=client_id,
            approved_profile_name=approved_profile_name,
            advisor_comment=advisor_comment,
            m1_result=m1_result,
            goal_feasibility_result=feasibility_report,
            risk_budget=risk_budget,
            governance_passed_tickers=governance_passed_tickers,
            suitability_passed_tickers=suitability_passed_tickers,
            esg_blocked_tickers=esg_blocked_tickers,
            data_quality_failed_tickers=data_quality_failed_tickers,
            final_optimizer_tickers=final_optimizer_tickers,
            return_estimates=return_estimates,
            covariance_matrix=covariance_matrix,
            portfolio_feasibility_result=portfolio_feasibility,
            candidate_set=candidate_set,
            reason_codes=reason_codes,
            warnings=warnings,
            notes=notes,
        )

    # ── Pipeline de filtrado interno ─────────────────────────────────────

    def _filter_pipeline(
        self,
        profile_name: str,
        esg_profile: Any,
        product_universe: ApprovedProductUniverse,
        suitability_matrix: InstrumentSuitabilityMatrix,
        esg_metadata_store: ESGMetadataStore,
        market_data_provider: MockMarketDataProvider,
        reason_codes: list[str],
        warnings: list[str],
        notes: list[str],
    ):
        """
        Aplica governance → suitability → ESG → data quality.

        Muta las listas `reason_codes`, `warnings` y `notes` agregando
        diagnósticos por ticker excluido o degradado.
        """
        esg_by_ticker = {}
        dq_by_ticker = {}

        # D. Governance
        governance_records = product_universe.filter_for_profile(profile_name)
        governance_passed_tickers = [r.ticker for r in governance_records]

        # E. Suitability
        suitability_passed_tickers: list[str] = []
        suitability_passed_records: list[ProductGovernanceRecord] = []
        for rec in governance_records:
            rule = suitability_matrix.evaluate(
                _suitability_type_for(rec), profile_name
            )
            if rule.status == InstrumentSuitabilityStatus.ALLOWED:
                suitability_passed_tickers.append(rec.ticker)
                suitability_passed_records.append(rec)
            elif rule.status == InstrumentSuitabilityStatus.LIMITED:
                suitability_passed_tickers.append(rec.ticker)
                suitability_passed_records.append(rec)
                warnings.append(
                    f"Suitability LIMITED para {rec.ticker} "
                    f"(max_allocation={rule.max_allocation})."
                )
                if RC_SUITABILITY_LIMITED not in reason_codes:
                    reason_codes.append(RC_SUITABILITY_LIMITED)
            # NOT_ALLOWED: simplemente se excluye. Las exclusiones quedan
            # implícitas por diferencia entre governance_passed y suitability_passed.

        # F. ESG
        esg_blocked_tickers: list[str] = []
        esg_passed_records: list[ProductGovernanceRecord] = []
        for rec in suitability_passed_records:
            result = self._esg_checker.evaluate(
                rec.ticker, esg_profile, esg_metadata_store
            )
            esg_by_ticker[rec.ticker] = result
            if result.is_blocked:
                esg_blocked_tickers.append(rec.ticker)
                if RC_ESG_BLOCKED not in reason_codes:
                    reason_codes.append(RC_ESG_BLOCKED)
                notes.append(
                    f"ESG bloqueado {rec.ticker}: {result.blocked_by}"
                )
                continue
            esg_passed_records.append(rec)
            if result.status == ESGComplianceStatus.UNKNOWN:
                warnings.append(
                    f"ESG UNKNOWN para {rec.ticker}: sin metadata ESG."
                )
                if RC_ESG_WARNING not in reason_codes:
                    reason_codes.append(RC_ESG_WARNING)
            elif result.status == ESGComplianceStatus.SOFT_WARNING:
                warnings.append(
                    f"ESG SOFT_WARNING para {rec.ticker}: "
                    f"{len(result.warnings)} preferencia(s) incumplida(s)."
                )
                if RC_ESG_WARNING not in reason_codes:
                    reason_codes.append(RC_ESG_WARNING)

        # G. Market data + Data quality
        data_quality_failed_tickers: list[str] = []
        final_optimizer_tickers: list[str] = []
        for rec in esg_passed_records:
            snap = market_data_provider.get_snapshot(rec.ticker)
            if snap is None:
                notes.append(
                    f"Sin market data para {rec.ticker} → excluido del universo final."
                )
                if RC_DATA_MISSING not in reason_codes:
                    reason_codes.append(RC_DATA_MISSING)
                continue

            dq_result = self._dq_gate.evaluate(snap)
            dq_by_ticker[rec.ticker] = dq_result

            if dq_result.status == DataQualityStatus.FAIL or not dq_result.is_usable:
                data_quality_failed_tickers.append(rec.ticker)
                if RC_DATA_QUALITY_FAILED not in reason_codes:
                    reason_codes.append(RC_DATA_QUALITY_FAILED)
                notes.append(
                    f"DataQuality FAIL para {rec.ticker}: "
                    f"reason_codes={dq_result.reason_codes}"
                )
                continue

            if dq_result.status == DataQualityStatus.WARNING:
                warnings.append(
                    f"DataQuality WARNING para {rec.ticker}: "
                    f"reason_codes={dq_result.reason_codes}"
                )

            final_optimizer_tickers.append(rec.ticker)

        return (
            governance_passed_tickers,
            suitability_passed_tickers,
            esg_blocked_tickers,
            data_quality_failed_tickers,
            final_optimizer_tickers,
            esg_by_ticker,
            dq_by_ticker,
        )
