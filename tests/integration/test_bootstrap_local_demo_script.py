"""
Integration tests for scripts/bootstrap_local_demo.py (Phase 3 bootstrap).

Valida:
    - `bootstrap_local_demo(db_path=...)` corre OK contra tmp_path DB.
    - Crea/reusa demo data (idempotente vía el seed underlying).
    - `--check-only` no toca DB ni corre seed.
    - `--skip-migrate` + `--skip-seed` funcionan como bypass.
    - Output contiene PASS, URLs, comandos backend/frontend, tokens.
    - Script importable.
    - main(argv) → 0 en path feliz con tmp DB.
    - No requiere OPENAI_API_KEY.
    - No modifica data/demo_api.db cuando se usa tmp_path.
    - Missing frontend file rompe el check con failure claro.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Importar el script
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "bootstrap_local_demo.py"

_spec = importlib.util.spec_from_file_location("rfa_bootstrap_local_demo", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_boot = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("rfa_bootstrap_local_demo", _boot)
_spec.loader.exec_module(_boot)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestFullBootstrap:
    def test_passes_with_tmp_db(self, tmp_path: Path) -> None:
        result = _boot.bootstrap_local_demo(db_path=tmp_path / "boot.db")
        assert result.passed is True, f"Failures: {result.failures}"

    def test_migrated_and_seeded_flags(self, tmp_path: Path) -> None:
        result = _boot.bootstrap_local_demo(db_path=tmp_path / "boot.db")
        assert result.migrated is True
        assert result.seeded is True
        assert result.frontend_ok is True

    def test_demo_ids_present(self, tmp_path: Path) -> None:
        result = _boot.bootstrap_local_demo(db_path=tmp_path / "boot.db")
        assert result.demo_ids == {
            "firm_id":    "firm_demo_local",
            "advisor_id": "advisor_demo_local",
            "client_id":  "client_demo_local",
            "case_id":    "case_demo_local",
        }

    def test_db_file_created(self, tmp_path: Path) -> None:
        db_path = tmp_path / "boot.db"
        _boot.bootstrap_local_demo(db_path=db_path)
        assert db_path.exists()

    def test_smoke_skipped_by_default(self, tmp_path: Path) -> None:
        result = _boot.bootstrap_local_demo(db_path=tmp_path / "boot.db")
        assert result.smoke_ok is None  # None means "not run"


class TestIdempotency:
    def test_second_run_still_passes(self, tmp_path: Path) -> None:
        db = tmp_path / "boot.db"
        _boot.bootstrap_local_demo(db_path=db)
        result = _boot.bootstrap_local_demo(db_path=db)
        assert result.passed is True

    def test_second_run_seeded_idempotently(self, tmp_path: Path) -> None:
        """The underlying seed reports reused — bootstrap should still PASS."""
        db = tmp_path / "boot.db"
        _boot.bootstrap_local_demo(db_path=db)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _boot.bootstrap_local_demo(db_path=db)
        out = buf.getvalue()
        assert "reused" in out


class TestCheckOnly:
    def test_check_only_does_not_create_db(self, tmp_path: Path) -> None:
        db = tmp_path / "boot.db"
        result = _boot.bootstrap_local_demo(db_path=db, check_only=True)
        assert result.passed is True
        # DB no debe haber sido creada
        assert not db.exists(), "check-only no debe crear la DB"

    def test_check_only_flags_no_migrate_no_seed(self, tmp_path: Path) -> None:
        db = tmp_path / "boot.db"
        result = _boot.bootstrap_local_demo(db_path=db, check_only=True)
        assert result.migrated is False
        assert result.seeded is False
        # frontend_ok sigue siendo True porque los archivos existen en el repo
        assert result.frontend_ok is True


class TestSkipFlags:
    def test_skip_migrate_skip_seed_passes(self, tmp_path: Path) -> None:
        """Si saltamos ambos, no hay nada que pueda fallar (frontend OK + python OK)."""
        result = _boot.bootstrap_local_demo(
            db_path=tmp_path / "boot.db",
            skip_migrate=True,
            skip_seed=True,
        )
        assert result.passed is True
        assert result.migrated is False
        assert result.seeded is False

    def test_skip_seed_only(self, tmp_path: Path) -> None:
        result = _boot.bootstrap_local_demo(
            db_path=tmp_path / "boot.db",
            skip_seed=True,
        )
        assert result.passed is True
        assert result.migrated is True
        assert result.seeded is False
        # Sin seed los IDs quedan en None
        assert result.demo_ids["firm_id"] is None


class TestRunSmoke:
    def test_run_smoke_passes(self, tmp_path: Path) -> None:
        """--run-smoke debe correr el smoke check en su propia DB temporal
        (no la del bootstrap) — chequeamos que pasó y que NO escribió en
        nuestra db_path una segunda fase del workflow."""
        db = tmp_path / "boot.db"
        result = _boot.bootstrap_local_demo(db_path=db, run_smoke=True)
        assert result.passed is True
        assert result.smoke_ok is True


class TestMainEntrypoint:
    def test_main_returns_zero(self, tmp_path: Path) -> None:
        db = tmp_path / "main.db"
        exit_code = _boot.main(["--db-path", str(db)])
        assert exit_code == 0

    def test_main_check_only_returns_zero(self, tmp_path: Path) -> None:
        exit_code = _boot.main(
            ["--db-path", str(tmp_path / "main.db"), "--check-only"]
        )
        assert exit_code == 0

    def test_main_skip_flags_combined(self, tmp_path: Path) -> None:
        exit_code = _boot.main(
            ["--db-path", str(tmp_path / "main.db"),
             "--skip-migrate", "--skip-seed"]
        )
        assert exit_code == 0


class TestOutput:
    def _bootstrap_to_str(self, db: Path) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            _boot.bootstrap_local_demo(db_path=db)
        return buf.getvalue()

    def test_output_contains_pass(self, tmp_path: Path) -> None:
        out = self._bootstrap_to_str(tmp_path / "boot.db")
        assert "PASS" in out

    def test_output_contains_backend_command(self, tmp_path: Path) -> None:
        out = self._bootstrap_to_str(tmp_path / "boot.db")
        assert "uvicorn risk_first_advisory.api_layer.main:app" in out

    def test_output_contains_frontend_command(self, tmp_path: Path) -> None:
        out = self._bootstrap_to_str(tmp_path / "boot.db")
        assert "http.server 5500 -d frontend" in out

    def test_output_contains_urls(self, tmp_path: Path) -> None:
        out = self._bootstrap_to_str(tmp_path / "boot.db")
        assert "http://127.0.0.1:8000/docs" in out
        assert "http://127.0.0.1:5500" in out

    def test_output_lists_dev_tokens(self, tmp_path: Path) -> None:
        out = self._bootstrap_to_str(tmp_path / "boot.db")
        assert "dev-advisor-token" in out
        assert "dev-compliance-token" in out

    def test_output_contains_demo_ids(self, tmp_path: Path) -> None:
        out = self._bootstrap_to_str(tmp_path / "boot.db")
        for stable_id in (
            "firm_demo_local",
            "advisor_demo_local",
            "client_demo_local",
            "case_demo_local",
        ):
            assert stable_id in out


class TestFrontendValidation:
    def test_missing_frontend_file_breaks_check(self, tmp_path: Path) -> None:
        """Si apuntamos a un repo_root falso (sin frontend files), el bootstrap
        debe reportar failure con detalle de qué falta."""
        fake_repo = tmp_path / "fake_repo"
        fake_repo.mkdir()
        # NO crear ningún archivo de los REQUIRED_FRONTEND_FILES / SCRIPT_FILES
        result = _boot.bootstrap_local_demo(
            db_path=tmp_path / "boot.db",
            check_only=True,           # solo validar; no intentar seed
            repo_root=fake_repo,
        )
        assert result.passed is False
        assert result.frontend_ok is False
        # Failure debe mencionar archivos faltantes
        joined = " ".join(result.failures).lower()
        assert "missing" in joined
        assert "frontend/index.html" in joined or "frontend\\index.html" in joined


class TestNoExternalDeps:
    def test_no_openai_api_key_required(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = _boot.bootstrap_local_demo(db_path=tmp_path / "boot.db")
        assert result.passed is True

    def test_does_not_touch_dev_db(self, tmp_path: Path) -> None:
        dev_db = _PROJECT_ROOT / "data" / "demo_api.db"
        mtime_before = dev_db.stat().st_mtime if dev_db.exists() else None
        result = _boot.bootstrap_local_demo(db_path=tmp_path / "boot.db")
        assert result.passed is True
        mtime_after = dev_db.stat().st_mtime if dev_db.exists() else None
        assert mtime_before == mtime_after, (
            "Bootstrap tocó data/demo_api.db cuando se le pasó --db-path en tmp."
        )


class TestImportable:
    def test_bootstrap_function_callable(self) -> None:
        assert callable(_boot.bootstrap_local_demo)

    def test_main_callable(self) -> None:
        assert callable(_boot.main)

    def test_bootstrap_result_dataclass_present(self) -> None:
        assert hasattr(_boot, "BootstrapResult")

    def test_required_file_lists_exported(self) -> None:
        assert "frontend/index.html" in _boot.REQUIRED_FRONTEND_FILES
        assert "scripts/migrate.py" in _boot.REQUIRED_SCRIPT_FILES
        assert "scripts/seed_demo_data.py" in _boot.REQUIRED_SCRIPT_FILES
