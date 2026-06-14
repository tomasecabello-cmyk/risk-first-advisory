"""
run_ai_profile_demo.py

Demo aislado de análisis de KYC con IA real (OpenAI).

Construye un KYC payload de ejemplo con contradicción intencional:
    - risk_tolerance_score bajo (4/10) — perfil conservador/defensivo
    - risk_capacity_score alto (8/10) — financieramente puede asumir riesgo
    - liquidity_need_score alto (7/10) — necesita liquidez a corto plazo
    - horizonte de inversión largo (15 años)
    - preocupación explícita por pérdidas en campos abiertos

La IA debería detectar la contradicción entre la baja tolerancia al riesgo,
la alta necesidad de liquidez y el largo horizonte declarado, y proponer
preguntas de follow-up para el asesor.

Uso:
    python scripts/run_ai_profile_demo.py

Requisitos:
    - OPENAI_API_KEY configurada en el entorno.
    - pip install openai

Si falta la API key, muestra instrucciones y sale con exit code 0
(para no romper entornos de CI sin IA configurada).
"""

from __future__ import annotations

import json
import sys

# ─────────────────────────────────────────────────────────────────────────────
# KYC payload de ejemplo
# ─────────────────────────────────────────────────────────────────────────────

DEMO_KYC_PAYLOAD: dict = {
    # Scores cuantitativos
    "risk_tolerance_score": 4,           # baja tolerancia subjetiva al riesgo
    "risk_capacity_score": 8,            # alta capacidad financiera
    "liquidity_need_score": 7,           # alta necesidad de liquidez
    "investment_horizon_years": 15,      # horizonte largo → contradice alta liquidez
    "max_acceptable_drawdown_pct": 10.0, # máximo 10% de caída → muy conservador

    # Perfil cualitativo
    "investment_experience": "moderada",
    "income_stability": "stable",
    "net_worth": 500_000,
    "liquid_net_worth": 150_000,

    # Expectativa declarada de retorno (la IA no debe usar esto para elevar perfil)
    "declared_return_expectation_pct": 15.0,  # expectativa alta — inconsistente con tolerancia

    # Campos abiertos
    "open_investment_goal": (
        "Quiero hacer crecer mi capital para la jubilación en 15 años, "
        "pero también me gustaría poder acceder al dinero si surge una emergencia."
    ),
    "open_risk_reaction": (
        "Me preocuparía mucho ver mi cartera caer más del 10%. "
        "Probablemente vendería si las pérdidas superan ese umbral."
    ),
    "open_past_experience": (
        "He tenido fondos de inversión durante 5 años. "
        "Vendí todo durante la pandemia de 2020 cuando vi las pérdidas."
    ),
    "open_concerns": (
        "Me preocupa la inflación, pero también me da miedo perder capital. "
        "Prefiero seguridad antes que rentabilidad alta."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Formateo de output
# ─────────────────────────────────────────────────────────────────────────────

def _print_section(title: str, width: int = 68) -> None:
    print()
    print("─" * width)
    print(f"  {title}")
    print("─" * width)


def _print_result(result: dict) -> None:
    profile = result.get("preliminary_profile", "—")
    confidence = result.get("confidence", 0.0)
    contradictions = result.get("contradictions", [])
    follow_ups = result.get("follow_up_questions", [])
    advisor_notes = result.get("advisor_notes", [])

    _print_section("PRELIMINARY PROFILE")
    print(f"  Profile    : {profile}")
    print(f"  Confidence : {confidence * 100:.1f}%")

    _print_section(f"CONTRADICTIONS DETECTED ({len(contradictions)})")
    if contradictions:
        for i, c in enumerate(contradictions, 1):
            sev = c.get("severity", "—").upper()
            field = c.get("field", "—")
            explanation = c.get("explanation", "—")
            print(f"  {i}. [{sev}] {field}")
            print(f"     {explanation}")
    else:
        print("  None detected.")

    _print_section(f"FOLLOW-UP QUESTIONS FOR ADVISOR ({len(follow_ups)})")
    if follow_ups:
        for i, q in enumerate(follow_ups, 1):
            print(f"  {i}. {q}")
    else:
        print("  None suggested.")

    _print_section(f"ADVISOR NOTES ({len(advisor_notes)})")
    if advisor_notes:
        for i, n in enumerate(advisor_notes, 1):
            print(f"  {i}. {n}")
    else:
        print("  None.")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    print()
    print("=" * 68)
    print("  RISK-FIRST ADVISORY — AI Profile Demo (OpenAI)")
    print("  Análisis aislado de KYC — sin workflow, sin frontend.")
    print("=" * 68)

    # ── Importar cliente ───────────────────────────────────────────────────
    try:
        from risk_first_advisory.ai_layer.openai_profile_client import (
            OpenAIProfileClient,
        )
    except ImportError as exc:
        print(f"\n[ERROR] No se pudo importar el módulo: {exc}")
        print("Asegurate de correr desde el root del proyecto con el venv activado.")
        return 1

    # ── Crear cliente (valida OPENAI_API_KEY) ──────────────────────────────
    try:
        client = OpenAIProfileClient()
    except ValueError as exc:
        print(f"\n[INFO] {exc}")
        print()
        print("  Para configurar la API key:")
        print()
        print("    Windows (PowerShell):")
        print("      $env:OPENAI_API_KEY = 'sk-...'")
        print()
        print("    Windows (cmd):")
        print("      set OPENAI_API_KEY=sk-...")
        print()
        print("    Unix/macOS:")
        print("      export OPENAI_API_KEY=sk-...")
        print()
        print("  Luego volver a correr el script.")
        return 0   # exit 0: no fallar en entornos sin API key
    except ImportError as exc:
        print(f"\n[ERROR] {exc}")
        print("  Instalar con: pip install openai")
        return 1

    # ── Mostrar KYC payload ────────────────────────────────────────────────
    _print_section("KYC PAYLOAD (demo)")
    for k, v in DEMO_KYC_PAYLOAD.items():
        if isinstance(v, str) and len(v) > 60:
            print(f"  {k}:")
            print(f"    \"{v[:80]}{'...' if len(v) > 80 else ''}\"")
        else:
            print(f"  {k}: {v!r}")

    # ── Llamar a la IA ─────────────────────────────────────────────────────
    print()
    print("  Llamando a OpenAI API...")

    try:
        result = client.analyze_kyc(DEMO_KYC_PAYLOAD)
    except ValueError as exc:
        print(f"\n[ERROR] {exc}")
        return 1
    except Exception as exc:
        print(f"\n[ERROR] Error inesperado: {type(exc).__name__}: {exc}")
        return 1

    # ── Mostrar resultado formateado ───────────────────────────────────────
    _print_result(result)

    # ── Mostrar JSON completo ──────────────────────────────────────────────
    _print_section("FULL JSON RESPONSE")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    print()
    print("=" * 68)
    print("  ✓  AI PROFILE DEMO COMPLETED")
    print("     Nota: este es un perfil PRELIMINAR.")
    print("     La aprobación final siempre corresponde al asesor humano.")
    print("=" * 68)
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
