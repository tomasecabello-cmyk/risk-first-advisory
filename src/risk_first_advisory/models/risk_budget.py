"""
RiskBudget — presupuesto de riesgo cuantitativo derivado del perfil aprobado.

Es el contrato que conecta la capa de reglas (cómo se construye) con la capa
cuantitativa (cómo se usa). Define límites duros que el optimizador NO puede
violar bajo ninguna circunstancia.

INVARIANTE: el RiskBudget se construye desde el approved_profile, NO desde
el preliminary_profile. Esto garantiza que solo el perfil validado por el
asesor llega a la capa cuantitativa.

Los retornos esperados NO forman parte del presupuesto de riesgo. El budget
solo describe LÍMITES, no objetivos de retorno.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RiskBudget:
    """
    Presupuesto de riesgo aprobado para un cliente.

    Todos los porcentajes están expresados como decimales:
        0.10 = 10%
        -0.15 = -15% (drawdown)

    Las unidades:
        - target_volatility, max_volatility: desvío estándar anualizado
        - max_drawdown: pérdida máxima esperada (valor negativo)
        - min_liquidity, max_*: fracciones del portfolio (0 a 1)
        - max_duration: años (duration de Macaulay/modificada)
    """

    profile_name: str
    target_volatility: float
    max_volatility: float
    max_drawdown: float            # valor negativo
    min_liquidity: float
    max_equity: float
    max_high_yield: float
    max_single_asset: float
    max_sector_exposure: float
    max_duration: float            # años
    complex_products_allowed: bool
    preferred_currency: str
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.profile_name.strip():
            raise ValueError("profile_name no puede estar vacío.")
        if not self.preferred_currency.strip():
            raise ValueError("preferred_currency no puede estar vacío.")
        if self.target_volatility < 0:
            raise ValueError("target_volatility no puede ser negativo.")
        if self.max_volatility < self.target_volatility:
            raise ValueError(
                f"max_volatility ({self.max_volatility}) debe ser >= "
                f"target_volatility ({self.target_volatility})."
            )
        if self.max_drawdown > 0:
            raise ValueError(
                f"max_drawdown debe ser <= 0 (es una pérdida). Recibido: {self.max_drawdown}."
            )
        if not 0.0 <= self.min_liquidity <= 1.0:
            raise ValueError(f"min_liquidity debe estar en [0.0, 1.0]. Recibido: {self.min_liquidity}.")
        for field_name in (
            "max_equity",
            "max_high_yield",
            "max_single_asset",
            "max_sector_exposure",
        ):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"{field_name} debe estar en [0.0, 1.0]. Recibido: {value}."
                )
        if self.max_duration < 0:
            raise ValueError(f"max_duration no puede ser negativo. Recibido: {self.max_duration}.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "target_volatility": self.target_volatility,
            "max_volatility": self.max_volatility,
            "max_drawdown": self.max_drawdown,
            "min_liquidity": self.min_liquidity,
            "max_equity": self.max_equity,
            "max_high_yield": self.max_high_yield,
            "max_single_asset": self.max_single_asset,
            "max_sector_exposure": self.max_sector_exposure,
            "max_duration": self.max_duration,
            "complex_products_allowed": self.complex_products_allowed,
            "preferred_currency": self.preferred_currency,
            "notes": list(self.notes),
        }