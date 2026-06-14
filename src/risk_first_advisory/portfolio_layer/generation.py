"""
PortfolioGenerationCoordinator — genera 3 carteras candidatas para un cliente.

Variantes:
    DEFENSIVE : MIN_VARIANCE con restricciones más conservadoras
    BALANCED  : MAX_UTILITY con risk_budget original (nunca excede el budget aprobado)
    GROWTH    : MAX_RETURN con growth_budget derivado (puede exceder parcialmente el
                budget aprobado; queda marcado con requires_advisor_override=True)

Política de variantes (PortfolioVariantMetadata):
    - BALANCED y DEFENSIVE nunca marcan risk_budget_exceeded ni requires_advisor_override.
    - GROWTH recibe un growth_budget que relaja max_volatility y, si es necesario,
      max_single_asset. Las dimensiones relajadas se registran en exceeded_constraints.
      Si al menos una dimensión es relajada, la variante queda marcada con
      requires_advisor_override=True y reason_code
      PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET.
    - La metadata no oculta excesos: es auditable en to_dict().

INVARIANTE sobre pre-check:
    El optimizer NO es la primera capa que detecta infactibilidad. Antes de cada
    llamada al optimizer, el coordinator corre PortfolioFeasibilityChecker sobre la
    combinación (return_estimates, covariance_matrix, budget de la variante). Si el
    pre-check devuelve INFEASIBLE, la variante se omite SIN invocar al optimizer y se
    registran reason_codes y notas accionables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from risk_first_advisory.data_layer.covariance import CovarianceMatrix
from risk_first_advisory.data_layer.return_estimator import ReturnEstimate
from risk_first_advisory.models.risk_budget import RiskBudget
from risk_first_advisory.portfolio_layer.feasibility import (
    PortfolioFeasibilityChecker,
    PortfolioFeasibilityResult,
    PortfolioFeasibilityStatus,
)
from risk_first_advisory.portfolio_layer.optimizer import (
    OptimizationInput,
    OptimizationObjective,
    OptimizedPortfolio,
    PortfolioOptimizer,
)

# ---------------------------------------------------------------------------
# Constantes / reason codes
# ---------------------------------------------------------------------------

RC_VARIANT_INFEASIBLE = "PORTFOLIO_VARIANT_INFEASIBLE"
RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET = "PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"

_DEFENSIVE_MAX_SINGLE_ASSET_CAP = 0.20


# ---------------------------------------------------------------------------
# PortfolioVariant
# ---------------------------------------------------------------------------

class PortfolioVariant(Enum):
    DEFENSIVE = "DEFENSIVE"
    BALANCED = "BALANCED"
    GROWTH = "GROWTH"


# Orden canónico de variantes
_VARIANT_ORDER: list[PortfolioVariant] = [
    PortfolioVariant.DEFENSIVE,
    PortfolioVariant.BALANCED,
    PortfolioVariant.GROWTH,
]


# ---------------------------------------------------------------------------
# PortfolioVariantMetadata
# ---------------------------------------------------------------------------

@dataclass
class PortfolioVariantMetadata:
    """
    Indica si una cartera candidata excede el RiskBudget aprobado y si
    requiere override explícito del asesor.

    Invariantes:
        - risk_budget_exceeded=True implica requires_advisor_override=True
        - GROWTH con requires_advisor_override=True debe incluir
          RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET en reason_codes
    """

    variant: PortfolioVariant
    risk_budget_exceeded: bool
    requires_advisor_override: bool
    exceeded_constraints: list[str]
    reason_codes: list[str]
    notes: list[str]

    def __post_init__(self) -> None:
        if not isinstance(self.variant, PortfolioVariant):
            raise ValueError(
                f"variant debe ser PortfolioVariant. Recibido: {type(self.variant).__name__}."
            )
        if not isinstance(self.risk_budget_exceeded, bool):
            raise ValueError("risk_budget_exceeded debe ser bool.")
        if not isinstance(self.requires_advisor_override, bool):
            raise ValueError("requires_advisor_override debe ser bool.")
        if not isinstance(self.exceeded_constraints, list):
            raise ValueError("exceeded_constraints debe ser list.")
        if not isinstance(self.reason_codes, list):
            raise ValueError("reason_codes debe ser list.")
        if not isinstance(self.notes, list):
            raise ValueError("notes debe ser list.")

        if self.risk_budget_exceeded and not self.requires_advisor_override:
            raise ValueError(
                "risk_budget_exceeded=True requiere requires_advisor_override=True."
            )

        if (
            self.requires_advisor_override
            and self.variant == PortfolioVariant.GROWTH
            and RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET not in self.reason_codes
        ):
            raise ValueError(
                f"GROWTH con requires_advisor_override=True debe incluir "
                f"{RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET!r} en reason_codes."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant.value,
            "risk_budget_exceeded": self.risk_budget_exceeded,
            "requires_advisor_override": self.requires_advisor_override,
            "exceeded_constraints": list(self.exceeded_constraints),
            "reason_codes": list(self.reason_codes),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# PortfolioCandidateSet
# ---------------------------------------------------------------------------

@dataclass
class PortfolioCandidateSet:
    """
    Conjunto de carteras candidatas generadas para un cliente.

    Invariantes:
        - client_id y approved_profile_name no vacíos
        - candidates no vacío, claves PortfolioVariant, valores OptimizedPortfolio
        - selected_variant None o presente en candidates
        - reason_codes y notes son listas
        - metadata: si no se provee, se crea metadata default (sin override) para
          cada candidato. Si se provee, sus claves deben ser PortfolioVariant presentes
          en candidates y sus valores PortfolioVariantMetadata.
    """

    client_id: str
    approved_profile_name: str
    candidates: dict[PortfolioVariant, OptimizedPortfolio]
    selected_variant: PortfolioVariant | None = None
    reason_codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metadata: dict[PortfolioVariant, PortfolioVariantMetadata] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.client_id or not self.client_id.strip():
            raise ValueError("client_id no puede estar vacío.")

        if not self.approved_profile_name or not self.approved_profile_name.strip():
            raise ValueError("approved_profile_name no puede estar vacío.")

        if not self.candidates:
            raise ValueError("candidates no puede estar vacío.")

        for k, v in self.candidates.items():
            if not isinstance(k, PortfolioVariant):
                raise ValueError(
                    f"Todas las claves de candidates deben ser PortfolioVariant. "
                    f"Encontrado: {type(k).__name__}."
                )
            if not isinstance(v, OptimizedPortfolio):
                raise ValueError(
                    f"Todos los valores de candidates deben ser OptimizedPortfolio. "
                    f"Encontrado: {type(v).__name__}."
                )

        if self.selected_variant is not None:
            if self.selected_variant not in self.candidates:
                raise ValueError(
                    f"selected_variant {self.selected_variant!r} no está "
                    f"dentro de candidates."
                )

        if not isinstance(self.reason_codes, list):
            raise ValueError("reason_codes debe ser una lista.")

        if not isinstance(self.notes, list):
            raise ValueError("notes debe ser una lista.")

        # Auto-fill metadata con defaults si no se proveyó.
        if not self.metadata:
            for variant in self.candidates:
                self.metadata[variant] = PortfolioVariantMetadata(
                    variant=variant,
                    risk_budget_exceeded=False,
                    requires_advisor_override=False,
                    exceeded_constraints=[],
                    reason_codes=[],
                    notes=[],
                )

        # Validar metadata provista (o la auto-completada).
        for k, v in self.metadata.items():
            if not isinstance(k, PortfolioVariant):
                raise ValueError(
                    f"metadata keys deben ser PortfolioVariant. "
                    f"Encontrado: {type(k).__name__}."
                )
            if not isinstance(v, PortfolioVariantMetadata):
                raise ValueError(
                    f"metadata values deben ser PortfolioVariantMetadata. "
                    f"Encontrado: {type(v).__name__}."
                )
            if k not in self.candidates:
                raise ValueError(
                    f"metadata refiere a variante {k!r} no presente en candidates."
                )

    # ── Accesores ──────────────────────────────────────────────────────────

    def get_candidate(self, variant: PortfolioVariant) -> OptimizedPortfolio:
        """Devuelve el portfolio de la variante solicitada.

        Raises:
            KeyError: si la variante no existe en candidates.
        """
        if variant not in self.candidates:
            raise KeyError(
                f"Variante {variant!r} no presente en candidates. "
                f"Disponibles: {list(self.candidates.keys())}."
            )
        return self.candidates[variant]

    def variants(self) -> list[PortfolioVariant]:
        """Devuelve las variantes disponibles en orden canónico (DEFENSIVE, BALANCED, GROWTH)."""
        return [v for v in _VARIANT_ORDER if v in self.candidates]

    @property
    def count(self) -> int:
        """Número de candidatos en el set."""
        return len(self.candidates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "approved_profile_name": self.approved_profile_name,
            "candidates": {
                variant.value: portfolio.to_dict()
                for variant, portfolio in self.candidates.items()
            },
            "selected_variant": (
                self.selected_variant.value
                if self.selected_variant is not None
                else None
            ),
            "reason_codes": list(self.reason_codes),
            "notes": list(self.notes),
            "metadata": {
                variant.value: meta.to_dict()
                for variant, meta in self.metadata.items()
            },
        }


# ---------------------------------------------------------------------------
# PortfolioGenerationCoordinator
# ---------------------------------------------------------------------------

class PortfolioGenerationCoordinator:
    """
    Genera hasta 3 carteras candidatas para un cliente.

    Política de variantes:
        DEFENSIVE — MIN_VARIANCE, budget conservador derivado. Nunca excede el
            RiskBudget aprobado. requires_advisor_override siempre False.
        BALANCED  — MAX_UTILITY, budget aprobado original. Nunca excede el
            RiskBudget aprobado. requires_advisor_override siempre False.
        GROWTH    — MAX_RETURN, growth_budget derivado con max_volatility y opcionalmente
            max_single_asset relajados. Si alguna dimensión es relajada respecto al
            budget original, la variante queda marcada con risk_budget_exceeded=True,
            requires_advisor_override=True y reason_code
            PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET.

    Flujo por variante:
        1. Construye el budget de la variante.
        2. Pre-check de factibilidad con PortfolioFeasibilityChecker.
        3. Si INFEASIBLE → variante omitida, se registra reason_code y nota.
        4. Si WARNING → se intenta optimizar; warnings propagados a notes.
        5. Si FEASIBLE → se optimiza normalmente.
        6. Si el optimizer falla pese al pre-check OK → omitir con reason_code.
    """

    def __init__(
        self,
        feasibility_checker: PortfolioFeasibilityChecker | None = None,
        optimizer: PortfolioOptimizer | None = None,
    ) -> None:
        self._feasibility_checker = feasibility_checker or PortfolioFeasibilityChecker()
        self._optimizer = optimizer or PortfolioOptimizer()

    def generate(
        self,
        client_id: str,
        approved_profile_name: str,
        return_estimates: list[ReturnEstimate],
        covariance_matrix: CovarianceMatrix,
        risk_budget: RiskBudget,
    ) -> PortfolioCandidateSet:
        """
        Genera las tres carteras candidatas.

        Raises:
            ValueError: si ninguna variante es factible.
        """
        candidates: dict[PortfolioVariant, OptimizedPortfolio] = {}
        metadata_by_variant: dict[PortfolioVariant, PortfolioVariantMetadata] = {}
        reason_codes: list[str] = []
        notes: list[str] = []

        asset_count = len(return_estimates)
        growth_budget, growth_exceeded = self._growth_budget(risk_budget, asset_count)

        # ── Especificaciones de cada variante ──────────────────────────────
        variant_specs: list[tuple[PortfolioVariant, OptimizationObjective, RiskBudget, list[str]]] = [
            (
                PortfolioVariant.DEFENSIVE,
                OptimizationObjective.MIN_VARIANCE,
                self._defensive_budget(risk_budget, asset_count=asset_count),
                [],
            ),
            (
                PortfolioVariant.BALANCED,
                OptimizationObjective.MAX_UTILITY,
                risk_budget,
                [],
            ),
            (
                PortfolioVariant.GROWTH,
                OptimizationObjective.MAX_RETURN,
                growth_budget,
                growth_exceeded,
            ),
        ]

        for variant, objective, budget, exceeded in variant_specs:
            # ── Pre-check de factibilidad ─────────────────────────────────
            feasibility = self._feasibility_checker.evaluate(
                return_estimates=return_estimates,
                covariance_matrix=covariance_matrix,
                risk_budget=budget,
            )

            if not feasibility.is_feasible:
                self._record_pre_check_infeasibility(
                    variant=variant,
                    feasibility=feasibility,
                    reason_codes=reason_codes,
                    notes=notes,
                )
                continue

            if feasibility.status == PortfolioFeasibilityStatus.WARNING:
                self._record_pre_check_warnings(
                    variant=variant,
                    feasibility=feasibility,
                    notes=notes,
                )

            # ── Llamada al optimizer ──────────────────────────────────────
            try:
                inp = OptimizationInput(
                    return_estimates=return_estimates,
                    covariance_matrix=covariance_matrix,
                    risk_budget=budget,
                    objective=objective,
                )
                portfolio = self._optimizer.optimize(inp)
                candidates[variant] = portfolio

                # ── Metadata de política ──────────────────────────────────
                if exceeded:
                    metadata_by_variant[variant] = PortfolioVariantMetadata(
                        variant=variant,
                        risk_budget_exceeded=True,
                        requires_advisor_override=True,
                        exceeded_constraints=list(exceeded),
                        reason_codes=[RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET],
                        notes=[
                            "GROWTH exceeds approved RiskBudget and requires "
                            "explicit advisor override."
                        ],
                    )
                else:
                    metadata_by_variant[variant] = PortfolioVariantMetadata(
                        variant=variant,
                        risk_budget_exceeded=False,
                        requires_advisor_override=False,
                        exceeded_constraints=[],
                        reason_codes=[],
                        notes=[],
                    )

            except ValueError as exc:
                reason_codes.append(RC_VARIANT_INFEASIBLE)
                notes.append(
                    f"Variante {variant.value} omitida por fallo del "
                    f"optimizer pese a pre-check OK: {exc}"
                )

        if not candidates:
            raise ValueError(
                f"Ninguna variante (DEFENSIVE, BALANCED, GROWTH) resultó factible "
                f"para el cliente {client_id!r} con perfil {approved_profile_name!r}. "
                f"Revisar risk_budget y datos de mercado."
            )

        return PortfolioCandidateSet(
            client_id=client_id,
            approved_profile_name=approved_profile_name,
            candidates=candidates,
            selected_variant=None,
            reason_codes=reason_codes,
            notes=notes,
            metadata=metadata_by_variant,
        )

    # ── Helpers de registro ──────────────────────────────────────────────────

    @staticmethod
    def _record_pre_check_infeasibility(
        variant: PortfolioVariant,
        feasibility: PortfolioFeasibilityResult,
        reason_codes: list[str],
        notes: list[str],
    ) -> None:
        reason_codes.append(RC_VARIANT_INFEASIBLE)
        for fc in feasibility.failed_checks:
            reason_codes.append(fc)
        failed_list = ", ".join(feasibility.failed_checks) or "(sin códigos)"
        notes.append(
            f"Variante {variant.value} omitida por pre-check de factibilidad: "
            f"{failed_list}."
        )
        for action in feasibility.suggested_actions:
            notes.append(f"Variante {variant.value} → sugerencia: {action}")
        for n in feasibility.notes:
            notes.append(f"Variante {variant.value} → {n}")

    @staticmethod
    def _record_pre_check_warnings(
        variant: PortfolioVariant,
        feasibility: PortfolioFeasibilityResult,
        notes: list[str],
    ) -> None:
        warn_list = ", ".join(feasibility.warnings) or "(sin warnings)"
        notes.append(
            f"Variante {variant.value} con warnings de pre-check de "
            f"factibilidad: {warn_list}. Se procede a optimizar."
        )

    # ── Construcción del budget DEFENSIVE ────────────────────────────────────

    @staticmethod
    def _defensive_budget(rb: RiskBudget, asset_count: int) -> RiskBudget:
        """Deriva un RiskBudget más conservador para la variante DEFENSIVE."""
        defensive_max_vol = min(rb.max_volatility, rb.target_volatility)
        minimum_feasible_single_asset = (1.0 / asset_count) + 1e-6
        defensive_max_single = min(
            rb.max_single_asset,
            max(_DEFENSIVE_MAX_SINGLE_ASSET_CAP, minimum_feasible_single_asset),
        )
        defensive_target_vol = min(rb.target_volatility, defensive_max_vol)

        return RiskBudget(
            profile_name=rb.profile_name,
            target_volatility=defensive_target_vol,
            max_volatility=defensive_max_vol,
            max_drawdown=rb.max_drawdown,
            min_liquidity=rb.min_liquidity,
            max_equity=rb.max_equity,
            max_high_yield=rb.max_high_yield,
            max_single_asset=defensive_max_single,
            max_sector_exposure=rb.max_sector_exposure,
            max_duration=rb.max_duration,
            complex_products_allowed=rb.complex_products_allowed,
            preferred_currency=rb.preferred_currency,
            notes=list(rb.notes) + ["Derived defensive budget."],
        )

    # ── Construcción del budget GROWTH ───────────────────────────────────────

    @staticmethod
    def _growth_budget(rb: RiskBudget, asset_count: int) -> tuple[RiskBudget, list[str]]:
        """
        Deriva un RiskBudget relajado para GROWTH y lista las dimensiones excedidas.

        Solo relaja max_volatility: min(original * 1.50, original + 0.05).
        max_single_asset NO se relaja para preservar la interpretabilidad del
        perfil aprobado y mantener la compatibilidad con los pre-checks.

        Returns:
            (growth_budget, exceeded_constraints)
            exceeded_constraints lista los parámetros que superan al budget
            original: siempre "max_volatility".
        """
        exceeded: list[str] = []

        growth_max_vol = min(rb.max_volatility * 1.50, rb.max_volatility + 0.05)
        growth_target_vol = min(rb.target_volatility * 1.50, growth_max_vol)

        if growth_max_vol > rb.max_volatility:
            exceeded.append("max_volatility")

        budget = RiskBudget(
            profile_name=rb.profile_name,
            target_volatility=growth_target_vol,
            max_volatility=growth_max_vol,
            max_drawdown=rb.max_drawdown,
            min_liquidity=rb.min_liquidity,
            max_equity=rb.max_equity,
            max_high_yield=rb.max_high_yield,
            max_single_asset=rb.max_single_asset,
            max_sector_exposure=rb.max_sector_exposure,
            max_duration=rb.max_duration,
            complex_products_allowed=rb.complex_products_allowed,
            preferred_currency=rb.preferred_currency,
            notes=list(rb.notes) + ["Derived growth budget."],
        )
        return budget, exceeded
