"""
Tests del AuditTrail.

INVARIANTES verificadas:
- Es append-only durante la sesión.
- close() impide nuevos records.
- close() es idempotente.
- Eventos quedan en orden cronológico.
- Serialización a JSON funciona y es estable.
"""

import json

import pytest

from risk_first_advisory.human_layer.audit_trail import (
    AuditTrail,
    AuditTrailClosedError,
)


def _build_trail():
    return AuditTrail(
        session_id="SES-TEST-001",
        client_id="CLI-001",
        advisor_id="ADV-001",
    )


def test_audit_trail_requires_session_id():
    with pytest.raises(ValueError, match="session_id"):
        AuditTrail(session_id="", client_id="CLI-001", advisor_id="ADV-001")


def test_audit_trail_requires_client_id():
    with pytest.raises(ValueError, match="client_id"):
        AuditTrail(session_id="SES-001", client_id="", advisor_id="ADV-001")


def test_audit_trail_requires_advisor_id():
    with pytest.raises(ValueError, match="advisor_id"):
        AuditTrail(session_id="SES-001", client_id="CLI-001", advisor_id="")


def test_audit_trail_starts_empty_and_open():
    trail = _build_trail()
    assert trail.events == []
    assert trail.is_closed is False


def test_audit_trail_records_single_event():
    trail = _build_trail()
    trail.record("session_started", {"provider": "mock"})
    assert len(trail.events) == 1
    assert trail.events[0].event_type == "session_started"
    assert trail.events[0].data == {"provider": "mock"}
    assert trail.events[0].timestamp_utc  # no vacío


def test_audit_trail_records_multiple_events_in_order():
    trail = _build_trail()
    trail.record("session_started", {})
    trail.record("ai_output_initial", {"profile": "moderado-defensivo"})
    trail.record("advisor_profile_approval", {"approved": "moderado"})
    assert trail.event_types() == [
        "session_started",
        "ai_output_initial",
        "advisor_profile_approval",
    ]


def test_audit_trail_records_with_empty_data_dict():
    trail = _build_trail()
    trail.record("session_started")
    assert trail.events[0].data == {}


def test_audit_trail_record_requires_event_type():
    trail = _build_trail()
    with pytest.raises(ValueError, match="event_type"):
        trail.record("", {"some": "data"})


def test_audit_trail_close_prevents_new_records():
    trail = _build_trail()
    trail.record("session_started", {})
    trail.close()
    assert trail.is_closed is True
    with pytest.raises(AuditTrailClosedError):
        trail.record("attempt_after_close", {"should": "fail"})


def test_audit_trail_close_is_idempotent():
    """Llamar close() dos veces no debe fallar."""
    trail = _build_trail()
    trail.record("session_started", {})
    trail.close()
    trail.close()  # no debe lanzar
    assert trail.is_closed is True


def test_audit_trail_events_property_returns_copy():
    """events debe ser una vista de solo lectura — modificarla no altera el trail."""
    trail = _build_trail()
    trail.record("event_one", {})
    snapshot = trail.events
    snapshot.clear()  # modificación externa
    assert len(trail.events) == 1, (
        "events debe devolver una copia — modificaciones externas no deben "
        "afectar el estado interno."
    )


def test_audit_trail_has_event():
    trail = _build_trail()
    trail.record("session_started", {})
    trail.record("ai_output_initial", {})
    assert trail.has_event("session_started") is True
    assert trail.has_event("ai_output_initial") is True
    assert trail.has_event("non_existent_event") is False


def test_audit_trail_get_events_by_type():
    trail = _build_trail()
    trail.record("variant_generated", {"variant": "protection"})
    trail.record("variant_generated", {"variant": "balanced"})
    trail.record("session_started", {})
    events = trail.get_events_by_type("variant_generated")
    assert len(events) == 2
    assert events[0].data["variant"] == "protection"
    assert events[1].data["variant"] == "balanced"


def test_audit_trail_to_dict_includes_all_metadata():
    trail = _build_trail()
    trail.record("session_started", {"provider": "mock"})
    trail.close()
    d = trail.to_dict()
    assert d["session_id"] == "SES-TEST-001"
    assert d["client_id"] == "CLI-001"
    assert d["advisor_id"] == "ADV-001"
    assert d["is_closed"] is True
    assert d["closed_at_utc"] is not None
    assert d["started_at_utc"] is not None
    assert len(d["events"]) == 1
    assert d["events"][0]["event_type"] == "session_started"


def test_audit_trail_to_json_produces_valid_json():
    trail = _build_trail()
    trail.record("session_started", {"provider": "mock", "seed": 42})
    trail.record("ai_output_initial", {"profile": "moderado"})
    trail.close()
    payload = trail.to_json()
    parsed = json.loads(payload)
    assert parsed["session_id"] == "SES-TEST-001"
    assert len(parsed["events"]) == 2
    assert parsed["events"][0]["data"]["seed"] == 42


def test_audit_trail_full_flow_simulation():
    """Simulación del flujo esperado de una sesión completa."""
    trail = AuditTrail(
        session_id="SES-FLOW-001",
        client_id="CLI-DEMO",
        advisor_id="ADV-DEMO",
    )
    trail.record("session_started", {"provider": "mock"})
    trail.record("ai_output_initial", {"profile": "moderado-defensivo", "confidence": 0.62})
    trail.record("follow_up_cycle_1_started", {"questions": ["q1", "q2"]})
    trail.record("follow_up_cycle_1_completed", {"rounds": 1})
    trail.record("ai_output_revised", {"profile": "moderado", "confidence": 0.81})
    trail.record(
        "advisor_profile_approval",
        {
            "original": "moderado-defensivo",
            "approved": "moderado",
            "modified": True,
            "advisor_comment": "Tras follow-up, tolerancia real del cliente es mayor.",
        },
    )
    trail.record("goal_feasibility", {"status": "viable"})
    trail.record("session_closed", {})
    trail.close()

    assert trail.is_closed
    assert trail.has_event("ai_output_initial")
    assert trail.has_event("ai_output_revised")
    assert trail.has_event("advisor_profile_approval")

    approval_events = trail.get_events_by_type("advisor_profile_approval")
    assert len(approval_events) == 1
    assert approval_events[0].data["original"] == "moderado-defensivo"
    assert approval_events[0].data["approved"] == "moderado"
    assert approval_events[0].data["modified"] is True
