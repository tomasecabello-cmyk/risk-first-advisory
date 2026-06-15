"""
Tests de portfolio_layer.option_framing — encuadre A/B + explicación por opción.
"""

from __future__ import annotations

from risk_first_advisory.portfolio_layer.option_framing import (
    GROUP_A_LABEL,
    GROUP_B_LABEL,
    ROLE_OVERRIDE,
    ROLE_WITHIN,
    frame_portfolio_options,
)


def _cand(variant, vol, ret, override=False, exceeded=None, div=None):
    return {
        "variant": variant,
        "volatility_annual": vol,
        "expected_return_annual": ret,
        "metadata": {
            "requires_advisor_override": override,
            "exceeded_constraints": exceeded or [],
        },
        "diversification": div or {
            "diversification_score": 80, "concentration_band": "baja",
            "holdings_count": 6, "flags": [],
        },
    }


def test_within_budget_goes_to_group_a():
    out = frame_portfolio_options([_cand("DEFENSIVE", 0.05, 0.04)])
    opt = out["options"][0]
    assert opt["option_role"] == ROLE_WITHIN
    assert opt["group_label"] == GROUP_A_LABEL
    assert "no requiere override" in opt["rationale"]
    assert out["group_a_count"] == 1 and out["group_b_count"] == 0


def test_override_goes_to_group_b_with_reason():
    out = frame_portfolio_options([
        _cand("GROWTH", 0.19, 0.12, override=True, exceeded=["max_volatility"]),
    ])
    opt = out["options"][0]
    assert opt["option_role"] == ROLE_OVERRIDE
    assert opt["group_label"] == GROUP_B_LABEL
    assert "override" in opt["rationale"]
    assert "max_volatility" in opt["rationale"]
    assert out["group_b_count"] == 1


def test_mixed_groups_summary_mentions_both():
    out = frame_portfolio_options([
        _cand("DEFENSIVE", 0.05, 0.04),
        _cand("BALANCED", 0.08, 0.06),
        _cand("GROWTH", 0.15, 0.10, override=True, exceeded=["max_volatility"]),
    ])
    assert out["group_a_count"] == 2
    assert out["group_b_count"] == 1
    assert "override" in out["summary"].lower()


def test_flags_surface_in_rationale():
    div = {"diversification_score": 50, "concentration_band": "alta",
           "holdings_count": 3, "flags": ["concentracion_single_asset", "clase_unica"]}
    out = frame_portfolio_options([_cand("GROWTH", 0.2, 0.15, div=div)])
    assert "ojo:" in out["options"][0]["rationale"]


def test_empty_candidates():
    out = frame_portfolio_options([])
    assert out["options"] == []
    assert "No hay" in out["summary"]


def test_is_deterministic():
    cands = [_cand("BALANCED", 0.08, 0.06)]
    assert frame_portfolio_options(cands) == frame_portfolio_options(cands)
