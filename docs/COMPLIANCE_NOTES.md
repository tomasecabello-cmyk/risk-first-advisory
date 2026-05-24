# Compliance Notes — risk-first-advisory

Notas de diseño relevantes para la revisión regulatoria y de compliance del sistema. Este documento no es asesoramiento legal. Describe las decisiones de arquitectura que soportan los requisitos de compliance de un sistema de asesoría de inversiones (MiFID II, CNBV, SEC/FINRA según jurisdicción).

---

## 1. Separación entre IA y decisión del asesor

El sistema implementa una separación explícita y auditada entre la propuesta computacional (IA) y la decisión vinculante (asesor humano):

- **`PreliminaryProfile`** (output del análisis de IA via `OpenAIProfileClient`): es una propuesta. `advisor_review_required = True` siempre. El perfil propuesto no tiene efecto vinculante.
- **`ApprovedProfile`** (output de `ScriptedAdvisorInterface`): es la decisión. El asesor puede aceptar, modificar o rechazar la propuesta de la IA. `is_modified` y `advisor_comment` quedan registrados.
- Los dos objetos son de tipos distintos y se mantienen separados en `M1SessionResult`.

Ningún flujo del sistema genera portfolios sin un `ApprovedProfile` previo en el workflow completo. El perfil aprobado es el input de `RiskBudgetBuilder` y de todo el pipeline posterior.

**Nota sobre el AI Filtered Portfolio Demo:** `POST /ai/filtered-portfolio-demo` acepta un `profile` directamente como parámetro de la request (sin pasar por el proceso de aprobación del asesor) porque es un endpoint de **demo aislado**, no parte del workflow completo. En un flujo de producción, el perfil debe surgir siempre de `ApprovedProfile`. Ver sección 13 de este documento.

---

## 2. Audit trail

`AuditTrail` registra todos los eventos relevantes de la sesión en orden cronológico:

1. `session_started` — inicio del flujo M1.
2. `ai_output_initial` — perfil propuesto por la IA, incluyendo contradicciones detectadas y si hay contradicciones bloqueantes.
3. `follow_up_cycle_N_started` — inicio del ciclo de follow-up (si aplica), incluyendo las preguntas y las contradicciones que las motivaron.
4. `follow_up_cycle_N_completed` — respuestas del asesor al follow-up.
5. `ai_output_revised` — perfil revisado por la IA tras el follow-up (si aplica).
6. `advisor_profile_approval` — perfil aprobado, perfil original, si fue modificado y el comentario del asesor.
7. `session_closed` — cierre de la sesión.

El `AuditTrail` es **append-only**: una vez cerrado no acepta nuevos eventos. El cierre es parte del flujo normal del M1; no es opcional.

El `AuditTrail` es serializable a JSON (`audit.to_json()`) para archivo, transmisión o integración con sistemas de auditoría externos.

---

## 3. Reason codes como trazabilidad

Cada decisión del sistema que excluye un instrumento, bloquea el flujo o genera una advertencia queda registrada con un `reason_code` específico. Ver `docs/REASON_CODES.md` para el catálogo completo.

Los `reason_codes` en `AdvisoryWorkflowResult` permiten al asesor y al auditor responder: "¿Por qué este instrumento no está en la cartera?" y "¿Por qué el workflow terminó bloqueado?" sin acceso al código fuente.

---

## 4. Orden de filtros: governance → suitability → ESG → datos

El pipeline de filtros aplica los criterios en un orden fijo que refleja la jerarquía regulatoria:

1. **Product governance** (`ApprovedProductUniverse`): ¿el instrumento está aprobado por la firma para este tipo de cliente/perfil? Es el filtro más restrictivo desde el punto de vista regulatorio.
2. **Suitability** (`InstrumentSuitabilityMatrix`): ¿el tipo de instrumento es adecuado para este cliente específico? Puede generar advertencias de concentración (LIMITED).
3. **ESG compliance** (`ESGComplianceChecker`): ¿el instrumento cumple las restricciones ESG declaradas por el cliente? Las hard exclusions bloquean; las soft preferences generan advertencias.
4. **Market data + Data quality** (`DataQualityGate`): ¿hay datos suficientes y confiables para optimizar? Excluye instrumentos sin datos o con datos degradados.

Este orden garantiza que el optimizador nunca recibe instrumentos que violen restricciones regulatorias o de cliente.

---

## 5. ESG: hard exclusions y soft warnings

