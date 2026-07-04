"""
Risk-assumption config loader — Fase 1 closing.

Migra los supuestos críticos de negocio que antes vivían hardcoded en
`rules_layer.risk_budget_builder.PROFILE_BASE_PARAMS` y
`rules_layer.goal_feasibility.DEFAULT_ACHIEVABLE_RETURNS` a YAMLs versionables
bajo `config/`.

Política de diseño:
    - Sin dependencias nuevas. Usa PyYAML (ya declarado en pyproject.toml).
    - Validación estricta del schema al cargar: 5 perfiles exactos,
      campos requeridos, tipos correctos (rechaza bool donde se espera
      numeric porque `isinstance(True, int) == True` en Python).
    - Errores claros con `ValueError` (o `FileNotFoundError` si el archivo
      no existe). NUNCA se ejecuta a tiempo de request — los `get_default_*`
      cachean lecturas y los módulos consumidores hacen el binding al
      importar.
    - Estos siguen siendo supuestos demo. NO reemplazan un CMA productivo
      ni la firma de un comité de inversiones.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# ─────────────────────────────────────────────────────────────────────────────
# Constantes públicas
# ─────────────────────────────────────────────────────────────────────────────

# `__file__` → src/risk_first_advisory/config_layer/risk_assumptions.py
# .parent      → config_layer/
# .parent.parent  → risk_first_advisory/
# .parent.parent.parent  → src/
# .parent.parent.parent.parent  → project root
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent
_CONFIG_DIR: Path = _PROJECT_ROOT / "config"

DEFAULT_RISK_PROFILES_PATH: Path = _CONFIG_DIR / "risk_profiles.yaml"
DEFAULT_ACHIEVABLE_RETURNS_PATH: Path = _CONFIG_DIR / "achievable_returns.yaml"
DEFAULT_GAMMA_ANCHORS_PATH: Path = _CONFIG_DIR / "gamma_anchors.yaml"

# Perfiles que DEBEN estar en cada archivo de config. Política estricta:
# el loader rechaza tanto perfiles faltantes como perfiles desconocidos
# (extras), para evitar que un typo en YAML degrade el catálogo silenciosamente.
EXPECTED_PROFILES: frozenset[str] = frozenset({
    "conservador",
    "moderado-defensivo",
    "moderado",
    "moderado-agresivo",
    "agresivo",
})

# Campos requeridos por perfil en `config/risk_profiles.yaml`. Mismo set que
# antes existía hardcoded + min_liquidity y preferred_currency (que el
# RiskBudgetBuilder hoy override-ea desde KYC, pero quedan en el contrato
# para futuras revisiones).
REQUIRED_PROFILE_FIELDS: tuple[str, ...] = (
    "target_volatility",
    "max_volatility",
    "max_drawdown",
    "max_equity",
    "max_high_yield",
    "max_single_asset",
    "max_sector_exposure",
    "max_duration",
    "min_liquidity",
    "preferred_currency",
    "complex_products_allowed",
)

# Subconjunto de campos numéricos (float | int) — usado por el validador
# para aplicar el bool-guard antes del isinstance numérico.
_NUMERIC_PROFILE_FIELDS: frozenset[str] = frozenset({
    "target_volatility",
    "max_volatility",
    "max_drawdown",
    "max_equity",
    "max_high_yield",
    "max_single_asset",
    "max_sector_exposure",
    "max_duration",
    "min_liquidity",
})


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de validación (privados)
# ─────────────────────────────────────────────────────────────────────────────


def _load_yaml(path: Path) -> Any:
    """
    Lee un archivo YAML y devuelve el documento parseado. Wrapper sobre
    `yaml.safe_load` con manejo de errores consistente.

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: si el YAML es inválido o el documento raíz es vacío.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Archivo de config no encontrado: {path}."
        )
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(
            f"YAML inválido en {path}: {exc}"
        ) from exc

    if data is None:
        raise ValueError(
            f"Archivo de config vacío: {path}."
        )
    return data


