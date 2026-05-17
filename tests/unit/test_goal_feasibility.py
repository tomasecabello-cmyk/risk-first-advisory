"""
Tests unitarios para GoalFeasibilityEngine.

Principio central:
    GoalFeasibilityEngine NO recibe KYCData.
    Opera solo con FinancialGoal + approved_profile_name.
    declared_return_expectation_pct no interviene en ningún cálculo.

Casos cubiertos:
    1. Caso viable/marginal para perfil conservador.
    2. Caso inviable con objetivo agresivo para perfil moderado.
    3. Objetivo ya alcanzado (required_return = 0.0).
    4. Aportes periódicos reducen el retorno requerido.
    5. Independencia total de KYCData.
    6. Perfil desconocido → ValueError.
    7. FeasibilityReport.to_dict() es serializable a JSON.
    8. Disclaimer presente en todos los reportes.

Valores pre-verificados antes de codificar los tests:
    viable-conservador : req ≈ 3.714%,  ach = 4.0%,  gap = -0.286% → MARGINAL
    inviable           : req ≈ 25.99%,  ach = 7.0%,  gap = +18.99% → INVIABLE
    ya-alcanzado       : req = 0.0%,    ach = 7.0%,  gap = -7.0%   → VIABLE
    con-aportes        : req ≈ 5.706%,  ach = 7.0%,  gap = -1.294% → MARGINAL
    kyc-independence   : req ≈ 5.963%,  ach = 7.0%,  gap = -1.037% → MARGINAL
    serializacion      : req ≈ 4.564%,  ach = 7.0%,  gap = -2.436% → VIABLE
"""

import inspect
import json
import math

import pytest

from risk_first_advisory.kyc.models import (
    ESGProfile,
    ESGStrictnessLevel,
    FinancialGoal,
    InvestmentObjective,
    InvestorExperience,
    KYCData,
)
from risk_first_advisory.rules_layer.goal_feasibility import (
    DISCLAIMER,
    FeasibilityReport,
    FeasibilityStatus,
    GoalFeasibilityEngine,
)


# ── Helper ───────────────────────────────────────────────────────────────────


def make_goal(
    initial: float,
    target: float,
    horizon: int,
    contribution: float = 0.0,
    freq: float = 1.0,
    target_flexible: bool = True,
    horizon_flexible: bool = True,
) -> FinancialGoal:
    """Construye un FinancialGoal con los campos mínimos requeridos."""
    return FinancialGoal(
        initial_capital_usd=initial,
        target_capital_usd=target,
        horizon_years=horizon,
        periodic_contribution_usd=contribution,
        contribution_frequency_years=freq,
        target_is_flexible=target_flexible,
        horizon_is_flexible=horizon_flexible,
    )


# ── Test 1: caso viable/marginal para perfil conservador ─────────────────────


class TestCasoConservador:
    """
    initial=500 000, target=600 000, horizon=5, contributions=0.
    required ≈ 3.714%  achievable (conservador) = 4.0%
    gap ≈ -0.286%  → dentro de la banda MARGINAL (±1.5%).
    """

    def test_status_es_viable_o_marginal(self):
        goal = make_goal(initial=500_000, target=600_000, horizon=5)
        report = GoalFeasibilityEngine().evaluate(goal, "conservador")
        assert report.status in (FeasibilityStatus.VIABLE, FeasibilityStatus.MARGINAL)

    def test_required_return_aproximado(self):
        # (600_000 / 500_000)^(1/5) - 1 ≈ 3.714 %
        goal = make_goal(initial=500_000, target=600_000, horizon=5)
        report = GoalFeasibilityEngine().evaluate(goal, "conservador")
        assert report.required_return_annual == pytest.approx(0.03714, abs=0.0005)

    def test_no_bloquea_portfolio(self):
        goal = make_goal(initial=500_000, target=600_000, horizon=5)
        report = GoalFeasibilityEngine().evaluate(goal, "conservador")
        assert report.block_portfolio_generation is False

    def test_achievable_es_el_del_perfil(self):
        goal = make_goal(initial=500_000, target=600_000, horizon=5)
        report = GoalFeasibilityEngine().evaluate(goal, "conservador")
        assert report.achievable_return_annual == pytest.approx(0.04)


# ── Test 2: caso inviable ────────────────────────────────────────────────────


