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

## DD-010 — `GROWTH` puede exceder el `RiskBudget` solo con advisor override explícito

**Estado:** Implementado parcialmente (M2-prep)  
**Fecha:** 2026-Q1 / actualizado 2026-05-19  
**Área:** `portfolio_layer`, `reporting_layer`

**Contexto:** En M1, las tres variantes (DEFENSIVE, BALANCED, GROWTH) operaban dentro del `RiskBudget` aprobado. A partir de M2-prep, `GROWTH` puede exceder parcialmente ese budget como alternativa de mayor riesgo, siempre que el exceso quede marcado y visible.

**Decisión:** `GROWTH` puede exceder `max_volatility` del `RiskBudget` aprobado usando un budget derivado (`growth_max_vol = min(original * 1.50, original + 0.05)`). No relaja `max_single_asset` (evita romper pre-checks de factibilidad con universos pequeños). Cuando `GROWTH` excede el budget original, `PortfolioGenerationCoordinator` registra en `PortfolioVariantMetadata`:
- `risk_budget_exceeded = True`
- `requires_advisor_override = True`
- `exceeded_constraints = ["max_volatility"]`
- `reason_codes = ["PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"]`

`BALANCED` sigue siendo la recomendación base dentro del perfil aprobado. `DEFENSIVE` opera con un budget más conservador que el aprobado. El reporte Markdown muestra la metadata por variante bajo **Variant Metadata**.

**Alternativa descartada:** Silenciar el exceso de riesgo en `GROWTH`. Descartada: ocultar que una cartera excede el perfil aprobado es una violación de compliance.

**Consecuencias:**
- `PortfolioVariantMetadata` implementado en `portfolio_layer/generation.py`.
- `PortfolioCandidateSet` incluye campo `metadata: dict[PortfolioVariant, PortfolioVariantMetadata]`.
- El reporte Markdown expone la metadata por variante (visible para el asesor).
- El override del asesor es una acción persistida y auditada: `POST /cases/{id}/override-approval` (case-scoped, con AuditEvent) y `POST /advisor/override-approval` (legacy, record SQLite). Pendientes menores (validación cruzada de records, firma digital) en `docs/ROADMAP.md`.

---

## DD-011 — KYC estandarizado como fuente primaria del perfil

**Estado:** Aceptado  
**Fecha:** 2026-05-18  
**Área:** `kyc`, `ai_layer`, suitability

**Contexto:** El sistema podría permitir que la IA converse libremente con el cliente y decida qué preguntar en cada caso. Eso daría flexibilidad, pero reduce comparabilidad, trazabilidad y defensa ante auditoría: dos clientes con perfiles similares podrían haber respondido variables distintas, haciendo imposible justificar por qué fueron tratados de forma consistente.

**Decisión:** El perfilamiento parte de un `KYCData` estructurado y estandarizado. La IA puede analizar el KYC, detectar contradicciones, generar preguntas de follow-up y ayudar a interpretar respuestas abiertas (`open_investment_goal`, `open_risk_reaction`, etc.), pero no reemplaza el cuestionario base ni decide libremente qué variables son necesarias para construir el perfil.

**Alternativa descartada:** Permitir que la IA construya el KYC de forma libre para cada cliente, preguntando lo que considere relevante. Descartada porque elimina la comparabilidad entre clientes y dificulta la defensa ante auditoría regulatoria.

**Consecuencias:**
- Todos los clientes pasan por el mismo conjunto de variables mínimas comparables.
- El sistema puede demostrar que dos clientes similares fueron tratados de forma consistente.
- La IA queda limitada a interpretación, detección de contradicciones y follow-up acotado.
- El asesor mantiene la aprobación final del perfil.
- Las respuestas abiertas (`open_*`) pueden existir en `KYCData` como observaciones para el asesor y la IA, pero no son campos duros que determinen automáticamente el perfil sin revisión.

---

## DD-012 — Risk Number 0-100: escala anclada al max_volatility por perfil (CVaR), número operativo capado por capacidad, alineación informativa

**Estado:** Aceptado
**Fecha:** 2026-07-03
**Área:** `ai_layer/risk_number.py`, `api_layer` (profile-analysis, portfolio-proposal)

