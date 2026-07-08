"""
FastAPI app — risk-first-advisory.

Endpoints:
    GET  /health          — verificación de salud del backend.
    POST /demo/run        — ejecuta el workflow demo con fixtures, persiste en SQLite,
                            genera reporte Markdown y devuelve JSON resumido.
    POST /workflow/run    — ejecuta el workflow con KYCData y FinancialGoal por JSON,
                            usando MockAIClient y ScriptedAdvisorInterface por defecto.

Ejecución:
    uvicorn risk_first_advisory.api_layer.main:app --reload

Constantes monkeypatcheables en tests:
    DEFAULT_DB_PATH              — ruta al SQLite compartido.
    DEFAULT_REPORT_PATH          — ruta al reporte del demo.
    DEFAULT_WORKFLOW_REPORT_DIR  — directorio para reportes de /workflow/run.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from risk_first_advisory.ai_layer.mock_ai_client import MockAIClient
from risk_first_advisory.api_layer.auth import (
    AdvisorIdentity,
    get_current_advisor_required,
    require_roles,
)
from risk_first_advisory.api_layer.schemas import (
    AdvisorCreateRequest,
    AdvisorIdentityResponse,
    AdvisorListResponse,
    AdvisorOverrideApprovalRequest,
    AdvisorOverrideApprovalResponse,
    AdvisorPortfolioSelectionRequest,
    AdvisorPortfolioSelectionResponse,
    AdvisorProfileApprovalRequest,
    AdvisorProfileApprovalResponse,
    AdvisorResponse,
    AdvisoryCaseCreateRequest,
    AdvisoryCaseListResponse,
    AdvisoryCaseResponse,
    AdvisoryCaseStatusUpdateRequest,
    AIContradictionResponse,
    AIFilteredPortfolioRequest,
    AIFilteredPortfolioResponse,
    AIInvestmentPreferencesRequest,
    AIInvestmentPreferencesResponse,
    AIProfileAnalysisCreateRequest,
    AIProfileAnalysisListResponse,
    AIProfileAnalysisResponse,
    AIProfileFollowUpRequest,
    AIProfileFollowUpResponse,
    AIProfileRequest,
    AIProfileResponse,
    AIRequestLogCreateRequest,
    AIRequestLogListResponse,
    AIRequestLogResponse,
    AIUniverseFilterResponse,
    AuditEventCreateRequest,
    AuditEventListResponse,
    AuditEventResponse,
    AuditVerifyResponse,
    CapacityGap,
    CaseAdvisorProfileApprovalCreateRequest,
    CaseAdvisorProfileApprovalListResponse,
    CaseAdvisorProfileApprovalResponse,
    CaseAISummaryResponse,
    CaseAuditSummaryResponse,
    CaseInvestmentPreferenceCreateRequest,
    CaseInvestmentPreferenceListResponse,
    CaseInvestmentPreferenceResponse,
    CaseOverrideApprovalCreateRequest,
    CaseOverrideApprovalListResponse,
    CaseOverrideApprovalResponse,
    CasePortfolioProposalCreateRequest,
    CasePortfolioProposalListResponse,
    CasePortfolioProposalResponse,
    CasePortfolioSelectionCreateRequest,
    CasePortfolioSelectionListResponse,
    CasePortfolioSelectionResponse,
    CaseProfileFollowUpRequest,
    CaseReportCreateRequest,
    CaseReportListResponse,
    CaseReportResponse,
    CaseSummaryResponse,
    CaseUniverseFilterRunCreateRequest,
    CaseUniverseFilterRunListResponse,
    CaseUniverseFilterRunResponse,
    CaseWorkflowProgressResponse,
    ClientCreateRequest,
    ClientListResponse,
    ClientResponse,
    ClientRiskNumber,
    DemoRunResponse,
    DeterministicAssessment,
    FilteredSnapshotResponse,
    FinancialGoalRequest,
    FirmCreateRequest,
    FirmListResponse,
    FirmResponse,
    HealthResponse,
    InstrumentExclusionResponse,
    InstrumentResponse,
    KYCDataRequest,
    KYCSubmissionListResponse,
    KYCSubmissionResponse,
    LivePortfolioCandidateResponse,
    LivePortfolioMetadataResponse,
    LivePortfolioRequest,
    LivePortfolioResponse,
    LivePortfolioWeightResponse,
    PersistenceRecordIds,
    RecordListResponse,
    RiskGap,
    StoredRecordResponse,
    UniverseFilterRequest,
    UniverseFilterResponse,
    WorkflowRunRequest,
    WorkflowRunResponse,
)
from risk_first_advisory.data_layer.market_data import MockMarketDataProvider
from risk_first_advisory.human_layer.scripted_advisor_interface import (
    ScriptedAdvisorInterface,
)
from risk_first_advisory.kyc.models import (
    ESGExclusion,
    ESGPreference,
    ESGProfile,
    ESGStrictnessLevel,
    FinancialGoal,
    InvestmentObjective,
    InvestorExperience,
    KYCData,
)
from risk_first_advisory.persistence_layer.entity_repository import (
    CaseTransitionError,
    EntityConflictError,
    EntityNotFoundError,
    SQLiteAdvisorProfileApprovalCaseRepository,
    SQLiteAdvisorRepository,
    SQLiteAdvisoryCaseRepository,
    SQLiteAIProfileAnalysisRepository,
    SQLiteAIRequestLogRepository,
    SQLiteAuditEventRepository,
    SQLiteCaseInvestmentPreferenceRepository,
    SQLiteCaseOverrideApprovalRepository,
    SQLiteCasePortfolioProposalRepository,
    SQLiteCasePortfolioSelectionRepository,
    SQLiteCaseReportRepository,
    SQLiteCaseUniverseFilterRunRepository,
    SQLiteClientRepository,
    SQLiteEntityStore,
    SQLiteFirmRepository,
    SQLiteKYCSubmissionRepository,
    compute_input_hash,
    redact_ai_input,
)
from risk_first_advisory.persistence_layer.repositories import (
    RecordNotFoundError,
    RepositoryError,
    StoredRecord,
)
from risk_first_advisory.persistence_layer.sqlite_repository import (
    SQLiteAdvisorOverrideApprovalRepository,
    SQLiteAdvisorPortfolioSelectionRepository,
    SQLiteAdvisorProfileApprovalRepository,
    SQLiteAIFilteredPortfolioRepository,
    SQLiteAuditRepository,
    SQLitePersistenceStore,
    SQLiteReportRepository,
    SQLiteWorkflowRunRepository,
)
from risk_first_advisory.reporting_layer import (
    AIFilteredPortfolioReportGenerator,
    CaseMarkdownReportGenerator,
    MarkdownReport,
    MarkdownReportGenerator,
)
from risk_first_advisory.rules_layer.esg_compliance import ESGMetadataStore
from risk_first_advisory.rules_layer.instrument_suitability import (
    InstrumentSuitabilityMatrix,
)
from risk_first_advisory.rules_layer.product_governance import ApprovedProductUniverse
from risk_first_advisory.universe_layer import (
    CSVInstrumentUniverseProvider,
    PreferenceFilterEngine,
)
from risk_first_advisory.workflow_layer import AdvisoryWorkflowCoordinator
from risk_first_advisory.workflow_layer.advisory_workflow import AdvisoryWorkflowResult

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent.parent.parent  # …/api_layer → …/risk_first_advisory → …/src → project root

FIXTURES = ROOT / "tests" / "fixtures"
_KYC_FIXTURE = FIXTURES / "kyc_profiles" / "contradictorio_alta_severidad.json"
_UNIVERSE_YAML = FIXTURES / "universes" / "m1_universe.yaml"
_SUITABILITY_YAML = FIXTURES / "suitability" / "instrument_matrix.yaml"
_ESG_YAML = FIXTURES / "esg" / "instrument_esg_metadata.yaml"
_MARKET_DATA_YAML = FIXTURES / "market_data" / "m1_market_data.yaml"
_INSTRUMENT_UNIVERSE_CSV = FIXTURES / "universe" / "sample_instrument_universe.csv"
# Universo de tickers REALES (resuelven en data912/yfinance/Rava), usado por el
# flujo del caso solo con RFA_LIVE_DATA. El fixture sintético queda intacto para
# los tests/offline. Ver data_layer/live_market_data.py.
_INSTRUMENT_UNIVERSE_CSV_LIVE = FIXTURES / "universe" / "live_instrument_universe.csv"

# Rutas por defecto — monkeypatcheables en tests.
DEFAULT_DB_PATH: Path = ROOT / "data" / "demo_api.db"
DEFAULT_REPORT_PATH: Path = ROOT / "reports" / "demo_api_report.md"
DEFAULT_WORKFLOW_REPORT_DIR: Path = ROOT / "reports"


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="risk-first-advisory API",
    description="AI proposes, advisor decides.",
    version="0.1.0",
)

# ─────────────────────────────────────────────────────────────────────────────
# CORS — permite que el frontend local consuma la API sin bloqueo de navegador.
# Solo orígenes locales conocidos. No usar allow_origins=["*"] en producción.
# ─────────────────────────────────────────────────────────────────────────────

_CORS_ORIGINS = [
    "http://127.0.0.1:5500",  # python -m http.server 5500 -d frontend
    "http://localhost:5500",
    "http://127.0.0.1:5173",  # Vite dev server (futuro)
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Universo ETF para /live/portfolio-demo (mismo que scripts/run_live_portfolio_demo.py)
# ─────────────────────────────────────────────────────────────────────────────

_LIVE_TICKERS: list[str] = [
    "BIL", "SHV", "AGG", "BND", "IEF",
    "VTI", "SPY", "VEA", "VWO", "HYG", "GLD",
]

_LIVE_ASSET_CLASS_MAP: dict[str, str] = {
    "BIL": "cash", "SHV": "cash",
    "AGG": "bond", "BND": "bond", "IEF": "bond",
    "VTI": "equity", "SPY": "equity", "VEA": "equity", "VWO": "equity",
    "HYG": "high_yield",
    "GLD": "commodity",
}

_LIVE_CURRENCY_MAP: dict[str, str] = {t: "USD" for t in _LIVE_TICKERS}


# ─────────────────────────────────────────────────────────────────────────────
# Scripted demo metadata para /workflow/run
#
# /workflow/run NO llama a OpenAI ni interactúa con un asesor humano. Corre el
# pipeline productivo (governance → suitability → ESG → DQ → optimizer) sobre
# un perfil scripted ("moderado", aprobado automáticamente). Estos campos se
# exponen en la respuesta para que ningún consumidor confunda el endpoint con
# un flujo de IA real o de aprobación real del asesor.
# ─────────────────────────────────────────────────────────────────────────────

_WORKFLOW_RUN_EXECUTION_MODE: str = "scripted_demo"
_WORKFLOW_RUN_AI_SOURCE: str = "mock_scripted"
_WORKFLOW_RUN_ADVISOR_SOURCE: str = "scripted_auto_approve"
_WORKFLOW_RUN_IS_PRODUCTION_READY: bool = False
_WORKFLOW_RUN_WARNING: str = (
    "This endpoint uses MockAIClient and ScriptedAdvisorInterface. "
    "It is intended for deterministic demo/testing only."
)


# ─────────────────────────────────────────────────────────────────────────────
# Scripts por defecto para /workflow/run
# ─────────────────────────────────────────────────────────────────────────────

# IA propone perfil moderado sin contradicciones ni follow-up.
_DEFAULT_AI_SCRIPT: dict = {
    "initial_profile_response": {
        "profile_name": "moderado",
        "confidence": 0.82,
        "binding_dimension": "capacity",
        "risk_tolerance": "media",
        "risk_capacity": "media",
        "risk_need": "media",
        "detected_contradictions": [],
        "follow_up_questions": [],
        "advisor_review_required": True,
    }
}

# Asesor aprueba moderado sin modificaciones.
_DEFAULT_ADVISOR_SCRIPT: dict = {
    "advisor_id": "ADV-DEFAULT",
    "profile_approval": {
        "decision": "approve_as_proposed",
        "approved_profile": "moderado",
        "advisor_comment": "Perfil aprobado sin modificaciones por el asesor.",
    },
    "follow_up_responses": [],
}

# Mapa de alias de experiencia → InvestorExperience.
_EXPERIENCE_MAP: dict[str, InvestorExperience] = {
    "ninguna": InvestorExperience.NONE,
    "none": InvestorExperience.NONE,
    "basica": InvestorExperience.BASIC,
    "basic": InvestorExperience.BASIC,
    "moderada": InvestorExperience.MODERATE,
    "moderate": InvestorExperience.MODERATE,
    "avanzada": InvestorExperience.ADVANCED,
    "advanced": InvestorExperience.ADVANCED,
    "experto": InvestorExperience.EXPERT,
    "expert": InvestorExperience.EXPERT,
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de hidratación de fixtures demo (privados)
# ─────────────────────────────────────────────────────────────────────────────


def _build_esg_profile(payload: dict) -> ESGProfile:
    return ESGProfile(
        strictness_level=ESGStrictnessLevel(payload["strictness_level"]),
        hard_exclusions=[
            ESGExclusion(
                excluded_item=ex["excluded_item"],
                exclusion_type=ex["exclusion_type"],
                source=ex["source"],
                rationale=ex.get("rationale", ""),
            )
            for ex in payload.get("hard_exclusions", [])
        ],
        soft_preferences=[
            ESGPreference(
                preference_type=p["preference_type"],
                weight=p["weight"],
                minimum_threshold=p.get("minimum_threshold"),
            )
            for p in payload.get("soft_preferences", [])
        ],
    )


def _build_kyc(fixture: dict) -> KYCData:
    k = fixture["kyc"]
    return KYCData(
        age=k["age"],
        annual_income_usd=k["annual_income_usd"],
        approx_net_worth_usd=k["approx_net_worth_usd"],
        investment_objective=InvestmentObjective(k["investment_objective"]),
        time_horizon_years=k["time_horizon_years"],
        liquidity_need_pct=k["liquidity_need_pct"],
        experience=InvestorExperience(k["experience"]),
        emotional_loss_tolerance_pct=k["emotional_loss_tolerance_pct"],
        financial_loss_capacity_pct=k["financial_loss_capacity_pct"],
        preferred_currency=k["preferred_currency"],
        needs_income=k["needs_income"],
        prefers_simple_products=k["prefers_simple_products"],
        jurisdiction=k["jurisdiction"],
        esg_profile=_build_esg_profile(fixture["esg_profile"]),
        open_investment_goal=k.get("open_investment_goal", ""),
        open_risk_reaction=k.get("open_risk_reaction", ""),
        open_past_experience=k.get("open_past_experience", ""),
        open_concerns=k.get("open_concerns", ""),
        declared_return_expectation_pct=k.get("declared_return_expectation_pct"),
    )


def _build_goal(fixture: dict) -> FinancialGoal:
    g = fixture["financial_goal"]
    return FinancialGoal(
        initial_capital_usd=g["initial_capital_usd"],
        target_capital_usd=g["target_capital_usd"],
        horizon_years=g["horizon_years"],
        periodic_contribution_usd=g["periodic_contribution_usd"],
        contribution_frequency_years=g["contribution_frequency_years"],
        target_is_flexible=g["target_is_flexible"],
        horizon_is_flexible=g["horizon_is_flexible"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de conversión request → dataclasses (privados)
# ─────────────────────────────────────────────────────────────────────────────


def _build_kyc_data(req: KYCDataRequest) -> KYCData:
    """
    Convierte KYCDataRequest a KYCData usando los campos reales del request.

    Cambios Fase 1.5:
        - jurisdiction / preferred_currency / investment_objective /
          prefers_simple_products vienen del request (antes eran hardcoded).
        - annual_income_usd se respeta cuando viene en el request; si es None,
          se mantiene el fallback histórico (liquid_net_worth * 0.05) por
          backward compatibility con payloads existentes.
        - ESGProfile se construye desde esg_strictness_level / esg_exclusions /
          esg_preferences del request. Si no se mandan, se construye un perfil
          vacío equivalente al ESGProfile() anterior.
    """
    experience = _EXPERIENCE_MAP.get(req.investment_experience, InvestorExperience.MODERATE)
    needs_income = req.income_stability.lower() != "stable"
    # La tolerancia psicológica es el mínimo entre el score y el drawdown declarado.
    emotional_tolerance = min(
        req.risk_tolerance_score * 10.0,
        req.max_acceptable_drawdown_pct,
    )

    # annual_income_usd:
    #   - si el request lo provee, se usa tal cual (validado >= 0 por Pydantic).
    #   - si es None, fallback histórico derivado del liquid_net_worth para no
    #     romper payloads que no declaran ingresos. Min 1.0 evita 0 que rompería
    #     ratios downstream.
    if req.annual_income_usd is not None:
        annual_income = req.annual_income_usd
    else:
        annual_income = max(req.liquid_net_worth * 0.05, 1.0)

    # ESGProfile construido desde el request. Las listas vacías por defecto
    # producen un perfil sin exclusions/preferences (equivalente a ESGProfile()).
    esg_profile = ESGProfile(
        strictness_level=ESGStrictnessLevel(req.esg_strictness_level),
        hard_exclusions=[
            ESGExclusion(
                excluded_item=ex.excluded_item,
                exclusion_type=ex.exclusion_type,
                source=ex.source,
                rationale=ex.rationale,
            )
            for ex in req.esg_exclusions
        ],
        soft_preferences=[
            ESGPreference(
                preference_type=p.preference_type,
                weight=p.weight,
                minimum_threshold=p.minimum_threshold,
            )
            for p in req.esg_preferences
        ],
    )

    return KYCData(
        age=req.age,
        annual_income_usd=annual_income,
        approx_net_worth_usd=req.net_worth,
        investment_objective=InvestmentObjective(req.investment_objective),
        time_horizon_years=req.investment_horizon_years,
        liquidity_need_pct=req.liquidity_need_score / 10.0,
        experience=experience,
        emotional_loss_tolerance_pct=emotional_tolerance,
        financial_loss_capacity_pct=req.risk_capacity_score * 10.0,
        preferred_currency=req.preferred_currency,
        needs_income=needs_income,
        prefers_simple_products=req.prefers_simple_products,
        jurisdiction=req.jurisdiction,
        esg_profile=esg_profile,
        open_investment_goal=req.open_investment_goal or "",
        open_risk_reaction=req.open_risk_reaction or "",
        open_past_experience=req.open_past_experience or "",
        open_concerns=req.open_concerns or "",
        declared_return_expectation_pct=req.declared_return_expectation_pct,
    )


def _build_financial_goal(req: FinancialGoalRequest) -> FinancialGoal:
    return FinancialGoal(
        initial_capital_usd=req.initial_amount,
        target_capital_usd=req.target_amount,
        horizon_years=req.horizon_years,
        periodic_contribution_usd=req.annual_contribution,
        contribution_frequency_years=1.0,
        target_is_flexible=True,
        horizon_is_flexible=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helper de persistencia compartido
# ─────────────────────────────────────────────────────────────────────────────


def _persist_workflow(
    result: AdvisoryWorkflowResult,
    report_path: Path,
    db_path: Path,
) -> tuple[PersistenceRecordIds, str]:
    """
    Genera el reporte Markdown, lo guarda en disco y persiste en SQLite.

    Devuelve (record_ids, report_path_str) para que el endpoint construya su response.
    """
    report = MarkdownReportGenerator().generate_from_workflow_result(result)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report.save(report_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLitePersistenceStore(db_path) as store:
        store.init_schema()
        w_repo = SQLiteWorkflowRunRepository(store)
        a_repo = SQLiteAuditRepository(store)
        r_repo = SQLiteReportRepository(store)

        workflow_rec = w_repo.save_workflow_result(result)

        audit_rec_id: str | None = None
        m1 = result.m1_result
        if m1 is not None:
            audit = getattr(m1, "audit", None)
            if audit is not None:
                audit_rec = a_repo.save_audit_trail(audit)
                audit_rec_id = audit_rec.record_id

        report_rec = r_repo.save_report(report)

    return (
        PersistenceRecordIds(
            workflow_record_id=workflow_rec.record_id,
            audit_record_id=audit_rec_id,
            report_record_id=report_rec.record_id,
        ),
        str(report_path),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helper de persistencia para /ai/filtered-portfolio-demo
# ─────────────────────────────────────────────────────────────────────────────


def _persist_ai_filtered_portfolio(
    payload: dict,
    report_md: str,
    client_id: str,
    profile: str,
    status: str,
    candidate_count: int,
    db_path: Path,
) -> tuple[str, str]:
    """
    Persiste en SQLite:
        1. El payload completo de la respuesta como record "ai_filtered_portfolio".
        2. El report_markdown como MarkdownReport ("markdown_report" record).

    Devuelve (record_id, report_record_id) para que el endpoint los exponga
    en la response.

    No escribe el reporte a disco; solo lo persiste en el record store SQLite.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLitePersistenceStore(db_path) as store:
        store.init_schema()
        ai_repo = SQLiteAIFilteredPortfolioRepository(store)
        r_repo = SQLiteReportRepository(store)

        ai_record = ai_repo.save_ai_filtered_portfolio(
            payload=payload,
            client_id=client_id,
            profile=profile,
            status=status,
            candidate_count=candidate_count,
        )

        report = MarkdownReport(
            title=f"AI Filtered Portfolio Report — {client_id}",
            content=report_md,
            client_id=client_id,
            generated_at_utc=datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        )
        report_record = r_repo.save_report(report)

    return ai_record.record_id, report_record.record_id


# ─────────────────────────────────────────────────────────────────────────────
# Helper de persistencia para /advisor/profile-approval
# ─────────────────────────────────────────────────────────────────────────────


def _persist_advisor_profile_approval(
    payload: dict,
    client_id: str,
    advisor_id: str,
    decision: str,
    proposed_profile: str,
    approved_profile: str | None,
    db_path: Path,
) -> tuple[str, str]:
    """
    Persiste la decisión del asesor en SQLite como record
    "advisor_profile_approval".

    Devuelve (record_id, created_at_utc) para que el endpoint los exponga
    en la response.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLitePersistenceStore(db_path) as store:
        store.init_schema()
        approval_repo = SQLiteAdvisorProfileApprovalRepository(store)
        record = approval_repo.save_approval(
            payload=payload,
            client_id=client_id,
            advisor_id=advisor_id,
            decision=decision,
            proposed_profile=proposed_profile,
            approved_profile=approved_profile,
        )
    return record.record_id, record.created_at_utc


# ─────────────────────────────────────────────────────────────────────────────
# Helper de persistencia para /advisor/override-approval
# ─────────────────────────────────────────────────────────────────────────────


def _persist_advisor_override_approval(
    payload: dict,
    client_id: str,
    advisor_id: str,
    decision: str,
    candidate_variant: str,
    related_record_id: str | None,
    db_path: Path,
) -> tuple[str, str]:
    """
    Persiste la decisión de advisor override en SQLite como record
    "advisor_override_approval".

    Devuelve (record_id, created_at_utc) para que el endpoint los exponga
    en la response.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLitePersistenceStore(db_path) as store:
        store.init_schema()
        override_repo = SQLiteAdvisorOverrideApprovalRepository(store)
        record = override_repo.save_approval(
            payload=payload,
            client_id=client_id,
            advisor_id=advisor_id,
            decision=decision,
            candidate_variant=candidate_variant,
            related_record_id=related_record_id,
        )
    return record.record_id, record.created_at_utc


# ─────────────────────────────────────────────────────────────────────────────
# Helper de persistencia para /advisor/portfolio-selection
# ─────────────────────────────────────────────────────────────────────────────


