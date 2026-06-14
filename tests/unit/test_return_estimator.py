"""
Tests unitarios para ReturnEstimator y ReturnEstimate.

Cobertura:
    1.  estimate sin ESG ni DataQuality resta expense_ratio.
    2.  expense_ratio agrega COST_EXPENSE_RATIO_APPLIED.
    3.  ESG PASS no modifica retorno.
    4.  ESG SOFT_WARNING penaliza según soft_score_adjustment * 0.01.
    5.  ESG UNKNOWN aplica -0.005.
    6.  ESG BLOCKED levanta ValueError.
    7.  DataQuality PASS no modifica retorno.
    8.  DataQuality WARNING aplica -0.0025.
    9.  DataQuality FAIL levanta ValueError.
    10. ESG WARNING + DataQuality WARNING acumulan ajustes.
    11. adjusted_expected_return_annual usa fórmula correcta.
    12. Clipping superior a 1.0 funciona y agrega RETURN_CLIPPED.
    13. Clipping inferior a -1.0 funciona en flujo completo + agrega RETURN_CLIPPED.
    14. estimate_many preserva orden.
    15. estimate_many usa diccionarios por ticker.
    16. estimate_many trata faltantes como None.
    17. estimate_many propaga errores.
    18. ReturnEstimate.to_dict es JSON serializable.
    19. has_penalties funciona.
    20. Validación: ticker vacío.
    21. Validación: raw_expected_return fuera de rango.
    22. Validación: expense_ratio negativa.
    23. Validación: esg_adjustment positivo.
    24. Validación: data_quality_adjustment positivo.
    25. Validación: adjusted_expected_return fuera de rango.
    26. Validación: reason_codes no es lista.
    27. Validación: notes no es lista.
"""

import json

import pytest

from risk_first_advisory.data_layer.data_quality import (
    DataQualityResult,
    DataQualityStatus,
)
from risk_first_advisory.data_layer.market_data import MarketDataSnapshot
from risk_first_advisory.data_layer.return_estimator import (
    DQ_WARNING_PENALTY,
    ESG_SOFT_SCALE,
    ESG_UNKNOWN_PENALTY,
    RC_COST_EXPENSE_RATIO,
    RC_DATA_QUALITY_WARNING,
    RC_ESG_UNKNOWN,
    RC_RETURN_CLIPPED,
    ReturnEstimate,
    ReturnEstimator,
)
from risk_first_advisory.rules_layer.esg_compliance import (
    ESGComplianceResult,
    ESGComplianceStatus,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_snapshot(
    ticker: str = "AAPL",
    raw: float = 0.08,
    expense: float = 0.001,
    volatility: float = 0.15,
    liquidity: float = 0.9,
    asset_class: str = "equity",
    currency: str = "USD",
) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        ticker=ticker,
        expected_return_annual=raw,
        volatility_annual=volatility,
        liquidity_score=liquidity,
        expense_ratio=expense,
        duration=None,
        asset_class=asset_class,
        currency=currency,
    )


def make_esg_pass(ticker: str = "AAPL") -> ESGComplianceResult:
    return ESGComplianceResult(
        ticker=ticker,
        status=ESGComplianceStatus.PASS,
    )


def make_esg_soft_warning(
    ticker: str = "AAPL",
    soft_adj: float = -0.5,
) -> ESGComplianceResult:
    return ESGComplianceResult(
        ticker=ticker,
        status=ESGComplianceStatus.SOFT_WARNING,
        soft_score_adjustment=soft_adj,
        warnings=["Soft preference incumplida."],
    )


def make_esg_unknown(ticker: str = "AAPL") -> ESGComplianceResult:
    return ESGComplianceResult(
        ticker=ticker,
        status=ESGComplianceStatus.UNKNOWN,
        warnings=["Sin metadata ESG."],
    )


def make_esg_blocked(ticker: str = "AAPL") -> ESGComplianceResult:
    return ESGComplianceResult(
        ticker=ticker,
        status=ESGComplianceStatus.BLOCKED,
        blocked_by=["sector=weapons"],
    )


def make_dq_pass(ticker: str = "AAPL") -> DataQualityResult:
    return DataQualityResult(
        ticker=ticker,
        status=DataQualityStatus.PASS,
        is_usable=True,
    )