**Contexto:** El Risk Number (docs/RISK_NUMBER_DESIGN.md, enfoque A — diferenciado del método patentado de Nitrogen) pone al cliente y a cada cartera candidata en una escala común 0-100. La primera implementación ancló la escala de cartera en los `max_drawdown` del YAML (copiados a mano) y comparó capacidad por bandas de 20; la revisión de código confirmó tres defectos sistémicos: (1) una cartera al `max_volatility` de su propio perfil producía un CVaR que excedía el `max_drawdown` de ese perfil → carteras compliant con el budget bandaban un nivel por encima y disparaban `over_capacity` espurio; (2) los cortes por banda disparaban con 0.1 puntos de diferencia en un borde y callaban con 19.9 dentro de una banda; (3) el `override_required` del alignment era una segunda señal de override que ningún endpoint aplica, contradiciendo a `metadata.requires_advisor_override` (I-018) y a `options_framing` en el mismo payload.

**Decisión:**
- **Escala de cartera:** los anclajes downside→número se DERIVAN al importar desde `config/risk_profiles.yaml`: el tope de la banda de cada perfil = pérdida CVaR(α=0.95, 1 año) de una cartera al `max_volatility` de ese perfil con μ=0 (`k·max_volatility`, k≈2.063). Garantía por construcción: una cartera dentro del budget de su perfil (σ ≤ max_volatility, μ ≥ 0) nunca banda por encima de ese perfil, y editar el YAML recalibra escala y budgets juntos.
- **Número del cliente:** `number = min(tolerance_number, capacity_ceiling_number)` — la capacidad acota la tolerancia, misma regla que el perfil efectivo del motor (`score_stated_profile`), así `risk_number.number` y `deterministic.score` no se contradicen en la misma respuesta. La tolerancia combinada (G-L + trade-off) y el techo viajan como campos separados.
- **Alineación:** comparaciones POR PUNTOS con holgura simétrica (media banda), nunca por índices de banda. La divergencia entre elicitaciones también es por puntos (≥20 = señal). El margen de "podés tomar más riesgo" se informa acotado por el techo de capacidad.
- **Señal informativa, no de enforcement:** `risk_alignment` NO expone flag de override; el override formal lo gobiernan `profile-approval` y `metadata.requires_advisor_override` en la selección (I-018). Cada alignment persiste `client_kyc_submission_id` (el KYC de la APROBACIÓN usada para el budget, no el vigente del case) para trazabilidad de auditoría.
- **Robustez:** NaN/inf en datos de mercado es `ValueError` explícito (nunca "riesgo 0"); el solver CRRA normaliza por riqueza (homoteticidad) para no desbordar con riquezas grandes; lista de retornos vacía es error explícito.

**Alternativas descartadas:** (a) anclar en `max_drawdown` (medida distinta a la que produce el optimizador → descalibración sistemática); (b) hacer del alignment una señal de enforcement (duplicaría I-018 con una fórmula distinta — dos verdades de compliance para la misma decisión); (c) exponer solo el número de willingness (contradice el score efectivo del motor y sugiere riesgo que la capacidad no soporta).

**Consecuencias:**
- Calibraciones = supuestos DEMO (α=0.95, horizonte 1 año, anchors de γ de literatura CRRA); no reemplazan un proceso de CMA ni la decisión de un comité de inversiones.
- `GAMMA_ANCHORS` (γ→número) sigue siendo constante de módulo tuneable por parámetro; los anchors downside ya no pueden divergir del YAML.
- Las bandas 0-100 tienen UNA definición (delegada en `risk_scoring._profile_from_score`).

---

## DD-013 — Risk Number de cartera mide dispersión pura (μ=0), no Expected Shortfall con drift

**Estado:** Aceptado
**Fecha:** 2026-07-04
**Área:** `ai_layer/risk_number.py`, universo demo

**Contexto:** Al ampliar el universo demo (`tests/fixtures/universe/live_instrument_universe.csv`, 24 → 52 instrumentos: US ETFs sectoriales/regionales/factor, commodities, high yield, más CEDEARs y soberanos ARG) y correrlo con `RFA_LIVE_DATA=1`, se destapó un bug de calibración en `portfolio_risk_number`. El número mapeaba sobre `portfolio_downside`, que resta el retorno esperado μ del downside (Expected Shortfall: `ES = μ − k·σ`). Pero los anclajes `DOWNSIDE_ANCHORS` se derivan a μ=0 (DD-012: `k·max_volatility`). Con retornos *trailing* de 3 años inflados (rally post-2022), μ "cancelaba" el riesgo: una cartera de 25% de volatilidad marcaba número ~20 y quedaba "under_tolerance" — obviamente incorrecto. Un conservador con cartera de 2.2% vol daba número 0.

