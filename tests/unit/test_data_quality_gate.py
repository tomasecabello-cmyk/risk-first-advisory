"""
Tests de DataQualityGate y DataQualityResult.

Cubre:
    - Reglas individuales (stale, missing critical, missing non-critical,
      low liquidity, zero volatility para no-cash).
    - Combinaciones (FAIL + WARNING → FAIL, acumulación de reason_codes).
    - evaluate_many preserva orden.
    - Filtros passed/failed/warning.
    - Validaciones del dataclass DataQualityResult.
    - Serialización JSON.
"""

import json

import pytest

from risk_first_advisory.data_layer.data_quality import (
    LOW_LIQUIDITY_THRESHOLD,
    REASON_CRITICAL_FIELD_MISSING,
    REASON_DATA_STALE,
    REASON_LOW_LIQUIDITY,
    REASON_NON_CRITICAL_FIELD_MISSING,
    REASON_ZERO_VOLATILITY_NON_CASH,
    DataQualityGate,
    DataQualityResult,
    DataQualityStatus,
)
from risk_first_advisory.data_layer.market_data import MarketDataSnapshot


# Helper para construir snapshots controlados
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


@pytest.fixture
def gate() -> DataQualityGate:
    return DataQualityGate()


# ── 1. Camino feliz ───────────────────────────────────────────────────────


class TestSnapshotCompleto:
    def test_snapshot_completo_pasa(self, gate):
        s = _make_snapshot()
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.PASS
        assert r.is_usable is True
        assert r.failed_fields == []
        assert r.warnings == []
        assert r.reason_codes == []

    def test_snapshot_cash_con_volatilidad_cero_pasa(self, gate):
        # Cash con vol 0 es esperado: NO debe disparar warning.
        s = _make_snapshot(asset_class="cash", volatility_annual=0.0)
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.PASS
        assert REASON_ZERO_VOLATILITY_NON_CASH not in r.reason_codes


# ── 2. Stale → FAIL ───────────────────────────────────────────────────────


class TestStale:
    def test_stale_falla(self, gate):
        s = _make_snapshot(stale=True)
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.FAIL
        assert r.is_usable is False
        assert REASON_DATA_STALE in r.reason_codes
        assert r.is_failed is True


# ── 3. Campos críticos faltantes → FAIL ───────────────────────────────────


class TestMissingCritical:
    def test_missing_expected_return_falla(self, gate):
        s = _make_snapshot(missing_fields=["expected_return_annual"])
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.FAIL
        assert r.is_usable is False
        assert REASON_CRITICAL_FIELD_MISSING in r.reason_codes
        assert "expected_return_annual" in r.failed_fields

    def test_missing_volatility_falla(self, gate):
        s = _make_snapshot(missing_fields=["volatility_annual"])
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.FAIL
        assert "volatility_annual" in r.failed_fields

    def test_missing_liquidity_score_falla(self, gate):
        s = _make_snapshot(missing_fields=["liquidity_score"])
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.FAIL
        assert "liquidity_score" in r.failed_fields

    def test_missing_asset_class_falla(self, gate):
        s = _make_snapshot(missing_fields=["asset_class"])
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.FAIL
        assert "asset_class" in r.failed_fields

    def test_missing_currency_falla(self, gate):
        s = _make_snapshot(missing_fields=["currency"])
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.FAIL
        assert "currency" in r.failed_fields

    def test_multiples_criticos_acumulan_en_failed_fields(self, gate):
        s = _make_snapshot(
            missing_fields=["expected_return_annual", "volatility_annual"]
        )
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.FAIL
        assert set(r.failed_fields) == {
            "expected_return_annual",
            "volatility_annual",
        }


# ── 4. Campos no críticos faltantes → WARNING ─────────────────────────────


class TestMissingNonCritical:
    def test_missing_expense_ratio_es_warning(self, gate):
        s = _make_snapshot(missing_fields=["expense_ratio"])
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.WARNING
        assert r.is_usable is True
        assert REASON_NON_CRITICAL_FIELD_MISSING in r.reason_codes
        assert r.failed_fields == []

    def test_missing_duration_es_warning(self, gate):
        s = _make_snapshot(missing_fields=["duration"])
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.WARNING
        assert r.is_usable is True
        assert REASON_NON_CRITICAL_FIELD_MISSING in r.reason_codes


# ── 5. Low liquidity → WARNING ────────────────────────────────────────────


class TestLowLiquidity:
    def test_low_liquidity_genera_warning(self, gate):
        s = _make_snapshot(liquidity_score=0.10)
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.WARNING
        assert r.is_usable is True
        assert REASON_LOW_LIQUIDITY in r.reason_codes

    def test_liquidity_en_umbral_no_dispara(self, gate):
        # Umbral 0.20; el criterio es `< 0.20`, así que 0.20 exacto no dispara.
        s = _make_snapshot(liquidity_score=LOW_LIQUIDITY_THRESHOLD)
        r = gate.evaluate(s)
        assert REASON_LOW_LIQUIDITY not in r.reason_codes

    def test_liquidity_apenas_debajo_dispara(self, gate):
        s = _make_snapshot(liquidity_score=LOW_LIQUIDITY_THRESHOLD - 0.01)
        r = gate.evaluate(s)
        assert REASON_LOW_LIQUIDITY in r.reason_codes


