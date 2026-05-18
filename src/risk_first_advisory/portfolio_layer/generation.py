"""
PortfolioGenerationCoordinator — genera 3 carteras candidatas para un cliente.

Variantes:
    DEFENSIVE : MIN_VARIANCE con restricciones más conservadoras
    BALANCED  : MAX_UTILITY con risk_budget original
    GROWTH    : MAX_RETURN con risk_budget original

Regla central: las 3 carteras surgen del risk_budget aprobado. No se
inventan restricciones incompatibles ni se ignora el perfil aprobado.

INVARIANTE NUEVO: el optimizer NO es la primera capa que detecta
infactibilidad. Antes de cada llamada al optimizer, el coordinator corre
PortfolioFeasibilityChecker sobre la combinación
(return_estimates, covariance_matrix, budget de la variante). Si el
pre-check devuelve INFEASIBLE, la variante se omite SIN invocar al
optimizer y se registran:
    - reason_code PORTFOLIO_VARIANT_INFEASIBLE en el candidate set
    - reason_codes específicos del feasibility (p. ej.
      PORTFOLIO_MAX_SINGLE_ASSET_TOO_LOW), acumulados sin reemplazar
    - notas legibles que mencionan "pre-check de factibilidad"

Esto produce mensajes accionables para el asesor en lugar de los
mensajes crípticos del solver.

Si el pre-check devuelve WARNING, la variante SÍ se intenta optimizar:
WARNING significa "factible pero degradado" (universo chico,
concentración alta, vol no determinada). Los warnings del pre-check se
propagan a las notas del candidate set para auditoría.

Si una variante pasa el pre-check pero el optimizer falla de todas formas
(por numerología del solver o restricciones blandas no capturadas por el
pre-check), se mantiene el comportamiento previo: omitir variante con
RC_VARIANT_INFEASIBLE y nota con el mensaje del optimizer.

Si ninguna variante queda disponible, se levanta ValueError.
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
    Genera hasta 3 carteras candidatas para un cliente.

    Flujo por variante:
        1. Construye el risk_budget de la variante (DEFENSIVE deriva uno
           más estricto; BALANCED y GROWTH usan el budget aprobado tal cual).
        2. Pre-check de factibilidad con PortfolioFeasibilityChecker.
        3. Si el pre-check dice INFEASIBLE → variante omitida, no se llama
           al optimizer, se registra reason_code y nota.
        4. Si dice WARNING → se intenta optimizar y los warnings del
           pre-check se propagan a notes del candidate set.
        5. Si dice FEASIBLE → se intenta optimizar normalmente.
        6. Si el optimizer falla aun habiendo pasado el pre-check → se
           omite la variante con reason_code y nota con el mensaje del
           solver (comportamiento previo preservado).

    No filtra instrumentos ni valida suitability: recibe datos ya preparados.
    """

    def __init__(
        self,
        feasibility_checker: PortfolioFeasibilityChecker | None = None,
        optimizer: PortfolioOptimizer | None = None,
    ) -> None:
        """
        Args:
            feasibility_checker: instancia de PortfolioFeasibilityChecker.
                Por defecto se construye una nueva. Aceptar la dependencia
                facilita testear el coordinator con un checker mockeado.
            optimizer: instancia de PortfolioOptimizer. Mismo criterio.
        """
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
            ValueError: si ninguna variante es factible (ni pasa el
                        pre-check ni el optimizer logra resolver).
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
            # ── Pre-check de factibilidad ─────────────────────────────────
            # Casos borde: si len(return_estimates) == 0 el budget DEFENSIVE
            # no se pudo construir (división por cero en _defensive_budget),
            # pero ese fallo ocurriría arriba antes de entrar al loop. Para
            # listas no vacías el pre-check siempre devuelve un resultado.
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

            # WARNING: factible pero degradado → optimizar y propagar warnings.
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
            except ValueError as exc:
                # El pre-check pasó pero el solver falla igual. Mantenemos
                # el comportamiento previo: omitimos con reason_code y nota
                # con el mensaje del solver.
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
        )

    # ── Helpers de registro ──────────────────────────────────────────────────

    @staticmethod
    def _record_pre_check_infeasibility(
        variant: PortfolioVariant,
        feasibility: PortfolioFeasibilityResult,
        reason_codes: list[str],
        notes: list[str],
    ) -> None:
        """Registra reason_codes y notes para una variante rechazada por el pre-check."""
        reason_codes.append(RC_VARIANT_INFEASIBLE)
        # También exponemos cada failed_check del feasibility en reason_codes,
        # para que el consumidor pueda razonar sobre el motivo específico
        # (PORTFOLIO_MAX_SINGLE_ASSET_TOO_LOW, etc.). Se acumulan sin
        # reemplazar, conservando el orden de detección.
        for fc in feasibility.failed_checks:
            reason_codes.append(fc)

        failed_list = ", ".join(feasibility.failed_checks) or "(sin códigos)"
        notes.append(
            f"Variante {variant.value} omitida por pre-check de factibilidad: "
            f"{failed_list}."
        )
        for action in feasibility.suggested_actions:
            notes.append(
                f"Variante {variant.value} → sugerencia: {action}"
            )
        for n in feasibility.notes:
            notes.append(f"Variante {variant.value} → {n}")

    @staticmethod
    def _record_pre_check_warnings(
        variant: PortfolioVariant,
        feasibility: PortfolioFeasibilityResult,
        notes: list[str],
    ) -> None:
        """Propaga warnings del pre-check a notes (la variante igual se intenta)."""
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