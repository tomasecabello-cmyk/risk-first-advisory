"""
Tests para PortfolioOptimizer, OptimizationInput y OptimizedPortfolio.

Cubre todos los requisitos del spec:
    - Validaciones de OptimizationInput
    - Correctitud de los tres objetivos (MIN_VARIANCE, MAX_RETURN, MAX_UTILITY)
    - Restricciones de riesgo y asignación
    - Infactibilidad → ValueError
    - Propiedades de OptimizedPortfolio
    - Serialización JSON
"""

from __future__ import annotations

import json
import math

import pytest

from risk_first_advisory.data_layer.covariance import CovarianceEngine, CovarianceMatrix
from risk_first_advisory.data_layer.market_data import MarketDataSnapshot
from risk_first_advisory.data_layer.return_estimator import ReturnEstimate
from risk_first_advisory.models.risk_budget import RiskBudget
from risk_first_advisory.portfolio_layer.optimizer import (
    OptimizationInput,
    OptimizationObjective,
    PortfolioOptimizer,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _snap(ticker: str, asset_class: str, vol: float = 0.10) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        ticker=ticker,
        expected_return_annual=0.07,
        volatility_annual=vol,
        liquidity_score=0.9,
        expense_ratio=0.001,
        duration=None,
        asset_class=asset_class,
        currency="USD",
    )


def _estimate(ticker: str, ret: float = 0.07) -> ReturnEstimate:
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


def _risk_budget(
    max_single_asset: float = 0.40,
    max_volatility: float = 0.20,
    target_volatility: float = 0.12,
) -> RiskBudget:
    return RiskBudget(
        profile_name="Test",
        target_volatility=target_volatility,
        max_volatility=max_volatility,
        max_drawdown=-0.20,
        min_liquidity=0.5,
        max_equity=1.0,
        max_high_yield=0.30,
        max_single_asset=max_single_asset,
        max_sector_exposure=0.40,
        max_duration=10.0,
        complex_products_allowed=False,
        preferred_currency="USD",
    )


def _build_covariance(tickers_assets: list[tuple[str, str, float]]) -> CovarianceMatrix:
    """Construye CovarianceMatrix desde lista (ticker, asset_class, vol)."""
    snaps = [_snap(t, ac, v) for t, ac, v in tickers_assets]
    engine = CovarianceEngine()
    return engine.build(snaps)


def _build_input(
    tickers_assets: list[tuple[str, str, float]],
    returns: list[float] | None = None,
    objective: OptimizationObjective = OptimizationObjective.MIN_VARIANCE,
    max_single_asset: float = 0.40,
    max_volatility: float = 0.20,
    target_volatility: float = 0.12,
    max_weight: float | None = None,
    min_weight: float = 0.0,
) -> OptimizationInput:
    estimates = [
        _estimate(t, ret)
        for (t, ac, v), ret in zip(
            tickers_assets,
            returns or [0.07] * len(tickers_assets),
        )
    ]
    cm = _build_covariance(tickers_assets)
    rb = _risk_budget(max_single_asset=max_single_asset, max_volatility=max_volatility, target_volatility=target_volatility)
    return OptimizationInput(
        return_estimates=estimates,
        covariance_matrix=cm,
        risk_budget=rb,
        objective=objective,
        max_weight=max_weight,
        min_weight=min_weight,
    )


# Portfolio de 3 activos estándar para tests básicos
_ASSETS = [
    ("SPY", "equity", 0.18),
    ("AGG", "bond", 0.05),
    ("BIL", "cash", 0.01),
]


# ---------------------------------------------------------------------------
# Tests de OptimizationInput — validaciones
# ---------------------------------------------------------------------------

