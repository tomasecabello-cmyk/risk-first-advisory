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
from risk_first_advisory.portfolio_layer.feasibility import (
    FC_MAX_SINGLE_ASSET_TOO_LOW,
    FC_MIN_VOL_EXCEEDS_BUDGET,
    PortfolioFeasibilityChecker,
    PortfolioFeasibilityResult,
    PortfolioFeasibilityStatus,
)
from risk_first_advisory.portfolio_layer.generation import (
    PortfolioCandidateSet,
    PortfolioGenerationCoordinator,
    PortfolioVariant,
    PortfolioVariantMetadata,
    RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET,
    RC_VARIANT_INFEASIBLE,
)
from risk_first_advisory.portfolio_layer.optimizer import (
    OptimizationObjective,
    OptimizedPortfolio,
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


# ---------------------------------------------------------------------------
# Tests de integración con PortfolioFeasibilityChecker
# ---------------------------------------------------------------------------

class _SpyOptimizer:
    """Optimizer spy: registra cuántas veces se llamó y con qué objetivos."""

    def __init__(self, delegate: PortfolioOptimizer | None = None):
        self.delegate = delegate or PortfolioOptimizer()
        self.calls: list[OptimizationObjective] = []

    def optimize(self, input_data):
        self.calls.append(input_data.objective)
        return self.delegate.optimize(input_data)


class _FakeFeasibilityChecker:
    """
    Feasibility checker mockeado para probar el flujo del coordinator
    sin depender del solver auxiliar interno.

    `result_by_call` se consume en orden: cada llamada a `evaluate` devuelve
    el siguiente resultado. Si se agota, levanta IndexError.
    """

    def __init__(self, results: list[PortfolioFeasibilityResult]):
        self.results = list(results)
        self.evaluate_calls = 0

    def evaluate(self, return_estimates, covariance_matrix, risk_budget):
        result = self.results[self.evaluate_calls]
        self.evaluate_calls += 1
        return result


def _make_feasibility(
    status: PortfolioFeasibilityStatus,
    asset_count: int = 4,
    failed_checks=None,
    warnings=None,
    suggested_actions=None,
    notes=None,
) -> PortfolioFeasibilityResult:
    return PortfolioFeasibilityResult(
        status=status,
        is_feasible=(status != PortfolioFeasibilityStatus.INFEASIBLE),
        asset_count=asset_count,
        required_min_single_asset_cap=(1.0 / asset_count) if asset_count else 0.0,
        actual_max_single_asset=0.40,
        min_achievable_volatility=0.05,
        max_allowed_volatility=0.20,
        failed_checks=failed_checks or [],
        warnings=warnings or [],
        suggested_actions=suggested_actions or [],
        notes=notes or [],
    )


class TestCoordinatorIntegratesFeasibilityChecker:
    """
    Suite enfocada en la integración del pre-check de factibilidad.

    Usa _FakeFeasibilityChecker para forzar exactamente el estado deseado
    en cada variante, y _SpyOptimizer para verificar qué variantes
    efectivamente llegaron al optimizer.
    """

    def setup_method(self):
        self.estimates, self.cm, self.rb = _build_inputs()

    # ── Caso: DEFENSIVE infactible por max_single_asset ──────────────────

    def test_infeasible_defensive_skips_optimizer_call(self):
        """Cuando DEFENSIVE es infeasible por pre-check, el optimizer NO debe llamarse para esa variante."""
        spy = _SpyOptimizer()
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(
                PortfolioFeasibilityStatus.INFEASIBLE,
                failed_checks=[FC_MAX_SINGLE_ASSET_TOO_LOW],
                suggested_actions=["sugerencia X"],
            ),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
        ])
        coordinator = PortfolioGenerationCoordinator(
            feasibility_checker=fake_checker,
            optimizer=spy,
        )

        result = coordinator.generate(
            "CLI-INTEG-001", "Moderate", self.estimates, self.cm, self.rb
        )

        # DEFENSIVE no debe estar en candidates.
        assert PortfolioVariant.DEFENSIVE not in result.candidates
        # El optimizer fue llamado solo 2 veces (BALANCED y GROWTH), nunca MIN_VARIANCE.
        assert len(spy.calls) == 2
        assert OptimizationObjective.MIN_VARIANCE not in spy.calls
        assert OptimizationObjective.MAX_UTILITY in spy.calls
        assert OptimizationObjective.MAX_RETURN in spy.calls

    def test_infeasible_defensive_reason_codes_include_variant_infeasible(self):
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(
                PortfolioFeasibilityStatus.INFEASIBLE,
                failed_checks=[FC_MAX_SINGLE_ASSET_TOO_LOW],
            ),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
        ])
        coordinator = PortfolioGenerationCoordinator(feasibility_checker=fake_checker)
        result = coordinator.generate(
            "CLI-INTEG-002", "Moderate", self.estimates, self.cm, self.rb
        )
        assert RC_VARIANT_INFEASIBLE in result.reason_codes

    def test_infeasible_defensive_reason_codes_include_specific_failed_check(self):
        """Los failed_checks del feasibility deben acumularse en reason_codes del candidate set."""
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(
                PortfolioFeasibilityStatus.INFEASIBLE,
                failed_checks=[FC_MAX_SINGLE_ASSET_TOO_LOW],
            ),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
        ])
        coordinator = PortfolioGenerationCoordinator(feasibility_checker=fake_checker)
        result = coordinator.generate(
            "CLI-INTEG-003", "Moderate", self.estimates, self.cm, self.rb
        )
        assert FC_MAX_SINGLE_ASSET_TOO_LOW in result.reason_codes

    def test_infeasible_defensive_notes_mention_pre_check(self):
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(
                PortfolioFeasibilityStatus.INFEASIBLE,
                failed_checks=[FC_MAX_SINGLE_ASSET_TOO_LOW],
            ),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
        ])
        coordinator = PortfolioGenerationCoordinator(feasibility_checker=fake_checker)
        result = coordinator.generate(
            "CLI-INTEG-004", "Moderate", self.estimates, self.cm, self.rb
        )
        joined_notes = " ".join(result.notes).lower()
        assert "pre-check" in joined_notes or "factibilidad" in joined_notes
        assert "defensive" in joined_notes.lower() or "DEFENSIVE" in " ".join(result.notes)

    def test_infeasible_defensive_notes_include_suggested_actions(self):
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(
                PortfolioFeasibilityStatus.INFEASIBLE,
                failed_checks=[FC_MAX_SINGLE_ASSET_TOO_LOW],
                suggested_actions=["Aumentar max_single_asset o ampliar universo."],
            ),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
        ])
        coordinator = PortfolioGenerationCoordinator(feasibility_checker=fake_checker)
        result = coordinator.generate(
            "CLI-INTEG-005", "Moderate", self.estimates, self.cm, self.rb
        )
        joined = " ".join(result.notes)
        assert "Aumentar max_single_asset" in joined

    # ── Caso: WARNING — la variante igual se intenta ─────────────────────

    def test_warning_variant_is_still_optimized(self):
        """Cuando feasibility devuelve WARNING, la variante debe llamar al optimizer y aparecer en candidates."""
        spy = _SpyOptimizer()
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(
                PortfolioFeasibilityStatus.WARNING,
                warnings=["PORTFOLIO_CONCENTRATION_REQUIRED"],
            ),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
        ])
        coordinator = PortfolioGenerationCoordinator(
            feasibility_checker=fake_checker,
            optimizer=spy,
        )
        result = coordinator.generate(
            "CLI-INTEG-006", "Moderate", self.estimates, self.cm, self.rb
        )
        # DEFENSIVE entra al optimizer (status WARNING ≠ INFEASIBLE).
        assert PortfolioVariant.DEFENSIVE in result.candidates
        assert OptimizationObjective.MIN_VARIANCE in spy.calls
        assert len(spy.calls) == 3

    def test_warning_variant_propagates_warnings_to_notes(self):
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(
                PortfolioFeasibilityStatus.WARNING,
                warnings=["PORTFOLIO_CONCENTRATION_REQUIRED"],
            ),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
        ])
        coordinator = PortfolioGenerationCoordinator(feasibility_checker=fake_checker)
        result = coordinator.generate(
            "CLI-INTEG-007", "Moderate", self.estimates, self.cm, self.rb
        )
        joined = " ".join(result.notes)
        assert "PORTFOLIO_CONCENTRATION_REQUIRED" in joined

    # ── Caso: FEASIBLE — generación normal ────────────────────────────────

    def test_all_feasible_generates_three_variants_via_optimizer(self):
        spy = _SpyOptimizer()
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
        ])
        coordinator = PortfolioGenerationCoordinator(
            feasibility_checker=fake_checker,
            optimizer=spy,
        )
        result = coordinator.generate(
            "CLI-INTEG-008", "Moderate", self.estimates, self.cm, self.rb
        )
        assert result.count == 3
        assert len(spy.calls) == 3

    def test_all_feasible_no_infeasible_reason_codes(self):
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
        ])
        coordinator = PortfolioGenerationCoordinator(feasibility_checker=fake_checker)
        result = coordinator.generate(
            "CLI-INTEG-009", "Moderate", self.estimates, self.cm, self.rb
        )
        assert RC_VARIANT_INFEASIBLE not in result.reason_codes

    # ── Caso: TODAS infactibles por pre-check ─────────────────────────────

    def test_all_pre_check_infeasible_raises_value_error_and_skips_optimizer(self):
        spy = _SpyOptimizer()
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(
                PortfolioFeasibilityStatus.INFEASIBLE,
                failed_checks=[FC_MAX_SINGLE_ASSET_TOO_LOW],
            ),
            _make_feasibility(
                PortfolioFeasibilityStatus.INFEASIBLE,
                failed_checks=[FC_MAX_SINGLE_ASSET_TOO_LOW],
            ),
            _make_feasibility(
                PortfolioFeasibilityStatus.INFEASIBLE,
                failed_checks=[FC_MAX_SINGLE_ASSET_TOO_LOW],
            ),
        ])
        coordinator = PortfolioGenerationCoordinator(
            feasibility_checker=fake_checker,
            optimizer=spy,
        )
        with pytest.raises(ValueError, match="factible"):
            coordinator.generate(
                "CLI-INTEG-010", "Moderate", self.estimates, self.cm, self.rb
            )
        # El optimizer nunca debe haber sido llamado.
        assert spy.calls == []

    # ── Caso: pre-check OK pero optimizer falla igual ─────────────────────

    class _AlwaysFailingOptimizer:
        """Optimizer que siempre lanza ValueError, simulando un solver que falla
        pese a que el pre-check considere factible el problema."""

        def __init__(self):
            self.calls: list[OptimizationObjective] = []

        def optimize(self, input_data):
            self.calls.append(input_data.objective)
            raise ValueError("solver failed: synthetic test failure")

    def test_optimizer_failure_after_feasible_pre_check_is_handled(self):
        """Si el pre-check pasa pero el optimizer falla, la variante se omite
        con reason_code y nota que mencione el solver."""
        failing = self._AlwaysFailingOptimizer()
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
        ])
        coordinator = PortfolioGenerationCoordinator(
            feasibility_checker=fake_checker,
            optimizer=failing,
        )
        with pytest.raises(ValueError, match="factible"):
            coordinator.generate(
                "CLI-INTEG-011", "Moderate", self.estimates, self.cm, self.rb
            )
        # El optimizer fue llamado 3 veces (cada variante pasó el pre-check
        # y falló en el solver).
        assert len(failing.calls) == 3

    # ── Caso: el checker se llama una vez por variante ────────────────────

    def test_feasibility_checker_called_once_per_variant(self):
        fake_checker = _FakeFeasibilityChecker(results=[
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
            _make_feasibility(PortfolioFeasibilityStatus.FEASIBLE),
        ])
        coordinator = PortfolioGenerationCoordinator(feasibility_checker=fake_checker)
        coordinator.generate(
            "CLI-INTEG-012", "Moderate", self.estimates, self.cm, self.rb
        )
        assert fake_checker.evaluate_calls == 3

    # ── Caso real: smoke con checker real, sin mocks ──────────────────────

    def test_real_checker_low_cap_infeasible_for_defensive(self):
        """Smoke con PortfolioFeasibilityChecker real: con cap muy bajo
        en el budget aprobado, las variantes con esos caps disparan
        PORTFOLIO_MAX_SINGLE_ASSET_TOO_LOW.

        Detalle de implementación que validamos: la DEFENSIVE deriva su
        propio cap reduciendo el original, así que si el ORIGINAL ya es
        infeasible, la DEFENSIVE también lo será.
        """
        # 4 activos con max_single_asset = 0.10 → 4*0.10=0.40 < 1.0 → todas
        # las variantes (incluida DEFENSIVE que deriva un cap aún menor)
        # disparan FC_MAX_SINGLE_ASSET_TOO_LOW.
        estimates, cm, rb = _build_inputs(
            max_single_asset=0.10,
            max_volatility=0.20,
            target_volatility=0.12,
        )
        spy = _SpyOptimizer()
        coordinator = PortfolioGenerationCoordinator(optimizer=spy)
        with pytest.raises(ValueError, match="factible"):
            coordinator.generate(
                "CLI-INTEG-013", "Moderate", estimates, cm, rb
            )
        # El optimizer NUNCA debe haber sido llamado: el pre-check
        # cortocircuitó todas las variantes.
        assert spy.calls == []


