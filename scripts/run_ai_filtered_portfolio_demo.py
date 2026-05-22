"""
run_ai_filtered_portfolio_demo.py

Demo de flujo completo hasta generación de portfolios:
  lenguaje natural → OpenAI (extracción de preferencias) → filtro de universo
  → InstrumentMarketDataAdapter → ReturnEstimator → CovarianceEngine
  → RiskBudget → PortfolioGenerationCoordinator → candidatos DEFENSIVE/BALANCED/GROWTH.

Si el universo filtrado produce menos de 3 snapshots usables, el script lo
indica claramente y termina sin intentar optimizar.

No persiste nada. No llama a yfinance. No toca el workflow.

Requisito: OPENAI_API_KEY configurada en el entorno.

Ejecución:
    python scripts/run_ai_filtered_portfolio_demo.py
    python scripts/run_ai_filtered_portfolio_demo.py --profile moderado --debug
    python scripts/run_ai_filtered_portfolio_demo.py \\
        --preferences "Solo quiero bonos soberanos y corporativos USD en Balanz."
"""

from __future__ import annotations

import argparse
import math
import sys
import traceback
from pathlib import Path
from typing import Any

# ── Hacer importable el paquete src/ aunque no esté instalado ────────────────
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Forzar UTF-8 en stdout/stderr para terminales Windows con cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Rutas ─────────────────────────────────────────────────────────────────────
_UNIVERSE_CSV = ROOT / "tests" / "fixtures" / "universe" / "sample_instrument_universe.csv"

