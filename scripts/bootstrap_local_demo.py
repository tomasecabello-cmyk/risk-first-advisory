"""
bootstrap_local_demo.py — Un solo comando para dejar el entorno local listo
para demo del Case Dashboard + Case Workbench.

Hace en orden:
    1. Verifica archivos críticos del repo (frontend + scripts).
    2. Aplica migrations sobre la DB local/dev default.
    3. Corre seed_demo_data (idempotente).
    4. Verifica que las entidades demo quedaron en la DB.
    5. Imprime configuración (tokens YAML, OPENAI_API_KEY) + comandos para
       levantar backend y frontend + URLs + tokens recomendados.

Opcionalmente corre el smoke check end-to-end (`--run-smoke`) en una DB
temporal aislada para no ensuciar la DB de demo.

**NO levanta servidores.** Solo imprime los comandos para que el dev los
copie. Decisión: bootstrap no debe spawn procesos zombies si el dev lo
interrumpe; mejor dejar el control al dev.

Ejecución:
    python scripts/bootstrap_local_demo.py
    python scripts/bootstrap_local_demo.py --db-path data/otra.db
    python scripts/bootstrap_local_demo.py --check-only
    python scripts/bootstrap_local_demo.py --skip-migrate --skip-seed
    python scripts/bootstrap_local_demo.py --run-smoke

Exit codes:
    0 → PASS (todos los pasos OK)
    1 → FAIL (al menos un paso crítico falló)
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── UTF-8 stdout/stderr (Windows cp1252) ─────────────────────────────────────
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ── sys.path bootstrap ──────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_FRONTEND_FILES: tuple[str, ...] = (
    "frontend/index.html",
    "frontend/css/base.css",
    "frontend/js/common.js",
    "frontend/js/legacy-demo.js",
    "frontend/js/case-dashboard.js",
    "frontend/js/case-workbench.js",
)

REQUIRED_SCRIPT_FILES: tuple[str, ...] = (
    "scripts/migrate.py",
    "scripts/seed_demo_data.py",
)

MIN_PYTHON: tuple[int, int] = (3, 11)

LINE = "=" * 70


# ─────────────────────────────────────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────────────────────────────────────


def _section(title: str) -> None:
    print()
    print(LINE)
    print(f"  {title}")
    print(LINE)


def _step_start(idx: int, total: int, label: str) -> None:
    print(f"  [{idx}/{total}] {label}…")


def _ok(label: str, detail: str = "") -> None:
    suffix = f" → {detail}" if detail else ""
    print(f"  ✓  {label}{suffix}")


def _info(label: str, detail: str = "") -> None:
    suffix = f" → {detail}" if detail else ""
    print(f"  ·  {label}{suffix}")


def _warn(label: str, detail: str = "") -> None:
    suffix = f" → {detail}" if detail else ""
    print(f"  !  {label}{suffix}")


def _fail(label: str, detail: str = "") -> None:
    suffix = f" → {detail}" if detail else ""
    print(f"  ✗  {label}{suffix}")


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class BootstrapResult:
    passed:          bool
    db_path:         Path
    migrated:        bool       # True si se aplicó migrate (o ya estaba al día)
    seeded:          bool       # True si seed corrió OK
    frontend_ok:     bool       # True si todos los assets críticos existen
    smoke_ok:        bool | None  # True/False si --run-smoke, None si no se corrió
    config_summary:  dict[str, Any] = field(default_factory=dict)
    demo_ids:        dict[str, str | None] = field(default_factory=dict)
    failures:        list[str]  = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers (delegan en módulos existentes)
# ─────────────────────────────────────────────────────────────────────────────


def _import_script(name: str, file_name: str):
    """Importa un script de scripts/ vía importlib."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file_name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


def _check_python_version() -> tuple[bool, str]:
    ok = sys.version_info >= MIN_PYTHON
    return ok, f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _check_repo_files(repo_root: Path) -> tuple[bool, list[str]]:
    """Devuelve (all_ok, missing_files)."""
    missing: list[str] = []
    for rel in (*REQUIRED_FRONTEND_FILES, *REQUIRED_SCRIPT_FILES):
        if not (repo_root / rel).exists():
            missing.append(rel)
    return len(missing) == 0, missing


