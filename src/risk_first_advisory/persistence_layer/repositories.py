"""
Persistence repository interfaces e implementaciones in-memory.

Diseño:
    - StoredRecord: contenedor serializable de cualquier artefacto persistido.
    - WorkflowRunRepository / AuditRepository / ReportRepository: contratos (ABC).
    - InMemory*: implementaciones para desarrollo y tests. Sin base de datos.

Política de IDs:
    workflow_<uuid4_hex>
    audit_<uuid4_hex>
    report_<uuid4_hex>

El core no importa implementaciones concretas. Los consumidores (scripts,
API, CLI) inyectan la implementación que corresponde al entorno.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# StoredRecord
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class StoredRecord:
    """
    Contenedor genérico de un artefacto persistido.

    `payload` contiene la representación JSON-serializable del artefacto.
    `metadata` contiene campos auxiliares (client_id, source_type, etc.)
    que permiten filtrar y auditar sin deserializar el payload completo.
    """

    record_id: str
    record_type: str
    created_at_utc: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for attr in ("record_id", "record_type", "created_at_utc"):
            val = getattr(self, attr)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"{attr} no puede estar vacío.")
        if not isinstance(self.payload, dict):
            raise ValueError("payload debe ser un dict.")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata debe ser un dict.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "record_type": self.record_type,
            "created_at_utc": self.created_at_utc,
            "payload": self.payload,
            "metadata": self.metadata,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Excepciones
# ─────────────────────────────────────────────────────────────────────────────


class RepositoryError(Exception):
    """Error base de la capa de persistencia."""


class RecordNotFoundError(RepositoryError):
    """El registro solicitado no existe en el repositorio."""


# ─────────────────────────────────────────────────────────────────────────────
# Contratos (ABC)
# ─────────────────────────────────────────────────────────────────────────────


class WorkflowRunRepository(ABC):
    @abstractmethod
    def save_workflow_result(self, result: Any) -> StoredRecord:
        """Persiste un AdvisoryWorkflowResult y devuelve el StoredRecord creado."""

    @abstractmethod
    def get_workflow_result(self, record_id: str) -> StoredRecord:
        """Recupera un StoredRecord por su record_id. Lanza RecordNotFoundError si no existe."""

    @abstractmethod
    def list_workflow_results(self, client_id: str | None = None) -> list[StoredRecord]:
        """Lista todos los registros, opcionalmente filtrados por client_id."""


class AuditRepository(ABC):
    @abstractmethod
    def save_audit_trail(self, audit_trail: Any) -> StoredRecord:
        """Persiste un AuditTrail y devuelve el StoredRecord creado."""

    @abstractmethod
    def get_audit_trail(self, record_id: str) -> StoredRecord:
        """Recupera un StoredRecord por su record_id. Lanza RecordNotFoundError si no existe."""

    @abstractmethod
    def list_audit_trails(self, client_id: str | None = None) -> list[StoredRecord]:
        """Lista todos los registros, opcionalmente filtrados por client_id."""


class ReportRepository(ABC):
    @abstractmethod
    def save_report(self, report: Any) -> StoredRecord:
        """Persiste un MarkdownReport y devuelve el StoredRecord creado."""

    @abstractmethod
    def get_report(self, record_id: str) -> StoredRecord:
        """Recupera un StoredRecord por su record_id. Lanza RecordNotFoundError si no existe."""

    @abstractmethod
    def list_reports(self, client_id: str | None = None) -> list[StoredRecord]:
        """Lista todos los registros, opcionalmente filtrados por client_id."""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def _to_payload(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "to_dict"):
        result = obj.to_dict()
        if isinstance(result, dict):
            return result
    return {"raw": str(obj)}


# ─────────────────────────────────────────────────────────────────────────────
# Implementaciones in-memory
# ─────────────────────────────────────────────────────────────────────────────


class InMemoryWorkflowRunRepository(WorkflowRunRepository):
    """
    Repositorio de workflow runs en memoria.

    Para desarrollo y tests. No persiste entre reinicios del proceso.
    """

    def __init__(self) -> None:
        self._store: dict[str, StoredRecord] = {}
        self._insertion_order: list[str] = []

    def save_workflow_result(self, result: Any) -> StoredRecord:
        record_id = _new_id("workflow_")
        client_id = getattr(result, "client_id", None)
        status = getattr(result, "status", None)
        record = StoredRecord(
            record_id=record_id,
            record_type="workflow_run",
            created_at_utc=_now_utc(),
            payload=_to_payload(result),
            metadata={
                "client_id": client_id,
                "source_type": "AdvisoryWorkflowResult",
                "status": status.value if status is not None else None,
            },
        )
        self._store[record_id] = record
        self._insertion_order.append(record_id)
        return record

    def get_workflow_result(self, record_id: str) -> StoredRecord:
        if record_id not in self._store:
            raise RecordNotFoundError(f"Workflow run no encontrado: {record_id!r}")
        return self._store[record_id]

    def list_workflow_results(self, client_id: str | None = None) -> list[StoredRecord]:
        records = [self._store[rid] for rid in self._insertion_order]
        if client_id is None:
            return records
        return [r for r in records if r.metadata.get("client_id") == client_id]


class InMemoryAuditRepository(AuditRepository):
    """
    Repositorio de audit trails en memoria.

    Para desarrollo y tests. No persiste entre reinicios del proceso.
    """

    def __init__(self) -> None:
        self._store: dict[str, StoredRecord] = {}
        self._insertion_order: list[str] = []

    def save_audit_trail(self, audit_trail: Any) -> StoredRecord:
        record_id = _new_id("audit_")
        client_id = getattr(audit_trail, "client_id", None)
        session_id = getattr(audit_trail, "session_id", None)
        record = StoredRecord(
            record_id=record_id,
            record_type="audit_trail",
            created_at_utc=_now_utc(),
            payload=_to_payload(audit_trail),
            metadata={
                "client_id": client_id,
                "session_id": session_id,
                "source_type": "AuditTrail",
            },
        )
        self._store[record_id] = record
        self._insertion_order.append(record_id)
        return record

    def get_audit_trail(self, record_id: str) -> StoredRecord:
        if record_id not in self._store:
            raise RecordNotFoundError(f"Audit trail no encontrado: {record_id!r}")
        return self._store[record_id]

    def list_audit_trails(self, client_id: str | None = None) -> list[StoredRecord]:
        records = [self._store[rid] for rid in self._insertion_order]
        if client_id is None:
            return records
        return [r for r in records if r.metadata.get("client_id") == client_id]


class InMemoryReportRepository(ReportRepository):
    """
    Repositorio de reportes Markdown en memoria.

    Para desarrollo y tests. No persiste entre reinicios del proceso.
    """

    def __init__(self) -> None:
        self._store: dict[str, StoredRecord] = {}
        self._insertion_order: list[str] = []

    def save_report(self, report: Any) -> StoredRecord:
        record_id = _new_id("report_")
        client_id = getattr(report, "client_id", None)
        title = getattr(report, "title", None)
        record = StoredRecord(
            record_id=record_id,
            record_type="markdown_report",
            created_at_utc=_now_utc(),
            payload=_to_payload(report),
            metadata={
                "client_id": client_id,
                "title": title,
                "source_type": "MarkdownReport",
            },
        )
        self._store[record_id] = record
        self._insertion_order.append(record_id)
        return record

    def get_report(self, record_id: str) -> StoredRecord:
        if record_id not in self._store:
            raise RecordNotFoundError(f"Report no encontrado: {record_id!r}")
        return self._store[record_id]

    def list_reports(self, client_id: str | None = None) -> list[StoredRecord]:
        records = [self._store[rid] for rid in self._insertion_order]
        if client_id is None:
            return records
        return [r for r in records if r.metadata.get("client_id") == client_id]