def _assert_not_bool(value: Any, where: str) -> None:
    """
    Levanta ValueError si `value` es bool. Python trata `bool` como subclase
    de `int`, así que `isinstance(True, (int, float))` devuelve True; este
    guard debe ejecutarse ANTES de la comprobación isinstance numérica.
    """
    if isinstance(value, bool):
        raise ValueError(
            f"{where}: se esperaba un número (int o float), no bool. "
            f"Valor recibido: {value!r}."
        )


def _assert_number(value: Any, where: str) -> None:
    """Valida que `value` sea int|float NO bool."""
    _assert_not_bool(value, where)
    if not isinstance(value, (int, float)):
        raise ValueError(
            f"{where}: se esperaba un número (int o float), "
            f"se recibió {type(value).__name__}: {value!r}."
        )


def _assert_bool(value: Any, where: str) -> None:
    """Valida que `value` sea bool real (no 0/1)."""
    if not isinstance(value, bool):
        raise ValueError(
            f"{where}: se esperaba bool, se recibió {type(value).__name__}: "
            f"{value!r}."
        )


def _assert_non_empty_str(value: Any, where: str) -> None:
    """Valida que `value` sea str y no whitespace."""
    if not isinstance(value, str):
        raise ValueError(
            f"{where}: se esperaba string, se recibió {type(value).__name__}: "
            f"{value!r}."
        )
    if not value.strip():
        raise ValueError(
            f"{where}: el string no puede estar vacío ni ser solo espacios."
        )


