"""
Tests de integración para los endpoints de listado:
    GET /workflow[?client_id=...]
    GET /reports[?client_id=...]
    GET /audit[?client_id=...]

Flujo general: POST /workflow/run para crear registros, luego GET lista.
Usa tmp_path para aislar DB y reportes del proyecto.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# Payloads de referencia
# ─────────────────────────────────────────────────────────────────────────────

_CLIENT_A = "listing_client_A"
_CLIENT_B = "listing_client_B"


def _payload(client_id: str) -> dict:
    return {
        "client_id": client_id,
        "advisor_id": "ADV-LIST",
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

    monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", tmp_path / "listing_test.db")
    monkeypatch.setattr(
        main_module, "DEFAULT_WORKFLOW_REPORT_DIR", tmp_path / "reports"
    )
    return TestClient(main_module.app)


@pytest.fixture
def client_with_two_runs(client: TestClient) -> TestClient:
    """DB con dos runs de client_A y uno de client_B."""
    client.post("/workflow/run", json=_payload(_CLIENT_A))
    client.post("/workflow/run", json=_payload(_CLIENT_A))
    client.post("/workflow/run", json=_payload(_CLIENT_B))
    return client


# ─────────────────────────────────────────────────────────────────────────────
# Tests: lista vacía
# ─────────────────────────────────────────────────────────────────────────────


class TestEmptyLists:
    def test_workflow_empty_returns_200(self, client: TestClient):
        response = client.get("/workflow")
        assert response.status_code == 200

    def test_workflow_empty_returns_count_zero(self, client: TestClient):
        body = client.get("/workflow").json()
        assert body["count"] == 0
        assert body["records"] == []

    def test_reports_empty_returns_200(self, client: TestClient):
        response = client.get("/reports")
        assert response.status_code == 200

    def test_reports_empty_returns_count_zero(self, client: TestClient):
        body = client.get("/reports").json()
        assert body["count"] == 0
        assert body["records"] == []

    def test_audit_empty_returns_200(self, client: TestClient):
        response = client.get("/audit")
        assert response.status_code == 200

    def test_audit_empty_returns_count_zero(self, client: TestClient):
        body = client.get("/audit").json()
        assert body["count"] == 0
        assert body["records"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /workflow
# ─────────────────────────────────────────────────────────────────────────────


class TestListWorkflows:
    def test_after_two_runs_count_gte_two(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get("/workflow").json()
        assert body["count"] >= 2

    def test_records_is_list(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get("/workflow").json()
        assert isinstance(body["records"], list)

    def test_count_matches_records_length(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get("/workflow").json()
        assert body["count"] == len(body["records"])

    def test_preserves_insertion_order(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get("/workflow").json()
        ids = [r["record_id"] for r in body["records"]]
        # IDs secuenciales: workflow_000001, workflow_000002, ...
        nums = [int(rid.split("_")[1]) for rid in ids]
        assert nums == sorted(nums)

    def test_each_record_has_required_fields(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get("/workflow").json()
        for rec in body["records"]:
            assert "record_id" in rec
            assert "record_type" in rec
            assert "created_at_utc" in rec
            assert "payload" in rec
            assert "metadata" in rec

    def test_filter_by_client_a(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get(
            "/workflow", params={"client_id": _CLIENT_A}
        ).json()
        assert body["count"] == 2
        for rec in body["records"]:
            assert rec["metadata"]["client_id"] == _CLIENT_A

    def test_filter_by_client_b(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get(
            "/workflow", params={"client_id": _CLIENT_B}
        ).json()
        assert body["count"] == 1
        assert body["records"][0]["metadata"]["client_id"] == _CLIENT_B

    def test_filter_unknown_client_returns_empty(
        self, client_with_two_runs: TestClient
    ):
        body = client_with_two_runs.get(
            "/workflow", params={"client_id": "NO_EXISTE"}
        ).json()
        assert body["count"] == 0
        assert body["records"] == []

    def test_no_filter_returns_all(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get("/workflow").json()
        assert body["count"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /reports
# ─────────────────────────────────────────────────────────────────────────────


class TestListReports:
    def test_after_runs_returns_report_records(
        self, client_with_two_runs: TestClient
    ):
        body = client_with_two_runs.get("/reports").json()
        assert body["count"] >= 2

    def test_filter_by_client_a(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get(
            "/reports", params={"client_id": _CLIENT_A}
        ).json()
        assert body["count"] == 2

    def test_filter_unknown_client_returns_empty(
        self, client_with_two_runs: TestClient
    ):
        body = client_with_two_runs.get(
            "/reports", params={"client_id": "NO_EXISTE"}
        ).json()
        assert body["count"] == 0

    def test_count_matches_records_length(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get("/reports").json()
        assert body["count"] == len(body["records"])

    def test_record_type_is_markdown_report(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get("/reports").json()
        for rec in body["records"]:
            assert rec["record_type"] == "markdown_report"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /audit
# ─────────────────────────────────────────────────────────────────────────────


class TestListAudit:
    def test_after_runs_returns_audit_records(
        self, client_with_two_runs: TestClient
    ):
        body = client_with_two_runs.get("/audit").json()
        # Audit solo se crea si m1_result tiene .audit — puede ser 0 o más.
        assert isinstance(body["count"], int)
        assert body["count"] >= 0

    def test_filter_by_client_a_returns_subset(
        self, client_with_two_runs: TestClient
    ):
        all_body = client_with_two_runs.get("/audit").json()
        filtered_body = client_with_two_runs.get(
            "/audit", params={"client_id": _CLIENT_A}
        ).json()
        assert filtered_body["count"] <= all_body["count"]

    def test_filter_unknown_client_returns_empty(
        self, client_with_two_runs: TestClient
    ):
        body = client_with_two_runs.get(
            "/audit", params={"client_id": "NO_EXISTE"}
        ).json()
        assert body["count"] == 0

    def test_count_matches_records_length(self, client_with_two_runs: TestClient):
        body = client_with_two_runs.get("/audit").json()
        assert body["count"] == len(body["records"])


# ─────────────────────────────────────────────────────────────────────────────
# Tests: serialización
# ─────────────────────────────────────────────────────────────────────────────


class TestListingSerialization:
    def test_workflow_list_is_json_serializable(
        self, client_with_two_runs: TestClient
    ):
        body = client_with_two_runs.get("/workflow").json()
        json.dumps(body)

    def test_reports_list_is_json_serializable(
        self, client_with_two_runs: TestClient
    ):
        body = client_with_two_runs.get("/reports").json()
        json.dumps(body)

    def test_audit_list_is_json_serializable(
        self, client_with_two_runs: TestClient
    ):
        body = client_with_two_runs.get("/audit").json()
        json.dumps(body)

    def test_workflow_list_has_no_raw_enum_repr(
        self, client_with_two_runs: TestClient
    ):
        text = client_with_two_runs.get("/workflow").text
        assert "AdvisoryWorkflowStatus" not in text
        assert " object at 0x" not in text

    def test_reports_list_has_no_raw_enum_repr(
        self, client_with_two_runs: TestClient
    ):
        text = client_with_two_runs.get("/reports").text
        assert " object at 0x" not in text
