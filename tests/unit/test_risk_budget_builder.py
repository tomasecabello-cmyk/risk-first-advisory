"""
Tests del RiskBudgetBuilder.

Validaciones cubiertas:
1. Parámetros base por perfil.
2. Ajustes por liquidez, horizonte, experiencia, simplicidad,
   capacidad financiera y tolerancia emocional.
3. Que declared_return_expectation_pct NO afecta el resultado.
4. Que perfil desconocido lanza ValueError.
5. Que el RiskBudget es serializable.
6. Que las notas explican los ajustes aplicados.
"""

import json
from dataclasses import replace

import pytest

from risk_first_advisory.kyc.models import (
    ESGProfile,
    ESGStrictnessLevel,
    FinancialGoal,
    InvestmentObjective,
    InvestorExperience,
    KYCData,
)
from risk_first_advisory.models.risk_budget import RiskBudget
from risk_first_advisory.rules_layer.risk_budget_builder import (
    PROFILE_BASE_PARAMS,
    VALID_PROFILES,
    RiskBudgetBuilder,
)

# ── Helpers ───────────────────────────────────────────────────────────────


def _build_kyc(**overrides) -> KYCData:
    """
    Builder de KYC válido y CONSERVADOR por defecto, para que las reglas de
    ajuste no se disparen salvo que el test lo pida explícitamente.
    """
    defaults = dict(
        age=50,
        annual_income_usd=100_000,
        approx_net_worth_usd=500_000,
        investment_objective=InvestmentObjective.BALANCED,
        time_horizon_years=10,
        liquidity_need_pct=0.0,
        experience=InvestorExperience.MODERATE,
        emotional_loss_tolerance_pct=50.0,  # alto: no dispara restricción
        financial_loss_capacity_pct=50.0,  # alto: no dispara restricción
        preferred_currency="USD",
        needs_income=False,
        prefers_simple_products=False,
        jurisdiction="AR",
        esg_profile=ESGProfile(strictness_level=ESGStrictnessLevel.NONE),
    )
    defaults.update(overrides)
    return KYCData(**defaults)


def _build_goal(**overrides) -> FinancialGoal:
    defaults = dict(
        initial_capital_usd=100_000,
        target_capital_usd=150_000,
        horizon_years=10,
        periodic_contribution_usd=0,
        contribution_frequency_years=1.0,
        target_is_flexible=True,
        horizon_is_flexible=True,
    )
    defaults.update(overrides)
    return FinancialGoal(**defaults)


def _build_neutral_kyc_for_profile(profile: str, **overrides) -> KYCData:
    """
    KYC neutral cuya tolerancia y capacidad permiten el drawdown base del
    perfil indicado, para que solo se disparen las reglas que el test pida.
    """
    base = PROFILE_BASE_PARAMS[profile]
    base_dd_abs = abs(base["max_drawdown"]) * 100  # en %
    cushion = max(base_dd_abs + 10.0, 50.0)
    cushion = min(cushion, 100.0)
    neutral = dict(
        emotional_loss_tolerance_pct=cushion,
        financial_loss_capacity_pct=cushion,
    )
    neutral.update(overrides)
    return _build_kyc(**neutral)


# ── 1. Parámetros base por perfil ─────────────────────────────────────────


