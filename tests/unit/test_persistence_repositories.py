"""
Tests unitarios para la capa de persistencia.

Estrategia:
    - StoredRecord: tests de construcción y validación.
    - InMemory*: tests de comportamiento (save/get/list) con objetos mínimos.
    - AdvisoryWorkflowResult mínimo válido construido directamente.
    - AuditTrail simulado con SimpleNamespace + to_dict().
    - MarkdownReport real desde reporting_layer.
"""

from __future__ import annotations

import json
import types

import pytest

from risk_first_advisory.persistence_layer import (
    InMemoryAuditRepository,
    InMemoryReportRepository,
    InMemoryWorkflowRunRepository,
    RecordNotFoundError,
    RepositoryError,
    StoredRecord,
)
from risk_first_advisory.reporting_layer import MarkdownReport
from risk_first_advisory.workflow_layer import AdvisoryWorkflowResult, AdvisoryWorkflowStatus


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_workflow_result(client_id: str = "CLI-001") -> AdvisoryWorkflowResult:
    """AdvisoryWorkflowResult mínimo válido para tests de persistencia."""
    return AdvisoryWorkflowResult(
        status=AdvisoryWorkflowStatus.COMPLETED,
        client_id=client_id,
        approved_profile_name="moderado",
        advisor_comment="Test comment.",
        m1_result=None,
        goal_feasibility_result=None,
        risk_budget=None,
        governance_passed_tickers=[],
        suitability_passed_tickers=[],
        esg_blocked_tickers=[],
        data_quality_failed_tickers=[],
        final_optimizer_tickers=[],
        return_estimates=[],
        covariance_matrix=None,
        portfolio_feasibility_result=None,
        candidate_set=None,
        reason_codes=[],
        warnings=[],
        notes=[],
    )


def _make_audit_trail(
    client_id: str = "CLI-001",
    session_id: str = "SES-TEST-001",
) -> types.SimpleNamespace:
    """Audit trail dummy con to_dict() compatible."""
    events = ["session_started", "ai_output_initial", "session_closed"]
    return types.SimpleNamespace(
        client_id=client_id,
        session_id=session_id,
        is_closed=True,
        to_dict=lambda: {
            "session_id": session_id,
            "client_id": client_id,
            "is_closed": True,
            "events": events,
        },
    )


