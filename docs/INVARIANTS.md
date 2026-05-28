# Invariantes del sistema — risk-first-advisory

Estos invariantes son contratos de diseño. Violarlos introduce inconsistencias de compliance o trazabilidad que no son detectables solo con pruebas unitarias.

---

## I-001 — La IA propone, el asesor decide

`PreliminaryProfile.advisor_review_required` es siempre `True`. Ningún perfil propuesto por la IA tiene efecto vinculante sin aprobación explícita del asesor. `ApprovedProfile` y `PreliminaryProfile` son tipos distintos, creados por actores distintos.

## I-002 — `preliminary_profile` y `approved_profile` son objetos distintos

`M1SessionResult` mantiene:
- `preliminary_profile_initial`: lo que la IA propuso originalmente.
- `preliminary_profile_revised`: lo que la IA propuso tras el follow-up (puede ser `None`).
- `approved_profile`: lo que el asesor aprobó (siempre presente).

Aunque en algunos casos los valores de `profile_name` coincidan, los objetos son de tipos distintos (`PreliminaryProfile` vs `ApprovedProfile`) y representan decisiones de actores distintos. `ApprovedProfile.original_profile` siempre refleja el perfil **inicial** propuesto por la IA, no el revisado, para preservar la trazabilidad completa de la modificación del asesor.

## I-003 — `return_target_annual_pct` no existe en `KYCData`

El retorno objetivo no es un dato que el cliente declare ni que el asesor fije en el KYC. Se deriva exclusivamente de `FinancialGoal` por `GoalFeasibilityEngine`. Introducirlo en `KYCData` crearía circularidad: el perfil dependería de un objetivo de retorno que a su vez depende del perfil.

## I-004 — `declared_return_expectation_pct` es solo informativo

`KYCData.declared_return_expectation_pct` registra lo que el cliente cree que quiere ganar. No se usa como input del perfil de riesgo, del `RiskBudget`, ni del `GoalFeasibilityEngine`. Su único uso legítimo es: mostrar al asesor si las expectativas del cliente son realistas para el perfil aprobado.

## I-005 — `FinancialGoal` es la única fuente para goal feasibility

`GoalFeasibilityEngine.evaluate(financial_goal, profile_name)` toma `FinancialGoal` directamente. No acepta un retorno objetivo declarado por el cliente. Esto garantiza que la evaluación de viabilidad del objetivo sea objetiva y auditada.

## I-006 — Goal feasibility puede bloquear la generación de portfolios

Si `FeasibilityReport.block_portfolio_generation is True`, el workflow termina en `BLOCKED_BY_GOAL_FEASIBILITY` sin construir `RiskBudget` ni ejecutar el pipeline de filtros. No hay portfolio cuando el objetivo financiero es inviable.

## I-007 — El `RiskBudget` aprobado no se relaja automáticamente en el workflow productivo

`AdvisoryWorkflowCoordinator` no ajusta ni relaja ningún límite del `RiskBudget` construido por `RiskBudgetBuilder`. Si el universo final hace infactible el `RiskBudget` aprobado, el workflow devuelve `BLOCKED_BY_PORTFOLIO_FEASIBILITY` con diagnóstico. La decisión de ajuste corresponde a la capa humana (asesor + compliance). Ver DD-008.

## I-008 — `PortfolioFeasibilityChecker` corre antes de `PortfolioOptimizer`

El pre-check de factibilidad detecta condiciones matemáticamente imposibles (ej. `N * max_single_asset < 1.0`) antes de invocar al optimizador. Esto evita mensajes crípticos del solver y permite emitir `reason_codes` accionables para el asesor.

## I-009 — `PortfolioOptimizer` no decide governance, suitability, ESG ni compliance

El optimizador recibe únicamente los tickers del universo final ya filtrado y validado. No tiene acceso al `KYCData`, al `ESGProfile` ni a la `InstrumentSuitabilityMatrix`. Toda decisión de elegibilidad ocurrió antes de llegar al optimizer.

## I-010 — `BALANCED` debe respetar el `RiskBudget` aprobado

La variante BALANCED usa el `RiskBudget` aprobado sin modificar. Es la recomendación base dentro del perfil aprobado.

## I-011 — `GROWTH` con exceso de riesgo requiere advisor override explícito (pendiente M2)

En M1, `GROWTH` también opera dentro del `RiskBudget` aprobado. En M2, `GROWTH` podrá exceder parcialmente el `RiskBudget`, pero debe marcarse con `requires_advisor_override = True`, `risk_budget_exceeded = True`, y el reason code `PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET`. No puede presentarse como recomendación base si excede el `RiskBudget`. Ver `docs/TODO_DESIGN_NOTES.md` y DD-010.

## I-012 — `AuditTrail` es append-only y se cierra al final de sesión

Los eventos del `AuditTrail` se acumulan en orden cronológico. Una vez llamado `audit.close()`, cualquier intento de `audit.record(...)` lanza `AuditTrailClosedError`. El cierre es irreversible dentro de la sesión.

## I-013 — Los reports formatean; no recalculan

`MarkdownReportGenerator` toma un `AdvisoryWorkflowResult` ya computado y lo formatea. No invoca ningún motor, no re-evalúa ESG, no llama al optimizador. El contenido del reporte es una proyección del resultado, no una fuente de verdad alternativa.

## I-014 — El pipeline de filtros sigue el orden governance → suitability → ESG → data

