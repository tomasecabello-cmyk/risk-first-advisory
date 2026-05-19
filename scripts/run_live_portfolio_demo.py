"""
run_live_portfolio_demo.py

Demo de generación de portfolios reales usando datos de yfinance.

Pipeline completo:
    FreeMarketDataProvider → DataQualityGate → ReturnEstimator
    → CovarianceEngine → RiskBudget → PortfolioGenerationCoordinator

Para cada variante (DEFENSIVE / BALANCED / GROWTH) imprime:
    - Métricas del portfolio (retorno esperado, volatilidad, risk_score)
    - Pesos de los activos ordenados de mayor a menor
    - Metadatos de risk budget y advisor override (si aplica)

Uso:
    python scripts/run_live_portfolio_demo.py
    python scripts/run_live_portfolio_demo.py --profile moderado-agresivo
    python scripts/run_live_portfolio_demo.py --profile agresivo --period 2y
    python scripts/run_live_portfolio_demo.py --debug

Perfiles válidos:
    conservador, moderado-defensivo, moderado, moderado-agresivo, agresivo

Requiere conexión a internet. Si falla, muestra mensaje claro sin stacktrace
(salvo --debug). Siempre exit 0 para no fallar en entornos sin internet.
"""

from __future__ import annotations

import argparse
import sys
import traceback

# ─────────────────────────────────────────────────────────────────────────────
# Universo de ETFs (mismo que live_market_data_demo)
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
# Formateo
# ─────────────────────────────────────────────────────────────────────────────

_WIDE = 70


def _sep(char: str = "─", width: int = _WIDE) -> str:
    return char * width


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _print_section(title: str) -> None:
    print()
    print(_sep("─"))
    print(f"  {title}")
    print(_sep("─"))


# ─────────────────────────────────────────────────────────────────────────────
# Construcción de RiskBudget sin KYCData
# ─────────────────────────────────────────────────────────────────────────────

