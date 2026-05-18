# Design Decisions — risk-first-advisory

Formato ADR liviano. Cada decisión incluye contexto, alternativa descartada y consecuencias.

---

## DD-001 — `risk_need` no entra en la construcción del perfil

**Estado:** Aceptado  
**Fecha:** 2026-Q1  
**Área:** `kyc`, `ai_layer`, `rules_layer`

**Contexto:** En algunos modelos de perfilado tradicional, el "riesgo necesario" (risk need) —cuánto riesgo debe tomar el cliente para alcanzar su objetivo— se combina con la tolerancia y capacidad para producir el perfil final. Esto crea circularidad: el perfil depende del objetivo de retorno, que depende del perfil.

**Decisión:** `risk_need` no se usa como input de la construcción del perfil en `ai_layer` ni en `RiskBudgetBuilder`. El perfil se construye a partir de tolerancia emocional, capacidad financiera, horizonte y objetivo de inversión declarado. La viabilidad del objetivo se evalúa por separado en `GoalFeasibilityEngine` después de que el perfil está aprobado.

**Alternativa descartada:** Pasar `risk_need` calculado desde `FinancialGoal` como campo adicional al constructor del perfil. Descartada por circularidad y porque convierte una evaluación de viabilidad en una restricción de diseño del cliente.

**Consecuencias:** La evaluación de goal feasibility puede bloquear el workflow después del M1. El asesor recibe un diagnóstico claro (perfil aprobado + objetivo inviable) en lugar de un perfil inflado artificialmente por el risk need.

---

## DD-002 — `return_target_annual_pct` se elimina del `KYCData`

**Estado:** Aceptado  
**Fecha:** 2026-Q1  
**Área:** `kyc`

**Contexto:** Una versión anterior del modelo de datos incluía `return_target_annual_pct` como campo declarado del cliente en `KYCData`. Esto implicaba que el cliente o asesor fijaban un retorno objetivo en el momento del onboarding.

**Decisión:** El campo fue eliminado. El retorno objetivo se deriva siempre de `FinancialGoal` (capital inicial, capital objetivo, horizonte, aportes). No existe como dato independiente en el KYC.

**Alternativa descartada:** Mantenerlo como campo opcional. Descartada porque su presencia invitaba a usarlo como input del optimizador o del feasibility engine, generando inconsistencias entre lo que el cliente "quiere" y lo que el objetivo financiero requiere.

**Consecuencias:** `GoalFeasibilityEngine` tiene una única fuente de verdad para el retorno requerido. Los tests que buscaban `return_target_annual_pct` en el KYC fueron eliminados. Ver DD-004.

---

## DD-003 — `declared_return_expectation_pct` queda como dato informativo

**Estado:** Aceptado  
**Fecha:** 2026-Q1  
**Área:** `kyc`, `rules_layer`

**Contexto:** Los clientes frecuentemente tienen una expectativa declarada de retorno ("quiero ganar un 10% anual") que puede diferir del retorno necesario para su objetivo y del retorno alcanzable para su perfil. Esta expectativa es información relevante para el asesor.

**Decisión:** `KYCData.declared_return_expectation_pct` se mantiene como campo opcional e informativo. Ningún componente de rules_layer, data_layer, portfolio_layer ni workflow_layer lo usa como input de cálculo. Su presencia en el KYC sirve para que el asesor compare expectativa vs. realidad durante la sesión de perfilado.

**Alternativa descartada:** Usarlo como restricción de retorno mínimo en el optimizador. Descartada: las expectativas del cliente no son restricciones de compliance; son input para la conversación asesor-cliente.

**Consecuencias:** El campo existe pero permanece "inerte" para el motor. Si en el futuro se decide usarlo para generar advertencias automáticas ("expectativa supera el alcanzable"), debe hacerse en la capa de reporting o en una capa de análisis separada, no en rules_layer.

---

## DD-004 — `GoalFeasibilityEngine` usa `FinancialGoal` como fuente única

**Estado:** Aceptado  
**Fecha:** 2026-Q1  
**Área:** `rules_layer`