def _persist_advisor_portfolio_selection(
    payload: dict,
    client_id: str,
    advisor_id: str,
    selected_variant: str,
    related_record_id: str | None,
    override_approval_record_id: str | None,
    db_path: Path,
) -> tuple[str, str]:
    """
    Persiste la selección final del asesor en SQLite como record
    "advisor_portfolio_selection".

    Devuelve (record_id, created_at_utc) para que el endpoint los exponga
    en la response.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLitePersistenceStore(db_path) as store:
        store.init_schema()
        selection_repo = SQLiteAdvisorPortfolioSelectionRepository(store)
        record = selection_repo.save_selection(
            payload=payload,
            client_id=client_id,
            advisor_id=advisor_id,
            selected_variant=selected_variant,
            related_record_id=related_record_id,
            override_approval_record_id=override_approval_record_id,
        )
    return record.record_id, record.created_at_utc


# ─────────────────────────────────────────────────────────────────────────────
# Helper de persistencia para AIRequestLog
#
# Política Fase 2:
#   - El logging NUNCA debe romper el endpoint AI principal. Si el insert
#     falla, se devuelve None y el endpoint continúa normalmente.
#   - Devolvemos el request_id en caso de éxito por si el caller quiere
#     incluirlo en la respuesta o en advisor_notes.
#   - El caller arma el input_payload original y la redacción / hash se
#     computan acá para garantizar consistencia.
# ─────────────────────────────────────────────────────────────────────────────


def _persist_ai_request_log(
    *,
    endpoint: str,
    model: str,
    prompt_version: str,
    input_payload: dict[str, Any],
    validation_status: str,
    db_path: Path,
    case_id: str | None = None,
    requested_by_advisor_id: str | None = None,
    raw_response: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    error_message: str | None = None,
) -> str | None:
    """
    Persiste un AIRequestLog. Devuelve `request_id` si tuvo éxito, None si
    falló (la operación principal del endpoint no se rompe).

    Importante: NUNCA loggea el input_payload original. La redacción y el
    hash se computan acá vía `redact_ai_input` / `compute_input_hash`.
    """
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        input_redacted = redact_ai_input(input_payload)
        input_hash = compute_input_hash(input_payload)
        with SQLiteEntityStore(db_path) as store:
            repo = SQLiteAIRequestLogRepository(store)
            data = repo.create(
                endpoint=endpoint,
                model=model,
                prompt_version=prompt_version,
                input_redacted=input_redacted,
                input_hash=input_hash,
                validation_status=validation_status,
                case_id=case_id,
                requested_by_advisor_id=requested_by_advisor_id,
                raw_response=raw_response,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                error_message=error_message,
            )
        return data["request_id"]
    except Exception:
        # Logging failure no rompe el endpoint AI. La operación principal
        # ya tiene su propia ruta de error/éxito. Si esto se vuelve un
        # problema operativo, una iteración futura puede agregar telemetría
        # o re-tirar la excepción.
        return None


def _resolve_ai_model_name(ai_client: Any) -> str:
    """Mejor esfuerzo para obtener el nombre de modelo del OpenAIProfileClient."""
    return str(getattr(ai_client, "_model", None) or "unknown")


# Prompt versions de cada endpoint AI integrado en Fase 2 Commit 7. Cambiar
# el sufijo si la forma del prompt / output schema cambia de forma incompatible.
_AI_LOG_ENDPOINT_INVESTMENT_PREFS:  str = "/ai/investment-preferences"
_AI_LOG_ENDPOINT_FILTER_UNIVERSE:   str = "/ai/filter-universe-demo"
_AI_LOG_ENDPOINT_FILTERED_PORTFOLIO: str = "/ai/filtered-portfolio-demo"

_AI_LOG_PROMPT_INVESTMENT_PREFS:    str = "investment_preferences_v1"
_AI_LOG_PROMPT_FILTER_UNIVERSE:     str = "ai_universe_filter_v1"
_AI_LOG_PROMPT_FILTERED_PORTFOLIO:  str = "ai_filtered_portfolio_v1"
_AI_LOG_PROMPT_CASE_PROFILE_ANALYSIS: str = "case_profile_analysis_v1"
_AI_LOG_PROMPT_CASE_PROFILE_FOLLOWUP: str = "case_profile_follow_up_v1"
_AI_LOG_PROMPT_CASE_INVESTMENT_PREFS: str = "case_investment_preferences_v1"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers para /live/portfolio-demo (privados, inyectables en tests)
# ─────────────────────────────────────────────────────────────────────────────


def _make_live_provider(period: str, interval: str):
    """
    Crea un FreeMarketDataProvider con el universo de ETFs live.

    Función separada para facilitar monkeypatch en tests sin llamar internet.
    """
    from risk_first_advisory.data_layer.free_market_data import FreeMarketDataProvider

    return FreeMarketDataProvider(
        tickers=_LIVE_TICKERS,
        asset_class_map=_LIVE_ASSET_CLASS_MAP,
        currency_map=_LIVE_CURRENCY_MAP,
        lookback_period=period,
        interval=interval,
    )


def _build_live_risk_budget(profile_name: str):
    """
    Construye un RiskBudget directamente desde PROFILE_BASE_PARAMS, sin KYCData.
    min_liquidity=0.0 y preferred_currency=USD como defaults.
    """
    from risk_first_advisory.models.risk_budget import RiskBudget
    from risk_first_advisory.rules_layer.risk_budget_builder import PROFILE_BASE_PARAMS

    params = dict(PROFILE_BASE_PARAMS[profile_name])
    return RiskBudget(
        profile_name=profile_name,
        target_volatility=params["target_volatility"],
        max_volatility=params["max_volatility"],
        max_drawdown=params["max_drawdown"],
        min_liquidity=0.0,
        max_equity=params["max_equity"],
        max_high_yield=params["max_high_yield"],
        max_single_asset=params["max_single_asset"],
        max_sector_exposure=params["max_sector_exposure"],
        max_duration=params["max_duration"],
        complex_products_allowed=params["complex_products_allowed"],
        preferred_currency="USD",
        notes=["source=live_portfolio_demo_api"],
    )


def _run_live_portfolio_demo(
    profile: str,
    period: str,
    interval: str,
    provider=None,
) -> LivePortfolioResponse:
    """
    Ejecuta el pipeline live completo:
        provider → DataQualityGate → ReturnEstimator
        → CovarianceEngine → RiskBudget → PortfolioGenerationCoordinator

    El parámetro ``provider`` permite inyectar un proveedor fake en tests.
    Si es None se crea un FreeMarketDataProvider real mediante _make_live_provider.
    """
    from risk_first_advisory.data_layer.covariance import CovarianceEngine
    from risk_first_advisory.data_layer.data_quality import DataQualityGate
    from risk_first_advisory.data_layer.return_estimator import ReturnEstimator
    from risk_first_advisory.portfolio_layer.generation import (
        PortfolioGenerationCoordinator,
        PortfolioVariant,
    )

    _variant_order = [
        PortfolioVariant.DEFENSIVE,
        PortfolioVariant.BALANCED,
        PortfolioVariant.GROWTH,
    ]

    base_kwargs = {"profile": profile, "period": period, "interval": interval}

    # ── Proveedor ──────────────────────────────────────────────────────────
    if provider is None:
        provider = _make_live_provider(period, interval)

    # ── DQ pass ───────────────────────────────────────────────────────────
    dq_gate = DataQualityGate()
    usable_snapshots = []
    dq_results_map: dict = {}
    dq_warnings: list[str] = []
    failed_or_missing = 0

    for ticker in _LIVE_TICKERS:
        try:
            snapshot = provider.get_snapshot(ticker)
        except Exception:
            failed_or_missing += 1
            continue

        if snapshot is None:
            failed_or_missing += 1
            continue

        try:
            dq_result = dq_gate.evaluate(snapshot)
        except Exception:
            failed_or_missing += 1
            continue

        dq_results_map[ticker] = dq_result
        if dq_result.warnings:
            dq_warnings.extend(
                f"{ticker}: {w}" for w in dq_result.warnings
            )

        if dq_result.is_usable:
            usable_snapshots.append(snapshot)
        else:
            failed_or_missing += 1

    if len(usable_snapshots) < 3:
        return LivePortfolioResponse(
            **base_kwargs,
            status="insufficient_data",
            total_tickers=len(_LIVE_TICKERS),
            usable_snapshots=len(usable_snapshots),
            failed_or_missing=failed_or_missing,
            dq_warnings=dq_warnings,
            candidates=[],
            candidate_count=0,
            message=(
                f"Solo {len(usable_snapshots)} snapshot(s) usables de "
                f"{len(_LIVE_TICKERS)} configurados. "
                "Se necesitan al menos 3. Verificar conexión a internet."
            ),
        )

    # ── Return estimates ──────────────────────────────────────────────────
    return_estimates = ReturnEstimator().estimate_many(
        usable_snapshots,
        data_quality_results_by_ticker=dq_results_map,
    )

    # ── Covariance matrix ─────────────────────────────────────────────────
    covariance_matrix = CovarianceEngine().build(usable_snapshots)

    # ── Risk budget ───────────────────────────────────────────────────────
    risk_budget = _build_live_risk_budget(profile)

    # ── Portfolio generation ──────────────────────────────────────────────
    try:
        candidate_set = PortfolioGenerationCoordinator().generate(
            client_id="LIVE-API-DEMO",
            approved_profile_name=profile,
            return_estimates=return_estimates,
            covariance_matrix=covariance_matrix,
            risk_budget=risk_budget,
        )
    except ValueError as exc:
        return LivePortfolioResponse(
            **base_kwargs,
            status="infeasible",
            total_tickers=len(_LIVE_TICKERS),
            usable_snapshots=len(usable_snapshots),
            failed_or_missing=failed_or_missing,
            dq_warnings=dq_warnings,
            candidates=[],
            candidate_count=0,
            message=f"Ninguna variante factible: {exc}",
        )

    # ── Serializar candidatos ─────────────────────────────────────────────
    candidates_out: list[LivePortfolioCandidateResponse] = []
    for variant in _variant_order:
        if variant not in candidate_set.candidates:
            continue
        portfolio = candidate_set.candidates[variant]
        meta = candidate_set.metadata.get(variant)

        # Pesos ordenados mayor → menor, solo > 0
        sorted_weights = sorted(
            ((t, w) for t, w in portfolio.weights.items() if w > 1e-6),
            key=lambda kv: kv[1],
            reverse=True,
        )

        meta_out = LivePortfolioMetadataResponse(
            risk_budget_exceeded=meta.risk_budget_exceeded if meta else False,
            requires_advisor_override=meta.requires_advisor_override if meta else False,
            exceeded_constraints=list(meta.exceeded_constraints) if meta else [],
            reason_codes=list(meta.reason_codes) if meta else [],
            notes=list(meta.notes) if meta else [],
        )

        candidates_out.append(
            LivePortfolioCandidateResponse(
                variant=variant.value,
                objective=portfolio.objective.value,
                expected_return_annual=portfolio.expected_return_annual,
                volatility_annual=portfolio.volatility_annual,
                risk_score=portfolio.risk_score,
                constraints_satisfied=portfolio.constraints_satisfied,
                reason_codes=list(portfolio.reason_codes),
                notes=list(portfolio.notes),
                metadata=meta_out,
                weights=[
                    LivePortfolioWeightResponse(ticker=t, weight=w)
                    for t, w in sorted_weights
                ],
            )
        )

    return LivePortfolioResponse(
        **base_kwargs,
        status="completed",
        total_tickers=len(_LIVE_TICKERS),
        usable_snapshots=len(usable_snapshots),
        failed_or_missing=failed_or_missing,
        dq_warnings=dq_warnings,
        candidates=candidates_out,
        candidate_count=len(candidates_out),
        message=f"{len(candidates_out)} portfolio(s) generado(s) para perfil '{profile}'.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Factory para /ai/profile-demo (privada, monkeypatcheable en tests)
# ─────────────────────────────────────────────────────────────────────────────


class _DemoProfileClient:
    """
    Cliente de perfil determinístico para la demo M-Demo (sin OPENAI_API_KEY).

    Se activa SOLO con la env var RFA_DEMO_MODE (no es un fallback silencioso
    en producción: sin la var, el endpoint sigue exigiendo OPENAI_API_KEY).

    El `preliminary_profile` se deriva del motor determinístico M-Engine
    (cuestionario Grable-Lytton + capacidad financiera de hechos), NO es un valor
    fijo: refleja lo que el cliente realmente cargó. La capacidad acota la
    tolerancia (effective = min(willingness, ability)), igual que en producción.

    Deriva una contradicción de la señal de estrés del KYC (`open_risk_reaction`):
    si el cliente expresa pánico/venta ante una caída, marca una contradicción
    media → el Risk Gap muestra gap_level "medium". Si no, queda alineado (low).
    Determinístico: misma KYC → misma respuesta.
    """

    _PANIC_HINTS = ("vend", "pánico", "panico", "todo", "salir", "miedo")

    def analyze_kyc(self, payload: dict) -> dict:
        from risk_first_advisory.ai_layer.risk_scoring import deterministic_assessment

        # Perfil REAL del cliente: cuestionario G-L + capacidad (no hardcodeado).
        profile = deterministic_assessment(payload)["profile"]

        reaction = str((payload or {}).get("open_risk_reaction") or "").lower()
        panics = any(h in reaction for h in self._PANIC_HINTS)
        if panics:
            return {
                "preliminary_profile": profile,
                "confidence": 0.7,
                "contradictions": [
                    {
                        "field": "open_risk_reaction",
                        "severity": "medium",
                        "explanation": (
                            f"El perfil declarado es {profile}, pero ante una caída "
                            "del 30% el cliente indica que vendería todo."
                        ),
                    }
                ],
                "follow_up_questions": [
                    "¿Cuánto tiempo podés mantener esta inversión sin tocar ese dinero?",
                    "Si tuvieras una pérdida importante, ¿afectaría tus gastos del día a día?",
                ],
                "advisor_notes": [
                    "Perfil determinístico (RFA_DEMO_MODE, sin OpenAI): derivado del "
                    "cuestionario Grable-Lytton y la capacidad financiera (M-Engine). "
                    "Revisar tolerancia real con el cliente.",
                ],
            }
        return {
            "preliminary_profile": profile,
            "confidence": 0.82,
            "contradictions": [],
            "follow_up_questions": [],
            "advisor_notes": [
                "Perfil determinístico (RFA_DEMO_MODE, sin OpenAI): derivado del "
                "cuestionario Grable-Lytton y la capacidad financiera (M-Engine).",
            ],
        }

    def analyze_follow_up(self, payload: dict) -> dict:
        """
        Segunda ronda determinística. Tras confirmar con el cliente:
          - si el análisis previo tenía contradicciones (la tolerancia revelada
            era menor que la declarada), ajusta el perfil UN escalón más
            conservador y marca las contradicciones como resueltas;
          - si no, confirma el perfil declarado sin cambios.
        Misma entrada → misma salida. NO aprueba: el asesor decide.
        """
        from risk_first_advisory.ai_layer.risk_scoring import PROFILES

        prev = (payload or {}).get("previous_analysis") or {}
        prev_profile = str(prev.get("preliminary_profile") or "moderado")
        had_contradictions = bool(prev.get("contradictions"))

        if had_contradictions:
            try:
                idx = PROFILES.index(prev_profile)
            except ValueError:
                idx = 2  # moderado
            revised = PROFILES[max(0, idx - 1)]
            reason = (
                f"Tras confirmar con el cliente, la tolerancia real resulta menor que "
                f"la declarada ({prev_profile}); se ajusta a un perfil más conservador "
                f"({revised})."
            )
        else:
            revised = prev_profile
            reason = "Las respuestas del cliente confirman el perfil declarado; sin cambios."

        return {
            "revised_profile": revised,
            "confidence": 0.85,
            "remaining_contradictions": [],
            "profile_change_reason": reason,
            "advisor_notes": [
                "Demo determinística (RFA_DEMO_MODE). Perfil revisado con las "
                "respuestas del cliente.",
            ],
        }


def _get_openai_profile_client():
    """
    Crea y devuelve un cliente de perfil.

    - Si RFA_DEMO_MODE está seteada y NO hay OPENAI_API_KEY, devuelve un
      _DemoProfileClient determinístico (para la demo local sin clave).
    - Si no, devuelve un OpenAIProfileClient real.

    Separada del endpoint para permitir monkeypatch en tests sin llamar
    a OpenAI ni requerir OPENAI_API_KEY en el entorno de CI.

    Raises:
        ValueError: si OPENAI_API_KEY no está configurada (y no hay demo mode).
        ImportError: si el paquete openai no está instalado.
    """
    import os

    if os.environ.get("RFA_DEMO_MODE") and not os.environ.get("OPENAI_API_KEY", "").strip():
        return _DemoProfileClient()

    from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

    return OpenAIProfileClient()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="risk-first-advisory")


@app.get("/kyc/tolerance-questionnaire")
def tolerance_questionnaire() -> dict[str, Any]:
    """
    Sirve el cuestionario Grable-Lytton (13 ítems) para que el frontend lo renderice
    dinámicamente. NO incluye los puntajes: el scoring queda server-side
    (compute_tolerance_score); el cliente solo manda las letras elegidas. Público.
    """
    from risk_first_advisory.ai_layer.grable_lytton import (
        GRABLE_LYTTON_ITEMS,
        RAW_MAX,
        RAW_MIN,
    )

    items = [
        {
            "id": item["id"],
            "text": item["text"],
            "options": [
                {"key": letter, "text": text, "points": pts}
                for (letter, text, pts) in item["options"]
            ],
        }
        for item in GRABLE_LYTTON_ITEMS
    ]
    return {
        "items": items,
        "raw_min": RAW_MIN,
        "raw_max": RAW_MAX,
        "source": "Grable & Lytton (1999), Financial Services Review 8",
    }


# ─────────────────────────────────────────────────────────────────────────────
# /auth/me — diagnostic endpoint for the Phase-1 advisor-auth scaffold.
#
# DEVELOPMENT-ONLY. Returns the advisor identity resolved from the Bearer
# token in the Authorization header. Used to validate auth wiring without
# touching any existing flow. The /ai/*, /workflow/*, /live/*, /universe/*
# and /demo/* endpoints DO NOT require auth yet — that hardening will be
# rolled out endpoint-by-endpoint in later Phase-1 tasks.
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/auth/me", response_model=AdvisorIdentityResponse)
def auth_me(
    advisor: AdvisorIdentity = Depends(get_current_advisor_required),
) -> AdvisorIdentityResponse:
    return AdvisorIdentityResponse(
        advisor_id=advisor.advisor_id,
        display_name=advisor.display_name,
        firm_id=advisor.firm_id,
        roles=list(advisor.roles),
    )


# ─────────────────────────────────────────────────────────────────────────────
# /advisor/profile-approval — primer acto formal del asesor (Fase 1).
#
# Registra la decisión del asesor sobre un perfil propuesto (por la IA o por
# el sistema).
#
# Auth: require_roles("advisor", "admin")
#   → 401 sin token / token inválido.
#   → 403 si el token es válido pero el rol es compliance o viewer.
# ─────────────────────────────────────────────────────────────────────────────


@app.post(
    "/advisor/profile-approval",
    response_model=AdvisorProfileApprovalResponse,
)
def advisor_profile_approval(
    req: AdvisorProfileApprovalRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> AdvisorProfileApprovalResponse:
    # La validación cruzada (decision/approved_profile) se hace en
    # AdvisorProfileApprovalRequest.model_validator → 422 automático
    # si las reglas se violan.

    # ── 1. Persistir ──────────────────────────────────────────────────────
    # Construimos primero el payload "preliminar" (sin record_id ni
    # created_at_utc) que es exactamente lo que serializaríamos como JSON
    # del lado del cliente. record_id y created_at_utc los agrega la
    # capa de persistencia y se completan en la response final.
    persist_payload: dict = {
        "client_id":             req.client_id,
        "advisor_id":            advisor.advisor_id,
        "advisor_display_name":  advisor.display_name,
        "firm_id":               advisor.firm_id,
        "proposed_profile":      req.proposed_profile,
        "decision":              req.decision,
        "approved_profile":      req.approved_profile,
        "rationale":             req.rationale,
        "source":                req.source,
        "related_record_id":     req.related_record_id,
    }

    try:
        record_id, created_at_utc = _persist_advisor_profile_approval(
            payload=persist_payload,
            client_id=req.client_id,
            advisor_id=advisor.advisor_id,
            decision=req.decision,
            proposed_profile=req.proposed_profile,
            approved_profile=req.approved_profile,
            db_path=DEFAULT_DB_PATH,
        )
    except Exception as err:
        raise HTTPException(
            status_code=500,
            detail="Advisor profile approval persistence failed.",
        ) from err

    # ── 2. Construir respuesta ────────────────────────────────────────────
    return AdvisorProfileApprovalResponse(
        record_id=record_id,
        client_id=req.client_id,
        advisor_id=advisor.advisor_id,
        advisor_display_name=advisor.display_name,
        firm_id=advisor.firm_id,
        proposed_profile=req.proposed_profile,
        decision=req.decision,
        approved_profile=req.approved_profile,
        rationale=req.rationale,
        source=req.source,
        related_record_id=req.related_record_id,
        created_at_utc=created_at_utc,
        status="recorded",
    )


# ─────────────────────────────────────────────────────────────────────────────
# /advisor/override-approval — segundo acto formal del asesor (Fase 1).
#
# Registra approve/reject sobre una variante de portfolio que excede el
# RiskBudget aprobado (típicamente GROWTH con
# reason_codes=["PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"]).
#
# Auth: require_roles("advisor", "admin")
#   → 401 sin token / token inválido.
#   → 403 si el token es válido pero el rol es compliance o viewer.
# Nota: no se valida todavía contra existencia real del candidate ni del
# record relacionado; el asesor declara reason_codes/exceeded_constraints
# explícitamente. Esa conciliación queda para una tarea posterior.
# Importante: para reject los reason_codes y exceeded_constraints se
# conservan en el record (no se borran) para trazabilidad de por qué se
# rechazó el override.
# ─────────────────────────────────────────────────────────────────────────────


@app.post(
    "/advisor/override-approval",
    response_model=AdvisorOverrideApprovalResponse,
)
def advisor_override_approval(
    req: AdvisorOverrideApprovalRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> AdvisorOverrideApprovalResponse:
    # ── 1. Persistir ──────────────────────────────────────────────────────
    persist_payload: dict = {
        "client_id":             req.client_id,
        "advisor_id":            advisor.advisor_id,
        "advisor_display_name":  advisor.display_name,
        "firm_id":               advisor.firm_id,
        "candidate_variant":     req.candidate_variant,
        "decision":              req.decision,
        "reason_codes":          list(req.reason_codes),
        "exceeded_constraints":  list(req.exceeded_constraints),
        "rationale":             req.rationale,
        "source":                req.source,
        "related_record_id":     req.related_record_id,
    }

    try:
        record_id, created_at_utc = _persist_advisor_override_approval(
            payload=persist_payload,
            client_id=req.client_id,
            advisor_id=advisor.advisor_id,
            decision=req.decision,
            candidate_variant=req.candidate_variant,
            related_record_id=req.related_record_id,
            db_path=DEFAULT_DB_PATH,
        )
    except Exception as _exc:
        raise HTTPException(
            status_code=500,
            detail="Advisor override approval persistence failed.",
        ) from _exc

    # ── 2. Construir respuesta ────────────────────────────────────────────
    return AdvisorOverrideApprovalResponse(
        record_id=record_id,
        client_id=req.client_id,
        advisor_id=advisor.advisor_id,
        advisor_display_name=advisor.display_name,
        firm_id=advisor.firm_id,
        candidate_variant=req.candidate_variant,
        decision=req.decision,
        reason_codes=list(req.reason_codes),
        exceeded_constraints=list(req.exceeded_constraints),
        rationale=req.rationale,
        source=req.source,
        related_record_id=req.related_record_id,
        created_at_utc=created_at_utc,
        status="recorded",
    )


# ─────────────────────────────────────────────────────────────────────────────
# /advisor/portfolio-selection — tercer acto formal del asesor (Fase 1).
#
# Registra la decisión final sobre cuál variante (DEFENSIVE / BALANCED /
# GROWTH) se presenta al cliente. Idealmente posterior a:
#   - una corrida de /ai/filtered-portfolio-demo (related_record_id)
#   - y, si la variante elegida es GROWTH, a un advisor override approval
#     (override_approval_record_id).
#
# Auth: require_roles("advisor", "admin")
#   → 401 sin token / token inválido.
#   → 403 si el token es válido pero el rol es compliance o viewer.
# Política Fase 1: NO se valida contra existencia real de los records
# enlazados; el endpoint solo registra la decisión declarada. Validación
# cruzada queda para una tarea de integración futura.
#
# Warning rules:
#   - GROWTH sin override_approval_record_id → warning en response:
#       "GROWTH selected without linked override approval record."
#   - DEFENSIVE/BALANCED con override_approval_record_id → aceptado sin warning.
# ─────────────────────────────────────────────────────────────────────────────


_GROWTH_WITHOUT_OVERRIDE_WARNING: str = (
    "GROWTH selected without linked override approval record."
)


@app.post(
    "/advisor/portfolio-selection",
    response_model=AdvisorPortfolioSelectionResponse,
)
def advisor_portfolio_selection(
    req: AdvisorPortfolioSelectionRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> AdvisorPortfolioSelectionResponse:
    # ── 1. Calcular warnings ──────────────────────────────────────────────
    warnings: list[str] = []
    if (
        req.selected_variant == "GROWTH"
        and req.override_approval_record_id is None
    ):
        warnings.append(_GROWTH_WITHOUT_OVERRIDE_WARNING)

    # ── 2. Persistir ──────────────────────────────────────────────────────
    # El warning forma parte del payload persistido para que compliance
    # pueda detectar selecciones de GROWTH sin override en una revisión
    # posterior (sin tener que recalcular la regla).
    persist_payload: dict = {
        "client_id":                    req.client_id,
        "advisor_id":                   advisor.advisor_id,
        "advisor_display_name":         advisor.display_name,
        "firm_id":                      advisor.firm_id,
        "selected_variant":             req.selected_variant,
        "rationale":                    req.rationale,
        "related_record_id":            req.related_record_id,
        "override_approval_record_id":  req.override_approval_record_id,
        "source":                       req.source,
        "warnings":                     list(warnings),
    }

    try:
        record_id, created_at_utc = _persist_advisor_portfolio_selection(
            payload=persist_payload,
            client_id=req.client_id,
            advisor_id=advisor.advisor_id,
            selected_variant=req.selected_variant,
            related_record_id=req.related_record_id,
            override_approval_record_id=req.override_approval_record_id,
            db_path=DEFAULT_DB_PATH,
        )
    except Exception as err:
        raise HTTPException(
            status_code=500,
            detail="Advisor portfolio selection persistence failed.",
        ) from err

    # ── 3. Construir respuesta ────────────────────────────────────────────
    return AdvisorPortfolioSelectionResponse(
        record_id=record_id,
        client_id=req.client_id,
        advisor_id=advisor.advisor_id,
        advisor_display_name=advisor.display_name,
        firm_id=advisor.firm_id,
        selected_variant=req.selected_variant,
        rationale=req.rationale,
        related_record_id=req.related_record_id,
        override_approval_record_id=req.override_approval_record_id,
        source=req.source,
        warnings=warnings,
        created_at_utc=created_at_utc,
        status="recorded",
    )


@app.post("/demo/run", response_model=DemoRunResponse)
def demo_run() -> DemoRunResponse:
    # Leer rutas en tiempo de llamada para que monkeypatch funcione en tests.
    db_path: Path = DEFAULT_DB_PATH
    report_path: Path = DEFAULT_REPORT_PATH

    # ── 1. Cargar fixture ─────────────────────────────────────────────────
    fixture_payload = json.loads(_KYC_FIXTURE.read_text(encoding="utf-8"))
    kyc = _build_kyc(fixture_payload)
    goal = _build_goal(fixture_payload)
    client_id: str = fixture_payload["client_id"]
    advisor_id: str = fixture_payload["advisor_script"]["advisor_id"]

    # ── 2. Construir dependencias mock ────────────────────────────────────
    universe = ApprovedProductUniverse.from_yaml(_UNIVERSE_YAML)
    suitability = InstrumentSuitabilityMatrix.from_yaml(_SUITABILITY_YAML)
    esg_store = ESGMetadataStore.from_yaml(_ESG_YAML)
    market_data = MockMarketDataProvider.from_yaml(_MARKET_DATA_YAML)
    ai_client = MockAIClient(scripted_responses=fixture_payload["ai_script"])
    advisor_interface = ScriptedAdvisorInterface(
        scripted_decisions=fixture_payload["advisor_script"]
    )

    # ── 3. Ejecutar workflow ──────────────────────────────────────────────
    result = AdvisoryWorkflowCoordinator().run(
        kyc_data=kyc,
        financial_goal=goal,
        client_id=client_id,
        advisor_id=advisor_id,
        ai_client=ai_client,
        advisor_interface=advisor_interface,
        product_universe=universe,
        suitability_matrix=suitability,
        esg_metadata_store=esg_store,
        market_data_provider=market_data,
    )

    # ── 4. Persistir y generar reporte ────────────────────────────────────
    records, report_path_str = _persist_workflow(result, report_path, db_path)

    # ── 5. Construir respuesta ────────────────────────────────────────────
    pf = result.portfolio_feasibility_result
    cs = result.candidate_set

    return DemoRunResponse(
        status=result.status.value,
        client_id=result.client_id,
        approved_profile_name=result.approved_profile_name,
        has_portfolios=result.has_portfolios,
        reason_codes=list(result.reason_codes),
        warnings=list(result.warnings),
        final_optimizer_tickers=list(result.final_optimizer_tickers),
        portfolio_feasibility_status=pf.status.value if pf is not None else None,
        candidate_count=cs.count if cs is not None else 0,
        records=records,
        report_path=report_path_str,
    )


@app.post("/ai/profile-demo", response_model=AIProfileResponse)
def ai_profile_demo(req: AIProfileRequest) -> AIProfileResponse:
    """
    Analiza KYC estructurado con IA real (OpenAI) y devuelve:
        - preliminary_profile : perfil preliminar sugerido por la IA
        - confidence          : confianza de la IA (0-1)
        - contradictions      : contradicciones detectadas en el KYC
        - follow_up_questions : preguntas de follow-up para el asesor
        - advisor_notes       : notas adicionales para el asesor

    La IA NO aprueba el perfil. La aprobación siempre corresponde al asesor.
    No persiste nada. No genera portfolios. No llama al workflow.
    """
    # ── 1. Crear cliente (valida OPENAI_API_KEY en el entorno) ────────────
    try:
        ai_client = _get_openai_profile_client()
    except (ValueError, ImportError) as err:
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not configured. Set the environment variable and retry.",
        ) from err

    # ── 2. Construir payload KYC como dict (excluye campos None) ──────────
    kyc_dict = req.kyc_payload.model_dump(exclude_none=True)
    # El client_id ayuda a la IA a contextualizar el caso (no lo usa para aprobar)
    kyc_dict["client_id"] = req.client_id

    # ── 3. Llamar a la IA ─────────────────────────────────────────────────
    try:
        result = ai_client.analyze_kyc(kyc_dict)
    except ValueError as err:
        raise HTTPException(
            status_code=502,
            detail="AI profile analysis failed. The AI returned an invalid response.",
        ) from err
    except Exception as _exc:
        raise HTTPException(
            status_code=502,
            detail="AI profile analysis failed due to an unexpected error.",
        ) from _exc

    # ── 4. Construir respuesta ─────────────────────────────────────────────
    contradictions = [
        AIContradictionResponse(
            field=c.get("field", ""),
            severity=c.get("severity", ""),
            explanation=c.get("explanation", ""),
        )
        for c in result.get("contradictions", [])
        if isinstance(c, dict)
    ]

    return AIProfileResponse(
        client_id=req.client_id,
        preliminary_profile=result["preliminary_profile"],
        confidence=float(result["confidence"]),
        contradictions=contradictions,
        follow_up_questions=[str(q) for q in result.get("follow_up_questions", [])],
        advisor_notes=[str(n) for n in result.get("advisor_notes", [])],
    )


@app.post("/ai/profile-follow-up", response_model=AIProfileFollowUpResponse)
def ai_profile_follow_up(req: AIProfileFollowUpRequest) -> AIProfileFollowUpResponse:
    """
    Segunda ronda de análisis de perfil con IA. Recibe el KYC original, el análisis
    previo y las respuestas del cliente a las preguntas de follow-up, y devuelve:
        - revised_profile          : perfil revisado por la IA
        - confidence               : confianza actualizada (0-1)
        - remaining_contradictions : contradicciones que persisten
        - profile_change_reason    : explicación del cambio (o mantenimiento) de perfil
        - advisor_notes            : notas actualizadas para el asesor

    La IA NO aprueba el perfil. La aprobación siempre corresponde al asesor.
    No persiste nada. No genera portfolios. No llama al workflow.
    """
    # ── 1. Crear cliente (valida OPENAI_API_KEY en el entorno) ────────────
    try:
        ai_client = _get_openai_profile_client()
    except (ValueError, ImportError) as err:
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not configured. Set the environment variable and retry.",
        ) from err

    # ── 2. Construir payload para la IA ──────────────────────────────────
    followup_payload = {
        "client_id": req.client_id,
        "original_kyc": req.original_kyc_payload.model_dump(exclude_none=True),
        "previous_analysis": req.previous_analysis.model_dump(),
        "follow_up_answers": [
            {"question": a.question, "answer": a.answer}
            for a in req.follow_up_answers
        ],
    }

    # ── 3. Llamar a la IA ─────────────────────────────────────────────────
    try:
        result = ai_client.analyze_follow_up(followup_payload)
    except ValueError as err:
        raise HTTPException(
            status_code=502,
            detail="AI profile follow-up analysis failed. The AI returned an invalid response.",
        ) from err
    except Exception as _exc:
        raise HTTPException(
            status_code=502,
            detail="AI profile follow-up analysis failed due to an unexpected error.",
        ) from _exc

    # ── 4. Construir respuesta ─────────────────────────────────────────────
    remaining_contradictions = [
        AIContradictionResponse(
            field=c.get("field", ""),
            severity=c.get("severity", ""),
            explanation=c.get("explanation", ""),
        )
        for c in result.get("remaining_contradictions", [])
        if isinstance(c, dict)
    ]

    return AIProfileFollowUpResponse(
        client_id=req.client_id,
        revised_profile=result["revised_profile"],
        confidence=float(result["confidence"]),
        remaining_contradictions=remaining_contradictions,
        profile_change_reason=str(result["profile_change_reason"]),
        advisor_notes=[str(n) for n in result.get("advisor_notes", [])],
    )


@app.post(
    "/ai/investment-preferences",
    response_model=AIInvestmentPreferencesResponse,
)
def ai_investment_preferences(
    req: AIInvestmentPreferencesRequest,
) -> AIInvestmentPreferencesResponse:
    """
    Extrae preferencias y restricciones de inversión estructuradas a partir de
    lenguaje natural del cliente.

    Transforma expresiones como "solo ONs hard dollar argentinas disponibles en Balanz"
    en un JSON estructurado con tipos de instrumento, moneda, país, entidad, sectores
    a evitar, etc. Aplicable luego al InstrumentUniverse.

    La IA NO filtra instrumentos. NO inventa tickers. NO genera portfolios.
    No persiste nada. No llama al workflow. No aprueba perfil.
    """
    # ── 1. Crear cliente (valida OPENAI_API_KEY en el entorno) ────────────
    try:
        ai_client = _get_openai_profile_client()
    except (ValueError, ImportError) as err:
        raise HTTPException(
            status_code=400,
            detail=(
                "OPENAI_API_KEY is not configured. "
                "Set the environment variable and retry."
            ),
        ) from err

    # ── 2. Construir payload para la IA ──────────────────────────────────
    preferences_payload: dict = {
        "client_id": req.client_id,
        "natural_language_preferences": req.natural_language_preferences,
        "kyc_context": req.kyc_context,
        "previous_profile_analysis": req.previous_profile_analysis,
    }

    # ── 3. Llamar a la IA + AIRequestLog automático ──────────────────────
    _start = time.perf_counter()
    _model_name = _resolve_ai_model_name(ai_client)
    try:
        result = ai_client.extract_investment_preferences(preferences_payload)
    except ValueError as exc:
        _persist_ai_request_log(
            endpoint=_AI_LOG_ENDPOINT_INVESTMENT_PREFS,
            model=_model_name,
            prompt_version=_AI_LOG_PROMPT_INVESTMENT_PREFS,
            input_payload=preferences_payload,
            validation_status="api_error",
            db_path=DEFAULT_DB_PATH,
            latency_ms=int((time.perf_counter() - _start) * 1000),
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "AI investment preferences extraction failed. "
                "The AI returned an invalid response. Check backend logs."
            ),
        ) from exc
    except Exception as exc:
        _persist_ai_request_log(
            endpoint=_AI_LOG_ENDPOINT_INVESTMENT_PREFS,
            model=_model_name,
            prompt_version=_AI_LOG_PROMPT_INVESTMENT_PREFS,
            input_payload=preferences_payload,
            validation_status="api_error",
            db_path=DEFAULT_DB_PATH,
            latency_ms=int((time.perf_counter() - _start) * 1000),
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail="AI investment preferences extraction failed due to an unexpected error.",
        ) from exc

    _persist_ai_request_log(
        endpoint=_AI_LOG_ENDPOINT_INVESTMENT_PREFS,
        model=_model_name,
        prompt_version=_AI_LOG_PROMPT_INVESTMENT_PREFS,
        input_payload=preferences_payload,
        validation_status="parsed_ok",
        db_path=DEFAULT_DB_PATH,
        raw_response=dict(result) if isinstance(result, dict) else None,
        latency_ms=int((time.perf_counter() - _start) * 1000),
    )

    # ── 4. Construir respuesta ─────────────────────────────────────────────
    return AIInvestmentPreferencesResponse(
        client_id=req.client_id,
        allowed_instrument_types=[
            str(t) for t in result.get("allowed_instrument_types", [])
        ],
        excluded_instrument_types=[
            str(t) for t in result.get("excluded_instrument_types", [])
        ],
        currency=result.get("currency"),
        country=result.get("country"),
        entity=result.get("entity"),
        hard_dollar_only=result.get("hard_dollar_only"),
        avoid_sectors=[str(s) for s in result.get("avoid_sectors", [])],
        prefer_sectors=[str(s) for s in result.get("prefer_sectors", [])],
        avoid_issuers=[str(i) for i in result.get("avoid_issuers", [])],
        prefer_issuers=[str(i) for i in result.get("prefer_issuers", [])],
        min_liquidity_score=result.get("min_liquidity_score"),
        max_maturity_year=result.get("max_maturity_year"),
        hard_constraints=[str(c) for c in result.get("hard_constraints", [])],
        soft_preferences=[str(p) for p in result.get("soft_preferences", [])],
        unparsed_preferences=[
            str(u) for u in result.get("unparsed_preferences", [])
        ],
        confidence=float(result["confidence"]),
        advisor_notes=[str(n) for n in result.get("advisor_notes", [])],
    )


# Keys from the AI response that PreferenceFilterEngine understands as filter inputs.
# The remaining AI metadata keys (hard_constraints, soft_preferences, confidence, …)
# are excluded here to avoid spurious "unknown_preference_key" warnings.
_AI_FILTER_PREFERENCE_KEYS: frozenset[str] = frozenset({
    "allowed_instrument_types",
    "excluded_instrument_types",
    "currency",
    "country",
    "entity",
    "hard_dollar_only",
    "avoid_sectors",
    "prefer_sectors",
    "avoid_issuers",
    "prefer_issuers",
    "min_liquidity_score",
    "max_maturity_year",
})


@app.post("/ai/filter-universe-demo", response_model=AIUniverseFilterResponse)
def ai_filter_universe_demo(
    req: AIInvestmentPreferencesRequest,
) -> AIUniverseFilterResponse:
    """
    Pipeline combinado: lenguaje natural → preferencias estructuradas → filtro de universo.

    1. Extrae preferencias de inversión desde lenguaje natural usando OpenAI.
    2. Carga el universo de instrumentos desde el fixture CSV.
    3. Aplica PreferenceFilterEngine con las preferencias extraídas.
    4. Devuelve AIUniverseFilterResponse con preferencias, instrumentos elegibles y exclusiones.

    La IA NO aprueba perfil. NO inventa tickers. NO genera portfolios.
    No persiste nada. No llama al workflow.
    """
    # ── 1. Crear cliente IA ───────────────────────────────────────────────
    try:
        ai_client = _get_openai_profile_client()
    except (ValueError, ImportError) as err:
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not configured. Set the environment variable and retry.",
        ) from err

    # ── 2. Extraer preferencias con IA + AIRequestLog automático ─────────
    preferences_payload: dict = {
        "client_id": req.client_id,
        "natural_language_preferences": req.natural_language_preferences,
        "kyc_context": req.kyc_context,
        "previous_profile_analysis": req.previous_profile_analysis,
    }
    _start = time.perf_counter()
    _model_name = _resolve_ai_model_name(ai_client)
    try:
        ai_result = ai_client.extract_investment_preferences(preferences_payload)
    except ValueError as exc:
        _persist_ai_request_log(
            endpoint=_AI_LOG_ENDPOINT_FILTER_UNIVERSE,
            model=_model_name,
            prompt_version=_AI_LOG_PROMPT_FILTER_UNIVERSE,
            input_payload=preferences_payload,
            validation_status="api_error",
            db_path=DEFAULT_DB_PATH,
            latency_ms=int((time.perf_counter() - _start) * 1000),
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail="AI investment preference extraction failed. The AI returned an invalid response.",
        ) from exc
    except Exception as exc:
        _persist_ai_request_log(
            endpoint=_AI_LOG_ENDPOINT_FILTER_UNIVERSE,
            model=_model_name,
            prompt_version=_AI_LOG_PROMPT_FILTER_UNIVERSE,
            input_payload=preferences_payload,
            validation_status="api_error",
            db_path=DEFAULT_DB_PATH,
            latency_ms=int((time.perf_counter() - _start) * 1000),
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail="AI investment preference extraction failed due to an unexpected error.",
        ) from exc

    _persist_ai_request_log(
        endpoint=_AI_LOG_ENDPOINT_FILTER_UNIVERSE,
        model=_model_name,
        prompt_version=_AI_LOG_PROMPT_FILTER_UNIVERSE,
        input_payload=preferences_payload,
        validation_status="parsed_ok",
        db_path=DEFAULT_DB_PATH,
        raw_response=dict(ai_result) if isinstance(ai_result, dict) else None,
        latency_ms=int((time.perf_counter() - _start) * 1000),
    )

    # ── 3. Cargar universo ────────────────────────────────────────────────
    csv_path: Path = _INSTRUMENT_UNIVERSE_CSV
    if not csv_path.exists():
        raise HTTPException(
            status_code=500,
            detail="Instrument universe fixture not found.",
        )
    try:
        universe = CSVInstrumentUniverseProvider(csv_path).load()
    except Exception as err:
        raise HTTPException(
            status_code=500,
            detail="Instrument universe fixture not found.",
        ) from err

    # ── 4. Construir dict de filtros (solo claves reconocidas por el engine) ──
    filter_prefs: dict = {
        k: v for k, v in ai_result.items() if k in _AI_FILTER_PREFERENCE_KEYS
    }

    # ── 5. Aplicar filtro ─────────────────────────────────────────────────
    try:
        filter_result = PreferenceFilterEngine().apply(universe, filter_prefs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ── 6. Serializar preferencias para la respuesta ──────────────────────
    preferences_resp = AIInvestmentPreferencesResponse(
        client_id=req.client_id,
        allowed_instrument_types=[str(t) for t in ai_result.get("allowed_instrument_types", [])],
        excluded_instrument_types=[str(t) for t in ai_result.get("excluded_instrument_types", [])],
        currency=ai_result.get("currency"),
        country=ai_result.get("country"),
        entity=ai_result.get("entity"),
        hard_dollar_only=ai_result.get("hard_dollar_only"),
        avoid_sectors=[str(s) for s in ai_result.get("avoid_sectors", [])],
        prefer_sectors=[str(s) for s in ai_result.get("prefer_sectors", [])],
        avoid_issuers=[str(i) for i in ai_result.get("avoid_issuers", [])],
        prefer_issuers=[str(i) for i in ai_result.get("prefer_issuers", [])],
        min_liquidity_score=ai_result.get("min_liquidity_score"),
        max_maturity_year=ai_result.get("max_maturity_year"),
        hard_constraints=[str(c) for c in ai_result.get("hard_constraints", [])],
        soft_preferences=[str(p) for p in ai_result.get("soft_preferences", [])],
        unparsed_preferences=[str(u) for u in ai_result.get("unparsed_preferences", [])],
        confidence=float(ai_result["confidence"]),
        advisor_notes=[str(n) for n in ai_result.get("advisor_notes", [])],
    )

    # ── 7. Serializar instrumentos y exclusiones ──────────────────────────
    eligible_out = [
        InstrumentResponse(
            ticker=inst.ticker,
            name=inst.name,
            issuer=inst.issuer,
            instrument_type=inst.instrument_type.value,
            asset_class=inst.asset_class.value,
            currency=inst.currency,
            country=inst.country,
            sector=inst.sector,
            available_entities=list(inst.available_entities),
            hard_dollar=inst.hard_dollar,
            maturity_date=inst.maturity_date,
            coupon_rate=inst.coupon_rate,
            ytm=inst.ytm,
            duration=inst.duration,
            liquidity_score=inst.liquidity_score,
            min_piece=inst.min_piece,
            rating=inst.rating,
            notes=list(inst.notes),
        )
        for inst in filter_result.eligible_universe.instruments
    ]

    exclusions_out = [
        InstrumentExclusionResponse(ticker=exc.ticker, reasons=list(exc.reasons))
        for exc in filter_result.exclusions
    ]

    return AIUniverseFilterResponse(
        client_id=req.client_id,
        preferences=preferences_resp,
        eligible_count=len(eligible_out),
        excluded_count=len(exclusions_out),
        eligible_instruments=eligible_out,
        exclusions=exclusions_out,
        applied_filters=list(filter_result.applied_filters),
        warnings=list(filter_result.warnings),
    )


@app.post("/universe/filter-demo", response_model=UniverseFilterResponse)
def universe_filter_demo(req: UniverseFilterRequest) -> UniverseFilterResponse:
    """
    Filtra el universo de instrumentos del fixture CSV usando PreferenceFilterEngine.

    Recibe preferencias estructuradas (misma forma que /ai/investment-preferences),
    carga el CSV de muestra, aplica filtros determinísticos y devuelve:
        - eligible_instruments : instrumentos que pasan todos los filtros activos
        - exclusions           : instrumentos excluidos con razones por ticker
        - applied_filters      : lista de filtros evaluados
        - warnings             : avisos (prefer_*, claves desconocidas, fechas faltantes)

    No llama a la IA. No persiste nada. No genera portfolios.
    """
    # ── 1. Verificar que el fixture existe ────────────────────────────────
    csv_path: Path = _INSTRUMENT_UNIVERSE_CSV
    if not csv_path.exists():
        raise HTTPException(
            status_code=500,
            detail="Instrument universe fixture not found.",
        )

    # ── 2. Cargar universo ────────────────────────────────────────────────
    try:
        universe = CSVInstrumentUniverseProvider(csv_path).load()
    except Exception as err:
        raise HTTPException(
            status_code=500,
            detail="Instrument universe fixture not found.",
        ) from err

    # ── 3. Construir dict de preferencias — solo claves con valor activo ──
    prefs: dict = req.model_dump(exclude_none=True)

    # ── 4. Aplicar filtro ─────────────────────────────────────────────────
    try:
        filter_result = PreferenceFilterEngine().apply(universe, prefs)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    # ── 5. Serializar respuesta ───────────────────────────────────────────
    eligible_out = [
        InstrumentResponse(
            ticker=inst.ticker,
            name=inst.name,
            issuer=inst.issuer,
            instrument_type=inst.instrument_type.value,
            asset_class=inst.asset_class.value,
            currency=inst.currency,
            country=inst.country,
            sector=inst.sector,
            available_entities=list(inst.available_entities),
            hard_dollar=inst.hard_dollar,
            maturity_date=inst.maturity_date,
            coupon_rate=inst.coupon_rate,
            ytm=inst.ytm,
            duration=inst.duration,
            liquidity_score=inst.liquidity_score,
            min_piece=inst.min_piece,
            rating=inst.rating,
            notes=list(inst.notes),
        )
        for inst in filter_result.eligible_universe.instruments
    ]

    exclusions_out = [
        InstrumentExclusionResponse(ticker=exc.ticker, reasons=list(exc.reasons))
        for exc in filter_result.exclusions
    ]

    return UniverseFilterResponse(
        eligible_count=len(eligible_out),
        excluded_count=len(exclusions_out),
        eligible_instruments=eligible_out,
        exclusions=exclusions_out,
        applied_filters=list(filter_result.applied_filters),
        warnings=list(filter_result.warnings),
    )


@app.post("/ai/filtered-portfolio-demo", response_model=AIFilteredPortfolioResponse)
def ai_filtered_portfolio_demo(
    req: AIFilteredPortfolioRequest,
) -> AIFilteredPortfolioResponse:
    """
    Pipeline completo: lenguaje natural → preferencias estructuradas → filtro de universo
    → snapshots → RiskBudget → generación de carteras candidatas.

    1. Extrae preferencias de inversión desde lenguaje natural usando OpenAI.
    2. Carga el universo de instrumentos desde el fixture CSV.
    3. Aplica PreferenceFilterEngine con las preferencias extraídas.
    4. Convierte instrumentos elegibles a MarketDataSnapshot via InstrumentMarketDataAdapter.
    5. Verifica diversificación mínima según el perfil de riesgo.
    6. Genera carteras DEFENSIVE / BALANCED / GROWTH vía PortfolioGenerationCoordinator.

    No persiste nada. No llama al workflow. No modifica el optimizador.

    Status codes en la respuesta:
        "completed"                                — carteras generadas.
        "blocked_insufficient_universe"            — < 3 snapshots usables.
        "blocked_insufficient_diversification_capacity" — snapshots < required_min_assets.
        "infeasible"                               — el optimizador no pudo generar ninguna variante.
    """
    import math

    from risk_first_advisory.data_layer.covariance import CovarianceEngine
    from risk_first_advisory.data_layer.instrument_market_data import (
        InstrumentMarketDataAdapter,
    )
    from risk_first_advisory.data_layer.return_estimator import ReturnEstimator
    from risk_first_advisory.portfolio_layer.generation import (
        PortfolioGenerationCoordinator,
        PortfolioVariant,
    )
    from risk_first_advisory.rules_layer.risk_budget_builder import VALID_PROFILES

    # ── 1. Validar perfil ─────────────────────────────────────────────────
    if req.profile not in VALID_PROFILES:
        valid = ", ".join(sorted(VALID_PROFILES))
        raise HTTPException(
            status_code=422,
            detail=f"Perfil desconocido: {req.profile!r}. Opciones válidas: {valid}.",
        )

    # ── 2. Crear cliente IA ───────────────────────────────────────────────
    try:
        ai_client = _get_openai_profile_client()
    except (ValueError, ImportError) as err:
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not configured. Set the environment variable and retry.",
        ) from err

    # ── 3. Extraer preferencias con IA + AIRequestLog automático ─────────
    preferences_payload: dict = {
        "client_id": req.client_id,
        "natural_language_preferences": req.natural_language_preferences,
        "kyc_context": req.kyc_context,
        "previous_profile_analysis": req.previous_profile_analysis,
    }
    _start = time.perf_counter()
    _model_name = _resolve_ai_model_name(ai_client)
    try:
        ai_result = ai_client.extract_investment_preferences(preferences_payload)
    except ValueError as exc:
        _persist_ai_request_log(
            endpoint=_AI_LOG_ENDPOINT_FILTERED_PORTFOLIO,
            model=_model_name,
            prompt_version=_AI_LOG_PROMPT_FILTERED_PORTFOLIO,
            input_payload=preferences_payload,
            validation_status="api_error",
            db_path=DEFAULT_DB_PATH,
            latency_ms=int((time.perf_counter() - _start) * 1000),
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail="AI investment preference extraction failed. The AI returned an invalid response.",
        ) from exc
    except Exception as exc:
        _persist_ai_request_log(
            endpoint=_AI_LOG_ENDPOINT_FILTERED_PORTFOLIO,
            model=_model_name,
            prompt_version=_AI_LOG_PROMPT_FILTERED_PORTFOLIO,
            input_payload=preferences_payload,
            validation_status="api_error",
            db_path=DEFAULT_DB_PATH,
            latency_ms=int((time.perf_counter() - _start) * 1000),
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail="AI investment preference extraction failed due to an unexpected error.",
        ) from exc

    _persist_ai_request_log(
        endpoint=_AI_LOG_ENDPOINT_FILTERED_PORTFOLIO,
        model=_model_name,
        prompt_version=_AI_LOG_PROMPT_FILTERED_PORTFOLIO,
        input_payload=preferences_payload,
        validation_status="parsed_ok",
        db_path=DEFAULT_DB_PATH,
        raw_response=dict(ai_result) if isinstance(ai_result, dict) else None,
        latency_ms=int((time.perf_counter() - _start) * 1000),
    )

    # ── 4. Cargar universo ────────────────────────────────────────────────
    csv_path: Path = _INSTRUMENT_UNIVERSE_CSV
    if not csv_path.exists():
        raise HTTPException(
            status_code=500,
            detail="Instrument universe fixture not found.",
        )
    try:
        universe = CSVInstrumentUniverseProvider(csv_path).load()
    except Exception as err:
        raise HTTPException(
            status_code=500,
            detail="Instrument universe fixture not found.",
        ) from err

    # ── 5. Aplicar filtro ─────────────────────────────────────────────────
    filter_prefs: dict = {
        k: v for k, v in ai_result.items() if k in _AI_FILTER_PREFERENCE_KEYS
    }
    try:
        filter_result = PreferenceFilterEngine().apply(universe, filter_prefs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ── 6. Serializar preferencias ────────────────────────────────────────
    preferences_resp = AIInvestmentPreferencesResponse(
        client_id=req.client_id,
        allowed_instrument_types=[str(t) for t in ai_result.get("allowed_instrument_types", [])],
        excluded_instrument_types=[str(t) for t in ai_result.get("excluded_instrument_types", [])],
        currency=ai_result.get("currency"),
        country=ai_result.get("country"),
        entity=ai_result.get("entity"),
        hard_dollar_only=ai_result.get("hard_dollar_only"),
        avoid_sectors=[str(s) for s in ai_result.get("avoid_sectors", [])],
        prefer_sectors=[str(s) for s in ai_result.get("prefer_sectors", [])],
        avoid_issuers=[str(i) for i in ai_result.get("avoid_issuers", [])],
        prefer_issuers=[str(i) for i in ai_result.get("prefer_issuers", [])],
        min_liquidity_score=ai_result.get("min_liquidity_score"),
        max_maturity_year=ai_result.get("max_maturity_year"),
        hard_constraints=[str(c) for c in ai_result.get("hard_constraints", [])],
        soft_preferences=[str(p) for p in ai_result.get("soft_preferences", [])],
        unparsed_preferences=[str(u) for u in ai_result.get("unparsed_preferences", [])],
        confidence=float(ai_result["confidence"]),
        advisor_notes=[str(n) for n in ai_result.get("advisor_notes", [])],
    )

    # ── 7. Serializar instrumentos elegibles y exclusiones ────────────────
    eligible_out = [
        InstrumentResponse(
            ticker=inst.ticker,
            name=inst.name,
            issuer=inst.issuer,
            instrument_type=inst.instrument_type.value,
            asset_class=inst.asset_class.value,
            currency=inst.currency,
            country=inst.country,
            sector=inst.sector,
            available_entities=list(inst.available_entities),
            hard_dollar=inst.hard_dollar,
            maturity_date=inst.maturity_date,
            coupon_rate=inst.coupon_rate,
            ytm=inst.ytm,
            duration=inst.duration,
            liquidity_score=inst.liquidity_score,
            min_piece=inst.min_piece,
            rating=inst.rating,
            notes=list(inst.notes),
        )
        for inst in filter_result.eligible_universe.instruments
    ]
    exclusions_out = [
        InstrumentExclusionResponse(ticker=exc.ticker, reasons=list(exc.reasons))
        for exc in filter_result.exclusions
    ]

    # ── 8. Convertir a snapshots ──────────────────────────────────────────
    all_snapshots = InstrumentMarketDataAdapter().to_many(
        filter_result.eligible_universe.instruments
    )
    usable_snapshots = [s for s in all_snapshots if s.is_usable]

    snapshots_out = [
        FilteredSnapshotResponse(
            ticker=s.ticker,
            expected_return_annual=s.expected_return_annual,
            volatility_annual=s.volatility_annual,
            duration=s.duration,
            liquidity_score=s.liquidity_score,
            notes=list(s.notes),
        )
        for s in all_snapshots
    ]

    # ── Helper: armar respuesta + generar reporte + persistir ─────────────
    # Todas las rutas (completed, blocked_*, infeasible) pasan por aquí, así
    # que cada respuesta del endpoint incluye report_markdown + record_ids.
    def _make_response(
        status: str,
        message: str,
        candidates: list[LivePortfolioCandidateResponse] | None = None,
    ) -> AIFilteredPortfolioResponse:
        cands = candidates or []
        response = AIFilteredPortfolioResponse(
            client_id=req.client_id,
            profile=req.profile,
            preferences=preferences_resp,
            eligible_count=len(eligible_out),
            excluded_count=len(exclusions_out),
            eligible_instruments=eligible_out,
            exclusions=exclusions_out,
            applied_filters=list(filter_result.applied_filters),
            warnings=list(filter_result.warnings),
            snapshots=snapshots_out,
            snapshot_count=len(snapshots_out),
            status=status,
            message=message,
            candidates=cands,
            candidate_count=len(cands),
        )

        # ── Generar reporte Markdown determinístico ────────────────────────
        try:
            report_payload = response.model_dump()
            report_payload["natural_language_preferences"] = (
                req.natural_language_preferences
            )
            report_md = AIFilteredPortfolioReportGenerator().generate(report_payload)
        except Exception as err:
            raise HTTPException(
                status_code=500,
                detail="AI filtered portfolio report generation failed.",
            ) from err
        response.report_markdown = report_md

        # ── Persistir en SQLite (payload + report) ─────────────────────────
        # Se lee DEFAULT_DB_PATH en tiempo de llamada para que monkeypatch
        # en tests pueda redirigir a tmp_path.
        try:
            persist_payload = response.model_dump()
            record_id, report_record_id = _persist_ai_filtered_portfolio(
                payload=persist_payload,
                report_md=report_md,
                client_id=response.client_id,
                profile=response.profile,
                status=response.status,
                candidate_count=response.candidate_count,
                db_path=DEFAULT_DB_PATH,
            )
        except Exception as err:
            raise HTTPException(
                status_code=500,
                detail="AI filtered portfolio persistence failed.",
            ) from err
        response.record_id = record_id
        response.report_record_id = report_record_id

        return response

    # ── 9. Bloqueo 1: mínimo absoluto ─────────────────────────────────────
    if len(usable_snapshots) < 3:
        return _make_response(
            status="blocked_insufficient_universe",
            message=(
                f"Solo {len(usable_snapshots)} snapshot(s) usable(s) en el universo filtrado. "
                "Se necesitan al menos 3 para generar un portfolio."
            ),
        )

    # ── 10. Construir RiskBudget ──────────────────────────────────────────
    risk_budget = _build_live_risk_budget(req.profile)
    msa = risk_budget.max_single_asset

    if msa <= 0.0:
        return _make_response(
            status="infeasible",
            message="RiskBudget inválido: max_single_asset debe ser > 0.",
        )

    # ── 11. Bloqueo 2: capacidad de diversificación ───────────────────────
    required_min = math.ceil(1.0 / msa)
    if len(usable_snapshots) < required_min:
        return _make_response(
            status="blocked_insufficient_diversification_capacity",
            message=(
                f"Solo {len(usable_snapshots)} snapshot(s) usable(s) para el perfil "
                f"'{req.profile}' (max_single_asset={msa:.0%}). "
                f"Se necesitan al menos {required_min} instrumentos para asignar el 100%."
            ),
        )

    # ── 12. Estimar retornos y covarianzas ────────────────────────────────
    return_estimates = ReturnEstimator().estimate_many(usable_snapshots)
    covariance_matrix = CovarianceEngine().build(usable_snapshots)

    # ── 13. Generar carteras candidatas ───────────────────────────────────
    try:
        candidate_set = PortfolioGenerationCoordinator().generate(
            client_id=req.client_id,
            approved_profile_name=req.profile,
            return_estimates=return_estimates,
            covariance_matrix=covariance_matrix,
            risk_budget=risk_budget,
        )
    except ValueError as exc:
        return _make_response(
            status="infeasible",
            message=f"Ninguna variante de cartera factible: {exc}",
        )

    # ── 14. Serializar candidatos ─────────────────────────────────────────
    _variant_order = [
        PortfolioVariant.DEFENSIVE,
        PortfolioVariant.BALANCED,
        PortfolioVariant.GROWTH,
    ]
    candidates_out: list[LivePortfolioCandidateResponse] = []
    for variant in _variant_order:
        if variant not in candidate_set.candidates:
            continue
        portfolio = candidate_set.candidates[variant]
        meta = candidate_set.metadata.get(variant)

        sorted_weights = sorted(
            ((t, w) for t, w in portfolio.weights.items() if w > 1e-6),
            key=lambda kv: kv[1],
            reverse=True,
        )
        meta_out = LivePortfolioMetadataResponse(
            risk_budget_exceeded=meta.risk_budget_exceeded if meta else False,
            requires_advisor_override=meta.requires_advisor_override if meta else False,
            exceeded_constraints=list(meta.exceeded_constraints) if meta else [],
            reason_codes=list(meta.reason_codes) if meta else [],
            notes=list(meta.notes) if meta else [],
        )
        candidates_out.append(
            LivePortfolioCandidateResponse(
                variant=variant.value,
                objective=portfolio.objective.value,
                expected_return_annual=portfolio.expected_return_annual,
                volatility_annual=portfolio.volatility_annual,
                risk_score=portfolio.risk_score,
                constraints_satisfied=portfolio.constraints_satisfied,
                reason_codes=list(portfolio.reason_codes),
                notes=list(portfolio.notes),
                metadata=meta_out,
                weights=[
                    LivePortfolioWeightResponse(ticker=t, weight=w)
                    for t, w in sorted_weights
                ],
            )
        )

    return _make_response(
        status="completed",
        message=f"{len(candidates_out)} candidato(s) generado(s) para perfil '{req.profile}'.",
        candidates=candidates_out,
    )


@app.post("/live/portfolio-demo", response_model=LivePortfolioResponse)
def live_portfolio_demo(req: LivePortfolioRequest) -> LivePortfolioResponse:
    from risk_first_advisory.rules_layer.risk_budget_builder import VALID_PROFILES

    if req.profile not in VALID_PROFILES:
        valid = ", ".join(sorted(VALID_PROFILES))
        raise HTTPException(
            status_code=422,
            detail=f"Perfil desconocido: {req.profile!r}. Válidos: {valid}",
        )
    return _run_live_portfolio_demo(
        profile=req.profile,
        period=req.period,
        interval=req.interval,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helper de recuperación compartido
# ─────────────────────────────────────────────────────────────────────────────


def _stored_record_to_response(record: StoredRecord) -> StoredRecordResponse:
    return StoredRecordResponse(
        record_id=record.record_id,
        record_type=record.record_type,
        created_at_utc=record.created_at_utc,
        payload=record.payload,
        metadata=record.metadata,
    )


@app.post("/workflow/run", response_model=WorkflowRunResponse)
def workflow_run(req: WorkflowRunRequest) -> WorkflowRunResponse:
    # Leer rutas en tiempo de llamada para que monkeypatch funcione en tests.
    db_path: Path = DEFAULT_DB_PATH
    report_dir: Path = DEFAULT_WORKFLOW_REPORT_DIR
    report_path = report_dir / f"workflow_{req.client_id}.md"

    # ── 1. Convertir request a dataclasses ───────────────────────────────
    kyc = _build_kyc_data(req.kyc_data)
    goal = _build_financial_goal(req.financial_goal)

    # ── 2. Construir dependencias mock ────────────────────────────────────
    universe = ApprovedProductUniverse.from_yaml(_UNIVERSE_YAML)
    suitability = InstrumentSuitabilityMatrix.from_yaml(_SUITABILITY_YAML)
    esg_store = ESGMetadataStore.from_yaml(_ESG_YAML)
    market_data = MockMarketDataProvider.from_yaml(_MARKET_DATA_YAML)
    ai_client = MockAIClient(scripted_responses=_DEFAULT_AI_SCRIPT)
    advisor_script = {**_DEFAULT_ADVISOR_SCRIPT, "advisor_id": req.advisor_id}
    advisor_interface = ScriptedAdvisorInterface(scripted_decisions=advisor_script)

    # ── 3. Ejecutar workflow ──────────────────────────────────────────────
    result = AdvisoryWorkflowCoordinator().run(
        kyc_data=kyc,
        financial_goal=goal,
        client_id=req.client_id,
        advisor_id=req.advisor_id,
        ai_client=ai_client,
        advisor_interface=advisor_interface,
        product_universe=universe,
        suitability_matrix=suitability,
        esg_metadata_store=esg_store,
        market_data_provider=market_data,
    )

    # ── 4. Persistir y generar reporte ────────────────────────────────────
    records, report_path_str = _persist_workflow(result, report_path, db_path)

    # ── 5. Construir respuesta ────────────────────────────────────────────
    pf = result.portfolio_feasibility_result
    cs = result.candidate_set

    # Append the scripted-demo warning to the workflow's own warnings list so
    # clients that only consume `warnings` still see the mock indicator.
    warnings_out: list[str] = list(result.warnings)
    warnings_out.append(_WORKFLOW_RUN_WARNING)

    return WorkflowRunResponse(
        status=result.status.value,
        client_id=result.client_id,
        approved_profile_name=result.approved_profile_name,
        has_portfolios=result.has_portfolios,
        reason_codes=list(result.reason_codes),
        warnings=warnings_out,
        final_optimizer_tickers=list(result.final_optimizer_tickers),
        portfolio_feasibility_status=pf.status.value if pf is not None else None,
        candidate_count=cs.count if cs is not None else 0,
        records=records,
        report_path=report_path_str,
        execution_mode=_WORKFLOW_RUN_EXECUTION_MODE,
        ai_source=_WORKFLOW_RUN_AI_SOURCE,
        advisor_source=_WORKFLOW_RUN_ADVISOR_SOURCE,
        is_production_ready=_WORKFLOW_RUN_IS_PRODUCTION_READY,
        warning=_WORKFLOW_RUN_WARNING,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval endpoints
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/workflow/{record_id}", response_model=StoredRecordResponse)
def get_workflow(record_id: str) -> StoredRecordResponse:
    db_path: Path = DEFAULT_DB_PATH
    try:
        with SQLitePersistenceStore(db_path) as store:
            store.init_schema()
            record = SQLiteWorkflowRunRepository(store).get_workflow_result(record_id)
    except RecordNotFoundError as err:
        raise HTTPException(status_code=404, detail="Record not found") from err
    except RepositoryError as _exc:
        raise HTTPException(status_code=500, detail="Persistence error") from _exc
    return _stored_record_to_response(record)


@app.get("/reports/{record_id}", response_model=StoredRecordResponse)
def get_report(record_id: str) -> StoredRecordResponse:
    db_path: Path = DEFAULT_DB_PATH
    try:
        with SQLitePersistenceStore(db_path) as store:
            store.init_schema()
            record = SQLiteReportRepository(store).get_report(record_id)
    except RecordNotFoundError as err:
        raise HTTPException(status_code=404, detail="Record not found") from err
    except RepositoryError as _exc:
        raise HTTPException(status_code=500, detail="Persistence error") from _exc
    return _stored_record_to_response(record)


@app.get("/audit/{record_id}", response_model=StoredRecordResponse)
def get_audit(record_id: str) -> StoredRecordResponse:
    db_path: Path = DEFAULT_DB_PATH
    try:
        with SQLitePersistenceStore(db_path) as store:
            store.init_schema()
            record = SQLiteAuditRepository(store).get_audit_trail(record_id)
    except RecordNotFoundError as err:
        raise HTTPException(status_code=404, detail="Record not found") from err
    except RepositoryError as _exc:
        raise HTTPException(status_code=500, detail="Persistence error") from _exc
    return _stored_record_to_response(record)


# ─────────────────────────────────────────────────────────────────────────────
# Listing endpoints
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/workflow", response_model=RecordListResponse)
def list_workflows(
    client_id: str | None = Query(default=None),
) -> RecordListResponse:
    db_path: Path = DEFAULT_DB_PATH
    try:
        with SQLitePersistenceStore(db_path) as store:
            store.init_schema()
            records = SQLiteWorkflowRunRepository(store).list_workflow_results(
                client_id=client_id
            )
    except RepositoryError as _exc:
        raise HTTPException(status_code=500, detail="Persistence error") from _exc
    items = [_stored_record_to_response(r) for r in records]
    return RecordListResponse(records=items, count=len(items))


@app.get("/reports", response_model=RecordListResponse)
def list_reports(
    client_id: str | None = Query(default=None),
) -> RecordListResponse:
    db_path: Path = DEFAULT_DB_PATH
    try:
        with SQLitePersistenceStore(db_path) as store:
            store.init_schema()
            records = SQLiteReportRepository(store).list_reports(client_id=client_id)
    except RepositoryError as _exc:
        raise HTTPException(status_code=500, detail="Persistence error") from _exc
    items = [_stored_record_to_response(r) for r in records]
    return RecordListResponse(records=items, count=len(items))


@app.get("/audit", response_model=RecordListResponse)
def list_audit(
    client_id: str | None = Query(default=None),
) -> RecordListResponse:
    db_path: Path = DEFAULT_DB_PATH
    try:
        with SQLitePersistenceStore(db_path) as store:
            store.init_schema()
            records = SQLiteAuditRepository(store).list_audit_trails(
                client_id=client_id
            )
    except RepositoryError as _exc:
        raise HTTPException(status_code=500, detail="Persistence error") from _exc
    items = [_stored_record_to_response(r) for r in records]
    return RecordListResponse(records=items, count=len(items))


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Entity endpoints: Firm, Advisor, Client
#
# RBAC:
#   POST /firms             → admin only
#   GET  /firms             → any valid token
#   GET  /firms/{firm_id}   → any valid token
#
#   POST /advisors                       → admin only
#   GET  /advisors                       → any valid token
#   GET  /advisors/{advisor_id}          → any valid token
#   GET  /firms/{firm_id}/advisors       → any valid token
#
#   POST /clients                        → admin or advisor
#   GET  /clients                        → any valid token
#   GET  /clients/{client_id}            → any valid token
#   GET  /firms/{firm_id}/clients        → any valid token
#   GET  /advisors/{advisor_id}/clients  → any valid token
#
# FK violations (firm_id / primary_advisor_id not found) → HTTP 422.
# PK collision (duplicate ID on explicit create) → HTTP 409.
# Cross-firm validation (advisor.firm_id ≠ req.firm_id) → HTTP 422.
# ─────────────────────────────────────────────────────────────────────────────


# ── Firms ─────────────────────────────────────────────────────────────────────


@app.post("/firms", response_model=FirmResponse, status_code=201)
def create_firm(
    req: FirmCreateRequest,
    _: AdvisorIdentity = Depends(require_roles("admin")),
) -> FirmResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLiteEntityStore(db_path) as store:
        repo = SQLiteFirmRepository(store)
        try:
            data = repo.create(
                firm_id=req.firm_id.strip() if req.firm_id else None,
                display_name=req.display_name.strip(),
                country=req.country.strip(),
                is_active=req.is_active,
            )
        except EntityConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FirmResponse(**data)


@app.get("/firms", response_model=FirmListResponse)
def list_firms(
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> FirmListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        data = SQLiteFirmRepository(store).list_all()
    return FirmListResponse(firms=[FirmResponse(**d) for d in data], count=len(data))


@app.get("/firms/{firm_id}", response_model=FirmResponse)
def get_firm(
    firm_id: str,
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> FirmResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        data = SQLiteFirmRepository(store).get(firm_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Firm not found: {firm_id!r}")
    return FirmResponse(**data)


# ── Advisors ──────────────────────────────────────────────────────────────────


@app.post("/advisors", response_model=AdvisorResponse, status_code=201)
def create_advisor(
    req: AdvisorCreateRequest,
    _: AdvisorIdentity = Depends(require_roles("admin")),
) -> AdvisorResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLiteEntityStore(db_path) as store:
        repo = SQLiteAdvisorRepository(store)
        try:
            data = repo.create(
                advisor_id=req.advisor_id.strip() if req.advisor_id else None,
                firm_id=req.firm_id.strip(),
                display_name=req.display_name.strip(),
                email=req.email.strip(),
                roles=req.roles,
                is_active=req.is_active,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            # PK collision → "UNIQUE constraint failed" → 409
            # FK violation → "FOREIGN KEY constraint failed" → 422
            status = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status, detail=detail) from exc
    return AdvisorResponse(**data)


@app.get("/advisors", response_model=AdvisorListResponse)
def list_advisors(
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> AdvisorListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        data = SQLiteAdvisorRepository(store).list_all()
    return AdvisorListResponse(
        advisors=[AdvisorResponse(**d) for d in data], count=len(data)
    )


@app.get("/advisors/{advisor_id}", response_model=AdvisorResponse)
def get_advisor(
    advisor_id: str,
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> AdvisorResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        data = SQLiteAdvisorRepository(store).get(advisor_id)
    if data is None:
        raise HTTPException(
            status_code=404, detail=f"Advisor not found: {advisor_id!r}"
        )
    return AdvisorResponse(**data)


@app.get("/firms/{firm_id}/advisors", response_model=AdvisorListResponse)
def list_firm_advisors(
    firm_id: str,
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> AdvisorListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        firm_data = SQLiteFirmRepository(store).get(firm_id)
        if firm_data is None:
            raise HTTPException(
                status_code=404, detail=f"Firm not found: {firm_id!r}"
            )
        data = SQLiteAdvisorRepository(store).list_by_firm(firm_id)
    return AdvisorListResponse(
        advisors=[AdvisorResponse(**d) for d in data], count=len(data)
    )


# ── Clients ───────────────────────────────────────────────────────────────────


@app.post("/clients", response_model=ClientResponse, status_code=201)
def create_client(
    req: ClientCreateRequest,
    _: AdvisorIdentity = Depends(require_roles("admin", "advisor")),
) -> ClientResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLiteEntityStore(db_path) as store:
        adv_repo = SQLiteAdvisorRepository(store)
        client_repo = SQLiteClientRepository(store)

        # Cross-firm validation: primary_advisor must belong to the same firm.
        advisor_data = adv_repo.get(req.primary_advisor_id.strip())
        if advisor_data is None:
            raise HTTPException(
                status_code=422,
                detail=f"Advisor not found: {req.primary_advisor_id!r}",
            )
        if advisor_data["firm_id"] != req.firm_id.strip():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Advisor {req.primary_advisor_id!r} belongs to firm "
                    f"{advisor_data['firm_id']!r}, not {req.firm_id!r}."
                ),
            )

        try:
            data = client_repo.create(
                client_id=req.client_id.strip() if req.client_id else None,
                firm_id=req.firm_id.strip(),
                primary_advisor_id=req.primary_advisor_id.strip(),
                display_name=req.display_name.strip(),
                external_ref=req.external_ref.strip() if req.external_ref else None,
                jurisdiction=req.jurisdiction.strip(),
                preferred_currency=req.preferred_currency.strip(),
                is_active=req.is_active,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            # PK collision → "UNIQUE constraint failed" → 409
            # FK violation → "FOREIGN KEY constraint failed" → 422
            status = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status, detail=detail) from exc
    return ClientResponse(**data)


@app.get("/clients", response_model=ClientListResponse)
def list_clients(
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> ClientListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        data = SQLiteClientRepository(store).list_all()
    return ClientListResponse(
        clients=[ClientResponse(**d) for d in data], count=len(data)
    )


@app.get("/clients/{client_id}", response_model=ClientResponse)
def get_client(
    client_id: str,
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> ClientResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        data = SQLiteClientRepository(store).get(client_id)
    if data is None:
        raise HTTPException(
            status_code=404, detail=f"Client not found: {client_id!r}"
        )
    return ClientResponse(**data)


@app.get("/firms/{firm_id}/clients", response_model=ClientListResponse)
def list_firm_clients(
    firm_id: str,
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> ClientListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        firm_data = SQLiteFirmRepository(store).get(firm_id)
        if firm_data is None:
            raise HTTPException(
                status_code=404, detail=f"Firm not found: {firm_id!r}"
            )
        data = SQLiteClientRepository(store).list_by_firm(firm_id)
    return ClientListResponse(
        clients=[ClientResponse(**d) for d in data], count=len(data)
    )


@app.get("/advisors/{advisor_id}/clients", response_model=ClientListResponse)
def list_advisor_clients(
    advisor_id: str,
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> ClientListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        adv_data = SQLiteAdvisorRepository(store).get(advisor_id)
        if adv_data is None:
            raise HTTPException(
                status_code=404, detail=f"Advisor not found: {advisor_id!r}"
            )
        data = SQLiteClientRepository(store).list_by_advisor(advisor_id)
    return ClientListResponse(
        clients=[ClientResponse(**d) for d in data], count=len(data)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — AdvisoryCase endpoints
#
# RBAC:
#   POST /cases                          → advisor, admin
#   PATCH /cases/{case_id}/status        → advisor, admin
#   GET  /cases                          → any valid token
#   GET  /cases/{case_id}                → any valid token
#   GET  /clients/{client_id}/cases      → any valid token
#   GET  /advisors/{advisor_id}/cases    → any valid token
#   GET  /firms/{firm_id}/cases          → any valid token
#
# Business validations on POST /cases:
#   - firm_id must exist (422 if not).
#   - client_id must exist (422 if not).
#   - lead_advisor_id must exist (422 if not).
#   - client.firm_id must match req.firm_id (422 cross-firm mismatch).
#   - advisor.firm_id must match req.firm_id (422 cross-firm mismatch).
#   - status must be in ALLOWED_CASE_STATUSES (validated by Pydantic, 422).
#   - Duplicate case_id → 409.
#
# PATCH /cases/{case_id}/status:
#   - Invalid status value → 422 (Pydantic).
#   - Invalid transition → 409 Conflict.
#   - Case not found → 404.
# ─────────────────────────────────────────────────────────────────────────────


def _pick_actor_role(roles: list[str], fallback: str = "advisor") -> str:
    """
    Selecciona un rol representativo del advisor para registrar en el audit
    event. Preferencia: admin > advisor > compliance > viewer > fallback.

    No reordena ni modifica los roles del advisor; solo elige uno para
    estampar en el audit (actor_role es un string single-valued en la tabla
    audit_events).
    """
    priority = ("admin", "advisor", "compliance", "viewer")
    for r in priority:
        if r in roles:
            return r
    return fallback


@app.post("/cases", response_model=AdvisoryCaseResponse, status_code=201)
def create_case(
    req: AdvisoryCaseCreateRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> AdvisoryCaseResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLiteEntityStore(db_path) as store:
        firm_repo = SQLiteFirmRepository(store)
        adv_repo = SQLiteAdvisorRepository(store)
        client_repo = SQLiteClientRepository(store)
        case_repo = SQLiteAdvisoryCaseRepository(store)
        audit_repo = SQLiteAuditEventRepository(store)

        # ── 1. firm must exist ────────────────────────────────────────────
        firm_data = firm_repo.get(req.firm_id.strip())
        if firm_data is None:
            raise HTTPException(
                status_code=422,
                detail=f"Firm not found: {req.firm_id!r}",
            )

        # ── 2. client must exist ──────────────────────────────────────────
        client_data = client_repo.get(req.client_id.strip())
        if client_data is None:
            raise HTTPException(
                status_code=422,
                detail=f"Client not found: {req.client_id!r}",
            )

        # ── 3. lead advisor must exist ────────────────────────────────────
        advisor_data = adv_repo.get(req.lead_advisor_id.strip())
        if advisor_data is None:
            raise HTTPException(
                status_code=422,
                detail=f"Advisor not found: {req.lead_advisor_id!r}",
            )

        # ── 4. client must belong to the same firm ────────────────────────
        if client_data["firm_id"] != req.firm_id.strip():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Client {req.client_id!r} belongs to firm "
                    f"{client_data['firm_id']!r}, not {req.firm_id!r}."
                ),
            )

        # ── 5. advisor must belong to the same firm ───────────────────────
        if advisor_data["firm_id"] != req.firm_id.strip():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Advisor {req.lead_advisor_id!r} belongs to firm "
                    f"{advisor_data['firm_id']!r}, not {req.firm_id!r}."
                ),
            )

        # ── 6. persist ────────────────────────────────────────────────────
        try:
            data = case_repo.create(
                case_id=req.case_id.strip() if req.case_id else None,
                firm_id=req.firm_id.strip(),
                client_id=req.client_id.strip(),
                lead_advisor_id=req.lead_advisor_id.strip(),
                title=req.title.strip(),
                status=req.status,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        # ── 7. audit event automático "case_created" ──────────────────────
        # Limitación: el insert del case y el insert del audit event NO están
        # envueltos en una sola transacción explícita. Si el audit insert falla
        # (debería ser muy raro: el case acaba de existir, los hashes son
        # determinísticos, no hay FK rota), el case queda persistido sin su
        # primer evento. Devolvemos 500 con mensaje claro en ese caso.
        #
        # Si esto se vuelve crítico, una iteración futura puede mover ambos
        # inserts a un BEGIN/COMMIT manual.
        #
        # actor_advisor_id: la tabla audit_events tiene FK a advisors. El
        # advisor_id del token NO siempre coincide con un advisor entity
        # registrado (los tokens son del scaffold de Phase 1, las entities
        # son Phase 2). Hacemos un soft lookup: si existe, lo usamos;
        # si no, dejamos None para no violar la FK. La identidad del actor
        # queda igualmente capturada via actor_role.
        token_advisor_id: str | None = None
        if adv_repo.get(advisor.advisor_id) is not None:
            token_advisor_id = advisor.advisor_id

        try:
            audit_repo.append(
                case_id=data["case_id"],
                event_type="case_created",
                actor_advisor_id=token_advisor_id,
                actor_role=_pick_actor_role(advisor.roles),
                payload={
                    "case_id":         data["case_id"],
                    "firm_id":         data["firm_id"],
                    "client_id":       data["client_id"],
                    "lead_advisor_id": data["lead_advisor_id"],
                    "status":          data["status"],
                    "title":           data["title"],
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Case {data['case_id']!r} was created but the initial "
                    f"audit event failed: {exc}"
                ),
            ) from exc

    return AdvisoryCaseResponse(**data)


@app.get("/cases", response_model=AdvisoryCaseListResponse)
def list_cases(
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> AdvisoryCaseListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        data = SQLiteAdvisoryCaseRepository(store).list_all()
    return AdvisoryCaseListResponse(
        cases=[AdvisoryCaseResponse(**d) for d in data], count=len(data)
    )


@app.get("/cases/{case_id}", response_model=AdvisoryCaseResponse)
def get_case(
    case_id: str,
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> AdvisoryCaseResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        data = SQLiteAdvisoryCaseRepository(store).get(case_id)
    if data is None:
        raise HTTPException(
            status_code=404, detail=f"Case not found: {case_id!r}"
        )
    return AdvisoryCaseResponse(**data)


@app.patch("/cases/{case_id}/status", response_model=AdvisoryCaseResponse)
def patch_case_status(
    case_id: str,
    req: AdvisoryCaseStatusUpdateRequest,
    _: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> AdvisoryCaseResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        repo = SQLiteAdvisoryCaseRepository(store)
        try:
            data = repo.update_status(case_id, req.status)
        except EntityNotFoundError as err:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            ) from err
        except CaseTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AdvisoryCaseResponse(**data)


@app.get("/clients/{client_id}/cases", response_model=AdvisoryCaseListResponse)
def list_client_cases(
    client_id: str,
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> AdvisoryCaseListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        client_data = SQLiteClientRepository(store).get(client_id)
        if client_data is None:
            raise HTTPException(
                status_code=404, detail=f"Client not found: {client_id!r}"
            )
        data = SQLiteAdvisoryCaseRepository(store).list_by_client(client_id)
    return AdvisoryCaseListResponse(
        cases=[AdvisoryCaseResponse(**d) for d in data], count=len(data)
    )


@app.get("/advisors/{advisor_id}/cases", response_model=AdvisoryCaseListResponse)
def list_advisor_cases(
    advisor_id: str,
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> AdvisoryCaseListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        adv_data = SQLiteAdvisorRepository(store).get(advisor_id)
        if adv_data is None:
            raise HTTPException(
                status_code=404, detail=f"Advisor not found: {advisor_id!r}"
            )
        data = SQLiteAdvisoryCaseRepository(store).list_by_advisor(advisor_id)
    return AdvisoryCaseListResponse(
        cases=[AdvisoryCaseResponse(**d) for d in data], count=len(data)
    )


@app.get("/firms/{firm_id}/cases", response_model=AdvisoryCaseListResponse)
def list_firm_cases(
    firm_id: str,
    _: AdvisorIdentity = Depends(get_current_advisor_required),
) -> AdvisoryCaseListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        firm_data = SQLiteFirmRepository(store).get(firm_id)
        if firm_data is None:
            raise HTTPException(
                status_code=404, detail=f"Firm not found: {firm_id!r}"
            )
        data = SQLiteAdvisoryCaseRepository(store).list_by_firm(firm_id)
    return AdvisoryCaseListResponse(
        cases=[AdvisoryCaseResponse(**d) for d in data], count=len(data)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — AuditEvent endpoints (hash chain por AdvisoryCase)
#
# RBAC:
#   POST  /cases/{case_id}/audit-events  → advisor, admin
#   GET   /cases/{case_id}/audit         → admin, advisor, compliance, viewer
#   GET   /cases/{case_id}/audit/verify  → admin, compliance
#
# Notas:
#   - case_created se registra automáticamente en POST /cases (ver create_case).
#   - El acceso por firma todavía no está controlado: cualquier token válido
#     con el rol adecuado puede ver/crear eventos de cualquier caso. Firm-level
#     scoping queda pendiente.
#   - Esto NO es blockchain: un actor con acceso directo a la DB puede
#     reescribir toda la cadena (incluyendo todos los event_hash). verify_chain
#     detecta mutaciones puntuales (un payload, un hash, un sequence gap), no
#     una reescritura completa coordinada.
# ─────────────────────────────────────────────────────────────────────────────


@app.post(
    "/cases/{case_id}/audit-events",
    response_model=AuditEventResponse,
    status_code=201,
)
def create_audit_event(
    case_id: str,
    req: AuditEventCreateRequest,
    _: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> AuditEventResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLiteEntityStore(db_path) as store:
        adv_repo = SQLiteAdvisorRepository(store)
        audit_repo = SQLiteAuditEventRepository(store)

        # Si actor_advisor_id viene declarado, debe existir en la DB.
        # Convención: el caller declara explícitamente al actor, y la API
        # rechaza referencias colgadas para mantener la cadena auditable.
        if req.actor_advisor_id is not None:
            advisor_row = adv_repo.get(req.actor_advisor_id)
            if advisor_row is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Advisor not found: {req.actor_advisor_id!r}",
                )

        try:
            data = audit_repo.append(
                case_id=case_id,
                event_type=req.event_type.strip(),
                actor_role=req.actor_role.strip(),
                payload=dict(req.payload),
                actor_advisor_id=req.actor_advisor_id,
            )
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

    return AuditEventResponse(**data)


@app.get(
    "/cases/{case_id}/audit",
    response_model=AuditEventListResponse,
)
def list_case_audit_events(
    case_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> AuditEventListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        case_row = SQLiteAdvisoryCaseRepository(store).get(case_id)
        if case_row is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        events = SQLiteAuditEventRepository(store).list_by_case(case_id)
    return AuditEventListResponse(
        events=[AuditEventResponse(**e) for e in events],
        count=len(events),
    )


@app.get(
    "/cases/{case_id}/audit/verify",
    response_model=AuditVerifyResponse,
)
def verify_case_audit_chain(
    case_id: str,
    _: AdvisorIdentity = Depends(require_roles("admin", "compliance")),
) -> AuditVerifyResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        case_row = SQLiteAdvisoryCaseRepository(store).get(case_id)
        if case_row is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        result = SQLiteAuditEventRepository(store).verify_chain(case_id)

    return AuditVerifyResponse(
        case_id=case_id,
        is_intact=result["is_intact"],
        total_events=result["total_events"],
        first_broken_sequence=result["first_broken_sequence"],
        checked_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        message=result["message"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — AIRequestLog endpoints
#
# RBAC:
#   GET  /admin/ai-logs               → admin, compliance
#   GET  /admin/ai-logs/{request_id}  → admin, compliance
#   GET  /cases/{case_id}/ai-logs     → admin, compliance
#   POST /admin/ai-logs               → admin only (creación manual)
#
# Política:
#   - Lectura solo para roles auditores (admin/compliance). advisor/viewer
#     no ven logs IA por default — pueden contener inferencias intermedias
#     que no son resultados consumibles.
#   - Logs ordenados por created_at_utc asc, request_id asc como tiebreaker.
#   - input_redacted siempre se devuelve; el payload original NUNCA se
#     persiste, solo su hash.
# ─────────────────────────────────────────────────────────────────────────────


@app.get(
    "/admin/ai-logs",
    response_model=AIRequestLogListResponse,
)
def list_ai_logs(
    limit: int | None = Query(default=None, ge=0, le=1000),
    _: AdvisorIdentity = Depends(require_roles("admin", "compliance")),
) -> AIRequestLogListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        data = SQLiteAIRequestLogRepository(store).list_all(limit=limit)
    return AIRequestLogListResponse(
        logs=[AIRequestLogResponse(**d) for d in data], count=len(data)
    )


@app.get(
    "/admin/ai-logs/{request_id}",
    response_model=AIRequestLogResponse,
)
def get_ai_log(
    request_id: str,
    _: AdvisorIdentity = Depends(require_roles("admin", "compliance")),
) -> AIRequestLogResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        data = SQLiteAIRequestLogRepository(store).get(request_id)
    if data is None:
        raise HTTPException(
            status_code=404, detail=f"AI request log not found: {request_id!r}"
        )
    return AIRequestLogResponse(**data)


@app.get(
    "/cases/{case_id}/ai-logs",
    response_model=AIRequestLogListResponse,
)
def list_case_ai_logs(
    case_id: str,
    _: AdvisorIdentity = Depends(require_roles("admin", "compliance")),
) -> AIRequestLogListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        case_row = SQLiteAdvisoryCaseRepository(store).get(case_id)
        if case_row is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        data = SQLiteAIRequestLogRepository(store).list_by_case(case_id)
    return AIRequestLogListResponse(
        logs=[AIRequestLogResponse(**d) for d in data], count=len(data)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — KYCSubmission endpoints (case-scoped, versioned)
#
# RBAC:
#   POST /cases/{case_id}/kyc  → advisor, admin
#   GET  /cases/{case_id}/kyc  → admin, advisor, compliance, viewer
#
# Comportamiento de POST:
#   - Valida que el case exista (404 si no).
#   - Rechaza con 409 si el case está CLOSED (no se aceptan nuevas KYC tras
#     cierre formal del caso).
#   - Crea kyc_submission con version siguiente por case_id (1, 2, 3, ...).
#   - Actualiza advisory_cases.current_kyc_submission_id → submission nueva.
#   - Si el case está en DRAFT, transiciona a IN_PROGRESS (sigue la FSM).
#   - Si el case ya está en IN_PROGRESS o PORTFOLIO_SELECTED, mantiene el
#     status (no se exige re-aprobación de variantes acá; eso queda para
#     iteraciones futuras).
#   - Crea AuditEvent automático "kyc_submitted" con payload mínimo
#     (case_id, kyc_submission_id, version, submitted_by_advisor_id,
#     payload_hash). NO loggea el payload KYC completo en el audit chain
#     — ese vive en kyc_submissions con su propio hash.
#
# Limitaciones:
#   - El KYC submission y el audit event NO se persisten en una única
#     transacción atómica. Si el audit insert falla después del KYC insert,
#     el endpoint devuelve 500 con mensaje claro (mismo patrón que
#     POST /cases). Iteración futura puede consolidar.
# ─────────────────────────────────────────────────────────────────────────────


@app.post(
    "/cases/{case_id}/kyc",
    response_model=KYCSubmissionResponse,
    status_code=201,
)
def create_case_kyc(
    case_id: str,
    req: KYCDataRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> KYCSubmissionResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLiteEntityStore(db_path) as store:
        case_repo = SQLiteAdvisoryCaseRepository(store)
        kyc_repo = SQLiteKYCSubmissionRepository(store)
        adv_repo = SQLiteAdvisorRepository(store)
        audit_repo = SQLiteAuditEventRepository(store)

        # ── 1. case debe existir ──────────────────────────────────────────
        case_data = case_repo.get(case_id)
        if case_data is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )

        # ── 2. case no puede estar CLOSED ─────────────────────────────────
        if case_data["status"] == "CLOSED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} is CLOSED; new KYC submissions are not "
                    "accepted. Re-open or create a new case."
                ),
            )

        # ── 3. resolver actor_advisor_id contra entity (soft FK) ──────────
        # submitted_by_advisor_id (kyc_submissions FK) y actor_advisor_id
        # (audit_events FK) requieren un advisor entity. El advisor_id del
        # token (Phase 1) puede no existir como entity → fallback a None
        # para no violar la FK. La identidad del actor queda capturada igual
        # via actor_role en el audit event.
        submitted_by_advisor_id: str | None = None
        if adv_repo.get(advisor.advisor_id) is not None:
            submitted_by_advisor_id = advisor.advisor_id

        # ── 4. persistir submission ───────────────────────────────────────
        payload_dict = req.model_dump()
        try:
            sub_data = kyc_repo.create(
                case_id=case_id,
                payload=payload_dict,
                submitted_by_advisor_id=submitted_by_advisor_id,
            )
        except EntityNotFoundError as exc:
            # Defensive — el case ya fue verificado arriba.
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        # ── 5. actualizar puntero current_kyc_submission_id ───────────────
        try:
            case_repo.update_current_kyc_submission(
                case_id, sub_data["kyc_submission_id"]
            )
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        # ── 6. mover status DRAFT → IN_PROGRESS si corresponde ────────────
        if case_data["status"] == "DRAFT":
            try:
                case_repo.update_status(case_id, "IN_PROGRESS")
            except (EntityNotFoundError, CaseTransitionError) as exc:
                # No deberíamos llegar acá si DRAFT → IN_PROGRESS está en la
                # FSM (lo está). Defensivo: devolver 500 con mensaje claro
                # si la FSM cambia en el futuro.
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"KYC submission persisted but case status transition "
                        f"failed: {exc}"
                    ),
                ) from exc

        # ── 7. AuditEvent kyc_submitted ───────────────────────────────────
        try:
            audit_repo.append(
                case_id=case_id,
                event_type="kyc_submitted",
                actor_advisor_id=submitted_by_advisor_id,
                actor_role=_pick_actor_role(advisor.roles),
                payload={
                    "case_id":                 case_id,
                    "kyc_submission_id":       sub_data["kyc_submission_id"],
                    "version":                 sub_data["version"],
                    "submitted_by_advisor_id": submitted_by_advisor_id,
                    "payload_hash":            sub_data["payload_hash"],
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"KYC submission {sub_data['kyc_submission_id']!r} was "
                    f"persisted but the audit event failed: {exc}"
                ),
            ) from exc

    return KYCSubmissionResponse(**sub_data)


@app.get(
    "/cases/{case_id}/kyc",
    response_model=KYCSubmissionListResponse,
)
def list_case_kyc(
    case_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> KYCSubmissionListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        case_row = SQLiteAdvisoryCaseRepository(store).get(case_id)
        if case_row is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        data = SQLiteKYCSubmissionRepository(store).list_by_case(case_id)
    return KYCSubmissionListResponse(
        submissions=[KYCSubmissionResponse(**d) for d in data],
        count=len(data),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — AIProfileAnalysis endpoints (case-scoped)
#
# RBAC:
#   POST /cases/{case_id}/ai/profile-analysis  → advisor, admin
#   GET  /cases/{case_id}/ai/profile-analysis  → admin, advisor, compliance, viewer
#
# Comportamiento de POST:
#   - 404 si el case no existe.
#   - 409 si el case está CLOSED (no se aceptan nuevos análisis tras cierre).
#   - 409 si no hay current_kyc_submission_id y el caller no pasa
#     kyc_submission_id explícito.
#   - 422 si kyc_submission_id explícito no existe o no pertenece al case.
#   - Carga el payload de la KYCSubmission, lo pasa a OpenAIProfileClient.
#   - Mide latency_ms con time.perf_counter.
#   - Persiste AIRequestLog (case_id poblado), AIProfileAnalysis con
#     ai_request_log_id, y AuditEvent ai_profile_analyzed.
#   - Si la llamada IA falla: persiste AIRequestLog api_error, devuelve 502,
#     NO crea AIProfileAnalysis ni AuditEvent.
#
# Notas:
#   - El payload original NUNCA se loggea: se redacta vía _persist_ai_request_log.
#   - input_hash se computa sobre el original; payload_hash es del KYC, no se
#     duplica.
# ─────────────────────────────────────────────────────────────────────────────


@app.post(
    "/cases/{case_id}/ai/profile-analysis",
    response_model=AIProfileAnalysisResponse,
    status_code=201,
)
def create_case_profile_analysis(
    case_id: str,
    req: AIProfileAnalysisCreateRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> AIProfileAnalysisResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 1. Validaciones contra la DB ─────────────────────────────────────────
    with SQLiteEntityStore(db_path) as store:
        case_repo = SQLiteAdvisoryCaseRepository(store)
        kyc_repo = SQLiteKYCSubmissionRepository(store)
        adv_repo = SQLiteAdvisorRepository(store)

        case_data = case_repo.get(case_id)
        if case_data is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )

        if case_data["status"] == "CLOSED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} is CLOSED; AI profile analysis is "
                    "not accepted after case closure."
                ),
            )

        # Resolver KYC submission a usar.
        if req.kyc_submission_id is not None:
            sub_data = kyc_repo.get(req.kyc_submission_id)
            if sub_data is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"KYC submission not found: {req.kyc_submission_id!r}"
                    ),
                )
            if sub_data["case_id"] != case_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"KYC submission {req.kyc_submission_id!r} belongs to "
                        f"case {sub_data['case_id']!r}, not {case_id!r}."
                    ),
                )
        else:
            current_id = case_data["current_kyc_submission_id"]
            if current_id is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Case {case_id!r} has no KYC submission. "
                        "Submit a KYC via POST /cases/{case_id}/kyc first."
                    ),
                )
            sub_data = kyc_repo.get(current_id)
            if sub_data is None:
                # Inconsistencia interna: el puntero apunta a un row que no
                # existe. Devolvemos 500 con mensaje claro.
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Case {case_id!r} current_kyc_submission_id "
                        f"{current_id!r} not found in kyc_submissions."
                    ),
                )

        # Soft FK lookup para requested_by_advisor_id (mismo patrón que
        # case_created / kyc_submitted): si el advisor_id del token existe
        # como entity, se usa; si no, None.
        requested_by_advisor_id: str | None = None
        if adv_repo.get(advisor.advisor_id) is not None:
            requested_by_advisor_id = advisor.advisor_id

    # ── 2. Llamar a OpenAI (fuera del store; usa su propia conexión) ────────
    try:
        ai_client = _get_openai_profile_client()
    except (ValueError, ImportError) as err:
        raise HTTPException(
            status_code=400,
            detail=(
                "OPENAI_API_KEY is not configured. "
                "Set the environment variable and retry."
            ),
        ) from err

    model_name = _resolve_ai_model_name(ai_client)
    endpoint_str = f"/cases/{case_id}/ai/profile-analysis"

    # Construir el input para la IA: payload KYC + metadata mínima de case.
    # client_id se setea con el case_id para que la IA tenga un identificador
    # opaco; el client_id real del cliente vive en clients/{client_id}.
    kyc_payload: dict[str, Any] = dict(sub_data["payload"])
    ai_input_payload: dict[str, Any] = dict(kyc_payload)
    ai_input_payload["client_id"] = case_id  # opaque ID para la IA
    ai_input_payload["case_id"] = case_id
    ai_input_payload["kyc_submission_id"] = sub_data["kyc_submission_id"]

    _start = time.perf_counter()
    try:
        ai_result = ai_client.analyze_kyc(ai_input_payload)
    except ValueError as exc:
        _persist_ai_request_log(
            endpoint=endpoint_str,
            model=model_name,
            prompt_version=_AI_LOG_PROMPT_CASE_PROFILE_ANALYSIS,
            input_payload=ai_input_payload,
            validation_status="api_error",
            db_path=db_path,
            case_id=case_id,
            requested_by_advisor_id=requested_by_advisor_id,
            latency_ms=int((time.perf_counter() - _start) * 1000),
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "AI profile analysis failed. "
                "The AI returned an invalid response."
            ),
        ) from exc
    except Exception as exc:
        _persist_ai_request_log(
            endpoint=endpoint_str,
            model=model_name,
            prompt_version=_AI_LOG_PROMPT_CASE_PROFILE_ANALYSIS,
            input_payload=ai_input_payload,
            validation_status="api_error",
            db_path=db_path,
            case_id=case_id,
            requested_by_advisor_id=requested_by_advisor_id,
            latency_ms=int((time.perf_counter() - _start) * 1000),
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail="AI profile analysis failed due to an unexpected error.",
        ) from exc

    latency_ms = int((time.perf_counter() - _start) * 1000)

    # ── 3. Persistir AIRequestLog (parsed_ok) ───────────────────────────────
    ai_request_log_id = _persist_ai_request_log(
        endpoint=endpoint_str,
        model=model_name,
        prompt_version=_AI_LOG_PROMPT_CASE_PROFILE_ANALYSIS,
        input_payload=ai_input_payload,
        validation_status="parsed_ok",
        db_path=db_path,
        case_id=case_id,
        requested_by_advisor_id=requested_by_advisor_id,
        raw_response=dict(ai_result) if isinstance(ai_result, dict) else None,
        latency_ms=latency_ms,
    )

    # ── 4. Persistir AIProfileAnalysis + AuditEvent ─────────────────────────
    preliminary_profile = (
        str(ai_result.get("preliminary_profile"))
        if isinstance(ai_result, dict) and ai_result.get("preliminary_profile") is not None
        else None
    )
    confidence_raw = ai_result.get("confidence") if isinstance(ai_result, dict) else None
    confidence_val: float | None
    try:
        confidence_val = float(confidence_raw) if confidence_raw is not None else None
    except (TypeError, ValueError):
        confidence_val = None

    with SQLiteEntityStore(db_path) as store:
        analysis_repo = SQLiteAIProfileAnalysisRepository(store)
        audit_repo = SQLiteAuditEventRepository(store)

        try:
            analysis_data = analysis_repo.create(
                case_id=case_id,
                kyc_submission_id=sub_data["kyc_submission_id"],
                analysis_type=req.analysis_type,
                result=dict(ai_result) if isinstance(ai_result, dict) else {},
                preliminary_profile=preliminary_profile,
                confidence=confidence_val,
                ai_request_log_id=ai_request_log_id,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        # AuditEvent ai_profile_analyzed con metadata mínima.
        try:
            audit_repo.append(
                case_id=case_id,
                event_type="ai_profile_analyzed",
                actor_advisor_id=requested_by_advisor_id,
                actor_role=_pick_actor_role(advisor.roles),
                payload={
                    "case_id":             case_id,
                    "analysis_id":         analysis_data["analysis_id"],
                    "kyc_submission_id":   sub_data["kyc_submission_id"],
                    "ai_request_log_id":   ai_request_log_id,
                    "analysis_type":       req.analysis_type,
                    "preliminary_profile": preliminary_profile,
                    "confidence":          confidence_val,
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"AI profile analysis {analysis_data['analysis_id']!r} was "
                    f"persisted but the audit event failed: {exc}"
                ),
            ) from exc

    # ── 5. Derivar Risk Gap + marco determinístico (campos derivados) ───────
    # Combina la capa IA (analyze_kyc) con el motor determinístico (M-Engine):
    # IA = capa rica; motor = base auditable + fallback sin key + cross-check.
    # Ver ai_layer/risk_gap.py::combine_risk_gaps y ai_layer/risk_scoring.py.
    from risk_first_advisory.ai_layer.risk_gap import combine_risk_gaps
    from risk_first_advisory.ai_layer.risk_scoring import (
        capacity_gap_from_kyc,
        deterministic_assessment,
    )

    risk_gap_dict = combine_risk_gaps(
        ai_result if isinstance(ai_result, dict) else None,
        kyc_payload,
    )
    risk_gap_obj = RiskGap(**risk_gap_dict) if risk_gap_dict is not None else None
    det_obj = DeterministicAssessment(**deterministic_assessment(kyc_payload))
    capacity_gap_obj = CapacityGap(**capacity_gap_from_kyc(kyc_payload))
    risk_number_obj = ClientRiskNumber(**_client_risk_number_tolerant(kyc_payload))

    return AIProfileAnalysisResponse(
        **analysis_data,
        risk_gap=risk_gap_obj,
        deterministic=det_obj,
        capacity_gap=capacity_gap_obj,
        risk_number=risk_number_obj,
    )


@app.get(
    "/cases/{case_id}/ai/profile-analysis",
    response_model=AIProfileAnalysisListResponse,
)
def list_case_profile_analyses(
    case_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> AIProfileAnalysisListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        case_row = SQLiteAdvisoryCaseRepository(store).get(case_id)
        if case_row is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        data = SQLiteAIProfileAnalysisRepository(store).list_by_case(case_id)
    return AIProfileAnalysisListResponse(
        analyses=[AIProfileAnalysisResponse(**d) for d in data],
        count=len(data),
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /cases/{case_id}/ai/profile-follow-up  → advisor, admin
#
# Segunda ronda case-scoped: el asesor envía las respuestas del cliente a las
# preguntas de confirmación del Risk Gap. Llama a ai_client.analyze_follow_up,
# persiste un nuevo AIProfileAnalysis (analysis_type="follow_up", append-only)
# con AIRequestLog + AuditEvent (ai_profile_follow_up), y recomputa el Risk Gap.
#
# La IA NO aprueba: el perfil revisado sigue siendo una propuesta; el asesor lo
# aprueba vía POST /cases/{id}/profile-approval (I-001 / I-016).
#   - 404 si el case no existe.
#   - 409 si el case está CLOSED.
#   - 409 si no hay análisis previo sobre el que hacer follow-up.
#   - 422 si analysis_id / kyc_submission_id explícitos no pertenecen al case.
# ─────────────────────────────────────────────────────────────────────────────


@app.post(
    "/cases/{case_id}/ai/profile-follow-up",
    response_model=AIProfileAnalysisResponse,
    status_code=201,
)
def create_case_profile_follow_up(
    case_id: str,
    req: CaseProfileFollowUpRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> AIProfileAnalysisResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 1. Validaciones + resolver análisis previo y KYC ────────────────────
    with SQLiteEntityStore(db_path) as store:
        case_repo = SQLiteAdvisoryCaseRepository(store)
        kyc_repo = SQLiteKYCSubmissionRepository(store)
        adv_repo = SQLiteAdvisorRepository(store)
        analysis_repo = SQLiteAIProfileAnalysisRepository(store)

        case_data = case_repo.get(case_id)
        if case_data is None:
            raise HTTPException(status_code=404, detail=f"Case not found: {case_id!r}")
        if case_data["status"] == "CLOSED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} is CLOSED; AI profile follow-up is not "
                    "accepted after case closure."
                ),
            )

        analyses = analysis_repo.list_by_case(case_id)  # ASC por created_at
        if not analyses:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} has no prior AI profile analysis. Run "
                    "POST /cases/{case_id}/ai/profile-analysis first."
                ),
            )

        if req.analysis_id is not None:
            prev = next((a for a in analyses if a["analysis_id"] == req.analysis_id), None)
            if prev is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"AI profile analysis {req.analysis_id!r} not found in "
                        f"case {case_id!r}."
                    ),
                )
        else:
            prev = analyses[-1]  # el último

        # Resolver KYC submission: explícito > el del análisis previo > current.
        kyc_id = (
            req.kyc_submission_id
            or prev.get("kyc_submission_id")
            or case_data.get("current_kyc_submission_id")
        )
        if kyc_id is None:
            raise HTTPException(
                status_code=409,
                detail=f"Case {case_id!r} has no KYC submission to follow up on.",
            )
        sub_data = kyc_repo.get(kyc_id)
        if sub_data is None:
            raise HTTPException(
                status_code=422, detail=f"KYC submission not found: {kyc_id!r}"
            )
        if sub_data["case_id"] != case_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"KYC submission {kyc_id!r} belongs to case "
                    f"{sub_data['case_id']!r}, not {case_id!r}."
                ),
            )

        requested_by_advisor_id: str | None = None
        if adv_repo.get(advisor.advisor_id) is not None:
            requested_by_advisor_id = advisor.advisor_id

    # ── 2. Construir payload y llamar a la IA (fuera del store) ──────────────
    try:
        ai_client = _get_openai_profile_client()
    except (ValueError, ImportError) as err:
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not configured. Set the environment variable and retry.",
        ) from err

    model_name = _resolve_ai_model_name(ai_client)
    endpoint_str = f"/cases/{case_id}/ai/profile-follow-up"

    kyc_payload: dict[str, Any] = dict(sub_data["payload"])
    prev_result_raw = prev.get("result")
    prev_result: dict[str, Any] = prev_result_raw if isinstance(prev_result_raw, dict) else {}
    previous_analysis = {
        "preliminary_profile": prev.get("preliminary_profile"),
        "contradictions": prev_result.get("contradictions", []),
        "confidence": prev.get("confidence"),
    }
    follow_up_answers = [
        {"question": a.question, "answer": a.answer} for a in req.follow_up_answers
    ]
    ai_input_payload: dict[str, Any] = {
        "client_id": case_id,
        "case_id": case_id,
        "kyc_submission_id": kyc_id,
        "original_kyc": kyc_payload,
        "previous_analysis": previous_analysis,
        "follow_up_answers": follow_up_answers,
    }

    _start = time.perf_counter()
    try:
        fu_result = ai_client.analyze_follow_up(ai_input_payload)
    except Exception as exc:  # ValueError (validación) o error inesperado
        _persist_ai_request_log(
            endpoint=endpoint_str,
            model=model_name,
            prompt_version=_AI_LOG_PROMPT_CASE_PROFILE_FOLLOWUP,
            input_payload=ai_input_payload,
            validation_status="api_error",
            db_path=db_path,
            case_id=case_id,
            requested_by_advisor_id=requested_by_advisor_id,
            latency_ms=int((time.perf_counter() - _start) * 1000),
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail="AI profile follow-up failed. The AI returned an invalid response.",
        ) from exc

    latency_ms = int((time.perf_counter() - _start) * 1000)

    # ── 3. Normalizar la respuesta de follow-up al shape de analyze_kyc ──────
    # Así reusamos combine_risk_gaps y el mismo AIProfileAnalysisResponse.
    revised_profile = (
        str(fu_result.get("revised_profile"))
        if isinstance(fu_result, dict) and fu_result.get("revised_profile") is not None
        else None
    )
    remaining = (
        [c for c in fu_result.get("remaining_contradictions", []) if isinstance(c, dict)]
        if isinstance(fu_result, dict) else []
    )
    confidence_raw = fu_result.get("confidence") if isinstance(fu_result, dict) else None
    try:
        confidence_val: float | None = float(confidence_raw) if confidence_raw is not None else None
    except (TypeError, ValueError):
        confidence_val = None

    normalized_result: dict[str, Any] = {
        "preliminary_profile": revised_profile,
        "confidence": confidence_val,
        "contradictions": remaining,
        "follow_up_questions": [],  # resueltas en esta ronda
        "advisor_notes": [str(n) for n in (fu_result.get("advisor_notes") or [])],
        "profile_change_reason": str(fu_result.get("profile_change_reason") or ""),
        "follow_up_answers": follow_up_answers,
        "source_analysis_id": prev["analysis_id"],
    }

    ai_request_log_id = _persist_ai_request_log(
        endpoint=endpoint_str,
        model=model_name,
        prompt_version=_AI_LOG_PROMPT_CASE_PROFILE_FOLLOWUP,
        input_payload=ai_input_payload,
        validation_status="parsed_ok",
        db_path=db_path,
        case_id=case_id,
        requested_by_advisor_id=requested_by_advisor_id,
        raw_response=dict(fu_result) if isinstance(fu_result, dict) else None,
        latency_ms=latency_ms,
    )

    # ── 4. Persistir AIProfileAnalysis (follow_up) + AuditEvent ──────────────
    with SQLiteEntityStore(db_path) as store:
        analysis_repo = SQLiteAIProfileAnalysisRepository(store)
        audit_repo = SQLiteAuditEventRepository(store)

        try:
            analysis_data = analysis_repo.create(
                case_id=case_id,
                kyc_submission_id=kyc_id,
                analysis_type="follow_up",
                result=normalized_result,
                preliminary_profile=revised_profile,
                confidence=confidence_val,
                ai_request_log_id=ai_request_log_id,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        try:
            audit_repo.append(
                case_id=case_id,
                event_type="ai_profile_follow_up",
                actor_advisor_id=requested_by_advisor_id,
                actor_role=_pick_actor_role(advisor.roles),
                payload={
                    "case_id":             case_id,
                    "analysis_id":         analysis_data["analysis_id"],
                    "source_analysis_id":  prev["analysis_id"],
                    "kyc_submission_id":   kyc_id,
                    "ai_request_log_id":   ai_request_log_id,
                    "analysis_type":       "follow_up",
                    "revised_profile":     revised_profile,
                    "confidence":          confidence_val,
                    "answers_count":       len(follow_up_answers),
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"AI profile follow-up {analysis_data['analysis_id']!r} was "
                    f"persisted but the audit event failed: {exc}"
                ),
            ) from exc

    # ── 5. Recomputar Risk Gap + marco determinístico ───────────────────────
    from risk_first_advisory.ai_layer.risk_gap import combine_risk_gaps
    from risk_first_advisory.ai_layer.risk_scoring import deterministic_assessment

    risk_gap_dict = combine_risk_gaps(normalized_result, kyc_payload)
    risk_gap_obj = RiskGap(**risk_gap_dict) if risk_gap_dict is not None else None
    det_obj = DeterministicAssessment(**deterministic_assessment(kyc_payload))

    return AIProfileAnalysisResponse(
        **analysis_data, risk_gap=risk_gap_obj, deterministic=det_obj
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — CaseAdvisorProfileApproval endpoints
#
# RBAC:
#   POST /cases/{case_id}/profile-approval  → advisor, admin
#   GET  /cases/{case_id}/profile-approval  → admin, advisor, compliance, viewer
#
# Comportamiento de POST:
#   - 404 si el case no existe.
#   - 409 si el case está CLOSED.
#   - 422 si ai_profile_analysis_id explícito no existe / no pertenece al case.
#   - 422 si kyc_submission_id explícito no existe / no pertenece al case.
#   - 422 si proposed_profile es None y no hay análisis (o el análisis no tiene
#     preliminary_profile válido).
#   - Si proposed_profile viene None, se deriva del análisis (explícito o el
#     último del case).
#   - Si kyc_submission_id viene None y se eligió un análisis, se hereda del
#     análisis.
#   - decision approve / modify: marca previous is_current=0, este queda
#     is_current=1, actualiza advisory_cases.current_approved_profile_id.
#   - decision reject: is_current=0, NO pisa current_approved_profile_id (si
#     no había uno previo, queda en NULL como estaba).
#   - Emite AuditEvent: advisor_profile_approved / _modified / _rejected.
#
# Diseño:
#   - El nuevo endpoint NO modifica /advisor/profile-approval legacy.
#   - Reusa _ADVISOR_VALID_PROFILES via schema; misma policy de decisión.
# ─────────────────────────────────────────────────────────────────────────────


_PROFILE_APPROVAL_EVENT_BY_DECISION: dict[str, str] = {
    "approve": "advisor_profile_approved",
    "modify":  "advisor_profile_modified",
    "reject":  "advisor_profile_rejected",
}

# Whitelist de perfiles válidos para derivación de proposed_profile desde un
# análisis IA. Se duplica acá (mismo conjunto que _ADVISOR_VALID_PROFILES en
# schemas.py) para evitar tener que importar nombres privados de schemas.
_ADVISOR_VALID_PROFILES_SET: frozenset[str] = frozenset({
    "conservador",
    "moderado-defensivo",
    "moderado",
    "moderado-agresivo",
    "agresivo",
})


@app.post(
    "/cases/{case_id}/profile-approval",
    response_model=CaseAdvisorProfileApprovalResponse,
    status_code=201,
)
def create_case_profile_approval(
    case_id: str,
    req: CaseAdvisorProfileApprovalCreateRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> CaseAdvisorProfileApprovalResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLiteEntityStore(db_path) as store:
        case_repo = SQLiteAdvisoryCaseRepository(store)
        analysis_repo = SQLiteAIProfileAnalysisRepository(store)
        kyc_repo = SQLiteKYCSubmissionRepository(store)
        adv_repo = SQLiteAdvisorRepository(store)
        approval_repo = SQLiteAdvisorProfileApprovalCaseRepository(store)
        audit_repo = SQLiteAuditEventRepository(store)

        # ── 1. case debe existir ──────────────────────────────────────────
        case_data = case_repo.get(case_id)
        if case_data is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )

        # ── 2. CLOSED → 409 ───────────────────────────────────────────────
        if case_data["status"] == "CLOSED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} is CLOSED; profile approvals are not "
                    "accepted after case closure."
                ),
            )

        # ── 3. resolver ai_profile_analysis ───────────────────────────────
        analysis_data: dict[str, Any] | None = None
        if req.ai_profile_analysis_id is not None:
            analysis_data = analysis_repo.get(req.ai_profile_analysis_id)
            if analysis_data is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"AI profile analysis not found: "
                        f"{req.ai_profile_analysis_id!r}"
                    ),
                )
            if analysis_data["case_id"] != case_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"AI profile analysis {req.ai_profile_analysis_id!r} "
                        f"belongs to case {analysis_data['case_id']!r}, not "
                        f"{case_id!r}."
                    ),
                )
        else:
            # Sin id explícito: usar el último análisis del case si existe.
            all_analyses = analysis_repo.list_by_case(case_id)
            if all_analyses:
                analysis_data = all_analyses[-1]

        # ── 4. resolver kyc_submission ────────────────────────────────────
        kyc_id: str | None = None
        if req.kyc_submission_id is not None:
            sub_data = kyc_repo.get(req.kyc_submission_id)
            if sub_data is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"KYC submission not found: {req.kyc_submission_id!r}"
                    ),
                )
            if sub_data["case_id"] != case_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"KYC submission {req.kyc_submission_id!r} belongs to "
                        f"case {sub_data['case_id']!r}, not {case_id!r}."
                    ),
                )
            kyc_id = req.kyc_submission_id
        elif analysis_data is not None:
            kyc_id = analysis_data["kyc_submission_id"]

        # ── 5. resolver proposed_profile y approved_profile ───────────────
        proposed_profile = req.proposed_profile
        approved_profile = req.approved_profile

        if proposed_profile is None:
            if analysis_data is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "proposed_profile is required when the case has no "
                        "AI profile analysis to derive it from."
                    ),
                )
            derived = analysis_data.get("preliminary_profile")
            if not isinstance(derived, str) or derived not in _ADVISOR_VALID_PROFILES_SET:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Cannot derive proposed_profile from the analysis: "
                        f"preliminary_profile={derived!r} is not a valid "
                        "profile. Pass proposed_profile explicitly."
                    ),
                )
            proposed_profile = derived

            # Coherencia cruzada equivalente al schema validator, ahora que
            # tenemos un proposed_profile derivado.
            if req.decision == "approve":
                if approved_profile is None:
                    approved_profile = proposed_profile
                elif approved_profile != proposed_profile:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "decision='approve' requires approved_profile "
                            "equal to proposed_profile (or None to auto-fill)."
                        ),
                    )
            elif req.decision == "modify":
                if approved_profile is None:
                    raise HTTPException(
                        status_code=422,
                        detail="decision='modify' requires approved_profile.",
                    )
            elif req.decision == "reject":
                if approved_profile is not None:
                    raise HTTPException(
                        status_code=422,
                        detail="decision='reject' requires approved_profile=None.",
                    )

        # ── 5b. Tope determinístico: el marco (capacidad) acota a la IA ───
        # Si el perfil aprobado es MÁS riesgoso que lo que la situación
        # financiera del cliente soporta (ability), exige override explícito.
        # La IA propone, el marco acota, el asesor firma. Mismo patrón que el
        # override de presupuesto de cartera.
        from risk_first_advisory.ai_layer.risk_scoring import (
            deterministic_ceiling,
            profile_exceeds,
        )

        framework_override = False
        framework_ceiling: str | None = None
        if (
            req.decision in ("approve", "modify")
            and approved_profile is not None
            and kyc_id is not None
        ):
            kyc_for_cap = kyc_repo.get(kyc_id)
            if kyc_for_cap is not None:
                framework_ceiling = deterministic_ceiling(kyc_for_cap["payload"])["cap_profile"]
                if profile_exceeds(approved_profile, framework_ceiling):
                    if not req.framework_override_acknowledged:
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                f"El perfil aprobado ({approved_profile!r}) supera el tope de "
                                f"capacidad del marco determinístico ({framework_ceiling!r}): el "
                                "cliente asumiría más riesgo del que su situación financiera "
                                "soporta. Para aprobarlo igualmente, reenviar con "
                                "framework_override_acknowledged=true y una justificación en "
                                "rationale."
                            ),
                        )
                    framework_override = True

        # ── 6. soft FK lookup advisor_id ──────────────────────────────────
        advisor_id_for_row: str | None = None
        if adv_repo.get(advisor.advisor_id) is not None:
            advisor_id_for_row = advisor.advisor_id

        # ── 7. persistir approval ─────────────────────────────────────────
        is_current_flag = req.decision != "reject"
        try:
            approval_data = approval_repo.create(
                case_id=case_id,
                ai_profile_analysis_id=(
                    analysis_data["analysis_id"] if analysis_data is not None else None
                ),
                kyc_submission_id=kyc_id,
                advisor_id=advisor_id_for_row,
                proposed_profile=proposed_profile,
                decision=req.decision,
                approved_profile=approved_profile,
                rationale=req.rationale,
                source=req.source,
                is_current=is_current_flag,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        # ── 8. mantener is_current consistente + current_approved_profile_id
        if req.decision in ("approve", "modify"):
            approval_repo.mark_previous_not_current(
                case_id, exclude_id=approval_data["approval_id"]
            )
            try:
                case_repo.update_current_approved_profile(
                    case_id, approval_data["approval_id"]
                )
            except EntityNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        # reject: NO toca current_approved_profile_id; is_current ya quedó 0.

        # ── 9. AuditEvent ─────────────────────────────────────────────────
        event_type = _PROFILE_APPROVAL_EVENT_BY_DECISION[req.decision]
        try:
            audit_repo.append(
                case_id=case_id,
                event_type=event_type,
                actor_advisor_id=advisor_id_for_row,
                actor_role=_pick_actor_role(advisor.roles),
                payload={
                    "case_id":                case_id,
                    "approval_id":            approval_data["approval_id"],
                    "ai_profile_analysis_id": approval_data["ai_profile_analysis_id"],
                    "kyc_submission_id":      approval_data["kyc_submission_id"],
                    "proposed_profile":       approval_data["proposed_profile"],
                    "decision":               approval_data["decision"],
                    "approved_profile":       approval_data["approved_profile"],
                    "advisor_id":             approval_data["advisor_id"],
                    "framework_ceiling_profile": framework_ceiling,
                    "framework_override":        framework_override,
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Approval {approval_data['approval_id']!r} was persisted "
                    f"but the audit event failed: {exc}"
                ),
            ) from exc

    return CaseAdvisorProfileApprovalResponse(
        **approval_data,
        framework_override=framework_override,
        framework_ceiling_profile=framework_ceiling,
    )


@app.get(
    "/cases/{case_id}/profile-approval",
    response_model=CaseAdvisorProfileApprovalListResponse,
)
def list_case_profile_approvals(
    case_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> CaseAdvisorProfileApprovalListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        case_row = SQLiteAdvisoryCaseRepository(store).get(case_id)
        if case_row is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        data = SQLiteAdvisorProfileApprovalCaseRepository(store).list_by_case(
            case_id
        )
    return CaseAdvisorProfileApprovalListResponse(
        approvals=[CaseAdvisorProfileApprovalResponse(**d) for d in data],
        count=len(data),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — CaseInvestmentPreferences endpoints
#
# RBAC:
#   POST /cases/{case_id}/investment-preferences  → advisor, admin
#   GET  /cases/{case_id}/investment-preferences  → admin, advisor, compliance, viewer
#
# Política de fuente:
#   - solo structured_preferences  → source="manual" (a menos que se override), no IA.
#   - solo natural_language_preferences  → llamada al extractor IA; AIRequestLog
#     se persiste con case_id; ai_request_log_id queda vinculado.
#   - ambos                          → structured es fuente de verdad; texto se
#     guarda como contexto; NO se llama a IA.
#
# `is_current` mantenido por el endpoint vía mark_previous_not_current.
# ─────────────────────────────────────────────────────────────────────────────


def _convert_ai_preferences_to_structured(ai_result: dict[str, Any]) -> dict[str, Any]:
    """
    Convierte el output del extractor IA al dict que entiende PreferenceFilterEngine.

    Filtra a las keys que el engine procesa (mismas que `_AI_FILTER_PREFERENCE_KEYS`)
    para no inyectar metadata IA (confidence, advisor_notes, etc.) en las
    preferences persistidas.
    """
    return {k: v for k, v in ai_result.items() if k in _AI_FILTER_PREFERENCE_KEYS}


@app.post(
    "/cases/{case_id}/investment-preferences",
    response_model=CaseInvestmentPreferenceResponse,
    status_code=201,
)
def create_case_investment_preference(
    case_id: str,
    req: CaseInvestmentPreferenceCreateRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> CaseInvestmentPreferenceResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 1. Validaciones de case ─────────────────────────────────────────────
    with SQLiteEntityStore(db_path) as store:
        case_repo = SQLiteAdvisoryCaseRepository(store)
        adv_repo = SQLiteAdvisorRepository(store)

        case_data = case_repo.get(case_id)
        if case_data is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )

        if case_data["status"] == "CLOSED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} is CLOSED; investment preferences are "
                    "not accepted after case closure."
                ),
            )

        created_by_advisor_id: str | None = None
        if adv_repo.get(advisor.advisor_id) is not None:
            created_by_advisor_id = advisor.advisor_id

    # ── 2. Resolver structured_preferences (con o sin IA) ──────────────────
    structured: dict[str, Any]
    ai_request_log_id: str | None = None
    final_source = req.source

    if req.structured_preferences is not None:
        # Fuente de verdad: structured. NO se llama a IA aunque venga NLP.
        structured = dict(req.structured_preferences)
    else:
        # Solo NLP: llamar al extractor IA.
        # (el schema garantiza que al menos uno de los dos viene)
        try:
            ai_client = _get_openai_profile_client()
        except (ValueError, ImportError) as err:
            raise HTTPException(
                status_code=400,
                detail=(
                    "OPENAI_API_KEY is not configured. "
                    "Set the environment variable and retry."
                ),
            ) from err

        model_name = _resolve_ai_model_name(ai_client)
        endpoint_str = f"/cases/{case_id}/investment-preferences"
        ai_input_payload: dict[str, Any] = {
            "client_id":                    case_id,  # opaque id para la IA
            "case_id":                      case_id,
            "natural_language_preferences": req.natural_language_preferences,
        }

        _start = time.perf_counter()
        try:
            ai_result = ai_client.extract_investment_preferences(ai_input_payload)
        except ValueError as exc:
            _persist_ai_request_log(
                endpoint=endpoint_str,
                model=model_name,
                prompt_version=_AI_LOG_PROMPT_CASE_INVESTMENT_PREFS,
                input_payload=ai_input_payload,
                validation_status="api_error",
                db_path=db_path,
                case_id=case_id,
                requested_by_advisor_id=created_by_advisor_id,
                latency_ms=int((time.perf_counter() - _start) * 1000),
                error_message=str(exc),
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "AI investment preferences extraction failed. "
                    "The AI returned an invalid response."
                ),
            ) from exc
        except Exception as exc:
            _persist_ai_request_log(
                endpoint=endpoint_str,
                model=model_name,
                prompt_version=_AI_LOG_PROMPT_CASE_INVESTMENT_PREFS,
                input_payload=ai_input_payload,
                validation_status="api_error",
                db_path=db_path,
                case_id=case_id,
                requested_by_advisor_id=created_by_advisor_id,
                latency_ms=int((time.perf_counter() - _start) * 1000),
                error_message=str(exc),
            )
            raise HTTPException(
                status_code=502,
                detail="AI investment preferences extraction failed due to an unexpected error.",
            ) from exc

        latency_ms = int((time.perf_counter() - _start) * 1000)
        ai_request_log_id = _persist_ai_request_log(
            endpoint=endpoint_str,
            model=model_name,
            prompt_version=_AI_LOG_PROMPT_CASE_INVESTMENT_PREFS,
            input_payload=ai_input_payload,
            validation_status="parsed_ok",
            db_path=db_path,
            case_id=case_id,
            requested_by_advisor_id=created_by_advisor_id,
            raw_response=dict(ai_result) if isinstance(ai_result, dict) else None,
            latency_ms=latency_ms,
        )

        structured = _convert_ai_preferences_to_structured(
            dict(ai_result) if isinstance(ai_result, dict) else {}
        )
        # Si el caller dejó source="manual" pero usó NLP, marcarlo como "ai".
        if req.source == "manual":
            final_source = "ai"

    # ── 3. Persistir preference + mark previous + AuditEvent ───────────────
    with SQLiteEntityStore(db_path) as store:
        pref_repo = SQLiteCaseInvestmentPreferenceRepository(store)
        audit_repo = SQLiteAuditEventRepository(store)

        try:
            pref_data = pref_repo.create(
                case_id=case_id,
                source=final_source,
                structured_preferences=structured,
                natural_language_preferences=req.natural_language_preferences,
                ai_request_log_id=ai_request_log_id,
                created_by_advisor_id=created_by_advisor_id,
                is_current=True,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        pref_repo.mark_previous_not_current(
            case_id, exclude_id=pref_data["preference_id"]
        )

        try:
            audit_repo.append(
                case_id=case_id,
                event_type="investment_preferences_recorded",
                actor_advisor_id=created_by_advisor_id,
                actor_role=_pick_actor_role(advisor.roles),
                payload={
                    "case_id":               case_id,
                    "preference_id":         pref_data["preference_id"],
                    "source":                pref_data["source"],
                    "ai_request_log_id":     pref_data["ai_request_log_id"],
                    "created_by_advisor_id": pref_data["created_by_advisor_id"],
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Preference {pref_data['preference_id']!r} was persisted "
                    f"but the audit event failed: {exc}"
                ),
            ) from exc

    return CaseInvestmentPreferenceResponse(**pref_data)


@app.get(
    "/cases/{case_id}/investment-preferences",
    response_model=CaseInvestmentPreferenceListResponse,
)
def list_case_investment_preferences(
    case_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> CaseInvestmentPreferenceListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        if SQLiteAdvisoryCaseRepository(store).get(case_id) is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        data = SQLiteCaseInvestmentPreferenceRepository(store).list_by_case(case_id)
    return CaseInvestmentPreferenceListResponse(
        preferences=[CaseInvestmentPreferenceResponse(**d) for d in data],
        count=len(data),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — CaseUniverseFilterRun endpoints
#
# RBAC:
#   POST /cases/{case_id}/universe-filter  → advisor, admin
#   GET  /cases/{case_id}/universe-filter  → admin, advisor, compliance, viewer
#
# Comportamiento POST:
#   - Resuelve preference: explícita (debe ser del case) o current del case.
#   - Carga universo CSV (mismo fixture que los endpoints legacy).
#   - Aplica PreferenceFilterEngine.
#   - Serializa instruments/exclusions y persiste el snapshot completo.
#   - mark_previous_not_current.
#   - Emite AuditEvent "universe_filtered".
# ─────────────────────────────────────────────────────────────────────────────


def _serialize_instrument_for_filter_run(inst: Any) -> dict[str, Any]:
    """Mismo shape que `InstrumentResponse` para coherencia con endpoints legacy."""
    return {
        "ticker":             inst.ticker,
        "name":               inst.name,
        "issuer":             inst.issuer,
        "instrument_type":    inst.instrument_type.value,
        "asset_class":        inst.asset_class.value,
        "currency":           inst.currency,
        "country":            inst.country,
        "sector":             inst.sector,
        "available_entities": list(inst.available_entities),
        "hard_dollar":        inst.hard_dollar,
        "maturity_date":      inst.maturity_date,
        "coupon_rate":        inst.coupon_rate,
        "ytm":                inst.ytm,
        "duration":           inst.duration,
        "liquidity_score":    inst.liquidity_score,
        "min_piece":          inst.min_piece,
        "rating":             inst.rating,
        "notes":              list(inst.notes),
    }


@app.post(
    "/cases/{case_id}/universe-filter",
    response_model=CaseUniverseFilterRunResponse,
    status_code=201,
)
def create_case_universe_filter_run(
    case_id: str,
    req: CaseUniverseFilterRunCreateRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> CaseUniverseFilterRunResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 1. Validaciones de case + resolución de preference ─────────────────
    with SQLiteEntityStore(db_path) as store:
        case_repo = SQLiteAdvisoryCaseRepository(store)
        pref_repo = SQLiteCaseInvestmentPreferenceRepository(store)
        adv_repo = SQLiteAdvisorRepository(store)

        case_data = case_repo.get(case_id)
        if case_data is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        if case_data["status"] == "CLOSED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} is CLOSED; universe filter runs are "
                    "not accepted after case closure."
                ),
            )

        preference_data: dict[str, Any] | None
        if req.preference_id is not None:
            preference_data = pref_repo.get(req.preference_id)
            if preference_data is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Investment preference not found: {req.preference_id!r}",
                )
            if preference_data["case_id"] != case_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Investment preference {req.preference_id!r} belongs "
                        f"to case {preference_data['case_id']!r}, not "
                        f"{case_id!r}."
                    ),
                )
        else:
            preference_data = pref_repo.get_current_for_case(case_id)
            if preference_data is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Case {case_id!r} has no investment preferences. "
                        "POST to /cases/{case_id}/investment-preferences first."
                    ),
                )

        created_by_advisor_id: str | None = None
        if adv_repo.get(advisor.advisor_id) is not None:
            created_by_advisor_id = advisor.advisor_id

    # ── 2. Cargar universo CSV + aplicar filter engine ─────────────────────
    # Con RFA_LIVE_DATA usa el universo de tickers reales (resuelven live);
    # sin la env var, el fixture sintético (tests/offline deterministas).
    import os
    csv_path: Path = _INSTRUMENT_UNIVERSE_CSV
    if os.environ.get("RFA_LIVE_DATA") and _INSTRUMENT_UNIVERSE_CSV_LIVE.exists():
        csv_path = _INSTRUMENT_UNIVERSE_CSV_LIVE
    if not csv_path.exists():
        raise HTTPException(
            status_code=500,
            detail="Instrument universe fixture not found.",
        )
    try:
        universe = CSVInstrumentUniverseProvider(csv_path).load()
    except Exception as err:
        raise HTTPException(
            status_code=500,
            detail="Instrument universe fixture not found.",
        ) from err

    total_count = len(universe.instruments)

    # Filtrar la dict de preferencias a las keys que el engine entiende
    # (defensa contra structured_preferences con metadata extra).
    structured_prefs = dict(preference_data["structured_preferences"])
    filter_prefs = _convert_ai_preferences_to_structured(structured_prefs)

    try:
        filter_result = PreferenceFilterEngine().apply(universe, filter_prefs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    eligible_serialized = [
        _serialize_instrument_for_filter_run(inst)
        for inst in filter_result.eligible_universe.instruments
    ]
    exclusions_serialized = [
        {"ticker": exc.ticker, "reasons": list(exc.reasons)}
        for exc in filter_result.exclusions
    ]
    applied_filters = list(filter_result.applied_filters)
    warnings = list(filter_result.warnings)

    # ── 3. Persistir + mark previous + AuditEvent ──────────────────────────
    with SQLiteEntityStore(db_path) as store:
        runs_repo = SQLiteCaseUniverseFilterRunRepository(store)
        audit_repo = SQLiteAuditEventRepository(store)

        try:
            run_data = runs_repo.create(
                case_id=case_id,
                preference_id=preference_data["preference_id"],
                source_universe=req.source_universe.strip(),
                eligible_instruments=eligible_serialized,
                exclusions=exclusions_serialized,
                applied_filters=applied_filters,
                warnings=warnings,
                eligible_count=len(eligible_serialized),
                excluded_count=len(exclusions_serialized),
                total_count=total_count,
                created_by_advisor_id=created_by_advisor_id,
                is_current=True,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        runs_repo.mark_previous_not_current(
            case_id, exclude_id=run_data["filter_run_id"]
        )

        try:
            audit_repo.append(
                case_id=case_id,
                event_type="universe_filtered",
                actor_advisor_id=created_by_advisor_id,
                actor_role=_pick_actor_role(advisor.roles),
                payload={
                    "case_id":         case_id,
                    "filter_run_id":   run_data["filter_run_id"],
                    "preference_id":   run_data["preference_id"],
                    "eligible_count":  run_data["eligible_count"],
                    "excluded_count":  run_data["excluded_count"],
                    "total_count":     run_data["total_count"],
                    "source_universe": run_data["source_universe"],
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Filter run {run_data['filter_run_id']!r} was persisted "
                    f"but the audit event failed: {exc}"
                ),
            ) from exc

    return CaseUniverseFilterRunResponse(**run_data)


@app.get(
    "/cases/{case_id}/universe-filter",
    response_model=CaseUniverseFilterRunListResponse,
)
def list_case_universe_filter_runs(
    case_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> CaseUniverseFilterRunListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        if SQLiteAdvisoryCaseRepository(store).get(case_id) is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        data = SQLiteCaseUniverseFilterRunRepository(store).list_by_case(case_id)
    return CaseUniverseFilterRunListResponse(
        filter_runs=[CaseUniverseFilterRunResponse(**d) for d in data],
        count=len(data),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — CasePortfolioProposal endpoints
#
# RBAC:
#   POST /cases/{case_id}/portfolio-proposal  → advisor, admin
#   GET  /cases/{case_id}/portfolio-proposal  → admin, advisor, compliance, viewer
#
# Comportamiento POST:
#   - 404 si case no existe.
#   - 409 si case está CLOSED.
#   - 409 si no hay approved_profile (current o explícito) en el case.
#   - 409 si no hay universe filter run (current o explícito) en el case.
#   - 422 si filter_run_id o approved_profile_id explícitos pertenecen a otro case.
#   - Reconstruye FinancialInstrument desde filter_run.eligible_instruments
#     (snapshot trazable; no se re-carga CSV).
#   - Convierte a MarketDataSnapshot vía InstrumentMarketDataAdapter.
#   - Construye RiskBudget desde profile_name vía _build_live_risk_budget.
#   - Aplica thresholds (min snapshots, diversification capacity) → status:
#     blocked_insufficient_universe / blocked_insufficient_diversification_capacity.
#   - Genera candidatos con PortfolioGenerationCoordinator → status completed
#     o infeasible (ValueError del coordinator).
#   - Persiste proposal + mark_previous_not_current + AuditEvent
#     portfolio_proposal_generated.
#   - Devuelve 201 con la response completa (también para casos blocked /
#     infeasible — el proposal se persiste con el status correspondiente para
#     auditabilidad).
# ─────────────────────────────────────────────────────────────────────────────


def _reconstruct_instrument_from_dict(d: dict[str, Any]) -> Any:
    """
    Reconstruye un FinancialInstrument desde el dict persistido por
    case_universe_filter_runs.eligible_instruments. Preserva el snapshot:
    no depende del CSV ni de cambios posteriores en el universo.
    """
    from risk_first_advisory.universe_layer.instruments import (
        AssetClass,
        FinancialInstrument,
        InstrumentType,
    )

    return FinancialInstrument(
        ticker=d["ticker"],
        name=d["name"],
        issuer=d["issuer"],
        instrument_type=InstrumentType(d["instrument_type"]),
        asset_class=AssetClass(d["asset_class"]),
        currency=d["currency"],
        country=d["country"],
        sector=d["sector"],
        available_entities=list(d.get("available_entities", [])),
        hard_dollar=bool(d["hard_dollar"]),
        maturity_date=d.get("maturity_date"),
        coupon_rate=d.get("coupon_rate"),
        ytm=d.get("ytm"),
        duration=d.get("duration"),
        liquidity_score=float(d.get("liquidity_score", 0.0)),
        min_piece=d.get("min_piece"),
        rating=d.get("rating"),
        notes=list(d.get("notes", [])),
    )


def _apply_live_market_data(instruments: list[Any], adapter_snapshots: list[Any]) -> list[Any]:
    """
    Reemplaza los snapshots derivados del fixture por datos de mercado REALES
    (data912 / yfinance / Rava, normalizados a USD) cuando se pueden traer; si un
    ticker falla, conserva el snapshot del adapter. Preserva el orden original.

    Opt-in: el endpoint solo lo llama si RFA_LIVE_DATA está seteada. Sin la env var,
    el flujo sigue con el fixture (tests y smoke check deterministas).
    """
    from risk_first_advisory.data_layer.live_market_data import (
        LiveMarketDataProvider,
        instrument_type_to_source,
    )

    source_map: dict[str, str] = {}
    for inst in instruments:
        ticker = getattr(inst, "ticker", None)
        if not ticker:
            continue
        itype = getattr(inst, "instrument_type", None)
        itype_str = str(getattr(itype, "value", None) or itype or "")
        source_map[ticker] = instrument_type_to_source(
            itype_str, getattr(inst, "country", "") or ""
        )
    if not source_map:
        return adapter_snapshots

    # La clase de activo es autoridad del UNIVERSO (CSV), no del source del provider.
    # Sin esto, un ETF de bonos US (TLT/SHY, source=us) saldría como "equity" porque
    # el provider deriva la clase del source — rompiendo max_equity / suitability y
    # dejando sin renta fija de baja vol a los perfiles conservadores.
    import dataclasses
    declared_class: dict[str, str] = {}
    for inst in instruments:
        tk = getattr(inst, "ticker", None)
        ac = getattr(inst, "asset_class", None)
        ac_str = str(getattr(ac, "value", None) or ac or "")
        if tk and ac_str.upper() == "FIXED_INCOME":
            declared_class[tk] = "fixed_income"

    provider = LiveMarketDataProvider(source_map, period="3y")
    by_ticker = {s.ticker: s for s in adapter_snapshots}

    # Fetch en PARALELO: bajar el histórico es I/O puro (red data912/yfinance +
    # cache en disco POR-ticker, sin colisión entre archivos). Secuencial, ~100
    # instrumentos × ~1.5s = minutos; con un pool de threads baja a ~10s en frío
    # y es instantáneo con el cache tibio (fetch_series_cached, TTL 24h).
    from concurrent.futures import ThreadPoolExecutor
    tickers = list(source_map)
    max_workers = min(16, len(tickers)) or 1
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        live_snaps = list(pool.map(provider.get_snapshot, tickers))
    for ticker, live in zip(tickers, live_snaps, strict=True):
        if live is not None:
            forced = declared_class.get(ticker)
            if forced and getattr(live, "asset_class", None) != forced:
                live = dataclasses.replace(live, asset_class=forced)
            by_ticker[ticker] = live  # reemplaza el del fixture o AGREGA uno nuevo

    # Devolver un snapshot por instrumento del universo (no solo los que el
    # adapter cubrió: así los ETF/CEDEAR con data live también entran al optimizador).
    ordered: list[Any] = []
    seen: set[str] = set()
    for inst in instruments:
        tk = getattr(inst, "ticker", None)
        if tk and tk in by_ticker and tk not in seen:
            ordered.append(by_ticker[tk])
            seen.add(tk)
    for snap in adapter_snapshots:  # defensivo: cualquier resto no mapeado
        if snap.ticker not in seen:
            ordered.append(snap)
            seen.add(snap.ticker)
    return ordered


def _apply_live_joint_market_data(
    instruments: list[Any], adapter_snapshots: list[Any]
) -> tuple[list[Any], Any | None, list[str]]:
    """
    Estimación CONJUNTA sobre series reales: además de reemplazar μ/σ por datos
    live, estima la covarianza real con Ledoit-Wolf y μ con Black-Litterman
    sobre la matriz de retornos alineada (data_layer/estimation, portado de
    markowitz-optimizer). Devuelve (snapshots, covariance | None, warnings).

    - Los tickers estimados van PRIMERO y en el orden del estimador, así el
      filtro is_usable produce una lista alineada 1:1 con covariance.tickers.
    - Los no estimados (fetch fallido, historia corta, vol absurda) quedan como
      snapshots stale con la razón en notes: visibles pero fuera del optimizador.
      Mezclar μ/σ del fixture con una Σ real seria estadísticamente incoherente.
    - Si la estimación conjunta entera falla (sin red, < 2 series), degrada al
      reemplazo per-ticker de _apply_live_market_data con covarianza mock
      (covariance=None) y lo deja avisado en warnings.
    """
    import dataclasses

    from risk_first_advisory.data_layer.estimation import (
        EstimationError,
        estimate_joint_moments,
    )
    from risk_first_advisory.data_layer.live_market_data import (
        instrument_type_to_source,
    )
    from risk_first_advisory.data_layer.market_data import MarketDataSnapshot

    source_map: dict[str, str] = {}
    declared_class: dict[str, str] = {}
    for inst in instruments:
        ticker = getattr(inst, "ticker", None)
        if not ticker:
            continue
        itype = getattr(inst, "instrument_type", None)
        itype_str = str(getattr(itype, "value", None) or itype or "")
        source_map[ticker] = instrument_type_to_source(
            itype_str, getattr(inst, "country", "") or ""
        )
        ac = getattr(inst, "asset_class", None)
        ac_str = str(getattr(ac, "value", None) or ac or "")
        if ac_str.upper() == "FIXED_INCOME":
            declared_class[ticker] = "fixed_income"
    if not source_map:
        return adapter_snapshots, None, []

    try:
        est = estimate_joint_moments(source_map, period="3y")
    except EstimationError as exc:
        snaps = _apply_live_market_data(instruments, adapter_snapshots)
        return snaps, None, [
            f"live: estimación conjunta no disponible ({exc}); "
            "fallback per-ticker con correlaciones mock por asset_class."
        ]

    adjusted_notes: dict[str, list[str]] = {}
    for a in est.adjusted:
        adjusted_notes.setdefault(a["ticker"], []).append(a["note"])

    estimated: list[Any] = []
    for t in est.tickers:
        m = est.meta[t]
        asset_class = declared_class.get(t) or (
            "fixed_income" if m.get("kind") == "bond" else "equity"
        )
        estimated.append(MarketDataSnapshot(
            ticker=t,
            expected_return_annual=round(est.mu[t], 6),
            volatility_annual=round(est.vol[t], 6),
            liquidity_score=0.7,  # heurística neutra, igual que el provider per-ticker
            expense_ratio=0.0,
            duration=None,
            asset_class=asset_class,
            currency="USD",
            stale=False,
            missing_fields=["expense_ratio"],
            notes=[
                f"source={m.get('source')}",
                f"ccy_native={m.get('ccy_native')}",
                f"obs={m.get('obs')}",
                f"mu_hist={est.mu_hist[t]:.4f}",
                f"mu=black_litterman sigma=ledoit_wolf(lambda={est.shrinkage:.3f})",
                *adjusted_notes.get(t, []),
            ],
        ))

    dropped_reason = {d["ticker"]: d["reason"] for d in est.dropped}
    estimated_set = set(est.tickers)
    rest: list[Any] = []
    for snap in adapter_snapshots:
        if snap.ticker in estimated_set:
            continue
        reason = dropped_reason.get(snap.ticker, "sin serie live utilizable")
        rest.append(dataclasses.replace(
            snap,
            stale=True,
            notes=[*snap.notes, f"excluded_from_live_estimation: {reason}"],
        ))

    warnings = [
        f"live: {d['ticker']} excluido de la estimación — {d['reason']}"
        for d in est.dropped
    ]
    warnings.extend(
        f"live: {a['ticker']} serie ajustada — {a['note']}"
        for a in est.adjusted
    )
    warnings.append(
        f"live: μ=Black-Litterman, Σ=Ledoit-Wolf (λ={est.shrinkage:.3f}) "
        f"sobre {len(est.tickers)} series alineadas."
    )
    return estimated + rest, est.covariance, warnings


def _serialize_snapshot_for_proposal(snap: Any) -> dict[str, Any]:
    """Mismo shape que FilteredSnapshotResponse para coherencia con endpoints legacy."""
    return {
        "ticker":                 snap.ticker,
        "expected_return_annual": snap.expected_return_annual,
        "volatility_annual":      snap.volatility_annual,
        "duration":               snap.duration,
        "liquidity_score":        snap.liquidity_score,
        "notes":                  list(snap.notes),
    }


def _tradeoff_from_kyc_payload(kyc_payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Arma el dict `tradeoff` para `client_risk_number` desde los campos
    OPCIONALES de la pregunta de trade-off del KYC (Slice 4b,
    docs/RISK_NUMBER_DESIGN.md): certainty equivalent de una apuesta 50/50
    ganar/perder vs. un monto seguro indiferente (framing académico CRRA,
    docs/RISK_SCORING_THEORY.md §3 — NO el framing patentado de Nitrogen).

    La riqueza W es `liquid_net_worth` del MISMO KYC (I-015: no se pregunta
    de nuevo, campo estructurado ya existente). None si la pregunta no fue
    respondida (falta cualquiera de los tres campos) — `client_risk_number`
    sigue funcionando solo con willingness, como hoy.
    """
    gain = kyc_payload.get("tradeoff_gain_usd")
    loss = kyc_payload.get("tradeoff_loss_usd")
    certain = kyc_payload.get("tradeoff_certain_amount_usd")
    if gain is None or loss is None or certain is None:
        return None
    return {
        "wealth": kyc_payload.get("liquid_net_worth"),
        "gain": gain,
        "loss": loss,
        "certain_amount": certain,
    }