- **Hard exclusions** (`ESGExclusion`): el instrumento es excluido si su sector, emisor o categoría coincide con una exclusión declarada por el cliente. La exclusión es binaria y no negociable dentro del flujo automático. Se registra como `ESG_BLOCKED`.
- **Soft preferences** (`ESGPreference`): el instrumento puede incluirse aunque no cumpla la preferencia, pero se registra como `ESG_WARNING`. El asesor decide si el incumplimiento de la preferencia es aceptable.
- **UNKNOWN**: instrumentos sin metadata ESG pasan al universo con advertencia `ESG_WARNING`. El asesor debe evaluar si son aceptables dado el perfil ESG del cliente.

La separación entre exclusiones hard y soft permite al cliente tener restricciones absolutas (ej. "no armas") y preferencias relativas (ej. "preferir ESG score alto") sin que las preferencias bloqueen el flujo.

---

## 6. No circularidad por retorno objetivo en el KYC

El campo `return_target_annual_pct` fue eliminado de `KYCData`. `declared_return_expectation_pct` existe pero es informativo y no participa en ningún cálculo.

El retorno objetivo se deriva exclusivamente de `FinancialGoal` (capital, horizonte, aportes) mediante `GoalFeasibilityEngine`. Esto elimina la circularidad: el perfil no depende de un retorno objetivo que a su vez dependería del perfil.

Ver DD-002, DD-003, DD-004 en `docs/DESIGN_DECISIONS.md`.

---

## 7. El workflow no relaja restricciones aprobadas

`AdvisoryWorkflowCoordinator` no ajusta `max_single_asset`, `max_volatility` ni ningún otro límite del `RiskBudget` aprobado, bajo ninguna condición.

Si el pre-check de portfolio feasibility detecta que el `RiskBudget` es infactible con el universo final, el workflow termina en `BLOCKED_BY_PORTFOLIO_FEASIBILITY` con diagnóstico completo. La decisión de relajar cualquier restricción corresponde exclusivamente al asesor con justificación documentada.

Esta política garantiza que ninguna cartera generada automáticamente viole restricciones aprobadas en el proceso de onboarding.

---

## 8. Demo adjustment histórico: eliminado del flujo productivo

Una versión anterior de `run_demo.py` relajaba localmente `max_single_asset` y `max_volatility` cuando el `RiskBudget` resultaba infactible, para poder mostrar portfolios de todas formas en el demo. Este comportamiento fue eliminado.

`run_demo.py` usa `AdvisoryWorkflowCoordinator` sin modificaciones. Si el workflow se bloquea, el demo lo muestra y explica. El demo es representativo del comportamiento productivo.

---

## 9. Reporting como formateo, no cálculo

`MarkdownReportGenerator` formatea el `AdvisoryWorkflowResult` ya computado. No invoca ningún motor de cálculo, no re-evalúa ESG, no llama al optimizador. El reporte es una proyección del resultado.

Esto garantiza que el contenido del reporte sea siempre consistente con los datos que el sistema usó para tomar decisiones, sin riesgo de divergencia por recálculo.

---

## 10. Limitaciones actuales (M2-prep / MVP)

Las siguientes funcionalidades no están implementadas en M1 y representan áreas de riesgo de compliance a resolver en M2 o posterior:

| Limitación | Impacto de compliance | Sprint objetivo |
|---|---|---|
| `OpenAIProfileClient` en producción | Los prompts de la IA real deben validarse periódicamente. Las respuestas de OpenAI son no determinísticas: el mismo KYC puede producir perfiles distintos en distintas llamadas. Requiere logging de todas las respuestas de OpenAI para auditoría. | M2/M3 |
| `MockMarketDataProvider` con datos de fixture | Los datos de mercado en producción deben tener SLA de frescura, auditoría de fuente y control de calidad automatizado. | M2 |
| Universo CSV de demo (`sample_instrument_universe.csv`) | Los retornos esperados de los instrumentos del universo CSV son derivados de YTM/cupón estáticos, no de precios de mercado actualizados. No aptos para producción. | M2 |
| `GROWTH` sin firma digital ni integración con AuditTrail | GROWTH se marca con `PortfolioVariantMetadata` cuando excede el RiskBudget (**implementado**). `POST /advisor/override-approval` persiste la decisión del asesor como `advisor_override_approval_NNNNNN` (**Fase 1 ✅**). Pendiente: integrar el record en el `AuditTrail` del workflow principal; firma digital del asesor; RBAC explícito. | M2+ |
| `ESGPreference` con `prefer_tag`/`avoid_tag` | Las preferencias cualitativas no se evalúan en M1. Los instrumentos afectados reciben `ESG_DATA_INCOMPLETE`. | M2 |
| Sin persistencia de sesión | El `AuditTrail` se genera en memoria. En producción debe persistirse antes del cierre de sesión. | M2 |
| Sin firma del asesor | `AdvisoryProfile.advisor_comment` es texto libre sin firma digital ni identificación verificada. | M3 |
| Sin modelo de idoneidad regulatoria explícito (MiFID II / CNBV) | La suitability actual es por tipo de instrumento y perfil; no incluye el cuestionario MiFID II completo ni el análisis de conocimiento y experiencia detallado. | M3 |

