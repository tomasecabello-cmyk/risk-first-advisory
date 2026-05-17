"""
Tests de MarketDataSnapshot y MockMarketDataProvider.

Cubre:
    - Validaciones del dataclass.
    - Propiedades is_complete e is_usable.
    - Carga desde YAML (válida e inválida).
    - Consultas: contains, get_snapshot, get_many, missing_tickers.
    - Copia defensiva de all_snapshots.
"""

import json
from pathlib import Path

import pytest

from risk_first_advisory.data_layer.market_data import (
    CRITICAL_FIELDS,
    MarketDataSnapshot,
    MockMarketDataProvider,
)


FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "market_data"
    / "m1_market_data.yaml"
)


@pytest.fixture
def provider() -> MockMarketDataProvider:
    return MockMarketDataProvider.from_yaml(FIXTURE_PATH)


# Helper para construir snapshots válidos en tests
def _make_snapshot(**overrides) -> MarketDataSnapshot:
    defaults = dict(
        ticker="TEST",
        expected_return_annual=0.05,
        volatility_annual=0.10,
        liquidity_score=0.90,
        expense_ratio=0.001,
        duration=None,
        asset_class="equity",
        currency="USD",
        stale=False,
        missing_fields=[],
        notes=[],
    )
    defaults.update(overrides)
    return MarketDataSnapshot(**defaults)


# ── 1. Validaciones del dataclass ─────────────────────────────────────────


class TestSnapshotValidacion:
    def test_snapshot_valido_se_construye(self):
        s = _make_snapshot()
        assert s.ticker == "TEST"
        assert s.asset_class == "equity"

    def test_ticker_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="ticker"):
            _make_snapshot(ticker="")

    def test_ticker_solo_espacios_lanza_error(self):
        with pytest.raises(ValueError, match="ticker"):
            _make_snapshot(ticker="   ")

    def test_expected_return_fuera_de_rango_superior_lanza_error(self):
        with pytest.raises(ValueError, match="expected_return_annual"):
            _make_snapshot(expected_return_annual=1.5)

    def test_expected_return_fuera_de_rango_inferior_lanza_error(self):
        with pytest.raises(ValueError, match="expected_return_annual"):
            _make_snapshot(expected_return_annual=-1.5)

    def test_expected_return_no_numerico_lanza_error(self):
        with pytest.raises(ValueError, match="expected_return_annual"):
            _make_snapshot(expected_return_annual="0.05")  # type: ignore[arg-type]

    def test_volatility_negativa_lanza_error(self):
        with pytest.raises(ValueError, match="volatility_annual"):
            _make_snapshot(volatility_annual=-0.01)

    def test_volatility_cero_es_valida(self):
        s = _make_snapshot(volatility_annual=0.0)
        assert s.volatility_annual == 0.0

    def test_liquidity_score_fuera_de_rango_lanza_error(self):
        with pytest.raises(ValueError, match="liquidity_score"):
            _make_snapshot(liquidity_score=1.5)

    def test_liquidity_score_negativo_lanza_error(self):
        with pytest.raises(ValueError, match="liquidity_score"):
            _make_snapshot(liquidity_score=-0.01)

    def test_expense_ratio_negativo_lanza_error(self):
        with pytest.raises(ValueError, match="expense_ratio"):
            _make_snapshot(expense_ratio=-0.001)

    def test_duration_negativa_lanza_error(self):
        with pytest.raises(ValueError, match="duration"):
            _make_snapshot(duration=-1.0)

    def test_duration_none_es_valida(self):
        s = _make_snapshot(duration=None)
        assert s.duration is None

    def test_duration_cero_es_valida(self):
        s = _make_snapshot(duration=0.0)
        assert s.duration == 0.0

    def test_asset_class_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="asset_class"):
            _make_snapshot(asset_class="")

    def test_currency_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="currency"):
            _make_snapshot(currency="")

    def test_missing_fields_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="missing_fields"):
            _make_snapshot(missing_fields="expected_return")  # type: ignore[arg-type]

    def test_notes_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="notes"):
            _make_snapshot(notes="una nota")  # type: ignore[arg-type]

    def test_stale_no_bool_lanza_error(self):
        with pytest.raises(ValueError, match="stale"):
            _make_snapshot(stale="true")  # type: ignore[arg-type]


