# Prompt Design — risk-first-advisory

Reglas de diseño para los prompts enviados al modelo de IA en el flujo de perfilado de riesgo. Aplican al `MockAIClient` actual y deben trasladarse al cliente de IA real en M2/M3.

---

## Principios generales

### P-001 — La IA propone, no aprueba

El output de la IA es siempre un `PreliminaryProfile` con `advisor_review_required = True`. El prompt no debe solicitar ni el modelo debe producir un perfil definitivo. El lenguaje del output debe dejar claro que es una propuesta sujeta a revisión del asesor.

**Correcto:** "Based on the client's data, the preliminary risk profile is **moderado**, pending advisor review."  
**Incorrecto:** "The client's approved risk profile is moderado."

### P-002 — El perfil se propone, no se justifica en términos de retorno

El prompt no debe incluir el `declared_return_expectation_pct` como input para determinar el perfil. El retorno esperado del cliente es informativo para el asesor, no una restricción de diseño del perfil. La propuesta de perfil se basa en tolerancia emocional, capacidad financiera, horizonte y objetivo de inversión declarado.

**Correcto:** Incluir `emotional_loss_tolerance_pct`, `financial_loss_capacity_pct`, `time_horizon_years`, `investment_objective` como inputs del perfil.  
**Incorrecto:** Incluir `declared_return_expectation_pct` como criterio de selección del perfil.

### P-003 — La IA debe detectar contradicciones y reportarlas con severidad

El modelo debe identificar contradicciones entre los datos del KYC. Una contradicción es cualquier par de campos cuya combinación indica inconsistencia en el perfil del cliente.

Ejemplos de contradicciones a detectar:
- `emotional_loss_tolerance_pct` alto + `investment_objective = preservacion_capital` (contradictorio: el cliente dice tolerar pérdidas pero quiere preservar capital).
- `experience = ninguna` + `prefers_simple_products = False` (contradictorio: el cliente sin experiencia prefiere productos complejos).
- `time_horizon_years` corto + `investment_objective = crecimiento_agresivo` (contradictorio: horizonte corto incompatible con objetivos de crecimiento).

Cada contradicción debe incluir:
- `dimension_a`: primer campo involucrado.
- `dimension_b`: segundo campo involucrado.
- `severity`: `"alta"` (requiere follow-up) o `"baja"` (informativa).
- `explanation`: descripción legible de la contradicción.

### P-004 — Contradicciones de severidad alta requieren follow-up

Si el modelo detecta al menos una contradicción de severidad `"alta"`, debe incluir preguntas de follow-up en el output (`follow_up_questions`). El flujo M1 ejecuta el ciclo de follow-up solo cuando `has_blocking_contradictions() is True`.

Las preguntas de follow-up deben:
- Ser específicas sobre la contradicción detectada.
- Estar formuladas para el asesor (no para el cliente directamente).
- Permitir al asesor aportar contexto real que la IA no puede inferir del KYC (ej. historial de comportamiento bajo estrés, patrimonio no declarado, contexto fiscal).

### P-005 — El modelo revisa el perfil tras el follow-up con las respuestas del asesor

Cuando el asesor responde el follow-up, el modelo recibe:
- El KYC original.
- El `PreliminaryProfile` inicial (con sus contradicciones).
- Las respuestas del asesor (`FollowUpResponse` list).

El output de la revisión es un nuevo `PreliminaryProfile` (revised) que debe reflejar el contexto aportado por el asesor. Si las respuestas resuelven las contradicciones, el revised profile no debe listar esas contradicciones. Si el contexto no las resuelve, el revised profile puede mantenerlas con su severidad original.

### P-006 — El modelo no recomienda portfolios ni activos específicos

El output de la IA se limita al `PreliminaryProfile` (nombre del perfil, dimensión vinculante, contradicciones, preguntas de follow-up). El modelo no debe sugerir activos, porcentajes de asignación, fondos específicos ni estrategias de inversión concretas.

La generación de portfolios es responsabilidad de `PortfolioGenerationCoordinator`, que opera sobre el `RiskBudget` aprobado y el universo filtrado, sin participación del modelo de lenguaje.

### P-007 — La dimensión vinculante determina el perfil cuando hay conflicto

Cuando los datos del KYC producen señales mixtas (ej. alta tolerancia emocional pero baja capacidad financiera), el modelo debe indicar cuál dimensión es la más restrictiva (`binding_dimension`). El perfil propuesto refleja la dimensión más restrictiva, no el promedio.

Ejemplo: cliente con alta tolerancia emocional (`emotional_loss_tolerance_pct = 0.40`) pero baja capacidad financiera (`financial_loss_capacity_pct = 0.10`) → `binding_dimension = "financial_capacity"` → perfil conservador, no agresivo.

### P-008 — Trazabilidad de reason codes en el output

El `PreliminaryProfile` debe incluir `detected_contradictions` con suficiente detalle para que el asesor entienda por qué el modelo propuso ese perfil y no otro. La trazabilidad no es opcional: es el mecanismo que permite al asesor evaluar, modificar y aprobar la propuesta con conocimiento de causa.

---

## Estructura del output esperado del modelo

El modelo debe producir un JSON con la siguiente estructura (compatible con `MockAIClient`):

```json
{
  "profile_name": "moderado-defensivo",
  "confidence": 0.72,
  "binding_dimension": "emotional_tolerance",
  "detected_contradictions": [
    {
      "dimension_a": "emotional_loss_tolerance_pct",
      "dimension_b": "investment_objective",
      "severity": "alta",
      "explanation": "El cliente declara alta tolerancia a pérdidas pero su objetivo es preservación de capital, lo que sugiere que la tolerancia declarada puede no ser real."
    }
  ],
  "follow_up_questions": [
    "¿El cliente ha experimentado pérdidas superiores al 15% en carteras anteriores? ¿Cuál fue su reacción documentada?",
    "¿El objetivo de 'preservación de capital' refleja una restricción real (ej. compromisos fiscales próximos) o es una preferencia general?"
  ],
  "advisor_review_required": true
}
```

Campos:
- `profile_name`: uno de los perfiles canónicos del sistema (ej. `conservador`, `moderado-defensivo`, `moderado`, `moderado-agresivo`, `agresivo`).
- `confidence`: float en [0, 1]. Refleja el nivel de certeza del modelo dado los datos disponibles.
- `binding_dimension`: campo del KYC que más limitó el perfil.
- `detected_contradictions`: lista (puede estar vacía).
- `follow_up_questions`: lista (vacía si no hay contradicciones de severidad alta).
- `advisor_review_required`: siempre `true`.

---

## Límites del modelo (M1)

En M1, el modelo es `MockAIClient` con respuestas scripted por fixture. No hay llamadas a un LLM real. Las respuestas scripted deben cumplir todas las reglas de esta sección para que los tests de integración sean representativos del comportamiento esperado del modelo real.

Antes de sustituir `MockAIClient` por un cliente real, se debe:
1. Validar que el modelo real cumple P-001 a P-008 contra el conjunto de fixtures existente.
2. Agregar tests de evaluación de output (no solo de estructura JSON) para contradicciones y follow-up.
3. Definir un proceso de revisión humana de prompts antes de cambios en producción.
