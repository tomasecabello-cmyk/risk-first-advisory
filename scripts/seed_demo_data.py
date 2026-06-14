"""
seed_demo_data.py — Crea/reusa entidades demo para Case Dashboard + Workbench.

Idempotente: corre múltiples veces sin duplicar datos. Las entidades demo
tienen IDs estables y reservados (`*_demo_local`):

    firm:    firm_demo_local
    advisor: advisor_demo_local
    client:  client_demo_local
    case:    case_demo_local

No requiere OpenAI ni servidor uvicorn (usa FastAPI TestClient internamente).
NO completa el workflow (KYC, AI analysis, approval, ...) — para eso usar
`scripts/run_case_workflow_smoke_check.py` o el Case Workbench frontend.

Ejecución:
    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --db-path data/demo_api.db
    python scripts/seed_demo_data.py --no-migrate

Exit codes:
    0 → PASS (todo creado o reutilizado limpiamente)
    1 → FAIL (al menos una entidad falló por motivo no idempotente)
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# UTF-8 stdout/stderr (Windows cp1252 crashea con ▶ ✓ ✗).
# Mismo patrón que scripts/migrate.py y scripts/run_case_workflow_smoke_check.py.
# ─────────────────────────────────────────────────────────────────────────────
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

DEMO_FIRM_ID    = "firm_demo_local"
DEMO_ADVISOR_ID = "advisor_demo_local"
DEMO_CLIENT_ID  = "client_demo_local"
DEMO_CASE_ID    = "case_demo_local"
DEMO_CASE_TITLE = "Demo advisory case"

# Tokens internos del seed script. Independientes de cualquier
# config/advisor_tokens.yaml productivo: el script escribe su propio YAML en
# tempdir y lo apunta vía ADVISOR_TOKENS_FILE env var. No afecta a uvicorn
# productivo ni al fallback dev tokens.
_SEED_ADMIN_TOKEN   = "seed-admin"
_SEED_ADVISOR_TOKEN = "seed-advisor"

_SEED_TOKENS_YAML = f"""\
tokens:
  {_SEED_ADMIN_TOKEN}:
    advisor_id: ADM-SEED-001
    display_name: Seed Admin
    firm_id: null
    roles: [admin]
  {_SEED_ADVISOR_TOKEN}:
    advisor_id: ADV-SEED-001
    display_name: Seed Advisor
    firm_id: null
    roles: [advisor]
