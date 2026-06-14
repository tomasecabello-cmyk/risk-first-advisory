"""
ApprovedProductUniverse — capa de governance del universo de productos.

INVARIANTE CENTRAL: el universo de inversión nace de governance, NO de
Bloomberg ni del proveedor de datos. Esta capa se ejecuta ANTES de descargar
cualquier dato de mercado, antes de filtros ESG, antes de suitability por
instrumento y antes del optimizador.

Estados de un producto:
    APPROVED              uso pleno dentro de los perfiles permitidos
    WATCHLIST             uso permitido + advertencia que el asesor debe ver
    RESTRICTED            política conservadora: NO pasa nunca
    TEMPORARILY_SUSPENDED bloqueado temporalmente
    PROHIBITED            nunca utilizable

POLÍTICA DE M1 (conservadora):
    - RESTRICTED no pasa nunca.
    - TEMPORARILY_SUSPENDED no pasa.
    - PROHIBITED no pasa.
    - review_due_date vencida → producto bloqueado hasta nueva revisión.

Esta política puede flexibilizarse en versiones futuras (por ejemplo, dejando
pasar RESTRICTED si el perfil aparece explícitamente en allowed_profiles y no
en restricted_profiles), pero en M1 se mantiene estricta para simplificar
auditoría y compliance.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class ProductGovernanceStatus(str, Enum):
    """Estados posibles de un producto en el universo aprobado."""

    APPROVED = "approved"
    WATCHLIST = "watchlist"
    RESTRICTED = "restricted"
    TEMPORARILY_SUSPENDED = "temporarily_suspended"
    PROHIBITED = "prohibited"


@dataclass
class ProductGovernanceRecord:
    """
    Ficha de governance de un producto.

    Validaciones:
        - ticker, name, instrument_type no pueden estar vacíos.
        - status debe ser ProductGovernanceStatus.
        - allowed_profiles y restricted_profiles deben ser listas.
        - Un perfil no puede estar simultáneamente en allowed y restricted.
    """

    ticker: str
    name: str
    instrument_type: str
    status: ProductGovernanceStatus
    allowed_profiles: list[str] = field(default_factory=list)
    restricted_profiles: list[str] = field(default_factory=list)
    review_due_date: str | None = None
    notes: list[str] = field(default_factory=list)
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not self.ticker or not self.ticker.strip():
            raise ValueError("ticker no puede estar vacío.")
        if not self.name or not self.name.strip():
            raise ValueError("name no puede estar vacío.")
        if not self.instrument_type or not self.instrument_type.strip():
            raise ValueError("instrument_type no puede estar vacío.")
        if not isinstance(self.status, ProductGovernanceStatus):
            raise ValueError(
                f"status debe ser ProductGovernanceStatus, recibido {type(self.status).__name__}."
            )
        if not isinstance(self.allowed_profiles, list):
            raise ValueError("allowed_profiles debe ser una lista.")
        if not isinstance(self.restricted_profiles, list):
            raise ValueError("restricted_profiles debe ser una lista.")

        # Un perfil no puede estar en ambas listas
        conflicting = set(self.allowed_profiles) & set(self.restricted_profiles)
        if conflicting:
            raise ValueError(
                f"Los perfiles {sorted(conflicting)} no pueden estar simultáneamente "
                f"en allowed_profiles y restricted_profiles del producto {self.ticker!r}."
            )

    def is_review_overdue(self, as_of: date | None = None) -> bool:
        """True si el review_due_date está en el pasado respecto a `as_of`."""
        if self.review_due_date is None:
            return False
        reference = as_of or date.today()
        try:
            due = date.fromisoformat(self.review_due_date)
        except ValueError as exc:
            raise ValueError(
                f"review_due_date inválido en {self.ticker!r}: {self.review_due_date!r}. "
                "Debe ser ISO 8601 (YYYY-MM-DD)."
            ) from exc
        return due < reference

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "instrument_type": self.instrument_type,
            "status": self.status.value,
            "allowed_profiles": list(self.allowed_profiles),
            "restricted_profiles": list(self.restricted_profiles),
            "review_due_date": self.review_due_date,
            "notes": list(self.notes),
            "reason_code": self.reason_code,
        }


class ApprovedProductUniverse:
    """
    Universo de productos aprobados por la firma.

    Se carga desde YAML y se consulta por ticker o por perfil.
    """

    def __init__(self, records: list[ProductGovernanceRecord]):
        self._records: dict[str, ProductGovernanceRecord] = {}
        for r in records:
            if r.ticker in self._records:
                raise ValueError(
                    f"Ticker duplicado en el universo: {r.ticker!r}."
                )
            self._records[r.ticker] = r

    # ── Carga desde YAML ──────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ApprovedProductUniverse":
        """Carga el universo desde un archivo YAML."""
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Archivo de universo no encontrado: {yaml_path}.")

        try:
            with yaml_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ValueError(
                f"YAML inválido en {yaml_path}: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"YAML inválido en {yaml_path}: el documento raíz debe ser un mapping."
            )
        if "products" not in data:
            raise ValueError(
                f"YAML inválido en {yaml_path}: falta la clave 'products' en la raíz."
            )
        if not isinstance(data["products"], list):
            raise ValueError(
                f"YAML inválido en {yaml_path}: 'products' debe ser una lista."
            )

        records: list[ProductGovernanceRecord] = []
        for idx, raw in enumerate(data["products"]):
            if not isinstance(raw, dict):
                raise ValueError(
                    f"YAML inválido en {yaml_path}: producto #{idx} no es un mapping."
                )
            records.append(cls._record_from_dict(raw, source=str(yaml_path), index=idx))
        return cls(records)

    @staticmethod
    def _record_from_dict(
        raw: dict[str, Any],
        source: str,
        index: int,
    ) -> ProductGovernanceRecord:
        try:
            status_raw = raw["status"]
        except KeyError as exc:
            raise ValueError(
                f"YAML inválido en {source}: producto #{index} no tiene 'status'."
            ) from exc

        try:
            status = ProductGovernanceStatus(status_raw)
        except ValueError as exc:
            valid = [s.value for s in ProductGovernanceStatus]
            raise ValueError(
                f"YAML inválido en {source}: status {status_raw!r} en producto #{index} "
                f"no es válido. Opciones: {valid}."
            ) from exc

        try:
            return ProductGovernanceRecord(
                ticker=raw["ticker"],
                name=raw["name"],
                instrument_type=raw["instrument_type"],
                status=status,
                allowed_profiles=list(raw.get("allowed_profiles", [])),
                restricted_profiles=list(raw.get("restricted_profiles", [])),
                review_due_date=raw.get("review_due_date"),
                notes=list(raw.get("notes", [])),
                reason_code=raw.get("reason_code"),
            )
        except KeyError as exc:
            raise ValueError(
                f"YAML inválido en {source}: producto #{index} falta el campo {exc.args[0]!r}."
            ) from exc

    # ── Consultas básicas ─────────────────────────────────────────────────

    def contains(self, ticker: str) -> bool:
        return ticker in self._records

    def get(self, ticker: str) -> ProductGovernanceRecord | None:
        """Devuelve el record o None si el ticker no está en el universo."""
        return self._records.get(ticker)

    def all_records(self) -> list[ProductGovernanceRecord]:
        """Copia defensiva del universo completo."""
        return list(self._records.values())

    def approved_records(self) -> list[ProductGovernanceRecord]:
        """
        Records con status APPROVED o WATCHLIST.

        Excluye RESTRICTED, TEMPORARILY_SUSPENDED y PROHIBITED.
        No considera perfiles ni vencimiento de review — eso es para filter_for_profile.
        """
        passable = {ProductGovernanceStatus.APPROVED, ProductGovernanceStatus.WATCHLIST}
        return [r for r in self._records.values() if r.status in passable]

    # ── Filtrado por perfil ───────────────────────────────────────────────

    def filter_for_profile(
        self,
        profile_name: str,
        as_of: date | None = None,
    ) -> list[ProductGovernanceRecord]:
        """
        Devuelve los records que pueden usarse para el perfil dado.

        POLÍTICA DE M1 (conservadora):
            - status debe ser APPROVED o WATCHLIST.
            - review_due_date no puede estar vencido.
            - profile_name no debe estar en restricted_profiles.
            - Si allowed_profiles tiene contenido, profile_name debe estar en él.
              Si allowed_profiles está vacío, se interpreta como "abierto a todos
              los perfiles compatibles con el resto de las reglas".
        """
        if not profile_name or not profile_name.strip():
            raise ValueError("profile_name no puede estar vacío.")

        result: list[ProductGovernanceRecord] = []
        for r in self._records.values():
            if self._passes_for_profile(r, profile_name, as_of):
                result.append(r)
        return result

    def exclusion_report_for_profile(
        self,
        profile_name: str,
        as_of: date | None = None,
    ) -> list[dict[str, Any]]:
        """
        Devuelve la lista de productos EXCLUIDOS para el perfil con el motivo.

        Cada entrada contiene: ticker, status, reason, reason_code, notes.
        """
        if not profile_name or not profile_name.strip():
            raise ValueError("profile_name no puede estar vacío.")

        report: list[dict[str, Any]] = []
        for r in self._records.values():
            passed, reason = self._evaluate_for_profile(r, profile_name, as_of)
            if not passed:
                report.append({
                    "ticker": r.ticker,
                    "status": r.status.value,
                    "reason": reason,
                    "reason_code": r.reason_code,
                    "notes": list(r.notes),
                })
        return report

    # ── Lógica de evaluación ──────────────────────────────────────────────

    def _passes_for_profile(
        self,
        record: ProductGovernanceRecord,
        profile_name: str,
        as_of: date | None,
    ) -> bool:
        passed, _ = self._evaluate_for_profile(record, profile_name, as_of)
        return passed

    @staticmethod
    def _evaluate_for_profile(
        record: ProductGovernanceRecord,
        profile_name: str,
        as_of: date | None,
    ) -> tuple[bool, str]:
        """
        Decide si un producto pasa para el perfil dado.

        Devuelve (passes, reason). Si pasa, reason describe el motivo de
        admisión (relevante para WATCHLIST). Si no pasa, reason explica
        por qué fue excluido.
        """
        if record.status == ProductGovernanceStatus.PROHIBITED:
            return False, "Producto prohibido por política de la firma."

        if record.status == ProductGovernanceStatus.TEMPORARILY_SUSPENDED:
            return False, "Producto temporalmente suspendido por governance."

        if record.status == ProductGovernanceStatus.RESTRICTED:
            return False, (
                "Producto RESTRICTED — política M1 conservadora no admite "
                "productos restringidos."
            )

        if record.is_review_overdue(as_of):
            return False, (
                f"Revisión de governance vencida desde {record.review_due_date}. "
                "Bloqueado hasta nueva revisión."
            )

        if profile_name in record.restricted_profiles:
            return False, (
                f"Perfil {profile_name!r} está en restricted_profiles del producto."
            )

        if record.allowed_profiles and profile_name not in record.allowed_profiles:
            return False, (
                f"Perfil {profile_name!r} no está en allowed_profiles "
                f"({record.allowed_profiles})."
            )

        # En este punto, status es APPROVED o WATCHLIST.
        if record.status == ProductGovernanceStatus.WATCHLIST:
            return True, "Producto en WATCHLIST — requiere atención del asesor."

        return True, "Producto aprobado para el perfil."

    # ── Utilidades ────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, ticker: str) -> bool:
        return self.contains(ticker)


def is_watchlist(record: ProductGovernanceRecord) -> bool:
    """Helper para identificar rápidamente productos en watchlist."""
    return record.status == ProductGovernanceStatus.WATCHLIST