def _make_report(client_id: str = "CLI-001") -> MarkdownReport:
    return MarkdownReport(
        title="Test Report",
        content="# Test\n\nContent.",
        client_id=client_id,
        generated_at_utc="2026-05-18T00:00:00Z",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests: StoredRecord
# ─────────────────────────────────────────────────────────────────────────────


class TestStoredRecord:
    def test_valid_construction(self):
        rec = StoredRecord(
            record_id="rec-001",
            record_type="workflow_run",
            created_at_utc="2026-05-18T00:00:00Z",
            payload={"status": "completed"},
            metadata={"client_id": "CLI-001"},
        )
        assert rec.record_id == "rec-001"
        assert rec.record_type == "workflow_run"
        assert rec.payload == {"status": "completed"}
        assert rec.metadata == {"client_id": "CLI-001"}

    def test_default_metadata_is_empty_dict(self):
        rec = StoredRecord(
            record_id="rec-001",
            record_type="workflow_run",
            created_at_utc="2026-05-18T00:00:00Z",
            payload={},
        )
        assert rec.metadata == {}

    def test_empty_record_id_raises(self):
        with pytest.raises(ValueError, match="record_id"):
            StoredRecord(
                record_id="",
                record_type="workflow_run",
                created_at_utc="2026-05-18T00:00:00Z",
                payload={},
            )

    def test_whitespace_record_id_raises(self):
        with pytest.raises(ValueError, match="record_id"):
            StoredRecord(
                record_id="   ",
                record_type="workflow_run",
                created_at_utc="2026-05-18T00:00:00Z",
                payload={},
            )

    def test_empty_record_type_raises(self):
        with pytest.raises(ValueError, match="record_type"):
            StoredRecord(
                record_id="rec-001",
                record_type="",
                created_at_utc="2026-05-18T00:00:00Z",
                payload={},
            )

    def test_empty_created_at_utc_raises(self):
        with pytest.raises(ValueError, match="created_at_utc"):
            StoredRecord(
                record_id="rec-001",
                record_type="workflow_run",
                created_at_utc="",
                payload={},
            )

    def test_payload_not_dict_raises(self):
        with pytest.raises(ValueError, match="payload"):
            StoredRecord(
                record_id="rec-001",
                record_type="workflow_run",
                created_at_utc="2026-05-18T00:00:00Z",
                payload="not a dict",  # type: ignore[arg-type]
            )

    def test_metadata_not_dict_raises(self):
        with pytest.raises(ValueError, match="metadata"):
            StoredRecord(
                record_id="rec-001",
                record_type="workflow_run",
                created_at_utc="2026-05-18T00:00:00Z",
                payload={},
                metadata=["not", "a", "dict"],  # type: ignore[arg-type]
            )

    def test_to_dict_has_all_keys(self):
        rec = StoredRecord(
            record_id="rec-001",
            record_type="workflow_run",
            created_at_utc="2026-05-18T00:00:00Z",
            payload={"k": "v"},
            metadata={"client_id": "CLI-001"},
        )
        d = rec.to_dict()
        assert d["record_id"] == "rec-001"
        assert d["record_type"] == "workflow_run"
        assert d["created_at_utc"] == "2026-05-18T00:00:00Z"
        assert d["payload"] == {"k": "v"}
        assert d["metadata"] == {"client_id": "CLI-001"}

    def test_to_dict_is_json_serializable(self):
        rec = StoredRecord(
            record_id="rec-001",
            record_type="workflow_run",
            created_at_utc="2026-05-18T00:00:00Z",
            payload={"status": "completed", "count": 3},
            metadata={"client_id": "CLI-001"},
        )
        payload = json.dumps(rec.to_dict())
        parsed = json.loads(payload)
        assert parsed["record_id"] == "rec-001"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: InMemoryWorkflowRunRepository
# ─────────────────────────────────────────────────────────────────────────────


class TestInMemoryWorkflowRunRepository:
    def _repo(self) -> InMemoryWorkflowRunRepository:
        return InMemoryWorkflowRunRepository()

    def test_save_returns_stored_record(self):
        repo = self._repo()
        result = _make_workflow_result()
        rec = repo.save_workflow_result(result)
        assert isinstance(rec, StoredRecord)

    def test_save_record_type_is_workflow_run(self):
        repo = self._repo()
        rec = repo.save_workflow_result(_make_workflow_result())
        assert rec.record_type == "workflow_run"

    def test_record_id_has_workflow_prefix(self):
        repo = self._repo()
        rec = repo.save_workflow_result(_make_workflow_result())
        assert rec.record_id.startswith("workflow_")

    def test_metadata_includes_client_id(self):
        repo = self._repo()
        rec = repo.save_workflow_result(_make_workflow_result(client_id="CLI-XYZ"))
        assert rec.metadata["client_id"] == "CLI-XYZ"

    def test_payload_uses_to_dict(self):
        repo = self._repo()
        result = _make_workflow_result(client_id="CLI-001")
        rec = repo.save_workflow_result(result)
        assert "client_id" in rec.payload
        assert rec.payload["client_id"] == "CLI-001"

    def test_get_workflow_result_by_id(self):
        repo = self._repo()
        saved = repo.save_workflow_result(_make_workflow_result())
        retrieved = repo.get_workflow_result(saved.record_id)
        assert retrieved.record_id == saved.record_id

    def test_get_nonexistent_raises_record_not_found(self):
        repo = self._repo()
        with pytest.raises(RecordNotFoundError):
            repo.get_workflow_result("workflow_does_not_exist")

    def test_record_not_found_is_subclass_of_repository_error(self):
        repo = self._repo()
        with pytest.raises(RepositoryError):
            repo.get_workflow_result("workflow_does_not_exist")

    def test_list_all_preserves_insertion_order(self):
        repo = self._repo()
        r1 = repo.save_workflow_result(_make_workflow_result(client_id="CLI-A"))
        r2 = repo.save_workflow_result(_make_workflow_result(client_id="CLI-B"))
        r3 = repo.save_workflow_result(_make_workflow_result(client_id="CLI-C"))
        all_records = repo.list_workflow_results()
        ids = [r.record_id for r in all_records]
        assert ids == [r1.record_id, r2.record_id, r3.record_id]

    def test_list_filters_by_client_id(self):
        repo = self._repo()
        repo.save_workflow_result(_make_workflow_result(client_id="CLI-A"))
        repo.save_workflow_result(_make_workflow_result(client_id="CLI-B"))
        repo.save_workflow_result(_make_workflow_result(client_id="CLI-A"))
        filtered = repo.list_workflow_results(client_id="CLI-A")
        assert len(filtered) == 2
        assert all(r.metadata["client_id"] == "CLI-A" for r in filtered)

    def test_list_none_client_id_returns_all(self):
        repo = self._repo()
        repo.save_workflow_result(_make_workflow_result(client_id="CLI-A"))
        repo.save_workflow_result(_make_workflow_result(client_id="CLI-B"))
        assert len(repo.list_workflow_results(client_id=None)) == 2

    def test_list_unknown_client_id_returns_empty(self):
        repo = self._repo()
        repo.save_workflow_result(_make_workflow_result(client_id="CLI-A"))
        assert repo.list_workflow_results(client_id="CLI-NONE") == []

    def test_created_at_utc_is_populated(self):
        repo = self._repo()
        rec = repo.save_workflow_result(_make_workflow_result())
        assert rec.created_at_utc
        assert "T" in rec.created_at_utc


# ─────────────────────────────────────────────────────────────────────────────
# Tests: InMemoryAuditRepository
# ─────────────────────────────────────────────────────────────────────────────


class TestInMemoryAuditRepository:
    def _repo(self) -> InMemoryAuditRepository:
        return InMemoryAuditRepository()

    def test_save_returns_stored_record(self):
        repo = self._repo()
        rec = repo.save_audit_trail(_make_audit_trail())
        assert isinstance(rec, StoredRecord)

    def test_record_type_is_audit_trail(self):
        repo = self._repo()
        rec = repo.save_audit_trail(_make_audit_trail())
        assert rec.record_type == "audit_trail"

    def test_record_id_has_audit_prefix(self):
        repo = self._repo()
        rec = repo.save_audit_trail(_make_audit_trail())
        assert rec.record_id.startswith("audit_")

    def test_metadata_includes_client_id(self):
        repo = self._repo()
        rec = repo.save_audit_trail(_make_audit_trail(client_id="CLI-AUDIT"))
        assert rec.metadata["client_id"] == "CLI-AUDIT"

    def test_metadata_includes_session_id(self):
        repo = self._repo()
        rec = repo.save_audit_trail(_make_audit_trail(session_id="SES-XYZ"))
        assert rec.metadata["session_id"] == "SES-XYZ"

    def test_payload_uses_to_dict(self):
        repo = self._repo()
        audit = _make_audit_trail(client_id="CLI-001", session_id="SES-001")
        rec = repo.save_audit_trail(audit)
        assert rec.payload["client_id"] == "CLI-001"
        assert rec.payload["session_id"] == "SES-001"
        assert "events" in rec.payload

    def test_get_audit_trail_by_id(self):
        repo = self._repo()
        saved = repo.save_audit_trail(_make_audit_trail())
        retrieved = repo.get_audit_trail(saved.record_id)
        assert retrieved.record_id == saved.record_id

    def test_get_nonexistent_raises_record_not_found(self):
        repo = self._repo()
        with pytest.raises(RecordNotFoundError):
            repo.get_audit_trail("audit_does_not_exist")

    def test_list_filters_by_client_id(self):
        repo = self._repo()
        repo.save_audit_trail(_make_audit_trail(client_id="CLI-A"))
        repo.save_audit_trail(_make_audit_trail(client_id="CLI-B"))
        result = repo.list_audit_trails(client_id="CLI-A")
        assert len(result) == 1
        assert result[0].metadata["client_id"] == "CLI-A"

    def test_list_all_preserves_insertion_order(self):
        repo = self._repo()
        r1 = repo.save_audit_trail(_make_audit_trail(session_id="SES-1"))
        r2 = repo.save_audit_trail(_make_audit_trail(session_id="SES-2"))
        ids = [r.record_id for r in repo.list_audit_trails()]
        assert ids == [r1.record_id, r2.record_id]


# ─────────────────────────────────────────────────────────────────────────────
# Tests: InMemoryReportRepository
# ─────────────────────────────────────────────────────────────────────────────


class TestInMemoryReportRepository:
    def _repo(self) -> InMemoryReportRepository:
        return InMemoryReportRepository()

    def test_save_returns_stored_record(self):
        repo = self._repo()
        rec = repo.save_report(_make_report())
        assert isinstance(rec, StoredRecord)

    def test_record_type_is_markdown_report(self):
        repo = self._repo()
        rec = repo.save_report(_make_report())
        assert rec.record_type == "markdown_report"

    def test_record_id_has_report_prefix(self):
        repo = self._repo()
        rec = repo.save_report(_make_report())
        assert rec.record_id.startswith("report_")

    def test_metadata_includes_client_id(self):
        repo = self._repo()
        rec = repo.save_report(_make_report(client_id="CLI-RPT"))
        assert rec.metadata["client_id"] == "CLI-RPT"

    def test_metadata_includes_title(self):
        repo = self._repo()
        rec = repo.save_report(_make_report())
        assert rec.metadata["title"] == "Test Report"

    def test_payload_uses_to_dict(self):
        repo = self._repo()
        rec = repo.save_report(_make_report(client_id="CLI-001"))
        assert rec.payload["client_id"] == "CLI-001"
        assert rec.payload["title"] == "Test Report"
        assert "content" in rec.payload

    def test_get_report_by_id(self):
        repo = self._repo()
        saved = repo.save_report(_make_report())
        retrieved = repo.get_report(saved.record_id)
        assert retrieved.record_id == saved.record_id

    def test_get_nonexistent_raises_record_not_found(self):
        repo = self._repo()
        with pytest.raises(RecordNotFoundError):
            repo.get_report("report_does_not_exist")

    def test_list_filters_by_client_id(self):
        repo = self._repo()
        repo.save_report(_make_report(client_id="CLI-A"))
        repo.save_report(_make_report(client_id="CLI-B"))
        repo.save_report(_make_report(client_id="CLI-A"))
        result = repo.list_reports(client_id="CLI-A")
        assert len(result) == 2
        assert all(r.metadata["client_id"] == "CLI-A" for r in result)

    def test_list_none_client_id_returns_all(self):
        repo = self._repo()
        repo.save_report(_make_report(client_id="CLI-A"))
        repo.save_report(_make_report(client_id="CLI-B"))
        assert len(repo.list_reports()) == 2

    def test_list_all_preserves_insertion_order(self):
        repo = self._repo()
        r1 = repo.save_report(_make_report(client_id="CLI-1"))
        r2 = repo.save_report(_make_report(client_id="CLI-2"))
        r3 = repo.save_report(_make_report(client_id="CLI-3"))
        ids = [r.record_id for r in repo.list_reports()]
        assert ids == [r1.record_id, r2.record_id, r3.record_id]

    def test_stored_record_to_dict_is_json_serializable(self):
        repo = self._repo()
        rec = repo.save_report(_make_report())
        payload = json.dumps(rec.to_dict())
        parsed = json.loads(payload)
        assert parsed["record_type"] == "markdown_report"

    def test_each_save_generates_unique_record_id(self):
        repo = self._repo()
        r1 = repo.save_report(_make_report())
        r2 = repo.save_report(_make_report())
        assert r1.record_id != r2.record_id
