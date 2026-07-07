#!/usr/bin/env python
"""
build_arg_universe.py — genera un universo ARG amplio y LÍQUIDO desde data912.

Motivación (2026-07-04): el usuario quiere el universo argentino "completo". El
mercado listado tiene ~900 instrumentos, pero la mayoría no tiene liquidez real
(no se pueden comprar/vender) y los ONs corporativos ni siquiera exponen
histórico en data912 (404). "Completo" útil = el mercado ARG efectivamente
INVERTIBLE: acciones del Merval/panel, CEDEARs líquidos (dan exposición US en
ARS) y soberanos hard-dollar. Se completa con un núcleo de ETFs US (los activos
investment-grade / cash-like que Argentina no ofrece).

El script:
  1. Baja las categorías live de data912 (arg_stocks, arg_cedears, arg_bonds).
  2. Dedup de sufijos C/D (variantes CCL/MEP del mismo subyacente).
  3. Filtra por liquidez (volumen > umbral por categoría).
  4. Asigna metadata (mapa curado para los nombres conocidos + fallback limpio).
  5. Fusiona con el núcleo de ETFs US curado (US_ETF_CORE).
  6. Escribe tests/fixtures/universe/live_instrument_universe.csv.
  7. (--warm) precalienta el caché de LiveMarketDataProvider para que la primera
     propuesta de la demo no espere ~1.5s por instrumento.

Reproducible y extensible: es la semilla del "universo dinámico" (ver
docs/ROADMAP.md). No corre en el request path; se ejecuta a mano cuando
se quiere refrescar el universo demo.

Uso:
    python scripts/build_arg_universe.py            # genera el CSV
    python scripts/build_arg_universe.py --warm     # + precalienta el caché
    python scripts/build_arg_universe.py --max-cedears 40 --max-stocks 20
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "tests" / "fixtures" / "universe" / "live_instrument_universe.csv"
_DATA912 = "https://data912.com"

# Columnas del schema del universo (mismas que CSVInstrumentUniverseProvider).
_COLS = [
    "ticker", "name", "issuer", "instrument_type", "asset_class", "currency",
    "country", "sector", "available_entities", "hard_dollar", "liquidity_score",
    "maturity_date", "coupon_rate", "ytm", "duration", "min_piece", "rating", "notes",
]

_ALL_BROKERS = "Balanz;PPI;Cocos"

# ── Núcleo de ETFs US (yfinance) — investment-grade / cash-like / diversificación
# que el mercado ARG no ofrece. Se mantiene curado a mano.
US_ETF_CORE: list[dict] = [
    ("SPY", "SPDR S&P 500 ETF", "State Street", "EQUITY", "Broad Equity", 0.99),
    ("VTI", "Vanguard Total Stock Market", "Vanguard", "EQUITY", "Broad Equity", 0.97),
    ("QQQ", "Invesco QQQ Nasdaq 100", "Invesco", "EQUITY", "Technology", 0.97),
    ("IWM", "iShares Russell 2000", "BlackRock", "EQUITY", "Small Cap", 0.95),
    ("EFA", "iShares MSCI EAFE", "BlackRock", "EQUITY", "Developed Intl", 0.94),
    ("EEM", "iShares MSCI Emerging Markets", "BlackRock", "EQUITY", "Emerging Markets", 0.93),
    ("VNQ", "Vanguard Real Estate", "Vanguard", "EQUITY", "Real Estate", 0.92),
    ("XLK", "Technology Select Sector SPDR", "State Street", "EQUITY", "Technology", 0.95),
    ("XLE", "Energy Select Sector SPDR", "State Street", "EQUITY", "Energy", 0.94),
    ("XLF", "Financial Select Sector SPDR", "State Street", "EQUITY", "Financials", 0.94),
    ("XLV", "Health Care Select Sector SPDR", "State Street", "EQUITY", "Health Care", 0.94),
    ("XLP", "Consumer Staples Select SPDR", "State Street", "EQUITY", "Consumer Staples", 0.93),
    ("GLD", "SPDR Gold Shares", "State Street", "COMMODITY", "Commodities", 0.90),
    ("SLV", "iShares Silver Trust", "BlackRock", "COMMODITY", "Commodities", 0.85),
    ("DBC", "Invesco DB Commodity Index", "Invesco", "COMMODITY", "Commodities", 0.80),
]
# ETFs US de renta fija (asset_class FIXED_INCOME, con ytm/duration para el reporte)
US_ETF_BONDS: list[tuple] = [
    # ticker, name, issuer, sector, liq, ytm, duration
    ("TLT", "iShares 20+ Year Treasury", "BlackRock", "Treasuries", 0.95, 4.20, 16.5),
    ("IEF", "iShares 7-10 Year Treasury", "BlackRock", "Treasuries", 0.95, 4.30, 7.5),
    ("SHY", "iShares 1-3 Year Treasury", "BlackRock", "Treasuries", 0.96, 4.60, 1.9),
    ("BND", "Vanguard Total Bond Market", "Vanguard", "Aggregate Bonds", 0.97, 4.50, 6.0),
    ("AGG", "iShares Core US Aggregate Bond", "BlackRock", "Aggregate Bonds", 0.97, 4.50, 6.0),
    ("LQD", "iShares iBoxx IG Corporate", "BlackRock", "Corporate Bonds", 0.95, 5.20, 8.4),
    ("VCSH", "Vanguard Short-Term Corporate", "Vanguard", "Corporate Bonds", 0.94, 5.00, 2.6),
    ("TIP", "iShares TIPS Bond", "BlackRock", "Inflation Linked", 0.93, 4.10, 6.8),
    ("BIL", "SPDR 1-3 Month T-Bill", "State Street", "Cash Equivalents", 0.99, 4.80, 0.2),
    ("SHV", "iShares Short Treasury Bond", "BlackRock", "Cash Equivalents", 0.98, 4.70, 0.3),
]
US_ETF_HY: list[tuple] = [
    ("HYG", "iShares iBoxx High Yield Corp", "BlackRock", "High Yield", 0.92, 7.30, 3.4),
]

# ── Soberanos ARG hard-dollar (data912 arg_bonds) — set curado con cupón/ytm/dur.
SOBERANOS: list[tuple] = [
    # ticker, name, coupon, ytm, duration, liq
    ("GD29", "Bono Global 2029", 1.00, 11.7, 3.4, 0.80),
    ("GD30", "Bono Global 2030", 0.75, 11.5, 4.3, 0.85),
    ("GD35", "Bono Global 2035", 1.50, 11.8, 6.5, 0.82),
    ("GD38", "Bono Global 2038", 2.00, 11.6, 7.6, 0.78),
    ("GD41", "Bono Global 2041", 2.50, 11.4, 8.2, 0.74),
    ("GD46", "Bono Global 2046", 2.75, 11.3, 9.0, 0.70),
    ("AL29", "Bonar 2029", 1.00, 11.9, 3.4, 0.80),
    ("AL30", "Bonar 2030", 0.75, 12.2, 4.2, 0.83),
    ("AL35", "Bonar 2035", 1.50, 12.5, 6.2, 0.79),
    ("AL41", "Bonar 2041", 2.50, 12.1, 8.0, 0.72),
    ("AE38", "Bonar 2038", 2.00, 12.3, 7.2, 0.75),
]

# ── CEDEARs líquidos (data912 arg_cedears) — mapa curado symbol -> (nombre, sector).
# Cubre los reconocibles del top de liquidez; el resto cae al fallback genérico.
_CEDEAR_META: dict[str, tuple[str, str]] = {
    "AAPL": ("Apple", "Technology"), "MSFT": ("Microsoft", "Technology"),
    "NVDA": ("NVIDIA", "Technology"), "GOOGL": ("Alphabet", "Technology"),
    "META": ("Meta Platforms", "Technology"), "AMZN": ("Amazon", "Consumer Discretionary"),
    "TSLA": ("Tesla", "Consumer Discretionary"), "MELI": ("MercadoLibre", "Consumer Discretionary"),
    "NFLX": ("Netflix", "Communication Services"), "NOW": ("ServiceNow", "Technology"),
    "GLOB": ("Globant", "Technology"), "VIST": ("Vista Energy", "Energy"),
    "BKNG": ("Booking Holdings", "Consumer Discretionary"), "MSTR": ("MicroStrategy", "Technology"),
    "NU": ("Nubank", "Financials"), "BIOX": ("Bioceres", "Materials"),
    "VST": ("Vistra", "Utilities"), "V": ("Visa", "Financials"),
    "ACN": ("Accenture", "Technology"), "NIO": ("NIO", "Consumer Discretionary"),
    "KO": ("Coca-Cola", "Consumer Staples"), "ADBE": ("Adobe", "Technology"),
    "PEP": ("PepsiCo", "Consumer Staples"), "WMT": ("Walmart", "Consumer Staples"),
    "MCD": ("McDonald's", "Consumer Discretionary"), "MRNA": ("Moderna", "Health Care"),
    "BRKB": ("Berkshire Hathaway", "Financials"), "NKE": ("Nike", "Consumer Discretionary"),
    "AVGO": ("Broadcom", "Technology"), "PFE": ("Pfizer", "Health Care"),
    "BABA": ("Alibaba", "Consumer Discretionary"), "INTC": ("Intel", "Technology"),
    "ASML": ("ASML", "Technology"), "COIN": ("Coinbase", "Financials"),
    "MU": ("Micron", "Technology"), "VALE": ("Vale", "Materials"),
    "SHOP": ("Shopify", "Technology"), "PBR": ("Petrobras", "Energy"),
    "CEG": ("Constellation Energy", "Utilities"), "IBM": ("IBM", "Technology"),
    "LRCX": ("Lam Research", "Technology"), "JPM": ("JPMorgan", "Financials"),
    "XOM": ("Exxon Mobil", "Energy"), "JNJ": ("Johnson & Johnson", "Health Care"),
    "BB": ("BlackBerry", "Technology"), "ADGO": ("Adecoagro", "Consumer Staples"),
    "COST": ("Costco", "Consumer Staples"), "DIS": ("Walt Disney", "Communication Services"),
    "GOLD": ("Barrick Gold", "Materials"), "AMD": ("AMD", "Technology"),
    # ETFs listados como CEDEAR (asset_class EQUITY salvo materias primas):
    "SPY": ("SPDR S&P 500 (CEDEAR)", "Broad Equity"), "IVV": ("iShares S&P 500 (CEDEAR)", "Broad Equity"),
    "QQQ": ("Invesco Nasdaq 100 (CEDEAR)", "Technology"), "EEM": ("iShares Emerging Mkts (CEDEAR)", "Emerging Markets"),
    "EWZ": ("iShares Brazil (CEDEAR)", "LatAm Equity"), "XLE": ("Energy Sector (CEDEAR)", "Energy"),
    "XLF": ("Financial Sector (CEDEAR)", "Financials"), "XLK": ("Tech Sector (CEDEAR)", "Technology"),
    "XLV": ("Health Sector (CEDEAR)", "Health Care"), "XLP": ("Staples Sector (CEDEAR)", "Consumer Staples"),
    "XLU": ("Utilities Sector (CEDEAR)", "Utilities"), "ARKK": ("ARK Innovation (CEDEAR)", "Technology"),
    "FXI": ("iShares China (CEDEAR)", "Emerging Markets"), "VEA": ("Vanguard Developed (CEDEAR)", "Developed Intl"),
    "EWY": ("iShares Korea (CEDEAR)", "Emerging Markets"), "ACWI": ("iShares World (CEDEAR)", "Broad Equity"),
    "SMH": ("VanEck Semiconductors (CEDEAR)", "Technology"), "COPX": ("Global X Copper (CEDEAR)", "Materials"),
    "IBIT": ("iShares Bitcoin Trust (CEDEAR)", "Crypto"), "ETHA": ("iShares Ethereum Trust (CEDEAR)", "Crypto"),
    "TQQQ": ("ProShares 3x Nasdaq (CEDEAR)", "Technology"), "SATL": ("Satellogic", "Technology"),
    "NBIS": ("Nebius Group", "Technology"), "IREN": ("IREN", "Technology"),
    "SNDK": ("SanDisk", "Technology"),
}
# CEDEARs con subyacente COMMODITY (oro/plata físico) — asset_class COMMODITY.
_CEDEAR_COMMODITY = {"GLD": ("SPDR Gold (CEDEAR)", "Commodities"),
                     "SLV": ("iShares Silver (CEDEAR)", "Commodities")}

# ── Acciones ARG líquidas (data912 arg_stocks) — Merval + panel general.
_STOCK_META: dict[str, tuple[str, str]] = {
    "GGAL": ("Grupo Galicia", "Financials"), "YPFD": ("YPF", "Energy"),
    "PAMP": ("Pampa Energía", "Utilities"), "ALUA": ("Aluar", "Materials"),
    "TXAR": ("Ternium Argentina", "Materials"), "BYMA": ("Bolsas y Mercados", "Financials"),
    "LOMA": ("Loma Negra", "Materials"), "CRES": ("Cresud", "Consumer Staples"),
    "TGSU2": ("Transportadora Gas Sur", "Utilities"), "TGNO4": ("Transportadora Gas Norte", "Utilities"),
    "CEPU": ("Central Puerto", "Utilities"), "EDN": ("Edenor", "Utilities"),
    "SUPV": ("Grupo Supervielle", "Financials"), "TRAN": ("Transener", "Utilities"),
    "COME": ("Sociedad Comercial del Plata", "Industrials"), "MIRG": ("Mirgor", "Consumer Discretionary"),
    "METR": ("Metrogas", "Utilities"), "CECO2": ("Central Costanera", "Utilities"),
    "VALO": ("Grupo Financiero Valores", "Financials"), "BHIP": ("Banco Hipotecario", "Financials"),
    "CADO": ("Carlos Casado", "Real Estate"), "AGRO": ("Agrometal", "Industrials"),
    "MORI": ("Morixe", "Consumer Staples"), "CELU": ("Celulosa Argentina", "Materials"),
    "OEST": ("Oeste (Autopistas)", "Industrials"), "OA912": ("", ""),
    "SEMI": ("Molinos Agro", "Consumer Staples"), "LEDE": ("Ledesma", "Consumer Staples"),
    "CARC": ("Carboclor", "Materials"), "GARO": ("Garovaglio y Zorraquín", "Industrials"),
    "HARG": ("Holcim Argentina", "Materials"), "GCDI": ("Grupo Concesionario Oeste", "Industrials"),
    "INVJ": ("Inversora Juramento", "Consumer Staples"), "LONG": ("Longvie", "Consumer Discretionary"),
    "FERR": ("Ferrum", "Industrials"), "BOLT": ("Boldt", "Consumer Discretionary"),
    "FIPL": ("Fiplasto", "Materials"), "ECOG": ("Generación Mediterránea", "Utilities"),
    "TXMD9": ("", ""),
}


def _fetch(cat: str) -> list[dict]:
    r = requests.get(f"{_DATA912}/live/{cat}", timeout=25)
    r.raise_for_status()
    return r.json()


def _dedup_by_volume(rows: list[dict]) -> dict[str, float]:
    """symbol base (sin sufijo C/D si el base existe) -> mejor volumen."""
    syms = {r["symbol"] for r in rows}
    best: dict[str, float] = {}
    for r in rows:
        s = r["symbol"]
        base = s[:-1] if s and s[-1] in "CD" and s[:-1] in syms else s
        v = float(r.get("v") or 0)
        if base not in best or v > best[base]:
            best[base] = v
    return best


def _row(ticker, name, issuer, itype, aclass, ccy, country, sector,
         hard_dollar, liq, coupon="", ytm="", duration="", rating="", note=""):
    return {
        "ticker": ticker, "name": name, "issuer": issuer, "instrument_type": itype,
        "asset_class": aclass, "currency": ccy, "country": country, "sector": sector,
        "available_entities": _ALL_BROKERS, "hard_dollar": str(hard_dollar).lower(),
        "liquidity_score": f"{liq:.2f}", "maturity_date": "", "coupon_rate": coupon,
        "ytm": ytm, "duration": duration, "min_piece": "", "rating": rating, "notes": note,
    }


def build(max_cedears: int, max_stocks: int, min_stock_vol: float) -> list[dict]:
    out: list[dict] = []
    # 1) núcleo US ETFs
    for tk, name, iss, aclass, sector, liq in US_ETF_CORE:
        out.append(_row(tk, name, iss, "ETF", aclass, "USD", "US", sector, False, liq,
                        duration="1.0", note="ETF US (yfinance)"))
    for tk, name, iss, sector, liq, ytm, dur in US_ETF_BONDS:
        out.append(_row(tk, name, iss, "ETF", "FIXED_INCOME", "USD", "US", sector, False, liq,
                        ytm=str(ytm), duration=str(dur), note="ETF renta fija US (yfinance)"))
    for tk, name, iss, sector, liq, ytm, dur in US_ETF_HY:
        out.append(_row(tk, name, iss, "ETF", "HIGH_YIELD", "USD", "US", sector, False, liq,
                        ytm=str(ytm), duration=str(dur), rating="BB", note="ETF high yield US (yfinance)"))
    # 2) soberanos ARG hard-dollar
    for tk, name, coupon, ytm, dur, liq in SOBERANOS:
        out.append(_row(tk, name, "Republica Argentina", "SOVEREIGN_BOND", "FIXED_INCOME",
                        "USD", "AR", "Government", True, liq, coupon=str(coupon), ytm=str(ytm),
                        duration=str(dur), rating="CCC", note="Soberano USD (data912)"))
    # 3) CEDEARs líquidos (dedup + top por volumen)
    ced = _dedup_by_volume(_fetch("arg_cedears"))
    seen = {r["ticker"] for r in out}
    for sym, _v in sorted(ced.items(), key=lambda x: -x[1])[:max_cedears]:
        if sym in seen:
            continue
        if sym in _CEDEAR_COMMODITY:
            name, sector = _CEDEAR_COMMODITY[sym]
            aclass = "COMMODITY"
        else:
            name, sector = _CEDEAR_META.get(sym, (f"{sym} (CEDEAR)", "Equity"))
            aclass = "EQUITY"
        out.append(_row(sym, name, name.split(" (")[0], "CEDEAR", aclass, "ARS", "AR", sector,
                        False, 0.72, note="CEDEAR en ARS (data912)"))
        seen.add(sym)
    # 4) acciones ARG líquidas
    stk = _dedup_by_volume(_fetch("arg_stocks"))
    for sym, v in sorted(stk.items(), key=lambda x: -x[1]):
        if sym in seen or v < min_stock_vol:
            continue
        meta = _STOCK_META.get(sym)
        if not meta or not meta[0]:
            continue  # sin nombre curado -> se omite (evita basura en el universo)
        name, sector = meta
        out.append(_row(sym, name, name, "STOCK", "EQUITY", "ARS", "AR", sector,
                        False, 0.60, note="Accion ARG (data912)"))
        seen.add(sym)
        if len([r for r in out if r["instrument_type"] == "STOCK"]) >= max_stocks:
            break
    return out


def warm_cache(rows: list[dict]) -> None:
    from risk_first_advisory.data_layer.live_market_data import (
        LiveMarketDataProvider,
        instrument_type_to_source,
    )
    source_map = {
        r["ticker"]: instrument_type_to_source(r["instrument_type"], r["country"])
        for r in rows
    }
    prov = LiveMarketDataProvider(source_map, period="3y")
    ok = 0
    for i, tk in enumerate(source_map, 1):
        snap = prov.get_snapshot(tk)
        ok += snap is not None
        print(f"  [{i}/{len(source_map)}] {tk}: {'ok' if snap else 'sin datos'}", flush=True)
    print(f"Caché precalentado: {ok}/{len(source_map)} con datos.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-cedears", type=int, default=45)
    ap.add_argument("--max-stocks", type=int, default=20)
    ap.add_argument("--min-stock-vol", type=float, default=50_000.0)
    ap.add_argument("--warm", action="store_true", help="precalienta el caché live")
    ap.add_argument("--out", type=Path, default=_OUT)
    args = ap.parse_args()

    rows = build(args.max_cedears, args.max_stocks, args.min_stock_vol)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_COLS)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    by_type = Counter(r["instrument_type"] for r in rows)
    print(f"Universo escrito: {len(rows)} instrumentos -> {args.out}")
    print(f"  por tipo: {dict(by_type)}")

    if args.warm:
        print("Precalentando caché (una vez ~1.5s por instrumento)...")
        warm_cache(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
