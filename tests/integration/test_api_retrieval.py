"""
Tests de integración para los endpoints de recuperación de registros:
    GET /workflow/{record_id}
    GET /reports/{record_id}
    GET /audit/{record_id}

Flujo general: primero POST /workflow/run para crear registros, luego GET.
Usa tmp_path para aislar DB y reportes del proyecto.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ─────────────────────────────────────────────────────────────────────────────
# Payload de referencia
# ─────────────────────────────────────────────────────────────────────────────

_PAYLOAD: dict = {
    "client_id": "retrieval_client_01",
    "advisor_id": "ADV-RETRIEVAL",
    "kyc_data": {
        "risk_tolerance_score": 6,
        "risk_capacity_score": 7,
        "liquidity_need_score": 3,
        "investment_horizon_years": 10,
        "investment_experience": "moderada",
        "income_stability": "stable",
        "net_worth": 500_000.0,
        "liquid_net_worth": 200_000.0,
        "max_acceptable_drawdown_pct": 25.0,
    },
    "financial_goal": {
        "initial_amount": 100_000.0,
        "target_amount": 200_000.0,
        "horizon_years": 10,
        "annual_contribution": 5_000.0,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import risk_first_advisory.api_layer.main as main_module

    monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", tmp_path / "retrieval_test.db")
    monkeypatch.setattr(
        main_module, "DEFAULT_WORKFLOW_REPORT_DIR", tmp_path / "reports"
    )
    return TestClient(main_module.app)


@pytest.fixture
def run_records(client: TestClient) -> dict:
    """Ejecuta POST /workflow/run y devuelve el campo 'records' de la respuesta."""
    response = client.post("/workflow/run", json=_PAYLOAD)
    assert response.status_code == 200, response.text
    return response.json()["records"]


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /workflow/{record_id}
# ─────────────────────────────────────────────────────────────────────────────


class TestGetWorkflow:
    def test_returns_200_after_run(self, client: TestClient, run_records: dict):
        wid = run_records["workflow_record_id"]
        response = client.get(f"/workflow/{wid}")
        assert response.status_code == 200

    def test_payload_contains_client_id(self, client: TestClient, run_records: dict):
        wid = run_records["workflow_record_id"]
        body = client.get(f"/workflow/{wid}").json()
        assert body["payload"]["client_id"] == _PAYLOAD["client_id"]

    def test_metadata_contains_client_id(self, client: TestClient, run_records: dict):
        wid = run_records["workflow_record_id"]
        body = client.get(f"/workflow/{wid}").json()
        assert body["metadata"]["client_id"] == _PAYLOAD["client_id"]

    def test_record_id_matches(self, client: TestClient, run_records: dict):
        wid = run_records["workflow_record_id"]
        body = client.get(f"/workflow/{wid}").json()
        assert body["record_id"] == wid

    def test_record_type_is_workflow(self, client: TestClient, run_records: dict):
        wid = run_records["workflow_record_id"]
        body = client.get(f"/workflow/{wid}").json()
        assert body["record_type"] == "workflow_run"

    def test_created_at_utc_is_string(self, client: TestClient, run_records: dict):
        wid = run_records["workflow_record_id"]
        body = client.get(f"/workflow/{wid}").json()
        assert isinstance(body["created_at_utc"], str)
        assert body["created_at_utc"]

    def test_nonexistent_workflow_returns_404(self, client: TestClient):
        response = client.get("/workflow/workflow_999999")
        assert response.status_code == 404

    def test_404_detail_is_record_not_found(self, client: TestClient):
        body = client.get("/workflow/workflow_999999").json()
        assert body["detail"] == "Record not found"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /reports/{record_id}
# ─────────────────────────────────────────────────────────────────────────────


class TestGetReport:
    def test_returns_200_after_run(self, client: TestClient, run_records: dict):
        rid = run_records["report_record_id"]
        response = client.get(f"/reports/{rid}")
        assert response.status_code == 200

    def test_record_id_matches(self, client: TestClient, run_records: dict):
        rid = run_records["report_record_id"]
        body = client.get(f"/reports/{rid}").json()
        assert body["record_id"] == rid

    def test_payload_contains_title_or_content(
        self, client: TestClient, run_records: dict
    ):
        rid = run_records["report_record_id"]
        body = client.get(f"/reports/{rid}").json()
        payload = body["payload"]
        assert "title" in payload or "content" in payload

    def test_payload_content_has_report_header(
        self, client: TestClient, run_records: dict
    ):
        rid = run_records["report_record_id"]
        body = client.get(f"/reports/{rid}").json()
        content = body["payload"].get("content", "")
        assert "Risk-First Advisory Report" in content

    def test_record_type_is_report(self, client: TestClient, run_records: dict):
        rid = run_records["report_record_id"]
        body = client.get(f"/reports/{rid}").json()
        assert body["record_type"] == "markdown_report"

    def test_nonexistent_report_returns_404(self, client: TestClient):
        response = client.get("/reports/report_999999")
        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /audit/{record_id}
# ─────────────────────────────────────────────────────────────────────────────


class TestGetAudit:
    def test_returns_200_when_audit_exists(self, client: TestClient, run_records: dict):
        audit_id = run_records.get("audit_record_id")
        if audit_id is None:
            pytest.skip("No hay audit_record_id en esta ejecución.")
        response = client.get(f"/audit/{audit_id}")
        assert response.status_code == 200

    def test_audit_payload_contains_session_or_events(
        self, client: TestClient, run_records: dict
    ):
        audit_id = run_records.get("audit_record_id")
        if audit_id is None:
            pytest.skip("No hay audit_record_id en esta ejecución.")
        body = client.get(f"/audit/{audit_id}").json()
        payload = body["payload"]
        has_session = "session_id" in payload
        has_events = "events" in payload
        assert has_session or has_events

    def test_record_id_matches(self, client: TestClient, run_records: dict):
        audit_id = run_records.get("audit_record_id")
        if audit_id is None:
            pytest.skip("No hay audit_record_id en esta ejecución.")
        body = client.get(f"/audit/{audit_id}").json()
        assert body["record_id"] == audit_id

    def test_record_type_is_audit(self, client: TestClient, run_records: dict):
        audit_id = run_records.get("audit_record_id")
        if audit_id is None:
            pytest.skip("No hay audit_record_id en esta ejecución.")
        body = client.get(f"/audit/{audit_id}").json()
        assert body["record_type"] == "audit_trail"

    def test_nonexistent_audit_returns_404(self, client: TestClient):
        response = client.get("/audit/audit_999999")
        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Tests: serialización
# ─────────────────────────────────────────────────────────────────────────────


class TestRetrievalSerialization:
    def test_workflow_response_is_json_serializable(
        self, client: TestClient, run_records: dict
    ):
        wid = run_records["workflow_record_id"]
        body = client.get(f"/workflow/{wid}").json()
        json.dumps(body)

    def test_report_response_is_json_serializable(
        self, client: TestClient, run_records: dict
    ):
        rid = run_records["report_record_id"]
        body = client.get(f"/reports/{rid}").json()
        json.dumps(body)

    def test_workflow_response_has_no_raw_enum_repr(
        self, client: TestClient, run_records: dict
    ):
        wid = run_records["workflow_record_id"]
        serialized = client.get(f"/workflow/{wid}").text
        # Sin class-name de enum ni repr de objetos Python.
        assert "AdvisoryWorkflowStatus" not in serialized
        assert "PortfolioFeasibilityStatus" not in serialized
        # El payload almacenado puede contener '<' en textos de notas,
        # pero no debe contener repr de objetos Python como "<ClassName object at 0x...>".
        assert " object at 0x" not in serialized

    def test_report_response_has_no_raw_enum_repr(
        self, client: TestClient, run_records: dict
    ):
        rid = run_records["report_record_id"]
        serialized = client.get(f"/reports/{rid}").text
        assert "<" not in serialized


# ─────────────────────────────────────────────────────────────────────────────
# Tests: demo/run también persiste recuperables
# ─────────────────────────────────────────────────────────────────────────────


class TestDemoRunRecordsRetrievable:
    """Verifica que los registros de /demo/run también se recuperan vía GET."""

    @pytest.fixture
    def demo_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> TestClient:
        import risk_first_advisory.api_layer.main as main_module

        monkeypatch.setattr(
            main_module, "DEFAULT_DB_PATH", tmp_path / "demo_retrieval.db"
        )
        monkeypatch.setattr(
            main_module, "DEFAULT_REPORT_PATH", tmp_path / "demo_report.md"
        )
        monkeypatch.setattr(
            main_module, "DEFAULT_WORKFLOW_REPORT_DIR", tmp_path / "reports"
        )
        return TestClient(main_module.app)

    def test_demo_workflow_record_retrievable(self, demo_client: TestClient):
        run_resp = demo_client.post("/demo/run").json()
        wid = run_resp["records"]["workflow_record_id"]
        get_resp = demo_client.get(f"/workflow/{wid}")
        assert get_resp.status_code == 200
        assert get_resp.json()["record_id"] == wid

    def test_demo_report_record_retrievable(self, demo_client: TestClient):
        run_resp = demo_client.post("/demo/run").json()
        rid = run_resp["records"]["report_record_id"]
        get_resp = demo_client.get(f"/reports/{rid}")
        assert get_resp.status_code == 200
        assert get_resp.json()["record_id"] == rid
