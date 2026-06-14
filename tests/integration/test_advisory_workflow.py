"""
Tests de integración de AdvisoryWorkflowCoordinator.

El workflow es la fachada productiva. Estos tests ejercitan flujos
end-to-end completos: M1 → goal feasibility → filtros → optimización.

Cubren los 6 escenarios principales del spec:
    1. Flujo completo con fixture contradictorio (puede terminar bloqueado
       por portfolio feasibility con el RB aprobado por default).
    2. Goal feasibility bloquea → BLOCKED_BY_GOAL_FEASIBILITY.
    3. Universo final vacío → BLOCKED_BY_EMPTY_UNIVERSE.
    4. Portfolios generados con warnings → COMPLETED_WITH_WARNINGS.
    5. Portfolios generados sin warnings → COMPLETED.
    6. RB infactible con universo final → no aplicar demo adjustment.

Además: Tests 7 (to_dict JSON-serializable) y 8 (properties).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from risk_first_advisory.ai_layer.mock_ai_client import MockAIClient
from risk_first_advisory.data_layer.market_data import (
    MarketDataSnapshot,
    MockMarketDataProvider,
)
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
from risk_first_advisory.rules_layer.esg_compliance import ESGMetadataStore
from risk_first_advisory.rules_layer.instrument_suitability import (
    InstrumentSuitabilityMatrix,
)
from risk_first_advisory.rules_layer.product_governance import (
    ApprovedProductUniverse,
)
from risk_first_advisory.workflow_layer import (
    RC_GOAL_FEASIBILITY_BLOCKED,
    RC_PORTFOLIO_EMPTY_FINAL_UNIVERSE,
    RC_PORTFOLIO_GENERATION_BLOCKED,
    AdvisoryWorkflowCoordinator,
    AdvisoryWorkflowResult,
    AdvisoryWorkflowStatus,
)

# ─────────────────────────────────────────────────────────────────────────
# Paths a fixtures existentes
# ─────────────────────────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent.parent / "fixtures"
KYC_FIXTURE = FIXTURES / "kyc_profiles" / "contradictorio_alta_severidad.json"
UNIVERSE_YAML = FIXTURES / "universes" / "m1_universe.yaml"
SUITABILITY_YAML = FIXTURES / "suitability" / "instrument_matrix.yaml"
ESG_YAML = FIXTURES / "esg" / "instrument_esg_metadata.yaml"
MARKET_DATA_YAML = FIXTURES / "market_data" / "m1_market_data.yaml"


# ─────────────────────────────────────────────────────────────────────────
# Helpers para hidratar el fixture JSON contradictorio → objetos del dominio
# ─────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────
# Helpers para construir un KYC sintético "limpio" (sin contradicciones)
# que permita probar otros escenarios sin pelearse con el fixture.
# ─────────────────────────────────────────────────────────────────────────

def _make_simple_kyc(
    *,
    liquidity_need_pct: float = 0.0,
    esg_hard_exclusions: list[ESGExclusion] | None = None,
    esg_strictness: ESGStrictnessLevel = ESGStrictnessLevel.LIGHT,
) -> KYCData:
    return KYCData(
        age=40,
        annual_income_usd=120000.0,
        approx_net_worth_usd=500000.0,
        investment_objective=InvestmentObjective("growth"),
        time_horizon_years=10,
        liquidity_need_pct=liquidity_need_pct,
        experience=InvestorExperience("moderada"),
        emotional_loss_tolerance_pct=20.0,
        financial_loss_capacity_pct=25.0,
        preferred_currency="USD",
        needs_income=False,
        prefers_simple_products=False,
        jurisdiction="AR",
        esg_profile=ESGProfile(
            strictness_level=esg_strictness,
            hard_exclusions=esg_hard_exclusions or [],
            soft_preferences=[],
        ),
    )


def _make_simple_goal(
    *,
    initial: float = 100_000.0,
    target: float = 180_000.0,
    horizon_years: int = 10,
    contribution: float = 0.0,
) -> FinancialGoal:
    return FinancialGoal(
        initial_capital_usd=initial,
        target_capital_usd=target,
        horizon_years=horizon_years,
        periodic_contribution_usd=contribution,
        contribution_frequency_years=1.0,
        target_is_flexible=False,
        horizon_is_flexible=False,
    )


def _make_no_followup_advisor_script(
    *,
    approved_profile: str = "moderado",
    advisor_id: str = "ADV-WORKFLOW",
) -> dict:
    """Script de asesor que no requiere follow-up: aprueba `approved_profile` directo."""
    return {
        "advisor_id": advisor_id,
        "follow_up_responses": [],
        "profile_approval": {
            "decision": "approve_as_proposed",
            "approved_profile": approved_profile,
            "advisor_comment": "",
        },
    }


def _make_ai_script_no_contradictions(profile_name: str = "moderado") -> dict:
    """Script de IA que propone `profile_name` sin contradicciones bloqueantes."""
    return {
        "initial_profile_response": {
            "profile_name": profile_name,
            "confidence": 0.85,
            "binding_dimension": "capacity",
            "risk_tolerance": "media",
            "risk_capacity": "media",
            "risk_need": "media",
            "advisor_review_required": True,
            "detected_contradictions": [],
            "follow_up_questions": [],
        }
    }


# ─────────────────────────────────────────────────────────────────────────
# Fixture pytest: stores cargados desde YAML
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def universe() -> ApprovedProductUniverse:
    return ApprovedProductUniverse.from_yaml(UNIVERSE_YAML)


@pytest.fixture
def suitability() -> InstrumentSuitabilityMatrix:
    return InstrumentSuitabilityMatrix.from_yaml(SUITABILITY_YAML)


@pytest.fixture
def esg_store() -> ESGMetadataStore:
    return ESGMetadataStore.from_yaml(ESG_YAML)


@pytest.fixture
def market_data() -> MockMarketDataProvider:
    return MockMarketDataProvider.from_yaml(MARKET_DATA_YAML)


@pytest.fixture
def coordinator() -> AdvisoryWorkflowCoordinator:
    return AdvisoryWorkflowCoordinator()


@pytest.fixture
def contradictorio_payload() -> dict:
    return json.loads(KYC_FIXTURE.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────
# Test 1 — flujo completo con fixture contradictorio
# ─────────────────────────────────────────────────────────────────────────


class TestContradictorioFullFlow:
    """
    Fixture contradictorio: la IA propone moderado-defensivo, hay follow-up,
    el asesor aprueba moderado. El RiskBudget aprobado (max_single_asset=0.15)
    es infactible con los 4 instrumentos del universo final, por lo que el
    workflow productivo termina en BLOCKED_BY_PORTFOLIO_FEASIBILITY.
    """

    def _run(self, coordinator, contradictorio_payload, universe, suitability,
             esg_store, market_data) -> AdvisoryWorkflowResult:
        return coordinator.run(
            kyc_data=_build_kyc(contradictorio_payload),
            financial_goal=_build_goal(contradictorio_payload),
            client_id=contradictorio_payload["client_id"],
            advisor_id=contradictorio_payload["advisor_script"]["advisor_id"],
            ai_client=MockAIClient(
                scripted_responses=contradictorio_payload["ai_script"]
            ),
            advisor_interface=ScriptedAdvisorInterface(
                scripted_decisions=contradictorio_payload["advisor_script"]
            ),
            product_universe=universe,
            suitability_matrix=suitability,
            esg_metadata_store=esg_store,
            market_data_provider=market_data,
        )

    def test_approved_profile_is_moderado(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = self._run(coordinator, contradictorio_payload, universe,
                           suitability, esg_store, market_data)
        assert result.approved_profile_name == "moderado"

    def test_goal_feasibility_evaluado(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = self._run(coordinator, contradictorio_payload, universe,
                           suitability, esg_store, market_data)
        assert result.goal_feasibility_result is not None

    def test_risk_budget_construido(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = self._run(coordinator, contradictorio_payload, universe,
                           suitability, esg_store, market_data)
        assert result.risk_budget is not None
        assert result.risk_budget.profile_name == "moderado"

    def test_universe_filtrado(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = self._run(coordinator, contradictorio_payload, universe,
                           suitability, esg_store, market_data)
        assert len(result.governance_passed_tickers) > 0
        assert len(result.suitability_passed_tickers) > 0

    def test_final_optimizer_tickers_no_vacio(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = self._run(coordinator, contradictorio_payload, universe,
                           suitability, esg_store, market_data)
        assert len(result.final_optimizer_tickers) > 0

    def test_status_es_blocked_by_portfolio_feasibility(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        """El RB aprobado tiene max_single_asset=0.15. Con 4 instrumentos
        finales, 4*0.15=0.60 < 1.0 → infeasible. El workflow NO debe
        relajar nada."""
        result = self._run(coordinator, contradictorio_payload, universe,
                           suitability, esg_store, market_data)
        assert result.status == AdvisoryWorkflowStatus.BLOCKED_BY_PORTFOLIO_FEASIBILITY

    def test_candidate_set_is_none(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = self._run(coordinator, contradictorio_payload, universe,
                           suitability, esg_store, market_data)
        assert result.candidate_set is None

    def test_portfolio_feasibility_diagnostico_presente(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = self._run(coordinator, contradictorio_payload, universe,
                           suitability, esg_store, market_data)
        assert result.portfolio_feasibility_result is not None
        assert result.portfolio_feasibility_result.is_feasible is False
        assert len(result.portfolio_feasibility_result.failed_checks) > 0

    def test_reason_codes_incluye_portfolio_generation_blocked(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = self._run(coordinator, contradictorio_payload, universe,
                           suitability, esg_store, market_data)
        assert RC_PORTFOLIO_GENERATION_BLOCKED in result.reason_codes

    def test_to_dict_es_json_serializable(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = self._run(coordinator, contradictorio_payload, universe,
                           suitability, esg_store, market_data)
        payload = result.to_dict()
        s = json.dumps(payload)
        parsed = json.loads(s)
        assert parsed["status"] == "blocked_by_portfolio_feasibility"
        assert parsed["approved_profile_name"] == "moderado"


# ─────────────────────────────────────────────────────────────────────────
# Test 2 — Goal Feasibility bloquea
# ─────────────────────────────────────────────────────────────────────────


class TestGoalFeasibilityBlocks:
    """Goal claramente inviable: 100k → 2M en 3 años sin contribuciones.
    Required return >> achievable (7% para moderado). El workflow debe
    terminar en BLOCKED_BY_GOAL_FEASIBILITY sin invocar portfolios."""

    def _run(self, coordinator, universe, suitability, esg_store, market_data):
        kyc = _make_simple_kyc()
        goal = _make_simple_goal(initial=100_000.0, target=2_000_000.0, horizon_years=3)
        return coordinator.run(
            kyc_data=kyc,
            financial_goal=goal,
            client_id="CLI-GOAL-BLOCK",
            advisor_id="ADV-WORKFLOW",
            ai_client=MockAIClient(
                scripted_responses=_make_ai_script_no_contradictions("moderado")
            ),
            advisor_interface=ScriptedAdvisorInterface(
                scripted_decisions=_make_no_followup_advisor_script(
                    approved_profile="moderado"
                )
            ),
            product_universe=universe,
            suitability_matrix=suitability,
            esg_metadata_store=esg_store,
            market_data_provider=market_data,
        )

    def test_status_es_blocked_by_goal_feasibility(
        self, coordinator, universe, suitability, esg_store, market_data,
    ):
        result = self._run(coordinator, universe, suitability, esg_store, market_data)
        assert result.status == AdvisoryWorkflowStatus.BLOCKED_BY_GOAL_FEASIBILITY

    def test_candidate_set_is_none(
        self, coordinator, universe, suitability, esg_store, market_data,
    ):
        result = self._run(coordinator, universe, suitability, esg_store, market_data)
        assert result.candidate_set is None

    def test_reason_codes_incluye_goal_feasibility_blocked(
        self, coordinator, universe, suitability, esg_store, market_data,
    ):
        result = self._run(coordinator, universe, suitability, esg_store, market_data)
        assert RC_GOAL_FEASIBILITY_BLOCKED in result.reason_codes

    def test_filtros_no_se_ejecutaron(
        self, coordinator, universe, suitability, esg_store, market_data,
    ):
        """Si goal bloquea, no debería haber pasado por governance/suitability."""
        result = self._run(coordinator, universe, suitability, esg_store, market_data)
        assert result.governance_passed_tickers == []
        assert result.suitability_passed_tickers == []
        assert result.final_optimizer_tickers == []

    def test_risk_budget_no_construido(
        self, coordinator, universe, suitability, esg_store, market_data,
    ):
        result = self._run(coordinator, universe, suitability, esg_store, market_data)
        assert result.risk_budget is None

    def test_portfolio_feasibility_no_evaluado(
        self, coordinator, universe, suitability, esg_store, market_data,
    ):
        result = self._run(coordinator, universe, suitability, esg_store, market_data)
        assert result.portfolio_feasibility_result is None


# ─────────────────────────────────────────────────────────────────────────
# Test 3 — Universo final vacío
# ─────────────────────────────────────────────────────────────────────────


class TestEmptyUniverse:
    """
    Universo intencionalmente vacío tras el pipeline de filtros completo.

    Estrategia:
        - ESG hard_exclusions bloquean los tickers con metadata ESG
          (AGG → Government+Corporate, VEA → Equity_Developed,
           HYG → Corporate, SGOV → Government).
        - Los tickers sin metadata ESG (BIL, SHV, IEF, VTI) pasan el
          filtro ESG como UNKNOWN, pero no tienen snapshot en el provider
          vacío → se excluyen en el paso de data availability.
        - Resultado: final_optimizer_tickers == [] → BLOCKED_BY_EMPTY_UNIVERSE.

    Por qué MockMarketDataProvider([]):
        BIL no tiene metadata ESG → pasa ESG como UNKNOWN → con el
        provider del fixture YAML tiene snapshot → llega al universo final.
        Un provider vacío garantiza que ningún ticker UNKNOWN sobreviva el
        paso de data availability, sin modificar la semántica productiva.
    """

    def _run(self, coordinator, universe, suitability, esg_store) -> AdvisoryWorkflowResult:
        hard = [
            ESGExclusion(excluded_item="Government", exclusion_type="sector",
                         source="client_explicit"),
            ESGExclusion(excluded_item="Corporate", exclusion_type="sector",
                         source="client_explicit"),
            ESGExclusion(excluded_item="Equity_Global", exclusion_type="sector",
                         source="client_explicit"),
            ESGExclusion(excluded_item="Equity_Developed", exclusion_type="sector",
                         source="client_explicit"),
        ]
        kyc = _make_simple_kyc(esg_hard_exclusions=hard)
        goal = _make_simple_goal()
        # Provider sin snapshots: los tickers UNKNOWN (sin metadata ESG)
        # no tienen datos de mercado → se descartan en data availability.
        empty_market_data = MockMarketDataProvider([])
        return coordinator.run(
            kyc_data=kyc,
            financial_goal=goal,
            client_id="CLI-EMPTY",
            advisor_id="ADV-WORKFLOW",
            ai_client=MockAIClient(
                scripted_responses=_make_ai_script_no_contradictions("moderado")
            ),
            advisor_interface=ScriptedAdvisorInterface(
                scripted_decisions=_make_no_followup_advisor_script(
                    approved_profile="moderado"
                )
            ),
            product_universe=universe,
            suitability_matrix=suitability,
            esg_metadata_store=esg_store,
            market_data_provider=empty_market_data,
        )

    def test_status_es_blocked_by_empty_universe(
        self, coordinator, universe, suitability, esg_store,
    ):
        result = self._run(coordinator, universe, suitability, esg_store)
        assert result.status == AdvisoryWorkflowStatus.BLOCKED_BY_EMPTY_UNIVERSE

    def test_final_optimizer_vacio(
        self, coordinator, universe, suitability, esg_store,
    ):
        result = self._run(coordinator, universe, suitability, esg_store)
        assert result.final_optimizer_tickers == []

    def test_reason_codes_incluye_empty_final_universe(
        self, coordinator, universe, suitability, esg_store,
    ):
        result = self._run(coordinator, universe, suitability, esg_store)
        assert RC_PORTFOLIO_EMPTY_FINAL_UNIVERSE in result.reason_codes

    def test_candidate_set_is_none(
        self, coordinator, universe, suitability, esg_store,
    ):
        result = self._run(coordinator, universe, suitability, esg_store)
        assert result.candidate_set is None


# ─────────────────────────────────────────────────────────────────────────
# Test 4 — Portfolios generados con warnings → COMPLETED_WITH_WARNINGS
# Test 5 — Portfolios generados sin warnings → COMPLETED
# ─────────────────────────────────────────────────────────────────────────
#
# Para que el workflow termine en COMPLETED necesitamos:
#   - Universo final no vacío.
#   - RB aprobado feasible con ese universo.
#
# El RB del perfil "moderado" tiene max_single_asset=0.15. Con 4 activos
# eso es infeasible (test 1). Necesitamos un RB con cap más grande o
# un universo de muchos activos. La forma más limpia: usar un MarketData
# provider extendido con más tickers para que 1/N <= cap del budget.
# Concretamente, "agresivo" tiene max_single_asset=0.25 según
# PROFILE_BASE_PARAMS, y con 4 activos required_cap=0.25 ⇒ borde.
# Con perfil "agresivo" y 4 activos no-cash el cap está justo en 0.25.
# Vamos a forzar un universo de 6+ activos extendiendo market_data
# y usar perfil "moderado-agresivo" (cap 0.20 → 1/6=0.167 < 0.20 OK).


def _extended_market_data_provider() -> MockMarketDataProvider:
    """
    Construye un provider con suficientes tickers como para que perfiles
    no-conservadores tengan universo final ≥ 1/cap activos.

    Tickers: BIL, AGG, VT, VEA, HYG, BND, IEF, SHV, VTI — 9 activos.
    SHV/IEF/VTI son nuevos snapshots, los demás ya existen en el fixture.
    """
    base = MockMarketDataProvider.from_yaml(MARKET_DATA_YAML)
    # Copiamos los existentes y agregamos nuevos
    new_snaps = list(base.all_snapshots())
    new_snaps.append(MarketDataSnapshot(
        ticker="SHV", expected_return_annual=0.036, volatility_annual=0.004,
        liquidity_score=0.98, expense_ratio=0.0015, duration=0.20,
        asset_class="cash", currency="USD",
    ))
    new_snaps.append(MarketDataSnapshot(
        ticker="IEF", expected_return_annual=0.042, volatility_annual=0.075,
        liquidity_score=0.92, expense_ratio=0.0015, duration=7.5,
        asset_class="bond", currency="USD",
    ))
    new_snaps.append(MarketDataSnapshot(
        ticker="VTI", expected_return_annual=0.078, volatility_annual=0.150,
        liquidity_score=0.94, expense_ratio=0.0003, duration=None,
        asset_class="equity", currency="USD",
    ))
    return MockMarketDataProvider(new_snaps)


def _run_for_status(
    coordinator: AdvisoryWorkflowCoordinator,
    universe: ApprovedProductUniverse,
    suitability: InstrumentSuitabilityMatrix,
    esg_store: ESGMetadataStore,
    market_data: MockMarketDataProvider,
    *,
    approved_profile: str = "moderado-agresivo",
    liquidity_need: float = 0.0,
    esg_hard_exclusions: list[ESGExclusion] | None = None,
) -> AdvisoryWorkflowResult:
    kyc = _make_simple_kyc(
        liquidity_need_pct=liquidity_need,
        esg_hard_exclusions=esg_hard_exclusions,
    )
    goal = _make_simple_goal()
    return coordinator.run(
        kyc_data=kyc,
        financial_goal=goal,
        client_id="CLI-COMPLETE",
        advisor_id="ADV-WORKFLOW",
        ai_client=MockAIClient(
            scripted_responses=_make_ai_script_no_contradictions(approved_profile)
        ),
        advisor_interface=ScriptedAdvisorInterface(
            scripted_decisions=_make_no_followup_advisor_script(
                approved_profile=approved_profile
            )
        ),
        product_universe=universe,
        suitability_matrix=suitability,
        esg_metadata_store=esg_store,
        market_data_provider=market_data,
    )


class TestPortfolioGenerationCompleted:
    """
    Con perfil moderado-agresivo (max_single_asset=0.20) y universo
    extendido a 9 snapshots, el universo final típicamente queda en >= 5
    instrumentos, dejando cap factible. El workflow debería terminar
    completado (con o sin warnings según ESG).
    """

    def test_completed_with_warnings(
        self, coordinator, universe, suitability, esg_store,
    ):
        """Con perfil moderado-agresivo y universo extendido se generan
        portfolios. Sin metadata ESG para varios tickers (UNKNOWN) hay
        warnings → COMPLETED_WITH_WARNINGS."""
        market = _extended_market_data_provider()
        result = _run_for_status(
            coordinator, universe, suitability, esg_store, market,
            approved_profile="moderado-agresivo",
        )
        assert result.status in (
            AdvisoryWorkflowStatus.COMPLETED,
            AdvisoryWorkflowStatus.COMPLETED_WITH_WARNINGS,
        )
        # Caso esperado en este universo: hay tickers sin metadata ESG
        # (SHV, IEF, VTI) → genera ESG_WARNING y por lo tanto
        # COMPLETED_WITH_WARNINGS. Si en el futuro se agrega metadata,
        # cae a COMPLETED sin warnings y el assert sigue válido.
        if result.warnings:
            assert result.status == AdvisoryWorkflowStatus.COMPLETED_WITH_WARNINGS
        else:
            assert result.status == AdvisoryWorkflowStatus.COMPLETED

    def test_has_portfolios(
        self, coordinator, universe, suitability, esg_store,
    ):
        market = _extended_market_data_provider()
        result = _run_for_status(
            coordinator, universe, suitability, esg_store, market,
            approved_profile="moderado-agresivo",
        )
        assert result.has_portfolios is True
        assert result.candidate_set is not None
        assert result.candidate_set.count >= 1

    def test_warnings_se_acumulan_si_corresponden(
        self, coordinator, universe, suitability, esg_store,
    ):
        """Con tickers sin metadata ESG en el universo, esperamos warnings."""
        market = _extended_market_data_provider()
        result = _run_for_status(
            coordinator, universe, suitability, esg_store, market,
            approved_profile="moderado-agresivo",
        )
        # SHV, IEF, VTI no están en esg metadata → ESG_WARNING
        assert result.has_warnings is True


# ─────────────────────────────────────────────────────────────────────────
# Test 6 — workflow NO aplica demo adjustment
# ─────────────────────────────────────────────────────────────────────────


class TestNoDemoAdjustment:
    """
    Con perfil moderado (max_single_asset=0.15) y solo 4 instrumentos
    con market data, el RB es infactible. El demo runner relaja eso
    localmente; el workflow productivo NO debe hacerlo.
    """

    def test_workflow_no_relaja_max_single_asset(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = coordinator.run(
            kyc_data=_build_kyc(contradictorio_payload),
            financial_goal=_build_goal(contradictorio_payload),
            client_id=contradictorio_payload["client_id"],
            advisor_id=contradictorio_payload["advisor_script"]["advisor_id"],
            ai_client=MockAIClient(
                scripted_responses=contradictorio_payload["ai_script"]
            ),
            advisor_interface=ScriptedAdvisorInterface(
                scripted_decisions=contradictorio_payload["advisor_script"]
            ),
            product_universe=universe,
            suitability_matrix=suitability,
            esg_metadata_store=esg_store,
            market_data_provider=market_data,
        )
        # El RiskBudget debe conservar su max_single_asset original (0.15)
        assert result.risk_budget is not None
        assert result.risk_budget.max_single_asset == pytest.approx(0.15)
        # Y el status debe reflejar la infactibilidad, no carteras "milagrosas"
        assert result.status == AdvisoryWorkflowStatus.BLOCKED_BY_PORTFOLIO_FEASIBILITY
        assert result.candidate_set is None


# ─────────────────────────────────────────────────────────────────────────
# Test 7 — to_dict JSON-serializable, sin enums crudos
# ─────────────────────────────────────────────────────────────────────────


class TestToDictSerialization:
    def test_no_enums_in_to_dict(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = coordinator.run(
            kyc_data=_build_kyc(contradictorio_payload),
            financial_goal=_build_goal(contradictorio_payload),
            client_id=contradictorio_payload["client_id"],
            advisor_id=contradictorio_payload["advisor_script"]["advisor_id"],
            ai_client=MockAIClient(
                scripted_responses=contradictorio_payload["ai_script"]
            ),
            advisor_interface=ScriptedAdvisorInterface(
                scripted_decisions=contradictorio_payload["advisor_script"]
            ),
            product_universe=universe,
            suitability_matrix=suitability,
            esg_metadata_store=esg_store,
            market_data_provider=market_data,
        )
        d = result.to_dict()

        def _no_enums(obj):
            from enum import Enum
            if isinstance(obj, Enum):
                return False
            if isinstance(obj, dict):
                return all(_no_enums(k) and _no_enums(v) for k, v in obj.items())
            if isinstance(obj, list):
                return all(_no_enums(x) for x in obj)
            return True

        assert _no_enums(d), "to_dict contiene un Enum crudo"

    def test_to_dict_es_json_dumps_serializable(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = coordinator.run(
            kyc_data=_build_kyc(contradictorio_payload),
            financial_goal=_build_goal(contradictorio_payload),
            client_id=contradictorio_payload["client_id"],
            advisor_id=contradictorio_payload["advisor_script"]["advisor_id"],
            ai_client=MockAIClient(
                scripted_responses=contradictorio_payload["ai_script"]
            ),
            advisor_interface=ScriptedAdvisorInterface(
                scripted_decisions=contradictorio_payload["advisor_script"]
            ),
            product_universe=universe,
            suitability_matrix=suitability,
            esg_metadata_store=esg_store,
            market_data_provider=market_data,
        )
        s = json.dumps(result.to_dict())
        parsed = json.loads(s)
        assert parsed["status"] == "blocked_by_portfolio_feasibility"
        # Roundtrip parcial: campos clave preservados
        assert parsed["client_id"] == contradictorio_payload["client_id"]
        assert parsed["approved_profile_name"] == "moderado"


# ─────────────────────────────────────────────────────────────────────────
# Test 8 — properties is_completed / has_portfolios / has_warnings
# ─────────────────────────────────────────────────────────────────────────


class TestProperties:
    def test_is_completed_false_cuando_blocked(
        self, coordinator, contradictorio_payload, universe, suitability,
        esg_store, market_data,
    ):
        result = coordinator.run(
            kyc_data=_build_kyc(contradictorio_payload),
            financial_goal=_build_goal(contradictorio_payload),
            client_id=contradictorio_payload["client_id"],
            advisor_id=contradictorio_payload["advisor_script"]["advisor_id"],
            ai_client=MockAIClient(
                scripted_responses=contradictorio_payload["ai_script"]
            ),
            advisor_interface=ScriptedAdvisorInterface(
                scripted_decisions=contradictorio_payload["advisor_script"]
            ),
            product_universe=universe,
            suitability_matrix=suitability,
            esg_metadata_store=esg_store,
            market_data_provider=market_data,
        )
        assert result.is_completed is False
        assert result.has_portfolios is False

    def test_has_portfolios_true_cuando_completed(
        self, coordinator, universe, suitability, esg_store,
    ):
        market = _extended_market_data_provider()
        result = _run_for_status(
            coordinator, universe, suitability, esg_store, market,
            approved_profile="moderado-agresivo",
        )
        assert result.has_portfolios is True
        assert result.is_completed is True

    def test_has_warnings_funciona(
        self, coordinator, universe, suitability, esg_store,
    ):
        market = _extended_market_data_provider()
        result = _run_for_status(
            coordinator, universe, suitability, esg_store, market,
            approved_profile="moderado-agresivo",
        )
        # En este universo extendido hay tickers sin metadata ESG → UNKNOWN
        # → warning. Verificamos la coherencia entre has_warnings y warnings.
        assert result.has_warnings == (len(result.warnings) > 0)

    def test_is_completed_solo_para_estados_completed(self):
        from risk_first_advisory.workflow_layer.advisory_workflow import (
            AdvisoryWorkflowResult,
        )
        # Construimos un AdvisoryWorkflowResult sintético para cada estado
        for status, expected_completed in [
            (AdvisoryWorkflowStatus.COMPLETED, True),
            (AdvisoryWorkflowStatus.COMPLETED_WITH_WARNINGS, True),
            (AdvisoryWorkflowStatus.BLOCKED_BY_GOAL_FEASIBILITY, False),
            (AdvisoryWorkflowStatus.BLOCKED_BY_PORTFOLIO_FEASIBILITY, False),
            (AdvisoryWorkflowStatus.BLOCKED_BY_EMPTY_UNIVERSE, False),
        ]:
            r = AdvisoryWorkflowResult(
                status=status,
                client_id="X",
                approved_profile_name="moderado",
                advisor_comment="",
                m1_result=None,
                goal_feasibility_result=None,
                risk_budget=None,
                governance_passed_tickers=[],
                suitability_passed_tickers=[],
                esg_blocked_tickers=[],
                data_quality_failed_tickers=[],
                final_optimizer_tickers=[],
                return_estimates=[],
                covariance_matrix=None,
                portfolio_feasibility_result=None,
                candidate_set=None,
            )
            assert r.is_completed is expected_completed


# ─────────────────────────────────────────────────────────────────────────
# Test 9 — Validaciones del dataclass AdvisoryWorkflowResult
# ─────────────────────────────────────────────────────────────────────────


class TestResultValidations:
    def _kwargs(self, **overrides):
        defaults = dict(
            status=AdvisoryWorkflowStatus.COMPLETED,
            client_id="C001",
            approved_profile_name="moderado",
            advisor_comment="",
            m1_result=None,
            goal_feasibility_result=None,
            risk_budget=None,
            governance_passed_tickers=[],
            suitability_passed_tickers=[],
            esg_blocked_tickers=[],
            data_quality_failed_tickers=[],
            final_optimizer_tickers=[],
            return_estimates=[],
            covariance_matrix=None,
            portfolio_feasibility_result=None,
            candidate_set=None,
        )
        defaults.update(overrides)
        return defaults

    def test_status_no_enum_lanza_error(self):
        with pytest.raises(ValueError, match="status"):
            AdvisoryWorkflowResult(**self._kwargs(status="completed"))  # type: ignore

    def test_client_id_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="client_id"):
            AdvisoryWorkflowResult(**self._kwargs(client_id=""))

    def test_approved_profile_vacio_lanza_error_si_no_failed(self):
        with pytest.raises(ValueError, match="approved_profile_name"):
            AdvisoryWorkflowResult(**self._kwargs(approved_profile_name=""))

    def test_approved_profile_vacio_es_valido_si_failed(self):
        r = AdvisoryWorkflowResult(**self._kwargs(
            status=AdvisoryWorkflowStatus.FAILED,
            approved_profile_name="",
        ))
        assert r.status == AdvisoryWorkflowStatus.FAILED

    def test_listas_no_son_lista_lanza_error(self):
        with pytest.raises(ValueError, match="reason_codes"):
            AdvisoryWorkflowResult(**self._kwargs(reason_codes="foo"))  # type: ignore