# ---------------------------------------------------------------------------
# Tests de PortfolioVariantMetadata
# ---------------------------------------------------------------------------

class TestPortfolioVariantMetadata:
    def _valid_kwargs(self, **overrides) -> dict:
        base = dict(
            variant=PortfolioVariant.BALANCED,
            risk_budget_exceeded=False,
            requires_advisor_override=False,
            exceeded_constraints=[],
            reason_codes=[],
            notes=[],
        )
        base.update(overrides)
        return base

    def test_valid_construction_balanced(self):
        m = PortfolioVariantMetadata(**self._valid_kwargs())
        assert m.variant == PortfolioVariant.BALANCED
        assert m.risk_budget_exceeded is False
        assert m.requires_advisor_override is False

    def test_valid_construction_defensive(self):
        m = PortfolioVariantMetadata(**self._valid_kwargs(variant=PortfolioVariant.DEFENSIVE))
        assert m.variant == PortfolioVariant.DEFENSIVE

    def test_valid_construction_growth_with_override(self):
        m = PortfolioVariantMetadata(
            variant=PortfolioVariant.GROWTH,
            risk_budget_exceeded=True,
            requires_advisor_override=True,
            exceeded_constraints=["max_volatility"],
            reason_codes=[RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET],
            notes=["GROWTH excede el budget aprobado."],
        )
        assert m.risk_budget_exceeded is True
        assert m.requires_advisor_override is True
        assert RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET in m.reason_codes

    def test_invalid_variant_type_raises(self):
        with pytest.raises(ValueError, match="PortfolioVariant"):
            PortfolioVariantMetadata(**self._valid_kwargs(variant="BALANCED"))

    def test_exceeded_constraints_not_list_raises(self):
        with pytest.raises(ValueError, match="exceeded_constraints"):
            PortfolioVariantMetadata(**self._valid_kwargs(exceeded_constraints="max_vol"))

    def test_reason_codes_not_list_raises(self):
        with pytest.raises(ValueError, match="reason_codes"):
            PortfolioVariantMetadata(**self._valid_kwargs(reason_codes="RC"))

    def test_notes_not_list_raises(self):
        with pytest.raises(ValueError, match="notes"):
            PortfolioVariantMetadata(**self._valid_kwargs(notes="nota"))

    def test_risk_budget_exceeded_true_requires_override_raises(self):
        with pytest.raises(ValueError, match="requires_advisor_override"):
            PortfolioVariantMetadata(**self._valid_kwargs(
                risk_budget_exceeded=True,
                requires_advisor_override=False,
            ))

    def test_growth_with_override_without_rc_raises(self):
        with pytest.raises(ValueError, match=RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET):
            PortfolioVariantMetadata(
                variant=PortfolioVariant.GROWTH,
                risk_budget_exceeded=True,
                requires_advisor_override=True,
                exceeded_constraints=["max_volatility"],
                reason_codes=[],  # falta RC
                notes=[],
            )

    def test_to_dict_variant_is_string(self):
        m = PortfolioVariantMetadata(**self._valid_kwargs())
        d = m.to_dict()
        assert isinstance(d["variant"], str)
        assert d["variant"] == "BALANCED"

    def test_to_dict_all_fields_present(self):
        m = PortfolioVariantMetadata(**self._valid_kwargs())
        d = m.to_dict()
        assert "variant" in d
        assert "risk_budget_exceeded" in d
        assert "requires_advisor_override" in d
        assert "exceeded_constraints" in d
        assert "reason_codes" in d
        assert "notes" in d

    def test_to_dict_is_json_serializable(self):
        m = PortfolioVariantMetadata(
            variant=PortfolioVariant.GROWTH,
            risk_budget_exceeded=True,
            requires_advisor_override=True,
            exceeded_constraints=["max_volatility"],
            reason_codes=[RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET],
            notes=["nota"],
        )
        json.dumps(m.to_dict())


