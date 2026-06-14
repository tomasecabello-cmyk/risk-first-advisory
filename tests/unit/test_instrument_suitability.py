"""
Tests de InstrumentSuitabilityMatrix y InstrumentSuitabilityRule.

Cubre:
    - Validaciones del dataclass.
    - Carga desde YAML (válida e inválida).
    - Consultas: get_rule, evaluate, is_allowed, is_limited, is_not_allowed.
    - Política conservadora ante reglas faltantes.
    - exclusion_report.
"""

from pathlib import Path

import pytest

from risk_first_advisory.rules_layer.instrument_suitability import (
    RULE_MISSING_REASON_CODE,
    InstrumentSuitabilityMatrix,
    InstrumentSuitabilityRule,
    InstrumentSuitabilityStatus,
)

FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "suitability"
    / "instrument_matrix.yaml"
)


@pytest.fixture
def matrix() -> InstrumentSuitabilityMatrix:
    return InstrumentSuitabilityMatrix.from_yaml(FIXTURE_PATH)


# ── 1. Validación del dataclass ───────────────────────────────────────────


class TestRuleValidacion:
    def test_rule_valida_se_construye(self):
        r = InstrumentSuitabilityRule(
            instrument_type="money_market",
            profile_name="conservador",
            status=InstrumentSuitabilityStatus.ALLOWED,
            max_allocation=1.0,
        )
        assert r.instrument_type == "money_market"
        assert r.status == InstrumentSuitabilityStatus.ALLOWED

    def test_instrument_type_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="instrument_type"):
            InstrumentSuitabilityRule(
                instrument_type="",
                profile_name="conservador",
                status=InstrumentSuitabilityStatus.ALLOWED,
            )

    def test_profile_name_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="profile_name"):
            InstrumentSuitabilityRule(
                instrument_type="money_market",
                profile_name="",
                status=InstrumentSuitabilityStatus.ALLOWED,
            )

    def test_status_no_enum_lanza_error(self):
        with pytest.raises(ValueError, match="status"):
            InstrumentSuitabilityRule(
                instrument_type="money_market",
                profile_name="conservador",
                status="allowed",  # type: ignore[arg-type]
            )

    def test_notes_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="notes"):
            InstrumentSuitabilityRule(
                instrument_type="money_market",
                profile_name="conservador",
                status=InstrumentSuitabilityStatus.ALLOWED,
                notes="una nota",  # type: ignore[arg-type]
            )

    def test_max_allocation_fuera_de_rango_lanza_error(self):
        with pytest.raises(ValueError, match="max_allocation"):
            InstrumentSuitabilityRule(
                instrument_type="money_market",
                profile_name="conservador",
                status=InstrumentSuitabilityStatus.LIMITED,
                max_allocation=1.5,
            )

    def test_max_allocation_negativa_lanza_error(self):
        with pytest.raises(ValueError, match="max_allocation"):
            InstrumentSuitabilityRule(
                instrument_type="money_market",
                profile_name="conservador",
                status=InstrumentSuitabilityStatus.LIMITED,
                max_allocation=-0.10,
            )

    def test_limited_sin_max_allocation_lanza_error(self):
        with pytest.raises(ValueError, match="LIMITED"):
            InstrumentSuitabilityRule(
                instrument_type="thematic_equity",
                profile_name="moderado",
                status=InstrumentSuitabilityStatus.LIMITED,
                max_allocation=None,
            )

    def test_limited_con_max_allocation_cero_lanza_error(self):
        with pytest.raises(ValueError, match="LIMITED"):
            InstrumentSuitabilityRule(
                instrument_type="thematic_equity",
                profile_name="moderado",
                status=InstrumentSuitabilityStatus.LIMITED,
                max_allocation=0.0,
            )

    def test_limited_con_max_allocation_uno_lanza_error(self):
        with pytest.raises(ValueError, match="LIMITED"):
            InstrumentSuitabilityRule(
                instrument_type="thematic_equity",
                profile_name="moderado",
                status=InstrumentSuitabilityStatus.LIMITED,
                max_allocation=1.0,
            )

    def test_not_allowed_con_max_allocation_positivo_lanza_error(self):
        with pytest.raises(ValueError, match="NOT_ALLOWED"):
            InstrumentSuitabilityRule(
                instrument_type="crypto_trust",
                profile_name="conservador",
                status=InstrumentSuitabilityStatus.NOT_ALLOWED,
                max_allocation=0.10,
            )

    def test_not_allowed_acepta_max_allocation_cero(self):
        r = InstrumentSuitabilityRule(
            instrument_type="crypto_trust",
            profile_name="conservador",
            status=InstrumentSuitabilityStatus.NOT_ALLOWED,
            max_allocation=0.0,
        )
        assert r.status == InstrumentSuitabilityStatus.NOT_ALLOWED

    def test_not_allowed_acepta_max_allocation_none(self):
        r = InstrumentSuitabilityRule(
            instrument_type="crypto_trust",
            profile_name="conservador",
            status=InstrumentSuitabilityStatus.NOT_ALLOWED,
            max_allocation=None,
        )
        assert r.max_allocation is None

    def test_to_dict_contiene_todos_los_campos(self):
        r = InstrumentSuitabilityRule(
            instrument_type="thematic_equity",
            profile_name="moderado",
            status=InstrumentSuitabilityStatus.LIMITED,
            max_allocation=0.05,
            requires_advisor_note=True,
            reason_code="SUIT_003",
            notes=["nota"],
        )
        d = r.to_dict()
        assert d["instrument_type"] == "thematic_equity"
        assert d["profile_name"] == "moderado"
        assert d["status"] == "limited"
        assert d["max_allocation"] == 0.05
        assert d["requires_advisor_note"] is True
        assert d["reason_code"] == "SUIT_003"
        assert d["notes"] == ["nota"]


