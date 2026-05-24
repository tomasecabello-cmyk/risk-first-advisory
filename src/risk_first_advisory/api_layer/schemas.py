"""
Pydantic schemas para la API de risk-first-advisory.

Política: exponer solo primitivos. Los objetos de dominio internos
(enums, dataclasses) se reducen a str / int / bool antes de llegar aquí.
"""

from __future__ import annotations

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

    @field_validator("investment_experience")
    @classmethod
    def validate_experience(cls, v: str) -> str:
        if v.lower() not in _VALID_EXPERIENCES:
            raise ValueError(
                f"investment_experience inválido: {v!r}. "
                f"Opciones: {sorted(_VALID_EXPERIENCES)}"
            )
        return v.lower()


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
