"""
Tests de ESGComplianceChecker, ESGMetadataStore y dataclasses asociados.

Cubre:
    - Validaciones de InstrumentESGMetadata y ESGComplianceResult.
    - Carga desde YAML.
    - Política M1 ante metadata faltante (UNKNOWN).
    - Hard exclusions: sector, tag, issuer, controversy.
    - Matching case-insensitive.
    - Soft preferences: min_esg_score, max_carbon_intensity, prefer/avoid tag.
    - score_adjustment: acumulación y clamp a -1.0.
    - PASS cuando no hay incumplimientos.
"""

import json
from pathlib import Path

import pytest

from risk_first_advisory.kyc.models import (
    ESGExclusion,
    ESGPreference,
    ESGProfile,
    ESGStrictnessLevel,
)
from risk_first_advisory.rules_layer.esg_compliance import (
    REASON_DATA_INCOMPLETE,
    REASON_HARD_EXCLUSION_CONTROVERSY,
    REASON_HARD_EXCLUSION_ISSUER,
    REASON_HARD_EXCLUSION_SECTOR,
    REASON_HARD_EXCLUSION_TAG,
    REASON_METADATA_MISSING,
    REASON_SOFT_MAX_CARBON,
    REASON_SOFT_MIN_ESG_SCORE,
    ESGComplianceChecker,
    ESGComplianceResult,
    ESGComplianceStatus,
    ESGMetadataStore,
    InstrumentESGMetadata,
)

FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "esg"
    / "instrument_esg_metadata.yaml"
)


# ── Fixtures pytest ───────────────────────────────────────────────────────


@pytest.fixture
def store() -> ESGMetadataStore:
    return ESGMetadataStore.from_yaml(FIXTURE_PATH)


@pytest.fixture
def checker() -> ESGComplianceChecker:
    return ESGComplianceChecker()


def _profile_with(
    hard_exclusions: list[ESGExclusion] | None = None,
    soft_preferences: list[ESGPreference] | None = None,
    strictness: ESGStrictnessLevel = ESGStrictnessLevel.LIGHT,
) -> ESGProfile:
    return ESGProfile(
        strictness_level=strictness,
        hard_exclusions=hard_exclusions or [],
        soft_preferences=soft_preferences or [],
    )


# ── 1. Validación InstrumentESGMetadata ───────────────────────────────────


class TestMetadataValidacion:
    def test_metadata_valida(self):
        m = InstrumentESGMetadata(
            ticker="AGG",
            issuer="BlackRock",
            sectors=["Government"],
            tags=["bond_etf"],
            esg_score=70.0,
            carbon_intensity=30.0,
        )
        assert m.ticker == "AGG"
        assert m.esg_score == 70.0

    def test_ticker_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="ticker"):
            InstrumentESGMetadata(ticker="", issuer="BlackRock")

    def test_issuer_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="issuer"):
            InstrumentESGMetadata(ticker="AGG", issuer="")

    def test_sectors_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="sectors"):
            InstrumentESGMetadata(
                ticker="AGG",
                issuer="BlackRock",
                sectors="Government",  # type: ignore[arg-type]
            )

    def test_tags_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="tags"):
            InstrumentESGMetadata(
                ticker="AGG",
                issuer="BlackRock",
                tags="bond_etf",  # type: ignore[arg-type]
            )

    def test_controversies_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="controversies"):
            InstrumentESGMetadata(
                ticker="AGG",
                issuer="BlackRock",
                controversies="ninguna",  # type: ignore[arg-type]
            )

    def test_esg_score_fuera_de_rango_lanza_error(self):
        with pytest.raises(ValueError, match="esg_score"):
            InstrumentESGMetadata(
                ticker="AGG", issuer="BlackRock", esg_score=150.0
            )

    def test_esg_score_negativo_lanza_error(self):
        with pytest.raises(ValueError, match="esg_score"):
            InstrumentESGMetadata(
                ticker="AGG", issuer="BlackRock", esg_score=-5.0
            )

    def test_carbon_intensity_negativa_lanza_error(self):
        with pytest.raises(ValueError, match="carbon_intensity"):
            InstrumentESGMetadata(
                ticker="AGG", issuer="BlackRock", carbon_intensity=-10.0
            )

    def test_esg_score_none_es_valido(self):
        m = InstrumentESGMetadata(ticker="X", issuer="Y", esg_score=None)
        assert m.esg_score is None

    def test_carbon_intensity_none_es_valido(self):
        m = InstrumentESGMetadata(ticker="X", issuer="Y", carbon_intensity=None)
        assert m.carbon_intensity is None

    def test_to_dict_contiene_todos_los_campos(self):
        m = InstrumentESGMetadata(
            ticker="MO",
            issuer="Altria",
            sectors=["Tobacco"],
            tags=["tobacco"],
            esg_score=30.0,
            carbon_intensity=40.0,
            controversies=["public_health"],
            notes=["nota"],
        )
        d = m.to_dict()
        assert d["ticker"] == "MO"
        assert d["sectors"] == ["Tobacco"]
        assert d["controversies"] == ["public_health"]


