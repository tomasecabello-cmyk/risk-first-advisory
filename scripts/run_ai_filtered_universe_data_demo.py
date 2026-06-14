"""
run_ai_filtered_universe_data_demo.py

Demo de flujo completo:
  lenguaje natural → OpenAI (extracción de preferencias) → filtro de universo
  → InstrumentMarketDataAdapter → MarketDataSnapshot portfolio-ready.

No genera portfolios. No llama a yfinance. No toca el workflow.

Requisito: OPENAI_API_KEY configurada en el entorno.

Ejecución:
    python scripts/run_ai_filtered_universe_data_demo.py
    python scripts/run_ai_filtered_universe_data_demo.py --debug
    python scripts/run_ai_filtered_universe_data_demo.py \\
        --preferences "Solo quiero ETFs en USD disponibles en PPI."
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path
from typing import Any

# Forzar UTF-8 en stdout/stderr para que los caracteres Unicode (─, ✓, etc.)
# no fallen en terminales Windows con codepage cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Hacer importable el paquete src/ aunque no esté instalado ────────────────
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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
_CLIENT_ID = "CLI-PREF-001"
_DIVIDER = "─" * 72
_THIN = "·" * 72


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────


def _pct(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.{decimals}f}%"


def _fmt(value: Any, decimals: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def _col(text: str, width: int) -> str:
    """Left-align *text* in a field of *width* chars, truncating if needed."""
    s = str(text) if text is not None else "—"
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s.ljust(width)


def _header(title: str) -> str:
    return f"\n{_DIVIDER}\n  {title}\n{_DIVIDER}"


def _section(letter: str, title: str) -> str:
    return f"\n  {letter}. {title}\n{_THIN}"


# ─────────────────────────────────────────────────────────────────────────────
# Print sections
# ─────────────────────────────────────────────────────────────────────────────


def _print_preferences(prefs: str) -> None:
    print(_section("A", "Natural language preferences"))
    print(f"  {prefs}")


def _print_ai_prefs(ai: dict[str, Any]) -> None:
    print(_section("B", "AI extracted preferences"))

    def _list_or_none(val: list[str] | None) -> str:
        if not val:
            return "—"
        return ", ".join(val)

    rows = [
        ("allowed_instrument_types", _list_or_none(ai.get("allowed_instrument_types"))),
        ("currency",                  ai.get("currency") or "—"),
        ("country",                   ai.get("country") or "—"),
        ("entity",                    ai.get("entity") or "—"),
        ("hard_dollar_only",          str(ai.get("hard_dollar_only"))),
        ("avoid_sectors",             _list_or_none(ai.get("avoid_sectors"))),
        ("min_liquidity_score",       _fmt(ai.get("min_liquidity_score"), 2) if ai.get("min_liquidity_score") is not None else "—"),
        ("max_maturity_year",         str(ai.get("max_maturity_year")) if ai.get("max_maturity_year") else "—"),
        ("confidence",                f"{ai.get('confidence', 0.0):.0%}"),
    ]
    for label, value in rows:
        print(f"  {label:<28} {value}")


def _print_filter_result(eligible_count: int, excluded_count: int,
                          applied_filters: list[str], warnings: list[str]) -> None:
    print(_section("C", "Universe filter result"))
    print(f"  eligible_count   : {eligible_count}")
    print(f"  excluded_count   : {excluded_count}")
    print(f"  applied_filters  : {', '.join(applied_filters) if applied_filters else '—'}")
    if warnings:
        print("  warnings         :")
        for w in warnings:
            print(f"    ⚠  {w}")
    else:
        print("  warnings         : none")


def _print_eligible_table(instruments: list[Any]) -> None:
    print(_section("D", "Eligible instruments"))
    if not instruments:
        print("  (no eligible instruments)")
        return

    # Column widths
    W = [7, 20, 16, 8, 7, 13, 7, 8, 9]
    headers = ["ticker", "issuer", "type", "currency", "country",
               "sector", "ytm%", "duration", "liquidity"]
    sep = "  " + "  ".join("─" * w for w in W)

    print("  " + "  ".join(_col(h, W[i]) for i, h in enumerate(headers)))
    print(sep)
    for inst in instruments:
        ytm_display = f"{inst.ytm:.2f}" if inst.ytm is not None else "—"
        dur_display = f"{inst.duration:.1f}" if inst.duration is not None else "—"
        row = [
            inst.ticker,
            inst.issuer,
            inst.instrument_type.value,
            inst.currency,
            inst.country,
            inst.sector,
            ytm_display,
            dur_display,
            f"{inst.liquidity_score:.2f}",
        ]
        print("  " + "  ".join(_col(str(v), W[i]) for i, v in enumerate(row)))


def _print_exclusions(exclusions: list[Any]) -> None:
    print(_section("E", "Exclusions summary"))
    if not exclusions:
        print("  (no exclusions)")
        return

    W = [8, 60]
    headers = ["ticker", "reasons"]
    print("  " + "  ".join(_col(h, W[i]) for i, h in enumerate(headers)))
    print("  " + "  ".join("─" * w for w in W))
    for exc in exclusions:
        reasons_str = "; ".join(exc.reasons)
        print("  " + "  ".join(_col(v, W[i]) for i, v in enumerate([exc.ticker, reasons_str])))


def _print_snapshots(snapshots: list[Any]) -> None:
    print(_section("F", "Portfolio-ready snapshots"))
    if not snapshots:
        print("  (no snapshots generated)")
        return

    W = [7, 10, 10, 8, 9, 36]
    headers = ["ticker", "return%/yr", "vol%/yr", "duration", "liquidity", "notes (excerpt)"]
    sep = "  " + "  ".join("─" * w for w in W)

    print("  " + "  ".join(_col(h, W[i]) for i, h in enumerate(headers)))
    print(sep)
    for snap in snapshots:
        # Show first 2 notes, joined
        notes_excerpt = " | ".join(snap.notes[:2]) if snap.notes else "—"
        row = [
            snap.ticker,
            f"{snap.expected_return_annual * 100:.2f}",
            f"{snap.volatility_annual * 100:.2f}",
            f"{snap.duration:.1f}" if snap.duration is not None else "—",
            f"{snap.liquidity_score:.2f}",
            notes_excerpt,
        ]
        print("  " + "  ".join(_col(str(v), W[i]) for i, v in enumerate(row)))


def _print_readiness(snapshots: list[Any]) -> None:
    print(_section("G", "Readiness"))
    n = len(snapshots)
    if n >= 3:
        print("  ✓  READY FOR PORTFOLIO GENERATION")
        print(f"     {n} portfolio-ready snapshot(s) available.")
    else:
        print("  ✗  INSUFFICIENT ELIGIBLE SNAPSHOTS FOR DIVERSIFIED PORTFOLIO")
        print(
            f"     Current filters produced only {n} snapshot(s). "
            "Consider relaxing constraints or expanding universe."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main flow
# ─────────────────────────────────────────────────────────────────────────────


def run(preferences: str, debug: bool) -> None:
    # ── Imports (after sys.path patch) ────────────────────────────────────────
    from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient
    from risk_first_advisory.data_layer.instrument_market_data import (
        InstrumentMarketDataAdapter,
    )
    from risk_first_advisory.universe_layer.csv_provider import (
        CSVInstrumentUniverseProvider,
    )
    from risk_first_advisory.universe_layer.preference_filter import (
        PreferenceFilterEngine,
    )

    print(_header("RISK-FIRST ADVISORY — AI Filtered Universe Data Demo"))
    print(f"\n  client_id : {_CLIENT_ID}")
    print(f"  universe  : {_UNIVERSE_CSV.name}  ({_UNIVERSE_CSV})")

    # ── A. Natural language preferences ───────────────────────────────────────
    _print_preferences(preferences)

    # ── Step 1: AI extraction ─────────────────────────────────────────────────
    print("\n  [1/4] Calling OpenAI to extract structured preferences…")
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

    _print_ai_prefs(ai_result)

    # ── Step 2: Load CSV universe ─────────────────────────────────────────────
    print("\n  [2/4] Loading instrument universe from CSV…")
    if not _UNIVERSE_CSV.exists():
        print(f"\n  ✗  Universe CSV not found: {_UNIVERSE_CSV}")
        print("     Ensure the fixture file exists at tests/fixtures/universe/sample_instrument_universe.csv")
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

    # ── Step 3: Apply filter ──────────────────────────────────────────────────
    print("\n  [3/4] Applying preference filter…")
    filter_preferences = {k: v for k, v in ai_result.items() if k in _FILTER_KEYS}
    try:
        engine = PreferenceFilterEngine()
        filter_result = engine.apply(universe, filter_preferences)
    except ValueError as exc:
        print(f"\n  ✗  Preference filter failed (invalid preferences): {exc}")
        if debug:
            traceback.print_exc()
        return

    eligible_instruments = filter_result.eligible_universe.instruments
    print(f"     Eligible: {len(eligible_instruments)} / {len(universe)}  |  "
          f"Excluded: {len(filter_result.exclusions)}")

    _print_filter_result(
        eligible_count=len(eligible_instruments),
        excluded_count=len(filter_result.exclusions),
        applied_filters=filter_result.applied_filters,
        warnings=filter_result.warnings,
    )
    _print_eligible_table(eligible_instruments)
    _print_exclusions(filter_result.exclusions)

    # ── Step 4: Convert to snapshots ──────────────────────────────────────────
    print("\n  [4/4] Converting eligible instruments to MarketDataSnapshot…")
    adapter = InstrumentMarketDataAdapter()
    snapshots = adapter.to_many(eligible_instruments)
    skipped = len(eligible_instruments) - len(snapshots)
    if skipped:
        print(f"     Note: {skipped} instrument(s) skipped "
              "(unsupported type for snapshot conversion — e.g. ETF, STOCK, CEDEAR).")
    print(f"     Snapshots ready: {len(snapshots)}")

    _print_snapshots(snapshots)

    # ── G. Readiness ──────────────────────────────────────────────────────────
    _print_readiness(snapshots)

    print(f"\n{_DIVIDER}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Filtered Universe Data Demo — risk-first-advisory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/run_ai_filtered_universe_data_demo.py\n"
            "  python scripts/run_ai_filtered_universe_data_demo.py --debug\n"
            '  python scripts/run_ai_filtered_universe_data_demo.py '
            '--preferences "Solo quiero ETFs en USD."\n'
            "\n"
            "Requires OPENAI_API_KEY in the environment:\n"
            '  $env:OPENAI_API_KEY="sk-..."\n'
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
        "--debug",
        action="store_true",
        default=False,
        help="Show full stack traces on errors.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(preferences=args.preferences, debug=args.debug)