# ---------------------------------------------------------------------------
# Tests de PortfolioCandidateSet — metadata
# ---------------------------------------------------------------------------

class TestPortfolioCandidateSetMetadata:
    def _single_balanced(self) -> PortfolioCandidateSet:
        return PortfolioCandidateSet(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={PortfolioVariant.BALANCED: _make_dummy_portfolio()},
        )

    def test_metadata_auto_filled_when_empty(self):
        cs = self._single_balanced()
        assert PortfolioVariant.BALANCED in cs.metadata

    def test_metadata_auto_filled_defaults_to_no_override(self):
        cs = self._single_balanced()
        m = cs.metadata[PortfolioVariant.BALANCED]
        assert m.risk_budget_exceeded is False
        assert m.requires_advisor_override is False

    def test_metadata_auto_filled_for_all_candidates(self):
        cs = PortfolioCandidateSet(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={
                PortfolioVariant.DEFENSIVE: _make_dummy_portfolio(),
                PortfolioVariant.BALANCED: _make_dummy_portfolio(),
                PortfolioVariant.GROWTH: _make_dummy_portfolio(),
            },
        )
        assert set(cs.metadata.keys()) == {
            PortfolioVariant.DEFENSIVE,
            PortfolioVariant.BALANCED,
            PortfolioVariant.GROWTH,
        }

    def test_metadata_explicit_accepted(self):
        meta = {
            PortfolioVariant.BALANCED: PortfolioVariantMetadata(
                variant=PortfolioVariant.BALANCED,
                risk_budget_exceeded=False,
                requires_advisor_override=False,
                exceeded_constraints=[],
                reason_codes=[],
                notes=["custom"],
            )
        }
        cs = PortfolioCandidateSet(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={PortfolioVariant.BALANCED: _make_dummy_portfolio()},
            metadata=meta,
        )
        assert cs.metadata[PortfolioVariant.BALANCED].notes == ["custom"]

    def test_metadata_invalid_key_raises(self):
        with pytest.raises(ValueError, match="PortfolioVariant"):
            PortfolioCandidateSet(
                client_id="C001",
                approved_profile_name="Moderate",
                candidates={PortfolioVariant.BALANCED: _make_dummy_portfolio()},
                metadata={"BALANCED": PortfolioVariantMetadata(  # type: ignore[arg-type]
                    variant=PortfolioVariant.BALANCED,
                    risk_budget_exceeded=False,
                    requires_advisor_override=False,
                    exceeded_constraints=[],
                    reason_codes=[],
                    notes=[],
                )},
            )

    def test_metadata_variant_not_in_candidates_raises(self):
        with pytest.raises(ValueError, match="candidates"):
            PortfolioCandidateSet(
                client_id="C001",
                approved_profile_name="Moderate",
                candidates={PortfolioVariant.BALANCED: _make_dummy_portfolio()},
                metadata={
                    PortfolioVariant.GROWTH: PortfolioVariantMetadata(
                        variant=PortfolioVariant.GROWTH,
                        risk_budget_exceeded=True,
                        requires_advisor_override=True,
                        exceeded_constraints=["max_volatility"],
                        reason_codes=[RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET],
                        notes=[],
                    )
                },
            )

    def test_to_dict_includes_metadata(self):
        cs = self._single_balanced()
        d = cs.to_dict()
        assert "metadata" in d

    def test_to_dict_metadata_keys_are_strings(self):
        cs = PortfolioCandidateSet(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={
                PortfolioVariant.DEFENSIVE: _make_dummy_portfolio(),
                PortfolioVariant.BALANCED: _make_dummy_portfolio(),
            },
        )
        d = cs.to_dict()
        for key in d["metadata"]:
            assert isinstance(key, str)

    def test_to_dict_is_json_serializable_with_metadata(self):
        cs = PortfolioCandidateSet(
            client_id="C001",
            approved_profile_name="Moderate",
            candidates={
                PortfolioVariant.DEFENSIVE: _make_dummy_portfolio(),
                PortfolioVariant.BALANCED: _make_dummy_portfolio(),
            },
        )
        json.dumps(cs.to_dict())


