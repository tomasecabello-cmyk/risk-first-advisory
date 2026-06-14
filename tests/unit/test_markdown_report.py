"""
Tests unitarios para MarkdownReport y MarkdownReportGenerator.

Estrategia de mocking: se usan types.SimpleNamespace para construir objetos
que imitan AdvisoryWorkflowResult y sus sub-objetos sin depender del
workflow_layer completo. Esto mantiene los tests rápidos y aislados.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from risk_first_advisory.reporting_layer import MarkdownReport, MarkdownReportGenerator
from risk_first_advisory.workflow_layer import AdvisoryWorkflowStatus

# ─────────────────────────────────────────────────────────────────────────────
# Helpers para construir objetos fake
# ─────────────────────────────────────────────────────────────────────────────


def _make_audit(session_id: str = "SES-TEST-001", closed: bool = True):
    events = [
        "session_started",
        "ai_output_initial",
        "advisor_profile_approval",
        "session_closed",
    ]
    return types.SimpleNamespace(
        is_closed=closed,
        event_types=lambda: events,
    )


def _make_m1_result(
    session_id: str = "SES-TEST-001",
    advisor_id: str = "ADV-001",
    client_id: str = "CLI-001",
    initial_profile: str = "moderado-defensivo",
    revised_profile: str | None = "moderado",
    approved_profile_name: str = "moderado",
    modified: bool = True,
    follow_up_rounds: int = 1,
    include_audit: bool = True,
):
    prelim_initial = types.SimpleNamespace(profile_name=initial_profile)
    prelim_revised = (
        types.SimpleNamespace(profile_name=revised_profile) if revised_profile else None
    )
    approved = types.SimpleNamespace(
        profile_name=approved_profile_name,
        original_profile=initial_profile,
        is_modified=modified,
        advisor_comment="Cliente con experiencia real mayor a la declarada.",
    )
    audit = _make_audit(session_id=session_id) if include_audit else None
    return types.SimpleNamespace(
        session_id=session_id,
        advisor_id=advisor_id,
        client_id=client_id,
        preliminary_profile_initial=prelim_initial,
        preliminary_profile_revised=prelim_revised,
        approved_profile=approved,
        advisor_modified_profile=modified,
        follow_up_rounds_executed=follow_up_rounds,
        audit=audit,
    )


def _make_feasibility_report(
    status_value: str = "viable",
    required: float = 0.07,
    achievable: float = 0.09,
    gap: float = -0.02,
    block: bool = False,
):
    from risk_first_advisory.rules_layer.goal_feasibility import FeasibilityStatus

    return types.SimpleNamespace(
        status=FeasibilityStatus(status_value),
        required_return_annual=required,
        achievable_return_annual=achievable,
        gap=gap,
        reason="Rendimiento histórico suficiente.",
        block_portfolio_generation=block,
        suggested_actions=[],
        disclaimer="Past performance is not a guarantee.",
    )


def _make_risk_budget():
    from risk_first_advisory.models.risk_budget import RiskBudget

    return RiskBudget(
        profile_name="moderado",
        target_volatility=0.10,
        max_volatility=0.14,
        max_drawdown=-0.20,
        min_liquidity=0.05,
        max_equity=0.70,
        max_high_yield=0.10,
        max_single_asset=0.25,
        max_sector_exposure=0.30,
        max_duration=7.0,
        complex_products_allowed=False,
        preferred_currency="USD",
    )


def _make_portfolio_feasibility(feasible: bool = True):
    from risk_first_advisory.portfolio_layer.feasibility import PortfolioFeasibilityStatus

    status = PortfolioFeasibilityStatus.FEASIBLE if feasible else PortfolioFeasibilityStatus.INFEASIBLE
    return types.SimpleNamespace(
        status=status,
        is_feasible=feasible,
        asset_count=4,
        required_min_single_asset_cap=0.25,
        actual_max_single_asset=0.30,
        min_achievable_volatility=0.08,
        max_allowed_volatility=0.14,
        failed_checks=[],
        warnings=[],
        suggested_actions=[],
        notes=[],
    )


def _make_optimized_portfolio(objective_value: str = "MAX_UTILITY"):
    from risk_first_advisory.portfolio_layer.optimizer import OptimizationObjective

    return types.SimpleNamespace(
        objective=OptimizationObjective(objective_value),
        weights={"AGG": 0.40, "VEA": 0.35, "HYG": 0.25},
        expected_return_annual=0.085,
        volatility_annual=0.11,
        risk_score=0.55,
        constraints_satisfied=True,
        reason_codes=[],
        notes=[],
    )


def _make_candidate_set(with_defensive: bool = False):
    from risk_first_advisory.portfolio_layer.generation import PortfolioVariant

    candidates = {
        PortfolioVariant.BALANCED: _make_optimized_portfolio("MAX_UTILITY"),
        PortfolioVariant.GROWTH: _make_optimized_portfolio("MAX_RETURN"),
    }
    if with_defensive:
        candidates[PortfolioVariant.DEFENSIVE] = _make_optimized_portfolio("MIN_VARIANCE")

    return types.SimpleNamespace(
        client_id="CLI-001",
        approved_profile_name="moderado",
        candidates=candidates,
        selected_variant=PortfolioVariant.BALANCED,
        count=len(candidates),
        reason_codes=[],
        notes=[],
        # Sin metadata: ejercita el path de defaults seguros
    )


def _make_candidate_set_with_metadata(with_growth_override: bool = False):
    """Candidate set con metadata explícita por variante.

    Si with_growth_override=True, GROWTH lleva risk_budget_exceeded=True y
    RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET en reason_codes.
    """
    from risk_first_advisory.portfolio_layer.generation import (
        RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET,
        PortfolioVariant,
        PortfolioVariantMetadata,
    )

    def _neutral(variant):
        return PortfolioVariantMetadata(
            variant=variant,
            risk_budget_exceeded=False,
            requires_advisor_override=False,
            exceeded_constraints=[],
            reason_codes=[],
            notes=[],
        )

    growth_meta = (
        PortfolioVariantMetadata(
            variant=PortfolioVariant.GROWTH,
            risk_budget_exceeded=True,
            requires_advisor_override=True,
            exceeded_constraints=["max_volatility"],
            reason_codes=[RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET],
            notes=["GROWTH exceeds approved RiskBudget and requires explicit advisor override."],
        )
        if with_growth_override
        else _neutral(PortfolioVariant.GROWTH)
    )

    candidates = {
        PortfolioVariant.BALANCED: _make_optimized_portfolio("MAX_UTILITY"),
        PortfolioVariant.GROWTH: _make_optimized_portfolio("MAX_RETURN"),
    }
    metadata = {
        PortfolioVariant.BALANCED: _neutral(PortfolioVariant.BALANCED),
        PortfolioVariant.GROWTH: growth_meta,
    }
    return types.SimpleNamespace(
        client_id="CLI-001",
        approved_profile_name="moderado",
        candidates=candidates,
        selected_variant=PortfolioVariant.BALANCED,
        count=len(candidates),
        reason_codes=[],
        notes=[],
        metadata=metadata,
    )


def _make_result(
    status: AdvisoryWorkflowStatus = AdvisoryWorkflowStatus.COMPLETED,
    client_id: str = "CLI-001",
    candidate_set=None,
    portfolio_feasibility=None,
    risk_budget=None,
    goal_feasibility=None,
    warnings: list[str] | None = None,
    reason_codes: list[str] | None = None,
    notes: list[str] | None = None,
    m1_result=None,
):
    is_completed = status in (
        AdvisoryWorkflowStatus.COMPLETED,
        AdvisoryWorkflowStatus.COMPLETED_WITH_WARNINGS,
    )
    return types.SimpleNamespace(
        status=status,
        client_id=client_id,
        approved_profile_name="moderado",
        advisor_comment="Cliente con experiencia real mayor a la declarada.",
        m1_result=m1_result if m1_result is not None else _make_m1_result(),
        goal_feasibility_result=goal_feasibility if goal_feasibility is not None else _make_feasibility_report(),
        risk_budget=risk_budget,
        governance_passed_tickers=["AGG", "VEA", "HYG", "BIL"],
        suitability_passed_tickers=["AGG", "VEA", "HYG", "BIL"],
        esg_blocked_tickers=[],
        data_quality_failed_tickers=[],
        final_optimizer_tickers=["AGG", "VEA", "HYG", "BIL"],
        return_estimates=[],
        covariance_matrix=None,
        portfolio_feasibility_result=portfolio_feasibility,
        candidate_set=candidate_set,
        reason_codes=reason_codes if reason_codes is not None else [],
        warnings=warnings if warnings is not None else [],
        notes=notes if notes is not None else [],
        is_completed=is_completed,
        has_portfolios=candidate_set is not None,
        has_warnings=bool(warnings),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests: MarkdownReport
# ─────────────────────────────────────────────────────────────────────────────


class TestMarkdownReport:
    def test_valid_construction(self):
        report = MarkdownReport(
            title="Test Report",
            content="# Hello",
            client_id="CLI-001",
            generated_at_utc="2026-01-01T00:00:00Z",
        )
        assert report.title == "Test Report"
        assert report.client_id == "CLI-001"

    def test_empty_title_raises(self):
        with pytest.raises(ValueError, match="title"):
            MarkdownReport(
                title="",
                content="# Hello",
                client_id="CLI-001",
                generated_at_utc="2026-01-01T00:00:00Z",
            )

    def test_whitespace_title_raises(self):
        with pytest.raises(ValueError, match="title"):
            MarkdownReport(
                title="   ",
                content="# Hello",
                client_id="CLI-001",
                generated_at_utc="2026-01-01T00:00:00Z",
            )

    def test_empty_content_raises(self):
        with pytest.raises(ValueError, match="content"):
            MarkdownReport(
                title="Report",
                content="",
                client_id="CLI-001",
                generated_at_utc="2026-01-01T00:00:00Z",
            )

    def test_empty_client_id_raises(self):
        with pytest.raises(ValueError, match="client_id"):
            MarkdownReport(
                title="Report",
                content="# Hello",
                client_id="",
                generated_at_utc="2026-01-01T00:00:00Z",
            )

    def test_empty_generated_at_raises(self):
        with pytest.raises(ValueError, match="generated_at_utc"):
            MarkdownReport(
                title="Report",
                content="# Hello",
                client_id="CLI-001",
                generated_at_utc="",
            )

    def test_notes_not_list_raises(self):
        with pytest.raises(ValueError, match="notes"):
            MarkdownReport(
                title="Report",
                content="# Hello",
                client_id="CLI-001",
                generated_at_utc="2026-01-01T00:00:00Z",
                notes="not a list",  # type: ignore[arg-type]
            )

    def test_to_dict_has_all_keys(self):
        report = MarkdownReport(
            title="Report",
            content="# Hello",
            client_id="CLI-001",
            generated_at_utc="2026-01-01T00:00:00Z",
            notes=["one note"],
        )
        d = report.to_dict()
        assert d["title"] == "Report"
        assert d["content"] == "# Hello"
        assert d["client_id"] == "CLI-001"
        assert d["generated_at_utc"] == "2026-01-01T00:00:00Z"
        assert d["notes"] == ["one note"]

    def test_to_dict_is_json_serializable(self):
        report = MarkdownReport(
            title="Report",
            content="# Hello",
            client_id="CLI-001",
            generated_at_utc="2026-01-01T00:00:00Z",
        )
        payload = json.dumps(report.to_dict())
        parsed = json.loads(payload)
        assert parsed["client_id"] == "CLI-001"

    def test_save_creates_file(self, tmp_path: Path):
        report = MarkdownReport(
            title="Report",
            content="# Hello\n\nContent here.",
            client_id="CLI-001",
            generated_at_utc="2026-01-01T00:00:00Z",
        )
        target = tmp_path / "report.md"
        returned = report.save(target)
        assert returned == target
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "# Hello\n\nContent here."

    def test_save_creates_parent_directories(self, tmp_path: Path):
        report = MarkdownReport(
            title="Report",
            content="# Content",
            client_id="CLI-001",
            generated_at_utc="2026-01-01T00:00:00Z",
        )
        nested = tmp_path / "a" / "b" / "c" / "report.md"
        report.save(nested)
        assert nested.exists()

    def test_save_accepts_string_path(self, tmp_path: Path):
        report = MarkdownReport(
            title="Report",
            content="# Content",
            client_id="CLI-001",
            generated_at_utc="2026-01-01T00:00:00Z",
        )
        target = str(tmp_path / "report.md")
        result = report.save(target)
        assert isinstance(result, Path)
        assert result.exists()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: MarkdownReportGenerator
# ─────────────────────────────────────────────────────────────────────────────


class TestMarkdownReportGenerator:
    def _gen(self) -> MarkdownReportGenerator:
        return MarkdownReportGenerator()

    def test_returns_markdown_report_instance(self):
        result = _make_result(status=AdvisoryWorkflowStatus.COMPLETED)
        report = self._gen().generate_from_workflow_result(result)
        assert isinstance(report, MarkdownReport)

    def test_title_is_risk_first_advisory_report(self):
        result = _make_result()
        report = self._gen().generate_from_workflow_result(result)
        assert report.title == "Risk-First Advisory Report"

    def test_client_id_matches_result(self):
        result = _make_result(client_id="CLI-XYZ")
        report = self._gen().generate_from_workflow_result(result)
        assert report.client_id == "CLI-XYZ"

    def test_generated_at_utc_is_populated(self):
        result = _make_result()
        report = self._gen().generate_from_workflow_result(result)
        assert report.generated_at_utc
        assert "T" in report.generated_at_utc

    def test_content_contains_all_12_section_headers(self):
        result = _make_result(
            status=AdvisoryWorkflowStatus.COMPLETED,
            risk_budget=_make_risk_budget(),
            portfolio_feasibility=_make_portfolio_feasibility(),
            candidate_set=_make_candidate_set(),
        )
        report = self._gen().generate_from_workflow_result(result)
        expected_sections = [
            "# Risk-First Advisory Report",
            "## Client",
            "## Workflow Status",
            "## Approved Profile",
            "## Goal Feasibility",
            "## Risk Budget",
            "## Universe Summary",
            "## Portfolio Feasibility",
            "## Candidate Portfolios",
            "## Warnings and Reason Codes",
            "## Audit Trail",
            "## Disclaimer",
        ]
        for section in expected_sections:
            assert section in report.content, f"Falta sección: {section!r}"

    def test_content_contains_client_id(self):
        result = _make_result(client_id="CLI-ABC")
        report = self._gen().generate_from_workflow_result(result)
        assert "CLI-ABC" in report.content

    def test_content_contains_workflow_status_value(self):
        result = _make_result(status=AdvisoryWorkflowStatus.COMPLETED)
        report = self._gen().generate_from_workflow_result(result)
        assert "completed" in report.content

    def test_content_contains_approved_profile_name(self):
        result = _make_result()
        report = self._gen().generate_from_workflow_result(result)
        assert "moderado" in report.content

    def test_default_disclaimer_in_content(self):
        result = _make_result()
        report = self._gen().generate_from_workflow_result(result)
        assert MarkdownReportGenerator.DEFAULT_DISCLAIMER in report.content

    def test_custom_disclaimer_overrides_default(self):
        result = _make_result()
        custom = "Custom disclaimer for this client."
        report = self._gen().generate_from_workflow_result(result, disclaimer=custom)
        assert custom in report.content
        assert MarkdownReportGenerator.DEFAULT_DISCLAIMER not in report.content

    def test_blocked_workflow_adds_note(self):
        result = _make_result(status=AdvisoryWorkflowStatus.BLOCKED_BY_EMPTY_UNIVERSE)
        report = self._gen().generate_from_workflow_result(result)
        assert any("blocked" in note.lower() for note in report.notes)

    def test_completed_workflow_no_blocked_note(self):
        result = _make_result(status=AdvisoryWorkflowStatus.COMPLETED)
        report = self._gen().generate_from_workflow_result(result)
        assert not any("blocked" in note.lower() for note in report.notes)

    def test_no_candidate_set_shows_no_portfolios_generated(self):
        result = _make_result(candidate_set=None)
        report = self._gen().generate_from_workflow_result(result)
        assert "No portfolios generated." in report.content

    def test_no_portfolio_feasibility_shows_not_evaluated(self):
        result = _make_result(portfolio_feasibility=None)
        report = self._gen().generate_from_workflow_result(result)
        assert "Not evaluated." in report.content

    def test_no_risk_budget_shows_not_computed(self):
        result = _make_result(risk_budget=None)
        report = self._gen().generate_from_workflow_result(result)
        assert "Not computed." in report.content

    def test_risk_budget_values_formatted_as_percentages(self):
        result = _make_result(risk_budget=_make_risk_budget())
        report = self._gen().generate_from_workflow_result(result)
        assert "10.00%" in report.content  # target_volatility = 0.10
        assert "14.00%" in report.content  # max_volatility = 0.14
        assert "25.00%" in report.content  # max_single_asset = 0.25

    def test_candidate_portfolios_in_canonical_order(self):
        result = _make_result(
            status=AdvisoryWorkflowStatus.COMPLETED,
            candidate_set=_make_candidate_set(with_defensive=True),
        )
        report = self._gen().generate_from_workflow_result(result)
        idx_defensive = report.content.find("### DEFENSIVE")
        idx_balanced = report.content.find("### BALANCED")
        idx_growth = report.content.find("### GROWTH")
        assert idx_defensive < idx_balanced < idx_growth, (
            "Variantes deben aparecer en orden DEFENSIVE → BALANCED → GROWTH"
        )

    def test_portfolio_weights_shown_as_percentages(self):
        result = _make_result(
            status=AdvisoryWorkflowStatus.COMPLETED,
            candidate_set=_make_candidate_set(),
        )
        report = self._gen().generate_from_workflow_result(result)
        assert "40.00%" in report.content  # AGG weight
        assert "35.00%" in report.content  # VEA weight
        assert "25.00%" in report.content  # HYG weight

    def test_audit_trail_events_appear_in_content(self):
        result = _make_result()
        report = self._gen().generate_from_workflow_result(result)
        assert "session_started" in report.content
        assert "session_closed" in report.content

    def test_warnings_appear_in_content(self):
        result = _make_result(
            status=AdvisoryWorkflowStatus.COMPLETED_WITH_WARNINGS,
            warnings=["DataQuality WARNING para HYG: reason_codes=[]"],
        )
        report = self._gen().generate_from_workflow_result(result)
        assert "DataQuality WARNING" in report.content

    def test_reason_codes_appear_in_content(self):
        result = _make_result(reason_codes=["ESG_BLOCKED", "SUITABILITY_LIMITED"])
        report = self._gen().generate_from_workflow_result(result)
        assert "ESG_BLOCKED" in report.content
        assert "SUITABILITY_LIMITED" in report.content

    def test_goal_feasibility_nan_gap_shown_as_na(self):
        from risk_first_advisory.rules_layer.goal_feasibility import FeasibilityStatus

        fr = types.SimpleNamespace(
            status=FeasibilityStatus("undetermined"),
            required_return_annual=0.07,
            achievable_return_annual=float("nan"),
            gap=float("nan"),
            reason="No se pudo determinar.",
            block_portfolio_generation=False,
            suggested_actions=[],
            disclaimer="",
        )
        result = _make_result(goal_feasibility=fr)
        report = self._gen().generate_from_workflow_result(result)
        assert "N/A" in report.content

    def test_full_report_to_dict_is_json_serializable(self):
        result = _make_result(
            status=AdvisoryWorkflowStatus.COMPLETED,
            risk_budget=_make_risk_budget(),
            portfolio_feasibility=_make_portfolio_feasibility(),
            candidate_set=_make_candidate_set(with_defensive=True),
        )
        report = self._gen().generate_from_workflow_result(result)
        payload = json.dumps(report.to_dict())
        parsed = json.loads(payload)
        assert parsed["title"] == "Risk-First Advisory Report"
        assert parsed["client_id"] == "CLI-001"

    def test_no_audit_shows_not_available(self):
        m1 = _make_m1_result(include_audit=False)
        result = _make_result(m1_result=m1)
        report = self._gen().generate_from_workflow_result(result)
        assert "No audit trail available." in report.content

    def test_selected_variant_marked_in_content(self):
        result = _make_result(
            status=AdvisoryWorkflowStatus.COMPLETED,
            candidate_set=_make_candidate_set(),
        )
        report = self._gen().generate_from_workflow_result(result)
        assert "*(selected)*" in report.content


# ─────────────────────────────────────────────────────────────────────────────
# Tests: metadata de variantes en el reporte
# ─────────────────────────────────────────────────────────────────────────────


class TestVariantMetadataInReport:
    def _gen(self) -> MarkdownReportGenerator:
        return MarkdownReportGenerator()

    def _result_with_metadata(self, with_growth_override: bool = False):
        return _make_result(
            status=AdvisoryWorkflowStatus.COMPLETED,
            candidate_set=_make_candidate_set_with_metadata(
                with_growth_override=with_growth_override
            ),
        )

    def _result_no_metadata(self):
        return _make_result(
            status=AdvisoryWorkflowStatus.COMPLETED,
            candidate_set=_make_candidate_set(),
        )

    # ── Presencia de la subsección ─────────────────────────────────────────

    def test_report_includes_variant_metadata_header(self):
        result = self._result_with_metadata()
        report = self._gen().generate_from_workflow_result(result)
        assert "Variant Metadata" in report.content

    def test_report_shows_risk_budget_exceeded_field(self):
        result = self._result_with_metadata()
        report = self._gen().generate_from_workflow_result(result)
        assert "risk_budget_exceeded" in report.content

    def test_report_shows_requires_advisor_override_field(self):
        result = self._result_with_metadata()
        report = self._gen().generate_from_workflow_result(result)
        assert "requires_advisor_override" in report.content

    def test_report_shows_exceeded_constraints_field(self):
        result = self._result_with_metadata()
        report = self._gen().generate_from_workflow_result(result)
        assert "exceeded_constraints" in report.content

    def test_report_shows_metadata_reason_codes_field(self):
        result = self._result_with_metadata()
        report = self._gen().generate_from_workflow_result(result)
        assert "reason_codes" in report.content

    def test_report_shows_metadata_notes_field(self):
        result = self._result_with_metadata()
        report = self._gen().generate_from_workflow_result(result)
        assert "notes" in report.content

    # ── GROWTH con override ────────────────────────────────────────────────

    def test_growth_override_shows_rc_in_content(self):
        from risk_first_advisory.portfolio_layer.generation import (
            RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET,
        )
        result = self._result_with_metadata(with_growth_override=True)
        report = self._gen().generate_from_workflow_result(result)
        assert RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET in report.content

    def test_growth_override_shows_requires_advisor_override_true(self):
        result = self._result_with_metadata(with_growth_override=True)
        report = self._gen().generate_from_workflow_result(result)
        assert "requires_advisor_override: true" in report.content

    def test_growth_override_shows_risk_budget_exceeded_true(self):
        result = self._result_with_metadata(with_growth_override=True)
        report = self._gen().generate_from_workflow_result(result)
        assert "risk_budget_exceeded: true" in report.content

    def test_growth_override_shows_max_volatility_in_exceeded_constraints(self):
        result = self._result_with_metadata(with_growth_override=True)
        report = self._gen().generate_from_workflow_result(result)
        assert "max_volatility" in report.content

    def test_growth_override_note_appears_in_content(self):
        result = self._result_with_metadata(with_growth_override=True)
        report = self._gen().generate_from_workflow_result(result)
        assert "GROWTH exceeds approved RiskBudget" in report.content

    # ── Variantes sin override ─────────────────────────────────────────────

    def test_balanced_not_marked_override(self):
        result = self._result_with_metadata(with_growth_override=True)
        report = self._gen().generate_from_workflow_result(result)
        content = report.content
        # BALANCED aparece antes de GROWTH; buscamos su sección específica
        balanced_start = content.find("### BALANCED")
        growth_start = content.find("### GROWTH")
        balanced_section = content[balanced_start:growth_start]
        assert "requires_advisor_override: false" in balanced_section

    def test_no_override_shows_risk_budget_exceeded_false(self):
        result = self._result_with_metadata(with_growth_override=False)
        report = self._gen().generate_from_workflow_result(result)
        assert "risk_budget_exceeded: false" in report.content

    # ── Sin metadata (defaults seguros) ───────────────────────────────────

    def test_no_metadata_shows_variant_metadata_header(self):
        result = self._result_no_metadata()
        report = self._gen().generate_from_workflow_result(result)
        assert "Variant Metadata" in report.content

    def test_no_metadata_shows_false_for_risk_budget_exceeded(self):
        result = self._result_no_metadata()
        report = self._gen().generate_from_workflow_result(result)
        assert "risk_budget_exceeded: false" in report.content

    def test_no_metadata_shows_false_for_requires_advisor_override(self):
        result = self._result_no_metadata()
        report = self._gen().generate_from_workflow_result(result)
        assert "requires_advisor_override: false" in report.content

    def test_no_metadata_shows_none_for_exceeded_constraints(self):
        result = self._result_no_metadata()
        report = self._gen().generate_from_workflow_result(result)
        assert "exceeded_constraints: None" in report.content

    def test_no_metadata_does_not_raise(self):
        result = self._result_no_metadata()
        report = self._gen().generate_from_workflow_result(result)
        assert isinstance(report, MarkdownReport)