class TestOptimizationInputValidation:
    def test_empty_return_estimates_raises(self):
        cm = _build_covariance([("SPY", "equity", 0.18)])
        rb = _risk_budget()
        with pytest.raises(ValueError, match="vacío"):
            OptimizationInput(
                return_estimates=[],
                covariance_matrix=cm,
                risk_budget=rb,
                objective=OptimizationObjective.MIN_VARIANCE,
            )

    def test_misaligned_tickers_raises(self):
        estimates = [_estimate("SPY"), _estimate("AGG")]
        cm = _build_covariance([("AGG", "bond", 0.05), ("SPY", "equity", 0.18)])
        rb = _risk_budget()
        with pytest.raises(ValueError, match="tickers"):
            OptimizationInput(
                return_estimates=estimates,
                covariance_matrix=cm,
                risk_budget=rb,
                objective=OptimizationObjective.MIN_VARIANCE,
            )

    def test_different_tickers_raises(self):
        estimates = [_estimate("SPY")]
        cm = _build_covariance([("QQQ", "equity", 0.20)])
        rb = _risk_budget()
        with pytest.raises(ValueError, match="tickers"):
            OptimizationInput(
                return_estimates=estimates,
                covariance_matrix=cm,
                risk_budget=rb,
                objective=OptimizationObjective.MIN_VARIANCE,
            )

    def test_invalid_objective_raises(self):
        estimates = [_estimate("SPY")]
        cm = _build_covariance([("SPY", "equity", 0.18)])
        rb = _risk_budget()
        with pytest.raises((ValueError, TypeError)):
            OptimizationInput(
                return_estimates=estimates,
                covariance_matrix=cm,
                risk_budget=rb,
                objective="MIN_VARIANCE",  # string, no enum
            )

    def test_max_assets_zero_raises(self):
        estimates = [_estimate("SPY")]
        cm = _build_covariance([("SPY", "equity", 0.18)])
        rb = _risk_budget()
        with pytest.raises(ValueError, match="max_assets"):
            OptimizationInput(
                return_estimates=estimates,
                covariance_matrix=cm,
                risk_budget=rb,
                objective=OptimizationObjective.MIN_VARIANCE,
                max_assets=0,
            )

    def test_min_weight_out_of_range_raises(self):
        estimates = [_estimate("SPY")]
        cm = _build_covariance([("SPY", "equity", 0.18)])
        rb = _risk_budget()
        with pytest.raises(ValueError, match="min_weight"):
            OptimizationInput(
                return_estimates=estimates,
                covariance_matrix=cm,
                risk_budget=rb,
                objective=OptimizationObjective.MIN_VARIANCE,
                min_weight=1.5,
            )

    def test_max_weight_less_than_min_weight_raises(self):
        estimates = [_estimate("SPY")]
        cm = _build_covariance([("SPY", "equity", 0.18)])
        rb = _risk_budget()
        with pytest.raises(ValueError):
            OptimizationInput(
                return_estimates=estimates,
                covariance_matrix=cm,
                risk_budget=rb,
                objective=OptimizationObjective.MIN_VARIANCE,
                min_weight=0.10,
                max_weight=0.05,
            )

    def test_valid_input_no_raises(self):
        inp = _build_input(_ASSETS)
        assert len(inp.return_estimates) == 3


# ---------------------------------------------------------------------------
# Tests de MIN_VARIANCE
# ---------------------------------------------------------------------------

class TestMinVariance:
    def setup_method(self):
        self.optimizer = PortfolioOptimizer()
        self.inp = _build_input(_ASSETS, objective=OptimizationObjective.MIN_VARIANCE)

    def test_weights_sum_to_one(self):
        result = self.optimizer.optimize(self.inp)
        assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-4)

    def test_long_only(self):
        result = self.optimizer.optimize(self.inp)
        for w in result.weights.values():
            assert w >= -1e-6

    def test_respects_max_single_asset(self):
        inp = _build_input(_ASSETS, max_single_asset=0.50,
                           objective=OptimizationObjective.MIN_VARIANCE)
        result = self.optimizer.optimize(inp)
        for w in result.weights.values():
            assert w <= 0.50 + 1e-4

    def test_respects_max_volatility(self):
        result = self.optimizer.optimize(self.inp)
        assert result.volatility_annual <= 0.20 + 1e-4

    def test_constraints_satisfied_true(self):
        result = self.optimizer.optimize(self.inp)
        assert result.constraints_satisfied is True

    def test_min_variance_prefers_low_vol_assets(self):
        """MIN_VARIANCE debería poner más peso en activos de baja vol."""
        result = self.optimizer.optimize(self.inp)
        # BIL (cash, vol=0.01) debe tener más peso que SPY (equity, vol=0.18)
        assert result.weights["BIL"] > result.weights["SPY"]


# ---------------------------------------------------------------------------
# Tests de MAX_RETURN
# ---------------------------------------------------------------------------

class TestMaxReturn:
    def setup_method(self):
        self.optimizer = PortfolioOptimizer()

    def test_weights_sum_to_one(self):
        inp = _build_input(_ASSETS, objective=OptimizationObjective.MAX_RETURN)
        result = self.optimizer.optimize(inp)
        assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-4)

    def test_respects_max_volatility(self):
        inp = _build_input(_ASSETS, objective=OptimizationObjective.MAX_RETURN,
                           max_volatility=0.15)
        result = self.optimizer.optimize(inp)
        assert result.volatility_annual <= 0.15 + 1e-4

    def test_favors_higher_return_when_feasible(self):
        """Con retornos muy distintos y volatilidad permisiva, MAX_RETURN
        debe concentrar en el activo de mayor retorno."""
        assets = [
            ("HI", "equity", 0.15),
            ("LO", "cash", 0.01),
        ]
        returns = [0.20, 0.01]
        inp = _build_input(
            assets,
            returns=returns,
            objective=OptimizationObjective.MAX_RETURN,
            max_single_asset=1.0,
            max_volatility=0.30,
        )
        result = self.optimizer.optimize(inp)
        assert result.weights["HI"] > result.weights["LO"]

    def test_long_only(self):
        inp = _build_input(_ASSETS, objective=OptimizationObjective.MAX_RETURN)
        result = self.optimizer.optimize(inp)
        for w in result.weights.values():
            assert w >= -1e-6


