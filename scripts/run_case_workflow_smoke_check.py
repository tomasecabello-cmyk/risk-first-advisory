"""
run_case_workflow_smoke_check.py — Smoke check end-to-end del workflow case-scoped
(Fase 2, candado de cierre).

Valida en una sola corrida que TODO el flujo case-scoped funciona:
    firm → advisor → client → case →
    KYC → AI profile analysis → profile approval →
    investment preferences → universe filter → portfolio proposal →
    override approval (si aplica) → portfolio selection → report →
    summary → audit verify

No requiere:
    - servidor uvicorn corriendo (usa FastAPI TestClient).
    - OPENAI_API_KEY real (mock determinístico de OpenAIProfileClient).
    - DB dev (usa una DB temporal con migrations aplicadas).

Ejecución:
    python scripts/run_case_workflow_smoke_check.py
    python scripts/run_case_workflow_smoke_check.py --keep-db
    python scripts/run_case_workflow_smoke_check.py --debug

Exit codes:
    0 → PASS
    1 → FAIL (al menos una validación falló)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# UTF-8 stdout/stderr (Windows cp1252 default crashea con ▶ ✓ ✗).
# Mismo patrón que scripts/migrate.py: errors='replace' garantiza que nunca
# crashee por encoding aunque el terminal no soporte el char.
# ─────────────────────────────────────────────────────────────────────────────
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ── Hacer importable el paquete src/ aunque no esté instalado ────────────────
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

LINE = "=" * 70
THIN = "-" * 70


_TOKENS_YAML_CONTENT = """\
tokens:
  smoke-admin:
    advisor_id: ADM-SMK-001
    display_name: Smoke Admin
    firm_id: null
    roles: [admin]
  smoke-advisor:
    advisor_id: ADV-SMK-001
    display_name: Smoke Advisor
    firm_id: null
    roles: [advisor]
  smoke-compliance:
    advisor_id: CMP-SMK-001
    display_name: Smoke Compliance
    firm_id: null
    roles: [compliance]
"""

_ADMIN     = "Bearer smoke-admin"
_ADVISOR   = "Bearer smoke-advisor"

# Mock AI response — perfil moderado, sin contradicciones (formato esperado
# por OpenAIProfileClient.analyze_kyc).
_MOCK_AI_KYC_RESPONSE: dict[str, Any] = {
    "preliminary_profile": "moderado",
    "confidence":          0.82,
    "contradictions":      [],
    "follow_up_questions": [],
    "advisor_notes":       ["Smoke check — perfil estable y sin red flags."],
}

# Demo KYC payload.
_DEMO_KYC: dict[str, Any] = {
    "age":                         40,
    "risk_tolerance_score":        6,
    "risk_capacity_score":         7,
    "liquidity_need_score":        3,
    "investment_horizon_years":    5,
    "investment_experience":       "moderada",
    "income_stability":            "stable",
    "net_worth":                   500_000.0,
    "liquid_net_worth":            150_000.0,
    "annual_income_usd":           80_000.0,
    "max_acceptable_drawdown_pct": 20.0,
    "jurisdiction":                "AR",
    "preferred_currency":          "USD",
    "investment_objective":        "balanced",
    "open_investment_goal":        "Ahorro de largo plazo con horizonte 5+ años.",
}

# Structured preferences amplias (compatibles con el fixture universe CSV).
# Permitir varios tipos de instrumento para que el filter no deje el universo
# vacío y el optimizer pueda generar candidates.
_DEMO_STRUCTURED_PREFS: dict[str, Any] = {
    "allowed_instrument_types": [
        "ETF", "CORPORATE_BOND", "SOVEREIGN_BOND",
        "STOCK", "CEDEAR", "MUTUAL_FUND", "MONEY_MARKET",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Pretty-print helpers
# ─────────────────────────────────────────────────────────────────────────────


def _section(title: str) -> None:
    print()
    print(LINE)
    print(f"  {title}")
    print(LINE)


def _step(label: str) -> None:
    print(f"  ▶  {label}")


def _ok(label: str, value: str = "") -> None:
    suffix = f" → {value}" if value else ""
    print(f"  ✓  {label}{suffix}")


def _warn(label: str, value: str = "") -> None:
    suffix = f" → {value}" if value else ""
    print(f"  !  {label}{suffix}")


def _fail(label: str, expected: Any, actual: Any) -> None:
    print(f"  ✗  {label}")
    print(f"      expected: {expected!r}")
    print(f"      actual:   {actual!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SmokeCheckResult:
    passed:           bool
    case_id:          str | None
    report_id:        str | None
    audit_intact:     bool
    completion_ratio: float
    next_action:      str
    db_path:          Path
    failures:         list[str]


# ─────────────────────────────────────────────────────────────────────────────
# Test client + AI stub setup
# ─────────────────────────────────────────────────────────────────────────────


def _import_migrate_module():
    """Importa scripts/migrate.py vía importlib (mismo patrón que los tests)."""
    migrate_path = ROOT / "scripts" / "migrate.py"
    spec = importlib.util.spec_from_file_location("rfa_migrate", migrate_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("rfa_migrate", module)
    spec.loader.exec_module(module)
    return module


def _build_fake_openai_chat(content: str) -> Any:
    """Construye un fake del openai.OpenAI() client (chat.completions.create)."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    cli = MagicMock()
    cli.chat.completions.create.return_value = completion
    return cli