# ── 2. ESGMetadataStore ───────────────────────────────────────────────────


class TestStore:
    def test_fixture_existe(self):
        assert FIXTURE_PATH.exists(), f"Fixture no encontrado: {FIXTURE_PATH}"

    def test_carga_yaml_correctamente(self, store):
        assert isinstance(store, ESGMetadataStore)
        assert len(store) >= 9

    def test_contains_devuelve_true_para_ticker_existente(self, store):
        assert store.contains("AGG") is True
        assert "MO" in store

    def test_contains_devuelve_false_para_ticker_inexistente(self, store):
        assert store.contains("UNKNOWN_TEST") is False
        assert "UNKNOWN_TEST" not in store

    def test_get_devuelve_metadata(self, store):
        m = store.get("MO")
        assert m is not None
        assert isinstance(m, InstrumentESGMetadata)
        assert "Tobacco" in m.sectors

    def test_get_devuelve_none_para_ticker_desconocido(self, store):
        assert store.get("UNKNOWN_TEST") is None

    def test_all_metadata_devuelve_copia_segura(self, store):
        items = store.all_metadata()
        initial_len = len(items)
        items.clear()
        assert len(store.all_metadata()) == initial_len

    def test_yaml_inexistente_lanza_filenotfounderror(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ESGMetadataStore.from_yaml(tmp_path / "missing.yaml")

    def test_yaml_sin_instruments_lanza_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("otra_clave: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="instruments"):
            ESGMetadataStore.from_yaml(bad)

    def test_yaml_ticker_duplicado_lanza_error(self, tmp_path):
        bad = tmp_path / "dup.yaml"
        bad.write_text(
            "instruments:\n"
            "  - ticker: AGG\n"
            "    issuer: BlackRock\n"
            "  - ticker: AGG\n"
            "    issuer: BlackRock\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="duplicado"):
            ESGMetadataStore.from_yaml(bad)


# ── 3. Política UNKNOWN para metadata faltante ────────────────────────────


class TestMetadataMissing:
    def test_sin_metadata_devuelve_unknown(self, store, checker):
        result = checker.evaluate(
            "UNKNOWN_TEST",
            _profile_with(),
            store,
        )
        assert result.status == ESGComplianceStatus.UNKNOWN
        assert result.is_blocked is False
        assert REASON_METADATA_MISSING in result.reason_codes
        assert len(result.warnings) >= 1


# ── 4. Hard exclusions ────────────────────────────────────────────────────


class TestHardExclusions:
    def test_sector_tobacco_bloquea_mo(self, store, checker):
        profile = _profile_with(
            hard_exclusions=[
                ESGExclusion(
                    excluded_item="Tobacco",
                    exclusion_type="sector",
                    source="client_explicit",
                )
            ]
        )
        result = checker.evaluate("MO", profile, store)
        assert result.status == ESGComplianceStatus.BLOCKED
        assert result.is_blocked is True
        assert REASON_HARD_EXCLUSION_SECTOR in result.reason_codes
        assert any("Tobacco" in b for b in result.blocked_by)

    def test_tag_fossil_fuels_bloquea_xle(self, store, checker):
        profile = _profile_with(
            hard_exclusions=[
                ESGExclusion(
                    excluded_item="fossil_fuels",
                    exclusion_type="tag",
                    source="client_explicit",
                )
            ]
        )
        result = checker.evaluate("XLE", profile, store)
        assert result.is_blocked is True
        assert REASON_HARD_EXCLUSION_TAG in result.reason_codes

    def test_issuer_altria_bloquea_mo(self, store, checker):
        profile = _profile_with(
            hard_exclusions=[
                ESGExclusion(
                    excluded_item="Altria Group",
                    exclusion_type="issuer",
                    source="client_explicit",
                )
            ]
        )
        result = checker.evaluate("MO", profile, store)
        assert result.is_blocked is True
        assert REASON_HARD_EXCLUSION_ISSUER in result.reason_codes

    def test_controversy_weapons_bloquea_lmt(self, store, checker):
        profile = _profile_with(
            hard_exclusions=[
                ESGExclusion(
                    excluded_item="weapons_manufacturing",
                    exclusion_type="controversy",
                    source="client_explicit",
                )
            ]
        )
        result = checker.evaluate("LMT", profile, store)
        assert result.is_blocked is True
        assert REASON_HARD_EXCLUSION_CONTROVERSY in result.reason_codes

    def test_matching_es_case_insensitive(self, store, checker):
        # Sector "Tobacco" en metadata, exclusión declarada en MAYÚSCULAS
        profile = _profile_with(
            hard_exclusions=[
                ESGExclusion(
                    excluded_item="TOBACCO",
                    exclusion_type="sector",
                    source="client_explicit",
                )
            ]
        )
        result = checker.evaluate("MO", profile, store)
        assert result.is_blocked is True

    def test_matching_case_insensitive_para_issuer(self, store, checker):
        profile = _profile_with(
            hard_exclusions=[
                ESGExclusion(
                    excluded_item="altria group",
                    exclusion_type="issuer",
                    source="client_explicit",
                )
            ]
        )
        result = checker.evaluate("MO", profile, store)
        assert result.is_blocked is True

    def test_hard_exclusion_no_aplica_si_no_match(self, store, checker):
        # SGOV no tiene tabaco — la exclusión no debe bloquear
        profile = _profile_with(
            hard_exclusions=[
                ESGExclusion(
                    excluded_item="Tobacco",
                    exclusion_type="sector",
                    source="client_explicit",
                )
            ]
        )
        result = checker.evaluate("SGOV", profile, store)
        assert result.status == ESGComplianceStatus.PASS
        assert result.is_blocked is False

    def test_bloqueado_no_evalua_soft_preferences(self, store, checker):
        """
        Cuando un instrumento está bloqueado, no se evalúan soft preferences.
        score_adjustment debe quedar en 0.0 (política documentada en el módulo).
        """
        profile = _profile_with(
            hard_exclusions=[
                ESGExclusion(
                    excluded_item="Tobacco",
                    exclusion_type="sector",
                    source="client_explicit",
                )
            ],
            soft_preferences=[
                ESGPreference(
                    preference_type="min_esg_score",
                    weight=0.5,
                    minimum_threshold=80.0,
                )
            ],
        )
        result = checker.evaluate("MO", profile, store)
        assert result.is_blocked is True
        assert result.soft_score_adjustment == 0.0


# ── 5. Soft preferences ───────────────────────────────────────────────────


class TestSoftPreferences:
    def test_min_esg_score_warning_si_no_cumple(self, store, checker):
        # HYG tiene esg_score=45. Threshold=80 → no cumple.
        profile = _profile_with(
            soft_preferences=[
                ESGPreference(
                    preference_type="min_esg_score",
                    weight=0.3,
                    minimum_threshold=80.0,
                )
            ]
        )
        result = checker.evaluate("HYG", profile, store)
        assert result.status == ESGComplianceStatus.SOFT_WARNING
        assert result.is_blocked is False
        assert result.has_warnings is True
        assert REASON_SOFT_MIN_ESG_SCORE in result.reason_codes
        assert result.soft_score_adjustment == pytest.approx(-0.3)

    def test_min_esg_score_pass_si_cumple(self, store, checker):
        # SGOV tiene esg_score=80. Threshold=70 → cumple.
        profile = _profile_with(
            soft_preferences=[
                ESGPreference(
                    preference_type="min_esg_score",
                    weight=0.3,
                    minimum_threshold=70.0,
                )
            ]
        )
        result = checker.evaluate("SGOV", profile, store)
        assert result.status == ESGComplianceStatus.PASS

    def test_max_carbon_intensity_warning_si_no_cumple(self, store, checker):
        # XLE tiene carbon_intensity=850. Threshold=300 → no cumple.
        profile = _profile_with(
            soft_preferences=[
                ESGPreference(
                    preference_type="max_carbon_intensity",
                    weight=0.4,
                    minimum_threshold=300.0,
                )
            ]
        )
        result = checker.evaluate("XLE", profile, store)
        assert result.status == ESGComplianceStatus.SOFT_WARNING
        assert REASON_SOFT_MAX_CARBON in result.reason_codes
        assert result.soft_score_adjustment == pytest.approx(-0.4)

    def test_max_carbon_intensity_pass_si_cumple(self, store, checker):
        # SGOV tiene carbon_intensity=5. Threshold=100 → cumple.
        profile = _profile_with(
            soft_preferences=[
                ESGPreference(
                    preference_type="max_carbon_intensity",
                    weight=0.4,
                    minimum_threshold=100.0,
                )
            ]
        )
        result = checker.evaluate("SGOV", profile, store)
        assert result.status == ESGComplianceStatus.PASS

    def test_prefer_tag_genera_warning_data_incomplete(self, store, checker):
        """
        El modelo actual de ESGPreference no tiene campo para el tag target.
        Política M1: warning con reason_code ESG_DATA_INCOMPLETE.
        """
        profile = _profile_with(
            soft_preferences=[
                ESGPreference(preference_type="prefer_tag", weight=0.2)
            ]
        )
        result = checker.evaluate("AGG", profile, store)
        assert result.status == ESGComplianceStatus.SOFT_WARNING
        assert REASON_DATA_INCOMPLETE in result.reason_codes

    def test_avoid_tag_genera_warning_data_incomplete(self, store, checker):
        profile = _profile_with(
            soft_preferences=[
                ESGPreference(preference_type="avoid_tag", weight=0.2)
            ]
        )
        result = checker.evaluate("AGG", profile, store)
        assert result.status == ESGComplianceStatus.SOFT_WARNING
        assert REASON_DATA_INCOMPLETE in result.reason_codes

    def test_score_adjustment_acumula_pesos_negativos(self, store, checker):
        # Combinamos dos preferencias incumplidas con weights 0.2 y 0.3 → -0.5
        profile = _profile_with(
            soft_preferences=[
                ESGPreference(
                    preference_type="min_esg_score",
                    weight=0.2,
                    minimum_threshold=90.0,
                ),
                ESGPreference(
                    preference_type="max_carbon_intensity",
                    weight=0.3,
                    minimum_threshold=10.0,
                ),
            ]
        )
        result = checker.evaluate("HYG", profile, store)
        assert result.soft_score_adjustment == pytest.approx(-0.5)

    def test_score_adjustment_no_baja_de_menos_uno(self, store, checker):
        # 4 preferencias de weight 0.5 cada una → sin clamp serían -2.0
        profile = _profile_with(
            soft_preferences=[
                ESGPreference(
                    preference_type="min_esg_score",
                    weight=0.5,
                    minimum_threshold=99.0,
                ),
                ESGPreference(
                    preference_type="max_carbon_intensity",
                    weight=0.5,
                    minimum_threshold=1.0,
                ),
                ESGPreference(preference_type="prefer_tag", weight=0.5),
                ESGPreference(preference_type="avoid_tag", weight=0.5),
            ]
        )
        result = checker.evaluate("XLE", profile, store)
        assert result.soft_score_adjustment == pytest.approx(-1.0)
        assert result.soft_score_adjustment >= -1.0

    def test_soft_warning_no_bloquea(self, store, checker):
        profile = _profile_with(
            soft_preferences=[
                ESGPreference(
                    preference_type="min_esg_score",
                    weight=0.3,
                    minimum_threshold=99.0,
                )
            ]
        )
        result = checker.evaluate("HYG", profile, store)
        assert result.status == ESGComplianceStatus.SOFT_WARNING
        assert result.is_blocked is False


# ── 6. PASS y profiles vacíos ─────────────────────────────────────────────


class TestPassYProfilesVacios:
    def test_pass_cuando_no_hay_exclusiones_ni_warnings(self, store, checker):
        profile = _profile_with()  # hard y soft vacíos
        result = checker.evaluate("AGG", profile, store)
        assert result.status == ESGComplianceStatus.PASS
        assert result.is_blocked is False
        assert result.has_warnings is False
        assert result.soft_score_adjustment == 0.0

    def test_pass_con_hard_y_soft_que_no_matchean(self, store, checker):
        profile = _profile_with(
            hard_exclusions=[
                ESGExclusion(
                    excluded_item="Tobacco",
                    exclusion_type="sector",
                    source="client_explicit",
                )
            ],
            soft_preferences=[
                ESGPreference(
                    preference_type="min_esg_score",
                    weight=0.2,
                    minimum_threshold=50.0,
                )
            ],
        )
        # AGG tiene esg_score=70 > 50 y no es Tobacco
        result = checker.evaluate("AGG", profile, store)
        assert result.status == ESGComplianceStatus.PASS


# ── 7. ESGComplianceResult ────────────────────────────────────────────────


class TestResult:
    def test_to_dict_es_json_serializable(self, store, checker):
        profile = _profile_with(
            hard_exclusions=[
                ESGExclusion(
                    excluded_item="Tobacco",
                    exclusion_type="sector",
                    source="client_explicit",
                )
            ]
        )
        result = checker.evaluate("MO", profile, store)
        payload = json.dumps(result.to_dict())
        parsed = json.loads(payload)
        assert parsed["ticker"] == "MO"
        assert parsed["status"] == "blocked"
        assert REASON_HARD_EXCLUSION_SECTOR in parsed["reason_codes"]

    def test_is_blocked_property(self):
        r = ESGComplianceResult(
            ticker="MO",
            status=ESGComplianceStatus.BLOCKED,
            blocked_by=["sector=Tobacco"],
        )
        assert r.is_blocked is True

    def test_has_warnings_property(self):
        r = ESGComplianceResult(
            ticker="HYG",
            status=ESGComplianceStatus.SOFT_WARNING,
            warnings=["esg_score bajo"],
            soft_score_adjustment=-0.3,
        )
        assert r.has_warnings is True

    def test_score_adjustment_positivo_lanza_error(self):
        with pytest.raises(ValueError, match="soft_score_adjustment"):
            ESGComplianceResult(
                ticker="AGG",
                status=ESGComplianceStatus.PASS,
                soft_score_adjustment=0.5,
            )

    def test_score_adjustment_menor_que_menos_uno_lanza_error(self):
        with pytest.raises(ValueError, match="soft_score_adjustment"):
            ESGComplianceResult(
                ticker="AGG",
                status=ESGComplianceStatus.PASS,
                soft_score_adjustment=-1.5,
            )

    def test_ticker_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="ticker"):
            ESGComplianceResult(
                ticker="",
                status=ESGComplianceStatus.PASS,
            )


# ── 8. Validación de entrada del checker ──────────────────────────────────


class TestCheckerInputs:
    def test_ticker_vacio_lanza_error(self, store, checker):
        with pytest.raises(ValueError, match="ticker"):
            checker.evaluate("", _profile_with(), store)
