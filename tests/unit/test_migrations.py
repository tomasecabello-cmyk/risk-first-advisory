"""
Tests para scripts/migrate.py — runner de migraciones SQLite (Fase 2 — schema base).

Cubre:
    - Aplicación sobre DB vacía.
    - schema_migrations queda con la versión 0001 registrada.
    - Las 6 tablas core de Fase 2 existen tras la migración.
    - La migración NO crea las tablas legacy `records` / `counters`.
    - SQLitePersistenceStore puede inicializarse sobre la misma DB sin colisión.
    - Idempotencia: re-ejecutar no duplica ni vuelve a aplicar.
    - Idempotencia (CLI): main() devuelve 0 en ambas corridas.
    - FK enforcement: con foreign_keys=ON, INSERT con FK rota → IntegrityError.
    - UNIQUE(case_id, sequence) en audit_events → IntegrityError en duplicado.
    - Índices declarados existen.
    - --db-path funciona tanto como argumento de función como por CLI.
    - Migration preserva registros legacy preexistentes en `records`.
    - Edge cases: directorio de migraciones vacío / inexistente.
    - Atomicidad: una migración inválida no deja la DB en estado intermedio.

No se testea contra DEFAULT_DB_PATH del proyecto — todos los tests usan tmp_path
para aislamiento total.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Importar el módulo `migrate` desde scripts/ sin contaminar sys.path
# globalmente (importlib es más robusto que sys.path.insert + import).
# ─────────────────────────────────────────────────────────────────────────────

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_MIGRATE_PATH: Path = PROJECT_ROOT / "scripts" / "migrate.py"
_MIGRATIONS_DIR: Path = PROJECT_ROOT / "migrations"

_spec = importlib.util.spec_from_file_location("rfa_migrate", _MIGRATE_PATH)
assert _spec is not None and _spec.loader is not None
migrate = importlib.util.module_from_spec(_spec)
sys.modules["rfa_migrate"] = migrate
_spec.loader.exec_module(migrate)


# ─────────────────────────────────────────────────────────────────────────────
# Importar SQLitePersistenceStore para los tests de coexistencia con legacy
# ─────────────────────────────────────────────────────────────────────────────

from risk_first_advisory.persistence_layer.sqlite_repository import (  # noqa: E402
    SQLitePersistenceStore,
)


# ─────────────────────────────────────────────────────────────────────────────
# Schema esperado tras 0001
# ─────────────────────────────────────────────────────────────────────────────

PHASE2_TABLES: frozenset[str] = frozenset({
    "schema_migrations",
    "firms",
    "advisors",
    "clients",
    "advisory_cases",
    "audit_events",
    "ai_request_logs",
    # 0002 — case-scoped KYC submissions
    "kyc_submissions",
    # 0003 — case-scoped AI profile analyses
    "ai_profile_analyses",
    # 0004 — case-scoped advisor profile approvals
    "advisor_profile_approvals",
    # 0005 — case-scoped investment preferences + universe filter runs
    "case_investment_preferences",
    "case_universe_filter_runs",
    # 0006 — case-scoped portfolio proposals
    "case_portfolio_proposals",
})

# Total de archivos .sql en migrations/. Cada vez que se agrega una migración,
# este número se actualiza (los tests de count usan TOTAL_MIGRATIONS).
TOTAL_MIGRATIONS: int = 6

LEGACY_TABLES: frozenset[str] = frozenset({"records", "counters"})

REQUIRED_INDEXES: frozenset[str] = frozenset({
    "idx_advisors_firm_id",
    "idx_clients_firm_id",
    "idx_clients_primary_advisor_id",
    "idx_advisory_cases_firm_id",
    "idx_advisory_cases_client_id",
    "idx_advisory_cases_lead_advisor_id",
    "idx_advisory_cases_status",
    "idx_audit_events_case_sequence",
    "idx_ai_request_logs_case_id",
    "idx_ai_request_logs_requested_by_advisor_id",
    # 0002 — kyc_submissions indices
    "idx_kyc_submissions_case_id",
    "idx_kyc_submissions_submitted_by_advisor_id",
    # 0003 — ai_profile_analyses indices
    "idx_ai_profile_analyses_case_id",
    "idx_ai_profile_analyses_kyc_submission_id",
    "idx_ai_profile_analyses_ai_request_log_id",
    # 0004 — advisor_profile_approvals indices
    "idx_advisor_profile_approvals_case_id",
    "idx_advisor_profile_approvals_ai_profile_analysis_id",
    "idx_advisor_profile_approvals_kyc_submission_id",
    "idx_advisor_profile_approvals_advisor_id",
    # 0005 — case_investment_preferences + case_universe_filter_runs indices
    "idx_case_investment_preferences_case_id",
    "idx_case_investment_preferences_ai_request_log_id",
    "idx_case_investment_preferences_created_by_advisor_id",
    "idx_case_universe_filter_runs_case_id",
    "idx_case_universe_filter_runs_preference_id",
    "idx_case_universe_filter_runs_created_by_advisor_id",
    # 0006 — case_portfolio_proposals indices
    "idx_case_portfolio_proposals_case_id",
    "idx_case_portfolio_proposals_filter_run_id",
    "idx_case_portfolio_proposals_approved_profile_id",
    "idx_case_portfolio_proposals_created_by_advisor_id",
})


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _list_tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def _list_indexes(db_path: Path) -> set[str]:
    """Solo índices creados explícitamente — filtra sqlite_autoindex_*."""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'index' AND name NOT LIKE 'sqlite_autoindex_%'"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def _table_columns(db_path: Path, table: str) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [row[1] for row in rows]
    finally:
        conn.close()


def _open_with_fks(db_path: Path) -> sqlite3.Connection:
    """Abre la DB con FK enforcement explícito (per-connection)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _seed_full_chain(conn: sqlite3.Connection) -> None:
    """Inserta firm + advisor + client + case mínimos para tests downstream."""
    conn.executescript(
        """
        INSERT INTO firms (firm_id, display_name, country, created_at_utc)
        VALUES ('firm_001', 'Demo Firm', 'AR', '2026-05-24T00:00:00Z');

        INSERT INTO advisors
            (advisor_id, firm_id, display_name, email, roles_json, created_at_utc)
        VALUES
            ('advisor_001', 'firm_001', 'A', 'a@x', '["advisor"]', '2026-05-24T00:00:00Z');

        INSERT INTO clients
            (client_id, firm_id, primary_advisor_id, display_name,
             jurisdiction, preferred_currency, created_at_utc)
        VALUES
            ('client_001', 'firm_001', 'advisor_001', 'C',
             'AR', 'USD', '2026-05-24T00:00:00Z');

        INSERT INTO advisory_cases
            (case_id, firm_id, client_id, lead_advisor_id, status, title, created_at_utc)
        VALUES
            ('case_001', 'firm_001', 'client_001', 'advisor_001',
             'DRAFT', 'Test case', '2026-05-24T00:00:00Z');
        """
    )
    conn.commit()


