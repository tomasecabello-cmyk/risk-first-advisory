"""
Tests para `config_layer/advisor_tokens.py` — loader + fallback de Fase 2.

Cubre:
    - load_advisor_tokens con path válido devuelve ambos tokens.
    - load_advisor_tokens con path inexistente → FileNotFoundError.
    - load_advisor_tokens sin path → usa DEFAULT_ADVISOR_TOKENS_PATH (FNF si
      el archivo default no existe).
    - get_default_advisor_tokens sin env ni archivo → fallback dev-only.
    - get_default_advisor_tokens con env var → carga ese archivo y reemplaza
      el fallback (los dev-* desaparecen).
    - get_default_advisor_tokens con env vacío/whitespace → fallback dev-only.
    - get_default_advisor_tokens sin env pero con archivo default → archivo.
    - El .example commiteado parsea válido.
    - Schema rejection: top-level missing tokens, tokens no dict, tokens vacío.
    - Schema rejection por campo: missing, unknown, empty, wrong type, bool.
    - Roles: vacío, no list, role inválido, role bool, role vacío.
    - firm_id: null OK, str vacío NO OK.
    - Defensa contra mutación: el fallback no se contamina entre llamadas.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from risk_first_advisory.config_layer.advisor_tokens import (
    ADVISOR_TOKENS_ENV_VAR,
    ALLOWED_ROLES,
    DEMO_MODE_ENV_VAR,
    DEV_TOKENS_FLAG_ENV_VAR,
    REQUIRED_TOKEN_FIELDS,
    AdvisorTokensNotConfiguredError,
    get_default_advisor_tokens,
    load_advisor_tokens,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_EXAMPLE_YAML: Path = _PROJECT_ROOT / "config" / "advisor_tokens.yaml.example"


@pytest.fixture(autouse=True)
def _isolate_advisor_tokens_env(monkeypatch, tmp_path):
    """
    Garantiza que ningún env var o archivo default contamine los tests.
    Cada test arranca con:
        - ADVISOR_TOKENS_FILE: unset
        - DEFAULT_ADVISOR_TOKENS_PATH: apunta a una ruta inexistente bajo tmp_path
    Tests que necesiten configurar env var / archivo lo hacen ellos mismos.
    """
    monkeypatch.delenv(ADVISOR_TOKENS_ENV_VAR, raising=False)
    import risk_first_advisory.config_layer.advisor_tokens as _mod
    monkeypatch.setattr(
        _mod, "DEFAULT_ADVISOR_TOKENS_PATH", tmp_path / "absent.yaml"
    )


def _write_valid_yaml(path: Path) -> None:
    path.write_text(
        """\
tokens:
  dev-advisor-token:
    advisor_id: ADV-001
    display_name: Demo Advisor
    firm_id: null
    roles:
      - advisor
  dev-compliance-token:
    advisor_id: CMP-001
    display_name: Demo Compliance
    firm_id: null
    roles:
      - compliance