El orden es fijo y significativo desde el punto de vista de compliance:
1. Governance: ¿el instrumento está aprobado para este perfil?
2. Suitability: ¿el tipo de instrumento es adecuado para este cliente?
3. ESG: ¿el instrumento cumple las restricciones ESG del cliente?
4. Market data + Data quality: ¿hay datos suficientes y confiables para optimizar?

Saltarse o reordenar pasos es una violación de compliance, no solo un bug.

## I-015 — KYC estandarizado como base obligatoria

El sistema debe partir de un `KYCData` estructurado. La IA no puede reemplazar el cuestionario base ni decidir libremente qué variables recolectar como mecanismo primario de perfilamiento. Puede detectar contradicciones entre los campos del KYC, generar preguntas de follow-up acotadas a esas contradicciones, y resumir o interpretar respuestas abiertas (`open_*`), siempre sujeto a revisión y aprobación del asesor. La comparabilidad entre clientes y la trazabilidad ante auditoría dependen de que todos partan del mismo conjunto de variables mínimas.

---

## Invariantes Fase 2 — workflow case-scoped

Los siguientes invariantes aplican al flujo case-scoped introducido en Fase 2. Son contratos de diseño del workflow `firm → … → report` consumido vía `/cases/*`.

## I-016 — La IA no aprueba la recomendación final case-scoped

`POST /cases/{id}/ai/profile-analysis` produce un `preliminary_profile` + `confidence` + `contradictions` + `follow_up_questions`. Este output es **propuesta**, no decisión. El campo `preliminary_profile` solo se convierte en perfil aprobado tras un `POST /cases/{id}/profile-approval` explícito con `decision ∈ {approve, modify}` y `rationale` no vacío. Misma separación que I-001 / I-002 pero materializada como entidades persistentes vinculadas al `case_id`.

## I-017 — `current_approved_profile_id` solo apunta a approvals con `decision ∈ {approve, modify}`

`POST /cases/{id}/profile-approval` con `decision=reject`:
- queda `is_current=0` desde el insert,
- NO actualiza `advisory_cases.current_approved_profile_id`,
- NO invalida una aprobación previa (el `current_approved_profile_id` anterior se mantiene).

Razón: un rechazo nuevo no invalida la última decisión vigente. Para invalidar, el asesor debe emitir un nuevo `modify` o re-aprobar con `approve`.

## I-018 — Override obligatorio para variants que exceden el RiskBudget

`POST /cases/{id}/portfolio-selection` rechaza con `409` si el `selected_variant` tiene `metadata.requires_advisor_override=True` y no se provee (explícitamente o vía `current_for_case`) un `override_approval_id` con `decision=approve`, `proposal_id` matching y `candidate_variant` matching. Inversamente, si el variant **no** requiere override, pasar `override_approval_id` explícito devuelve `422`. Política estricta: override approval es solo para variants exceeding-budget.

## I-019 — Portfolio selection es decisión humana del asesor

Ningún endpoint genera automáticamente una `CasePortfolioSelection`. Solo `POST /cases/{id}/portfolio-selection` (RBAC `advisor`/`admin`) crea el row, transiciona el case a `PORTFOLIO_SELECTED` y materializa `advisory_cases.current_portfolio_selection_id`. La selección NO se infiere del proposal ni del análisis IA.

## I-020 — Los reports case-scoped son review-ready, NO recomendación automática

`CaseMarkdownReportGenerator` produce markdown puramente formateando los snapshots ya persistidos (proposal, selection, approval, override). NO invoca el optimizer, NO consulta a OpenAI, NO recalcula nada. Los reports incluyen 4 disclaimers fijos (no es recomendación automática, requiere revisión advisor, datos pueden ser proxy/demo, IA no aprueba la recomendación final). El advisor es responsable de presentarlo al cliente.

## I-021 — AuditEvent hash chain debe permanecer verificable

`audit_events` es append-only a nivel API. Cada evento incluye `previous_hash` + `event_hash` (SHA-256 sobre canonical JSON). `GET /cases/{id}/audit/verify` debe devolver `is_intact=true` después de cualquier flujo válido del workflow. Si un test, script o endpoint hace que `verify` devuelva `is_intact=false` sin manipulación explícita de DB, es un bug crítico de compliance, no un edge case.

## I-022 — AIRequestLog no persiste input sensible sin redacción

Toda llamada a OpenAI registrada en `ai_request_logs` aplica `redact_ai_input()` al payload original antes de persistirlo. Las claves redactadas explícitamente (`natural_language_preferences`, `open_*`, `kyc_context`, `previous_profile_analysis`) y `client_id` (hasheado a `client_<sha256[:8]>`) NO deben aparecer en claro en `input_redacted_json`. API keys (`sk-`, `Bearer`) siempre redactadas en cualquier posición (incluso anidadas en dicts/lists). El `input_hash` se computa sobre el original (no el redactado) para correlación sin exposición.

## I-023 — Append-only a nivel API en todas las entidades case-scoped

Ningún endpoint expone update / delete sobre `kyc_submissions`, `ai_profile_analyses`, `advisor_profile_approvals`, `case_investment_preferences`, `case_universe_filter_runs`, `case_portfolio_proposals`, `case_override_approvals`, `case_portfolio_selections`, `case_reports`, `audit_events`, `ai_request_logs`. La única mutación permitida es `mark_previous_not_current(case_id, exclude_id=new_id)` que setea `is_current=0` a los rows previos del case (sin tocar el contenido). Cambios de estado se modelan como nuevos rows con version incremental o `is_current=1` nuevo.
