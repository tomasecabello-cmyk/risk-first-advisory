"""
Tests para PortfolioGenerationCoordinator y PortfolioCandidateSet.

Cubre todos los requisitos del spec.
"""

from __future__ import annotations

import json
import pytest

from risk_first_advisory.data_layer.covariance import CovarianceEngine
from risk_first_advisory.data_layer.market_data import MarketDataSnapshot
from risk_first_advisory.data_layer.return_estimator import ReturnEstimate
from risk_first_advisory.models.risk_budget import RiskBudget
from risk_first_advisory.portfolio_layer.generation import (
    PortfolioCandidateSet,
    PortfolioGenerationCoordinator,
    PortfolioVariant,
    RC_VARIANT_INFEASIBLE,
)
from risk_first_advisory.portfolio_layer.optimizer import (
    OptimizationObjective,
    OptimizedPortfolio,
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
        profile_name="Moderate",
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


# 4-asset universe with varied risk profiles
_ASSETS = [
    ("SPY", "equity", 0.18),
    ("AGG", "bond", 0.05),
    ("BIL", "cash", 0.01),
    ("HYG", "high_yield", 0.12),
]
_RETURNS = [0.09, 0.04, 0.02, 0.07]


def _build_inputs(
    assets=None,
    returns=None,
    max_single_asset: float = 0.40,
    max_volatility: float = 0.20,
    target_volatility: float = 0.12,
):
    assets = assets or _ASSETS
    returns = returns or _RETURNS
    engine = CovarianceEngine()
    snaps = [_snap(t, ac, v) for t, ac, v in assets]
    cm = engine.build(snaps)
    estimates = [_estimate(t, r) for (t, _, _), r in zip(assets, returns)]
    rb = _risk_budget(
        max_single_asset=max_single_asset,
        max_volatility=max_volatility,
        target_volatility=target_volatility,
    )
    return estimates, cm, rb


def _make_dummy_portfolio() -> OptimizedPortfolio:
    return OptimizedPortfolio(
        objective=OptimizationObjective.MIN_VARIANCE,
        weights={"SPY": 0.5, "AGG": 0.5},
        expected_return_annual=0.05,
        volatility_annual=0.08,
        risk_score=0.4,
        constraints_satisfied=True,
        reason_codes=[],
        notes=[],
    )


# ---------------------------------------------------------------------------
# Tests de PortfolioCandidateSet — validaciones
# ---------------------------------------------------------------------------

class TestPortfolioCandidateSetValidation:
    def _valid_set(self, **kwargs) -> dict:
        base = dict(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={PortfolioVariant.BALANCED: _make_dummy_portfolio()},
        )
        base.update(kwargs)
        return base

    def test_valid_construction(self):
        cs = PortfolioCandidateSet(**self._valid_set())
        assert cs.client_id == "C001"

    def test_empty_client_id_raises(self):
        with pytest.raises(ValueError, match="client_id"):
            PortfolioCandidateSet(**self._valid_set(client_id=""))

    def test_blank_client_id_raises(self):
        with pytest.raises(ValueError, match="client_id"):
            PortfolioCandidateSet(**self._valid_set(client_id="   "))

    def test_empty_approved_profile_name_raises(self):
        with pytest.raises(ValueError, match="approved_profile_name"):
            PortfolioCandidateSet(**self._valid_set(approved_profile_name=""))

    def test_empty_candidates_raises(self):
        with pytest.raises(ValueError, match="candidates"):
            PortfolioCandidateSet(**self._valid_set(candidates={}))

    def test_invalid_key_in_candidates_raises(self):
        with pytest.raises(ValueError):
            PortfolioCandidateSet(
                **self._valid_set(candidates={"DEFENSIVE": _make_dummy_portfolio()})
            )

    def test_invalid_value_in_candidates_raises(self):
        with pytest.raises(ValueError):
            PortfolioCandidateSet(
                **self._valid_set(candidates={PortfolioVariant.BALANCED: "not_a_portfolio"})
            )

    def test_selected_variant_not_in_candidates_raises(self):
        with pytest.raises(ValueError):
            PortfolioCandidateSet(
                **self._valid_set(selected_variant=PortfolioVariant.GROWTH)
            )

    def test_selected_variant_none_is_valid(self):
        cs = PortfolioCandidateSet(**self._valid_set(selected_variant=None))
        assert cs.selected_variant is None

    def test_reason_codes_not_list_raises(self):
        with pytest.raises(ValueError):
            PortfolioCandidateSet(**self._valid_set(reason_codes="code"))

    def test_notes_not_list_raises(self):
        with pytest.raises(ValueError):
            PortfolioCandidateSet(**self._valid_set(notes="note"))


# ---------------------------------------------------------------------------
# Tests de PortfolioCandidateSet — métodos
# ---------------------------------------------------------------------------

class TestPortfolioCandidateSetMethods:
    def setup_method(self):
        p_def = _make_dummy_portfolio()
        p_bal = _make_dummy_portfolio()
        p_gro = _make_dummy_portfolio()
        self.cs = PortfolioCandidateSet(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={
                PortfolioVariant.DEFENSIVE: p_def,
                PortfolioVariant.BALANCED: p_bal,
                PortfolioVariant.GROWTH: p_gro,
            },
        )

    def test_count_returns_number_of_candidates(self):
        assert self.cs.count == 3

    def test_count_partial(self):
        cs = PortfolioCandidateSet(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={PortfolioVariant.BALANCED: _make_dummy_portfolio()},
        )
        assert cs.count == 1

    def test_variants_returns_canonical_order(self):
        assert self.cs.variants() == [
            PortfolioVariant.DEFENSIVE,
            PortfolioVariant.BALANCED,
            PortfolioVariant.GROWTH,
        ]

    def test_variants_partial_respects_order(self):
        cs = PortfolioCandidateSet(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={
                PortfolioVariant.GROWTH: _make_dummy_portfolio(),
                PortfolioVariant.DEFENSIVE: _make_dummy_portfolio(),
            },
        )
        assert cs.variants() == [PortfolioVariant.DEFENSIVE, PortfolioVariant.GROWTH]

    def test_get_candidate_returns_correct_portfolio(self):
        p = _make_dummy_portfolio()
        cs = PortfolioCandidateSet(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={PortfolioVariant.BALANCED: p},
        )
        assert cs.get_candidate(PortfolioVariant.BALANCED) is p

    def test_get_candidate_absent_variant_raises_key_error(self):
        cs = PortfolioCandidateSet(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={PortfolioVariant.BALANCED: _make_dummy_portfolio()},
        )
        with pytest.raises(KeyError):
            cs.get_candidate(PortfolioVariant.GROWTH)

    def test_to_dict_is_json_serializable(self):
        d = self.cs.to_dict()
        s = json.dumps(d)
        assert isinstance(s, str)

    def test_to_dict_converts_enum_keys_to_string(self):
        d = self.cs.to_dict()
        for key in d["candidates"]:
            assert isinstance(key, str)

    def test_to_dict_selected_variant_none(self):
        d = self.cs.to_dict()
        assert d["selected_variant"] is None

    def test_to_dict_selected_variant_string(self):
        cs = PortfolioCandidateSet(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={
                PortfolioVariant.BALANCED: _make_dummy_portfolio(),
                PortfolioVariant.GROWTH: _make_dummy_portfolio(),
            },
            selected_variant=PortfolioVariant.BALANCED,
        )
        d = cs.to_dict()
        assert d["selected_variant"] == "BALANCED"


# ---------------------------------------------------------------------------
# Tests de PortfolioGenerationCoordinator
# ---------------------------------------------------------------------------

class TestPortfolioGenerationCoordinator:
    def setup_method(self):
        self.coordinator = PortfolioGenerationCoordinator()
        self.estimates, self.cm, self.rb = _build_inputs()

    def test_generates_candidate_set_with_client_id(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        assert result.client_id == "CLI-001"

    def test_generates_candidate_set_with_profile_name(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        assert result.approved_profile_name == "Moderate"

    def test_generates_three_variants_when_all_feasible(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        assert result.count == 3

    def test_variants_in_canonical_order(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        assert result.variants() == [
            PortfolioVariant.DEFENSIVE,
            PortfolioVariant.BALANCED,
            PortfolioVariant.GROWTH,
        ]

    def test_count_equals_number_of_generated_variants(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        assert result.count == len(result.candidates)

    def test_get_candidate_returns_correct_type(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        p = result.get_candidate(PortfolioVariant.BALANCED)
        assert isinstance(p, OptimizedPortfolio)

    def test_get_candidate_absent_raises_key_error(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        # Remove a variant to test KeyError
        result.candidates.pop(PortfolioVariant.GROWTH, None)
        with pytest.raises(KeyError):
            result.get_candidate(PortfolioVariant.GROWTH)

    def test_selected_variant_is_none_by_default(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        assert result.selected_variant is None

    def test_to_dict_is_json_serializable(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        d = result.to_dict()
        s = json.dumps(d)
        assert isinstance(s, str)

    def test_to_dict_enum_keys_are_strings(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        d = result.to_dict()
        for key in d["candidates"]:
            assert isinstance(key, str)

    def test_all_generated_portfolios_satisfy_constraints(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        for variant, portfolio in result.candidates.items():
            assert portfolio.constraints_satisfied is True, (
                f"Variant {variant} has constraints_satisfied=False"
            )

    def test_all_generated_portfolios_have_invested_weight_near_one(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        for variant, portfolio in result.candidates.items():
            assert abs(portfolio.invested_weight - 1.0) < 1e-3, (
                f"Variant {variant} invested_weight={portfolio.invested_weight}"
            )

    def test_all_generated_portfolios_respect_max_volatility(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        for variant, portfolio in result.candidates.items():
            assert portfolio.volatility_annual <= self.rb.max_volatility + 1e-4, (
                f"Variant {variant} volatility={portfolio.volatility_annual} "
                f"> max={self.rb.max_volatility}"
            )

    def test_defensive_volatility_le_balanced_volatility(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        if (PortfolioVariant.DEFENSIVE in result.candidates
                and PortfolioVariant.BALANCED in result.candidates):
            def_vol = result.candidates[PortfolioVariant.DEFENSIVE].volatility_annual
            bal_vol = result.candidates[PortfolioVariant.BALANCED].volatility_annual
            # DEFENSIVE is constrained more tightly, should have <= vol
            assert def_vol <= bal_vol + 1e-4

    def test_growth_return_ge_defensive_return(self):
        result = self.coordinator.generate("CLI-001", "Moderate", self.estimates, self.cm, self.rb)
        if (PortfolioVariant.GROWTH in result.candidates
                and PortfolioVariant.DEFENSIVE in result.candidates):
            growth_ret = result.candidates[PortfolioVariant.GROWTH].expected_return_annual
            def_ret = result.candidates[PortfolioVariant.DEFENSIVE].expected_return_annual
            assert growth_ret >= def_ret - 1e-4

    def test_infeasible_variant_omitted_others_generated(self):
        """DEFENSIVE es infactible si max_single_asset muy bajo + target_vol muy bajo."""
        # Con target_vol=0.001 y max_single_asset=0.40, DEFENSIVE tendrá max_vol=0.001
        # que es infactible con activos equity/high_yield.
        estimates, cm, rb = _build_inputs(
            target_volatility=0.001,
            max_volatility=0.20,
            max_single_asset=0.40,
        )
        # DEFENSIVE: max_vol = min(0.20, 0.001) = 0.001 → infactible
        result = self.coordinator.generate("CLI-002", "Moderate", estimates, cm, rb)
        assert PortfolioVariant.DEFENSIVE not in result.candidates
        assert PortfolioVariant.BALANCED in result.candidates or \
               PortfolioVariant.GROWTH in result.candidates
        assert RC_VARIANT_INFEASIBLE in result.reason_codes

    def test_all_infeasible_raises_value_error(self):
        """Si todas las variantes son infactibles, debe levantar ValueError."""
        # max_single_asset=0.30 con 4 activos → 4*0.30=1.20 >= 1 pero
        # target_vol=0.001 → DEFENSIVE max_vol=0.001 infactible
        # max_volatility=0.001 → BALANCED y GROWTH también infactibles
        estimates, cm, rb = _build_inputs(
            max_volatility=0.001,
            target_volatility=0.001,
            max_single_asset=0.40,
        )
        with pytest.raises(ValueError, match="factible"):
            self.coordinator.generate("CLI-003", "Moderate", estimates, cm, rb)