def _detect_tokens_config(repo_root: Path) -> dict[str, Any]:
    """Reporta dónde vendrán los tokens del backend cuando arranque uvicorn."""
    # Import perezoso: solo lo necesitamos para conocer el nombre del env var
    # y el path default.
    from risk_first_advisory.config_layer import advisor_tokens as tm

    env_path = os.environ.get(tm.ADVISOR_TOKENS_ENV_VAR)
    default_path = repo_root / "config" / "advisor_tokens.yaml"
    if env_path:
        return {
            "source":  "env_var",
            "path":    env_path,
            "exists":  Path(env_path).exists(),
            "note":    f"{tm.ADVISOR_TOKENS_ENV_VAR} set; backend usará ese YAML.",
        }
    if default_path.exists():
        return {
            "source":  "default_yaml",
            "path":    str(default_path),
            "exists":  True,
            "note":    "config/advisor_tokens.yaml detectado; backend lo usará.",
        }
    return {
        "source":  "fallback",
        "path":    None,
        "exists":  False,
        "note":    (
            "Sin YAML custom — backend usará dev-only fallback "
            "(solo dev-advisor-token + dev-compliance-token). "
            "Operaciones admin (crear firm/advisor en Dashboard) fallarán con "
            "403 sin un YAML custom con rol admin."
        ),
    }


