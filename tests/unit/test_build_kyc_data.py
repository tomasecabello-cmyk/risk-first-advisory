"""
Tests unitarios para el helper _build_kyc_data en api_layer/main.py.

Verifica que el campo 'age' del request se propague correctamente al KYCData
resultante, y no se use el valor hardcodeado anterior (40).
"""

from __future__ import annotations

import pytest

from risk_first_advisory.api_layer.main import _build_kyc_data
from risk_first_advisory.api_layer.schemas import KYCDataRequest


# ─────────────────────────────────────────────────────────────────────────────
# Fixture base: KYCDataRequest mínimo válido
# ─────────────────────────────────────────────────────────────────────────────

def _make_request(**overrides) -> KYCDataRequest:
    """Crea un KYCDataRequest válido con los overrides dados."""
    base = dict(
        risk_tolerance_score=6,
        risk_capacity_score=7,
        liquidity_need_score=3,
        investment_horizon_years=10,
        investment_experience="moderada",
        income_stability="stable",
        net_worth=500_000.0,
        liquid_net_worth=200_000.0,
        max_acceptable_drawdown_pct=25.0,
    )
    base.update(overrides)
    return KYCDataRequest(**base)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: age propagado correctamente
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildKYCDataAge:
    def test_age_75_is_propagated(self):
        """age=75 en el request debe aparecer en KYCData.age — no 40."""
        req = _make_request(age=75)
        kyc = _build_kyc_data(req)
        assert kyc.age == 75, f"Esperado age=75, obtenido {kyc.age}"

    def test_age_18_minimum_is_propagated(self):
        """age=18 (mínimo válido) debe llegar a KYCData.age."""
        req = _make_request(age=18)
        kyc = _build_kyc_data(req)
        assert kyc.age == 18

    def test_age_120_maximum_is_propagated(self):
        """age=120 (máximo válido) debe llegar a KYCData.age."""
        req = _make_request(age=120)
        kyc = _build_kyc_data(req)
        assert kyc.age == 120

    def test_age_default_40_is_propagated(self):
        """Sin age explícito, el default=40 debe llegar a KYCData.age."""
        req = _make_request()  # sin 'age' → default=40
        kyc = _build_kyc_data(req)
        assert kyc.age == 40

    def test_age_30_is_not_hardcoded_40(self):
        """age=30 no debe ser reemplazado por 40 (regresión del bug)."""
        req = _make_request(age=30)
        kyc = _build_kyc_data(req)
        assert kyc.age == 30
        assert kyc.age != 40

    def test_age_65_is_not_hardcoded_40(self):
        """age=65 no debe ser reemplazado por 40 (regresión del bug)."""
        req = _make_request(age=65)
        kyc = _build_kyc_data(req)
        assert kyc.age == 65
        assert kyc.age != 40


# ─────────────────────────────────────────────────────────────────────────────
# Tests: otros campos de KYCData no se ven afectados por el cambio de age
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildKYCDataOtherFields:
    def test_risk_capacity_propagated(self):
        req = _make_request(risk_capacity_score=8)
        kyc = _build_kyc_data(req)
        # financial_loss_capacity_pct = risk_capacity_score * 10
        assert kyc.financial_loss_capacity_pct == pytest.approx(80.0)

    def test_investment_horizon_propagated(self):
        req = _make_request(investment_horizon_years=15)
        kyc = _build_kyc_data(req)
        assert kyc.time_horizon_years == 15

    def test_net_worth_propagated(self):
        req = _make_request(net_worth=1_000_000.0)
        kyc = _build_kyc_data(req)
        assert kyc.approx_net_worth_usd == pytest.approx(1_000_000.0)

    def test_open_fields_propagated(self):
        req = _make_request(
            open_investment_goal="Crecer capital.",
            open_concerns="Inflación.",
        )
        kyc = _build_kyc_data(req)
        assert kyc.open_investment_goal == "Crecer capital."
        assert kyc.open_concerns == "Inflación."
