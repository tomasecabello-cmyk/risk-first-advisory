"""
Integration tests for scripts/seed_demo_data.py (Phase 3 seed).

Valida:
    - `seed_demo_data(db_path=...)` crea las 4 entidades en la primera corrida.
    - Segunda corrida es idempotente (todas reused, mismos IDs).
    - DB contiene firm + advisor + client + case con los IDs estables.
    - Output incluye PASS + IDs.
    - No requiere OPENAI_API_KEY.
    - No toca data/demo_api.db cuando se usa --db-path tmp.
    - `main(['--db-path', ...])` exit code 0.
    - Script importable.

Se testea via función directa + main entrypoint (no subprocess) — mismo
patrón que test_case_workflow_smoke_check_script.py.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Importar el script vía importlib
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "seed_demo_data.py"

_spec = importlib.util.spec_from_file_location("rfa_seed_demo_data", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_seed = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("rfa_seed_demo_data", _seed)
_spec.loader.exec_module(_seed)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSeedFunction:
    def test_first_run_passes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "seed.db"
        result = _seed.seed_demo_data(db_path=db_path)
        assert result.passed is True, f"Failures: {result.failures}"

    def test_first_run_creates_all_four(self, tmp_path: Path) -> None:
        result = _seed.seed_demo_data(db_path=tmp_path / "seed.db")
        assert result.firm_status    == "created"
        assert result.advisor_status == "created"
        assert result.client_status  == "created"
        assert result.case_status    == "created"

    def test_first_run_returns_expected_stable_ids(self, tmp_path: Path) -> None:
        result = _seed.seed_demo_data(db_path=tmp_path / "seed.db")
        assert result.firm_id    == "firm_demo_local"
        assert result.advisor_id == "advisor_demo_local"
        assert result.client_id  == "client_demo_local"
        assert result.case_id    == "case_demo_local"

    def test_result_db_path_matches_input(self, tmp_path: Path) -> None:
        db_path = tmp_path / "subdir" / "custom.db"
        result = _seed.seed_demo_data(db_path=db_path)
        assert result.db_path == db_path
        assert db_path.exists()


class TestIdempotency:
    def test_second_run_passes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "seed.db"
        _seed.seed_demo_data(db_path=db_path)
        result = _seed.seed_demo_data(db_path=db_path)
        assert result.passed is True, f"Failures: {result.failures}"

    def test_second_run_reports_all_reused(self, tmp_path: Path) -> None:
        db_path = tmp_path / "seed.db"
        _seed.seed_demo_data(db_path=db_path)
        result = _seed.seed_demo_data(db_path=db_path)
        assert result.firm_status    == "reused"
        assert result.advisor_status == "reused"
        assert result.client_status  == "reused"
        assert result.case_status    == "reused"

    def test_third_run_still_passes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "seed.db"
        _seed.seed_demo_data(db_path=db_path)
        _seed.seed_demo_data(db_path=db_path)
        result = _seed.seed_demo_data(db_path=db_path)
        assert result.passed is True

    def test_idempotent_no_duplicate_firm(self, tmp_path: Path) -> None:
        """Garantía: 2 runs no producen 2 firms."""
        db_path = tmp_path / "seed.db"
        _seed.seed_demo_data(db_path=db_path)
        _seed.seed_demo_data(db_path=db_path)
        # Query DB directly via repos to count.
        from risk_first_advisory.persistence_layer.entity_repository import (
            SQLiteEntityStore,
            SQLiteFirmRepository,
        )
        with SQLiteEntityStore(db_path) as store:
            firms = SQLiteFirmRepository(store).list_all()
        assert len(firms) == 1, f"Expected 1 firm, got {len(firms)}: {firms}"

    def test_idempotent_no_duplicate_case(self, tmp_path: Path) -> None:
        db_path = tmp_path / "seed.db"
        _seed.seed_demo_data(db_path=db_path)
        _seed.seed_demo_data(db_path=db_path)
        from risk_first_advisory.persistence_layer.entity_repository import (
            SQLiteAdvisoryCaseRepository,
            SQLiteEntityStore,
        )
        with SQLiteEntityStore(db_path) as store:
            cases = SQLiteAdvisoryCaseRepository(store).list_all()
        assert len(cases) == 1, f"Expected 1 case, got {len(cases)}"
        assert cases[0]["case_id"] == "case_demo_local"


class TestDbContents:
    def test_db_contains_demo_firm(self, tmp_path: Path) -> None:
        db_path = tmp_path / "seed.db"
        _seed.seed_demo_data(db_path=db_path)
        from risk_first_advisory.persistence_layer.entity_repository import (
            SQLiteEntityStore,
            SQLiteFirmRepository,
        )
        with SQLiteEntityStore(db_path) as store:
            firm = SQLiteFirmRepository(store).get("firm_demo_local")
        assert firm is not None
        assert firm["display_name"] == "Demo Advisory Firm"
        assert firm["country"] == "AR"

    def test_db_contains_demo_advisor(self, tmp_path: Path) -> None:
        db_path = tmp_path / "seed.db"
        _seed.seed_demo_data(db_path=db_path)
        from risk_first_advisory.persistence_layer.entity_repository import (
            SQLiteAdvisorRepository,
            SQLiteEntityStore,
        )
        with SQLiteEntityStore(db_path) as store:
            adv = SQLiteAdvisorRepository(store).get("advisor_demo_local")
        assert adv is not None
        assert adv["firm_id"] == "firm_demo_local"
        assert "advisor" in adv["roles"]

    def test_db_contains_demo_client(self, tmp_path: Path) -> None:
        db_path = tmp_path / "seed.db"
        _seed.seed_demo_data(db_path=db_path)
        from risk_first_advisory.persistence_layer.entity_repository import (
            SQLiteClientRepository,
            SQLiteEntityStore,
        )
        with SQLiteEntityStore(db_path) as store:
            cli = SQLiteClientRepository(store).get("client_demo_local")
        assert cli is not None
        assert cli["firm_id"] == "firm_demo_local"
        assert cli["primary_advisor_id"] == "advisor_demo_local"

    def test_db_contains_demo_case_with_correct_links(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "seed.db"
        _seed.seed_demo_data(db_path=db_path)
        from risk_first_advisory.persistence_layer.entity_repository import (
            SQLiteAdvisoryCaseRepository,
            SQLiteEntityStore,
        )
        with SQLiteEntityStore(db_path) as store:
            case = SQLiteAdvisoryCaseRepository(store).get("case_demo_local")
        assert case is not None
        assert case["firm_id"]         == "firm_demo_local"
        assert case["client_id"]       == "client_demo_local"
        assert case["lead_advisor_id"] == "advisor_demo_local"
        assert case["title"]           == "Demo advisory case"
        assert case["status"]          == "DRAFT"

    def test_case_created_audit_event_emitted(self, tmp_path: Path) -> None:
        """POST /cases siempre emite case_created — el seed debe registrarlo."""
        db_path = tmp_path / "seed.db"
        _seed.seed_demo_data(db_path=db_path)
        from risk_first_advisory.persistence_layer.entity_repository import (
            SQLiteAuditEventRepository,
            SQLiteEntityStore,
        )
        with SQLiteEntityStore(db_path) as store:
            events = SQLiteAuditEventRepository(store).list_by_case("case_demo_local")
        types = [e["event_type"] for e in events]
        assert "case_created" in types


class TestMainEntrypoint:
    def test_main_returns_zero(self, tmp_path: Path) -> None:
        db_path = tmp_path / "main.db"
        exit_code = _seed.main(["--db-path", str(db_path)])
        assert exit_code == 0

    def test_main_idempotent_zero(self, tmp_path: Path) -> None:
        db_path = tmp_path / "main.db"
        assert _seed.main(["--db-path", str(db_path)]) == 0
        assert _seed.main(["--db-path", str(db_path)]) == 0

    def test_main_no_migrate_flag_passes_when_schema_present(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "main.db"
        # Primer run aplica migrations + seedea.
        assert _seed.main(["--db-path", str(db_path)]) == 0
        # Segundo run con --no-migrate todavía debería pasar (schema ya está).
        assert _seed.main(["--db-path", str(db_path), "--no-migrate"]) == 0


class TestOutput:
    def test_output_contains_pass(self, tmp_path: Path) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            _seed.seed_demo_data(db_path=tmp_path / "seed.db")
        out = buf.getvalue()
        assert "PASS" in out

    def test_output_contains_all_demo_ids(self, tmp_path: Path) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            _seed.seed_demo_data(db_path=tmp_path / "seed.db")
        out = buf.getvalue()
        for stable_id in (
            "firm_demo_local",
            "advisor_demo_local",
            "client_demo_local",
            "case_demo_local",
        ):
            assert stable_id in out, f"missing {stable_id} in output"

    def test_output_mentions_frontend_and_backend_urls(
        self, tmp_path: Path
    ) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            _seed.seed_demo_data(db_path=tmp_path / "seed.db")
        out = buf.getvalue()
        assert "http://127.0.0.1:8000/docs" in out
        assert "http://127.0.0.1:5500" in out

    def test_output_lists_dev_tokens(self, tmp_path: Path) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            _seed.seed_demo_data(db_path=tmp_path / "seed.db")
        out = buf.getvalue()
        assert "dev-admin-token" in out
        assert "dev-advisor-token" in out

    def test_second_run_output_says_reused(self, tmp_path: Path) -> None:
        db_path = tmp_path / "seed.db"
        _seed.seed_demo_data(db_path=db_path)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _seed.seed_demo_data(db_path=db_path)
        out = buf.getvalue()
        # 4 entities reused — match el marker que usa _reused()
        assert "(reused)" in out
        assert out.count("(reused)") >= 4


class TestNoExternalDeps:
    def test_no_openai_api_key_required(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = _seed.seed_demo_data(db_path=tmp_path / "seed.db")
        assert result.passed is True

    def test_does_not_touch_dev_db(
        self, tmp_path: Path
    ) -> None:
        dev_db = _PROJECT_ROOT / "data" / "demo_api.db"
        mtime_before = dev_db.stat().st_mtime if dev_db.exists() else None
        result = _seed.seed_demo_data(db_path=tmp_path / "seed.db")
        assert result.passed is True
        mtime_after = dev_db.stat().st_mtime if dev_db.exists() else None
        assert mtime_before == mtime_after, (
            "Seed script tocó data/demo_api.db cuando se le pasó --db-path en tmp."
        )


class TestImportable:
    def test_seed_function_is_callable(self) -> None:
        assert callable(_seed.seed_demo_data)

    def test_main_is_callable(self) -> None:
        assert callable(_seed.main)

    def test_seed_demo_result_present(self) -> None:
        assert hasattr(_seed, "SeedDemoResult")

    def test_stable_demo_ids_exported(self) -> None:
        # Documentación: los IDs estables son parte del contrato público.
        assert _seed.DEMO_FIRM_ID    == "firm_demo_local"
        assert _seed.DEMO_ADVISOR_ID == "advisor_demo_local"
        assert _seed.DEMO_CLIENT_ID  == "client_demo_local"
        assert _seed.DEMO_CASE_ID    == "case_demo_local"
