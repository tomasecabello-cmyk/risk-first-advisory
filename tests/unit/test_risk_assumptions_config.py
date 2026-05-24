"""
Unit tests for `config_layer/risk_assumptions.py`.

Cubre:
    - Carga del YAML por defecto (los archivos versionados bajo `config/`).
    - Validación estricta de schema: perfiles requeridos, campos requeridos,
      tipos correctos (bool-guard para campos numéricos).
    - Cache de los defaults — get_default_* devuelve copias para evitar
      mutación accidental.
    - Errores claros (ValueError / FileNotFoundError) para inputs inválidos.
    - Valores numéricos coinciden exactamente con los anteriores hardcoded
      (regression contra los valores históricos).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from risk_first_advisory.config_layer.risk_assumptions import (
    DEFAULT_ACHIEVABLE_RETURNS_PATH,
    DEFAULT_RISK_PROFILES_PATH,
    EXPECTED_PROFILES,
    REQUIRED_PROFILE_FIELDS,
    get_default_achievable_returns,
    get_default_risk_profile_params,
    load_achievable_returns,
    load_risk_profile_params,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers para construir YAMLs inválidos rápidamente en tmp_path
# ─────────────────────────────────────────────────────────────────────────────


def _write(tmp: Path, name: str, content: str) -> Path:
    p = tmp / name
    p.write_text(content, encoding="utf-8")
    return p


def _full_profiles_yaml(*, override: str | None = None) -> str:
    """
    YAML válido base. Si se da `override`, reemplaza el bloque interno de
    profiles (debe incluir indentación correcta).
    """
    base = """\
profiles:
  conservador:
    target_volatility: 0.035
    max_volatility: 0.050
    max_drawdown: -0.070
    max_equity: 0.10
    max_high_yield: 0.00
    max_single_asset: 0.15
    max_sector_exposure: 0.20
    max_duration: 2.0
    min_liquidity: 0.0
    preferred_currency: "USD"
    complex_products_allowed: false
  moderado-defensivo:
    target_volatility: 0.055
    max_volatility: 0.075
    max_drawdown: -0.100
    max_equity: 0.25
    max_high_yield: 0.05
    max_single_asset: 0.15
    max_sector_exposure: 0.25
    max_duration: 3.5
    min_liquidity: 0.0
    preferred_currency: "USD"
    complex_products_allowed: false
  moderado:
    target_volatility: 0.075
    max_volatility: 0.100
    max_drawdown: -0.150
    max_equity: 0.40
    max_high_yield: 0.10
    max_single_asset: 0.15
    max_sector_exposure: 0.30
    max_duration: 5.0
    min_liquidity: 0.0
    preferred_currency: "USD"
    complex_products_allowed: false
  moderado-agresivo:
    target_volatility: 0.105
    max_volatility: 0.140
    max_drawdown: -0.220
    max_equity: 0.60
    max_high_yield: 0.15
    max_single_asset: 0.20
    max_sector_exposure: 0.35
    max_duration: 7.0
    min_liquidity: 0.0
    preferred_currency: "USD"
    complex_products_allowed: true
  agresivo:
    target_volatility: 0.140
    max_volatility: 0.200
    max_drawdown: -0.300
    max_equity: 0.80
    max_high_yield: 0.25
    max_single_asset: 0.25
    max_sector_exposure: 0.40
    max_duration: 10.0
    min_liquidity: 0.0
    preferred_currency: "USD"
    complex_products_allowed: true
"""
    return base if override is None else override


def _full_returns_yaml() -> str:
    return """\
achievable_returns:
  conservador: 0.04
  moderado-defensivo: 0.055
  moderado: 0.07
  moderado-agresivo: 0.09
  agresivo: 0.11