**Decisión:** El **número de riesgo 0-100 de una cartera mide dispersión pura (μ=0)**, consistente con la derivación de los anclajes. Nueva función `risk_scoring_downside`:
- paramétrico: `pérdida = k(α)·σ·√h` (sin término μ);
- empírico: **centra** los retornos (`r − media`) antes de tomar la cola, midiendo dispersión y no drift.

`portfolio_risk_number` usa esta pérdida para el número; `mu_annual` se acepta en la firma por compatibilidad pero NO entra al número. El retorno esperado de la cartera se muestra en su propia columna (no se mezcla con el riesgo). `portfolio_downside` (ES honesto con drift) se conserva como función pura para referencia/otros usos, pero ya no alimenta el número.

**Justificación:** (1) Consistencia: escala y medición ahora usan la misma convención μ=0, así una cartera dentro del budget de su perfil nunca banda por encima (garantía de DD-012 preservada). (2) Correcto conceptualmente: un **puntaje de riesgo** describe cuánto podés perder en un mal escenario; un retorno esperado optimista (y encima estimado de trailing, poco confiable como forward) no reduce el riesgo real del año que viene. Es como lo hace Nitrogen (banda de downside, no Sharpe). (3) Monotonicidad: más volatilidad ⇒ número más alto, siempre.

**Alternativa descartada:** Mantener el ES con drift y "arreglar" los μ inflados (capar, usar risk-free, CMA forward). Descartada: mete un problema de estimación de retornos esperados (difícil, poco confiable) dentro de un puntaje de riesgo que no lo necesita; μ=0 es más simple y más honesto.

**Consecuencias:**
- El número de cartera es función monótona de la volatilidad (a horizonte/α fijos).
- Cambió el valor esperado en los tests unitarios (recalibrados a mano) — ningún cambio de contrato en la API (mismas claves salvo que el número ya no expone `cvar`).
- El universo demo ampliado sólo rinde con `RFA_LIVE_DATA=1` (equities/ETF necesitan precios reales; sin la env var el adapter sólo cubre renta fija). La demo debe correrse con datos en vivo.

---

## DD-014 — Estimación live: Σ Ledoit-Wolf + μ Black-Litterman (portados de markowitz-optimizer)

**Estado:** Aceptado
**Fecha:** 2026-07-07
**Área:** `data_layer/estimation.py`, `api_layer` (portfolio-proposal case-scoped), `portfolio_layer/generation.py`

**Contexto:** El path live (`RFA_LIVE_DATA=1`) estimaba μ por media histórica diaria ×252 (2 años) por ticker, y Σ con vols reales pero **correlaciones mock por asset_class** (`CovarianceEngine`). Consecuencias observadas probando "cliente solo-ARG": (1) μ de 30-40% en soberanos post-rally que MAX_RETURN perseguía; (2) correlaciones fijas 0.80/0.85 que negaban diversificación intra-clase e inflaban el piso de vol mínima a ~30% (todo perfil infactible); (3) una serie CEDEAR corrupta (ETHA, vol 119.651%) entraba al optimizador, envenenaba Σ y el solver fallaba con un mensaje genérico sin culpable.

**Decisión:** Nuevo `data_layer/estimation.py` (portado del proyecto hermano `markowitz-optimizer`, sin dependencia cruzada):
- **Σ = Ledoit-Wolf (2004)** sobre la matriz de retornos diarios ALINEADA (inner join de fechas, ARS→USD CCL): shrinkage hacia identidad escalada con λ óptimo de fórmula cerrada (numpy puro, equivalente a sklearn — no se suma scikit-learn como dependencia). Correlaciones reales, matriz bien condicionada.
- **μ = Black-Litterman (1992)**: prior de equilibrio Π = δΣw_ref (w_ref equal-weight; no afirmamos conocer el portafolio de mercado ARG+US) mezclado con la media histórica como view (P=I, Ω=diag(τΣ), He & Litterman 2002). Shrinkage de μ hacia un ancla económica; δ=2.5, τ=0.05, rf=4%.
- **Sanity bound de volatilidad** (`MAX_SANE_VOL=300%` anual): series corruptas se DESCARTAN con razón auditada (persistida en `warnings` del proposal), en el estimador conjunto y en `LiveMarketDataProvider`.
- **Diagnóstico de infactibilidad**: `PortfolioGenerationInfeasibleError` (subclase de ValueError) conserva reason_codes y notas por variante del pre-check; la API las persiste en `warnings` (incluye `min_achievable_volatility` vs budget y sugerencias). Las variantes omitidas en un proposal `completed` también dejan sus notas.
- Los tickers sin serie utilizable quedan como snapshots `stale` con la razón en notes (visibles, fuera del optimizador): mezclar μ/σ de fixture con Σ real sería incoherente. Sin `RFA_LIVE_DATA` nada cambia: fixture + `CovarianceEngine` mock, tests y smoke deterministas.