class TestCasoInviable:
    """
    initial=100 000, target=200 000, horizon=3, contributions=0, perfil=moderado.
    required ≈ 25.99%  achievable = 7.0%  gap ≈ +18.99% → INVIABLE.
    """

    def test_status_inviable(self):
        goal = make_goal(initial=100_000, target=200_000, horizon=3)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.status == FeasibilityStatus.INVIABLE

    def test_bloquea_portfolio(self):
        goal = make_goal(initial=100_000, target=200_000, horizon=3)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.block_portfolio_generation is True

    def test_required_muy_superior_al_alcanzable(self):
        # 2^(1/3) - 1 ≈ 25.99 %
        goal = make_goal(initial=100_000, target=200_000, horizon=3)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.required_return_annual > 0.20
        assert report.gap > MARGINAL_BAND_VALUE()

    def test_suggested_actions_incluye_alternativas_clave(self):
        goal = make_goal(initial=100_000, target=200_000, horizon=3)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        text = " ".join(report.suggested_actions).lower()
        assert "horizonte" in text
        assert "reducir" in text or "objetivo" in text
        assert "aportes" in text

    def test_suggested_actions_menciona_revision_con_condicion(self):
        """Revisar el perfil solo si el asesor valida tolerancia y capacidad."""
        goal = make_goal(initial=100_000, target=200_000, horizon=3)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        text = " ".join(report.suggested_actions).lower()
        assert "asesor" in text or "tolerancia" in text or "capacidad" in text


def MARGINAL_BAND_VALUE() -> float:
    """Devuelve el valor de la constante MARGINAL_BAND para las assertions."""
    from risk_first_advisory.rules_layer.goal_feasibility import MARGINAL_BAND
    return MARGINAL_BAND


# ── Test 3: objetivo ya alcanzado ────────────────────────────────────────────


class TestObjetivoYaAlcanzado:
    """
    initial=100 000, target=100 000, horizon=5, contributions=0.
    FV(0) = initial = target → required_return = 0.0.
    gap = 0.0 - 0.07 = -0.07 → VIABLE.
    """

    def test_required_return_es_cero(self):
        goal = make_goal(initial=100_000, target=100_000, horizon=5)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.required_return_annual == pytest.approx(0.0, abs=1e-9)

    def test_status_es_viable(self):
        goal = make_goal(initial=100_000, target=100_000, horizon=5)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.status == FeasibilityStatus.VIABLE

    def test_gap_muy_negativo(self):
        # gap = 0.0 - 0.07 = -0.07, claramente por debajo de -MARGINAL_BAND
        goal = make_goal(initial=100_000, target=100_000, horizon=5)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.gap == pytest.approx(-0.07, abs=1e-9)

    def test_no_bloquea_portfolio(self):
        goal = make_goal(initial=100_000, target=100_000, horizon=5)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.block_portfolio_generation is False

    def test_target_mayor_que_initial_con_cero_retorno(self):
        """Capital inicial supera el objetivo: también required = 0."""
        goal = make_goal(initial=200_000, target=150_000, horizon=5,
                         contribution=5_000)  # necesario por validación
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.required_return_annual == pytest.approx(0.0, abs=1e-9)


# ── Test 4: aportes periódicos reducen el retorno requerido ──────────────────


class TestCasoConAportes:
    """
    initial=100 000, target=160 000, horizon=5.
    Sin aportes  : req ≈ 9.856% → INVIABLE para moderado.
    Con aportes 5 000/año: req ≈ 5.706% → MARGINAL para moderado.
    """

    def test_required_menor_con_aportes(self):
        goal_sin = make_goal(initial=100_000, target=160_000, horizon=5)
        goal_con = make_goal(initial=100_000, target=160_000, horizon=5,
                             contribution=5_000)
        engine = GoalFeasibilityEngine()
        r_sin = engine.evaluate(goal_sin, "moderado").required_return_annual
        r_con = engine.evaluate(goal_con, "moderado").required_return_annual
        assert r_con < r_sin

    def test_required_con_aportes_en_rango_razonable(self):
        # req ≈ 5.706 % → dentro de (4%, 10%)
        goal = make_goal(initial=100_000, target=160_000, horizon=5,
                         contribution=5_000)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert 0.04 < report.required_return_annual < 0.10

    def test_required_con_aportes_valor_exacto(self):
        goal = make_goal(initial=100_000, target=160_000, horizon=5,
                         contribution=5_000)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.required_return_annual == pytest.approx(0.05706, abs=0.0005)

    def test_gap_negativo_con_aportes(self):
        goal = make_goal(initial=100_000, target=160_000, horizon=5,
                         contribution=5_000)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        # gap = 5.706% - 7.0% = -1.294%
        assert report.gap < 0


# ── Test 5: independencia total de KYCData ───────────────────────────────────