"""


# ─────────────────────────────────────────────────────────────────────────────
# load_risk_profile_params — default YAML (regresión vs valores históricos)
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadRiskProfileParamsDefault:
    def test_default_file_loads_without_error(self):
        params = load_risk_profile_params()
        assert isinstance(params, dict)

    def test_contains_exactly_five_profiles(self):
        params = load_risk_profile_params()
        assert set(params.keys()) == EXPECTED_PROFILES
        assert len(params) == 5

    def test_moderado_target_volatility_matches_historical(self):
        params = load_risk_profile_params()
        assert params["moderado"]["target_volatility"] == 0.075

    def test_moderado_max_volatility_matches_historical(self):
        params = load_risk_profile_params()
        assert params["moderado"]["max_volatility"] == 0.100

    def test_moderado_max_drawdown_matches_historical(self):
        params = load_risk_profile_params()
        assert params["moderado"]["max_drawdown"] == -0.150

    def test_moderado_max_equity_matches_historical(self):
        params = load_risk_profile_params()
        assert params["moderado"]["max_equity"] == 0.40

    def test_moderado_max_single_asset_matches_historical(self):
        params = load_risk_profile_params()
        assert params["moderado"]["max_single_asset"] == 0.15

    def test_moderado_complex_products_allowed_is_real_bool_false(self):
        params = load_risk_profile_params()
        v = params["moderado"]["complex_products_allowed"]
        assert v is False
        assert isinstance(v, bool)

    def test_agresivo_complex_products_allowed_is_real_bool_true(self):
        params = load_risk_profile_params()
        v = params["agresivo"]["complex_products_allowed"]
        assert v is True
        assert isinstance(v, bool)

    def test_each_profile_has_all_required_fields(self):
        params = load_risk_profile_params()
        for profile_name in EXPECTED_PROFILES:
            missing = set(REQUIRED_PROFILE_FIELDS) - set(params[profile_name].keys())
            assert not missing, f"{profile_name} missing {missing}"

    def test_full_historical_values_for_all_five_profiles(self):
        """Regression contra los valores anteriores hardcoded."""
        params = load_risk_profile_params()

        expected_subset = {
            "conservador":         {"target_volatility": 0.035, "max_drawdown": -0.070, "max_equity": 0.10},
            "moderado-defensivo":  {"target_volatility": 0.055, "max_drawdown": -0.100, "max_equity": 0.25},
            "moderado":            {"target_volatility": 0.075, "max_drawdown": -0.150, "max_equity": 0.40},
            "moderado-agresivo":   {"target_volatility": 0.105, "max_drawdown": -0.220, "max_equity": 0.60},
            "agresivo":            {"target_volatility": 0.140, "max_drawdown": -0.300, "max_equity": 0.80},
        }
        for profile, expected_fields in expected_subset.items():
            for field, expected_value in expected_fields.items():
                assert params[profile][field] == expected_value, (
                    f"{profile}.{field}: got {params[profile][field]}, "
                    f"expected {expected_value}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# load_risk_profile_params — schema validation
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadRiskProfileParamsValidation:
    def test_missing_file_raises_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError) as exc_info:
            load_risk_profile_params(tmp_path / "no_existe.yaml")
        assert "no encontrado" in str(exc_info.value)

    def test_empty_file_raises_value_error(self, tmp_path: Path):
        path = _write(tmp_path, "empty.yaml", "")
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        assert "vacío" in str(exc_info.value).lower()

    def test_invalid_yaml_raises_value_error(self, tmp_path: Path):
        path = _write(tmp_path, "bad.yaml", "this: is: : invalid: yaml: :\n")
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        assert "YAML inválido" in str(exc_info.value)

    def test_missing_profiles_key_raises(self, tmp_path: Path):
        path = _write(tmp_path, "noroot.yaml", "other_key: 1\n")
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        assert "profiles" in str(exc_info.value)

    def test_root_not_a_mapping_raises(self, tmp_path: Path):
        path = _write(tmp_path, "list.yaml", "- 1\n- 2\n")
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        assert "mapping" in str(exc_info.value)

    def test_profile_required_missing_raises(self, tmp_path: Path):
        # Sólo 4 de los 5 perfiles esperados.
        content = """\
profiles:
  conservador:
    target_volatility: 0.035
    max_volatility: 0.050
    max_drawdown: -0.070
    max_equity: 0.10
    max_high_yield: 0.00
    max_single_asset: 0.15
    max_sector_exposure: 0.20
    max_duration: 2.0
    min_liquidity: 0.0
    preferred_currency: "USD"
    complex_products_allowed: false
