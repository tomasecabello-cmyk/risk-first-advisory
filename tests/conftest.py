"""
Fixtures globales de la suite.

RFA_ALLOW_DEV_TOKENS=1: la suite completa asume disponible el fallback
dev-only de advisor tokens (dev-advisor-token / dev-compliance-token).
Desde el kill-switch de seguridad (2026-07), el fallback es fail-closed
sin esta env var. Los tests que verifican el comportamiento fail-closed
la borran explícitamente con monkeypatch.
"""

from __future__ import annotations

import os

os.environ.setdefault("RFA_ALLOW_DEV_TOKENS", "1")