# ═════════════════════════════════════════════════════════════════════════════
# Tests
# ═════════════════════════════════════════════════════════════════════════════


# ── Aplicación sobre DB vacía ────────────────────────────────────────────────


def test_run_returns_number_of_applied_migrations(tmp_path):
    db = tmp_path / "test.db"
    applied = migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    assert applied == TOTAL_MIGRATIONS


def test_run_creates_db_file_if_missing(tmp_path):
    db = tmp_path / "subdir" / "fresh.db"
    assert not db.exists()
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    assert db.exists()


def test_all_phase2_tables_exist_after_migration(tmp_path):
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    tables = _list_tables(db)
    for expected in PHASE2_TABLES:
        assert expected in tables, f"falta tabla {expected!r}"


# ── schema_migrations ────────────────────────────────────────────────────────


def test_schema_migrations_has_expected_columns(tmp_path):
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    cols = _table_columns(db, "schema_migrations")
    assert "version" in cols
    assert "description" in cols
    assert "applied_at_utc" in cols


def test_schema_migrations_records_0001_with_metadata(tmp_path):
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT version, description, applied_at_utc "
            "FROM schema_migrations ORDER BY version"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == TOTAL_MIGRATIONS
    # La primera fila (orden lexicográfico) debe ser 0001 — phase2 core.
    version, description, applied_at = rows[0]
    assert version == "0001"
    assert "phase2" in description.lower()
    # ISO-8601 UTC con sufijo Z (alineado con SQLitePersistenceStore)
    assert applied_at.endswith("Z")
    assert "T" in applied_at
    # La segunda fila debe ser 0002 — kyc_submissions.
    version2, description2, applied_at2 = rows[1]
    assert version2 == "0002"
    assert "kyc" in description2.lower()
    assert applied_at2.endswith("Z")
    # La tercera fila debe ser 0003 — ai_profile_analyses.
    version3, description3, applied_at3 = rows[2]
    assert version3 == "0003"
    assert "ai" in description3.lower() or "profile" in description3.lower()
    assert applied_at3.endswith("Z")
    # La cuarta fila debe ser 0004 — case_profile_approvals.
    version4, description4, applied_at4 = rows[3]
    assert version4 == "0004"
    assert "approval" in description4.lower() or "profile" in description4.lower()
    assert applied_at4.endswith("Z")
    # La quinta fila debe ser 0005 — investment_preferences + universe_filters.
    version5, description5, applied_at5 = rows[4]
    assert version5 == "0005"
    assert (
        "preference" in description5.lower()
        or "universe" in description5.lower()
        or "filter" in description5.lower()
    )
    assert applied_at5.endswith("Z")
    # La sexta fila debe ser 0006 — case_portfolio_proposals.
    version6, description6, applied_at6 = rows[5]
    assert version6 == "0006"
    assert "portfolio" in description6.lower() or "proposal" in description6.lower()
    assert applied_at6.endswith("Z")