"""
        path = _write(tmp_path, "missing_profiles.yaml", content)
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        msg = str(exc_info.value)
        assert "faltan perfiles requeridos" in msg
        assert "moderado" in msg

    def test_unknown_profile_raises(self, tmp_path: Path):
        # Los 5 esperados + uno extra inventado.
        content = _full_profiles_yaml() + """  ultra_agresivo:
    target_volatility: 0.30
    max_volatility: 0.40
    max_drawdown: -0.50
    max_equity: 0.90
    max_high_yield: 0.30
    max_single_asset: 0.30
    max_sector_exposure: 0.50
    max_duration: 15.0
    min_liquidity: 0.0
    preferred_currency: "USD"
    complex_products_allowed: true
"""
        path = _write(tmp_path, "unknown_profile.yaml", content)
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        assert "perfiles desconocidos" in str(exc_info.value)
        assert "ultra_agresivo" in str(exc_info.value)

    def test_required_field_missing_raises(self, tmp_path: Path):
        # `moderado` sin `max_drawdown`.
        broken = _full_profiles_yaml().replace(
            "    max_drawdown: -0.150\n", "", 1
        )
        path = _write(tmp_path, "missing_field.yaml", broken)
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        msg = str(exc_info.value)
        assert "campos faltantes" in msg
        assert "max_drawdown" in msg

    def test_numeric_field_as_bool_raises(self, tmp_path: Path):
        # `moderado.target_volatility: true` — bool donde se espera número.
        broken = _full_profiles_yaml().replace(
            "    target_volatility: 0.075\n", "    target_volatility: true\n", 1
        )
        path = _write(tmp_path, "bool_numeric.yaml", broken)
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        msg = str(exc_info.value)
        assert "target_volatility" in msg
        assert "bool" in msg

    def test_numeric_field_as_string_raises(self, tmp_path: Path):
        broken = _full_profiles_yaml().replace(
            "    max_volatility: 0.100\n", '    max_volatility: "high"\n', 1
        )
        path = _write(tmp_path, "string_numeric.yaml", broken)
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        msg = str(exc_info.value)
        assert "max_volatility" in msg
        assert "número" in msg

    def test_preferred_currency_empty_raises(self, tmp_path: Path):
        broken = _full_profiles_yaml().replace(
            '    preferred_currency: "USD"\n', '    preferred_currency: ""\n'
        )
        path = _write(tmp_path, "empty_currency.yaml", broken)
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        assert "preferred_currency" in str(exc_info.value)

    def test_preferred_currency_whitespace_only_raises(self, tmp_path: Path):
        broken = _full_profiles_yaml().replace(
            '    preferred_currency: "USD"\n', '    preferred_currency: "   "\n'
        )
        path = _write(tmp_path, "ws_currency.yaml", broken)
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        assert "preferred_currency" in str(exc_info.value)

    def test_preferred_currency_not_a_string_raises(self, tmp_path: Path):
        broken = _full_profiles_yaml().replace(
            '    preferred_currency: "USD"\n', "    preferred_currency: 42\n"
        )
        path = _write(tmp_path, "non_str_currency.yaml", broken)
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        assert "string" in str(exc_info.value)

    def test_complex_products_allowed_as_int_raises(self, tmp_path: Path):
        broken = _full_profiles_yaml().replace(
            "    complex_products_allowed: false\n",
            "    complex_products_allowed: 0\n",
            1,
        )
        path = _write(tmp_path, "int_complex.yaml", broken)
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        assert "complex_products_allowed" in str(exc_info.value)
        assert "bool" in str(exc_info.value)

    def test_complex_products_allowed_as_string_raises(self, tmp_path: Path):
        broken = _full_profiles_yaml().replace(
            "    complex_products_allowed: false\n",
            '    complex_products_allowed: "no"\n',
            1,
        )
        path = _write(tmp_path, "str_complex.yaml", broken)
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        assert "complex_products_allowed" in str(exc_info.value)

    def test_profile_not_a_mapping_raises(self, tmp_path: Path):
        content = """\
profiles:
  conservador: "not a mapping"
