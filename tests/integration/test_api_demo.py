"""
Tests de integración para la API demo de risk-first-advisory.

Usa TestClient (síncrono) de FastAPI.
Monkeypatcha DEFAULT_DB_PATH y DEFAULT_REPORT_PATH para que los tests
no toquen data/demo_api.db ni reports/demo_api_report.md del proyecto.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """
    TestClient con rutas de DB y reporte apuntando a tmp_path.

    El monkeypatch se aplica ANTES de cada request para que el endpoint
    lea DEFAULT_DB_PATH y DEFAULT_REPORT_PATH ya parcheados.
    """
    import risk_first_advisory.api_layer.main as main_module

    monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", tmp_path / "api_test.db")
    monkeypatch.setattr(main_module, "DEFAULT_REPORT_PATH", tmp_path / "api_test_report.md")
    return TestClient(main_module.app)


@pytest.fixture
def demo_response(client: TestClient) -> dict:
    """Ejecuta POST /demo/run una vez y cachea la respuesta."""
    response = client.post("/demo/run")
    assert response.status_code == 200, response.text
    return response.json()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /health
# ─────────────────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_returns_200(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_status_ok(self, client: TestClient):
        response = client.get("/health")
        assert response.json()["status"] == "ok"

    def test_health_returns_service_name(self, client: TestClient):
        response = client.get("/health")
        assert response.json()["service"] == "risk-first-advisory"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: POST /demo/run — campos de respuesta
# ─────────────────────────────────────────────────────────────────────────────


class TestDemoRunResponse:
    def test_returns_200(self, client: TestClient):
        response = client.post("/demo/run")
        assert response.status_code == 200

    def test_returns_client_id(self, demo_response: dict):
        assert "client_id" in demo_response
        assert demo_response["client_id"]  # no vacío

    def test_returns_status_string(self, demo_response: dict):
        assert "status" in demo_response
        assert isinstance(demo_response["status"], str)
        assert demo_response["status"]

    def test_returns_approved_profile_name(self, demo_response: dict):
        assert "approved_profile_name" in demo_response
        assert demo_response["approved_profile_name"]

    def test_returns_has_portfolios_bool(self, demo_response: dict):
        assert "has_portfolios" in demo_response
        assert isinstance(demo_response["has_portfolios"], bool)

    def test_returns_reason_codes_as_list(self, demo_response: dict):
        assert "reason_codes" in demo_response
        assert isinstance(demo_response["reason_codes"], list)
        # Todos los elementos son strings (no Enum crudos).
        for rc in demo_response["reason_codes"]:
            assert isinstance(rc, str)

    def test_returns_warnings_as_list(self, demo_response: dict):
        assert isinstance(demo_response["warnings"], list)

    def test_returns_final_optimizer_tickers_as_list(self, demo_response: dict):
        assert "final_optimizer_tickers" in demo_response
        assert isinstance(demo_response["final_optimizer_tickers"], list)

    def test_returns_candidate_count_int(self, demo_response: dict):
        assert "candidate_count" in demo_response
        assert isinstance(demo_response["candidate_count"], int)

    def test_returns_report_path_string(self, demo_response: dict):
        assert "report_path" in demo_response
        assert isinstance(demo_response["report_path"], str)
        assert demo_response["report_path"]

    def test_portfolio_feasibility_status_is_string_or_none(self, demo_response: dict):
        pf_status = demo_response.get("portfolio_feasibility_status")
        assert pf_status is None or isinstance(pf_status, str)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: POST /demo/run — records de persistencia
# ─────────────────────────────────────────────────────────────────────────────


class TestDemoRunRecords:
    def test_returns_records_object(self, demo_response: dict):
        assert "records" in demo_response
        assert isinstance(demo_response["records"], dict)

    def test_records_has_workflow_record_id(self, demo_response: dict):
        records = demo_response["records"]
        assert "workflow_record_id" in records
        assert records["workflow_record_id"].startswith("workflow_")

    def test_records_has_report_record_id(self, demo_response: dict):
        records = demo_response["records"]
        assert "report_record_id" in records
        assert records["report_record_id"].startswith("report_")

    def test_audit_record_id_is_string_or_none(self, demo_response: dict):
        audit_id = demo_response["records"].get("audit_record_id")
        assert audit_id is None or (isinstance(audit_id, str) and audit_id.startswith("audit_"))


# ─────────────────────────────────────────────────────────────────────────────
# Tests: POST /demo/run — persistencia real en SQLite
# ─────────────────────────────────────────────────────────────────────────────


class TestDemoRunPersistence:
    def test_sqlite_db_is_created(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import risk_first_advisory.api_layer.main as main_module

        db_path = tmp_path / "check.db"
        monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", db_path)
        monkeypatch.setattr(main_module, "DEFAULT_REPORT_PATH", tmp_path / "r.md")

        client = TestClient(main_module.app)
        response = client.post("/demo/run")
        assert response.status_code == 200
        assert db_path.exists()

    def test_workflow_record_retrievable_from_sqlite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLitePersistenceStore,
            SQLiteWorkflowRunRepository,
        )

        db_path = tmp_path / "verify.db"
        monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", db_path)
        monkeypatch.setattr(main_module, "DEFAULT_REPORT_PATH", tmp_path / "r.md")

        client = TestClient(main_module.app)
        data = client.post("/demo/run").json()

        workflow_id = data["records"]["workflow_record_id"]
        with SQLitePersistenceStore(db_path) as store:
            store.init_schema()
            rec = SQLiteWorkflowRunRepository(store).get_workflow_result(workflow_id)
        assert rec.record_id == workflow_id

    def test_report_file_is_created(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import risk_first_advisory.api_layer.main as main_module

        report_path = tmp_path / "sub" / "api_report.md"
        monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", tmp_path / "a.db")
        monkeypatch.setattr(main_module, "DEFAULT_REPORT_PATH", report_path)

        client = TestClient(main_module.app)
        client.post("/demo/run")
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "# Risk-First Advisory Report" in content

    def test_two_runs_generate_distinct_ids(self, client: TestClient):
        r1 = client.post("/demo/run").json()
        r2 = client.post("/demo/run").json()
        assert r1["records"]["workflow_record_id"] != r2["records"]["workflow_record_id"]
        assert r1["records"]["report_record_id"] != r2["records"]["report_record_id"]

    def test_second_run_increments_workflow_id(self, client: TestClient):
        r1 = client.post("/demo/run").json()
        r2 = client.post("/demo/run").json()
        # IDs secuenciales: workflow_000001, workflow_000002
        n1 = int(r1["records"]["workflow_record_id"].split("_")[1])
        n2 = int(r2["records"]["workflow_record_id"].split("_")[1])
        assert n2 == n1 + 1


# ─────────────────────────────────────────────────────────────────────────────
# Tests: serialización
# ─────────────────────────────────────────────────────────────────────────────


class TestDemoRunSerialization:
    def test_response_is_json_serializable(self, demo_response: dict):
        # No debe lanzar.
        json.dumps(demo_response)

    def test_response_has_no_raw_enum_repr(self, demo_response: dict):
        serialized = json.dumps(demo_response)
        assert "AdvisoryWorkflowStatus" not in serialized
        assert "PortfolioFeasibilityStatus" not in serialized
        # Sin representaciones de objetos Python crudos.
        assert "<" not in serialized

    def test_status_is_lowercase_value(self, demo_response: dict):
        # El status debe ser el .value del enum (snake_case), no el nombre.
        status = demo_response["status"]
        assert status == status.lower() or "_" in status
        assert "AdvisoryWorkflowStatus" not in status

    def test_all_list_fields_contain_only_strings(self, demo_response: dict):
        for field in ("reason_codes", "warnings", "final_optimizer_tickers"):
            for item in demo_response[field]:
                assert isinstance(item, str), f"{field} contiene no-string: {item!r}"
