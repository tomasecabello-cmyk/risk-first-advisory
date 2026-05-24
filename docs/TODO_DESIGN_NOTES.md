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

## KYCDataRequest extended fields — Fase 1.5 ✅

### Estado actual

`/workflow/run` ya no inventa silenciosamente los siguientes campos:

| Campo antes hardcoded | Estado actual |
|---|---|
| `jurisdiction="AR"` | viene del request (`KYCDataRequest.jurisdiction`, default `"AR"`, no vacío) |
| `preferred_currency="USD"` | viene del request (default `"USD"`, no vacío) |
| `investment_objective=BALANCED` | viene del request como string validado contra el enum (default `"balanced"`) |
| `prefers_simple_products=False` | viene del request (default `false`) |
| `annual_income_usd` derivado de `liquid_net_worth * 0.05` | viene del request si se manda; si no, **fallback histórico documentado** |
| `ESGProfile()` vacío | construido desde `esg_strictness_level` + `esg_exclusions` + `esg_preferences` del request; default = perfil vacío equivalente |

Todos los defaults son backward-compatible: payloads existentes siguen 200.

### Limitaciones aceptadas

- **ESG sigue básico.** El dominio `kyc.models.ESGProfile` no soporta `esg_min_score` global, así que el campo no se expone en la API. La granularidad fina queda en `ESGPreference.minimum_threshold` por preferencia.
- **`annual_income_usd` con fallback.** Para no romper payloads sin ingresos declarados, el endpoint mantiene `annual_income = max(liquid_net_worth * 0.05, 1.0)` cuando el campo es `null`. Para auditoría productiva conviene exigir el valor explícito (eliminar fallback con un flag de config en una tarea posterior).
- **`investment_experience` mapping legacy.** El mapeo `_EXPERIENCE_MAP` cae a `InvestorExperience.MODERATE` si recibe un alias desconocido — el validador Pydantic ya rechaza valores fuera de la lista, así que en práctica el fallback nunca se ejecuta vía API. Queda como defensa en profundidad.

### Próximos pasos opcionales

1. Hacer `annual_income_usd` obligatorio cuando un nuevo flag (`STRICT_KYC=true`) esté activo, para entornos productivos.
2. Soporte de `esg_min_score` global si el dominio se expande (cambio en `ESGProfile`).
3. Validación cruzada `investment_objective` vs `risk_tolerance_score` / `risk_capacity_score` (ej. avisar si `investment_objective="aggressive_growth"` con `risk_tolerance_score=2`).
4. Mover los enums duplicados (`_VALID_INVESTMENT_OBJECTIVES`, `_VALID_ESG_STRICTNESS`, `_VALID_ESG_EXCLUSION_TYPES`) a un módulo compartido cuando crezca la API surface.

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
2. ~~**Segundo endpoint: advisor override de GROWTH**~~ ✅ `POST /advisor/override-approval` agregado: registra `approve`/`reject` sobre una variante (típicamente GROWTH) que excede el RiskBudget aprobado, con reason_codes y exceeded_constraints explícitos. Persiste como `advisor_override_approval_NNNNNN`. NO valida todavía contra existencia real del candidate ni del record relacionado.
3. ~~**Tercer endpoint: selección final de cartera**~~ ✅ `POST /advisor/portfolio-selection` agregado: registra la variante final (`DEFENSIVE`/`BALANCED`/`GROWTH`) a presentar al cliente, con `related_record_id` y `override_approval_record_id` opcionales. Si selected_variant=GROWTH y override_approval_record_id está vacío, la response incluye warning `"GROWTH selected without linked override approval record."` (persistido también en el payload). NO bloquea — solo deja rastro. NO valida todavía contra existencia real de los records enlazados.
4. **Conciliación dominio ↔ API**: el módulo `human_layer.override_approval.AdvisorOverrideApproval` ya existía con un contrato más estricto (enums, comment ≥ 20 chars, validación contra `PortfolioVariantMetadata` viva) pensado para integración con workflow. El endpoint API usa schemas independientes y más laxos (rationale ≥ 1 char, sin live metadata). Cuando exista un endpoint que invoque el override desde dentro de un workflow corriendo (en lugar de "registro post-mortem"), conviene unificar ambos o usar el dominio como capa interna.
5. **Validación contra existencia real de records enlazados** (post-Fase 1):
   - `/advisor/override-approval`: si `related_record_id` apunta a un `ai_filtered_portfolio_NNNNNN`, verificar que el `candidate_variant` exista en ese record y que efectivamente tenga `requires_advisor_override=True`.
   - `/advisor/portfolio-selection`: si `related_record_id` apunta a un `ai_filtered_portfolio_NNNNNN`, verificar que `selected_variant` esté entre los candidatos generados. Si `override_approval_record_id` apunta a un `advisor_override_approval_NNNNNN`, verificar que el `advisor_id`, `client_id`, `candidate_variant` y `decision="approve"` sean coherentes con la selección.
   - Si los datos no coinciden, devolver 422 o registrar con flag `_inconsistent_with_source=True` para que compliance lo revise.
6. **Endpoints de retrieval** (post-Fase 1):
   - `GET /advisor/profile-approval/{record_id}`
   - `GET /advisor/override-approval/{record_id}`
   - `GET /advisor/portfolio-selection/{record_id}`
   - Listing por `client_id` para los tres (los repos ya lo soportan vía `list_*`).
7. **RBAC por rol** — restringir endpoints de decisión a `roles=["advisor"]`; permitir a `compliance` solo retrieval/listado.
8. **Reemplazar el mapa hard-coded** por un identity provider externo (OIDC, SAML, JWT firmado por IdP).
9. **Persistir `advisor_id` en audit trail** en cada acción de aprobación (no solo el `advisor_id` declarado en `WorkflowRunRequest`).
10. **Multi-tenant**: poblar `firm_id` desde el IdP y propagar como filtro implícito en todas las consultas al record store.
11. **Roles**: actualmente sólo `advisor` y `compliance`; ampliar (`reviewer`, `admin`, etc.) cuando los flujos de aprobación lo justifiquen, y agregar checks por rol en cada endpoint que lo necesite.

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