""",
        encoding="utf-8",
    )


# ═════════════════════════════════════════════════════════════════════════════
# load_advisor_tokens — explicit path
# ═════════════════════════════════════════════════════════════════════════════


class TestLoadExplicit:
    def test_loads_both_default_tokens(self, tmp_path: Path):
        yaml_path = tmp_path / "tokens.yaml"
        _write_valid_yaml(yaml_path)

        tokens = load_advisor_tokens(yaml_path)

        assert "dev-advisor-token" in tokens
        assert "dev-compliance-token" in tokens
        assert len(tokens) == 2

    def test_advisor_token_entry_shape(self, tmp_path: Path):
        yaml_path = tmp_path / "tokens.yaml"
        _write_valid_yaml(yaml_path)

        entry = load_advisor_tokens(yaml_path)["dev-advisor-token"]

        assert entry["advisor_id"] == "ADV-001"
        assert entry["display_name"] == "Demo Advisor"
        assert entry["firm_id"] is None
        assert entry["roles"] == ["advisor"]
        assert set(entry.keys()) == REQUIRED_TOKEN_FIELDS

    def test_compliance_token_has_compliance_role(self, tmp_path: Path):
        yaml_path = tmp_path / "tokens.yaml"
        _write_valid_yaml(yaml_path)

        entry = load_advisor_tokens(yaml_path)["dev-compliance-token"]

        assert entry["advisor_id"] == "CMP-001"
        assert "compliance" in entry["roles"]

    def test_accepts_string_path(self, tmp_path: Path):
        yaml_path = tmp_path / "tokens.yaml"
        _write_valid_yaml(yaml_path)

        tokens = load_advisor_tokens(str(yaml_path))

        assert "dev-advisor-token" in tokens

    def test_nonexistent_path_raises_file_not_found(self, tmp_path: Path):
        ghost = tmp_path / "does_not_exist.yaml"
        with pytest.raises(FileNotFoundError):
            load_advisor_tokens(ghost)

    def test_none_path_uses_default(self, tmp_path: Path, monkeypatch):
        """
        path=None debe caer en DEFAULT_ADVISOR_TOKENS_PATH (que el fixture
        autouse apuntó a un archivo que no existe).
        """
        with pytest.raises(FileNotFoundError):
            load_advisor_tokens(None)


# ═════════════════════════════════════════════════════════════════════════════
# load_advisor_tokens — schema rejection (top level)
# ═════════════════════════════════════════════════════════════════════════════


class TestSchemaRejectionTopLevel:
    def test_missing_tokens_key_raises(self, tmp_path: Path):
        p = tmp_path / "no_tokens.yaml"
        p.write_text("other_key:\n  foo: bar\n", encoding="utf-8")
        with pytest.raises(ValueError, match="'tokens'"):
            load_advisor_tokens(p)

    def test_tokens_not_a_dict_raises(self, tmp_path: Path):
        p = tmp_path / "bad_tokens.yaml"
        p.write_text("tokens:\n  - just\n  - a\n  - list\n", encoding="utf-8")
        with pytest.raises(ValueError, match="mapping"):
            load_advisor_tokens(p)

    def test_empty_tokens_dict_raises(self, tmp_path: Path):
        p = tmp_path / "empty.yaml"
        p.write_text("tokens: {}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="vacío"):
            load_advisor_tokens(p)

    def test_root_not_a_mapping_raises(self, tmp_path: Path):
        p = tmp_path / "list_root.yaml"
        p.write_text("- foo\n- bar\n", encoding="utf-8")
        with pytest.raises(ValueError, match="mapping"):
            load_advisor_tokens(p)

    def test_empty_file_raises(self, tmp_path: Path):
        p = tmp_path / "empty_file.yaml"
        p.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="vacío"):
            load_advisor_tokens(p)

    def test_invalid_yaml_raises_value_error(self, tmp_path: Path):
        p = tmp_path / "broken.yaml"
        p.write_text("tokens:\n  - unbalanced: [\n", encoding="utf-8")
        with pytest.raises(ValueError, match="YAML inválido"):
            load_advisor_tokens(p)


# ═════════════════════════════════════════════════════════════════════════════
# load_advisor_tokens — schema rejection (per-entry)
# ═════════════════════════════════════════════════════════════════════════════


class TestSchemaRejectionEntry:
    def _write(self, tmp_path: Path, body: str) -> Path:
        p = tmp_path / "tokens.yaml"
        p.write_text(f"tokens:\n{body}", encoding="utf-8")
        return p

    def test_entry_missing_required_field(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-001\n"
            "    display_name: D\n"
            "    roles: [advisor]\n",  # falta firm_id
        )
        with pytest.raises(ValueError, match="faltan campos requeridos"):
            load_advisor_tokens(p)

    def test_entry_unknown_field_rejected(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-001\n"
            "    display_name: D\n"
            "    firm_id: null\n"
            "    roles: [advisor]\n"
            "    extra_field: nope\n",  # extra → reject
        )
        with pytest.raises(ValueError, match="desconocidos"):
            load_advisor_tokens(p)

    def test_entry_not_a_mapping(self, tmp_path: Path):
        p = self._write(tmp_path, "  abc: just_a_string\n")
        with pytest.raises(ValueError, match="mapping"):
            load_advisor_tokens(p)

    def test_advisor_id_empty_string(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: \"\"\n"
            "    display_name: D\n"
            "    firm_id: null\n"
            "    roles: [advisor]\n",
        )
        with pytest.raises(ValueError, match="advisor_id"):
            load_advisor_tokens(p)

    def test_advisor_id_whitespace_only(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: \"   \"\n"
            "    display_name: D\n"
            "    firm_id: null\n"
            "    roles: [advisor]\n",
        )
        with pytest.raises(ValueError, match="advisor_id"):
            load_advisor_tokens(p)

    def test_advisor_id_as_bool_rejected(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: true\n"
            "    display_name: D\n"
            "    firm_id: null\n"
            "    roles: [advisor]\n",
        )
        with pytest.raises(ValueError, match="bool"):
            load_advisor_tokens(p)

    def test_display_name_empty(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-1\n"
            "    display_name: \"\"\n"
            "    firm_id: null\n"
            "    roles: [advisor]\n",
        )
        with pytest.raises(ValueError, match="display_name"):
            load_advisor_tokens(p)

    def test_display_name_as_bool_rejected(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-1\n"
            "    display_name: false\n"
            "    firm_id: null\n"
            "    roles: [advisor]\n",
        )
        with pytest.raises(ValueError, match="bool"):
            load_advisor_tokens(p)

    def test_firm_id_empty_string_rejected(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-1\n"
            "    display_name: D\n"
            "    firm_id: \"\"\n"
            "    roles: [advisor]\n",
        )
        with pytest.raises(ValueError, match="firm_id"):
            load_advisor_tokens(p)

    def test_firm_id_null_is_accepted(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-1\n"
            "    display_name: D\n"
            "    firm_id: null\n"
            "    roles: [advisor]\n",
        )
        result = load_advisor_tokens(p)
        assert result["abc"]["firm_id"] is None

    def test_firm_id_non_empty_str_is_accepted(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-1\n"
            "    display_name: D\n"
            "    firm_id: firm_ALPHA\n"
            "    roles: [advisor]\n",
        )
        result = load_advisor_tokens(p)
        assert result["abc"]["firm_id"] == "firm_ALPHA"

    def test_roles_empty_list_rejected(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-1\n"
            "    display_name: D\n"
            "    firm_id: null\n"
            "    roles: []\n",
        )
        with pytest.raises(ValueError, match="vacía"):
            load_advisor_tokens(p)

    def test_roles_not_a_list(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-1\n"
            "    display_name: D\n"
            "    firm_id: null\n"
            "    roles: advisor\n",  # str en vez de list
        )
        with pytest.raises(ValueError, match="lista"):
            load_advisor_tokens(p)

    def test_invalid_role_rejected(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-1\n"
            "    display_name: D\n"
            "    firm_id: null\n"
            "    roles: [superadmin]\n",
        )
        with pytest.raises(ValueError, match="inválido"):
            load_advisor_tokens(p)

    def test_role_as_bool_rejected(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-1\n"
            "    display_name: D\n"
            "    firm_id: null\n"
            "    roles: [true]\n",
        )
        with pytest.raises(ValueError, match="bool"):
            load_advisor_tokens(p)

    def test_empty_role_string_rejected(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            "  abc:\n"
            "    advisor_id: ADV-1\n"
            "    display_name: D\n"
            "    firm_id: null\n"
            "    roles: [\"\"]\n",
        )
        with pytest.raises(ValueError, match="vacío"):
            load_advisor_tokens(p)

    def test_all_allowed_roles_accepted(self, tmp_path: Path):
        roles_yaml = "\n".join(f"      - {r}" for r in sorted(ALLOWED_ROLES))
        p = self._write(
            tmp_path,
            "  multi:\n"
            "    advisor_id: ADV-MULTI\n"
            "    display_name: Multi\n"
            "    firm_id: null\n"
            "    roles:\n" + roles_yaml + "\n",
        )
        result = load_advisor_tokens(p)
        assert set(result["multi"]["roles"]) == ALLOWED_ROLES


# ═════════════════════════════════════════════════════════════════════════════
# get_default_advisor_tokens — resolución de fallback
# ═════════════════════════════════════════════════════════════════════════════


class TestGetDefaultResolution:
    def test_no_env_no_file_returns_dev_fallback(self):
        tokens = get_default_advisor_tokens()
        assert "dev-advisor-token" in tokens
        assert "dev-compliance-token" in tokens
        assert tokens["dev-advisor-token"]["advisor_id"] == "ADV-001"
        assert tokens["dev-compliance-token"]["advisor_id"] == "CMP-001"

    def test_fallback_advisor_token_shape(self):
        tokens = get_default_advisor_tokens()
        entry = tokens["dev-advisor-token"]
        assert entry["display_name"] == "Demo Advisor"
        assert entry["firm_id"] is None
        assert entry["roles"] == ["advisor"]

    def test_fallback_compliance_token_shape(self):
        tokens = get_default_advisor_tokens()
        entry = tokens["dev-compliance-token"]
        assert entry["display_name"] == "Demo Compliance"
        assert entry["firm_id"] is None
        assert entry["roles"] == ["compliance"]

    def test_env_var_overrides_fallback(self, tmp_path: Path, monkeypatch):
        custom = tmp_path / "custom.yaml"
        custom.write_text(
            """\