def _validate_profile_set(profile_keys: set[str], source: str) -> None:
    """
    Valida que `profile_keys` coincida exactamente con EXPECTED_PROFILES.
    Política estricta: rechaza tanto faltantes como extras.
    """
    missing = EXPECTED_PROFILES - profile_keys
    unknown = profile_keys - EXPECTED_PROFILES
    if missing:
        raise ValueError(
            f"{source}: faltan perfiles requeridos: {sorted(missing)}. "
            f"Esperados: {sorted(EXPECTED_PROFILES)}."
        )
    if unknown:
        raise ValueError(
            f"{source}: perfiles desconocidos: {sorted(unknown)}. "
            f"Esperados: {sorted(EXPECTED_PROFILES)}."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Loaders públicos
# ─────────────────────────────────────────────────────────────────────────────


def load_risk_profile_params(
    path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Carga `config/risk_profiles.yaml` y devuelve un dict
    {profile_name: {field: value, ...}}.

    Valida estrictamente:
        - documento raíz es mapping con clave `profiles`.
        - exactamente los 5 perfiles de `EXPECTED_PROFILES`.
        - cada perfil tiene los campos de `REQUIRED_PROFILE_FIELDS`.
        - campos numéricos son int|float y NO bool.
        - `complex_products_allowed` es bool real.
        - `preferred_currency` es str no vacío.

    Args:
        path: ruta al YAML. Si None, usa `DEFAULT_RISK_PROFILES_PATH`.

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: si el schema o los tipos son inválidos.
    """
    target = path if path is not None else DEFAULT_RISK_PROFILES_PATH
    data = _load_yaml(target)
    if not isinstance(data, dict):
        raise ValueError(
            f"{target}: el documento raíz debe ser un mapping."
        )
    if "profiles" not in data:
        raise ValueError(
            f"{target}: falta la clave de nivel superior 'profiles'."
        )

    profiles_raw = data["profiles"]
    if not isinstance(profiles_raw, dict):
        raise ValueError(
            f"{target}: 'profiles' debe ser un mapping de perfil → parámetros."
        )

    _validate_profile_set(set(profiles_raw.keys()), str(target))

    result: dict[str, dict[str, Any]] = {}
    for profile_name, fields in profiles_raw.items():
        if not isinstance(fields, dict):
            raise ValueError(
                f"{target}: profile '{profile_name}' debe ser un mapping de "
                f"campos. Recibido: {type(fields).__name__}."
            )

        missing = set(REQUIRED_PROFILE_FIELDS) - set(fields.keys())
        if missing:
            raise ValueError(
                f"{target}: profile '{profile_name}' tiene campos faltantes: "
                f"{sorted(missing)}. Requeridos: {list(REQUIRED_PROFILE_FIELDS)}."
            )

        # Validación por tipo de campo.
        for field_name in REQUIRED_PROFILE_FIELDS:
            value = fields[field_name]
            where = f"{target}: profile '{profile_name}' campo '{field_name}'"
            if field_name in _NUMERIC_PROFILE_FIELDS:
                _assert_number(value, where)
            elif field_name == "complex_products_allowed":
                _assert_bool(value, where)
            elif field_name == "preferred_currency":
                _assert_non_empty_str(value, where)
            else:
                # Defensivo: no debería caer aquí mientras la lista coincida.
                raise ValueError(
                    f"{where}: campo no tiene reglas de validación definidas."
                )

        # Copia explícita con solo las claves requeridas — ignora extras.
        # Mantiene el dict resultante con la misma "forma" que el antiguo
        # PROFILE_BASE_PARAMS para no romper consumidores indexados.
        result[profile_name] = {
            field_name: fields[field_name] for field_name in REQUIRED_PROFILE_FIELDS
        }

    return result


def load_achievable_returns(path: Path | None = None) -> dict[str, float]:
    """
    Carga `config/achievable_returns.yaml` y devuelve {profile_name: rate}.

    Valida:
        - documento raíz es mapping con clave `achievable_returns`.
        - exactamente los 5 perfiles de `EXPECTED_PROFILES`.
        - cada valor es int|float y NO bool.
        - convierte int → float para garantizar tipo estable.

    Args:
        path: ruta al YAML. Si None, usa `DEFAULT_ACHIEVABLE_RETURNS_PATH`.

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: si el schema o los tipos son inválidos.
    """
    target = path if path is not None else DEFAULT_ACHIEVABLE_RETURNS_PATH
    data = _load_yaml(target)
    if not isinstance(data, dict):
        raise ValueError(
            f"{target}: el documento raíz debe ser un mapping."
        )
    if "achievable_returns" not in data:
        raise ValueError(
            f"{target}: falta la clave de nivel superior 'achievable_returns'."
        )

    returns_raw = data["achievable_returns"]
    if not isinstance(returns_raw, dict):
        raise ValueError(
            f"{target}: 'achievable_returns' debe ser un mapping "
            f"perfil → rate."
        )

    _validate_profile_set(set(returns_raw.keys()), str(target))

    result: dict[str, float] = {}
    for profile_name, value in returns_raw.items():
        where = f"{target}: achievable_returns['{profile_name}']"
        _assert_number(value, where)
        result[profile_name] = float(value)

    return result


def load_gamma_anchors(
    path: Path | None = None,
) -> tuple[tuple[float, float], ...]:
    """
    Carga `config/gamma_anchors.yaml` y devuelve los anclajes γ→número como
    tupla de pares `((gamma, number), ...)`, en el mismo formato que consumía
    la constante `GAMMA_ANCHORS` hardcoded en `ai_layer/risk_number.py`.

    Valida:
        - documento raíz es mapping con clave `gamma_anchors`.
        - `gamma_anchors` es una lista de al menos 2 pares (la interpolación
          lineal a trozos necesita dos puntos como mínimo).
        - cada item es un mapping con `gamma` y `number` numéricos (NO bool).
        - `number` está en [0, 100].
        - `gamma` es ESTRICTAMENTE creciente entre items (requisito de
          `_piecewise_linear`; si no, la interpolación es ambigua).

    Args:
        path: ruta al YAML. Si None, usa `DEFAULT_GAMMA_ANCHORS_PATH`.

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: si el schema, los tipos o la monotonía son inválidos.
    """
    target = path if path is not None else DEFAULT_GAMMA_ANCHORS_PATH
    data = _load_yaml(target)
    if not isinstance(data, dict):
        raise ValueError(
            f"{target}: el documento raíz debe ser un mapping."
        )
    if "gamma_anchors" not in data:
        raise ValueError(
            f"{target}: falta la clave de nivel superior 'gamma_anchors'."
        )

    anchors_raw = data["gamma_anchors"]
    if not isinstance(anchors_raw, list):
        raise ValueError(
            f"{target}: 'gamma_anchors' debe ser una lista de pares "
            f"{{gamma, number}}."
        )
    if len(anchors_raw) < 2:
        raise ValueError(
            f"{target}: 'gamma_anchors' necesita al menos 2 pares para "
            f"interpolar; tiene {len(anchors_raw)}."
        )

    result: list[tuple[float, float]] = []
    prev_gamma: float | None = None
    for i, item in enumerate(anchors_raw):
        where = f"{target}: gamma_anchors[{i}]"
        if not isinstance(item, dict):
            raise ValueError(
                f"{where}: cada anclaje debe ser un mapping con 'gamma' y "
                f"'number'. Recibido: {type(item).__name__}."
            )
        for key in ("gamma", "number"):
            if key not in item:
                raise ValueError(f"{where}: falta la clave '{key}'.")
        _assert_number(item["gamma"], f"{where}.gamma")
        _assert_number(item["number"], f"{where}.number")
        gamma = float(item["gamma"])
        number = float(item["number"])
        if not 0.0 <= number <= 100.0:
            raise ValueError(
                f"{where}.number: debe estar en [0, 100]. Recibido: {number}."
            )
        if prev_gamma is not None and gamma <= prev_gamma:
            raise ValueError(
                f"{where}.gamma: los anclajes deben ser estrictamente "
                f"crecientes en gamma. {gamma} no es mayor que el anterior "
                f"{prev_gamma}."
            )
        prev_gamma = gamma
        result.append((gamma, number))

    return tuple(result)


# ─────────────────────────────────────────────────────────────────────────────
# Defaults cacheados — single read en el import del módulo consumidor
# ─────────────────────────────────────────────────────────────────────────────
#
# Los módulos que antes hacían `PROFILE_BASE_PARAMS = {...}` ahora hacen
# `PROFILE_BASE_PARAMS = get_default_risk_profile_params()` a tiempo de
# import. Para evitar I/O repetido entre tests o ejecuciones concurrentes,
# cacheamos el resultado de la primera lectura.
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_RISK_PROFILE_PARAMS_CACHE: dict[str, dict[str, Any]] | None = None
_DEFAULT_ACHIEVABLE_RETURNS_CACHE: dict[str, float] | None = None
_DEFAULT_GAMMA_ANCHORS_CACHE: tuple[tuple[float, float], ...] | None = None


def get_default_risk_profile_params() -> dict[str, dict[str, Any]]:
    """
    Devuelve los parámetros por perfil cargados desde el YAML por defecto.

    Cacheado: la primera llamada lee el archivo, las siguientes devuelven
    una copia profunda para evitar mutación accidental del cache.
    """
    global _DEFAULT_RISK_PROFILE_PARAMS_CACHE
    if _DEFAULT_RISK_PROFILE_PARAMS_CACHE is None:
        _DEFAULT_RISK_PROFILE_PARAMS_CACHE = load_risk_profile_params()
    # Copia profunda manual: los valores son tipos primitivos (no anidados),
    # alcanza con dict-comp + copia del dict interno.
    return {
        profile: dict(fields)
        for profile, fields in _DEFAULT_RISK_PROFILE_PARAMS_CACHE.items()
    }


def get_default_achievable_returns() -> dict[str, float]:
    """
    Devuelve los retornos alcanzables por perfil cargados desde el YAML por
    defecto. Cacheado.
    """
    global _DEFAULT_ACHIEVABLE_RETURNS_CACHE
    if _DEFAULT_ACHIEVABLE_RETURNS_CACHE is None:
        _DEFAULT_ACHIEVABLE_RETURNS_CACHE = load_achievable_returns()
    # Copia para evitar mutación del cache.
    return dict(_DEFAULT_ACHIEVABLE_RETURNS_CACHE)


def get_default_gamma_anchors() -> tuple[tuple[float, float], ...]:
    """
    Devuelve los anclajes γ→número cargados desde el YAML por defecto.
    Cacheado. La tupla es inmutable, así que se devuelve el cache directo
    (no hace falta copiar como en los dicts).
    """
    global _DEFAULT_GAMMA_ANCHORS_CACHE
    if _DEFAULT_GAMMA_ANCHORS_CACHE is None:
        _DEFAULT_GAMMA_ANCHORS_CACHE = load_gamma_anchors()
    return _DEFAULT_GAMMA_ANCHORS_CACHE
