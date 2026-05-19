"""
AdvisorOverrideApproval — registro formal de la decisión del asesor cuando una
variante de portfolio requiere override explícito (ej. GROWTH excede RiskBudget).

Responsabilidades:
    - AdvisorOverrideApproval: dataclass con validaciones y serialización.
    - AdvisorOverrideApprovalService: crea y valida aprobaciones/rechazos.

No persiste todavía. No expone endpoints todavía.
La firma digital del asesor y el audit trail de override quedan para la capa
de workflow/UI futura.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from risk_first_advisory.portfolio_layer.generation import (
    PortfolioVariant,
    PortfolioVariantMetadata,
    RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OverrideDecision(Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class OverrideApprovalStatus(Enum):
    VALID = "VALID"
    INVALID = "INVALID"


# ---------------------------------------------------------------------------
# AdvisorOverrideApproval
# ---------------------------------------------------------------------------


@dataclass
class AdvisorOverrideApproval:
    """
    Registro formal de la decisión del asesor sobre una variante que requiere override.

    Invariantes:
        - Todos los campos string obligatorios no pueden estar vacíos.
        - advisor_comment debe tener al menos 20 caracteres.
        - variant debe ser PortfolioVariant.
        - decision debe ser OverrideDecision.
        - reason_codes y exceeded_constraints deben ser listas.
        - status debe ser OverrideApprovalStatus.
    """

    approval_id: str
    workflow_record_id: str
    client_id: str
    advisor_id: str
    variant: PortfolioVariant
    decision: OverrideDecision
    reason_codes: list[str]
    exceeded_constraints: list[str]
    advisor_comment: str
    approved_at_utc: str
    status: OverrideApprovalStatus

    _COMMENT_MIN_LEN: int = field(default=20, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # --- string fields no vacíos ---
        if not isinstance(self.approval_id, str) or not self.approval_id.strip():
            raise ValueError("approval_id no puede estar vacío.")
        if not isinstance(self.workflow_record_id, str) or not self.workflow_record_id.strip():
            raise ValueError("workflow_record_id no puede estar vacío.")
        if not isinstance(self.client_id, str) or not self.client_id.strip():
            raise ValueError("client_id no puede estar vacío.")
        if not isinstance(self.advisor_id, str) or not self.advisor_id.strip():
            raise ValueError("advisor_id no puede estar vacío.")
        if not isinstance(self.advisor_comment, str) or not self.advisor_comment.strip():
            raise ValueError("advisor_comment no puede estar vacío.")
        if len(self.advisor_comment.strip()) < 20:
            raise ValueError(
                f"advisor_comment debe tener al menos 20 caracteres. "
                f"Recibido: {len(self.advisor_comment.strip())} caracteres."
            )
        if not isinstance(self.approved_at_utc, str) or not self.approved_at_utc.strip():
            raise ValueError("approved_at_utc no puede estar vacío.")

        # --- enum fields ---
        if not isinstance(self.variant, PortfolioVariant):
            raise ValueError(
                f"variant debe ser PortfolioVariant. Recibido: {type(self.variant).__name__}."
            )
        if not isinstance(self.decision, OverrideDecision):
            raise ValueError(
                f"decision debe ser OverrideDecision. Recibido: {type(self.decision).__name__}."
            )
        if not isinstance(self.status, OverrideApprovalStatus):
            raise ValueError(
                f"status debe ser OverrideApprovalStatus. Recibido: {type(self.status).__name__}."
            )

        # --- list fields ---
        if not isinstance(self.reason_codes, list):
            raise ValueError(
                f"reason_codes debe ser list. Recibido: {type(self.reason_codes).__name__}."
            )
        if not isinstance(self.exceeded_constraints, list):
            raise ValueError(
                f"exceeded_constraints debe ser list. "
                f"Recibido: {type(self.exceeded_constraints).__name__}."
            )

    # --- propiedades de conveniencia ---

    @property
    def is_approved(self) -> bool:
        return self.decision == OverrideDecision.APPROVED

    @property
    def is_rejected(self) -> bool:
        return self.decision == OverrideDecision.REJECTED

    # --- serialización ---

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "workflow_record_id": self.workflow_record_id,
            "client_id": self.client_id,
            "advisor_id": self.advisor_id,
            "variant": self.variant.value,
            "decision": self.decision.value,
            "reason_codes": list(self.reason_codes),
            "exceeded_constraints": list(self.exceeded_constraints),
            "advisor_comment": self.advisor_comment,
            "approved_at_utc": self.approved_at_utc,
            "status": self.status.value,
        }


# ---------------------------------------------------------------------------
# AdvisorOverrideApprovalService
# ---------------------------------------------------------------------------


class AdvisorOverrideApprovalService:
    """
    Crea registros formales de aprobación/rechazo de advisor override.

    Reglas:
        - Solo puede crear un approval si variant_metadata.requires_advisor_override
          es True. Si es False, levanta ValueError.
        - Copia reason_codes y exceeded_constraints desde variant_metadata.
        - Genera approval_id con prefijo "override_" más timestamp UTC.
        - approved_at_utc es ISO format con timezone UTC.
        - status siempre VALID si se crea correctamente.
    """

    @staticmethod
    def _generate_approval_id() -> str:
        now = datetime.now(tz=timezone.utc)
        return f"override_{now.strftime('%Y%m%d_%H%M%S')}"

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    def evaluate_and_create(
        self,
        workflow_record_id: str,
        client_id: str,
        advisor_id: str,
        variant_metadata: PortfolioVariantMetadata,
        decision: OverrideDecision,
        advisor_comment: str,
    ) -> AdvisorOverrideApproval:
        """
        Evalúa la metadata de una variante y registra la decisión del asesor.

        Args:
            workflow_record_id: ID del workflow al que pertenece esta decisión.
            client_id: ID del cliente.
            advisor_id: ID del asesor que aprueba/rechaza.
            variant_metadata: PortfolioVariantMetadata de la variante a revisar.
            decision: APPROVED o REJECTED.
            advisor_comment: Justificación del asesor (mínimo 20 caracteres).

        Returns:
            AdvisorOverrideApproval con status VALID.

        Raises:
            ValueError: Si variant_metadata.requires_advisor_override es False.
            ValueError: Si advisor_comment es vacío o menor a 20 caracteres.
        """
        if not variant_metadata.requires_advisor_override:
            raise ValueError(
                f"La variante {variant_metadata.variant.value!r} no requiere advisor override "
                f"(requires_advisor_override=False). No se puede registrar una aprobación/rechazo "
                f"para una variante dentro del RiskBudget aprobado."
            )

        approval_id = self._generate_approval_id()
        approved_at_utc = self._utc_now_iso()

        return AdvisorOverrideApproval(
            approval_id=approval_id,
            workflow_record_id=workflow_record_id,
            client_id=client_id,
            advisor_id=advisor_id,
            variant=variant_metadata.variant,
            decision=decision,
            reason_codes=list(variant_metadata.reason_codes),
            exceeded_constraints=list(variant_metadata.exceeded_constraints),
            advisor_comment=advisor_comment,
            approved_at_utc=approved_at_utc,
            status=OverrideApprovalStatus.VALID,
        )