# ---------------------------------------------------------------------------
# Tests de política de variantes del coordinator
# ---------------------------------------------------------------------------

class TestCoordinatorVariantPolicy:
    def setup_method(self):
        self.coordinator = PortfolioGenerationCoordinator()
        self.estimates, self.cm, self.rb = _build_inputs()

    def test_growth_marked_risk_budget_exceeded(self):
        result = self.coordinator.generate("CLI-POL-001", "Moderate", self.estimates, self.cm, self.rb)
        if PortfolioVariant.GROWTH in result.candidates:
            m = result.metadata[PortfolioVariant.GROWTH]
            assert m.risk_budget_exceeded is True

    def test_growth_requires_advisor_override(self):
        result = self.coordinator.generate("CLI-POL-002", "Moderate", self.estimates, self.cm, self.rb)
        if PortfolioVariant.GROWTH in result.candidates:
            m = result.metadata[PortfolioVariant.GROWTH]
            assert m.requires_advisor_override is True

    def test_growth_has_reason_code(self):
        result = self.coordinator.generate("CLI-POL-003", "Moderate", self.estimates, self.cm, self.rb)
        if PortfolioVariant.GROWTH in result.candidates:
            m = result.metadata[PortfolioVariant.GROWTH]
            assert RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET in m.reason_codes

    def test_growth_exceeded_constraints_includes_max_volatility(self):
        result = self.coordinator.generate("CLI-POL-004", "Moderate", self.estimates, self.cm, self.rb)
        if PortfolioVariant.GROWTH in result.candidates:
            m = result.metadata[PortfolioVariant.GROWTH]
            assert "max_volatility" in m.exceeded_constraints

    def test_balanced_not_marked_override(self):
        result = self.coordinator.generate("CLI-POL-005", "Moderate", self.estimates, self.cm, self.rb)
        if PortfolioVariant.BALANCED in result.candidates:
            m = result.metadata[PortfolioVariant.BALANCED]
            assert m.risk_budget_exceeded is False
            assert m.requires_advisor_override is False

    def test_defensive_not_marked_override(self):
        result = self.coordinator.generate("CLI-POL-006", "Moderate", self.estimates, self.cm, self.rb)
        if PortfolioVariant.DEFENSIVE in result.candidates:
            m = result.metadata[PortfolioVariant.DEFENSIVE]
            assert m.risk_budget_exceeded is False
            assert m.requires_advisor_override is False

    def test_balanced_no_reason_codes_in_metadata(self):
        result = self.coordinator.generate("CLI-POL-007", "Moderate", self.estimates, self.cm, self.rb)
        if PortfolioVariant.BALANCED in result.candidates:
            m = result.metadata[PortfolioVariant.BALANCED]
            assert RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET not in m.reason_codes

    def test_metadata_covers_all_generated_candidates(self):
        result = self.coordinator.generate("CLI-POL-008", "Moderate", self.estimates, self.cm, self.rb)
        assert set(result.metadata.keys()) == set(result.candidates.keys())

    def test_to_dict_with_growth_metadata_is_json_serializable(self):
        result = self.coordinator.generate("CLI-POL-009", "Moderate", self.estimates, self.cm, self.rb)
        json.dumps(result.to_dict())

    def test_growth_metadata_variant_field_is_growth(self):
        result = self.coordinator.generate("CLI-POL-010", "Moderate", self.estimates, self.cm, self.rb)
        if PortfolioVariant.GROWTH in result.candidates:
            m = result.metadata[PortfolioVariant.GROWTH]
            assert m.variant == PortfolioVariant.GROWTH

    def test_all_generated_portfolios_respect_original_max_volatility(self):
        """GROWTH usa budget relajado pero con 4 activos su vol real no supera el original."""
        result = self.coordinator.generate("CLI-POL-011", "Moderate", self.estimates, self.cm, self.rb)
        for variant, portfolio in result.candidates.items():
            assert portfolio.volatility_annual <= self.rb.max_volatility + 1e-4, (
                f"Variante {variant} vol={portfolio.volatility_annual} > max={self.rb.max_volatility}"
            )