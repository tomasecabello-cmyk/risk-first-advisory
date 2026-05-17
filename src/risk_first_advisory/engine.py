"""
RiskFirstSuitabilityEngine — orquestador del flujo de asesoría.

Versión M1 mínima: ejercita la cadena KYC → IA → follow-up → asesor → audit.

NO incluye todavía:
    - Goal feasibility (capa B)
    - Risk budget builder (capa B)
    - Product governance (capa B)
    - Data providers (capa C)
    - Optimizer (capa C)
    - Portfolio generation (capa C)

Esos componentes entran en sprints posteriores. M1 valida que el contrato
entre IA mock, asesor scripted y audit trail funciona end-to-end.

INVARIANTE: cuando el asesor aprueba el perfil, se le pasan DOS argumentos:
    - original_preliminary_profile_name: el perfil INICIAL propuesto por la IA.
    - current_preliminary_profile_name:  el perfil vigente tras follow-up (o el
                                         mismo inicial si no hubo follow-up).

Esto garantiza que ApprovedProfile.original_profile siempre refleje la primera
propuesta de la IA, preservando la trazabilidad de la modificación del asesor.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from risk_first_advisory.ai_layer.mock_ai_client import (
    MockAIClient,
    PreliminaryProfile,
)
from risk_first_advisory.human_layer.audit_trail import AuditTrail
from risk_first_advisory.human_layer.scripted_advisor_interface import (
    ApprovedProfile,
    FollowUpResponse,
    ScriptedAdvisorInterface,
)
from risk_first_advisory.kyc.models import FinancialGoal, KYCData


MAX_FOLLOW_UP_ROUNDS = 3


@dataclass
class M1SessionResult:
    """
    Resultado de una sesión M1.

    Mantiene `preliminary_profile` y `approved_profile` como objetos
    SEPARADOS — son conceptualmente distintos.
    """

    session_id: str
    client_id: str
    advisor_id: str

    # Lo que la IA propuso inicialmente
    preliminary_profile_initial: PreliminaryProfile

    # Lo que la IA propuso tras follow-up (None si no hubo follow-up)
    preliminary_profile_revised: PreliminaryProfile | None

    # Lo que el asesor finalmente aprobó
    approved_profile: ApprovedProfile

    # Respuestas del follow-up (vacío si no hubo)
    follow_up_responses: list[FollowUpResponse] = field(default_factory=list)

    follow_up_rounds_executed: int = 0

    audit: AuditTrail | None = None

    @property
    def preliminary_profile(self) -> PreliminaryProfile:
        """El perfil preliminar vigente (revised si existe, initial si no)."""
        return self.preliminary_profile_revised or self.preliminary_profile_initial

    @property
    def advisor_modified_profile(self) -> bool:
        return self.approved_profile.is_modified


class RiskFirstSuitabilityEngine:
    """
    Orquestador del flujo. Versión M1 mínima.

    Flujo:
        1. Registra session_started.
        2. IA propone perfil inicial → registra ai_output_initial.
        3. Si hay contradicción alta:
            3.1. Registra follow_up_cycle_1_started.
            3.2. Asesor responde follow-up.
            3.3. Registra follow_up_cycle_1_completed.
            3.4. IA revisa con respuestas → registra ai_output_revised.
        4. Asesor aprueba perfil → registra advisor_profile_approval.
           El asesor recibe ambos perfiles (original inicial + vigente actual)
           para que ApprovedProfile.original_profile preserve el INICIAL.
        5. Registra session_closed.
        6. Cierra audit trail.
    """

    def __init__(
        self,
        ai_client: MockAIClient,
        advisor_interface: ScriptedAdvisorInterface,
    ):
        self.ai_client = ai_client
        self.advisor = advisor_interface

    def run_m1(
        self,
        kyc: KYCData,
        financial_goal: FinancialGoal,
        client_id: str,
        advisor_id: str,
        session_id: str | None = None,
    ) -> M1SessionResult:
        """
        Ejecuta el flujo M1 (KYC → perfil aprobado, sin portfolios).
        """
        sid = session_id or self._generate_session_id()
        audit = AuditTrail(session_id=sid, client_id=client_id, advisor_id=advisor_id)
        audit.record("session_started", {"mode": "m1_mock", "advisor_id": advisor_id})

        # ── Fase 1: IA propone perfil inicial ──────────────────────────
        prelim_initial = self.ai_client.propose_preliminary_profile(kyc, financial_goal)
        audit.record(
            "ai_output_initial",
            {
                "profile": prelim_initial.profile_name,
                "confidence": prelim_initial.confidence,
                "binding_dimension": prelim_initial.binding_dimension,
                "contradictions_count": len(prelim_initial.detected_contradictions),
                "has_blocking": prelim_initial.has_blocking_contradictions(),
            },
        )

        # ── Fase 2: ciclo de follow-up (si corresponde) ────────────────
        current_profile = prelim_initial
        prelim_revised: PreliminaryProfile | None = None
        follow_up_responses: list[FollowUpResponse] = []
        rounds_executed = 0

        if prelim_initial.has_blocking_contradictions() and prelim_initial.follow_up_questions:
            rounds_executed = 1
            audit.record(
                "follow_up_cycle_1_started",
                {
                    "questions": list(prelim_initial.follow_up_questions),
                    "blocking_contradictions": [
                        c.to_dict()
                        for c in prelim_initial.detected_contradictions
                        if c.severity == "alta"
                    ],
                },
            )

            follow_up_responses = self.advisor.collect_follow_up_responses(
                prelim_initial.follow_up_questions
            )
            audit.record(
                "follow_up_cycle_1_completed",
                {
                    "responses_count": len(follow_up_responses),
                    "responses": [r.to_dict() for r in follow_up_responses],
                },
            )

            prelim_revised = self.ai_client.revise_profile_after_followup(
                kyc,
                financial_goal,
                [r.to_dict() for r in follow_up_responses],
            )
            audit.record(
                "ai_output_revised",
                {
                    "profile": prelim_revised.profile_name,
                    "confidence": prelim_revised.confidence,
                    "binding_dimension": prelim_revised.binding_dimension,
                    "contradictions_count": len(prelim_revised.detected_contradictions),
                },
            )
            current_profile = prelim_revised

        # ── Fase 3: asesor aprueba ─────────────────────────────────────
        # Se pasan AMBOS perfiles: el INICIAL preserva la trazabilidad en
        # ApprovedProfile.original_profile; el VIGENTE es el que el asesor
        # ve al momento de aprobar.
        approved = self.advisor.approve_profile(
            original_preliminary_profile_name=prelim_initial.profile_name,
            current_preliminary_profile_name=current_profile.profile_name,
        )
        audit.record("advisor_profile_approval", approved.to_audit_record())

        # ── Fase 4: cierre ─────────────────────────────────────────────
        audit.record("session_closed", {"reason": "m1_flow_completed"})
        audit.close()

        return M1SessionResult(
            session_id=sid,
            client_id=client_id,
            advisor_id=advisor_id,
            preliminary_profile_initial=prelim_initial,
            preliminary_profile_revised=prelim_revised,
            approved_profile=approved,
            follow_up_responses=follow_up_responses,
            follow_up_rounds_executed=rounds_executed,
            audit=audit,
        )

    @staticmethod
    def _generate_session_id() -> str:
        return f"SES-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"