class TestParametrosBase:
    def test_perfil_conservador_genera_limites_base(self):
        kyc = _build_neutral_kyc_for_profile("conservador")
        goal = _build_goal(horizon_years=10)
        b = RiskBudgetBuilder().build("conservador", kyc, goal)

        assert b.profile_name == "conservador"
        assert b.target_volatility == pytest.approx(0.035)
        assert b.max_volatility == pytest.approx(0.050)
        assert b.max_drawdown == pytest.approx(-0.070)
        assert b.max_equity == pytest.approx(0.10)
        assert b.max_high_yield == pytest.approx(0.00)
        assert b.max_single_asset == pytest.approx(0.15)
        assert b.max_sector_exposure == pytest.approx(0.20)
        assert b.max_duration == pytest.approx(2.0)
        assert b.complex_products_allowed is False

    def test_perfil_moderado_target_y_max_volatility(self):
        kyc = _build_neutral_kyc_for_profile("moderado")
        goal = _build_goal(horizon_years=10)
        b = RiskBudgetBuilder().build("moderado", kyc, goal)

        assert b.target_volatility == pytest.approx(0.075)
        assert b.max_volatility == pytest.approx(0.100)
        assert b.max_drawdown == pytest.approx(-0.150)

    def test_perfil_moderado_defensivo_base(self):
        kyc = _build_neutral_kyc_for_profile("moderado-defensivo")
        goal = _build_goal(horizon_years=10)
        b = RiskBudgetBuilder().build("moderado-defensivo", kyc, goal)
        assert b.target_volatility == pytest.approx(0.055)
        assert b.max_volatility == pytest.approx(0.075)
        assert b.max_drawdown == pytest.approx(-0.100)

    def test_perfil_moderado_agresivo_permite_complejos(self):
        kyc = _build_neutral_kyc_for_profile(
            "moderado-agresivo",
            experience=InvestorExperience.ADVANCED,
            prefers_simple_products=False,
        )
        goal = _build_goal(horizon_years=10)
        b = RiskBudgetBuilder().build("moderado-agresivo", kyc, goal)
        assert b.complex_products_allowed is True

    def test_perfil_agresivo_base(self):
        kyc = _build_neutral_kyc_for_profile(
            "agresivo",
            experience=InvestorExperience.ADVANCED,
            prefers_simple_products=False,
        )
        goal = _build_goal(horizon_years=15)
        b = RiskBudgetBuilder().build("agresivo", kyc, goal)
        assert b.target_volatility == pytest.approx(0.140)
        assert b.max_volatility == pytest.approx(0.200)
        assert b.max_equity == pytest.approx(0.80)
        assert b.complex_products_allowed is True


# ── 2. Liquidez ───────────────────────────────────────────────────────────


class TestLiquidez:
    def test_liquidity_need_pct_aumenta_min_liquidity(self):
        kyc = _build_neutral_kyc_for_profile("moderado", liquidity_need_pct=0.30)
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert b.min_liquidity == pytest.approx(0.30)

    def test_sin_necesidad_de_liquidez_min_liquidity_es_cero(self):
        kyc = _build_neutral_kyc_for_profile("moderado", liquidity_need_pct=0.0)
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert b.min_liquidity == pytest.approx(0.0)

    def test_nota_de_liquidez_se_agrega_cuando_corresponde(self):
        kyc = _build_neutral_kyc_for_profile("moderado", liquidity_need_pct=0.40)
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert any("liquidez" in n.lower() or "liquidity" in n.lower() for n in b.notes)


# ── 3. Horizonte ──────────────────────────────────────────────────────────


class TestHorizonte:
    def test_horizonte_corto_recorta_equity_y_duration(self):
        kyc = _build_neutral_kyc_for_profile("moderado")
        goal = _build_goal(horizon_years=1)
        b = RiskBudgetBuilder().build("moderado", kyc, goal)
        assert b.max_equity <= 0.15
        assert b.max_duration <= 2.0

    def test_horizonte_corto_agrega_notas(self):
        kyc = _build_neutral_kyc_for_profile("moderado")
        goal = _build_goal(horizon_years=1)
        b = RiskBudgetBuilder().build("moderado", kyc, goal)
        assert any("horizonte" in n.lower() for n in b.notes)

    def test_horizonte_medio_recorta_max_duration_al_horizonte(self):
        # perfil moderado tiene max_duration=5.0; con horizon=3 debe quedar 3.0
        kyc = _build_neutral_kyc_for_profile("moderado")
        goal = _build_goal(horizon_years=3)
        b = RiskBudgetBuilder().build("moderado", kyc, goal)
        assert b.max_duration == pytest.approx(3.0)

    def test_horizonte_medio_no_recorta_si_duration_ya_es_menor(self):
        # perfil conservador max_duration=2.0; con horizon=4 NO debe inflar a 4
        kyc = _build_neutral_kyc_for_profile("conservador")
        goal = _build_goal(horizon_years=4)
        b = RiskBudgetBuilder().build("conservador", kyc, goal)
        assert b.max_duration == pytest.approx(2.0)

    def test_horizonte_largo_no_recorta_duration(self):
        kyc = _build_neutral_kyc_for_profile("moderado")
        goal = _build_goal(horizon_years=15)
        b = RiskBudgetBuilder().build("moderado", kyc, goal)
        assert b.max_duration == pytest.approx(5.0)


