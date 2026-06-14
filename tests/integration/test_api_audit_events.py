"""
Integration tests for Phase 2 AuditEvent endpoints (hash chain por case).

Cubre:
    POST  /cases                        — verifica que se genera audit event automático.
    POST  /cases/{case_id}/audit-events — advisor/admin agrega evento manual.
    GET   /cases/{case_id}/audit        — lista en orden de sequence.
    GET   /cases/{case_id}/audit/verify — recomputa hashes y valida cadena.

Manipulación directa de DB para forzar verify=false:
    - mutar payload_json   → payload_hash mismatch
    - mutar previous_hash  → encadenamiento roto
    - borrar evento medio  → gap de sequence

No usa OpenAI. No escribe en data/demo_api.db (monkeypatch de DEFAULT_DB_PATH).
La migración 0001 se aplica a la DB temporal antes de cada test.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import risk_first_advisory.api_layer.main as _main_module
import risk_first_advisory.config_layer.advisor_tokens as _tokens_module
from risk_first_advisory.persistence_layer.entity_repository import (
    compute_event_hash,
    compute_payload_hash,
)

# ─────────────────────────────────────────────────────────────────────────────
# Import migrate module (no es paquete — importlib)
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS_DIR = _PROJECT_ROOT / "migrations"
_MIGRATE_PATH = _PROJECT_ROOT / "scripts" / "migrate.py"

_spec = importlib.util.spec_from_file_location("rfa_migrate", _MIGRATE_PATH)
_migrate_module = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules.setdefault("rfa_migrate", _migrate_module)
_spec.loader.exec_module(_migrate_module)  # type: ignore[union-attr]
migrate = _migrate_module


# ─────────────────────────────────────────────────────────────────────────────
# Tokens — 4 roles
# ─────────────────────────────────────────────────────────────────────────────

_AUDIT_TEST_TOKENS_YAML = """\
tokens:
  test-admin-token:
    advisor_id: ADM-AUD-001
    display_name: Test Admin
    firm_id: null
    roles:
      - admin
  test-advisor-token:
    advisor_id: ADV-AUD-001
    display_name: Test Advisor
    firm_id: null
    roles:
      - advisor
  test-compliance-token:
    advisor_id: CMP-AUD-001
    display_name: Test Compliance
    firm_id: null
    roles:
      - compliance
  test-viewer-token:
    advisor_id: VWR-AUD-001
    display_name: Test Viewer
    firm_id: null
    roles:
      - viewer
