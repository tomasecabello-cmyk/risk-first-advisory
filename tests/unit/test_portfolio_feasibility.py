"""
Tests para PortfolioFeasibilityChecker y PortfolioFeasibilityResult.

Cubre:
    - Validaciones del dataclass.
    - Check A: universo vacío.
    - Check B: tickers desalineados.
    - Check C: max_single_asset insuficiente.
    - Check D: min vol alcanzable > max_volatility.
    - Check E: universo chico (warning).
    - Check F: concentración alta requerida (warning).
    - Acumulación de failed_checks.
    - Status final consolidado.
    - Inmutabilidad de inputs.
    - Serialización JSON.
"""

from __future__ import annotations

import copy
import json

import pytest

from risk_first_advisory.data_layer.covariance import (
    CovarianceEngine,
    CovarianceMatrix,
)
from risk_first_advisory.data_layer.market_data import MarketDataSnapshot
from risk_first_advisory.data_layer.return_estimator import ReturnEstimate
from risk_first_advisory.models.risk_budget import RiskBudget
from risk_first_advisory.portfolio_layer.feasibility import (
    FC_MAX_SINGLE_ASSET_TOO_LOW,
    FC_MIN_VOL_EXCEEDS_BUDGET,
    FC_NO_ASSETS,
    FC_TICKER_MISMATCH,
    WARN_CONCENTRATION_REQUIRED,
    WARN_LOW_DIVERSIFICATION,
    PortfolioFeasibilityChecker,
    PortfolioFeasibilityResult,
    PortfolioFeasibilityStatus,
)

# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _snap(ticker: str, asset_class: str, vol: float) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        ticker=ticker,
        expected_return_annual=0.05,
        volatility_annual=vol,
        liquidity_score=0.9,
        expense_ratio=0.001,
        duration=None,
        asset_class=asset_class,
        currency="USD",
    )


def _estimate(ticker: str, ret: float = 0.05) -> ReturnEstimate:
    return ReturnEstimate(
        ticker=ticker,
        raw_expected_return_annual=ret,
        expense_ratio=0.001,
        esg_adjustment=0.0,
        data_quality_adjustment=0.0,
        adjusted_expected_return_annual=ret - 0.001,
        reason_codes=[],
        notes=[],
    )


def _build_cov(snaps: list[MarketDataSnapshot]) -> CovarianceMatrix:
    return CovarianceEngine().build(snaps)


def _risk_budget(
    max_single_asset: float = 0.40,
    max_volatility: float = 0.20,
    target_volatility: float = 0.12,
) -> RiskBudget:
    return RiskBudget(
        profile_name="moderado",
        target_volatility=target_volatility,
        max_volatility=max_volatility,
        max_drawdown=-0.20,
        min_liquidity=0.0,
        max_equity=1.0,
        max_high_yield=0.30,
        max_single_asset=max_single_asset,
        max_sector_exposure=0.40,
        max_duration=10.0,
        complex_products_allowed=False,
        preferred_currency="USD",
    )


def _build_universe(n: int = 4) -> tuple[list[ReturnEstimate], CovarianceMatrix]:
    """Universo de N activos diversificados con volatilidades moderadas."""
    assets = [
        ("BIL", "cash", 0.005),
        ("AGG", "bond", 0.055),
        ("VEA", "equity", 0.165),
        ("HYG", "high_yield", 0.085),
        ("VTI", "equity", 0.150),
        ("BND", "bond", 0.054),
        ("SGOV", "cash", 0.004),
        ("TLT", "bond", 0.130),
    ]
    chosen = assets[:n]
    snaps = [_snap(t, ac, v) for t, ac, v in chosen]
    cov = _build_cov(snaps)
    estimates = [_estimate(t) for t, _, _ in chosen]
    return estimates, cov


@pytest.fixture
def checker() -> PortfolioFeasibilityChecker:
    return PortfolioFeasibilityChecker()


# ─────────────────────────────────────────────────────────────────────────
# Validaciones del dataclass
# ─────────────────────────────────────────────────────────────────────────