class TestIndependenciaDelKYC:
    """
    GoalFeasibilityEngine no recibe KYCData.
    Un KYC con declared_return_expectation_pct=25% no debe afectar el resultado.
    """

    def test_evaluate_no_acepta_kyc_como_parametro(self):
        sig = inspect.signature(GoalFeasibilityEngine.evaluate)
        param_names = list(sig.parameters.keys())
        # Solo: self, goal, approved_profile_name
        assert "kyc" not in param_names
        assert "kyc_data" not in param_names
        assert len(param_names) == 3

    def test_mismo_goal_produce_mismo_resultado_independientemente_del_kyc_externo(self):
        """
        Dos evaluaciones del mismo FinancialGoal producen resultado idéntico.
        Ningún estado del KYC externo puede interferir.
        """
        goal = make_goal(initial=200_000, target=300_000, horizon=7)
        engine = GoalFeasibilityEngine()
        report_a = engine.evaluate(goal, "moderado")
        report_b = engine.evaluate(goal, "moderado")
        assert report_a.required_return_annual == pytest.approx(
            report_b.required_return_annual, abs=1e-12
        )
        assert report_a.status == report_b.status

    def test_declared_return_expectation_pct_alto_no_cambia_requerido(self):
        """
        Se construye un KYC con declared_return_expectation_pct=0.25 (25%).
        El engine NO recibe ese KYC; el retorno requerido viene solo de FinancialGoal.
        required ≈ (300 000/200 000)^(1/7) - 1 ≈ 5.963%  ≠ 25%.
        """
        # Construimos el KYC para demostrar que existe y tiene expectativa alta
        _kyc_with_high_expectation = KYCData(
            age=40,
            annual_income_usd=150_000,
            approx_net_worth_usd=500_000,
            investment_objective=InvestmentObjective.GROWTH,
            time_horizon_years=7,
            liquidity_need_pct=0.10,
            experience=InvestorExperience.MODERATE,
            emotional_loss_tolerance_pct=20.0,
            financial_loss_capacity_pct=30.0,
            preferred_currency="USD",
            needs_income=False,
            prefers_simple_products=False,
            jurisdiction="AR",
            esg_profile=ESGProfile(strictness_level=ESGStrictnessLevel.NONE),
            declared_return_expectation_pct=0.25,  # 25% declarado — no interviene
        )

        goal = make_goal(initial=200_000, target=300_000, horizon=7)
        # El engine NO recibe _kyc_with_high_expectation
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")

        # El retorno requerido es ≈ 5.963%, no el 25% del KYC
        assert report.required_return_annual == pytest.approx(0.05963, abs=0.001)
        assert report.required_return_annual < 0.10


# ── Test 6: perfil desconocido ───────────────────────────────────────────────


class TestPerfilDesconocido:
    """Perfil no registrado en el catálogo → ValueError."""

    def test_perfil_invalido_levanta_value_error(self):
        goal = make_goal(initial=100_000, target=150_000, horizon=5)
        engine = GoalFeasibilityEngine()
        with pytest.raises(ValueError, match="Perfil desconocido"):
            engine.evaluate(goal, "ultra-agresivo")

    def test_perfil_vacio_levanta_value_error(self):
        goal = make_goal(initial=100_000, target=150_000, horizon=5)
        engine = GoalFeasibilityEngine()
        with pytest.raises(ValueError, match="Perfil desconocido"):
            engine.evaluate(goal, "")

    def test_perfil_case_sensitive(self):
        """'Moderado' (mayúscula) no es 'moderado'."""
        goal = make_goal(initial=100_000, target=150_000, horizon=5)
        engine = GoalFeasibilityEngine()
        with pytest.raises(ValueError, match="Perfil desconocido"):
            engine.evaluate(goal, "Moderado")

    def test_perfiles_validos_no_lanzan_excepcion(self):
        goal = make_goal(initial=100_000, target=110_000, horizon=5)
        engine = GoalFeasibilityEngine()
        for profile in ("conservador", "moderado-defensivo", "moderado",
                        "moderado-agresivo", "agresivo"):
            report = engine.evaluate(goal, profile)
            assert isinstance(report, FeasibilityReport)


# ── Test 7: serialización ────────────────────────────────────────────────────