"""

_ADMIN = "Bearer test-admin-token"
_ADVISOR = "Bearer test-advisor-token"
_COMPLIANCE = "Bearer test-compliance-token"
_VIEWER = "Bearer test-viewer-token"
_RBAC_403_DETAIL = "Advisor role is not authorized for this action."


# ─────────────────────────────────────────────────────────────────────────────
# Autouse fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_audit_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, raising=False)
    monkeypatch.setattr(
        _tokens_module, "DEFAULT_ADVISOR_TOKENS_PATH", tmp_path / "absent.yaml"
    )
    tokens_yaml = tmp_path / "audit_tokens.yaml"
    tokens_yaml.write_text(_AUDIT_TEST_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def audit_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "audit_test.db"
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Payload helpers
# ─────────────────────────────────────────────────────────────────────────────


def _firm_body(**kw: Any) -> dict:
    return {"display_name": "Audit Firm", "country": "AR", **kw}


def _advisor_body(firm_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "display_name": "Audit Advisor",
        "email": "a@audit.com",
        "roles": ["advisor"],
        **kw,
    }


def _client_body(firm_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "primary_advisor_id": advisor_id,
        "display_name": "Audit Client",
        **kw,
    }


def _case_body(firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id":         firm_id,
        "client_id":       client_id,
        "lead_advisor_id": advisor_id,
        "title":           "Audit Case",
        **kw,
    }


def _create_firm(client: TestClient, **kw: Any) -> dict:
    r = client.post("/firms", json=_firm_body(**kw), headers={"Authorization": _ADMIN})
    assert r.status_code == 201, r.text
    return r.json()


def _create_advisor(client: TestClient, firm_id: str, **kw: Any) -> dict:
    r = client.post(
        "/advisors",
        json=_advisor_body(firm_id, **kw),
        headers={"Authorization": _ADMIN},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_client(client: TestClient, firm_id: str, advisor_id: str, **kw: Any) -> dict:
    r = client.post(
        "/clients",
        json=_client_body(firm_id, advisor_id, **kw),
        headers={"Authorization": _ADMIN},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_case(client: TestClient, firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    r = client.post(
        "/cases",
        json=_case_body(firm_id, client_id, advisor_id, **kw),
        headers={"Authorization": _ADVISOR},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _full_chain(
    client: TestClient,
    *,
    advisor_id: str = "ADV-AUD-001",
) -> dict:
    """
    Crea firm + advisor + client + case y devuelve el case dict.

    Por default, el advisor entity se crea con advisor_id=ADV-AUD-001
    (el mismo que el token de _ADVISOR), para que el audit event automático
    pueda registrar actor_advisor_id sin violar la FK
    audit_events.actor_advisor_id → advisors.advisor_id.
    """
    firm = _create_firm(client)
    adv = _create_advisor(client, firm["firm_id"], advisor_id=advisor_id)
    cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
    case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
    return case


def _open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# POST /cases auto-event
# ─────────────────────────────────────────────────────────────────────────────


class TestAutoCaseCreatedEvent:
    def test_post_cases_generates_initial_audit_event(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 1
        assert len(body["events"]) == 1

    def test_initial_event_has_sequence_1(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        )
        evt = r.json()["events"][0]
        assert evt["sequence"] == 1

    def test_initial_event_type_is_case_created(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        )
        evt = r.json()["events"][0]
        assert evt["event_type"] == "case_created"

    def test_initial_event_previous_hash_is_none(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        )
        evt = r.json()["events"][0]
        assert evt["previous_hash"] is None

    def test_initial_event_id_prefix(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        )
        evt = r.json()["events"][0]
        assert evt["event_id"].startswith("audit_event_")

    def test_initial_event_actor_role_is_advisor(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        )
        evt = r.json()["events"][0]
        assert evt["actor_role"] == "advisor"

    def test_initial_event_actor_advisor_id_from_token(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        )
        evt = r.json()["events"][0]
        assert evt["actor_advisor_id"] == "ADV-AUD-001"

    def test_initial_event_payload_contains_case_metadata(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        )
        payload = r.json()["events"][0]["payload"]
        assert payload["case_id"] == case["case_id"]
        assert payload["firm_id"] == case["firm_id"]
        assert payload["client_id"] == case["client_id"]
        assert payload["lead_advisor_id"] == case["lead_advisor_id"]
        assert payload["status"] == "DRAFT"
        assert payload["title"] == case["title"]

    def test_initial_event_payload_hash_matches_canonical(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        )
        evt = r.json()["events"][0]
        # Recompute payload_hash from response payload (round-trip).
        expected = compute_payload_hash(evt["payload"])
        assert evt["payload_hash"] == expected

    def test_admin_creating_case_uses_admin_actor_role(
        self, client: TestClient
    ) -> None:
        firm = _create_firm(client)
        # Register both the case's lead advisor AND the admin token's
        # advisor_id so the FK actor_advisor_id → advisors satisfies.
        adv = _create_advisor(client, firm["firm_id"])
        _create_advisor(
            client,
            firm["firm_id"],
            advisor_id="ADM-AUD-001",
            display_name="Admin As Advisor Entity",
            email="adm@audit.com",
            roles=["admin"],
        )
        cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
        r = client.post(
            "/cases",
            json=_case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"]),
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 201, r.text
        case = r.json()
        listing = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADMIN},
        )
        evt = listing.json()["events"][0]
        assert evt["actor_role"] == "admin"
        assert evt["actor_advisor_id"] == "ADM-AUD-001"


# ─────────────────────────────────────────────────────────────────────────────
# POST /cases/{case_id}/audit-events — happy
# ─────────────────────────────────────────────────────────────────────────────


class TestAppendAuditEvent:
    def test_append_creates_sequence_2(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={
                "event_type": "kyc_submitted",
                "actor_advisor_id": "ADV-AUD-001",
                "actor_role": "advisor",
                "payload": {"submission_id": "kyc_001"},
            },
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 201, r.text
        assert r.json()["sequence"] == 2

    def test_appended_event_previous_hash_equals_prior_event_hash(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        # event 1 (initial)
        first_resp = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()
        first_event_hash = first_resp["events"][0]["event_hash"]
        # append event 2
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={
                "event_type": "note",
                "actor_advisor_id": "ADV-AUD-001",
                "actor_role": "advisor",
                "payload": {"note": "hello"},
            },
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 201, r.text
        assert r.json()["previous_hash"] == first_event_hash

    def test_list_orders_by_sequence_asc(self, client: TestClient) -> None:
        case = _full_chain(client)
        for i in range(3):
            client.post(
                f"/cases/{case['case_id']}/audit-events",
                json={
                    "event_type": f"step_{i}",
                    "actor_advisor_id": "ADV-AUD-001",
                    "actor_role": "advisor",
                    "payload": {"step": i},
                },
                headers={"Authorization": _ADVISOR},
            )
        body = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()
        seqs = [e["sequence"] for e in body["events"]]
        assert seqs == [1, 2, 3, 4]
        assert body["count"] == 4

    def test_event_id_prefix_audit_event(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={
                "event_type": "x",
                "actor_role": "advisor",
                "payload": {},
            },
            headers={"Authorization": _ADVISOR},
        )
        assert r.json()["event_id"].startswith("audit_event_")

    def test_payload_round_trips_as_dict(self, client: TestClient) -> None:
        case = _full_chain(client)
        payload = {"nested": {"a": 1, "b": [1, 2, 3]}, "z": "ñ"}
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={
                "event_type": "complex",
                "actor_role": "advisor",
                "payload": payload,
            },
            headers={"Authorization": _ADVISOR},
        )
        assert r.json()["payload"] == payload

    def test_empty_payload_is_allowed(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={
                "event_type": "ping",
                "actor_role": "system",
                "payload": {},
            },
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 201
        assert r.json()["payload"] == {}


# ─────────────────────────────────────────────────────────────────────────────
# Hash determinism
# ─────────────────────────────────────────────────────────────────────────────


class TestHashDeterminism:
    def test_payload_hash_is_sha256_of_canonical_json(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={
                "event_type": "x",
                "actor_role": "advisor",
                "payload": {"a": 1, "b": 2},
            },
            headers={"Authorization": _ADVISOR},
        )
        evt = r.json()
        # canonical JSON: sort_keys, no whitespace
        canonical = json.dumps({"a": 1, "b": 2}, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert evt["payload_hash"] == expected

    def test_same_payload_different_key_order_yields_same_hash(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r1 = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": {"a": 1, "b": 2}},
            headers={"Authorization": _ADVISOR},
        )
        r2 = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": {"b": 2, "a": 1}},
            headers={"Authorization": _ADVISOR},
        )
        assert r1.json()["payload_hash"] == r2.json()["payload_hash"]

    def test_different_payloads_have_different_event_hashes(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r1 = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": {"a": 1}},
            headers={"Authorization": _ADVISOR},
        )
        r2 = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": {"a": 2}},
            headers={"Authorization": _ADVISOR},
        )
        assert r1.json()["event_hash"] != r2.json()["event_hash"]

    def test_event_hash_recomputable_from_metadata(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={
                "event_type":       "demo",
                "actor_advisor_id": "ADV-AUD-001",
                "actor_role":       "advisor",
                "payload":          {"k": "v"},
            },
            headers={"Authorization": _ADVISOR},
        )
        evt = r.json()
        recomputed = compute_event_hash(
            previous_hash=evt["previous_hash"],
            sequence=evt["sequence"],
            event_type=evt["event_type"],
            actor_advisor_id=evt["actor_advisor_id"],
            actor_role=evt["actor_role"],
            created_at_utc=evt["created_at_utc"],
            payload_hash=evt["payload_hash"],
        )
        assert recomputed == evt["event_hash"]


# ─────────────────────────────────────────────────────────────────────────────
# Verify endpoint
# ─────────────────────────────────────────────────────────────────────────────


class TestVerifyChain:
    def test_verify_intact_after_create(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_intact"] is True
        assert body["total_events"] == 1
        assert body["first_broken_sequence"] is None
        assert body["case_id"] == case["case_id"]

    def test_verify_intact_with_multiple_events(self, client: TestClient) -> None:
        case = _full_chain(client)
        for i in range(3):
            client.post(
                f"/cases/{case['case_id']}/audit-events",
                json={
                    "event_type": f"step_{i}",
                    "actor_role": "advisor",
                    "payload": {"step": i},
                },
                headers={"Authorization": _ADVISOR},
            )
        r = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _ADMIN},
        )
        body = r.json()
        assert body["is_intact"] is True
        assert body["total_events"] == 4

    def test_verify_detects_payload_tampering(
        self, client: TestClient, audit_db: Path
    ) -> None:
        case = _full_chain(client)
        # mutar payload_json directamente en DB
        with _open_db(audit_db) as conn:
            conn.execute(
                "UPDATE audit_events SET payload_json = ? WHERE case_id = ? AND sequence = 1",
                ('{"tampered":true}', case["case_id"]),
            )
            conn.commit()
        r = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _ADMIN},
        )
        body = r.json()
        assert body["is_intact"] is False
        assert body["first_broken_sequence"] == 1

    def test_verify_detects_previous_hash_tampering(
        self, client: TestClient, audit_db: Path
    ) -> None:
        case = _full_chain(client)
        # crear evento 2 para tener encadenamiento
        client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": {}},
            headers={"Authorization": _ADVISOR},
        )
        with _open_db(audit_db) as conn:
            conn.execute(
                "UPDATE audit_events SET previous_hash = ? WHERE case_id = ? AND sequence = 2",
                ("0" * 64, case["case_id"]),
            )
            conn.commit()
        r = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _ADMIN},
        )
        body = r.json()
        assert body["is_intact"] is False
        assert body["first_broken_sequence"] == 2

    def test_verify_detects_sequence_gap(
        self, client: TestClient, audit_db: Path
    ) -> None:
        case = _full_chain(client)
        for i in range(2):
            client.post(
                f"/cases/{case['case_id']}/audit-events",
                json={"event_type": f"x{i}", "actor_role": "advisor", "payload": {}},
                headers={"Authorization": _ADVISOR},
            )
        # ahora hay sequence 1, 2, 3. Borrar el 2 → gap.
        with _open_db(audit_db) as conn:
            conn.execute(
                "DELETE FROM audit_events WHERE case_id = ? AND sequence = 2",
                (case["case_id"],),
            )
            conn.commit()
        r = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _ADMIN},
        )
        body = r.json()
        assert body["is_intact"] is False
        # Después de borrar sequence 2, el segundo evento es sequence 3 → gap detectado.
        assert body["first_broken_sequence"] == 3

    def test_verify_first_broken_sequence_reported(
        self, client: TestClient, audit_db: Path
    ) -> None:
        case = _full_chain(client)
        with _open_db(audit_db) as conn:
            conn.execute(
                "UPDATE audit_events SET event_hash = ? WHERE case_id = ? AND sequence = 1",
                ("ff" * 32, case["case_id"]),
            )
            conn.commit()
        body = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _ADMIN},
        ).json()
        assert body["is_intact"] is False
        assert body["first_broken_sequence"] == 1

    def test_verify_response_has_checked_at_utc(self, client: TestClient) -> None:
        case = _full_chain(client)
        body = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _ADMIN},
        ).json()
        assert "checked_at_utc" in body
        assert body["checked_at_utc"].endswith("Z")


# ─────────────────────────────────────────────────────────────────────────────
# RBAC
# ─────────────────────────────────────────────────────────────────────────────


class TestRBACAppend:
    def test_no_token_returns_401(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": {}},
        )
        assert r.status_code == 401

    def test_compliance_returns_403(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": {}},
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == _RBAC_403_DETAIL

    def test_viewer_returns_403(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": {}},
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 403

    def test_advisor_returns_201(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": {}},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 201

    def test_admin_returns_201(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "admin", "payload": {}},
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 201


class TestRBACVerify:
    def test_advisor_returns_403(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 403

    def test_viewer_returns_403(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 403

    def test_compliance_returns_200(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 200

    def test_admin_returns_200(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 200

    def test_no_token_returns_401(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(f"/cases/{case['case_id']}/audit/verify")
        assert r.status_code == 401


class TestRBACList:
    def test_no_token_returns_401(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(f"/cases/{case['case_id']}/audit")
        assert r.status_code == 401

    def test_viewer_returns_200(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 200

    def test_compliance_returns_200(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 200

    def test_advisor_returns_200(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200

    def test_admin_returns_200(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────


class TestValidation:
    def test_missing_case_for_list_returns_404(self, client: TestClient) -> None:
        r = client.get(
            "/cases/case_nope/audit",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 404

    def test_missing_case_for_post_returns_404(self, client: TestClient) -> None:
        r = client.post(
            "/cases/case_nope/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": {}},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 404

    def test_missing_case_for_verify_returns_404(self, client: TestClient) -> None:
        r = client.get(
            "/cases/case_nope/audit/verify",
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 404

    def test_empty_event_type_returns_422(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "", "actor_role": "advisor", "payload": {}},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 422

    def test_whitespace_event_type_returns_422(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "   ", "actor_role": "advisor", "payload": {}},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 422

    def test_empty_actor_role_returns_422(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "", "payload": {}},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 422

    def test_whitespace_actor_role_returns_422(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "   ", "payload": {}},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 422

    def test_payload_as_list_returns_422(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": [1, 2, 3]},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 422

    def test_payload_as_string_returns_422(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": "hello"},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 422

    def test_payload_as_null_returns_422(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={"event_type": "x", "actor_role": "advisor", "payload": None},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 422

    def test_actor_advisor_id_unknown_returns_422(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={
                "event_type": "x",
                "actor_advisor_id": "advisor_does_not_exist",
                "actor_role": "advisor",
                "payload": {},
            },
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 422

    def test_actor_advisor_id_none_is_allowed(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/audit-events",
            json={
                "event_type": "system_event",
                "actor_role": "system",
                "payload": {"info": "automated"},
                # actor_advisor_id omitido → None
            },
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 201
        assert r.json()["actor_advisor_id"] is None


# ─────────────────────────────────────────────────────────────────────────────
# No regression on existing endpoints
# ─────────────────────────────────────────────────────────────────────────────


class TestNoRegression:
    def test_health_still_works_without_token(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200

    def test_auth_me_still_works_with_advisor_token(
        self, client: TestClient
    ) -> None:
        r = client.get("/auth/me", headers={"Authorization": _ADVISOR})
        assert r.status_code == 200
        assert r.json()["advisor_id"] == "ADV-AUD-001"