class TestResultDataclass:
    def _baseline(self, **overrides) -> dict:
        defaults = dict(
            status=PortfolioFeasibilityStatus.FEASIBLE,
            is_feasible=True,
            asset_count=4,
            required_min_single_asset_cap=0.25,
            actual_max_single_asset=0.40,
            min_achievable_volatility=0.06,
            max_allowed_volatility=0.20,
        )
        defaults.update(overrides)
        return defaults

    def test_result_valido_se_construye(self):
        r = PortfolioFeasibilityResult(**self._baseline())
        assert r.is_feasible is True
        assert r.status == PortfolioFeasibilityStatus.FEASIBLE

    def test_status_no_enum_lanza_error(self):
        with pytest.raises(ValueError, match="status"):
            PortfolioFeasibilityResult(
                **self._baseline(status="feasible")  # type: ignore[arg-type]
            )

    def test_is_feasible_no_bool_lanza_error(self):
        with pytest.raises(ValueError, match="is_feasible"):
            PortfolioFeasibilityResult(
                **self._baseline(is_feasible="true")  # type: ignore[arg-type]
            )

    def test_asset_count_negativo_lanza_error(self):
        with pytest.raises(ValueError, match="asset_count"):
            PortfolioFeasibilityResult(**self._baseline(asset_count=-1))

    def test_required_cap_fuera_de_rango_lanza_error(self):
        with pytest.raises(ValueError, match="required_min_single_asset_cap"):
            PortfolioFeasibilityResult(
                **self._baseline(required_min_single_asset_cap=1.5)
            )

    def test_actual_cap_fuera_de_rango_lanza_error(self):
        with pytest.raises(ValueError, match="actual_max_single_asset"):
            PortfolioFeasibilityResult(
                **self._baseline(actual_max_single_asset=-0.1)
            )

    def test_min_vol_negativa_lanza_error(self):
        with pytest.raises(ValueError, match="min_achievable_volatility"):
            PortfolioFeasibilityResult(
                **self._baseline(min_achievable_volatility=-0.01)
            )

    def test_min_vol_none_es_valida(self):
        r = PortfolioFeasibilityResult(
            **self._baseline(min_achievable_volatility=None)
        )
        assert r.min_achievable_volatility is None

    def test_max_vol_negativa_lanza_error(self):
        with pytest.raises(ValueError, match="max_allowed_volatility"):
            PortfolioFeasibilityResult(
                **self._baseline(max_allowed_volatility=-0.1)
            )

    def test_failed_checks_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="failed_checks"):
            PortfolioFeasibilityResult(
                **self._baseline(failed_checks="foo")  # type: ignore[arg-type]
            )

    def test_warnings_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="warnings"):
            PortfolioFeasibilityResult(
                **self._baseline(warnings="foo")  # type: ignore[arg-type]
            )

    def test_suggested_actions_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="suggested_actions"):
            PortfolioFeasibilityResult(
                **self._baseline(suggested_actions="foo")  # type: ignore[arg-type]
            )

    def test_notes_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="notes"):
            PortfolioFeasibilityResult(
                **self._baseline(notes="foo")  # type: ignore[arg-type]
            )

    def test_has_warnings_funciona(self):
        r = PortfolioFeasibilityResult(
            **self._baseline(warnings=["alguna"]),
        )
        assert r.has_warnings is True

    def test_has_warnings_false_si_vacia(self):
        r = PortfolioFeasibilityResult(**self._baseline())
        assert r.has_warnings is False

    def test_has_failed_checks_funciona(self):
        r = PortfolioFeasibilityResult(
            **self._baseline(
                status=PortfolioFeasibilityStatus.INFEASIBLE,
                is_feasible=False,
                failed_checks=["X"],
            )
        )
        assert r.has_failed_checks is True

    def test_has_failed_checks_false_si_vacia(self):
        r = PortfolioFeasibilityResult(**self._baseline())
        assert r.has_failed_checks is False


# ─────────────────────────────────────────────────────────────────────────
# Check A: universo vacío
# ─────────────────────────────────────────────────────────────────────────


class TestCheckEmptyUniverse:
    def test_universo_vacio_infeasible(self, checker):
        # Necesitamos una cov_matrix mínima válida (1 ticker dummy);
        # el checker debe rechazar antes de mirar la matriz porque ve
        # asset_count=0.
        estimates: list[ReturnEstimate] = []
        cov = _build_cov([_snap("X", "equity", 0.10)])
        rb = _risk_budget()
        result = checker.evaluate(estimates, cov, rb)
        assert result.status == PortfolioFeasibilityStatus.INFEASIBLE
        assert result.is_feasible is False
        assert FC_NO_ASSETS in result.failed_checks
        assert result.asset_count == 0
        assert result.required_min_single_asset_cap == 0.0
        assert result.suggested_actions  # no vacío