# ── Legacy coexistence ──────────────────────────────────────────────────────


def test_migration_does_not_create_legacy_tables(tmp_path):
    """Las tablas records/counters son de SQLitePersistenceStore, no de la migración."""
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    tables = _list_tables(db)
    for legacy in LEGACY_TABLES:
        assert legacy not in tables, (
            f"la migración creó inesperadamente la tabla legacy {legacy!r}"
        )


def test_legacy_persistence_store_init_works_after_migration(tmp_path):
    """SQLitePersistenceStore.init_schema() crea records/counters sin colisión."""
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)

    with SQLitePersistenceStore(db) as store:
        store.init_schema()

    tables = _list_tables(db)
    assert "records" in tables
    assert "counters" in tables
    for t in PHASE2_TABLES:
        assert t in tables


def test_legacy_persistence_store_init_before_migration(tmp_path):
    """Orden inverso: SQLitePersistenceStore primero, después migración."""
    db = tmp_path / "test.db"
    with SQLitePersistenceStore(db) as store:
        store.init_schema()

    applied = migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    assert applied == TOTAL_MIGRATIONS
    tables = _list_tables(db)
    assert "records" in tables
    assert "counters" in tables
    for t in PHASE2_TABLES:
        assert t in tables


def test_migration_preserves_preexisting_legacy_records(tmp_path):
    """
    Records insertados con SQLitePersistenceStore antes de migrar deben sobrevivir.
    Es la garantía núcleo de Fase 2: la migración aditiva no toca data existente.
    """
    db = tmp_path / "legacy.db"

    # Crear schema legacy e insertar un record antes de migrar
    with SQLitePersistenceStore(db) as store:
        store.init_schema()
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO records "
            "(record_id, record_type, client_id, created_at_utc, payload_json, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "workflow_legacy_001",
                "workflow_run",
                "CLI-LEGACY",
                "2026-01-01T00:00:00Z",
                '{"foo":"bar"}',
                '{"source":"legacy"}',
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Correr migración
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)

    # El record original sigue ahí, intacto
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT record_id, record_type, client_id, payload_json "
            "FROM records WHERE record_id = ?",
            ("workflow_legacy_001",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "workflow_legacy_001"
    assert row[1] == "workflow_run"
    assert row[2] == "CLI-LEGACY"
    assert row[3] == '{"foo":"bar"}'

    # Y las tablas de Fase 2 también están
    tables = _list_tables(db)
    for t in PHASE2_TABLES:
        assert t in tables


# ── Idempotencia ─────────────────────────────────────────────────────────────


def test_run_is_idempotent_second_call_applies_nothing(tmp_path):
    db = tmp_path / "test.db"
    n1 = migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    n2 = migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    assert n1 == TOTAL_MIGRATIONS
    assert n2 == 0


def test_idempotent_run_does_not_duplicate_schema_migrations_rows(tmp_path):
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)

    conn = sqlite3.connect(str(db))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
            ("0001",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_cli_main_is_idempotent(tmp_path):
    db = tmp_path / "cli.db"
    rc1 = migrate.main(["--db-path", str(db), "--quiet"])
    rc2 = migrate.main(["--db-path", str(db), "--quiet"])
    assert rc1 == 0
    assert rc2 == 0


# ── FK enforcement ───────────────────────────────────────────────────────────


def test_fk_blocks_client_with_unknown_firm(tmp_path):
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    conn = _open_with_fks(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO clients "
                "(client_id, firm_id, primary_advisor_id, display_name, "
                " jurisdiction, preferred_currency, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "client_X",
                    "firm_DOES_NOT_EXIST",
                    "advisor_DOES_NOT_EXIST",
                    "X",
                    "AR",
                    "USD",
                    "2026-05-24T00:00:00Z",
                ),
            )
            conn.commit()
    finally:
        conn.close()


