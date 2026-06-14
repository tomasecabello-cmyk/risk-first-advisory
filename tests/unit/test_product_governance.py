"""
Tests del ApprovedProductUniverse y ProductGovernanceRecord.

Cubre:
    - Construcción y validación del dataclass.
    - Carga desde YAML (válido e inválido).
    - Consultas básicas: contains, get, all_records, approved_records.
    - filter_for_profile con la política M1 conservadora.
    - exclusion_report_for_profile con motivos legibles.
    - Bloqueos por estado, review vencida, perfiles restringidos.
    - Watchlist pasa pero queda identificable.
"""

from datetime import date
from pathlib import Path

import pytest

from risk_first_advisory.rules_layer.product_governance import (
    ApprovedProductUniverse,
    ProductGovernanceRecord,
    ProductGovernanceStatus,
    is_watchlist,
)

FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "universes"
    / "m1_universe.yaml"
)


# ── Fixtures pytest ───────────────────────────────────────────────────────


@pytest.fixture
def universe() -> ApprovedProductUniverse:
    return ApprovedProductUniverse.from_yaml(FIXTURE_PATH)


# ── 1. Construcción del dataclass ─────────────────────────────────────────


class TestProductGovernanceRecordConstruccion:
    def test_record_valido_se_construye(self):
        r = ProductGovernanceRecord(
            ticker="AGG",
            name="iShares Core US Aggregate Bond ETF",
            instrument_type="bond_etf",
            status=ProductGovernanceStatus.APPROVED,
        )
        assert r.ticker == "AGG"
        assert r.status == ProductGovernanceStatus.APPROVED
        assert r.allowed_profiles == []
        assert r.restricted_profiles == []

    def test_ticker_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="ticker"):
            ProductGovernanceRecord(
                ticker="",
                name="Algún producto",
                instrument_type="bond_etf",
                status=ProductGovernanceStatus.APPROVED,
            )

    def test_ticker_solo_espacios_lanza_error(self):
        with pytest.raises(ValueError, match="ticker"):
            ProductGovernanceRecord(
                ticker="   ",
                name="Algún producto",
                instrument_type="bond_etf",
                status=ProductGovernanceStatus.APPROVED,
            )

    def test_name_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="name"):
            ProductGovernanceRecord(
                ticker="AGG",
                name="",
                instrument_type="bond_etf",
                status=ProductGovernanceStatus.APPROVED,
            )

    def test_instrument_type_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="instrument_type"):
            ProductGovernanceRecord(
                ticker="AGG",
                name="Algún producto",
                instrument_type="",
                status=ProductGovernanceStatus.APPROVED,
            )

    def test_status_no_enum_lanza_error(self):
        with pytest.raises(ValueError, match="status"):
            ProductGovernanceRecord(
                ticker="AGG",
                name="Algún producto",
                instrument_type="bond_etf",
                status="approved",  # type: ignore[arg-type]
            )

    def test_allowed_profiles_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="allowed_profiles"):
            ProductGovernanceRecord(
                ticker="AGG",
                name="x",
                instrument_type="bond_etf",
                status=ProductGovernanceStatus.APPROVED,
                allowed_profiles="moderado",  # type: ignore[arg-type]
            )

    def test_restricted_profiles_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="restricted_profiles"):
            ProductGovernanceRecord(
                ticker="AGG",
                name="x",
                instrument_type="bond_etf",
                status=ProductGovernanceStatus.APPROVED,
                restricted_profiles="moderado",  # type: ignore[arg-type]
            )

    def test_conflicto_allowed_y_restricted_lanza_error(self):
        with pytest.raises(ValueError, match="simultáneamente"):
            ProductGovernanceRecord(
                ticker="AGG",
                name="x",
                instrument_type="bond_etf",
                status=ProductGovernanceStatus.APPROVED,
                allowed_profiles=["moderado", "agresivo"],
                restricted_profiles=["moderado"],
            )

    def test_to_dict_contiene_todos_los_campos(self):
        r = ProductGovernanceRecord(
            ticker="AGG",
            name="iShares Core US Aggregate Bond ETF",
            instrument_type="bond_etf",
            status=ProductGovernanceStatus.WATCHLIST,
            allowed_profiles=["moderado"],
            restricted_profiles=["conservador"],
            review_due_date="2099-12-31",
            notes=["nota1"],
            reason_code="GOV_006",
        )
        d = r.to_dict()
        assert d["ticker"] == "AGG"
        assert d["status"] == "watchlist"
        assert d["allowed_profiles"] == ["moderado"]
        assert d["restricted_profiles"] == ["conservador"]
        assert d["review_due_date"] == "2099-12-31"
        assert d["notes"] == ["nota1"]
        assert d["reason_code"] == "GOV_006"