# ─────────────────────────────────────────────────────────────────────────
# Check B: tickers desalineados
# ─────────────────────────────────────────────────────────────────────────


class TestCheckTickerMismatch:
    def test_tickers_distintos_infeasible(self, checker):
        snaps = [_snap("A", "equity", 0.10), _snap("B", "bond", 0.05)]
        cov = _build_cov(snaps)
        estimates = [_estimate("X"), _estimate("Y")]
        rb = _risk_budget()
        result = checker.evaluate(estimates, cov, rb)
        assert result.status == PortfolioFeasibilityStatus.INFEASIBLE
        assert FC_TICKER_MISMATCH in result.failed_checks

    def test_mismo_set_distinto_orden_infeasible(self, checker):
        snaps = [_snap("A", "equity", 0.10), _snap("B", "bond", 0.05)]
        cov = _build_cov(snaps)
        # Estimates en orden invertido
        estimates = [_estimate("B"), _estimate("A")]
        rb = _risk_budget()
        result = checker.evaluate(estimates, cov, rb)
        assert FC_TICKER_MISMATCH in result.failed_checks


# ─────────────────────────────────────────────────────────────────────────
# Check C: max_single_asset insuficiente
# ─────────────────────────────────────────────────────────────────────────


class TestCheckMaxSingleAssetTooLow:
    def test_4_activos_cap_015_infeasible(self, checker):
        estimates, cov = _build_universe(n=4)
        rb = _risk_budget(max_single_asset=0.15)
        result = checker.evaluate(estimates, cov, rb)
        assert result.status == PortfolioFeasibilityStatus.INFEASIBLE
        assert FC_MAX_SINGLE_ASSET_TOO_LOW in result.failed_checks
        assert result.required_min_single_asset_cap == pytest.approx(0.25)
        assert result.actual_max_single_asset == pytest.approx(0.15)

    def test_4_activos_cap_025_no_falla_por_concentracion(self, checker):
        estimates, cov = _build_universe(n=4)
        rb = _risk_budget(
            max_single_asset=0.25,
            max_volatility=0.20,
            target_volatility=0.10,
        )
        result = checker.evaluate(estimates, cov, rb)
        # No debe fallar por max_single_asset
        assert FC_MAX_SINGLE_ASSET_TOO_LOW not in result.failed_checks

    def test_4_activos_cap_0251_es_factible_por_tolerancia(self, checker):
        estimates, cov = _build_universe(n=4)
        rb = _risk_budget(
            max_single_asset=0.2501,
            max_volatility=0.20,
            target_volatility=0.10,
        )
        result = checker.evaluate(estimates, cov, rb)
        assert FC_MAX_SINGLE_ASSET_TOO_LOW not in result.failed_checks

    def test_2_activos_cap_049_infeasible(self, checker):
        estimates, cov = _build_universe(n=2)
        rb = _risk_budget(max_single_asset=0.49)
        result = checker.evaluate(estimates, cov, rb)
        assert FC_MAX_SINGLE_ASSET_TOO_LOW in result.failed_checks


# ─────────────────────────────────────────────────────────────────────────
# Check D: min_achievable_volatility > max_volatility
# ─────────────────────────────────────────────────────────────────────────


