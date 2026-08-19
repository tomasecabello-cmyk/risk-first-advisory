# Reason Codes — risk-first-advisory

Los reason codes son strings constantes que identifican condiciones relevantes del flujo. Se acumulan en `AdvisoryWorkflowResult.reason_codes` (bloqueos y advertencias estructurales) y en las listas `reason_codes` de sub-objetos como `PortfolioCandidateSet` y `OptimizedPortfolio`.

Convención: un reason code en `AdvisoryWorkflowResult.reason_codes` que corresponde a una condición de bloqueo está asociado a un `AdvisoryWorkflowStatus` bloqueado. Un reason code de advertencia está asociado a `COMPLETED_WITH_WARNINGS` o aparece en el objeto afectado sin bloquear el flujo.

---

## Reason codes del workflow

### `GOAL_FEASIBILITY_BLOCKED`
- **Significado:** `GoalFeasibilityEngine` determinó que el objetivo financiero del cliente es inviable dado el perfil aprobado.
- **Bloquea:** Sí → `BLOCKED_BY_GOAL_FEASIBILITY`.
- **Capa:** `rules_layer` (workflow_layer lo registra).
- **Acción esperada:** El asesor revisa `FeasibilityReport.suggested_actions`. Opciones típicas: ampliar horizonte, reducir objetivo de capital, aumentar aportes periódicos, revisar el perfil a uno más agresivo.

### `PORTFOLIO_EMPTY_FINAL_UNIVERSE`
- **Significado:** Tras aplicar governance, suitability, ESG y data quality, no quedan instrumentos elegibles para optimizar.
- **Bloquea:** Sí → `BLOCKED_BY_EMPTY_UNIVERSE`.
- **Capa:** `workflow_layer`.
- **Acción esperada:** El asesor revisa qué filtro eliminó los últimos instrumentos (ver `notes` del resultado). Opciones: ampliar el universo aprobado, relajar restricciones ESG, revisar permisos de suitability.

### `PORTFOLIO_GENERATION_BLOCKED`
- **Significado:** El pre-check de portfolio feasibility o el `PortfolioGenerationCoordinator` determinaron que no es posible generar ninguna variante de portfolio con el RiskBudget aprobado y el universo final.
- **Bloquea:** Sí → `BLOCKED_BY_PORTFOLIO_FEASIBILITY`.
- **Capa:** `portfolio_layer` (workflow_layer lo registra).
- **Acción esperada:** Ver los 4 caminos tipificados en el diagnóstico de bloqueo: (1) revisar perfil más agresivo, (2) ampliar universo, (3) renegociar cap de concentración con compliance, (4) ajustar RiskBudget con justificación auditada.

---

## Reason codes de ESG

### `ESG_BLOCKED`
- **Significado:** Uno o más instrumentos fueron excluidos por una restricción ESG hard (hard exclusion del cliente).
- **Bloquea:** No el workflow (el instrumento se excluye, los demás continúan).
- **Capa:** `rules_layer` (`ESGComplianceChecker`).
- **Acción esperada:** Informativo. El asesor puede revisar si la exclusión es correcta o si el cliente quiere modificar sus restricciones ESG.

### `ESG_WARNING`
- **Significado:** Uno o más instrumentos tienen status ESG UNKNOWN (sin metadata) o SOFT_WARNING (incumplen preferencias blandas). El instrumento NO fue excluido.
- **Bloquea:** No.
- **Capa:** `rules_layer` (`ESGComplianceChecker`).
- **Acción esperada:** El asesor evalúa si los instrumentos con ESG UNKNOWN son aceptables dado el perfil ESG del cliente. Puede solicitar metadata ESG adicional.

### `ESG_DATA_INCOMPLETE`
- **Significado:** La metadata ESG del instrumento existe pero está incompleta (ej. `prefer_tag` / `avoid_tag` presentes en la preferencia del cliente pero no evaluables con la metadata disponible).
- **Bloquea:** No.
- **Capa:** `rules_layer` (`ESGComplianceChecker`).
- **Acción esperada:** Completar la metadata ESG del instrumento o aceptar el instrumento con advertencia documentada.

---

## Reason codes de datos

### `DATA_MISSING`
- **Significado:** El proveedor de datos no tiene snapshot para un ticker que pasó ESG. El ticker se excluye del universo final.
- **Bloquea:** No el workflow (el ticker se excluye).
- **Capa:** `data_layer` (workflow_layer lo registra).
- **Acción esperada:** Verificar si el ticker está disponible en el proveedor de datos. Si es un ticker legítimo, actualizar el proveedor o el fixture de datos.

