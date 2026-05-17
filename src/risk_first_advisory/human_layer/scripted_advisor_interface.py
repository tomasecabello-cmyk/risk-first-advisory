"""
ScriptedAdvisorInterface — interfaz del asesor scripted para tests.

No interactúa con un humano real. Lee decisiones pre-configuradas del
`advisor_script` del fixture. Permite correr el flujo end-to-end en CI
y en tests de regresión.

Contrato para M1 (sin portfolios):
    - collect_follow_up_responses(questions) → list[FollowUpResponse]
    - approve_profile(original_preliminary_profile_name,
                      current_preliminary_profile_name) → ApprovedProfile

INVARIANTE: ApprovedProfile.original_profile preserva SIEMPRE el perfil
inicial propuesto por la IA, no el revisado tras follow-up. Esto garantiza
que la trazabilidad de la modificación del asesor (IA inicial → asesor final)
quede registrada correctamente en el audit trail.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

MIN_ADVISOR_COMMENT_LEN = 30


@dataclass
class FollowUpResponse:
    """Respuesta del asesor a una pregunta de seguimiento."""

    question: str
    answer: str
    answered_by: str  # "advisor" | "client_via_advisor"
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "answered_by": self.answered_by,
            "timestamp_utc": self.timestamp_utc,
        }


@dataclass
class ApprovedProfile:
    """
    Perfil aprobado por el asesor.

    INVARIANTE: este es un objeto CONCEPTUALMENTE DISTINTO de PreliminaryProfile.
    Toda diferencia entre `original_profile` y `profile_name` exige
    `advisor_comment` con mínimo 30 caracteres.

    `original_profile` debe contener el perfil INICIAL propuesto por la IA
    (antes de cualquier follow-up). Eso preserva la trazabilidad de la
    modificación del asesor.
    """

    profile_name: str
    original_profile: str  # el preliminary_profile INICIAL que la IA propuso
    advisor_id: str
    advisor_comment: str
    approved_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if not self.profile_name.strip():
            raise ValueError("profile_name no puede estar vacío.")
        if not self.original_profile.strip():
            raise ValueError("original_profile no puede estar vacío.")
        if not self.advisor_id.strip():
            raise ValueError("advisor_id no puede estar vacío.")
        if self.is_modified and len(self.advisor_comment.strip()) < MIN_ADVISOR_COMMENT_LEN:
            raise ValueError(
                f"Cuando el asesor modifica el perfil propuesto por la IA, "
                f"advisor_comment debe tener mínimo {MIN_ADVISOR_COMMENT_LEN} caracteres. "
                f"Recibido: {len(self.advisor_comment.strip())} caracteres."
            )

    @property
    def is_modified(self) -> bool:
        return self.profile_name != self.original_profile

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "original": self.original_profile,
            "approved": self.profile_name,
            "modified": self.is_modified,
            "advisor_id": self.advisor_id,
            "advisor_comment": self.advisor_comment,
            "approved_at_utc": self.approved_at_utc,
        }


class ScriptedAdvisorInterface:
    """
    Interfaz del asesor scripted. Lee decisiones del fixture.

    Estructura esperada del `advisor_script`:
        {
            "follow_up_responses": [
                {"question": "...", "answer": "...", "answered_by": "advisor"},
                ...
            ],
            "profile_approval": {
                "decision": "approve_as_revised" | "approve_as_proposed" | "modify",
                "approved_profile": "moderado",
                "advisor_comment": "..."
            }
        }
    """

    def __init__(self, scripted_decisions: dict[str, Any]):
        if "profile_approval" not in scripted_decisions:
            raise ValueError("advisor_script debe contener 'profile_approval'.")
        self._script = scripted_decisions
        self._advisor_id = scripted_decisions.get("advisor_id", "ADV-SCRIPTED")

    def collect_follow_up_responses(
        self,
        questions: list[str],
    ) -> list[FollowUpResponse]:
        """
        Devuelve las respuestas scripted para las preguntas de follow-up.

        El script debe tener una respuesta por cada pregunta esperada. Si
        faltan respuestas, falla explícitamente — esto fuerza que los fixtures
        estén alineados con lo que la IA mock va a proponer.
        """
        scripted = self._script.get("follow_up_responses", [])
        if len(scripted) < len(questions):
            raise RuntimeError(
                f"El script tiene {len(scripted)} respuestas pero se pidieron "
                f"{len(questions)} preguntas. Ajustar el fixture."
            )
        responses = []
        for i, question in enumerate(questions):
            entry = scripted[i]
            responses.append(
                FollowUpResponse(
                    question=entry.get("question", question),
                    answer=entry["answer"],
                    answered_by=entry.get("answered_by", "advisor"),
                )
            )
        return responses

    def approve_profile(
        self,
        original_preliminary_profile_name: str,
        current_preliminary_profile_name: str,
    ) -> ApprovedProfile:
        """
        Devuelve el perfil aprobado por el asesor.

        Recibe dos argumentos distintos:
            - original_preliminary_profile_name: lo que la IA propuso AL INICIO
              (antes de cualquier follow-up). Queda en ApprovedProfile.original_profile
              para preservar la trazabilidad.
            - current_preliminary_profile_name: lo que la IA propone AHORA
              (puede ser el inicial si no hubo follow-up, o el revisado si lo hubo).
              No se persiste directamente — solo se usa como contexto para validar
              que el asesor revisó el estado vigente del perfil.

        Si el asesor modifica el perfil respecto del original, el ApprovedProfile
        lo refleja con is_modified=True y requiere advisor_comment válido.
        """
        if not original_preliminary_profile_name.strip():
            raise ValueError("original_preliminary_profile_name no puede estar vacío.")
        if not current_preliminary_profile_name.strip():
            raise ValueError("current_preliminary_profile_name no puede estar vacío.")

        approval = self._script["profile_approval"]
        approved_name = approval["approved_profile"]
        comment = approval.get("advisor_comment", "")
        return ApprovedProfile(
            profile_name=approved_name,
            original_profile=original_preliminary_profile_name,
            advisor_id=self._advisor_id,
            advisor_comment=comment,
        )

    @property
    def advisor_id(self) -> str:
        return self._advisor_id
