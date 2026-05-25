"""
Entity repositories for Phase 2 core entities: Firm, Advisor, Client.

These repositories operate on tables created by migrations/0001_phase2_core_schema.sql.
They do NOT create or manage the entity schema — scripts/migrate.py must have been run
before using them.

Design:
    SQLiteEntityStore — manages the connection (parallel to SQLitePersistenceStore).
        - Enables PRAGMA foreign_keys=ON and journal_mode=WAL.
        - Bootstraps the `counters` table idempotently. The counters table is shared
          with SQLitePersistenceStore; both stores can safely coexist on the same file.
        - Provides _next_id(prefix) for sequential entity IDs.

    SQLiteFirmRepository    — CRUD for the `firms` table.
    SQLiteAdvisorRepository — CRUD for the `advisors` table.
    SQLiteClientRepository  — CRUD for the `clients` table.

Error conventions:
    EntityNotFoundError  — entity with given ID does not exist.
    EntityConflictError  — ID collision (duplicate PK) on insert.

    FK violations on INSERT raise EntityConflictError (wrapping sqlite3.IntegrityError).
    Callers (endpoints) inspect detail to decide HTTP status code.

Note on FK enforcement:
    SQLite enforces FK constraints only when PRAGMA foreign_keys=ON is active on the
    *connection that executes the DML*. SQLiteEntityStore sets this pragma at open time
    for every connection it creates.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class EntityNotFoundError(Exception):
    """Raised when a GET by ID finds no matching row."""


class EntityConflictError(Exception):
    """Raised on PK collision or FK violation during INSERT."""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteEntityStore
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteEntityStore:
    """
    SQLite connection manager for Phase 2 entity tables.

    Counterpart to SQLitePersistenceStore: same connection setup, but targeted at
    the entity tables (firms, advisors, clients) rather than the legacy records table.

    Bootstrap rule: the `counters` table is created here if it does not exist
    (idempotent CREATE TABLE IF NOT EXISTS). This lets the entity store work even
    if SQLitePersistenceStore.init_schema() has not yet been called on the same DB,
    and it is safe to call it after — the second CREATE IF NOT EXISTS is a no-op.

    Usage:
        with SQLiteEntityStore(db_path) as store:
            firm_repo = SQLiteFirmRepository(store)
            data = firm_repo.create(display_name="Acme", country="AR")
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._bootstrap_counters()

    def _bootstrap_counters(self) -> None:
        """Creates the counters table if it does not already exist. Idempotent."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS counters (
                    prefix      TEXT PRIMARY KEY,
                    next_val    INTEGER NOT NULL DEFAULT 1
                )
                """
            )

    def _next_id(self, prefix: str) -> str:
        """
        Generates the next sequential ID for the given prefix.

        Mirrors SQLitePersistenceStore._next_id exactly. The same counters row
        is used regardless of which store opened the connection first.

        Examples:
            _next_id("firm_")    → "firm_000001"
            _next_id("advisor_") → "advisor_000001"
            _next_id("client_")  → "client_000001"
        """
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
        return f"{prefix}{row[0]:06d}"

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def __enter__(self) -> "SQLiteEntityStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteFirmRepository
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteFirmRepository:
    """
    Persists and retrieves Firm entities from the `firms` table.

    Schema (from 0001_phase2_core_schema.sql):
        firms(firm_id TEXT PK, display_name TEXT, country TEXT,
              is_active INTEGER, created_at_utc TEXT)
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        firm_id: str | None = None,
        display_name: str,
        country: str,
        is_active: bool = True,
    ) -> dict[str, Any]:
        """
        Inserts a new firm. If firm_id is None, a sequential ID is generated.

        Raises:
            EntityConflictError: if firm_id already exists in the table.
        """
        if firm_id is None:
            firm_id = self._store._next_id("firm_")
        now = _now_utc()
        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO firms
                        (firm_id, display_name, country, is_active, created_at_utc)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (firm_id, display_name, country, 1 if is_active else 0, now),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(
                f"firm_id already exists: {firm_id!r}"
            ) from exc
        return {
            "firm_id": firm_id,
            "display_name": display_name,
            "country": country,
            "is_active": is_active,
            "created_at_utc": now,
        }

    def get(self, firm_id: str) -> dict[str, Any] | None:
        """Returns the firm dict, or None if not found."""
        row = self._store._conn.execute(
            """
            SELECT firm_id, display_name, country, is_active, created_at_utc
            FROM firms WHERE firm_id = ?
            """,
            (firm_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_all(self) -> list[dict[str, Any]]:
        """Returns all firms in insertion order."""
        rows = self._store._conn.execute(
            """
            SELECT firm_id, display_name, country, is_active, created_at_utc
            FROM firms ORDER BY rowid ASC
            """
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "firm_id": row["firm_id"],
            "display_name": row["display_name"],
            "country": row["country"],
            "is_active": bool(row["is_active"]),
            "created_at_utc": row["created_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteAdvisorRepository
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteAdvisorRepository:
    """
    Persists and retrieves Advisor entities from the `advisors` table.

    Schema (from 0001_phase2_core_schema.sql):
        advisors(advisor_id TEXT PK, firm_id TEXT FK→firms,
                 display_name TEXT, email TEXT, roles_json TEXT,
                 is_active INTEGER, created_at_utc TEXT)

    `roles` is serialized as a JSON array in `roles_json`.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        advisor_id: str | None = None,
        firm_id: str,
        display_name: str,
        email: str,
        roles: list[str],
        is_active: bool = True,
    ) -> dict[str, Any]:
        """
        Inserts a new advisor. If advisor_id is None, a sequential ID is generated.

        Raises:
            EntityConflictError: on PK collision or FK violation (firm_id not found).
        """
        if advisor_id is None:
            advisor_id = self._store._next_id("advisor_")
        now = _now_utc()
        roles_json = json.dumps(roles, ensure_ascii=False)
        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO advisors
                        (advisor_id, firm_id, display_name, email,
                         roles_json, is_active, created_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        advisor_id, firm_id, display_name, email,
                        roles_json, 1 if is_active else 0, now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc
        return {
            "advisor_id": advisor_id,
            "firm_id": firm_id,
            "display_name": display_name,
            "email": email,
            "roles": roles,
            "is_active": is_active,
            "created_at_utc": now,
        }

    def get(self, advisor_id: str) -> dict[str, Any] | None:
        """Returns the advisor dict, or None if not found."""
        row = self._store._conn.execute(
            """
            SELECT advisor_id, firm_id, display_name, email,
                   roles_json, is_active, created_at_utc
            FROM advisors WHERE advisor_id = ?
            """,
            (advisor_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_all(self) -> list[dict[str, Any]]:
        """Returns all advisors in insertion order."""
        rows = self._store._conn.execute(
            """
            SELECT advisor_id, firm_id, display_name, email,
                   roles_json, is_active, created_at_utc
            FROM advisors ORDER BY rowid ASC
            """
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_by_firm(self, firm_id: str) -> list[dict[str, Any]]:
        """Returns all advisors belonging to the given firm."""
        rows = self._store._conn.execute(
            """
            SELECT advisor_id, firm_id, display_name, email,
                   roles_json, is_active, created_at_utc
            FROM advisors WHERE firm_id = ? ORDER BY rowid ASC
            """,
            (firm_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "advisor_id": row["advisor_id"],
            "firm_id": row["firm_id"],
            "display_name": row["display_name"],
            "email": row["email"],
            "roles": json.loads(row["roles_json"]),
            "is_active": bool(row["is_active"]),
            "created_at_utc": row["created_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteClientRepository
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteClientRepository:
    """
    Persists and retrieves Client entities from the `clients` table.

    Schema (from 0001_phase2_core_schema.sql):
        clients(client_id TEXT PK, firm_id TEXT FK→firms,
                primary_advisor_id TEXT FK→advisors,
                display_name TEXT, external_ref TEXT,
                jurisdiction TEXT, preferred_currency TEXT,
                is_active INTEGER, created_at_utc TEXT)
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        client_id: str | None = None,
        firm_id: str,
        primary_advisor_id: str,
        display_name: str,
        external_ref: str | None = None,
        jurisdiction: str = "AR",
        preferred_currency: str = "USD",
        is_active: bool = True,
    ) -> dict[str, Any]:
        """
        Inserts a new client. If client_id is None, a sequential ID is generated.

        Note: cross-firm validation (primary_advisor_id must belong to firm_id)
        is NOT enforced here — it is the caller's responsibility to pre-validate.

        Raises:
            EntityConflictError: on PK collision or FK violation
                (firm_id or primary_advisor_id not found).
        """
        if client_id is None:
            client_id = self._store._next_id("client_")
        now = _now_utc()
        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO clients
                        (client_id, firm_id, primary_advisor_id, display_name,
                         external_ref, jurisdiction, preferred_currency,
                         is_active, created_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        client_id, firm_id, primary_advisor_id, display_name,
                        external_ref, jurisdiction, preferred_currency,
                        1 if is_active else 0, now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc
        return {
            "client_id": client_id,
            "firm_id": firm_id,
            "primary_advisor_id": primary_advisor_id,
            "display_name": display_name,
            "external_ref": external_ref,
            "jurisdiction": jurisdiction,
            "preferred_currency": preferred_currency,
            "is_active": is_active,
            "created_at_utc": now,
        }

    def get(self, client_id: str) -> dict[str, Any] | None:
        """Returns the client dict, or None if not found."""
        row = self._store._conn.execute(
            """
            SELECT client_id, firm_id, primary_advisor_id, display_name,
                   external_ref, jurisdiction, preferred_currency,
                   is_active, created_at_utc
            FROM clients WHERE client_id = ?
            """,
            (client_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_all(self) -> list[dict[str, Any]]:
        """Returns all clients in insertion order."""
        rows = self._store._conn.execute(
            """
            SELECT client_id, firm_id, primary_advisor_id, display_name,
                   external_ref, jurisdiction, preferred_currency,
                   is_active, created_at_utc
            FROM clients ORDER BY rowid ASC
            """
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_by_firm(self, firm_id: str) -> list[dict[str, Any]]:
        """Returns all clients belonging to the given firm."""
        rows = self._store._conn.execute(
            """
            SELECT client_id, firm_id, primary_advisor_id, display_name,
                   external_ref, jurisdiction, preferred_currency,
                   is_active, created_at_utc
            FROM clients WHERE firm_id = ? ORDER BY rowid ASC
            """,
            (firm_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_by_advisor(self, primary_advisor_id: str) -> list[dict[str, Any]]:
        """Returns all clients whose primary advisor is the given advisor."""
        rows = self._store._conn.execute(
            """
            SELECT client_id, firm_id, primary_advisor_id, display_name,
                   external_ref, jurisdiction, preferred_currency,
                   is_active, created_at_utc
            FROM clients WHERE primary_advisor_id = ? ORDER BY rowid ASC
            """,
            (primary_advisor_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "client_id": row["client_id"],
            "firm_id": row["firm_id"],
            "primary_advisor_id": row["primary_advisor_id"],
            "display_name": row["display_name"],
            "external_ref": row["external_ref"],
            "jurisdiction": row["jurisdiction"],
            "preferred_currency": row["preferred_currency"],
            "is_active": bool(row["is_active"]),
            "created_at_utc": row["created_at_utc"],
        }
