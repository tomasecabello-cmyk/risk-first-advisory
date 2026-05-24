"""
SQLite persistence layer — implementaciones concretas de los repositorios.

Usa sqlite3 estándar de Python. Sin SQLAlchemy ni migrations complejas.

Diseño:
    - SQLitePersistenceStore: gestiona la conexión y el schema.
    - SQLite*Repository: implementan las interfaces ABC de repositories.py.
    - Un store se comparte entre repositorios; cada repo recibe el store como dep.

Schema:
    records  — tabla genérica de artefactos persistidos.
    counters — tabla de contadores por prefijo para IDs secuenciales.

IDs secuenciales:
    workflow_000001, audit_000001, report_000001, ...
    El contador persiste en la DB; continúa tras cerrar y reabrir el store.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from risk_first_advisory.persistence_layer.repositories import (
    AuditRepository,
    RecordNotFoundError,
    RepositoryError,
    ReportRepository,
    StoredRecord,
    WorkflowRunRepository,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_payload(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "to_dict"):
        result = obj.to_dict()
        if isinstance(result, dict):
            return result
    return {"raw": str(obj)}


# ─────────────────────────────────────────────────────────────────────────────
# SQLitePersistenceStore
# ─────────────────────────────────────────────────────────────────────────────


class SQLitePersistenceStore:
    """
    Gestiona la conexión SQLite y el schema compartido por todos los repositorios.

    Uso típico:
        store = SQLitePersistenceStore("advisory.db")
        store.init_schema()
        repo = SQLiteWorkflowRunRepository(store)
        ...
        store.close()

    O como context manager:
        with SQLitePersistenceStore("advisory.db") as store:
            store.init_schema()
            ...
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        # PRAGMA para integridad referencial y performance básica.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def init_schema(self) -> None:
        """Crea las tablas si no existen. Idempotente."""
        try:
            with self._conn:
                self._conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS records (
                        record_id       TEXT PRIMARY KEY,
                        record_type     TEXT NOT NULL,
                        client_id       TEXT,
                        created_at_utc  TEXT NOT NULL,
                        payload_json    TEXT NOT NULL,
                        metadata_json   TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS counters (
                        prefix      TEXT PRIMARY KEY,
                        next_val    INTEGER NOT NULL DEFAULT 1
                    );
                    """
                )
        except sqlite3.Error as exc:
            raise RepositoryError(f"Error al inicializar schema: {exc}") from exc

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def __enter__(self) -> "SQLitePersistenceStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ── Operaciones internas usadas por los repositorios ─────────────────────

    def _next_id(self, prefix: str) -> str:
        """
        Genera el siguiente ID secuencial para el prefijo dado.

        Garantía: si el store se cierra y reabre, el contador continúa
        desde el último valor persistido en la tabla `counters`.
        """
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO counters (prefix, next_val) VALUES (?, 1)",
                    (prefix,),
                )
                self._conn.execute(
                    "UPDATE counters SET next_val = next_val + 1 WHERE prefix = ?",
                    (prefix,),
                )
                row = self._conn.execute(
                    "SELECT next_val - 1 FROM counters WHERE prefix = ?",
                    (prefix,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError(
                f"Error al generar ID para prefijo {prefix!r}: {exc}"
            ) from exc
        return f"{prefix}{row[0]:06d}"

    def _insert_record(
        self,
        record_id: str,
        record_type: str,
        client_id: str | None,
        created_at_utc: str,
        payload: dict[str, Any],
        metadata: dict[str, Any],
    ) -> StoredRecord:
        payload_json = json.dumps(payload, ensure_ascii=False)
        metadata_json = json.dumps(metadata, ensure_ascii=False)
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO records
                        (record_id, record_type, client_id, created_at_utc,
                         payload_json, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        record_type,
                        client_id,
                        created_at_utc,
                        payload_json,
                        metadata_json,
                    ),
                )
        except sqlite3.Error as exc:
            raise RepositoryError(
                f"Error al insertar registro {record_id!r}: {exc}"
            ) from exc
        return StoredRecord(
            record_id=record_id,
            record_type=record_type,
            created_at_utc=created_at_utc,
            payload=payload,
            metadata=metadata,
        )

    def _get_record(self, record_id: str, not_found_msg: str) -> StoredRecord:
        try:
            row = self._conn.execute(
                """
                SELECT record_id, record_type, created_at_utc,
                       payload_json, metadata_json
                FROM records
                WHERE record_id = ?
                """,
                (record_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError(f"Error al recuperar registro: {exc}") from exc
        if row is None:
            raise RecordNotFoundError(not_found_msg)
        return StoredRecord(
            record_id=row["record_id"],
            record_type=row["record_type"],
            created_at_utc=row["created_at_utc"],
            payload=json.loads(row["payload_json"]),
            metadata=json.loads(row["metadata_json"]),
        )

    def _list_records(
        self,
        record_type: str,
        client_id: str | None,
    ) -> list[StoredRecord]:
        try:
            if client_id is None:
                rows = self._conn.execute(
                    """
                    SELECT record_id, record_type, created_at_utc,
                           payload_json, metadata_json
                    FROM records
                    WHERE record_type = ?
                    ORDER BY rowid ASC
                    """,
                    (record_type,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT record_id, record_type, created_at_utc,
                           payload_json, metadata_json
                    FROM records
                    WHERE record_type = ? AND client_id = ?
                    ORDER BY rowid ASC
                    """,
                    (record_type, client_id),
                ).fetchall()
        except sqlite3.Error as exc:
            raise RepositoryError(f"Error al listar registros: {exc}") from exc
        return [
            StoredRecord(
                record_id=row["record_id"],
                record_type=row["record_type"],
                created_at_utc=row["created_at_utc"],
                payload=json.loads(row["payload_json"]),
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteWorkflowRunRepository
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteWorkflowRunRepository(WorkflowRunRepository):
    def __init__(self, store: SQLitePersistenceStore) -> None:
        self._store = store

    def save_workflow_result(self, result: Any) -> StoredRecord:
        record_id = self._store._next_id("workflow_")
        client_id = getattr(result, "client_id", None)
        status = getattr(result, "status", None)
        return self._store._insert_record(
            record_id=record_id,
            record_type="workflow_run",
            client_id=client_id,
            created_at_utc=_now_utc(),
            payload=_to_payload(result),
            metadata={
                "client_id": client_id,
                "source_type": "workflow_result",
                "status": status.value if status is not None else None,
            },
        )

    def get_workflow_result(self, record_id: str) -> StoredRecord:
        return self._store._get_record(
            record_id,
            f"Workflow run no encontrado: {record_id!r}",
        )

    def list_workflow_results(self, client_id: str | None = None) -> list[StoredRecord]:
        return self._store._list_records("workflow_run", client_id)


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteAuditRepository
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteAuditRepository(AuditRepository):
    def __init__(self, store: SQLitePersistenceStore) -> None:
        self._store = store

    def save_audit_trail(self, audit_trail: Any) -> StoredRecord:
        record_id = self._store._next_id("audit_")
        client_id = getattr(audit_trail, "client_id", None)
        session_id = getattr(audit_trail, "session_id", None)
        return self._store._insert_record(
            record_id=record_id,
            record_type="audit_trail",
            client_id=client_id,
            created_at_utc=_now_utc(),
            payload=_to_payload(audit_trail),
            metadata={
                "client_id": client_id,
                "session_id": session_id,
                "source_type": "audit_trail",
            },
        )

    def get_audit_trail(self, record_id: str) -> StoredRecord:
        return self._store._get_record(
            record_id,
            f"Audit trail no encontrado: {record_id!r}",
        )

    def list_audit_trails(self, client_id: str | None = None) -> list[StoredRecord]:
        return self._store._list_records("audit_trail", client_id)


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteReportRepository
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteAdvisorProfileApprovalRepository:
    """
    Persiste decisiones del asesor sobre perfiles propuestos
    (`POST /advisor/profile-approval`).

    record_type = "advisor_profile_approval"
    id prefix   = "advisor_profile_approval_"

    Metadata mínima persistida (para filtrar sin deserializar el payload):
        - client_id
        - advisor_id
        - decision           (approve | modify | reject)
        - proposed_profile
        - approved_profile   (puede ser None si decision=reject)
        - endpoint
        - source_type

    Diseño: igual que SQLiteAIFilteredPortfolioRepository — no usa ABC porque
    no existe un patrón in-memory equivalente todavía.
    """

    def __init__(self, store: SQLitePersistenceStore) -> None:
        self._store = store

    def save_approval(
        self,
        payload: dict[str, Any],
        client_id: str,
        advisor_id: str,
        decision: str,
        proposed_profile: str,
        approved_profile: str | None,
    ) -> StoredRecord:
        record_id = self._store._next_id("advisor_profile_approval_")
        return self._store._insert_record(
            record_id=record_id,
            record_type="advisor_profile_approval",
            client_id=client_id,
            created_at_utc=_now_utc(),
            payload=payload,
            metadata={
                "client_id": client_id,
                "advisor_id": advisor_id,
                "decision": decision,
                "proposed_profile": proposed_profile,
                "approved_profile": approved_profile,
                "endpoint": "/advisor/profile-approval",
                "source_type": "advisor_profile_approval",
            },
        )

    def get_approval(self, record_id: str) -> StoredRecord:
        return self._store._get_record(
            record_id,
            f"Advisor profile approval no encontrado: {record_id!r}",
        )

    def list_approvals(
        self, client_id: str | None = None
    ) -> list[StoredRecord]:
        return self._store._list_records("advisor_profile_approval", client_id)


class SQLiteAIFilteredPortfolioRepository:
    """
    Persiste el resultado completo de POST /ai/filtered-portfolio-demo.

    record_type = "ai_filtered_portfolio"
    id prefix   = "ai_filtered_portfolio_"

    Metadata mínima persistida (para filtrar sin deserializar el payload):
        - client_id
        - profile
        - status
        - candidate_count
        - endpoint
        - source_type

    Diseño: no usa ABC todavía porque no hay un patrón in-memory equivalente.
    Si en el futuro se necesita, mover el contrato a repositories.py.
    """

    def __init__(self, store: SQLitePersistenceStore) -> None:
        self._store = store

    def save_ai_filtered_portfolio(
        self,
        payload: dict[str, Any],
        client_id: str,
        profile: str,
        status: str,
        candidate_count: int,
    ) -> StoredRecord:
        record_id = self._store._next_id("ai_filtered_portfolio_")
        return self._store._insert_record(
            record_id=record_id,
            record_type="ai_filtered_portfolio",
            client_id=client_id,
            created_at_utc=_now_utc(),
            payload=payload,
            metadata={
                "client_id": client_id,
                "profile": profile,
                "status": status,
                "candidate_count": candidate_count,
                "endpoint": "/ai/filtered-portfolio-demo",
                "source_type": "ai_filtered_portfolio",
            },
        )

    def get_ai_filtered_portfolio(self, record_id: str) -> StoredRecord:
        return self._store._get_record(
            record_id,
            f"AI Filtered Portfolio no encontrado: {record_id!r}",
        )

    def list_ai_filtered_portfolios(
        self, client_id: str | None = None
    ) -> list[StoredRecord]:
        return self._store._list_records("ai_filtered_portfolio", client_id)


class SQLiteReportRepository(ReportRepository):
    def __init__(self, store: SQLitePersistenceStore) -> None:
        self._store = store

    def save_report(self, report: Any) -> StoredRecord:
        record_id = self._store._next_id("report_")
        client_id = getattr(report, "client_id", None)
        title = getattr(report, "title", None)
        return self._store._insert_record(
            record_id=record_id,
            record_type="markdown_report",
            client_id=client_id,
            created_at_utc=_now_utc(),
            payload=_to_payload(report),
            metadata={
                "client_id": client_id,
                "title": title,
                "source_type": "markdown_report",
            },
        )

    def get_report(self, record_id: str) -> StoredRecord:
        return self._store._get_record(
            record_id,
            f"Report no encontrado: {record_id!r}",
        )

    def list_reports(self, client_id: str | None = None) -> list[StoredRecord]:
        return self._store._list_records("markdown_report", client_id)