class TestCheckMinVolExceedsBudget:
    def test_min_vol_se_calcula(self, checker):
        estimates, cov = _build_universe(n=4)
        rb = _risk_budget(max_single_asset=0.40, max_volatility=0.20)
        result = checker.evaluate(estimates, cov, rb)
        assert result.min_achievable_volatility is not None
        assert result.min_achievable_volatility >= 0.0

    def test_min_vol_excede_max_vol_infeasible(self, checker):
        # Universo con muchos equities (vol alta) y max_vol muy bajo
        snaps = [
            _snap("E1", "equity", 0.20),
            _snap("E2", "equity", 0.22),
            _snap("E3", "equity", 0.18),
            _snap("E4", "equity", 0.25),
        ]
        cov = _build_cov(snaps)
        estimates = [_estimate(s.ticker) for s in snaps]
        rb = _risk_budget(
            max_single_asset=0.40,
            max_volatility=0.05,  # muy bajo, imposible con equities corr=0.85
            target_volatility=0.05,
        )
        result = checker.evaluate(estimates, cov, rb)
        assert result.status == PortfolioFeasibilityStatus.INFEASIBLE
        assert FC_MIN_VOL_EXCEEDS_BUDGET in result.failed_checks
        assert result.min_achievable_volatility is not None
        assert result.min_achievable_volatility > rb.max_volatility

    def test_min_vol_dentro_del_budget_no_falla(self, checker):
        # Universo con cash dominante; min vol cercana a 0
        snaps = [
            _snap("BIL", "cash", 0.005),
            _snap("AGG", "bond", 0.055),
            _snap("BND", "bond", 0.054),
            _snap("SGOV", "cash", 0.004),
        ]
        cov = _build_cov(snaps)
        estimates = [_estimate(s.ticker) for s in snaps]
        rb = _risk_budget(
            max_single_asset=0.40,
            max_volatility=0.10,
            target_volatility=0.05,
        )
        result = checker.evaluate(estimates, cov, rb)
        assert FC_MIN_VOL_EXCEEDS_BUDGET not in result.failed_checks

    def test_min_vol_no_se_calcula_si_cap_infeasible(self, checker):
        """Si cap es infeasible, no tiene sentido calcular min vol —
        el checker reporta cap infeasible y omite el cálculo de vol."""
        estimates, cov = _build_universe(n=4)
        rb = _risk_budget(max_single_asset=0.15)
        result = checker.evaluate(estimates, cov, rb)
        assert FC_MAX_SINGLE_ASSET_TOO_LOW in result.failed_checks
        assert result.min_achievable_volatility is None


# ─────────────────────────────────────────────────────────────────────────
# Check E: universo chico (warning)
# ─────────────────────────────────────────────────────────────────────────


class TestCheckLowDiversification:
    def test_2_activos_genera_warning_si_feasible(self, checker):
        # 2 activos, caps suficientes y vols razonables
        snaps = [_snap("A", "cash", 0.01), _snap("B", "bond", 0.06)]
        cov = _build_cov(snaps)
        estimates = [_estimate("A"), _estimate("B")]
        rb = _risk_budget(
            max_single_asset=0.60,
            max_volatility=0.15,
            target_volatility=0.05,
        )
        result = checker.evaluate(estimates, cov, rb)
        assert result.is_feasible is True
        assert result.status == PortfolioFeasibilityStatus.WARNING
        assert WARN_LOW_DIVERSIFICATION in result.warnings

    def test_3_activos_no_genera_warning_low_diversification(self, checker):
        estimates, cov = _build_universe(n=3)
        rb = _risk_budget(
            max_single_asset=0.50,
            max_volatility=0.20,
            target_volatility=0.10,
        )
        result = checker.evaluate(estimates, cov, rb)
        assert WARN_LOW_DIVERSIFICATION not in result.warnings


# ─────────────────────────────────────────────────────────────────────────
# Check F: concentración alta requerida (warning)
# ─────────────────────────────────────────────────────────────────────────


class TestCheckHighConcentration:
    def test_3_activos_concentracion_alta_genera_warning(self, checker):
        # 3 activos → required_cap = 0.333 > 0.25 → warning
        estimates, cov = _build_universe(n=3)
        rb = _risk_budget(
            max_single_asset=0.50,
            max_volatility=0.20,
            target_volatility=0.10,
        )
        result = checker.evaluate(estimates, cov, rb)
        assert result.is_feasible is True
        # En 3 activos, required_cap = 0.333 > 0.25 → warning de concentración.
        assert WARN_CONCENTRATION_REQUIRED in result.warnings

    def test_5_activos_required_cap_02_no_warning(self, checker):
        estimates, cov = _build_universe(n=5)
        rb = _risk_budget(
            max_single_asset=0.40,
            max_volatility=0.20,
            target_volatility=0.10,
        )
        result = checker.evaluate(estimates, cov, rb)
        assert WARN_CONCENTRATION_REQUIRED not in result.warnings