def make_dq_warning(ticker: str = "AAPL") -> DataQualityResult:
    return DataQualityResult(
        ticker=ticker,
        status=DataQualityStatus.WARNING,
        is_usable=True,
        warnings=["liquidity_score bajo."],
    )


def make_dq_fail(ticker: str = "AAPL") -> DataQualityResult:
    return DataQualityResult(
        ticker=ticker,
        status=DataQualityStatus.FAIL,
        is_usable=False,
        warnings=["Snapshot stale."],
    )


def make_estimate(
    ticker: str = "T",
    raw: float = 0.07,
    expense: float = 0.001,
    esg_adj: float = 0.0,
    dq_adj: float = 0.0,
    adjusted: float = 0.069,
    reason_codes: list[str] | None = None,
    notes: list[str] | None = None,
) -> ReturnEstimate:
    """Construye un ReturnEstimate directo para tests de validación."""
    return ReturnEstimate(
        ticker=ticker,
        raw_expected_return_annual=raw,
        expense_ratio=expense,
        esg_adjustment=esg_adj,
        data_quality_adjustment=dq_adj,
        adjusted_expected_return_annual=adjusted,
        reason_codes=reason_codes if reason_codes is not None else [],
        notes=notes if notes is not None else [],
    )


# ── Test 1-2: expense_ratio ───────────────────────────────────────────────────