# ── Claves del resultado de IA que se pasan al filtro determinístico ──────────
_FILTER_KEYS: frozenset[str] = frozenset({
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

_DEFAULT_PREFERENCES = (
    "Solo quiero invertir en ONs hard dollar argentinas "
    "disponibles en Balanz y evitar energia."
)
_CLIENT_ID = "CLI-PREF-PORT-001"
_DIVIDER = "─" * 72
_THIN = "·" * 72


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────


def _col(text: Any, width: int) -> str:
    s = str(text) if text is not None else "—"
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s.ljust(width)


def _pct(value: float, decimals: int = 2) -> str:
    return f"{value * 100:.{decimals}f}%"


def _header(title: str) -> str:
    return f"\n{_DIVIDER}\n  {title}\n{_DIVIDER}"


def _section(letter: str, title: str) -> str:
    return f"\n  {letter}. {title}\n{_THIN}"


def _list_or_none(val: list[str] | None) -> str:
    if not val:
        return "—"
    return ", ".join(val)


# ─────────────────────────────────────────────────────────────────────────────
# Print sections
# ─────────────────────────────────────────────────────────────────────────────


def _print_section_a(prefs: str) -> None:
    print(_section("A", "Natural language preferences"))
    print(f"  {prefs}")


def _print_section_b(ai: dict[str, Any]) -> None:
    print(_section("B", "AI extracted preferences"))
    rows = [
        ("allowed_instrument_types", _list_or_none(ai.get("allowed_instrument_types"))),
        ("currency",                 ai.get("currency") or "—"),
        ("country",                  ai.get("country") or "—"),
        ("entity",                   ai.get("entity") or "—"),
        ("hard_dollar_only",         str(ai.get("hard_dollar_only"))),
        ("avoid_sectors",            _list_or_none(ai.get("avoid_sectors"))),
        ("min_liquidity_score",      str(ai.get("min_liquidity_score")) if ai.get("min_liquidity_score") is not None else "—"),
        ("max_maturity_year",        str(ai.get("max_maturity_year")) if ai.get("max_maturity_year") else "—"),
        ("confidence",               f"{ai.get('confidence', 0.0):.0%}"),
    ]
    for label, value in rows:
        print(f"  {label:<28} {value}")


def _print_section_c(
    eligible_count: int,
    excluded_count: int,
    applied_filters: list[str],
    warnings: list[str],
) -> None:
    print(_section("C", "Universe filter result"))
    print(f"  eligible_count   : {eligible_count}")
    print(f"  excluded_count   : {excluded_count}")
    print(f"  applied_filters  : {', '.join(applied_filters) if applied_filters else '—'}")
    if warnings:
        for w in warnings:
            print(f"  ⚠  {w}")


def _print_section_d(snapshots: list[Any]) -> None:
    print(_section("D", "Portfolio-ready snapshots"))
    if not snapshots:
        print("  (none)")
        return
    W = [7, 10, 10, 8, 9]
    headers = ["ticker", "return/yr", "vol/yr", "duration", "liquidity"]
    print("  " + "  ".join(_col(h, W[i]) for i, h in enumerate(headers)))
    print("  " + "  ".join("─" * w for w in W))
    for snap in snapshots:
        row = [
            snap.ticker,
            _pct(snap.expected_return_annual),
            _pct(snap.volatility_annual),
            f"{snap.duration:.1f}" if snap.duration is not None else "—",
            f"{snap.liquidity_score:.2f}",
        ]
        print("  " + "  ".join(_col(v, W[i]) for i, v in enumerate(row)))


def _print_section_e(rb: Any) -> None:
    print(_section("E", "Risk budget"))
    rows = [
        ("profile_name",         rb.profile_name),
        ("target_volatility",    _pct(rb.target_volatility)),
        ("max_volatility",       _pct(rb.max_volatility)),
        ("max_drawdown",         _pct(rb.max_drawdown)),
        ("max_equity",           _pct(rb.max_equity)),
        ("max_high_yield",       _pct(rb.max_high_yield)),
        ("max_single_asset",     _pct(rb.max_single_asset)),
        ("max_sector_exposure",  _pct(rb.max_sector_exposure)),
        ("max_duration",         f"{rb.max_duration:.1f} yrs"),
        ("min_liquidity",        _pct(rb.min_liquidity)),
        ("preferred_currency",   rb.preferred_currency),
        ("complex_products",     str(rb.complex_products_allowed)),
    ]
    for label, value in rows:
        print(f"  {label:<28} {value}")


def _print_section_f_candidates(candidate_set: Any) -> None:
    print(_section("F", "Candidate portfolios"))
    variants = candidate_set.variants()
    if not variants:
        print("  (no candidates generated)")
        return

    for variant in variants:
        portfolio = candidate_set.get_candidate(variant)
        meta = candidate_set.metadata.get(variant)

        print(f"\n  ── {variant.value} ──────────────────────────────")
        print(f"  objective            : {portfolio.objective.value}")
        print(f"  expected_return/yr   : {_pct(portfolio.expected_return_annual)}")
        print(f"  volatility/yr        : {_pct(portfolio.volatility_annual)}")
        print(f"  risk_score           : {portfolio.risk_score:.4f}")
        print(f"  constraints_satisfied: {portfolio.constraints_satisfied}")

        if meta:
            print(f"  risk_budget_exceeded : {meta.risk_budget_exceeded}")
            print(f"  advisor_override     : {meta.requires_advisor_override}")
            if meta.exceeded_constraints:
                print(f"  exceeded_constraints : {', '.join(meta.exceeded_constraints)}")
            if meta.reason_codes:
                print(f"  reason_codes         : {', '.join(meta.reason_codes)}")

        if portfolio.reason_codes:
            print(f"  optimizer_codes      : {', '.join(portfolio.reason_codes)}")

        # Weights table (non-zero only, descending)
        active = {t: w for t, w in portfolio.weights.items() if w > 1e-6}
        if active:
            print(f"\n  {'ticker':<10}  {'weight':>8}")
            print(f"  {'─' * 10}  {'─' * 8}")
            for ticker, weight in sorted(active.items(), key=lambda x: -x[1]):
                print(f"  {ticker:<10}  {weight * 100:>7.2f}%")
        else:
            print("  (no active positions)")

    if candidate_set.notes:
        print(f"\n  Coordinator notes:")
        for note in candidate_set.notes:
            print(f"    • {note}")


def _print_blocked(n: int) -> None:
    print(_section("F", "Portfolio generation"))
    print("  ✗  PORTFOLIO GENERATION BLOCKED — INSUFFICIENT ELIGIBLE UNIVERSE")
    print(f"     Current filters produced only {n} usable snapshot(s).")
    print("     Consider relaxing constraints or expanding universe.")


def _required_min_assets(max_single_asset: float) -> int:
    """
    Minimum number of instruments needed to allocate 100% given max_single_asset.

    Example: max_single_asset=0.15 → ceil(1/0.15) = ceil(6.67) = 7
    """
    return math.ceil(1.0 / max_single_asset)


def _print_blocked_diversification(
    n: int, max_single_asset: float, required: int
) -> None:
    print(_section("F", "Portfolio generation"))
    print("  ✗  PORTFOLIO GENERATION BLOCKED — INSUFFICIENT DIVERSIFICATION CAPACITY")
    print(f"     Filtered universe has {n} usable snapshot(s).")
    print(f"     RiskBudget max_single_asset is {_pct(max_single_asset)}.")
    print(f"     At least {required} instruments are required to allocate 100%.")
    print(
        "     Consider relaxing constraints, expanding the universe, "
        "or reviewing max_single_asset."
    )


def _print_blocked_invalid_budget() -> None:
    print(_section("F", "Portfolio generation"))
    print("  ✗  PORTFOLIO GENERATION BLOCKED — INVALID RISK BUDGET")
    print("     max_single_asset must be > 0 to compute diversification requirements.")


# ─────────────────────────────────────────────────────────────────────────────
# Risk budget builder (mirrors _build_live_risk_budget in main.py)
# ─────────────────────────────────────────────────────────────────────────────


def _build_risk_budget(profile_name: str) -> Any:
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
        notes=["source=ai_filtered_portfolio_demo_script"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main flow
# ─────────────────────────────────────────────────────────────────────────────


def run(preferences: str, profile: str, debug: bool) -> None:
    from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient
    from risk_first_advisory.data_layer.covariance import CovarianceEngine
    from risk_first_advisory.data_layer.instrument_market_data import (
        InstrumentMarketDataAdapter,
    )
    from risk_first_advisory.data_layer.return_estimator import ReturnEstimator
    from risk_first_advisory.portfolio_layer.generation import (
        PortfolioGenerationCoordinator,
    )
    from risk_first_advisory.rules_layer.risk_budget_builder import PROFILE_BASE_PARAMS
    from risk_first_advisory.universe_layer.csv_provider import (
        CSVInstrumentUniverseProvider,
    )
    from risk_first_advisory.universe_layer.preference_filter import (
        PreferenceFilterEngine,
    )

    # Validate profile early
    if profile not in PROFILE_BASE_PARAMS:
        valid = sorted(PROFILE_BASE_PARAMS.keys())
        print(f"\n  ✗  Unknown profile: {profile!r}")
        print(f"     Valid profiles: {', '.join(valid)}")
        return

    print(_header("RISK-FIRST ADVISORY — AI Filtered Portfolio Demo"))
    print(f"\n  client_id : {_CLIENT_ID}")
    print(f"  profile   : {profile}")
    print(f"  universe  : {_UNIVERSE_CSV.name}  ({_UNIVERSE_CSV})")

    # ── A ─────────────────────────────────────────────────────────────────────
    _print_section_a(preferences)

    # ── Step 1: AI extraction ─────────────────────────────────────────────────
    print(f"\n  [1/5] Calling OpenAI to extract structured preferences…")
    try:
        client = OpenAIProfileClient()
    except ValueError as exc:
        print("\n  ✗  OPENAI_API_KEY is not configured.")
        print("     Set it before running this script:")
        print('     $env:OPENAI_API_KEY="your_key_here"')
        print(f"\n     Detail: {exc}")
        return
    except ImportError as exc:
        print(f"\n  ✗  Import error: {exc}")
        return

    payload = {
        "client_id": _CLIENT_ID,
        "natural_language_preferences": preferences,
        "kyc_context": None,
        "previous_profile_analysis": None,
    }
    try:
        ai_result = client.extract_investment_preferences(payload)
    except ValueError as exc:
        print(f"\n  ✗  OpenAI call failed: {exc}")
        if debug:
            traceback.print_exc()
        return

    _print_section_b(ai_result)

    # ── Step 2: Load CSV universe ─────────────────────────────────────────────
    print(f"\n  [2/5] Loading instrument universe from CSV…")
    if not _UNIVERSE_CSV.exists():
        print(f"\n  ✗  Universe CSV not found: {_UNIVERSE_CSV}")
        return

    try:
        provider = CSVInstrumentUniverseProvider(_UNIVERSE_CSV)
        universe = provider.load()
    except Exception as exc:
        print(f"\n  ✗  Failed to load universe CSV: {exc}")
        if debug:
            traceback.print_exc()
        return

    print(f"     Loaded {len(universe)} instruments.")

    # ── Step 3: Filter ────────────────────────────────────────────────────────
    print(f"\n  [3/5] Applying preference filter…")
    filter_preferences = {k: v for k, v in ai_result.items() if k in _FILTER_KEYS}
    try:
        filter_result = PreferenceFilterEngine().apply(universe, filter_preferences)
    except ValueError as exc:
        print(f"\n  ✗  Preference filter failed (invalid preferences): {exc}")
        if debug:
            traceback.print_exc()
        return

    eligible_instruments = filter_result.eligible_universe.instruments
    print(f"     Eligible: {len(eligible_instruments)} / {len(universe)}  |  "
          f"Excluded: {len(filter_result.exclusions)}")

    _print_section_c(
        eligible_count=len(eligible_instruments),
        excluded_count=len(filter_result.exclusions),
        applied_filters=filter_result.applied_filters,
        warnings=filter_result.warnings,
    )

    # ── Step 4: Convert to snapshots ──────────────────────────────────────────
    print(f"\n  [4/5] Converting eligible instruments to MarketDataSnapshot…")
    all_snapshots = InstrumentMarketDataAdapter().to_many(eligible_instruments)
    usable_snapshots = [s for s in all_snapshots if s.is_usable]

    skipped_type = len(eligible_instruments) - len(all_snapshots)
    skipped_dq = len(all_snapshots) - len(usable_snapshots)
    if skipped_type:
        print(f"     Skipped {skipped_type} instrument(s): unsupported type "
              "(ETF / STOCK / CEDEAR — no adapter for these).")
    if skipped_dq:
        print(f"     Skipped {skipped_dq} snapshot(s): missing critical fields "
              "(no ytm or coupon_rate available).")
    print(f"     Usable snapshots: {len(usable_snapshots)}")

    _print_section_d(usable_snapshots)

    # ── Block check 1: absolute minimum ──────────────────────────────────────
    if len(usable_snapshots) < 3:
        _print_blocked(len(usable_snapshots))
        print(f"\n{_DIVIDER}\n")
        return

    # ── Build risk budget (needed for diversification pre-check) ──────────────
    risk_budget = _build_risk_budget(profile)

    # ── Block check 2: diversification capacity ───────────────────────────────
    msa = risk_budget.max_single_asset
    if msa <= 0.0:
        _print_blocked_invalid_budget()
        print(f"\n{_DIVIDER}\n")
        return

    required_min = _required_min_assets(msa)
    if len(usable_snapshots) < required_min:
        _print_blocked_diversification(
            n=len(usable_snapshots),
            max_single_asset=msa,
            required=required_min,
        )
        print(f"\n{_DIVIDER}\n")
        return

    # ── Step 5: Portfolio generation ──────────────────────────────────────────
    print(f"\n  [5/5] Generating candidate portfolios…")

    return_estimates = ReturnEstimator().estimate_many(usable_snapshots)
    covariance_matrix = CovarianceEngine().build(usable_snapshots)

    _print_section_e(risk_budget)

    try:
        candidate_set = PortfolioGenerationCoordinator().generate(
            client_id=_CLIENT_ID,
            approved_profile_name=profile,
            return_estimates=return_estimates,
            covariance_matrix=covariance_matrix,
            risk_budget=risk_budget,
        )
    except ValueError as exc:
        print(_section("F", "Portfolio generation"))
        print("  ✗  No feasible portfolio could be generated with the filtered "
              "universe and approved risk budget.")
        print(f"     {exc}")
        if debug:
            traceback.print_exc()
        print(f"\n{_DIVIDER}\n")
        return

    print(f"     Generated {candidate_set.count} candidate(s): "
          f"{', '.join(v.value for v in candidate_set.variants())}")

    _print_section_f_candidates(candidate_set)
    print(f"\n{_DIVIDER}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Filtered Portfolio Demo — risk-first-advisory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/run_ai_filtered_portfolio_demo.py\n"
            "  python scripts/run_ai_filtered_portfolio_demo.py --profile moderado-agresivo\n"
            '  python scripts/run_ai_filtered_portfolio_demo.py '
            '--preferences "Solo quiero bonos soberanos y corporativos USD en Balanz."\n'
            "\n"
            "Requires OPENAI_API_KEY in the environment:\n"
            '  $env:OPENAI_API_KEY="sk-..."\n'
            "\n"
            "Valid profiles:\n"
            "  conservador, moderado-defensivo, moderado, moderado-agresivo, agresivo\n"
        ),
    )
    parser.add_argument(
        "--preferences",
        type=str,
        default=_DEFAULT_PREFERENCES,
        help=(
            "Natural language investment preferences "
            f'(default: "{_DEFAULT_PREFERENCES}")'
        ),
    )
    parser.add_argument(
        "--profile",
        type=str,
        default="moderado",
        help="Risk profile to use for the RiskBudget (default: moderado).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Show full stack traces on errors.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(preferences=args.preferences, profile=args.profile, debug=args.debug)
