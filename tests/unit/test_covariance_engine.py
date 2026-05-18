"""
Tests para CovarianceEngine y CovarianceMatrix.

Cubre todos los requisitos funcionales del spec:
    - Validaciones de CovarianceMatrix
    - Errores de build (lista vacía, duplicados, snapshots no usables)
    - Propiedades matriciales (NxN, simetría, diagonal)
    - Correlaciones mock por asset_class
    - Accesores get_covariance / get_correlation
    - Serialización to_dict
"""

import json
import pytest

from risk_first_advisory.data_layer.market_data import MarketDataSnapshot
from risk_first_advisory.data_layer.covariance import (
    CovarianceEngine,
    CovarianceMatrix,
)


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------

def _snap(
    ticker: str,
    asset_class: str,
    vol: float = 0.10,
    stale: bool = False,
    missing_fields: list[str] | None = None,
) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        ticker=ticker,
        expected_return_annual=0.05,
        volatility_annual=vol,
        liquidity_score=0.8,
        expense_ratio=0.001,
        duration=None,
        asset_class=asset_class,
        currency="USD",
        stale=stale,
        missing_fields=missing_fields or [],
    )


# ---------------------------------------------------------------------------
# Tests de CovarianceEngine.build — errores de entrada
# ---------------------------------------------------------------------------

class TestCovarianceEngineBuildErrors:
    def test_empty_list_raises_value_error(self):
        engine = CovarianceEngine()
        with pytest.raises(ValueError, match="vacía"):
            engine.build([])

    def test_duplicate_ticker_raises_value_error(self):
        engine = CovarianceEngine()
        snaps = [
            _snap("SPY", "equity"),
            _snap("SPY", "equity"),
        ]
        with pytest.raises(ValueError, match="duplicado"):
            engine.build(snaps)

    def test_stale_snapshot_raises_value_error(self):
        engine = CovarianceEngine()
        snaps = [_snap("SPY", "equity", stale=True)]
        with pytest.raises(ValueError):
            engine.build(snaps)

    def test_non_usable_snapshot_raises_value_error(self):
        """Snapshot con missing critical field no es usable."""
        engine = CovarianceEngine()
        snaps = [
            _snap("SPY", "equity", missing_fields=["volatility_annual"]),
        ]
        with pytest.raises(ValueError):
            engine.build(snaps)


# ---------------------------------------------------------------------------
# Tests de CovarianceEngine.build — propiedades básicas
# ---------------------------------------------------------------------------

class TestCovarianceEngineBuildBasic:
    def setup_method(self):
        self.engine = CovarianceEngine()

    def test_preserves_ticker_order(self):
        snaps = [
            _snap("ZZZ", "cash"),
            _snap("AAA", "equity"),
            _snap("MMM", "bond"),
        ]
        cm = self.engine.build(snaps)
        assert cm.tickers == ["ZZZ", "AAA", "MMM"]

    def test_covariance_is_nxn(self):
        snaps = [_snap("A", "equity"), _snap("B", "bond"), _snap("C", "cash")]
        cm = self.engine.build(snaps)
        n = len(snaps)
        assert len(cm.covariance) == n
        for row in cm.covariance:
            assert len(row) == n

    def test_correlation_is_nxn(self):
        snaps = [_snap("A", "equity"), _snap("B", "bond"), _snap("C", "cash")]
        cm = self.engine.build(snaps)
        n = len(snaps)
        assert len(cm.correlation) == n
        for row in cm.correlation:
            assert len(row) == n

    def test_correlation_diagonal_is_one(self):
        snaps = [_snap("A", "equity"), _snap("B", "bond"), _snap("C", "cash")]
        cm = self.engine.build(snaps)
        for i in range(len(snaps)):
            assert cm.correlation[i][i] == pytest.approx(1.0)

    def test_covariance_diagonal_is_vol_squared(self):
        vols = [0.15, 0.08, 0.20]
        snaps = [
            _snap("A", "equity", vol=vols[0]),
            _snap("B", "bond", vol=vols[1]),
            _snap("C", "cash", vol=vols[2]),
        ]
        cm = self.engine.build(snaps)
        for i, v in enumerate(vols):
            assert cm.covariance[i][i] == pytest.approx(v ** 2)

    def test_covariance_is_symmetric(self):
        snaps = [_snap("A", "equity"), _snap("B", "bond"), _snap("C", "cash")]
        cm = self.engine.build(snaps)
        n = len(snaps)
        for i in range(n):
            for j in range(n):
                assert cm.covariance[i][j] == pytest.approx(cm.covariance[j][i])

    def test_correlation_is_symmetric(self):
        snaps = [_snap("A", "equity"), _snap("B", "bond"), _snap("C", "cash")]
        cm = self.engine.build(snaps)
        n = len(snaps)
        for i in range(n):
            for j in range(n):
                assert cm.correlation[i][j] == pytest.approx(cm.correlation[j][i])

    def test_annualized_is_true(self):
        snaps = [_snap("A", "equity")]
        cm = self.engine.build(snaps)
        assert cm.annualized is True

    def test_single_asset(self):
        snaps = [_snap("SPY", "equity", vol=0.18)]
        cm = self.engine.build(snaps)
        assert cm.tickers == ["SPY"]
        assert cm.correlation[0][0] == pytest.approx(1.0)
        assert cm.covariance[0][0] == pytest.approx(0.18 ** 2)