### `DATA_QUALITY_FAILED`
- **Significado:** El snapshot existe pero `DataQualityGate` lo evalúa como FAIL o `is_usable = False`. El ticker se excluye del universo final.
- **Bloquea:** No el workflow (el ticker se excluye).
- **Capa:** `data_layer` (`DataQualityGate`).
- **Acción esperada:** Investigar el reason code específico del DataQualityResult para determinar la causa (ver subcódigos abajo).

### `DATA_STALE`
- **Significado:** La fecha del snapshot es anterior al umbral de frescura aceptable.
- **Bloquea:** Contribuye a `DATA_QUALITY_FAILED` si el campo es crítico.
- **Capa:** `data_layer` (`DataQualityGate`).
- **Acción esperada:** Actualizar el snapshot del instrumento en el proveedor de datos.

### `DATA_CRITICAL_FIELD_MISSING`
- **Significado:** Un campo crítico del snapshot (precio, volumen, volatilidad) está ausente o es `None`.
- **Bloquea:** Contribuye a `DATA_QUALITY_FAILED`.
- **Capa:** `data_layer` (`DataQualityGate`).
- **Acción esperada:** Completar los datos del instrumento o excluirlo del universo aprobado.

### `DATA_NON_CRITICAL_FIELD_MISSING`
- **Significado:** Un campo no crítico del snapshot está ausente. El ticker puede seguir siendo usable.
- **Bloquea:** No (genera WARNING).
- **Capa:** `data_layer` (`DataQualityGate`).
- **Acción esperada:** Informativo. Completar los datos cuando sea posible.

### `DATA_LOW_LIQUIDITY`
- **Significado:** El volumen promedio del instrumento está por debajo del umbral mínimo de liquidez del RiskBudget.
- **Bloquea:** Contribuye a `DATA_QUALITY_FAILED` o genera WARNING según la severidad.
- **Capa:** `data_layer` (`DataQualityGate`).
- **Acción esperada:** El asesor evalúa si el instrumento es apropiado para el tamaño de la cartera del cliente.

### `DATA_ZERO_VOLATILITY_NON_CASH`
- **Significado:** Un instrumento non-cash tiene volatilidad histórica reportada como cero, lo que indica datos incorrectos o un problema de cálculo.
- **Bloquea:** Contribuye a `DATA_QUALITY_FAILED`.
- **Capa:** `data_layer` (`DataQualityGate`).
- **Acción esperada:** Verificar el cálculo de volatilidad histórica en el proveedor de datos.

---

## Reason codes de portfolio

### `PORTFOLIO_MAX_SINGLE_ASSET_TOO_LOW`
- **Significado:** `N * max_single_asset < 1.0` donde N es el número de activos en el universo final. Es matemáticamente imposible construir una cartera long-only que sume 100%.
- **Bloquea:** La variante afectada (contribuye a `PORTFOLIO_GENERATION_BLOCKED` si afecta todas las variantes).
- **Capa:** `portfolio_layer` (`PortfolioFeasibilityChecker`).
- **Acción esperada:** Ampliar el universo de activos, aumentar `max_single_asset` (requiere override del asesor con justificación), o revisar el perfil.

### `PORTFOLIO_MIN_VOL_EXCEEDS_BUDGET`
- **Significado:** La volatilidad mínima alcanzable con el universo final supera `max_volatility` del RiskBudget. No existe cartera dentro del límite de volatilidad.
- **Bloquea:** La variante afectada.
- **Capa:** `portfolio_layer` (`PortfolioFeasibilityChecker`).
- **Acción esperada:** Aumentar `max_volatility` (requiere override) o añadir activos de menor volatilidad al universo.

### `PORTFOLIO_NO_ASSETS`
- **Significado:** El universo de activos para la variante está vacío.
- **Bloquea:** La variante afectada.
- **Capa:** `portfolio_layer` (`PortfolioFeasibilityChecker`).
- **Acción esperada:** Verificar que el universo final no esté vacío antes de llegar al optimizer.

### `PORTFOLIO_TICKER_MISMATCH`
- **Significado:** Los tickers de `return_estimates` y `covariance_matrix` no están alineados. Error de programación o de preparación de datos.
- **Bloquea:** La variante afectada (error interno).
- **Capa:** `portfolio_layer` (`PortfolioFeasibilityChecker` o `PortfolioOptimizer`).
- **Acción esperada:** Investigar el orden de construcción de los inputs en el workflow.

### `PORTFOLIO_LOW_DIVERSIFICATION_UNIVERSE`
- **Significado:** El universo tiene muy pocos activos (ej. < 3). El portfolio resultante tendrá alta concentración. No bloquea pero genera advertencia.
- **Bloquea:** No.
- **Capa:** `portfolio_layer` (`PortfolioFeasibilityChecker`).
- **Acción esperada:** Considerar ampliar el universo o documentar la concentración en el reporte.