**Resultado medido (2026-07-07):** piso de vol solo-ARG: ~30% (mock) → ~9.7% (LW real) ⇒ `moderado` solo-ARG pasó de infactible a `completed` (BALANCED 10% vol, 100% instrumentos AR); GD29: μ 40%→10.4%, vol 61%→19.6%; `conservador` solo-ARG sigue infactible (correcto) pero ahora con diagnóstico accionable por variante.

**Alternativas descartadas:** (a) depender de scikit-learn (pesado para una fórmula cerrada de 30 líneas); (b) importar markowitz-optimizer como paquete (acoplamiento entre repos con ciclos de vida distintos; se porta el método con crédito); (c) shrinkage solo de Σ sin tocar μ (deja el garbage-in de la media histórica, que era el problema dominante).

**Consecuencias:**
- La ventana efectiva es la INTERSECCIÓN de fechas de las series (el instrumento más joven la limita); queda registrada en notes (`window=...`, `obs=`).
- `CovarianceEngine` (correlaciones mock) sigue siendo el motor del modo fixture y el fallback si la estimación conjunta falla (sin red) — el ROADMAP ya no lo lista como deuda del path live.
- δ, τ, rf y el bound de vol son supuestos DEMO tuneables por parámetro; no reemplazan un proceso de CMA formal.

## DD-015 — El requisito de override del progreso se evalúa contra la selección vigente

**Estado:** Aceptado
**Fecha:** 2026-07-08
**Área:** `api_layer/main.py` (`GET /cases/{id}/summary`), `scripts/run_case_workflow_smoke_check.py`

**Contexto:** `has_override_requirement` se computaba a nivel PROPOSAL (¿algún candidate requiere override?). Si el proposal tenía una variante con override (típicamente GROWTH) pero el asesor seleccionaba una que NO lo requería, `next_recommended_action` quedaba clavado en `review_override` y `completion_ratio` topaba en 8/9 ≈ 0.89 — el caso nunca "terminaba" según el summary. El smoke check esquivaba el quirk seleccionando siempre la variante con override.

**Decisión:** `_override_requirement_for_progress(proposal, selection)`:
- **Con selección vigente**, manda la variante ELEGIDA (`selected_candidate.metadata.requires_advisor_override`). Si la elegida requiere override, el endpoint de selección ya garantizó el override approval (422 si falta) ⇒ 9/9. Si no lo requiere, el paso de override no aplica ⇒ denominador 8 y el caso llega a 1.0 / `ready_for_review`.
- **Sin selección**, se mantiene la evaluación a nivel proposal: recomendar `review_override` antes de elegir sigue siendo la guía correcta para el asesor.
- Un override approval registrado sobre una variante que finalmente NO se seleccionó ni cuenta ni penaliza (queda en el audit trail y en `current_override_approval`, como siempre).

El smoke check ahora ejercita este path en vez de esquivarlo: registra el override approval sobre la variante que lo requiere (cobertura del endpoint) y luego selecciona la variante SIN override, exigiendo `completion_ratio == 1.0`.

**Alternativas descartadas:** (a) dejar el quirk documentado (confunde a quien lee el summary y rompe la semántica de "caso completo"); (b) evaluar SIEMPRE contra la selección (antes de seleccionar no hay selección: el proposal es la única señal disponible para guiar la revisión); (c) contar el override approval huérfano en el ratio (mezclaría un paso no requerido en el denominador de otro path).

**Consecuencias:** el summary es la única superficie afectada — los endpoints de override/selección no cambian sus validaciones (I-016/I-019 intactos). La vista del cliente no cambia (solo usa el copy de progreso pre-selección).