# ── 4. Experiencia inversora ──────────────────────────────────────────────


class TestExperiencia:
    def test_experiencia_basica_bloquea_complex_products(self):
        kyc = _build_neutral_kyc_for_profile(
            "moderado-agresivo",
            experience=InvestorExperience.BASIC,
        )
        b = RiskBudgetBuilder().build("moderado-agresivo", kyc, _build_goal(horizon_years=10))
        assert b.complex_products_allowed is False
        assert any("basica" in n.lower() or "experiencia" in n.lower() for n in b.notes)

    def test_experiencia_basica_limita_max_single_asset(self):
        # agresivo tiene max_single_asset=0.25; con experiencia básica → 0.15
        kyc = _build_neutral_kyc_for_profile(
            "agresivo",
            experience=InvestorExperience.BASIC,
        )
        b = RiskBudgetBuilder().build("agresivo", kyc, _build_goal(horizon_years=10))
        assert b.max_single_asset <= 0.15

    def test_experiencia_moderada_no_bloquea_complex_products_en_agresivo(self):
        kyc = _build_neutral_kyc_for_profile(
            "moderado-agresivo",
            experience=InvestorExperience.MODERATE,
            prefers_simple_products=False,
        )
        b = RiskBudgetBuilder().build("moderado-agresivo", kyc, _build_goal(horizon_years=10))
        assert b.complex_products_allowed is True


# ── 5. Preferencia por productos simples ──────────────────────────────────


class TestPrefersSimpleProducts:
    def test_prefers_simple_bloquea_complex_products(self):
        kyc = _build_neutral_kyc_for_profile(
            "moderado-agresivo",
            experience=InvestorExperience.ADVANCED,
            prefers_simple_products=True,
        )
        b = RiskBudgetBuilder().build("moderado-agresivo", kyc, _build_goal(horizon_years=10))
        assert b.complex_products_allowed is False
        assert any("simple" in n.lower() for n in b.notes)

    def test_prefers_simple_false_no_bloquea(self):
        kyc = _build_neutral_kyc_for_profile(
            "moderado-agresivo",
            experience=InvestorExperience.ADVANCED,
            prefers_simple_products=False,
        )
        b = RiskBudgetBuilder().build("moderado-agresivo", kyc, _build_goal(horizon_years=10))
        assert b.complex_products_allowed is True


# ── 6. Capacidad financiera de pérdida ────────────────────────────────────


class TestCapacidadFinanciera:
    def test_capacidad_menor_reduce_max_drawdown(self):
        # moderado tiene max_drawdown=-0.15; con capacity=8.0 debe quedar -0.08
        kyc = _build_neutral_kyc_for_profile(
            "moderado",
            financial_loss_capacity_pct=8.0,
            emotional_loss_tolerance_pct=50.0,
        )
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert b.max_drawdown == pytest.approx(-0.08)

    def test_capacidad_menor_reduce_volatilidad_proporcionalmente(self):
        kyc = _build_neutral_kyc_for_profile(
            "moderado",
            financial_loss_capacity_pct=8.0,
            emotional_loss_tolerance_pct=50.0,
        )
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        # factor = 0.08 / 0.15 ≈ 0.5333
        # target esperado ≈ 0.075 * 0.5333 ≈ 0.04
        assert b.target_volatility < 0.075
        assert b.max_volatility < 0.100
        assert b.target_volatility == pytest.approx(0.075 * (0.08 / 0.15), rel=1e-4)

    def test_capacidad_menor_agrega_nota(self):
        kyc = _build_neutral_kyc_for_profile(
            "moderado",
            financial_loss_capacity_pct=8.0,
            emotional_loss_tolerance_pct=50.0,
        )
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert any("capacidad" in n.lower() or "capacity" in n.lower() for n in b.notes)

    def test_capacidad_mayor_no_modifica_drawdown(self):
        kyc = _build_neutral_kyc_for_profile(
            "moderado",
            financial_loss_capacity_pct=80.0,
            emotional_loss_tolerance_pct=80.0,
        )
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert b.max_drawdown == pytest.approx(-0.15)


