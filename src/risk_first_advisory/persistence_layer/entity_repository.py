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

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
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

    def __enter__(self) -> SQLiteEntityStore:
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


# ─────────────────────────────────────────────────────────────────────────────
# AdvisoryCase constants
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_CASE_STATUSES: frozenset[str] = frozenset(
    {"DRAFT", "IN_PROGRESS", "PORTFOLIO_SELECTED", "CLOSED"}
)

# Each status maps to the set of statuses it can legally transition to.
# CLOSED has no outgoing transitions (terminal state).
_CASE_VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT":              frozenset({"IN_PROGRESS"}),
    "IN_PROGRESS":        frozenset({"PORTFOLIO_SELECTED"}),
    "PORTFOLIO_SELECTED": frozenset({"CLOSED"}),
    "CLOSED":             frozenset(),
}


class CaseTransitionError(Exception):
    """Raised when a requested status transition is not permitted."""


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteAdvisoryCaseRepository
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteAdvisoryCaseRepository:
    """
    Persists and retrieves AdvisoryCase entities from the `advisory_cases` table.

    Schema (from 0001_phase2_core_schema.sql):
        advisory_cases(
            case_id TEXT PK,
            firm_id TEXT FK→firms,
            client_id TEXT FK→clients,
            lead_advisor_id TEXT FK→advisors,
            status TEXT,
            title TEXT,
            current_kyc_submission_id TEXT,
            current_approved_profile_id TEXT,
            current_portfolio_selection_id TEXT,
            created_at_utc TEXT,
            closed_at_utc TEXT
        )

    The three `current_*` fields start as NULL and are updated by later
    workflow steps (not yet implemented in Fase 2 Commit 5).

    Cross-entity validations (client ∈ firm, advisor ∈ firm) are the
    caller's responsibility — the repository only enforces DB-level FKs.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        case_id: str | None = None,
        firm_id: str,
        client_id: str,
        lead_advisor_id: str,
        title: str,
        status: str = "DRAFT",
    ) -> dict[str, Any]:
        """
        Inserts a new advisory case. closed_at_utc is always None on creation.

        Raises:
            EntityConflictError: on PK collision or FK violation.
        """
        if case_id is None:
            case_id = self._store._next_id("case_")
        now = _now_utc()
        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO advisory_cases
                        (case_id, firm_id, client_id, lead_advisor_id,
                         status, title,
                         current_kyc_submission_id, current_approved_profile_id,
                         current_portfolio_selection_id,
                         created_at_utc, closed_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL)
                    """,
                    (case_id, firm_id, client_id, lead_advisor_id, status, title, now),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc
        return {
            "case_id": case_id,
            "firm_id": firm_id,
            "client_id": client_id,
            "lead_advisor_id": lead_advisor_id,
            "status": status,
            "title": title,
            "current_kyc_submission_id": None,
            "current_approved_profile_id": None,
            "current_portfolio_selection_id": None,
            "created_at_utc": now,
            "closed_at_utc": None,
        }

    def get(self, case_id: str) -> dict[str, Any] | None:
        """Returns the case dict, or None if not found."""
        row = self._store._conn.execute(
            """
            SELECT case_id, firm_id, client_id, lead_advisor_id,
                   status, title,
                   current_kyc_submission_id, current_approved_profile_id,
                   current_portfolio_selection_id,
                   created_at_utc, closed_at_utc
            FROM advisory_cases WHERE case_id = ?
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_all(self) -> list[dict[str, Any]]:
        """Returns all cases in insertion order."""
        rows = self._store._conn.execute(
            """
            SELECT case_id, firm_id, client_id, lead_advisor_id,
                   status, title,
                   current_kyc_submission_id, current_approved_profile_id,
                   current_portfolio_selection_id,
                   created_at_utc, closed_at_utc
            FROM advisory_cases ORDER BY rowid ASC
            """
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_by_client(self, client_id: str) -> list[dict[str, Any]]:
        """Returns all cases for the given client, in insertion order."""
        rows = self._store._conn.execute(
            """
            SELECT case_id, firm_id, client_id, lead_advisor_id,
                   status, title,
                   current_kyc_submission_id, current_approved_profile_id,
                   current_portfolio_selection_id,
                   created_at_utc, closed_at_utc
            FROM advisory_cases WHERE client_id = ? ORDER BY rowid ASC
            """,
            (client_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_by_advisor(self, lead_advisor_id: str) -> list[dict[str, Any]]:
        """Returns all cases whose lead advisor is the given advisor."""
        rows = self._store._conn.execute(
            """
            SELECT case_id, firm_id, client_id, lead_advisor_id,
                   status, title,
                   current_kyc_submission_id, current_approved_profile_id,
                   current_portfolio_selection_id,
                   created_at_utc, closed_at_utc
            FROM advisory_cases WHERE lead_advisor_id = ? ORDER BY rowid ASC
            """,
            (lead_advisor_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_by_firm(self, firm_id: str) -> list[dict[str, Any]]:
        """Returns all cases belonging to the given firm."""
        rows = self._store._conn.execute(
            """
            SELECT case_id, firm_id, client_id, lead_advisor_id,
                   status, title,
                   current_kyc_submission_id, current_approved_profile_id,
                   current_portfolio_selection_id,
                   created_at_utc, closed_at_utc
            FROM advisory_cases WHERE firm_id = ? ORDER BY rowid ASC
            """,
            (firm_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_current_portfolio_selection(
        self, case_id: str, selection_id: str | None
    ) -> dict[str, Any]:
        """
        Setea advisory_cases.current_portfolio_selection_id = selection_id.

        Pasar None lo limpia. No valida que el selection_id exista en
        case_portfolio_selections — ese contrato lo cumple el endpoint.

        Raises:
            EntityNotFoundError: si el case no existe.
        """
        current = self.get(case_id)
        if current is None:
            raise EntityNotFoundError(f"Case not found: {case_id!r}")
        with self._store._conn:
            self._store._conn.execute(
                """
                UPDATE advisory_cases
                SET current_portfolio_selection_id = ?
                WHERE case_id = ?
                """,
                (selection_id, case_id),
            )
        updated = dict(current)
        updated["current_portfolio_selection_id"] = selection_id
        return updated

    def update_current_approved_profile(
        self, case_id: str, approval_id: str | None
    ) -> dict[str, Any]:
        """
        Setea advisory_cases.current_approved_profile_id = approval_id.

        Pasar None lo limpia. No valida que el approval_id exista en
        advisor_profile_approvals — ese contrato lo cumple el endpoint.

        Raises:
            EntityNotFoundError: si el case no existe.
        """
        current = self.get(case_id)
        if current is None:
            raise EntityNotFoundError(f"Case not found: {case_id!r}")
        with self._store._conn:
            self._store._conn.execute(
                """
                UPDATE advisory_cases
                SET current_approved_profile_id = ?
                WHERE case_id = ?
                """,
                (approval_id, case_id),
            )
        updated = dict(current)
        updated["current_approved_profile_id"] = approval_id
        return updated

    def update_current_kyc_submission(
        self, case_id: str, kyc_submission_id: str
    ) -> dict[str, Any]:
        """
        Setea advisory_cases.current_kyc_submission_id = kyc_submission_id.

        No valida que el kyc_submission_id exista en kyc_submissions —
        ese contrato lo cumple el endpoint (que acaba de insertarlo).

        Raises:
            EntityNotFoundError: si el case no existe.
        """
        current = self.get(case_id)
        if current is None:
            raise EntityNotFoundError(f"Case not found: {case_id!r}")
        with self._store._conn:
            self._store._conn.execute(
                """
                UPDATE advisory_cases
                SET current_kyc_submission_id = ?
                WHERE case_id = ?
                """,
                (kyc_submission_id, case_id),
            )
        updated = dict(current)
        updated["current_kyc_submission_id"] = kyc_submission_id
        return updated

    def update_status(self, case_id: str, new_status: str) -> dict[str, Any]:
        """
        Transitions the case to new_status.

        - Sets closed_at_utc to now when transitioning to CLOSED.
        - Validates the transition against _CASE_VALID_TRANSITIONS.

        Raises:
            EntityNotFoundError:  if the case does not exist.
            CaseTransitionError:  if the transition is not permitted.
        """
        current = self.get(case_id)
        if current is None:
            raise EntityNotFoundError(f"Case not found: {case_id!r}")

        current_status = current["status"]
        allowed_next = _CASE_VALID_TRANSITIONS.get(current_status, frozenset())
        if new_status not in allowed_next:
            allowed_str = (
                ", ".join(sorted(allowed_next)) if allowed_next else "none (terminal state)"
            )
            raise CaseTransitionError(
                f"Cannot transition from {current_status!r} to {new_status!r}. "
                f"Allowed next: {allowed_str}."
            )

        closed_at = _now_utc() if new_status == "CLOSED" else current["closed_at_utc"]
        with self._store._conn:
            self._store._conn.execute(
                "UPDATE advisory_cases SET status = ?, closed_at_utc = ? WHERE case_id = ?",
                (new_status, closed_at, case_id),
            )
        updated = dict(current)
        updated["status"] = new_status
        updated["closed_at_utc"] = closed_at
        return updated

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "case_id": row["case_id"],
            "firm_id": row["firm_id"],
            "client_id": row["client_id"],
            "lead_advisor_id": row["lead_advisor_id"],
            "status": row["status"],
            "title": row["title"],
            "current_kyc_submission_id": row["current_kyc_submission_id"],
            "current_approved_profile_id": row["current_approved_profile_id"],
            "current_portfolio_selection_id": row["current_portfolio_selection_id"],
            "created_at_utc": row["created_at_utc"],
            "closed_at_utc": row["closed_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# AuditEvent — hash chain helpers
# ─────────────────────────────────────────────────────────────────────────────
#
# Cada evento de audit forma un eslabón de una cadena append-only por
# case_id. Los hashes son determinísticos: dada la misma terna
# (payload + metadatos del evento + previous_hash) el event_hash siempre
# es el mismo. Esto permite verificar integridad sin secretos.
#
# Limitaciones:
#   - No es blockchain: no es resistente a un admin con acceso directo a la
#     DB que reescriba toda la cadena (incluyendo todos los hashes).
#   - Solo protege contra mutaciones puntuales: cambiar un payload, un
#     previous_hash o crear un gap de sequence se detecta vía verify_chain.
#   - Las firmas digitales / anclaje externo (timestamping authority,
#     publicación de root hash a otro storage) quedan fuera del scope.
# ─────────────────────────────────────────────────────────────────────────────


def _canonical_json(payload: Mapping[str, Any]) -> str:
    """
    Serialización canonical determinística para hashing.

    Mantiene:
        sort_keys=True            → orden estable
        separators=(",", ":")     → sin whitespace
        ensure_ascii=False        → no escapa unicode innecesariamente
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_payload_hash(payload: Mapping[str, Any]) -> str:
    """SHA-256 hex digest del payload canonical."""
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def compute_event_hash(
    *,
    previous_hash: str | None,
    sequence: int,
    event_type: str,
    actor_advisor_id: str | None,
    actor_role: str,
    created_at_utc: str,
    payload_hash: str,
) -> str:
    """
    SHA-256 hex digest del evento, incluyendo el hash del eslabón anterior.

    Representación estable: dict serializado vía _canonical_json. None se
    sustituye por "" para `previous_hash` y `actor_advisor_id` para evitar
    ambigüedad entre null y empty string en la cadena hasheada.
    """
    parts = {
        "previous_hash":    previous_hash or "",
        "sequence":         sequence,
        "event_type":       event_type,
        "actor_advisor_id": actor_advisor_id or "",
        "actor_role":       actor_role,
        "created_at_utc":   created_at_utc,
        "payload_hash":     payload_hash,
    }
    return hashlib.sha256(_canonical_json(parts).encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteAuditEventRepository
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteAuditEventRepository:
    """
    Append-only audit event log per AdvisoryCase con hash chain.

    Tabla (de 0001_phase2_core_schema.sql):
        audit_events(
            event_id TEXT PK,
            case_id TEXT FK→advisory_cases,
            sequence INTEGER,
            event_type TEXT,
            actor_advisor_id TEXT NULL FK→advisors,
            actor_role TEXT,
            payload_json TEXT,
            payload_hash TEXT,
            previous_hash TEXT NULL,
            event_hash TEXT,
            created_at_utc TEXT,
            UNIQUE(case_id, sequence)
        )

    Operaciones:
        append(...)       — crea un nuevo evento con sequence siguiente.
        list_by_case(...) — devuelve eventos del caso ordenados por sequence asc.
        verify_chain(...) — recomputa hashes y valida sequence/previous_hash.

    No expone update ni delete.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    # ── append ───────────────────────────────────────────────────────────────

    def append(
        self,
        *,
        case_id: str,
        event_type: str,
        actor_role: str,
        payload: Mapping[str, Any] | None = None,
        actor_advisor_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Inserta un nuevo audit event al final de la cadena del case_id.

        Comportamiento:
            - sequence empieza en 1 y crece monotónicamente por case_id.
            - previous_hash = None si sequence == 1; en otro caso, event_hash
              del evento anterior.
            - payload_hash y event_hash se calculan determinísticamente.

        Raises:
            EntityNotFoundError: si case_id no existe.
            EntityConflictError: si hay colisión en UNIQUE(case_id, sequence)
                                 (race condition extremo) o FK violation.
        """
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            raise ValueError(
                f"payload debe ser un mapping (dict); recibido {type(payload).__name__}."
            )

        # ── 1. El case debe existir ─────────────────────────────────────────
        case_row = self._store._conn.execute(
            "SELECT case_id FROM advisory_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        if case_row is None:
            raise EntityNotFoundError(f"Case not found: {case_id!r}")

        # ── 2. sequence y previous_hash ─────────────────────────────────────
        last_row = self._store._conn.execute(
            """
            SELECT sequence, event_hash
            FROM audit_events
            WHERE case_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
        if last_row is None:
            new_sequence = 1
            previous_hash: str | None = None
        else:
            new_sequence = int(last_row["sequence"]) + 1
            previous_hash = last_row["event_hash"]

        # ── 3. Hashes ───────────────────────────────────────────────────────
        payload_dict = dict(payload)
        payload_json = _canonical_json(payload_dict)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        now = _now_utc()
        event_hash = compute_event_hash(
            previous_hash=previous_hash,
            sequence=new_sequence,
            event_type=event_type,
            actor_advisor_id=actor_advisor_id,
            actor_role=actor_role,
            created_at_utc=now,
            payload_hash=payload_hash,
        )

        # ── 4. ID e insert ──────────────────────────────────────────────────
        event_id = self._store._next_id("audit_event_")
        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO audit_events
                        (event_id, case_id, sequence, event_type,
                         actor_advisor_id, actor_role,
                         payload_json, payload_hash, previous_hash,
                         event_hash, created_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id, case_id, new_sequence, event_type,
                        actor_advisor_id, actor_role,
                        payload_json, payload_hash, previous_hash,
                        event_hash, now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc

        return {
            "event_id":         event_id,
            "case_id":          case_id,
            "sequence":         new_sequence,
            "event_type":       event_type,
            "actor_advisor_id": actor_advisor_id,
            "actor_role":       actor_role,
            "payload":          payload_dict,
            "payload_hash":     payload_hash,
            "previous_hash":    previous_hash,
            "event_hash":       event_hash,
            "created_at_utc":   now,
        }

    # ── list ─────────────────────────────────────────────────────────────────

    def list_by_case(self, case_id: str) -> list[dict[str, Any]]:
        """Devuelve eventos del caso en orden de sequence ascendente."""
        rows = self._store._conn.execute(
            """
            SELECT event_id, case_id, sequence, event_type,
                   actor_advisor_id, actor_role,
                   payload_json, payload_hash, previous_hash,
                   event_hash, created_at_utc
            FROM audit_events
            WHERE case_id = ?
            ORDER BY sequence ASC
            """,
            (case_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ── verify ───────────────────────────────────────────────────────────────

    def verify_chain(self, case_id: str) -> dict[str, Any]:
        """
        Recomputa hashes y valida sequence/previous_hash para la cadena del caso.

        Devuelve dict con:
            is_intact:              bool
            total_events:           int
            first_broken_sequence:  int | None
            message:                str

        Reglas:
            - Cadena vacía (0 eventos)            → is_intact=True
            - sequence debe ser 1..N sin gaps      → false si hay gap
            - previous_hash debe encadenar         → false si no coincide
            - payload_hash recomputado == stored   → false si payload manipulado
            - event_hash recomputado == stored     → false si metadata manipulada
        """
        rows = self._store._conn.execute(
            """
            SELECT event_id, case_id, sequence, event_type,
                   actor_advisor_id, actor_role,
                   payload_json, payload_hash, previous_hash,
                   event_hash, created_at_utc
            FROM audit_events
            WHERE case_id = ?
            ORDER BY sequence ASC
            """,
            (case_id,),
        ).fetchall()

        if not rows:
            return {
                "is_intact":             True,
                "total_events":          0,
                "first_broken_sequence": None,
                "message":               "No audit events for this case.",
            }

        expected_previous_hash: str | None = None
        total = len(rows)

        for i, row in enumerate(rows):
            expected_seq = i + 1
            actual_seq = int(row["sequence"])

            # ── sequence 1..N sin gaps ─────────────────────────────────────
            if actual_seq != expected_seq:
                return {
                    "is_intact":             False,
                    "total_events":          total,
                    "first_broken_sequence": actual_seq,
                    "message": (
                        f"Sequence mismatch at position {expected_seq}: "
                        f"found sequence={actual_seq}."
                    ),
                }

            # ── previous_hash encadena con event_hash anterior ─────────────
            if row["previous_hash"] != expected_previous_hash:
                return {
                    "is_intact":             False,
                    "total_events":          total,
                    "first_broken_sequence": actual_seq,
                    "message": (
                        f"previous_hash mismatch at sequence {actual_seq}."
                    ),
                }

            # ── payload_hash recomputado ───────────────────────────────────
            try:
                payload_obj = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                return {
                    "is_intact":             False,
                    "total_events":          total,
                    "first_broken_sequence": actual_seq,
                    "message": (
                        f"payload_json is not valid JSON at sequence {actual_seq}."
                    ),
                }
            if not isinstance(payload_obj, dict):
                return {
                    "is_intact":             False,
                    "total_events":          total,
                    "first_broken_sequence": actual_seq,
                    "message": (
                        f"payload_json is not a JSON object at sequence {actual_seq}."
                    ),
                }
            recomputed_payload_hash = hashlib.sha256(
                _canonical_json(payload_obj).encode("utf-8")
            ).hexdigest()
            if recomputed_payload_hash != row["payload_hash"]:
                return {
                    "is_intact":             False,
                    "total_events":          total,
                    "first_broken_sequence": actual_seq,
                    "message": (
                        f"payload_hash mismatch at sequence {actual_seq}."
                    ),
                }

            # ── event_hash recomputado ─────────────────────────────────────
            recomputed_event_hash = compute_event_hash(
                previous_hash=row["previous_hash"],
                sequence=actual_seq,
                event_type=row["event_type"],
                actor_advisor_id=row["actor_advisor_id"],
                actor_role=row["actor_role"],
                created_at_utc=row["created_at_utc"],
                payload_hash=row["payload_hash"],
            )
            if recomputed_event_hash != row["event_hash"]:
                return {
                    "is_intact":             False,
                    "total_events":          total,
                    "first_broken_sequence": actual_seq,
                    "message": (
                        f"event_hash mismatch at sequence {actual_seq}."
                    ),
                }

            expected_previous_hash = row["event_hash"]

        return {
            "is_intact":             True,
            "total_events":          total,
            "first_broken_sequence": None,
            "message":               f"Chain verified for {total} event(s).",
        }

    # ── row mapper ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id":         row["event_id"],
            "case_id":          row["case_id"],
            "sequence":         int(row["sequence"]),
            "event_type":       row["event_type"],
            "actor_advisor_id": row["actor_advisor_id"],
            "actor_role":       row["actor_role"],
            "payload":          json.loads(row["payload_json"]),
            "payload_hash":     row["payload_hash"],
            "previous_hash":    row["previous_hash"],
            "event_hash":       row["event_hash"],
            "created_at_utc":   row["created_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# AIRequestLog — constants, redaction, repository
# ─────────────────────────────────────────────────────────────────────────────
#
# Logging trazable de cada llamada a IA: qué endpoint la disparó, qué modelo
# y prompt_version se usaron, payload (redactado) que se mandó, respuesta cruda
# capturada (si la hubo) y un input_hash sobre el original para correlación
# sin necesidad de exponer texto libre del cliente.
#
# Limitaciones documentadas:
#   - No hay cifrado at-rest (SQLite plain file).
#   - No hay retention / pruning de logs.
#   - No hay prompt registry formal: `prompt_version` es un string libre que
#     el endpoint declara.
#   - El log queda case-scoped solo si el caller pasa explícitamente case_id
#     (los endpoints /ai/* actuales no son case-scoped todavía).
#   - La redacción es por allowlist + denylist explícita; tipos no reconocidos
#     se recursan pero los strings se evalúan contra heurísticas defensivas.
# ─────────────────────────────────────────────────────────────────────────────


ALLOWED_AI_LOG_STATUSES: frozenset[str] = frozenset(
    {"parsed_ok", "parse_error", "validation_error", "api_error"}
)


# Campos estructurados conocidos — se conservan en claro porque no contienen
# texto libre ni datos identificatorios fuertes. Esto cubre los inputs típicos
# de los endpoints /ai/* en Fase 2.
_AI_LOG_STRUCTURED_KEYS: frozenset[str] = frozenset({
    "age",
    "risk_tolerance_score",
    "risk_capacity_score",
    "liquidity_need_score",
    "liquidity_needs",
    "investment_horizon_years",
    "max_acceptable_drawdown_pct",
    "investment_experience",
    "income_stability",
    "needs_income",
    "net_worth",
    "net_worth_usd",
    "liquid_net_worth",
    "liquid_net_worth_usd",
    "annual_income_usd",
    "jurisdiction",
    "preferred_currency",
    "investment_objective",
    "prefers_simple_products",
    "profile",
    "model",
    "prompt_version",
    "endpoint",
    "allowed_instrument_types",
    "excluded_instrument_types",
    "currency",
    "country",
    "entity",
    "hard_dollar_only",
    "esg_strictness_level",
    "esg_exclusions",
    "esg_preferences",
})


# Campos siempre redactados — texto libre o blobs de contexto cuyo contenido
# puede arrastrar PII / opiniones sensibles del cliente.
_AI_LOG_REDACTED_KEYS: frozenset[str] = frozenset({
    "natural_language_preferences",
    "open_investment_goal",
    "open_risk_reaction",
    "open_past_experience",
    "open_concerns",
    "kyc_context",
    "previous_profile_analysis",
    # Contexto patrimonial/fiscal informativo (DD-017 ext.): texto libre que
    # puede nombrar bancos, brokers o situación fiscal del cliente — PII.
    # Los montos (held_away_investments_usd, total_liabilities_usd) son
    # numéricos y se conservan, igual que net_worth.
    "held_away_notes",
    "tax_status",
})


# Heurística de longitud: strings con más de N chars y NO en allowlist se
# redactan. Pensado para atrapar texto libre que no aparezca explícitamente
# en _AI_LOG_REDACTED_KEYS (defensa en profundidad).
_AI_LOG_FREE_TEXT_MIN_LEN: int = 80


def _hash_short_client_id(client_id: str) -> str:
    """Hash corto determinístico de un client_id; útil para correlación sin PII."""
    digest = hashlib.sha256(client_id.encode("utf-8")).hexdigest()
    return f"client_{digest[:8]}"


def _redact_string(value: str) -> str:
    """Reemplaza un string libre con su longitud nominal."""
    return f"<REDACTED:text_{len(value)}_chars>"


def _looks_like_api_key(value: str) -> bool:
    """
    Heurística para detectar API keys que jamás deberían persistirse.
    Cubre claves OpenAI ('sk-...'), tokens 'Bearer ...' y prefijos comunes.
    """
    s = value.strip()
    if len(s) < 20:
        return False
    lower = s.lower()
    return (
        s.startswith("sk-")
        or s.startswith("sk_")
        or s.startswith("pk-")
        or lower.startswith("bearer ")
        or lower.startswith("api_key=")
        or lower.startswith("token=")
    )


def _redact_value(key: str | None, value: Any) -> Any:
    """
    Aplica la política de redacción a un (key, value).

    Reglas:
        - value es dict  → recurse con `redact_ai_input`.
        - value es list  → redactar cada elemento (sin key context).
        - key == 'client_id' (str) → hash corto.
        - key en _AI_LOG_REDACTED_KEYS:
            * str  → `<REDACTED:text_N_chars>`
            * dict → recurse (pero se preserva la forma)
            * list → redactar cada elemento
            * None → None
            * otro → `<REDACTED:non_str>` (defensivo)
        - key en _AI_LOG_STRUCTURED_KEYS → conservar tal cual.
        - value es str que parece API key → siempre redactar.
        - value es str "largo" (>= _AI_LOG_FREE_TEXT_MIN_LEN) y key NO en
          allowlist → redactar.
        - Otros (números, bool, None, strings cortos no sensibles) → conservar.
    """
    if isinstance(value, dict):
        return redact_ai_input(value)

    if isinstance(value, list):
        return [_redact_value(None, item) for item in value]

    if key == "client_id" and isinstance(value, str):
        return _hash_short_client_id(value)

    if key in _AI_LOG_REDACTED_KEYS:
        if isinstance(value, str):
            return _redact_string(value)
        if value is None:
            return None
        return "<REDACTED:non_str>"

    if isinstance(value, str):
        if _looks_like_api_key(value):
            return _redact_string(value)
        if key not in _AI_LOG_STRUCTURED_KEYS and len(value) >= _AI_LOG_FREE_TEXT_MIN_LEN:
            return _redact_string(value)
        return value

    # números, bool, None → conservar
    return value


def redact_ai_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    """
    Devuelve una copia del payload con campos sensibles redactados.

    Política:
        - Estructura preservada (dict in / dict out, mismas claves top-level).
        - Texto libre conocido (open_*, natural_language_preferences,
          kyc_context, previous_profile_analysis) → `<REDACTED:text_N_chars>`.
        - client_id → `client_<sha256[:8]>` (correlación sin PII).
        - API keys (sk-, Bearer ...) → siempre redactadas (defensa).
        - Strings largos en keys no whitelisted → redactados.
        - Numéricos, bools y None → conservados.

    No modifica el payload original.
    """
    if not isinstance(payload, Mapping):
        raise ValueError(
            f"redact_ai_input requiere un mapping; recibido {type(payload).__name__}."
        )
    out: dict[str, Any] = {}
    for key, value in payload.items():
        out[str(key)] = _redact_value(str(key), value)
    return out


def compute_input_hash(payload: Mapping[str, Any]) -> str:
    """SHA-256 hex digest del payload original (canonical JSON)."""
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


# Campos de la RESPUESTA del modelo que se redactan siempre: texto libre
# generado que puede citar las respuestas abiertas del cliente (open_*,
# preferencias) y re-introducir PII al log por la puerta del output (I-022 ext.
# 2026-07). Las claves estructuradas (preliminary_profile, confidence, flags)
# se conservan: son el valor de auditoría del log.
_AI_LOG_OUTPUT_REDACTED_KEYS: frozenset[str] = frozenset({
    "contradictions",
    "remaining_contradictions",
    "follow_up_questions",
    "advisor_notes",
    "profile_change_reason",
    "summary",
    "rationale",
    "reasoning",
})


def _fully_redact(value: Any) -> Any:
    """
    Redacción total preservando estructura: strings → placeholder con longitud,
    dicts/lists → recursión, números/bools/None → se conservan (no son texto).
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, list):
        return [_fully_redact(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _fully_redact(v) for k, v in value.items()}
    return value


def _redact_output_value(key: str | None, value: Any) -> Any:
    """
    Política de redacción para la RESPUESTA del modelo.

    - key en _AI_LOG_OUTPUT_REDACTED_KEYS → redacción total (los elementos de
      una lista de contradicciones se redactan aunque sean cortos: citan al
      cliente).
    - dict/list → recursión con esta misma política.
    - resto → política base de input (_redact_value): hash de client_id,
      API keys, heurística de longitud para texto libre no anticipado.
    """
    if key in _AI_LOG_OUTPUT_REDACTED_KEYS:
        return _fully_redact(value)
    if isinstance(value, dict):
        return redact_ai_output(value)
    if isinstance(value, list):
        return [_redact_output_value(None, item) for item in value]
    return _redact_value(key, value)


def redact_ai_output(payload: Mapping[str, Any]) -> dict[str, Any]:
    """
    Redacta la respuesta cruda del modelo antes de persistirla en
    `ai_request_logs.raw_response_json` (I-022 extendido al output).

    Igual contrato que `redact_ai_input`: dict in / dict out, estructura
    top-level preservada, no muta el original.
    """
    if not isinstance(payload, Mapping):
        raise ValueError(
            f"redact_ai_output requiere un mapping; recibido {type(payload).__name__}."
        )
    out: dict[str, Any] = {}
    for key, value in payload.items():
        out[str(key)] = _redact_output_value(str(key), value)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteAIRequestLogRepository
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteAIRequestLogRepository:
    """
    Append-only log de llamadas a IA.

    Tabla (de 0001_phase2_core_schema.sql):
        ai_request_logs(
            request_id TEXT PK,
            case_id TEXT NULL FK→advisory_cases,
            requested_by_advisor_id TEXT NULL FK→advisors,
            endpoint TEXT,
            model TEXT,
            prompt_version TEXT,
            input_redacted_json TEXT,
            input_hash TEXT,
            raw_response_json TEXT NULL,
            validation_status TEXT,
            latency_ms INTEGER NULL,
            prompt_tokens INTEGER NULL,
            completion_tokens INTEGER NULL,
            error_message TEXT NULL,
            created_at_utc TEXT
        )

    Operaciones:
        create(...)         — inserta un nuevo log.
        get(request_id)     — devuelve dict | None.
        list_by_case(...)   — lista los logs de un case, ordenados por
                              created_at_utc asc (luego request_id asc).
        list_all(limit=...) — lista los logs (limit opcional).

    No expone update ni delete.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        endpoint: str,
        model: str,
        prompt_version: str,
        input_redacted: Mapping[str, Any],
        input_hash: str,
        validation_status: str,
        case_id: str | None = None,
        requested_by_advisor_id: str | None = None,
        raw_response: Mapping[str, Any] | None = None,
        latency_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        """
        Inserta un nuevo AIRequestLog y devuelve el dict equivalente.

        Raises:
            EntityConflictError: PK collision o FK violation.
        """
        if validation_status not in ALLOWED_AI_LOG_STATUSES:
            raise ValueError(
                f"validation_status inválido: {validation_status!r}. "
                f"Permitidos: {sorted(ALLOWED_AI_LOG_STATUSES)}."
            )
        request_id = self._store._next_id("ai_request_")
        now = _now_utc()

        input_redacted_json = _canonical_json(dict(input_redacted))
        # I-022 (ext. output): la respuesta del modelo se redacta SIEMPRE acá,
        # a nivel repositorio, para que ningún caller (endpoints de casos,
        # backfill admin) pueda persistir texto libre del cliente citado por
        # el modelo.
        raw_response_redacted: dict[str, Any] | None = None
        raw_response_json: str | None = None
        if raw_response is not None:
            raw_response_redacted = redact_ai_output(raw_response)
            raw_response_json = _canonical_json(raw_response_redacted)

        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO ai_request_logs
                        (request_id, case_id, requested_by_advisor_id,
                         endpoint, model, prompt_version,
                         input_redacted_json, input_hash,
                         raw_response_json, validation_status,
                         latency_ms, prompt_tokens, completion_tokens,
                         error_message, created_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id, case_id, requested_by_advisor_id,
                        endpoint, model, prompt_version,
                        input_redacted_json, input_hash,
                        raw_response_json, validation_status,
                        latency_ms, prompt_tokens, completion_tokens,
                        error_message, now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc

        return {
            "request_id":              request_id,
            "case_id":                 case_id,
            "requested_by_advisor_id": requested_by_advisor_id,
            "endpoint":                endpoint,
            "model":                   model,
            "prompt_version":          prompt_version,
            "input_redacted":          dict(input_redacted),
            "input_hash":              input_hash,
            "raw_response":            raw_response_redacted,
            "validation_status":       validation_status,
            "latency_ms":              latency_ms,
            "prompt_tokens":           prompt_tokens,
            "completion_tokens":       completion_tokens,
            "error_message":           error_message,
            "created_at_utc":          now,
        }

    def get(self, request_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT request_id, case_id, requested_by_advisor_id,
                   endpoint, model, prompt_version,
                   input_redacted_json, input_hash,
                   raw_response_json, validation_status,
                   latency_ms, prompt_tokens, completion_tokens,
                   error_message, created_at_utc
            FROM ai_request_logs WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_by_case(self, case_id: str) -> list[dict[str, Any]]:
        """
        Lista los logs del caso. Orden: created_at_utc asc, request_id asc
        como tiebreaker determinístico.
        """
        rows = self._store._conn.execute(
            """
            SELECT request_id, case_id, requested_by_advisor_id,
                   endpoint, model, prompt_version,
                   input_redacted_json, input_hash,
                   raw_response_json, validation_status,
                   latency_ms, prompt_tokens, completion_tokens,
                   error_message, created_at_utc
            FROM ai_request_logs
            WHERE case_id = ?
            ORDER BY created_at_utc ASC, request_id ASC
            """,
            (case_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_all(self, limit: int | None = None) -> list[dict[str, Any]]:
        """
        Lista todos los logs ordenados por created_at_utc asc, request_id asc.
        Si limit se provee, aplica un LIMIT simple.
        """
        if limit is not None and (not isinstance(limit, int) or limit < 0):
            raise ValueError(f"limit debe ser int >= 0; recibido {limit!r}.")
        sql = """
            SELECT request_id, case_id, requested_by_advisor_id,
                   endpoint, model, prompt_version,
                   input_redacted_json, input_hash,
                   raw_response_json, validation_status,
                   latency_ms, prompt_tokens, completion_tokens,
                   error_message, created_at_utc
            FROM ai_request_logs
            ORDER BY created_at_utc ASC, request_id ASC
        """
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        rows = self._store._conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        raw_resp = row["raw_response_json"]
        raw_response: dict[str, Any] | None
        if raw_resp is None:
            raw_response = None
        else:
            try:
                parsed = json.loads(raw_resp)
            except json.JSONDecodeError:
                # No debería pasar — siempre se serializa via _canonical_json.
                # Defensivo: devolvemos un wrapper para no romper la lectura.
                parsed = {"__raw_response_parse_error__": True}
            raw_response = parsed if isinstance(parsed, dict) else {"value": parsed}

        return {
            "request_id":              row["request_id"],
            "case_id":                 row["case_id"],
            "requested_by_advisor_id": row["requested_by_advisor_id"],
            "endpoint":                row["endpoint"],
            "model":                   row["model"],
            "prompt_version":          row["prompt_version"],
            "input_redacted":          json.loads(row["input_redacted_json"]),
            "input_hash":              row["input_hash"],
            "raw_response":            raw_response,
            "validation_status":       row["validation_status"],
            "latency_ms":              row["latency_ms"],
            "prompt_tokens":           row["prompt_tokens"],
            "completion_tokens":       row["completion_tokens"],
            "error_message":           row["error_message"],
            "created_at_utc":          row["created_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteKYCSubmissionRepository — Fase 2 Commit 8 (case-scoped KYC)
# ─────────────────────────────────────────────────────────────────────────────
#
# Cada submission queda fija en el tiempo. La versión más reciente del case
# se sigue desde advisory_cases.current_kyc_submission_id (el endpoint
# actualiza ese puntero después del insert).
#
# Limitaciones:
#   - No expone update / delete: cada modificación es una nueva submission
#     con version siguiente.
#   - El payload se serializa con canonical JSON para que payload_hash sea
#     reproducible. Si una migración futura quisiera cambiar el formato,
#     habría que versionar el algoritmo de hashing.
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteKYCSubmissionRepository:
    """
    Persiste y lee KYCSubmissions desde `kyc_submissions`.

    Tabla (de 0002_kyc_submissions.sql):
        kyc_submissions(
            kyc_submission_id TEXT PK,
            case_id TEXT NOT NULL FK→advisory_cases,
            version INTEGER NOT NULL,
            submitted_by_advisor_id TEXT NULL FK→advisors,
            payload_json TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            UNIQUE(case_id, version)
        )

    Operaciones:
        create(...)         — inserta version siguiente para el case_id dado.
        get(submission_id)  — dict | None.
        list_by_case(...)   — ordenado por version asc.

    No expone update ni delete.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        case_id: str,
        payload: Mapping[str, Any],
        submitted_by_advisor_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Inserta una nueva submission. Calcula version = MAX(version)+1 por
        case_id; payload_hash sobre el canonical JSON.

        Raises:
            EntityNotFoundError: si el case no existe.
            EntityConflictError: PK collision (extremadamente raro) o FK
                violation en submitted_by_advisor_id (el caller debe
                pre-validar el case_id; FK del case se traduce igualmente).
            ValueError: si payload no es un mapping.
        """
        if not isinstance(payload, Mapping):
            raise ValueError(
                f"payload debe ser un mapping (dict); recibido {type(payload).__name__}."
            )

        # ── 1. case debe existir (defensa explícita; la FK abajo también lo
        #       atrapa pero un error claro es mejor que el mensaje SQLite).
        case_row = self._store._conn.execute(
            "SELECT case_id FROM advisory_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        if case_row is None:
            raise EntityNotFoundError(f"Case not found: {case_id!r}")

        # ── 2. sequence (version) siguiente ─────────────────────────────────
        last_row = self._store._conn.execute(
            "SELECT MAX(version) FROM kyc_submissions WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        last_version = last_row[0] if last_row and last_row[0] is not None else 0
        new_version = int(last_version) + 1

        # ── 3. payload canonical + hash ─────────────────────────────────────
        payload_dict = dict(payload)
        payload_json = _canonical_json(payload_dict)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        now = _now_utc()

        # ── 4. ID e insert ──────────────────────────────────────────────────
        submission_id = self._store._next_id("kyc_submission_")
        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO kyc_submissions
                        (kyc_submission_id, case_id, version,
                         submitted_by_advisor_id,
                         payload_json, payload_hash, created_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        submission_id, case_id, new_version,
                        submitted_by_advisor_id,
                        payload_json, payload_hash, now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc

        return {
            "kyc_submission_id":       submission_id,
            "case_id":                 case_id,
            "version":                 new_version,
            "submitted_by_advisor_id": submitted_by_advisor_id,
            "payload":                 payload_dict,
            "payload_hash":            payload_hash,
            "created_at_utc":          now,
        }

    def get(self, kyc_submission_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT kyc_submission_id, case_id, version,
                   submitted_by_advisor_id,
                   payload_json, payload_hash, created_at_utc
            FROM kyc_submissions WHERE kyc_submission_id = ?
            """,
            (kyc_submission_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_by_case(self, case_id: str) -> list[dict[str, Any]]:
        """Lista las submissions del case ordenadas por version ascendente."""
        rows = self._store._conn.execute(
            """
            SELECT kyc_submission_id, case_id, version,
                   submitted_by_advisor_id,
                   payload_json, payload_hash, created_at_utc
            FROM kyc_submissions
            WHERE case_id = ?
            ORDER BY version ASC
            """,
            (case_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "kyc_submission_id":       row["kyc_submission_id"],
            "case_id":                 row["case_id"],
            "version":                 int(row["version"]),
            "submitted_by_advisor_id": row["submitted_by_advisor_id"],
            "payload":                 json.loads(row["payload_json"]),
            "payload_hash":            row["payload_hash"],
            "created_at_utc":          row["created_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# AIProfileAnalysis — Fase 2 Commit 9 (case-scoped AI profile analysis)
# ─────────────────────────────────────────────────────────────────────────────
#
# Cada análisis vincula:
#   - case_id            (AdvisoryCase)
#   - kyc_submission_id  (KYCSubmission concreta del case)
#   - ai_request_log_id  (AIRequestLog que registró la llamada — opcional)
#
# Limitaciones:
#   - No expone update / delete: cada análisis nuevo es un nuevo row.
#   - result_json se persiste en canonical JSON; preliminary_profile y
#     confidence son extractos denormalizados del result para indexar.
#   - analysis_type se modela como string libre a nivel DB; la API restringe
#     a {initial, follow_up} (este commit solo expone "initial").
# ─────────────────────────────────────────────────────────────────────────────


ALLOWED_PROFILE_ANALYSIS_TYPES: frozenset[str] = frozenset({"initial", "follow_up"})


class SQLiteAIProfileAnalysisRepository:
    """
    Persiste y lee análisis IA de perfil case-scoped sobre la tabla
    `ai_profile_analyses` (de migration 0003).

    Esquema:
        ai_profile_analyses(
            analysis_id TEXT PK,
            case_id TEXT NOT NULL FK→advisory_cases,
            kyc_submission_id TEXT NOT NULL FK→kyc_submissions,
            ai_request_log_id TEXT NULL FK→ai_request_logs,
            analysis_type TEXT NOT NULL,
            preliminary_profile TEXT NULL,
            confidence REAL NULL,
            result_json TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        )

    Operaciones:
        create(...)         — inserta un nuevo análisis.
        get(analysis_id)    — dict | None.
        list_by_case(...)   — orden `created_at_utc ASC, analysis_id ASC`.

    No expone update ni delete.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        case_id: str,
        kyc_submission_id: str,
        analysis_type: str,
        result: Mapping[str, Any],
        preliminary_profile: str | None = None,
        confidence: float | None = None,
        ai_request_log_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Inserta un nuevo análisis. result se serializa canonical.

        Raises:
            EntityConflictError: PK collision o FK violation (case_id,
                kyc_submission_id, ai_request_log_id deben existir).
            ValueError: si result no es mapping.
        """
        if not isinstance(result, Mapping):
            raise ValueError(
                f"result debe ser un mapping (dict); recibido {type(result).__name__}."
            )

        result_dict = dict(result)
        result_json = _canonical_json(result_dict)
        now = _now_utc()
        analysis_id = self._store._next_id("ai_profile_analysis_")

        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO ai_profile_analyses
                        (analysis_id, case_id, kyc_submission_id,
                         ai_request_log_id, analysis_type,
                         preliminary_profile, confidence,
                         result_json, created_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        analysis_id, case_id, kyc_submission_id,
                        ai_request_log_id, analysis_type,
                        preliminary_profile,
                        float(confidence) if confidence is not None else None,
                        result_json, now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc

        return {
            "analysis_id":          analysis_id,
            "case_id":              case_id,
            "kyc_submission_id":    kyc_submission_id,
            "ai_request_log_id":    ai_request_log_id,
            "analysis_type":        analysis_type,
            "preliminary_profile":  preliminary_profile,
            "confidence":           float(confidence) if confidence is not None else None,
            "result":               result_dict,
            "created_at_utc":       now,
        }

    def get(self, analysis_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT analysis_id, case_id, kyc_submission_id,
                   ai_request_log_id, analysis_type,
                   preliminary_profile, confidence,
                   result_json, created_at_utc
            FROM ai_profile_analyses WHERE analysis_id = ?
            """,
            (analysis_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_by_case(self, case_id: str) -> list[dict[str, Any]]:
        """Lista análisis del case ordenados por created_at_utc + analysis_id asc."""
        rows = self._store._conn.execute(
            """
            SELECT analysis_id, case_id, kyc_submission_id,
                   ai_request_log_id, analysis_type,
                   preliminary_profile, confidence,
                   result_json, created_at_utc
            FROM ai_profile_analyses
            WHERE case_id = ?
            ORDER BY created_at_utc ASC, analysis_id ASC
            """,
            (case_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        confidence = row["confidence"]
        return {
            "analysis_id":          row["analysis_id"],
            "case_id":              row["case_id"],
            "kyc_submission_id":    row["kyc_submission_id"],
            "ai_request_log_id":    row["ai_request_log_id"],
            "analysis_type":        row["analysis_type"],
            "preliminary_profile":  row["preliminary_profile"],
            "confidence":           float(confidence) if confidence is not None else None,
            "result":               json.loads(row["result_json"]),
            "created_at_utc":       row["created_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# AdvisorProfileApproval — Fase 2 Commit 10 (case-scoped advisor decision)
# ─────────────────────────────────────────────────────────────────────────────
#
# Decisión humana del asesor sobre el perfil de riesgo de un AdvisoryCase.
# Cada decisión queda anclada al case, opcionalmente al ai_profile_analysis
# y a la kyc_submission vigente.
#
# Política is_current (mantenida por el endpoint, no por el repo):
#   - approve / modify  → is_current=1; las approvals anteriores del mismo
#     case se marcan is_current=0 vía mark_previous_not_current.
#   - reject            → is_current=0 desde el insert. No pisa una approval
#     vigente previa (current_approved_profile_id del case se mantiene).
# ─────────────────────────────────────────────────────────────────────────────


ALLOWED_PROFILE_APPROVAL_DECISIONS: frozenset[str] = frozenset(
    {"approve", "modify", "reject"}
)


class SQLiteAdvisorProfileApprovalCaseRepository:
    """
    Persiste y lee approvals case-scoped sobre `advisor_profile_approvals`
    (migration 0004).

    Esquema (resumen):
        advisor_profile_approvals(
            approval_id TEXT PK,
            case_id TEXT NOT NULL FK→advisory_cases,
            ai_profile_analysis_id TEXT NULL FK→ai_profile_analyses,
            kyc_submission_id TEXT NULL FK→kyc_submissions,
            advisor_id TEXT NULL FK→advisors,
            proposed_profile TEXT NOT NULL,
            decision TEXT NOT NULL,
            approved_profile TEXT NULL,
            rationale TEXT NOT NULL,
            source TEXT NOT NULL,
            is_current INTEGER NOT NULL DEFAULT 1,
            created_at_utc TEXT NOT NULL
        )

    NB: nombre `SQLiteAdvisorProfileApprovalCaseRepository` para distinguir
    del `SQLiteAdvisorProfileApprovalRepository` legacy (Phase 1, sobre
    `records` table client-scoped).

    Operaciones:
        create(...)                       — inserta nuevo approval.
        get(approval_id)                  — dict | None.
        list_by_case(case_id)             — orden created_at_utc asc, id asc.
        mark_previous_not_current(case_id, exclude_id=None)
                                          — bulk update is_current=0 a todos
                                            los approvals del case excepto
                                            opcionalmente `exclude_id`.

    No expone update/delete arbitrarios; mark_previous_not_current es la
    única mutación permitida (necesaria para mantener is_current consistente).
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        case_id: str,
        proposed_profile: str,
        decision: str,
        rationale: str,
        source: str = "manual",
        ai_profile_analysis_id: str | None = None,
        kyc_submission_id: str | None = None,
        advisor_id: str | None = None,
        approved_profile: str | None = None,
        is_current: bool = True,
    ) -> dict[str, Any]:
        """
        Inserta un approval. Validaciones de negocio (perfil válido, coherencia
        decision/approved_profile) se hacen en el endpoint / schema; este
        repo solo valida shape mínimo y FKs.

        Raises:
            EntityConflictError: PK collision o FK violation.
            ValueError: si decision no está en ALLOWED_PROFILE_APPROVAL_DECISIONS.
        """
        if decision not in ALLOWED_PROFILE_APPROVAL_DECISIONS:
            raise ValueError(
                f"decision inválida: {decision!r}. "
                f"Permitidas: {sorted(ALLOWED_PROFILE_APPROVAL_DECISIONS)}."
            )

        approval_id = self._store._next_id("advisor_profile_approval_")
        now = _now_utc()
        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO advisor_profile_approvals
                        (approval_id, case_id,
                         ai_profile_analysis_id, kyc_submission_id, advisor_id,
                         proposed_profile, decision, approved_profile,
                         rationale, source, is_current, created_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        approval_id, case_id,
                        ai_profile_analysis_id, kyc_submission_id, advisor_id,
                        proposed_profile, decision, approved_profile,
                        rationale, source, 1 if is_current else 0, now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc

        return {
            "approval_id":            approval_id,
            "case_id":                case_id,
            "ai_profile_analysis_id": ai_profile_analysis_id,
            "kyc_submission_id":      kyc_submission_id,
            "advisor_id":             advisor_id,
            "proposed_profile":       proposed_profile,
            "decision":               decision,
            "approved_profile":       approved_profile,
            "rationale":              rationale,
            "source":                 source,
            "is_current":             bool(is_current),
            "created_at_utc":         now,
        }

    def get(self, approval_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT approval_id, case_id,
                   ai_profile_analysis_id, kyc_submission_id, advisor_id,
                   proposed_profile, decision, approved_profile,
                   rationale, source, is_current, created_at_utc
            FROM advisor_profile_approvals WHERE approval_id = ?
            """,
            (approval_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_by_case(self, case_id: str) -> list[dict[str, Any]]:
        """Lista approvals del case ordenadas por created_at_utc, approval_id asc."""
        rows = self._store._conn.execute(
            """
            SELECT approval_id, case_id,
                   ai_profile_analysis_id, kyc_submission_id, advisor_id,
                   proposed_profile, decision, approved_profile,
                   rationale, source, is_current, created_at_utc
            FROM advisor_profile_approvals
            WHERE case_id = ?
            ORDER BY created_at_utc ASC, approval_id ASC
            """,
            (case_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_current_for_case(self, case_id: str) -> dict[str, Any] | None:
        """
        Devuelve el approval `is_current=1` más reciente del case, o None.

        Útil para el summary endpoint, donde `case.current_approved_profile_id`
        puede no estar materializado (e.g., el último approval fue reject).
        """
        row = self._store._conn.execute(
            """
            SELECT approval_id, case_id,
                   ai_profile_analysis_id, kyc_submission_id, advisor_id,
                   proposed_profile, decision, approved_profile,
                   rationale, source, is_current, created_at_utc
            FROM advisor_profile_approvals
            WHERE case_id = ? AND is_current = 1
            ORDER BY created_at_utc DESC, approval_id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def mark_previous_not_current(
        self, case_id: str, exclude_id: str | None = None
    ) -> int:
        """
        Marca is_current=0 a todos los approvals del case excepto `exclude_id`
        (típicamente el approval recién creado que debe quedar is_current=1).

        Devuelve la cantidad de rows afectadas. No falla si el case no
        existe (devuelve 0).
        """
        if exclude_id is None:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE advisor_profile_approvals
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1
                    """,
                    (case_id,),
                )
        else:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE advisor_profile_approvals
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1 AND approval_id != ?
                    """,
                    (case_id, exclude_id),
                )
        return cur.rowcount if cur.rowcount is not None else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "approval_id":            row["approval_id"],
            "case_id":                row["case_id"],
            "ai_profile_analysis_id": row["ai_profile_analysis_id"],
            "kyc_submission_id":      row["kyc_submission_id"],
            "advisor_id":             row["advisor_id"],
            "proposed_profile":       row["proposed_profile"],
            "decision":               row["decision"],
            "approved_profile":       row["approved_profile"],
            "rationale":              row["rationale"],
            "source":                 row["source"],
            "is_current":             bool(row["is_current"]),
            "created_at_utc":         row["created_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# CaseInvestmentPreference — Fase 2 Commit 11 (case-scoped preferences)
# ─────────────────────────────────────────────────────────────────────────────
#
# Preferencias estructuradas del cliente sobre instrumentos, ancladas a un
# AdvisoryCase. Pueden originarse manualmente (advisor las introduce) o por
# extracción IA desde lenguaje natural.
#
# is_current se mantiene desde el endpoint (vía mark_previous_not_current),
# no por triggers. Cada nuevo POST marca las previas =0 y la nueva =1.
# ─────────────────────────────────────────────────────────────────────────────


ALLOWED_INVESTMENT_PREFERENCE_SOURCES: frozenset[str] = frozenset(
    {"manual", "ai", "imported"}
)


class SQLiteCaseInvestmentPreferenceRepository:
    """
    Persiste y lee preferencias case-scoped sobre `case_investment_preferences`
    (migration 0005).

    Operaciones:
        create(...)                       — inserta nuevo registro.
        get(preference_id)                — dict | None.
        list_by_case(case_id)             — orden created_at_utc asc.
        mark_previous_not_current(case_id, exclude_id=None)
                                          — bulk is_current=0.

    No expone update / delete arbitrarios.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        case_id: str,
        source: str,
        structured_preferences: Mapping[str, Any],
        natural_language_preferences: str | None = None,
        ai_request_log_id: str | None = None,
        created_by_advisor_id: str | None = None,
        is_current: bool = True,
    ) -> dict[str, Any]:
        if source not in ALLOWED_INVESTMENT_PREFERENCE_SOURCES:
            raise ValueError(
                f"source inválido: {source!r}. "
                f"Permitidos: {sorted(ALLOWED_INVESTMENT_PREFERENCE_SOURCES)}."
            )
        if not isinstance(structured_preferences, Mapping):
            raise ValueError(
                "structured_preferences debe ser un mapping (dict); "
                f"recibido {type(structured_preferences).__name__}."
            )

        preference_id = self._store._next_id("case_investment_preference_")
        now = _now_utc()
        prefs_dict = dict(structured_preferences)
        prefs_json = _canonical_json(prefs_dict)

        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO case_investment_preferences
                        (preference_id, case_id, source,
                         natural_language_preferences,
                         structured_preferences_json,
                         ai_request_log_id, created_by_advisor_id,
                         created_at_utc, is_current)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        preference_id, case_id, source,
                        natural_language_preferences,
                        prefs_json,
                        ai_request_log_id, created_by_advisor_id,
                        now, 1 if is_current else 0,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc

        return {
            "preference_id":                preference_id,
            "case_id":                      case_id,
            "source":                       source,
            "natural_language_preferences": natural_language_preferences,
            "structured_preferences":       prefs_dict,
            "ai_request_log_id":            ai_request_log_id,
            "created_by_advisor_id":        created_by_advisor_id,
            "is_current":                   bool(is_current),
            "created_at_utc":               now,
        }

    def get(self, preference_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT preference_id, case_id, source,
                   natural_language_preferences,
                   structured_preferences_json,
                   ai_request_log_id, created_by_advisor_id,
                   created_at_utc, is_current
            FROM case_investment_preferences WHERE preference_id = ?
            """,
            (preference_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_by_case(self, case_id: str) -> list[dict[str, Any]]:
        rows = self._store._conn.execute(
            """
            SELECT preference_id, case_id, source,
                   natural_language_preferences,
                   structured_preferences_json,
                   ai_request_log_id, created_by_advisor_id,
                   created_at_utc, is_current
            FROM case_investment_preferences
            WHERE case_id = ?
            ORDER BY created_at_utc ASC, preference_id ASC
            """,
            (case_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_current_for_case(self, case_id: str) -> dict[str, Any] | None:
        """Devuelve la preference is_current=1 más reciente del case, o None."""
        row = self._store._conn.execute(
            """
            SELECT preference_id, case_id, source,
                   natural_language_preferences,
                   structured_preferences_json,
                   ai_request_log_id, created_by_advisor_id,
                   created_at_utc, is_current
            FROM case_investment_preferences
            WHERE case_id = ? AND is_current = 1
            ORDER BY created_at_utc DESC, preference_id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def mark_previous_not_current(
        self, case_id: str, exclude_id: str | None = None
    ) -> int:
        if exclude_id is None:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_investment_preferences
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1
                    """,
                    (case_id,),
                )
        else:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_investment_preferences
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1 AND preference_id != ?
                    """,
                    (case_id, exclude_id),
                )
        return cur.rowcount if cur.rowcount is not None else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "preference_id":                row["preference_id"],
            "case_id":                      row["case_id"],
            "source":                       row["source"],
            "natural_language_preferences": row["natural_language_preferences"],
            "structured_preferences":       json.loads(row["structured_preferences_json"]),
            "ai_request_log_id":            row["ai_request_log_id"],
            "created_by_advisor_id":        row["created_by_advisor_id"],
            "is_current":                   bool(row["is_current"]),
            "created_at_utc":               row["created_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# CaseUniverseFilterRun — Fase 2 Commit 11
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteCaseUniverseFilterRunRepository:
    """
    Persiste y lee filter runs sobre `case_universe_filter_runs` (migration 0005).

    Cada run captura el snapshot completo del resultado del filter engine:
    instruments elegibles, exclusiones, filtros aplicados, warnings y counts.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        case_id: str,
        source_universe: str,
        eligible_instruments: list[dict[str, Any]],
        exclusions: list[dict[str, Any]],
        applied_filters: list[str],
        warnings: list[str],
        eligible_count: int,
        excluded_count: int,
        total_count: int,
        preference_id: str | None = None,
        created_by_advisor_id: str | None = None,
        is_current: bool = True,
    ) -> dict[str, Any]:
        filter_run_id = self._store._next_id("case_universe_filter_run_")
        now = _now_utc()

        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO case_universe_filter_runs
                        (filter_run_id, case_id, preference_id,
                         source_universe,
                         eligible_instruments_json, exclusions_json,
                         applied_filters_json, warnings_json,
                         eligible_count, excluded_count, total_count,
                         created_by_advisor_id, created_at_utc, is_current)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        filter_run_id, case_id, preference_id,
                        source_universe,
                        _canonical_json({"items": eligible_instruments}),
                        _canonical_json({"items": exclusions}),
                        _canonical_json({"items": list(applied_filters)}),
                        _canonical_json({"items": list(warnings)}),
                        int(eligible_count), int(excluded_count), int(total_count),
                        created_by_advisor_id, now, 1 if is_current else 0,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc

        return {
            "filter_run_id":          filter_run_id,
            "case_id":                case_id,
            "preference_id":          preference_id,
            "source_universe":        source_universe,
            "eligible_instruments":   list(eligible_instruments),
            "exclusions":             list(exclusions),
            "applied_filters":        list(applied_filters),
            "warnings":               list(warnings),
            "eligible_count":         int(eligible_count),
            "excluded_count":         int(excluded_count),
            "total_count":            int(total_count),
            "created_by_advisor_id":  created_by_advisor_id,
            "is_current":             bool(is_current),
            "created_at_utc":         now,
        }

    def get(self, filter_run_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT filter_run_id, case_id, preference_id,
                   source_universe,
                   eligible_instruments_json, exclusions_json,
                   applied_filters_json, warnings_json,
                   eligible_count, excluded_count, total_count,
                   created_by_advisor_id, created_at_utc, is_current
            FROM case_universe_filter_runs WHERE filter_run_id = ?
            """,
            (filter_run_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_by_case(self, case_id: str) -> list[dict[str, Any]]:
        rows = self._store._conn.execute(
            """
            SELECT filter_run_id, case_id, preference_id,
                   source_universe,
                   eligible_instruments_json, exclusions_json,
                   applied_filters_json, warnings_json,
                   eligible_count, excluded_count, total_count,
                   created_by_advisor_id, created_at_utc, is_current
            FROM case_universe_filter_runs
            WHERE case_id = ?
            ORDER BY created_at_utc ASC, filter_run_id ASC
            """,
            (case_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def mark_previous_not_current(
        self, case_id: str, exclude_id: str | None = None
    ) -> int:
        if exclude_id is None:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_universe_filter_runs
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1
                    """,
                    (case_id,),
                )
        else:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_universe_filter_runs
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1 AND filter_run_id != ?
                    """,
                    (case_id, exclude_id),
                )
        return cur.rowcount if cur.rowcount is not None else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "filter_run_id":          row["filter_run_id"],
            "case_id":                row["case_id"],
            "preference_id":          row["preference_id"],
            "source_universe":        row["source_universe"],
            "eligible_instruments":   json.loads(row["eligible_instruments_json"]).get("items", []),
            "exclusions":             json.loads(row["exclusions_json"]).get("items", []),
            "applied_filters":        json.loads(row["applied_filters_json"]).get("items", []),
            "warnings":               json.loads(row["warnings_json"]).get("items", []),
            "eligible_count":         int(row["eligible_count"]),
            "excluded_count":         int(row["excluded_count"]),
            "total_count":            int(row["total_count"]),
            "created_by_advisor_id":  row["created_by_advisor_id"],
            "is_current":             bool(row["is_current"]),
            "created_at_utc":         row["created_at_utc"],
        }

    def get_current_for_case(self, case_id: str) -> dict[str, Any] | None:
        """Devuelve el filter run is_current=1 más reciente del case, o None."""
        row = self._store._conn.execute(
            """
            SELECT filter_run_id, case_id, preference_id,
                   source_universe,
                   eligible_instruments_json, exclusions_json,
                   applied_filters_json, warnings_json,
                   eligible_count, excluded_count, total_count,
                   created_by_advisor_id, created_at_utc, is_current
            FROM case_universe_filter_runs
            WHERE case_id = ? AND is_current = 1
            ORDER BY created_at_utc DESC, filter_run_id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# CasePortfolioProposal — Fase 2 Commit 12 (case-scoped portfolio generation)
# ─────────────────────────────────────────────────────────────────────────────
#
# Snapshot completo de una propuesta generada por PortfolioGenerationCoordinator
# sobre el universo filtrado del case + RiskBudget construido desde el profile
# aprobado.
#
# Listas/dicts grandes (risk_budget, snapshots, candidates, warnings) van como
# canonical JSON. Para listas se usa el wrapper {"items": [...]} (mismo patrón
# que case_universe_filter_runs).
#
# Status posibles:
#   - completed
#   - blocked_insufficient_universe
#   - blocked_insufficient_diversification_capacity
#   - infeasible
# Alineados con /ai/filtered-portfolio-demo legacy.
# ─────────────────────────────────────────────────────────────────────────────


ALLOWED_PORTFOLIO_PROPOSAL_STATUSES: frozenset[str] = frozenset({
    "completed",
    "blocked_insufficient_universe",
    "blocked_insufficient_diversification_capacity",
    "infeasible",
})


class SQLiteCasePortfolioProposalRepository:
    """
    Persiste y lee proposals case-scoped sobre `case_portfolio_proposals`
    (migration 0006).

    Operaciones:
        create(...)                  — inserta nueva proposal.
        get(proposal_id)             — dict | None.
        list_by_case(case_id)        — orden created_at_utc asc, id asc.
        get_current_for_case(case_id) — is_current=1 más reciente o None.
        mark_previous_not_current(case_id, exclude_id=None)
                                     — bulk is_current=0.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        case_id: str,
        filter_run_id: str,
        profile_name: str,
        status: str,
        risk_budget: Mapping[str, Any],
        snapshots: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        warnings: list[str],
        approved_profile_id: str | None = None,
        created_by_advisor_id: str | None = None,
        is_current: bool = True,
    ) -> dict[str, Any]:
        if status not in ALLOWED_PORTFOLIO_PROPOSAL_STATUSES:
            raise ValueError(
                f"status inválido: {status!r}. "
                f"Permitidos: {sorted(ALLOWED_PORTFOLIO_PROPOSAL_STATUSES)}."
            )
        if not isinstance(risk_budget, Mapping):
            raise ValueError(
                f"risk_budget debe ser un mapping (dict); recibido {type(risk_budget).__name__}."
            )

        proposal_id = self._store._next_id("case_portfolio_proposal_")
        now = _now_utc()
        risk_budget_dict = dict(risk_budget)

        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO case_portfolio_proposals
                        (proposal_id, case_id, filter_run_id,
                         approved_profile_id, profile_name,
                         risk_budget_json, snapshots_json,
                         candidates_json, warnings_json,
                         status, created_by_advisor_id,
                         created_at_utc, is_current)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal_id, case_id, filter_run_id,
                        approved_profile_id, profile_name,
                        _canonical_json(risk_budget_dict),
                        _canonical_json({"items": list(snapshots)}),
                        _canonical_json({"items": list(candidates)}),
                        _canonical_json({"items": list(warnings)}),
                        status, created_by_advisor_id,
                        now, 1 if is_current else 0,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc

        return {
            "proposal_id":            proposal_id,
            "case_id":                case_id,
            "filter_run_id":          filter_run_id,
            "approved_profile_id":    approved_profile_id,
            "profile_name":           profile_name,
            "risk_budget":            risk_budget_dict,
            "snapshots":              list(snapshots),
            "candidates":             list(candidates),
            "warnings":               list(warnings),
            "status":                 status,
            "created_by_advisor_id":  created_by_advisor_id,
            "is_current":             bool(is_current),
            "created_at_utc":         now,
        }

    def get(self, proposal_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT proposal_id, case_id, filter_run_id,
                   approved_profile_id, profile_name,
                   risk_budget_json, snapshots_json,
                   candidates_json, warnings_json,
                   status, created_by_advisor_id,
                   created_at_utc, is_current
            FROM case_portfolio_proposals WHERE proposal_id = ?
            """,
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_by_case(self, case_id: str) -> list[dict[str, Any]]:
        rows = self._store._conn.execute(
            """
            SELECT proposal_id, case_id, filter_run_id,
                   approved_profile_id, profile_name,
                   risk_budget_json, snapshots_json,
                   candidates_json, warnings_json,
                   status, created_by_advisor_id,
                   created_at_utc, is_current
            FROM case_portfolio_proposals
            WHERE case_id = ?
            ORDER BY created_at_utc ASC, proposal_id ASC
            """,
            (case_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_current_for_case(self, case_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT proposal_id, case_id, filter_run_id,
                   approved_profile_id, profile_name,
                   risk_budget_json, snapshots_json,
                   candidates_json, warnings_json,
                   status, created_by_advisor_id,
                   created_at_utc, is_current
            FROM case_portfolio_proposals
            WHERE case_id = ? AND is_current = 1
            ORDER BY created_at_utc DESC, proposal_id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def mark_previous_not_current(
        self, case_id: str, exclude_id: str | None = None
    ) -> int:
        if exclude_id is None:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_portfolio_proposals
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1
                    """,
                    (case_id,),
                )
        else:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_portfolio_proposals
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1 AND proposal_id != ?
                    """,
                    (case_id, exclude_id),
                )
        return cur.rowcount if cur.rowcount is not None else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "proposal_id":            row["proposal_id"],
            "case_id":                row["case_id"],
            "filter_run_id":          row["filter_run_id"],
            "approved_profile_id":    row["approved_profile_id"],
            "profile_name":           row["profile_name"],
            "risk_budget":            json.loads(row["risk_budget_json"]),
            "snapshots":              json.loads(row["snapshots_json"]).get("items", []),
            "candidates":             json.loads(row["candidates_json"]).get("items", []),
            "warnings":               json.loads(row["warnings_json"]).get("items", []),
            "status":                 row["status"],
            "created_by_advisor_id":  row["created_by_advisor_id"],
            "is_current":             bool(row["is_current"]),
            "created_at_utc":         row["created_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# CaseOverrideApproval — Fase 2 Commit 13 (case-scoped advisor override)
# ─────────────────────────────────────────────────────────────────────────────
#
# Decisión del asesor sobre una variante de portfolio (típicamente GROWTH) que
# excede el RiskBudget aprobado y requiere advisor override.
#
# is_current se mantiene a nivel case: cada nuevo override approval invalida
# los previos del case, sin discriminar por proposal_id o candidate_variant.
# Política simple y suficiente para Phase 2 (un override vigente por case).
# ─────────────────────────────────────────────────────────────────────────────


ALLOWED_OVERRIDE_APPROVAL_DECISIONS: frozenset[str] = frozenset({"approve", "reject"})


class SQLiteCaseOverrideApprovalRepository:
    """
    Persiste y lee override approvals case-scoped sobre `case_override_approvals`
    (migration 0007).

    Operaciones:
        create(...)                       — inserta nueva approval.
        get(override_approval_id)         — dict | None.
        list_by_case(case_id)             — orden created_at_utc asc, id asc.
        get_current_for_case(case_id)     — is_current=1 más reciente o None.
        mark_previous_not_current(case_id, exclude_id=None)
                                          — bulk is_current=0.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        case_id: str,
        proposal_id: str,
        candidate_variant: str,
        decision: str,
        rationale: str,
        source: str = "manual",
        reason_codes: list[str] | None = None,
        exceeded_constraints: list[str] | None = None,
        advisor_id: str | None = None,
        is_current: bool = True,
    ) -> dict[str, Any]:
        if decision not in ALLOWED_OVERRIDE_APPROVAL_DECISIONS:
            raise ValueError(
                f"decision inválida: {decision!r}. "
                f"Permitidas: {sorted(ALLOWED_OVERRIDE_APPROVAL_DECISIONS)}."
            )

        codes_list = list(reason_codes or [])
        constraints_list = list(exceeded_constraints or [])

        override_approval_id = self._store._next_id("case_override_approval_")
        now = _now_utc()

        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO case_override_approvals
                        (override_approval_id, case_id, proposal_id,
                         candidate_variant, decision,
                         reason_codes_json, exceeded_constraints_json,
                         rationale, source, advisor_id,
                         created_at_utc, is_current)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        override_approval_id, case_id, proposal_id,
                        candidate_variant, decision,
                        _canonical_json({"items": codes_list}),
                        _canonical_json({"items": constraints_list}),
                        rationale, source, advisor_id,
                        now, 1 if is_current else 0,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc

        return {
            "override_approval_id": override_approval_id,
            "case_id":              case_id,
            "proposal_id":          proposal_id,
            "candidate_variant":    candidate_variant,
            "decision":             decision,
            "reason_codes":         codes_list,
            "exceeded_constraints": constraints_list,
            "rationale":            rationale,
            "source":               source,
            "advisor_id":           advisor_id,
            "is_current":           bool(is_current),
            "created_at_utc":       now,
        }

    def get(self, override_approval_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT override_approval_id, case_id, proposal_id,
                   candidate_variant, decision,
                   reason_codes_json, exceeded_constraints_json,
                   rationale, source, advisor_id,
                   created_at_utc, is_current
            FROM case_override_approvals WHERE override_approval_id = ?
            """,
            (override_approval_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_by_case(self, case_id: str) -> list[dict[str, Any]]:
        rows = self._store._conn.execute(
            """
            SELECT override_approval_id, case_id, proposal_id,
                   candidate_variant, decision,
                   reason_codes_json, exceeded_constraints_json,
                   rationale, source, advisor_id,
                   created_at_utc, is_current
            FROM case_override_approvals
            WHERE case_id = ?
            ORDER BY created_at_utc ASC, override_approval_id ASC
            """,
            (case_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_current_for_case(self, case_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT override_approval_id, case_id, proposal_id,
                   candidate_variant, decision,
                   reason_codes_json, exceeded_constraints_json,
                   rationale, source, advisor_id,
                   created_at_utc, is_current
            FROM case_override_approvals
            WHERE case_id = ? AND is_current = 1
            ORDER BY created_at_utc DESC, override_approval_id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def mark_previous_not_current(
        self, case_id: str, exclude_id: str | None = None
    ) -> int:
        if exclude_id is None:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_override_approvals
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1
                    """,
                    (case_id,),
                )
        else:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_override_approvals
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1
                          AND override_approval_id != ?
                    """,
                    (case_id, exclude_id),
                )
        return cur.rowcount if cur.rowcount is not None else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "override_approval_id": row["override_approval_id"],
            "case_id":              row["case_id"],
            "proposal_id":          row["proposal_id"],
            "candidate_variant":    row["candidate_variant"],
            "decision":             row["decision"],
            "reason_codes":         json.loads(row["reason_codes_json"]).get("items", []),
            "exceeded_constraints": json.loads(row["exceeded_constraints_json"]).get("items", []),
            "rationale":            row["rationale"],
            "source":               row["source"],
            "advisor_id":           row["advisor_id"],
            "is_current":           bool(row["is_current"]),
            "created_at_utc":       row["created_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# CasePortfolioSelection — Fase 2 Commit 14 (selección final case-scoped)
# ─────────────────────────────────────────────────────────────────────────────
#
# Decisión final del asesor: cuál variant del proposal se presenta al cliente.
# Cambia el status del case a PORTFOLIO_SELECTED y materializa el puntero
# advisory_cases.current_portfolio_selection_id.
#
# is_current a nivel case (una selección vigente por case). El endpoint
# valida la coherencia override / candidate-requires-override antes del insert.
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteCasePortfolioSelectionRepository:
    """
    Persiste y lee selections case-scoped sobre `case_portfolio_selections`
    (migration 0008).

    Operaciones:
        create(...)                       — inserta nueva selection.
        get(selection_id)                 — dict | None.
        list_by_case(case_id)             — orden created_at_utc asc, id asc.
        get_current_for_case(case_id)     — is_current=1 más reciente o None.
        mark_previous_not_current(case_id, exclude_id=None)
                                          — bulk is_current=0.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        case_id: str,
        proposal_id: str,
        selected_variant: str,
        selected_candidate: Mapping[str, Any],
        rationale: str,
        source: str = "manual",
        override_approval_id: str | None = None,
        advisor_id: str | None = None,
        considered_alternatives: Sequence[Mapping[str, Any]] | None = None,
        is_current: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(selected_candidate, Mapping):
            raise ValueError(
                "selected_candidate debe ser un mapping (dict); recibido "
                f"{type(selected_candidate).__name__}."
            )

        selection_id = self._store._next_id("case_portfolio_selection_")
        now = _now_utc()
        candidate_dict = dict(selected_candidate)
        # NULL = no documentado; "[]" = documentó que no consideró otras.
        alternatives_list: list[dict[str, Any]] | None = (
            None
            if considered_alternatives is None
            else [dict(a) for a in considered_alternatives]
        )
        alternatives_json: str | None = (
            None
            if alternatives_list is None
            else json.dumps(alternatives_list, ensure_ascii=False)
        )

        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO case_portfolio_selections
                        (selection_id, case_id, proposal_id,
                         override_approval_id, selected_variant,
                         selected_candidate_json, rationale, source,
                         advisor_id, considered_alternatives_json,
                         created_at_utc, is_current)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        selection_id, case_id, proposal_id,
                        override_approval_id, selected_variant,
                        _canonical_json(candidate_dict),
                        rationale, source,
                        advisor_id, alternatives_json,
                        now, 1 if is_current else 0,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc

        return {
            "selection_id":            selection_id,
            "case_id":                 case_id,
            "proposal_id":             proposal_id,
            "override_approval_id":    override_approval_id,
            "selected_variant":        selected_variant,
            "selected_candidate":      candidate_dict,
            "rationale":               rationale,
            "source":                  source,
            "advisor_id":              advisor_id,
            "considered_alternatives": alternatives_list,
            "is_current":              bool(is_current),
            "created_at_utc":          now,
        }

    def get(self, selection_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT selection_id, case_id, proposal_id,
                   override_approval_id, selected_variant,
                   selected_candidate_json, rationale, source,
                   advisor_id, considered_alternatives_json,
                   created_at_utc, is_current
            FROM case_portfolio_selections WHERE selection_id = ?
            """,
            (selection_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_by_case(self, case_id: str) -> list[dict[str, Any]]:
        rows = self._store._conn.execute(
            """
            SELECT selection_id, case_id, proposal_id,
                   override_approval_id, selected_variant,
                   selected_candidate_json, rationale, source,
                   advisor_id, considered_alternatives_json,
                   created_at_utc, is_current
            FROM case_portfolio_selections
            WHERE case_id = ?
            ORDER BY created_at_utc ASC, selection_id ASC
            """,
            (case_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_current_for_case(self, case_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT selection_id, case_id, proposal_id,
                   override_approval_id, selected_variant,
                   selected_candidate_json, rationale, source,
                   advisor_id, considered_alternatives_json,
                   created_at_utc, is_current
            FROM case_portfolio_selections
            WHERE case_id = ? AND is_current = 1
            ORDER BY created_at_utc DESC, selection_id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def mark_previous_not_current(
        self, case_id: str, exclude_id: str | None = None
    ) -> int:
        if exclude_id is None:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_portfolio_selections
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1
                    """,
                    (case_id,),
                )
        else:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_portfolio_selections
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1 AND selection_id != ?
                    """,
                    (case_id, exclude_id),
                )
        return cur.rowcount if cur.rowcount is not None else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        raw_alternatives = row["considered_alternatives_json"]
        return {
            "selection_id":            row["selection_id"],
            "case_id":                 row["case_id"],
            "proposal_id":             row["proposal_id"],
            "override_approval_id":    row["override_approval_id"],
            "selected_variant":        row["selected_variant"],
            "selected_candidate":      json.loads(row["selected_candidate_json"]),
            "rationale":               row["rationale"],
            "source":                  row["source"],
            "advisor_id":              row["advisor_id"],
            "considered_alternatives": (
                None if raw_alternatives is None else json.loads(raw_alternatives)
            ),
            "is_current":              bool(row["is_current"]),
            "created_at_utc":          row["created_at_utc"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# CaseReport — Fase 2 Commit 15 (case-scoped markdown reports)
# ─────────────────────────────────────────────────────────────────────────────
#
# Reportes markdown generados por el asesor para presentar al cliente.
# Versionados por case_id (UNIQUE(case_id, version)). Append-only:
# cada POST crea una version nueva con is_current=1 y marca las previas =0.
# ─────────────────────────────────────────────────────────────────────────────


class SQLiteCaseReportRepository:
    """
    Persiste y lee reportes case-scoped sobre `case_reports` (migration 0009).

    Operaciones:
        create(...)                       — inserta version siguiente del case.
        get(report_id)                    — dict | None.
        list_by_case(case_id)             — orden version asc.
        get_current_for_case(case_id)     — is_current=1 más reciente o None.
        mark_previous_not_current(case_id, exclude_id=None)
                                          — bulk is_current=0.
    """

    def __init__(self, store: SQLiteEntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        case_id: str,
        report_type: str,
        status: str,
        markdown: str,
        metadata: Mapping[str, Any],
        portfolio_selection_id: str | None = None,
        portfolio_proposal_id: str | None = None,
        generated_by_advisor_id: str | None = None,
        is_current: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):
            raise ValueError(
                "metadata debe ser un mapping (dict); recibido "
                f"{type(metadata).__name__}."
            )

        # version = MAX(version)+1 por case_id.
        last_row = self._store._conn.execute(
            "SELECT MAX(version) FROM case_reports WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        last_version = last_row[0] if last_row and last_row[0] is not None else 0
        new_version = int(last_version) + 1

        report_id = self._store._next_id("case_report_")
        now = _now_utc()
        meta_dict = dict(metadata)

        try:
            with self._store._conn:
                self._store._conn.execute(
                    """
                    INSERT INTO case_reports
                        (report_id, case_id,
                         portfolio_selection_id, portfolio_proposal_id,
                         report_type, status, version,
                         markdown, metadata_json,
                         generated_by_advisor_id, created_at_utc, is_current)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report_id, case_id,
                        portfolio_selection_id, portfolio_proposal_id,
                        report_type, status, new_version,
                        markdown, _canonical_json(meta_dict),
                        generated_by_advisor_id, now, 1 if is_current else 0,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityConflictError(str(exc)) from exc

        return {
            "report_id":               report_id,
            "case_id":                 case_id,
            "portfolio_selection_id":  portfolio_selection_id,
            "portfolio_proposal_id":   portfolio_proposal_id,
            "report_type":             report_type,
            "status":                  status,
            "version":                 new_version,
            "markdown":                markdown,
            "metadata":                meta_dict,
            "generated_by_advisor_id": generated_by_advisor_id,
            "is_current":              bool(is_current),
            "created_at_utc":          now,
        }

    def get(self, report_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT report_id, case_id,
                   portfolio_selection_id, portfolio_proposal_id,
                   report_type, status, version,
                   markdown, metadata_json,
                   generated_by_advisor_id, created_at_utc, is_current
            FROM case_reports WHERE report_id = ?
            """,
            (report_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_by_case(self, case_id: str) -> list[dict[str, Any]]:
        rows = self._store._conn.execute(
            """
            SELECT report_id, case_id,
                   portfolio_selection_id, portfolio_proposal_id,
                   report_type, status, version,
                   markdown, metadata_json,
                   generated_by_advisor_id, created_at_utc, is_current
            FROM case_reports
            WHERE case_id = ?
            ORDER BY version ASC
            """,
            (case_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_current_for_case(self, case_id: str) -> dict[str, Any] | None:
        row = self._store._conn.execute(
            """
            SELECT report_id, case_id,
                   portfolio_selection_id, portfolio_proposal_id,
                   report_type, status, version,
                   markdown, metadata_json,
                   generated_by_advisor_id, created_at_utc, is_current
            FROM case_reports
            WHERE case_id = ? AND is_current = 1
            ORDER BY version DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def mark_previous_not_current(
        self, case_id: str, exclude_id: str | None = None
    ) -> int:
        if exclude_id is None:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_reports
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1
                    """,
                    (case_id,),
                )
        else:
            with self._store._conn:
                cur = self._store._conn.execute(
                    """
                    UPDATE case_reports
                    SET is_current = 0
                    WHERE case_id = ? AND is_current = 1 AND report_id != ?
                    """,
                    (case_id, exclude_id),
                )
        return cur.rowcount if cur.rowcount is not None else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "report_id":               row["report_id"],
            "case_id":                 row["case_id"],
            "portfolio_selection_id":  row["portfolio_selection_id"],
            "portfolio_proposal_id":   row["portfolio_proposal_id"],
            "report_type":             row["report_type"],
            "status":                  row["status"],
            "version":                 int(row["version"]),
            "markdown":                row["markdown"],
            "metadata":                json.loads(row["metadata_json"]),
            "generated_by_advisor_id": row["generated_by_advisor_id"],
            "is_current":              bool(row["is_current"]),
            "created_at_utc":          row["created_at_utc"],
        }
