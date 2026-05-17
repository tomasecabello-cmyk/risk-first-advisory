"""
Test de integración M1 — fixture contradictorio_alta_severidad.json.

Este es el caso estrella del MVP. Demuestra:
    1. La IA propone moderado-defensivo por una contradicción alta.
    2. Se ejecuta un ciclo de follow-up.
    3. El asesor aporta contexto real del cliente.
    4. La IA revisa y propone moderado.
    5. El asesor aprueba moderado con justificación documentada.
    6. preliminary_profile y approved_profile quedan como objetos distintos.
    7. El audit trail registra todos los eventos y queda cerrado.

Cuando este test pasa por primera vez en consola, el proyecto deja de ser
una especificación y empieza a existir.
"""

import json
from pathlib import Path

import pytest

from risk_first_advisory.ai_layer.mock_ai_client import MockAIClient
from risk_first_advisory.engine import RiskFirstSuitabilityEngine
from risk_first_advisory.human_layer.audit_trail import AuditTrailClosedError
from risk_first_advisory.human_layer.scripted_advisor_interface import (
    ScriptedAdvisorInterface,
)
from risk_first_advisory.kyc.models import (
    ESGExclusion,
    ESGPreference,
    ESGProfile,
    ESGStrictnessLevel,
    FinancialGoal,
    InvestmentObjective,
    InvestorExperience,
    KYCData,
)


FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "kyc_profiles"
    / "contradictorio_alta_severidad.json"
)


# ── Helpers para hidratar fixture → objetos del dominio ──────────────────


def _build_esg_profile(payload: dict) -> ESGProfile:
    return ESGProfile(
        strictness_level=ESGStrictnessLevel(payload["strictness_level"]),
        hard_exclusions=[
            ESGExclusion(
                excluded_item=ex["excluded_item"],
                exclusion_type=ex["exclusion_type"],
                source=ex["source"],
                rationale=ex.get("rationale", ""),
            )
            for ex in payload.get("hard_exclusions", [])
        ],
        soft_preferences=[
            ESGPreference(
                preference_type=p["preference_type"],
                weight=p["weight"],
                minimum_threshold=p.get("minimum_threshold"),
            )
            for p in payload.get("soft_preferences", [])
        ],
    )


def _build_kyc(fixture: dict) -> KYCData:
    kyc_data = fixture["kyc"]
    return KYCData(
        age=kyc_data["age"],
        annual_income_usd=kyc_data["annual_income_usd"],
        approx_net_worth_usd=kyc_data["approx_net_worth_usd"],
        investment_objective=InvestmentObjective(kyc_data["investment_objective"]),
        time_horizon_years=kyc_data["time_horizon_years"],
        liquidity_need_pct=kyc_data["liquidity_need_pct"],
        experience=InvestorExperience(kyc_data["experience"]),
        emotional_loss_tolerance_pct=kyc_data["emotional_loss_tolerance_pct"],
        financial_loss_capacity_pct=kyc_data["financial_loss_capacity_pct"],
        preferred_currency=kyc_data["preferred_currency"],
        needs_income=kyc_data["needs_income"],
        prefers_simple_products=kyc_data["prefers_simple_products"],
        jurisdiction=kyc_data["jurisdiction"],
        esg_profile=_build_esg_profile(fixture["esg_profile"]),
        open_investment_goal=kyc_data.get("open_investment_goal", ""),
        open_risk_reaction=kyc_data.get("open_risk_reaction", ""),
        open_past_experience=kyc_data.get("open_past_experience", ""),
        open_concerns=kyc_data.get("open_concerns", ""),
        declared_return_expectation_pct=kyc_data.get("declared_return_expectation_pct"),
    )


def _build_goal(fixture: dict) -> FinancialGoal:
    g = fixture["financial_goal"]
    return FinancialGoal(
        initial_capital_usd=g["initial_capital_usd"],
        target_capital_usd=g["target_capital_usd"],
        horizon_years=g["horizon_years"],
        periodic_contribution_usd=g["periodic_contribution_usd"],
        contribution_frequency_years=g["contribution_frequency_years"],
        target_is_flexible=g["target_is_flexible"],
        horizon_is_flexible=g["horizon_is_flexible"],
    )


