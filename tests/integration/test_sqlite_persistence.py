"""
Tests de integración para la capa SQLite.

Usa tmp_path de pytest para crear DBs temporales que se limpian solas.
No ejecuta el workflow real: construye objetos mínimos válidos.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from risk_first_advisory.persistence_layer.repositories import (
    RecordNotFoundError,
    StoredRecord,
)
from risk_first_advisory.persistence_layer.sqlite_repository import (
    SQLiteAuditRepository,
    SQLitePersistenceStore,
    SQLiteReportRepository,
    SQLiteWorkflowRunRepository,
)
from risk_first_advisory.reporting_layer import MarkdownReport
from risk_first_advisory.workflow_layer import AdvisoryWorkflowResult, AdvisoryWorkflowStatus

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_workflow_result(client_id: str = "CLI-001") -> AdvisoryWorkflowResult:
    return AdvisoryWorkflowResult(
        status=AdvisoryWorkflowStatus.COMPLETED,
        client_id=client_id,
        approved_profile_name="moderado",
        advisor_comment="Test.",
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


def _make_audit(
    client_id: str = "CLI-001",
    session_id: str = "SES-001",
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        client_id=client_id,
        session_id=session_id,
        is_closed=True,
        to_dict=lambda: {
            "session_id": session_id,
            "client_id": client_id,
            "is_closed": True,
            "events": ["session_started", "session_closed"],
        },
    )


def _make_report(client_id: str = "CLI-001") -> MarkdownReport:
    return MarkdownReport(
        title="Integration Test Report",
        content="# Report\n\nContent.",
        client_id=client_id,
        generated_at_utc="2026-05-18T00:00:00Z",
    )


def _open_store(db_path: Path) -> SQLitePersistenceStore:
    store = SQLitePersistenceStore(db_path)
    store.init_schema()
    return store


# ─────────────────────────────────────────────────────────────────────────────
# Tests: SQLitePersistenceStore — schema
# ─────────────────────────────────────────────────────────────────────────────


class TestSQLitePersistenceStoreSchema:
    def test_init_schema_creates_records_table(self, tmp_path: Path):
        store = SQLitePersistenceStore(tmp_path / "test.db")
        store.init_schema()
        row = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='records'"
        ).fetchone()
        assert row is not None
        store.close()

    def test_init_schema_creates_counters_table(self, tmp_path: Path):
        store = SQLitePersistenceStore(tmp_path / "test.db")
        store.init_schema()
        row = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='counters'"
        ).fetchone()
        assert row is not None
        store.close()

    def test_init_schema_is_idempotent(self, tmp_path: Path):
        store = SQLitePersistenceStore(tmp_path / "test.db")
        store.init_schema()
        store.init_schema()  # segunda llamada no debe lanzar
        store.close()

    def test_context_manager_closes_connection(self, tmp_path: Path):
        with SQLitePersistenceStore(tmp_path / "test.db") as store:
            store.init_schema()
        # Tras el with, la conexión debe estar cerrada.
        # Verificamos que una nueva apertura funcione sin conflictos.
        with SQLitePersistenceStore(tmp_path / "test.db") as store2:
            store2.init_schema()
            assert store2._conn is not None


# ─────────────────────────────────────────────────────────────────────────────
# Tests: SQLiteWorkflowRunRepository
# ─────────────────────────────────────────────────────────────────────────────


class TestSQLiteWorkflowRunRepository:
    def _setup(self, tmp_path: Path):
        store = _open_store(tmp_path / "test.db")
        repo = SQLiteWorkflowRunRepository(store)
        return store, repo

    def test_save_returns_stored_record(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_workflow_result(_make_workflow_result())
        assert isinstance(rec, StoredRecord)
        store.close()

    def test_record_type_is_workflow_run(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_workflow_result(_make_workflow_result())
        assert rec.record_type == "workflow_run"
        store.close()

    def test_record_id_has_workflow_prefix(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_workflow_result(_make_workflow_result())
        assert rec.record_id.startswith("workflow_")
        store.close()

    def test_record_id_is_zero_padded_sequential(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        r1 = repo.save_workflow_result(_make_workflow_result())
        r2 = repo.save_workflow_result(_make_workflow_result())
        assert r1.record_id == "workflow_000001"
        assert r2.record_id == "workflow_000002"
        store.close()

    def test_get_workflow_result_retrieves_exact_payload(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        result = _make_workflow_result(client_id="CLI-XYZ")
        saved = repo.save_workflow_result(result)
        retrieved = repo.get_workflow_result(saved.record_id)
        assert retrieved.record_id == saved.record_id
        assert retrieved.payload["client_id"] == "CLI-XYZ"
        store.close()

    def test_get_nonexistent_raises_record_not_found(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        with pytest.raises(RecordNotFoundError):
            repo.get_workflow_result("workflow_999999")
        store.close()

    def test_list_workflow_results_preserves_insertion_order(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        r1 = repo.save_workflow_result(_make_workflow_result(client_id="CLI-A"))
        r2 = repo.save_workflow_result(_make_workflow_result(client_id="CLI-B"))
        r3 = repo.save_workflow_result(_make_workflow_result(client_id="CLI-C"))
        all_records = repo.list_workflow_results()
        assert [r.record_id for r in all_records] == [
            r1.record_id, r2.record_id, r3.record_id
        ]
        store.close()

    def test_list_workflow_results_filters_by_client_id(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        repo.save_workflow_result(_make_workflow_result(client_id="CLI-A"))
        repo.save_workflow_result(_make_workflow_result(client_id="CLI-B"))
        repo.save_workflow_result(_make_workflow_result(client_id="CLI-A"))
        filtered = repo.list_workflow_results(client_id="CLI-A")
        assert len(filtered) == 2
        assert all(r.metadata["client_id"] == "CLI-A" for r in filtered)
        store.close()

    def test_list_none_client_id_returns_all(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        repo.save_workflow_result(_make_workflow_result(client_id="CLI-A"))
        repo.save_workflow_result(_make_workflow_result(client_id="CLI-B"))
        assert len(repo.list_workflow_results(client_id=None)) == 2
        store.close()

    def test_payload_uses_to_dict(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        result = _make_workflow_result(client_id="CLI-001")
        rec = repo.save_workflow_result(result)
        retrieved = repo.get_workflow_result(rec.record_id)
        assert isinstance(retrieved.payload, dict)
        assert "client_id" in retrieved.payload
        store.close()

    def test_metadata_includes_client_id(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_workflow_result(_make_workflow_result(client_id="CLI-META"))
        retrieved = repo.get_workflow_result(rec.record_id)
        assert retrieved.metadata["client_id"] == "CLI-META"
        store.close()

    def test_payload_json_round_trips_as_dict(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_workflow_result(_make_workflow_result())
        retrieved = repo.get_workflow_result(rec.record_id)
        # payload debe ser un dict, no una cadena
        assert isinstance(retrieved.payload, dict)
        # metadata también
        assert isinstance(retrieved.metadata, dict)
        store.close()

    def test_ids_continue_after_close_and_reopen(self, tmp_path: Path):
        db_path = tmp_path / "persist.db"

        # Primera sesión: guardar 2 registros
        store1 = _open_store(db_path)
        repo1 = SQLiteWorkflowRunRepository(store1)
        r1 = repo1.save_workflow_result(_make_workflow_result())
        r2 = repo1.save_workflow_result(_make_workflow_result())
        assert r1.record_id == "workflow_000001"
        assert r2.record_id == "workflow_000002"
        store1.close()

        # Segunda sesión: el contador debe continuar desde 3
        store2 = _open_store(db_path)
        repo2 = SQLiteWorkflowRunRepository(store2)
        r3 = repo2.save_workflow_result(_make_workflow_result())
        assert r3.record_id == "workflow_000003"
        store2.close()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: SQLiteAuditRepository
# ─────────────────────────────────────────────────────────────────────────────


class TestSQLiteAuditRepository:
    def _setup(self, tmp_path: Path):
        store = _open_store(tmp_path / "test.db")
        repo = SQLiteAuditRepository(store)
        return store, repo

    def test_save_returns_stored_record(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_audit_trail(_make_audit())
        assert isinstance(rec, StoredRecord)
        store.close()

    def test_record_type_is_audit_trail(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_audit_trail(_make_audit())
        assert rec.record_type == "audit_trail"
        store.close()

    def test_record_id_has_audit_prefix(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_audit_trail(_make_audit())
        assert rec.record_id.startswith("audit_")
        store.close()

    def test_record_id_is_zero_padded_sequential(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        r1 = repo.save_audit_trail(_make_audit())
        r2 = repo.save_audit_trail(_make_audit())
        assert r1.record_id == "audit_000001"
        assert r2.record_id == "audit_000002"
        store.close()

    def test_get_audit_trail_retrieves(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        saved = repo.save_audit_trail(_make_audit(session_id="SES-XYZ"))
        retrieved = repo.get_audit_trail(saved.record_id)
        assert retrieved.payload["session_id"] == "SES-XYZ"
        store.close()

    def test_get_nonexistent_raises_record_not_found(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        with pytest.raises(RecordNotFoundError):
            repo.get_audit_trail("audit_999999")
        store.close()

    def test_payload_uses_to_dict(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        audit = _make_audit(client_id="CLI-001", session_id="SES-001")
        rec = repo.save_audit_trail(audit)
        retrieved = repo.get_audit_trail(rec.record_id)
        assert retrieved.payload["client_id"] == "CLI-001"
        assert "events" in retrieved.payload
        store.close()

    def test_metadata_includes_client_id_and_session_id(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_audit_trail(_make_audit(client_id="CLI-A", session_id="SES-A"))
        retrieved = repo.get_audit_trail(rec.record_id)
        assert retrieved.metadata["client_id"] == "CLI-A"
        assert retrieved.metadata["session_id"] == "SES-A"
        store.close()

    def test_list_audit_trails_filters_by_client_id(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        repo.save_audit_trail(_make_audit(client_id="CLI-A"))
        repo.save_audit_trail(_make_audit(client_id="CLI-B"))
        repo.save_audit_trail(_make_audit(client_id="CLI-A"))
        result = repo.list_audit_trails(client_id="CLI-A")
        assert len(result) == 2
        assert all(r.metadata["client_id"] == "CLI-A" for r in result)
        store.close()

    def test_list_preserves_insertion_order(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        r1 = repo.save_audit_trail(_make_audit(session_id="SES-1"))
        r2 = repo.save_audit_trail(_make_audit(session_id="SES-2"))
        ids = [r.record_id for r in repo.list_audit_trails()]
        assert ids == [r1.record_id, r2.record_id]
        store.close()

    def test_audit_counter_independent_of_workflow_counter(self, tmp_path: Path):
        store = _open_store(tmp_path / "test.db")
        w_repo = SQLiteWorkflowRunRepository(store)
        a_repo = SQLiteAuditRepository(store)
        w_repo.save_workflow_result(_make_workflow_result())
        r = a_repo.save_audit_trail(_make_audit())
        # El contador de audit_ empieza en 1 independiente de workflow_
        assert r.record_id == "audit_000001"
        store.close()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: SQLiteReportRepository
# ─────────────────────────────────────────────────────────────────────────────


class TestSQLiteReportRepository:
    def _setup(self, tmp_path: Path):
        store = _open_store(tmp_path / "test.db")
        repo = SQLiteReportRepository(store)
        return store, repo

    def test_save_returns_stored_record(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_report(_make_report())
        assert isinstance(rec, StoredRecord)
        store.close()

    def test_record_type_is_markdown_report(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_report(_make_report())
        assert rec.record_type == "markdown_report"
        store.close()

    def test_record_id_has_report_prefix(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_report(_make_report())
        assert rec.record_id.startswith("report_")
        store.close()

    def test_record_id_is_zero_padded_sequential(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        r1 = repo.save_report(_make_report())
        r2 = repo.save_report(_make_report())
        assert r1.record_id == "report_000001"
        assert r2.record_id == "report_000002"
        store.close()

    def test_get_report_retrieves(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        saved = repo.save_report(_make_report(client_id="CLI-RPT"))
        retrieved = repo.get_report(saved.record_id)
        assert retrieved.payload["client_id"] == "CLI-RPT"
        assert retrieved.payload["title"] == "Integration Test Report"
        store.close()

    def test_get_nonexistent_raises_record_not_found(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        with pytest.raises(RecordNotFoundError):
            repo.get_report("report_999999")
        store.close()

    def test_payload_uses_to_dict(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_report(_make_report())
        retrieved = repo.get_report(rec.record_id)
        assert "content" in retrieved.payload
        assert "title" in retrieved.payload
        store.close()

    def test_metadata_includes_client_id_and_title(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_report(_make_report(client_id="CLI-M"))
        retrieved = repo.get_report(rec.record_id)
        assert retrieved.metadata["client_id"] == "CLI-M"
        assert retrieved.metadata["title"] == "Integration Test Report"
        store.close()

    def test_list_reports_filters_by_client_id(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        repo.save_report(_make_report(client_id="CLI-A"))
        repo.save_report(_make_report(client_id="CLI-B"))
        repo.save_report(_make_report(client_id="CLI-A"))
        result = repo.list_reports(client_id="CLI-A")
        assert len(result) == 2
        assert all(r.metadata["client_id"] == "CLI-A" for r in result)
        store.close()

    def test_list_none_returns_all(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        repo.save_report(_make_report(client_id="CLI-A"))
        repo.save_report(_make_report(client_id="CLI-B"))
        assert len(repo.list_reports()) == 2
        store.close()

    def test_list_preserves_insertion_order(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        r1 = repo.save_report(_make_report(client_id="CLI-1"))
        r2 = repo.save_report(_make_report(client_id="CLI-2"))
        r3 = repo.save_report(_make_report(client_id="CLI-3"))
        ids = [r.record_id for r in repo.list_reports()]
        assert ids == [r1.record_id, r2.record_id, r3.record_id]
        store.close()

    def test_metadata_json_round_trips_as_dict(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_report(_make_report())
        retrieved = repo.get_report(rec.record_id)
        assert isinstance(retrieved.metadata, dict)
        assert isinstance(retrieved.payload, dict)
        store.close()

    def test_stored_record_to_dict_is_json_serializable(self, tmp_path: Path):
        store, repo = self._setup(tmp_path)
        rec = repo.save_report(_make_report())
        retrieved = repo.get_report(rec.record_id)
        payload = json.dumps(retrieved.to_dict())
        parsed = json.loads(payload)
        assert parsed["record_type"] == "markdown_report"
        store.close()

    def test_report_ids_continue_after_close_and_reopen(self, tmp_path: Path):
        db_path = tmp_path / "persist.db"

        store1 = _open_store(db_path)
        repo1 = SQLiteReportRepository(store1)
        repo1.save_report(_make_report())
        repo1.save_report(_make_report())
        store1.close()

        store2 = _open_store(db_path)
        repo2 = SQLiteReportRepository(store2)
        r3 = repo2.save_report(_make_report())
        assert r3.record_id == "report_000003"
        store2.close()

    def test_three_repos_share_store_without_conflict(self, tmp_path: Path):
        store = _open_store(tmp_path / "test.db")
        w_repo = SQLiteWorkflowRunRepository(store)
        a_repo = SQLiteAuditRepository(store)
        r_repo = SQLiteReportRepository(store)

        w = w_repo.save_workflow_result(_make_workflow_result())
        a = a_repo.save_audit_trail(_make_audit())
        r = r_repo.save_report(_make_report())

        assert w.record_id == "workflow_000001"
        assert a.record_id == "audit_000001"
        assert r.record_id == "report_000001"

        # Todos persisten en la misma tabla records
        all_w = w_repo.list_workflow_results()
        all_a = a_repo.list_audit_trails()
        all_r = r_repo.list_reports()
        assert len(all_w) == 1
        assert len(all_a) == 1
        assert len(all_r) == 1
        store.close()