def test_fk_blocks_case_with_unknown_client(tmp_path):
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    conn = _open_with_fks(db)
    try:
        # Crear solo firm + advisor — no client.
        conn.executescript(
            """
            INSERT INTO firms (firm_id, display_name, country, created_at_utc)
            VALUES ('firm_001', 'F', 'AR', '2026-05-24T00:00:00Z');

            INSERT INTO advisors
                (advisor_id, firm_id, display_name, email, roles_json, created_at_utc)
            VALUES
                ('advisor_001', 'firm_001', 'A', 'a@x', '["advisor"]', '2026-05-24T00:00:00Z');
            """
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO advisory_cases "
                "(case_id, firm_id, client_id, lead_advisor_id, status, title, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "case_X",
                    "firm_001",
                    "client_NOPE",
                    "advisor_001",
                    "DRAFT",
                    "T",
                    "2026-05-24T00:00:00Z",
                ),
            )
            conn.commit()
    finally:
        conn.close()


def test_fk_blocks_audit_event_with_unknown_case(tmp_path):
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    conn = _open_with_fks(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO audit_events "
                "(event_id, case_id, sequence, event_type, actor_role, "
                " payload_json, payload_hash, event_hash, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "event_X",
                    "case_NOPE",
                    1,
                    "case_created",
                    "system",
                    "{}",
                    "h1",
                    "eh1",
                    "2026-05-24T00:00:00Z",
                ),
            )
            conn.commit()
    finally:
        conn.close()


# ── UNIQUE (case_id, sequence) en audit_events ───────────────────────────────


def test_unique_case_sequence_blocks_duplicates(tmp_path):
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    conn = _open_with_fks(db)
    try:
        _seed_full_chain(conn)

        conn.execute(
            "INSERT INTO audit_events "
            "(event_id, case_id, sequence, event_type, actor_role, "
            " payload_json, payload_hash, event_hash, created_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "event_001",
                "case_001",
                1,
                "case_created",
                "system",
                "{}",
                "h1",
                "eh1",
                "2026-05-24T00:00:01Z",
            ),
        )
        conn.commit()

        # Mismo (case_id, sequence) — debe romper UNIQUE
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO audit_events "
                "(event_id, case_id, sequence, event_type, actor_role, "
                " payload_json, payload_hash, event_hash, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "event_002",
                    "case_001",
                    1,  # ← duplicado
                    "kyc_submitted",
                    "advisor",
                    "{}",
                    "h2",
                    "eh2",
                    "2026-05-24T00:00:02Z",
                ),
            )
            conn.commit()
    finally:
        conn.close()


def test_unique_case_sequence_allows_same_sequence_in_different_cases(tmp_path):
    """sequence=1 puede existir en case_001 y case_002 simultáneamente."""
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    conn = _open_with_fks(db)
    try:
        _seed_full_chain(conn)
        # Segundo caso, mismo cliente
        conn.execute(
            "INSERT INTO advisory_cases "
            "(case_id, firm_id, client_id, lead_advisor_id, status, title, created_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("case_002", "firm_001", "client_001", "advisor_001",
             "DRAFT", "Otro caso", "2026-05-24T00:00:00Z"),
        )
        conn.commit()

        for case_id in ("case_001", "case_002"):
            conn.execute(
                "INSERT INTO audit_events "
                "(event_id, case_id, sequence, event_type, actor_role, "
                " payload_json, payload_hash, event_hash, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"event_{case_id}_1",
                    case_id,
                    1,
                    "case_created",
                    "system",
                    "{}",
                    "h",
                    "eh",
                    "2026-05-24T00:00:01Z",
                ),
            )
        conn.commit()

        count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        assert count == 2
    finally:
        conn.close()