def _client_risk_number_tolerant(kyc_payload: dict[str, Any]) -> dict[str, Any]:
    """
    `client_risk_number(kyc_payload)` con el trade-off opcional armado desde
    el mismo KYC, tolerante SOLO a un trade-off inválido: una apuesta mal
    formada (p.ej. certain_amount fuera de (-loss, gain), o wealth <= 0) hace
    `ValueError` dentro de `crra_gamma_from_certainty_equivalent` — en ese
    caso se cae a willingness-only (tradeoff=None) en vez de romper el
    endpoint con un 500.

    NO tolera un KYC fundamentalmente impuntuable: si la vía willingness-only
    (`score_stated_profile`) tampoco puede puntuar el payload, la excepción se
    propaga — mismo comportamiento que `deterministic_assessment` /
    `capacity_gap_from_kyc`, que se llaman al lado sin envolver. Los callers
    que tratan el número del cliente como OPCIONAL (portfolio-proposal,
    reporte) envuelven esta llamada en su propio try/except → None; el de
    profile-analysis no, y falla junto con sus vecinos si el KYC no es
    puntuable (all-or-nothing, coherente).
    """
    from risk_first_advisory.ai_layer.risk_number import (
        client_risk_number as compute_client_risk_number,
    )

    tradeoff = _tradeoff_from_kyc_payload(kyc_payload)
    if tradeoff is not None:
        try:
            return compute_client_risk_number(kyc_payload, tradeoff=tradeoff)
        except (TypeError, ValueError):
            pass
    return compute_client_risk_number(kyc_payload)


