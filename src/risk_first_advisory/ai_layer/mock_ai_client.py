"""
MockAIClient — cliente de IA scripted para tests M1.

No usa Anthropic ni ningún modelo real. Devuelve respuestas pre-configuradas
desde el `ai_script` del fixture. Permite ejercitar el flujo completo sin
costos de API ni variabilidad de respuestas.

Contrato mínimo para M1 (sin portfolios):
    - propose_preliminary_profile(kyc, goal) → PreliminaryProfile
    - revise_profile_after_followup(kyc, goal, follow_up_responses) → PreliminaryProfile
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Contradiction:
    """Contradicción detectada por la IA."""

    code: str
    description: str
    severity: str  # "alta" | "media" | "baja"
    suggested_follow_up: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "description": self.description,
            "severity": self.severity,
            "suggested_follow_up": self.suggested_follow_up,
        }


@dataclass
class PreliminaryProfile:
    """
    Perfil preliminar propuesto por la IA.

    Es el output de la capa A. SIEMPRE requiere revisión del asesor.
    Es conceptualmente distinto del approved_profile (que sale del asesor).
    """

    profile_name: str
    confidence: float
    binding_dimension: str  # "tolerance" | "capacity"
    risk_tolerance: str
    risk_capacity: str
    risk_need: str
    detected_contradictions: list[Contradiction] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)
    advisor_review_required: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence debe estar en [0.0, 1.0], recibido {self.confidence}.")
        if self.binding_dimension not in {"tolerance", "capacity"}:
            raise ValueError(
                f"binding_dimension inválido: {self.binding_dimension!r}. "
                "Opciones: tolerance, capacity."
            )
        if not self.advisor_review_required:
            raise ValueError(
                "advisor_review_required debe ser True. La IA nunca toma decisiones finales."
            )

    def has_blocking_contradictions(self) -> bool:
        """Una contradicción de severidad alta bloquea el avance del flujo."""
        return any(c.severity == "alta" for c in self.detected_contradictions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "confidence": self.confidence,
            "binding_dimension": self.binding_dimension,
            "risk_tolerance": self.risk_tolerance,
            "risk_capacity": self.risk_capacity,
            "risk_need": self.risk_need,
            "detected_contradictions": [c.to_dict() for c in self.detected_contradictions],
            "follow_up_questions": list(self.follow_up_questions),
            "advisor_review_required": self.advisor_review_required,
        }


class MockAIClient:
    """
    Cliente de IA scripted. Devuelve respuestas pre-configuradas.

    El `ai_script` tiene la forma:
        {
            "initial_profile_response": { ... },
            "revised_profile_after_followup": { ... }
        }

    Cada respuesta es un dict con los campos de PreliminaryProfile.
    Las contradicciones se pasan como lista de dicts y se hidratan a Contradiction.
    """

    def __init__(self, scripted_responses: dict[str, Any]):
        if "initial_profile_response" not in scripted_responses:
            raise ValueError(
                "ai_script debe contener 'initial_profile_response'."
            )
        self._script = scripted_responses
        self._initial_call_count = 0
        self._revised_call_count = 0

    def propose_preliminary_profile(self, kyc: Any, goal: Any) -> PreliminaryProfile:
        """
        Propone el perfil preliminar inicial.

        Para M1, simplemente devuelve la respuesta scripted.
        En implementación real, llamaría a Anthropic con el prompt build_profile.
        """
        self._initial_call_count += 1
        return self._hydrate(self._script["initial_profile_response"])

    def revise_profile_after_followup(
        self,
        kyc: Any,
        goal: Any,
        follow_up_responses: list[dict[str, Any]],
    ) -> PreliminaryProfile:
        """
        Re-evalúa el perfil con las respuestas adicionales del asesor.

        Para M1, devuelve la respuesta scripted en revised_profile_after_followup.
        En implementación real, llamaría a Anthropic con KYC enriquecido.
        """
        if "revised_profile_after_followup" not in self._script:
            raise RuntimeError(
                "El script no incluye 'revised_profile_after_followup', "
                "pero el flujo invocó revise_profile_after_followup."
            )
        self._revised_call_count += 1
        return self._hydrate(self._script["revised_profile_after_followup"])

    @property
    def initial_call_count(self) -> int:
        return self._initial_call_count

    @property
    def revised_call_count(self) -> int:
        return self._revised_call_count

    @staticmethod
    def _hydrate(payload: dict[str, Any]) -> PreliminaryProfile:
        """Construye un PreliminaryProfile desde el dict scripted."""
        contradictions_raw = payload.get("detected_contradictions", [])
        contradictions = [
            Contradiction(
                code=c["code"],
                description=c["description"],
                severity=c["severity"],
                suggested_follow_up=c["suggested_follow_up"],
            )
            for c in contradictions_raw
        ]
        return PreliminaryProfile(
            profile_name=payload["profile_name"],
            confidence=float(payload["confidence"]),
            binding_dimension=payload["binding_dimension"],
            risk_tolerance=payload["risk_tolerance"],
            risk_capacity=payload["risk_capacity"],
            risk_need=payload["risk_need"],
            detected_contradictions=contradictions,
            follow_up_questions=list(payload.get("follow_up_questions", [])),
            advisor_review_required=payload.get("advisor_review_required", True),
        )