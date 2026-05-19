"""
run_live_market_data_demo.py

Demo de datos de mercado reales usando FreeMarketDataProvider + DataQualityGate.

Descarga históricos de ETFs desde yfinance, construye MarketDataSnapshot para
cada ticker y pasa DataQualityGate. Imprime tabla de resultados y summary.

Uso:
    python scripts/run_live_market_data_demo.py
    python scripts/run_live_market_data_demo.py --period 2y
    python scripts/run_live_market_data_demo.py --period 1y --interval 1wk
    python scripts/run_live_market_data_demo.py --debug

Requiere conexión a internet. Si falla, mostrar mensaje claro sin stacktrace
(salvo --debug).
"""

from __future__ import annotations

import argparse
import sys
import traceback
from typing import NamedTuple

# ─────────────────────────────────────────────────────────────────────────────
# Universo de ETFs
# ─────────────────────────────────────────────────────────────────────────────

TICKERS: list[str] = [
    "BIL",   # SPDR Bloomberg 1-3 Month T-Bill ETF
    "SHV",   # iShares Short Treasury Bond ETF
    "AGG",   # iShares Core U.S. Aggregate Bond ETF
    "BND",   # Vanguard Total Bond Market ETF
    "IEF",   # iShares 7-10 Year Treasury Bond ETF
    "VTI",   # Vanguard Total Stock Market ETF
    "SPY",   # SPDR S&P 500 ETF
    "VEA",   # Vanguard FTSE Developed Markets ETF
    "VWO",   # Vanguard FTSE Emerging Markets ETF
    "HYG",   # iShares iBoxx $ High Yield Corporate Bond ETF
    "GLD",   # SPDR Gold Shares
]

ASSET_CLASS_MAP: dict[str, str] = {
    "BIL": "cash",
    "SHV": "cash",
    "AGG": "bond",
    "BND": "bond",
    "IEF": "bond",
    "VTI": "equity",
    "SPY": "equity",
    "VEA": "equity",
    "VWO": "equity",
    "HYG": "high_yield",
    "GLD": "commodity",
}

CURRENCY_MAP: dict[str, str] = {t: "USD" for t in TICKERS}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de formateo
# ─────────────────────────────────────────────────────────────────────────────

_COL_WIDTHS = {
    "ticker":                   6,
    "asset_class":              10,
    "currency":                 8,
    "expected_return_annual":   12,
    "volatility_annual":        10,
    "liquidity_score":          9,
    "dq_status":                9,
    "usable":                   6,
}

_HEADERS = {
    "ticker":                   "TICKER",
    "asset_class":              "ASSET_CLS",
    "currency":                 "CURRENCY",
    "expected_return_annual":   "RET_ANN%",
    "volatility_annual":        "VOL_ANN%",
    "liquidity_score":          "LIQUIDITY",
    "dq_status":                "DQ_STATUS",
    "usable":                   "USABLE",
}

_COLS = list(_COL_WIDTHS.keys())


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _row_separator() -> str:
    return "-" * (sum(_COL_WIDTHS.values()) + len(_COL_WIDTHS) * 3 + 1)


def _format_row(values: dict[str, str]) -> str:
    parts = []
    for col in _COLS:
        w = _COL_WIDTHS[col]
        parts.append(values.get(col, "").ljust(w)[:w])
    return "| " + " | ".join(parts) + " |"


def _header_row() -> str:
    return _format_row({col: _HEADERS[col] for col in _COLS})


# ─────────────────────────────────────────────────────────────────────────────
# Resultado por ticker
# ─────────────────────────────────────────────────────────────────────────────

