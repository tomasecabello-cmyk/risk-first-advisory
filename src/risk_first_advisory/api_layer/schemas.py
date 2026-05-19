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