# ── Índices ──────────────────────────────────────────────────────────────────


def test_all_required_indexes_exist(tmp_path):
    db = tmp_path / "test.db"
    migrate.run(db_path=db, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    indexes = _list_indexes(db)
    missing = REQUIRED_INDEXES - indexes
    assert not missing, f"índices faltantes: {sorted(missing)}"


# ── --db-path ────────────────────────────────────────────────────────────────


def test_db_path_function_argument_targets_distinct_files(tmp_path):
    db1 = tmp_path / "db1.db"
    db2 = tmp_path / "db2.db"
    migrate.run(db_path=db1, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    migrate.run(db_path=db2, migrations_dir=_MIGRATIONS_DIR, verbose=False)
    assert db1.exists()
    assert db2.exists()
    # Cada DB tiene su propia schema_migrations independiente
    assert _list_tables(db1) == _list_tables(db2)


def test_db_path_cli_argument_creates_target(tmp_path):
    db = tmp_path / "cli_target.db"
    rc = migrate.main(["--db-path", str(db), "--quiet"])
    assert rc == 0
    assert db.exists()
    tables = _list_tables(db)
    for t in PHASE2_TABLES:
        assert t in tables


def test_cli_returns_zero_when_no_pending_migrations(tmp_path):
    db = tmp_path / "noop.db"
    migrate.main(["--db-path", str(db), "--quiet"])
    rc = migrate.main(["--db-path", str(db), "--quiet"])
    assert rc == 0


# ── Edge cases del runner ────────────────────────────────────────────────────


def test_empty_migrations_dir_returns_zero_and_does_not_fail(tmp_path):
    db = tmp_path / "empty_migs.db"
    empty_dir = tmp_path / "empty_migrations"
    empty_dir.mkdir()
    applied = migrate.run(db_path=db, migrations_dir=empty_dir, verbose=False)
    assert applied == 0
    # schema_migrations debe seguir existiendo (se crea siempre)
    tables = _list_tables(db)
    assert "schema_migrations" in tables


def test_nonexistent_migrations_dir_returns_zero(tmp_path):
    db = tmp_path / "ghost_migs.db"
    ghost_dir = tmp_path / "does_not_exist"
    applied = migrate.run(db_path=db, migrations_dir=ghost_dir, verbose=False)
    assert applied == 0


def test_invalid_migration_does_not_partially_apply(tmp_path):
    """
    Una migración con SQL inválido NO debe quedar registrada en
    schema_migrations ni dejar tablas a medias.
    """
    db = tmp_path / "bad.db"
    bad_dir = tmp_path / "bad_migrations"
    bad_dir.mkdir()
    bad_sql = bad_dir / "0001_busted.sql"
    bad_sql.write_text(
        # Primera sentencia válida, segunda inválida — debe ROLLBACK todo.
        "CREATE TABLE will_be_rolled_back (id TEXT PRIMARY KEY);\n"
        "CREATE TABLE THIS IS NOT VALID SQL AT ALL;\n",
        encoding="utf-8",
    )

    with pytest.raises(sqlite3.Error):
        migrate.run(db_path=db, migrations_dir=bad_dir, verbose=False)

    tables = _list_tables(db)
    # schema_migrations sí existe (se crea fuera de la tx de cada migration)
    assert "schema_migrations" in tables
    # Pero NO hay registro de 0001 aplicada
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    finally:
        conn.close()
    assert rows == []
    # Y la tabla parcial NO debe haberse creado (rollback)
    assert "will_be_rolled_back" not in tables


def test_parse_version_description_from_canonical_filename():
    p = Path("0001_phase2_core_schema.sql")
    version, description = migrate._parse_version_description(p)
    assert version == "0001"
    assert description == "phase2_core_schema"


def test_split_sql_statements_strips_comments_and_splits_by_semicolon():
    sql = (
        "-- header comment\n"
        "CREATE TABLE a (x TEXT); -- inline comment\n"
        "\n"
        "CREATE TABLE b (y TEXT);\n"
        "-- trailing\n"
    )
    stmts = migrate._split_sql_statements(sql)
    assert len(stmts) == 2
    assert stmts[0].startswith("CREATE TABLE a")
    assert stmts[1].startswith("CREATE TABLE b")