# ── 7. Tolerancia emocional ───────────────────────────────────────────────


class TestToleranciaEmocional:
    def test_tolerancia_menor_reduce_max_drawdown(self):
        # moderado max_drawdown=-0.15; tolerance=10% → -0.10
        kyc = _build_neutral_kyc_for_profile(
            "moderado",
            emotional_loss_tolerance_pct=10.0,
            financial_loss_capacity_pct=50.0,
        )
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert b.max_drawdown == pytest.approx(-0.10)

    def test_tolerancia_menor_reduce_volatilidad(self):
        kyc = _build_neutral_kyc_for_profile(
            "moderado",
            emotional_loss_tolerance_pct=10.0,
            financial_loss_capacity_pct=50.0,
        )
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert b.target_volatility < 0.075
        assert b.max_volatility < 0.100

    def test_tolerancia_menor_agrega_nota(self):
        kyc = _build_neutral_kyc_for_profile(
            "moderado",
            emotional_loss_tolerance_pct=10.0,
            financial_loss_capacity_pct=50.0,
        )
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert any("tolerancia" in n.lower() or "emocional" in n.lower() for n in b.notes)

    def test_tolerancia_menor_que_capacidad_aplica_la_mas_restrictiva(self):
        # capacity=12% → drawdown candidato -0.12
        # tolerance=8% → drawdown candidato -0.08 (más restrictivo)
        # debe quedar el de tolerancia.
        kyc = _build_neutral_kyc_for_profile(
            "moderado",
            financial_loss_capacity_pct=12.0,
            emotional_loss_tolerance_pct=8.0,
        )
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert b.max_drawdown == pytest.approx(-0.08)


# ── 8. Moneda ─────────────────────────────────────────────────────────────


class TestMoneda:
    def test_preferred_currency_se_propaga_al_risk_budget(self):
        kyc = _build_neutral_kyc_for_profile("moderado", preferred_currency="EUR")
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert b.preferred_currency == "EUR"

    def test_preferred_currency_usd(self):
        kyc = _build_neutral_kyc_for_profile("moderado", preferred_currency="USD")
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert b.preferred_currency == "USD"


# ── 9. Perfil desconocido ─────────────────────────────────────────────────


class TestPerfilDesconocido:
    def test_perfil_invalido_lanza_value_error(self):
        kyc = _build_kyc()
        goal = _build_goal()
        with pytest.raises(ValueError, match="approved_profile_name"):
            RiskBudgetBuilder().build("super-agresivo", kyc, goal)

    def test_perfil_vacio_lanza_value_error(self):
        kyc = _build_kyc()
        goal = _build_goal()
        with pytest.raises(ValueError):
            RiskBudgetBuilder().build("", kyc, goal)

    def test_perfil_none_lanza_value_error(self):
        kyc = _build_kyc()
        goal = _build_goal()
        with pytest.raises(ValueError):
            RiskBudgetBuilder().build(None, kyc, goal)  # type: ignore[arg-type]

    def test_todos_los_perfiles_validos_construyen_budget(self):
        for profile in VALID_PROFILES:
            kyc = _build_neutral_kyc_for_profile(
                profile,
                experience=InvestorExperience.ADVANCED,
                prefers_simple_products=False,
            )
            goal = _build_goal(horizon_years=10)
            b = RiskBudgetBuilder().build(profile, kyc, goal)
            assert b.profile_name == profile


