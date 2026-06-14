"""
Tests unitarios para el helper _build_kyc_data en api_layer/main.py.

Cubre:
    - Propagación de 'age' (regresión del bug hardcoded=40).
    - Propagación de los campos antes hardcoded en _build_kyc_data
      (jurisdiction, preferred_currency, investment_objective,
      prefers_simple_products, annual_income_usd, ESG profile).
    - Backward compatibility: payload mínimo legacy sigue funcionando.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from risk_first_advisory.api_layer.main import _build_kyc_data
from risk_first_advisory.api_layer.schemas import KYCDataRequest
from risk_first_advisory.kyc.models import (
    ESGStrictnessLevel,
    InvestmentObjective,
)

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


# ─────────────────────────────────────────────────────────────────────────────
# Tests: jurisdiction (antes hardcoded "AR")
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildKYCDataJurisdiction:
    def test_jurisdiction_explicit_value_is_propagated(self):
        req = _make_request(jurisdiction="MX")
        kyc = _build_kyc_data(req)
        assert kyc.jurisdiction == "MX"

    def test_jurisdiction_default_AR_is_propagated(self):
        """Backward compatibility: sin jurisdiction el default 'AR' debe llegar."""
        req = _make_request()
        kyc = _build_kyc_data(req)
        assert kyc.jurisdiction == "AR"

    def test_jurisdiction_us_is_not_silently_replaced(self):
        req = _make_request(jurisdiction="US")
        kyc = _build_kyc_data(req)
        assert kyc.jurisdiction == "US"
        assert kyc.jurisdiction != "AR"

    def test_jurisdiction_empty_string_rejected_by_pydantic(self):
        with pytest.raises(ValidationError):
            _make_request(jurisdiction="")

    def test_jurisdiction_whitespace_only_rejected_by_pydantic(self):
        with pytest.raises(ValidationError):
            _make_request(jurisdiction="   ")


# ─────────────────────────────────────────────────────────────────────────────
# Tests: preferred_currency (antes hardcoded "USD")
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildKYCDataPreferredCurrency:
    def test_preferred_currency_explicit_eur_propagated(self):
        req = _make_request(preferred_currency="EUR")
        kyc = _build_kyc_data(req)
        assert kyc.preferred_currency == "EUR"

    def test_preferred_currency_default_USD_propagated(self):
        """Backward compatibility: sin preferred_currency el default 'USD'."""
        req = _make_request()
        kyc = _build_kyc_data(req)
        assert kyc.preferred_currency == "USD"

    def test_preferred_currency_ars_is_not_silently_replaced(self):
        req = _make_request(preferred_currency="ARS")
        kyc = _build_kyc_data(req)
        assert kyc.preferred_currency == "ARS"
        assert kyc.preferred_currency != "USD"

    def test_preferred_currency_empty_rejected_by_pydantic(self):
        with pytest.raises(ValidationError):
            _make_request(preferred_currency="")

    def test_preferred_currency_whitespace_only_rejected_by_pydantic(self):
        with pytest.raises(ValidationError):
            _make_request(preferred_currency="   ")


# ─────────────────────────────────────────────────────────────────────────────
# Tests: investment_objective (antes hardcoded InvestmentObjective.BALANCED)
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildKYCDataInvestmentObjective:
    def test_default_balanced_propagated(self):
        """Backward compatibility: sin investment_objective → BALANCED."""
        req = _make_request()
        kyc = _build_kyc_data(req)
        assert kyc.investment_objective == InvestmentObjective.BALANCED

    def test_growth_propagated(self):
        req = _make_request(investment_objective="growth")
        kyc = _build_kyc_data(req)
        assert kyc.investment_objective == InvestmentObjective.GROWTH

    def test_capital_preservation_propagated(self):
        req = _make_request(investment_objective="capital_preservation")
        kyc = _build_kyc_data(req)
        assert kyc.investment_objective == InvestmentObjective.CAPITAL_PRESERVATION

    def test_aggressive_growth_propagated(self):
        req = _make_request(investment_objective="aggressive_growth")
        kyc = _build_kyc_data(req)
        assert kyc.investment_objective == InvestmentObjective.AGGRESSIVE_GROWTH

    def test_income_propagated(self):
        req = _make_request(investment_objective="income")
        kyc = _build_kyc_data(req)
        assert kyc.investment_objective == InvestmentObjective.INCOME

    def test_uppercase_normalized_to_lowercase(self):
        """El validador acepta variantes en mayúsculas y las normaliza."""
        req = _make_request(investment_objective="GROWTH")
        kyc = _build_kyc_data(req)
        assert kyc.investment_objective == InvestmentObjective.GROWTH

    def test_invalid_objective_rejected_by_pydantic(self):
        with pytest.raises(ValidationError) as exc_info:
            _make_request(investment_objective="speculative")
        # El mensaje debe ser útil para debugging del cliente.
        msg = str(exc_info.value)
        assert "investment_objective" in msg
        assert "speculative" in msg

    def test_invalid_objective_lists_valid_options(self):
        with pytest.raises(ValidationError) as exc_info:
            _make_request(investment_objective="ultra_safe")
        msg = str(exc_info.value)
        assert "balanced" in msg.lower() or "Opciones" in msg


# ─────────────────────────────────────────────────────────────────────────────
# Tests: prefers_simple_products (antes hardcoded False)
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildKYCDataPrefersSimpleProducts:
    def test_default_false_propagated(self):
        """Backward compatibility: sin prefers_simple_products → False."""
        req = _make_request()
        kyc = _build_kyc_data(req)
        assert kyc.prefers_simple_products is False

    def test_true_propagated(self):
        req = _make_request(prefers_simple_products=True)
        kyc = _build_kyc_data(req)
        assert kyc.prefers_simple_products is True
        # Regression: no debe colapsar a False por hardcoded.
        assert kyc.prefers_simple_products is not False

    def test_explicit_false_propagated(self):
        req = _make_request(prefers_simple_products=False)
        kyc = _build_kyc_data(req)
        assert kyc.prefers_simple_products is False


# ─────────────────────────────────────────────────────────────────────────────
# Tests: annual_income_usd (antes derivado de liquid_net_worth * 0.05)
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildKYCDataAnnualIncome:
    def test_explicit_value_used_directly(self):
        req = _make_request(annual_income_usd=120_000.0)
        kyc = _build_kyc_data(req)
        assert kyc.annual_income_usd == pytest.approx(120_000.0)

    def test_explicit_value_overrides_liquid_net_worth_fallback(self):
        """Si annual_income viene, ignora el fallback aunque liquid_net_worth sea grande."""
        req = _make_request(liquid_net_worth=10_000_000.0, annual_income_usd=50_000.0)
        kyc = _build_kyc_data(req)
        # Si usara fallback, sería 500_000 (10M * 0.05). Debe ser 50_000.
        assert kyc.annual_income_usd == pytest.approx(50_000.0)
        assert kyc.annual_income_usd != pytest.approx(500_000.0)

    def test_none_falls_back_to_liquid_net_worth_times_005(self):
        """Backward compatibility: si no se manda, fallback histórico."""
        req = _make_request(liquid_net_worth=200_000.0)  # annual_income_usd default = None
        kyc = _build_kyc_data(req)
        # 200_000 * 0.05 = 10_000
        assert kyc.annual_income_usd == pytest.approx(10_000.0)

    def test_none_with_zero_liquid_net_worth_uses_minimum_1(self):
        """El fallback usa max(..., 1.0) para evitar 0 que rompería ratios."""
        req = _make_request(liquid_net_worth=0.0)
        kyc = _build_kyc_data(req)
        assert kyc.annual_income_usd == pytest.approx(1.0)

    def test_zero_explicit_value_accepted(self):
        """annual_income_usd=0 es válido (cliente sin ingresos declarados)."""
        req = _make_request(annual_income_usd=0.0)
        kyc = _build_kyc_data(req)
        assert kyc.annual_income_usd == pytest.approx(0.0)

    def test_negative_value_rejected_by_pydantic(self):
        with pytest.raises(ValidationError):
            _make_request(annual_income_usd=-1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: ESG profile (antes hardcoded ESGProfile() vacío)
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildKYCDataESGProfile:
    def test_default_empty_profile_backward_compatible(self):
        """Backward compatibility: sin campos ESG → ESGProfile equivalente al anterior."""
        req = _make_request()
        kyc = _build_kyc_data(req)
        assert kyc.esg_profile.strictness_level == ESGStrictnessLevel.NONE
        assert kyc.esg_profile.hard_exclusions == []
        assert kyc.esg_profile.soft_preferences == []

    def test_strictness_level_propagated(self):
        req = _make_request(esg_strictness_level="strict")
        kyc = _build_kyc_data(req)
        assert kyc.esg_profile.strictness_level == ESGStrictnessLevel.STRICT

    def test_uppercase_strictness_normalized(self):
        req = _make_request(esg_strictness_level="IMPACT")
        kyc = _build_kyc_data(req)
        assert kyc.esg_profile.strictness_level == ESGStrictnessLevel.IMPACT

    def test_invalid_strictness_rejected_by_pydantic(self):
        with pytest.raises(ValidationError):
            _make_request(esg_strictness_level="extreme")

    def test_hard_exclusions_propagated(self):
        req = _make_request(
            esg_exclusions=[
                {
                    "excluded_item": "tobacco",
                    "exclusion_type": "sector",
                    "source": "client_explicit",
                    "rationale": "Convicción personal del cliente.",
                },
                {
                    "excluded_item": "weapons",
                    "exclusion_type": "activity",
                    "source": "firm_policy",
                },
            ],
        )
        kyc = _build_kyc_data(req)
        assert len(kyc.esg_profile.hard_exclusions) == 2
        first = kyc.esg_profile.hard_exclusions[0]
        assert first.excluded_item == "tobacco"
        assert first.exclusion_type == "sector"
        assert first.source == "client_explicit"
        assert first.rationale == "Convicción personal del cliente."
        # rationale default vacío para la segunda exclusión.
        assert kyc.esg_profile.hard_exclusions[1].rationale == ""

    def test_soft_preferences_propagated(self):
        req = _make_request(
            esg_preferences=[
                {
                    "preference_type": "low_carbon",
                    "weight": 0.7,
                    "minimum_threshold": 50.0,
                },
                {
                    "preference_type": "diversity_leaders",
                    "weight": 0.3,
                },
            ],
        )
        kyc = _build_kyc_data(req)
        assert len(kyc.esg_profile.soft_preferences) == 2
        assert kyc.esg_profile.soft_preferences[0].preference_type == "low_carbon"
        assert kyc.esg_profile.soft_preferences[0].weight == pytest.approx(0.7)
        assert kyc.esg_profile.soft_preferences[0].minimum_threshold == pytest.approx(50.0)
        assert kyc.esg_profile.soft_preferences[1].minimum_threshold is None

    def test_full_esg_profile_construction(self):
        """Smoke test: strictness + exclusions + preferences combinados."""
        req = _make_request(
            esg_strictness_level="light",
            esg_exclusions=[{
                "excluded_item": "fossil_fuels",
                "exclusion_type": "sector",
                "source": "client_explicit",
            }],
            esg_preferences=[{
                "preference_type": "low_carbon",
                "weight": 0.5,
            }],
        )
        kyc = _build_kyc_data(req)
        assert kyc.esg_profile.strictness_level == ESGStrictnessLevel.LIGHT
        assert kyc.esg_profile.has_hard_exclusions()
        assert kyc.esg_profile.has_soft_preferences()

    def test_invalid_exclusion_type_rejected_by_pydantic(self):
        with pytest.raises(ValidationError):
            _make_request(esg_exclusions=[{
                "excluded_item": "tobacco",
                "exclusion_type": "made_up_type",
                "source": "client_explicit",
            }])

    def test_exclusion_with_empty_excluded_item_rejected(self):
        with pytest.raises(ValidationError):
            _make_request(esg_exclusions=[{
                "excluded_item": "",
                "exclusion_type": "sector",
                "source": "client_explicit",
            }])

    def test_preference_weight_out_of_range_rejected(self):
        """ESGPreference.weight debe estar en [0.0, 1.0]."""
        with pytest.raises(ValidationError):
            _make_request(esg_preferences=[{
                "preference_type": "low_carbon",
                "weight": 1.5,
            }])

    def test_preference_negative_weight_rejected(self):
        with pytest.raises(ValidationError):
            _make_request(esg_preferences=[{
                "preference_type": "low_carbon",
                "weight": -0.1,
            }])


# ─────────────────────────────────────────────────────────────────────────────
# Tests: backward compatibility — request mínimo legacy sigue funcionando
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildKYCDataBackwardCompatibility:
    def test_minimal_legacy_request_still_works(self):
        """
        Un request con SOLO los campos viejos (sin jurisdiction, sin currency,
        sin investment_objective, sin prefers_simple_products, sin annual_income,
        sin ESG) debe construir un KYCData válido con los mismos defaults que
        antes producía _build_kyc_data hardcoded.
        """
        req = _make_request()
        kyc = _build_kyc_data(req)
        # Defaults históricos:
        assert kyc.jurisdiction == "AR"
        assert kyc.preferred_currency == "USD"
        assert kyc.investment_objective == InvestmentObjective.BALANCED
        assert kyc.prefers_simple_products is False
        assert kyc.esg_profile.strictness_level == ESGStrictnessLevel.NONE
        assert kyc.esg_profile.hard_exclusions == []
        assert kyc.esg_profile.soft_preferences == []
        # annual_income_usd con fallback: liquid_net_worth=200_000 * 0.05 = 10_000
        assert kyc.annual_income_usd == pytest.approx(10_000.0)

    def test_age_default_with_all_new_defaults(self):
        """Comprueba que el set completo de defaults históricos coexiste."""
        req = _make_request()
        kyc = _build_kyc_data(req)
        assert kyc.age == 40  # default histórico
        assert kyc.jurisdiction == "AR"
        assert kyc.preferred_currency == "USD"
