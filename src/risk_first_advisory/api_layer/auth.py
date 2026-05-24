"""
Advisor authentication scaffold — Phase 1.

DEVELOPMENT-ONLY. This module implements a minimal Bearer-token check used to
resolve the advisor identity behind a request. It is a scaffold for the Phase-1
approval endpoints; it is NOT a production auth system.

Out of scope here:
    - JWT signing / rotation
    - .env loading or secret storage
    - Token issuance, refresh, revocation
    - Per-firm tenancy enforcement
    - Rate limiting / brute force protection

Design:
    - `AdvisorIdentity` is the small dataclass that downstream endpoints will
      consume via FastAPI `Depends(...)`.
    - `get_current_advisor_optional` returns `AdvisorIdentity | None`:
        * no Authorization header  → None
        * invalid token / malformed → HTTP 401
        * valid token              → AdvisorIdentity
      Use this when an endpoint *may* benefit from advisor identity but must
      still work for anonymous demo callers.
    - `get_current_advisor_required` returns `AdvisorIdentity` and ALWAYS
      raises HTTP 401 on missing/invalid auth. Use this in approval / override
      endpoints where an advisor identity is mandatory.

Error policy:
    - Never echo the offending token in error messages or logs.
    - Always use the same generic message so an attacker cannot distinguish
      "unknown token" from "malformed header".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from fastapi import Header, HTTPException, status


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
# Development-only token mapping. Replace before production.
# ─────────────────────────────────────────────────────────────────────────────
#
# This map is intentionally hard-coded for Phase 1. Real tokens must come from
# an external identity provider (JWT signed by IdP, OIDC session, etc.). Until
# that exists, these demo tokens let us iterate on approval endpoints locally.
#
# DO NOT commit real tokens here. DO NOT load secrets from .env in this phase.
# ─────────────────────────────────────────────────────────────────────────────

_DEMO_TOKENS: Mapping[str, AdvisorIdentity] = {
    "dev-advisor-token": AdvisorIdentity(
        advisor_id="ADV-001",
        display_name="Demo Advisor",
        firm_id=None,
        roles=["advisor"],
    ),
    "dev-compliance-token": AdvisorIdentity(
        advisor_id="CMP-001",
        display_name="Demo Compliance",
        firm_id=None,
        roles=["compliance"],
    ),
}


# Generic error message — never leaks token shape or value.
_AUTH_ERROR_DETAIL: str = "Invalid or missing advisor authentication token."


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────


def _raise_401() -> None:
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


def _lookup_advisor(token: str) -> AdvisorIdentity:
    """
    Resuelve el token al `AdvisorIdentity` correspondiente. 401 si el token
    no está registrado. No loguea ni incluye el token en el error.
    """
    identity = _DEMO_TOKENS.get(token)
    if identity is None:
        _raise_401()
    return identity


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
    # type-check: _raise_401 levanta excepción; aquí token es str.
    return _lookup_advisor(token)