# ── 10. Serialización ─────────────────────────────────────────────────────


class TestSerializacion:
    def test_to_dict_es_serializable_a_json(self):
        kyc = _build_neutral_kyc_for_profile("moderado")
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        payload = json.dumps(b.to_dict())
        parsed = json.loads(payload)
        assert parsed["profile_name"] == "moderado"
        assert parsed["target_volatility"] == pytest.approx(0.075)

    def test_to_dict_contiene_todos_los_campos(self):
        kyc = _build_neutral_kyc_for_profile("moderado")
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        d = b.to_dict()
        expected_keys = {
            "profile_name",
            "target_volatility",
            "max_volatility",
            "max_drawdown",
            "min_liquidity",
            "max_equity",
            "max_high_yield",
            "max_single_asset",
            "max_sector_exposure",
            "max_duration",
            "complex_products_allowed",
            "preferred_currency",
            "notes",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_notes_es_lista(self):
        kyc = _build_neutral_kyc_for_profile("moderado", liquidity_need_pct=0.20)
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert isinstance(b.to_dict()["notes"], list)


# ── 11. declared_return_expectation_pct no afecta el resultado ────────────


class TestIndependenciaDeDeclaredReturnExpectation:
    def test_dos_kycs_identicos_salvo_declared_return_producen_mismo_budget(self):
        """
        INVARIANTE central (DD-003): declared_return_expectation_pct es solo
        informativo. NO debe afectar la construcción del RiskBudget.
        """
        kyc_sin = _build_neutral_kyc_for_profile("moderado")
        kyc_con_alto = replace(kyc_sin, declared_return_expectation_pct=0.30)
        kyc_con_bajo = replace(kyc_sin, declared_return_expectation_pct=0.01)

        builder = RiskBudgetBuilder()
        goal = _build_goal(horizon_years=10)
        b_sin = builder.build("moderado", kyc_sin, goal)
        b_alto = builder.build("moderado", kyc_con_alto, goal)
        b_bajo = builder.build("moderado", kyc_con_bajo, goal)

        # Los presupuestos deben ser idénticos en todos los campos numéricos
        # y de flags. Las notas también deben coincidir.
        assert b_sin.to_dict() == b_alto.to_dict()
        assert b_sin.to_dict() == b_bajo.to_dict()

    def test_declared_return_no_modifica_volatilidad(self):
        kyc_a = _build_neutral_kyc_for_profile("moderado", declared_return_expectation_pct=0.50)
        kyc_b = _build_neutral_kyc_for_profile("moderado", declared_return_expectation_pct=None)
        b_a = RiskBudgetBuilder().build("moderado", kyc_a, _build_goal(horizon_years=10))
        b_b = RiskBudgetBuilder().build("moderado", kyc_b, _build_goal(horizon_years=10))
        assert b_a.target_volatility == b_b.target_volatility
        assert b_a.max_volatility == b_b.max_volatility


# ── 12. Notas explicativas ────────────────────────────────────────────────


class TestNotas:
    def test_kyc_neutral_no_genera_notas_extra(self):
        """
        Un KYC con tolerancia y capacidad altas, horizonte largo, sin liquidez
        ni preferencia por simples, no debería generar notas restrictivas.
        """
        kyc = _build_neutral_kyc_for_profile(
            "moderado",
            liquidity_need_pct=0.0,
            prefers_simple_products=False,
            experience=InvestorExperience.MODERATE,
        )
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        # Puede tener 0 notas o solo la de liquidez si fuera distinto.
        assert len(b.notes) == 0

    def test_kyc_restrictivo_genera_multiples_notas(self):
        kyc = _build_neutral_kyc_for_profile(
            "moderado",
            liquidity_need_pct=0.30,
            financial_loss_capacity_pct=8.0,
            emotional_loss_tolerance_pct=8.0,
            prefers_simple_products=True,
        )
        b = RiskBudgetBuilder().build("moderado", kyc, _build_goal(horizon_years=10))
        assert len(b.notes) >= 2


# ── 13. RiskBudget directo: validaciones del dataclass ────────────────────


class TestRiskBudgetDataclass:
    def test_max_volatility_menor_que_target_lanza_error(self):
        with pytest.raises(ValueError, match="max_volatility"):
            RiskBudget(
                profile_name="moderado",
                target_volatility=0.10,
                max_volatility=0.05,
                max_drawdown=-0.15,
                min_liquidity=0.0,
                max_equity=0.40,
                max_high_yield=0.10,
                max_single_asset=0.15,
                max_sector_exposure=0.30,
                max_duration=5.0,
                complex_products_allowed=False,
                preferred_currency="USD",
            )

    def test_drawdown_positivo_lanza_error(self):
        with pytest.raises(ValueError, match="max_drawdown"):
            RiskBudget(
                profile_name="moderado",
                target_volatility=0.075,
                max_volatility=0.10,
                max_drawdown=0.05,
                min_liquidity=0.0,
                max_equity=0.40,
                max_high_yield=0.10,
                max_single_asset=0.15,
                max_sector_exposure=0.30,
                max_duration=5.0,
                complex_products_allowed=False,
                preferred_currency="USD",
            )

    def test_min_liquidity_fuera_de_rango_lanza_error(self):
        with pytest.raises(ValueError, match="min_liquidity"):
            RiskBudget(
                profile_name="moderado",
                target_volatility=0.075,
                max_volatility=0.10,
                max_drawdown=-0.15,
                min_liquidity=1.5,
                max_equity=0.40,
                max_high_yield=0.10,
                max_single_asset=0.15,
                max_sector_exposure=0.30,
                max_duration=5.0,
                complex_products_allowed=False,
                preferred_currency="USD",
            )

    def test_preferred_currency_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="preferred_currency"):
            RiskBudget(
                profile_name="moderado",
                target_volatility=0.075,
                max_volatility=0.10,
                max_drawdown=-0.15,
                min_liquidity=0.0,
                max_equity=0.40,
                max_high_yield=0.10,
                max_single_asset=0.15,
                max_sector_exposure=0.30,
                max_duration=5.0,
                complex_products_allowed=False,
                preferred_currency="",
            )