# ── 6. Zero volatility para no-cash → WARNING ─────────────────────────────


class TestZeroVolatilityNonCash:
    def test_zero_volatility_equity_dispara_warning(self, gate):
        s = _make_snapshot(asset_class="equity", volatility_annual=0.0)
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.WARNING
        assert REASON_ZERO_VOLATILITY_NON_CASH in r.reason_codes

    def test_zero_volatility_bond_dispara_warning(self, gate):
        s = _make_snapshot(asset_class="bond", volatility_annual=0.0)
        r = gate.evaluate(s)
        assert REASON_ZERO_VOLATILITY_NON_CASH in r.reason_codes

    def test_zero_volatility_cash_no_dispara_warning(self, gate):
        s = _make_snapshot(asset_class="cash", volatility_annual=0.0)
        r = gate.evaluate(s)
        assert REASON_ZERO_VOLATILITY_NON_CASH not in r.reason_codes
        assert r.status == DataQualityStatus.PASS


# ── 7. Combinaciones FAIL + WARNING ───────────────────────────────────────


class TestCombinacionesFailWarning:
    def test_fail_y_warning_simultaneos_dan_fail(self, gate):
        s = _make_snapshot(
            missing_fields=["expected_return_annual", "expense_ratio"],
        )
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.FAIL
        assert r.is_usable is False
        assert REASON_CRITICAL_FIELD_MISSING in r.reason_codes
        assert REASON_NON_CRITICAL_FIELD_MISSING in r.reason_codes

    def test_stale_mas_low_liquidity_da_fail(self, gate):
        s = _make_snapshot(stale=True, liquidity_score=0.05)
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.FAIL
        assert r.is_usable is False
        assert REASON_DATA_STALE in r.reason_codes
        assert REASON_LOW_LIQUIDITY in r.reason_codes

    def test_reason_codes_acumulan_multiples_razones(self, gate):
        s = _make_snapshot(
            stale=True,
            missing_fields=["expected_return_annual", "duration"],
            liquidity_score=0.10,
            asset_class="equity",
            volatility_annual=0.0,
        )
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.FAIL
        # Las 5 reglas activas
        assert REASON_DATA_STALE in r.reason_codes
        assert REASON_CRITICAL_FIELD_MISSING in r.reason_codes
        assert REASON_NON_CRITICAL_FIELD_MISSING in r.reason_codes
        assert REASON_LOW_LIQUIDITY in r.reason_codes
        assert REASON_ZERO_VOLATILITY_NON_CASH in r.reason_codes
        assert len(r.reason_codes) == 5

    def test_solo_warnings_da_warning(self, gate):
        s = _make_snapshot(
            missing_fields=["duration"],
            liquidity_score=0.10,
        )
        r = gate.evaluate(s)
        assert r.status == DataQualityStatus.WARNING
        assert r.is_usable is True
        assert REASON_NON_CRITICAL_FIELD_MISSING in r.reason_codes
        assert REASON_LOW_LIQUIDITY in r.reason_codes


# ── 8. evaluate_many ──────────────────────────────────────────────────────


class TestEvaluateMany:
    def test_evaluate_many_preserva_orden(self, gate):
        s1 = _make_snapshot(ticker="AAA")
        s2 = _make_snapshot(ticker="BBB", stale=True)
        s3 = _make_snapshot(ticker="CCC", liquidity_score=0.10)
        results = gate.evaluate_many([s1, s2, s3])
        assert [r.ticker for r in results] == ["AAA", "BBB", "CCC"]
        assert results[0].status == DataQualityStatus.PASS
        assert results[1].status == DataQualityStatus.FAIL
        assert results[2].status == DataQualityStatus.WARNING

    def test_evaluate_many_lista_vacia(self, gate):
        assert gate.evaluate_many([]) == []


# ── 9. Filtros passed/failed/warning ─────────────────────────────────────


class TestFiltros:
    @pytest.fixture
    def mixed_results(self, gate) -> list[DataQualityResult]:
        return gate.evaluate_many([
            _make_snapshot(ticker="PASS_A"),
            _make_snapshot(ticker="FAIL_A", stale=True),
            _make_snapshot(ticker="WARN_A", liquidity_score=0.10),
            _make_snapshot(ticker="PASS_B"),
            _make_snapshot(
                ticker="FAIL_B",
                missing_fields=["expected_return_annual"],
            ),
            _make_snapshot(
                ticker="WARN_B",
                missing_fields=["duration"],
            ),
        ])

    def test_passed_devuelve_tickers_pass(self, gate, mixed_results):
        assert gate.passed(mixed_results) == ["PASS_A", "PASS_B"]

    def test_failed_devuelve_tickers_fail(self, gate, mixed_results):
        assert gate.failed(mixed_results) == ["FAIL_A", "FAIL_B"]

    def test_warning_devuelve_tickers_warning(self, gate, mixed_results):
        assert gate.warning(mixed_results) == ["WARN_A", "WARN_B"]

    def test_passed_failed_warning_disjuntos(self, gate, mixed_results):
        passed = set(gate.passed(mixed_results))
        failed = set(gate.failed(mixed_results))
        warning = set(gate.warning(mixed_results))
        assert passed.isdisjoint(failed)
        assert passed.isdisjoint(warning)
        assert failed.isdisjoint(warning)
        # La unión cubre todos los resultados
        total = passed | failed | warning
        assert total == {r.ticker for r in mixed_results}

    def test_filtros_sobre_lista_vacia(self, gate):
        assert gate.passed([]) == []
        assert gate.failed([]) == []
        assert gate.warning([]) == []