# ---------------------------------------------------------------------------
# Tests de correlaciones mock por asset_class
# ---------------------------------------------------------------------------

class TestCovarianceEngineMockCorrelations:
    def setup_method(self):
        self.engine = CovarianceEngine()

    def _build_two(self, ac_a: str, ac_b: str) -> tuple[CovarianceMatrix, int, int]:
        snaps = [_snap("A", ac_a), _snap("B", ac_b)]
        cm = self.engine.build(snaps)
        return cm, 0, 1

    def test_cash_equity_correlation_is_zero(self):
        cm, i, j = self._build_two("cash", "equity")
        assert cm.correlation[i][j] == pytest.approx(0.00)

    def test_bond_equity_correlation(self):
        cm, i, j = self._build_two("bond", "equity")
        assert cm.correlation[i][j] == pytest.approx(0.25)

    def test_equity_equity_correlation_between_two_distinct(self):
        snaps = [_snap("SPY", "equity"), _snap("QQQ", "equity")]
        cm = self.engine.build(snaps)
        assert cm.correlation[0][1] == pytest.approx(0.85)

    def test_high_yield_equity_correlation(self):
        cm, i, j = self._build_two("high_yield", "equity")
        assert cm.correlation[i][j] == pytest.approx(0.60)

    def test_thematic_equity_sector_equity_correlation(self):
        cm, i, j = self._build_two("thematic_equity", "sector_equity")
        assert cm.correlation[i][j] == pytest.approx(0.75)

    def test_alias_fixed_income_treated_as_bond(self):
        snaps = [_snap("AGG", "fixed_income"), _snap("SPY", "equity")]
        cm = self.engine.build(snaps)
        assert cm.correlation[0][1] == pytest.approx(0.25)

    def test_alias_global_equity_treated_as_equity(self):
        snaps = [_snap("VT", "global_equity"), _snap("AGG", "bond")]
        cm = self.engine.build(snaps)
        assert cm.correlation[0][1] == pytest.approx(0.25)

    def test_unknown_asset_class_conservative_correlation(self):
        """unknown usa 0.75 contra todo salvo cash (0.0)."""
        snaps = [_snap("X", "weird_exotic"), _snap("SPY", "equity")]
        cm = self.engine.build(snaps)
        assert cm.correlation[0][1] == pytest.approx(0.75)

    def test_unknown_vs_cash_correlation_is_zero(self):
        snaps = [_snap("X", "weird_exotic"), _snap("CASH", "cash")]
        cm = self.engine.build(snaps)
        assert cm.correlation[0][1] == pytest.approx(0.00)

    def test_covariance_formula_cov_eq_corr_times_vols(self):
        """cov[i][j] = corr(i,j) * vol_i * vol_j"""
        vol_a, vol_b = 0.15, 0.08
        snaps = [_snap("A", "equity", vol=vol_a), _snap("B", "bond", vol=vol_b)]
        cm = self.engine.build(snaps)
        expected_corr = 0.25
        expected_cov = expected_corr * vol_a * vol_b
        assert cm.covariance[0][1] == pytest.approx(expected_cov)
        assert cm.covariance[1][0] == pytest.approx(expected_cov)


# ---------------------------------------------------------------------------
# Tests de accesores
# ---------------------------------------------------------------------------