tokens:
  custom-token-abc:
    advisor_id: CUSTOM-007
    display_name: Custom Advisor
    firm_id: firm_XYZ
    roles:
      - advisor
""",
            encoding="utf-8",
        )
        monkeypatch.setenv(ADVISOR_TOKENS_ENV_VAR, str(custom))

        tokens = get_default_advisor_tokens()

        assert "custom-token-abc" in tokens
        # Fallback dev tokens NO deben aparecer cuando hay env file
        assert "dev-advisor-token" not in tokens
        assert "dev-compliance-token" not in tokens
        assert tokens["custom-token-abc"]["advisor_id"] == "CUSTOM-007"
        assert tokens["custom-token-abc"]["firm_id"] == "firm_XYZ"

    def test_empty_env_var_uses_fallback(self, monkeypatch):
        monkeypatch.setenv(ADVISOR_TOKENS_ENV_VAR, "")
        tokens = get_default_advisor_tokens()
        assert "dev-advisor-token" in tokens

    def test_whitespace_env_var_uses_fallback(self, monkeypatch):
        monkeypatch.setenv(ADVISOR_TOKENS_ENV_VAR, "   ")
        tokens = get_default_advisor_tokens()
        assert "dev-advisor-token" in tokens

    def test_default_file_used_when_no_env(self, tmp_path: Path, monkeypatch):
        """Sin env, pero DEFAULT_ADVISOR_TOKENS_PATH existe → carga el archivo."""
        custom = tmp_path / "default_target.yaml"
        custom.write_text(
            """\
