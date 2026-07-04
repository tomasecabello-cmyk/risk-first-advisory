"""
Tests unitarios para los helpers de trade-off en api_layer/main.py:
`_tradeoff_from_kyc_payload` (arma el dict tradeoff desde el KYC) y
`_client_risk_number_tolerant` (client_risk_number con fallback a
willingness-only si el trade-off es inválido).
"""

from __future__ import annotations

from risk_first_advisory.api_layer.main import (
    _client_risk_number_tolerant,
    _tradeoff_from_kyc_payload,
)

_BASE_KYC = {
    "age": 42, "risk_tolerance_score": 6, "risk_capacity_score": 7,
    "liquidity_need_score": 3, "investment_horizon_years": 10,
    "investment_experience": "moderada", "income_stability": "stable",
    "net_worth": 500_000.0, "liquid_net_worth": 150_000.0,
    "max_acceptable_drawdown_pct": 20.0,
}


def test_tradeoff_none_when_fields_missing():
    assert _tradeoff_from_kyc_payload(_BASE_KYC) is None


def test_tradeoff_none_when_only_some_fields_present():
    kyc = dict(_BASE_KYC, tradeoff_gain_usd=15000.0, tradeoff_loss_usd=7500.0)
    assert _tradeoff_from_kyc_payload(kyc) is None


def test_tradeoff_built_from_liquid_net_worth_as_wealth():
    kyc = dict(
        _BASE_KYC, tradeoff_gain_usd=15000.0, tradeoff_loss_usd=7500.0,
        tradeoff_certain_amount_usd=3000.0,
    )
    tradeoff = _tradeoff_from_kyc_payload(kyc)
    assert tradeoff == {
        "wealth": 150_000.0, "gain": 15000.0, "loss": 7500.0, "certain_amount": 3000.0,
    }


def test_client_risk_number_tolerant_uses_tradeoff_when_valid():
    kyc = dict(
        _BASE_KYC, tradeoff_gain_usd=15000.0, tradeoff_loss_usd=7500.0,
        tradeoff_certain_amount_usd=3000.0,
    )
    result = _client_risk_number_tolerant(kyc)
    assert result["tradeoff_number"] is not None
    assert result["gamma"] is not None


def test_client_risk_number_tolerant_falls_back_when_tradeoff_invalid():
    """certain_amount fuera de (-loss, gain): el motor levanta ValueError
    dentro de client_risk_number → el helper cae a willingness-only, nunca
    propaga la excepción."""
    kyc = dict(
        _BASE_KYC, tradeoff_gain_usd=15000.0, tradeoff_loss_usd=7500.0,
        tradeoff_certain_amount_usd=99999.0,
    )
    result = _client_risk_number_tolerant(kyc)
    assert result["tradeoff_number"] is None
    assert result["gamma"] is None
    assert result["number"] is not None  # willingness-only sigue funcionando


def test_client_risk_number_tolerant_without_tradeoff_matches_legacy():
    result = _client_risk_number_tolerant(_BASE_KYC)
    assert result["tradeoff_number"] is None
    assert result["gamma"] is None