def _compute_candidate_risk_number(
    portfolio: Any,
    expected_returns: dict[str, float] | None,
    cov_tickers: list[str] | None,
    cov_matrix: list[list[float]] | None,
    client_number: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Risk Number 0-100 de ESTA cartera candidata (desde sus pesos reales +
    retornos/covarianza ya estimados para la propuesta — Slice 2 del Risk
    Number) + alineación con el número del cliente, si está disponible.

    Puramente derivado de datos ya computados en este mismo request (no
    vuelve a llamar al optimizer ni a ningún proveedor de mercado) —
    consistente con I-013/I-020. Tolerante: si faltan datos de mercado para
    los tickers con peso, o si contienen valores no finitos (NaN/inf de un
    proveedor live degenerado), devuelve (None, None) en vez de romper la
    generación de la propuesta o de emitir un número confiadamente erróneo.

    La alineación es INFORMATIVA (conversación asesor↔cliente): el override
    formal lo gobiernan profile-approval y metadata.requires_advisor_override
    en la selección (I-018) — por eso NO expone ningún flag de override.
    `client_kyc_submission_id` registra qué KYC produjo el número del cliente.

    Returns (risk_number_dict | None, risk_alignment_dict | None).
    """
    if not expected_returns or not cov_tickers or not cov_matrix:
        return None, None
    from risk_first_advisory.ai_layer.risk_number import (
        align_numbers,
        portfolio_risk_number_from_weights,
    )
    try:
        rn = portfolio_risk_number_from_weights(
            weights=portfolio.weights,
            expected_returns=expected_returns,
            tickers=cov_tickers,
            covariance=cov_matrix,
        )
    except ValueError:
        return None, None

    alignment = None
    if client_number is not None:
        alignment = align_numbers(
            client_number=client_number["number"],
            capacity_ceiling_number=client_number["capacity_ceiling_number"],
            portfolio_number=rn["number"],
        )
        alignment["client_kyc_submission_id"] = client_number.get("kyc_submission_id")
    return rn, alignment


def _serialize_candidate_for_proposal(
    variant_name: str,
    portfolio: Any,
    meta: Any,
    instruments_by_ticker: dict[str, dict[str, Any]] | None = None,
    risk_budget: Any = None,
    expected_returns: dict[str, float] | None = None,
    cov_tickers: list[str] | None = None,
    cov_matrix: list[list[float]] | None = None,
    client_number: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Mismo shape que LivePortfolioCandidateResponse para coherencia con
    /ai/filtered-portfolio-demo. Pesos ordenados mayor→menor, solo > 1e-6.

    Phase 3.6 — composición visible:
        Además de `weights` (mantenido por compatibilidad), agrega
        `holdings` enriquecidas con metadata del instrumento (nombre,
        tipo, moneda, asset_class, sector, etc.), `holdings_count` y
        `total_weight`. Esto permite al frontend / reporte mostrar la
        composición real de cada cartera candidata sin que el visitante
        tenga que abrir Swagger.

        `instruments_by_ticker` se construye desde el snapshot del filter
        run (`filter_data["eligible_instruments"]`), keyed por ticker.
        Si un ticker del portfolio no aparece en el snapshot (caso edge),
        la holding se emite con metadata `None` pero conserva ticker/weight.

    Risk Number (Slice 2/3 — docs/RISK_NUMBER_DESIGN.md):
        `expected_returns`/`cov_tickers`/`cov_matrix` (de esta misma
        generación, ver paso 6 del endpoint) producen `risk_number`: el
        número 0-100 de ESTA cartera, misma escala que el del cliente.
        `client_number` (del KYC vigente del case, si existe) agrega
        `risk_alignment`: cómo se compara esta cartera contra el cliente y
        su techo de capacidad. Ambos quedan `None` si faltan datos —no
        bloquean la generación de la propuesta.
    """
    from risk_first_advisory.portfolio_layer.diversification import (
        assess_diversification,
    )

    sorted_weights = sorted(
        ((t, w) for t, w in portfolio.weights.items() if w > 1e-6),
        key=lambda kv: kv[1],
        reverse=True,
    )
    instruments_by_ticker = instruments_by_ticker or {}
    max_single_asset = getattr(risk_budget, "max_single_asset", None) if risk_budget else None

    holdings: list[dict[str, Any]] = []
    total_weight = 0.0
    for ticker, weight in sorted_weights:
        total_weight += float(weight)
        instr = instruments_by_ticker.get(ticker) or {}
        risk_flags: list[str] = []
        if isinstance(max_single_asset, (int, float)) and max_single_asset > 0 and float(weight) > float(max_single_asset) + 1e-9:
            risk_flags.append("exceeds_max_single_asset")
        # rationale humano-legible derivado de metadata del instrumento
        rationale_bits: list[str] = []
        if instr.get("asset_class"):
            rationale_bits.append(str(instr["asset_class"]))
        if instr.get("instrument_type"):
            rationale_bits.append(str(instr["instrument_type"]))
        if instr.get("currency"):
            rationale_bits.append(str(instr["currency"]))
        rationale = " · ".join(rationale_bits) if rationale_bits else None
        # Reason codes derivadas de la composición del instrumento (informativo,
        # NO viene del optimizador per-instrument).
        inclusion_reason_codes: list[str] = []
        if instr.get("asset_class"):
            inclusion_reason_codes.append(f"asset_class:{instr['asset_class']}")
        if instr.get("hard_dollar"):
            inclusion_reason_codes.append("hard_dollar")
        holdings.append({
            "instrument_id":          ticker,
            "ticker":                 ticker,
            "name":                   instr.get("name"),
            "issuer":                 instr.get("issuer"),
            "instrument_type":        instr.get("instrument_type"),
            "asset_class":            instr.get("asset_class"),
            "currency":               instr.get("currency"),
            "sector":                 instr.get("sector"),
            "country":                instr.get("country"),
            "weight":                 float(weight),
            "weight_percent":         round(float(weight) * 100.0, 4),
            "rationale":              rationale,
            "inclusion_reason_codes": inclusion_reason_codes,
            "risk_flags":             risk_flags,
            "suitability_status":     None,  # TODO Fase 4: suitability per-instrument
        })

    # Risk Number de esta cartera (None si faltan retornos/covarianza para los
    # tickers con peso) + alineación con el cliente (None sin KYC del case).
    risk_number, risk_alignment = _compute_candidate_risk_number(
        portfolio, expected_returns, cov_tickers, cov_matrix, client_number
    )

    return {
        "variant":                variant_name,
        "objective":              portfolio.objective.value,
        "expected_return_annual": portfolio.expected_return_annual,
        "volatility_annual":      portfolio.volatility_annual,
        "risk_score":             portfolio.risk_score,
        "constraints_satisfied":  portfolio.constraints_satisfied,
        "reason_codes":           list(portfolio.reason_codes),
        "notes":                  list(portfolio.notes),
        "metadata": {
            "risk_budget_exceeded":      meta.risk_budget_exceeded if meta else False,
            "requires_advisor_override": meta.requires_advisor_override if meta else False,
            "exceeded_constraints":      list(meta.exceeded_constraints) if meta else [],
            "reason_codes":              list(meta.reason_codes) if meta else [],
            "notes":                     list(meta.notes) if meta else [],
        },
        # `weights` se mantiene para no romper consumidores existentes (UI legacy,
        # reportes anteriores, smoke checks).
        "weights": [{"ticker": t, "weight": w} for t, w in sorted_weights],
        # `holdings` enriquece la composición con metadata visible al asesor.
        "holdings":       holdings,
        "holdings_count": len(holdings),
        "total_weight":   round(total_weight, 6),
        # Descomposición de diversificación (pura, sin red/LLM): concentración,
        # repartos por eje y score, para comparar variantes y explicar el porqué.
        "diversification": assess_diversification(holdings),
        "risk_number":     risk_number,
        "risk_alignment":  risk_alignment,
    }


@app.post(
    "/cases/{case_id}/portfolio-proposal",
    response_model=CasePortfolioProposalResponse,
    status_code=201,
)
def create_case_portfolio_proposal(
    case_id: str,
    req: CasePortfolioProposalCreateRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> CasePortfolioProposalResponse:
    import math

    from risk_first_advisory.data_layer.covariance import CovarianceEngine
    from risk_first_advisory.data_layer.instrument_market_data import (
        InstrumentMarketDataAdapter,
    )
    from risk_first_advisory.data_layer.return_estimator import ReturnEstimator
    from risk_first_advisory.portfolio_layer.generation import (
        PortfolioGenerationCoordinator,
        PortfolioGenerationInfeasibleError,
        PortfolioVariant,
    )
    from risk_first_advisory.rules_layer.risk_budget_builder import VALID_PROFILES

    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 1. Validaciones contra la DB ─────────────────────────────────────────
    with SQLiteEntityStore(db_path) as store:
        case_repo = SQLiteAdvisoryCaseRepository(store)
        filter_repo = SQLiteCaseUniverseFilterRunRepository(store)
        approval_repo = SQLiteAdvisorProfileApprovalCaseRepository(store)
        adv_repo = SQLiteAdvisorRepository(store)

        case_data = case_repo.get(case_id)
        if case_data is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        if case_data["status"] == "CLOSED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} is CLOSED; portfolio proposals are "
                    "not accepted after case closure."
                ),
            )

        # Resolver approved profile.
        approval_data: dict[str, Any] | None
        if req.approved_profile_id is not None:
            approval_data = approval_repo.get(req.approved_profile_id)
            if approval_data is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Profile approval not found: {req.approved_profile_id!r}"
                    ),
                )
            if approval_data["case_id"] != case_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Profile approval {req.approved_profile_id!r} belongs "
                        f"to case {approval_data['case_id']!r}, not {case_id!r}."
                    ),
                )
        else:
            current_id = case_data["current_approved_profile_id"]
            if current_id is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Case {case_id!r} has no approved profile. "
                        "POST a profile-approval first."
                    ),
                )
            approval_data = approval_repo.get(current_id)
            if approval_data is None:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Case {case_id!r} current_approved_profile_id "
                        f"{current_id!r} not found in advisor_profile_approvals."
                    ),
                )

        # profile_name: derivar de approved_profile (preferencia) o
        # proposed_profile como fallback.
        profile_name = approval_data.get("approved_profile") or approval_data.get(
            "proposed_profile"
        )
        if not isinstance(profile_name, str) or profile_name not in VALID_PROFILES:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Approved profile {profile_name!r} is not a valid "
                    f"portfolio profile. Valid: {sorted(VALID_PROFILES)}."
                ),
            )

        # Resolver filter run.
        filter_data: dict[str, Any] | None
        if req.filter_run_id is not None:
            filter_data = filter_repo.get(req.filter_run_id)
            if filter_data is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Universe filter run not found: {req.filter_run_id!r}",
                )
            if filter_data["case_id"] != case_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Universe filter run {req.filter_run_id!r} belongs to "
                        f"case {filter_data['case_id']!r}, not {case_id!r}."
                    ),
                )
        else:
            filter_data = filter_repo.get_current_for_case(case_id)
            if filter_data is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Case {case_id!r} has no universe filter run. "
                        "POST a universe-filter first."
                    ),
                )

        created_by_advisor_id: str | None = None
        if adv_repo.get(advisor.advisor_id) is not None:
            created_by_advisor_id = advisor.advisor_id

        # ── 1b. KYC que respalda el Risk Number del cliente ─────────────────
        # Se prefiere el KYC registrado por la APROBACIÓN usada para el budget
        # sobre el vigente del case, para que el número del cliente y el budget
        # describan la misma decisión (un KYC re-enviado después de aprobar no
        # cambia en silencio contra qué se alinean los candidatos). El id usado
        # queda registrado por candidato (risk_alignment.client_kyc_submission_id).
        rn_kyc_submission_id: str | None = (
            approval_data.get("kyc_submission_id")
            or case_data.get("current_kyc_submission_id")
        )
        rn_kyc_payload: dict[str, Any] | None = None
        if rn_kyc_submission_id is not None:
            kyc_row = SQLiteKYCSubmissionRepository(store).get(rn_kyc_submission_id)
            payload_raw = (kyc_row or {}).get("payload")
            if isinstance(payload_raw, dict):
                rn_kyc_payload = payload_raw

    # ── 2. Reconstruir instrumentos desde el snapshot del filter run ────────
    eligible_dicts = filter_data["eligible_instruments"]
    eligible_instruments = [_reconstruct_instrument_from_dict(d) for d in eligible_dicts]

    # ── 3. Convertir a MarketDataSnapshot ───────────────────────────────────
    adapter = InstrumentMarketDataAdapter()
    all_snapshots = adapter.to_many(eligible_instruments)

    # ── 3b. Data de mercado REAL (opt-in via RFA_LIVE_DATA) ─────────────────
    # Estimación CONJUNTA sobre series reales: μ Black-Litterman + Σ Ledoit-Wolf
    # (correlaciones reales). Sin la env var, sigue el fixture con la covarianza
    # mock por asset_class → tests y smoke check deterministas.
    import os
    live_covariance: Any | None = None
    live_warnings: list[str] = []
    if os.environ.get("RFA_LIVE_DATA"):
        all_snapshots, live_covariance, live_warnings = _apply_live_joint_market_data(
            eligible_instruments, all_snapshots
        )

    usable_snapshots = [s for s in all_snapshots if s.is_usable]
    snapshots_serialized = [_serialize_snapshot_for_proposal(s) for s in all_snapshots]

    # ── 4. RiskBudget ───────────────────────────────────────────────────────
    risk_budget = _build_live_risk_budget(profile_name)
    risk_budget_dict = risk_budget.to_dict()

    # ── 5. Threshold blocks ─────────────────────────────────────────────────
    def _persist_and_return(
        status: str, candidates: list[dict[str, Any]], warnings: list[str]
    ) -> CasePortfolioProposalResponse:
        with SQLiteEntityStore(db_path) as store:
            proposal_repo = SQLiteCasePortfolioProposalRepository(store)
            audit_repo = SQLiteAuditEventRepository(store)
            try:
                proposal_data = proposal_repo.create(
                    case_id=case_id,
                    filter_run_id=filter_data["filter_run_id"],
                    approved_profile_id=approval_data["approval_id"],
                    profile_name=profile_name,
                    status=status,
                    risk_budget=risk_budget_dict,
                    snapshots=snapshots_serialized,
                    candidates=candidates,
                    warnings=warnings,
                    created_by_advisor_id=created_by_advisor_id,
                    is_current=True,
                )
            except EntityConflictError as exc:
                detail = str(exc)
                status_code = 409 if "UNIQUE constraint" in detail else 422
                raise HTTPException(status_code=status_code, detail=detail) from exc

            proposal_repo.mark_previous_not_current(
                case_id, exclude_id=proposal_data["proposal_id"]
            )

            try:
                audit_repo.append(
                    case_id=case_id,
                    event_type="portfolio_proposal_generated",
                    actor_advisor_id=created_by_advisor_id,
                    actor_role=_pick_actor_role(advisor.roles),
                    payload={
                        "case_id":             case_id,
                        "proposal_id":         proposal_data["proposal_id"],
                        "filter_run_id":       proposal_data["filter_run_id"],
                        "approved_profile_id": proposal_data["approved_profile_id"],
                        "profile_name":        proposal_data["profile_name"],
                        "candidate_count":     len(proposal_data["candidates"]),
                        "status":              proposal_data["status"],
                    },
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Proposal {proposal_data['proposal_id']!r} was persisted "
                        f"but the audit event failed: {exc}"
                    ),
                ) from exc

        # Encuadre A/B (dentro de capacidad vs requiere override) + explicación
        # por opción. Derivado de los candidatos persistidos; no se persiste.
        from risk_first_advisory.portfolio_layer.option_framing import (
            frame_portfolio_options,
        )
        framing = frame_portfolio_options(proposal_data.get("candidates") or [])
        return CasePortfolioProposalResponse(**proposal_data, options_framing=framing)

    if len(usable_snapshots) < 3:
        return _persist_and_return(
            status="blocked_insufficient_universe",
            candidates=[],
            warnings=live_warnings + [
                f"Only {len(usable_snapshots)} usable snapshot(s) for filtered universe; need at least 3."
            ],
        )

    msa = risk_budget.max_single_asset
    if msa <= 0.0:
        return _persist_and_return(
            status="infeasible",
            candidates=[],
            warnings=live_warnings + ["RiskBudget invalid: max_single_asset must be > 0."],
        )

    required_min = math.ceil(1.0 / msa)
    if len(usable_snapshots) < required_min:
        return _persist_and_return(
            status="blocked_insufficient_diversification_capacity",
            candidates=[],
            warnings=live_warnings + [
                f"Only {len(usable_snapshots)} usable snapshot(s) for profile "
                f"{profile_name!r} (max_single_asset={msa:.0%}); need at least "
                f"{required_min} instruments."
            ],
        )

    # ── 6. Estimar retornos / covarianzas ───────────────────────────────────
    # Con estimación conjunta live: Σ = Ledoit-Wolf real, alineada 1:1 con los
    # usables (los estimados van primero y el resto quedó stale). Si el orden
    # no coincidiera (defensivo), se degrada a la covarianza mock avisando.
    return_estimates = ReturnEstimator().estimate_many(usable_snapshots)
    if live_covariance is not None and (
        [s.ticker for s in usable_snapshots] == list(live_covariance.tickers)
    ):
        covariance_matrix = live_covariance
    else:
        if live_covariance is not None:
            live_warnings.append(
                "live: covarianza conjunta desalineada con los snapshots usables; "
                "se usa la covarianza mock por asset_class."
            )
        covariance_matrix = CovarianceEngine().build(usable_snapshots)

    # ── 6b. Risk Number: datos planos para el número de cartera + cliente ───
    # docs/RISK_NUMBER_DESIGN.md (Slice 3). Puramente derivado de lo estimado
    # arriba (nada de red/optimizer adicional) + el KYC de la aprobación,
    # cargado en el paso 1b sin abrir otra conexión. Tolerante: sin KYC o con
    # un payload que el motor no pueda puntuar (rows legacy pre-tipado), el
    # número queda None por candidato sin bloquear la propuesta.
    expected_returns_by_ticker = {
        e.ticker: e.adjusted_expected_return_annual for e in return_estimates
    }
    client_number: dict[str, Any] | None = None
    if rn_kyc_payload is not None:
        try:
            client_number = _client_risk_number_tolerant(rn_kyc_payload)
        except (TypeError, ValueError):
            client_number = None
        else:
            # Trazabilidad (audit): qué KYC produjo el número del cliente.
            client_number["kyc_submission_id"] = rn_kyc_submission_id

    # ── 7. Generar candidatos ───────────────────────────────────────────────
    try:
        candidate_set = PortfolioGenerationCoordinator().generate(
            client_id=case_id,  # opaque id para el coordinator
            approved_profile_name=profile_name,
            return_estimates=return_estimates,
            covariance_matrix=covariance_matrix,
            risk_budget=risk_budget,
        )
    except PortfolioGenerationInfeasibleError as exc:
        # Diagnóstico completo: qué pre-check falló en cada variante y qué
        # sugiere el feasibility checker — el asesor sabe qué tocar.
        return _persist_and_return(
            status="infeasible",
            candidates=[],
            warnings=(
                live_warnings
                + [f"PortfolioGenerationCoordinator failed: {exc}"]
                + [f"reason_code: {rc}" for rc in dict.fromkeys(exc.reason_codes)]
                + list(exc.notes)
            ),
        )
    except ValueError as exc:
        return _persist_and_return(
            status="infeasible",
            candidates=[],
            warnings=live_warnings + [f"PortfolioGenerationCoordinator failed: {exc}"],
        )

    # ── 8. Serializar candidatos ────────────────────────────────────────────
    _variant_order = [
        PortfolioVariant.DEFENSIVE,
        PortfolioVariant.BALANCED,
        PortfolioVariant.GROWTH,
    ]
    # Lookup ticker → instrument metadata desde el snapshot del filter run, así
    # las holdings serializadas exponen nombre / tipo / moneda / asset_class
    # sin que el frontend tenga que re-cruzar.
    instruments_by_ticker: dict[str, dict[str, Any]] = {
        d["ticker"]: d for d in eligible_dicts if isinstance(d, dict) and "ticker" in d
    }
    candidates_serialized: list[dict[str, Any]] = []
    for variant in _variant_order:
        if variant not in candidate_set.candidates:
            continue
        portfolio = candidate_set.candidates[variant]
        meta = candidate_set.metadata.get(variant)
        candidates_serialized.append(
            _serialize_candidate_for_proposal(
                variant.value, portfolio, meta,
                instruments_by_ticker=instruments_by_ticker,
                risk_budget=risk_budget,
                expected_returns=expected_returns_by_ticker,
                cov_tickers=covariance_matrix.tickers,
                cov_matrix=covariance_matrix.covariance,
                client_number=client_number,
            )
        )

    # Diagnóstico de variantes omitidas (infactibilidad PARCIAL): si alguna
    # variante quedó afuera por pre-check, sus notas también son accionables.
    return _persist_and_return(
        status="completed",
        candidates=candidates_serialized,
        warnings=live_warnings + list(candidate_set.notes),
    )


