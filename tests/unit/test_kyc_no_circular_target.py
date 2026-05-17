"""
Tests que protegen la invariante DD-002:
    return_target_annual_pct NO existe en KYCData.
    El retorno requerido se calcula desde FinancialGoal, no desde el KYC.
"""

import dataclasses

import pytest

from risk_first_advisory.kyc.models import (
    ESGProfile,
    ESGStrictnessLevel,
    FinancialGoal,
    InvestmentObjective,
    InvestorExperience,
    KYCData,
)


def _build_valid_kyc(**overrides):
    """Builder de KYC válido para tests. Permite overrides puntuales."""
    defaults = dict(
        age=42,
        annual_income_usd=80_000,
        approx_net_worth_usd=300_000,
        investment_objective=InvestmentObjective.BALANCED,
        time_horizon_years=10,
        liquidity_need_pct=0.20,
        experience=InvestorExperience.MODERATE,
        emotional_loss_tolerance_pct=15.0,
        financial_loss_capacity_pct=20.0,
        preferred_currency="USD",
        needs_income=False,
        prefers_simple_products=True,
        jurisdiction="AR",
        esg_profile=ESGProfile(strictness_level=ESGStrictnessLevel.NONE),
    )
    defaults.update(overrides)
    return KYCData(**defaults)


def test_kyc_data_does_not_have_return_target_field():
    """
    Protege contra reintroducir return_target_annual_pct en KYCData.
    Si alguien lo agrega "porque sería más práctico", este test lo detecta.
    """
    fields = {f.name for f in dataclasses.fields(KYCData)}
    assert "return_target_annual_pct" not in fields, (
        "return_target_annual_pct NO debe existir en KYCData. "
        "El retorno requerido se calcula desde FinancialGoal (DD-002)."
    )


def test_kyc_data_has_declared_return_expectation_as_informative_field():
    """
    declared_return_expectation_pct existe como campo informativo opcional.
    Documentado como NO-usado-en-cálculos.
    """
    fields = {f.name for f in dataclasses.fields(KYCData)}
    assert "declared_return_expectation_pct" in fields, (
        "declared_return_expectation_pct debe existir como campo informativo (DD-003)."
    )


def test_kyc_data_declared_return_expectation_defaults_to_none():
    kyc = _build_valid_kyc()
    assert kyc.declared_return_expectation_pct is None


def test_kyc_data_accepts_declared_return_expectation_value():
    kyc = _build_valid_kyc(declared_return_expectation_pct=0.08)
    assert kyc.declared_return_expectation_pct == 0.08


def test_kyc_data_has_note_documenting_informative_status():
    """El modelo debe documentar explícitamente que el campo es informativo."""
    assert hasattr(KYCData, "DECLARED_RETURN_NOTE")
    note = KYCData.DECLARED_RETURN_NOTE.lower()
    assert "no se usa" in note or "no interviene" in note or "informativo" in note
    assert "financialgoal" in note


def test_financial_goal_is_the_single_source_for_viability():
    """
    FinancialGoal contiene todos los datos necesarios para calcular viabilidad
    SIN consultar nada del KYC.
    """
    goal = FinancialGoal(
        initial_capital_usd=100_000,
        target_capital_usd=150_000,
        horizon_years=5,
        periodic_contribution_usd=5_000,
        contribution_frequency_years=1.0,
        target_is_flexible=True,
        horizon_is_flexible=True,
    )
    # Todos los campos necesarios para IRR están presentes:
    assert goal.initial_capital_usd == 100_000
    assert goal.target_capital_usd == 150_000
    assert goal.horizon_years == 5
    assert goal.periodic_contribution_usd == 5_000


def test_financial_goal_rejects_target_below_initial_without_contributions():
    """No tiene sentido un objetivo de decrecimiento sin aportes."""
    with pytest.raises(ValueError, match="target_capital"):
        FinancialGoal(
            initial_capital_usd=100_000,
            target_capital_usd=80_000,
            horizon_years=5,
            periodic_contribution_usd=0,
            contribution_frequency_years=1.0,
            target_is_flexible=True,
            horizon_is_flexible=True,
        )


def test_financial_goal_accepts_preservation_case():
    """target == initial es válido (preservación de capital)."""
    goal = FinancialGoal(
        initial_capital_usd=100_000,
        target_capital_usd=100_000,
        horizon_years=5,
        periodic_contribution_usd=0,
        contribution_frequency_years=1.0,
        target_is_flexible=False,
        horizon_is_flexible=False,
    )
    assert goal.target_capital_usd == goal.initial_capital_usd


def test_financial_goal_rejects_invalid_horizon():
    with pytest.raises(ValueError, match="horizon_years"):
        FinancialGoal(
            initial_capital_usd=100_000,
            target_capital_usd=150_000,
            horizon_years=0,
            periodic_contribution_usd=0,
            contribution_frequency_years=1.0,
            target_is_flexible=True,
            horizon_is_flexible=True,
        )


def test_kyc_data_validates_tolerance_range():
    with pytest.raises(ValueError, match="emotional_loss_tolerance_pct"):
        _build_valid_kyc(emotional_loss_tolerance_pct=150.0)


def test_kyc_data_validates_capacity_range():
    with pytest.raises(ValueError, match="financial_loss_capacity_pct"):
        _build_valid_kyc(financial_loss_capacity_pct=-5.0)


def test_kyc_data_validates_liquidity_range():
    with pytest.raises(ValueError, match="liquidity_need_pct"):
        _build_valid_kyc(liquidity_need_pct=1.5)


def test_kyc_data_can_be_constructed_with_minimal_valid_inputs():
    kyc = _build_valid_kyc()
    assert kyc.age == 42
    assert kyc.investment_objective == InvestmentObjective.BALANCED
    assert kyc.esg_profile.strictness_level == ESGStrictnessLevel.NONE