# ── 14. Combinación de reglas: caso integrado ─────────────────────────────


class TestCombinacionDeReglas:
    def test_caso_realista_perfil_moderado_con_multiples_ajustes(self):
        """
        Cliente con perfil moderado pero:
        - horizonte de 3 años → recorta duration
        - liquidez 25%
        - tolerancia emocional 10% → recorta drawdown y vol
        - experiencia basica → bloquea complex y limita single asset
        - prefiere simples
        """
        kyc = _build_kyc(
            liquidity_need_pct=0.25,
            experience=InvestorExperience.BASIC,
            prefers_simple_products=True,
            emotional_loss_tolerance_pct=10.0,
            financial_loss_capacity_pct=30.0,
            preferred_currency="USD",
        )
        goal = _build_goal(horizon_years=3)
        b = RiskBudgetBuilder().build("moderado", kyc, goal)

        assert b.profile_name == "moderado"
        assert b.min_liquidity == pytest.approx(0.25)
        assert b.max_duration == pytest.approx(3.0)  # horizonte medio
        assert b.complex_products_allowed is False
        assert b.max_single_asset <= 0.15
        # tolerancia emocional 10% → drawdown debe estar acotado a -0.10
        assert b.max_drawdown == pytest.approx(-0.10)
        # volatilidad reducida proporcionalmente desde el base 0.075
        assert b.target_volatility < 0.075
        assert b.max_volatility < 0.100
        # múltiples notas
        assert len(b.notes) >= 3
