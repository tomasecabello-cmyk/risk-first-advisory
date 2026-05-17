"""
Modelos del KYC: KYCData, FinancialGoal, ESGProfile.

Decisión de diseño DD-002:
    `return_target_annual_pct` NO existe en KYCData. Su presencia generaba
    circularidad porque alimentaba el cálculo de viabilidad con el mismo
    retorno que después se intentaba evaluar.

Decisión de diseño DD-003:
    `declared_return_expectation_pct` existe SOLO como campo informativo.
    Documenta la expectativa verbal del cliente para que la IA detecte
    contradicciones psicológicas. NUNCA se usa en cálculos de viabilidad
    ni en construcción de cartera.

La viabilidad del objetivo se calcula exclusivamente desde `FinancialGoal`:
    initial_capital + contributions + target_capital + horizon → IRR requerida
"""

from dataclasses import dataclass, field
from enum import Enum


class InvestmentObjective(str, Enum):
    CAPITAL_PRESERVATION = "capital_preservation"
    INCOME = "income"
    BALANCED = "balanced"
    GROWTH = "growth"
    AGGRESSIVE_GROWTH = "aggressive_growth"


class InvestorExperience(str, Enum):
    NONE = "ninguna"
    BASIC = "basica"
    MODERATE = "moderada"
    ADVANCED = "avanzada"
    EXPERT = "experto"


class ESGStrictnessLevel(str, Enum):
    NONE = "none"
    LIGHT = "light"
    STRICT = "strict"
    IMPACT = "impact"


@dataclass
class ESGExclusion:
    """Exclusión moral o normativa. Bloquea activos. No negociable."""

    excluded_item: str
    exclusion_type: str  # "sector" | "activity" | "issuer" | "country"
    source: str  # "client_explicit" | "regulatory" | "firm_policy"
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.excluded_item.strip():
            raise ValueError("excluded_item no puede estar vacío.")
        if self.exclusion_type not in {"sector", "activity", "issuer", "country"}:
            raise ValueError(
                f"exclusion_type inválido: {self.exclusion_type!r}. "
                "Opciones: sector, activity, issuer, country."
            )


@dataclass
class ESGPreference:
    """Preferencia blanda. Suma o resta score, no bloquea."""

    preference_type: str  # "low_carbon" | "high_esg_score" | "diversity_leaders"
    weight: float  # 0.0–1.0, importancia relativa para el cliente
    minimum_threshold: float | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"weight debe estar en [0.0, 1.0], recibido {self.weight}.")


@dataclass
class ESGProfile:
    """Perfil ESG con separación entre exclusiones duras y preferencias blandas."""

    strictness_level: ESGStrictnessLevel = ESGStrictnessLevel.NONE
    hard_exclusions: list[ESGExclusion] = field(default_factory=list)
    soft_preferences: list[ESGPreference] = field(default_factory=list)

    def has_hard_exclusions(self) -> bool:
        return len(self.hard_exclusions) > 0

    def has_soft_preferences(self) -> bool:
        return len(self.soft_preferences) > 0


@dataclass
class FinancialGoal:
    """
    Datos financieros objetivos del cliente.

    Es la ÚNICA fuente de verdad para calcular viabilidad del objetivo.
    No depende de retornos declarados ni expectativas verbales.
    """

    initial_capital_usd: float
    target_capital_usd: float
    horizon_years: int
    periodic_contribution_usd: float
    contribution_frequency_years: float  # 1.0 = anual, 0.5 = semestral
    target_is_flexible: bool
    horizon_is_flexible: bool

    def __post_init__(self) -> None:
        if self.initial_capital_usd < 0:
            raise ValueError("initial_capital_usd no puede ser negativo.")
        if self.target_capital_usd < 0:
            raise ValueError("target_capital_usd no puede ser negativo.")
        if self.horizon_years <= 0:
            raise ValueError("horizon_years debe ser positivo.")
        if self.periodic_contribution_usd < 0:
            raise ValueError("periodic_contribution_usd no puede ser negativo.")
        if self.contribution_frequency_years <= 0:
            raise ValueError("contribution_frequency_years debe ser positivo.")
        if (
            self.target_capital_usd <= self.initial_capital_usd
            and self.periodic_contribution_usd == 0
            and self.target_capital_usd != self.initial_capital_usd
        ):
            raise ValueError(
                "target_capital debe superar initial_capital si no hay aportes. "
                "Para preservación de capital usá target = initial."
            )


@dataclass
class KYCData:
    """
    Datos del cliente capturados en el KYC.

    INVARIANTES:
    - NO existe `return_target_annual_pct` (eliminado en DD-002).
    - `declared_return_expectation_pct` es solo informativo (DD-003).
    - El retorno requerido se deriva exclusivamente de FinancialGoal.
    """

    # Datos demográficos y financieros básicos
    age: int
    annual_income_usd: float
    approx_net_worth_usd: float

    # Objetivo y horizonte
    investment_objective: InvestmentObjective
    time_horizon_years: int

    # Liquidez y experiencia
    liquidity_need_pct: float
    experience: InvestorExperience

    # Las dos dimensiones de APTITUD de riesgo.
    # `risk_need` NO se declara — se DERIVA del FinancialGoal vs CMA del perfil.
    emotional_loss_tolerance_pct: float
    financial_loss_capacity_pct: float

    # Preferencias operativas
    preferred_currency: str
    needs_income: bool
    prefers_simple_products: bool
    jurisdiction: str

    # ESG
    esg_profile: ESGProfile

    # Respuestas abiertas
    open_investment_goal: str = ""
    open_risk_reaction: str = ""
    open_past_experience: str = ""
    open_concerns: str = ""

    # Campo informativo opcional — NO interviene en cálculos
    declared_return_expectation_pct: float | None = None

    DECLARED_RETURN_NOTE = (
        "Campo informativo de la expectativa de retorno verbalizada por el cliente. "
        "No se usa en cálculos de viabilidad ni de construcción de cartera. "
        "El retorno requerido se calcula exclusivamente desde FinancialGoal."
    )

    def __post_init__(self) -> None:
        if self.age < 0 or self.age > 130:
            raise ValueError(f"age inválido: {self.age}.")
        if self.annual_income_usd < 0:
            raise ValueError("annual_income_usd no puede ser negativo.")
        if self.approx_net_worth_usd < 0:
            raise ValueError("approx_net_worth_usd no puede ser negativo.")
        if self.time_horizon_years <= 0:
            raise ValueError("time_horizon_years debe ser positivo.")
        if not 0.0 <= self.liquidity_need_pct <= 1.0:
            raise ValueError(
                f"liquidity_need_pct debe estar en [0.0, 1.0], recibido {self.liquidity_need_pct}."
            )
        if not 0.0 <= self.emotional_loss_tolerance_pct <= 100.0:
            raise ValueError(
                "emotional_loss_tolerance_pct debe estar en [0.0, 100.0], "
                f"recibido {self.emotional_loss_tolerance_pct}."
            )
        if not 0.0 <= self.financial_loss_capacity_pct <= 100.0:
            raise ValueError(
                "financial_loss_capacity_pct debe estar en [0.0, 100.0], "
                f"recibido {self.financial_loss_capacity_pct}."
            )
        if not self.preferred_currency.strip():
            raise ValueError("preferred_currency no puede estar vacío.")
        if not self.jurisdiction.strip():
            raise ValueError("jurisdiction no puede estar vacío.")