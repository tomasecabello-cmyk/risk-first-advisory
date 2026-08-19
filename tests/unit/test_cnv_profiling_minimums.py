"""
Mínimos de perfilamiento CNV en el KYC (DD-018).

Normas CNV (N.T. 2013 y mod.), Título VII: art. 12 inc. j) Cap. I (AN) y
art. 16 inc. j) Cap. II (ALyC). El agente debe conocer el perfil de riesgo del
cliente considerando como mínimo, entre otros aspectos, el grado de conocimiento
de los instrumentos disponibles, el porcentaje de ahorros destinado a estas
inversiones y el nivel de ahorros que está dispuesto a arriesgar.

Cubre:
    - compute_drawdown_from_savings: la caída tolerada sale de dos hechos
      DECLARADOS, no de la tolerancia (rompe la circularidad, I-024).
    - KYCData: validación de rangos y missing_cnv_profiling_minimums().
    - _cnv_profiling_warning: KYC_013 cuando falta alguno de los tres.
    - _build_kyc_data: el gate drawdown_from_savings manda sobre el valor
      declarado, y sin gate el comportamiento legacy queda intacto.
    - Sección del reporte: formatea lo declarado, nunca lo completa.

Función pura en todos los casos: no toca DB, red ni OpenAI.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from risk_first_advisory.ai_layer.risk_scoring import compute_drawdown_from_savings
from risk_first_advisory.api_layer.main import _build_kyc_data, _cnv_profiling_warning
from risk_first_advisory.api_layer.schemas import KYCDataRequest
from risk_first_advisory.kyc.models import (
    ESGProfile,
    InvestmentObjective,
    InvestorExperience,
    KYCData,
)
from risk_first_advisory.reporting_layer.case_markdown_report import (
    _cnv_profiling_complete,
    _section_cnv_profiling,
)
from risk_first_advisory.rules_layer.reason_codes import REASON_CODE_CATALOG, ReasonCode


def _make_request(**overrides) -> KYCDataRequest:
    base = dict(
        risk_tolerance_score=6,
        risk_capacity_score=7,
        liquidity_need_score=3,
        investment_horizon_years=10,
        investment_experience="moderada",
        income_stability="stable",
        net_worth=500_000.0,
        liquid_net_worth=200_000.0,
        max_acceptable_drawdown_pct=25.0,
    )
    base.update(overrides)
    return KYCDataRequest(**base)


def _make_kyc(**overrides) -> KYCData:
    base = dict(
        age=42,
        annual_income_usd=80_000.0,
        approx_net_worth_usd=500_000.0,
        investment_objective=InvestmentObjective.BALANCED,
        time_horizon_years=10,
        liquidity_need_pct=0.3,
        experience=InvestorExperience.MODERATE,
        emotional_loss_tolerance_pct=25.0,
        financial_loss_capacity_pct=40.0,
        preferred_currency="USD",
        needs_income=False,
        prefers_simple_products=False,
        jurisdiction="AR",
        esg_profile=ESGProfile(),
    )
    base.update(overrides)
    return KYCData(**base)


# ─────────────────────────────────────────────────────────────────────────────
# compute_drawdown_from_savings
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("allocated", "at_risk", "esperado"),
    [
        (50.0, 10.0, 20.0),    # arriesga 10% del ahorro con 50% invertido → 20% de la cartera
        (100.0, 30.0, 30.0),   # todo el ahorro invertido → los dos porcentajes coinciden
        (25.0, 25.0, 100.0),   # dispuesto a perder todo lo invertido
        (10.0, 1.0, 10.0),
        (50.0, 0.0, 0.0),      # no está dispuesto a perder nada
    ],
)
def test_drawdown_derivado_de_los_dos_porcentajes(allocated, at_risk, esperado):
    payload = {"savings_allocated_pct": allocated, "savings_at_risk_pct": at_risk}
    assert compute_drawdown_from_savings(payload) == pytest.approx(esperado)


def test_drawdown_se_acota_a_100_si_arriesga_mas_de_lo_asignado():
    """Declarar arriesgar más de lo invertido no puede dar una caída > 100%."""
    payload = {"savings_allocated_pct": 20.0, "savings_at_risk_pct": 80.0}
    assert compute_drawdown_from_savings(payload) == 100.0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"savings_allocated_pct": 50.0},                       # falta at_risk
        {"savings_at_risk_pct": 10.0},                         # falta allocated
        {"savings_allocated_pct": 0.0, "savings_at_risk_pct": 5.0},   # nada invertido
        {"savings_allocated_pct": "x", "savings_at_risk_pct": 5.0},   # no numérico
        {"savings_allocated_pct": None, "savings_at_risk_pct": None},
    ],
)
def test_drawdown_devuelve_none_si_no_hay_datos_suficientes(payload):
    assert compute_drawdown_from_savings(payload) is None


def test_drawdown_no_depende_de_la_tolerancia():
    """
    Regresión de la circularidad (I-024): el resultado no puede cambiar por
    mover la tolerancia ni las respuestas del cuestionario.
    """
    base = {"savings_allocated_pct": 40.0, "savings_at_risk_pct": 8.0}
    conservador = compute_drawdown_from_savings(
        {**base, "risk_tolerance_score": 1, "tolerance_answers": {"q1": "d"}}
    )
    agresivo = compute_drawdown_from_savings(
        {**base, "risk_tolerance_score": 10, "tolerance_answers": {"q1": "a"}}
    )
    assert conservador == agresivo == 20.0


# ─────────────────────────────────────────────────────────────────────────────
# KYCData
# ─────────────────────────────────────────────────────────────────────────────


def test_kyc_data_acepta_los_tres_minimos():
    kyc = _make_kyc(
        instrument_knowledge={"STOCK": "basico", "CEDEAR": "ninguno"},
        savings_allocated_pct=50.0,
        savings_at_risk_pct=10.0,
    )
    assert kyc.instrument_knowledge["STOCK"] == "basico"
    assert kyc.savings_allocated_pct == 50.0
    assert kyc.savings_at_risk_pct == 10.0
    assert kyc.missing_cnv_profiling_minimums() == []


def test_kyc_data_sin_los_campos_sigue_siendo_valido_y_reporta_faltantes():
    """Backward compat: los KYC anteriores a DD-018 siguen construyéndose."""
    kyc = _make_kyc()
    assert kyc.instrument_knowledge == {}
    assert kyc.savings_allocated_pct is None
    assert kyc.savings_at_risk_pct is None
    assert kyc.missing_cnv_profiling_minimums() == [
        "instrument_knowledge",
        "savings_allocated_pct",
        "savings_at_risk_pct",
    ]


def test_kyc_data_reporta_solo_lo_que_falta():
    kyc = _make_kyc(instrument_knowledge={"ETF": "avanzado"}, savings_allocated_pct=30.0)
    assert kyc.missing_cnv_profiling_minimums() == ["savings_at_risk_pct"]


@pytest.mark.parametrize("pct", [-1.0, 100.1, 250.0])
def test_kyc_data_rechaza_porcentajes_fuera_de_rango(pct):
    with pytest.raises(ValueError, match="debe estar en"):
        _make_kyc(savings_allocated_pct=pct)


def test_kyc_data_rechaza_nivel_de_conocimiento_invalido():
    with pytest.raises(ValueError, match="nivel de conocimiento inválido"):
        _make_kyc(instrument_knowledge={"STOCK": "experto"})


def test_kyc_data_acepta_cero_por_ciento():
    """0.0 es una respuesta válida, no un 'sin dato'."""
    kyc = _make_kyc(
        instrument_knowledge={"STOCK": "ninguno"},
        savings_allocated_pct=0.0,
        savings_at_risk_pct=0.0,
    )
    assert kyc.missing_cnv_profiling_minimums() == []


# ─────────────────────────────────────────────────────────────────────────────
# Schema (validación en el borde de la API)
# ─────────────────────────────────────────────────────────────────────────────


def test_schema_rechaza_instrument_type_desconocido():
    with pytest.raises(ValidationError, match="instrument_type inválido"):
        _make_request(instrument_knowledge={"CRIPTO": "basico"})


def test_schema_rechaza_nivel_desconocido():
    with pytest.raises(ValidationError, match="nivel de conocimiento inválido"):
        _make_request(instrument_knowledge={"STOCK": "muchisimo"})


@pytest.mark.parametrize("campo", ["savings_allocated_pct", "savings_at_risk_pct"])
def test_schema_rechaza_porcentajes_fuera_de_rango(campo):
    with pytest.raises(ValidationError):
        _make_request(**{campo: 101.0})


def test_schema_defaults_no_rompen_payloads_existentes():
    req = _make_request()
    assert req.instrument_knowledge == {}
    assert req.savings_allocated_pct is None
    assert req.savings_at_risk_pct is None
    assert req.drawdown_from_savings is False


# ─────────────────────────────────────────────────────────────────────────────
# Warning KYC_013
# ─────────────────────────────────────────────────────────────────────────────


def test_warning_cuando_faltan_los_tres():
    warning = _cnv_profiling_warning(_make_request())
    assert warning is not None
    assert ReasonCode.KYC_CNV_PROFILING_INCOMPLETE.value in warning
    assert "instrument_knowledge" in warning
    assert "savings_allocated_pct" in warning
    assert "savings_at_risk_pct" in warning


def test_sin_warning_cuando_estan_los_tres():
    req = _make_request(
        instrument_knowledge={"STOCK": "basico"},
        savings_allocated_pct=50.0,
        savings_at_risk_pct=10.0,
    )
    assert _cnv_profiling_warning(req) is None


def test_warning_nombra_solo_lo_que_falta():
    req = _make_request(instrument_knowledge={"STOCK": "basico"}, savings_allocated_pct=50.0)
    warning = _cnv_profiling_warning(req)
    assert warning is not None
    assert "savings_at_risk_pct" in warning
    assert "instrument_knowledge" not in warning


def test_kyc_013_esta_en_el_catalogo_y_no_bloquea():
    entry = REASON_CODE_CATALOG[ReasonCode.KYC_CNV_PROFILING_INCOMPLETE]
    assert entry["domain"] == "kyc"
    assert entry["blocks_advancement"] is False
    assert entry["implies_follow_up"] is True


# ─────────────────────────────────────────────────────────────────────────────
# _build_kyc_data — el gate manda sobre el valor declarado
# ─────────────────────────────────────────────────────────────────────────────


def test_build_kyc_data_propaga_los_tres_campos():
    req = _make_request(
        instrument_knowledge={"CEDEAR": "ninguno"},
        savings_allocated_pct=40.0,
        savings_at_risk_pct=8.0,
    )
    kyc = _build_kyc_data(req)
    assert kyc.instrument_knowledge == {"CEDEAR": "ninguno"}
    assert kyc.savings_allocated_pct == 40.0
    assert kyc.savings_at_risk_pct == 8.0


def test_gate_activo_deriva_la_caida_e_ignora_el_placeholder():
    """
    max_acceptable_drawdown_pct=90 es un placeholder absurdo; con el gate
    encendido el motor usa el 20% derivado de los porcentajes declarados.
    La tolerancia emocional es min(score*10, drawdown) = min(60, 20) = 20.
    """
    req = _make_request(
        risk_tolerance_score=6,
        max_acceptable_drawdown_pct=90.0,
        savings_allocated_pct=50.0,
        savings_at_risk_pct=10.0,
        drawdown_from_savings=True,
    )
    kyc = _build_kyc_data(req)
    assert kyc.emotional_loss_tolerance_pct == pytest.approx(20.0)


def test_gate_apagado_mantiene_el_comportamiento_legacy():
    req = _make_request(
        risk_tolerance_score=6,
        max_acceptable_drawdown_pct=15.0,
        savings_allocated_pct=50.0,
        savings_at_risk_pct=10.0,
        drawdown_from_savings=False,
    )
    kyc = _build_kyc_data(req)
    assert kyc.emotional_loss_tolerance_pct == pytest.approx(15.0)


def test_gate_activo_sin_porcentajes_cae_al_valor_declarado():
    """El gate no puede romper el KYC si faltan los datos para derivar."""
    req = _make_request(max_acceptable_drawdown_pct=15.0, drawdown_from_savings=True)
    kyc = _build_kyc_data(req)
    assert kyc.emotional_loss_tolerance_pct == pytest.approx(15.0)


# ─────────────────────────────────────────────────────────────────────────────
# Sección del reporte
# ─────────────────────────────────────────────────────────────────────────────


def test_seccion_reporte_lista_lo_declarado():
    md = _section_cnv_profiling({
        "instrument_knowledge": {"STOCK": "basico", "CEDEAR": "ninguno"},
        "savings_allocated_pct": 50.0,
        "savings_at_risk_pct": 10.0,
    })
    assert "Mínimos de perfilamiento (Normas CNV)" in md
    assert "`STOCK`: conocimiento básico" in md
    assert "`CEDEAR`: sin conocimiento" in md
    assert ReasonCode.KYC_CNV_PROFILING_INCOMPLETE.value not in md


def test_seccion_reporte_marca_lo_que_falta():
    md = _section_cnv_profiling({"savings_allocated_pct": 50.0})
    assert "no relevado" in md
    assert ReasonCode.KYC_CNV_PROFILING_INCOMPLETE.value in md


def test_seccion_reporte_vacia_sin_kyc():
    assert _section_cnv_profiling(None) == ""


def test_seccion_reporte_no_deriva_la_caida():
    """
    I-013/I-020: el generator formatea lo declarado y nada más. La caída
    tolerada la deriva el motor (compute_drawdown_from_savings) y se muestra
    en la sección de capacidad, no acá.
    """
    payload = {"savings_allocated_pct": 50.0, "savings_at_risk_pct": 10.0}
    md = _section_cnv_profiling(payload).lower()
    assert "caída" not in md
    assert "drawdown" not in md


@pytest.mark.parametrize(
    ("payload", "esperado"),
    [
        (None, None),
        ({}, False),
        ({"instrument_knowledge": {"STOCK": "basico"}}, False),
        (
            {
                "instrument_knowledge": {"STOCK": "basico"},
                "savings_allocated_pct": 50.0,
                "savings_at_risk_pct": 10.0,
            },
            True,
        ),
    ],
)
def test_metadata_cnv_profiling_complete(payload, esperado):
    assert _cnv_profiling_complete(payload) is esperado