# ── 2. Carga YAML ─────────────────────────────────────────────────────────


class TestCargaYAML:
    def test_fixture_existe(self):
        assert FIXTURE_PATH.exists(), f"Fixture no encontrado: {FIXTURE_PATH}"

    def test_carga_yaml_correctamente(self, matrix):
        assert isinstance(matrix, InstrumentSuitabilityMatrix)
        # 8 instrument_types × 5 perfiles = 40 reglas
        assert len(matrix) == 40

    def test_yaml_inexistente_lanza_filenotfounderror(self, tmp_path):
        missing = tmp_path / "no_existe.yaml"
        with pytest.raises(FileNotFoundError):
            InstrumentSuitabilityMatrix.from_yaml(missing)

    def test_yaml_invalido_lanza_value_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("rules: : invalid : yaml", encoding="utf-8")
        with pytest.raises(ValueError, match="YAML inválido"):
            InstrumentSuitabilityMatrix.from_yaml(bad)

    def test_yaml_sin_rules_lanza_error(self, tmp_path):
        bad = tmp_path / "no_rules.yaml"
        bad.write_text("otra_clave: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="rules"):
            InstrumentSuitabilityMatrix.from_yaml(bad)

    def test_yaml_rules_no_lista_lanza_error(self, tmp_path):
        bad = tmp_path / "wrong_type.yaml"
        bad.write_text("rules: not_a_list\n", encoding="utf-8")
        with pytest.raises(ValueError, match="lista"):
            InstrumentSuitabilityMatrix.from_yaml(bad)

    def test_yaml_status_invalido_lanza_error(self, tmp_path):
        bad = tmp_path / "bad_status.yaml"
        bad.write_text(
            "rules:\n"
            "  - instrument_type: money_market\n"
            "    profile_name: conservador\n"
            "    status: super_aprobado\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="status"):
            InstrumentSuitabilityMatrix.from_yaml(bad)

    def test_yaml_falta_campo_lanza_error(self, tmp_path):
        bad = tmp_path / "missing_field.yaml"
        bad.write_text(
            "rules:\n"
            "  - instrument_type: money_market\n"
            "    status: allowed\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="YAML inválido"):
            InstrumentSuitabilityMatrix.from_yaml(bad)

    def test_yaml_reglas_duplicadas_lanza_error(self, tmp_path):
        bad = tmp_path / "duplicate.yaml"
        bad.write_text(
            "rules:\n"
            "  - instrument_type: money_market\n"
            "    profile_name: conservador\n"
            "    status: allowed\n"
            "    max_allocation: 1.0\n"
            "  - instrument_type: money_market\n"
            "    profile_name: conservador\n"
            "    status: limited\n"
            "    max_allocation: 0.5\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="duplicada"):
            InstrumentSuitabilityMatrix.from_yaml(bad)

    def test_yaml_limited_sin_max_allocation_lanza_error(self, tmp_path):
        bad = tmp_path / "limited_no_max.yaml"
        bad.write_text(
            "rules:\n"
            "  - instrument_type: money_market\n"
            "    profile_name: conservador\n"
            "    status: limited\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="LIMITED"):
            InstrumentSuitabilityMatrix.from_yaml(bad)


# ── 3. Consultas básicas ──────────────────────────────────────────────────


class TestConsultas:
    def test_get_rule_devuelve_regla_existente(self, matrix):
        r = matrix.get_rule("money_market", "conservador")
        assert r is not None
        assert r.status == InstrumentSuitabilityStatus.ALLOWED
        assert r.max_allocation == 1.0

    def test_get_rule_devuelve_none_si_no_existe(self, matrix):
        assert matrix.get_rule("unknown_instrument", "conservador") is None
        assert matrix.get_rule("money_market", "perfil-inexistente") is None

    def test_evaluate_devuelve_regla_existente(self, matrix):
        r = matrix.evaluate("equity_etf_global", "moderado")
        assert r.status == InstrumentSuitabilityStatus.ALLOWED
        assert r.max_allocation == 0.40

    def test_evaluate_para_regla_faltante_devuelve_not_allowed(self, matrix):
        r = matrix.evaluate("instrumento_inventado", "conservador")
        assert r.status == InstrumentSuitabilityStatus.NOT_ALLOWED
        assert r.reason_code == RULE_MISSING_REASON_CODE
        assert r.max_allocation == 0.0
        assert "M1 conservadora" in r.notes[0] or "NOT_ALLOWED" in r.notes[0]

    def test_evaluate_para_perfil_desconocido_devuelve_not_allowed(self, matrix):
        r = matrix.evaluate("money_market", "perfil-inventado")
        assert r.status == InstrumentSuitabilityStatus.NOT_ALLOWED
        assert r.reason_code == RULE_MISSING_REASON_CODE

    def test_evaluate_instrument_type_vacio_lanza_error(self, matrix):
        with pytest.raises(ValueError, match="instrument_type"):
            matrix.evaluate("", "conservador")

    def test_evaluate_profile_name_vacio_lanza_error(self, matrix):
        with pytest.raises(ValueError, match="profile_name"):
            matrix.evaluate("money_market", "")


# ── 4. Helpers is_allowed / is_limited / is_not_allowed ──────────────────


class TestHelpersStatus:
    def test_is_allowed_funciona(self, matrix):
        assert matrix.is_allowed("money_market", "conservador") is True
        assert matrix.is_allowed("high_yield_bond", "conservador") is False
        assert matrix.is_allowed("equity_etf_global", "moderado") is True

    def test_is_limited_funciona(self, matrix):
        assert matrix.is_limited("equity_etf_global", "conservador") is True
        assert matrix.is_limited("money_market", "conservador") is False
        assert matrix.is_limited("crypto_trust", "agresivo") is False

    def test_is_not_allowed_funciona(self, matrix):
        assert matrix.is_not_allowed("high_yield_bond", "conservador") is True
        assert matrix.is_not_allowed("crypto_trust", "agresivo") is True
        assert matrix.is_not_allowed("money_market", "conservador") is False

    def test_is_not_allowed_para_regla_faltante(self, matrix):
        assert matrix.is_not_allowed("instrumento_inventado", "moderado") is True
        assert matrix.is_allowed("instrumento_inventado", "moderado") is False


# ── 5. Reglas específicas esperadas ───────────────────────────────────────


class TestReglasEsperadas:
    def test_money_market_allowed_para_conservador(self, matrix):
        r = matrix.evaluate("money_market", "conservador")
        assert r.status == InstrumentSuitabilityStatus.ALLOWED
        assert r.max_allocation == 1.0

    def test_money_market_allowed_para_todos_los_perfiles(self, matrix):
        for profile in ["conservador", "moderado-defensivo", "moderado",
                        "moderado-agresivo", "agresivo"]:
            r = matrix.evaluate("money_market", profile)
            assert r.status == InstrumentSuitabilityStatus.ALLOWED, (
                f"money_market debería ser ALLOWED para {profile!r}"
            )

    def test_equity_etf_global_limitado_para_conservador_con_max_10pct(self, matrix):
        r = matrix.evaluate("equity_etf_global", "conservador")
        assert r.status == InstrumentSuitabilityStatus.LIMITED
        assert r.max_allocation == pytest.approx(0.10)
        assert r.requires_advisor_note is True

    def test_equity_etf_global_progresion_por_perfil(self, matrix):
        assert matrix.evaluate("equity_etf_global", "moderado-defensivo").max_allocation == pytest.approx(0.25)
        assert matrix.evaluate("equity_etf_global", "moderado").max_allocation == pytest.approx(0.40)
        assert matrix.evaluate("equity_etf_global", "moderado-agresivo").max_allocation == pytest.approx(0.60)
        assert matrix.evaluate("equity_etf_global", "agresivo").max_allocation == pytest.approx(0.80)

    def test_high_yield_bond_no_permitido_para_conservador(self, matrix):
        r = matrix.evaluate("high_yield_bond", "conservador")
        assert r.status == InstrumentSuitabilityStatus.NOT_ALLOWED
        assert r.reason_code == "SUIT_001"

    def test_high_yield_bond_progresion_para_perfiles_superiores(self, matrix):
        assert matrix.evaluate("high_yield_bond", "moderado-defensivo").max_allocation == pytest.approx(0.05)
        assert matrix.evaluate("high_yield_bond", "moderado").max_allocation == pytest.approx(0.10)
        assert matrix.evaluate("high_yield_bond", "moderado-agresivo").max_allocation == pytest.approx(0.15)
        assert matrix.evaluate("high_yield_bond", "agresivo").max_allocation == pytest.approx(0.25)

    def test_thematic_equity_requires_advisor_note_para_moderado(self, matrix):
        r = matrix.evaluate("thematic_equity", "moderado")
        assert r.status == InstrumentSuitabilityStatus.LIMITED
        assert r.max_allocation == pytest.approx(0.05)
        assert r.requires_advisor_note is True

    def test_thematic_equity_requires_advisor_note_para_perfiles_superiores(self, matrix):
        for profile in ["moderado", "moderado-agresivo", "agresivo"]:
            r = matrix.evaluate("thematic_equity", profile)
            assert r.requires_advisor_note is True, (
                f"thematic_equity en {profile!r} debe requerir advisor_note."
            )

    def test_thematic_equity_no_permitido_para_perfiles_defensivos(self, matrix):
        for profile in ["conservador", "moderado-defensivo"]:
            r = matrix.evaluate("thematic_equity", profile)
            assert r.status == InstrumentSuitabilityStatus.NOT_ALLOWED

    def test_crypto_trust_no_permitido_para_todos(self, matrix):
        for profile in ["conservador", "moderado-defensivo", "moderado",
                        "moderado-agresivo", "agresivo"]:
            r = matrix.evaluate("crypto_trust", profile)
            assert r.status == InstrumentSuitabilityStatus.NOT_ALLOWED, (
                f"crypto_trust no debe estar permitido en {profile!r} en M1."
            )

    def test_sector_equity_progresion(self, matrix):
        assert matrix.is_not_allowed("sector_equity", "conservador")
        assert matrix.evaluate("sector_equity", "moderado-defensivo").max_allocation == pytest.approx(0.05)
        assert matrix.evaluate("sector_equity", "moderado").max_allocation == pytest.approx(0.10)
        assert matrix.evaluate("sector_equity", "moderado-agresivo").max_allocation == pytest.approx(0.15)
        assert matrix.evaluate("sector_equity", "agresivo").max_allocation == pytest.approx(0.20)

    def test_long_duration_bond_progresion(self, matrix):
        assert matrix.is_not_allowed("long_duration_bond", "conservador")
        assert matrix.evaluate("long_duration_bond", "moderado-defensivo").max_allocation == pytest.approx(0.10)
        assert matrix.evaluate("long_duration_bond", "moderado").max_allocation == pytest.approx(0.15)
        assert matrix.evaluate("long_duration_bond", "moderado-agresivo").max_allocation == pytest.approx(0.20)
        assert matrix.evaluate("long_duration_bond", "agresivo").max_allocation == pytest.approx(0.25)


# ── 6. all_rules ──────────────────────────────────────────────────────────


class TestAllRules:
    def test_all_rules_devuelve_lista(self, matrix):
        rules = matrix.all_rules()
        assert isinstance(rules, list)
        assert len(rules) == 40
        assert all(isinstance(r, InstrumentSuitabilityRule) for r in rules)

    def test_all_rules_devuelve_copia_segura(self, matrix):
        rules = matrix.all_rules()
        initial_len = len(rules)
        rules.clear()
        assert len(matrix.all_rules()) == initial_len


# ── 7. Exclusion report ───────────────────────────────────────────────────


class TestExclusionReport:
    def test_report_devuelve_estructura_esperada(self, matrix):
        report = matrix.exclusion_report(
            ["money_market", "high_yield_bond", "crypto_trust"],
            "conservador",
        )
        assert len(report) >= 2  # high_yield_bond + crypto_trust
        for entry in report:
            assert "instrument_type" in entry
            assert "profile_name" in entry
            assert "status" in entry
            assert "max_allocation" in entry
            assert "requires_advisor_note" in entry
            assert "reason_code" in entry
            assert "notes" in entry

    def test_report_no_incluye_allowed(self, matrix):
        report = matrix.exclusion_report(
            ["money_market", "high_yield_bond"],
            "conservador",
        )
        tipos_en_reporte = {e["instrument_type"] for e in report}
        assert "money_market" not in tipos_en_reporte
        assert "high_yield_bond" in tipos_en_reporte

    def test_report_incluye_limited(self, matrix):
        # equity_etf_global es LIMITED para conservador
        report = matrix.exclusion_report(
            ["equity_etf_global"],
            "conservador",
        )
        assert len(report) == 1
        assert report[0]["status"] == "limited"
        assert report[0]["max_allocation"] == pytest.approx(0.10)

    def test_report_para_perfil_vacio_lanza_error(self, matrix):
        with pytest.raises(ValueError, match="profile_name"):
            matrix.exclusion_report(["money_market"], "")

    def test_report_para_instrument_type_desconocido_incluye_rule_missing(self, matrix):
        report = matrix.exclusion_report(["instrumento_inventado"], "moderado")
        assert len(report) == 1
        assert report[0]["status"] == "not_allowed"
        assert report[0]["reason_code"] == RULE_MISSING_REASON_CODE


# ── 8. len y __contains__ implícito ───────────────────────────────────────


class TestUtilidades:
    def test_len_de_matrix(self, matrix):
        assert len(matrix) == 40

    def test_rule_missing_reason_code_es_constante(self):
        assert RULE_MISSING_REASON_CODE == "SUITABILITY_RULE_MISSING"