### `PORTFOLIO_CONCENTRATION_REQUIRED`
- **Significado:** Dado el número de activos y el `max_single_asset`, algunas posiciones deberán ser relativamente grandes. No imposible matemáticamente, pero puede resultar en concentración elevada.
- **Bloquea:** No (genera WARNING).
- **Capa:** `portfolio_layer` (`PortfolioFeasibilityChecker`).
- **Acción esperada:** El asesor evalúa si la concentración resultante es aceptable para el cliente.

### `PORTFOLIO_VARIANT_INFEASIBLE`
- **Significado:** Una variante específica (ej. DEFENSIVE con sub-budget interno) no es factible. Otras variantes pueden seguir siendo válidas.
- **Bloquea:** La variante específica (no el workflow si al menos una variante es válida).
- **Capa:** `portfolio_layer` (`PortfolioGenerationCoordinator`).
- **Acción esperada:** Informativo. El asesor revisa qué variantes están disponibles.

### `PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET`
- **Significado:** La variante `GROWTH` fue construida con un budget derivado que relaja `max_volatility` por encima del `RiskBudget` aprobado para el cliente. La cartera GROWTH resultante excede la volatilidad máxima aprobada.
- **Bloquea:** No bloquea la variante, pero la marca con `risk_budget_exceeded=True` y `requires_advisor_override=True` en `PortfolioVariantMetadata`. Los campos excedidos quedan listados en `exceeded_constraints`.
- **Capa:** `portfolio_layer` (`PortfolioGenerationCoordinator`). Implementado en M2-prep.
- **Acción esperada:** El asesor revisa los límites excedidos (ver `exceeded_constraints` en el reporte Markdown) y decide si aprueba la variante con override documentado. La variante `GROWTH` no puede presentarse como recomendación base si excede el `RiskBudget`. **Pendiente:** la firma/persistencia del override del asesor queda para la capa de workflow/UI futura.

---

## Reason codes de suitability

### `SUITABILITY_LIMITED`
- **Significado:** Un instrumento tiene suitability LIMITED para el perfil del cliente (no NOT_ALLOWED). El instrumento pasa al universo pero con un cap de asignación (`max_allocation`).
- **Bloquea:** No.
- **Capa:** `rules_layer` (`InstrumentSuitabilityMatrix`).
- **Acción esperada:** El asesor verifica que el optimizador respete el cap de asignación del instrumento LIMITED.

---

## Reason codes de KYC

Catálogo completo en `rules_layer/reason_codes.py` (`ReasonCode` + `REASON_CODE_CATALOG`). Acá se documentan los que el flujo case-scoped emite hacia el asesor.

### `KYC_012` — `KYC_STALE`
- **Significado:** el KYC que respalda el proposal supera la antigüedad máxima configurada (`RFA_KYC_MAX_AGE_DAYS`, default 365; `<= 0` desactiva).
- **Bloquea:** no (severity media). Aparece como warning antepuesto en el proposal.
- **Capa:** `api_layer` (`_kyc_staleness_warning`), DD-017.
- **Acción esperada:** reconfirmar los datos del cliente y registrar un KYC nuevo antes de presentar la propuesta.

### `KYC_013` — `KYC_CNV_PROFILING_INCOMPLETE`
- **Significado:** el KYC no cubre todos los mínimos de perfilamiento exigidos por las Normas CNV (N.T. 2013 y mod.), Título VII, art. 12 inc. j) Cap. I / art. 16 inc. j) Cap. II. Los tres que se chequean son los que se agregaron en DD-018: `instrument_knowledge` (grado de conocimiento de los instrumentos disponibles), `savings_allocated_pct` (porcentaje de ahorros destinado a estas inversiones) y `savings_at_risk_pct` (nivel de ahorros que el cliente está dispuesto a arriesgar). Los otros mínimos del artículo ya viajaban en el KYC: experiencia en el mercado, objetivo de inversión, situación financiera y horizonte.
- **Bloquea:** no (severity media, `blocks_advancement: false`). El KYC se registra igual — la decisión de completarlo es del asesor (I-001).
- **Dónde aparece:** campo `warnings` de la response de `POST /cases/{id}/kyc`, nombrando cuáles faltan; el `AuditEvent kyc_submitted` deja `cnv_profiling_complete: bool`; el reporte del caso lo repite en la sección "Mínimos de perfilamiento (Normas CNV)".
- **Capa:** `api_layer` (`_cnv_profiling_warning`), DD-018.
- **Acción esperada:** completar los campos faltantes en el KYC antes de presentar la propuesta al cliente.