# ── 2. is_complete e is_usable ────────────────────────────────────────────


class TestProperties:
    def test_is_complete_true_para_snapshot_completo(self):
        s = _make_snapshot()
        assert s.is_complete is True

    def test_is_complete_false_si_stale(self):
        s = _make_snapshot(stale=True)
        assert s.is_complete is False

    def test_is_complete_false_si_missing_fields(self):
        s = _make_snapshot(missing_fields=["expected_return_annual"])
        assert s.is_complete is False

    def test_is_complete_false_si_falta_campo_no_critico(self):
        s = _make_snapshot(missing_fields=["duration"])
        assert s.is_complete is False

    def test_is_usable_true_para_snapshot_completo(self):
        s = _make_snapshot()
        assert s.is_usable is True

    def test_is_usable_false_si_stale(self):
        s = _make_snapshot(stale=True)
        assert s.is_usable is False

    def test_is_usable_false_si_falta_campo_critico(self):
        s = _make_snapshot(missing_fields=["expected_return_annual"])
        assert s.is_usable is False

    def test_is_usable_false_si_falta_volatility(self):
        s = _make_snapshot(missing_fields=["volatility_annual"])
        assert s.is_usable is False

    def test_is_usable_false_si_falta_liquidity(self):
        s = _make_snapshot(missing_fields=["liquidity_score"])
        assert s.is_usable is False

    def test_is_usable_false_si_falta_asset_class(self):
        s = _make_snapshot(missing_fields=["asset_class"])
        assert s.is_usable is False

    def test_is_usable_false_si_falta_currency(self):
        s = _make_snapshot(missing_fields=["currency"])
        assert s.is_usable is False

    def test_is_usable_true_si_solo_falta_campo_no_critico(self):
        # duration es no-crítico para equity
        s = _make_snapshot(missing_fields=["duration"])
        assert s.is_usable is True

    def test_is_usable_true_si_solo_falta_expense_ratio(self):
        s = _make_snapshot(missing_fields=["expense_ratio"])
        assert s.is_usable is True

    def test_is_usable_false_si_stale_y_faltan_no_criticos(self):
        s = _make_snapshot(stale=True, missing_fields=["duration"])
        assert s.is_usable is False

    def test_critical_fields_conjunto_esperado(self):
        assert CRITICAL_FIELDS == frozenset(
            {
                "expected_return_annual",
                "volatility_annual",
                "liquidity_score",
                "asset_class",
                "currency",
            }
        )


# ── 3. to_dict y serialización ────────────────────────────────────────────