def _print_launch_block(repo_root: Path, demo_ids: dict[str, str | None],
                         config: dict[str, Any]) -> None:
    """Imprime el bloque final de instrucciones para el dev."""
    print()
    print("=" * 70)
    print("  Demo data IDs")
    print("=" * 70)
    for k, v in demo_ids.items():
        print(f"    {k:<11} : {v}")

    print()
    print("=" * 70)
    print("  Start backend (Terminal 1)")
    print("=" * 70)
    print("    python -m uvicorn risk_first_advisory.api_layer.main:app --reload")

    print()
    print("=" * 70)
    print("  Start frontend (Terminal 2)")
    print("=" * 70)
    print("    python -m http.server 5500 -d frontend")

    print()
    print("=" * 70)
    print("  Open in browser")
    print("=" * 70)
    print("    Backend Swagger : http://127.0.0.1:8000/docs")
    print("    Frontend        : http://127.0.0.1:5500")

    print()
    print("=" * 70)
    print("  Tokens (Bearer) — usar en el input del Case Dashboard")
    print("=" * 70)
    if config.get("source") == "fallback":
        print("    dev-advisor-token      (rol: advisor    — workflow)")
        print("    dev-compliance-token   (rol: compliance — audit/verify + ai-logs)")
        print("    !  NO hay dev-admin-token / dev-viewer-token en el fallback.")
        print("    !  Para crear firm/advisor en el Dashboard, escribir un")
        print("       config/advisor_tokens.yaml propio con rol admin, o usar")
        print("       'Quick demo seed' del Dashboard (que reusa los IDs del bootstrap).")
    else:
        print(f"    Tokens cargan desde: {config.get('path')}")
        print("    Roles típicos: admin / advisor / compliance / viewer")
        print("    Revisar el YAML para ver los tokens exactos disponibles.")

    print()
    print("=" * 70)
    print("  Optional verifications")
    print("=" * 70)
    print("    Smoke check end-to-end (DB temporal, sin OpenAI ni uvicorn):")
    print("      python scripts/run_case_workflow_smoke_check.py")
    print("    Re-seed demo data (idempotente):")
    print("      python scripts/seed_demo_data.py")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def bootstrap_local_demo(
    *,
    db_path: Path | str | None = None,
    skip_migrate: bool = False,
    skip_seed: bool = False,
    run_smoke: bool = False,
    check_only: bool = False,
    debug: bool = False,
    repo_root: Path | str | None = None,
) -> BootstrapResult:
    """
    Deja el entorno local listo para demo. Devuelve `BootstrapResult`.

    `check_only=True` skip migrate + seed + smoke; solo valida archivos y
    config, e imprime instrucciones. Útil para CI o para "qué falta antes
    de demo".
    """
    repo = Path(repo_root) if repo_root else ROOT
    failures: list[str] = []
    migrated = False
    seeded = False
    frontend_ok = False
    smoke_ok: bool | None = None
    demo_ids: dict[str, str | None] = {
        "firm_id":    None,
        "advisor_id": None,
        "client_id":  None,
        "case_id":    None,
    }
    config_summary: dict[str, Any] = {}

    # ── Resolver db_path ────────────────────────────────────────────────────
    if db_path is None:
        import risk_first_advisory.api_layer.main as _main_for_default
        db_path = _main_for_default.DEFAULT_DB_PATH
    db_path = Path(db_path)

    total_steps = 5 if not check_only else 3
    _section("bootstrap_local_demo — Phase 3 local environment")
    _info(f"Repo root  : {repo}")
    _info(f"DB path    : {db_path}")
    _info("Mode       : check-only" if check_only else "Mode       : full bootstrap")

    try:
        # ── 1. Python + repo files ─────────────────────────────────────────
        _section(f"[1/{total_steps}] Checking environment")
        py_ok, py_ver = _check_python_version()
        if py_ok:
            _ok("python version", f"{py_ver} (>= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})")
        else:
            failures.append(f"Python {py_ver} < {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")
            _fail("python version", f"{py_ver} (need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})")

        files_ok, missing = _check_repo_files(repo)
        frontend_ok = files_ok
        if files_ok:
            _ok("repo files", f"{len(REQUIRED_FRONTEND_FILES)} frontend + "
                              f"{len(REQUIRED_SCRIPT_FILES)} script — all present")
        else:
            failures.append(f"Missing repo files: {missing}")
            _fail("repo files", f"missing: {missing}")

        # Tokens config detection
        config_summary = _detect_tokens_config(repo)
        _info(f"tokens config: {config_summary['source']} → {config_summary['note']}")

        # OPENAI_API_KEY status (informativo; no falla)
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        config_summary["openai_api_key_configured"] = bool(openai_key)
        if openai_key:
            _ok("OPENAI_API_KEY", "configured (full AI demos available)")
        else:
            _info("OPENAI_API_KEY", "NOT configured "
                  "(seed/migrate/smoke check no la necesitan; "
                  "endpoints /ai/* reales fallarán con 400 hasta configurar)")

        # ── 2. Migrations ──────────────────────────────────────────────────
        if check_only:
            _section(f"[2/{total_steps}] Printing launch instructions (check-only)")
            _print_launch_block(repo, demo_ids, config_summary)
        else:
            if skip_migrate:
                _section(f"[2/{total_steps}] Apply migrations (SKIPPED via --skip-migrate)")
                _info("Asumiendo schema actual — si no, seed/runtime fallarán con SQL errors.")
                migrated = False
            else:
                _section(f"[2/{total_steps}] Apply migrations")
                migrate = _import_script("rfa_migrate", "migrate.py")
                try:
                    applied = migrate.run(
                        db_path=db_path,
                        migrations_dir=repo / "migrations",
                        verbose=False,
                    )
                    _ok("migrations applied / verified", f"{applied} pending")
                    migrated = True
                except Exception as exc:
                    failures.append(f"migrate failed: {type(exc).__name__}: {exc}")
                    _fail("migrate", f"{type(exc).__name__}: {exc}")

            # ── 3. Seed ───────────────────────────────────────────────────
            if skip_seed:
                _section(f"[3/{total_steps}] Seed demo data (SKIPPED via --skip-seed)")
                _info("Asumiendo entidades demo ya presentes; no verifico DB content.")
                seeded = False
            else:
                _section(f"[3/{total_steps}] Seed demo data (idempotent)")
                seed = _import_script("rfa_seed_demo_data", "seed_demo_data.py")
                try:
                    sresult = seed.seed_demo_data(
                        db_path=db_path,
                        apply_migrations=False,  # ya las corrimos arriba
                        debug=debug,
                    )
                    if sresult.passed:
                        seeded = True
                        demo_ids = {
                            "firm_id":    sresult.firm_id,
                            "advisor_id": sresult.advisor_id,
                            "client_id":  sresult.client_id,
                            "case_id":    sresult.case_id,
                        }
                        _ok("seed", f"firm={sresult.firm_status}, "
                                    f"advisor={sresult.advisor_status}, "
                                    f"client={sresult.client_status}, "
                                    f"case={sresult.case_status}")
                    else:
                        failures.append(f"seed failed: {sresult.failures}")
                        _fail("seed", "; ".join(sresult.failures))
                except Exception as exc:
                    failures.append(f"seed exception: {type(exc).__name__}: {exc}")
                    _fail("seed", f"{type(exc).__name__}: {exc}")

            # ── 4. Optional smoke check ───────────────────────────────────
            _section(f"[4/{total_steps}] End-to-end smoke check "
                     f"({'ENABLED via --run-smoke' if run_smoke else 'SKIPPED — default'})")
            if run_smoke:
                # Smoke check siempre corre en DB temporal aislada para no
                # contaminar la demo DB con un case completo del smoke.
                smoke_db_dir = Path(tempfile.mkdtemp(prefix="rfa_bootstrap_smoke_"))
                smoke_db = smoke_db_dir / "smoke.db"
                _info(f"Smoke DB temporal: {smoke_db}")
                try:
                    smk = _import_script(
                        "rfa_smoke_check", "run_case_workflow_smoke_check.py"
                    )
                    smresult = smk.run_case_workflow_smoke_check(
                        db_path=smoke_db, debug=debug
                    )
                    smoke_ok = smresult.passed
                    if smresult.passed:
                        _ok("smoke check", "PASS")
                    else:
                        _fail("smoke check", "; ".join(smresult.failures))
                        failures.append(f"smoke check failed: {smresult.failures}")
                except Exception as exc:
                    smoke_ok = False
                    failures.append(f"smoke exception: {type(exc).__name__}: {exc}")
                    _fail("smoke check exception", f"{type(exc).__name__}: {exc}")
                finally:
                    shutil.rmtree(smoke_db_dir, ignore_errors=True)
            else:
                _info("Skipped por default. Pasar --run-smoke para activarlo (DB temporal).")

            # ── 5. Print launch instructions ──────────────────────────────
            _section(f"[5/{total_steps}] Launch instructions")
            _print_launch_block(repo, demo_ids, config_summary)

    except Exception as exc:
        failures.append(f"Unexpected exception: {type(exc).__name__}: {exc}")
        _fail("UNEXPECTED EXCEPTION", f"{type(exc).__name__}: {exc}")
        if debug:
            traceback.print_exc()

    # ── Verdict ─────────────────────────────────────────────────────────────
    _section("Result")
    passed = len(failures) == 0
    if passed:
        print("  ✓  PASS — local demo environment is ready")
        if check_only:
            print("      (check-only: DB / seed no fueron tocados)")
    else:
        print(f"  ✗  FAIL — {len(failures)} issue(s):")
        for f in failures:
            print(f"        - {f}")

    return BootstrapResult(
        passed=passed,
        db_path=db_path,
        migrated=migrated,
        seeded=seeded,
        frontend_ok=frontend_ok,
        smoke_ok=smoke_ok,
        config_summary=config_summary,
        demo_ids=demo_ids,
        failures=failures,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap local environment for Case Dashboard + Workbench demo.",
    )
    parser.add_argument(
        "--db-path", type=Path, default=None,
        help="Ruta a la DB SQLite. Default: api_layer.main.DEFAULT_DB_PATH.",
    )
    parser.add_argument(
        "--skip-migrate", action="store_true",
        help="No aplicar migrations (asume schema actual).",
    )
    parser.add_argument(
        "--skip-seed", action="store_true",
        help="No correr seed_demo_data.",
    )
    parser.add_argument(
        "--run-smoke", action="store_true",
        help="Correr smoke check end-to-end en DB temporal aislada.",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="Solo verificar archivos + config; no tocar DB.",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Imprimir traceback en excepciones inesperadas.",
    )
    args = parser.parse_args(argv)

    result = bootstrap_local_demo(
        db_path=args.db_path,
        skip_migrate=args.skip_migrate,
        skip_seed=args.skip_seed,
        run_smoke=args.run_smoke,
        check_only=args.check_only,
        debug=args.debug,
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