# ─────────────────────────────────────────────────────────────────────────
# Caso factible y warning combinado
# ─────────────────────────────────────────────────────────────────────────


class TestStatusFinal:
    def test_caso_factible_devuelve_feasible(self, checker):
        estimates, cov = _build_universe(n=5)
        rb = _risk_budget(
            max_single_asset=0.40,
            max_volatility=0.20,
            target_volatility=0.10,
        )
        result = checker.evaluate(estimates, cov, rb)
        assert result.status == PortfolioFeasibilityStatus.FEASIBLE
        assert result.is_feasible is True
        assert result.failed_checks == []
        assert result.warnings == []

    def test_caso_warning_es_feasible_pero_status_warning(self, checker):
        # 2 activos → low diversification + posiblemente concentration
        snaps = [_snap("A", "cash", 0.01), _snap("B", "bond", 0.06)]
        cov = _build_cov(snaps)
        estimates = [_estimate("A"), _estimate("B")]
        rb = _risk_budget(
            max_single_asset=0.60,
            max_volatility=0.15,
            target_volatility=0.05,
        )
        result = checker.evaluate(estimates, cov, rb)
        assert result.is_feasible is True
        assert result.status == PortfolioFeasibilityStatus.WARNING
        assert result.warnings  # no vacío


# ─────────────────────────────────────────────────────────────────────────
# Acumulación de failed_checks
# ─────────────────────────────────────────────────────────────────────────


class TestAcumulacion:
    def test_failed_checks_acumula_multiples_razones(self, checker):
        """
        Caso construido para que falle por max_single_asset Y para que la
        suggested_actions tenga al menos dos entradas.
        Nota: cuando cap es infeasible, min_vol no se evalúa para no
        producir falsos diagnósticos; por eso D no se acumula con C.
        """
        # 5 activos con cap 0.10 → 5*0.10 = 0.5 < 1.0 → C falla.
        estimates, cov = _build_universe(n=5)
        rb = _risk_budget(
            max_single_asset=0.10,
            max_volatility=0.05,
            target_volatility=0.04,
        )
        result = checker.evaluate(estimates, cov, rb)
        assert result.status == PortfolioFeasibilityStatus.INFEASIBLE
        assert FC_MAX_SINGLE_ASSET_TOO_LOW in result.failed_checks
        assert len(result.suggested_actions) >= 1

    def test_failed_checks_acumula_cap_no_se_combina_con_min_vol(self, checker):
        """Confirma la política: si C falla, D se omite (min_vol = None)."""
        estimates, cov = _build_universe(n=4)
        rb = _risk_budget(
            max_single_asset=0.10,
            max_volatility=0.001, # imposible incluso si cap fuera ok
            target_volatility=0.0005
        )
        result = checker.evaluate(estimates, cov, rb)
        assert FC_MAX_SINGLE_ASSET_TOO_LOW in result.failed_checks
        # D no se acumula porque C la cortocircuita
        assert FC_MIN_VOL_EXCEEDS_BUDGET not in result.failed_checks
        assert result.min_achievable_volatility is None


# ─────────────────────────────────────────────────────────────────────────
# Suggested actions cuando hay infeasibility
# ─────────────────────────────────────────────────────────────────────────


class TestSuggestedActions:
    def test_infeasible_siempre_tiene_suggested_actions(self, checker):
        # No assets
        cov = _build_cov([_snap("X", "equity", 0.10)])
        rb = _risk_budget()
        result = checker.evaluate([], cov, rb)
        assert result.suggested_actions

    def test_cap_too_low_tiene_suggested_actions(self, checker):
        estimates, cov = _build_universe(n=4)
        rb = _risk_budget(max_single_asset=0.10)
        result = checker.evaluate(estimates, cov, rb)
        assert result.suggested_actions
        # Mensaje específico de cap too low
        assert any(
            "max_single_asset" in s or "cash" in s
            for s in result.suggested_actions
        )

    def test_min_vol_exceeds_tiene_suggested_actions(self, checker):
        snaps = [
            _snap("E1", "equity", 0.20),
            _snap("E2", "equity", 0.22),
            _snap("E3", "equity", 0.18),
            _snap("E4", "equity", 0.25),
        ]
        cov = _build_cov(snaps)
        estimates = [_estimate(s.ticker) for s in snaps]
        rb = _risk_budget(
            max_single_asset=0.40,
            max_volatility=0.05,
            target_volatility=0.05,
        )
        result = checker.evaluate(estimates, cov, rb)
        assert result.suggested_actions


