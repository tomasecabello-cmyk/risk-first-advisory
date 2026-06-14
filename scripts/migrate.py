#!/usr/bin/env python3
"""
SQLite schema migrator — risk-first-advisory.

Aplica los archivos .sql bajo migrations/ a la base de datos, registrando cada
versión aplicada en la tabla `schema_migrations`. Idempotente: re-ejecutar no
re-aplica nada.

Diseño:
    - Cada archivo de migración se llama  NNNN_descripcion_corta.sql
      donde NNNN es la versión lexicográficamente ordenable (ej. "0001").
    - Cada archivo se ejecuta dentro de UNA transacción manejada por este
      runner: si cualquier statement falla, la transacción se hace ROLLBACK
      y la versión NO queda registrada como aplicada.
    - Los archivos .sql NO deben contener BEGIN/COMMIT explícitos (el runner
      los envuelve).
    - El runner activa PRAGMA foreign_keys=ON, journal_mode=WAL,
      busy_timeout=5000 en su conexión. Estos PRAGMAs son per-connection
      (foreign_keys, busy_timeout) o persistentes en el archivo
      (journal_mode=WAL); las apps que abran la DB después deben volver a
      activar foreign_keys=ON en su propia conexión.
    - El runner NO toca las tablas legacy `records` y `counters` — esas
      pertenecen a SQLitePersistenceStore y se crean por separado.

Uso:
    python scripts/migrate.py
    python scripts/migrate.py --db-path data/dev_phase2.db
    python scripts/migrate.py --migrations-dir migrations
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Configurar stdout/stderr para UTF-8 cuando es posible.
#
# Windows consolas por defecto usan cp1252 y crashean (UnicodeEncodeError) al
# imprimir caracteres como ✓, ─, etc. Python 3.7+ permite reconfigurar el
# stream; si no se puede (stream no-reconfigurable o Python viejo), se aceptan
# errors='replace' para nunca crashear por encoding.
# ─────────────────────────────────────────────────────────────────────────────
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Paths por defecto
# ─────────────────────────────────────────────────────────────────────────────

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_MIGRATIONS_DIR: Path = PROJECT_ROOT / "migrations"
DEFAULT_DB_PATH: Path = PROJECT_ROOT / "data" / "demo_api.db"


# ─────────────────────────────────────────────────────────────────────────────
# DDL del propio registro de migraciones (NO va como migración 0000; es meta).
# Se ejecuta antes de cualquier migración y es seguro de re-ejecutar.
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_MIGRATIONS_DDL: str = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version        TEXT PRIMARY KEY,
    description    TEXT NOT NULL,
    applied_at_utc TEXT NOT NULL
);
"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_version_description(path: Path) -> tuple[str, str]:
    """
    Extrae (version, description) del filename.

    Convención: NNNN_descripcion_corta.sql
        -> version="NNNN", description="descripcion_corta"
    Si el filename no tiene "_", version == description == stem.
    """
    stem = path.stem
    if "_" not in stem:
        return stem, stem
    version, _, description = stem.partition("_")
    return version, description


def _discover_migrations(migrations_dir: Path) -> list[Path]:
    """
    Devuelve los .sql del directorio en orden lexicográfico.
    Si el directorio no existe, devuelve [].
    """
    if not migrations_dir.exists():
        return []
    return sorted(migrations_dir.glob("*.sql"))


def _split_sql_statements(sql: str) -> list[str]:
    """
    Split de SQL por `;`, removiendo comentarios `--`.

    Conservador: NO maneja `;` dentro de string literals porque nuestras
    migraciones no contienen tales literales. Si alguna futura migración
    los necesita, refactorizar para usar sqlglot o un parser real.
    """
    cleaned_lines: list[str] = []
    for line in sql.splitlines():
        comment_idx = line.find("--")
        if comment_idx >= 0:
            line = line[:comment_idx]
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)

    parts = [s.strip() for s in cleaned.split(";")]
    return [s for s in parts if s]


def _open_connection(db_path: Path) -> sqlite3.Connection:
    """
    Abre la conexión SQLite con los PRAGMAs estándar de la app.
    Crea el directorio padre si no existe.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # journal_mode=WAL es persistente; los demás son per-connection.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    """Crea schema_migrations si no existe. Idempotente."""
    with conn:
        conn.executescript(SCHEMA_MIGRATIONS_DDL)


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def _apply_migration(
    conn: sqlite3.Connection,
    version: str,
    description: str,
    sql: str,
) -> None:
    """
    Aplica UNA migración dentro de una transacción manual.

    Si cualquier statement del .sql falla — o el INSERT en schema_migrations
    — toda la transacción hace ROLLBACK. La versión queda como NO aplicada.
    """
    old_iso = conn.isolation_level
    conn.isolation_level = None  # autocommit OFF: manejamos BEGIN/COMMIT manualmente
    try:
        conn.execute("BEGIN")
        try:
            for stmt in _split_sql_statements(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version, description, applied_at_utc) "
                "VALUES (?, ?, ?)",
                (version, description, _now_utc()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = old_iso


# ─────────────────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────────────────


def run(
    db_path: Path | str | None = None,
    migrations_dir: Path | str | None = None,
    verbose: bool = True,
) -> int:
    """
    Aplica todas las migraciones pendientes. Devuelve la cantidad aplicada.

    Args:
        db_path: ruta al SQLite. Default DEFAULT_DB_PATH.
        migrations_dir: directorio de .sql. Default DEFAULT_MIGRATIONS_DIR.
        verbose: si True, imprime progreso.

    Returns:
        Número de migraciones efectivamente aplicadas (0 si todas ya estaban).
    """
    db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    migrations_dir = (
        Path(migrations_dir) if migrations_dir is not None else DEFAULT_MIGRATIONS_DIR
    )

    conn = _open_connection(db_path)
    try:
        _ensure_schema_migrations(conn)
        already_applied = _applied_versions(conn)
        files = _discover_migrations(migrations_dir)

        if not files:
            if verbose:
                print(f"  (sin archivos de migración en {migrations_dir})")
            return 0

        applied_now = 0
        for path in files:
            version, description = _parse_version_description(path)
            if version in already_applied:
                if verbose:
                    print(f"  ·  {version}  ya aplicada ({path.name}) — skip")
                continue

            if verbose:
                print(f"  +  {version}  aplicando {path.name} ...")
            sql = path.read_text(encoding="utf-8")
            _apply_migration(conn, version, description, sql)
            applied_now += 1
            if verbose:
                print(f"  ✓  {version}  aplicada — {description}")

        return applied_now
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aplica las migraciones SQLite de risk-first-advisory.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Ruta al SQLite (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
        help=f"Directorio con archivos .sql (default: {DEFAULT_MIGRATIONS_DIR})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="No imprimir progreso.",
    )
    args = parser.parse_args(argv)

    verbose = not args.quiet
    if verbose:
        print("=== risk-first-advisory · SQLite migrator ===")
        print(f"DB         : {args.db_path}")
        print(f"Migrations : {args.migrations_dir}")

    try:
        applied = run(
            db_path=args.db_path,
            migrations_dir=args.migrations_dir,
            verbose=verbose,
        )
    except sqlite3.Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if verbose:
        if applied == 0:
            print("--- sin cambios — DB ya estaba al día ---")
        elif applied == 1:
            print("--- 1 migración aplicada ---")
        else:
            print(f"--- {applied} migraciones aplicadas ---")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
