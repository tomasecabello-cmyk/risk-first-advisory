"""
Unit test del flag de producto complejo en la serialización de candidates
(DD-017 ext.): determinístico, sin depender de que el optimizador asigne
peso a un CEDEAR en el fixture (eso lo cubre, cuando ocurre, la integración).
"""

from __future__ import annotations

from types import SimpleNamespace

from risk_first_advisory.api_layer.main import _serialize_candidate_for_proposal


def _stub_portfolio(weights: dict[str, float]) -> SimpleNamespace:
    return SimpleNamespace(
        weights=weights,
        objective=SimpleNamespace(value="MAX_RETURN"),
        expected_return_annual=0.12,
        volatility_annual=0.18,
        risk_score=0.5,
        constraints_satisfied=True,
        reason_codes=[],
        notes=[],
    )


def _instruments() -> dict[str, dict]:
    return {
        "AAPL": {
            "ticker": "AAPL", "name": "Apple CEDEAR", "issuer": "Apple",
            "instrument_type": "CEDEAR", "asset_class": "EQUITY",
            "currency": "USD", "sector": "Technology", "country": "AR",
            "hard_dollar": False,
        },
        "GD30": {
            "ticker": "GD30", "name": "Global 2030", "issuer": "Rep. Argentina",
            "instrument_type": "SOVEREIGN_BOND", "asset_class": "FIXED_INCOME",
            "currency": "USD", "sector": "Sovereign", "country": "AR",
            "hard_dollar": True,
        },
    }


def test_cedear_holding_flagged_complex():
    cand = _serialize_candidate_for_proposal(
        "GROWTH",
        _stub_portfolio({"AAPL": 0.6, "GD30": 0.4}),
        None,
        instruments_by_ticker=_instruments(),
    )
    by_ticker = {h["ticker"]: h for h in cand["holdings"]}

    cedear = by_ticker["AAPL"]
    assert cedear["complex_product_note"] is not None
    assert "ratio" in cedear["complex_product_note"].lower()
    assert "complex_product" in cedear["risk_flags"]
    assert "SUIT_003" in cedear["inclusion_reason_codes"]

    bond = by_ticker["GD30"]
    assert bond["complex_product_note"] is None
    assert "complex_product" not in bond["risk_flags"]
    assert "SUIT_003" not in bond["inclusion_reason_codes"]


def test_holding_without_metadata_tolerated():
    """Ticker fuera del snapshot (caso edge documentado): metadata None,
    sin nota de producto y sin crash."""
    cand = _serialize_candidate_for_proposal(
        "BALANCED",
        _stub_portfolio({"XXXX": 1.0}),
        None,
        instruments_by_ticker={},
    )
    (holding,) = cand["holdings"]
    assert holding["complex_product_note"] is None
    assert "complex_product" not in holding["risk_flags"]