# ─────────────────────────────────────────────────────────────────────────
# Serialización JSON
# ─────────────────────────────────────────────────────────────────────────


class TestSerializacion:
    def test_to_dict_es_json_serializable(self, checker):
        estimates, cov = _build_universe(n=4)
        rb = _risk_budget(max_single_asset=0.15)
        result = checker.evaluate(estimates, cov, rb)
        payload = json.dumps(result.to_dict())
        parsed = json.loads(payload)
        assert parsed["status"] == "infeasible"
        assert parsed["is_feasible"] is False
        assert parsed["asset_count"] == 4

    def test_to_dict_contiene_todos_los_campos(self, checker):
        estimates, cov = _build_universe(n=5)
        rb = _risk_budget(
            max_single_asset=0.40,
            max_volatility=0.20,
            target_volatility=0.10,
        )
        result = checker.evaluate(estimates, cov, rb)
        d = result.to_dict()
        expected = {
            "status",
            "is_feasible",
            "asset_count",
            "required_min_single_asset_cap",
            "actual_max_single_asset",
            "min_achievable_volatility",
            "max_allowed_volatility",
            "failed_checks",
            "warnings",
            "suggested_actions",
            "notes",
        }
        assert set(d.keys()) == expected

    def test_to_dict_min_vol_none_se_serializa(self, checker):
        # universo vacío → min_achievable_volatility = None
        cov = _build_cov([_snap("X", "equity", 0.10)])
        rb = _risk_budget()
        result = checker.evaluate([], cov, rb)
        d = result.to_dict()
        assert d["min_achievable_volatility"] is None


# ─────────────────────────────────────────────────────────────────────────
# Inmutabilidad de inputs
# ─────────────────────────────────────────────────────────────────────────


class TestInmutabilidad:
    def test_evaluate_no_muta_inputs(self, checker):
        estimates, cov = _build_universe(n=4)
        rb = _risk_budget(
            max_single_asset=0.40,
            max_volatility=0.20,
            target_volatility=0.10,
        )

        # Snapshots de los inputs antes de evaluar
        estimates_snapshot = [copy.deepcopy(e) for e in estimates]
        cov_snapshot = copy.deepcopy(cov)
        rb_snapshot = copy.deepcopy(rb)

        _ = checker.evaluate(estimates, cov, rb)

        # Comparación campo a campo
        assert len(estimates) == len(estimates_snapshot)
        for e_after, e_before in zip(estimates, estimates_snapshot, strict=True):
            assert e_after.ticker == e_before.ticker
            assert (
                e_after.raw_expected_return_annual
                == e_before.raw_expected_return_annual
            )
            assert (
                e_after.adjusted_expected_return_annual
                == e_before.adjusted_expected_return_annual
            )
            assert e_after.expense_ratio == e_before.expense_ratio

        assert cov.tickers == cov_snapshot.tickers
        assert cov.covariance == cov_snapshot.covariance
        assert cov.correlation == cov_snapshot.correlation

        assert rb.max_single_asset == rb_snapshot.max_single_asset
        assert rb.max_volatility == rb_snapshot.max_volatility
        assert rb.target_volatility == rb_snapshot.target_volatility
        assert rb.profile_name == rb_snapshot.profile_name


# ─────────────────────────────────────────────────────────────────────────
# Validación de tipos en evaluate
# ─────────────────────────────────────────────────────────────────────────


class TestValidacionEntrada:
    def test_covariance_matrix_tipo_invalido_lanza_error(self, checker):
        with pytest.raises(ValueError, match="covariance_matrix"):
            checker.evaluate(
                [_estimate("A")],
                "no soy una matriz",  # type: ignore[arg-type]
                _risk_budget(),
            )

    def test_risk_budget_tipo_invalido_lanza_error(self, checker):
        estimates, cov = _build_universe(n=2)
        with pytest.raises(ValueError, match="risk_budget"):
            checker.evaluate(
                estimates,
                cov,
                "no soy un budget",  # type: ignore[arg-type]
            )