# ── Fixture pytest ────────────────────────────────────────────────────────


@pytest.fixture
def fixture_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def m1_result(fixture_payload):
    """Ejecuta el flujo M1 completo y devuelve el resultado."""
    engine = RiskFirstSuitabilityEngine(
        ai_client=MockAIClient(scripted_responses=fixture_payload["ai_script"]),
        advisor_interface=ScriptedAdvisorInterface(
            scripted_decisions=fixture_payload["advisor_script"]
        ),
    )
    return engine.run_m1(
        kyc=_build_kyc(fixture_payload),
        financial_goal=_build_goal(fixture_payload),
        client_id=fixture_payload["client_id"],
        advisor_id=fixture_payload["advisor_script"]["advisor_id"],
    )


# ── Tests ─────────────────────────────────────────────────────────────────


def test_fixture_file_exists():
    assert FIXTURE_PATH.exists(), f"Fixture no encontrado en {FIXTURE_PATH}."


def test_ia_propone_perfil_inicial_moderado_defensivo(m1_result):
    assert m1_result.preliminary_profile_initial.profile_name == "moderado-defensivo"


def test_ia_detecta_al_menos_una_contradiccion_de_severidad_alta(m1_result):
    contradicciones = m1_result.preliminary_profile_initial.detected_contradictions
    altas = [c for c in contradicciones if c.severity == "alta"]
    assert len(altas) >= 1, (
        "La IA debería haber detectado al menos una contradicción de severidad alta "
        "en el fixture contradictorio."
    )


def test_se_ejecuta_exactamente_una_ronda_de_follow_up(m1_result):
    assert m1_result.follow_up_rounds_executed == 1


def test_asesor_responde_las_dos_preguntas_de_follow_up(m1_result):
    assert len(m1_result.follow_up_responses) == 2
    for r in m1_result.follow_up_responses:
        assert r.answer.strip(), "Toda respuesta del asesor debe tener contenido."


def test_ia_propone_perfil_revisado_moderado_tras_follow_up(m1_result):
    assert m1_result.preliminary_profile_revised is not None
    assert m1_result.preliminary_profile_revised.profile_name == "moderado"


def test_perfil_revisado_no_tiene_contradicciones(m1_result):
    revised = m1_result.preliminary_profile_revised
    assert revised is not None
    assert len(revised.detected_contradictions) == 0


def test_asesor_aprueba_perfil_moderado(m1_result):
    assert m1_result.approved_profile.profile_name == "moderado"


def test_preliminary_y_approved_son_objetos_distintos(m1_result):
    """
    INVARIANTE central del producto: preliminary_profile (lo que propone la IA)
    y approved_profile (lo que valida el asesor) son conceptos distintos.
    En este fixture específico, ambos son "moderado" tras el follow-up, pero
    el initial era "moderado-defensivo" — el approved difiere del preliminary
    INICIAL aunque coincida con el revisado.
    """
    assert (
        m1_result.preliminary_profile_initial.profile_name
        != m1_result.approved_profile.profile_name
    ), (
        "El approved_profile debe diferir del preliminary_profile_initial "
        "en este caso de prueba."
    )
    # Y aunque coincida con el revised, son objetos de tipos distintos:
    assert type(m1_result.preliminary_profile_initial).__name__ == "PreliminaryProfile"
    assert type(m1_result.approved_profile).__name__ == "ApprovedProfile"


def test_advisor_modified_profile_es_true(m1_result):
    """El asesor modificó el perfil original propuesto por la IA."""
    assert m1_result.advisor_modified_profile is True
    assert m1_result.approved_profile.is_modified is True


def test_advisor_comment_tiene_minimo_30_caracteres(m1_result):
    comment = m1_result.approved_profile.advisor_comment.strip()
    assert len(comment) >= 30, (
        f"advisor_comment debe tener mínimo 30 caracteres cuando hay modificación. "
        f"Recibido: {len(comment)} caracteres."
    )


def test_audit_trail_registra_session_started(m1_result):
    assert m1_result.audit is not None
    assert m1_result.audit.has_event("session_started")