class TestCovarianceMatrixAccessors:
    def setup_method(self):
        engine = CovarianceEngine()
        snaps = [
            _snap("SPY", "equity", vol=0.18),
            _snap("AGG", "bond", vol=0.05),
            _snap("BIL", "cash", vol=0.01),
        ]
        self.cm = engine.build(snaps)

    def test_get_covariance_diagonal(self):
        assert self.cm.get_covariance("SPY", "SPY") == pytest.approx(0.18 ** 2)

    def test_get_covariance_off_diagonal(self):
        expected = 0.25 * 0.18 * 0.05
        assert self.cm.get_covariance("SPY", "AGG") == pytest.approx(expected)

    def test_get_correlation_diagonal(self):
        assert self.cm.get_correlation("AGG", "AGG") == pytest.approx(1.0)

    def test_get_correlation_off_diagonal(self):
        assert self.cm.get_correlation("SPY", "AGG") == pytest.approx(0.25)

    def test_get_covariance_unknown_ticker_raises_key_error(self):
        with pytest.raises(KeyError):
            self.cm.get_covariance("UNKNOWN", "SPY")

    def test_get_correlation_unknown_ticker_raises_key_error(self):
        with pytest.raises(KeyError):
            self.cm.get_correlation("SPY", "UNKNOWN")

    def test_get_covariance_symmetric(self):
        assert self.cm.get_covariance("SPY", "AGG") == pytest.approx(
            self.cm.get_covariance("AGG", "SPY")
        )

    def test_get_correlation_symmetric(self):
        assert self.cm.get_correlation("SPY", "AGG") == pytest.approx(
            self.cm.get_correlation("AGG", "SPY")
        )


# ---------------------------------------------------------------------------
# Tests de to_dict y serialización JSON
# ---------------------------------------------------------------------------

class TestCovarianceMatrixToDict:
    def test_to_dict_is_json_serializable(self):
        engine = CovarianceEngine()
        snaps = [_snap("A", "equity"), _snap("B", "bond")]
        cm = engine.build(snaps)
        d = cm.to_dict()
        serialized = json.dumps(d)
        assert isinstance(serialized, str)

    def test_to_dict_has_expected_keys(self):
        engine = CovarianceEngine()
        snaps = [_snap("A", "equity")]
        cm = engine.build(snaps)
        d = cm.to_dict()
        assert set(d.keys()) == {"tickers", "covariance", "correlation", "annualized", "notes"}

    def test_to_dict_tickers_match(self):
        engine = CovarianceEngine()
        snaps = [_snap("SPY", "equity"), _snap("AGG", "bond")]
        cm = engine.build(snaps)
        d = cm.to_dict()
        assert d["tickers"] == ["SPY", "AGG"]

    def test_to_dict_annualized_is_true(self):
        engine = CovarianceEngine()
        snaps = [_snap("A", "equity")]
        cm = engine.build(snaps)
        d = cm.to_dict()
        assert d["annualized"] is True

    def test_to_dict_notes_is_list(self):
        engine = CovarianceEngine()
        snaps = [_snap("A", "equity")]
        cm = engine.build(snaps)
        d = cm.to_dict()
        assert isinstance(d["notes"], list)


# ---------------------------------------------------------------------------
# Tests de validación directa de CovarianceMatrix
# ---------------------------------------------------------------------------

class TestCovarianceMatrixValidation:
    def _valid_matrix(self):
        """Devuelve args válidos para una matriz 2x2."""
        return dict(
            tickers=["A", "B"],
            covariance=[[0.04, 0.002], [0.002, 0.01]],
            correlation=[[1.0, 0.25], [0.25, 1.0]],
            annualized=True,
            notes=[],
        )

    def test_valid_construction(self):
        cm = CovarianceMatrix(**self._valid_matrix())
        assert cm.tickers == ["A", "B"]

    def test_empty_tickers_raises(self):
        args = self._valid_matrix()
        args["tickers"] = []
        with pytest.raises(ValueError, match="tickers"):
            CovarianceMatrix(**args)

    def test_covariance_wrong_row_count_raises(self):
        args = self._valid_matrix()
        args["covariance"] = [[0.04, 0.002]]  # 1 fila en vez de 2
        with pytest.raises(ValueError):
            CovarianceMatrix(**args)

    def test_covariance_wrong_col_count_raises(self):
        args = self._valid_matrix()
        args["covariance"] = [[0.04], [0.002]]  # columnas incorrectas
        with pytest.raises(ValueError):
            CovarianceMatrix(**args)

    def test_correlation_wrong_dimensions_raises(self):
        args = self._valid_matrix()
        args["correlation"] = [[1.0]]  # 1x1 en vez de 2x2
        with pytest.raises(ValueError):
            CovarianceMatrix(**args)

    def test_correlation_diagonal_not_one_raises(self):
        args = self._valid_matrix()
        args["correlation"] = [[0.99, 0.25], [0.25, 1.0]]
        with pytest.raises(ValueError, match="diagonal"):
            CovarianceMatrix(**args)

    def test_annualized_not_bool_raises(self):
        args = self._valid_matrix()
        args["annualized"] = 1  # int, no bool
        with pytest.raises(ValueError, match="annualized"):
            CovarianceMatrix(**args)

    def test_notes_not_list_raises(self):
        args = self._valid_matrix()
        args["notes"] = "una nota"
        with pytest.raises(ValueError, match="notes"):
            CovarianceMatrix(**args)