"""
ESGComplianceChecker — evaluación ESG y moral de instrumentos.

INVARIANTE CENTRAL: hard_exclusions BLOQUEAN instrumentos. soft_preferences
NO bloquean; generan score_adjustment / warnings / notas que las etapas
posteriores (suitability score, optimizador) pueden usar como penalización.

Política M1 ante metadata faltante:
    Si no hay metadata ESG para un ticker, status = UNKNOWN con warning y
    reason_code ESG_METADATA_MISSING. NO se bloquea automáticamente — la
    decisión de tratamiento queda en las capas superiores.
    Razón: bloquear todo lo que falte metadata haría imposible operar en
    universos donde ESG no está completamente cubierto. La trazabilidad
    queda en el reason_code para que el asesor pueda decidir.

Política sobre score_adjustment cuando hay hard exclusion:
    Cuando un instrumento queda BLOCKED, soft_preferences NO se evalúan.
    score_adjustment se reporta como 0.0 en ese caso — el instrumento no
    llega al optimizador, así que el ajuste de score es irrelevante. Esto
    evita doble penalización y simplifica el contrato del result.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from risk_first_advisory.kyc.models import ESGExclusion, ESGPreference, ESGProfile


# Códigos de motivo específicos de ESG.
# Las capas superiores pueden mapearlos al catálogo de ReasonCode si lo desean.
REASON_METADATA_MISSING = "ESG_METADATA_MISSING"
REASON_DATA_INCOMPLETE = "ESG_DATA_INCOMPLETE"
REASON_HARD_EXCLUSION_SECTOR = "ESG_HARD_EXCLUSION_SECTOR"
REASON_HARD_EXCLUSION_TAG = "ESG_HARD_EXCLUSION_TAG"
REASON_HARD_EXCLUSION_ISSUER = "ESG_HARD_EXCLUSION_ISSUER"
REASON_HARD_EXCLUSION_CONTROVERSY = "ESG_HARD_EXCLUSION_CONTROVERSY"
REASON_SOFT_MIN_ESG_SCORE = "ESG_SOFT_MIN_ESG_SCORE"
REASON_SOFT_MAX_CARBON = "ESG_SOFT_MAX_CARBON_INTENSITY"
REASON_SOFT_PREFER_TAG = "ESG_SOFT_PREFER_TAG"
REASON_SOFT_AVOID_TAG = "ESG_SOFT_AVOID_TAG"


# ── Enum de estado ────────────────────────────────────────────────────────

from enum import Enum


class ESGComplianceStatus(str, Enum):
    """Resultado de la evaluación ESG para un instrumento."""

    PASS = "pass"
    SOFT_WARNING = "soft_warning"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


# ── Metadata ESG por instrumento ──────────────────────────────────────────


@dataclass
class InstrumentESGMetadata:
    """
    Información ESG y de exposición para un ticker.

    Los campos opcionales (esg_score, carbon_intensity) reflejan que no
    todos los instrumentos tienen cobertura ESG completa.
    """

    ticker: str
    issuer: str
    sectors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    esg_score: float | None = None
    carbon_intensity: float | None = None
    controversies: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.ticker or not self.ticker.strip():
            raise ValueError("ticker no puede estar vacío.")
        if not self.issuer or not self.issuer.strip():
            raise ValueError("issuer no puede estar vacío.")
        if not isinstance(self.sectors, list):
            raise ValueError("sectors debe ser una lista.")
        if not isinstance(self.tags, list):
            raise ValueError("tags debe ser una lista.")
        if not isinstance(self.controversies, list):
            raise ValueError("controversies debe ser una lista.")
        if not isinstance(self.notes, list):
            raise ValueError("notes debe ser una lista.")
        if self.esg_score is not None:
            if not isinstance(self.esg_score, (int, float)):
                raise ValueError(
                    f"esg_score debe ser numérico o None. Recibido: "
                    f"{type(self.esg_score).__name__}."
                )
            if not 0.0 <= float(self.esg_score) <= 100.0:
                raise ValueError(
                    f"esg_score debe estar en [0, 100]. Recibido: {self.esg_score}."
                )
        if self.carbon_intensity is not None:
            if not isinstance(self.carbon_intensity, (int, float)):
                raise ValueError(
                    f"carbon_intensity debe ser numérico o None. Recibido: "
                    f"{type(self.carbon_intensity).__name__}."
                )
            if float(self.carbon_intensity) < 0:
                raise ValueError(
                    f"carbon_intensity no puede ser negativa. Recibido: "
                    f"{self.carbon_intensity}."
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "issuer": self.issuer,
            "sectors": list(self.sectors),
            "tags": list(self.tags),
            "esg_score": self.esg_score,
            "carbon_intensity": self.carbon_intensity,
            "controversies": list(self.controversies),
            "notes": list(self.notes),
        }


# ── Resultado de la evaluación ────────────────────────────────────────────


@dataclass
class ESGComplianceResult:
    """
    Resultado de evaluar un ticker contra un ESGProfile.

    Reglas:
        - is_blocked: True si status == BLOCKED.
        - has_warnings: True si hay items en warnings.
        - soft_score_adjustment: número en [-1.0, 0.0], aplicable al
          suitability score del activo en etapas posteriores.
    """

    ticker: str
    status: ESGComplianceStatus
    blocked_by: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    soft_score_adjustment: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.ticker or not self.ticker.strip():
            raise ValueError("ticker no puede estar vacío.")
        if not isinstance(self.status, ESGComplianceStatus):
            raise ValueError(
                f"status debe ser ESGComplianceStatus. Recibido: "
                f"{type(self.status).__name__}."
            )
        if self.soft_score_adjustment < -1.0:
            # Defensa interna: el checker ya clampa, pero protegemos el dataclass.
            raise ValueError(
                f"soft_score_adjustment no puede ser menor a -1.0. Recibido: "
                f"{self.soft_score_adjustment}."
            )
        if self.soft_score_adjustment > 0.0:
            raise ValueError(
                f"soft_score_adjustment debe ser <= 0.0. Recibido: "
                f"{self.soft_score_adjustment}."
            )

    @property
    def is_blocked(self) -> bool:
        return self.status == ESGComplianceStatus.BLOCKED

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "status": self.status.value,
            "blocked_by": list(self.blocked_by),
            "warnings": list(self.warnings),
            "soft_score_adjustment": self.soft_score_adjustment,
            "reason_codes": list(self.reason_codes),
            "notes": list(self.notes),
        }


# ── Store de metadata cargado desde YAML ──────────────────────────────────


class ESGMetadataStore:
    """
    Repositorio de InstrumentESGMetadata.

    Carga desde YAML y permite consultas por ticker. En M1 es un store
    estático en memoria; en producción podría conectarse a una fuente real
    de datos ESG.
    """

    def __init__(self, items: list[InstrumentESGMetadata]):
        self._items: dict[str, InstrumentESGMetadata] = {}
        for it in items:
            if it.ticker in self._items:
                raise ValueError(
                    f"Ticker duplicado en metadata ESG: {it.ticker!r}."
                )
            self._items[it.ticker] = it

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ESGMetadataStore":
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(
                f"Archivo de metadata ESG no encontrado: {yaml_path}."
            )

        try:
            with yaml_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ValueError(f"YAML inválido en {yaml_path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"YAML inválido en {yaml_path}: el documento raíz debe ser un mapping."
            )
        if "instruments" not in data:
            raise ValueError(
                f"YAML inválido en {yaml_path}: falta la clave 'instruments' en la raíz."
            )
        if not isinstance(data["instruments"], list):
            raise ValueError(
                f"YAML inválido en {yaml_path}: 'instruments' debe ser una lista."
            )

        items: list[InstrumentESGMetadata] = []
        for idx, raw in enumerate(data["instruments"]):
            if not isinstance(raw, dict):
                raise ValueError(
                    f"YAML inválido en {yaml_path}: instrumento #{idx} no es un mapping."
                )
            try:
                items.append(
                    InstrumentESGMetadata(
                        ticker=raw["ticker"],
                        issuer=raw["issuer"],
                        sectors=list(raw.get("sectors", [])),
                        tags=list(raw.get("tags", [])),
                        esg_score=raw.get("esg_score"),
                        carbon_intensity=raw.get("carbon_intensity"),
                        controversies=list(raw.get("controversies", [])),
                        notes=list(raw.get("notes", [])),
                    )
                )
            except KeyError as exc:
                raise ValueError(
                    f"YAML inválido en {yaml_path}: instrumento #{idx} falta el campo "
                    f"{exc.args[0]!r}."
                ) from exc
            except ValueError as exc:
                raise ValueError(
                    f"YAML inválido en {yaml_path}: instrumento #{idx} es inválido: {exc}"
                ) from exc

        return cls(items)

    def get(self, ticker: str) -> InstrumentESGMetadata | None:
        return self._items.get(ticker)

    def contains(self, ticker: str) -> bool:
        return ticker in self._items

    def all_metadata(self) -> list[InstrumentESGMetadata]:
        """Copia defensiva: modificar la lista no altera el store."""
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, ticker: str) -> bool:
        return self.contains(ticker)


# ── Checker ──────────────────────────────────────────────────────────────


class ESGComplianceChecker:
    """
    Evalúa un ticker contra el ESGProfile del cliente.

    El método principal es `evaluate`. Devuelve siempre un
    ESGComplianceResult con status, blocked_by, warnings, score_adjustment,
    reason_codes y notes.
    """

    VALID_HARD_EXCLUSION_TYPES = frozenset(
        {"sector", "tag", "issuer", "controversy"}
    )

    VALID_SOFT_PREFERENCE_TYPES = frozenset(
        {"min_esg_score", "max_carbon_intensity", "prefer_tag", "avoid_tag"}
    )

    def evaluate(
        self,
        ticker: str,
        esg_profile: ESGProfile,
        metadata_store: ESGMetadataStore,
    ) -> ESGComplianceResult:
        if not ticker or not ticker.strip():
            raise ValueError("ticker no puede estar vacío.")

        metadata = metadata_store.get(ticker)

        # ── Caso 1: sin metadata → UNKNOWN ────────────────────────────
        if metadata is None:
            return ESGComplianceResult(
                ticker=ticker,
                status=ESGComplianceStatus.UNKNOWN,
                blocked_by=[],
                warnings=[
                    f"No hay metadata ESG disponible para {ticker!r}. "
                    "No se puede evaluar contra el perfil ESG del cliente."
                ],
                soft_score_adjustment=0.0,
                reason_codes=[REASON_METADATA_MISSING],
                notes=[],
            )

        # ── Caso 2: hard exclusions ───────────────────────────────────
        blocked_by, hard_reason_codes = self._evaluate_hard_exclusions(
            metadata, esg_profile.hard_exclusions
        )
        if blocked_by:
            return ESGComplianceResult(
                ticker=ticker,
                status=ESGComplianceStatus.BLOCKED,
                blocked_by=blocked_by,
                warnings=[],
                # Política: cuando bloqueado, soft no se evalúa. score = 0.0.
                soft_score_adjustment=0.0,
                reason_codes=hard_reason_codes,
                notes=[],
            )

        # ── Caso 3: soft preferences ──────────────────────────────────
        warnings, soft_reason_codes, score_adjustment = (
            self._evaluate_soft_preferences(metadata, esg_profile.soft_preferences)
        )

        if warnings:
            status = ESGComplianceStatus.SOFT_WARNING
        else:
            status = ESGComplianceStatus.PASS

        return ESGComplianceResult(
            ticker=ticker,
            status=status,
            blocked_by=[],
            warnings=warnings,
            soft_score_adjustment=score_adjustment,
            reason_codes=soft_reason_codes,
            notes=[],
        )

    # ── Hard exclusions ──────────────────────────────────────────────────

    def _evaluate_hard_exclusions(
        self,
        metadata: InstrumentESGMetadata,
        hard_exclusions: list[ESGExclusion],
    ) -> tuple[list[str], list[str]]:
        """
        Devuelve (blocked_by, reason_codes) para hard_exclusions que matchean.

        Matching case-insensitive sobre todos los campos.
        """
        blocked_by: list[str] = []
        reason_codes: list[str] = []

        sectors_lower = {s.lower() for s in metadata.sectors}
        tags_lower = {t.lower() for t in metadata.tags}
        controversies_lower = {c.lower() for c in metadata.controversies}
        issuer_lower = metadata.issuer.lower()

        for excl in hard_exclusions:
            if excl.exclusion_type not in self.VALID_HARD_EXCLUSION_TYPES:
                # Tipos desconocidos se ignoran silenciosamente — la validación
                # estricta vive en el dataclass ESGExclusion. Esto evita romper
                # la evaluación si un cliente declara un tipo aún no soportado.
                continue

            item_lower = excl.excluded_item.lower()
            matched = False

            if excl.exclusion_type == "sector" and item_lower in sectors_lower:
                blocked_by.append(
                    f"sector={excl.excluded_item!r} match en sectores del instrumento"
                )
                reason_codes.append(REASON_HARD_EXCLUSION_SECTOR)
                matched = True

            elif excl.exclusion_type == "tag" and item_lower in tags_lower:
                blocked_by.append(
                    f"tag={excl.excluded_item!r} match en tags del instrumento"
                )
                reason_codes.append(REASON_HARD_EXCLUSION_TAG)
                matched = True

            elif excl.exclusion_type == "issuer" and item_lower == issuer_lower:
                blocked_by.append(
                    f"issuer={excl.excluded_item!r} match con issuer del instrumento"
                )
                reason_codes.append(REASON_HARD_EXCLUSION_ISSUER)
                matched = True

            elif excl.exclusion_type == "controversy" and item_lower in controversies_lower:
                blocked_by.append(
                    f"controversy={excl.excluded_item!r} match en controversies del instrumento"
                )
                reason_codes.append(REASON_HARD_EXCLUSION_CONTROVERSY)
                matched = True

            _ = matched  # variable de ayuda para legibilidad; no se usa fuera

        return blocked_by, reason_codes

    # ── Soft preferences ─────────────────────────────────────────────────

    def _evaluate_soft_preferences(
        self,
        metadata: InstrumentESGMetadata,
        soft_preferences: list[ESGPreference],
    ) -> tuple[list[str], list[str], float]:
        """
        Devuelve (warnings, reason_codes, score_adjustment).

        score_adjustment es la suma negativa de pesos de preferencias incumplidas,
        clampada a -1.0 como piso.
        """
        warnings: list[str] = []
        reason_codes: list[str] = []
        score_adjustment = 0.0

        tags_lower = {t.lower() for t in metadata.tags}

        for pref in soft_preferences:
            if pref.preference_type not in self.VALID_SOFT_PREFERENCE_TYPES:
                # Mismo criterio que con hard: tipos desconocidos se ignoran.
                continue

            unmet, reason_code, data_incomplete = self._evaluate_single_preference(
                pref, metadata, tags_lower
            )

            if data_incomplete:
                warnings.append(
                    f"Datos ESG insuficientes para evaluar preferencia "
                    f"{pref.preference_type!r}."
                )
                reason_codes.append(REASON_DATA_INCOMPLETE)
                score_adjustment -= pref.weight
                continue

            if unmet:
                warnings.append(unmet)
                reason_codes.append(reason_code)
                score_adjustment -= pref.weight

        score_adjustment = max(score_adjustment, -1.0)
        # Defensa contra ruido de punto flotante por sumas/clamping
        score_adjustment = min(score_adjustment, 0.0)
        return warnings, reason_codes, score_adjustment

    def _evaluate_single_preference(
        self,
        pref: ESGPreference,
        metadata: InstrumentESGMetadata,
        tags_lower: set[str],
    ) -> tuple[str | None, str, bool]:
        """
        Devuelve (warning_text, reason_code, data_incomplete).

        Si la preferencia se cumple → (None, reason_code, False).
        Si no se cumple              → (texto del warning, reason_code, False).
        Si faltan datos              → (None, "", True).
        """
        if pref.preference_type == "min_esg_score":
            threshold = pref.minimum_threshold
            if threshold is None:
                # Preferencia mal formada: tratamos como dato incompleto.
                return (None, REASON_SOFT_MIN_ESG_SCORE, True)
            if metadata.esg_score is None:
                return (None, REASON_SOFT_MIN_ESG_SCORE, True)
            if float(metadata.esg_score) < float(threshold):
                return (
                    f"esg_score={metadata.esg_score} debajo del umbral mínimo "
                    f"de {threshold}.",
                    REASON_SOFT_MIN_ESG_SCORE,
                    False,
                )
            return (None, REASON_SOFT_MIN_ESG_SCORE, False)

        if pref.preference_type == "max_carbon_intensity":
            threshold = pref.minimum_threshold
            if threshold is None:
                return (None, REASON_SOFT_MAX_CARBON, True)
            if metadata.carbon_intensity is None:
                return (None, REASON_SOFT_MAX_CARBON, True)
            if float(metadata.carbon_intensity) > float(threshold):
                return (
                    f"carbon_intensity={metadata.carbon_intensity} supera el "
                    f"máximo de {threshold}.",
                    REASON_SOFT_MAX_CARBON,
                    False,
                )
            return (None, REASON_SOFT_MAX_CARBON, False)

        if pref.preference_type == "prefer_tag":
            # Usamos minimum_threshold para guardar el "umbral conceptual"
            # en otros preference_type; para tags el match es contra el
            # ticker/tags. Acá NO se permite usar threshold; el tag se
            # extrae de notes o del propio preference_type. Para mantener
            # el contrato simple en M1, asumimos que la "etiqueta a preferir"
            # se codifica fuera del schema actual: si no hay forma de saber
            # cuál tag preferir, devolvemos data incompleta. Cuando soft
            # preferences gane un campo `tag` explícito, esto se simplificará.
            return (None, REASON_SOFT_PREFER_TAG, True)

        if pref.preference_type == "avoid_tag":
            return (None, REASON_SOFT_AVOID_TAG, True)

        return (None, "", True)