def test_audit_trail_registra_ai_output_initial(m1_result):
    assert m1_result.audit.has_event("ai_output_initial")
    events = m1_result.audit.get_events_by_type("ai_output_initial")
    assert events[0].data["profile"] == "moderado-defensivo"
    assert events[0].data["has_blocking"] is True


def test_audit_trail_registra_follow_up_cycle_started(m1_result):
    assert m1_result.audit.has_event("follow_up_cycle_1_started")
    events = m1_result.audit.get_events_by_type("follow_up_cycle_1_started")
    assert len(events[0].data["questions"]) == 2


def test_audit_trail_registra_follow_up_cycle_completed(m1_result):
    assert m1_result.audit.has_event("follow_up_cycle_1_completed")
    events = m1_result.audit.get_events_by_type("follow_up_cycle_1_completed")
    assert events[0].data["responses_count"] == 2


def test_audit_trail_registra_ai_output_revised(m1_result):
    assert m1_result.audit.has_event("ai_output_revised")
    events = m1_result.audit.get_events_by_type("ai_output_revised")
    assert events[0].data["profile"] == "moderado"


def test_audit_trail_registra_advisor_profile_approval_con_metadata_completa(m1_result):
    assert m1_result.audit.has_event("advisor_profile_approval")
    events = m1_result.audit.get_events_by_type("advisor_profile_approval")
    assert len(events) == 1
    data = events[0].data
    assert data["original"] == "moderado-defensivo"
    assert data["approved"] == "moderado"
    assert data["modified"] is True
    assert len(data["advisor_comment"].strip()) >= 30


def test_audit_trail_registra_session_closed(m1_result):
    assert m1_result.audit.has_event("session_closed")


def test_audit_trail_queda_cerrado(m1_result):
    assert m1_result.audit.is_closed is True


def test_audit_trail_no_acepta_records_despues_del_cierre(m1_result):
    with pytest.raises(AuditTrailClosedError):
        m1_result.audit.record("attempt_after_close", {"should": "fail"})


def test_eventos_aparecen_en_el_orden_esperado(m1_result):
    """Los eventos quedaron en orden cronológico correcto."""
    expected_order = [
        "session_started",
        "ai_output_initial",
        "follow_up_cycle_1_started",
        "follow_up_cycle_1_completed",
        "ai_output_revised",
        "advisor_profile_approval",
        "session_closed",
    ]
    actual_order = m1_result.audit.event_types()
    assert actual_order == expected_order, (
        f"Eventos del audit trail no están en el orden esperado.\n"
        f"Esperado: {expected_order}\n"
        f"Actual:   {actual_order}"
    )


def test_audit_trail_serializable_a_json(m1_result):
    payload = m1_result.audit.to_json()
    parsed = json.loads(payload)
    assert parsed["session_id"] == m1_result.session_id
    assert parsed["client_id"] == m1_result.client_id
    assert parsed["is_closed"] is True
    assert len(parsed["events"]) == 7


def test_expected_outcome_del_fixture_coincide_con_resultado(m1_result, fixture_payload):
    """Test final que confronta todo el resultado contra el expected_outcome del fixture."""
    expected = fixture_payload["expected_outcome"]
    assert (
        m1_result.preliminary_profile_initial.profile_name
        == expected["preliminary_profile_initial"]
    )
    assert (
        m1_result.preliminary_profile_revised.profile_name
        == expected["preliminary_profile_revised"]
    )
    assert m1_result.approved_profile.profile_name == expected["approved_profile"]
    assert m1_result.advisor_modified_profile == expected["advisor_modified_profile"]
    assert (
        m1_result.preliminary_profile_initial.binding_dimension
        == expected["binding_dimension"]
    )
    assert (
        len(m1_result.preliminary_profile_initial.detected_contradictions)
        == expected["contradictions_count_initial"]
    )
    assert (
        len(m1_result.preliminary_profile_revised.detected_contradictions)
        == expected["contradictions_count_after_followup"]
    )
    assert m1_result.follow_up_rounds_executed == expected["follow_up_rounds_executed"]
    for evt in expected["audit_events_expected"]:
        assert m1_result.audit.has_event(evt), f"Falta el evento {evt!r} en audit."