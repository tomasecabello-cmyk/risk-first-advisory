\# TODO / Design Notes



\## ESGPreference target pendiente



Actualmente `ESGPreference` tiene los campos:



\- `preference\_type`

\- `weight`

\- `minimum\_threshold`



Esto permite modelar preferencias cuantitativas como:



\- `min\_esg\_score`

\- `max\_carbon\_intensity`



Pero no permite especificar directamente qué tag se quiere preferir o evitar para:



\- `prefer\_tag`

\- `avoid\_tag`



Por eso, en M1, `ESGComplianceChecker` trata `prefer\_tag` y `avoid\_tag` como datos incompletos y devuelve warning con reason code:



`ESG\_DATA\_INCOMPLETE`



\## Decisión actual



No extender `ESGPreference` todavía.



\## Posible cambio futuro



Agregar un campo opcional:



```python

target: str | None = None

---

## Portfolio variant policy pendiente

Actualmente `PortfolioGenerationCoordinator` genera tres variantes:

- `DEFENSIVE`
- `BALANCED`
- `GROWTH`

En M1, las variantes se mantienen dentro del `RiskBudget` aprobado o quedan bloqueadas por `PortfolioFeasibilityChecker` si el universo final no permite construir una cartera compatible.

## Decisión conceptual

No queremos que el sistema encajone al cliente en una única zona de riesgo.

La política objetivo para M2 es:

- `DEFENSIVE` debe ser más conservadora que el `RiskBudget` aprobado.
- `BALANCED` debe respetar estrictamente el `RiskBudget` aprobado.
- `GROWTH` puede exceder parcialmente el `RiskBudget` aprobado como alternativa de mayor riesgo.

## Condición obligatoria para GROWTH

Si `GROWTH` excede cualquier límite del `RiskBudget` aprobado, el exceso no debe ocultarse.

Debe quedar marcado explícitamente como:

- `requires_advisor_override = True`
- `risk_budget_exceeded = True`
- `reason_code = PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET`

También debe registrar qué restricciones fueron excedidas, por ejemplo:

- `max_volatility`
- `max_single_asset`
- `max_equity`
- `max_high_yield`

## Criterio de compliance

`BALANCED` representa la recomendación base dentro del perfil aprobado.

`GROWTH` puede mostrarse como alternativa de mayor riesgo, pero no debe presentarse como recomendación base si excede el `RiskBudget`.

El cliente puede elegir moverse hacia una alternativa más agresiva, pero esa decisión requiere revisión y aprobación explícita del asesor.

## Estado actual

**Implementado parcialmente (M2-prep).**

- `PortfolioVariantMetadata` agregado en `portfolio_layer/generation.py`.
- `PortfolioCandidateSet` incluye campo `metadata: dict[PortfolioVariant, PortfolioVariantMetadata]`.
- `PortfolioGenerationCoordinator` genera metadata por variante en cada `generate()`.
- `GROWTH` usa un budget derivado con `max_volatility` relajado (`min(original * 1.5, original + 0.05)`).
- `GROWTH` **no** relaja `max_single_asset` por ahora (evita romper pre-checks de factibilidad).
- Cuando `GROWTH` excede el budget original, queda marcado con `risk_budget_exceeded=True`, `requires_advisor_override=True` y `RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET`.
- El reporte Markdown muestra la metadata por variante bajo `**Variant Metadata:**`.

## Pendiente

- El override del asesor todavía no es una acción persistida/firmada. El reporte lo expone visualmente, pero no existe un endpoint o UI donde el asesor confirme explícitamente que acepta la variante GROWTH fuera del budget.
- Eso queda para la capa de workflow/UI futura (firma de override, trazabilidad en audit trail).

---

## Advisor auth scaffold — Fase 1 (development-only)

### Estado actual

`api_layer/auth.py` implementa una resolución de identidad por Bearer token con un mapa hard-coded de tokens demo:

- `dev-advisor-token` → `ADV-001` (rol `advisor`)
- `dev-compliance-token` → `CMP-001` (rol `compliance`)

Expone dos dependencias FastAPI:

- `get_current_advisor_required` — usar en endpoints de aprobación / override.
- `get_current_advisor_optional` — usar en endpoints que aún funcionan de forma anónima en demo.

Único endpoint nuevo: `GET /auth/me` (diagnóstico). Ningún otro endpoint requiere auth en Fase 1; eso se irá habilitando endpoint por endpoint.

### Limitaciones intencionales (por qué NO usar esto en producción)

- Tokens hard-coded en el código fuente. Sin `.env`, sin secret store.
- Sin firma criptográfica (no JWT, no PASETO).
- Sin TTL, rotación, revocación, refresh.
- Sin emisión de tokens (no hay `/auth/login`).
- Sin tenancy (`firm_id` siempre `None` para los tokens demo).
- Sin rate limiting / protección de brute force.
- Sin auditoría de intentos fallidos.

### Próximos pasos (post-Fase 1 inicial)

1. ~~**Primer endpoint protegido del asesor**~~ ✅ `POST /advisor/profile-approval` agregado: registra `approve`/`modify`/`reject` con rationale obligatorio. Persiste como `advisor_profile_approval_NNNNNN`. Sin RBAC todavía (cualquier identidad demo puede registrar).
2. **Proteger endpoints adicionales** con `Depends(get_current_advisor_required)`:
   - Firma de advisor override de GROWTH.
   - Selección de variante a presentar al cliente.
   - Cualquier endpoint que registre eventos en audit trail debe atribuirse a un `advisor_id` real.
3. **RBAC por rol** — restringir `POST /advisor/profile-approval` a `roles=["advisor"]`; permitir a `compliance` solo retrieval/listado. Endpoint pending: `GET /advisor/profile-approval/{record_id}`.
4. **Reemplazar el mapa hard-coded** por un identity provider externo (OIDC, SAML, JWT firmado por IdP).
5. **Persistir `advisor_id` en audit trail** en cada acción de aprobación (no solo el `advisor_id` declarado en `WorkflowRunRequest`).
6. **Multi-tenant**: poblar `firm_id` desde el IdP y propagar como filtro implícito en todas las consultas al record store.
7. **Roles**: actualmente sólo `advisor` y `compliance`; ampliar (`reviewer`, `admin`, etc.) cuando los flujos de aprobación lo justifiquen, y agregar checks por rol en cada endpoint que lo necesite.

---

## AI Filtered Portfolio — pendientes de diseño (MVP post)

### Persistencia y reporte ✅ CERRADO EN FASE 0

`POST /ai/filtered-portfolio-demo` ahora:
- Devuelve `report_markdown` generado por `AIFilteredPortfolioReportGenerator` (determinístico, 10 secciones).
- Persiste el payload completo de la respuesta en SQLite como record `ai_filtered_portfolio` (id `ai_filtered_portfolio_NNNNNN`) y expone `record_id` en la response.
- Persiste el reporte Markdown como `MarkdownReport` (id `report_NNNNNN`) y expone `report_record_id` en la response.
- Metadata persistida: `client_id`, `profile`, `status`, `candidate_count`, `endpoint`.
- Esto aplica para los cuatro `status` posibles (completed + tres variantes blocked).

No se escriben archivos `.md` a disco; sólo se persiste en el record store SQLite.

**Pendiente (post-Fase 0):**
- Endpoint para que el asesor seleccione la variante a presentar al cliente (DEFENSIVE/BALANCED/GROWTH) con registro en audit trail.
- Endpoint para firmar/aprobar override de GROWTH con justificación documentada.
- Endpoint genérico de retrieval para records `ai_filtered_portfolio` (análogo a `GET /workflow/{record_id}`).

### Universo de instrumentos

El universo actual (`tests/fixtures/universe/sample_instrument_universe.csv`, 20 instrumentos) es un fixture de demo con datos ficticios de YTM, cupón y liquidez. No es apto para producción.

**Pendiente:**
- Diseñar `InstrumentUniverseProvider` con soporte para múltiples fuentes: CSV, base de datos, API externa.
- Conectar `InstrumentMarketDataAdapter` a datos reales de mercado con SLA de frescura documentado.
- Definir política de actualización del universo (manual, automática, auditada).

### Retornos proxy vs. datos de mercado reales

`InstrumentMarketDataAdapter` deriva `expected_return_annual` desde `ytm` o `coupon_rate` del CSV. Esto es una aproximación válida para instrumentos de renta fija en demo, pero:
- Ignora duration, convexidad, spread de crédito y precio de mercado real.
- No aplica para ETFs, CEDEARs ni acciones (que producen `snapshot=None`).
- En producción debe reemplazarse por datos de precio histórico o estimaciones de un modelo de retorno calibrado.

### Diversification pre-check

El pre-check actual es: `usable_snapshots < ceil(1.0 / max_single_asset)` → bloqueado.

Esta lógica es correcta para portfolios de máxima concentración uniforme, pero no contempla:
- Instrumentos con distintos límites de concentración (ej. activos con restricción sectorial).
- Portfolios con restricciones de activo mínimo (no solo máximo).
- La posibilidad de que el optimizador encuentre solución con concentraciones asimétricas aunque `usable < required_min_uniform`.

Revisar si el pre-check debe ser más permisivo o si el bloqueo es suficientemente conservador para el MVP.

### Caching de preferencias de OpenAI

Cada request a `/ai/filtered-portfolio-demo` llama a OpenAI para extraer preferencias, incluso si el texto de preferencias es idéntico al de una request anterior. Para un demo de volumen bajo esto es aceptable, pero en producción añadir:
- Cache con clave `hash(natural_language_preferences)` con TTL configurable.
- O un endpoint separado de "guardar preferencias" para que el asesor valide y reutilice el resultado de OpenAI sin re-llamar cada vez.

### Firma del asesor en el flujo filtrado

El endpoint actual devuelve portfolios candidatos sin ninguna acción de aprobación del asesor. En producción, el flujo debe incluir:
- Un paso de revisión donde el asesor valida las preferencias extraídas por la IA antes de que se apliquen al filtro.
- Un paso de aprobación del portfolio seleccionado (DEFENSIVE, BALANCED o GROWTH) con registro en audit trail.
- Si GROWTH requiere override, firma explícita del asesor con justificación documentada.