"""
Advisor authentication scaffold — Fase 1, ajustado en Fase 2.

DEVELOPMENT-ONLY. This module implements a minimal Bearer-token check used to
resolve the advisor identity behind a request. It is a scaffold for the Phase-1
approval endpoints; it is NOT a production auth system.

Out of scope here:
    - JWT signing / rotation
    - .env loading or secret storage
    - Token issuance, refresh, revocation
    - Per-firm tenancy enforcement
    - Rate limiting / brute force protection

Diseño:
    - `AdvisorIdentity` es el dataclass que los endpoints downstream consumen
      vía FastAPI `Depends(...)`.
    - `get_current_advisor_optional` devuelve `AdvisorIdentity | None`:
        * no Authorization header  → None
        * invalid token / malformed → HTTP 401
        * valid token              → AdvisorIdentity
      Para endpoints que pueden seguir funcionando anónimos pero aprovechan
      la identidad cuando exista.
    - `get_current_advisor_required` devuelve `AdvisorIdentity` y SIEMPRE
      levanta HTTP 401 ante missing/invalid auth.

Cambio de Fase 2:
    - El mapa de tokens ya NO vive hardcoded en este archivo.
    - `_lookup_advisor` consulta `config_layer.advisor_tokens.get_default_advisor_tokens()`
      que resuelve, en orden:
        1. ENV var `ADVISOR_TOKENS_FILE`
        2. `config/advisor_tokens.yaml`
        3. Fallback dev-only (mismos tokens que antes: dev-advisor-token /
           dev-compliance-token) — para que tests y demos no necesiten archivo.
    - El contrato externo NO cambia: los endpoints siguen recibiendo
      `AdvisorIdentity` con la misma forma.

Error policy:
    - Nunca echo del token ofensor en mensajes ni logs.
    - Mismo mensaje genérico para todos los caminos de error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NoReturn

from fastapi import Header, HTTPException, status

from risk_first_advisory.config_layer.advisor_tokens import (
    get_default_advisor_tokens,
)


# ─────────────────────────────────────────────────────────────────────────────
# AdvisorIdentity
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AdvisorIdentity:
    """Identidad resuelta del asesor que ejecuta la request."""

    advisor_id: str
    display_name: str
    firm_id: str | None = None
    roles: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.advisor_id, str) or not self.advisor_id.strip():
            raise ValueError("advisor_id no puede estar vacío.")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("display_name no puede estar vacío.")
        if self.firm_id is not None and (
            not isinstance(self.firm_id, str) or not self.firm_id.strip()
        ):
            raise ValueError("firm_id, si se provee, no puede ser cadena vacía.")
        if not isinstance(self.roles, list):
            raise ValueError("roles debe ser una lista.")
        for r in self.roles:
            if not isinstance(r, str) or not r.strip():
                raise ValueError("cada rol debe ser un string no vacío.")


# ─────────────────────────────────────────────────────────────────────────────
# Token lookup — delegated to config_layer.advisor_tokens
# ─────────────────────────────────────────────────────────────────────────────
#
# El mapa de tokens se resuelve dinámicamente en cada lookup vía
# `get_default_advisor_tokens()`. Esto deja que tests monkeypatcheen el env
# var `ADVISOR_TOKENS_FILE` sin tener que invalidar caches manualmente.
#
# El costo en perf es despreciable a esta escala (1–3 advisors, pocos
# requests/segundo); a cambio se gana simplicidad y testabilidad.
#
# NO commitear tokens reales — el archivo `config/advisor_tokens.yaml` está
# gitignored. El fallback dev-only es para tests/demos exclusivamente.
# ─────────────────────────────────────────────────────────────────────────────


# Generic error message — never leaks token shape or value.
_AUTH_ERROR_DETAIL: str = "Invalid or missing advisor authentication token."

# RBAC error message — same string regardless of which role(s) were required.
# Never reveals the caller's roles, the allowed set, or the token.
_RBAC_ERROR_DETAIL: str = "Advisor role is not authorized for this action."


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────


def _raise_401() -> NoReturn:
    """
    Levanta HTTP 401 con detalle genérico y cabecera WWW-Authenticate
    según RFC 6750. Centralizado para garantizar que ningún caller
    inadvertidamente expone más información.
    """
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_AUTH_ERROR_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _extract_bearer_token(authorization: str | None) -> str | None:
    """
    Devuelve el token bruto del header Authorization, o None si la cabecera
    no está presente. Levanta HTTP 401 si la cabecera está mal formada.

    Acepta solo el esquema 'Bearer' (case-insensitive). Cualquier otro esquema
    o formato → 401.

    Reglas:
        - None / "" / cadena con solo espacios          → None (sin auth)
        - "Basic xyz"                                    → 401 (esquema no soportado)
        - "Bearer"                                       → 401 (sin token)
        - "Bearer "                                      → 401 (token vacío)
        - "Bearer abc def"                               → 401 (token con espacios)
        - "Bearer abc"                                   → "abc"
    """
    if authorization is None:
        return None

    stripped = authorization.strip()
    if not stripped:
        # Header presente pero vacío → tratamos como ausente para que
        # get_current_advisor_optional pueda devolver None de forma natural.
        return None

    parts = stripped.split()
    # Esperamos exactamente dos tokens: "Bearer" + <opaque>.
    if len(parts) != 2:
        _raise_401()
    scheme, token = parts[0], parts[1]
    if scheme.lower() != "bearer":
        _raise_401()
    if not token.strip():
        _raise_401()
    return token


def _identity_from_entry(entry: dict[str, Any]) -> AdvisorIdentity:
    """
    Construye un `AdvisorIdentity` desde el dict que devuelve el loader.
    El loader ya validó schema; este builder solo arma el dataclass.
    """
    return AdvisorIdentity(
        advisor_id=entry["advisor_id"],
        display_name=entry["display_name"],
        firm_id=entry.get("firm_id"),
        roles=list(entry["roles"]),
    )


def _lookup_advisor(token: str) -> AdvisorIdentity:
    """
    Resuelve el token al `AdvisorIdentity` correspondiente. 401 si el token
    no está registrado. No loguea ni incluye el token en el error.

    El lookup va a `get_default_advisor_tokens()` que aplica la cadena de
    resolución env-var → file → fallback. Cualquier error de schema en el
    archivo configurado se propaga (FastAPI lo convierte en 500), porque
    una config rota debe fallar loud y no silenciar como 401.
    """
    tokens = get_default_advisor_tokens()
    entry = tokens.get(token)
    if entry is None:
        _raise_401()
    return _identity_from_entry(entry)


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI dependencies
# ─────────────────────────────────────────────────────────────────────────────


def get_current_advisor_optional(
    authorization: str | None = Header(default=None),
) -> AdvisorIdentity | None:
    """
    Devuelve la identidad del asesor si hay un Bearer válido. Devuelve None
    si la cabecera Authorization está ausente. Levanta 401 si la cabecera está
    presente pero es inválida.

    Usar en endpoints que aún funcionan de forma anónima en demo pero
    pueden aprovechar la identidad del asesor cuando esté disponible.
    """
    token = _extract_bearer_token(authorization)
    if token is None:
        return None
    return _lookup_advisor(token)


def get_current_advisor_required(
    authorization: str | None = Header(default=None),
) -> AdvisorIdentity:
    """
    Devuelve la identidad del asesor. Levanta 401 si la cabecera falta o el
    token es inválido.

    Usar en endpoints de aprobación / override donde la identidad del asesor
    es obligatoria (firma de GROWTH, selección de variante, etc.).
    """
    token = _extract_bearer_token(authorization)
    if token is None:
        _raise_401()
    # _raise_401 es NoReturn → token es str aquí.
    return _lookup_advisor(token)


# ─────────────────────────────────────────────────────────────────────────────
# RBAC — require_roles factory
# ─────────────────────────────────────────────────────────────────────────────


def require_roles(*allowed_roles: str):
    """
    Factory de dependencias FastAPI para RBAC a nivel de rol.

    Uso:
        @app.post("/advisor/some-act")
        def my_endpoint(
            advisor: AdvisorIdentity = Depends(require_roles("advisor", "admin")),
        ) -> ...:
            ...

    Comportamiento:
        - Token ausente o malformado  → HTTP 401 (igual que
          get_current_advisor_required).
        - Token válido, pero ningún rol del advisor está en `allowed_roles`
          → HTTP 403, detalle genérico, sin eco del token ni de los roles.
        - Token válido + rol permitido → devuelve AdvisorIdentity.

    Precondición de arranque:
        require_roles() sin argumentos es un error de programación —
        levanta ValueError en tiempo de definición del endpoint, no en runtime.

    Política de información:
        El error 403 siempre usa `_RBAC_ERROR_DETAIL`: misma cadena sin
        importar qué roles faltan, para no filtrar la estructura de permisos.
    """
    if not allowed_roles:
        raise ValueError(
            "require_roles() debe recibir al menos un rol. "
            "Usar get_current_advisor_required() si no hay restricción de rol."
        )
    allowed: frozenset[str] = frozenset(allowed_roles)

    def _check(authorization: str | None = Header(default=None)) -> AdvisorIdentity:
        token = _extract_bearer_token(authorization)
        if token is None:
            _raise_401()
        # _raise_401 es NoReturn → token es str aquí.
        identity = _lookup_advisor(token)
        if not any(r in allowed for r in identity.roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_RBAC_ERROR_DETAIL,
            )
        return identity

    return _check