"""
        path = _write(tmp_path, "wrong_shape.yaml", content)
        with pytest.raises(ValueError) as exc_info:
            load_risk_profile_params(path)
        assert "mapping" in str(exc_info.value)

    def test_valid_yaml_with_extra_keys_in_profile_is_ignored(self, tmp_path: Path):
        """Campos extra dentro de un perfil no rompen; sólo se copian los requeridos."""
        with_extra = _full_profiles_yaml() + ""
        with_extra = with_extra.replace(
            "    complex_products_allowed: false\n  moderado-defensivo:",
            (
                "    complex_products_allowed: false\n"
                "    some_future_field: 999\n"
                "  moderado-defensivo:"
            ),
            1,
        )
        path = _write(tmp_path, "extra_keys.yaml", with_extra)
        params = load_risk_profile_params(path)
        # El campo extra no debe aparecer en el dict resultante.
        assert "some_future_field" not in params["conservador"]
        # Pero el resto sigue intacto.
        assert params["conservador"]["target_volatility"] == 0.035


# ─────────────────────────────────────────────────────────────────────────────
# load_achievable_returns — default YAML
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadAchievableReturnsDefault:
    def test_default_file_loads_without_error(self):
        returns = load_achievable_returns()
        assert isinstance(returns, dict)

    def test_contains_exactly_five_profiles(self):
        returns = load_achievable_returns()
        assert set(returns.keys()) == EXPECTED_PROFILES

    def test_moderado_matches_historical(self):
        returns = load_achievable_returns()
        assert returns["moderado"] == pytest.approx(0.07)

    def test_all_historical_values(self):
        returns = load_achievable_returns()
        expected = {
            "conservador": 0.04,
            "moderado-defensivo": 0.055,
            "moderado": 0.07,
            "moderado-agresivo": 0.09,
            "agresivo": 0.11,
        }
        for profile, expected_value in expected.items():
            assert returns[profile] == pytest.approx(expected_value)

    def test_values_are_floats_not_bool(self):
        returns = load_achievable_returns()
        for profile, value in returns.items():
            assert isinstance(value, float)
            assert not isinstance(value, bool)


# ─────────────────────────────────────────────────────────────────────────────
# load_achievable_returns — schema validation
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadAchievableReturnsValidation:
    def test_missing_file_raises_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_achievable_returns(tmp_path / "no_existe.yaml")

    def test_missing_returns_key_raises(self, tmp_path: Path):
        path = _write(tmp_path, "noroot.yaml", "other: 1\n")
        with pytest.raises(ValueError) as exc_info:
            load_achievable_returns(path)
        assert "achievable_returns" in str(exc_info.value)

    def test_missing_profile_raises(self, tmp_path: Path):
        content = """\
achievable_returns:
  conservador: 0.04
  moderado: 0.07
"""
        path = _write(tmp_path, "incomplete.yaml", content)
        with pytest.raises(ValueError) as exc_info:
            load_achievable_returns(path)
        assert "faltan perfiles requeridos" in str(exc_info.value)

    def test_unknown_profile_raises(self, tmp_path: Path):
        content = _full_returns_yaml() + "  ultra_agresivo: 0.30\n"
        path = _write(tmp_path, "unknown.yaml", content)
        with pytest.raises(ValueError) as exc_info:
            load_achievable_returns(path)
        assert "perfiles desconocidos" in str(exc_info.value)

    def test_return_as_bool_raises(self, tmp_path: Path):
        broken = _full_returns_yaml().replace(
            "  moderado: 0.07\n", "  moderado: true\n"
        )
        path = _write(tmp_path, "bool_return.yaml", broken)
        with pytest.raises(ValueError) as exc_info:
            load_achievable_returns(path)
        assert "bool" in str(exc_info.value)
        assert "moderado" in str(exc_info.value)

    def test_return_as_string_raises(self, tmp_path: Path):
        broken = _full_returns_yaml().replace(
            "  agresivo: 0.11\n", '  agresivo: "high"\n'
        )
        path = _write(tmp_path, "str_return.yaml", broken)
        with pytest.raises(ValueError) as exc_info:
            load_achievable_returns(path)
        assert "número" in str(exc_info.value) or "string" in str(exc_info.value)

    def test_returns_not_a_mapping_raises(self, tmp_path: Path):
        content = """\
achievable_returns:
  - 0.04
  - 0.05