@app.get(
    "/cases/{case_id}/portfolio-proposal",
    response_model=CasePortfolioProposalListResponse,
)
def list_case_portfolio_proposals(
    case_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> CasePortfolioProposalListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        if SQLiteAdvisoryCaseRepository(store).get(case_id) is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        data = SQLiteCasePortfolioProposalRepository(store).list_by_case(case_id)
    return CasePortfolioProposalListResponse(
        proposals=[CasePortfolioProposalResponse(**d) for d in data],
        count=len(data),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — CaseOverrideApproval endpoints
#
# RBAC:
#   POST /cases/{case_id}/override-approval  → advisor, admin
#   GET  /cases/{case_id}/override-approval  → admin, advisor, compliance, viewer
#
# Comportamiento POST:
#   - 404 si case no existe.
#   - 409 si case está CLOSED.
#   - Resuelve proposal_id explícito (debe pertenecer al case) o current.
#   - 409 si no hay proposal en el case.
#   - 409 si proposal.status != "completed" (override sin candidates no aplica).
#   - 422 si candidate_variant no está en proposal.candidates.
#   - 422 si el candidate NO requiere override (metadata.requires_advisor_override=False).
#   - Persiste override approval + mark_previous_not_current (a nivel case).
#   - AuditEvent: approve → advisor_override_approved; reject → advisor_override_rejected.
# ─────────────────────────────────────────────────────────────────────────────


_OVERRIDE_EVENT_BY_DECISION: dict[str, str] = {
    "approve": "advisor_override_approved",
    "reject":  "advisor_override_rejected",
}


def _candidate_requires_override(candidate: dict[str, Any]) -> bool:
    """
    Inspecciona el dict de un candidate (mismo shape que el persistido en
    case_portfolio_proposals.candidates_json) para determinar si requiere
    advisor override.

    Política: confiar en metadata.requires_advisor_override (poblado por
    `_serialize_candidate_for_proposal` desde meta.requires_advisor_override
    del coordinator).
    """
    if not isinstance(candidate, dict):
        return False
    meta = candidate.get("metadata")
    if isinstance(meta, dict):
        return bool(meta.get("requires_advisor_override", False))
    return False


@app.post(
    "/cases/{case_id}/override-approval",
    response_model=CaseOverrideApprovalResponse,
    status_code=201,
)
def create_case_override_approval(
    case_id: str,
    req: CaseOverrideApprovalCreateRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> CaseOverrideApprovalResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with SQLiteEntityStore(db_path) as store:
        case_repo = SQLiteAdvisoryCaseRepository(store)
        proposal_repo = SQLiteCasePortfolioProposalRepository(store)
        adv_repo = SQLiteAdvisorRepository(store)
        override_repo = SQLiteCaseOverrideApprovalRepository(store)
        audit_repo = SQLiteAuditEventRepository(store)

        # ── 1. case ───────────────────────────────────────────────────────
        case_data = case_repo.get(case_id)
        if case_data is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        if case_data["status"] == "CLOSED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} is CLOSED; override approvals are not "
                    "accepted after case closure."
                ),
            )

        # ── 2. resolver proposal ──────────────────────────────────────────
        proposal_data: dict[str, Any] | None
        if req.proposal_id is not None:
            proposal_data = proposal_repo.get(req.proposal_id)
            if proposal_data is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Portfolio proposal not found: {req.proposal_id!r}",
                )
            if proposal_data["case_id"] != case_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Portfolio proposal {req.proposal_id!r} belongs to "
                        f"case {proposal_data['case_id']!r}, not {case_id!r}."
                    ),
                )
        else:
            proposal_data = proposal_repo.get_current_for_case(case_id)
            if proposal_data is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Case {case_id!r} has no portfolio proposal. "
                        "POST a portfolio-proposal first."
                    ),
                )

        # ── 3. proposal status debe ser completed ─────────────────────────
        if proposal_data["status"] != "completed":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Portfolio proposal {proposal_data['proposal_id']!r} has "
                    f"status {proposal_data['status']!r}; override approval "
                    "requires a completed proposal with candidates."
                ),
            )

        # ── 4. candidate_variant debe existir + requerir override ─────────
        candidates_by_variant: dict[str, dict[str, Any]] = {
            c["variant"]: c
            for c in proposal_data["candidates"]
            if isinstance(c, dict) and "variant" in c
        }
        if req.candidate_variant not in candidates_by_variant:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Candidate variant {req.candidate_variant!r} not found in "
                    f"proposal {proposal_data['proposal_id']!r}. Available: "
                    f"{sorted(candidates_by_variant.keys())}."
                ),
            )

        chosen_candidate = candidates_by_variant[req.candidate_variant]
        if not _candidate_requires_override(chosen_candidate):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Candidate {req.candidate_variant!r} does not require "
                    "advisor override (metadata.requires_advisor_override=False)."
                ),
            )

        # ── 5. soft FK lookup advisor_id ──────────────────────────────────
        advisor_id_for_row: str | None = None
        if adv_repo.get(advisor.advisor_id) is not None:
            advisor_id_for_row = advisor.advisor_id

        # ── 6. persistir override approval ────────────────────────────────
        try:
            override_data = override_repo.create(
                case_id=case_id,
                proposal_id=proposal_data["proposal_id"],
                candidate_variant=req.candidate_variant,
                decision=req.decision,
                rationale=req.rationale,
                source=req.source,
                reason_codes=list(req.reason_codes),
                exceeded_constraints=list(req.exceeded_constraints),
                advisor_id=advisor_id_for_row,
                is_current=True,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        # ── 7. mark previous not current (a nivel case) ───────────────────
        override_repo.mark_previous_not_current(
            case_id, exclude_id=override_data["override_approval_id"]
        )

        # ── 8. AuditEvent ─────────────────────────────────────────────────
        event_type = _OVERRIDE_EVENT_BY_DECISION[req.decision]
        try:
            audit_repo.append(
                case_id=case_id,
                event_type=event_type,
                actor_advisor_id=advisor_id_for_row,
                actor_role=_pick_actor_role(advisor.roles),
                payload={
                    "case_id":              case_id,
                    "override_approval_id": override_data["override_approval_id"],
                    "proposal_id":          override_data["proposal_id"],
                    "candidate_variant":    override_data["candidate_variant"],
                    "decision":             override_data["decision"],
                    "advisor_id":           override_data["advisor_id"],
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Override approval {override_data['override_approval_id']!r} "
                    f"was persisted but the audit event failed: {exc}"
                ),
            ) from exc

    return CaseOverrideApprovalResponse(**override_data)


@app.get(
    "/cases/{case_id}/override-approval",
    response_model=CaseOverrideApprovalListResponse,
)
def list_case_override_approvals(
    case_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> CaseOverrideApprovalListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        if SQLiteAdvisoryCaseRepository(store).get(case_id) is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        data = SQLiteCaseOverrideApprovalRepository(store).list_by_case(case_id)
    return CaseOverrideApprovalListResponse(
        override_approvals=[CaseOverrideApprovalResponse(**d) for d in data],
        count=len(data),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — CasePortfolioSelection endpoints
#
# RBAC:
#   POST /cases/{case_id}/portfolio-selection  → advisor, admin
#   GET  /cases/{case_id}/portfolio-selection  → admin, advisor, compliance, viewer
#
# Comportamiento POST:
#   - 404 si case no existe.
#   - 409 si case está CLOSED.
#   - Resuelve proposal (current o explícito); 409 si no hay; 422 si de otro case.
#   - 409 si proposal.status != "completed".
#   - 422 si selected_variant no está en proposal.candidates.
#   - Si candidate requiere override:
#       - Si override_approval_id viene: debe pertenecer al case + al proposal +
#         al variant + decision=approve.
#       - Si no viene: usa current override approval del case; mismas validaciones.
#       - Si no hay override válido: 409.
#   - Si candidate NO requiere override:
#       - 422 si override_approval_id se pasa explícito (rechazo: no debe usarse).
#   - Persiste selection + mark_previous_not_current + actualiza
#     advisory_cases.current_portfolio_selection_id + transiciona status a
#     PORTFOLIO_SELECTED (si la FSM lo permite desde el status actual).
#   - AuditEvent portfolio_selected.
# ─────────────────────────────────────────────────────────────────────────────


@app.post(
    "/cases/{case_id}/portfolio-selection",
    response_model=CasePortfolioSelectionResponse,
    status_code=201,
)
def create_case_portfolio_selection(
    case_id: str,
    req: CasePortfolioSelectionCreateRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> CasePortfolioSelectionResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with SQLiteEntityStore(db_path) as store:
        case_repo = SQLiteAdvisoryCaseRepository(store)
        proposal_repo = SQLiteCasePortfolioProposalRepository(store)
        override_repo = SQLiteCaseOverrideApprovalRepository(store)
        adv_repo = SQLiteAdvisorRepository(store)
        selection_repo = SQLiteCasePortfolioSelectionRepository(store)
        audit_repo = SQLiteAuditEventRepository(store)

        # ── 1. case ───────────────────────────────────────────────────────
        case_data = case_repo.get(case_id)
        if case_data is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        if case_data["status"] == "CLOSED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} is CLOSED; portfolio selections are "
                    "not accepted after case closure."
                ),
            )

        # ── 2. resolver proposal ──────────────────────────────────────────
        proposal_data: dict[str, Any] | None
        if req.proposal_id is not None:
            proposal_data = proposal_repo.get(req.proposal_id)
            if proposal_data is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Portfolio proposal not found: {req.proposal_id!r}",
                )
            if proposal_data["case_id"] != case_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Portfolio proposal {req.proposal_id!r} belongs to "
                        f"case {proposal_data['case_id']!r}, not {case_id!r}."
                    ),
                )
        else:
            proposal_data = proposal_repo.get_current_for_case(case_id)
            if proposal_data is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Case {case_id!r} has no portfolio proposal. "
                        "POST a portfolio-proposal first."
                    ),
                )

        if proposal_data["status"] != "completed":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Portfolio proposal {proposal_data['proposal_id']!r} has "
                    f"status {proposal_data['status']!r}; selection requires "
                    "a completed proposal with candidates."
                ),
            )

        # ── 3. resolver candidate ─────────────────────────────────────────
        candidates_by_variant: dict[str, dict[str, Any]] = {
            c["variant"]: c
            for c in proposal_data["candidates"]
            if isinstance(c, dict) and "variant" in c
        }
        if req.selected_variant not in candidates_by_variant:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Selected variant {req.selected_variant!r} not found in "
                    f"proposal {proposal_data['proposal_id']!r}. Available: "
                    f"{sorted(candidates_by_variant.keys())}."
                ),
            )
        chosen_candidate = candidates_by_variant[req.selected_variant]
        requires_override = _candidate_requires_override(chosen_candidate)

        # ── 4. resolver override (si aplica) ──────────────────────────────
        resolved_override_id: str | None = None
        if requires_override:
            # candidate requiere override → override es obligatorio
            override_data: dict[str, Any] | None
            if req.override_approval_id is not None:
                override_data = override_repo.get(req.override_approval_id)
                if override_data is None:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Override approval not found: {req.override_approval_id!r}"
                        ),
                    )
                if override_data["case_id"] != case_id:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Override approval {req.override_approval_id!r} "
                            f"belongs to case {override_data['case_id']!r}, "
                            f"not {case_id!r}."
                        ),
                    )
                if override_data["proposal_id"] != proposal_data["proposal_id"]:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Override approval {req.override_approval_id!r} "
                            f"belongs to proposal {override_data['proposal_id']!r}, "
                            f"not {proposal_data['proposal_id']!r}."
                        ),
                    )
                if override_data["candidate_variant"] != req.selected_variant:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Override approval {req.override_approval_id!r} "
                            f"is for candidate "
                            f"{override_data['candidate_variant']!r}, "
                            f"not {req.selected_variant!r}."
                        ),
                    )
                if override_data["decision"] != "approve":
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Override approval {req.override_approval_id!r} "
                            f"has decision {override_data['decision']!r}; "
                            "selection requires decision='approve'."
                        ),
                    )
                resolved_override_id = override_data["override_approval_id"]
            else:
                # Sin override explícito: buscar el current del case que
                # coincida con proposal + variant + decision=approve.
                current_override = override_repo.get_current_for_case(case_id)
                if (
                    current_override is None
                    or current_override["proposal_id"] != proposal_data["proposal_id"]
                    or current_override["candidate_variant"] != req.selected_variant
                    or current_override["decision"] != "approve"
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Candidate {req.selected_variant!r} requires an "
                            "approved override; no matching override approval "
                            f"found for proposal "
                            f"{proposal_data['proposal_id']!r}."
                        ),
                    )
                resolved_override_id = current_override["override_approval_id"]
        else:
            # Candidate NO requiere override → no debe pasar override_approval_id
            if req.override_approval_id is not None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Candidate {req.selected_variant!r} does not require "
                        "advisor override; do not pass override_approval_id."
                    ),
                )

        # ── 5. soft FK lookup advisor_id ──────────────────────────────────
        advisor_id_for_row: str | None = None
        if adv_repo.get(advisor.advisor_id) is not None:
            advisor_id_for_row = advisor.advisor_id

        # ── 6. persistir selection ────────────────────────────────────────
        try:
            selection_data = selection_repo.create(
                case_id=case_id,
                proposal_id=proposal_data["proposal_id"],
                selected_variant=req.selected_variant,
                selected_candidate=chosen_candidate,
                rationale=req.rationale,
                source=req.source,
                override_approval_id=resolved_override_id,
                advisor_id=advisor_id_for_row,
                is_current=True,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        # ── 7. mark previous + actualizar puntero + transicionar status ───
        selection_repo.mark_previous_not_current(
            case_id, exclude_id=selection_data["selection_id"]
        )
        try:
            case_repo.update_current_portfolio_selection(
                case_id, selection_data["selection_id"]
            )
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        # Transición de status: IN_PROGRESS → PORTFOLIO_SELECTED. Si el
        # case ya estaba en PORTFOLIO_SELECTED (re-selección), mantener.
        # CLOSED ya fue rechazado arriba. DRAFT requiere KYC primero (caso
        # edge que no debería ocurrir en el flow productivo); aceptamos
        # DRAFT como "salto" defensivo, pero no genera evento de status.
        current_status = case_data["status"]
        if current_status == "IN_PROGRESS":
            try:
                case_repo.update_status(case_id, "PORTFOLIO_SELECTED")
            except CaseTransitionError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Selection persisted but case status transition "
                        f"failed: {exc}"
                    ),
                ) from exc
        # current_status == "PORTFOLIO_SELECTED" → no-op (idempotente).
        # current_status == "DRAFT" → no transicionamos (no es path productivo).

        # ── 8. AuditEvent ─────────────────────────────────────────────────
        try:
            audit_repo.append(
                case_id=case_id,
                event_type="portfolio_selected",
                actor_advisor_id=advisor_id_for_row,
                actor_role=_pick_actor_role(advisor.roles),
                payload={
                    "case_id":              case_id,
                    "selection_id":         selection_data["selection_id"],
                    "proposal_id":          selection_data["proposal_id"],
                    "override_approval_id": selection_data["override_approval_id"],
                    "selected_variant":     selection_data["selected_variant"],
                    "advisor_id":           selection_data["advisor_id"],
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Selection {selection_data['selection_id']!r} was "
                    f"persisted but the audit event failed: {exc}"
                ),
            ) from exc

    return CasePortfolioSelectionResponse(**selection_data)