# ---------------------------------------------------------------------------
# Tests de MAX_UTILITY
# ---------------------------------------------------------------------------

class TestMaxUtility:
    def setup_method(self):
        self.optimizer = PortfolioOptimizer()
        self.inp = _build_input(_ASSETS, objective=OptimizationObjective.MAX_UTILITY)

    def test_weights_sum_to_one(self):
        result = self.optimizer.optimize(self.inp)
        assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-4)

    def test_expected_return_is_calculable(self):
        result = self.optimizer.optimize(self.inp)
        assert math.isfinite(result.expected_return_annual)

    def test_volatility_is_calculable(self):
        result = self.optimizer.optimize(self.inp)
        assert math.isfinite(result.volatility_annual)
        assert result.volatility_annual >= 0.0

    def test_long_only(self):
        result = self.optimizer.optimize(self.inp)
        for w in result.weights.values():
            assert w >= -1e-6

    def test_respects_max_volatility(self):
        result = self.optimizer.optimize(self.inp)
        assert result.volatility_annual <= 0.20 + 1e-4


# ---------------------------------------------------------------------------
# Tests de infactibilidad
# ---------------------------------------------------------------------------

class TestInfeasibility:
    def setup_method(self):
        self.optimizer = PortfolioOptimizer()

    def test_infeasible_max_single_asset_too_low_raises(self):
        """Con 3 activos y max_single_asset < 1/3, es imposible sum(w)=1."""
        inp = _build_input(
            _ASSETS,
            max_single_asset=0.30,  # 3 * 0.30 = 0.90 < 1.0 → infactible
            objective=OptimizationObjective.MIN_VARIANCE,
        )
        with pytest.raises(ValueError):
            self.optimizer.optimize(inp)

    def test_infeasible_max_volatility_too_low_raises(self):
        """Con activos muy correlacionados y vol alta, volatilidad 0 es infactible."""
        # Un solo activo equity con vol 0.30, max_volatility 0.001 → imposible
        assets = [("SPY", "equity", 0.30)]
        inp = _build_input(
            assets,
            max_single_asset=1.0,
            max_volatility=0.001,
            target_volatility=0.0005,
            objective=OptimizationObjective.MIN_VARIANCE,
        )
        with pytest.raises(ValueError):
            self.optimizer.optimize(inp)


# ---------------------------------------------------------------------------
# Tests de OptimizedPortfolio
# ---------------------------------------------------------------------------

class TestOptimizedPortfolio:
    def setup_method(self):
        optimizer = PortfolioOptimizer()
        inp = _build_input(_ASSETS, objective=OptimizationObjective.MIN_VARIANCE)
        self.result = optimizer.optimize(inp)

    def test_to_dict_is_json_serializable(self):
        d = self.result.to_dict()
        s = json.dumps(d)
        assert isinstance(s, str)

    def test_to_dict_has_expected_keys(self):
        d = self.result.to_dict()
        expected = {
            "objective", "weights", "expected_return_annual",
            "volatility_annual", "risk_score", "constraints_satisfied",
            "reason_codes", "notes",
        }
        assert set(d.keys()) == expected

    def test_invested_weight(self):
        assert self.result.invested_weight == pytest.approx(1.0, abs=1e-4)

    def test_number_of_assets(self):
        # Al menos 1 activo con peso > 0
        assert self.result.number_of_assets >= 1

    def test_number_of_assets_type(self):
        assert isinstance(self.result.number_of_assets, int)

    def test_risk_score_is_non_negative(self):
        assert self.result.risk_score >= 0.0

    def test_objective_preserved(self):
        assert self.result.objective == OptimizationObjective.MIN_VARIANCE

    def test_small_weights_cleaned(self):
        """Ningún peso debe ser positivo pero menor al threshold de limpieza."""
        from risk_first_advisory.portfolio_layer.optimizer import WEIGHT_CLEANUP_THRESHOLD
        for w in self.result.weights.values():
            assert w == 0.0 or w >= WEIGHT_CLEANUP_THRESHOLD


# ---------------------------------------------------------------------------
# Tests de max_weight constraint
# ---------------------------------------------------------------------------

class TestMaxWeightConstraint:
    def setup_method(self):
        self.optimizer = PortfolioOptimizer()

    def test_max_weight_respected(self):
        inp = _build_input(
            _ASSETS,
            max_weight=0.35,
            objective=OptimizationObjective.MIN_VARIANCE,
        )
        result = self.optimizer.optimize(inp)
        for w in result.weights.values():
            assert w <= 0.35 + 1e-4