class TickerResult(NamedTuple):
    ticker: str
    snapshot_loaded: bool
    usable: bool
    dq_status: str
    reason_codes: list[str]
    expected_return_annual: float | None
    volatility_annual: float | None
    liquidity_score: float | None
    asset_class: str | None
    currency: str | None


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main(period: str, interval: str, debug: bool) -> int:
    # Imports diferidos: si falta yfinance el error es claro aquí
    try:
        from risk_first_advisory.data_layer.data_quality import DataQualityGate
        from risk_first_advisory.data_layer.free_market_data import FreeMarketDataProvider
    except ImportError as exc:
        print(f"\n[ERROR] No se pudo importar el módulo: {exc}")
        print("Asegurate de correr desde el root del proyecto con el venv activado.")
        return 1

    print()
    print("=" * 70)
    print("  RISK-FIRST ADVISORY — Live Market Data Demo")
    print(f"  Universo: {len(TICKERS)} ETFs  |  período: {period}  |  intervalo: {interval}")
    print("=" * 70)
    print()
    print(f"  Descargando datos desde yfinance... (esto puede tardar unos segundos)")
    print()

    # ── 1. Construir provider ──────────────────────────────────────────────
    try:
        provider = FreeMarketDataProvider(
            tickers=TICKERS,
            asset_class_map=ASSET_CLASS_MAP,
            currency_map=CURRENCY_MAP,
            lookback_period=period,
            interval=interval,
        )
    except Exception as exc:
        _handle_error(exc, debug, "construir FreeMarketDataProvider")
        return 1

    dq_gate = DataQualityGate()
    results: list[TickerResult] = []

    # ── 2. Evaluar cada ticker ─────────────────────────────────────────────
    for ticker in TICKERS:
        try:
            snapshot = provider.get_snapshot(ticker)
        except Exception as exc:
            _handle_error(exc, debug, f"obtener snapshot de {ticker!r}")
            results.append(TickerResult(
                ticker=ticker,
                snapshot_loaded=False,
                usable=False,
                dq_status="error",
                reason_codes=["DOWNLOAD_ERROR"],
                expected_return_annual=None,
                volatility_annual=None,
                liquidity_score=None,
                asset_class=ASSET_CLASS_MAP.get(ticker),
                currency=CURRENCY_MAP.get(ticker),
            ))
            continue

        if snapshot is None:
            print(f"  [{ticker:>4}]  sin datos suficientes (< 60 observaciones o yfinance vacío)")
            results.append(TickerResult(
                ticker=ticker,
                snapshot_loaded=False,
                usable=False,
                dq_status="no_data",
                reason_codes=["INSUFFICIENT_DATA"],
                expected_return_annual=None,
                volatility_annual=None,
                liquidity_score=None,
                asset_class=ASSET_CLASS_MAP.get(ticker),
                currency=CURRENCY_MAP.get(ticker),
            ))
            continue

        try:
            dq_result = dq_gate.evaluate(snapshot)
        except Exception as exc:
            _handle_error(exc, debug, f"DataQualityGate.evaluate({ticker!r})")
            dq_result = None

        if dq_result is not None:
            results.append(TickerResult(
                ticker=ticker,
                snapshot_loaded=True,
                usable=dq_result.is_usable,
                dq_status=dq_result.status.value,
                reason_codes=list(dq_result.reason_codes),
                expected_return_annual=snapshot.expected_return_annual,
                volatility_annual=snapshot.volatility_annual,
                liquidity_score=snapshot.liquidity_score,
                asset_class=snapshot.asset_class,
                currency=snapshot.currency,
            ))
        else:
            results.append(TickerResult(
                ticker=ticker,
                snapshot_loaded=True,
                usable=snapshot.is_usable,
                dq_status="dq_error",
                reason_codes=["DQ_EVALUATION_ERROR"],
                expected_return_annual=snapshot.expected_return_annual,
                volatility_annual=snapshot.volatility_annual,
                liquidity_score=snapshot.liquidity_score,
                asset_class=snapshot.asset_class,
                currency=snapshot.currency,
            ))

    # ── 3. Imprimir tabla ──────────────────────────────────────────────────
    sep = _row_separator()
    print(sep)
    print(_header_row())
    print(sep)

    for r in results:
        if not r.snapshot_loaded:
            row = {
                "ticker":                   r.ticker,
                "asset_class":              r.asset_class or "—",
                "currency":                 r.currency or "—",
                "expected_return_annual":   "—",
                "volatility_annual":        "—",
                "liquidity_score":          "—",
                "dq_status":                r.dq_status,
                "usable":                   "false",
            }
        else:
            row = {
                "ticker":                   r.ticker,
                "asset_class":              r.asset_class or "—",
                "currency":                 r.currency or "—",
                "expected_return_annual":   _pct(r.expected_return_annual),
                "volatility_annual":        _pct(r.volatility_annual),
                "liquidity_score":          f"{r.liquidity_score:.2f}",
                "dq_status":                r.dq_status,
                "usable":                   "true" if r.usable else "false",
            }
        print(_format_row(row))

    print(sep)

    # ── 4. DQ warnings detail ─────────────────────────────────────────────
    warnings_to_show = [r for r in results if r.snapshot_loaded and r.reason_codes]
    if warnings_to_show:
        print()
        print("  Data Quality — reason codes:")
        for r in warnings_to_show:
            codes = ", ".join(r.reason_codes)
            print(f"    {r.ticker:>4}  {codes}")

    # ── 5. Summary ────────────────────────────────────────────────────────
    total = len(TICKERS)
    loaded = sum(1 for r in results if r.snapshot_loaded)
    usable_count = sum(1 for r in results if r.usable)
    failed_count = total - loaded

    print()
    print("─" * 40)
    print("  SUMMARY")
    print("─" * 40)
    print(f"  Total tickers configured : {total}")
    print(f"  Snapshots loaded         : {loaded}")
    print(f"  Usable snapshots         : {usable_count}")
    print(f"  Failed / no data         : {failed_count}")
    print()

    usable_tickers = [r.ticker for r in results if r.usable]
    failed_tickers = [r.ticker for r in results if not r.snapshot_loaded]

    if usable_tickers:
        print(f"  Usable  : {' '.join(usable_tickers)}")
    if failed_tickers:
        print(f"  Failed  : {' '.join(failed_tickers)}")

    # ── 6. Resultado final ────────────────────────────────────────────────
    print()
    print("=" * 70)
    if usable_count >= 3:
        print("  ✓  LIVE MARKET DATA DEMO COMPLETED SUCCESSFULLY")
    else:
        print("  ⚠  LIVE MARKET DATA DEMO COMPLETED WITH INSUFFICIENT DATA")
        print(f"     Solo {usable_count} snapshot(s) usable (se necesitan al menos 3).")
        if failed_count > 0:
            print("     Verificar conexión a internet o disponibilidad de yfinance.")
    print("=" * 70)
    print()

    return 0