**Contexto:** El motor de factibilidad necesita calcular el retorno anual requerido para que el cliente alcance su objetivo. Hay dos candidatos: `FinancialGoal` (capital, horizonte, aportes) y `declared_return_expectation_pct` del KYC.

**Decisión:** `GoalFeasibilityEngine.evaluate(financial_goal, profile_name)` usa exclusivamente `FinancialGoal`. El retorno requerido se calcula por valor futuro descontado (fórmula de anualidad). `declared_return_expectation_pct` no participa.

**Alternativa descartada:** Aceptar ambos y tomar el mayor. Descartada: mezclaría una expectativa subjetiva con un objetivo objetivo, produciendo resultados difíciles de auditar.

**Consecuencias:** El feasibility es reproducible y auditable. El asesor puede mostrar al cliente exactamente por qué su objetivo es o no viable, basado en números, no en expectativas declaradas.

---

## DD-005 — Product governance va antes que suitability, ESG y datos

**Estado:** Aceptado  
**Fecha:** 2026-Q1  
**Área:** `rules_layer`, `workflow_layer`

**Contexto:** El pipeline de filtros aplica cuatro criterios en secuencia. El orden importa porque cada filtro reduce el universo y los subsiguientes operan sobre el subconjunto ya filtrado.

**Decisión:** El orden fijo es: governance → suitability → ESG → market data/DQ. Governance elimina instrumentos que no están aprobados para el perfil del cliente en absoluto; tiene sentido que sea el primer filtro porque es el más categórico desde el punto de vista regulatorio.

**Alternativa descartada:** Aplicar los filtros en paralelo y hacer la intersección al final. Descartada: oculta cuántos instrumentos caen en cada etapa, lo que dificulta el diagnóstico de asesor y la auditoría de compliance.

**Consecuencias:** Los `reason_codes` y las listas de tickers por etapa en `AdvisoryWorkflowResult` permiten reconstruir exactamente qué filtro eliminó cada instrumento. El asesor puede actuar sobre la causa raíz.

---

## DD-006 — `DataQualityGate` bloquea datos stale o con campos críticos faltantes

**Estado:** Aceptado  
**Fecha:** 2026-Q1  
**Área:** `data_layer`

**Contexto:** El optimizador necesita datos de retorno y covarianza fiables. Datos stale o incompletos producen pesos de cartera inválidos que pasan todos los tests formales pero son incorrectos en la práctica.

**Decisión:** `DataQualityGate` evalúa cada snapshot antes de que llegue al `ReturnEstimator` y al `CovarianceEngine`. Los tickers con status FAIL o `is_usable = False` se excluyen del universo final. Los tickers con status WARNING se incluyen pero se emite un `reason_code`.

**Alternativa descartada:** Dejar que el optimizer falle o produzca pesos degenerados con datos malos. Descartada: el fallo del optimizer produce mensajes crípticos; el DataQualityGate produce mensajes accionables.

**Consecuencias:** El universo final siempre contiene solo tickers con datos utilizables. El asesor ve exactamente qué tickers fueron excluidos por calidad de datos y por qué.

---

## DD-007 — `PortfolioFeasibilityChecker` va antes de `PortfolioOptimizer`

**Estado:** Aceptado  
**Fecha:** 2026-Q1  
**Área:** `portfolio_layer`

**Contexto:** Si el universo final tiene N activos y `max_single_asset < 1/N`, no existe ninguna cartera long-only que sume 100% y respete el límite de concentración. El optimizador SLSQP en estos casos produce resultados numéricos sin sentido o falla con mensajes internos del solver.

**Decisión:** `PortfolioFeasibilityChecker` evalúa la combinación (return estimates, covariance matrix, risk budget) antes de invocar al optimizador. Si el resultado es INFEASIBLE, la variante se omite con un reason_code específico (ej. `PORTFOLIO_MAX_SINGLE_ASSET_TOO_LOW`). El optimizador no se llama.

**Alternativa descartada:** Capturar la excepción del solver y reportarla. Descartada: los mensajes del solver son crípticos y no accionables para un asesor financiero.

**Consecuencias:** Los `reason_codes` del pre-check son legibles y mapean directamente a acciones del asesor (ampliar universo, renegociar cap de concentración, etc.). El optimizador solo se invoca cuando hay probabilidad razonable de éxito.

