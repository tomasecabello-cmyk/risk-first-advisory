"""
Pydantic schemas para la API de risk-first-advisory.

Política: exponer solo primitivos. Los objetos de dominio internos
(enums, dataclasses) se reducen a str / int / bool antes de llegar aquí.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# ─────────────────────────────────────────────────────────────────────────────
# Shared
# ─────────────────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    service: str


# ─────────────────────────────────────────────────────────────────────────────
# /auth/me  (Phase 1 — development-only)
# ─────────────────────────────────────────────────────────────────────────────


class AdvisorIdentityResponse(BaseModel):
    """Identidad resuelta del asesor para diagnóstico (`GET /auth/me`)."""

    advisor_id:   str
    display_name: str
    firm_id:      str | None  = None
    roles:        list[str]


class PersistenceRecordIds(BaseModel):
    workflow_record_id: str
    audit_record_id: str | None = None
    report_record_id: str


# ─────────────────────────────────────────────────────────────────────────────
# /demo/run
# ─────────────────────────────────────────────────────────────────────────────


class DemoRunResponse(BaseModel):
    status: str
    client_id: str
    approved_profile_name: str
    has_portfolios: bool
    reason_codes: list[str]
    warnings: list[str]
    final_optimizer_tickers: list[str]
    portfolio_feasibility_status: str | None
    candidate_count: int
    records: PersistenceRecordIds
    report_path: str


# ─────────────────────────────────────────────────────────────────────────────
# /workflow/run — request
# ─────────────────────────────────────────────────────────────────────────────

_VALID_EXPERIENCES = frozenset(
    {"ninguna", "basica", "moderada", "avanzada", "experto",
     "none", "basic", "moderate", "advanced", "expert"}
)

# Mirrors enums in risk_first_advisory.kyc.models. Duplicated to avoid an
# api_layer→kyc dependency on enum string literals here. If the domain enums
# change, validators below will reject requests with the old vocabulary.
_VALID_INVESTMENT_OBJECTIVES = frozenset({
    "capital_preservation", "income", "balanced", "growth", "aggressive_growth"
})

_VALID_ESG_STRICTNESS = frozenset({"none", "light", "strict", "impact"})

# Matches ESGExclusion.__post_init__ in kyc.models.
_VALID_ESG_EXCLUSION_TYPES = frozenset({
    "sector", "activity", "issuer", "country", "tag", "controversy"
})


class ESGExclusionRequest(BaseModel):
    """Mirror de `kyc.models.ESGExclusion` para la API."""

    excluded_item:  str  = Field(min_length=1)
    exclusion_type: str
    source:         str  = Field(min_length=1)
    rationale:      str  = ""

    @field_validator("excluded_item")
    @classmethod
    def _validate_excluded_item(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("excluded_item no puede ser solo espacios en blanco.")
        return v

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source no puede ser solo espacios en blanco.")
        return v

    @field_validator("exclusion_type")
    @classmethod
    def _validate_exclusion_type(cls, v: str) -> str:
        if v not in _VALID_ESG_EXCLUSION_TYPES:
            raise ValueError(
                f"exclusion_type inválido: {v!r}. "
                f"Opciones: {sorted(_VALID_ESG_EXCLUSION_TYPES)}."
            )
        return v


class ESGPreferenceRequest(BaseModel):
    """Mirror de `kyc.models.ESGPreference` para la API."""

    preference_type:    str           = Field(min_length=1)
    weight:             float         = Field(ge=0.0, le=1.0)
    minimum_threshold:  float | None  = None

    @field_validator("preference_type")
    @classmethod
    def _validate_preference_type(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("preference_type no puede ser solo espacios en blanco.")
        return v


class KYCDataRequest(BaseModel):
    age: int = Field(default=40, ge=18, le=120)
    risk_tolerance_score: int = Field(ge=1, le=10)
    risk_capacity_score: int = Field(ge=1, le=10)
    liquidity_need_score: int = Field(ge=1, le=10)
    investment_horizon_years: int = Field(gt=0)
    investment_experience: str
    income_stability: str
    net_worth: float = Field(ge=0.0)
    liquid_net_worth: float = Field(ge=0.0)
    max_acceptable_drawdown_pct: float = Field(ge=0.0, le=100.0)
    declared_return_expectation_pct: float | None = None
    open_investment_goal: str | None = None
    open_risk_reaction: str | None = None
    open_past_experience: str | None = None
    open_concerns: str | None = None

    # ── Phase-1.5: campos antes hardcodeados en _build_kyc_data ───────────
    # Todos llevan defaults backward-compatible (los mismos valores que
    # _build_kyc_data hardcodeaba antes). Los tests/payloads existentes
    # siguen funcionando sin cambios.
    jurisdiction:            str          = "AR"
    preferred_currency:      str          = "USD"
    investment_objective:    str          = "balanced"
    prefers_simple_products: bool         = False
    # Si annual_income_usd es None → /workflow/run mantiene el fallback
    # histórico de derivarlo desde liquid_net_worth * 0.05 (documentado).
    annual_income_usd:       float | None = Field(default=None, ge=0.0)

    # ESG — opcional. Por defecto se construye un ESGProfile vacío
    # (strictness_level=none, sin exclusions/preferences) que reproduce
    # el comportamiento previo del endpoint.
    esg_strictness_level: str                          = "none"
    esg_exclusions:       list[ESGExclusionRequest]    = Field(default_factory=list)
    esg_preferences:      list[ESGPreferenceRequest]   = Field(default_factory=list)

    @field_validator("investment_experience")
    @classmethod
    def validate_experience(cls, v: str) -> str:
        if v.lower() not in _VALID_EXPERIENCES:
            raise ValueError(
                f"investment_experience inválido: {v!r}. "
                f"Opciones: {sorted(_VALID_EXPERIENCES)}"
            )
        return v.lower()

    @field_validator("jurisdiction")
    @classmethod
    def _validate_jurisdiction(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("jurisdiction no puede ser solo espacios en blanco.")
        return v

    @field_validator("preferred_currency")
    @classmethod
    def _validate_preferred_currency(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("preferred_currency no puede ser solo espacios en blanco.")
        return v

    @field_validator("investment_objective")
    @classmethod
    def _validate_investment_objective(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in _VALID_INVESTMENT_OBJECTIVES:
            raise ValueError(
                f"investment_objective inválido: {v!r}. "
                f"Opciones: {sorted(_VALID_INVESTMENT_OBJECTIVES)}."
            )
        return normalized

    @field_validator("esg_strictness_level")
    @classmethod
    def _validate_esg_strictness_level(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in _VALID_ESG_STRICTNESS:
            raise ValueError(
                f"esg_strictness_level inválido: {v!r}. "
                f"Opciones: {sorted(_VALID_ESG_STRICTNESS)}."
            )
        return normalized


class FinancialGoalRequest(BaseModel):
    initial_amount: float = Field(ge=0.0)
    target_amount: float = Field(ge=0.0)
    horizon_years: int = Field(gt=0)
    annual_contribution: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def check_amounts(self) -> "FinancialGoalRequest":
        if (
            self.target_amount < self.initial_amount
            and self.annual_contribution == 0.0
            and self.target_amount != self.initial_amount
        ):
            raise ValueError(
                "target_amount debe ser >= initial_amount cuando annual_contribution "
                "es 0, salvo preservación de capital (target == initial)."
            )
        return self


class WorkflowRunRequest(BaseModel):
    client_id: str = Field(min_length=1)
    advisor_id: str = Field(min_length=1)
    kyc_data: KYCDataRequest
    financial_goal: FinancialGoalRequest


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval endpoints
# ─────────────────────────────────────────────────────────────────────────────


class StoredRecordResponse(BaseModel):
    record_id: str
    record_type: str
    created_at_utc: str
    payload: dict
    metadata: dict


class RecordListResponse(BaseModel):
    records: list[StoredRecordResponse]
    count: int


# ─────────────────────────────────────────────────────────────────────────────
# /workflow/run — response
# ─────────────────────────────────────────────────────────────────────────────


class WorkflowRunResponse(BaseModel):
    status: str
    client_id: str
    approved_profile_name: str
    has_portfolios: bool
    reason_codes: list[str]
    warnings: list[str]
    final_optimizer_tickers: list[str]
    portfolio_feasibility_status: str | None
    candidate_count: int
    records: PersistenceRecordIds
    report_path: str
    # ── Scripted-demo disclosure ──────────────────────────────────────────────
    # /workflow/run runs a deterministic scripted pipeline (MockAIClient +
    # ScriptedAdvisorInterface). These fields make that explicit so consumers
    # cannot mistake it for a productive AI/advisor flow.
    execution_mode: str
    ai_source: str
    advisor_source: str
    is_production_ready: bool
    warning: str


# ─────────────────────────────────────────────────────────────────────────────
# /live/portfolio-demo
# ─────────────────────────────────────────────────────────────────────────────


class LivePortfolioRequest(BaseModel):
    profile: str = "moderado"
    period: str = "3y"
    interval: str = "1d"


class LivePortfolioWeightResponse(BaseModel):
    ticker: str
    weight: float


class LivePortfolioMetadataResponse(BaseModel):
    risk_budget_exceeded: bool
    requires_advisor_override: bool
    exceeded_constraints: list[str]
    reason_codes: list[str]
    notes: list[str]


class LivePortfolioCandidateResponse(BaseModel):
    variant: str
    objective: str
    expected_return_annual: float
    volatility_annual: float
    risk_score: float
    constraints_satisfied: bool
    reason_codes: list[str]
    notes: list[str]
    metadata: LivePortfolioMetadataResponse
    weights: list[LivePortfolioWeightResponse]


class LivePortfolioResponse(BaseModel):
    status: str
    profile: str
    period: str
    interval: str
    total_tickers: int
    usable_snapshots: int
    failed_or_missing: int
    dq_warnings: list[str]
    candidates: list[LivePortfolioCandidateResponse]
    candidate_count: int
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# /ai/profile-demo
# ─────────────────────────────────────────────────────────────────────────────


class AIProfileKYCRequest(BaseModel):
    risk_tolerance_score: int = Field(ge=1, le=10)
    risk_capacity_score: int = Field(ge=1, le=10)
    liquidity_need_score: int = Field(ge=1, le=10)
    investment_horizon_years: int = Field(gt=0)
    max_acceptable_drawdown_pct: float = Field(ge=0.0)
    investment_experience: str
    income_stability: str
    net_worth: float = Field(ge=0.0)
    liquid_net_worth: float = Field(ge=0.0)
    declared_return_expectation_pct: float | None = None
    open_investment_goal: str | None = None
    open_risk_reaction: str | None = None
    open_past_experience: str | None = None
    open_concerns: str | None = None


class AIProfileRequest(BaseModel):
    client_id: str = Field(min_length=1)
    kyc_payload: AIProfileKYCRequest


class AIContradictionResponse(BaseModel):
    field: str
    severity: str
    explanation: str


class AIProfileResponse(BaseModel):
    client_id: str
    preliminary_profile: str
    confidence: float
    contradictions: list[AIContradictionResponse]
    follow_up_questions: list[str]
    advisor_notes: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# /ai/profile-follow-up
# ─────────────────────────────────────────────────────────────────────────────


class AIFollowUpAnswerRequest(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class AIProfileFollowUpRequest(BaseModel):
    client_id: str = Field(min_length=1)
    original_kyc_payload: AIProfileKYCRequest
    previous_analysis: AIProfileResponse
    follow_up_answers: list[AIFollowUpAnswerRequest] = Field(min_length=1)


class AIProfileFollowUpResponse(BaseModel):
    client_id: str
    revised_profile: str
    confidence: float
    remaining_contradictions: list[AIContradictionResponse]
    profile_change_reason: str
    advisor_notes: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# /ai/investment-preferences
# ─────────────────────────────────────────────────────────────────────────────


class AIInvestmentPreferencesRequest(BaseModel):
    client_id: str = Field(min_length=1)
    natural_language_preferences: str = Field(min_length=1)
    kyc_context: dict | None = None
    previous_profile_analysis: dict | None = None


class AIInvestmentPreferencesResponse(BaseModel):
    client_id: str
    allowed_instrument_types: list[str]
    excluded_instrument_types: list[str]
    currency: str | None
    country: str | None
    entity: str | None
    hard_dollar_only: bool | None
    avoid_sectors: list[str]
    prefer_sectors: list[str]
    avoid_issuers: list[str]
    prefer_issuers: list[str]
    min_liquidity_score: float | None
    max_maturity_year: int | None
    hard_constraints: list[str]
    soft_preferences: list[str]
    unparsed_preferences: list[str]
    confidence: float
    advisor_notes: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# /universe/filter-demo
# ─────────────────────────────────────────────────────────────────────────────


class UniverseFilterRequest(BaseModel):
    allowed_instrument_types:  list[str]      = Field(default_factory=list)
    excluded_instrument_types: list[str]      = Field(default_factory=list)
    currency:                  str | None     = None
    country:                   str | None     = None
    entity:                    str | None     = None
    hard_dollar_only:          bool | None    = None
    avoid_sectors:             list[str]      = Field(default_factory=list)
    prefer_sectors:            list[str]      = Field(default_factory=list)
    avoid_issuers:             list[str]      = Field(default_factory=list)
    prefer_issuers:            list[str]      = Field(default_factory=list)
    min_liquidity_score:       float | None   = None
    max_maturity_year:         int | None     = None


class InstrumentResponse(BaseModel):
    ticker:             str
    name:               str
    issuer:             str
    instrument_type:    str
    asset_class:        str
    currency:           str
    country:            str
    sector:             str
    available_entities: list[str]
    hard_dollar:        bool
    maturity_date:      str | None
    coupon_rate:        float | None
    ytm:                float | None
    duration:           float | None
    liquidity_score:    float
    min_piece:          float | None
    rating:             str | None
    notes:              list[str]


class InstrumentExclusionResponse(BaseModel):
    ticker:  str
    reasons: list[str]


class UniverseFilterResponse(BaseModel):
    eligible_count:       int
    excluded_count:       int
    eligible_instruments: list[InstrumentResponse]
    exclusions:           list[InstrumentExclusionResponse]
    applied_filters:      list[str]
    warnings:             list[str]


# ─────────────────────────────────────────────────────────────────────────────
# /ai/filter-universe-demo
# ─────────────────────────────────────────────────────────────────────────────


class AIUniverseFilterResponse(BaseModel):
    client_id:            str
    preferences:          AIInvestmentPreferencesResponse
    eligible_count:       int
    excluded_count:       int
    eligible_instruments: list[InstrumentResponse]
    exclusions:           list[InstrumentExclusionResponse]
    applied_filters:      list[str]
    warnings:             list[str]


# ─────────────────────────────────────────────────────────────────────────────
# /ai/filtered-portfolio-demo
# ─────────────────────────────────────────────────────────────────────────────


class AIFilteredPortfolioRequest(BaseModel):
    client_id:                    str  = Field(min_length=1)
    profile:                      str  = "moderado"
    natural_language_preferences: str  = Field(min_length=1)
    kyc_context:                  dict | None = None
    previous_profile_analysis:    dict | None = None


class FilteredSnapshotResponse(BaseModel):
    ticker:                  str
    expected_return_annual:  float
    volatility_annual:       float
    duration:                float | None
    liquidity_score:         float
    notes:                   list[str]


# ─────────────────────────────────────────────────────────────────────────────
# /advisor/profile-approval  (Phase 1 — primer acto formal del asesor)
# ─────────────────────────────────────────────────────────────────────────────

# Perfiles válidos. Se mantiene una copia local (en lugar de importar
# VALID_PROFILES) para que schemas.py no dependa de la lógica del optimizador.
# Sincronizado manualmente con rules_layer.risk_budget_builder.PROFILE_BASE_PARAMS.
_ADVISOR_VALID_PROFILES: frozenset[str] = frozenset({
    "conservador",
    "moderado-defensivo",
    "moderado",
    "moderado-agresivo",
    "agresivo",
})

_ADVISOR_VALID_DECISIONS: frozenset[str] = frozenset({"approve", "modify", "reject"})


class AdvisorProfileApprovalRequest(BaseModel):
    """
    Decisión del asesor sobre un perfil propuesto (por la IA o por el sistema).

    Reglas cruzadas (validadas en `model_validator`):
        - approve  : approved_profile None o igual a proposed_profile.
                     Si viene None, se completa con proposed_profile.
                     Si viene distinto → 422.
        - modify   : approved_profile obligatorio y debe ser perfil válido.
                     Puede coincidir con proposed_profile (no se bloquea).
        - reject   : approved_profile DEBE ser None.
    """

    client_id:          str         = Field(min_length=1)
    proposed_profile:   str         = Field(min_length=1)
    decision:           str
    approved_profile:   str | None  = None
    rationale:          str         = Field(min_length=1)
    source:             str         = "manual"
    related_record_id:  str | None  = None

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, v: str) -> str:
        if v not in _ADVISOR_VALID_DECISIONS:
            raise ValueError(
                f"decision inválida: {v!r}. "
                f"Opciones: {sorted(_ADVISOR_VALID_DECISIONS)}."
            )
        return v

    @field_validator("proposed_profile")
    @classmethod
    def _validate_proposed_profile(cls, v: str) -> str:
        if v not in _ADVISOR_VALID_PROFILES:
            raise ValueError(
                f"proposed_profile inválido: {v!r}. "
                f"Opciones: {sorted(_ADVISOR_VALID_PROFILES)}."
            )
        return v

    @field_validator("rationale")
    @classmethod
    def _validate_rationale_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale no puede ser solo espacios en blanco.")
        return v

    @field_validator("source")
    @classmethod
    def _validate_source_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source no puede estar vacío.")
        return v

    @model_validator(mode="after")
    def _validate_decision_consistency(self) -> "AdvisorProfileApprovalRequest":
        if self.decision == "approve":
            if self.approved_profile is None:
                # Completar approved_profile con proposed_profile para
                # mantener invariante: si decision != reject → approved_profile != None.
                object.__setattr__(self, "approved_profile", self.proposed_profile)
            elif self.approved_profile != self.proposed_profile:
                raise ValueError(
                    "decision='approve' requiere approved_profile igual a "
                    "proposed_profile (o None para auto-completar). "
                    f"Recibido proposed={self.proposed_profile!r}, "
                    f"approved={self.approved_profile!r}. "
                    "Usar decision='modify' para aprobar un perfil distinto."
                )

        elif self.decision == "modify":
            if self.approved_profile is None:
                raise ValueError(
                    "decision='modify' requiere approved_profile no nulo."
                )
            if self.approved_profile not in _ADVISOR_VALID_PROFILES:
                raise ValueError(
                    f"approved_profile inválido: {self.approved_profile!r}. "
                    f"Opciones: {sorted(_ADVISOR_VALID_PROFILES)}."
                )

        elif self.decision == "reject":
            if self.approved_profile is not None:
                raise ValueError(
                    "decision='reject' requiere approved_profile=None."
                )

        return self


class AdvisorProfileApprovalResponse(BaseModel):
    record_id:              str
    client_id:              str
    advisor_id:             str
    advisor_display_name:   str
    firm_id:                str | None
    proposed_profile:       str
    decision:               str
    approved_profile:       str | None
    rationale:              str
    source:                 str
    related_record_id:      str | None
    created_at_utc:         str
    status:                 str = "recorded"


# ─────────────────────────────────────────────────────────────────────────────
# /advisor/portfolio-selection  (Phase 1 — tercer acto formal del asesor)
# ─────────────────────────────────────────────────────────────────────────────

# Las variantes válidas coinciden con _ADVISOR_OVERRIDE_VALID_VARIANTS pero se
# declara explícita para evitar acoplamiento implícito entre dos schemas que
# pueden evolucionar de forma independiente en el futuro.
_ADVISOR_SELECTION_VALID_VARIANTS: frozenset[str] = frozenset({
    "DEFENSIVE", "BALANCED", "GROWTH"
})


class AdvisorPortfolioSelectionRequest(BaseModel):
    """
    Selección final del asesor sobre la variante de portfolio a presentar al
    cliente.

    Reglas Fase 1:
        - NO valida contra existencia real de `related_record_id`.
        - NO valida contra existencia real de `override_approval_record_id`.
        - Si selected_variant == "GROWTH" y override_approval_record_id falta,
          el endpoint agrega un warning en la response (no bloquea).
        - Si selected_variant != "GROWTH" y override_approval_record_id viene,
          se acepta sin warning especial (decisión: menor complejidad).
    """

    client_id:                    str         = Field(min_length=1)
    related_record_id:            str | None  = None
    selected_variant:             str
    rationale:                    str         = Field(min_length=1)
    override_approval_record_id:  str | None  = None
    source:                       str         = "manual"

    @field_validator("selected_variant")
    @classmethod
    def _validate_selected_variant(cls, v: str) -> str:
        if v not in _ADVISOR_SELECTION_VALID_VARIANTS:
            raise ValueError(
                f"selected_variant inválido: {v!r}. "
                f"Opciones: {sorted(_ADVISOR_SELECTION_VALID_VARIANTS)}."
            )
        return v

    @field_validator("rationale")
    @classmethod
    def _validate_rationale_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale no puede ser solo espacios en blanco.")
        return v

    @field_validator("source")
    @classmethod
    def _validate_source_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source no puede estar vacío.")
        return v


class AdvisorPortfolioSelectionResponse(BaseModel):
    record_id:                    str
    client_id:                    str
    advisor_id:                   str
    advisor_display_name:         str
    firm_id:                      str | None
    selected_variant:             str
    rationale:                    str
    related_record_id:            str | None
    override_approval_record_id:  str | None
    source:                       str
    warnings:                     list[str]
    created_at_utc:               str
    status:                       str = "recorded"


# ─────────────────────────────────────────────────────────────────────────────
# /advisor/override-approval  (Phase 1 — segundo acto formal del asesor)
# ─────────────────────────────────────────────────────────────────────────────
#
# Nota: existe `risk_first_advisory.human_layer.override_approval.AdvisorOverrideApproval`
# como objeto de dominio para integración con workflow (con enums, comment
# mínimo 20 chars, y validación contra PortfolioVariantMetadata viva). Ese
# modelo no encaja con el contrato API que pide la Fase 1 (string-based,
# rationale min_length=1, sin live metadata). Por eso las schemas aquí son
# independientes y NO modifican el modelo del dominio. La conciliación
# advisor_override domain ↔ API queda para una tarea de integración futura.

_ADVISOR_OVERRIDE_VALID_VARIANTS: frozenset[str] = frozenset({
    "DEFENSIVE", "BALANCED", "GROWTH"
})

_ADVISOR_OVERRIDE_VALID_DECISIONS: frozenset[str] = frozenset({"approve", "reject"})


def _validate_str_list_no_empty(value: list[str], field_name: str) -> list[str]:
    """Cada item debe ser str no vacío (sin solo whitespace)."""
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"{field_name}[{i}] debe ser un string no vacío. Recibido: {item!r}."
            )
    return value


class AdvisorOverrideApprovalRequest(BaseModel):
    """
    Decisión del asesor sobre una variante de portfolio que excede el RiskBudget
    aprobado y requiere advisor override (típicamente GROWTH).

    Diseño Fase 1:
        - NO valida contra existencia real del candidate ni del record relacionado.
        - NO requiere requires_advisor_override=True (a diferencia del dominio).
        - El asesor declara reason_codes y exceeded_constraints explícitamente
          (los copia del payload del portfolio o los escribe a mano).
        - Para reject, los reason_codes/exceeded_constraints se conservan en el
          record (no se borran) para mantener trazabilidad de por qué se
          rechazó el override.
    """

    client_id:             str         = Field(min_length=1)
    related_record_id:     str | None  = None
    candidate_variant:     str         = Field(min_length=1)
    decision:              str
    reason_codes:          list[str]   = Field(default_factory=list)
    exceeded_constraints:  list[str]   = Field(default_factory=list)
    rationale:             str         = Field(min_length=1)
    source:                str         = "manual"

    @field_validator("candidate_variant")
    @classmethod
    def _validate_candidate_variant(cls, v: str) -> str:
        if v not in _ADVISOR_OVERRIDE_VALID_VARIANTS:
            raise ValueError(
                f"candidate_variant inválido: {v!r}. "
                f"Opciones: {sorted(_ADVISOR_OVERRIDE_VALID_VARIANTS)}."
            )
        return v

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, v: str) -> str:
        if v not in _ADVISOR_OVERRIDE_VALID_DECISIONS:
            raise ValueError(
                f"decision inválida: {v!r}. "
                f"Opciones: {sorted(_ADVISOR_OVERRIDE_VALID_DECISIONS)}."
            )
        return v

    @field_validator("rationale")
    @classmethod
    def _validate_rationale_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale no puede ser solo espacios en blanco.")
        return v

    @field_validator("source")
    @classmethod
    def _validate_source_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source no puede estar vacío.")
        return v

    @field_validator("reason_codes")
    @classmethod
    def _validate_reason_codes(cls, v: list[str]) -> list[str]:
        return _validate_str_list_no_empty(v, "reason_codes")

    @field_validator("exceeded_constraints")
    @classmethod
    def _validate_exceeded_constraints(cls, v: list[str]) -> list[str]:
        return _validate_str_list_no_empty(v, "exceeded_constraints")


class AdvisorOverrideApprovalResponse(BaseModel):
    record_id:             str
    client_id:             str
    advisor_id:            str
    advisor_display_name:  str
    firm_id:               str | None
    candidate_variant:     str
    decision:              str
    reason_codes:          list[str]
    exceeded_constraints:  list[str]
    rationale:             str
    source:                str
    related_record_id:     str | None
    created_at_utc:        str
    status:                str = "recorded"


class AIFilteredPortfolioResponse(BaseModel):
    client_id:            str
    profile:              str
    preferences:          AIInvestmentPreferencesResponse
    eligible_count:       int
    excluded_count:       int
    eligible_instruments: list[InstrumentResponse]
    exclusions:           list[InstrumentExclusionResponse]
    applied_filters:      list[str]
    warnings:             list[str]
    snapshots:            list[FilteredSnapshotResponse]
    snapshot_count:       int
    status:               str
    message:              str
    candidates:           list[LivePortfolioCandidateResponse]
    candidate_count:      int
    # ── Phase-0 MVP additions ─────────────────────────────────────────────────
    # Auditable Markdown report for advisor review, generated deterministically
    # by AIFilteredPortfolioReportGenerator from this response payload.
    report_markdown:      str         = ""
    # SQLite persistence IDs (None only if persistence layer is bypassed in
    # tests that monkeypatch the persistence helper).
    record_id:            str | None  = None
    report_record_id:     str | None  = None


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 entities — Firm, Advisor, Client
# ─────────────────────────────────────────────────────────────────────────────

# Roles permitidos para entidades Advisor. Mismo conjunto que ALLOWED_ROLES
# en config_layer/advisor_tokens.py — duplicado para evitar dependencia circular.
_ALLOWED_ENTITY_ROLES: frozenset[str] = frozenset(
    {"advisor", "compliance", "admin", "viewer"}
)


# ── Firm ─────────────────────────────────────────────────────────────────────


class FirmCreateRequest(BaseModel):
    firm_id:      str | None = None
    display_name: str        = Field(min_length=1)
    country:      str        = Field(min_length=1)
    is_active:    bool       = True

    @field_validator("firm_id", mode="before")
    @classmethod
    def _firm_id_not_empty(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("firm_id no puede ser cadena vacía.")
        return v

    @field_validator("country")
    @classmethod
    def _country_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("country no puede ser solo espacios.")
        return v


class FirmResponse(BaseModel):
    firm_id:        str
    display_name:   str
    country:        str
    is_active:      bool
    created_at_utc: str


class FirmListResponse(BaseModel):
    firms: list[FirmResponse]
    count: int


# ── Advisor ──────────────────────────────────────────────────────────────────


class AdvisorCreateRequest(BaseModel):
    advisor_id:   str | None = None
    firm_id:      str        = Field(min_length=1)
    display_name: str        = Field(min_length=1)
    email:        str        = Field(min_length=1)
    roles:        list[str]  = Field(min_length=1)
    is_active:    bool       = True

    @field_validator("advisor_id", mode="before")
    @classmethod
    def _advisor_id_not_empty(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("advisor_id no puede ser cadena vacía.")
        return v

    @field_validator("email")
    @classmethod
    def _email_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("email no puede ser solo espacios.")
        return v

    @field_validator("roles")
    @classmethod
    def _validate_roles(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("roles debe tener al menos un elemento.")
        for r in v:
            if not isinstance(r, str) or not r.strip():
                raise ValueError("cada rol debe ser un string no vacío.")
            if r not in _ALLOWED_ENTITY_ROLES:
                raise ValueError(
                    f"rol {r!r} no permitido. "
                    f"Roles válidos: {sorted(_ALLOWED_ENTITY_ROLES)}."
                )
        return v


class AdvisorResponse(BaseModel):
    advisor_id:     str
    firm_id:        str
    display_name:   str
    email:          str
    roles:          list[str]
    is_active:      bool
    created_at_utc: str


class AdvisorListResponse(BaseModel):
    advisors: list[AdvisorResponse]
    count:    int


# ── Client ───────────────────────────────────────────────────────────────────


class ClientCreateRequest(BaseModel):
    client_id:          str | None = None
    firm_id:            str        = Field(min_length=1)
    primary_advisor_id: str        = Field(min_length=1)
    display_name:       str        = Field(min_length=1)
    external_ref:       str | None = None
    jurisdiction:       str        = Field(default="AR", min_length=1)
    preferred_currency: str        = Field(default="USD", min_length=1)
    is_active:          bool       = True

    @field_validator("client_id", mode="before")
    @classmethod
    def _client_id_not_empty(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("client_id no puede ser cadena vacía.")
        return v

    @field_validator("jurisdiction", "preferred_currency")
    @classmethod
    def _not_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("no puede ser solo espacios.")
        return v


class ClientResponse(BaseModel):
    client_id:          str
    firm_id:            str
    primary_advisor_id: str
    display_name:       str
    external_ref:       str | None
    jurisdiction:       str
    preferred_currency: str
    is_active:          bool
    created_at_utc:     str


class ClientListResponse(BaseModel):
    clients: list[ClientResponse]
    count:   int


# ─────────────────────────────────────────────────────────────────────────────
# AdvisoryCase — Fase 2 Commit 5
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_CASE_STATUSES: frozenset[str] = frozenset(
    {"DRAFT", "IN_PROGRESS", "PORTFOLIO_SELECTED", "CLOSED"}
)


class AdvisoryCaseCreateRequest(BaseModel):
    case_id:          str | None = None
    firm_id:          str        = Field(min_length=1)
    client_id:        str        = Field(min_length=1)
    lead_advisor_id:  str        = Field(min_length=1)
    title:            str        = Field(min_length=1)
    status:           str        = "DRAFT"

    @field_validator("case_id", mode="before")
    @classmethod
    def _case_id_not_empty(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("case_id no puede ser cadena vacía.")
        return v

    @field_validator("title")
    @classmethod
    def _title_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title no puede ser solo espacios.")
        return v

    @field_validator("status")
    @classmethod
    def _status_must_be_valid(cls, v: str) -> str:
        if v not in _ALLOWED_CASE_STATUSES:
            valid = sorted(_ALLOWED_CASE_STATUSES)
            raise ValueError(f"status debe ser uno de {valid}.")
        return v


class AdvisoryCaseResponse(BaseModel):
    case_id:                        str
    firm_id:                        str
    client_id:                      str
    lead_advisor_id:                str
    status:                         str
    title:                          str
    current_kyc_submission_id:      str | None
    current_approved_profile_id:    str | None
    current_portfolio_selection_id: str | None
    created_at_utc:                 str
    closed_at_utc:                  str | None


class AdvisoryCaseListResponse(BaseModel):
    cases: list[AdvisoryCaseResponse]
    count: int


class AdvisoryCaseStatusUpdateRequest(BaseModel):
    status: str
    reason: str | None = None

    @field_validator("status")
    @classmethod
    def _status_must_be_valid(cls, v: str) -> str:
        if v not in _ALLOWED_CASE_STATUSES:
            valid = sorted(_ALLOWED_CASE_STATUSES)
            raise ValueError(f"status debe ser uno de {valid}.")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# AuditEvent — Fase 2 Commit 6 (hash chain por AdvisoryCase)
# ─────────────────────────────────────────────────────────────────────────────


class AuditEventCreateRequest(BaseModel):
    """
    Request para crear un audit event manual sobre un caso.

    El sistema agrega además eventos automáticos (case_created, ...) sin que
    el caller los tenga que enviar.
    """

    event_type:        str               = Field(min_length=1)
    actor_advisor_id:  str | None        = None
    actor_role:        str               = "system"
    payload:           dict[str, Any]    = Field(default_factory=dict)

    @field_validator("event_type")
    @classmethod
    def _event_type_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("event_type no puede ser solo espacios.")
        return v

    @field_validator("actor_role")
    @classmethod
    def _actor_role_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("actor_role no puede ser solo espacios.")
        return v

    @field_validator("actor_advisor_id")
    @classmethod
    def _actor_advisor_id_not_empty(cls, v: str | None) -> str | None:
        if v is not None and (not isinstance(v, str) or not v.strip()):
            raise ValueError("actor_advisor_id, si se provee, no puede ser cadena vacía.")
        return v

    @field_validator("payload", mode="before")
    @classmethod
    def _payload_must_be_dict(cls, v: object) -> object:
        # Pydantic acepta dict-like nativamente; aquí se rechaza list/str/None
        # para que el caller no mande una lista o string como payload.
        if v is None:
            raise ValueError("payload no puede ser null. Usar {} para payload vacío.")
        if not isinstance(v, dict):
            raise ValueError(
                f"payload debe ser un objeto JSON (dict); recibido {type(v).__name__}."
            )
        return v


class AuditEventResponse(BaseModel):
    event_id:          str
    case_id:           str
    sequence:          int
    event_type:        str
    actor_advisor_id:  str | None
    actor_role:        str
    payload:           dict[str, Any]
    payload_hash:      str
    previous_hash:     str | None
    event_hash:        str
    created_at_utc:    str


class AuditEventListResponse(BaseModel):
    events: list[AuditEventResponse]
    count:  int


class AuditVerifyResponse(BaseModel):
    case_id:               str
    is_intact:             bool
    total_events:          int
    first_broken_sequence: int | None
    checked_at_utc:        str
    message:               str


# ─────────────────────────────────────────────────────────────────────────────
# AIRequestLog — Fase 2 Commit 7
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_AI_LOG_STATUSES: frozenset[str] = frozenset(
    {"parsed_ok", "parse_error", "validation_error", "api_error"}
)


class AIRequestLogResponse(BaseModel):
    request_id:              str
    case_id:                 str | None
    requested_by_advisor_id: str | None
    endpoint:                str
    model:                   str
    prompt_version:          str
    input_redacted:          dict[str, Any]
    input_hash:              str
    raw_response:            dict[str, Any] | None
    validation_status:       str
    latency_ms:              int | None
    prompt_tokens:           int | None
    completion_tokens:       int | None
    error_message:           str | None
    created_at_utc:          str


class AIRequestLogListResponse(BaseModel):
    logs:  list[AIRequestLogResponse]
    count: int


class AIRequestLogCreateRequest(BaseModel):
    """
    Para creación manual de logs (endpoints admin / scripts internos).

    No es el camino normal: lo habitual es que los endpoints `/ai/*`
    persistan logs automáticamente. Esta request existe para soportar
    backfill, importación o tests manuales.
    """

    case_id:                 str | None     = None
    requested_by_advisor_id: str | None     = None
    endpoint:                str            = Field(min_length=1)
    model:                   str            = Field(min_length=1)
    prompt_version:          str            = Field(min_length=1)
    input_payload:           dict[str, Any] = Field(default_factory=dict)
    raw_response:            dict[str, Any] | None = None
    validation_status:       str
    latency_ms:              int | None     = None
    prompt_tokens:           int | None     = None
    completion_tokens:       int | None     = None
    error_message:           str | None     = None

    @field_validator("endpoint")
    @classmethod
    def _endpoint_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("endpoint no puede ser solo espacios.")
        return v

    @field_validator("model")
    @classmethod
    def _model_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model no puede ser solo espacios.")
        return v

    @field_validator("prompt_version")
    @classmethod
    def _prompt_version_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt_version no puede ser solo espacios.")
        return v

    @field_validator("validation_status")
    @classmethod
    def _validation_status_must_be_allowed(cls, v: str) -> str:
        if v not in _ALLOWED_AI_LOG_STATUSES:
            raise ValueError(
                f"validation_status inválido: {v!r}. "
                f"Permitidos: {sorted(_ALLOWED_AI_LOG_STATUSES)}."
            )
        return v

    @field_validator("latency_ms")
    @classmethod
    def _latency_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("latency_ms debe ser >= 0.")
        return v

    @field_validator("prompt_tokens")
    @classmethod
    def _prompt_tokens_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("prompt_tokens debe ser >= 0.")
        return v

    @field_validator("completion_tokens")
    @classmethod
    def _completion_tokens_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("completion_tokens debe ser >= 0.")
        return v

    @field_validator("input_payload", mode="before")
    @classmethod
    def _input_payload_must_be_dict(cls, v: object) -> object:
        if v is None:
            raise ValueError("input_payload no puede ser null; usar {} si está vacío.")
        if not isinstance(v, dict):
            raise ValueError(
                f"input_payload debe ser un objeto JSON (dict); recibido {type(v).__name__}."
            )
        return v


# ─────────────────────────────────────────────────────────────────────────────
# KYCSubmission — Fase 2 Commit 8 (case-scoped KYC)
# ─────────────────────────────────────────────────────────────────────────────
#
# Nota: el request del POST es KYCDataRequest (reutilizado, no duplicado).
# Solo se agregan los modelos de respuesta.
# ─────────────────────────────────────────────────────────────────────────────


class KYCSubmissionResponse(BaseModel):
    kyc_submission_id:       str
    case_id:                 str
    version:                 int
    submitted_by_advisor_id: str | None
    payload:                 dict[str, Any]
    payload_hash:            str
    created_at_utc:          str


class KYCSubmissionListResponse(BaseModel):
    submissions: list[KYCSubmissionResponse]
    count:       int


# ─────────────────────────────────────────────────────────────────────────────
# AIProfileAnalysis — Fase 2 Commit 9 (case-scoped AI profile analysis)
# ─────────────────────────────────────────────────────────────────────────────

# Restringido a "initial" en este commit. "follow_up" queda reservado pero NO
# implementado todavía: requiere previous_analysis + follow_up_answers (otra
# llamada a OpenAIProfileClient.analyze_follow_up).
_ALLOWED_PROFILE_ANALYSIS_TYPES: frozenset[str] = frozenset({"initial", "follow_up"})
_IMPLEMENTED_PROFILE_ANALYSIS_TYPES: frozenset[str] = frozenset({"initial"})


class AIProfileAnalysisCreateRequest(BaseModel):
    kyc_submission_id: str | None = None
    analysis_type:     str        = "initial"

    @field_validator("kyc_submission_id", mode="before")
    @classmethod
    def _kyc_submission_id_not_empty(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("kyc_submission_id no puede ser cadena vacía.")
        return v

    @field_validator("analysis_type")
    @classmethod
    def _analysis_type_must_be_allowed(cls, v: str) -> str:
        if v not in _ALLOWED_PROFILE_ANALYSIS_TYPES:
            raise ValueError(
                f"analysis_type inválido: {v!r}. "
                f"Valores permitidos: {sorted(_ALLOWED_PROFILE_ANALYSIS_TYPES)}."
            )
        if v not in _IMPLEMENTED_PROFILE_ANALYSIS_TYPES:
            raise ValueError(
                f"analysis_type={v!r} aún no está implementado. "
                f"Implementados: {sorted(_IMPLEMENTED_PROFILE_ANALYSIS_TYPES)}."
            )
        return v


class AIProfileAnalysisResponse(BaseModel):
    analysis_id:         str
    case_id:             str
    kyc_submission_id:   str
    ai_request_log_id:   str | None
    analysis_type:       str
    preliminary_profile: str | None
    confidence:          float | None
    result:              dict[str, Any]
    created_at_utc:      str


class AIProfileAnalysisListResponse(BaseModel):
    analyses: list[AIProfileAnalysisResponse]
    count:    int


# ─────────────────────────────────────────────────────────────────────────────
# CaseAdvisorProfileApproval — Fase 2 Commit 10 (decisión humana case-scoped)
# ─────────────────────────────────────────────────────────────────────────────
#
# Reutiliza el mismo set de perfiles válidos que la Phase 1 schema legacy
# (_ADVISOR_VALID_PROFILES) y el mismo enum de decisiones
# (_ADVISOR_VALID_DECISIONS) para garantizar coherencia entre los dos
# endpoints (legacy y case-scoped).
# ─────────────────────────────────────────────────────────────────────────────


class CaseAdvisorProfileApprovalCreateRequest(BaseModel):
    """
    Decisión del asesor sobre el perfil de un caso.

    Reglas cruzadas (model_validator):
        - approve : approved_profile None o igual a proposed_profile.
                    Si None, se auto-completa con proposed_profile.
                    Distinto → 422.
        - modify  : approved_profile obligatorio y debe ser perfil válido.
        - reject  : approved_profile DEBE ser None.

    Reglas adicionales (validadas en el endpoint contra la DB):
        - ai_profile_analysis_id (si viene) debe existir y pertenecer al case.
        - kyc_submission_id (si viene) debe existir y pertenecer al case.
        - Si proposed_profile no viene, se deriva del último análisis del case
          (o del análisis explícito). Si no hay análisis y no se manda
          proposed_profile → 422.
    """

    ai_profile_analysis_id: str | None = None
    kyc_submission_id:      str | None = None
    proposed_profile:       str | None = None
    decision:               str
    approved_profile:       str | None = None
    rationale:              str        = Field(min_length=1)
    source:                 str        = "manual"

    @field_validator("ai_profile_analysis_id", mode="before")
    @classmethod
    def _analysis_id_not_empty(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("ai_profile_analysis_id no puede ser cadena vacía.")
        return v

    @field_validator("kyc_submission_id", mode="before")
    @classmethod
    def _kyc_submission_id_not_empty(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("kyc_submission_id no puede ser cadena vacía.")
        return v

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, v: str) -> str:
        if v not in _ADVISOR_VALID_DECISIONS:
            raise ValueError(
                f"decision inválida: {v!r}. "
                f"Opciones: {sorted(_ADVISOR_VALID_DECISIONS)}."
            )
        return v

    @field_validator("proposed_profile")
    @classmethod
    def _validate_proposed_profile(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _ADVISOR_VALID_PROFILES:
            raise ValueError(
                f"proposed_profile inválido: {v!r}. "
                f"Opciones: {sorted(_ADVISOR_VALID_PROFILES)}."
            )
        return v

    @field_validator("approved_profile")
    @classmethod
    def _validate_approved_profile(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _ADVISOR_VALID_PROFILES:
            raise ValueError(
                f"approved_profile inválido: {v!r}. "
                f"Opciones: {sorted(_ADVISOR_VALID_PROFILES)}."
            )
        return v

    @field_validator("rationale")
    @classmethod
    def _validate_rationale_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale no puede ser solo espacios en blanco.")
        return v

    @field_validator("source")
    @classmethod
    def _validate_source_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source no puede estar vacío.")
        return v

    @model_validator(mode="after")
    def _cross_validate_decision(self) -> "CaseAdvisorProfileApprovalCreateRequest":
        # Si proposed_profile NO viene, no se puede validar coherencia acá;
        # el endpoint lo deriva del último análisis o devuelve 422.
        if self.proposed_profile is None:
            return self

        if self.decision == "approve":
            if self.approved_profile is None:
                object.__setattr__(self, "approved_profile", self.proposed_profile)
            elif self.approved_profile != self.proposed_profile:
                raise ValueError(
                    "decision='approve' requiere approved_profile igual a "
                    "proposed_profile (o None para auto-completar). "
                    f"Recibido proposed={self.proposed_profile!r}, "
                    f"approved={self.approved_profile!r}. "
                    "Usar decision='modify' para aprobar un perfil distinto."
                )
        elif self.decision == "modify":
            if self.approved_profile is None:
                raise ValueError(
                    "decision='modify' requiere approved_profile no nulo."
                )
            # Profile validity ya validado por _validate_approved_profile.
        elif self.decision == "reject":
            if self.approved_profile is not None:
                raise ValueError(
                    "decision='reject' requiere approved_profile=None."
                )
        return self


class CaseAdvisorProfileApprovalResponse(BaseModel):
    approval_id:            str
    case_id:                str
    ai_profile_analysis_id: str | None
    kyc_submission_id:      str | None
    advisor_id:             str | None
    proposed_profile:       str
    decision:               str
    approved_profile:       str | None
    rationale:              str
    source:                 str
    is_current:             bool
    created_at_utc:         str


class CaseAdvisorProfileApprovalListResponse(BaseModel):
    approvals: list[CaseAdvisorProfileApprovalResponse]
    count:     int


# ─────────────────────────────────────────────────────────────────────────────
# CaseInvestmentPreference + CaseUniverseFilterRun — Fase 2 Commit 11
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_INVESTMENT_PREFERENCE_SOURCES: frozenset[str] = frozenset(
    {"manual", "ai", "imported"}
)


class CaseInvestmentPreferenceCreateRequest(BaseModel):
    """
    Preferencias case-scoped del cliente. Puede venir como:
      - structured_preferences (dict): se usa tal cual. ai_request_log_id=None.
      - natural_language_preferences (str): se llama al extractor IA.
      - ambos: structured_preferences es la fuente de verdad; el texto se
        guarda como contexto. No se llama a IA.

    Al menos uno de los dos debe venir.
    """

    natural_language_preferences: str | None             = None
    structured_preferences:       dict[str, Any] | None  = None
    source:                       str                    = "manual"

    @field_validator("natural_language_preferences")
    @classmethod
    def _nlp_not_whitespace(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.strip():
            raise ValueError(
                "natural_language_preferences no puede ser solo espacios."
            )
        return v

    @field_validator("structured_preferences", mode="before")
    @classmethod
    def _structured_must_be_dict_if_present(cls, v: object) -> object:
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError(
                "structured_preferences debe ser un objeto JSON (dict); "
                f"recibido {type(v).__name__}."
            )
        return v

    @field_validator("source")
    @classmethod
    def _source_must_be_allowed(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source no puede ser solo espacios.")
        if v not in _ALLOWED_INVESTMENT_PREFERENCE_SOURCES:
            raise ValueError(
                f"source inválido: {v!r}. "
                f"Permitidos: {sorted(_ALLOWED_INVESTMENT_PREFERENCE_SOURCES)}."
            )
        return v

    @model_validator(mode="after")
    def _at_least_one_input(self) -> "CaseInvestmentPreferenceCreateRequest":
        if self.natural_language_preferences is None and self.structured_preferences is None:
            raise ValueError(
                "Debe proveerse al menos uno de "
                "natural_language_preferences o structured_preferences."
            )
        return self


class CaseInvestmentPreferenceResponse(BaseModel):
    preference_id:                str
    case_id:                      str
    source:                       str
    natural_language_preferences: str | None
    structured_preferences:       dict[str, Any]
    ai_request_log_id:            str | None
    created_by_advisor_id:        str | None
    is_current:                   bool
    created_at_utc:               str


class CaseInvestmentPreferenceListResponse(BaseModel):
    preferences: list[CaseInvestmentPreferenceResponse]
    count:       int


# ── UniverseFilterRun ───────────────────────────────────────────────────────


class CaseUniverseFilterRunCreateRequest(BaseModel):
    preference_id:   str | None = None
    source_universe: str        = "sample_instrument_universe.csv"

    @field_validator("preference_id", mode="before")
    @classmethod
    def _preference_id_not_empty(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("preference_id no puede ser cadena vacía.")
        return v

    @field_validator("source_universe")
    @classmethod
    def _source_universe_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source_universe no puede ser solo espacios.")
        return v


class CaseUniverseFilterRunResponse(BaseModel):
    filter_run_id:          str
    case_id:                str
    preference_id:          str | None
    source_universe:        str
    eligible_instruments:   list[dict[str, Any]]
    exclusions:             list[dict[str, Any]]
    applied_filters:        list[str]
    warnings:               list[str]
    eligible_count:         int
    excluded_count:         int
    total_count:            int
    created_by_advisor_id:  str | None
    is_current:             bool
    created_at_utc:         str


class CaseUniverseFilterRunListResponse(BaseModel):
    filter_runs: list[CaseUniverseFilterRunResponse]
    count:       int
