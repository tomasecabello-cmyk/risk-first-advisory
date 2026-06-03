# Risk Gap — Notas de metodología (honestidad para revisión académica)

Este documento dice con precisión **qué es y qué no es** el Risk Gap, para
presentarlo a un profesor o asesor sin sobre-vender el mecanismo.

## Qué ES

El Risk Gap es un **flag de inconsistencia**. Compara el perfil de riesgo que el
cliente **declara** en el KYC contra **otras respuestas del mismo cliente**
(incluida su reacción a un escenario de estrés), y marca cuando hay una
contradicción. Cuando la marca, le entrega al asesor **preguntas concretas** para
confirmarla con el cliente.

El output es:
- `declared_profile`: el perfil declarado (uno de los 5 perfiles del sistema).
- `stress_signal`: la respuesta del cliente al escenario de estrés (texto del KYC).
- `gap_level`: `low` | `medium` | `high` (cualitativo).
- `gap_explanation`: la lectura en lenguaje natural.
- `confirmation_questions`: 1–2 preguntas para que el asesor investigue.

## Qué NO es

- **NO es una medición ni una inferencia de un "perfil conductual".** No
  produce un score psicométrico ni clasifica la conducta del cliente.
- **NO es un instrumento validado** tipo FinaMetrica / Oxford Risk / Riskalyze.
  No tiene validación psicométrica, ni calibración, ni base poblacional.
- **NO emite un número de confianza.** Deliberadamente no hay un `confidence`
  numérico: sería un número inventado, indefendible ante la pregunta "¿calibrado
  contra qué?". El nivel es cualitativo (low/medium/high).
- **NO decide el perfil.** La IA propone la señal; **el asesor decide** el perfil
  y lo aprueba (human-in-the-loop). Es una regla dura del sistema.

## Cómo funciona (mecanismo real)

`gap_level` se deriva de las **contradicciones** que el análisis de KYC ya detecta
(`OpenAIProfileClient.analyze_kyc`), mapeadas por una función pura y determinística
(`ai_layer/risk_gap.py::derive_risk_gap`):
- contradicción de severidad alta → `high`
- severidad media → `medium`
- sin contradicciones → `low` (estado alineado: "sin inconsistencia que confirmar")

En la demo local sin `OPENAI_API_KEY` (`RFA_DEMO_MODE=1`), un cliente determinístico
deriva la contradicción de la señal de estrés del KYC (`open_risk_reaction`). No hay
LLM en ese camino; es regla explícita y reproducible.

## Límites conocidos / trabajo futuro (M-Engine)

- La inferencia real vía LLM del flag (no solo el mapeo de contradicciones) está
  **diferida** hasta validar con asesores reales que el gap es un dolor que cambia
  su flujo de trabajo.
- Un LLM es no determinístico: M-Engine requiere un chequeo de consistencia
  (mismo KYC → mismo `gap_level`) antes de presentarse como confiable.
- No reemplaza un instrumento de tolerancia al riesgo validado. Si el objetivo
  fuera medir conducta, ese es un problema de investigación distinto (behavioral
  finance / prospect theory), explícitamente fuera de alcance.