# ── 10. DataQualityResult: serialización y propiedades ────────────────────


class TestResultDataclass:
    def test_to_dict_es_json_serializable(self, gate):
        s = _make_snapshot(stale=True, missing_fields=["duration"])
        r = gate.evaluate(s)
        payload = json.dumps(r.to_dict())
        parsed = json.loads(payload)
        assert parsed["ticker"] == "TEST"
        assert parsed["status"] == "fail"
        assert parsed["is_usable"] is False
        assert REASON_DATA_STALE in parsed["reason_codes"]

    def test_to_dict_contiene_todos_los_campos(self):
        r = DataQualityResult(
            ticker="X",
            status=DataQualityStatus.PASS,
            is_usable=True,
        )
        d = r.to_dict()
        expected_keys = {
            "ticker",
            "status",
            "is_usable",
            "failed_fields",
            "warnings",
            "reason_codes",
            "notes",
        }
        assert set(d.keys()) == expected_keys

    def test_has_warnings_true(self):
        r = DataQualityResult(
            ticker="X",
            status=DataQualityStatus.WARNING,
            is_usable=True,
            warnings=["algo"],
        )
        assert r.has_warnings is True

    def test_has_warnings_false(self):
        r = DataQualityResult(
            ticker="X",
            status=DataQualityStatus.PASS,
            is_usable=True,
        )
        assert r.has_warnings is False

    def test_is_failed_true(self):
        r = DataQualityResult(
            ticker="X",
            status=DataQualityStatus.FAIL,
            is_usable=False,
        )
        assert r.is_failed is True

    def test_is_failed_false_para_pass(self):
        r = DataQualityResult(
            ticker="X",
            status=DataQualityStatus.PASS,
            is_usable=True,
        )
        assert r.is_failed is False

    def test_is_failed_false_para_warning(self):
        r = DataQualityResult(
            ticker="X",
            status=DataQualityStatus.WARNING,
            is_usable=True,
        )
        assert r.is_failed is False


# ── 11. Validaciones del dataclass ────────────────────────────────────────


class TestValidacionesResult:
    def test_ticker_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="ticker"):
            DataQualityResult(
                ticker="",
                status=DataQualityStatus.PASS,
                is_usable=True,
            )

    def test_ticker_solo_espacios_lanza_error(self):
        with pytest.raises(ValueError, match="ticker"):
            DataQualityResult(
                ticker="   ",
                status=DataQualityStatus.PASS,
                is_usable=True,
            )

    def test_status_no_enum_lanza_error(self):
        with pytest.raises(ValueError, match="status"):
            DataQualityResult(
                ticker="X",
                status="pass",  # type: ignore[arg-type]
                is_usable=True,
            )

    def test_is_usable_no_bool_lanza_error(self):
        with pytest.raises(ValueError, match="is_usable"):
            DataQualityResult(
                ticker="X",
                status=DataQualityStatus.PASS,
                is_usable="true",  # type: ignore[arg-type]
            )

    def test_failed_fields_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="failed_fields"):
            DataQualityResult(
                ticker="X",
                status=DataQualityStatus.PASS,
                is_usable=True,
                failed_fields="foo",  # type: ignore[arg-type]
            )

    def test_warnings_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="warnings"):
            DataQualityResult(
                ticker="X",
                status=DataQualityStatus.PASS,
                is_usable=True,
                warnings="foo",  # type: ignore[arg-type]
            )

    def test_reason_codes_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="reason_codes"):
            DataQualityResult(
                ticker="X",
                status=DataQualityStatus.PASS,
                is_usable=True,
                reason_codes="foo",  # type: ignore[arg-type]
            )

    def test_notes_no_lista_lanza_error(self):
        with pytest.raises(ValueError, match="notes"):
            DataQualityResult(
                ticker="X",
                status=DataQualityStatus.PASS,
                is_usable=True,
                notes="foo",  # type: ignore[arg-type]
            )


# ── 12. Entrada inválida en evaluate ──────────────────────────────────────


class TestEvaluateInputs:
    def test_evaluate_con_tipo_invalido_lanza_error(self, gate):
        with pytest.raises(ValueError, match="MarketDataSnapshot"):
            gate.evaluate("no soy un snapshot")  # type: ignore[arg-type]

    def test_evaluate_con_none_lanza_error(self, gate):
        with pytest.raises(ValueError, match="MarketDataSnapshot"):
            gate.evaluate(None)  # type: ignore[arg-type]