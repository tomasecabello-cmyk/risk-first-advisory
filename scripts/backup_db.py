#!/usr/bin/env python3
"""
Backup utility — risk-first-advisory.

Crea una copia compacta de la base SQLite en
    data/backups/YYYYMMDD_HHMMSS/<original_filename>

Usa `VACUUM INTO` (SQLite ≥ 3.27, Python ≥ 3.7) que es online-safe:
respeta WAL y no captura transacciones in-flight, a diferencia de un `cp`
crudo. El archivo destino es una DB compacta (página vacuum'd), lista para
abrir con sqlite3.

Limitaciones aceptadas para esta versión:
    - No comprime el archivo.
    - No calcula checksum (futuro: SHA-256 del backup).
    - No rota / borra backups viejos.
    - No verifica integridad post-copia (futuro: PRAGMA integrity_check).
Si la firma productiva lo necesita, se añade en una tarea posterior.

Uso:
    python scripts/backup_db.py
    python scripts/backup_db.py --db-path data/dev_phase2.db
    python scripts/backup_db.py --backup-root /tmp/rfa-backups
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


# Stdout/stderr en UTF-8 para que la consola Windows no crashee en caracteres
# fuera de cp1252. Mismo patrón que scripts/migrate.py.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Paths por defecto (mismas convenciones que migrate.py)
# ─────────────────────────────────────────────────────────────────────────────

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH: Path = PROJECT_ROOT / "data" / "demo_api.db"
DEFAULT_BACKUP_ROOT: Path = PROJECT_ROOT / "data" / "backups"


def _timestamp_dirname() -> str:
    # Local time intencional: el backup es para inspección humana.
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup(
    db_path: Path | str,
    backup_root: Path | str | None = None,
) -> Path:
    """
    Hace VACUUM INTO de db_path a backup_root/<timestamp>/<filename>.

    Returns:
        Ruta absoluta al archivo de backup creado.

    Raises:
        FileNotFoundError: si db_path no existe.
        sqlite3.Error: si el VACUUM INTO falla (ej. target ya existe).
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Source DB not found: {db_path}")

    backup_root = (
        Path(backup_root) if backup_root is not None else DEFAULT_BACKUP_ROOT
    )
    backup_dir = backup_root / _timestamp_dirname()
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_path = backup_dir / db_path.name

    src = sqlite3.connect(str(db_path))
    try:
        # VACUUM INTO no acepta parámetros, así que tenemos que interpolar
        # la ruta. Quoting con single quotes y escapando ' duplicándolo es
        # el patrón estándar SQL.
        target = str(backup_path).replace("'", "''")
        src.execute(f"VACUUM INTO '{target}'")
    finally:
        src.close()

    return backup_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backup de la DB SQLite de risk-first-advisory.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Ruta al SQLite source (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=DEFAULT_BACKUP_ROOT,
        help=f"Directorio raíz de backups (default: {DEFAULT_BACKUP_ROOT})",
    )
    args = parser.parse_args(argv)

    print("=== risk-first-advisory · DB backup ===")
    print(f"Source : {args.db_path}")
    try:
        out = backup(args.db_path, args.backup_root)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Backup : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