tokens:
  file-only-token:
    advisor_id: FILE-001
    display_name: From File
    firm_id: null
    roles:
      - advisor
""",
            encoding="utf-8",
        )
        import risk_first_advisory.config_layer.advisor_tokens as _mod
        monkeypatch.setattr(_mod, "DEFAULT_ADVISOR_TOKENS_PATH", custom)

        tokens = get_default_advisor_tokens()

        assert "file-only-token" in tokens
        assert "dev-advisor-token" not in tokens

    def test_env_var_takes_precedence_over_default_file(
        self, tmp_path: Path, monkeypatch
    ):
        """Si AMBOS existen (env + default file), env gana."""
        default_file = tmp_path / "default.yaml"
        default_file.write_text(
            """\
tokens:
  from-default:
    advisor_id: DEF-001
    display_name: From Default File
    firm_id: null
    roles: [advisor]
""",
            encoding="utf-8",
        )
        env_file = tmp_path / "env.yaml"
        env_file.write_text(
            """\
tokens:
  from-env:
    advisor_id: ENV-001
    display_name: From Env File
    firm_id: null
    roles: [advisor]
""",
            encoding="utf-8",
        )
        import risk_first_advisory.config_layer.advisor_tokens as _mod
        monkeypatch.setattr(_mod, "DEFAULT_ADVISOR_TOKENS_PATH", default_file)
        monkeypatch.setenv(ADVISOR_TOKENS_ENV_VAR, str(env_file))

        tokens = get_default_advisor_tokens()

        assert "from-env" in tokens
        assert "from-default" not in tokens

    def test_env_var_pointing_to_missing_file_raises(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv(ADVISOR_TOKENS_ENV_VAR, str(tmp_path / "ghost.yaml"))
        with pytest.raises(FileNotFoundError):
            get_default_advisor_tokens()

    def test_env_var_pointing_to_invalid_file_raises(self, tmp_path: Path, monkeypatch):
        bad = tmp_path / "bad.yaml"
        bad.write_text("tokens: 'not a dict'\n", encoding="utf-8")
        monkeypatch.setenv(ADVISOR_TOKENS_ENV_VAR, str(bad))
        with pytest.raises(ValueError):
            get_default_advisor_tokens()


# ═════════════════════════════════════════════════════════════════════════════
# Kill-switch del fallback dev-only (auditoría de seguridad 2026-07-17)
# ═════════════════════════════════════════════════════════════════════════════


class TestDevFallbackKillSwitch:
    """
    Sin fuente de tokens (env var + default file ausentes, garantizado por el
    fixture autouse) el fallback dev-only SOLO se habilita con
    RFA_ALLOW_DEV_TOKENS o RFA_DEMO_MODE no vacías. La suite corre con
    RFA_ALLOW_DEV_TOKENS=1 (tests/conftest.py); estos tests la borran para
    verificar el comportamiento fail-closed.
    """

    def test_without_flags_raises_not_configured(self, monkeypatch):
        monkeypatch.delenv(DEV_TOKENS_FLAG_ENV_VAR, raising=False)
        monkeypatch.delenv(DEMO_MODE_ENV_VAR, raising=False)
        with pytest.raises(AdvisorTokensNotConfiguredError):
            get_default_advisor_tokens()

    def test_error_message_is_actionable_without_leaking_tokens(self, monkeypatch):
        monkeypatch.delenv(DEV_TOKENS_FLAG_ENV_VAR, raising=False)
        monkeypatch.delenv(DEMO_MODE_ENV_VAR, raising=False)
        with pytest.raises(AdvisorTokensNotConfiguredError) as exc_info:
            get_default_advisor_tokens()
        msg = str(exc_info.value)
        assert DEV_TOKENS_FLAG_ENV_VAR in msg
        assert DEMO_MODE_ENV_VAR in msg
        assert "dev-advisor-token" not in msg
        assert "dev-compliance-token" not in msg

    def test_empty_flags_count_as_disabled(self, monkeypatch):
        monkeypatch.setenv(DEV_TOKENS_FLAG_ENV_VAR, "")
        monkeypatch.setenv(DEMO_MODE_ENV_VAR, "   ")
        with pytest.raises(AdvisorTokensNotConfiguredError):
            get_default_advisor_tokens()

    def test_allow_dev_tokens_flag_enables_fallback(self, monkeypatch):
        monkeypatch.delenv(DEMO_MODE_ENV_VAR, raising=False)
        monkeypatch.setenv(DEV_TOKENS_FLAG_ENV_VAR, "1")
        tokens = get_default_advisor_tokens()
        assert "dev-advisor-token" in tokens

    def test_demo_mode_flag_enables_fallback(self, monkeypatch):
        monkeypatch.delenv(DEV_TOKENS_FLAG_ENV_VAR, raising=False)
        monkeypatch.setenv(DEMO_MODE_ENV_VAR, "1")
        tokens = get_default_advisor_tokens()
        assert "dev-compliance-token" in tokens

    def test_explicit_file_ignores_kill_switch(self, tmp_path: Path, monkeypatch):
        """Con archivo configurado, el kill-switch es irrelevante."""
        monkeypatch.delenv(DEV_TOKENS_FLAG_ENV_VAR, raising=False)
        monkeypatch.delenv(DEMO_MODE_ENV_VAR, raising=False)
        custom = tmp_path / "custom.yaml"
        custom.write_text(
            """\
