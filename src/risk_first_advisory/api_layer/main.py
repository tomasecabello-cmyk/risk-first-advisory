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
from pathlib import Path

from fastapi import FastAPI

from risk_first_advisory.ai_layer.mock_ai_client import MockAIClient
from risk_first_advisory.api_layer.schemas import (
    DemoRunResponse,
    FinancialGoalRequest,
    HealthResponse,
    KYCDataRequest,
    PersistenceRecordIds,
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
from risk_first_advisory.persistence_layer.sqlite_repository import (
    SQLiteAuditRepository,
    SQLitePersistenceStore,
    SQLiteReportRepository,
    SQLiteWorkflowRunRepository,
)
from risk_first_advisory.reporting_layer import MarkdownReportGenerator
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
        age=40,
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
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="risk-first-advisory")


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

    return WorkflowRunResponse(
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
