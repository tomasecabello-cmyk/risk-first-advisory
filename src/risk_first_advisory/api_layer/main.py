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
    AdvisoryCaseCreateRequest,
    AdvisoryCaseListResponse,
    AdvisoryCaseResponse,
    AdvisoryCaseStatusUpdateRequest,
    AIProfileAnalysisCreateRequest,
    AIProfileAnalysisListResponse,
    AIProfileAnalysisResponse,
    AIRequestLogCreateRequest,
    AIRequestLogListResponse,
    AIRequestLogResponse,
    AuditEventCreateRequest,
    AuditEventListResponse,
    AuditEventResponse,
    AuditVerifyResponse,
    AdvisorOverrideApprovalRequest,
    AdvisorOverrideApprovalResponse,
    AdvisorPortfolioSelectionRequest,
    AdvisorPortfolioSelectionResponse,
    AdvisorProfileApprovalRequest,
    AdvisorProfileApprovalResponse,
    AdvisorResponse,
    CaseAdvisorProfileApprovalCreateRequest,
    CaseAdvisorProfileApprovalListResponse,
    CaseAdvisorProfileApprovalResponse,
    AIContradictionResponse,
    AIFilteredPortfolioRequest,
    AIFilteredPortfolioResponse,
    AIFollowUpAnswerRequest,
    AIInvestmentPreferencesRequest,
    AIInvestmentPreferencesResponse,
    AIProfileFollowUpRequest,
    AIProfileFollowUpResponse,
    AIProfileRequest,
    AIProfileResponse,
    AIUniverseFilterResponse,
    ClientCreateRequest,
    ClientListResponse,
    ClientResponse,
    DemoRunResponse,
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
    StoredRecordResponse,
    UniverseFilterRequest,
    UniverseFilterResponse,
    WorkflowRunRequest,
    WorkflowRunResponse,
)
from risk_first_advisory.universe_layer import (
    CSVInstrumentUniverseProvider,
    PreferenceFilterEngine,
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
from risk_first_advisory.persistence_layer.repositories import (
    RecordNotFoundError,
    RepositoryError,
    StoredRecord,
)
from risk_first_advisory.persistence_layer.entity_repository import (
    ALLOWED_AI_LOG_STATUSES,
    ALLOWED_CASE_STATUSES,
    CaseTransitionError,
    EntityConflictError,
    EntityNotFoundError,
    SQLiteAdvisorRepository,
    SQLiteAdvisorProfileApprovalCaseRepository,
    SQLiteAdvisoryCaseRepository,
    SQLiteAIProfileAnalysisRepository,
    SQLiteAIRequestLogRepository,
    SQLiteAuditEventRepository,
    SQLiteClientRepository,
    SQLiteEntityStore,
    SQLiteFirmRepository,
    SQLiteKYCSubmissionRepository,
    compute_input_hash,
    redact_ai_input,
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
    MarkdownReport,
    MarkdownReportGenerator,
)
from risk_first_advisory.rules_layer.esg_compliance import ESGMetadataStore
from risk_first_advisory.rules_layer.instrument_suitability import (
    InstrumentSuitabilityMatrix,
)
from risk_first_advisory.rules_layer.product_governance import ApprovedProductUniverse
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


def _get_openai_profile_client():
    """
    Crea y devuelve un OpenAIProfileClient real.

    Separada del endpoint para permitir monkeypatch en tests sin llamar
    a OpenAI ni requerir OPENAI_API_KEY en el entorno de CI.

    Raises:
        ValueError: si OPENAI_API_KEY no está configurada.
        ImportError: si el paquete openai no está instalado.
    """
    from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

    return OpenAIProfileClient()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="risk-first-advisory")


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
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Advisor profile approval persistence failed.",
        )

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
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Advisor override approval persistence failed.",
        )

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
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Advisor portfolio selection persistence failed.",
        )

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
    except (ValueError, ImportError):
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not configured. Set the environment variable and retry.",
        )

    # ── 2. Construir payload KYC como dict (excluye campos None) ──────────
    kyc_dict = req.kyc_payload.model_dump(exclude_none=True)
    # El client_id ayuda a la IA a contextualizar el caso (no lo usa para aprobar)
    kyc_dict["client_id"] = req.client_id

    # ── 3. Llamar a la IA ─────────────────────────────────────────────────
    try:
        result = ai_client.analyze_kyc(kyc_dict)
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="AI profile analysis failed. The AI returned an invalid response.",
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="AI profile analysis failed due to an unexpected error.",
        )

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
    except (ValueError, ImportError):
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not configured. Set the environment variable and retry.",
        )

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
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="AI profile follow-up analysis failed. The AI returned an invalid response.",
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="AI profile follow-up analysis failed due to an unexpected error.",
        )

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
    except (ValueError, ImportError):
        raise HTTPException(
            status_code=400,
            detail=(
                "OPENAI_API_KEY is not configured. "
                "Set the environment variable and retry."
            ),
        )

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
        )
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
        )

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
    except (ValueError, ImportError):
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not configured. Set the environment variable and retry.",
        )

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
        )
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
        )

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
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Instrument universe fixture not found.",
        )

    # ── 4. Construir dict de filtros (solo claves reconocidas por el engine) ──
    filter_prefs: dict = {
        k: v for k, v in ai_result.items() if k in _AI_FILTER_PREFERENCE_KEYS
    }

    # ── 5. Aplicar filtro ─────────────────────────────────────────────────
    try:
        filter_result = PreferenceFilterEngine().apply(universe, filter_prefs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

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
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Instrument universe fixture not found.",
        )

    # ── 3. Construir dict de preferencias — solo claves con valor activo ──
    prefs: dict = req.model_dump(exclude_none=True)

    # ── 4. Aplicar filtro ─────────────────────────────────────────────────
    try:
        filter_result = PreferenceFilterEngine().apply(universe, prefs)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        )

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
    except (ValueError, ImportError):
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not configured. Set the environment variable and retry.",
        )

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
        )
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
        )

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
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Instrument universe fixture not found.",
        )

    # ── 5. Aplicar filtro ─────────────────────────────────────────────────
    filter_prefs: dict = {
        k: v for k, v in ai_result.items() if k in _AI_FILTER_PREFERENCE_KEYS
    }
    try:
        filter_result = PreferenceFilterEngine().apply(universe, filter_prefs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

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
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="AI filtered portfolio report generation failed.",
            )
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
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="AI filtered portfolio persistence failed.",
            )
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
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    except RepositoryError:
        raise HTTPException(status_code=500, detail="Persistence error")
    return _stored_record_to_response(record)


