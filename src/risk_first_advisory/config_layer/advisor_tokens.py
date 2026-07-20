"""
Advisor token loader — Fase 2 (commit 2).

Reemplaza el mapa hardcodeado en `api_layer/auth.py` por un loader YAML
configurable + fallback dev-only. El módulo de auth sigue recibiendo un
dict `{token: {advisor_id, display_name, firm_id, roles}}` — el contrato
externo no cambia.

Resolución de `get_default_advisor_tokens()`:
    1. ENV var `ADVISOR_TOKENS_FILE` (si está set y no vacío)
    2. `config/advisor_tokens.yaml` (si existe)
    3. Fallback hardcoded development-only — SOLO si el kill-switch lo habilita:
       env var `RFA_ALLOW_DEV_TOKENS` o `RFA_DEMO_MODE` con valor no vacío.
       Sin fuente de tokens y sin kill-switch → AdvisorTokensNotConfiguredError
       (fail-closed: los tokens dev-* son públicos en el repo y no deben
       autenticar por accidente en un backend expuesto).

Cuando se usan (1) o (2), el archivo REEMPLAZA por completo al fallback —
no hay merge. Los tokens dev-* no resuelven si el env var / archivo apunta
a un YAML que no los lista.

Política de diseño (alineada con `risk_assumptions.py`):
    - Sin dependencias nuevas (usa PyYAML, ya declarado en pyproject).
    - Validación estricta en `load_advisor_tokens`: schema-rejection con
      mensaje claro. Campos desconocidos por token → ValueError (fail-loud).
    - `bool` rechazado donde se espera `str` (Python trata bool como subclase
      de int — el guard explícito evita aceptar True/False como advisor_id).
    - El loader devuelve dicts simples, NO objetos del dominio. Evita el
      ciclo de imports api_layer ↔ config_layer.
    - El fallback dev-only es para tests y demos. NO usar en producción.

Nota de seguridad:
    - No imprimir tokens ni en logs ni en errores.
    - El archivo real `config/advisor_tokens.yaml` está gitignored; solo el
      `.example` se commitea.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# ─────────────────────────────────────────────────────────────────────────────
# Paths y constantes públicas
# ─────────────────────────────────────────────────────────────────────────────

# Igual layout que risk_assumptions.py:
#   __file__ → src/risk_first_advisory/config_layer/advisor_tokens.py
#   .parent.parent.parent.parent → project root
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent
_CONFIG_DIR: Path = _PROJECT_ROOT / "config"

DEFAULT_ADVISOR_TOKENS_PATH: Path = _CONFIG_DIR / "advisor_tokens.yaml"
ADVISOR_TOKENS_ENV_VAR: str = "ADVISOR_TOKENS_FILE"

# Kill-switch del fallback dev-only (auditoría de seguridad 2026-07-17).
# El fallback con tokens dev-* (públicos en el repo) solo se habilita si
# alguna de estas env vars tiene valor no vacío. `RFA_DEMO_MODE` cuenta
# porque ya es la señal explícita de "demo local sin llaves" (misma
# semántica truthy que usa api_layer.main para el profile client demo).
DEV_TOKENS_FLAG_ENV_VAR: str = "RFA_ALLOW_DEV_TOKENS"
DEMO_MODE_ENV_VAR: str = "RFA_DEMO_MODE"


class AdvisorTokensNotConfiguredError(RuntimeError):
    """No hay fuente de tokens y el fallback dev-only no está habilitado."""

# Roles permitidos en `roles[]`. Cualquier otro valor → ValueError.
# (No hay enforcement de RBAC todavía — esto es solo validación de schema.)
ALLOWED_ROLES: frozenset[str] = frozenset({
    "advisor",
    "compliance",
    "admin",
    "viewer",
})

# Campos requeridos por entrada de token. Política estricta: además de
# requeridos, cualquier campo NO listado aquí → ValueError (fail-loud).
REQUIRED_TOKEN_FIELDS: frozenset[str] = frozenset({
    "advisor_id",
    "display_name",
    "firm_id",
    "roles",
})


# ─────────────────────────────────────────────────────────────────────────────
# Fallback development-only
# ─────────────────────────────────────────────────────────────────────────────
#
# Mismo mapa que vivía en `api_layer/auth.py` antes de este commit. Sigue
# siendo desarrollo-local. Reemplazar por archivo YAML explícito en
# staging/producción (vía env var `ADVISOR_TOKENS_FILE` o `config/advisor_tokens.yaml`).
# ─────────────────────────────────────────────────────────────────────────────

_DEV_ONLY_FALLBACK_TOKENS: dict[str, dict[str, Any]] = {
    "dev-advisor-token": {
        "advisor_id": "ADV-001",
        "display_name": "Demo Advisor",
        "firm_id": None,
        "roles": ["advisor"],
    },
    "dev-compliance-token": {
        "advisor_id": "CMP-001",
        "display_name": "Demo Compliance",
        "firm_id": None,
        "roles": ["compliance"],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de validación (privados, mismo patrón que risk_assumptions.py)
# ─────────────────────────────────────────────────────────────────────────────


def _assert_not_bool(value: Any, where: str) -> None:
    """
    Rechaza `bool` donde se espera `str`. En Python `isinstance(True, int)`
    es True; este guard debe correr ANTES de `isinstance(value, str)` o
    cualquier check numérico que pueda aceptar bools por accidente.
    """
    if isinstance(value, bool):
        raise ValueError(
            f"{where}: se esperaba string, no bool. Valor: {value!r}."
        )


def _assert_non_empty_str(value: Any, where: str) -> None:
    """Valida que `value` sea str, no bool, y no whitespace."""
    _assert_not_bool(value, where)
    if not isinstance(value, str):
        raise ValueError(
            f"{where}: se esperaba string, se recibió {type(value).__name__}."
        )
    if not value.strip():
        raise ValueError(
            f"{where}: el string no puede estar vacío ni ser solo espacios."
        )


def _load_yaml(path: Path) -> Any:
    """
    Lee y parsea un YAML. Errores claros sin filtrar contenido del archivo.

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: si el YAML es inválido o el documento es vacío.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Archivo de advisor tokens no encontrado: {path}."
        )
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML inválido en {path}: {exc}") from exc
    if data is None:
        raise ValueError(f"Archivo de advisor tokens vacío: {path}.")
    return data


