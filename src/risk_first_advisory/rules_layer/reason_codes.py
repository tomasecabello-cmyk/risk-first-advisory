"""
Catálogo central de ReasonCode.

Toda exclusión, contradicción, decisión o evento del sistema debe citar un
código de este catálogo. Los códigos son estables: una vez publicados nunca
se renombran — solo se deprecan creando un código nuevo.

Formato del identificador: DOMINIO_DESCRIPCION = "DOM_NNN"
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReasonCode(str, Enum):
    """Catálogo estable de motivos del sistema."""

    # ─── KYC: contradicciones detectadas ──────────────────────────────────
    KYC_CONTRADICTION_OBJECTIVE_TOLERANCE = "KYC_001"
    KYC_CONTRADICTION_HORIZON_ASSET_CLASS = "KYC_002"
    KYC_CONTRADICTION_EXPERIENCE_COMPLEXITY = "KYC_003"
    KYC_CONTRADICTION_LIQUIDITY_ILLIQUID_ASSETS = "KYC_004"
    KYC_CONTRADICTION_ESG_INDIRECT_EXPOSURE = "KYC_005"
    KYC_CONTRADICTION_PRESERVATION_RETURN = "KYC_006"
    KYC_CONTRADICTION_NEED_EXCEEDS_APTITUDE = "KYC_007"
    KYC_INSUFFICIENT_INFORMATION = "KYC_010"
    KYC_AMBIGUOUS_OPEN_RESPONSE = "KYC_011"
    KYC_STALE = "KYC_012"
    KYC_CNV_PROFILING_INCOMPLETE = "KYC_013"

    # ─── Goal feasibility ─────────────────────────────────────────────────
    GOAL_INFEASIBLE_REQUIRED_RETURN = "GOAL_001"
    GOAL_MARGINAL_TIGHT_HEADROOM = "GOAL_002"
    GOAL_INFEASIBLE_HORIZON_INSUFFICIENT = "GOAL_003"
    GOAL_VIABILITY_OVERRIDE_BY_ADVISOR = "GOAL_004"

    # ─── ESG ──────────────────────────────────────────────────────────────
    ESG_HARD_EXCLUSION_SECTOR = "ESG_001"
    ESG_HARD_EXCLUSION_ISSUER = "ESG_002"
    ESG_HARD_EXCLUSION_COUNTRY = "ESG_003"
    ESG_INDIRECT_EXPOSURE_EXCEEDS_THRESHOLD = "ESG_004"
    ESG_CARBON_INTENSITY_EXCEEDS_LIMIT = "ESG_005"
    ESG_CONTROVERSY_SCORE_BELOW_MINIMUM = "ESG_006"
    ESG_SOFT_PREFERENCE_PENALTY_APPLIED = "ESG_010"

    # ─── Product governance ───────────────────────────────────────────────
    GOVERNANCE_PRODUCT_PROHIBITED = "GOV_001"
    GOVERNANCE_PRODUCT_TEMPORARILY_SUSPENDED = "GOV_002"
    GOVERNANCE_PRODUCT_NOT_IN_APPROVED_UNIVERSE = "GOV_003"
    GOVERNANCE_RESTRICTED_FOR_PROFILE = "GOV_004"
    GOVERNANCE_REVIEW_OVERDUE = "GOV_005"
    GOVERNANCE_WATCHLIST_REQUIRES_NOTE = "GOV_006"

    # ─── Data quality ─────────────────────────────────────────────────────
    DATA_QUALITY_MISSING_PRICES = "DQ_001"
    DATA_QUALITY_INSUFFICIENT_HISTORY = "DQ_002"
    DATA_QUALITY_MISSING_CURRENCY = "DQ_003"
    DATA_QUALITY_MISSING_SECTOR = "DQ_004"
    DATA_QUALITY_MISSING_DURATION = "DQ_005"
    DATA_QUALITY_MISSING_RATING = "DQ_006"
    DATA_QUALITY_MISSING_LIQUIDITY = "DQ_007"
    DATA_QUALITY_STALE_DATA = "DQ_008"

    # ─── Suitability (instrumento × perfil) ───────────────────────────────
    SUITABILITY_INSTRUMENT_NOT_ALLOWED = "SUIT_001"
    SUITABILITY_REQUIRES_EXPERIENCE = "SUIT_002"
    SUITABILITY_REQUIRES_ADVISOR_NOTE = "SUIT_003"
    SUITABILITY_WEIGHT_CEILING_BINDING = "SUIT_004"

    # ─── Optimization ─────────────────────────────────────────────────────
    OPTIMIZER_VARIANT_INFEASIBLE = "OPT_001"
    OPTIMIZER_VARIANT_DEGENERATE = "OPT_002"
    OPTIMIZER_ZERO_WEIGHT_LOW_CONTRIBUTION = "OPT_003"
    OPTIMIZER_SEPARATION_INSUFFICIENT = "OPT_004"

    # ─── Decisiones del asesor ────────────────────────────────────────────
    ADVISOR_PROFILE_APPROVED_UNCHANGED = "ADV_001"
    ADVISOR_PROFILE_MODIFIED = "ADV_002"
    ADVISOR_OVERRIDE_DATA_CORRECTION = "ADV_003"
    ADVISOR_OVERRIDE_GOAL_CHANGE = "ADV_004"
    ADVISOR_OVERRIDE_PROCEED_WITH_DISCLAIMER = "ADV_005"
    ADVISOR_RETURN_OVERRIDE_APPLIED = "ADV_006"
    ADVISOR_PORTFOLIO_APPROVED = "ADV_007"
    ADVISOR_PORTFOLIO_REJECTED = "ADV_008"


# Catálogo descriptivo — fuente única de verdad para metadata de cada código.
REASON_CODE_CATALOG: dict[ReasonCode, dict[str, Any]] = {
    ReasonCode.KYC_CONTRADICTION_OBJECTIVE_TOLERANCE: {
        "domain": "kyc",
        "severity": "alta",
        "description": "Contradicción entre objetivo de inversión y tolerancia emocional declarada.",
        "implies_follow_up": True,
        "blocks_advancement": True,
    },
    ReasonCode.KYC_CONTRADICTION_HORIZON_ASSET_CLASS: {
        "domain": "kyc",
        "severity": "alta",
        "description": "Horizonte temporal incompatible con la clase de activo deseada.",
        "implies_follow_up": True,
        "blocks_advancement": True,
    },
    ReasonCode.KYC_CONTRADICTION_EXPERIENCE_COMPLEXITY: {
        "domain": "kyc",
        "severity": "media",
        "description": "Experiencia inversora insuficiente para productos complejos solicitados.",
        "implies_follow_up": True,
        "blocks_advancement": False,
    },
    ReasonCode.KYC_CONTRADICTION_LIQUIDITY_ILLIQUID_ASSETS: {
        "domain": "kyc",
        "severity": "alta",
        "description": "Necesidad de liquidez declarada incompatible con activos ilíquidos solicitados.",
        "implies_follow_up": True,
        "blocks_advancement": True,
    },
    ReasonCode.KYC_CONTRADICTION_ESG_INDIRECT_EXPOSURE: {
        "domain": "kyc",
        "severity": "media",
        "description": "Restricción ESG estricta con tolerancia a ETFs de exposición indirecta.",
        "implies_follow_up": True,
        "blocks_advancement": False,
    },
    ReasonCode.KYC_CONTRADICTION_PRESERVATION_RETURN: {
        "domain": "kyc",
        "severity": "alta",
        "description": "Objetivo de preservación de capital con expectativa de retorno incompatible.",
        "implies_follow_up": True,
        "blocks_advancement": True,
    },
    ReasonCode.KYC_CONTRADICTION_NEED_EXCEEDS_APTITUDE: {
        "domain": "kyc",
        "severity": "alta",
        "description": "El objetivo requiere más riesgo del que el cliente puede o quiere asumir.",
        "implies_follow_up": True,
        "blocks_advancement": True,
    },
    ReasonCode.KYC_INSUFFICIENT_INFORMATION: {
        "domain": "kyc",
        "severity": "media",
        "description": "Información del KYC insuficiente para construir perfil con confianza adecuada.",
        "implies_follow_up": True,
        "blocks_advancement": True,
    },
    ReasonCode.KYC_AMBIGUOUS_OPEN_RESPONSE: {
        "domain": "kyc",
        "severity": "baja",
        "description": "Respuesta abierta del cliente es ambigua y requiere aclaración.",
        "implies_follow_up": True,
        "blocks_advancement": False,
    },
    ReasonCode.KYC_STALE: {
        "domain": "kyc",
        "severity": "media",
        "description": (
            "El KYC que respalda la propuesta supera la antigüedad máxima "
            "configurada; el asesor debe reconfirmar los datos del cliente."
        ),
        "implies_follow_up": True,
        "blocks_advancement": False,
    },
    ReasonCode.KYC_CNV_PROFILING_INCOMPLETE: {
        "domain": "kyc",
        "severity": "media",
        "description": (
            "El KYC no cubre todos los mínimos de perfilamiento exigidos por "
            "las Normas CNV (Título VII, art. 12 inc. j / art. 16 inc. j): "
            "conocimiento de los instrumentos, porcentaje de ahorros destinado "
            "a la inversión y nivel de ahorros que el cliente está dispuesto a "
            "arriesgar."
        ),
        "implies_follow_up": True,
        "blocks_advancement": False,
    },
    ReasonCode.GOAL_INFEASIBLE_REQUIRED_RETURN: {
        "domain": "goal_feasibility",
        "severity": "alta",
        "description": "Retorno requerido excede el alcanzable dentro del perfil aprobado.",
        "implies_follow_up": False,
        "blocks_advancement": True,
    },
    ReasonCode.GOAL_MARGINAL_TIGHT_HEADROOM: {
        "domain": "goal_feasibility",
        "severity": "media",
        "description": "Objetivo viable pero con holgura estrecha frente al retorno alcanzable.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.GOAL_INFEASIBLE_HORIZON_INSUFFICIENT: {
        "domain": "goal_feasibility",
        "severity": "alta",
        "description": "Horizonte temporal insuficiente para alcanzar el objetivo.",
        "implies_follow_up": False,
        "blocks_advancement": True,
    },
    ReasonCode.GOAL_VIABILITY_OVERRIDE_BY_ADVISOR: {
        "domain": "goal_feasibility",
        "severity": "media",
        "description": "El asesor decidió continuar pese a inviabilidad documentada.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ESG_HARD_EXCLUSION_SECTOR: {
        "domain": "esg",
        "severity": "alta",
        "description": "Activo excluido por restricción dura de sector.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ESG_HARD_EXCLUSION_ISSUER: {
        "domain": "esg",
        "severity": "alta",
        "description": "Activo excluido por restricción dura de emisor.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ESG_HARD_EXCLUSION_COUNTRY: {
        "domain": "esg",
        "severity": "alta",
        "description": "Activo excluido por restricción dura de país.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ESG_INDIRECT_EXPOSURE_EXCEEDS_THRESHOLD: {
        "domain": "esg",
        "severity": "media",
        "description": "Exposición indirecta vía composición de ETF supera el umbral configurado.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ESG_CARBON_INTENSITY_EXCEEDS_LIMIT: {
        "domain": "esg",
        "severity": "media",
        "description": "Intensidad de carbono del activo supera el límite del perfil ESG.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ESG_CONTROVERSY_SCORE_BELOW_MINIMUM: {
        "domain": "esg",
        "severity": "media",
        "description": "Score de controversias por debajo del mínimo aceptado.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ESG_SOFT_PREFERENCE_PENALTY_APPLIED: {
        "domain": "esg",
        "severity": "baja",
        "description": "Penalización aplicada al score de suitability por preferencia ESG blanda.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.GOVERNANCE_PRODUCT_PROHIBITED: {
        "domain": "governance",
        "severity": "alta",
        "description": "Producto prohibido por política de la firma.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.GOVERNANCE_PRODUCT_TEMPORARILY_SUSPENDED: {
        "domain": "governance",
        "severity": "alta",
        "description": "Producto temporalmente suspendido por governance.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.GOVERNANCE_PRODUCT_NOT_IN_APPROVED_UNIVERSE: {
        "domain": "governance",
        "severity": "alta",
        "description": "Producto no incluido en el universo aprobado por la firma.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.GOVERNANCE_RESTRICTED_FOR_PROFILE: {
        "domain": "governance",
        "severity": "media",
        "description": "Producto restringido para este perfil específico.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.GOVERNANCE_REVIEW_OVERDUE: {
        "domain": "governance",
        "severity": "alta",
        "description": "Revisión de governance vencida — producto bloqueado hasta nueva revisión.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.GOVERNANCE_WATCHLIST_REQUIRES_NOTE: {
        "domain": "governance",
        "severity": "media",
        "description": "Producto en watchlist — uso permitido con nota del asesor.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.DATA_QUALITY_MISSING_PRICES: {
        "domain": "data_quality",
        "severity": "alta",
        "description": "Precios históricos faltantes — activo bloqueado.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.DATA_QUALITY_INSUFFICIENT_HISTORY: {
        "domain": "data_quality",
        "severity": "alta",
        "description": "Historial de precios insuficiente para cálculo confiable de riesgo.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.DATA_QUALITY_MISSING_CURRENCY: {
        "domain": "data_quality",
        "severity": "alta",
        "description": "Moneda del activo no disponible.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.DATA_QUALITY_MISSING_SECTOR: {
        "domain": "data_quality",
        "severity": "media",
        "description": "Sector del activo faltante.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.DATA_QUALITY_MISSING_DURATION: {
        "domain": "data_quality",
        "severity": "alta",
        "description": "Duration faltante en activo de renta fija.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.DATA_QUALITY_MISSING_RATING: {
        "domain": "data_quality",
        "severity": "alta",
        "description": "Calificación crediticia faltante en activo de renta fija.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.DATA_QUALITY_MISSING_LIQUIDITY: {
        "domain": "data_quality",
        "severity": "baja",
        "description": "Estimación de liquidez no disponible — penalización aplicada.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.DATA_QUALITY_STALE_DATA: {
        "domain": "data_quality",
        "severity": "media",
        "description": "Datos con más de 5 días de antigüedad.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.SUITABILITY_INSTRUMENT_NOT_ALLOWED: {
        "domain": "suitability",
        "severity": "alta",
        "description": "Tipo de instrumento no permitido para el perfil aprobado.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.SUITABILITY_REQUIRES_EXPERIENCE: {
        "domain": "suitability",
        "severity": "alta",
        "description": "Instrumento requiere nivel de experiencia que el cliente no declara.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.SUITABILITY_REQUIRES_ADVISOR_NOTE: {
        "domain": "suitability",
        "severity": "media",
        "description": "Instrumento requiere nota justificatoria del asesor.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.SUITABILITY_WEIGHT_CEILING_BINDING: {
        "domain": "suitability",
        "severity": "baja",
        "description": "Techo de peso por tipo de instrumento está activo en la optimización.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.OPTIMIZER_VARIANT_INFEASIBLE: {
        "domain": "optimizer",
        "severity": "alta",
        "description": "Optimización infactible para la variante.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.OPTIMIZER_VARIANT_DEGENERATE: {
        "domain": "optimizer",
        "severity": "media",
        "description": "Variante generada pero degenerada (sin separación significativa).",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.OPTIMIZER_ZERO_WEIGHT_LOW_CONTRIBUTION: {
        "domain": "optimizer",
        "severity": "baja",
        "description": "Activo recibió peso cero por bajo aporte al perfil riesgo/retorno.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.OPTIMIZER_SEPARATION_INSUFFICIENT: {
        "domain": "optimizer",
        "severity": "media",
        "description": "Las tres variantes no son suficientemente distintas entre sí.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ADVISOR_PROFILE_APPROVED_UNCHANGED: {
        "domain": "advisor",
        "severity": "baja",
        "description": "Asesor aprobó el perfil preliminar sin modificaciones.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ADVISOR_PROFILE_MODIFIED: {
        "domain": "advisor",
        "severity": "media",
        "description": "Asesor modificó el perfil preliminar propuesto por la IA.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ADVISOR_OVERRIDE_DATA_CORRECTION: {
        "domain": "advisor",
        "severity": "media",
        "description": "Override por corrección de datos del KYC.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ADVISOR_OVERRIDE_GOAL_CHANGE: {
        "domain": "advisor",
        "severity": "media",
        "description": "Override por cambio del objetivo financiero.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ADVISOR_OVERRIDE_PROCEED_WITH_DISCLAIMER: {
        "domain": "advisor",
        "severity": "alta",
        "description": "Asesor decidió continuar con disclaimer explícito de inviabilidad.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ADVISOR_RETURN_OVERRIDE_APPLIED: {
        "domain": "advisor",
        "severity": "media",
        "description": "Override del asesor sobre retorno esperado de un activo.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ADVISOR_PORTFOLIO_APPROVED: {
        "domain": "advisor",
        "severity": "baja",
        "description": "Asesor aprobó portfolio para presentación al cliente.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
    ReasonCode.ADVISOR_PORTFOLIO_REJECTED: {
        "domain": "advisor",
        "severity": "media",
        "description": "Asesor rechazó portfolio generado.",
        "implies_follow_up": False,
        "blocks_advancement": False,
    },
}


@dataclass
class Reason:
    """
    Wrapper estándar — todo motivo en el sistema usa esta estructura.

    El campo `context` permite enriquecer el motivo con datos específicos del
    caso (ticker, sector, valores), sin alterar el código en sí.
    """

    code: ReasonCode
    context: dict[str, Any] = field(default_factory=dict)
    custom_note: str = ""

    @property
    def description(self) -> str:
        return REASON_CODE_CATALOG[self.code]["description"]

    @property
    def severity(self) -> str:
        return REASON_CODE_CATALOG[self.code]["severity"]

    @property
    def domain(self) -> str:
        return REASON_CODE_CATALOG[self.code]["domain"]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "domain": self.domain,
            "severity": self.severity,
            "description": self.description,
            "context": self.context,
            "custom_note": self.custom_note,
        }
