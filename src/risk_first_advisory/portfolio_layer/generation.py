"""
PortfolioGenerationCoordinator — genera 3 carteras candidatas para un cliente.

Variantes:
    DEFENSIVE : MIN_VARIANCE con restricciones más conservadoras
    BALANCED  : MAX_UTILITY con risk_budget original
    GROWTH    : MAX_RETURN con risk_budget original

Regla central: las 3 carteras surgen del risk_budget aprobado. No se
inventan restricciones incompatibles ni se ignora el perfil aprobado.

Si una variante no es factible se omite con reason_code; si ninguna lo
es, se levanta ValueError.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from risk_first_advisory.data_layer.covariance import CovarianceMatrix
from risk_first_advisory.data_layer.return_estimator import ReturnEstimate
from risk_first_advisory.models.risk_budget import RiskBudget
from risk_first_advisory.portfolio_layer.optimizer import (
    OptimizationInput,
    OptimizationObjective,
    OptimizedPortfolio,
    PortfolioOptimizer,
)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

RC_VARIANT_INFEASIBLE = "PORTFOLIO_VARIANT_INFEASIBLE"
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
    """

    client_id: str
    approved_profile_name: str
    candidates: dict[PortfolioVariant, OptimizedPortfolio]
    selected_variant: PortfolioVariant | None = None
    reason_codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

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
        }


# ---------------------------------------------------------------------------
# PortfolioGenerationCoordinator
# ---------------------------------------------------------------------------

class PortfolioGenerationCoordinator:
    """
    Genera hasta 3 carteras candidatas para un cliente usando PortfolioOptimizer.

    No filtra instrumentos ni valida suitability: recibe datos ya preparados.
    """

    def __init__(self) -> None:
        self._optimizer = PortfolioOptimizer()

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
        reason_codes: list[str] = []
        notes: list[str] = []

        # ── Especificaciones de cada variante ──────────────────────────────
        variant_specs = [
            (
                PortfolioVariant.DEFENSIVE,
                OptimizationObjective.MIN_VARIANCE,
                self._defensive_budget(risk_budget, asset_count=len(return_estimates)),
            ),
            (
                PortfolioVariant.BALANCED,
                OptimizationObjective.MAX_UTILITY,
                risk_budget,
            ),
            (
                PortfolioVariant.GROWTH,
                OptimizationObjective.MAX_RETURN,
                risk_budget,
            ),
        ]

        for variant, objective, budget in variant_specs:
            try:
                inp = OptimizationInput(
                    return_estimates=return_estimates,
                    covariance_matrix=covariance_matrix,
                    risk_budget=budget,
                    objective=objective,
                )
                portfolio = self._optimizer.optimize(inp)
                candidates[variant] = portfolio
            except ValueError as exc:
                reason_codes.append(RC_VARIANT_INFEASIBLE)
                notes.append(
                    f"Variante {variant.value} omitida por infactibilidad: {exc}"
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
        )

    @staticmethod
    def _defensive_budget(rb: RiskBudget, asset_count: int) -> RiskBudget:
        """Deriva un RiskBudget más conservador para la variante DEFENSIVE."""
        defensive_max_vol = min(rb.max_volatility, rb.target_volatility)
        minimum_feasible_single_asset = (1.0 / asset_count) + 1e-6
        defensive_max_single = min(rb.max_single_asset, max( _DEFENSIVE_MAX_SINGLE_ASSET_CAP, minimum_feasible_single_asset))

        # target_volatility para el budget derivado debe ser <= max_volatility
        # Como reducimos max_volatility, ajustamos también target_volatility
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