def _validate_token_entry(
    token: str,
    entry: Any,
    source: str,
) -> dict[str, Any]:
    """
    Valida UNA entrada de token y devuelve el dict normalizado.

    `source` es la ruta del archivo (para mensajes de error). El propio
    `token` NO aparece en los mensajes de error — solo el contexto del
    archivo + el campo problemático.
    """
    # token-key validation: tiene que ser str no-vacío. NO se incluye el
    # valor en el mensaje (los tokens son secretos).
    if not isinstance(token, str) or isinstance(token, bool) or not token.strip():
        raise ValueError(
            f"{source}: encontrado un token-key inválido (tipo "
            f"{type(token).__name__} o vacío). Las claves deben ser strings "
            "no vacíos."
        )

    where = f"{source}: token entry"

    if not isinstance(entry, dict):
        raise ValueError(
            f"{where}: cada entry debe ser un mapping. "
            f"Recibido: {type(entry).__name__}."
        )

    keys = set(entry.keys())
    missing = REQUIRED_TOKEN_FIELDS - keys
    if missing:
        raise ValueError(
            f"{where}: faltan campos requeridos: {sorted(missing)}. "
            f"Esperados: {sorted(REQUIRED_TOKEN_FIELDS)}."
        )
    unknown = keys - REQUIRED_TOKEN_FIELDS
    if unknown:
        raise ValueError(
            f"{where}: campos desconocidos: {sorted(unknown)}. "
            f"Solo se aceptan: {sorted(REQUIRED_TOKEN_FIELDS)}."
        )

    # ── Validación por campo ──────────────────────────────────────────────
    _assert_non_empty_str(entry["advisor_id"], f"{where} 'advisor_id'")
    _assert_non_empty_str(entry["display_name"], f"{where} 'display_name'")

    firm_id = entry["firm_id"]
    if firm_id is not None:
        _assert_non_empty_str(firm_id, f"{where} 'firm_id'")

    roles = entry["roles"]
    if not isinstance(roles, list):
        raise ValueError(
            f"{where} 'roles': debe ser una lista. "
            f"Recibido: {type(roles).__name__}."
        )
    if not roles:
        raise ValueError(f"{where} 'roles': la lista no puede estar vacía.")
    for i, role in enumerate(roles):
        role_where = f"{where} 'roles'[{i}]"
        _assert_non_empty_str(role, role_where)
        if role not in ALLOWED_ROLES:
            raise ValueError(
                f"{role_where}: rol inválido {role!r}. "
                f"Permitidos: {sorted(ALLOWED_ROLES)}."
            )

    return {
        "advisor_id": entry["advisor_id"],
        "display_name": entry["display_name"],
        "firm_id": firm_id,
        "roles": list(roles),
    }


