"""
InstrumentSuitabilityMatrix — matriz de suitability por tipo de instrumento y perfil.

INVARIANTE CENTRAL: que un producto esté aprobado por governance NO significa
que sea suitable para todos los perfiles. Esta capa se ejecuta DESPUÉS de
Product Governance y ANTES de datos, ESG y optimización.

Política M1 conservadora ante reglas faltantes:
    Si no existe regla para (instrument_type, profile_name) en la matriz,
    el sistema devuelve NOT_ALLOWED con reason_code SUITABILITY_RULE_MISSING.
    No se asume permisividad por omisión.

La matriz se carga desde YAML para que governance / compliance pueda
revisarla sin tocar código.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class InstrumentSuitabilityStatus(str, Enum):
    """Estados posibles de suitability para (instrument_type, profile_name)."""

    ALLOWED = "allowed"
    LIMITED = "limited"
    NOT_ALLOWED = "not_allowed"


# Código de motivo cuando falta una regla en la matriz.
# No se importa del módulo reason_codes para no acoplar la matriz a ese catálogo
# en M1 — los tests verifican el string explícitamente.
RULE_MISSING_REASON_CODE = "SUITABILITY_RULE_MISSING"


@dataclass
class InstrumentSuitabilityRule:
    """
    Regla de suitability para una combinación (instrument_type, profile_name).

    Reglas de validación:
        - instrument_type y profile_name no pueden estar vacíos.
        - status debe ser InstrumentSuitabilityStatus.
        - max_allocation debe ser None o estar en [0.0, 1.0].
        - Si status == NOT_ALLOWED, max_allocation debe ser 0.0 o None.
        - Si status == LIMITED, max_allocation debe ser > 0.0 y < 1.0.
        - Si status == ALLOWED, max_allocation puede ser None (sin tope explícito)
          o un valor en (0.0, 1.0]. Acá no hay restricción adicional — un
          instrumento ALLOWED puede tener cap natural por governance/risk budget.
    """

    instrument_type: str
    profile_name: str
    status: InstrumentSuitabilityStatus
    max_allocation: float | None = None
    requires_advisor_note: bool = False
    reason_code: str | None = None
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.instrument_type or not self.instrument_type.strip():
            raise ValueError("instrument_type no puede estar vacío.")
        if not self.profile_name or not self.profile_name.strip():
            raise ValueError("profile_name no puede estar vacío.")
        if not isinstance(self.status, InstrumentSuitabilityStatus):
            raise ValueError(
                f"status debe ser InstrumentSuitabilityStatus, recibido "
                f"{type(self.status).__name__}."
            )
        if not isinstance(self.notes, list):
            raise ValueError("notes debe ser una lista.")

        if self.max_allocation is not None:
            if not isinstance(self.max_allocation, (int, float)):
                raise ValueError(
                    f"max_allocation debe ser numérico o None, recibido "
                    f"{type(self.max_allocation).__name__}."
                )
            if not 0.0 <= float(self.max_allocation) <= 1.0:
                raise ValueError(
                    f"max_allocation debe estar en [0.0, 1.0]. Recibido: "
                    f"{self.max_allocation}."
                )

        if self.status == InstrumentSuitabilityStatus.NOT_ALLOWED:
            if self.max_allocation not in (None, 0.0):
                raise ValueError(
                    f"Para status NOT_ALLOWED, max_allocation debe ser 0.0 o None. "
                    f"Recibido: {self.max_allocation}."
                )

        if self.status == InstrumentSuitabilityStatus.LIMITED:
            if self.max_allocation is None:
                raise ValueError(
                    "Para status LIMITED, max_allocation no puede ser None."
                )
            if not (0.0 < float(self.max_allocation) < 1.0):
                raise ValueError(
                    f"Para status LIMITED, max_allocation debe estar en (0.0, 1.0). "
                    f"Recibido: {self.max_allocation}."
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_type": self.instrument_type,
            "profile_name": self.profile_name,
            "status": self.status.value,
            "max_allocation": self.max_allocation,
            "requires_advisor_note": self.requires_advisor_note,
            "reason_code": self.reason_code,
            "notes": list(self.notes),
        }


class InstrumentSuitabilityMatrix:
    """
    Matriz indexada por (instrument_type, profile_name).

    Una vez construida es de solo lectura. Las consultas más usadas son
    `evaluate` (regla efectiva, con fallback sintético) y los helpers
    `is_allowed` / `is_limited` / `is_not_allowed`.
    """

    def __init__(self, rules: list[InstrumentSuitabilityRule]):
        self._rules: dict[tuple[str, str], InstrumentSuitabilityRule] = {}
        for r in rules:
            key = (r.instrument_type, r.profile_name)
            if key in self._rules:
                raise ValueError(
                    f"Regla duplicada en la matriz: instrument_type="
                    f"{r.instrument_type!r}, profile_name={r.profile_name!r}."
                )
            self._rules[key] = r

    # ── Carga desde YAML ──────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str | Path) -> "InstrumentSuitabilityMatrix":
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(
                f"Archivo de matriz no encontrado: {yaml_path}."
            )

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
        if "rules" not in data:
            raise ValueError(
                f"YAML inválido en {yaml_path}: falta la clave 'rules' en la raíz."
            )
        if not isinstance(data["rules"], list):
            raise ValueError(
                f"YAML inválido en {yaml_path}: 'rules' debe ser una lista."
            )

        rules: list[InstrumentSuitabilityRule] = []
        for idx, raw in enumerate(data["rules"]):
            if not isinstance(raw, dict):
                raise ValueError(
                    f"YAML inválido en {yaml_path}: regla #{idx} no es un mapping."
                )
            rules.append(cls._rule_from_dict(raw, source=str(yaml_path), index=idx))
        return cls(rules)

    @staticmethod
    def _rule_from_dict(
        raw: dict[str, Any],
        source: str,
        index: int,
    ) -> InstrumentSuitabilityRule:
        try:
            status_raw = raw["status"]
        except KeyError as exc:
            raise ValueError(
                f"YAML inválido en {source}: regla #{index} no tiene 'status'."
            ) from exc

        try:
            status = InstrumentSuitabilityStatus(status_raw)
        except ValueError as exc:
            valid = [s.value for s in InstrumentSuitabilityStatus]
            raise ValueError(
                f"YAML inválido en {source}: status {status_raw!r} en regla #{index} "
                f"no es válido. Opciones: {valid}."
            ) from exc

        try:
            return InstrumentSuitabilityRule(
                instrument_type=raw["instrument_type"],
                profile_name=raw["profile_name"],
                status=status,
                max_allocation=raw.get("max_allocation"),
                requires_advisor_note=bool(raw.get("requires_advisor_note", False)),
                reason_code=raw.get("reason_code"),
                notes=list(raw.get("notes", [])),
            )
        except KeyError as exc:
            raise ValueError(
                f"YAML inválido en {source}: regla #{index} falta el campo "
                f"{exc.args[0]!r}."
            ) from exc
        except ValueError as exc:
            # Errores de validación del dataclass se propagan con contexto.
            raise ValueError(
                f"YAML inválido en {source}: regla #{index} es inválida: {exc}"
            ) from exc

    # ── Consultas ─────────────────────────────────────────────────────────

    def get_rule(
        self,
        instrument_type: str,
        profile_name: str,
    ) -> InstrumentSuitabilityRule | None:
        """Devuelve la regla exacta o None si no existe en la matriz."""
        return self._rules.get((instrument_type, profile_name))

    def evaluate(
        self,
        instrument_type: str,
        profile_name: str,
    ) -> InstrumentSuitabilityRule:
        """
        Devuelve la regla efectiva. Siempre devuelve un InstrumentSuitabilityRule.

        Si no hay regla en la matriz, devuelve una regla sintética NOT_ALLOWED
        con reason_code SUITABILITY_RULE_MISSING.
        """
        if not instrument_type or not instrument_type.strip():
            raise ValueError("instrument_type no puede estar vacío.")
        if not profile_name or not profile_name.strip():
            raise ValueError("profile_name no puede estar vacío.")

        existing = self._rules.get((instrument_type, profile_name))
        if existing is not None:
            return existing

        return InstrumentSuitabilityRule(
            instrument_type=instrument_type,
            profile_name=profile_name,
            status=InstrumentSuitabilityStatus.NOT_ALLOWED,
            max_allocation=0.0,
            requires_advisor_note=False,
            reason_code=RULE_MISSING_REASON_CODE,
            notes=[
                f"No existe regla de suitability para instrument_type="
                f"{instrument_type!r} y profile_name={profile_name!r}. "
                "Política M1 conservadora: NOT_ALLOWED por defecto."
            ],
        )

    def is_allowed(self, instrument_type: str, profile_name: str) -> bool:
        return self.evaluate(instrument_type, profile_name).status == \
            InstrumentSuitabilityStatus.ALLOWED

    def is_limited(self, instrument_type: str, profile_name: str) -> bool:
        return self.evaluate(instrument_type, profile_name).status == \
            InstrumentSuitabilityStatus.LIMITED

    def is_not_allowed(self, instrument_type: str, profile_name: str) -> bool:
        return self.evaluate(instrument_type, profile_name).status == \
            InstrumentSuitabilityStatus.NOT_ALLOWED

    def all_rules(self) -> list[InstrumentSuitabilityRule]:
        """Copia defensiva: modificar la lista no altera la matriz."""
        return list(self._rules.values())

    def exclusion_report(
        self,
        instrument_types: list[str],
        profile_name: str,
    ) -> list[dict[str, Any]]:
        """
        Reporte de instrument_types que no son ALLOWED para el perfil dado.

        LIMITED y NOT_ALLOWED entran al reporte porque ambos imponen
        restricciones (allocation tope o exclusión total). El consumidor
        decide cómo presentarlos.
        """
        if not profile_name or not profile_name.strip():
            raise ValueError("profile_name no puede estar vacío.")

        report: list[dict[str, Any]] = []
        for instrument_type in instrument_types:
            rule = self.evaluate(instrument_type, profile_name)
            if rule.status == InstrumentSuitabilityStatus.ALLOWED:
                continue
            report.append({
                "instrument_type": rule.instrument_type,
                "profile_name": rule.profile_name,
                "status": rule.status.value,
                "max_allocation": rule.max_allocation,
                "requires_advisor_note": rule.requires_advisor_note,
                "reason_code": rule.reason_code,
                "notes": list(rule.notes),
            })
        return report

    def __len__(self) -> int:
        return len(self._rules)