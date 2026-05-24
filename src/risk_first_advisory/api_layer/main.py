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
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from risk_first_advisory.ai_layer.mock_ai_client import MockAIClient
from risk_first_advisory.api_layer.auth import (
    AdvisorIdentity,
    get_current_advisor_required,
)
from risk_first_advisory.api_layer.schemas import (
    AdvisorIdentityResponse,
    AdvisorOverrideApprovalRequest,
    AdvisorOverrideApprovalResponse,
    AdvisorPortfolioSelectionRequest,
    AdvisorPortfolioSelectionResponse,
    AdvisorProfileApprovalRequest,
    AdvisorProfileApprovalResponse,
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
    DemoRunResponse,
    FilteredSnapshotResponse,
    FinancialGoalRequest,
    HealthResponse,
    InstrumentExclusionResponse,
    InstrumentResponse,
    KYCDataRequest,
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
    """Convierte KYCDataRequest a KYCData con valores por defecto razonables."""
    experience = _EXPERIENCE_MAP.get(req.investment_experience, InvestorExperience.MODERATE)
    needs_income = req.income_stability.lower() != "stable"
    # La tolerancia psicológica es el mínimo entre el score y el drawdown declarado.
    emotional_tolerance = min(
        req.risk_tolerance_score * 10.0,
        req.max_acceptable_drawdown_pct,
    )
    # annual_income_usd: derivado del liquid_net_worth cuando no se declara explícitamente.
    annual_income = max(req.liquid_net_worth * 0.05, 1.0)
    return KYCData(
        age=req.age,
        annual_income_usd=annual_income,
        approx_net_worth_usd=req.net_worth,
        investment_objective=InvestmentObjective.BALANCED,
        time_horizon_years=req.investment_horizon_years,
        liquidity_need_pct=req.liquidity_need_score / 10.0,
        experience=experience,
        emotional_loss_tolerance_pct=emotional_tolerance,
        financial_loss_capacity_pct=req.risk_capacity_score * 10.0,
        preferred_currency="USD",
        needs_income=needs_income,
        prefers_simple_products=False,
        jurisdiction="AR",
        esg_profile=ESGProfile(),
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
# el sistema). Auth: get_current_advisor_required → 401 sin token válido.
#
# Por ahora cualquier identidad demo (advisor o compliance) puede registrar
# una decisión. RBAC más estricto (solo rol "advisor") queda para tareas
# posteriores de Fase 1.
# ─────────────────────────────────────────────────────────────────────────────


@app.post(
    "/advisor/profile-approval",
    response_model=AdvisorProfileApprovalResponse,
)
def advisor_profile_approval(
    req: AdvisorProfileApprovalRequest,
    advisor: AdvisorIdentity = Depends(get_current_advisor_required),
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
# Auth: get_current_advisor_required → 401 sin token válido.
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
    advisor: AdvisorIdentity = Depends(get_current_advisor_required),
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
# Auth: get_current_advisor_required → 401 sin token válido.
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
    advisor: AdvisorIdentity = Depends(get_current_advisor_required),
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

    # ── 3. Llamar a la IA ─────────────────────────────────────────────────
    try:
        result = ai_client.extract_investment_preferences(preferences_payload)
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail=(
                "AI investment preferences extraction failed. "
                "The AI returned an invalid response. Check backend logs."
            ),
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="AI investment preferences extraction failed due to an unexpected error.",
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

    # ── 2. Extraer preferencias con IA ───────────────────────────────────
    preferences_payload: dict = {
        "client_id": req.client_id,
        "natural_language_preferences": req.natural_language_preferences,
        "kyc_context": req.kyc_context,
        "previous_profile_analysis": req.previous_profile_analysis,
    }
    try:
        ai_result = ai_client.extract_investment_preferences(preferences_payload)
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="AI investment preference extraction failed. The AI returned an invalid response.",
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="AI investment preference extraction failed due to an unexpected error.",
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

    # ── 3. Extraer preferencias con IA ───────────────────────────────────
    preferences_payload: dict = {
        "client_id": req.client_id,
        "natural_language_preferences": req.natural_language_preferences,
        "kyc_context": req.kyc_context,
        "previous_profile_analysis": req.previous_profile_analysis,
    }
    try:
        ai_result = ai_client.extract_investment_preferences(preferences_payload)
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="AI investment preference extraction failed. The AI returned an invalid response.",
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="AI investment preference extraction failed due to an unexpected error.",
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