@app.get("/reports/{record_id}", response_model=StoredRecordResponse)
def get_report(record_id: str) -> StoredRecordResponse:
    db_path: Path = DEFAULT_DB_PATH
    try:
        with SQLitePersistenceStore(db_path) as store:
            store.init_schema()
            record = SQLiteReportRepository(store).get_report(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    except RepositoryError:
        raise HTTPException(status_code=500, detail="Persistence error")
    return _stored_record_to_response(record)


@app.get("/audit/{record_id}", response_model=StoredRecordResponse)
def get_audit(record_id: str) -> StoredRecordResponse:
    db_path: Path = DEFAULT_DB_PATH
    try:
        with SQLitePersistenceStore(db_path) as store:
            store.init_schema()
            record = SQLiteAuditRepository(store).get_audit_trail(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    except RepositoryError:
        raise HTTPException(status_code=500, detail="Persistence error")
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
    except RepositoryError:
        raise HTTPException(status_code=500, detail="Persistence error")
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
    except RepositoryError:
        raise HTTPException(status_code=500, detail="Persistence error")
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
    except RepositoryError:
        raise HTTPException(status_code=500, detail="Persistence error")
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
        except EntityNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"Case not found: {case_id!r}"
            )
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
    except (ValueError, ImportError):
        raise HTTPException(
            status_code=400,
            detail=(
                "OPENAI_API_KEY is not configured. "
                "Set the environment variable and retry."
            ),
        )

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
        )
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
        )

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

    return AIProfileAnalysisResponse(**analysis_data)


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

    return CaseAdvisorProfileApprovalResponse(**approval_data)


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