class TestSerializacion:
    """FeasibilityReport.to_dict() produce un dict JSON-serializable."""

    def _report(self) -> FeasibilityReport:
        goal = make_goal(initial=200_000, target=250_000, horizon=5)
        return GoalFeasibilityEngine().evaluate(goal, "moderado")

    def test_to_dict_devuelve_dict(self):
        assert isinstance(self._report().to_dict(), dict)

    def test_to_dict_tiene_todas_las_claves_requeridas(self):
        required_keys = {
            "status",
            "required_return_annual",
            "achievable_return_annual",
            "gap",
            "reason",
            "suggested_actions",
            "block_portfolio_generation",
            "disclaimer",
        }
        assert required_keys <= self._report().to_dict().keys()

    def test_to_dict_status_es_string(self):
        d = self._report().to_dict()
        assert isinstance(d["status"], str)

    def test_to_dict_suggested_actions_es_lista(self):
        d = self._report().to_dict()
        assert isinstance(d["suggested_actions"], list)

    def test_to_dict_es_json_serializable(self):
        d = self._report().to_dict()
        serialized = json.dumps(d)
        assert len(serialized) > 0

    def test_to_dict_round_trip(self):
        """Los valores numéricos sobreviven json.dumps → json.loads."""
        d = self._report().to_dict()
        d2 = json.loads(json.dumps(d))
        assert d2["status"] == d["status"]
        assert d2["required_return_annual"] == pytest.approx(
            d["required_return_annual"], rel=1e-9
        )

    def test_to_dict_no_contiene_objetos_enum(self):
        """El dict no debe contener instancias de Enum — solo str."""
        d = self._report().to_dict()
        for v in d.values():
            assert not isinstance(v, FeasibilityStatus)

    def test_to_dict_undetermined_tiene_none_en_lugar_de_nan(self):
        """Para status UNDETERMINED, los NaN se convierten a None en to_dict."""
        # Usamos un engine con un perfil custom y un goal físicamente imposible
        # (required > 500% anual)
        engine = GoalFeasibilityEngine(
            achievable_returns={"super-imposible": 0.03}
        )
        # Con techo de bisección en 500%, un goal absurdo fuerza UNDETERMINED
        from risk_first_advisory.rules_layer.goal_feasibility import BISECTION_MAX_RATE
        goal_absurdo = FinancialGoal(
            initial_capital_usd=1.0,
            target_capital_usd=(1.0 + BISECTION_MAX_RATE) ** 10 * 10,  # > FV at max
            horizon_years=10,
            periodic_contribution_usd=0.0,
            contribution_frequency_years=1.0,
            target_is_flexible=False,
            horizon_is_flexible=False,
        )
        report = engine.evaluate(goal_absurdo, "super-imposible")
        assert report.status == FeasibilityStatus.UNDETERMINED
        d = report.to_dict()
        assert d["required_return_annual"] is None
        assert d["gap"] is None
        # Y es JSON-serializable (None → null)
        serialized = json.dumps(d)
        assert "null" in serialized


# ── Test 8: disclaimer ───────────────────────────────────────────────────────


class TestDisclaimer:
    """El disclaimer debe existir y ser el texto exacto en todos los reportes."""

    @pytest.mark.parametrize("profile,initial,target,horizon", [
        ("conservador", 100_000, 105_000, 3),
        ("moderado", 100_000, 200_000, 3),
        ("agresivo", 100_000, 110_000, 5),
        ("moderado-defensivo", 500_000, 550_000, 4),
        ("moderado-agresivo", 200_000, 400_000, 8),
    ])
    def test_disclaimer_siempre_presente_y_no_vacio(
        self, profile: str, initial: float, target: float, horizon: int
    ) -> None:
        goal = make_goal(initial=initial, target=target, horizon=horizon)
        report = GoalFeasibilityEngine().evaluate(goal, profile)
        assert report.disclaimer
        assert len(report.disclaimer) > 0

    def test_disclaimer_menciona_garantia(self):
        goal = make_goal(initial=200_000, target=250_000, horizon=5)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert "garantizados" in report.disclaimer

    def test_disclaimer_es_texto_exacto(self):
        goal = make_goal(initial=200_000, target=250_000, horizon=5)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.disclaimer == DISCLAIMER

    def test_disclaimer_presente_en_caso_viable(self):
        goal = make_goal(initial=100_000, target=100_000, horizon=5)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.status == FeasibilityStatus.VIABLE
        assert report.disclaimer == DISCLAIMER

    def test_disclaimer_presente_en_caso_inviable(self):
        goal = make_goal(initial=100_000, target=200_000, horizon=3)
        report = GoalFeasibilityEngine().evaluate(goal, "moderado")
        assert report.status == FeasibilityStatus.INVIABLE
        assert report.disclaimer == DISCLAIMER

    def test_disclaimer_presente_en_to_dict(self):
        goal = make_goal(initial=200_000, target=250_000, horizon=5)
        d = GoalFeasibilityEngine().evaluate(goal, "moderado").to_dict()
        assert d["disclaimer"] == DISCLAIMER