def _install_stubs(db_path: Path, tokens_yaml: Path) -> None:
    """
    Instala los stubs / monkeypatches necesarios. Reemplaza:
        - DEFAULT_DB_PATH en api_layer.main → db_path
        - DEFAULT_ADVISOR_TOKENS_PATH en config_layer.advisor_tokens → ruta inexistente
        - ADVISOR_TOKENS_FILE env var → tokens_yaml
        - _get_openai_profile_client en api_layer.main → cliente con fake chat
    """
    import os

    import risk_first_advisory.api_layer.main as main_mod
    import risk_first_advisory.config_layer.advisor_tokens as tokens_mod
    from risk_first_advisory.ai_layer.openai_profile_client import (
        OpenAIProfileClient,
    )

    main_mod.DEFAULT_DB_PATH = db_path
    tokens_mod.DEFAULT_ADVISOR_TOKENS_PATH = db_path.parent / "absent_tokens.yaml"
    os.environ[tokens_mod.ADVISOR_TOKENS_ENV_VAR] = str(tokens_yaml)

    fake_chat = _build_fake_openai_chat(json.dumps(_MOCK_AI_KYC_RESPONSE))
    ai_client = OpenAIProfileClient(_client=fake_chat)
    main_mod._get_openai_profile_client = lambda: ai_client