---

## DD-008 — El workflow productivo no aplica demo adjustment

**Estado:** Aceptado  
**Fecha:** 2026-Q1  
**Área:** `workflow_layer`

**Contexto:** En una versión anterior de `run_demo.py`, cuando el `RiskBudget` aprobado resultaba infactible con el universo final, el demo relajaba localmente `max_single_asset` y `max_volatility` para poder mostrar portfolios de todas formas. Este ajuste era solo del demo.

**Decisión:** `AdvisoryWorkflowCoordinator` nunca relaja el `RiskBudget` aprobado. Si el pre-check de portfolio feasibility devuelve INFEASIBLE, el workflow termina en `BLOCKED_BY_PORTFOLIO_FEASIBILITY` con diagnóstico completo. La relajación de restricciones es una decisión de la capa humana, no del sistema.

**Alternativa descartada:** Mantener el demo adjustment como opción configurable. Descartada: cualquier relajación automática de restricciones aprobadas por compliance sin override explícito del asesor es una violación de las invariantes del sistema.

**Consecuencias:** El demo también usa el coordinator y puede terminar en BLOCKED. El bloqueo es el comportamiento correcto y esperado. `run_demo.py` incluye una sección de diagnóstico que explica el bloqueo y los caminos de resolución disponibles para el asesor.

---

## DD-009 — `run_demo.py` usa `AdvisoryWorkflowCoordinator` como fuente única de verdad

**Estado:** Aceptado  
**Fecha:** 2026-Q1  
**Área:** `scripts`

**Contexto:** Una versión anterior de `run_demo.py` implementaba manualmente el pipeline de filtros (governance, suitability, ESG, data quality) duplicando la lógica del coordinator. Cualquier cambio al coordinator requería actualizar también el demo.

**Decisión:** `run_demo.py` llama directamente a `AdvisoryWorkflowCoordinator().run(...)` y formatea el `AdvisoryWorkflowResult`. No reimplementa ninguna capa del pipeline.

**Alternativa descartada:** Mantener el demo con pipeline propio para mayor control. Descartada: el demo dejaba de ser representativo del comportamiento productivo tan pronto como el coordinator cambiaba.

**Consecuencias:** El demo es siempre fiel al comportamiento productivo. Si el coordinator bloquea, el demo lo muestra. Si el coordinator genera portfolios, el demo los muestra. La única responsabilidad adicional del demo es cargar fixtures, imprimir el resultado y guardar el reporte Markdown.

---

## DD-010 — `GROWTH` puede exceder el `RiskBudget` solo con advisor override explícito (pendiente M2)

**Estado:** Pendiente — M2  
**Fecha:** 2026-Q1  
**Área:** `portfolio_layer`

**Contexto:** En M1, las tres variantes (DEFENSIVE, BALANCED, GROWTH) operan dentro del `RiskBudget` aprobado. El objetivo de diseño de M2 es permitir que `GROWTH` sea una alternativa de mayor riesgo que el perfil aprobado, siempre que se marque explícitamente como tal.

**Decisión (futura):** `GROWTH` podrá exceder parcialmente el `RiskBudget` aprobado, pero debe registrar:
- `requires_advisor_override = True`
- `risk_budget_exceeded = True`
- `reason_code = PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET`
- Lista de restricciones excedidas (`max_volatility`, `max_single_asset`, etc.)

`GROWTH` no puede presentarse como recomendación base si excede el `RiskBudget`. `BALANCED` sigue siendo la recomendación dentro del perfil aprobado.

**Alternativa descartada:** Silenciar el exceso de riesgo en `GROWTH`. Descartada: ocultar que una cartera excede el perfil aprobado es una violación de compliance.

**Consecuencias (anticipadas):** Requiere cambios en `PortfolioGenerationCoordinator`, en `OptimizedPortfolio` (campos `requires_advisor_override`, `risk_budget_exceeded`), en `AdvisoryWorkflowCoordinator`, y en los tests de integración. Pendiente para M2. Ver también `docs/TODO_DESIGN_NOTES.md`.
