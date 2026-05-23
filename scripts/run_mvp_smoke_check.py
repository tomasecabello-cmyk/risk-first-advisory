"""
run_mvp_smoke_check.py — Smoke check determinístico del MVP de risk-first-advisory.

Valida el flujo principal de punta a punta usando preferencias ya estructuradas,
sin llamar a OpenAI. Reproduce exactamente el pipeline de POST /ai/filtered-portfolio-demo
pero con un dict de preferencias fijo en lugar del resultado de la IA.

Pipeline validado:
    1. CSVInstrumentUniverseProvider.load()         — carga el universo fixture
    2. PreferenceFilterEngine.apply(universe, prefs) — filtro determinístico
    3. InstrumentMarketDataAdapter.to_many()         — convierte a snapshots proxy
    4. RiskBudget desde PROFILE_BASE_PARAMS          — sin KYCData
    5. ReturnEstimator + CovarianceEngine            — estimaciones de retorno/cov
    6. PortfolioGenerationCoordinator.generate()     — portfolios candidatos

Ejecución:
    python scripts/run_mvp_smoke_check.py
    python scripts/run_mvp_smoke_check.py --debug
"""

from __future__ import annotations

import argparse
import math
import sys
import traceback
from pathlib import Path

# ── Hacer importable el paquete src/ aunque no esté instalado ────────────────
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ── Constantes de configuración ──────────────────────────────────────────────

PROFILE = "moderado"
CLIENT_ID = "SMOKE-CHECK-001"

UNIVERSE_CSV = (
    ROOT / "tests" / "fixtures" / "universe" / "sample_instrument_universe.csv"
)

# Preferencias equivalentes a:
#   "Solo quiero invertir en ONs hard dollar argentinas disponibles en Balanz
#    y evitar energia."
# Mismo dict de claves que entiende PreferenceFilterEngine.apply().
PREFERENCES: dict = {
    "allowed_instrument_types": ["CORPORATE_BOND"],
    "currency": "USD",
    "country": "Argentina",
    "entity": "Balanz",
    "hard_dollar_only": True,
    "avoid_sectors": ["Energy"],
}

# ── Umbrales de verificación ─────────────────────────────────────────────────

MIN_ELIGIBLE = 7       # Paso 4: eligible_count >= 7
MIN_SNAPSHOTS = 7      # Paso 6: snapshot_count (usables) >= 7
MIN_CANDIDATES = 1     # Paso 11: candidate_count >= 1

# ── Formato de salida ────────────────────────────────────────────────────────

LINE = "=" * 60
THIN = "-" * 60


def _section(title: str) -> None:
    print()
    print(LINE)
    print(f"  {title}")
    print(LINE)


def _ok(label: str, value: str) -> None:
    print(f"  ✓  {label:<42} {value}")


def _fail_line(label: str, value: str) -> None:
    print(f"  ✗  {label:<42} {value}")


def _info(msg: str) -> None:
    print(f"     {msg}")


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


# ── Runner principal ─────────────────────────────────────────────────────────

