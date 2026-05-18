"""
run_demo.py — Demo end-to-end de risk-first-advisory.

Interfaz de consola sobre AdvisoryWorkflowCoordinator. Carga fixtures,
invoca el workflow productivo y muestra el AdvisoryWorkflowResult.

NO duplica lógica del pipeline. NO aplica demo adjustment.
Si el RiskBudget aprobado resulta infactible, lo muestra y explica.

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

from risk_first_advisory.ai_layer.mock_ai_client import MockAIClient
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
from risk_first_advisory.portfolio_layer.generation import PortfolioVariant
from risk_first_advisory.rules_layer.esg_compliance import ESGMetadataStore
from risk_first_advisory.rules_layer.instrument_suitability import (
    InstrumentSuitabilityMatrix,
)
from risk_first_advisory.rules_layer.product_governance import ApprovedProductUniverse
from risk_first_advisory.workflow_layer import (
    AdvisoryWorkflowCoordinator,
    AdvisoryWorkflowResult,
    AdvisoryWorkflowStatus,
)


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
    if x is None:
        return "n/a"
    return f"{x * 100:.{decimals}f}%"


def _num(x, decimals: int = 4) -> str:
    if x is None:
        return "n/a"
    return f"{x:.{decimals}f}"


# ─────────────────────────────────────────────────────────────────────────
# Secciones de impresión
# ─────────────────────────────────────────────────────────────────────────

def _print_header(result: AdvisoryWorkflowResult) -> None:
    _section("RISK-FIRST ADVISORY — DEMO RUN")
    m1 = result.m1_result
    print(f"Client ID:                 {result.client_id}")
    if m1 is not None:
        print(f"Session ID:                {getattr(m1, 'session_id', 'n/a')}")
        print(f"Advisor ID:                {getattr(m1, 'advisor_id', 'n/a')}")
        prelim_initial = getattr(m1, "preliminary_profile_initial", None)
        if prelim_initial is not None:
            print(
                f"Preliminary profile (IA):  "
                f"{getattr(prelim_initial, 'profile_name', 'n/a')}"
            )
        prelim_revised = getattr(m1, "preliminary_profile_revised", None)
        if prelim_revised is not None:
            rounds = getattr(m1, "follow_up_rounds_executed", 0)
            print(
                f"Revised preliminary (IA):  "
                f"{getattr(prelim_revised, 'profile_name', 'n/a')} "
                f"(después de {rounds} ronda(s) de follow-up)"
            )
        modified = getattr(m1, "advisor_modified_profile", False)
        print(f"Advisor modified profile:  {modified}")
    print(f"Approved profile:          {result.approved_profile_name}")
    print(f"Workflow status:           {result.status.value}")
    if result.advisor_comment:
        print(f"Advisor comment:           {result.advisor_comment.strip()}")
    if result.reason_codes:
        print(f"Reason codes:              {result.reason_codes}")


def _print_goal_feasibility(result: AdvisoryWorkflowResult) -> None:
    report = result.goal_feasibility_result
    _subsection("Goal Feasibility")
    if report is None:
        print("- (not evaluated)")
        return
    print(f"- status:                  {report.status.value}")
    print(f"- required_return:         {_pct(report.required_return_annual)}")
    print(f"- achievable_return:       {_pct(report.achievable_return_annual)}")
    gap = report.gap
    print(f"- gap (req - achievable):  {_pct(gap) if gap is not None else 'n/a'}")
    print(f"- blocks_portfolio:        {report.block_portfolio_generation}")
    print(f"- reason:                  {report.reason}")


def _print_risk_budget(result: AdvisoryWorkflowResult) -> None:
    rb = result.risk_budget
    _subsection("Risk Budget")
    if rb is None:
        print("- (not built — goal feasibility blocked first)")
        return
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


def _print_universe(result: AdvisoryWorkflowResult) -> None:
    _subsection("Universe")
    gov = result.governance_passed_tickers
    suit = result.suitability_passed_tickers
    esg_blocked = result.esg_blocked_tickers
    dq_failed = result.data_quality_failed_tickers
    final = result.final_optimizer_tickers
    print(f"- governance passed ({len(gov)}):   {gov}")
    print(f"- suitability passed ({len(suit)}):  {suit}")
    print(
        f"- ESG blocked ({len(esg_blocked)}):       "
        f"{esg_blocked if esg_blocked else '[]'}"
    )
    print(
        f"- data quality failed ({len(dq_failed)}): "
        f"{dq_failed if dq_failed else '[]'}"
    )
    print(f"- final optimizer universe ({len(final)}): {final}")
    if result.warnings:
        print("- warnings:")
        for w in result.warnings:
            print(f"    · {w}")


def _print_portfolio_feasibility(result: AdvisoryWorkflowResult) -> None:
    report = result.portfolio_feasibility_result
    _subsection("Portfolio Feasibility")
    if report is None:
        print("- (not evaluated)")
        return
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


def _print_portfolios(result: AdvisoryWorkflowResult) -> None:
    _subsection("Generated Portfolios")
    candidate_set = result.candidate_set
    if candidate_set is None:
        print("No portfolios generated.")
        if result.reason_codes:
            print(f"reason_codes: {result.reason_codes}")
        if result.notes:
            print("notes:")
            for note in result.notes:
                print(f"  · {note}")
        return

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


def _print_audit(result: AdvisoryWorkflowResult) -> None:
    _subsection("Audit")
    m1 = result.m1_result
    if m1 is None:
        print("- (m1_result not available)")
        return
    audit = getattr(m1, "audit", None)
    if audit is None:
        print("- (audit trail not available)")
        return
    events = getattr(audit, "events", [])
    is_closed = getattr(audit, "is_closed", False)
    print(f"- session events:          {len(events)}")
    print(f"- audit closed:            {is_closed}")
    if hasattr(audit, "event_types"):
        print("- event sequence:")
        for evt in audit.event_types():
            print(f"    · {evt}")


def _print_blocked_explanation(result: AdvisoryWorkflowResult) -> None:
    """Sección explicativa cuando el workflow queda bloqueado."""
    _subsection("Diagnóstico de bloqueo")
    print(f"El workflow terminó en: {result.status.value}")
    if result.status == AdvisoryWorkflowStatus.BLOCKED_BY_PORTFOLIO_FEASIBILITY:
        rb = result.risk_budget
        pf = result.portfolio_feasibility_result
        final = result.final_optimizer_tickers
        print()
        print(
            "El RiskBudget aprobado no es factible con el universo final."
        )
        if rb is not None and final:
            n = len(final)
            print(
                f"  max_single_asset aprobado: {_pct(rb.max_single_asset)}  "
                f"->  N * cap = {n} * {_pct(rb.max_single_asset)} = "
                f"{_pct(n * rb.max_single_asset)}"
            )
            if n * rb.max_single_asset < 1.0:
                print(
                    f"  Necesita al menos {_pct(1.0 / n)} por activo "
                    f"para sumar 100%."
                )
        if pf is not None and pf.failed_checks:
            print(f"  failed_checks: {pf.failed_checks}")
        print()
        print(
            "Política productiva: el workflow NO relaja el RiskBudget aprobado."
        )
        print(
            "Caminos de resolución (capa humana):"
        )
        print("  1. Asesor revisa y aprueba un perfil más agresivo.")
        print("  2. Ampliar el universo de instrumentos elegibles.")
        print("  3. Renegociar el cap de concentración con compliance.")
        print("  4. Ajustar manualmente el RiskBudget con justificación auditada.")
    elif result.status == AdvisoryWorkflowStatus.BLOCKED_BY_GOAL_FEASIBILITY:
        report = result.goal_feasibility_result
        if report is not None:
            print(f"  Motivo: {report.reason}")
            for action in report.suggested_actions:
                print(f"  · {action}")
    elif result.status == AdvisoryWorkflowStatus.BLOCKED_BY_EMPTY_UNIVERSE:
        print(
            "  No quedan instrumentos en el universo final tras governance, "
            "suitability, ESG y data quality."
        )


# ─────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    # Garantizar UTF-8 en stdout para notas del workflow que usan → y similares.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # ── 1. Carga del fixture KYC ──────────────────────────────────────
    fixture_payload = json.loads(KYC_FIXTURE.read_text(encoding="utf-8"))
    kyc = _build_kyc(fixture_payload)
    goal = _build_goal(fixture_payload)
    client_id = fixture_payload["client_id"]
    advisor_id = fixture_payload["advisor_script"]["advisor_id"]

    # ── 2. Construcción de dependencias ───────────────────────────────
    universe = ApprovedProductUniverse.from_yaml(UNIVERSE_YAML)
    suitability = InstrumentSuitabilityMatrix.from_yaml(SUITABILITY_YAML)
    esg_store = ESGMetadataStore.from_yaml(ESG_YAML)
    market_data = MockMarketDataProvider.from_yaml(MARKET_DATA_YAML)

    ai_client = MockAIClient(scripted_responses=fixture_payload["ai_script"])
    advisor_interface = ScriptedAdvisorInterface(
        scripted_decisions=fixture_payload["advisor_script"]
    )

    # ── 3. Flujo productivo completo ──────────────────────────────────
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

    # ── 4. Impresión del resultado ────────────────────────────────────
    _print_header(result)
    _print_goal_feasibility(result)
    _print_risk_budget(result)
    _print_universe(result)
    _print_portfolio_feasibility(result)
    _print_portfolios(result)

    if not result.is_completed:
        _print_blocked_explanation(result)

    _print_audit(result)

    print()
    print(LINE)
    print("DEMO RUN COMPLETED SUCCESSFULLY")
    print(LINE)


if __name__ == "__main__":
    main()