class TestExpenseRatio:
    """Sin ESG ni DataQuality, se resta expense_ratio y se agrega el reason code."""

    def test_resta_expense_ratio(self):
        snap = make_snapshot(raw=0.08, expense=0.001)
        report = ReturnEstimator().estimate(snap)
        # adjusted = 0.08 - 0.001 = 0.079
        assert report.adjusted_expected_return_annual == pytest.approx(0.079)

    def test_agrega_reason_code_expense(self):
        snap = make_snapshot(raw=0.08, expense=0.001)
        report = ReturnEstimator().estimate(snap)
        assert RC_COST_EXPENSE_RATIO in report.reason_codes

    def test_sin_expense_no_agrega_reason_code(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(snap)
        assert RC_COST_EXPENSE_RATIO not in report.reason_codes

    def test_raw_se_preserva_intacto(self):
        snap = make_snapshot(raw=0.08, expense=0.005)
        report = ReturnEstimator().estimate(snap)
        assert report.raw_expected_return_annual == pytest.approx(0.08)

    def test_expense_ratio_se_preserva_intacto(self):
        snap = make_snapshot(raw=0.08, expense=0.005)
        report = ReturnEstimator().estimate(snap)
        assert report.expense_ratio == pytest.approx(0.005)


# ── Test 3: ESG PASS ──────────────────────────────────────────────────────────


class TestESGPass:
    """ESG PASS: esg_adjustment = 0.0, sin reason code ESG."""

    def test_no_modifica_retorno(self):
        snap = make_snapshot(raw=0.08, expense=0.001)
        report = ReturnEstimator().estimate(snap, esg_result=make_esg_pass())
        # adjusted = 0.08 - 0.001 + 0.0 = 0.079
        assert report.adjusted_expected_return_annual == pytest.approx(0.079)

    def test_esg_adjustment_es_cero(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(snap, esg_result=make_esg_pass())
        assert report.esg_adjustment == pytest.approx(0.0)

    def test_sin_reason_codes_esg(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(snap, esg_result=make_esg_pass())
        assert RC_ESG_UNKNOWN not in report.reason_codes


# ── Test 4: ESG SOFT_WARNING ──────────────────────────────────────────────────


class TestESGSoftWarning:
    """ESG SOFT_WARNING: esg_adjustment = soft_score_adjustment * ESG_SOFT_SCALE."""

    def test_penaliza_segun_soft_score_adjustment(self):
        # soft_adj=-0.5 → esg_adjustment = -0.5 * 0.01 = -0.005
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(
            snap, esg_result=make_esg_soft_warning(soft_adj=-0.5)
        )
        assert report.esg_adjustment == pytest.approx(-0.5 * ESG_SOFT_SCALE)
        assert report.adjusted_expected_return_annual == pytest.approx(0.08 - 0.005)

    def test_soft_score_maximo_negativo(self):
        # soft_adj=-1.0 → esg_adjustment = -1.0 * 0.01 = -0.01
        snap = make_snapshot(raw=0.10, expense=0.0)
        report = ReturnEstimator().estimate(
            snap, esg_result=make_esg_soft_warning(soft_adj=-1.0)
        )
        assert report.esg_adjustment == pytest.approx(-0.01)
        assert report.adjusted_expected_return_annual == pytest.approx(0.09)

    def test_soft_score_cero_sin_penalizacion(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(
            snap, esg_result=make_esg_soft_warning(soft_adj=0.0)
        )
        assert report.esg_adjustment == pytest.approx(0.0)
        assert report.adjusted_expected_return_annual == pytest.approx(0.08)


# ── Test 5: ESG UNKNOWN ───────────────────────────────────────────────────────


class TestESGUnknown:
    """ESG UNKNOWN: aplica ESG_UNKNOWN_PENALTY (-0.005) y agrega ESG_UNKNOWN_ADJUSTMENT."""

    def test_aplica_penalizacion_fija(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(snap, esg_result=make_esg_unknown())
        assert report.esg_adjustment == pytest.approx(ESG_UNKNOWN_PENALTY)

    def test_agrega_reason_code_esg_unknown(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(snap, esg_result=make_esg_unknown())
        assert RC_ESG_UNKNOWN in report.reason_codes

    def test_ajusta_retorno_correctamente(self):
        snap = make_snapshot(raw=0.08, expense=0.001)
        report = ReturnEstimator().estimate(snap, esg_result=make_esg_unknown())
        # adjusted = 0.08 - 0.001 - 0.005 = 0.074
        assert report.adjusted_expected_return_annual == pytest.approx(0.074)


# ── Test 6: ESG BLOCKED ───────────────────────────────────────────────────────


class TestESGBlocked:
    """ESG BLOCKED: levantar ValueError. El instrumento no debe estimarse."""

    def test_levanta_value_error(self):
        snap = make_snapshot(raw=0.08, expense=0.001)
        with pytest.raises(ValueError, match="BLOCKED"):
            ReturnEstimator().estimate(snap, esg_result=make_esg_blocked())

    def test_error_menciona_ticker(self):
        snap = make_snapshot(ticker="WEAPON-CO", raw=0.08, expense=0.0)
        with pytest.raises(ValueError, match="WEAPON-CO"):
            ReturnEstimator().estimate(
                snap, esg_result=make_esg_blocked(ticker="WEAPON-CO")
            )


# ── Test 7: DataQuality PASS ──────────────────────────────────────────────────


class TestDataQualityPass:
    """DataQuality PASS: data_quality_adjustment = 0.0, sin reason code DQ."""

    def test_no_modifica_retorno(self):
        snap = make_snapshot(raw=0.08, expense=0.001)
        report = ReturnEstimator().estimate(
            snap, data_quality_result=make_dq_pass()
        )
        assert report.adjusted_expected_return_annual == pytest.approx(0.079)

    def test_data_quality_adjustment_es_cero(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(
            snap, data_quality_result=make_dq_pass()
        )
        assert report.data_quality_adjustment == pytest.approx(0.0)

    def test_sin_reason_code_dq(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(
            snap, data_quality_result=make_dq_pass()
        )
        assert RC_DATA_QUALITY_WARNING not in report.reason_codes


# ── Test 8: DataQuality WARNING ───────────────────────────────────────────────


class TestDataQualityWarning:
    """DataQuality WARNING: aplica DQ_WARNING_PENALTY (-0.0025)."""

    def test_aplica_penalizacion_fija(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(
            snap, data_quality_result=make_dq_warning()
        )
        assert report.data_quality_adjustment == pytest.approx(DQ_WARNING_PENALTY)

    def test_agrega_reason_code_dq_warning(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(
            snap, data_quality_result=make_dq_warning()
        )
        assert RC_DATA_QUALITY_WARNING in report.reason_codes

    def test_ajusta_retorno_correctamente(self):
        snap = make_snapshot(raw=0.08, expense=0.001)
        report = ReturnEstimator().estimate(
            snap, data_quality_result=make_dq_warning()
        )
        # adjusted = 0.08 - 0.001 - 0.0025 = 0.0765
        assert report.adjusted_expected_return_annual == pytest.approx(0.0765)


# ── Test 9: DataQuality FAIL ──────────────────────────────────────────────────


class TestDataQualityFail:
    """DataQuality FAIL: levantar ValueError. El instrumento no debe estimarse."""

    def test_levanta_value_error(self):
        snap = make_snapshot(raw=0.08, expense=0.001)
        with pytest.raises(ValueError, match="FAIL"):
            ReturnEstimator().estimate(
                snap, data_quality_result=make_dq_fail()
            )

    def test_error_menciona_ticker(self):
        snap = make_snapshot(ticker="STALE-BOND", raw=0.05, expense=0.0)
        with pytest.raises(ValueError, match="STALE-BOND"):
            ReturnEstimator().estimate(
                snap, data_quality_result=make_dq_fail(ticker="STALE-BOND")
            )


# ── Test 10: Acumulación de ajustes ──────────────────────────────────────────


class TestAcumulacionAjustes:
    """ESG WARNING + DataQuality WARNING: ambos ajustes se acumulan."""

    def test_ambos_ajustes_se_acumulan(self):
        # raw=0.10, expense=0.005, esg_adj=-0.005, dq_adj=-0.0025
        # adjusted = 0.10 - 0.005 - 0.005 - 0.0025 = 0.0875
        snap = make_snapshot(raw=0.10, expense=0.005)
        report = ReturnEstimator().estimate(
            snap,
            esg_result=make_esg_soft_warning(soft_adj=-0.5),  # -0.5 * 0.01 = -0.005
            data_quality_result=make_dq_warning(),
        )
        assert report.adjusted_expected_return_annual == pytest.approx(0.0875)

    def test_ambos_reason_codes_presentes(self):
        snap = make_snapshot(raw=0.10, expense=0.005)
        report = ReturnEstimator().estimate(
            snap,
            esg_result=make_esg_unknown(),
            data_quality_result=make_dq_warning(),
        )
        assert RC_ESG_UNKNOWN in report.reason_codes
        assert RC_DATA_QUALITY_WARNING in report.reason_codes
        assert RC_COST_EXPENSE_RATIO in report.reason_codes

    def test_ajustes_individuales_correctos(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(
            snap,
            esg_result=make_esg_unknown(),
            data_quality_result=make_dq_warning(),
        )
        assert report.esg_adjustment == pytest.approx(ESG_UNKNOWN_PENALTY)
        assert report.data_quality_adjustment == pytest.approx(DQ_WARNING_PENALTY)


# ── Test 11: Fórmula correcta ─────────────────────────────────────────────────


class TestFormulaCorrecta:
    """adjusted = raw - expense_ratio + esg_adjustment + data_quality_adjustment."""

    @pytest.mark.parametrize(
        "raw,expense,soft_adj,use_dq_warn,expected_adj",
        [
            (0.07,  0.001,  0.0,   False, 0.069),
            (0.07,  0.001,  0.0,   True,  0.069 - 0.0025),
            (0.10,  0.005, -0.5,   False, 0.10 - 0.005 - 0.005),
            (0.10,  0.005, -0.5,   True,  0.10 - 0.005 - 0.005 - 0.0025),
            (0.05,  0.0,    0.0,   False, 0.05),
            (0.05,  0.002,  0.0,   False, 0.048),
        ],
    )
    def test_formula(
        self,
        raw: float,
        expense: float,
        soft_adj: float,
        use_dq_warn: bool,
        expected_adj: float,
    ) -> None:
        snap = make_snapshot(raw=raw, expense=expense)
        esg = make_esg_soft_warning(soft_adj=soft_adj) if soft_adj != 0.0 else None
        dq = make_dq_warning() if use_dq_warn else None
        report = ReturnEstimator().estimate(snap, esg_result=esg, data_quality_result=dq)
        assert report.adjusted_expected_return_annual == pytest.approx(expected_adj, abs=1e-10)

    def test_adjusted_consistente_con_componentes(self):
        """adjusted == raw - expense + esg_adj + dq_adj es siempre la identidad."""
        snap = make_snapshot(raw=0.09, expense=0.003)
        report = ReturnEstimator().estimate(
            snap,
            esg_result=make_esg_unknown(),
            data_quality_result=make_dq_warning(),
        )
        expected = (
            report.raw_expected_return_annual
            - report.expense_ratio
            + report.esg_adjustment
            + report.data_quality_adjustment
        )
        assert report.adjusted_expected_return_annual == pytest.approx(expected)


# ── Test 12: Clipping superior ────────────────────────────────────────────────


class TestClippingSuperior:
    """
    Clipping superior a 1.0: el mecanismo funciona y agrega RETURN_CLIPPED.

    Con inputs válidos (raw ∈ [-1,1], adjustments ≤ 0, expense ≥ 0),
    adjusted nunca excede 1.0 en el flujo normal. Se verifica el mecanismo
    directamente a través del método estático _clip_and_annotate.
    """

    def test_clip_superior_devuelve_1_y_agrega_reason_code(self):
        adjusted, codes = ReturnEstimator._clip_and_annotate(1.5, [])
        assert adjusted == pytest.approx(1.0)
        assert RC_RETURN_CLIPPED in codes

    def test_clip_en_exactamente_1_no_dispara_clip(self):
        adjusted, codes = ReturnEstimator._clip_and_annotate(1.0, [])
        assert adjusted == pytest.approx(1.0)
        assert RC_RETURN_CLIPPED not in codes

    def test_clip_superior_preserva_codes_anteriores(self):
        prev = [RC_COST_EXPENSE_RATIO]
        adjusted, codes = ReturnEstimator._clip_and_annotate(2.0, prev)
        assert adjusted == pytest.approx(1.0)
        assert RC_COST_EXPENSE_RATIO in codes
        assert RC_RETURN_CLIPPED in codes

    def test_clip_superior_no_muta_input(self):
        original = [RC_COST_EXPENSE_RATIO]
        ReturnEstimator._clip_and_annotate(2.0, original)
        assert original == [RC_COST_EXPENSE_RATIO]  # lista original sin mutar


# ── Test 13: Clipping inferior ────────────────────────────────────────────────


class TestClippingInferior:
    """
    Clipping inferior a -1.0: escenario realista en flujo completo.

    raw=-0.985, expense=0.02, ESG UNKNOWN (-0.005), DQ WARNING (-0.0025)
    pre_adjusted = -0.985 - 0.02 - 0.005 - 0.0025 = -1.0125 → clip a -1.0
    """

    def test_clip_inferior_via_clip_and_annotate(self):
        adjusted, codes = ReturnEstimator._clip_and_annotate(-1.5, [])
        assert adjusted == pytest.approx(-1.0)
        assert RC_RETURN_CLIPPED in codes

    def test_clip_inferior_flujo_completo(self):
        snap = make_snapshot(ticker="CLIP-LOW", raw=-0.985, expense=0.02)
        esg = make_esg_unknown(ticker="CLIP-LOW")
        dq = make_dq_warning(ticker="CLIP-LOW")
        report = ReturnEstimator().estimate(
            snap, esg_result=esg, data_quality_result=dq
        )
        assert report.adjusted_expected_return_annual == pytest.approx(-1.0)
        assert RC_RETURN_CLIPPED in report.reason_codes

    def test_clip_en_exactamente_menos_1_no_dispara_clip(self):
        adjusted, codes = ReturnEstimator._clip_and_annotate(-1.0, [])
        assert adjusted == pytest.approx(-1.0)
        assert RC_RETURN_CLIPPED not in codes

    def test_clip_inferior_tiene_todos_los_codes(self):
        snap = make_snapshot(ticker="CL2", raw=-0.985, expense=0.02)
        report = ReturnEstimator().estimate(
            snap,
            esg_result=make_esg_unknown(ticker="CL2"),
            data_quality_result=make_dq_warning(ticker="CL2"),
        )
        assert RC_COST_EXPENSE_RATIO in report.reason_codes
        assert RC_ESG_UNKNOWN in report.reason_codes
        assert RC_DATA_QUALITY_WARNING in report.reason_codes
        assert RC_RETURN_CLIPPED in report.reason_codes


# ── Test 14: estimate_many preserva orden ────────────────────────────────────


class TestEstimateManyOrden:
    """estimate_many devuelve resultados en el mismo orden que los snapshots."""

    def test_preserva_orden(self):
        tickers = ["Z", "A", "M", "B", "C"]
        snaps = [make_snapshot(ticker=t, expense=0.0) for t in tickers]
        reports = ReturnEstimator().estimate_many(snaps)
        assert [r.ticker for r in reports] == tickers

    def test_len_igual_a_snapshots(self):
        snaps = [make_snapshot(ticker=f"T{i}", expense=0.0) for i in range(5)]
        reports = ReturnEstimator().estimate_many(snaps)
        assert len(reports) == 5

    def test_lista_vacia(self):
        reports = ReturnEstimator().estimate_many([])
        assert reports == []


# ── Test 15: estimate_many usa diccionarios por ticker ───────────────────────


class TestEstimateManyDiccionarios:
    """estimate_many aplica los resultados ESG/DQ del dict correspondiente al ticker."""

    def test_aplica_esg_correcto_por_ticker(self):
        snaps = [
            make_snapshot(ticker="PASS-ETF", raw=0.07, expense=0.0),
            make_snapshot(ticker="UNK-BOND", raw=0.05, expense=0.0),
        ]
        esg_by_ticker = {
            "PASS-ETF": make_esg_pass(ticker="PASS-ETF"),
            "UNK-BOND": make_esg_unknown(ticker="UNK-BOND"),
        }
        reports = ReturnEstimator().estimate_many(snaps, esg_results_by_ticker=esg_by_ticker)

        pass_rep = next(r for r in reports if r.ticker == "PASS-ETF")
        unk_rep = next(r for r in reports if r.ticker == "UNK-BOND")

        assert pass_rep.esg_adjustment == pytest.approx(0.0)
        assert unk_rep.esg_adjustment == pytest.approx(ESG_UNKNOWN_PENALTY)

    def test_aplica_dq_correcto_por_ticker(self):
        snaps = [
            make_snapshot(ticker="GOOD", raw=0.08, expense=0.0),
            make_snapshot(ticker="WARN", raw=0.06, expense=0.0),
        ]
        dq_by_ticker = {
            "GOOD": make_dq_pass(ticker="GOOD"),
            "WARN": make_dq_warning(ticker="WARN"),
        }
        reports = ReturnEstimator().estimate_many(
            snaps, data_quality_results_by_ticker=dq_by_ticker
        )

        good_rep = next(r for r in reports if r.ticker == "GOOD")
        warn_rep = next(r for r in reports if r.ticker == "WARN")

        assert good_rep.data_quality_adjustment == pytest.approx(0.0)
        assert warn_rep.data_quality_adjustment == pytest.approx(DQ_WARNING_PENALTY)


# ── Test 16: estimate_many trata faltantes como None ─────────────────────────


class TestEstimateManyFaltantes:
    """Tickers sin entrada en los dicts se tratan como None (sin penalización)."""

    def test_esg_faltante_trata_como_none(self):
        snaps = [
            make_snapshot(ticker="CON-ESG", expense=0.0),
            make_snapshot(ticker="SIN-ESG", expense=0.0),
        ]
        esg_by_ticker = {"CON-ESG": make_esg_unknown(ticker="CON-ESG")}
        reports = ReturnEstimator().estimate_many(snaps, esg_results_by_ticker=esg_by_ticker)

        sin_esg = next(r for r in reports if r.ticker == "SIN-ESG")
        assert sin_esg.esg_adjustment == pytest.approx(0.0)
        assert RC_ESG_UNKNOWN not in sin_esg.reason_codes

    def test_dq_faltante_trata_como_none(self):
        snaps = [
            make_snapshot(ticker="CON-DQ", expense=0.0),
            make_snapshot(ticker="SIN-DQ", expense=0.0),
        ]
        dq_by_ticker = {"CON-DQ": make_dq_warning(ticker="CON-DQ")}
        reports = ReturnEstimator().estimate_many(
            snaps, data_quality_results_by_ticker=dq_by_ticker
        )

        sin_dq = next(r for r in reports if r.ticker == "SIN-DQ")
        assert sin_dq.data_quality_adjustment == pytest.approx(0.0)
        assert RC_DATA_QUALITY_WARNING not in sin_dq.reason_codes

    def test_none_dicts_equivale_a_sin_ajustes(self):
        snaps = [make_snapshot(ticker="X", raw=0.08, expense=0.001)]
        r1 = ReturnEstimator().estimate_many(snaps)[0]
        r2 = ReturnEstimator().estimate_many(
            snaps,
            esg_results_by_ticker=None,
            data_quality_results_by_ticker=None,
        )[0]
        assert r1.adjusted_expected_return_annual == pytest.approx(
            r2.adjusted_expected_return_annual
        )


# ── Test 17: estimate_many propaga errores ────────────────────────────────────


class TestEstimateManyPropagaErrores:
    """Si un snapshot genera ValueError, el error se propaga sin silenciar."""

    def test_propaga_esg_blocked(self):
        snaps = [
            make_snapshot(ticker="GOOD", expense=0.0),
            make_snapshot(ticker="BLOCKED", expense=0.0),
        ]
        esg_by_ticker = {"BLOCKED": make_esg_blocked(ticker="BLOCKED")}
        with pytest.raises(ValueError, match="BLOCKED"):
            ReturnEstimator().estimate_many(snaps, esg_results_by_ticker=esg_by_ticker)

    def test_propaga_dq_fail(self):
        snaps = [
            make_snapshot(ticker="OK", expense=0.0),
            make_snapshot(ticker="STALE", expense=0.0),
        ]
        dq_by_ticker = {"STALE": make_dq_fail(ticker="STALE")}
        with pytest.raises(ValueError, match="FAIL"):
            ReturnEstimator().estimate_many(
                snaps, data_quality_results_by_ticker=dq_by_ticker
            )

    def test_no_omite_silenciosamente(self):
        """
        estimate_many no debe silenciar errores ni devolver lista incompleta.
        El caller es responsable de pre-filtrar.
        """
        snaps = [make_snapshot(ticker="BAD", expense=0.0)]
        esg_by_ticker = {"BAD": make_esg_blocked(ticker="BAD")}
        with pytest.raises(ValueError):
            ReturnEstimator().estimate_many(snaps, esg_results_by_ticker=esg_by_ticker)


# ── Test 18: to_dict JSON serializable ───────────────────────────────────────


class TestToDict:
    """ReturnEstimate.to_dict() produce un dict completamente JSON-serializable."""

    def _estimate(self) -> ReturnEstimate:
        snap = make_snapshot(raw=0.07, expense=0.001)
        return ReturnEstimator().estimate(
            snap,
            esg_result=make_esg_unknown(),
            data_quality_result=make_dq_warning(),
        )

    def test_to_dict_devuelve_dict(self):
        assert isinstance(self._estimate().to_dict(), dict)

    def test_to_dict_tiene_claves_requeridas(self):
        d = self._estimate().to_dict()
        required = {
            "ticker",
            "raw_expected_return_annual",
            "expense_ratio",
            "esg_adjustment",
            "data_quality_adjustment",
            "adjusted_expected_return_annual",
            "reason_codes",
            "notes",
        }
        assert required <= d.keys()

    def test_to_dict_reason_codes_es_lista(self):
        d = self._estimate().to_dict()
        assert isinstance(d["reason_codes"], list)

    def test_to_dict_notes_es_lista(self):
        d = self._estimate().to_dict()
        assert isinstance(d["notes"], list)

    def test_to_dict_json_serializable(self):
        d = self._estimate().to_dict()
        serialized = json.dumps(d)
        assert len(serialized) > 0

    def test_to_dict_round_trip(self):
        d = self._estimate().to_dict()
        d2 = json.loads(json.dumps(d))
        assert d2["ticker"] == d["ticker"]
        assert d2["adjusted_expected_return_annual"] == pytest.approx(
            d["adjusted_expected_return_annual"], rel=1e-9
        )

    def test_to_dict_no_contiene_enums(self):
        """El dict no debe contener instancias de Enum — solo tipos primitivos."""
        d = self._estimate().to_dict()
        for v in d.values():
            assert not hasattr(v, "value")  # no es Enum


# ── Test 19: has_penalties ────────────────────────────────────────────────────


class TestHasPenalties:
    """has_penalties es True si hay algún ajuste negativo o expense > 0."""

    def test_true_si_expense_mayor_que_cero(self):
        report = ReturnEstimator().estimate(make_snapshot(raw=0.08, expense=0.001))
        assert report.has_penalties is True

    def test_false_si_sin_penalizaciones(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(snap, esg_result=make_esg_pass())
        assert report.has_penalties is False

    def test_true_si_esg_adjustment_negativo(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(snap, esg_result=make_esg_unknown())
        assert report.has_penalties is True

    def test_true_si_dq_adjustment_negativo(self):
        snap = make_snapshot(raw=0.08, expense=0.0)
        report = ReturnEstimator().estimate(snap, data_quality_result=make_dq_warning())
        assert report.has_penalties is True

    def test_false_en_dataclass_construido_directamente_sin_ajustes(self):
        r = make_estimate(expense=0.0, esg_adj=0.0, dq_adj=0.0, adjusted=0.07)
        assert r.has_penalties is False


# ── Tests 20-27: Validaciones de ReturnEstimate ───────────────────────────────


class TestValidacionesReturnEstimate:
    """Validaciones de __post_init__ de ReturnEstimate."""

    # 20. ticker vacío
    def test_ticker_vacio_levanta_error(self):
        with pytest.raises(ValueError, match="ticker"):
            make_estimate(ticker="")

    def test_ticker_solo_espacios_levanta_error(self):
        with pytest.raises(ValueError, match="ticker"):
            make_estimate(ticker="   ")

    # 21. raw_expected_return fuera de rango
    def test_raw_superior_a_1_levanta_error(self):
        with pytest.raises(ValueError, match="raw_expected_return_annual"):
            make_estimate(raw=1.001, adjusted=1.0)

    def test_raw_inferior_a_menos_1_levanta_error(self):
        with pytest.raises(ValueError, match="raw_expected_return_annual"):
            make_estimate(raw=-1.001, adjusted=-1.0)

    def test_raw_en_limites_no_levanta_error(self):
        assert make_estimate(raw=1.0, adjusted=1.0).raw_expected_return_annual == 1.0
        assert make_estimate(raw=-1.0, adjusted=-1.0).raw_expected_return_annual == -1.0

    # 22. expense_ratio negativa
    def test_expense_negativa_levanta_error(self):
        with pytest.raises(ValueError, match="expense_ratio"):
            make_estimate(expense=-0.001)

    # 23. esg_adjustment positivo
    def test_esg_adjustment_positivo_levanta_error(self):
        with pytest.raises(ValueError, match="esg_adjustment"):
            make_estimate(esg_adj=0.001)

    def test_esg_adjustment_en_limite_cero_no_levanta_error(self):
        assert make_estimate(esg_adj=0.0).esg_adjustment == 0.0

    def test_esg_adjustment_en_limite_menos_1_no_levanta_error(self):
        assert make_estimate(esg_adj=-1.0, adjusted=-1.0).esg_adjustment == -1.0

    # 24. data_quality_adjustment positivo
    def test_dq_adjustment_positivo_levanta_error(self):
        with pytest.raises(ValueError, match="data_quality_adjustment"):
            make_estimate(dq_adj=0.001)

    def test_dq_adjustment_en_limite_cero_no_levanta_error(self):
        assert make_estimate(dq_adj=0.0).data_quality_adjustment == 0.0

    # 25. adjusted_expected_return fuera de rango
    def test_adjusted_superior_a_1_levanta_error(self):
        with pytest.raises(ValueError, match="adjusted_expected_return_annual"):
            make_estimate(adjusted=1.001)

    def test_adjusted_inferior_a_menos_1_levanta_error(self):
        with pytest.raises(ValueError, match="adjusted_expected_return_annual"):
            make_estimate(adjusted=-1.001)

    def test_adjusted_en_limites_no_levanta_error(self):
        assert make_estimate(raw=1.0, adjusted=1.0).adjusted_expected_return_annual == 1.0
        assert make_estimate(raw=-1.0, adjusted=-1.0).adjusted_expected_return_annual == -1.0

    # 26. reason_codes no es lista
    def test_reason_codes_no_lista_levanta_error(self):
        with pytest.raises(ValueError, match="reason_codes"):
            make_estimate(reason_codes="ESG_001")  # type: ignore[arg-type]

    def test_reason_codes_tuple_levanta_error(self):
        with pytest.raises(ValueError, match="reason_codes"):
            make_estimate(reason_codes=("ESG_001",))  # type: ignore[arg-type]

    # 27. notes no es lista
    def test_notes_no_lista_levanta_error(self):
        with pytest.raises(ValueError, match="notes"):
            make_estimate(notes="nota suelta")  # type: ignore[arg-type]

    def test_notes_tuple_levanta_error(self):
        with pytest.raises(ValueError, match="notes"):
            make_estimate(notes=("nota",))  # type: ignore[arg-type]