def run_smoke_check(debug: bool = False) -> bool:  # noqa: C901
    """
    Ejecuta todos los pasos del smoke check.
    Devuelve True si todos los checks pasan, False en caso contrario.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    errors: list[str] = []

    print()
    print(LINE)
    print("  RISK-FIRST ADVISORY — MVP Smoke Check")
    print(f"  Profile : {PROFILE}")
    print(f"  Client  : {CLIENT_ID}")
    print(f"  Universe: {UNIVERSE_CSV.relative_to(ROOT)}")
    print(LINE)

    # ── Paso 1: Verificar que el CSV existe ──────────────────────────────────
    _section("Step 1 — Universe CSV")
    if not UNIVERSE_CSV.exists():
        msg = f"CSV not found: {UNIVERSE_CSV}"
        _fail_line("csv_exists", "MISSING")
        errors.append(msg)
        _print_result(errors)
        return False
    _ok("csv_exists", str(UNIVERSE_CSV.relative_to(ROOT)))

    # ── Paso 2: Cargar universo ──────────────────────────────────────────────
    _section("Step 2 — Load instrument universe")
    try:
        from risk_first_advisory.universe_layer import CSVInstrumentUniverseProvider
        universe = CSVInstrumentUniverseProvider(UNIVERSE_CSV).load()
    except Exception as exc:
        msg = f"CSVInstrumentUniverseProvider failed: {exc}"
        _fail_line("load_universe", "FAIL")
        if debug:
            traceback.print_exc()
        errors.append(msg)
        _print_result(errors)
        return False

    universe_count = len(universe.instruments)
    _ok("universe_count", str(universe_count))

    if universe_count == 0:
        msg = "Universe loaded but has 0 instruments."
        _fail_line("universe_count > 0", "FAIL")
        errors.append(msg)
        _print_result(errors)
        return False

    # ── Paso 3: Aplicar filtro ───────────────────────────────────────────────
    _section("Step 3 — PreferenceFilterEngine")
    _info(f"Preferences: {PREFERENCES}")
    try:
        from risk_first_advisory.universe_layer import PreferenceFilterEngine
        filter_result = PreferenceFilterEngine().apply(universe, PREFERENCES)
    except Exception as exc:
        msg = f"PreferenceFilterEngine.apply() failed: {exc}"
        _fail_line("filter_apply", "FAIL")
        if debug:
            traceback.print_exc()
        errors.append(msg)
        _print_result(errors)
        return False

    eligible_instruments = filter_result.eligible_universe.instruments
    eligible_count = len(eligible_instruments)
    excluded_count = len(filter_result.exclusions)
    applied_filters = list(filter_result.applied_filters)

    _ok("eligible_count", str(eligible_count))
    _ok("excluded_count", str(excluded_count))
    _info(f"applied_filters: {applied_filters}")
    if filter_result.warnings:
        _info(f"warnings: {list(filter_result.warnings)}")

    # ── Paso 4: Verificar eligible_count ────────────────────────────────────
    _section("Step 4 — Assert eligible_count >= " + str(MIN_ELIGIBLE))
    if eligible_count >= MIN_ELIGIBLE:
        _ok(f"eligible_count ({eligible_count}) >= {MIN_ELIGIBLE}", "PASS")
    else:
        msg = (
            f"eligible_count ({eligible_count}) < {MIN_ELIGIBLE}. "
            f"Eligible tickers: {[i.ticker for i in eligible_instruments]}"
        )
        _fail_line(f"eligible_count ({eligible_count}) >= {MIN_ELIGIBLE}", "FAIL")
        errors.append(msg)

    # ── Paso 5: Convertir a snapshots ────────────────────────────────────────
    _section("Step 5 — InstrumentMarketDataAdapter → snapshots")
    try:
        from risk_first_advisory.data_layer.instrument_market_data import (
            InstrumentMarketDataAdapter,
        )
        all_snapshots = InstrumentMarketDataAdapter().to_many(eligible_instruments)
    except Exception as exc:
        msg = f"InstrumentMarketDataAdapter.to_many() failed: {exc}"
        _fail_line("to_many", "FAIL")
        if debug:
            traceback.print_exc()
        errors.append(msg)
        _print_result(errors)
        return False

    usable_snapshots = [s for s in all_snapshots if s.is_usable]
    snapshot_count = len(usable_snapshots)
    non_usable = len(all_snapshots) - snapshot_count

    _ok("total_snapshots_produced", str(len(all_snapshots)))
    _ok("usable_snapshots", str(snapshot_count))
    if non_usable:
        _info(
            f"non-usable (missing return data): {non_usable} "
            f"— tickers: {[s.ticker for s in all_snapshots if not s.is_usable]}"
        )
    if debug:
        for s in usable_snapshots:
            _info(
                f"  {s.ticker:<8}  ret={_pct(s.expected_return_annual)}  "
                f"vol={_pct(s.volatility_annual)}  dur={s.duration}  "
                f"liq={s.liquidity_score:.2f}"
            )

    # ── Paso 6: Verificar snapshot_count ────────────────────────────────────
    _section("Step 6 — Assert snapshot_count >= " + str(MIN_SNAPSHOTS))
    if snapshot_count >= MIN_SNAPSHOTS:
        _ok(f"snapshot_count ({snapshot_count}) >= {MIN_SNAPSHOTS}", "PASS")
    else:
        msg = (
            f"snapshot_count ({snapshot_count}) < {MIN_SNAPSHOTS}. "
            "Too few usable market data snapshots for portfolio generation."
        )
        _fail_line(f"snapshot_count ({snapshot_count}) >= {MIN_SNAPSHOTS}", "FAIL")
        errors.append(msg)

    # ── Paso 7: Construir RiskBudget ─────────────────────────────────────────
    _section("Step 7 — RiskBudget for profile '" + PROFILE + "'")
    try:
        from risk_first_advisory.models.risk_budget import RiskBudget
        from risk_first_advisory.rules_layer.risk_budget_builder import (
            PROFILE_BASE_PARAMS,
        )
        params = dict(PROFILE_BASE_PARAMS[PROFILE])
        risk_budget = RiskBudget(
            profile_name=PROFILE,
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
            notes=["source=mvp_smoke_check"],
        )
    except Exception as exc:
        msg = f"RiskBudget construction failed: {exc}"
        _fail_line("build_risk_budget", "FAIL")
        if debug:
            traceback.print_exc()
        errors.append(msg)
        _print_result(errors)
        return False

    msa = risk_budget.max_single_asset
    required_min = math.ceil(1.0 / msa)
    _ok("profile", PROFILE)
    _ok("max_single_asset", _pct(msa))
    _ok("max_volatility", _pct(risk_budget.max_volatility))
    _ok("required_min_assets = ceil(1/msa)", str(required_min))

    # ── Paso 8: Verificar diversificación mínima ─────────────────────────────
    _section(f"Step 8 — Assert snapshot_count >= required_min ({required_min})")
    if snapshot_count >= required_min:
        _ok(
            f"snapshot_count ({snapshot_count}) >= required_min ({required_min})",
            "PASS",
        )
    else:
        msg = (
            f"snapshot_count ({snapshot_count}) < required_min ({required_min}). "
            f"Profile '{PROFILE}' with max_single_asset={_pct(msa)} "
            f"needs at least {required_min} assets to allocate 100%."
        )
        _fail_line(
            f"snapshot_count ({snapshot_count}) >= required_min ({required_min})",
            "FAIL",
        )
        errors.append(msg)

    # Abort early if diversification or snapshot checks already failed
    if errors:
        _print_result(errors)
        return False

    # ── Paso 9: ReturnEstimator + CovarianceEngine ───────────────────────────
    _section("Step 9 — ReturnEstimator + CovarianceEngine")
    try:
        from risk_first_advisory.data_layer.covariance import CovarianceEngine
        from risk_first_advisory.data_layer.return_estimator import ReturnEstimator

        return_estimates = ReturnEstimator().estimate_many(usable_snapshots)
        covariance_matrix = CovarianceEngine().build(usable_snapshots)
    except Exception as exc:
        msg = f"ReturnEstimator/CovarianceEngine failed: {exc}"
        _fail_line("return_estimates + covariance_matrix", "FAIL")
        if debug:
            traceback.print_exc()
        errors.append(msg)
        _print_result(errors)
        return False

    n_cov = len(covariance_matrix.tickers)
    _ok("return_estimates keys", str(len(return_estimates)))
    _ok("covariance_matrix shape", f"{n_cov} x {n_cov}")

    # ── Paso 10: PortfolioGenerationCoordinator ──────────────────────────────
    _section("Step 10 — PortfolioGenerationCoordinator.generate()")
    try:
        from risk_first_advisory.portfolio_layer.generation import (
            PortfolioGenerationCoordinator,
            PortfolioVariant,
        )
        candidate_set = PortfolioGenerationCoordinator().generate(
            client_id=CLIENT_ID,
            approved_profile_name=PROFILE,
            return_estimates=return_estimates,
            covariance_matrix=covariance_matrix,
            risk_budget=risk_budget,
        )
    except ValueError as exc:
        msg = f"PortfolioGenerationCoordinator.generate() raised ValueError: {exc}"
        _fail_line("generate() — infeasible", "FAIL")
        errors.append(msg)
        _print_result(errors)
        return False
    except Exception as exc:
        msg = f"PortfolioGenerationCoordinator.generate() failed: {exc}"
        _fail_line("generate()", "FAIL")
        if debug:
            traceback.print_exc()
        errors.append(msg)
        _print_result(errors)
        return False

    candidate_count = candidate_set.count
    variant_order = [PortfolioVariant.DEFENSIVE, PortfolioVariant.BALANCED, PortfolioVariant.GROWTH]

    _ok("candidate_count", str(candidate_count))
    for variant in variant_order:
        if variant not in candidate_set.candidates:
            _info(f"  [{variant.value}]  (not generated)")
            continue
        p = candidate_set.candidates[variant]
        meta = candidate_set.metadata.get(variant)
        override = (meta is not None and meta.requires_advisor_override)
        override_str = "  ⚠ advisor override required" if override else ""
        _info(
            f"  [{variant.value:<10}]  "
            f"ret={_pct(p.expected_return_annual)}  "
            f"vol={_pct(p.volatility_annual)}  "
            f"assets={p.number_of_assets}  "
            f"ok={p.constraints_satisfied}"
            f"{override_str}"
        )
        if debug and override and meta:
            _info(f"             exceeded: {list(meta.exceeded_constraints)}")
            _info(f"             codes:    {list(meta.reason_codes)}")

    # ── Paso 11: Verificar candidate_count ──────────────────────────────────
    _section("Step 11 — Assert candidate_count >= " + str(MIN_CANDIDATES))
    if candidate_count >= MIN_CANDIDATES:
        _ok(f"candidate_count ({candidate_count}) >= {MIN_CANDIDATES}", "PASS")
    else:
        msg = (
            f"candidate_count ({candidate_count}) < {MIN_CANDIDATES}. "
            "The optimizer could not generate any feasible portfolio variant."
        )
        _fail_line(f"candidate_count ({candidate_count}) >= {MIN_CANDIDATES}", "FAIL")
        errors.append(msg)

    _print_result(errors)
    return len(errors) == 0


def _print_result(errors: list[str]) -> None:
    """Imprime el resumen final con PASS o FAIL."""
    print()
    print(LINE)
    if errors:
        print("  FAIL — MVP smoke check found the following issues:")
        print(THIN)
        for i, err in enumerate(errors, 1):
            print(f"  {i}. {err}")
        print(LINE)
    else:
        print("  PASS — MVP smoke check completed successfully")
        print(LINE)
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MVP smoke check for risk-first-advisory (no OpenAI required).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Print extra detail: snapshot metrics, tracebacks on error.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    passed = run_smoke_check(debug=args.debug)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