tokens:
  real-token:
    advisor_id: REAL-001
    display_name: Real Advisor
    firm_id: null
    roles: [advisor]
""",
            encoding="utf-8",
        )
        monkeypatch.setenv(ADVISOR_TOKENS_ENV_VAR, str(custom))
        tokens = get_default_advisor_tokens()
        assert "real-token" in tokens
        assert "dev-advisor-token" not in tokens

    def test_auth_returns_500_when_not_configured(self, monkeypatch):
        """
        Vía API: token presentado sin fuente de tokens configurada → 500
        fail-loud (config ausente es error operativo, no un 401 silencioso).
        """
        monkeypatch.delenv(DEV_TOKENS_FLAG_ENV_VAR, raising=False)
        monkeypatch.delenv(DEMO_MODE_ENV_VAR, raising=False)
        from fastapi.testclient import TestClient

        import risk_first_advisory.api_layer.main as main_mod

        client = TestClient(main_mod.app, raise_server_exceptions=False)
        resp = client.get(
            "/auth/me", headers={"Authorization": "Bearer dev-advisor-token"}
        )
        assert resp.status_code == 500


# ═════════════════════════════════════════════════════════════════════════════
# Fallback isolation — defensa contra mutación
# ═════════════════════════════════════════════════════════════════════════════


class TestFallbackIsolation:
    def test_mutating_returned_dict_does_not_affect_next_call(self):
        first = get_default_advisor_tokens()
        first["dev-advisor-token"]["advisor_id"] = "MUTATED"
        first["dev-advisor-token"]["roles"].append("admin")
        first["injected-token"] = {"advisor_id": "X", "display_name": "X",
                                   "firm_id": None, "roles": ["admin"]}

        second = get_default_advisor_tokens()

        assert second["dev-advisor-token"]["advisor_id"] == "ADV-001"
        assert second["dev-advisor-token"]["roles"] == ["advisor"]
        assert "injected-token" not in second


# ═════════════════════════════════════════════════════════════════════════════
# El .example committeado debe parsear
# ═════════════════════════════════════════════════════════════════════════════


class TestExampleFileParses:
    def test_example_file_is_present(self):
        assert _EXAMPLE_YAML.exists(), (
            f"El template {_EXAMPLE_YAML} debe existir para que devs lo copien."
        )

    def test_example_file_loads_with_both_dev_tokens(self):
        tokens = load_advisor_tokens(_EXAMPLE_YAML)
        assert "dev-advisor-token" in tokens
        assert "dev-compliance-token" in tokens

    def test_example_file_matches_fallback_for_dev_tokens(self):
        """
        El .example debe documentar exactamente los tokens del fallback dev-only
        para que copiar el .example a .yaml NO cambie comportamiento.
        """
        from_file = load_advisor_tokens(_EXAMPLE_YAML)
        # Llamada con env limpio y default path inexistente → fallback dev-only
        fallback = get_default_advisor_tokens()

        assert set(from_file.keys()) == set(fallback.keys())
        for token in from_file:
            assert from_file[token] == fallback[token]