"""
        path = _write(tmp_path, "list_returns.yaml", content)
        with pytest.raises(ValueError) as exc_info:
            load_achievable_returns(path)
        assert "mapping" in str(exc_info.value)

    def test_integer_return_accepted_and_coerced_to_float(self, tmp_path: Path):
        # YAML 1 → int. El loader debe aceptarlo y convertirlo a float.
        broken = _full_returns_yaml().replace(
            "  conservador: 0.04\n", "  conservador: 1\n"
        )
        path = _write(tmp_path, "int_return.yaml", broken)
        returns = load_achievable_returns(path)
        assert returns["conservador"] == 1.0
        assert isinstance(returns["conservador"], float)


# ─────────────────────────────────────────────────────────────────────────────
# get_default_* — caching y aislamiento (no permite mutación accidental)
# ─────────────────────────────────────────────────────────────────────────────


class TestDefaultsCache:
    def test_get_default_risk_profile_params_returns_dict_with_all_profiles(self):
        params = get_default_risk_profile_params()
        assert set(params.keys()) == EXPECTED_PROFILES

    def test_get_default_achievable_returns_returns_dict_with_all_profiles(self):
        returns = get_default_achievable_returns()
        assert set(returns.keys()) == EXPECTED_PROFILES

    def test_mutating_risk_profile_result_does_not_affect_next_call(self):
        """Defensa contra mutación accidental del cache."""
        params1 = get_default_risk_profile_params()
        params1["moderado"]["target_volatility"] = 999.0
        params2 = get_default_risk_profile_params()
        assert params2["moderado"]["target_volatility"] == 0.075

    def test_mutating_achievable_returns_result_does_not_affect_next_call(self):
        ret1 = get_default_achievable_returns()
        ret1["moderado"] = 999.0
        ret2 = get_default_achievable_returns()
        assert ret2["moderado"] == pytest.approx(0.07)

    def test_default_paths_point_to_config_dir(self):
        # Verifica que las rutas por defecto apunten al `config/` versionado.
        assert DEFAULT_RISK_PROFILES_PATH.name == "risk_profiles.yaml"
        assert DEFAULT_RISK_PROFILES_PATH.parent.name == "config"
        assert DEFAULT_RISK_PROFILES_PATH.exists()
        assert DEFAULT_ACHIEVABLE_RETURNS_PATH.name == "achievable_returns.yaml"
        assert DEFAULT_ACHIEVABLE_RETURNS_PATH.parent.name == "config"
        assert DEFAULT_ACHIEVABLE_RETURNS_PATH.exists()


# ─────────────────────────────────────────────────────────────────────────────
# Regression: consistency entre loader y las constantes históricas
# ─────────────────────────────────────────────────────────────────────────────


class TestConsistencyWithHistoricalConstants:
    """
    Garantiza que las constantes públicas exportadas por `rules_layer`
    siguen siendo idénticas a las que existían pre-Fase 1 cuando estaban
    hardcoded. Si alguien edita el YAML por error, este test salta.
    """

    def test_PROFILE_BASE_PARAMS_re_exports_loader_values(self):
        from risk_first_advisory.rules_layer.risk_budget_builder import (
            PROFILE_BASE_PARAMS,
        )
        loader_params = load_risk_profile_params()
        # Comparar campos clave en moderado:
        for field in (
            "target_volatility",
            "max_volatility",
            "max_drawdown",
            "max_equity",
            "max_high_yield",
            "max_single_asset",
            "max_sector_exposure",
            "max_duration",
            "complex_products_allowed",
        ):
            assert (
                PROFILE_BASE_PARAMS["moderado"][field]
                == loader_params["moderado"][field]
            ), f"PROFILE_BASE_PARAMS.moderado.{field} mismatch"

    def test_DEFAULT_ACHIEVABLE_RETURNS_re_exports_loader_values(self):
        from risk_first_advisory.rules_layer.goal_feasibility import (
            DEFAULT_ACHIEVABLE_RETURNS,
        )
        loader_returns = load_achievable_returns()
        for profile in EXPECTED_PROFILES:
            assert (
                DEFAULT_ACHIEVABLE_RETURNS[profile]
                == loader_returns[profile]
            )