class TestSerializacion:
    def test_to_dict_es_json_serializable(self):
        s = _make_snapshot(
            ticker="AGG",
            duration=6.2,
            asset_class="bond",
            notes=["nota1"],
        )
        payload = json.dumps(s.to_dict())
        parsed = json.loads(payload)
        assert parsed["ticker"] == "AGG"
        assert parsed["duration"] == 6.2
        assert parsed["notes"] == ["nota1"]

    def test_to_dict_contiene_todos_los_campos(self):
        s = _make_snapshot()
        d = s.to_dict()
        expected_keys = {
            "ticker",
            "expected_return_annual",
            "volatility_annual",
            "liquidity_score",
            "expense_ratio",
            "duration",
            "asset_class",
            "currency",
            "stale",
            "missing_fields",
            "notes",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_duration_none_se_serializa(self):
        s = _make_snapshot(duration=None)
        d = s.to_dict()
        assert d["duration"] is None


# ── 4. Carga desde YAML ───────────────────────────────────────────────────


class TestCargaYAML:
    def test_fixture_existe(self):
        assert FIXTURE_PATH.exists(), f"Fixture no encontrado: {FIXTURE_PATH}"

    def test_carga_yaml_correctamente(self, provider):
        assert isinstance(provider, MockMarketDataProvider)
        assert len(provider) >= 12

    def test_yaml_inexistente_lanza_filenotfounderror(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            MockMarketDataProvider.from_yaml(tmp_path / "missing.yaml")

    def test_yaml_invalido_lanza_value_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("snapshots: : invalid : yaml", encoding="utf-8")
        with pytest.raises(ValueError, match="YAML inválido"):
            MockMarketDataProvider.from_yaml(bad)

    def test_yaml_raiz_no_mapping_lanza_error(self, tmp_path):
        bad = tmp_path / "list_root.yaml"
        bad.write_text("- ticker: AGG\n", encoding="utf-8")
        with pytest.raises(ValueError, match="mapping"):
            MockMarketDataProvider.from_yaml(bad)

    def test_yaml_sin_snapshots_lanza_error(self, tmp_path):
        bad = tmp_path / "no_snapshots.yaml"
        bad.write_text("otra_clave: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="snapshots"):
            MockMarketDataProvider.from_yaml(bad)

    def test_yaml_snapshots_no_lista_lanza_error(self, tmp_path):
        bad = tmp_path / "wrong_type.yaml"
        bad.write_text("snapshots: not_a_list\n", encoding="utf-8")
        with pytest.raises(ValueError, match="lista"):
            MockMarketDataProvider.from_yaml(bad)

    def test_yaml_falta_campo_critico_lanza_error(self, tmp_path):
        bad = tmp_path / "missing_field.yaml"
        bad.write_text(
            "snapshots:\n"
            "  - ticker: X\n"
            "    expected_return_annual: 0.05\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="YAML inválido"):
            MockMarketDataProvider.from_yaml(bad)

    def test_yaml_ticker_duplicado_lanza_error(self, tmp_path):
        bad = tmp_path / "dup.yaml"
        bad.write_text(
            "snapshots:\n"
            "  - ticker: AGG\n"
            "    expected_return_annual: 0.045\n"
            "    volatility_annual: 0.055\n"
            "    liquidity_score: 0.95\n"
            "    expense_ratio: 0.0003\n"
            "    duration: 6.0\n"
            "    asset_class: bond\n"
            "    currency: USD\n"
            "  - ticker: AGG\n"
            "    expected_return_annual: 0.044\n"
            "    volatility_annual: 0.054\n"
            "    liquidity_score: 0.94\n"
            "    expense_ratio: 0.0003\n"
            "    duration: 6.0\n"
            "    asset_class: bond\n"
            "    currency: USD\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="duplicado"):
            MockMarketDataProvider.from_yaml(bad)

    def test_yaml_valor_invalido_se_propaga_con_contexto(self, tmp_path):
        # volatility negativa debería disparar la validación del dataclass
        bad = tmp_path / "neg_vol.yaml"
        bad.write_text(
            "snapshots:\n"
            "  - ticker: X\n"
            "    expected_return_annual: 0.05\n"
            "    volatility_annual: -0.10\n"
            "    liquidity_score: 0.9\n"
            "    expense_ratio: 0.001\n"
            "    duration: null\n"
            "    asset_class: equity\n"
            "    currency: USD\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="YAML inválido"):
            MockMarketDataProvider.from_yaml(bad)


# ── 5. Consultas básicas ──────────────────────────────────────────────────


class TestConsultas:
    def test_contains_devuelve_true_para_ticker_existente(self, provider):
        assert provider.contains("AGG") is True
        assert "VT" in provider

    def test_contains_devuelve_false_para_ticker_inexistente(self, provider):
        assert provider.contains("UNKNOWN_TICKER") is False
        assert "UNKNOWN_TICKER" not in provider

    def test_get_snapshot_devuelve_market_data_snapshot(self, provider):
        s = provider.get_snapshot("AGG")
        assert s is not None
        assert isinstance(s, MarketDataSnapshot)
        assert s.ticker == "AGG"
        assert s.asset_class == "bond"

    def test_get_snapshot_devuelve_none_para_unknown(self, provider):
        assert provider.get_snapshot("UNKNOWN_TICKER") is None

    def test_all_snapshots_devuelve_lista(self, provider):
        items = provider.all_snapshots()
        assert isinstance(items, list)
        assert len(items) >= 12
        assert all(isinstance(s, MarketDataSnapshot) for s in items)

    def test_all_snapshots_devuelve_copia_segura(self, provider):
        items = provider.all_snapshots()
        initial_len = len(items)
        items.clear()
        assert len(provider.all_snapshots()) == initial_len


# ── 6. get_many y missing_tickers ─────────────────────────────────────────


class TestGetManyYMissing:
    def test_get_many_devuelve_orden_solicitado(self, provider):
        result = provider.get_many(["VT", "AGG", "BIL"])
        assert [s.ticker for s in result] == ["VT", "AGG", "BIL"]

    def test_get_many_omite_tickers_inexistentes(self, provider):
        result = provider.get_many(["AGG", "NO_EXISTE", "VT"])
        assert [s.ticker for s in result] == ["AGG", "VT"]

    def test_get_many_lista_vacia(self, provider):
        assert provider.get_many([]) == []

    def test_missing_tickers_devuelve_los_no_encontrados(self, provider):
        missing = provider.missing_tickers(["AGG", "NO_EXISTE", "VT", "TAMPOCO"])
        assert missing == ["NO_EXISTE", "TAMPOCO"]

    def test_missing_tickers_vacio_si_todos_existen(self, provider):
        assert provider.missing_tickers(["AGG", "VT", "BIL"]) == []

    def test_missing_tickers_lista_vacia(self, provider):
        assert provider.missing_tickers([]) == []


# ── 7. Snapshots de fixture ───────────────────────────────────────────────


class TestSnapshotsDeFixture:
    def test_sgov_es_cash_con_baja_volatilidad(self, provider):
        s = provider.get_snapshot("SGOV")
        assert s.asset_class == "cash"
        assert s.volatility_annual < 0.02
        assert 0.02 <= s.expected_return_annual <= 0.05

    def test_agg_es_bond_con_duration_positiva(self, provider):
        s = provider.get_snapshot("AGG")
        assert s.asset_class == "bond"
        assert s.duration is not None
        assert s.duration > 0.0

    def test_vt_es_equity_sin_duration(self, provider):
        s = provider.get_snapshot("VT")
        assert s.asset_class == "equity"
        assert s.duration is None

    def test_arkk_tiene_volatilidad_alta(self, provider):
        s = provider.get_snapshot("ARKK")
        assert s.volatility_annual > 0.20

    def test_tlt_tiene_duration_extrema(self, provider):
        s = provider.get_snapshot("TLT")
        assert s.duration is not None
        assert s.duration > 10.0

    def test_stale_tiene_stale_true(self, provider):
        s = provider.get_snapshot("STALE")
        assert s.stale is True
        assert s.is_usable is False
        assert s.is_complete is False

    def test_bad_missing_tiene_missing_fields(self, provider):
        s = provider.get_snapshot("BAD_MISSING")
        assert len(s.missing_fields) > 0
        assert s.is_usable is False
        assert s.is_complete is False

    def test_snapshots_normales_son_usables(self, provider):
        for ticker in ["SGOV", "BIL", "AGG", "BND", "VT", "VEA", "HYG",
                       "ARKK", "XLE", "TLT"]:
            s = provider.get_snapshot(ticker)
            assert s.is_usable is True, f"{ticker} debería ser usable"
            assert s.is_complete is True, f"{ticker} debería estar completo"


# ── 8. Utilidades ─────────────────────────────────────────────────────────


class TestUtilidades:
    def test_len_provider(self, provider):
        assert len(provider) >= 12