def _build_test_client():
    """Construye un FastAPI TestClient con la app actual."""
    from fastapi.testclient import TestClient
    import risk_first_advisory.api_layer.main as main_mod

    return TestClient(main_mod.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers
# ─────────────────────────────────────────────────────────────────────────────


def _post(client: Any, path: str, body: dict, token: str = _ADVISOR) -> Any:
    return client.post(path, json=body, headers={"Authorization": token})


def _get(client: Any, path: str, token: str = _ADVISOR) -> Any:
    return client.get(path, headers={"Authorization": token})


def _expect(
    failures: list[str],
    condition: bool,
    label: str,
    *,
    expected: Any = None,
    actual: Any = None,
) -> bool:
    """Helper de aserción: registra failure si no se cumple. Devuelve la condition."""
    if condition:
        _ok(label, value=str(actual) if actual is not None else "")
        return True
    _fail(label, expected=expected, actual=actual)
    failures.append(label)
    return False


def _find_override_variant(proposal: dict) -> str | None:
    for c in proposal.get("candidates", []):
        meta = c.get("metadata") or {}
        if meta.get("requires_advisor_override") is True:
            return c.get("variant")
    return None


def _find_non_override_variant(proposal: dict) -> str | None:
    for c in proposal.get("candidates", []):
        meta = c.get("metadata") or {}
        if meta.get("requires_advisor_override") is False:
            return c.get("variant")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────


def run_case_workflow_smoke_check(
    *, db_path: Path | None = None, debug: bool = False
) -> SmokeCheckResult:
    """
    Ejecuta el smoke check end-to-end. Devuelve un `SmokeCheckResult`.

    Args:
        db_path: ruta a la DB SQLite. Si es None, se crea una temporal en
                 tempfile.mkdtemp() (no se limpia automáticamente).
        debug:   si True, imprime traceback completo en fallas.
    """
    failures: list[str] = []
    case_id: str | None = None
    report_id: str | None = None
    audit_intact = False
    completion_ratio = 0.0
    next_action = "unknown"

    # ── Setup DB temporal + tokens ──────────────────────────────────────────
    workdir: Path
    if db_path is None:
        workdir = Path(tempfile.mkdtemp(prefix="rfa_case_smoke_"))
        db_path = workdir / "case_smoke.db"
    else:
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        workdir = db_path.parent

    tokens_yaml = workdir / "smoke_tokens.yaml"
    tokens_yaml.write_text(_TOKENS_YAML_CONTENT, encoding="utf-8")

    _section("Case workflow smoke check — Phase 2 closing gate")
    _step(f"Workdir       : {workdir}")
    _step(f"DB path       : {db_path}")
    _step(f"Tokens YAML   : {tokens_yaml}")

    try:
        # ── Migrate ─────────────────────────────────────────────────────────
        _section("Step 1 / 14: migrate database")
        migrate = _import_migrate_module()
        migrations_dir = ROOT / "migrations"
        applied = migrate.run(
            db_path=db_path, migrations_dir=migrations_dir, verbose=False
        )
        _ok("migrations applied", value=str(applied))

        # ── Install stubs ───────────────────────────────────────────────────
        _section("Step 2 / 14: install stubs (no OpenAI, no uvicorn)")
        _install_stubs(db_path, tokens_yaml)
        _ok("stubs installed (DB path + tokens + OpenAI mock)")

        client = _build_test_client()
        _ok("FastAPI TestClient built")

        # ── Firm / Advisor / Client / Case ──────────────────────────────────
        _section("Step 3 / 14: firm + advisor + client + case")
        firm = _post(client, "/firms",
                     {"display_name": "Smoke Firm", "country": "AR"},
                     token=_ADMIN).json()
        _expect(failures, "firm_id" in firm, "firm created",
                expected="firm_id present", actual=firm.get("firm_id"))

        adv = _post(client, "/advisors", {
            "firm_id": firm["firm_id"],
            "advisor_id": "ADV-SMK-001",
            "display_name": "Smoke Advisor Entity",
            "email": "a@smk.com",
            "roles": ["advisor"],
        }, token=_ADMIN).json()
        _expect(failures, adv.get("advisor_id") == "ADV-SMK-001",
                "advisor created with matching token id",
                expected="ADV-SMK-001", actual=adv.get("advisor_id"))

        cli = _post(client, "/clients", {
            "firm_id": firm["firm_id"],
            "primary_advisor_id": adv["advisor_id"],
            "display_name": "Smoke Client",
        }, token=_ADMIN).json()
        _expect(failures, "client_id" in cli, "client created",
                actual=cli.get("client_id"))

        case_resp = _post(client, "/cases", {
            "firm_id": firm["firm_id"],
            "client_id": cli["client_id"],
            "lead_advisor_id": adv["advisor_id"],
            "title": "Smoke case workflow",
        })
        case = case_resp.json()
        _expect(failures, case_resp.status_code == 201,
                "case POST status 201", expected=201,
                actual=case_resp.status_code)
        case_id = case.get("case_id")
        _expect(failures, isinstance(case_id, str) and case_id.startswith("case_"),
                "case_id has correct prefix", actual=case_id)

        if case_id is None:
            raise RuntimeError("case_id missing; aborting smoke check.")

        # ── KYC ─────────────────────────────────────────────────────────────
        _section("Step 4 / 14: KYC submission")
        kyc = _post(client, f"/cases/{case_id}/kyc", _DEMO_KYC).json()
        _expect(failures, kyc.get("version") == 1,
                "kyc version == 1", expected=1, actual=kyc.get("version"))
        _expect(failures, kyc.get("kyc_submission_id", "").startswith("kyc_submission_"),
                "kyc_submission_id prefix", actual=kyc.get("kyc_submission_id"))

        # ── AI profile analysis ─────────────────────────────────────────────
        _section("Step 5 / 14: AI profile analysis (mocked)")
        analysis = _post(client, f"/cases/{case_id}/ai/profile-analysis", {}).json()
        _expect(failures, "analysis_id" in analysis,
                "analysis_id present", actual=analysis.get("analysis_id"))
        _expect(failures, analysis.get("preliminary_profile") == "moderado",
                "analysis preliminary_profile=moderado",
                expected="moderado", actual=analysis.get("preliminary_profile"))

        # ── Profile approval ────────────────────────────────────────────────
        _section("Step 6 / 14: advisor profile approval (approve)")
        approval = _post(client, f"/cases/{case_id}/profile-approval", {
            "decision": "approve",
            "rationale": "Perfil moderado consistente con KYC declarado.",
        }).json()
        _expect(failures, approval.get("decision") == "approve",
                "approval decision=approve", actual=approval.get("decision"))
        # Verificar que el case lo materializó:
        case_after_approval = _get(client, f"/cases/{case_id}").json()
        _expect(failures,
                case_after_approval.get("current_approved_profile_id") == approval.get("approval_id"),
                "case.current_approved_profile_id updated",
                expected=approval.get("approval_id"),
                actual=case_after_approval.get("current_approved_profile_id"))

        # ── Investment preferences ──────────────────────────────────────────
        _section("Step 7 / 14: investment preferences (structured manual)")
        pref = _post(client, f"/cases/{case_id}/investment-preferences", {
            "structured_preferences": _DEMO_STRUCTURED_PREFS,
        }).json()
        _expect(failures, "preference_id" in pref,
                "preference_id present", actual=pref.get("preference_id"))
        _expect(failures, pref.get("source") == "manual",
                "preference source=manual", actual=pref.get("source"))

        # ── Universe filter ─────────────────────────────────────────────────
        _section("Step 8 / 14: universe filter")
        filter_run = _post(client, f"/cases/{case_id}/universe-filter", {}).json()
        _expect(failures, filter_run.get("eligible_count", 0) > 0,
                "universe filter eligible_count > 0",
                actual=filter_run.get("eligible_count"))

        # ── Portfolio proposal ──────────────────────────────────────────────
        _section("Step 9 / 14: portfolio proposal")
        proposal = _post(client, f"/cases/{case_id}/portfolio-proposal", {}).json()
        _expect(failures, proposal.get("status") == "completed",
                "proposal.status == completed (required for full workflow)",
                expected="completed", actual=proposal.get("status"))
        candidates = proposal.get("candidates") or []
        _expect(failures, len(candidates) > 0,
                "proposal has candidates", actual=len(candidates))

        # ── Override approval (si aplica) ───────────────────────────────────
        #
        # Política del smoke check: si el proposal contiene CUALQUIER candidate
        # que requiera override (típicamente GROWTH), aprobamos el override
        # para ese variant y lo seleccionamos. Razón: el summary computa
        # `has_override_requirement` a nivel proposal (no a nivel selection),
        # entonces para alcanzar `completion_ratio=1.0` y
        # `next_action=ready_for_review` el smoke check debe ejercitar el
        # path con override. También cubre el caso productivo más interesante.
        _section("Step 10 / 14: override approval (if required)")
        override_variant = _find_override_variant(proposal)
        non_override_variant = _find_non_override_variant(proposal)
        if override_variant is not None:
            _step(f"override-requiring variant present; approving for {override_variant}")
            ovr = _post(client, f"/cases/{case_id}/override-approval", {
                "candidate_variant": override_variant,
                "decision": "approve",
                "rationale": "Smoke check: aprobando override para ejercitar path completo.",
            }).json()
            _expect(failures, ovr.get("decision") == "approve",
                    "override decision=approve", actual=ovr.get("decision"))
            chosen_variant = override_variant
        elif non_override_variant is not None:
            _ok("no override-requiring variant; selecting non-override variant",
                value=non_override_variant)
            chosen_variant = non_override_variant
        else:
            failures.append("No usable candidate variants in proposal")
            _fail("no candidate variants available", expected=">=1", actual=0)
            chosen_variant = ""

        # ── Portfolio selection ─────────────────────────────────────────────
        _section("Step 11 / 14: portfolio selection")
        selection = _post(client, f"/cases/{case_id}/portfolio-selection", {
            "selected_variant": chosen_variant,
            "rationale": f"Smoke check: seleccionando {chosen_variant}.",
        }).json()
        _expect(failures,
                selection.get("selected_variant") == chosen_variant,
                "selection.selected_variant matches",
                expected=chosen_variant, actual=selection.get("selected_variant"))
        case_after_selection = _get(client, f"/cases/{case_id}").json()
        _expect(failures,
                case_after_selection.get("status") == "PORTFOLIO_SELECTED",
                "case status transitioned to PORTFOLIO_SELECTED",
                expected="PORTFOLIO_SELECTED",
                actual=case_after_selection.get("status"))

        # ── Report ──────────────────────────────────────────────────────────
        _section("Step 12 / 14: case report (markdown)")
        report = _post(client, f"/cases/{case_id}/reports", {}).json()
        report_id = report.get("report_id")
        _expect(failures,
                isinstance(report_id, str) and report_id.startswith("case_report_"),
                "report_id has correct prefix", actual=report_id)
        markdown = report.get("markdown", "")
        _expect(failures, isinstance(markdown, str) and len(markdown) > 100,
                "report markdown non-empty (>100 chars)",
                actual=f"{len(markdown)} chars")
        _expect(failures, case_id in markdown,
                "report markdown contains case_id")
        _expect(failures, chosen_variant in markdown,
                "report markdown contains selected variant")

        # ── Summary ─────────────────────────────────────────────────────────
        _section("Step 13 / 14: case summary")
        summary = _get(client, f"/cases/{case_id}/summary").json()
        progress = summary.get("progress") or {}
        _expect(failures, progress.get("has_report") is True,
                "summary.progress.has_report is True",
                actual=progress.get("has_report"))
        next_action = progress.get("next_recommended_action", "")
        _expect(failures, next_action == "ready_for_review",
                "summary.progress.next_recommended_action == ready_for_review",
                expected="ready_for_review", actual=next_action)
        completion_ratio = float(progress.get("completion_ratio", 0.0))
        _expect(failures, completion_ratio == 1.0,
                "summary.progress.completion_ratio == 1.0",
                expected=1.0, actual=completion_ratio)
        ai = summary.get("ai") or {}
        _expect(failures, ai.get("ai_logs_count", 0) >= 1,
                "summary.ai.ai_logs_count >= 1",
                actual=ai.get("ai_logs_count"))

        # ── Audit verify ────────────────────────────────────────────────────
        _section("Step 14 / 14: audit chain verify")
        verify = _get(client, f"/cases/{case_id}/audit/verify",
                      token=_ADMIN).json()
        audit_intact = bool(verify.get("is_intact"))
        _expect(failures, audit_intact is True,
                "audit.is_intact == True", actual=audit_intact)
        _expect(failures, int(verify.get("total_events", 0)) >= 7,
                "audit.total_events >= 7 (case_created + kyc + analysis + approval + prefs + filter + proposal + selection + report)",
                actual=verify.get("total_events"))

    except Exception as exc:
        failures.append(f"Unexpected exception: {type(exc).__name__}: {exc}")
        print()
        print(THIN)
        print(f"  ✗  UNEXPECTED EXCEPTION: {type(exc).__name__}: {exc}")
        if debug:
            traceback.print_exc()

    # ── Final verdict ────────────────────────────────────────────────────────
    _section("Result")
    passed = len(failures) == 0
    if passed:
        print(f"  ✓  PASS — case workflow smoke check completed")
        print(f"      case_id          : {case_id}")
        print(f"      report_id        : {report_id}")
        print(f"      audit intact     : {audit_intact}")
        print(f"      completion ratio : {completion_ratio}")
        print(f"      next action      : {next_action}")
    else:
        print(f"  ✗  FAIL — {len(failures)} failure(s):")
        for f in failures:
            print(f"        - {f}")

    return SmokeCheckResult(
        passed=passed,
        case_id=case_id,
        report_id=report_id,
        audit_intact=audit_intact,
        completion_ratio=completion_ratio,
        next_action=next_action,
        db_path=db_path,
        failures=failures,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end smoke check del workflow case-scoped (Fase 2).",
    )
    parser.add_argument(
        "--db-path", type=Path, default=None,
        help="Ruta a la DB SQLite. Default: tempdir.",
    )
    parser.add_argument(
        "--keep-db", action="store_true",
        help="No borrar la DB temporal al terminar (útil para inspección).",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Imprime traceback completo si hay excepciones.",
    )
    args = parser.parse_args(argv)

    result = run_case_workflow_smoke_check(
        db_path=args.db_path, debug=args.debug
    )

    # Cleanup: solo si fue tempdir y --keep-db no se pasó.
    if (
        args.db_path is None
        and not args.keep_db
        and result.db_path is not None
    ):
        try:
            shutil.rmtree(result.db_path.parent, ignore_errors=True)
        except Exception:
            pass

    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