def _build_risk_budget_direct(profile_name: str):
    """
    Construye un RiskBudget directamente desde PROFILE_BASE_PARAMS sin
    pasar por RiskBudgetBuilder (que requiere KYCData y FinancialGoal completos).

    Usa min_liquidity=0.0 y preferred_currency="USD" como valores por defecto
    (el builder partiría también de 0.0 antes de aplicar ajustes de KYC).
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
        notes=["source=live_portfolio_demo", "kyc=synthetic_defaults"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Impresión de sección de market data
# ─────────────────────────────────────────────────────────────────────────────

def _print_market_data_section(
    usable_snapshots,
    dq_results_map: dict,
    return_estimates,
    failed_tickers: list[str],
) -> None:
    _print_section("MARKET DATA  (yfinance → DataQualityGate → ReturnEstimator)")

    col_w = {"ticker": 6, "dq": 9, "ret_raw": 10, "ret_adj": 10, "vol": 9, "liq": 8}
    header = (
        f"  {'TICKER':<{col_w['ticker']}}  "
        f"{'DQ':^{col_w['dq']}}  "
        f"{'RET_RAW%':>{col_w['ret_raw']}}  "
        f"{'RET_ADJ%':>{col_w['ret_adj']}}  "
        f"{'VOL%':>{col_w['vol']}}  "
        f"{'LIQUIDITY':>{col_w['liq']}}"
    )
    print(header)
    print("  " + "─" * (sum(col_w.values()) + len(col_w) * 2 + 2))

    # Mapa retornos por ticker
    ret_map = {re.ticker: re for re in return_estimates}

    for snap in usable_snapshots:
        t = snap.ticker
        dq = dq_results_map[t]
        re = ret_map.get(t)
        ret_raw = _pct(snap.expected_return_annual)
        ret_adj = _pct(re.adjusted_expected_return_annual) if re else "—"
        vol = _pct(snap.volatility_annual)
        liq = f"{snap.liquidity_score:.2f}"
        dq_status = dq.status.value if dq else "—"
        print(
            f"  {t:<{col_w['ticker']}}  "
            f"{dq_status:^{col_w['dq']}}  "
            f"{ret_raw:>{col_w['ret_raw']}}  "
            f"{ret_adj:>{col_w['ret_adj']}}  "
            f"{vol:>{col_w['vol']}}  "
            f"{liq:>{col_w['liq']}}"
        )

    if failed_tickers:
        print(f"\n  Sin datos suficientes / fallidos: {' '.join(failed_tickers)}")

    print(f"\n  Total usable: {len(usable_snapshots)} / {len(TICKERS)}")


# ─────────────────────────────────────────────────────────────────────────────
# Impresión de sección de risk budget
# ─────────────────────────────────────────────────────────────────────────────

def _print_risk_budget_section(risk_budget) -> None:
    _print_section(f"RISK BUDGET  (perfil: {risk_budget.profile_name})")
    rb = risk_budget
    print(f"  target_volatility    : {_pct(rb.target_volatility)}")
    print(f"  max_volatility       : {_pct(rb.max_volatility)}")
    print(f"  max_drawdown         : {_pct(rb.max_drawdown)}")
    print(f"  max_equity           : {_pct(rb.max_equity)}")
    print(f"  max_high_yield       : {_pct(rb.max_high_yield)}")
    print(f"  max_single_asset     : {_pct(rb.max_single_asset)}")
    print(f"  max_sector_exposure  : {_pct(rb.max_sector_exposure)}")
    print(f"  max_duration         : {rb.max_duration:.1f} años")
    print(f"  complex_products     : {rb.complex_products_allowed}")
    print(f"  min_liquidity        : {rb.min_liquidity:.2f}")


# ─────────────────────────────────────────────────────────────────────────────
# Impresión de portafolio candidato
# ─────────────────────────────────────────────────────────────────────────────

def _print_portfolio(variant_name: str, portfolio, metadata) -> None:
    print(f"\n  ── {variant_name} ──")

    # Métricas
    print(
        f"     Retorno esperado  : {_pct(portfolio.expected_return_annual)}"
    )
    print(
        f"     Volatilidad anual : {_pct(portfolio.volatility_annual)}"
    )
    print(
        f"     Risk score        : {portfolio.risk_score:.4f}"
    )
    print(
        f"     Constraints OK    : {portfolio.constraints_satisfied}"
    )

    # Metadata de override
    if metadata is not None:
        if metadata.requires_advisor_override:
            exceeded = ", ".join(metadata.exceeded_constraints) or "—"
            print(f"     ⚠  Requiere advisor override  (excede: {exceeded})")
        else:
            print(f"     ✓  Dentro del risk budget aprobado")

    # Pesos (ordenados mayor a menor, solo > 0)
    active_weights = {
        t: w for t, w in portfolio.weights.items() if w > 1e-6
    }
    if active_weights:
        sorted_weights = sorted(
            active_weights.items(), key=lambda kv: kv[1], reverse=True
        )
        print(f"\n     Pesos ({len(sorted_weights)} activos):")
        for ticker, weight in sorted_weights:
            bar_len = int(weight * 40)
            bar = "█" * bar_len
            print(f"       {ticker:<6}  {_pct(weight):>7}  {bar}")
    else:
        print("     (sin pesos > 0)")

    # Reason codes del portfolio (si los hay)
    if portfolio.reason_codes:
        codes = ", ".join(portfolio.reason_codes)
        print(f"\n     Reason codes: {codes}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main(profile: str, period: str, interval: str, debug: bool) -> int:
    # ── 0. Imports diferidos ───────────────────────────────────────────────
    try:
        from risk_first_advisory.data_layer.covariance import CovarianceEngine
        from risk_first_advisory.data_layer.data_quality import DataQualityGate
        from risk_first_advisory.data_layer.free_market_data import FreeMarketDataProvider
        from risk_first_advisory.data_layer.return_estimator import ReturnEstimator
        from risk_first_advisory.portfolio_layer.generation import PortfolioGenerationCoordinator
        from risk_first_advisory.rules_layer.risk_budget_builder import VALID_PROFILES
    except ImportError as exc:
        print(f"\n[ERROR] No se pudo importar el módulo: {exc}")
        print("Asegurate de correr desde el root del proyecto con el venv activado.")
        return 1

    # Validar perfil
    if profile not in VALID_PROFILES:
        valid = ", ".join(sorted(VALID_PROFILES))
        print(f"\n[ERROR] Perfil desconocido: {profile!r}")
        print(f"        Perfiles válidos: {valid}")
        return 1

    # ── Header ────────────────────────────────────────────────────────────
    print()
    print(_sep("="))
    print("  RISK-FIRST ADVISORY — Live Portfolio Demo")
    print(
        f"  Perfil: {profile}  |  período: {period}  |  intervalo: {interval}"
    )
    print(_sep("="))
    print()
    print("  Descargando datos de mercado desde yfinance...")
    print()

    # ── 1. Market data → DQ ───────────────────────────────────────────────
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
        return 0  # exit 0 para no fallar sin internet

    dq_gate = DataQualityGate()
    usable_snapshots = []
    dq_results_map: dict = {}
    failed_tickers: list[str] = []

    for ticker in TICKERS:
        try:
            snapshot = provider.get_snapshot(ticker)
        except Exception as exc:
            _handle_error(exc, debug, f"obtener snapshot de {ticker!r}")
            failed_tickers.append(ticker)
            continue

        if snapshot is None:
            failed_tickers.append(ticker)
            continue

        try:
            dq_result = dq_gate.evaluate(snapshot)
        except Exception as exc:
            _handle_error(exc, debug, f"DataQualityGate.evaluate({ticker!r})")
            failed_tickers.append(ticker)
            continue

        dq_results_map[ticker] = dq_result

        if dq_result.is_usable:
            usable_snapshots.append(snapshot)
        else:
            failed_tickers.append(ticker)

    if len(usable_snapshots) < 3:
        print(
            f"  [ERROR] Solo {len(usable_snapshots)} snapshot(s) usables. "
            "Se necesitan al menos 3 para optimizar."
        )
        print("         Verificar conexión a internet o disponibilidad de yfinance.")
        return 0

    # ── 2. Return estimates ───────────────────────────────────────────────
    try:
        estimator = ReturnEstimator()
        return_estimates = estimator.estimate_many(
            usable_snapshots,
            data_quality_results_by_ticker=dq_results_map,
        )
    except Exception as exc:
        _handle_error(exc, debug, "ReturnEstimator.estimate_many")
        return 0

    # ── 3. Covariance matrix ──────────────────────────────────────────────
    try:
        covariance_matrix = CovarianceEngine().build(usable_snapshots)
    except Exception as exc:
        _handle_error(exc, debug, "CovarianceEngine.build")
        return 0

    # ── 4. Risk budget ────────────────────────────────────────────────────
    try:
        risk_budget = _build_risk_budget_direct(profile)
    except Exception as exc:
        _handle_error(exc, debug, "construir RiskBudget")
        return 0

    # ── 5. Imprimir secciones de datos ────────────────────────────────────
    _print_market_data_section(
        usable_snapshots, dq_results_map, return_estimates, failed_tickers
    )
    _print_risk_budget_section(risk_budget)

    # ── 6. Generar portfolios ─────────────────────────────────────────────
    _print_section("PORTFOLIOS CANDIDATOS")

    try:
        coordinator = PortfolioGenerationCoordinator()
        candidate_set = coordinator.generate(
            client_id="DEMO-LIVE",
            approved_profile_name=profile,
            return_estimates=return_estimates,
            covariance_matrix=covariance_matrix,
            risk_budget=risk_budget,
        )
    except ValueError as exc:
        print(f"\n  [INFEASIBLE] Ninguna variante es factible: {exc}")
        print()
        print(_sep("="))
        print("  ⚠  LIVE PORTFOLIO DEMO — SIN PORTFOLIOS FACTIBLES")
        print(_sep("="))
        print()
        return 0
    except Exception as exc:
        _handle_error(exc, debug, "PortfolioGenerationCoordinator.generate")
        return 0

    # ── 7. Imprimir portafolios ───────────────────────────────────────────
    from risk_first_advisory.portfolio_layer.generation import PortfolioVariant

    variant_labels = {
        PortfolioVariant.DEFENSIVE: "DEFENSIVE  (mínima varianza)",
        PortfolioVariant.BALANCED: "BALANCED   (máxima utilidad)",
        PortfolioVariant.GROWTH: "GROWTH     (máximo retorno)",
    }

    portfolios_printed = 0
    for variant in [PortfolioVariant.DEFENSIVE, PortfolioVariant.BALANCED, PortfolioVariant.GROWTH]:
        if variant not in candidate_set.candidates:
            print(f"\n  ── {variant.value} ── [no generado / infactible]")
            continue
        portfolio = candidate_set.candidates[variant]
        metadata = candidate_set.metadata.get(variant)
        _print_portfolio(variant_labels[variant], portfolio, metadata)
        portfolios_printed += 1

    # ── 8. Reason codes del candidate set ─────────────────────────────────
    if candidate_set.reason_codes:
        print()
        print("  Reason codes del conjunto:")
        for rc in candidate_set.reason_codes:
            print(f"    • {rc}")

    # ── 9. Summary ─────────────────────────────────────────────────────────
    print()
    print(_sep("─"))
    print("  SUMMARY")
    print(_sep("─"))
    print(f"  Perfil aprobado      : {profile}")
    print(f"  Tickers configurados : {len(TICKERS)}")
    print(f"  Snapshots usables    : {len(usable_snapshots)}")
    print(f"  Portfolios generados : {portfolios_printed} / 3")
    if failed_tickers:
        print(f"  Sin datos            : {' '.join(failed_tickers)}")

    print()
    print(_sep("="))
    if portfolios_printed >= 1:
        print("  ✓  LIVE PORTFOLIO DEMO COMPLETED SUCCESSFULLY")
    else:
        print("  ⚠  LIVE PORTFOLIO DEMO COMPLETED — NINGUNA VARIANTE GENERADA")
    print(_sep("="))
    print()

    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Error handler
# ─────────────────────────────────────────────────────────────────────────────

def _handle_error(exc: Exception, debug: bool, context: str) -> None:
    if debug:
        print(f"\n[ERROR] Al {context}:")
        traceback.print_exc()
    else:
        msg = str(exc)
        exc_name = type(exc).__name__.lower()
        if any(kw in exc_name for kw in ("connection", "timeout", "network")):
            print(
                "\n[ERROR] No se pudieron descargar datos de mercado. "
                "Verificar conexión a internet o disponibilidad de yfinance."
            )
        elif "yfinance" in msg.lower() or "yahoo" in msg.lower():
            print(
                "\n[ERROR] No se pudieron descargar datos de mercado. "
                "Verificar conexión a internet o disponibilidad de yfinance."
            )
        else:
            print(f"\n[ERROR] Al {context}: {type(exc).__name__}: {msg}")
        print("         Ejecutar con --debug para ver el stacktrace completo.")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Demo de generación de portfolios con datos reales de yfinance. "
            "Pipeline completo: FreeMarketDataProvider → DataQualityGate → "
            "ReturnEstimator → CovarianceEngine → PortfolioGenerationCoordinator."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Perfiles válidos:
  conservador, moderado-defensivo, moderado, moderado-agresivo, agresivo

Ejemplos:
  python scripts/run_live_portfolio_demo.py
  python scripts/run_live_portfolio_demo.py --profile moderado-agresivo
  python scripts/run_live_portfolio_demo.py --profile agresivo --period 2y
  python scripts/run_live_portfolio_demo.py --debug
        """,
    )
    parser.add_argument(
        "--profile",
        default="moderado",
        help="Perfil de riesgo aprobado (default: moderado).",
    )
    parser.add_argument(
        "--period",
        default="3y",
        help="Período histórico para yfinance (ej. 1y, 2y, 3y). Default: 3y",
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
        exit_code = main(
            profile=args.profile,
            period=args.period,
            interval=args.interval,
            debug=args.debug,
        )
    except KeyboardInterrupt:
        print("\n[Interrumpido por el usuario]")
        exit_code = 0
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        else:
            print(
                "\n[ERROR] No se pudieron descargar datos de mercado. "
                "Verificar conexión a internet o disponibilidad de yfinance."
            )
            print("         Ejecutar con --debug para ver el stacktrace completo.")
        exit_code = 0   # exit 0: no fallar en entornos sin internet
    sys.exit(exit_code)