---

## 11. KYC estandarizado y uso limitado de IA

El sistema usa un `KYCData` estructurado como fuente primaria del perfil. Este diseño es una decisión de compliance, no solo una preferencia técnica.

**Por qué KYC estructurado:**
- Garantiza que todos los clientes respondan el mismo conjunto de variables mínimas, lo que hace los perfiles comparables entre sí.
- Permite demostrar ante un auditor que dos clientes con características similares fueron tratados de forma consistente.
- Los campos del KYC son la evidencia documental del proceso de perfilamiento; su ausencia o variación libre haría indefendible la recomendación final.

**Rol acotado de la IA:**
- La IA analiza el `KYCData` ya recolectado. No decide libremente qué preguntar como mecanismo primario de perfilamiento.
- Las preguntas de follow-up que genera la IA son consecuencia de contradicciones o ambigüedades detectadas en el KYC estructurado, no una conversación libre.
- Las respuestas abiertas (`open_investment_goal`, `open_risk_reaction`, `open_past_experience`, `open_concerns`) existen en `KYCData` como observaciones textuales para el asesor y la IA. No modifican automáticamente campos duros del perfil sin revisión del asesor.

**Aprobación del asesor:**
- El perfil final es siempre un `ApprovedProfile` firmado por el asesor. Ninguna propuesta de la IA —ni siquiera tras el follow-up— se convierte en decisión sin ese paso.
- El `AuditTrail` registra la trazabilidad completa: KYC recibido → perfil propuesto por IA → follow-up (si aplica) → perfil revisado → aprobación del asesor.

**Beneficio ante auditoría:** este diseño permite responder con evidencia documental a las preguntas regulatorias estándar: "¿Qué datos recopiló?", "¿Cómo llegó a este perfil?", "¿Por qué este cliente tiene este perfil y no otro?", y "¿Quién tomó la decisión final?"

---

## 12. Portfolio variant metadata y advisor override (M2-prep)

El sistema genera hasta tres variantes de cartera por sesión: `DEFENSIVE`, `BALANCED` y `GROWTH`. Cada variante tiene una relación distinta con el `RiskBudget` aprobado del cliente:

- **`DEFENSIVE`** opera con un budget más conservador que el aprobado. No puede exceder el `RiskBudget`.
- **`BALANCED`** respeta estrictamente el `RiskBudget` aprobado. Es la recomendación base.
- **`GROWTH`** puede exceder parcialmente el `RiskBudget` aprobado (específicamente `max_volatility`). Cuando lo hace, el exceso no se silencia.

**Mecanismo de transparencia implementado:**

Cuando `GROWTH` excede el `RiskBudget`, `PortfolioGenerationCoordinator` registra en `PortfolioVariantMetadata`:
- `risk_budget_exceeded = True`
- `requires_advisor_override = True`
- `exceeded_constraints` — lista de restricciones excedidas (ej. `["max_volatility"]`)
- `reason_codes = ["PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"]`

Esta metadata se almacena en `PortfolioCandidateSet.metadata` y se muestra en el reporte Markdown bajo **Variant Metadata** para cada variante. El reporte muestra los valores de forma explícita para que el asesor pueda evaluar el exceso antes de cualquier presentación al cliente.

**Lo que esta política garantiza:**
- `GROWTH` nunca se presenta al cliente sin que el asesor haya visto su clasificación de exceso.
- `BALANCED` es siempre la recomendación base dentro del perfil aprobado.
- El exceso de riesgo en `GROWTH` es auditable: queda en el `PortfolioCandidateSet`, en el reporte Markdown y (en el futuro) en el audit trail con firma del asesor.

**Estado Fase 1 — advisor override persistido:**

`POST /advisor/override-approval` (Fase 1) permite al asesor registrar explícitamente la decisión de `approve` o `reject` sobre la variante GROWTH fuera del budget, con:
- `rationale` obligatorio (≥ 1 carácter).
- `reason_codes` y `exceeded_constraints` declarados por el asesor.
- Identidad del asesor (`advisor_id`, `advisor_display_name`) resuelta desde el Bearer token.
- Persistencia como record SQLite `advisor_override_approval_NNNNNN` con `created_at_utc`.

**Pendiente de compliance (post-Fase 1):**