@app.get(
    "/cases/{case_id}/portfolio-selection",
    response_model=CasePortfolioSelectionListResponse,
)
def list_case_portfolio_selections(
    case_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> CasePortfolioSelectionListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        if SQLiteAdvisoryCaseRepository(store).get(case_id) is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        data = SQLiteCasePortfolioSelectionRepository(store).list_by_case(case_id)
    return CasePortfolioSelectionListResponse(
        selections=[CasePortfolioSelectionResponse(**d) for d in data],
        count=len(data),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — CaseReport endpoints (markdown reports)
#
# RBAC:
#   POST /cases/{case_id}/reports                → advisor, admin
#   GET  /cases/{case_id}/reports                → admin, advisor, compliance, viewer
#   GET  /cases/{case_id}/reports/{report_id}    → admin, advisor, compliance, viewer
#
# Comportamiento POST:
#   - 404 si case no existe.
#   - 409 si case está CLOSED.
#   - Resuelve portfolio_selection_id explícito (debe pertenecer al case) o
#     usa case.current_portfolio_selection_id. Si no hay selection → 409.
#   - Carga proposal y approval para enriquecer el reporte; override si aplica.
#   - Genera markdown con CaseMarkdownReportGenerator.
#   - Persiste report con version siguiente; mark_previous_not_current.
#   - AuditEvent "report_generated".
#
# GET /cases/{case_id}/reports/{report_id}:
#   - 404 si case no existe.
#   - 404 si report no existe.
#   - 404 si report pertenece a otro case (no exponemos IDs cross-case).
# ─────────────────────────────────────────────────────────────────────────────


@app.post(
    "/cases/{case_id}/reports",
    response_model=CaseReportResponse,
    status_code=201,
)
def create_case_report(
    case_id: str,
    req: CaseReportCreateRequest,
    advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
) -> CaseReportResponse:
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with SQLiteEntityStore(db_path) as store:
        case_repo = SQLiteAdvisoryCaseRepository(store)
        selection_repo = SQLiteCasePortfolioSelectionRepository(store)
        proposal_repo = SQLiteCasePortfolioProposalRepository(store)
        approval_repo = SQLiteAdvisorProfileApprovalCaseRepository(store)
        override_repo = SQLiteCaseOverrideApprovalRepository(store)
        adv_repo = SQLiteAdvisorRepository(store)
        report_repo = SQLiteCaseReportRepository(store)
        audit_repo = SQLiteAuditEventRepository(store)

        # ── 1. case ───────────────────────────────────────────────────────
        case_data = case_repo.get(case_id)
        if case_data is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        if case_data["status"] == "CLOSED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Case {case_id!r} is CLOSED; new reports are not "
                    "accepted after case closure."
                ),
            )

        # ── 2. resolver portfolio_selection ───────────────────────────────
        selection_data: dict[str, Any] | None
        if req.portfolio_selection_id is not None:
            selection_data = selection_repo.get(req.portfolio_selection_id)
            if selection_data is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Portfolio selection not found: "
                        f"{req.portfolio_selection_id!r}"
                    ),
                )
            if selection_data["case_id"] != case_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Portfolio selection {req.portfolio_selection_id!r} "
                        f"belongs to case {selection_data['case_id']!r}, not "
                        f"{case_id!r}."
                    ),
                )
        else:
            current_id = case_data.get("current_portfolio_selection_id")
            if current_id is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Case {case_id!r} has no current portfolio selection. "
                        "POST a portfolio-selection first."
                    ),
                )
            selection_data = selection_repo.get(current_id)
            if selection_data is None:
                # Inconsistencia interna: puntero hacia row inexistente.
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Case {case_id!r} current_portfolio_selection_id "
                        f"{current_id!r} not found in case_portfolio_selections."
                    ),
                )

        # ── 3. cargar proposal y override / approval para enriquecer ──────
        proposal_data: dict[str, Any] | None = proposal_repo.get(
            selection_data["proposal_id"]
        )
        # proposal_data podría ser None solo si la FK se rompió manualmente;
        # se tolera y se reporta sin el detail. El advisor verá un report
        # con métricas del selected_candidate (snapshot) intacto.

        override_data: dict[str, Any] | None = None
        if selection_data.get("override_approval_id") is not None:
            override_data = override_repo.get(selection_data["override_approval_id"])

        approval_data: dict[str, Any] | None = None
        approval_id = case_data.get("current_approved_profile_id")
        if approval_id is not None:
            approval_data = approval_repo.get(approval_id)

        # ── 4. soft FK lookup advisor_id ──────────────────────────────────
        generated_by_advisor_id: str | None = None
        if adv_repo.get(advisor.advisor_id) is not None:
            generated_by_advisor_id = advisor.advisor_id

        # latest analysis para derivar el Risk Gap (campo derivado del result).
        latest_analysis_data: dict[str, Any] | None = None
        _analyses = SQLiteAIProfileAnalysisRepository(store).list_by_case(case_id)
        if _analyses:
            latest_analysis_data = _analyses[-1]

        # ── 4b. Capacidad vs. tolerancia (diferencial) desde el KYC vigente ──
        # Carga el KYC del caso y computa el marco determinístico (capacidad
        # acota tolerancia) + el capacity gap, para la sección de capacidad y el
        # resumen ejecutivo del reporte. Tolerante: si no hay KYC, queda None.
        capacity_data: dict[str, Any] | None = None
        risk_number_data: dict[str, Any] | None = None
        kyc_id = case_data.get("current_kyc_submission_id")
        if kyc_id is not None:
            kyc_row = SQLiteKYCSubmissionRepository(store).get(kyc_id)
            kyc_payload = (kyc_row or {}).get("payload")
            if isinstance(kyc_payload, dict):
                from risk_first_advisory.ai_layer.risk_scoring import (
                    capacity_gap_from_kyc,
                    deterministic_assessment,
                )
                capacity_data = {
                    "deterministic": deterministic_assessment(kyc_payload),
                    "capacity_gap": capacity_gap_from_kyc(kyc_payload),
                }
                # Risk Number del cliente (docs/RISK_NUMBER_DESIGN.md): mismo
                # patrón que capacity_data, recomputado del KYC vigente
                # (incluye el trade-off opcional si el KYC lo respondió). La
                # cartera SELECCIONADA ya trae su propio risk_number/risk_alignment
                # persistidos en selected_candidate — el generator los formatea,
                # no los recalcula (I-013/I-020).
                try:
                    risk_number_data = {"client": _client_risk_number_tolerant(kyc_payload)}
                except (TypeError, ValueError):
                    risk_number_data = None

        # ── 5. generar markdown ───────────────────────────────────────────
        try:
            markdown, metadata = CaseMarkdownReportGenerator().generate(
                case_data=case_data,
                selection_data=selection_data,
                proposal_data=proposal_data,
                approval_data=approval_data,
                override_data=override_data,
                analysis_data=latest_analysis_data,
                capacity_data=capacity_data,
                risk_number_data=risk_number_data,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Report generation failed: {exc}",
            ) from exc

        # ── 6. persistir report ───────────────────────────────────────────
        try:
            report_data = report_repo.create(
                case_id=case_id,
                report_type=req.report_type,
                status=req.status,
                markdown=markdown,
                metadata=metadata,
                portfolio_selection_id=selection_data["selection_id"],
                portfolio_proposal_id=selection_data["proposal_id"],
                generated_by_advisor_id=generated_by_advisor_id,
                is_current=True,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        # ── 7. mark previous not current ──────────────────────────────────
        report_repo.mark_previous_not_current(
            case_id, exclude_id=report_data["report_id"]
        )

        # ── 8. AuditEvent ─────────────────────────────────────────────────
        try:
            audit_repo.append(
                case_id=case_id,
                event_type="report_generated",
                actor_advisor_id=generated_by_advisor_id,
                actor_role=_pick_actor_role(advisor.roles),
                payload={
                    "case_id":                case_id,
                    "report_id":              report_data["report_id"],
                    "portfolio_selection_id": report_data["portfolio_selection_id"],
                    "portfolio_proposal_id":  report_data["portfolio_proposal_id"],
                    "report_type":            report_data["report_type"],
                    "status":                 report_data["status"],
                    "version":                report_data["version"],
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Report {report_data['report_id']!r} was persisted but "
                    f"the audit event failed: {exc}"
                ),
            ) from exc

    return CaseReportResponse(**report_data)


@app.get(
    "/cases/{case_id}/reports",
    response_model=CaseReportListResponse,
)
def list_case_reports(
    case_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> CaseReportListResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        if SQLiteAdvisoryCaseRepository(store).get(case_id) is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        data = SQLiteCaseReportRepository(store).list_by_case(case_id)
    return CaseReportListResponse(
        reports=[CaseReportResponse(**d) for d in data],
        count=len(data),
    )


@app.get(
    "/cases/{case_id}/reports/{report_id}",
    response_model=CaseReportResponse,
)
def get_case_report(
    case_id: str,
    report_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> CaseReportResponse:
    db_path: Path = DEFAULT_DB_PATH
    with SQLiteEntityStore(db_path) as store:
        if SQLiteAdvisoryCaseRepository(store).get(case_id) is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
        report_data = SQLiteCaseReportRepository(store).get(report_id)

    # 404 si no existe OR pertenece a otro case (no exponemos IDs cross-case).
    if report_data is None or report_data["case_id"] != case_id:
        raise HTTPException(
            status_code=404,
            detail=f"Report not found: {report_id!r}",
        )
    return CaseReportResponse(**report_data)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Case Summary endpoint (full case state en una sola request)
#
# RBAC:
#   GET /cases/{case_id}/summary  → admin, advisor, compliance, viewer
#
# Cargado en un único store (conexión SQLite compartida). Cada entidad
# relacionada se carga "best effort": si no existe, queda None. Esto evita
# que una inconsistencia puntual (e.g., FK rota) rompa el endpoint.
#
# El próximo Case Workbench frontend usará este endpoint para hidratar la
# vista completa de un caso sin múltiples round-trips.
# ─────────────────────────────────────────────────────────────────────────────


_PROGRESS_STEPS_TOTAL: int = 9  # kyc, analysis, approval, prefs, filter, proposal, override*, selection, report
_PROGRESS_STEPS_BASE: int = 8   # sin override (override es condicional)


def _proposal_has_override_required(proposal_data: dict[str, Any] | None) -> bool:
    """True si algún candidate del proposal requiere advisor override."""
    if proposal_data is None:
        return False
    for c in proposal_data.get("candidates") or []:
        if _candidate_requires_override(c):
            return True
    return False


def _override_requirement_for_progress(
    proposal_data: dict[str, Any] | None,
    selection_data: dict[str, Any] | None,
) -> bool:
    """
    Requisito de override a efectos del progreso del workflow (DD-015).

    Con una selección vigente manda la variante ELEGIDA: si no requiere
    override, el paso de override no aplica aunque otra variante del proposal
    sí lo requiera (si la elegida lo requiere, el endpoint de selección ya
    garantizó el override approval). Sin selección se evalúa a nivel proposal,
    para guiar al asesor a revisar el override antes de elegir.
    """
    if selection_data is not None:
        candidate = selection_data.get("selected_candidate")
        return isinstance(candidate, dict) and _candidate_requires_override(candidate)
    return _proposal_has_override_required(proposal_data)


def _compute_next_recommended_action(
    *,
    case_status: str,
    has_kyc: bool,
    has_ai_profile_analysis: bool,
    has_profile_approval: bool,
    has_investment_preferences: bool,
    has_universe_filter: bool,
    has_portfolio_proposal: bool,
    has_override_requirement: bool,
    has_override_approval: bool,
    has_portfolio_selection: bool,
    has_report: bool,
) -> str:
    """
    Calcula la siguiente acción recomendada en el workflow. Determinístico,
    sin side-effects. CLOSED tiene prioridad sobre el progreso.
    """
    if case_status == "CLOSED":
        return "closed"
    if not has_kyc:
        return "submit_kyc"
    if not has_ai_profile_analysis:
        return "run_ai_profile_analysis"
    if not has_profile_approval:
        return "approve_profile"
    if not has_investment_preferences:
        return "record_investment_preferences"
    if not has_universe_filter:
        return "run_universe_filter"
    if not has_portfolio_proposal:
        return "generate_portfolio_proposal"
    if has_override_requirement and not has_override_approval:
        return "review_override"
    if not has_portfolio_selection:
        return "select_portfolio"
    if not has_report:
        return "generate_report"
    return "ready_for_review"


def _compute_completion_ratio(
    *,
    has_kyc: bool,
    has_ai_profile_analysis: bool,
    has_profile_approval: bool,
    has_investment_preferences: bool,
    has_universe_filter: bool,
    has_portfolio_proposal: bool,
    has_override_requirement: bool,
    has_override_approval: bool,
    has_portfolio_selection: bool,
    has_report: bool,
) -> float:
    """
    Ratio de completitud 0.0 a 1.0, redondeado a 2 decimales.

    Denominator se ajusta dinámicamente: si el proposal NO tiene candidates
    que requieran override, override no penaliza (8 pasos en vez de 9).
    """
    completed = sum([
        has_kyc,
        has_ai_profile_analysis,
        has_profile_approval,
        has_investment_preferences,
        has_universe_filter,
        has_portfolio_proposal,
        has_portfolio_selection,
        has_report,
    ])
    denominator = _PROGRESS_STEPS_BASE
    if has_override_requirement:
        denominator = _PROGRESS_STEPS_TOTAL
        if has_override_approval:
            completed += 1
    return round(completed / denominator, 2)


@app.get(
    "/cases/{case_id}/summary",
    response_model=CaseSummaryResponse,
)
def get_case_summary(
    case_id: str,
    _: AdvisorIdentity = Depends(
        require_roles("admin", "advisor", "compliance", "viewer")
    ),
) -> CaseSummaryResponse:
    db_path: Path = DEFAULT_DB_PATH

    with SQLiteEntityStore(db_path) as store:
        case_repo = SQLiteAdvisoryCaseRepository(store)
        case_data = case_repo.get(case_id)
        if case_data is None:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )

        # ── Entidades relacionadas (best effort) ──────────────────────────
        firm_data = SQLiteFirmRepository(store).get(case_data["firm_id"])
        client_data = SQLiteClientRepository(store).get(case_data["client_id"])
        lead_advisor_data = SQLiteAdvisorRepository(store).get(
            case_data["lead_advisor_id"]
        )

        # ── latest_kyc ────────────────────────────────────────────────────
        kyc_repo = SQLiteKYCSubmissionRepository(store)
        latest_kyc: dict[str, Any] | None = None
        current_kyc_id = case_data.get("current_kyc_submission_id")
        if current_kyc_id is not None:
            latest_kyc = kyc_repo.get(current_kyc_id)
        if latest_kyc is None:
            # Fallback: último por versión.
            all_kyc = kyc_repo.list_by_case(case_id)
            if all_kyc:
                latest_kyc = all_kyc[-1]

        # ── latest_ai_profile_analysis ────────────────────────────────────
        analyses = SQLiteAIProfileAnalysisRepository(store).list_by_case(case_id)
        latest_ai_analysis: dict[str, Any] | None = analyses[-1] if analyses else None

        # ── current_profile_approval ──────────────────────────────────────
        approval_repo = SQLiteAdvisorProfileApprovalCaseRepository(store)
        current_approval: dict[str, Any] | None = None
        current_approval_id = case_data.get("current_approved_profile_id")
        if current_approval_id is not None:
            current_approval = approval_repo.get(current_approval_id)
        if current_approval is None:
            current_approval = approval_repo.get_current_for_case(case_id)
        if current_approval is None:
            # Último por created_at_utc como fallback.
            all_approvals = approval_repo.list_by_case(case_id)
            if all_approvals:
                current_approval = all_approvals[-1]

        # ── current_investment_preferences ────────────────────────────────
        pref_repo = SQLiteCaseInvestmentPreferenceRepository(store)
        current_pref = pref_repo.get_current_for_case(case_id)
        if current_pref is None:
            all_prefs = pref_repo.list_by_case(case_id)
            if all_prefs:
                current_pref = all_prefs[-1]

        # ── current_universe_filter ───────────────────────────────────────
        filter_repo = SQLiteCaseUniverseFilterRunRepository(store)
        current_filter = filter_repo.get_current_for_case(case_id)
        if current_filter is None:
            all_filters = filter_repo.list_by_case(case_id)
            if all_filters:
                current_filter = all_filters[-1]

        # ── current_portfolio_proposal ────────────────────────────────────
        proposal_repo = SQLiteCasePortfolioProposalRepository(store)
        current_proposal = proposal_repo.get_current_for_case(case_id)
        if current_proposal is None:
            all_proposals = proposal_repo.list_by_case(case_id)
            if all_proposals:
                current_proposal = all_proposals[-1]

        # ── current_override_approval ─────────────────────────────────────
        override_repo = SQLiteCaseOverrideApprovalRepository(store)
        current_override = override_repo.get_current_for_case(case_id)
        if current_override is None:
            all_overrides = override_repo.list_by_case(case_id)
            if all_overrides:
                current_override = all_overrides[-1]

        # ── current_portfolio_selection ───────────────────────────────────
        selection_repo = SQLiteCasePortfolioSelectionRepository(store)
        current_selection: dict[str, Any] | None = None
        current_selection_id = case_data.get("current_portfolio_selection_id")
        if current_selection_id is not None:
            current_selection = selection_repo.get(current_selection_id)
        if current_selection is None:
            current_selection = selection_repo.get_current_for_case(case_id)

        # ── current_report ────────────────────────────────────────────────
        report_repo = SQLiteCaseReportRepository(store)
        current_report = report_repo.get_current_for_case(case_id)
        if current_report is None:
            all_reports = report_repo.list_by_case(case_id)
            if all_reports:
                current_report = all_reports[-1]

        # ── audit summary ─────────────────────────────────────────────────
        audit_result = SQLiteAuditEventRepository(store).verify_chain(case_id)

        # ── AI logs summary ───────────────────────────────────────────────
        ai_logs = SQLiteAIRequestLogRepository(store).list_by_case(case_id)
        ai_logs_count = len(ai_logs)
        latest_ai_log_id: str | None = None
        latest_validation_status: str | None = None
        if ai_logs:
            latest_log = ai_logs[-1]
            latest_ai_log_id = latest_log["request_id"]
            latest_validation_status = latest_log["validation_status"]

    # ── Progress flags ───────────────────────────────────────────────────────
    has_kyc                    = latest_kyc is not None
    has_ai_profile_analysis    = latest_ai_analysis is not None
    has_profile_approval       = current_approval is not None
    has_investment_preferences = current_pref is not None
    has_universe_filter        = current_filter is not None
    has_portfolio_proposal     = current_proposal is not None
    has_override_approval      = current_override is not None
    has_portfolio_selection    = current_selection is not None
    has_report                 = current_report is not None
    has_override_requirement   = _override_requirement_for_progress(
        current_proposal, current_selection
    )

    next_action = _compute_next_recommended_action(
        case_status=case_data["status"],
        has_kyc=has_kyc,
        has_ai_profile_analysis=has_ai_profile_analysis,
        has_profile_approval=has_profile_approval,
        has_investment_preferences=has_investment_preferences,
        has_universe_filter=has_universe_filter,
        has_portfolio_proposal=has_portfolio_proposal,
        has_override_requirement=has_override_requirement,
        has_override_approval=has_override_approval,
        has_portfolio_selection=has_portfolio_selection,
        has_report=has_report,
    )
    completion_ratio = _compute_completion_ratio(
        has_kyc=has_kyc,
        has_ai_profile_analysis=has_ai_profile_analysis,
        has_profile_approval=has_profile_approval,
        has_investment_preferences=has_investment_preferences,
        has_universe_filter=has_universe_filter,
        has_portfolio_proposal=has_portfolio_proposal,
        has_override_requirement=has_override_requirement,
        has_override_approval=has_override_approval,
        has_portfolio_selection=has_portfolio_selection,
        has_report=has_report,
    )

    # ── Construir response ───────────────────────────────────────────────────
    return CaseSummaryResponse(
        case=AdvisoryCaseResponse(**case_data),
        firm=FirmResponse(**firm_data) if firm_data else None,
        client=ClientResponse(**client_data) if client_data else None,
        lead_advisor=AdvisorResponse(**lead_advisor_data) if lead_advisor_data else None,
        latest_kyc=KYCSubmissionResponse(**latest_kyc) if latest_kyc else None,
        latest_ai_profile_analysis=(
            AIProfileAnalysisResponse(**latest_ai_analysis) if latest_ai_analysis else None
        ),
        current_profile_approval=(
            CaseAdvisorProfileApprovalResponse(**current_approval) if current_approval else None
        ),
        current_investment_preferences=(
            CaseInvestmentPreferenceResponse(**current_pref) if current_pref else None
        ),
        current_universe_filter=(
            CaseUniverseFilterRunResponse(**current_filter) if current_filter else None
        ),
        current_portfolio_proposal=(
            CasePortfolioProposalResponse(**current_proposal) if current_proposal else None
        ),
        current_override_approval=(
            CaseOverrideApprovalResponse(**current_override) if current_override else None
        ),
        current_portfolio_selection=(
            CasePortfolioSelectionResponse(**current_selection) if current_selection else None
        ),
        current_report=(
            CaseReportResponse(**current_report) if current_report else None
        ),
        audit=CaseAuditSummaryResponse(
            is_intact=audit_result["is_intact"],
            total_events=audit_result["total_events"],
            first_broken_sequence=audit_result["first_broken_sequence"],
            message=audit_result["message"],
        ),
        ai=CaseAISummaryResponse(
            ai_logs_count=ai_logs_count,
            latest_ai_log_id=latest_ai_log_id,
            latest_validation_status=latest_validation_status,
        ),
        progress=CaseWorkflowProgressResponse(
            has_kyc=has_kyc,
            has_ai_profile_analysis=has_ai_profile_analysis,
            has_profile_approval=has_profile_approval,
            has_investment_preferences=has_investment_preferences,
            has_universe_filter=has_universe_filter,
            has_portfolio_proposal=has_portfolio_proposal,
            has_override_approval=has_override_approval,
            has_portfolio_selection=has_portfolio_selection,
            has_report=has_report,
            next_recommended_action=next_action,
            completion_ratio=completion_ratio,
        ),
    )


@app.post(
    "/admin/ai-logs",
    response_model=AIRequestLogResponse,
    status_code=201,
)
def create_ai_log(
    req: AIRequestLogCreateRequest,
    _: AdvisorIdentity = Depends(require_roles("admin")),
) -> AIRequestLogResponse:
    """
    Creación manual de log (backfill / scripts / tests internos).

    Valida FKs (case_id / requested_by_advisor_id) y redacta el
    input_payload antes de persistir. El input original NO se persiste.
    """
    db_path: Path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLiteEntityStore(db_path) as store:
        # FK validation explícita en endpoint (igual patrón que /cases)
        if req.case_id is not None:
            if SQLiteAdvisoryCaseRepository(store).get(req.case_id) is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Case not found: {req.case_id!r}",
                )
        if req.requested_by_advisor_id is not None:
            if SQLiteAdvisorRepository(store).get(req.requested_by_advisor_id) is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Advisor not found: {req.requested_by_advisor_id!r}",
                )

        input_redacted = redact_ai_input(req.input_payload)
        input_hash = compute_input_hash(req.input_payload)

        try:
            data = SQLiteAIRequestLogRepository(store).create(
                endpoint=req.endpoint.strip(),
                model=req.model.strip(),
                prompt_version=req.prompt_version.strip(),
                input_redacted=input_redacted,
                input_hash=input_hash,
                validation_status=req.validation_status,
                case_id=req.case_id,
                requested_by_advisor_id=req.requested_by_advisor_id,
                raw_response=req.raw_response,
                latency_ms=req.latency_ms,
                prompt_tokens=req.prompt_tokens,
                completion_tokens=req.completion_tokens,
                error_message=req.error_message,
            )
        except EntityConflictError as exc:
            detail = str(exc)
            status_code = 409 if "UNIQUE constraint" in detail else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

    return AIRequestLogResponse(**data)
