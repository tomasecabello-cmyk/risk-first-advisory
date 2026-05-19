"""
Tests para AdvisorOverrideApproval y AdvisorOverrideApprovalService.

Cubre:
    - Construcción válida de AdvisorOverrideApproval.
    - Validaciones de campos obligatorios (vacío, tipo, longitud).
    - Propiedades is_approved e is_rejected.
    - Serialización to_dict: JSON-serializable, sin enums crudos.
    - AdvisorOverrideApprovalService:
        - Crea aprobación APPROVED para metadata GROWTH con override.
        - Crea rechazo REJECTED para metadata GROWTH con override.
        - Copia reason_codes y exceeded_constraints desde metadata.
        - Rechaza metadata sin requires_advisor_override.
        - approval_id usa prefijo override_.
        - approved_at_utc incluye timezone UTC.
"""

from __future__ import annotations

import json

import pytest

from risk_first_advisory.human_layer.override_approval import (
    AdvisorOverrideApproval,
    AdvisorOverrideApprovalService,
    OverrideApprovalStatus,
    OverrideDecision,
)
from risk_first_advisory.portfolio_layer.generation import (
    PortfolioVariant,
    PortfolioVariantMetadata,
    RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _growth_metadata_with_override() -> PortfolioVariantMetadata:
    """Metadata GROWTH que requiere advisor override (excede RiskBudget)."""
    return PortfolioVariantMetadata(
        variant=PortfolioVariant.GROWTH,
        risk_budget_exceeded=True,
        requires_advisor_override=True,
        exceeded_constraints=["max_volatility"],
        reason_codes=[RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET],
        notes=["GROWTH excede el RiskBudget aprobado y requiere override explícito del asesor."],
    )


def _balanced_metadata_no_override() -> PortfolioVariantMetadata:
    """Metadata BALANCED que NO requiere advisor override."""
    return PortfolioVariantMetadata(
        variant=PortfolioVariant.BALANCED,
        risk_budget_exceeded=False,
        requires_advisor_override=False,
        exceeded_constraints=[],
        reason_codes=[],
        notes=[],
    )


def _valid_approval(**overrides) -> AdvisorOverrideApproval:
    """Construye un AdvisorOverrideApproval válido con valores por defecto."""
    defaults = dict(
        approval_id="override_20260519_120000",
        workflow_record_id="workflow_000001",
        client_id="CLI-001",
        advisor_id="ADV-001",
        variant=PortfolioVariant.GROWTH,
        decision=OverrideDecision.APPROVED,
        reason_codes=[RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET],
        exceeded_constraints=["max_volatility"],
        advisor_comment="El cliente acepta el riesgo adicional de la variante GROWTH. Documentado.",
        approved_at_utc="2026-05-19T12:00:00+00:00",
        status=OverrideApprovalStatus.VALID,
    )
    defaults.update(overrides)
    return AdvisorOverrideApproval(**defaults)


# ---------------------------------------------------------------------------
# TestAdvisorOverrideApproval — construcción válida
# ---------------------------------------------------------------------------


class TestAdvisorOverrideApprovalValid:
    def test_valid_approval_constructs(self):
        approval = _valid_approval()
        assert approval.approval_id == "override_20260519_120000"
        assert approval.workflow_record_id == "workflow_000001"
        assert approval.client_id == "CLI-001"
        assert approval.advisor_id == "ADV-001"
        assert approval.variant == PortfolioVariant.GROWTH
        assert approval.decision == OverrideDecision.APPROVED
        assert approval.reason_codes == [RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET]
        assert approval.exceeded_constraints == ["max_volatility"]
        assert "GROWTH" in approval.advisor_comment
        assert approval.approved_at_utc == "2026-05-19T12:00:00+00:00"
        assert approval.status == OverrideApprovalStatus.VALID

    def test_valid_rejection_constructs(self):
        approval = _valid_approval(
            decision=OverrideDecision.REJECTED,
            advisor_comment="El exceso de volatilidad no es aceptable para este cliente en este momento.",
        )
        assert approval.decision == OverrideDecision.REJECTED

    def test_empty_lists_are_allowed(self):
        # reason_codes y exceeded_constraints pueden estar vacíos (no todas las variantes tienen)
        approval = _valid_approval(reason_codes=[], exceeded_constraints=[])
        assert approval.reason_codes == []
        assert approval.exceeded_constraints == []


# ---------------------------------------------------------------------------
# TestAdvisorOverrideApproval — validaciones de campos string obligatorios
# ---------------------------------------------------------------------------


class TestAdvisorOverrideApprovalStringValidations:
    def test_approval_id_empty_raises(self):
        with pytest.raises(ValueError, match="approval_id"):
            _valid_approval(approval_id="")

    def test_approval_id_whitespace_raises(self):
        with pytest.raises(ValueError, match="approval_id"):
            _valid_approval(approval_id="   ")

    def test_workflow_record_id_empty_raises(self):
        with pytest.raises(ValueError, match="workflow_record_id"):
            _valid_approval(workflow_record_id="")

    def test_workflow_record_id_whitespace_raises(self):
        with pytest.raises(ValueError, match="workflow_record_id"):
            _valid_approval(workflow_record_id="   ")

    def test_client_id_empty_raises(self):
        with pytest.raises(ValueError, match="client_id"):
            _valid_approval(client_id="")

    def test_client_id_whitespace_raises(self):
        with pytest.raises(ValueError, match="client_id"):
            _valid_approval(client_id="   ")

    def test_advisor_id_empty_raises(self):
        with pytest.raises(ValueError, match="advisor_id"):
            _valid_approval(advisor_id="")

    def test_advisor_id_whitespace_raises(self):
        with pytest.raises(ValueError, match="advisor_id"):
            _valid_approval(advisor_id="   ")

    def test_advisor_comment_empty_raises(self):
        with pytest.raises(ValueError, match="advisor_comment"):
            _valid_approval(advisor_comment="")

    def test_advisor_comment_whitespace_raises(self):
        with pytest.raises(ValueError, match="advisor_comment"):
            _valid_approval(advisor_comment="   ")

    def test_advisor_comment_too_short_raises(self):
        with pytest.raises(ValueError, match="20 caracteres"):
            _valid_approval(advisor_comment="Muy corto.")  # 10 chars

    def test_advisor_comment_exactly_20_chars_ok(self):
        # exactamente 20 caracteres sin espacios leading/trailing
        approval = _valid_approval(advisor_comment="A" * 20)
        assert len(approval.advisor_comment) == 20

    def test_advisor_comment_19_chars_raises(self):
        with pytest.raises(ValueError, match="20 caracteres"):
            _valid_approval(advisor_comment="A" * 19)

    def test_approved_at_utc_empty_raises(self):
        with pytest.raises(ValueError, match="approved_at_utc"):
            _valid_approval(approved_at_utc="")

    def test_approved_at_utc_whitespace_raises(self):
        with pytest.raises(ValueError, match="approved_at_utc"):
            _valid_approval(approved_at_utc="   ")


# ---------------------------------------------------------------------------
# TestAdvisorOverrideApproval — validaciones de tipo enum
# ---------------------------------------------------------------------------


class TestAdvisorOverrideApprovalEnumValidations:
    def test_variant_invalid_type_raises(self):
        with pytest.raises(ValueError, match="PortfolioVariant"):
            _valid_approval(variant="GROWTH")

    def test_variant_none_raises(self):
        with pytest.raises(ValueError, match="PortfolioVariant"):
            _valid_approval(variant=None)

    def test_decision_invalid_type_raises(self):
        with pytest.raises(ValueError, match="OverrideDecision"):
            _valid_approval(decision="APPROVED")

    def test_decision_none_raises(self):
        with pytest.raises(ValueError, match="OverrideDecision"):
            _valid_approval(decision=None)

    def test_status_invalid_type_raises(self):
        with pytest.raises(ValueError, match="OverrideApprovalStatus"):
            _valid_approval(status="VALID")

    def test_status_none_raises(self):
        with pytest.raises(ValueError, match="OverrideApprovalStatus"):
            _valid_approval(status=None)


# ---------------------------------------------------------------------------
# TestAdvisorOverrideApproval — validaciones de tipo lista
# ---------------------------------------------------------------------------


class TestAdvisorOverrideApprovalListValidations:
    def test_reason_codes_not_list_raises(self):
        with pytest.raises(ValueError, match="reason_codes"):
            _valid_approval(reason_codes="not_a_list")

    def test_reason_codes_none_raises(self):
        with pytest.raises(ValueError, match="reason_codes"):
            _valid_approval(reason_codes=None)

    def test_exceeded_constraints_not_list_raises(self):
        with pytest.raises(ValueError, match="exceeded_constraints"):
            _valid_approval(exceeded_constraints="not_a_list")

    def test_exceeded_constraints_none_raises(self):
        with pytest.raises(ValueError, match="exceeded_constraints"):
            _valid_approval(exceeded_constraints=None)


# ---------------------------------------------------------------------------
# TestAdvisorOverrideApproval — propiedades
# ---------------------------------------------------------------------------


class TestAdvisorOverrideApprovalProperties:
    def test_is_approved_true_when_approved(self):
        approval = _valid_approval(decision=OverrideDecision.APPROVED)
        assert approval.is_approved is True
        assert approval.is_rejected is False

    def test_is_rejected_true_when_rejected(self):
        approval = _valid_approval(decision=OverrideDecision.REJECTED)
        assert approval.is_rejected is True
        assert approval.is_approved is False

    def test_is_approved_and_is_rejected_mutually_exclusive(self):
        approved = _valid_approval(decision=OverrideDecision.APPROVED)
        rejected = _valid_approval(decision=OverrideDecision.REJECTED)
        assert approved.is_approved != approved.is_rejected
        assert rejected.is_approved != rejected.is_rejected


# ---------------------------------------------------------------------------
# TestAdvisorOverrideApproval — serialización
# ---------------------------------------------------------------------------


class TestAdvisorOverrideApprovalSerialization:
    def test_to_dict_returns_dict(self):
        approval = _valid_approval()
        d = approval.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_is_json_serializable(self):
        approval = _valid_approval()
        result = json.dumps(approval.to_dict())
        assert isinstance(result, str)

    def test_to_dict_variant_is_string(self):
        approval = _valid_approval()
        d = approval.to_dict()
        assert isinstance(d["variant"], str)
        assert d["variant"] == "GROWTH"

    def test_to_dict_decision_is_string(self):
        approval = _valid_approval()
        d = approval.to_dict()
        assert isinstance(d["decision"], str)
        assert d["decision"] == "APPROVED"

    def test_to_dict_status_is_string(self):
        approval = _valid_approval()
        d = approval.to_dict()
        assert isinstance(d["status"], str)
        assert d["status"] == "VALID"

    def test_to_dict_no_raw_enums(self):
        approval = _valid_approval()
        d = approval.to_dict()
        for v in d.values():
            assert not isinstance(v, PortfolioVariant)
            assert not isinstance(v, OverrideDecision)
            assert not isinstance(v, OverrideApprovalStatus)

    def test_to_dict_contains_expected_keys(self):
        approval = _valid_approval()
        d = approval.to_dict()
        expected_keys = {
            "approval_id",
            "workflow_record_id",
            "client_id",
            "advisor_id",
            "variant",
            "decision",
            "reason_codes",
            "exceeded_constraints",
            "advisor_comment",
            "approved_at_utc",
            "status",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_lists_are_copies(self):
        approval = _valid_approval(reason_codes=["RC_A"], exceeded_constraints=["max_vol"])
        d = approval.to_dict()
        d["reason_codes"].append("mutated")
        d["exceeded_constraints"].append("mutated")
        assert approval.reason_codes == ["RC_A"]
        assert approval.exceeded_constraints == ["max_vol"]


# ---------------------------------------------------------------------------
# TestAdvisorOverrideApprovalService — casos nominales
# ---------------------------------------------------------------------------


class TestAdvisorOverrideApprovalServiceNominal:
    def setup_method(self):
        self.service = AdvisorOverrideApprovalService()
        self.growth_meta = _growth_metadata_with_override()

    def test_service_creates_approved_for_growth_override(self):
        approval = self.service.evaluate_and_create(
            workflow_record_id="workflow_000001",
            client_id="CLI-001",
            advisor_id="ADV-001",
            variant_metadata=self.growth_meta,
            decision=OverrideDecision.APPROVED,
            advisor_comment="Cliente informado y acepta mayor riesgo de la variante GROWTH.",
        )
        assert approval.is_approved
        assert approval.variant == PortfolioVariant.GROWTH
        assert approval.status == OverrideApprovalStatus.VALID

    def test_service_creates_rejected_for_growth_override(self):
        approval = self.service.evaluate_and_create(
            workflow_record_id="workflow_000001",
            client_id="CLI-001",
            advisor_id="ADV-001",
            variant_metadata=self.growth_meta,
            decision=OverrideDecision.REJECTED,
            advisor_comment="El exceso de volatilidad no es compatible con el perfil del cliente.",
        )
        assert approval.is_rejected
        assert approval.variant == PortfolioVariant.GROWTH
        assert approval.status == OverrideApprovalStatus.VALID

    def test_service_copies_reason_codes_from_metadata(self):
        approval = self.service.evaluate_and_create(
            workflow_record_id="workflow_000001",
            client_id="CLI-001",
            advisor_id="ADV-001",
            variant_metadata=self.growth_meta,
            decision=OverrideDecision.APPROVED,
            advisor_comment="Cliente informado y acepta mayor riesgo de la variante GROWTH.",
        )
        assert RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET in approval.reason_codes

    def test_service_copies_exceeded_constraints_from_metadata(self):
        approval = self.service.evaluate_and_create(
            workflow_record_id="workflow_000001",
            client_id="CLI-001",
            advisor_id="ADV-001",
            variant_metadata=self.growth_meta,
            decision=OverrideDecision.APPROVED,
            advisor_comment="Cliente informado y acepta mayor riesgo de la variante GROWTH.",
        )
        assert "max_volatility" in approval.exceeded_constraints

    def test_service_reason_codes_are_independent_copy(self):
        approval = self.service.evaluate_and_create(
            workflow_record_id="workflow_000001",
            client_id="CLI-001",
            advisor_id="ADV-001",
            variant_metadata=self.growth_meta,
            decision=OverrideDecision.APPROVED,
            advisor_comment="Cliente informado y acepta mayor riesgo de la variante GROWTH.",
        )
        approval.reason_codes.append("MUTATED")
        assert "MUTATED" not in self.growth_meta.reason_codes

    def test_service_exceeded_constraints_are_independent_copy(self):
        approval = self.service.evaluate_and_create(
            workflow_record_id="workflow_000001",
            client_id="CLI-001",
            advisor_id="ADV-001",
            variant_metadata=self.growth_meta,
            decision=OverrideDecision.APPROVED,
            advisor_comment="Cliente informado y acepta mayor riesgo de la variante GROWTH.",
        )
        approval.exceeded_constraints.append("MUTATED")
        assert "MUTATED" not in self.growth_meta.exceeded_constraints


# ---------------------------------------------------------------------------
# TestAdvisorOverrideApprovalService — approval_id y timestamp
# ---------------------------------------------------------------------------


class TestAdvisorOverrideApprovalServiceIds:
    def setup_method(self):
        self.service = AdvisorOverrideApprovalService()
        self.growth_meta = _growth_metadata_with_override()

    def _make_approval(self, decision=OverrideDecision.APPROVED):
        return self.service.evaluate_and_create(
            workflow_record_id="workflow_000001",
            client_id="CLI-001",
            advisor_id="ADV-001",
            variant_metadata=self.growth_meta,
            decision=decision,
            advisor_comment="Cliente informado y acepta mayor riesgo de la variante GROWTH.",
        )

    def test_approval_id_starts_with_override_prefix(self):
        approval = self._make_approval()
        assert approval.approval_id.startswith("override_")

    def test_approval_id_is_not_empty(self):
        approval = self._make_approval()
        assert approval.approval_id.strip() != ""

    def test_approved_at_utc_includes_utc_offset(self):
        approval = self._make_approval()
        # ISO format con UTC: debe contener "+00:00" o "Z" o ser parseable como UTC
        utc_str = approval.approved_at_utc
        assert "+00:00" in utc_str or utc_str.endswith("Z"), (
            f"approved_at_utc no incluye offset UTC: {utc_str!r}"
        )

    def test_approved_at_utc_is_not_empty(self):
        approval = self._make_approval()
        assert approval.approved_at_utc.strip() != ""

    def test_two_approvals_have_valid_ids(self):
        a1 = self._make_approval()
        a2 = self._make_approval()
        # ambos tienen el prefijo correcto
        assert a1.approval_id.startswith("override_")
        assert a2.approval_id.startswith("override_")


# ---------------------------------------------------------------------------
# TestAdvisorOverrideApprovalService — rechazo por requires_advisor_override=False
# ---------------------------------------------------------------------------


class TestAdvisorOverrideApprovalServiceGuard:
    def setup_method(self):
        self.service = AdvisorOverrideApprovalService()
        self.balanced_meta = _balanced_metadata_no_override()

    def test_service_raises_if_no_override_required(self):
        with pytest.raises(ValueError, match="requires_advisor_override"):
            self.service.evaluate_and_create(
                workflow_record_id="workflow_000001",
                client_id="CLI-001",
                advisor_id="ADV-001",
                variant_metadata=self.balanced_meta,
                decision=OverrideDecision.APPROVED,
                advisor_comment="Este comentario es suficientemente largo para pasar la validación.",
            )

    def test_service_error_message_mentions_variant(self):
        with pytest.raises(ValueError, match="BALANCED"):
            self.service.evaluate_and_create(
                workflow_record_id="workflow_000001",
                client_id="CLI-001",
                advisor_id="ADV-001",
                variant_metadata=self.balanced_meta,
                decision=OverrideDecision.REJECTED,
                advisor_comment="Este comentario es suficientemente largo para pasar la validación.",
            )

    def test_service_raises_for_defensive_without_override(self):
        defensive_meta = PortfolioVariantMetadata(
            variant=PortfolioVariant.DEFENSIVE,
            risk_budget_exceeded=False,
            requires_advisor_override=False,
            exceeded_constraints=[],
            reason_codes=[],
            notes=[],
        )
        with pytest.raises(ValueError, match="requires_advisor_override"):
            self.service.evaluate_and_create(
                workflow_record_id="workflow_000001",
                client_id="CLI-001",
                advisor_id="ADV-001",
                variant_metadata=defensive_meta,
                decision=OverrideDecision.APPROVED,
                advisor_comment="Este comentario es suficientemente largo para pasar la validación.",
            )

    def test_service_result_is_json_serializable(self):
        growth_meta = _growth_metadata_with_override()
        approval = self.service.evaluate_and_create(
            workflow_record_id="workflow_000001",
            client_id="CLI-001",
            advisor_id="ADV-001",
            variant_metadata=growth_meta,
            decision=OverrideDecision.APPROVED,
            advisor_comment="Cliente informado y acepta mayor riesgo de la variante GROWTH.",
        )
        result = json.dumps(approval.to_dict())
        assert isinstance(result, str)
