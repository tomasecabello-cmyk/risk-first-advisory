"""
Tests de portfolio_layer.diversification — descomposición pura de diversificación.

Cubre: HHI / equivalente diversificado, concentración single-asset, clase única,
repartos por eje, normalización de pesos, score y determinismo.
"""

from __future__ import annotations

from risk_first_advisory.portfolio_layer.diversification import assess_diversification


def _h(ticker, weight, asset_class="EQUITY", sector="Tech", currency="USD"):
    return {
        "ticker": ticker, "weight": weight, "asset_class": asset_class,
        "sector": sector, "currency": currency,
    }


def test_well_diversified_high_score_low_band():
    # 8 posiciones iguales repartidas en 3 clases → HHI 0.125 < 0.15 (baja).
    classes = ["EQUITY", "FIXED_INCOME", "COMMODITY"]
    holdings = [
        _h(f"T{i}", 0.125, classes[i % 3], f"Sector{i % 3}")
        for i in range(8)
    ]
    d = assess_diversification(holdings)
    assert d["concentration_band"] == "baja"
    assert d["diversification_score"] > 70
    assert "concentracion_single_asset" not in d["flags"]
    assert d["effective_holdings"] == 8.0  # 8 posiciones iguales


def test_four_equal_holdings_is_media_band():
    # HHI = 4 * 0.25^2 = 0.25 → banda media (no baja). Documenta el umbral.
    holdings = [
        _h("SPY", 0.25, "EQUITY", "Equity"),
        _h("TLT", 0.25, "FIXED_INCOME", "Treasuries"),
        _h("GLD", 0.25, "COMMODITY", "Commodities"),
        _h("VTI", 0.25, "EQUITY", "Equity"),
    ]
    d = assess_diversification(holdings)
    assert d["concentration_band"] == "media"
    assert d["effective_holdings"] == 4.0


def test_single_asset_flagged_and_low_score():
    d = assess_diversification([_h("AAPL", 1.0)])
    assert d["max_weight"] == 1.0
    assert d["max_weight_ticker"] == "AAPL"
    assert "concentracion_single_asset" in d["flags"]
    assert "pocas_posiciones" in d["flags"]
    assert d["concentration_band"] == "alta"
    assert d["diversification_score"] == 0.0


def test_single_asset_class_penalizes_even_with_many_tickers():
    # 5 acciones tech: muchos tickers PERO una sola clase → flag clase_unica.
    holdings = [_h(f"T{i}", 0.2, "EQUITY", "Technology") for i in range(5)]
    d = assess_diversification(holdings)
    assert "clase_unica" in d["flags"]
    # con HHI 0.2 el score base sería 80; con penalización por clase única, menor.
    assert d["diversification_score"] < 80


def test_weights_are_normalized_when_not_summing_to_one():
    # Pesos que suman 2.0 → se normalizan; HHI igual que con pesos /2.
    holdings = [_h("A", 1.0, "EQUITY", "X"), _h("B", 1.0, "FIXED_INCOME", "Y")]
    d = assess_diversification(holdings)
    assert abs(d["max_weight"] - 0.5) < 1e-9
    assert abs(d["hhi"] - 0.5) < 1e-9


def test_sector_concentration_flag():
    holdings = [
        _h("A", 0.6, "EQUITY", "Energy"),
        _h("B", 0.2, "FIXED_INCOME", "Treasuries"),
        _h("C", 0.2, "EQUITY", "Health"),
    ]
    d = assess_diversification(holdings)
    assert "concentracion_sectorial" in d["flags"]
    assert d["by_sector"]["Energy"] == 0.6


def test_empty_portfolio():
    d = assess_diversification([])
    assert d["holdings_count"] == 0
    assert "cartera_vacia" in d["flags"]


def test_is_deterministic():
    holdings = [_h("A", 0.5, "EQUITY"), _h("B", 0.5, "FIXED_INCOME")]
    assert assess_diversification(holdings) == assess_diversification(holdings)
