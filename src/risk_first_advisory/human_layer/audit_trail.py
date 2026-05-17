"""
AuditTrail — registro append-only, inmutable tras close().

INVARIANTES:
- Cada evento se registra con timestamp UTC automático.
- Una vez llamado close(), no se pueden agregar más eventos.
- Los eventos se almacenan en orden cronológico.
- El trail es serializable a JSON para persistencia externa.

Esta clase es el corazón de compliance del sistema. Toda decisión, override,
generación y aprobación debe quedar registrada acá.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class AuditTrailClosedError(Exception):
    """Se intentó modificar un AuditTrail ya cerrado."""


@dataclass
class AuditEvent:
    """Un evento individual del trail."""

    event_type: str
    timestamp_utc: str  # ISO 8601
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "timestamp_utc": self.timestamp_utc,
            "data": self.data,
        }


@dataclass
class AuditTrail:
    """
    Registro append-only de eventos de una sesión de asesoría.

    Uso típico:
        trail = AuditTrail(session_id="SES-001", client_id="CLI-001", advisor_id="ADV-001")
        trail.record("session_started", {"provider": "mock"})
        ...
        trail.close()
    """

    session_id: str
    client_id: str
    advisor_id: str
    started_at_utc: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    _events: list[AuditEvent] = field(default_factory=list, repr=False)
    _closed: bool = field(default=False, repr=False)
    _closed_at_utc: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id no puede estar vacío.")
        if not self.client_id.strip():
            raise ValueError("client_id no puede estar vacío.")
        if not self.advisor_id.strip():
            raise ValueError("advisor_id no puede estar vacío.")

    def record(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Agrega un evento al trail. Falla si el trail ya está cerrado."""
        if self._closed:
            raise AuditTrailClosedError(
                f"AuditTrail {self.session_id!r} ya está cerrado. "
                "No se pueden agregar más eventos."
            )
        if not event_type.strip():
            raise ValueError("event_type no puede estar vacío.")
        event = AuditEvent(
            event_type=event_type,
            timestamp_utc=datetime.utcnow().isoformat(),
            data=data if data is not None else {},
        )
        self._events.append(event)

    def close(self) -> None:
        """Cierra el trail. Tras esto, record() lanza AuditTrailClosedError."""
        if self._closed:
            return  # idempotente
        self._closed = True
        self._closed_at_utc = datetime.utcnow().isoformat()

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def events(self) -> list[AuditEvent]:
        """Vista de solo lectura sobre los eventos registrados."""
        return list(self._events)

    def event_types(self) -> list[str]:
        """Lista de tipos de evento registrados, en orden."""
        return [e.event_type for e in self._events]

    def has_event(self, event_type: str) -> bool:
        return any(e.event_type == event_type for e in self._events)

    def get_events_by_type(self, event_type: str) -> list[AuditEvent]:
        return [e for e in self._events if e.event_type == event_type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "client_id": self.client_id,
            "advisor_id": self.advisor_id,
            "started_at_utc": self.started_at_utc,
            "closed_at_utc": self._closed_at_utc,
            "is_closed": self._closed,
            "events": [e.to_dict() for e in self._events],
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)