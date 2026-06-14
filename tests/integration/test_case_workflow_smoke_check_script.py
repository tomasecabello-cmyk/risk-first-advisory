"""
Integration tests for scripts/run_case_workflow_smoke_check.py (Phase 2 candado).

Valida:
    - La función `run_case_workflow_smoke_check()` devuelve PASS sin args.
    - `main()` devuelve exit code 0 cuando todo pasa.
    - El script no requiere OPENAI_API_KEY real.
    - El script no toca la DB dev permanente (usa tempdir o el db_path dado).
    - Output incluye PASS, case_id, report_id, audit intact.

Se testea via función expuesta + `main()` directo (no subprocess) para evitar
problemas de entorno cross-platform. La función expone `SmokeCheckResult`
para aserciones programáticas.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Importar el script vía importlib (no es paquete instalable).
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "run_case_workflow_smoke_check.py"

_spec = importlib.util.spec_from_file_location(
    "rfa_case_workflow_smoke_check", _SCRIPT_PATH
)
assert _spec is not None and _spec.loader is not None
_smoke_check = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("rfa_case_workflow_smoke_check", _smoke_check)
_spec.loader.exec_module(_smoke_check)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRunFunction:
    def test_returns_pass_with_no_args(self, tmp_path: Path) -> None:
        # Usar tmp_path explícito para que NO use tempfile.mkdtemp (que
        # quedaría sin limpiar si el test falla).
        db_path = tmp_path / "smoke.db"
        result = _smoke_check.run_case_workflow_smoke_check(db_path=db_path)
        assert result.passed is True, f"Failures: {result.failures}"

    def test_result_has_case_id(self, tmp_path: Path) -> None:
        result = _smoke_check.run_case_workflow_smoke_check(
            db_path=tmp_path / "smoke.db"
        )
        assert result.case_id is not None
        assert result.case_id.startswith("case_")

    def test_result_has_report_id(self, tmp_path: Path) -> None:
        result = _smoke_check.run_case_workflow_smoke_check(
            db_path=tmp_path / "smoke.db"
        )
        assert result.report_id is not None
        assert result.report_id.startswith("case_report_")

    def test_audit_intact(self, tmp_path: Path) -> None:
        result = _smoke_check.run_case_workflow_smoke_check(
            db_path=tmp_path / "smoke.db"
        )
        assert result.audit_intact is True

    def test_completion_ratio_one(self, tmp_path: Path) -> None:
        result = _smoke_check.run_case_workflow_smoke_check(
            db_path=tmp_path / "smoke.db"
        )
        assert result.completion_ratio == 1.0

    def test_next_action_ready_for_review(self, tmp_path: Path) -> None:
        result = _smoke_check.run_case_workflow_smoke_check(
            db_path=tmp_path / "smoke.db"
        )
        assert result.next_action == "ready_for_review"

    def test_no_failures(self, tmp_path: Path) -> None:
        result = _smoke_check.run_case_workflow_smoke_check(
            db_path=tmp_path / "smoke.db"
        )
        assert result.failures == []

    def test_uses_given_db_path(self, tmp_path: Path) -> None:
        db_path = tmp_path / "subdir" / "custom.db"
        result = _smoke_check.run_case_workflow_smoke_check(db_path=db_path)
        assert result.db_path == db_path
        assert db_path.exists()


class TestMainEntrypoint:
    def test_main_returns_zero_with_db_path(self, tmp_path: Path) -> None:
        db_path = tmp_path / "main.db"
        exit_code = _smoke_check.main(["--db-path", str(db_path)])
        assert exit_code == 0

    def test_main_returns_zero_with_keep_db(self, tmp_path: Path) -> None:
        # --keep-db combinado con --db-path explícito no debería borrar nada.
        db_path = tmp_path / "keep.db"
        exit_code = _smoke_check.main(
            ["--db-path", str(db_path), "--keep-db"]
        )
        assert exit_code == 0
        assert db_path.exists()


class TestOutput:
    def test_output_contains_pass(self, tmp_path: Path) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            _smoke_check.run_case_workflow_smoke_check(
                db_path=tmp_path / "smoke.db"
            )
        output = buf.getvalue()
        assert "PASS" in output

    def test_output_contains_case_id(self, tmp_path: Path) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = _smoke_check.run_case_workflow_smoke_check(
                db_path=tmp_path / "smoke.db"
            )
        output = buf.getvalue()
        assert result.case_id is not None
        assert result.case_id in output

    def test_output_contains_report_id(self, tmp_path: Path) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = _smoke_check.run_case_workflow_smoke_check(
                db_path=tmp_path / "smoke.db"
            )
        output = buf.getvalue()
        assert result.report_id is not None
        assert result.report_id in output

    def test_output_mentions_audit_intact(self, tmp_path: Path) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            _smoke_check.run_case_workflow_smoke_check(
                db_path=tmp_path / "smoke.db"
            )
        output = buf.getvalue()
        # Header del audit step y/o resumen final mencionan "audit"
        assert "audit" in output.lower()
        assert "intact" in output.lower() or "True" in output


class TestNoExternalDeps:
    def test_no_openai_api_key_required(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El script debe pasar incluso sin OPENAI_API_KEY en el entorno."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = _smoke_check.run_case_workflow_smoke_check(
            db_path=tmp_path / "smoke.db"
        )
        assert result.passed is True, f"Failures: {result.failures}"

    def test_does_not_touch_dev_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El script no debe escribir en data/demo_api.db ni en la DB dev."""
        dev_db = _PROJECT_ROOT / "data" / "demo_api.db"
        dev_db_mtime_before = (
            dev_db.stat().st_mtime if dev_db.exists() else None
        )
        # Correr en una DB temporal explícita.
        result = _smoke_check.run_case_workflow_smoke_check(
            db_path=tmp_path / "smoke.db"
        )
        assert result.passed is True
        # La DB dev no fue tocada (mtime no cambió o sigue sin existir).
        dev_db_mtime_after = (
            dev_db.stat().st_mtime if dev_db.exists() else None
        )
        assert dev_db_mtime_before == dev_db_mtime_after, (
            "Smoke check tocó la DB dev (data/demo_api.db) — debe usar tmp_path."
        )


class TestImportable:
    def test_run_function_is_callable(self) -> None:
        assert callable(_smoke_check.run_case_workflow_smoke_check)

    def test_main_is_callable(self) -> None:
        assert callable(_smoke_check.main)

    def test_smoke_check_result_dataclass_present(self) -> None:
        assert hasattr(_smoke_check, "SmokeCheckResult")
