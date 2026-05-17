"""
Estados del portfolio.

Máquina de estados:
    PortfolioCandidate  →  AdvisorReviewedPortfolio  →  ApprovedPortfolio
                                                              ↓
                                                    ClientSelectedPortfolio

INVARIANTE: solo ApprovedPortfolio puede presentarse al cliente. Los estados
anteriores son internos al sistema y no deben llegar a la capa de cliente.

Esta estructura preserva la diferencia entre:
- preliminary_profile (lo que propone la IA)
- approved_profile    (lo que valida el asesor)
en etapas posteriores del flujo.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class PortfolioStatus(str, Enum):
    GENERATED = "generated"
    REVIEW_PENDING = "review_pending"
    ADVISOR_MODIFIED = "advisor_modified"
    ADVISOR_APPROVED = "advisor_approved"
    CLIENT_SELECTED = "client_selected"
    REJECTED = "rejected"


@dataclass
class PortfolioCandidate:
    """
    Output directo del optimizador. NO presentable al cliente.

    El campo `variant` identifica si es protection / balanced / controlled_growth.
    """

    variant: str
    weights: dict[str, float]
    status: PortfolioStatus = PortfolioStatus.GENERATED
    generated_at: datetime = field(default_factory=datetime.utcnow)
    discard_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.variant.strip():
            raise ValueError("variant no puede estar vacío.")
        if not self.weights:
            raise ValueError("weights no puede estar vacío.")
        weight_sum = sum(self.weights.values())
        if not 0.99 <= weight_sum <= 1.01:
            raise ValueError(
                f"weights debe sumar aproximadamente 1.0, suma actual: {weight_sum:.4f}."
            )
        for ticker, weight in self.weights.items():
            if weight < 0:
                raise ValueError(f"weight de {ticker!r} es negativo: {weight}.")


@dataclass
class AdvisorReviewedPortfolio:
    """El asesor revisó la candidata. Puede haber modificado pesos."""

    candidate: PortfolioCandidate
    advisor_id: str
    reviewed_at: datetime
    modifications: list[str] = field(default_factory=list)
    advisor_comments: str = ""
    status: PortfolioStatus = PortfolioStatus.REVIEW_PENDING

    def __post_init__(self) -> None:
        if not self.advisor_id.strip():
            raise ValueError("advisor_id no puede estar vacío.")

    def approve(self, advisor_id: str) -> "ApprovedPortfolio":
        """Transiciona a ApprovedPortfolio — único estado presentable al cliente."""
        if not advisor_id.strip():
            raise ValueError("advisor_id no puede estar vacío.")
        return ApprovedPortfolio(
            reviewed=self,
            advisor_id=advisor_id,
            approved_at=datetime.utcnow(),
        )

    def reject(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("reason no puede estar vacío al rechazar un portfolio.")
        self.status = PortfolioStatus.REJECTED
        self.candidate.discard_reason = reason


@dataclass
class ApprovedPortfolio:
    """
    Único estado del portfolio que puede ser presentado al cliente.

    INVARIANTE: solo este estado pasa al método select() del cliente.
    """

    reviewed: AdvisorReviewedPortfolio
    advisor_id: str
    approved_at: datetime
    status: PortfolioStatus = PortfolioStatus.ADVISOR_APPROVED

    def __post_init__(self) -> None:
        if not self.advisor_id.strip():
            raise ValueError("advisor_id no puede estar vacío.")

    def select(self, client_id: str) -> "ClientSelectedPortfolio":
        if not client_id.strip():
            raise ValueError("client_id no puede estar vacío.")
        return ClientSelectedPortfolio(
            approved=self,
            client_id=client_id,
            selected_at=datetime.utcnow(),
        )


@dataclass
class ClientSelectedPortfolio:
    """Portfolio finalmente elegido por el cliente."""

    approved: ApprovedPortfolio
    client_id: str
    selected_at: datetime
    status: PortfolioStatus = PortfolioStatus.CLIENT_SELECTED

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise ValueError("client_id no puede estar vacío.")