def _handle_error(exc: Exception, debug: bool, context: str) -> None:
    if debug:
        print(f"\n[ERROR] Al {context}:")
        traceback.print_exc()
    else:
        msg = str(exc)
        if any(kw in type(exc).__name__.lower() for kw in ("connection", "timeout", "network")):
            print(
                "\n[ERROR] Could not download market data. "
                "Check internet connection or yfinance availability."
            )
        elif "yfinance" in msg.lower() or "yahoo" in msg.lower():
            print(
                "\n[ERROR] Could not download market data. "
                "Check internet connection or yfinance availability."
            )
        else:
            print(f"\n[ERROR] Al {context}: {type(exc).__name__}: {msg}")
        print("         Ejecutar con --debug para ver el stacktrace completo.")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Demo de FreeMarketDataProvider: descarga ETFs desde yfinance y aplica DataQualityGate.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/run_live_market_data_demo.py
  python scripts/run_live_market_data_demo.py --period 2y
  python scripts/run_live_market_data_demo.py --period 1y --interval 1wk
  python scripts/run_live_market_data_demo.py --debug
        """,
    )
    parser.add_argument(
        "--period",
        default="3y",
        help="Período histórico para yfinance (ej. 1y, 2y, 3y, 5y). Default: 3y",
    )
    parser.add_argument(
        "--interval",
        default="1d",
        help="Frecuencia de datos (ej. 1d, 1wk). Default: 1d",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Mostrar stacktrace completo en caso de error.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        exit_code = main(period=args.period, interval=args.interval, debug=args.debug)
    except KeyboardInterrupt:
        print("\n[Interrompido por el usuario]")
        exit_code = 0
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        else:
            print(
                "\n[ERROR] Could not download market data. "
                "Check internet connection or yfinance availability."
            )
            print("         Ejecutar con --debug para ver el stacktrace completo.")
        exit_code = 0   # exit 0: no queremos que falle en entornos sin internet
    sys.exit(exit_code)