- La decisión de override no está todavía integrada en el `AuditTrail` del workflow principal — solo vive como record SQLite independiente. Para auditoría completa: propagar a `AuditTrail` con evento `advisor_override_approval`.
- No hay firma digital del asesor (el `rationale` es texto libre sin firma criptográfica ni identificación verificada por IdP).
- El endpoint no valida todavía que la variante `candidate_variant` exista realmente en el `ai_filtered_portfolio_NNNNNN` apuntado por `related_record_id`, ni que `requires_advisor_override=True`. La validación cruzada queda para Fase 2.
- No hay RBAC: cualquier token demo (advisor o compliance) puede registrar el override. Fase 2: restringir a `roles=["advisor"]`.
- Ver `docs/DESIGN_DECISIONS.md` DD-010 y `docs/TODO_DESIGN_NOTES.md`.

---

## 13. AI Filtered Portfolio Demo — postura de compliance

`POST /ai/filtered-portfolio-demo` implementa un pipeline de cuatro pasos: extracción de preferencias (OpenAI) → filtro determinístico (universo CSV) → snapshots proxy → generación de portfolios.

### Separación de responsabilidades en el pipeline

La separación entre IA y motor determinístico es un principio de diseño central:

1. **OpenAI solo estructura el texto libre del cliente.** La IA convierte "quiero ONs argentinas en Balanz sin energía" en campos estructurados (`allowed_instrument_types`, `entity`, `avoid_sectors`, etc.). No selecciona instrumentos. No calcula pesos. No aprueba nada.

2. **`PreferenceFilterEngine` es determinístico y auditado.** Dadas las mismas preferencias estructuradas y el mismo universo CSV, el resultado del filtro es siempre idéntico. Cada exclusión tiene una razón explícita (`instrument_type_not_allowed:ETF`, `sector_avoided:Energy`, etc.) auditable sin acceso al código fuente.

3. **El optimizador respeta el `RiskBudget` del perfil.** El perfil seleccionado en la request determina el `RiskBudget` via `PROFILE_BASE_PARAMS`. El motor no lo relaja automáticamente. Si el universo filtrado es insuficiente para satisfacer el budget, el endpoint devuelve un status bloqueado con diagnóstico explícito.

### Lo que este endpoint NO hace (límites de diseño)

- **No aprueba el perfil del cliente.** El `profile` se selecciona directamente como parámetro de demo. En producción debe surgir del proceso de perfilamiento y aprobación del asesor.
- ~~**No persiste el resultado.**~~ — ✅ **Cerrado en Fase 0.** Cada respuesta de `/ai/filtered-portfolio-demo` se persiste en SQLite como record `ai_filtered_portfolio_NNNNNN` (payload completo + metadata) y el reporte Markdown como `report_NNNNNN`. Ambos IDs se exponen en la response (`record_id`, `report_record_id`). Aplica para los cuatro `status` posibles (`completed` y las tres variantes `blocked`).
- **No genera un reporte comercial para el cliente.** El campo `report_markdown` es un reporte técnico para revisión del asesor (generado por `AIFilteredPortfolioReportGenerator`, 10 secciones fijas). No es un documento de presentación al cliente. No hay PDF ni firma digital en esta fase.
- **No valida que el asesor haya revisado las preferencias extraídas por la IA.** Las preferencias estructuradas por OpenAI se aplican directamente al filtro sin un paso de revisión intermedio del asesor. En producción, el asesor debe poder ver y corregir las preferencias antes de que se apliquen.
- **Las decisiones del asesor sobre el portfolio son actos separados.** Los tres endpoints de Fase 1 (`/advisor/profile-approval`, `/advisor/override-approval`, `/advisor/portfolio-selection`) permiten al asesor registrar formalmente sus decisiones sobre el resultado de `/ai/filtered-portfolio-demo`, enlazándolas por `related_record_id`. No están integrados en un flujo transaccional único todavía.

### Datos proxy y sus limitaciones

Los retornos esperados en el universo CSV se derivan de `ytm` (yield to maturity) o `coupon_rate` como proxy. Esto es aceptable para una demo de arquitectura, pero no para producción:
- El YTM estático no refleja el precio de mercado actual ni el spread de crédito corriente.
- La volatilidad proxy es una constante derivada del `ytm / 10`, no una estimación calibrada.
- ETFs, CEDEARs y acciones no tienen `ytm` ni `coupon_rate` en el CSV, por lo que el adaptador no genera snapshots usables para esos instrumentos.

Antes de usar este endpoint con clientes reales, los datos de mercado deben reemplazarse por fuentes con SLA de frescura documentado y proceso de validación auditado.