# ── 2. Carga desde YAML ───────────────────────────────────────────────────


class TestCargaYAML:
    def test_fixture_yaml_existe(self):
        assert FIXTURE_PATH.exists(), f"Fixture no encontrado: {FIXTURE_PATH}"

    def test_carga_yaml_correctamente(self, universe):
        assert isinstance(universe, ApprovedProductUniverse)
        assert len(universe) >= 10

    def test_yaml_inexistente_lanza_filenotfounderror(self, tmp_path):
        missing = tmp_path / "no_existe.yaml"
        with pytest.raises(FileNotFoundError):
            ApprovedProductUniverse.from_yaml(missing)

    def test_yaml_invalido_lanza_value_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("products: : invalid : yaml", encoding="utf-8")
        with pytest.raises(ValueError, match="YAML inválido"):
            ApprovedProductUniverse.from_yaml(bad)

    def test_yaml_sin_clave_products_lanza_error(self, tmp_path):
        bad = tmp_path / "no_products.yaml"
        bad.write_text("otra_clave: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="products"):
            ApprovedProductUniverse.from_yaml(bad)

    def test_yaml_products_no_lista_lanza_error(self, tmp_path):
        bad = tmp_path / "wrong_type.yaml"
        bad.write_text("products: not_a_list\n", encoding="utf-8")
        with pytest.raises(ValueError, match="lista"):
            ApprovedProductUniverse.from_yaml(bad)

    def test_yaml_status_invalido_lanza_error(self, tmp_path):
        bad = tmp_path / "bad_status.yaml"
        bad.write_text(
            "products:\n"
            "  - ticker: X\n"
            "    name: X product\n"
            "    instrument_type: bond_etf\n"
            "    status: super_aprobado\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="status"):
            ApprovedProductUniverse.from_yaml(bad)

    def test_yaml_falta_campo_lanza_error(self, tmp_path):
        bad = tmp_path / "missing_field.yaml"
        bad.write_text(
            "products:\n"
            "  - ticker: X\n"
            "    status: approved\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="YAML inválido"):
            ApprovedProductUniverse.from_yaml(bad)

    def test_yaml_ticker_duplicado_lanza_error(self, tmp_path):
        bad = tmp_path / "duplicate.yaml"
        bad.write_text(
            "products:\n"
            "  - ticker: AGG\n"
            "    name: AGG ETF\n"
            "    instrument_type: bond_etf\n"
            "    status: approved\n"
            "  - ticker: AGG\n"
            "    name: AGG duplicado\n"
            "    instrument_type: bond_etf\n"
            "    status: approved\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="duplicado"):
            ApprovedProductUniverse.from_yaml(bad)


# ── 3. Consultas básicas ──────────────────────────────────────────────────


class TestConsultas:
    def test_contains_devuelve_true_para_ticker_existente(self, universe):
        assert universe.contains("AGG") is True

    def test_contains_devuelve_false_para_ticker_inexistente(self, universe):
        assert universe.contains("NO_EXISTE") is False

    def test_in_operator_funciona(self, universe):
        assert "AGG" in universe
        assert "NO_EXISTE" not in universe

    def test_get_devuelve_record(self, universe):
        r = universe.get("AGG")
        assert r is not None
        assert isinstance(r, ProductGovernanceRecord)
        assert r.ticker == "AGG"

    def test_get_devuelve_none_para_ticker_desconocido(self, universe):
        """Política de M1: get devuelve None, no KeyError."""
        r = universe.get("UNKNOWN_TICKER_XYZ")
        assert r is None

    def test_all_records_devuelve_lista(self, universe):
        records = universe.all_records()
        assert isinstance(records, list)
        assert len(records) >= 10
        assert all(isinstance(r, ProductGovernanceRecord) for r in records)

    def test_all_records_devuelve_copia_segura(self, universe):
        """Modificar la lista retornada no afecta el universo."""
        records = universe.all_records()
        initial_len = len(records)
        records.clear()
        assert len(universe.all_records()) == initial_len


# ── 4. approved_records ───────────────────────────────────────────────────


class TestApprovedRecords:
    def test_approved_records_excluye_prohibited(self, universe):
        approved = universe.approved_records()
        tickers = {r.ticker for r in approved}
        assert "GBTC" not in tickers  # prohibited

    def test_approved_records_excluye_suspended(self, universe):
        approved = universe.approved_records()
        tickers = {r.ticker for r in approved}
        assert "XLE" not in tickers  # temporarily_suspended

    def test_approved_records_excluye_restricted(self, universe):
        approved = universe.approved_records()
        tickers = {r.ticker for r in approved}
        assert "TLT" not in tickers  # restricted

    def test_approved_records_incluye_approved(self, universe):
        approved = universe.approved_records()
        tickers = {r.ticker for r in approved}
        assert "AGG" in tickers

    def test_approved_records_incluye_watchlist(self, universe):
        """WATCHLIST entra en approved_records — el flag se gestiona aparte."""
        approved = universe.approved_records()
        tickers = {r.ticker for r in approved}
        assert "ARKK" in tickers


# ── 5. filter_for_profile ─────────────────────────────────────────────────


class TestFilterForProfile:
    def test_filter_for_conservador_excluye_equity_global(self, universe):
        records = universe.filter_for_profile("conservador")
        tickers = {r.ticker for r in records}
        assert "VTI" not in tickers
        assert "VEA" not in tickers
        assert "ARKK" not in tickers

    def test_filter_for_conservador_excluye_high_yield(self, universe):
        records = universe.filter_for_profile("conservador")
        tickers = {r.ticker for r in records}
        assert "HYG" not in tickers

    def test_filter_for_conservador_incluye_money_market(self, universe):
        records = universe.filter_for_profile("conservador")
        tickers = {r.ticker for r in records}
        assert "BIL" in tickers
        assert "SHV" in tickers

    def test_filter_for_conservador_incluye_agg(self, universe):
        records = universe.filter_for_profile("conservador")
        tickers = {r.ticker for r in records}
        assert "AGG" in tickers

    def test_filter_for_moderado_incluye_productos_moderados(self, universe):
        records = universe.filter_for_profile("moderado")
        tickers = {r.ticker for r in records}
        assert "AGG" in tickers
        assert "VTI" in tickers
        assert "HYG" in tickers

    def test_filter_for_agresivo_incluye_thematic_watchlist(self, universe):
        records = universe.filter_for_profile("agresivo")
        tickers = {r.ticker for r in records}
        assert "ARKK" in tickers

    def test_filter_excluye_prohibited_para_todos_los_perfiles(self, universe):
        for profile in ["conservador", "moderado", "agresivo"]:
            tickers = {r.ticker for r in universe.filter_for_profile(profile)}
            assert "GBTC" not in tickers, f"GBTC apareció en {profile!r}"

    def test_filter_excluye_temporarily_suspended_para_todos(self, universe):
        for profile in ["conservador", "moderado", "agresivo"]:
            tickers = {r.ticker for r in universe.filter_for_profile(profile)}
            assert "XLE" not in tickers, f"XLE apareció en {profile!r}"

    def test_filter_excluye_restricted_para_todos_en_politica_m1(self, universe):
        for profile in ["conservador", "moderado", "agresivo", "moderado-agresivo"]:
            tickers = {r.ticker for r in universe.filter_for_profile(profile)}
            assert "TLT" not in tickers, (
                f"TLT (restricted) apareció en {profile!r} — viola política M1."
            )

    def test_filter_excluye_producto_con_review_vencida(self, universe):
        records = universe.filter_for_profile("moderado")
        tickers = {r.ticker for r in records}
        assert "STALE" not in tickers

    def test_filter_excluye_perfil_en_restricted_profiles(self, universe):
        # AGG no tiene a moderado-agresivo en restricted, pero VEA sí tiene a
        # moderado-defensivo en restricted.
        records = universe.filter_for_profile("moderado-defensivo")
        tickers = {r.ticker for r in records}
        assert "VEA" not in tickers

    def test_filter_respeta_allowed_profiles(self, universe):
        # ARKK solo permite moderado-agresivo y agresivo
        for not_allowed in ["conservador", "moderado-defensivo", "moderado"]:
            records = universe.filter_for_profile(not_allowed)
            tickers = {r.ticker for r in records}
            assert "ARKK" not in tickers, f"ARKK apareció en {not_allowed!r}"

    def test_filter_profile_vacio_lanza_error(self, universe):
        with pytest.raises(ValueError, match="profile_name"):
            universe.filter_for_profile("")

    def test_filter_acepta_as_of_para_overriding_fecha(self, universe):
        # Con as_of antes de la fecha vencida, STALE debería pasar
        past = date(2019, 1, 1)
        records = universe.filter_for_profile("moderado", as_of=past)
        tickers = {r.ticker for r in records}
        assert "STALE" in tickers, (
            "Con as_of=2019, STALE no debería estar vencida (due 2020-01-01)."
        )

    def test_filter_perfil_desconocido_devuelve_solo_productos_sin_allowed_restrictivo(
        self, universe
    ):
        """
        Un perfil no listado en allowed_profiles de los productos restrictivos
        no debería pasar para esos productos. Esto valida que el filtro NO
        admita perfiles arbitrarios para productos que declaran allowed_profiles.
        """
        records = universe.filter_for_profile("desconocido-xyz")
        tickers = {r.ticker for r in records}
        # AGG no tiene a "desconocido-xyz" en allowed_profiles → no pasa
        assert "AGG" not in tickers
        assert "VTI" not in tickers


# ── 6. Watchlist ──────────────────────────────────────────────────────────


class TestWatchlist:
    def test_watchlist_pasa_para_perfil_permitido(self, universe):
        records = universe.filter_for_profile("agresivo")
        arkk = next((r for r in records if r.ticker == "ARKK"), None)
        assert arkk is not None
        assert arkk.status == ProductGovernanceStatus.WATCHLIST

    def test_helper_is_watchlist_funciona(self, universe):
        records = universe.filter_for_profile("agresivo")
        watchlist_tickers = [r.ticker for r in records if is_watchlist(r)]
        assert "ARKK" in watchlist_tickers

    def test_watchlist_aparece_con_reason_code_o_notas(self, universe):
        arkk = universe.get("ARKK")
        assert arkk is not None
        assert arkk.notes  # tiene al menos una nota
        # ARKK en el fixture trae reason_code GOV_006
        assert arkk.reason_code == "GOV_006"


# ── 7. Exclusion report ───────────────────────────────────────────────────


class TestExclusionReport:
    def test_report_incluye_ticker_status_reason(self, universe):
        report = universe.exclusion_report_for_profile("conservador")
        assert len(report) > 0
        for entry in report:
            assert "ticker" in entry
            assert "status" in entry
            assert "reason" in entry
            assert "reason_code" in entry
            assert "notes" in entry
            assert isinstance(entry["reason"], str)
            assert entry["reason"].strip()  # razón no vacía

    def test_report_para_conservador_incluye_gbtc_prohibited(self, universe):
        report = universe.exclusion_report_for_profile("conservador")
        gbtc = next((e for e in report if e["ticker"] == "GBTC"), None)
        assert gbtc is not None
        assert gbtc["status"] == "prohibited"
        assert "prohibido" in gbtc["reason"].lower()

    def test_report_para_conservador_incluye_xle_suspended(self, universe):
        report = universe.exclusion_report_for_profile("conservador")
        xle = next((e for e in report if e["ticker"] == "XLE"), None)
        assert xle is not None
        assert xle["status"] == "temporarily_suspended"
        assert "suspendido" in xle["reason"].lower()

    def test_report_para_conservador_incluye_tlt_restricted(self, universe):
        report = universe.exclusion_report_for_profile("conservador")
        tlt = next((e for e in report if e["ticker"] == "TLT"), None)
        assert tlt is not None
        assert tlt["status"] == "restricted"
        assert "restrict" in tlt["reason"].lower()

    def test_report_para_moderado_incluye_stale_por_review_vencida(self, universe):
        report = universe.exclusion_report_for_profile("moderado")
        stale = next((e for e in report if e["ticker"] == "STALE"), None)
        assert stale is not None
        assert "vencida" in stale["reason"].lower() or "review" in stale["reason"].lower()

    def test_report_para_moderado_incluye_vea_por_restricted_profile(self, universe):
        # VEA tiene a moderado-defensivo en restricted, no a moderado.
        # Pero VEA permite "moderado" en allowed_profiles, así que NO debería
        # estar en el report para moderado.
        report = universe.exclusion_report_for_profile("moderado")
        vea = next((e for e in report if e["ticker"] == "VEA"), None)
        assert vea is None, "VEA debería estar permitido para 'moderado'."

    def test_report_para_moderado_defensivo_incluye_vea(self, universe):
        report = universe.exclusion_report_for_profile("moderado-defensivo")
        vea = next((e for e in report if e["ticker"] == "VEA"), None)
        assert vea is not None
        assert "restricted_profiles" in vea["reason"]

    def test_report_no_incluye_productos_que_pasan(self, universe):
        report = universe.exclusion_report_for_profile("agresivo")
        tickers_excluidos = {e["ticker"] for e in report}
        # ARKK pasa para agresivo (watchlist + allowed)
        assert "ARKK" not in tickers_excluidos
        # BIL pasa para todos
        assert "BIL" not in tickers_excluidos

    def test_report_profile_vacio_lanza_error(self, universe):
        with pytest.raises(ValueError, match="profile_name"):
            universe.exclusion_report_for_profile("")


# ── 8. Consistencia: filter + report = universo total ────────────────────


class TestConsistencia:
    def test_pasados_mas_excluidos_igual_universo_total(self, universe):
        """Todo producto del universo: o pasa o está en el report. No ambos, no ninguno."""
        for profile in ["conservador", "moderado", "agresivo"]:
            pasados = {r.ticker for r in universe.filter_for_profile(profile)}
            excluidos = {e["ticker"] for e in universe.exclusion_report_for_profile(profile)}
            total = {r.ticker for r in universe.all_records()}

            assert pasados.isdisjoint(excluidos), (
                f"Hay overlap entre pasados y excluidos para {profile!r}: "
                f"{pasados & excluidos}"
            )
            assert pasados | excluidos == total, (
                f"pasados + excluidos != total para {profile!r}.\n"
                f"Faltan: {total - (pasados | excluidos)}"
            )


# ── 9. review_due_date ────────────────────────────────────────────────────


class TestReviewDueDate:
    def test_review_due_date_none_no_bloquea(self):
        r = ProductGovernanceRecord(
            ticker="X",
            name="X product",
            instrument_type="bond_etf",
            status=ProductGovernanceStatus.APPROVED,
            review_due_date=None,
        )
        assert r.is_review_overdue() is False

    def test_review_due_date_pasada_bloquea(self):
        r = ProductGovernanceRecord(
            ticker="X",
            name="X product",
            instrument_type="bond_etf",
            status=ProductGovernanceStatus.APPROVED,
            review_due_date="2000-01-01",
        )
        assert r.is_review_overdue() is True

    def test_review_due_date_futura_no_bloquea(self):
        r = ProductGovernanceRecord(
            ticker="X",
            name="X product",
            instrument_type="bond_etf",
            status=ProductGovernanceStatus.APPROVED,
            review_due_date="2099-12-31",
        )
        assert r.is_review_overdue() is False

    def test_review_due_date_invalido_lanza_error_al_evaluar(self):
        r = ProductGovernanceRecord(
            ticker="X",
            name="X product",
            instrument_type="bond_etf",
            status=ProductGovernanceStatus.APPROVED,
            review_due_date="no-es-una-fecha",
        )
        with pytest.raises(ValueError, match="review_due_date"):
            r.is_review_overdue()