"""

LINE = "=" * 70


# ─────────────────────────────────────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────────────────────────────────────


def _section(title: str) -> None:
    print()
    print(LINE)
    print(f"  {title}")
    print(LINE)


def _step(label: str) -> None:
    print(f"  ▶  {label}")


def _ok(label: str, detail: str = "") -> None:
    suffix = f" → {detail}" if detail else ""
    print(f"  ✓  {label}{suffix}")


def _reused(label: str, detail: str = "") -> None:
    suffix = f" → {detail}" if detail else ""
    print(f"  ↺  {label} (reused){suffix}")


def _fail(label: str, detail: str = "") -> None:
    suffix = f" → {detail}" if detail else ""
    print(f"  ✗  {label}{suffix}")


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SeedDemoResult:
    passed:     bool
    db_path:    Path
    firm_id:    str | None
    advisor_id: str | None
    client_id:  str | None
    case_id:    str | None
    # Per-entity status: "created", "reused", o "failed"
    firm_status:    str
    advisor_status: str
    client_status:  str
    case_status:    str
    failures:       list[str]


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────


def _import_migrate_module():
    """Importa scripts/migrate.py vía importlib (mismo patrón que otros scripts)."""
    migrate_path = ROOT / "scripts" / "migrate.py"
    spec = importlib.util.spec_from_file_location("rfa_migrate", migrate_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("rfa_migrate", module)
    spec.loader.exec_module(module)
    return module


def _install_seed_environment(db_path: Path, tokens_yaml: Path):
    """
    Monkeypatch DEFAULT_DB_PATH + ADVISOR_TOKENS_FILE env var + tokens path.
    Returns (main_module, tokens_module) ready to be used by TestClient.
    """
    import os

    import risk_first_advisory.api_layer.main as main_mod
    import risk_first_advisory.config_layer.advisor_tokens as tokens_mod

    main_mod.DEFAULT_DB_PATH = db_path
    # Apuntar el módulo de tokens al YAML del seed, vía env var.
    # No tocamos config/advisor_tokens.yaml del usuario; el seed siempre usa
    # el suyo propio en tempdir.
    tokens_mod.DEFAULT_ADVISOR_TOKENS_PATH = db_path.parent / "absent_seed_default.yaml"
    os.environ[tokens_mod.ADVISOR_TOKENS_ENV_VAR] = str(tokens_yaml)
    return main_mod, tokens_mod


def _build_test_client(main_mod):
    from fastapi.testclient import TestClient
    return TestClient(main_mod.app, raise_server_exceptions=False)


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _post(client, path: str, body: dict, token: str) -> Any:
    return client.post(path, json=body, headers=_auth_header(token))


def _get(client, path: str, token: str) -> Any:
    return client.get(path, headers=_auth_header(token))


# ─────────────────────────────────────────────────────────────────────────────
# Idempotent entity creation
# ─────────────────────────────────────────────────────────────────────────────


def _create_or_reuse_firm(client) -> tuple[str | None, str, str | None]:
    """
    Returns (firm_id, status, error). status in {created, reused, failed}.
    """
    body = {
        "firm_id":      DEMO_FIRM_ID,
        "display_name": "Demo Advisory Firm",
        "country":      "AR",
        "is_active":    True,
    }
    r = _post(client, "/firms", body, _SEED_ADMIN_TOKEN)
    if r.status_code == 201:
        return r.json().get("firm_id", DEMO_FIRM_ID), "created", None
    if r.status_code == 409:
        # Already exists — verify with GET
        rg = _get(client, f"/firms/{DEMO_FIRM_ID}", _SEED_ADMIN_TOKEN)
        if rg.status_code == 200:
            return DEMO_FIRM_ID, "reused", None
        return None, "failed", f"409 but GET returned {rg.status_code}"
    return None, "failed", f"HTTP {r.status_code}: {r.text[:200]}"


def _create_or_reuse_advisor(client) -> tuple[str | None, str, str | None]:
    body = {
        "advisor_id":   DEMO_ADVISOR_ID,
        "firm_id":      DEMO_FIRM_ID,
        "display_name": "Demo Advisor",
        "email":        "advisor.demo@example.local",
        "roles":        ["advisor"],
        "is_active":    True,
    }
    r = _post(client, "/advisors", body, _SEED_ADMIN_TOKEN)
    if r.status_code == 201:
        return r.json().get("advisor_id", DEMO_ADVISOR_ID), "created", None
    if r.status_code == 409:
        rg = _get(client, f"/advisors/{DEMO_ADVISOR_ID}", _SEED_ADMIN_TOKEN)
        if rg.status_code == 200:
            return DEMO_ADVISOR_ID, "reused", None
        return None, "failed", f"409 but GET returned {rg.status_code}"
    return None, "failed", f"HTTP {r.status_code}: {r.text[:200]}"


def _create_or_reuse_client(client) -> tuple[str | None, str, str | None]:
    body = {
        "client_id":          DEMO_CLIENT_ID,
        "firm_id":            DEMO_FIRM_ID,
        "primary_advisor_id": DEMO_ADVISOR_ID,
        "display_name":       "Demo Client",
        "jurisdiction":       "AR",
        "preferred_currency": "USD",
        "is_active":          True,
    }
    r = _post(client, "/clients", body, _SEED_ADMIN_TOKEN)
    if r.status_code == 201:
        return r.json().get("client_id", DEMO_CLIENT_ID), "created", None
    if r.status_code == 409:
        rg = _get(client, f"/clients/{DEMO_CLIENT_ID}", _SEED_ADMIN_TOKEN)
        if rg.status_code == 200:
            return DEMO_CLIENT_ID, "reused", None
        return None, "failed", f"409 but GET returned {rg.status_code}"
    return None, "failed", f"HTTP {r.status_code}: {r.text[:200]}"


def _create_or_reuse_case(client) -> tuple[str | None, str, str | None]:
    """
    Case usa case_id custom (DEMO_CASE_ID) que el backend acepta como
    override del auto-generado. Si ya existe → 409 → reuse.
    """
    body = {
        "case_id":         DEMO_CASE_ID,
        "firm_id":         DEMO_FIRM_ID,
        "client_id":       DEMO_CLIENT_ID,
        "lead_advisor_id": DEMO_ADVISOR_ID,
        "title":           DEMO_CASE_TITLE,
    }
    # POST /cases requiere rol advisor o admin; usamos seed-advisor para
    # que el AuditEvent case_created quede con actor_role=advisor (más
    # representativo del flujo real).
    r = _post(client, "/cases", body, _SEED_ADVISOR_TOKEN)
    if r.status_code == 201:
        return r.json().get("case_id", DEMO_CASE_ID), "created", None
    if r.status_code == 409:
        rg = _get(client, f"/cases/{DEMO_CASE_ID}", _SEED_ADVISOR_TOKEN)
        if rg.status_code == 200:
            return DEMO_CASE_ID, "reused", None
        return None, "failed", f"409 but GET returned {rg.status_code}"
    return None, "failed", f"HTTP {r.status_code}: {r.text[:200]}"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def seed_demo_data(
    *,
    db_path: Path | str | None = None,
    apply_migrations: bool = True,
    debug: bool = False,
) -> SeedDemoResult:
    """
    Crea o reusa firm + advisor + client + case demo en la DB indicada.

    Args:
        db_path: ruta a la DB SQLite. Si None, usa `api_layer.main.DEFAULT_DB_PATH`
                 (data/demo_api.db por default).
        apply_migrations: si True, corre `scripts/migrate.py` antes de seedear.
                          Por default True — un seed local debería garantizar
                          schema disponible.
        debug: si True, imprime traceback en excepciones inesperadas.

    Returns:
        `SeedDemoResult` con flags por entidad + estado global.
    """
    failures: list[str] = []
    firm_id = advisor_id = client_id = case_id = None
    firm_st = advisor_st = client_st = case_st = "failed"

    # ── Resolver db_path ────────────────────────────────────────────────────
    if db_path is None:
        import risk_first_advisory.api_layer.main as _main_for_default
        db_path = _main_for_default.DEFAULT_DB_PATH
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # tokens YAML del seed: tempdir junto al DB del seed.
    workdir = db_path.parent
    tokens_yaml = workdir / "_seed_tokens.yaml"
    tokens_yaml.write_text(_SEED_TOKENS_YAML, encoding="utf-8")

    _section("seed_demo_data — Phase 3 local seed")
    _step(f"DB path     : {db_path}")
    _step(f"Tokens YAML : {tokens_yaml}")

    try:
        # ── Migrations ──────────────────────────────────────────────────────
        if apply_migrations:
            _section("Step 1 / 2: apply migrations")
            migrate = _import_migrate_module()
            applied = migrate.run(
                db_path=db_path,
                migrations_dir=ROOT / "migrations",
                verbose=False,
            )
            _ok("migrations applied / verified", detail=f"{applied} pending")
        else:
            _step("(skip) --no-migrate flag set; assumes schema is current")

        # ── Install env, build TestClient, seed ────────────────────────────
        _section("Step 2 / 2: seed entities (idempotent)")
        main_mod, _ = _install_seed_environment(db_path, tokens_yaml)
        client = _build_test_client(main_mod)

        firm_id, firm_st, ferr = _create_or_reuse_firm(client)
        if firm_st == "failed":
            failures.append(f"firm: {ferr}")
            _fail("firm", ferr or "")
        elif firm_st == "created":
            _ok("firm", firm_id)
        else:
            _reused("firm", firm_id)

        if firm_id is not None:
            advisor_id, advisor_st, aerr = _create_or_reuse_advisor(client)
            if advisor_st == "failed":
                failures.append(f"advisor: {aerr}")
                _fail("advisor", aerr or "")
            elif advisor_st == "created":
                _ok("advisor", advisor_id)
            else:
                _reused("advisor", advisor_id)

        if advisor_id is not None:
            client_id, client_st, cerr = _create_or_reuse_client(client)
            if client_st == "failed":
                failures.append(f"client: {cerr}")
                _fail("client", cerr or "")
            elif client_st == "created":
                _ok("client", client_id)
            else:
                _reused("client", client_id)

        if client_id is not None:
            case_id, case_st, kerr = _create_or_reuse_case(client)
            if case_st == "failed":
                failures.append(f"case: {kerr}")
                _fail("case", kerr or "")
            elif case_st == "created":
                _ok("case", case_id)
            else:
                _reused("case", case_id)

    except Exception as exc:
        failures.append(f"Unexpected exception: {type(exc).__name__}: {exc}")
        _fail("UNEXPECTED EXCEPTION", f"{type(exc).__name__}: {exc}")
        if debug:
            traceback.print_exc()

    # ── Verdict ─────────────────────────────────────────────────────────────
    _section("Result")
    passed = len(failures) == 0
    if passed:
        print("  ✓  PASS — demo data ready")
        print(f"      firm_id    : {firm_id}    ({firm_st})")
        print(f"      advisor_id : {advisor_id} ({advisor_st})")
        print(f"      client_id  : {client_id}  ({client_st})")
        print(f"      case_id    : {case_id}    ({case_st})")
        print()
        print("  Next steps:")
        print("    Backend  : uvicorn risk_first_advisory.api_layer.main:app --reload")
        print("               http://127.0.0.1:8000/docs")
        print("    Frontend : python -m http.server 5500 -d frontend")
        print("               http://127.0.0.1:5500")
        print("    Tokens   :")
        print("      dev-admin-token       — admin role (setup)")
        print("      dev-advisor-token     — advisor role (workflow)")
        print("      dev-compliance-token  — audit/verify + ai-logs")
        print("      (Frontend default es dev-advisor-token; cambiar en input")
        print("       'Bearer token' del Case Dashboard según operación)")
    else:
        print(f"  ✗  FAIL — {len(failures)} failure(s):")
        for f in failures:
            print(f"        - {f}")

    return SeedDemoResult(
        passed=passed,
        db_path=db_path,
        firm_id=firm_id,
        advisor_id=advisor_id,
        client_id=client_id,
        case_id=case_id,
        firm_status=firm_st,
        advisor_status=advisor_st,
        client_status=client_st,
        case_status=case_st,
        failures=failures,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed demo data for Case Dashboard + Workbench (idempotent).",
    )
    parser.add_argument(
        "--db-path", type=Path, default=None,
        help="Ruta a la DB SQLite. Default: api_layer.main.DEFAULT_DB_PATH (data/demo_api.db).",
    )
    parser.add_argument(
        "--no-migrate", action="store_true",
        help="No aplicar migrations antes del seed (asume schema actual).",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Imprimir traceback en excepciones inesperadas.",
    )
    args = parser.parse_args(argv)

    result = seed_demo_data(
        db_path=args.db_path,
        apply_migrations=not args.no_migrate,
        debug=args.debug,
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
