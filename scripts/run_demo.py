"""
run_demo.py — Demo end-to-end de risk-first-advisory.

Ejecuta el flujo completo:
    KYC → IA → follow-up → asesor → approved_profile
        → GoalFeasibility
        → RiskBudget
        → Governance → Suitability → ESG → DataQuality
        → ReturnEstimator → CovarianceMatrix
        → 3 portfolios (DEFENSIVE, BALANCED, GROWTH)

Usa exclusivamente fixtures y mocks. NO toca IA real, Bloomberg ni datos
de mercado reales.

Ejecución:
    python scripts/run_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Hacer importable el paquete src/ aunque no esté instalado ────────────
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ── Imports del dominio ──────────────────────────────────────────────────
from risk_first_advisory.ai_layer.mock_ai_client import MockAIClient
from risk_first_advisory.data_layer.covariance import (
    CovarianceEngine,
    CovarianceMatrix,
)
from risk_first_advisory.data_layer.data_quality import (
    DataQualityGate,
    DataQualityResult,
    DataQualityStatus,
)
from risk_first_advisory.data_layer.market_data import (
    MarketDataSnapshot,
    MockMarketDataProvider,
)
from risk_first_advisory.data_layer.return_estimator import (
    ReturnEstimate,
    ReturnEstimator,
)
from risk_first_advisory.engine import M1SessionResult, RiskFirstSuitabilityEngine
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
from risk_first_advisory.portfolio_layer.feasibility import (
    PortfolioFeasibilityChecker,
    PortfolioFeasibilityResult,
)
from risk_first_advisory.portfolio_layer.generation import (
    PortfolioCandidateSet,
    PortfolioGenerationCoordinator,
    PortfolioVariant,
)
from risk_first_advisory.rules_layer.esg_compliance import (
    ESGComplianceChecker,
    ESGComplianceResult,
    ESGMetadataStore,
)
from risk_first_advisory.rules_layer.goal_feasibility import (
    FeasibilityReport,
    GoalFeasibilityEngine,
)
from risk_first_advisory.rules_layer.instrument_suitability import (
    InstrumentSuitabilityMatrix,
    InstrumentSuitabilityStatus,
)
from risk_first_advisory.rules_layer.product_governance import (
    ApprovedProductUniverse,
    ProductGovernanceRecord,
)
from risk_first_advisory.rules_layer.risk_budget_builder import RiskBudgetBuilder


# ─────────────────────────────────────────────────────────────────────────
# Paths a los fixtures
# ─────────────────────────────────────────────────────────────────────────

FIXTURES = ROOT / "tests" / "fixtures"
KYC_FIXTURE = FIXTURES / "kyc_profiles" / "contradictorio_alta_severidad.json"
UNIVERSE_YAML = FIXTURES / "universes" / "m1_universe.yaml"
SUITABILITY_YAML = FIXTURES / "suitability" / "instrument_matrix.yaml"
ESG_YAML = FIXTURES / "esg" / "instrument_esg_metadata.yaml"
MARKET_DATA_YAML = FIXTURES / "market_data" / "m1_market_data.yaml"


# ─────────────────────────────────────────────────────────────────────────
# Helpers para hidratar el fixture KYC → objetos de dominio
# (espejo de los helpers del test de integración M1)
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
# Helpers de formato
# ─────────────────────────────────────────────────────────────────────────

LINE = "=" * 60
SUBLINE = "-" * 60


def _section(title: str) -> None:
    print()
    print(LINE)
    print(title)
    print(LINE)


def _subsection(title: str) -> None:
    print()
    print(title)
    print(SUBLINE)


def _pct(x, decimals: int = 2) -> str:
    """Formatea un número en [0..1] como porcentaje. None → 'n/a'."""
    if x is None:
        return "n/a"
    return f"{x * 100:.{decimals}f}%"


def _num(x, decimals: int = 4) -> str:
    if x is None:
        return "n/a"
    return f"{x:.{decimals}f}"


# ─────────────────────────────────────────────────────────────────────────
# Pipeline de filtrado: governance → suitability → ESG → data quality
# ─────────────────────────────────────────────────────────────────────────

# Mapeo de instrument_type del universo → instrument_type de la matriz
# de suitability. Las claves son los `instrument_type` que aparecen en
# m1_universe.yaml; los valores son los `instrument_type` que la matriz
# entiende. Si el tipo no está mapeado, se usa tal cual.
_SUITABILITY_TYPE_ALIASES: dict[str, str] = {
    "equity_etf_sector": "sector_equity",
}


def _suitability_type_for(governance_record: ProductGovernanceRecord) -> str:
    raw = governance_record.instrument_type
    return _SUITABILITY_TYPE_ALIASES.get(raw, raw)


def _filter_universe(
    profile_name: str,
    universe: ApprovedProductUniverse,
    suitability: InstrumentSuitabilityMatrix,
    esg_store: ESGMetadataStore,
    esg_checker: ESGComplianceChecker,
    esg_profile: ESGProfile,
    market_provider: MockMarketDataProvider,
    dq_gate: DataQualityGate,
) -> tuple[
    list[str],                                  # final_universe
    list[ProductGovernanceRecord],              # governance_passed
    dict[str, str],                             # suitability_status_by_ticker
    dict[str, ESGComplianceResult],             # esg_by_ticker
    dict[str, DataQualityResult],               # dq_by_ticker
]:
    """Aplica todos los filtros y devuelve el universo final + auditoría."""
    governance_passed = universe.filter_for_profile(profile_name)

    # Suitability
    suitability_status: dict[str, str] = {}
    suitability_passed: list[ProductGovernanceRecord] = []
    for rec in governance_passed:
        rule = suitability.evaluate(
            _suitability_type_for(rec),
            profile_name,
        )
        suitability_status[rec.ticker] = rule.status.value
        if rule.status in (
            InstrumentSuitabilityStatus.ALLOWED,
            InstrumentSuitabilityStatus.LIMITED,
        ):
            suitability_passed.append(rec)

    # ESG
    esg_by_ticker: dict[str, ESGComplianceResult] = {}
    esg_passed: list[ProductGovernanceRecord] = []
    for rec in suitability_passed:
        result = esg_checker.evaluate(rec.ticker, esg_profile, esg_store)
        esg_by_ticker[rec.ticker] = result
        if not result.is_blocked:
            esg_passed.append(rec)

    # Data Quality (necesitamos primero el snapshot)
    dq_by_ticker: dict[str, DataQualityResult] = {}
    final_universe: list[str] = []
    for rec in esg_passed:
        snap = market_provider.get_snapshot(rec.ticker)
        if snap is None:
            # Sin datos de mercado: no puede pasar al optimizador.
            continue
        dq_result = dq_gate.evaluate(snap)
        dq_by_ticker[rec.ticker] = dq_result
        if dq_result.is_usable:
            final_universe.append(rec.ticker)

    return (
        final_universe,
        governance_passed,
        suitability_status,
        esg_by_ticker,
        dq_by_ticker,
    )


# ─────────────────────────────────────────────────────────────────────────
# Impresoras de cada sección
# ─────────────────────────────────────────────────────────────────────────

def _print_header(client_id: str, m1: M1SessionResult) -> None:
    _section("RISK-FIRST ADVISORY — DEMO RUN")
    print(f"Client ID:                 {client_id}")
    print(f"Session ID:                {m1.session_id}")
    print(f"Advisor ID:                {m1.advisor_id}")
    print(f"Preliminary profile (IA):  {m1.preliminary_profile_initial.profile_name}")
    if m1.preliminary_profile_revised is not None:
        print(
            f"Revised preliminary (IA):  "
            f"{m1.preliminary_profile_revised.profile_name} "
            f"(después de {m1.follow_up_rounds_executed} ronda(s) de follow-up)"
        )
    print(f"Approved profile:          {m1.approved_profile.profile_name}")
    print(f"Advisor modified profile:  {m1.advisor_modified_profile}")
    if m1.advisor_modified_profile:
        comment = m1.approved_profile.advisor_comment.strip()
        print(f"Advisor comment:           {comment}")


def _print_feasibility(report: FeasibilityReport) -> None:
    _subsection("Goal Feasibility")
    print(f"- status:                  {report.status.value}")
    print(f"- required_return:         {_pct(report.required_return_annual)}")
    print(f"- achievable_return:       {_pct(report.achievable_return_annual)}")
    gap = report.gap
    print(f"- gap (req - achievable):  {_pct(gap) if gap is not None else 'n/a'}")
    print(f"- blocks_portfolio:        {report.block_portfolio_generation}")
    print(f"- reason:                  {report.reason}")


def _print_risk_budget(rb) -> None:
    _subsection("Risk Budget")
    print(f"- profile_name:            {rb.profile_name}")
    print(f"- target_volatility:       {_pct(rb.target_volatility)}")
    print(f"- max_volatility:          {_pct(rb.max_volatility)}")
    print(f"- max_drawdown:            {_pct(rb.max_drawdown)}")
    print(f"- min_liquidity:           {_pct(rb.min_liquidity)}")
    print(f"- max_equity:              {_pct(rb.max_equity)}")
    print(f"- max_high_yield:          {_pct(rb.max_high_yield)}")
    print(f"- max_single_asset:        {_pct(rb.max_single_asset)}")
    print(f"- max_sector_exposure:     {_pct(rb.max_sector_exposure)}")
    print(f"- max_duration (years):    {rb.max_duration:.2f}")
    print(f"- complex_products_allowed:{rb.complex_products_allowed}")
    print(f"- preferred_currency:      {rb.preferred_currency}")


def _print_universe_summary(
    universe_total: int,
    governance_passed: list[ProductGovernanceRecord],
    suitability_status: dict[str, str],
    esg_by_ticker: dict[str, ESGComplianceResult],
    dq_by_ticker: dict[str, DataQualityResult],
    final_universe: list[str],
) -> None:
    _subsection("Universe")
    governance_passed_tickers = [r.ticker for r in governance_passed]
    suit_passed_tickers = [
        t for t, status in suitability_status.items()
        if status in ("allowed", "limited")
    ]
    esg_blocked_tickers = [
        t for t, r in esg_by_ticker.items() if r.is_blocked
    ]
    dq_failed_tickers = [
        t for t, r in dq_by_ticker.items()
        if r.status == DataQualityStatus.FAIL
    ]
    dq_warning_tickers = [
        t for t, r in dq_by_ticker.items()
        if r.status == DataQualityStatus.WARNING
    ]

    print(f"- universe loaded:         {universe_total} products")
    print(
        f"- governance passed ({len(governance_passed_tickers)}): "
        f"{governance_passed_tickers}"
    )
    print(
        f"- suitability passed ({len(suit_passed_tickers)}): "
        f"{suit_passed_tickers}"
    )
    print(
        f"- ESG blocked ({len(esg_blocked_tickers)}): "
        f"{esg_blocked_tickers if esg_blocked_tickers else '[]'}"
    )
    print(
        f"- data quality failed ({len(dq_failed_tickers)}): "
        f"{dq_failed_tickers if dq_failed_tickers else '[]'}"
    )
    print(
        f"- data quality warnings ({len(dq_warning_tickers)}): "
        f"{dq_warning_tickers if dq_warning_tickers else '[]'}"
    )
    print(
        f"- final optimizer universe ({len(final_universe)}): "
        f"{final_universe}"
    )


def _print_suitability_detail(
    suitability_status: dict[str, str],
) -> None:
    _subsection("Suitability Results (per governance-passed ticker)")
    if not suitability_status:
        print("- (no tickers passed governance)")
        return
    for ticker, status in suitability_status.items():
        print(f"- {ticker:<6} {status}")


def _print_esg_detail(esg_by_ticker: dict[str, ESGComplianceResult]) -> None:
    _subsection("ESG Compliance Results (per suitability-passed ticker)")
    if not esg_by_ticker:
        print("- (no tickers reached ESG checking)")
        return
    for ticker, r in esg_by_ticker.items():
        score = r.soft_score_adjustment
        score_str = f"score_adj={score:+.4f}" if score != 0.0 else "score_adj=0.0"
        extras = []
        if r.is_blocked:
            extras.append(f"blocked_by={r.blocked_by}")
        if r.has_warnings:
            extras.append(f"{len(r.warnings)} warning(s)")
        extra_str = "  " + " | ".join(extras) if extras else ""
        print(f"- {ticker:<6} {r.status.value:<14} {score_str}{extra_str}")


def _print_dq_detail(dq_by_ticker: dict[str, DataQualityResult]) -> None:
    _subsection("DataQuality Results (per ESG-passed ticker)")
    if not dq_by_ticker:
        print("- (no tickers reached data quality check)")
        return
    for ticker, r in dq_by_ticker.items():
        codes = ",".join(r.reason_codes) if r.reason_codes else "-"
        print(
            f"- {ticker:<6} {r.status.value:<8} usable={r.is_usable}  "
            f"reason_codes=[{codes}]"
        )


def _print_return_estimates(estimates: list[ReturnEstimate]) -> None:
    _subsection("Return Estimates (raw → adjusted)")
    for est in estimates:
        diff = est.adjusted_expected_return_annual - est.raw_expected_return_annual
        print(
            f"- {est.ticker:<6} "
            f"raw={_pct(est.raw_expected_return_annual)}  "
            f"adj={_pct(est.adjusted_expected_return_annual)}  "
            f"Δ={_pct(diff, decimals=3)}  "
            f"expense={_pct(est.expense_ratio, decimals=3)}  "
            f"esg_adj={est.esg_adjustment:+.4f}  "
            f"dq_adj={est.data_quality_adjustment:+.4f}"
        )


def _print_covariance_summary(cm: CovarianceMatrix) -> None:
    _subsection("Covariance Matrix (summary)")
    print(f"- tickers ({len(cm.tickers)}):     {cm.tickers}")
    print(f"- annualized:              {cm.annualized}")
    # Volatilidades implícitas en la diagonal de covarianza
    print("- volatilities (diag):")
    for i, t in enumerate(cm.tickers):
        var = cm.covariance[i][i]
        vol = var ** 0.5 if var > 0 else 0.0
        print(f"    {t:<6} vol={_pct(vol)}")
    # Resumen de correlaciones medias entre pares distintos
    n = len(cm.tickers)
    if n >= 2:
        offdiag = [
            cm.correlation[i][j]
            for i in range(n)
            for j in range(n)
            if i != j
        ]
        avg = sum(offdiag) / len(offdiag)
        mn = min(offdiag)
        mx = max(offdiag)
        print(
            f"- off-diagonal correlation: min={mn:.3f}  avg={avg:.3f}  max={mx:.3f}"
        )


def _print_feasibility_report(report: PortfolioFeasibilityResult) -> None:
    """
    Imprime el diagnóstico de PortfolioFeasibilityChecker para el RiskBudget
    aprobado original ANTES de invocar al coordinator. Hace explícito que la
    detección de infactibilidad NO viene del solver: viene de una capa de
    diagnóstico determinista y auditable.
    """
    _subsection("Portfolio Feasibility — Approved RiskBudget")
    print(f"- status:                          {report.status.value}")
    print(f"- is_feasible:                     {report.is_feasible}")
    print(f"- asset_count:                     {report.asset_count}")
    print(
        "- required_min_single_asset_cap:   "
        f"{report.required_min_single_asset_cap:.6f}"
    )
    print(
        "- actual_max_single_asset:         "
        f"{report.actual_max_single_asset:.6f}"
    )
    if report.min_achievable_volatility is None:
        min_vol_str = "n/a (no se pudo determinar)"
    else:
        min_vol_str = f"{report.min_achievable_volatility:.6f}"
    print(f"- min_achievable_volatility:       {min_vol_str}")
    print(
        "- max_allowed_volatility:          "
        f"{report.max_allowed_volatility:.6f}"
    )
    print(
        "- failed_checks:                   "
        f"{report.failed_checks if report.failed_checks else '[]'}"
    )
    print(
        "- warnings:                        "
        f"{report.warnings if report.warnings else '[]'}"
    )
    if report.suggested_actions:
        print("- suggested_actions:")
        for action in report.suggested_actions:
            print(f"    · {action}")
    else:
        print("- suggested_actions:               []")


def _print_portfolios(candidate_set: PortfolioCandidateSet) -> None:
    _subsection("Generated Portfolios")
    print(f"- client_id:               {candidate_set.client_id}")
    print(f"- approved_profile_name:   {candidate_set.approved_profile_name}")
    print(f"- candidates generated:    {candidate_set.count}")
    if candidate_set.reason_codes:
        print(f"- reason_codes:            {candidate_set.reason_codes}")
        for note in candidate_set.notes:
            print(f"    note: {note}")

    canonical_order = [
        PortfolioVariant.DEFENSIVE,
        PortfolioVariant.BALANCED,
        PortfolioVariant.GROWTH,
    ]
    for variant in canonical_order:
        if variant not in candidate_set.candidates:
            print()
            print(f"[{variant.value}]")
            print("  (no factible — variante omitida)")
            continue
        p = candidate_set.candidates[variant]
        print()
        print(f"[{variant.value}]  objective={p.objective.value}")
        print(f"  Expected return:       {_pct(p.expected_return_annual)}")
        print(f"  Volatility:            {_pct(p.volatility_annual)}")
        print(f"  Risk score (vol/cap):  {_num(p.risk_score, decimals=3)}")
        print(f"  Number of assets:      {p.number_of_assets}")
        print(f"  Constraints satisfied: {p.constraints_satisfied}")
        print("  Weights:")
        non_zero = sorted(
            ((t, w) for t, w in p.weights.items() if w > 0.0),
            key=lambda kv: -kv[1],
        )
        if not non_zero:
            print("    (cartera vacía)")
        for ticker, weight in non_zero:
            print(f"    - {ticker:<6} {_pct(weight)}")


def _print_audit(m1: M1SessionResult) -> None:
    _subsection("Audit")
    audit = m1.audit
    if audit is None:
        print("- (audit trail not available)")
        return
    print(f"- session events:          {len(audit.events)}")
    print(f"- audit closed:            {audit.is_closed}")
    print("- event sequence:")
    for evt in audit.event_types():
        print(f"    · {evt}")


# ─────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── Carga del fixture KYC ─────────────────────────────────────────
    fixture_payload = json.loads(KYC_FIXTURE.read_text(encoding="utf-8"))
    kyc = _build_kyc(fixture_payload)
    goal = _build_goal(fixture_payload)
    client_id = fixture_payload["client_id"]
    advisor_id = fixture_payload["advisor_script"]["advisor_id"]

    # ── Flujo M1 completo (IA → follow-up → asesor → audit) ───────────
    engine = RiskFirstSuitabilityEngine(
        ai_client=MockAIClient(scripted_responses=fixture_payload["ai_script"]),
        advisor_interface=ScriptedAdvisorInterface(
            scripted_decisions=fixture_payload["advisor_script"]
        ),
    )
    m1_result = engine.run_m1(
        kyc=kyc,
        financial_goal=goal,
        client_id=client_id,
        advisor_id=advisor_id,
    )

    approved_profile_name = m1_result.approved_profile.profile_name

    _print_header(client_id, m1_result)

    # ── GoalFeasibility ───────────────────────────────────────────────
    feasibility = GoalFeasibilityEngine().evaluate(goal, approved_profile_name)
    _print_feasibility(feasibility)

    # ── RiskBudget ────────────────────────────────────────────────────
    risk_budget = RiskBudgetBuilder().build(approved_profile_name, kyc, goal)
    _print_risk_budget(risk_budget)

    # ── Carga del universo + suitability + ESG + market data ─────────
    universe = ApprovedProductUniverse.from_yaml(UNIVERSE_YAML)
    suitability = InstrumentSuitabilityMatrix.from_yaml(SUITABILITY_YAML)
    esg_store = ESGMetadataStore.from_yaml(ESG_YAML)
    esg_checker = ESGComplianceChecker()
    market_provider = MockMarketDataProvider.from_yaml(MARKET_DATA_YAML)
    dq_gate = DataQualityGate()

    # ── Pipeline de filtrado ──────────────────────────────────────────
    (
        final_universe,
        governance_passed,
        suitability_status,
        esg_by_ticker,
        dq_by_ticker,
    ) = _filter_universe(
        profile_name=approved_profile_name,
        universe=universe,
        suitability=suitability,
        esg_store=esg_store,
        esg_checker=esg_checker,
        esg_profile=kyc.esg_profile,
        market_provider=market_provider,
        dq_gate=dq_gate,
    )

    _print_universe_summary(
        universe_total=len(universe),
        governance_passed=governance_passed,
        suitability_status=suitability_status,
        esg_by_ticker=esg_by_ticker,
        dq_by_ticker=dq_by_ticker,
        final_universe=final_universe,
    )
    _print_suitability_detail(suitability_status)
    _print_esg_detail(esg_by_ticker)
    _print_dq_detail(dq_by_ticker)

    # ── Si feasibility bloquea, no avanzamos a portfolios ─────────────
    if feasibility.block_portfolio_generation:
        _section("PORTFOLIO GENERATION SKIPPED")
        print(
            "GoalFeasibilityEngine bloqueó la generación de portfolios.\n"
            f"Motivo: {feasibility.reason}"
        )
        for action in feasibility.suggested_actions:
            print(f"  · {action}")
        _print_audit(m1_result)
        return

    # ── Si no hay universo final, tampoco podemos avanzar ─────────────
    if not final_universe:
        _section("PORTFOLIO GENERATION SKIPPED")
        print(
            "El universo final está vacío tras governance, suitability, "
            "ESG y data quality. No hay instrumentos para optimizar."
        )
        _print_audit(m1_result)
        return

    # ── ReturnEstimates ───────────────────────────────────────────────
    snapshots: list[MarketDataSnapshot] = []
    for t in final_universe:
        s = market_provider.get_snapshot(t)
        if s is not None:
            snapshots.append(s)

    estimator = ReturnEstimator()
    estimates = estimator.estimate_many(
        snapshots=snapshots,
        esg_results_by_ticker={t: esg_by_ticker[t] for t in final_universe},
        data_quality_results_by_ticker={
            t: dq_by_ticker[t] for t in final_universe
        },
    )
    _print_return_estimates(estimates)

    # ── CovarianceMatrix ──────────────────────────────────────────────
    covariance = CovarianceEngine().build(snapshots)
    _print_covariance_summary(covariance)

    # ── PortfolioFeasibilityChecker sobre el RiskBudget APROBADO ─────
    # Esta capa hace el diagnóstico ANTES de cualquier ajuste local del
    # demo, y muestra explícitamente por qué el RB aprobado puede no ser
    # factible con el universo final. El RB aprobado NO se modifica.
    feasibility_checker = PortfolioFeasibilityChecker()
    feasibility_report = feasibility_checker.evaluate(
        return_estimates=estimates,
        covariance_matrix=covariance,
        risk_budget=risk_budget,
    )
    _print_feasibility_report(feasibility_report)

    # ── Generación de los 3 portfolios ────────────────────────────────
    # Rama A (FEASIBLE): generamos con el RB aprobado tal como vino,
    #                    sin demo adjustment.
    # Rama B (INFEASIBLE): mantenemos el ajuste demo-only existente para
    #                    poder visualizar carteras. El RB aprobado NO se
    #                    modifica; solo construimos un budget paralelo
    #                    para el demo.
    # En producción la rama B disparaba la capa humana de infeasibility
    # resolution (4 caminos tipificados). Acá la simulamos solo para que
    # el demo pueda mostrar las 3 variantes.
    coordinator = PortfolioGenerationCoordinator()

    def _try_generate(rb_to_use):
        return coordinator.generate(
            client_id=client_id,
            approved_profile_name=approved_profile_name,
            return_estimates=estimates,
            covariance_matrix=covariance,
            risk_budget=rb_to_use,
        )

    candidate_set: PortfolioCandidateSet | None = None
    rb_used = risk_budget

    if feasibility_report.is_feasible:
        # Rama A — feasible: generamos directamente con el RB aprobado.
        try:
            candidate_set = _try_generate(risk_budget)
        except ValueError as exc:
            # Caso borde: pre-check del RB original pasó, pero el coordinator
            # internamente deriva budgets más estrictos para DEFENSIVE y/o el
            # solver falla. No aplicamos demo adjustment porque el contrato
            # del usuario es: si is_feasible=True, no relajamos nada.
            _section("PORTFOLIO GENERATION FAILED")
            print(
                "PortfolioFeasibilityChecker dictaminó FEASIBLE para el "
                "RiskBudget aprobado, pero la generación falló igual:"
            )
            print(f"  {exc}")
            print(
                "Causa típica: la variante DEFENSIVE deriva un sub-budget "
                "más estricto que el coordinator considera infactible "
                "internamente, y el resto de las variantes también fallaron "
                "en el solver."
            )
            _print_audit(m1_result)
            return
    else:
        # Rama B — infeasible: mensaje claro + demo adjustment.
        print()
        print(
            "Approved RiskBudget is not directly feasible with the final "
            "optimizer universe."
        )
        print(
            "El RiskBudget aprobado NO se modifica. Para que el demo pueda "
            "mostrar carteras, construimos un budget paralelo DEMO-ONLY a "
            "partir del diagnóstico anterior."
        )

        n_final = len(estimates)
        min_feasible_cap = (1.0 / n_final) + 1e-3

        # Vol mínima alcanzable del universo: w = (1/n,...,1/n) como cota
        # superior conservadora de la vol mínima (puede ser menor con
        # optimización, pero asegura factibilidad). Sumamos margen.
        eq_w = [1.0 / n_final] * n_final
        cov = covariance.covariance
        eq_var = sum(
            eq_w[i] * eq_w[j] * cov[i][j]
            for i in range(n_final)
            for j in range(n_final)
        )
        eq_vol = eq_var ** 0.5 if eq_var > 0 else 0.0
        demo_max_vol = max(risk_budget.max_volatility, eq_vol + 0.02)

        new_max_single = max(risk_budget.max_single_asset, min_feasible_cap)
        # Importante para DEFENSIVE: el coordinator deriva un sub-budget
        # con max_vol=min(rb.max_vol, rb.target_vol). Si target_vol no
        # supera la vol mínima del universo, DEFENSIVE queda infactible.
        # Igualamos target_volatility a demo_max_vol para mantener
        # consistencia con la relajación.
        new_target_vol = demo_max_vol

        from risk_first_advisory.models.risk_budget import RiskBudget

        demo_rb = RiskBudget(
            profile_name=risk_budget.profile_name,
            target_volatility=new_target_vol,
            max_volatility=demo_max_vol,
            max_drawdown=risk_budget.max_drawdown,
            min_liquidity=risk_budget.min_liquidity,
            max_equity=risk_budget.max_equity,
            max_high_yield=risk_budget.max_high_yield,
            max_single_asset=new_max_single,
            max_sector_exposure=risk_budget.max_sector_exposure,
            max_duration=risk_budget.max_duration,
            complex_products_allowed=risk_budget.complex_products_allowed,
            preferred_currency=risk_budget.preferred_currency,
            notes=list(risk_budget.notes) + [
                "DEMO-ONLY: budget relajado para garantizar factibilidad."
            ],
        )
        demo_adjustment_notes = [
            "Causas detectadas por el pre-check:",
            *(
                f"  · {fc}"
                for fc in feasibility_report.failed_checks
            ),
            "Ajustes locales del demo (NO modifican el RiskBudget aprobado):",
            f"  · max_single_asset → {new_max_single:.4f} "
            f"(original {risk_budget.max_single_asset:.4f})",
            f"  · max_volatility   → {demo_max_vol:.4f} "
            f"(original {risk_budget.max_volatility:.4f})",
            f"  · target_volatility → {new_target_vol:.4f} "
            f"(original {risk_budget.target_volatility:.4f})",
            "En producción esto dispara la capa de infeasibility "
            "(4 caminos tipificados).",
        ]

        _subsection("Demo Adjustment (DEMO-ONLY)")
        for line in demo_adjustment_notes:
            print(f"  {line}")

        try:
            candidate_set = _try_generate(demo_rb)
            rb_used = demo_rb
        except ValueError as exc:
            _section("PORTFOLIO GENERATION FAILED")
            print(
                "Ni siquiera con un budget relajado DEMO-ONLY se obtuvo "
                f"solución factible: {exc}"
            )
            _print_audit(m1_result)
            return

    _print_portfolios(candidate_set)

    if rb_used is not risk_budget:
        print()
        print(
            "(*) Portfolios generados con RiskBudget DEMO-ONLY relajado. "
            "El RiskBudget aprobado original no fue modificado."
        )

    # ── Audit final ───────────────────────────────────────────────────
    _print_audit(m1_result)

    print()
    print(LINE)
    print("DEMO RUN COMPLETED SUCCESSFULLY")
    print(LINE)


if __name__ == "__main__":
    main()