def _dev_fallback_enabled() -> bool:
    """True si alguna env var del kill-switch tiene valor no vacío."""
    for var in (DEV_TOKENS_FLAG_ENV_VAR, DEMO_MODE_ENV_VAR):
        if os.environ.get(var, "").strip():
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────────────────


def load_advisor_tokens(
    path: Path | str | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Carga y valida un archivo YAML de advisor tokens.

    No es la función de "default resolution" — eso es `get_default_advisor_tokens`.
    Esta función es un loader puro de UN archivo.

    Args:
        path: ruta al YAML. Si None, usa `DEFAULT_ADVISOR_TOKENS_PATH`.
              Pasar None y NO tener archivo en esa ruta → FileNotFoundError.

    Returns:
        Dict {token: {advisor_id, display_name, firm_id, roles}}.

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: si el YAML es inválido o el schema no cumple.
    """
    target = Path(path) if path is not None else DEFAULT_ADVISOR_TOKENS_PATH
    data = _load_yaml(target)

    if not isinstance(data, dict):
        raise ValueError(
            f"{target}: el documento raíz debe ser un mapping."
        )
    if "tokens" not in data:
        raise ValueError(
            f"{target}: falta la clave de nivel superior 'tokens'."
        )

    tokens_raw = data["tokens"]
    if not isinstance(tokens_raw, dict):
        raise ValueError(
            f"{target}: 'tokens' debe ser un mapping token → entry. "
            f"Recibido: {type(tokens_raw).__name__}."
        )
    if not tokens_raw:
        raise ValueError(f"{target}: 'tokens' no puede estar vacío.")

    result: dict[str, dict[str, Any]] = {}
    for token, entry in tokens_raw.items():
        result[token] = _validate_token_entry(token, entry, str(target))
    return result


def get_default_advisor_tokens() -> dict[str, dict[str, Any]]:
    """
    Devuelve el mapa de tokens de advisor con la siguiente cadena de fallback:

        1. ENV var `ADVISOR_TOKENS_FILE` (si está set y no vacío después de strip).
        2. `config/advisor_tokens.yaml` (si existe).
        3. Fallback hardcoded dev-only — SOLO con kill-switch habilitado
           (`RFA_ALLOW_DEV_TOKENS` o `RFA_DEMO_MODE` no vacías).

    Las opciones (1) y (2) REEMPLAZAN al fallback completamente (no hay merge).

    No cachea. Cada llamada vuelve a chequear env var y existencia de archivo.
    Para nuestra escala (1–3 advisors, pocos requests/segundo), el costo es
    irrelevante; a cambio, los tests pueden monkeypatchear env vars sin
    preocuparse por invalidar caches.

    Raises:
        FileNotFoundError: si la env var apunta a un archivo inexistente.
        ValueError: si el archivo cargado tiene schema inválido.
        AdvisorTokensNotConfiguredError: sin fuente de tokens y sin kill-switch.
            Fail-closed y fail-loud (FastAPI lo convierte en 500): preferimos
            un error operable a que tokens públicos autentiquen en silencio.
    """
    env_path = os.environ.get(ADVISOR_TOKENS_ENV_VAR)
    if env_path is not None and env_path.strip():
        return load_advisor_tokens(env_path.strip())

    if DEFAULT_ADVISOR_TOKENS_PATH.exists():
        return load_advisor_tokens(DEFAULT_ADVISOR_TOKENS_PATH)

    if not _dev_fallback_enabled():
        raise AdvisorTokensNotConfiguredError(
            "No hay fuente de advisor tokens: ni ADVISOR_TOKENS_FILE, ni "
            f"{DEFAULT_ADVISOR_TOKENS_PATH.name} en config/, ni el fallback "
            "dev-only habilitado. Para desarrollo local, setear "
            f"{DEV_TOKENS_FLAG_ENV_VAR}=1 (o {DEMO_MODE_ENV_VAR}=1 si es la "
            "demo guiada). Para cualquier otro entorno, proveer un YAML de "
            "tokens propio."
        )

    # Fallback: devolver copia profunda para evitar mutación accidental
    # del fallback compartido entre llamadas.
    return {
        token: {
            "advisor_id": entry["advisor_id"],
            "display_name": entry["display_name"],
            "firm_id": entry["firm_id"],
            "roles": list(entry["roles"]),
        }
        for token, entry in _DEV_ONLY_FALLBACK_TOKENS.items()
    }
