\# TODO / Design Notes

---

## Fase 2 — Workflow case-scoped backend readiness ✅ (cerrada)

Fase 2 está **funcionalmente cerrada a nivel backend/workflow**. El flujo completo end-to-end de un `AdvisoryCase` está implementado, testeado (3016 tests verdes) y validado vía smoke check ejecutable.

### Qué incluye Fase 2 cerrada

| Bloque | Estado | Endpoints / artefactos |
|---|---|---|
| Migrations infra + core schema | ✅ | `migrations/0001..0009`, runner `scripts/migrate.py` |
| Advisor tokens desde config | ✅ | `config/advisor_tokens.yaml` + `ADVISOR_TOKENS_FILE` env var |
| RBAC enforcement por rol | ✅ | `require_roles("admin", "advisor", "compliance", "viewer")` |
| Firm / Advisor / Client entities | ✅ | `/firms`, `/advisors`, `/clients` (CRUD) |
| AdvisoryCase + FSM | ✅ | `/cases` (POST/GET/list), `PATCH /cases/{id}/status`, FSM DRAFT → IN_PROGRESS → PORTFOLIO_SELECTED → CLOSED |
| KYCSubmission case-scoped | ✅ | `POST/GET /cases/{id}/kyc`; versionado por case; auto-event `kyc_submitted` |
| AIProfileAnalysis case-scoped | ✅ | `POST/GET /cases/{id}/ai/profile-analysis`; vincula KYC + AIRequestLog |
| AdvisorProfileApproval case-scoped | ✅ | `POST/GET /cases/{id}/profile-approval`; mantiene `is_current` + `current_approved_profile_id`; auto-events `advisor_profile_approved/_modified/_rejected` |
| InvestmentPreferences case-scoped | ✅ | `POST/GET /cases/{id}/investment-preferences`; manual o AI-extracted |
| UniverseFilterRun case-scoped | ✅ | `POST/GET /cases/{id}/universe-filter` sobre CSV |
| PortfolioProposal case-scoped | ✅ | `POST/GET /cases/{id}/portfolio-proposal` |
| OverrideApproval case-scoped | ✅ | `POST/GET /cases/{id}/override-approval` |
| PortfolioSelection case-scoped | ✅ | `POST/GET /cases/{id}/portfolio-selection`; actualiza puntero + status |
| CaseReport case-scoped | ✅ | `POST/GET /cases/{id}/reports`, `GET /cases/{id}/reports/{report_id}`; markdown determinístico |
| Case Summary | ✅ | `GET /cases/{id}/summary` — full case state en un solo response |
| AuditEvent hash chain por case | ✅ | `GET /cases/{id}/audit`, `/audit/verify`, `POST /cases/{id}/audit-events` |
| AIRequestLog con redacción de PII | ✅ | `GET /admin/ai-logs`, `/admin/ai-logs/{id}`, `/cases/{id}/ai-logs`, `POST /admin/ai-logs` |
| End-to-end smoke check | ✅ | `python scripts/run_case_workflow_smoke_check.py` |

### Lo que Fase 2 NO incluye

Esto está documentado para evitar confusiones operativas, **no** son bugs ni regresiones:

- **Frontend nuevo case-scoped** — el legacy `frontend/index.html` sigue mostrando solo Fase 0/1. Item Fase 3.
- **Firm-level access control** completo — cualquier token con rol válido ve cualquier case. Item Fase 4.
- **Auth productiva** (JWT/OIDC/IdP) — tokens son strings opacos en YAML. Item Fase 4.
- **Live market data provider** — el universe-filter sigue usando CSV fixture. Item Fase 4.
- **PDF / branding del report** — solo markdown. Item Fase 3.
- **Lifecycle formal de reports** (draft → reviewed → final → sent) — solo `{draft, final}`. Item Fase 3.
- **Cifrado at-rest** / WORM external storage / sign-off legal formal — items Fase 4.

### Próximos focos

- **Fase 3 (próxima)**: plug-and-play local + Case Workbench frontend. Ver sección "Fase 3 — UI + bootstrap local" más abajo.
- **Fase 4**: pilot readiness / production hardening. Ver sección "Fase 4 — Pilot readiness" más abajo.

---

## Fase 3 — UI + bootstrap local (próxima, NO empezada)

Objetivo: que un dev nuevo pueda clonar el repo, correr un script, y ver el flujo case-scoped end-to-end en el navegador sin pasos manuales adicionales.

- ~~**Case Dashboard frontend** — listado de cases con `current_*` flags y `next_recommended_action` consumidos de `GET /cases/{id}/summary`.~~ ✅
- ~~**Case Workbench frontend** — vista detalle por case con tabs para KYC / análisis / approval / preferences / filter / proposal / override / selection / report / audit / AI logs / compliance snapshot.~~ ✅ (15 paneles end-to-end)
- ~~**Frontend cleanup / split** — separar HTML estructural de CSS/JS.~~ ✅ (`css/base.css` + `js/common.js` + `js/legacy-demo.js` + `js/case-dashboard.js` + `js/case-workbench.js`)
- ~~**Seed demo data script** — crea/reusa firm/advisor/client/case demo con IDs estables `*_demo_local`; idempotente; aplica migrations automáticamente.~~ ✅ (`scripts/seed_demo_data.py`)
- ~~**Local bootstrap script** — un comando que aplica migrations + corre seed + valida archivos del frontend + detecta config + imprime comandos backend/frontend + tokens. Flags `--check-only`, `--skip-migrate`, `--skip-seed`, `--run-smoke`.~~ ✅ (`scripts/bootstrap_local_demo.py`)
- **Setup health checks** — `GET /health` extendido o `/health/full` que valide migrations aplicadas, tokens cargados, fixtures presentes. Próximo entregable.
- **Plug-and-play docs** — README "5 min quickstart" para Case Workbench.

## Fase 4 — Pilot readiness (después de Fase 3)

Hardening necesario para correr el sistema con un asesor piloto real (no producción aún):

- **Firm-level access control** — `firm_id` en token + filtrado por firm en todos los `/cases/*`.
- **Production auth** — JWT/OIDC/IdP integration; rotación de tokens; revocation.
- **Market data provider productivo** — reemplazar el CSV fixture por live provider con SLA de frescura y validación.
- **Manual universe upload** — admin endpoint para reemplazar el CSV sin redeploy.
- **PDF / branding del report** — render de markdown a PDF con logo + colores + header de la firm.
- **Backup / restore** de la DB SQLite (o migración a PostgreSQL si la escala lo pide).
- **Pilot readiness checklist** — documentación legal/compliance, sign-off, runbook de incidentes.
- **Cifrado at-rest** + retention/pruning policy para `ai_request_logs`, `kyc_submissions`, etc.
- **Anclaje externo del audit chain** (timestamping authority o append-only external store) para defenderse contra DBA malicioso.
- **AuditEvent integrado en endpoints legacy** (`/advisor/profile-approval`, `/advisor/override-approval`, `/advisor/portfolio-selection`, `PATCH /cases/{id}/status`).

---

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

**Cerrado en Fase 1.**

- `PortfolioVariantMetadata` agregado en `portfolio_layer/generation.py`.
- `PortfolioCandidateSet` incluye campo `metadata: dict[PortfolioVariant, PortfolioVariantMetadata]`.
- `PortfolioGenerationCoordinator` genera metadata por variante en cada `generate()`.
- `GROWTH` usa un budget derivado con `max_volatility` relajado (`min(original * 1.5, original + 0.05)`).
- `GROWTH` **no** relaja `max_single_asset` por ahora (evita romper pre-checks de factibilidad).
- Cuando `GROWTH` excede el budget original, queda marcado con `risk_budget_exceeded=True`, `requires_advisor_override=True` y `RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET`.
- El reporte Markdown muestra la metadata por variante bajo `**Variant Metadata:**`.
- ~~El override del asesor todavía no es una acción persistida/firmada.~~ → **✅ Cerrado en Fase 1.** `POST /advisor/override-approval` persiste la decisión del asesor con rationale, reason_codes y exceeded_constraints como record `advisor_override_approval_NNNNNN` en SQLite. Requiere Bearer token.
- ~~No existe un endpoint o UI donde el asesor seleccione la variante final.~~ → **✅ Cerrado en Fase 1.** `POST /advisor/portfolio-selection` registra la selección final (`DEFENSIVE`/`BALANCED`/`GROWTH`) con `override_approval_record_id` opcional. Si GROWTH se selecciona sin override link, se emite warning (persistido en payload). Requiere Bearer token.

## Pendiente (Fase 2)

- **Validación cruzada de records existentes:** `/advisor/override-approval` no verifica que el `candidate_variant` exista en el `ai_filtered_portfolio_NNNNNN` apuntado por `related_record_id`, ni que `requires_advisor_override=True`. `/advisor/portfolio-selection` no verifica que `selected_variant` sea candidato real ni que el override aprobado sea coherente con la selección.
- **Conciliación dominio ↔ API:** `human_layer.override_approval.AdvisorOverrideApproval` tiene un contrato más estricto (enums, comment ≥ 20 chars, validación contra `PortfolioVariantMetadata` viva) que los schemas API de Fase 1 (rationale ≥ 1 char, sin live metadata). Cuando el override se dispare desde dentro de un workflow corriendo (no como "registro post-mortem"), unificar.
- **Endpoints de retrieval:** `GET /advisor/profile-approval/{record_id}`, `GET /advisor/override-approval/{record_id}`, `GET /advisor/portfolio-selection/{record_id}` + listing por `client_id`.
- **Integración con AuditTrail:** las acciones del asesor (`profile-approval`, `override-approval`, `portfolio-selection`) aún no quedan como eventos en el `AuditTrail` del workflow principal. Solo se persisten como records SQLite independientes.
- ~~**RBAC por rol:** actualmente cualquier token demo (advisor o compliance) puede registrar cualquier decisión. Fase 2: restringir endpoints de decisión a `roles=["advisor"]`; compliance solo retrieval.~~ → **✅ Cerrado.** `require_roles("advisor", "admin")` aplicado a los tres `/advisor/*`. Compliance/viewer → 403 genérico. Ver sección "Fase 2 — RBAC enforcement".
- **Firma digital:** `rationale` es texto libre sin firma criptográfica ni identificación verificada del asesor. Para piloto productivo: JWT con identidad del IdP propagada al record.

---

## Supuestos críticos en config YAML — Fase 1.6 ✅

### Estado actual

Los siguientes supuestos que antes vivían como literales Python ahora se cargan desde YAMLs versionables:

| Antes (hardcoded) | Ahora |
|---|---|
| `rules_layer.risk_budget_builder.PROFILE_BASE_PARAMS` (dict literal) | Cargado desde `config/risk_profiles.yaml` vía `config_layer.risk_assumptions.get_default_risk_profile_params()`. La constante `PROFILE_BASE_PARAMS` sigue exportándose (re-bind del loader) para no romper imports. |
| `rules_layer.goal_feasibility.DEFAULT_ACHIEVABLE_RETURNS` (dict literal) | Cargado desde `config/achievable_returns.yaml` vía `config_layer.risk_assumptions.get_default_achievable_returns()`. La constante `DEFAULT_ACHIEVABLE_RETURNS` sigue exportándose. |

Cero cambios numéricos: tests de regresión (`test_PROFILE_BASE_PARAMS_re_exports_loader_values`, `test_DEFAULT_ACHIEVABLE_RETURNS_re_exports_loader_values`) verifican identidad punto-a-punto vs los valores anteriores.

### Beneficios

- Una firma puede revisar/versionar los supuestos críticos en code review sin tocar Python.
- Git history del archivo YAML documenta cuándo y por qué cambiaron los supuestos (vs. un commit que tocaba lógica + supuestos mezclados).
- Validación estricta del schema al inicio del proceso: si el YAML está mal, el módulo falla con `ValueError` claro en lugar de degradar silenciosamente con valores `None` / vacíos.

### Limitaciones aceptadas (no es un sistema de CMA)

- **No reemplaza un proceso CMA formal.** Sigue siendo un demo. Cambios al YAML no pasan por validación de un comité de inversiones automatizada — depende del proceso de la firma alrededor de git/PRs.
- **No hay firma criptográfica de los YAMLs.** Cualquiera con write access al repo puede cambiar los valores. Para piloto productivo: branch protection + required reviewers.
- **No hay versioning explícito de los YAMLs.** No incluyen `schema_version`. Si la lista de campos requeridos cambia, hay que coordinar update del loader y del YAML en el mismo PR. Mientras el set sea fijo (los 11 campos actuales), no es un problema.
- **`min_liquidity` y `preferred_currency` en el YAML son contractuales pero no efectivos.** El `RiskBudgetBuilder` los OVERRIDE-EA con `kyc.liquidity_need_pct` y `kyc.preferred_currency` respectivamente. Quedan en el YAML por completitud para futuras revisiones donde el perfil pueda imponer un piso/moneda.

### Próximos pasos opcionales

1. **`schema_version` en cada YAML** + check explícito en el loader — útil cuando la lista de campos crezca o cambie semántica.
2. **`config/cma/<year>/...`** estructura por año cuando exista un CMA real con vencimiento.
3. **Override por env var** para entornos de QA: `RISK_FIRST_ADVISORY_CONFIG_DIR` → permitir apuntar a otro directorio de config sin tocar código.
4. **Hash/checksum del YAML logueado al inicio** de la API — para auditoría posterior de "qué supuestos estaba usando el sistema cuando se generó esta cartera".

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

---

## Fase 2 — Infraestructura de migrations y schema base ✅ (sin wiring de API)

### Estado actual

Primer commit de Fase 2 — solo infraestructura de DB, **sin endpoints ni repositorios todavía**.

- **`scripts/migrate.py`** — runner SQLite stdlib. Descubre `.sql` bajo `migrations/`, los aplica en orden lexicográfico, cada uno dentro de su propia transacción manual (`BEGIN` + statements + `INSERT INTO schema_migrations` + `COMMIT`/`ROLLBACK`). Idempotente vía la tabla `schema_migrations(version PK)`. Activa `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`. Acepta `--db-path` y `--migrations-dir`.
- **`scripts/backup_db.py`** — usa `VACUUM INTO` para producir copia compacta en `data/backups/YYYYMMDD_HHMMSS/`. Online-safe (respeta WAL).
- **`migrations/0001_phase2_core_schema.sql`** — crea las 6 tablas core de Fase 2: `firms`, `advisors`, `clients`, `advisory_cases`, `audit_events`, `ai_request_logs`, con todos los índices declarados en el diseño. **No toca** `records` / `counters` (de `SQLitePersistenceStore`).
- **`tests/unit/test_migrations.py`** — 25 tests cubriendo: aplicación sobre DB vacía, idempotencia (3 corridas), preservación de records legacy preexistentes, coexistencia con `SQLitePersistenceStore.init_schema()` en ambos órdenes, FK enforcement (3 escenarios), UNIQUE(case_id, sequence) en audit_events, presencia de los 10 índices declarados, `--db-path` por función y por CLI, edge cases (dir vacío / inexistente), atomicidad ante migration inválida.

### Garantías que esto da

| Garantía | Cómo se sostiene |
|---|---|
| **Aditiva** — no modifica records/counters existentes | Test `test_migration_preserves_preexisting_legacy_records` inserta un record vía `SQLitePersistenceStore`, corre la migración, verifica que el record sigue presente con payload idéntico. |
| **Idempotente** — re-ejecutar es seguro | Versión registrada en `schema_migrations`. Test `test_idempotent_run_does_not_duplicate_schema_migrations_rows` corre 3 veces y verifica COUNT = 1. |
| **Atómica por archivo** — fallo a mitad ⇒ ROLLBACK total | `_apply_migration` envuelve en transacción manual con `isolation_level=None`. Test `test_invalid_migration_does_not_partially_apply` confirma que una tabla intermedia no sobrevive el ROLLBACK. |
| **Orden estable** | `sorted(migrations_dir.glob("*.sql"))` por nombre. Convención `NNNN_descripcion.sql`. |
| **FK enforcement disponible** | El runner activa `PRAGMA foreign_keys=ON`; SQLitePersistenceStore también lo hace. Apps nuevas deben replicar el PRAGMA per-connection (es la semántica SQLite, no un bug del runner). |

### Lo que NO está en este commit (queda para los siguientes)

- Ningún endpoint nuevo. `main.py` intacto.
- Ningún repositorio nuevo. La capa `persistence_layer` no ganó archivos.
- Ningún modelo de dominio nuevo (`Firm`, `Advisor`, `Client`, `AdvisoryCase` no existen como Python).
- El auth scaffold no se tocó.
- El frontend no se tocó.
- `data/demo_api.db` no se migra automáticamente al arrancar la API — hay que correr `python scripts/migrate.py` manualmente. La integración API-side queda para una tarea posterior (probablemente un evento de startup de FastAPI).

### Decisiones de diseño documentadas

1. **`schema_migrations` no es la migración 0000.** Es metadata creada con `CREATE TABLE IF NOT EXISTS` antes de aplicar cualquier `.sql`. Esto evita el huevo-y-la-gallina de "necesito una tabla para registrar que tengo tablas".
2. **No se usa `executescript()` para las migraciones.** Su semántica de transacción es opaca (commit implícito al inicio y al final). El runner splittea SQL por `;` (estrictamente: tras stripear comentarios `--`), ejecuta cada statement con `conn.execute()` dentro de una transacción manual. Limitación documentada: NO maneja `;` dentro de string literals — nuestras migraciones no los contienen.
3. **Index explícito sobre `(case_id, sequence)` además del implícito de `UNIQUE(case_id, sequence)`.** Costo mínimo, intención explícita.
4. **`booleans → INTEGER 0/1`.** Convención SQLite estándar (no `BOOLEAN`, que en SQLite es alias de NUMERIC).
5. **Timestamps como `TEXT` ISO-8601 UTC con sufijo `Z`.** Alineado con `SQLitePersistenceStore._now_utc`. No se usa `INTEGER unix epoch` para mantener la legibilidad humana en consultas ad-hoc.

### Pendiente / próximos commits de Fase 2

1. ~~Tokens de advisor configurables (YAML/env, no hard-coded).~~ ✅ Commit 2.
2. ~~RBAC enforcement en endpoints `/advisor/*` existentes.~~ ✅ Commit 3.
3. Repositorios `FirmRepository` / `AdvisorRepository` / `ClientRepository` + endpoints CRUD.
4. `AdvisoryCase` repo + FSM mínima + endpoints `/cases/*`.
5. AuditEvent recorder con hash chain + endpoint `/cases/{id}/audit/verify`.
6. AIRequestLog wrapper alrededor de `OpenAIProfileClient` + redaction de PII.
7. Auto-migrate en startup de FastAPI (opcional, behind feature flag).

### Cómo migrar la DB de desarrollo actual

```powershell
# Backup primero
python scripts/backup_db.py --db-path data/demo_api.db
# Aplicar
python scripts/migrate.py --db-path data/demo_api.db
# Re-ejecutar para verificar idempotencia
python scripts/migrate.py --db-path data/demo_api.db
```

Si la DB tiene records existentes de Fase 0/1 (workflows, reports, advisor_*_approval), todos sobreviven.

---

## Fase 2 — Advisor tokens configurables ✅ (sin JWT, sin RBAC)

### Estado actual

Segundo commit de Fase 2 — los advisor tokens dejan de vivir hardcoded en `api_layer/auth.py` y pasan a resolverse desde un loader auditable + fallback dev-only.

- **`config/advisor_tokens.yaml.example`** — plantilla commiteada con los dos tokens demo (`dev-advisor-token` / `dev-compliance-token`). Documenta el schema y la política de uso.
- **`config/advisor_tokens.yaml`** — **gitignored**. Es donde el operador pone los tokens reales del entorno (dev local, staging, etc.). Si no existe, el sistema cae al fallback.
- **`src/risk_first_advisory/config_layer/advisor_tokens.py`** — loader nuevo. Expone:
  - `load_advisor_tokens(path: Path | str | None = None)` — loader puro de UN archivo. Sin fallback. `path=None` usa `DEFAULT_ADVISOR_TOKENS_PATH`.
  - `get_default_advisor_tokens()` — orquesta la cadena de fallback:
    1. ENV var `ADVISOR_TOKENS_FILE` (si está set y no vacío después de strip).
    2. `config/advisor_tokens.yaml` (si existe).
    3. Fallback dev-only hardcoded (mismos tokens que antes vivían en `auth.py`).
  - Validación estricta: top-level `tokens` dict, campos requeridos por entrada, roles ∈ `{advisor, compliance, admin, viewer}`, rechaza bool donde se espera str, rechaza campos desconocidos (fail-loud).
- **`src/risk_first_advisory/api_layer/auth.py`** — `_DEMO_TOKENS` removido. `_lookup_advisor(token)` ahora consulta `get_default_advisor_tokens()` en cada llamada y arma `AdvisorIdentity` desde el dict. `AdvisorIdentity` y los `Depends(...)` no cambian de contrato.
- **`tests/unit/test_advisor_tokens_config.py`** — 43 tests cubriendo: load explicit, default path, fallback dev-only, env var override, env var con archivo malformado, schema rejection top-level y por entry, todos los roles permitidos, defensa contra mutación del fallback, el `.example` parsea y matchea el fallback.
- **`tests/integration/test_api_auth.py`** — 37 tests (30 originales sin cambios + 7 nuevos). El autouse fixture nuevo aísla cada test del entorno local (elimina env var, redirige `DEFAULT_ADVISOR_TOKENS_PATH` a una ruta inexistente). El bloque nuevo `TestAuthMeCustomTokenFile` valida el reemplazo completo del fallback cuando el env var apunta a un archivo custom; `TestAuthMeMalformedConfigFile` valida que una config rota produzca 500 (no 401 silente).

### Resolución de orden visual

```
get_default_advisor_tokens()
    │
    ├── env var ADVISOR_TOKENS_FILE set & non-empty?
    │     ├── YES → load_advisor_tokens(env_path)  ← schema-validated
    │     │           ├── ok → return tokens (fallback NO se mergea)
    │     │           ├── ValueError → propaga (FastAPI → 500)
    │     │           └── FileNotFoundError → propaga (FastAPI → 500)
    │     └── NO  → siguiente paso
    │
    ├── config/advisor_tokens.yaml existe?
    │     ├── YES → load_advisor_tokens(default_path)  ← schema-validated
    │     │           └── (mismo manejo de errores)
    │     └── NO  → siguiente paso
    │
    └── fallback dev-only hardcoded
          └── return copy de _DEV_ONLY_FALLBACK_TOKENS
```

### Garantías

| Garantía | Cómo se sostiene |
|---|---|
| **Backward compatible**: los demos y tests siguen funcionando con `dev-advisor-token` / `dev-compliance-token` | Fallback dev-only vive en el loader y se usa cuando no hay env var ni archivo. Los 30 tests de integración originales pasan sin tocarlos. |
| **Reemplazo completo** (no merge) entre file y fallback | `get_default_advisor_tokens` retorna AS-IS lo que devuelve el loader. Tests `test_dev_advisor_token_does_not_resolve_when_env_set` y `test_dev_compliance_token_does_not_resolve_when_env_set` lo confirman. |
| **No cache**: cambios de env entre requests aplican inmediatamente | Cada `/auth/me` (o cualquier endpoint con `Depends(get_current_advisor_*)`) re-resuelve. Costo despreciable a escala piloto (1–3 advisors). |
| **Fail-loud** ante config rota | YAML inválido / FileNotFound del env-var-path / schema rejection → ValueError o FileNotFoundError propagan hasta FastAPI → 500. Tests `TestAuthMeMalformedConfigFile` lo verifican. |
| **No filtra tokens en errores** | `_validate_token_entry` NO incluye el valor del token en los mensajes (sólo el contexto del archivo + campo problemático). `_lookup_advisor` usa el mensaje genérico de auth.py. |
| **Defensa contra mutación del fallback** | El fallback retorna copia profunda por llamada. Test `test_mutating_returned_dict_does_not_affect_next_call` lo verifica. |

### Decisiones de diseño

1. **Loader devuelve dicts simples, no `AdvisorIdentity`** — evita el ciclo de imports `config_layer ↔ api_layer`. El builder a `AdvisorIdentity` vive en `auth.py` (`_identity_from_entry`).
2. **No hay cache** — la simplicidad gana sobre la perf en este punto. Si una sola lectura de YAML por request se vuelve perceptible (1000s req/s), se agrega `functools.lru_cache` después.
3. **Política de campos desconocidos: fail-loud** — un typo como `advisor-id` (con guión) sería silenciosamente ignorado si aceptáramos extras. Mejor romper al arrancar que servir un identity malformado.
4. **Rechazar `bool` donde se espera `str`** — `isinstance(True, int)` es `True` en Python; sin guard explícito, `advisor_id: true` parsearía. El loader replica el mismo patrón `_assert_not_bool` que ya usa `risk_assumptions.py`.
5. **`firm_id` admite `null` o string no vacío** — mantiene compatibilidad con el fallback dev-only (que tiene `firm_id=None`) sin abrir la puerta a strings vacíos por accidente.
6. **Roles whitelist en `ALLOWED_ROLES = {advisor, compliance, admin, viewer}`** — fija el vocabulario de Fase 2. Cualquier role nuevo requiere agregarse explícitamente al frozenset, lo que aparece en el diff y obliga a discutirlo.
7. **Env var `ADVISOR_TOKENS_FILE`** (no `ADVISOR_TOKENS_PATH`) — alineado con otras convenciones tipo `OPENAI_API_KEY` / `LOG_FILE`. Vacío o whitespace = "no set" para evitar trampas con `export X=""` en shell scripts.
8. **Autouse fixture en `test_api_auth.py`** — los integration tests se aíslan del entorno local. Esto vale más que la elegancia de "tests no necesitan fixture": sin ese fixture, un dev con `config/advisor_tokens.yaml` local rompería los 30 tests originales.
9. **`config/advisor_tokens.yaml` está en `.gitignore`** — solo el `.example` se commitea. Análogo a `.env.example`.

### Lo que NO está en este commit

- **JWT / firma criptográfica de tokens** — sigue siendo opaque string ↔ identity lookup. La rotación, expiración y firma quedan para Fase 2.5 (siguiente paso del diseño Opus).
- ~~**RBAC enforcement**~~ ✅ `require_roles("advisor", "admin")` aplicado a los tres `/advisor/*` en Commit 3. Ver sección "Fase 2 — RBAC enforcement".
- **Multi-tenant real** — `firm_id` viaja en la identity, pero ningún endpoint filtra recursos por `firm_id`. Llega con las entidades de Fase 2 (Client/AdvisoryCase).
- **Persistencia de tokens en la nueva tabla `advisors`** — el loader sigue siendo file-backed. Cuando exista `AdvisorRepository`, los tokens van a salir de DB; el loader YAML pasará a ser una forma de seed inicial.
- **Auto-creación de `config/advisor_tokens.yaml` desde `.example`** — el operador lo hace manualmente. Un script de bootstrap puede llegar después.

---

## Fase 2 — RBAC enforcement en endpoints `/advisor/*` ✅ (Commit 3)

### Estado actual

Tercer commit de Fase 2 — solo los roles `advisor` y `admin` pueden ejecutar actos formales del asesor. Compliance y viewer reciben 403.

- **`src/risk_first_advisory/api_layer/auth.py`** — cambios:
  - `_raise_401() -> None` → `_raise_401() -> NoReturn` (anotación correcta; habilita narrowing de tipo).
  - `_RBAC_ERROR_DETAIL: str` — constante genérica `"Advisor role is not authorized for this action."`. Nunca revela qué roles se requerían ni cuáles tiene el caller.
  - `require_roles(*allowed_roles: str)` — factory de dependencias FastAPI. Recibe uno o más roles permitidos; devuelve un callable que: (1) extrae y valida el Bearer token → 401 si falta/inválido, (2) resuelve identidad vía `_lookup_advisor`, (3) comprueba que `any(r in allowed for r in identity.roles)` → 403 si ningún rol coincide. `require_roles()` sin argumentos levanta `ValueError` en tiempo de definición del endpoint.
  - `get_current_advisor_required` — sin cambios de contrato; sigue siendo la dependencia de `/auth/me` (que acepta cualquier token válido sin filtrar por rol).

- **`src/risk_first_advisory/api_layer/main.py`** — tres endpoints actualizados:
  - `POST /advisor/profile-approval`: `Depends(get_current_advisor_required)` → `Depends(require_roles("advisor", "admin"))`
  - `POST /advisor/override-approval`: ídem
  - `POST /advisor/portfolio-selection`: ídem

- **`tests/integration/test_api_auth.py`** — `TestAdvisorRBACEnforcement` añadida (21 tests): compliance → 403 en los tres endpoints, 403 genérico, no echo de token, 401 sin token, viewer (YAML custom) → 403, admin (YAML custom) → 200 en los tres endpoints.

- **`tests/integration/test_api_advisor_profile_approval.py`**:
  - Añadido autouse fixture `_isolate_advisor_tokens_env` (mismo patrón que `test_api_auth.py`).
  - `test_compliance_token_is_accepted` → `test_compliance_token_returns_403` (403 + detalle genérico).
  - `TestAdvisorProfileApprovalRBAC` añadida (4 tests: viewer → 403, admin → 200, no echo, 401 ≠ 403).

- **`tests/integration/test_api_advisor_override_approval.py`**: mismo patrón.

- **`tests/integration/test_api_advisor_portfolio_selection.py`**: mismo patrón.

**Total tests tras este commit:** 2359 (todos pasando).

### Tabla de RBAC

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `POST /advisor/profile-approval` | ✅ 200 | ✅ 200 | ❌ 403 | ❌ 403 | ❌ 401 |
| `POST /advisor/override-approval` | ✅ 200 | ✅ 200 | ❌ 403 | ❌ 403 | ❌ 401 |
| `POST /advisor/portfolio-selection` | ✅ 200 | ✅ 200 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /auth/me` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |
| `GET /health` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 |
| `/ai/*`, `/universe/*` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 |

### Decisiones de diseño

1. **Factory function, no decorator** — `require_roles("advisor", "admin")` retorna un callable que FastAPI inspecciona vía `Depends()`. La alternativa (un decorator `@require_roles`) no se integra limpiamente con el sistema de inyección de dependencias de FastAPI.
2. **frozenset interno para `allowed`** — evita recalcular la intersección por request; la cobertura `any(r in allowed ...)` es O(k) con k = roles del usuario (típicamente 1–3), no O(roles * allowed).
3. **Mismo 403 detail siempre** — `"Advisor role is not authorized for this action."` no varía según el rol del caller ni según los roles requeridos. Evita information leakage de la estructura de permisos.
4. **authn precede a authz** — token ausente/inválido → 401 (con `WWW-Authenticate: Bearer`). Solo si el token es válido se evalúa la lógica de roles → 403 si insuficiente. No existe un camino que devuelva 403 sin haber resuelto una identidad válida.
5. **`require_roles()` sin args → ValueError en startup** — se detecta como error de programación en tiempo de definición del endpoint (cuando FastAPI registra la ruta), no en el primer request que lo llama.
6. **Isolation fixture autouse en los tres archivos de test** — garantiza que los tests no se contaminen con `config/advisor_tokens.yaml` local del dev. El mismo patrón que `test_api_auth.py` desde Commit 2.
7. **`_raise_401` → `NoReturn`** — corrección de anotación (la función siempre levanta `HTTPException`; `-> None` era incorrecto). Con `NoReturn`, mypy entiende el narrowing `if token is None: _raise_401()` y no requiere `# type: ignore`.

### Lo que NO está en este commit

- **Retrieval endpoints con RBAC** — `GET /advisor/*/...` no existen todavía. Cuando se implementen: compliance → solo lectura, advisor/admin → lectura + escritura.
- **JWT / firma criptográfica** — sigue siendo opaque string lookup.
- **Multi-tenant por `firm_id`** — `require_roles` no filtra por `firm_id`. Un advisor de la firma A podría leer registros de la firma B si no hay filtro adicional. Eso llega con `ClientRepository` + `AdvisoryCase`.
- **Roles compuestos** — un advisor con `roles=["advisor", "admin"]` pasa `require_roles("advisor")` y `require_roles("admin")` igual. No hay jerarquía implícita; cada endpoint declara sus roles explícitamente.

---

## Fase 2 — Entidades core: Firm, Advisor, Client ✅ (Commit 4)

### Estado actual

Cuarto commit de Fase 2 — repositorios SQLite, schemas Pydantic y endpoints CRUD para las tres entidades core.

#### Archivos creados / modificados

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — nuevo. Implementa:
  - `EntityNotFoundError` / `EntityConflictError` — excepciones propias (no dependen de `RepositoryError`).
  - `SQLiteEntityStore` — connection manager análogo a `SQLitePersistenceStore`. Activa `PRAGMA foreign_keys=ON` y `journal_mode=WAL`. Llama a `_bootstrap_counters()` (idempotente `CREATE TABLE IF NOT EXISTS counters`) para que el `counters` compartido exista aunque `SQLitePersistenceStore.init_schema()` no se haya llamado todavía.
  - `_next_id(prefix)` — mismo patrón que en `SQLitePersistenceStore` (`INSERT OR IGNORE` + `UPDATE` + `SELECT next_val - 1`). Genera `firm_000001`, `advisor_000001`, `client_000001`.
  - `SQLiteFirmRepository` — CRUD sobre tabla `firms`. `create()` lanza `EntityConflictError("firm_id already exists: ...")` en PK collision.
  - `SQLiteAdvisorRepository` — CRUD sobre tabla `advisors`. `roles` se serializa como JSON array en `roles_json TEXT`. FK violations (firm_id no existe) propagan el mensaje SQLite raw.
  - `SQLiteClientRepository` — CRUD sobre tabla `clients`. Nota: la validación cross-firm (advisor pertenece a la misma firma que el client) NO es responsabilidad del repositorio — la hace el endpoint.

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con:
  - `FirmCreateRequest` / `FirmResponse` / `FirmListResponse`
  - `AdvisorCreateRequest` / `AdvisorResponse` / `AdvisorListResponse`
  - `ClientCreateRequest` / `ClientResponse` / `ClientListResponse`
  - `_ALLOWED_ENTITY_ROLES: frozenset` — whitelist de roles válidos para advisors.
  - Validators: `firm_id` / `advisor_id` / `client_id` no pueden ser strings vacíos o whitespace si se proveen; `country`, `email`, `jurisdiction`, `preferred_currency` no pueden ser whitespace-only; `roles` valida contra `_ALLOWED_ENTITY_ROLES`.

- **`src/risk_first_advisory/api_layer/main.py`** — 12 endpoints nuevos:

  | Endpoint | RBAC | Descripción |
  |---|---|---|
  | `POST /firms` | admin | Crea firma; 409 en PK collision |
  | `GET /firms` | any token | Lista todas las firmas |
  | `GET /firms/{firm_id}` | any token | Detalle de firma; 404 si no existe |
  | `POST /advisors` | admin | Crea advisor; 422 en FK violation; 409 en PK |
  | `GET /advisors` | any token | Lista todos los advisors |
  | `GET /advisors/{advisor_id}` | any token | Detalle; 404 |
  | `GET /firms/{firm_id}/advisors` | any token | Advisors de la firma; 404 si firma no existe |
  | `POST /clients` | admin, advisor | Crea client con validación cross-firm; 422/409 |
  | `GET /clients` | any token | Lista todos los clients |
  | `GET /clients/{client_id}` | any token | Detalle; 404 |
  | `GET /firms/{firm_id}/clients` | any token | Clients de la firma; 404 si firma no existe |
  | `GET /advisors/{advisor_id}/clients` | any token | Clients del advisor; 404 si advisor no existe |

- **`tests/integration/test_api_entities.py`** — 54 tests nuevos organizados en 6 clases:
  - `TestCreateFirm` (10 tests): 201 + shape + auto-id + explicit-id + echo + 409 + 401 + 403×3.
  - `TestListGetFirm` (6 tests): empty list + populated + 401 + get-200 + 404 + 401.
  - `TestCreateAdvisor` (9 tests): 201 + shape + auto-id + echo + FK-422 + 409 + 401 + 403×2.
  - `TestListGetAdvisor` (7 tests): empty + populated + get-200 + 404 + firm-filter + firm-404 + 401.
  - `TestCreateClient` (11 tests): admin-201 + advisor-201 + shape + defaults + auto-id + cross-firm-422 + advisor-404-422 + dup-409 + 401 + 403×2.
  - `TestListGetClient` (9 tests): empty + populated + get-200 + 404 + firm-filter + firm-404 + advisor-filter + advisor-404 + 401.
  - `TestNoRegression` (2 tests): `/health` y `/auth/me` no rotos.

**Total tests tras este commit:** 2413 (todos pasando). Δ = +54.

#### Setup de tests

Los tests usan dos autouse fixtures:
- `_setup_entity_test_env` — aísla tokens (mismo patrón que otros archivos de integración) y activa los 4 tokens de test (admin, advisor, compliance, viewer) con `firm_id: null`.
- `entity_db` — crea la DB temporal, corre `migrate.run(db_path, _MIGRATIONS_DIR)` para crear las tablas de entidades, y redirige `DEFAULT_DB_PATH`. El módulo `migrate` se importa vía `importlib.util.spec_from_file_location` (mismo patrón que `test_migrations.py`).

#### Decisiones de diseño

1. **`SQLiteEntityStore` separado de `SQLitePersistenceStore`** — evita acoplar la capa legacy (records/counters) con la capa de entidades. Ambos stores pueden coexistir en el mismo archivo SQLite; el `counters` se comparte sin conflicto.
2. **`_bootstrap_counters()` en `__init__`** — garantiza que `counters` existe aunque nadie haya llamado a `SQLitePersistenceStore.init_schema()`. Idempotente (`CREATE TABLE IF NOT EXISTS`).
3. **Validación cross-firm en el endpoint, no en el repositorio** — el repositorio solo conoce su propia tabla. La lógica de negocio ("el advisor debe pertenecer a la misma firma que el client") es responsabilidad de la capa API. Esto mantiene el repositorio simple y reutilizable.
4. **PK collision → 409, FK violation → 422** — se distinguen inspeccionando el mensaje SQLite: `"UNIQUE constraint"` → 409; cualquier otro `IntegrityError` → 422. Para `firms` se usa el mensaje propio `"firm_id already exists"` (más legible); para `advisors` y `clients` se reutiliza el mensaje SQLite directamente.
5. **`status_code=201` en los tres POST de creación** — más correcto semánticamente que 200. Los tests verifican 201.
6. **GET endpoints usan `get_current_advisor_required` (cualquier token válido)** — no se aplica RBAC por rol a la lectura; todos los roles autenticados pueden ver entidades. Si se necesita RBAC de lectura en el futuro, se puede añadir sin romper contratos existentes.
7. **`migrate.run(verbose=False)` en tests** — suprime el output de progreso de las migraciones para no contaminar los logs de pytest.

### Tabla de RBAC actualizada (todos los endpoints protegidos)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `POST /firms` | ❌ 403 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /firms`, `GET /firms/{id}` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |
| `POST /advisors` | ❌ 403 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /advisors`, `GET /advisors/{id}`, `GET /firms/{id}/advisors` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |
| `POST /clients` | ✅ 201 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /clients`, `GET /clients/{id}`, `GET /firms/{id}/clients`, `GET /advisors/{id}/clients` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |
| `POST /advisor/profile-approval` | ✅ 200 | ✅ 200 | ❌ 403 | ❌ 403 | ❌ 401 |
| `POST /advisor/override-approval` | ✅ 200 | ✅ 200 | ❌ 403 | ❌ 403 | ❌ 401 |
| `POST /advisor/portfolio-selection` | ✅ 200 | ✅ 200 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /auth/me` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |
| `GET /health` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 |

### Pendiente / próximos commits de Fase 2

1. ~~Tokens de advisor configurables (YAML/env, no hard-coded).~~ ✅ Commit 2.
2. ~~RBAC enforcement en endpoints `/advisor/*` existentes.~~ ✅ Commit 3.
3. ~~Repositorios `FirmRepository` / `AdvisorRepository` / `ClientRepository` + endpoints CRUD.~~ ✅ Commit 4.
4. ~~`AdvisoryCase` repo + FSM mínima + endpoints `/cases/*`.~~ ✅ Commit 5.
5. ~~AuditEvent recorder con hash chain + endpoint `/cases/{id}/audit/verify`.~~ ✅ Commit 6.
6. ~~AIRequestLog wrapper alrededor de los endpoints `/ai/*` + redaction de PII.~~ ✅ Commit 7.
7. ~~KYCSubmission case-scoped (POST/GET `/cases/{case_id}/kyc`) + auto-event `kyc_submitted` + transición DRAFT → IN_PROGRESS.~~ ✅ Commit 8.
8. ~~AIProfileAnalysis case-scoped (POST/GET `/cases/{case_id}/ai/profile-analysis`) sobre la última KYC; vincula `ai_request_log_id`; auto-event `ai_profile_analyzed`.~~ ✅ Commit 9.
9. ~~CaseAdvisorProfileApproval case-scoped (POST/GET `/cases/{case_id}/profile-approval`); vincula `ai_profile_analysis_id` + `kyc_submission_id` + `advisor_id`; mantiene `is_current` + `current_approved_profile_id`; auto-events `advisor_profile_approved` / `_modified` / `_rejected`.~~ ✅ Commit 10.
10. ~~CaseInvestmentPreference + CaseUniverseFilterRun case-scoped (POST/GET `/cases/{case_id}/investment-preferences`, POST/GET `/cases/{case_id}/universe-filter`); preferencias manuales o AI-extracted; filter engine sobre CSV; auto-events `investment_preferences_recorded` + `universe_filtered`; AIRequestLog cuando se usa IA.~~ ✅ Commit 11.
11. ~~CasePortfolioProposal case-scoped (POST/GET `/cases/{case_id}/portfolio-proposal`); reconstruye instrumentos desde el filter run, corre PortfolioGenerationCoordinator con RiskBudget del approved profile; persiste snapshot completo (risk_budget + snapshots + candidates + warnings + status); auto-event `portfolio_proposal_generated`.~~ ✅ Commit 12.
12. ~~CaseOverrideApproval case-scoped (POST/GET `/cases/{case_id}/override-approval`); ancla decisión a `(case_id, proposal_id, candidate_variant)`; valida que el candidate exista y requiera override; auto-events `advisor_override_approved` / `_rejected`.~~ ✅ Commit 13.
13. ~~CasePortfolioSelection case-scoped (POST/GET `/cases/{case_id}/portfolio-selection`); vincula proposal + override_approval cuando aplica; actualiza `current_portfolio_selection_id`; transiciona status a `PORTFOLIO_SELECTED`; auto-event `portfolio_selected`.~~ ✅ Commit 14.
14. ~~CaseReport case-scoped (POST/GET `/cases/{case_id}/reports`, GET `/cases/{case_id}/reports/{report_id}`); markdown determinístico vía `CaseMarkdownReportGenerator`; versionado monotónico por case_id; auto-event `report_generated`.~~ ✅ Commit 15.
15. ~~Case summary endpoint (`GET /cases/{id}/summary`) que devuelve case + firm/client/advisor + todos los `current_*` + audit integrity + AI logs count + workflow progress + next_recommended_action en un solo response.~~ ✅ Commit 16.
16. ~~Case workflow smoke check script (`scripts/run_case_workflow_smoke_check.py`) — candado de cierre de Fase 2. Valida end-to-end firm → … → report → summary → audit verify sin OpenAI ni uvicorn, en DB temporal.~~ ✅ Commit 17.
17. PDF rendering del case report (hoy solo markdown).
18. Case report branding (firm logo, colores, header customizable).
19. Lifecycle formal de reports (workflow draft → reviewed → final → sent, con AuditEvents de cada transición).
20. Frontend Case Workbench (UI que consume `/cases/{id}/summary` para hidratar la vista completa del caso sin múltiples round-trips).
15. Auto-migrate en startup de FastAPI (opcional, behind feature flag).
16. Integrar AuditEvent automáticamente en los demás endpoints decisorios legacy (`/advisor/profile-approval`, `/advisor/override-approval`, `/advisor/portfolio-selection`, `PATCH /cases/{id}/status`).
17. Firm-level access control sobre `/cases/*` (todos los sub-endpoints case-scoped).
18. AIRequestLog case-scoped por default en los endpoints `/ai/*` no case-scoped — hoy `case_id=None`; cuando esos endpoints sean case-scoped, propagar `case_id` automáticamente.
19. Cifrado at-rest del DB y retention / pruning policy para todas las tablas append-only.
20. Case-scoped AI profile follow-up (`analysis_type=follow_up`) — hoy reservado pero NO implementado (rechaza con 422).
21. Live market data provider para case-scoped flow (hoy portfolio-proposal y universe-filter usan el fixture CSV vía `source_universe="sample_instrument_universe.csv"`).
22. Deprecar / migrar el endpoint legacy `/advisor/profile-approval` (client-scoped, sin case linkage).
23. UI Case Workbench (frontend para flujo end-to-end por case).

---

## Fase 2 — AuditEvent hash chain ✅ (Commit 6)

### Estado actual

Sexto commit de Fase 2 — append-only audit log por `AdvisoryCase` con encadenamiento determinístico de hashes (SHA-256). Permite verificar integridad de la línea de tiempo sin secretos.

#### Archivos creados / modificados

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — ampliado con:
  - `_canonical_json(payload)` — serialización determinística (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`).
  - `compute_payload_hash(payload)` — SHA-256 hex digest del canonical JSON. Exportada para que tests y otros módulos puedan recomputar.
  - `compute_event_hash(*, previous_hash, sequence, event_type, actor_advisor_id, actor_role, created_at_utc, payload_hash)` — SHA-256 hex digest del dict canonical formado por la metadata + el hash del eslabón anterior. `previous_hash` y `actor_advisor_id` se mapean a `""` cuando son `None` para evitar ambigüedad entre `null` y empty string.
  - `SQLiteAuditEventRepository` — operaciones:
    - `append(*, case_id, event_type, actor_role, payload, actor_advisor_id=None)` → `dict`. Calcula sequence siguiente (MAX(sequence)+1 por case_id), determina `previous_hash`, computa `payload_hash` + `event_hash`, e inserta en `audit_events`. Lanza `EntityNotFoundError` si el case no existe, `EntityConflictError` en FK/UNIQUE violation.
    - `list_by_case(case_id)` → lista ordenada por `sequence ASC`.
    - `verify_chain(case_id)` → `dict` con `is_intact / total_events / first_broken_sequence / message`. Recomputa hashes de todos los eventos, valida que `sequence` sea `1..N` sin gaps y que `previous_hash` encadene con el `event_hash` anterior. Devuelve `is_intact=True / total_events=0` para casos sin eventos.
  - **No expone `update` ni `delete`** — el log es append-only.
  - IDs generados con prefijo `audit_event_` (formato `audit_event_000001`).

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con:
  - `AuditEventCreateRequest`: `event_type` (no whitespace), `actor_advisor_id` (opcional, no empty string si se provee), `actor_role` (no whitespace, default `"system"`), `payload: dict[str, Any] = {}`. Un validator `mode="before"` rechaza `payload` como `list`/`str`/`null` con 422.
  - `AuditEventResponse`: serializa todos los campos del evento incluyendo `payload` como dict, `payload_hash`, `previous_hash`, `event_hash` y `created_at_utc`.
  - `AuditEventListResponse`: `events: list[AuditEventResponse]` + `count: int`.
  - `AuditVerifyResponse`: `case_id`, `is_intact`, `total_events`, `first_broken_sequence`, `checked_at_utc` (UTC ISO-8601 generado por el endpoint), `message`.

- **`src/risk_first_advisory/api_layer/main.py`** — 3 endpoints nuevos + integración automática en `POST /cases`:

  | Endpoint | RBAC | Descripción |
  |---|---|---|
  | `POST /cases/{case_id}/audit-events` | advisor, admin | Crea audit event manual; 404 si case no existe; 422 si `actor_advisor_id` no existe como advisor entity |
  | `GET /cases/{case_id}/audit` | admin, advisor, compliance, viewer | Lista eventos ordenados por sequence asc |
  | `GET /cases/{case_id}/audit/verify` | admin, compliance | Recomputa hashes + valida cadena → `AuditVerifyResponse` |

  Además:
  - `POST /cases` ahora genera automáticamente un evento `case_created` (sequence 1) con `payload` que contiene `case_id`, `firm_id`, `client_id`, `lead_advisor_id`, `status`, `title`.
  - Helper `_pick_actor_role(roles)` elige un rol single-valued para `actor_role` siguiendo prioridad `admin > advisor > compliance > viewer` (la tabla guarda un solo string).

- **`tests/integration/test_api_audit_events.py`** — 58 tests nuevos organizados en 8 clases:
  - `TestAutoCaseCreatedEvent` (10): POST /cases genera evento sequence 1 con `event_type=case_created`, `previous_hash=None`, `actor_role` y `actor_advisor_id` correctos, payload con metadata del case, `payload_hash` recomputable.
  - `TestAppendAuditEvent` (6): segundo evento con sequence 2, `previous_hash == first.event_hash`, orden por sequence asc, `event_id` con prefijo `audit_event_`, payload round-trip, payload vacío permitido.
  - `TestHashDeterminism` (4): `payload_hash` = `sha256(canonical)`, mismo payload con keys reordenadas → mismo hash, payloads distintos → event_hashes distintos, `event_hash` recomputable vía `compute_event_hash`.
  - `TestVerifyChain` (7): intact con 1 / N eventos, mutar `payload_json` directamente en DB → `is_intact=False`, mutar `previous_hash` → false, borrar evento medio (gap) → false con `first_broken_sequence` correcto, response incluye `checked_at_utc`.
  - `TestRBACAppend` (5): 401 / 403 (compliance, viewer) / 201 (advisor, admin).
  - `TestRBACVerify` (5): 403 (advisor, viewer) / 200 (admin, compliance) / 401 sin token.
  - `TestRBACList` (5): 401 sin token / 200 para todos los roles válidos.
  - `TestValidation` (11): case no existe (3 endpoints) → 404; `event_type`/`actor_role` vacíos o whitespace → 422; `payload` como list/string/null → 422; `actor_advisor_id` inexistente → 422; `actor_advisor_id` omitido → 201.
  - `TestNoRegression` (4): `/health`, `/auth/me`, `/advisor/profile-approval`, `/ai/filtered-portfolio-demo` siguen funcionando con la misma política de auth.

**Total tests tras este commit:** 2521 (todos pasando). Δ = +58.

#### Decisiones de diseño

1. **Append-only sin update/delete** — `SQLiteAuditEventRepository` no expone API para mutar eventos. Cualquier mutación pasa por SQL directo (fuera del scope del repositorio).
2. **Sequence calculado en write-time, no via AUTOINCREMENT** — `MAX(sequence)+1` por case_id en la misma transacción del insert. La tabla mantiene `UNIQUE(case_id, sequence)` como guard rail; un race condition extremo entre dos appends concurrentes del mismo case se traduce en `EntityConflictError` (UNIQUE violation) que el endpoint mapea a 409.
3. **Hash chain por case, no global** — cada `case_id` tiene su propia secuencia 1..N. No hay "merkle root" inter-case en Fase 2.
4. **Canonical JSON con `ensure_ascii=False`** — preserva caracteres unicode en su forma original (útil para advisor notes en español). El hash es estable porque `sort_keys=True` + `separators` fijos eliminan toda fuente de variabilidad.
5. **`None` se mapea a `""` en `compute_event_hash`** — evita la ambigüedad entre `{"previous_hash": null}` y `{"previous_hash": ""}` en el JSON canonical (ambos casos hashean al mismo resultado).
6. **Soft FK lookup para `actor_advisor_id` en el evento `case_created` automático** — el `advisor_id` del token (Phase 1 scaffold, p. ej. `dev-advisor-token` → `ADV-001`) no siempre coincide con un advisor entity (Phase 2). El endpoint hace `adv_repo.get(advisor.advisor_id)` antes del insert; si no existe, deja `actor_advisor_id=None` (FK-safe). La identidad queda igualmente capturada vía `actor_role`.
7. **`actor_advisor_id` explícito en POST audit-events requiere FK estricta** — si el caller pasa un `actor_advisor_id`, el endpoint exige que exista como advisor entity (422 si no). Política: las referencias colgadas no se aceptan en eventos manuales para mantener trazabilidad. Para "evento sin actor identificado" el caller debe omitir el campo (queda `None`).
8. **`actor_role` es single-valued** — la tabla `audit_events` tiene una columna `TEXT NOT NULL`. Cuando el token tiene roles compuestos (`["admin", "compliance"]`), `_pick_actor_role` elige uno por prioridad (`admin > advisor > compliance > viewer`). El advisor identity completo se preserva vía `auth.py`; el evento solo guarda el rol "activo" de la operación.
9. **`payload` validado como dict en el request** — Pydantic acepta cualquier shape por default; un `field_validator(mode="before")` rechaza list/str/null para evitar payloads ambiguos en el hash.
10. **Limitación documentada: case + audit no son atómicos en `POST /cases`** — el endpoint inserta primero el case (commit) y luego el audit event (otro commit). Si el audit falla (debería ser extremadamente raro: case acaba de existir, hashes determinísticos), el case queda sin su primer evento y el endpoint devuelve 500 con mensaje claro. Una iteración futura puede mover ambos a un `BEGIN ... COMMIT` manual.

#### Tabla de RBAC actualizada (nuevos endpoints AuditEvent)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `POST /cases/{id}/audit-events` | ✅ 201 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /cases/{id}/audit` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |
| `GET /cases/{id}/audit/verify` | ❌ 403 | ✅ 200 | ✅ 200 | ❌ 403 | ❌ 401 |

#### Lo que NO está en este commit

- **AuditEvent NO se integra todavía con `/advisor/profile-approval`, `/advisor/override-approval`, `/advisor/portfolio-selection`, `PATCH /cases/{id}/status`** — solo `POST /cases` registra evento automático. La integración completa queda para un commit siguiente.
- **Firm-level access control sobre `/cases/{id}/audit*`** — cualquier token con el rol adecuado puede leer/escribir audit events de cualquier case. El filtrado por `firm_id` queda pendiente.
- **AIRequestLog** se completa en Commit 7 (ver siguiente sección).
- **Acuse externo / firma digital** — el hash chain no es blockchain: un actor con acceso directo a SQLite puede reescribir coherentemente toda la cadena (incluyendo todos los `event_hash`). `verify_chain` detecta mutaciones puntuales (un payload, un hash, un sequence gap), no una reescritura completa coordinada. Para protección contra DBA malicioso haría falta firma asimétrica por evento o anclaje a una autoridad de timestamping externa.

---

## Fase 2 — AIRequestLog funcional ✅ (Commit 7)

### Estado actual

Séptimo commit de Fase 2 — logging trazable y append-only de cada llamada a IA, con redacción de PII y `input_hash` sobre el payload original para correlación sin exposición.

#### Archivos creados / modificados

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — ampliado con:
  - `ALLOWED_AI_LOG_STATUSES = {"parsed_ok", "parse_error", "validation_error", "api_error"}`.
  - `_AI_LOG_STRUCTURED_KEYS` (allowlist de campos no sensibles que se conservan en claro: scores, montos, `currency`, `country`, `entity`, `allowed_instrument_types`, `model`, `prompt_version`, etc.).
  - `_AI_LOG_REDACTED_KEYS` (denylist de campos siempre redactados: `natural_language_preferences`, `open_*`, `kyc_context`, `previous_profile_analysis`).
  - `_AI_LOG_FREE_TEXT_MIN_LEN = 80` — heurística defensiva: strings largos en claves NO whitelisted se redactan aunque no estén en denylist.
  - `_hash_short_client_id(value)` → `client_<sha256[:8]>`.
  - `_looks_like_api_key(value)` → heurística para detectar OpenAI keys (`sk-`, `sk_`, `pk-`), Bearer tokens y prefijos `api_key=`/`token=`.
  - `_redact_string(value)` → `<REDACTED:text_N_chars>`.
  - `_redact_value(key, value)` — recursivo (dict → recurse, list → redact each, str → policy, otros → conservar).
  - `redact_ai_input(payload)` — entrada pública: devuelve copia redactada (no muta el original); levanta `ValueError` si no es mapping.
  - `compute_input_hash(payload)` — SHA-256 hex digest del canonical JSON del **original** (no del redactado), para que dos inputs con el mismo texto libre tengan el mismo hash.
  - `SQLiteAIRequestLogRepository` con:
    - `create(...)` — inserta y devuelve dict. IDs `ai_request_000001`, ... . FK violation → `EntityConflictError`.
    - `get(request_id)` → dict | None.
    - `list_by_case(case_id)` — orden `created_at_utc ASC, request_id ASC`.
    - `list_all(limit=None)` — mismo orden, con LIMIT opcional.
    - Sin update ni delete (append-only).

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con:
  - `AIRequestLogResponse` (campos: `request_id`, `case_id`, `requested_by_advisor_id`, `endpoint`, `model`, `prompt_version`, `input_redacted`, `input_hash`, `raw_response`, `validation_status`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `error_message`, `created_at_utc`).
  - `AIRequestLogListResponse` (`logs`, `count`).
  - `AIRequestLogCreateRequest` con validators (`endpoint`/`model`/`prompt_version` no whitespace, `validation_status` ∈ allowlist, `latency_ms`/`prompt_tokens`/`completion_tokens` ≥ 0 si vienen, `input_payload` debe ser dict).

- **`src/risk_first_advisory/api_layer/main.py`** — agregado:
  - `_persist_ai_request_log(...)` helper que aplica `redact_ai_input` + `compute_input_hash` y persiste sin nunca propagar excepciones (fail-safe: logging failure no rompe el endpoint AI principal).
  - `_resolve_ai_model_name(client)` — best-effort getattr a `_model`.
  - Constantes `_AI_LOG_PROMPT_INVESTMENT_PREFS = "investment_preferences_v1"`, `_AI_LOG_PROMPT_FILTER_UNIVERSE = "ai_universe_filter_v1"`, `_AI_LOG_PROMPT_FILTERED_PORTFOLIO = "ai_filtered_portfolio_v1"`.
  - Integración automática en `/ai/investment-preferences`, `/ai/filter-universe-demo`, `/ai/filtered-portfolio-demo`: medición de `latency_ms` con `time.perf_counter`, `validation_status="parsed_ok"` en éxito y `"api_error"` en `ValueError`/`Exception`, con `error_message` poblado.
  - 4 endpoints nuevos:

  | Endpoint | RBAC | Descripción |
  |---|---|---|
  | `GET /admin/ai-logs` | admin, compliance | Lista todos los logs (query opcional `limit`, 0–1000) |
  | `GET /admin/ai-logs/{request_id}` | admin, compliance | Detalle de un log; 404 si no existe |
  | `GET /cases/{case_id}/ai-logs` | admin, compliance | Logs del caso; 404 si case no existe |
  | `POST /admin/ai-logs` | admin only | Creación manual con FK validation explícita; redacta el input antes de persistir |

- **`tests/unit/test_ai_request_log_redaction.py`** — 35 tests unitarios (sin DB):
  - `TestClientIdRedaction` (4): `client_id` → `client_<sha256[:8]>` determinístico.
  - `TestFreeTextRedaction` (7): `natural_language_preferences` / `open_*` / `kyc_context` (dict recursivo) redactados con longitud preservada.
  - `TestStructuredFieldsPreserved` (10): scores, amounts, currency, country, entity, instrument types, bools y None se mantienen en claro.
  - `TestSafetyNets` (8): keys `sk-...` y `Bearer ...` siempre redactadas (incluyendo dentro de dicts y lists anidados), strings largos en keys desconocidas redactados, no mutación del input, non-dict input levanta `ValueError`.
  - `TestInputHash` (6): SHA-256 hex; estable bajo reordenamiento de keys; cambia con el payload; computado sobre el ORIGINAL (no el redactado); maneja unicode.

- **`tests/integration/test_api_ai_request_logs.py`** — 38 tests de integración:
  - `TestRBACList` (5): 401/403 (advisor, viewer) / 200 (admin, compliance).
  - `TestRBACGet` (2): 404 cuando no existe; 403 para advisor.
  - `TestRBACCaseLogs` (4): compliance OK con count=0; advisor 403; sin token 401; case inexistente 404.
  - `TestPostManual` (11): admin crea OK; advisor/compliance 403; `validation_status` inválido 422; case/advisor FK violation 422; con case existente OK; endpoint vacío 422; latency negativa 422; `input_payload` no dict 422; input persistido está realmente redactado.
  - `TestAutoInvestmentPreferences` (8): log creado con endpoint/prompt_version correctos; `natural_language_preferences` no aparece en claro; `client_id` hasheado; `raw_response` capturado; contrato del endpoint intacto; `input_hash` cambia con el payload; `validation_status=api_error` cuando OpenAI falla; `latency_ms` poblado.
  - `TestAutoFilterUniverse` (1): log con `prompt_version=ai_universe_filter_v1`.
  - `TestAutoFilteredPortfolio` (1): log con `prompt_version=ai_filtered_portfolio_v1`.
  - `TestListOrdering` (2): orden por `created_at_utc ASC, request_id ASC`; query param `limit` respetado.
  - `TestNoRegression` (4): `/health`, `/auth/me`, `/advisor/profile-approval`, `/ai/filtered-portfolio-demo` sin auth.

**Total tests tras este commit:** 2594 (todos pasando). Δ = +73 (35 unit + 38 integration).

#### Decisiones de diseño

1. **`input_hash` sobre el ORIGINAL, no sobre el redactado.** Esto garantiza que dos inputs idénticos hasheen igual y que un cambio en texto libre cambie el hash, aunque el `input_redacted_json` persistido sea el mismo. Sirve para correlación (auditor puede confirmar "este texto produjo este log") sin necesidad de almacenar el texto.
2. **Canonical JSON `sort_keys=True / separators=(",",":") / ensure_ascii=False`** — mismo formato que `compute_payload_hash` y `compute_event_hash` (Commit 6). Determinismo total.
3. **Redacción por allowlist + denylist + heurística defensiva.** El allowlist (`_AI_LOG_STRUCTURED_KEYS`) cubre los campos estructurados conocidos de Phase 2; el denylist (`_AI_LOG_REDACTED_KEYS`) cubre el texto libre conocido; la heurística "string largo en key no whitelisted → redactar" atrapa campos no anticipados (defensa en profundidad). Strings cortos en keys desconocidas se conservan — over-redaction de etiquetas no aporta seguridad y rompe debuggability.
4. **API keys siempre redactadas, en cualquier posición.** `_looks_like_api_key` se evalúa sobre TODO string leaf (no solo keys conocidas), incluyendo dentro de dicts y lists anidados. Cubre `sk-`, `sk_`, `pk-`, `Bearer ...`, `api_key=`, `token=`.
5. **`client_id` se hashea, no se redacta como texto libre.** `client_<sha256[:8]>` es determinístico y permite correlacionar logs del mismo cliente sin exponer el ID.
6. **Logging es fail-safe en los endpoints automáticos.** `_persist_ai_request_log` captura cualquier excepción y devuelve `None`. Decisión: una llamada a IA que tuvo éxito (o que falló por OpenAI) NO debe propagar un 5xx por un problema de persistencia del log. La operación principal del endpoint manda. Iteración futura puede agregar telemetría / re-tirar bajo feature flag.
7. **`AIRequestLogResponse` siempre devuelve `raw_response` como dict o null.** Si el JSON persistido es válido se devuelve directamente; defensivo: si por alguna razón el JSON está corrupto, se envuelve en `{"__raw_response_parse_error__": True}` para no romper la lectura.
8. **POST `/admin/ai-logs` valida FKs en el endpoint, no en el repositorio.** Mismo patrón que `POST /cases`. El repositorio solo conoce su tabla. La política "case_id debe existir si se provee" es de negocio.
9. **POST `/admin/ai-logs` es admin-only.** Compliance puede leer pero no crear logs (preserva la propiedad de que los logs son producidos por el sistema, no inyectados por revisores).
10. **`latency_ms` se mide con `time.perf_counter()`** — monotónico, alta resolución; correcto para diffs de tiempo (no para timestamps absolutos).
11. **`prompt_version` es un string libre declarado por el endpoint.** No hay registry formal todavía (item 10 del pending list). El convención `<feature>_v<n>` se aplica en los tres endpoints integrados.
12. **`POST /admin/ai-logs` para test/backfill manual.** El camino productivo NO es este endpoint — es la integración automática. Existe para soportar importación, scripts internos y testing del repositorio sin tener que disparar IA real.

#### Tabla de RBAC actualizada (nuevos endpoints AIRequestLog)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `GET /admin/ai-logs` | ❌ 403 | ✅ 200 | ✅ 200 | ❌ 403 | ❌ 401 |
| `GET /admin/ai-logs/{id}` | ❌ 403 | ✅ 200/404 | ✅ 200/404 | ❌ 403 | ❌ 401 |
| `GET /cases/{id}/ai-logs` | ❌ 403 | ✅ 200/404 | ✅ 200/404 | ❌ 403 | ❌ 401 |
| `POST /admin/ai-logs` | ❌ 403 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |

#### Lo que NO está en este commit

- **AIRequestLog NO está case-scoped por default en los endpoints automáticos.** `case_id=None` salvo cuando se setea via POST manual. Cuando los endpoints `/ai/*` sean case-scoped (futuro), propagar `case_id` automáticamente.
- **No hay cifrado at-rest del SQLite.** Los `input_redacted_json` quedan en plano dentro del archivo. Para producción real haría falta cifrado a nivel de filesystem o de columna.
- **No hay retention / pruning policy.** Los logs se acumulan indefinidamente.
- **No hay prompt registry formal.** `prompt_version` es un string declarado por endpoint. Cambios incompatibles del prompt requieren bump manual (e.g. `_v1` → `_v2`).
- **No se integra con `/ai/profile-demo` ni `/ai/profile-follow-up`.** Sólo los tres endpoints declarados en el alcance del commit. Los otros dos quedan para una iteración posterior; el helper `_persist_ai_request_log` es reusable directamente.
- **`prompt_tokens` y `completion_tokens` se persisten como `None`.** El `OpenAIProfileClient` actual no expone token usage de la respuesta de OpenAI; cuando se exponga, el campo se puebla sin cambios de schema.
- **Firm-level access control sobre `/admin/ai-logs` y `/cases/{id}/ai-logs`** — un compliance/admin de la firma A puede leer logs de la firma B. Pendiente con el resto del scoping multi-tenant.

---

## Fase 2 — KYCSubmission case-scoped ✅ (Commit 8)

### Estado actual

Octavo commit de Fase 2 — primer paso del workflow real conectado al `AdvisoryCase`. El KYC ahora vive dentro de un case, con versionado monotónico, audit chain automático y transición de estado.

#### Archivos creados / modificados

- **`migrations/0002_kyc_submissions.sql`** — nueva migración:
  - Tabla `kyc_submissions(kyc_submission_id PK, case_id FK→advisory_cases, version INT, submitted_by_advisor_id NULL FK→advisors, payload_json, payload_hash, created_at_utc, UNIQUE(case_id, version))`.
  - Índices `idx_kyc_submissions_case_id`, `idx_kyc_submissions_submitted_by_advisor_id`.
  - Sin BEGIN/COMMIT explícitos (el runner los envuelve).

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — ampliado con:
  - `SQLiteAdvisoryCaseRepository.update_current_kyc_submission(case_id, kyc_submission_id)` — setea el puntero sin pasar por la FSM. Lanza `EntityNotFoundError` si el case no existe.
  - `SQLiteKYCSubmissionRepository`:
    - `create(*, case_id, payload, submitted_by_advisor_id=None)` — valida que el case exista (404 antes que mensaje FK), calcula `version = MAX(version)+1` por `case_id`, serializa el payload con `_canonical_json` y hashea con SHA-256. IDs con prefijo `kyc_submission_`.
    - `get(kyc_submission_id)` → dict | None.
    - `list_by_case(case_id)` → orden `version ASC`.
    - Sin `update` / `delete` (append-only por design).

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con `KYCSubmissionResponse` y `KYCSubmissionListResponse`. **No se introduce un nuevo request schema**: el POST reutiliza `KYCDataRequest` (que ya tiene todos los validators de Phase 1).

- **`src/risk_first_advisory/api_layer/main.py`** — 2 endpoints nuevos + integración con el case lifecycle:

  | Endpoint | RBAC | Descripción |
  |---|---|---|
  | `POST /cases/{case_id}/kyc` | advisor, admin | Crea submission; actualiza `current_kyc_submission_id`; transiciona `DRAFT → IN_PROGRESS` si corresponde; emite `kyc_submitted` audit event |
  | `GET /cases/{case_id}/kyc` | admin, advisor, compliance, viewer | Lista submissions ordenadas por `version` asc |

- **`tests/integration/test_api_case_kyc.py`** — 45 tests nuevos en 7 clases:
  - `TestCreateAndList` (12): 201 + `kyc_submission_` prefix + case_id correcto + version 1 + round-trip de `age`/`jurisdiction`/`preferred_currency` + `payload_hash` len=64 + `created_at_utc` con sufijo Z + `submitted_by_advisor_id` resuelto a entity + segunda submission → version 2 + GET lista [1, 2, 3].
  - `TestCaseStateSideEffects` (5): `current_kyc_submission_id` actualizado + apunta al último tras N submissions + DRAFT → IN_PROGRESS + IN_PROGRESS se mantiene + CLOSED rechaza con 409.
  - `TestAuditEventIntegration` (4): chain contiene `case_created` + `kyc_submitted`; payload del `kyc_submitted` tiene `case_id`/`kyc_submission_id`/`version`/`payload_hash`; `actor_advisor_id` propagado; `verify_chain` sigue `is_intact=true` después de KYC.
  - `TestRBACPost` (5): 401 / 403 (compliance, viewer) / 201 (advisor, admin).
  - `TestRBACGet` (5): 401 sin token / 200 para todos los roles válidos.
  - `TestValidation` (7): case inexistente (POST y GET) → 404; age < 18 → 422; annual_income negativo → 422; jurisdiction whitespace → 422; preferred_currency whitespace → 422; investment_objective inválido → 422.
  - `TestPersistence` (4): `payload_hash = sha256(canonical(payload))`; repo directo con case inexistente lanza `EntityNotFoundError`; repo directo devuelve dict con version=1; `update_current_kyc_submission` actualiza el puntero sin pasar por FSM.
  - `TestNoRegression` (3): `/health`, `/auth/me`, `/advisor/profile-approval` siguen funcionando.

- **`tests/unit/test_migrations.py`** — actualizado para reflejar la nueva migración:
  - `PHASE2_TABLES` incluye `kyc_submissions`.
  - `REQUIRED_INDEXES` incluye los dos nuevos índices.
  - Nuevo `TOTAL_MIGRATIONS = 2` reemplaza los `assert applied == 1` hardcoded.
  - `test_schema_migrations_records_0001_with_metadata` ahora valida también la fila `0002`.

**Total tests tras este commit:** 2639 (todos pasando). Δ = +45 (45 KYC integration).

#### Decisiones de diseño

1. **`version` se calcula en write-time (`MAX(version)+1` por `case_id`)**, no via AUTOINCREMENT. Mismo patrón que `audit_events.sequence` (Commit 6). `UNIQUE(case_id, version)` actúa como guard rail; un race condition extremo entre dos POST concurrentes para el mismo case → `EntityConflictError` (UNIQUE) → 409.
2. **`payload_json` se persiste en formato canonical** (`sort_keys=True / separators=(",", ":") / ensure_ascii=False`) para que `payload_hash` sea reproducible. Si una iteración futura quisiera cambiar el algoritmo de hashing, habría que versionarlo.
3. **El POST reutiliza `KYCDataRequest`**, no se introduce un schema nuevo. Reusa todos los validators de Phase 1 (age, jurisdiction, currency, investment_objective, ESG, etc.) sin duplicación. Si Phase 2 necesita validaciones específicas del case (e.g., el KYC debe coincidir con el firm del case), se agregan via post-validation en el endpoint, no en el schema.
4. **Soft FK lookup para `submitted_by_advisor_id`**, igual al patrón de `case_created` y `kyc_submitted` actor: si el `advisor.advisor_id` del token existe como advisor entity → se usa; si no → None. Defensivo contra la separación entre tokens (Phase 1) y entidades (Phase 2).
5. **Status transitions**:
   - `DRAFT → IN_PROGRESS` automático en el primer (y cualquier) POST mientras el case esté en DRAFT.
   - `IN_PROGRESS` se mantiene en POSTs subsecuentes (no se exige nueva FSM transition).
   - `PORTFOLIO_SELECTED` permite nuevo KYC sin cambiar status (decisión: re-KYC durante revisión de portfolio no invalida la selección automáticamente; queda a juicio del advisor si re-aprueba o no).
   - `CLOSED` → 409 hard: tras cierre formal del caso no se aceptan más submissions. Re-open / nuevo case son los workflows correctos.
6. **AuditEvent automático con payload mínimo.** El evento `kyc_submitted` registra solo metadata (`case_id`, `kyc_submission_id`, `version`, `submitted_by_advisor_id`, `payload_hash`) — NO el KYC payload completo. La fuente de verdad del payload sigue siendo `kyc_submissions` con su propio hash. Esto evita duplicación y mantiene el audit chain liviano.
7. **No-atomicidad documentada**: KYC insert + case update + status transition + audit insert NO están en una transacción única. Si el audit falla después del KYC insert, el endpoint devuelve 500 con mensaje claro. Mismo patrón que `POST /cases` (Commit 6). Iteración futura puede consolidar todo en un `BEGIN ... COMMIT` manual.
8. **`update_current_kyc_submission` no pasa por la FSM**. Es un setter directo del puntero. La razón: actualizar el puntero al último KYC NO es una transición de status del case (eso se hace via `update_status`). Mantenerlos separados evita confusión y permite que el caller decida cuándo cada uno se invoca.
9. **GET es abierto a todos los roles válidos** (admin/advisor/compliance/viewer); POST es solo advisor/admin. Mismo principio que audit listing.
10. **Tests usan `_full_chain` con `advisor_id="ADV-KYC-001"` explícito** para que el advisor entity coincida con el token, permitiendo testear el path donde `submitted_by_advisor_id` se resuelve (no `None`). Mismo patrón que `test_api_audit_events.py`.

#### Tabla de RBAC actualizada (nuevos endpoints KYC)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `POST /cases/{id}/kyc` | ✅ 201 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /cases/{id}/kyc` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |

#### Lo que NO está en este commit

- **No hay case-scoped AI profile analysis todavía.** `/ai/profile-demo` y `/ai/profile-follow-up` siguen recibiendo el KYC payload directamente; no consultan `current_kyc_submission_id`. Queda como item 13 del pending list.
- **No hay case-scoped profile approval todavía.** `/advisor/profile-approval` sigue recibiendo `client_id`, no `case_id`. `advisory_cases.current_approved_profile_id` queda en `None`. Item 14.
- **No hay case-scoped portfolio proposal todavía.** `/ai/filtered-portfolio-demo` no actualiza `current_portfolio_selection_id`. Item 15.
- **No hay UI Case Workbench.** El flujo end-to-end por case solo se puede ejercer via API. Item 16.
- **No hay firm-level access control sobre `/cases/{id}/kyc`** — un advisor/admin de la firma A puede crear/leer KYC submissions de cualquier case. Mismo gap que en los otros endpoints `/cases/*`.
- **El `PATCH /cases/{id}/status` no genera audit event automático todavía.** Cuando KYC dispara la transición `DRAFT → IN_PROGRESS`, el audit chain registra solo `case_created` + `kyc_submitted` (no un evento separado de transición). Iteración futura: agregar `status_changed` event en el endpoint PATCH y en el path automático del POST KYC.

---

## Fase 2 — AIProfileAnalysis case-scoped ✅ (Commit 9)

### Estado actual

Noveno commit de Fase 2 — segundo paso del workflow real conectado al `AdvisoryCase`. El análisis IA de perfil ahora vive dentro de un case, anclado a una `KYCSubmission` concreta y vinculado al `AIRequestLog` que registró la llamada.

#### Archivos creados / modificados

- **`migrations/0003_ai_profile_analyses.sql`** — nueva migración:
  - Tabla `ai_profile_analyses(analysis_id PK, case_id FK→advisory_cases NOT NULL, kyc_submission_id FK→kyc_submissions NOT NULL, ai_request_log_id NULL FK→ai_request_logs, analysis_type, preliminary_profile NULL, confidence REAL NULL, result_json, created_at_utc)`.
  - Índices `idx_ai_profile_analyses_case_id`, `idx_ai_profile_analyses_kyc_submission_id`, `idx_ai_profile_analyses_ai_request_log_id`.

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — ampliado con:
  - `ALLOWED_PROFILE_ANALYSIS_TYPES = {"initial", "follow_up"}` constant.
  - `SQLiteAIProfileAnalysisRepository`:
    - `create(*, case_id, kyc_submission_id, analysis_type, result, preliminary_profile=None, confidence=None, ai_request_log_id=None)` — IDs con prefijo `ai_profile_analysis_`. `result` se persiste canonical JSON. FK violation → `EntityConflictError`.
    - `get(analysis_id)` → dict | None.
    - `list_by_case(case_id)` → orden `created_at_utc ASC, analysis_id ASC`.
    - Sin `update` / `delete` (append-only).

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con:
  - `AIProfileAnalysisCreateRequest` (`kyc_submission_id: str | None`, `analysis_type: str = "initial"`). Validators: `analysis_type` debe estar en `{initial, follow_up}` (422 si otro); `follow_up` rechaza con 422 explícito (`"aún no está implementado"`).
  - `AIProfileAnalysisResponse` (campos: `analysis_id`, `case_id`, `kyc_submission_id`, `ai_request_log_id`, `analysis_type`, `preliminary_profile`, `confidence`, `result`, `created_at_utc`).
  - `AIProfileAnalysisListResponse` (`analyses`, `count`).

- **`src/risk_first_advisory/api_layer/main.py`** — agregado:
  - Constante `_AI_LOG_PROMPT_CASE_PROFILE_ANALYSIS = "case_profile_analysis_v1"`.
  - 2 endpoints:

  | Endpoint | RBAC | Descripción |
  |---|---|---|
  | `POST /cases/{case_id}/ai/profile-analysis` | advisor, admin | Resuelve KYC → llama OpenAIProfileClient → persiste AIRequestLog + AIProfileAnalysis + AuditEvent. |
  | `GET /cases/{case_id}/ai/profile-analysis` | admin, advisor, compliance, viewer | Lista análisis ordenados por `created_at_utc` asc. |

  - Reutiliza el helper existente `_persist_ai_request_log` (que ya soporta `case_id` desde Commit 7); el `ai_request_log_id` retornado se persiste en `ai_profile_analyses.ai_request_log_id`.
  - Mismo patrón de soft FK lookup para `requested_by_advisor_id` (advisor del token solo si existe como entity).
  - Mismo patrón de `_pick_actor_role` para el `actor_role` del audit event.

- **`tests/integration/test_api_case_ai_profile_analysis.py`** — 48 tests en 8 clases:
  - `TestCreateAnalysis` (11): 201; `ai_profile_analysis_` prefix; `case_id`/`kyc_submission_id`/`ai_request_log_id` correctos; `analysis_type=initial`; `preliminary_profile`/`confidence` desde la IA; `result` contiene `contradictions`/`follow_up_questions`/`advisor_notes`; GET lista 1 y luego 2.
  - `TestKYCSelection` (5): default usa `current_kyc_submission_id`; explícito usa el dado; KYC inexistente → 422; KYC de otro case → 422; case sin KYC → 409.
  - `TestAIRequestLogIntegration` (6): log tiene `case_id`; `input_redacted` NO contiene `open_concerns` ni el texto `xyz123`; `validation_status=parsed_ok`; `prompt_version=case_profile_analysis_v1`; endpoint correcto; el log aparece en `/cases/{id}/ai-logs`.
  - `TestAuditIntegration` (3): chain contiene `case_created` + `kyc_submitted` + `ai_profile_analyzed`; payload del nuevo evento tiene `analysis_id`/`kyc_submission_id`/`ai_request_log_id`/`analysis_type`/`preliminary_profile`; `verify_chain` sigue `is_intact=true`.
  - `TestRBACPost` (5): 401 / 403 (compliance, viewer) / 201 (advisor, admin).
  - `TestRBACGet` (5): 401 / 200 para los 4 roles válidos.
  - `TestValidation` (5): case inexistente (POST y GET) → 404; CLOSED → 409; `analysis_type=bogus` → 422; `analysis_type=follow_up` → 422 (no implementado).
  - `TestOpenAIFailure` (4): falla OpenAI → 502; AIRequestLog con `validation_status=api_error` y `error_message` poblado; NO se crea `AIProfileAnalysis`; NO se crea audit event `ai_profile_analyzed`.
  - `TestNoRegression` (4): `/health`, `/auth/me`, `/advisor/profile-approval`, `/ai/filtered-portfolio-demo` siguen funcionando.

- **`tests/unit/test_migrations.py`** — actualizado:
  - `PHASE2_TABLES` incluye `ai_profile_analyses`.
  - `REQUIRED_INDEXES` incluye los tres nuevos índices.
  - `TOTAL_MIGRATIONS = 3`.
  - `test_schema_migrations_records_0001_with_metadata` ahora valida también la fila `0003`.

**Total tests tras este commit:** 2687 (todos pasando). Δ = +48 integration.

#### Decisiones de diseño

1. **KYC selection: default a `current_kyc_submission_id` del case, override explícito vía body**. Si el caller no pasa `kyc_submission_id`, se usa el más reciente (el puntero que actualiza Commit 8). Si pasa uno explícito, debe (a) existir y (b) pertenecer al mismo case. Esto soporta dos casos de uso: "analiza el KYC actual" (default) y "re-analiza una versión histórica" (override).
2. **`kyc_submission_id` es NOT NULL en la tabla**. Cada análisis se hace sobre una KYC concreta, no anonymous. Trazabilidad versión → análisis es central para auditoría.
3. **`ai_request_log_id` es NULL-able**. El camino productivo (endpoint POST) siempre lo vincula, pero el repo permite análisis sin log para backfill / scripts internos. Es FK opcional, no requerida por design.
4. **`preliminary_profile` y `confidence` son denormalizados del `result_json`**. Sirven para indexar (e.g., "lista de análisis del case con confidence < 0.5") sin parsear JSON. `result` siempre contiene el JSON completo de la IA por si se necesita más detalle.
5. **`result_json` en canonical JSON** (mismo formato que `payload_json` de KYC y `payload_json` de audit events). Determinismo y reproducibilidad si se necesita re-hashear.
6. **`analysis_type` restringido a `{initial, follow_up}` a nivel API, libre a nivel DB.** Permite futuras extensiones sin migración. `follow_up` rechaza con 422 + mensaje explícito ("aún no está implementado") para que el cliente sepa que no es un typo de validation.
7. **CLOSED case rechaza con 409** (mismo patrón que KYC). Tras cierre formal no se aceptan más análisis.
8. **Caso sin KYC rechaza con 409**, no 422. Decisión: la condición ("el case no tiene KYC todavía") es de estado del recurso, no de validación del payload. El caller debe POSTear un KYC primero.
9. **KYC de otro case rechaza con 422** (validación cross-resource). El payload está bien formado pero referencia un recurso inválido para este context.
10. **El `client_id` que se pasa a la IA es el `case_id`** (opaque identifier), no el `client_id` real del cliente. Esto evita exponer el client_id del CRM a la IA y mantiene el log redactado correctamente (`case_id` no es PII).
11. **El input a la IA incluye metadata mínima** (`case_id`, `kyc_submission_id`, además del payload KYC). Esto permite que la IA contextualice el análisis (futuro: prompt podría usar esta metadata) y el `input_hash` cambia si la KYC version cambia.
12. **Si OpenAI falla, NO se crea AIProfileAnalysis NI AuditEvent**. Política: el análisis solo existe si la llamada IA tuvo éxito. El AIRequestLog con `validation_status=api_error` queda como evidencia auditable de que se intentó, pero el evento `ai_profile_analyzed` solo se emite si hay análisis real. Esto mantiene el audit chain consistente con la realidad.
13. **El AIRequestLog se persiste ANTES del AIProfileAnalysis**. Necesario porque `ai_profile_analyses.ai_request_log_id` es FK a `ai_request_logs.request_id`. Si el log falla (silenciosamente, helper es fail-safe), `ai_request_log_id` queda en `None` pero el análisis igual se crea.
14. **El AIRequestLog se persiste en una segunda apertura del store**. Razón: `_persist_ai_request_log` abre su propio `SQLiteEntityStore`. Para no romper esa contrato y mantener el helper reusable, el endpoint cierra el primer store (donde validó las precondiciones), llama al helper, y abre un segundo store para persistir el análisis + audit. Trade-off entre simplicidad del helper y atomicidad estricta — se eligió simplicidad (consistente con AIRequestLog en Commits 7).
15. **Reusa `_persist_ai_request_log` sin modificación**. El helper de Commit 7 ya soportaba `case_id` y `requested_by_advisor_id`. Aprovecha esa generalidad y evita drift entre logging case-scoped y non-case-scoped.
16. **`time.perf_counter()` para latency_ms** (mismo patrón que Commit 7).

#### Tabla de RBAC actualizada (nuevos endpoints AIProfileAnalysis)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `POST /cases/{id}/ai/profile-analysis` | ✅ 201 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /cases/{id}/ai/profile-analysis` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |

#### Lo que NO está en este commit

- **`analysis_type=follow_up` NO está implementado.** Pydantic acepta el valor en `_ALLOWED_PROFILE_ANALYSIS_TYPES` (para futuros) pero el endpoint lo rechaza con 422 explícito ("aún no está implementado"). Item 14 del pending list. Implementarlo requiere: seleccionar un `previous_analysis_id`, pedirle al cliente `follow_up_answers`, llamar a `OpenAIProfileClient.analyze_follow_up`.
- **No hay case-scoped profile approval todavía.** El análisis IA no se aprueba ni rechaza por el advisor en este commit. `advisory_cases.current_approved_profile_id` sigue en `None`. Item 15.
- **No hay case-scoped universe filter ni portfolio proposal.** Items 16 y similar.
- **Firm-level access control sigue pendiente** (item 11).
- **No hay UI Case Workbench** (item 17).
- **Latency_ms se mide solo de la llamada IA, no del round-trip total del endpoint** (consistente con AIRequestLog en Commit 7). El tiempo de validación previa + persistence posterior no se incluye.
- **Cross-firm scoping**: el endpoint no valida que el `kyc_submission_id` explícito provenga de un case de la misma firma que el del token. Como el firm-level scoping general sigue pendiente, esto es coherente con el resto del sistema.

---

## Fase 2 — CaseAdvisorProfileApproval case-scoped ✅ (Commit 10)

### Estado actual

Décimo commit de Fase 2 — la decisión humana del asesor sobre el perfil ahora vive dentro del case, vinculada al análisis IA y a la KYC vigente. Tres outcomes (`approve` / `modify` / `reject`) con semántica diferenciada y `is_current` consistente.

#### Archivos creados / modificados

- **`migrations/0004_case_profile_approvals.sql`** — nueva migración:
  - Tabla `advisor_profile_approvals(approval_id PK, case_id NOT NULL FK→advisory_cases, ai_profile_analysis_id NULL FK→ai_profile_analyses, kyc_submission_id NULL FK→kyc_submissions, advisor_id NULL FK→advisors, proposed_profile NOT NULL, decision NOT NULL, approved_profile NULL, rationale NOT NULL, source NOT NULL, is_current INTEGER DEFAULT 1, created_at_utc)`.
  - 4 índices: `idx_advisor_profile_approvals_case_id`, `idx_*_ai_profile_analysis_id`, `idx_*_kyc_submission_id`, `idx_*_advisor_id`.
  - **Sin colisión** con `records` (legacy SQLitePersistenceStore usa `records.record_type='advisor_profile_approval'`); son storages distintos: esta tabla es case-scoped, el legacy es client_id-scoped.

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — ampliado con:
  - `SQLiteAdvisoryCaseRepository.update_current_approved_profile(case_id, approval_id | None)` — setter directo del puntero; pasar `None` lo limpia. No valida que el approval exista (responsabilidad del endpoint).
  - `ALLOWED_PROFILE_APPROVAL_DECISIONS = {"approve", "modify", "reject"}` constant.
  - `SQLiteAdvisorProfileApprovalCaseRepository` (nombre con sufijo `CaseRepository` para distinguir del legacy `SQLiteAdvisorProfileApprovalRepository` Phase 1):
    - `create(*, case_id, proposed_profile, decision, rationale, source="manual", ai_profile_analysis_id=None, kyc_submission_id=None, advisor_id=None, approved_profile=None, is_current=True)` — IDs `advisor_profile_approval_NNNNNN`. Valida `decision ∈ ALLOWED_PROFILE_APPROVAL_DECISIONS`. FK violation → `EntityConflictError`.
    - `get(approval_id)` → dict | None.
    - `list_by_case(case_id)` → orden `created_at_utc ASC, approval_id ASC`.
    - `mark_previous_not_current(case_id, exclude_id=None)` — bulk UPDATE `is_current=0` a todos los `is_current=1` del case excepto opcionalmente `exclude_id`. Devuelve `rowcount`.

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con:
  - `CaseAdvisorProfileApprovalCreateRequest` (campos: `ai_profile_analysis_id` opt, `kyc_submission_id` opt, `proposed_profile` opt, `decision`, `approved_profile` opt, `rationale`, `source="manual"`). Reusa `_ADVISOR_VALID_PROFILES` y `_ADVISOR_VALID_DECISIONS` (Phase 1). `model_validator` aplica reglas cruzadas decision/approved_profile cuando `proposed_profile != None` (si es None, el endpoint las aplica tras la derivación).
  - `CaseAdvisorProfileApprovalResponse` (todos los campos incluyendo `is_current: bool`).
  - `CaseAdvisorProfileApprovalListResponse`.

- **`src/risk_first_advisory/api_layer/main.py`** — agregado:
  - Constante `_PROFILE_APPROVAL_EVENT_BY_DECISION` mapeando `approve/modify/reject` → `advisor_profile_approved/_modified/_rejected`.
  - Constante `_ADVISOR_VALID_PROFILES_SET` (duplicada de schemas para no importar nombres privados; usada solo para validar derivación de `proposed_profile` desde análisis).
  - 2 endpoints:

  | Endpoint | RBAC | Descripción |
  |---|---|---|
  | `POST /cases/{case_id}/profile-approval` | advisor, admin | Resuelve análisis/KYC, deriva proposed_profile si falta, valida cross-resource, persiste approval + mantiene is_current + current_approved_profile_id + AuditEvent. |
  | `GET /cases/{case_id}/profile-approval` | admin, advisor, compliance, viewer | Lista approvals ordenados por `created_at_utc` asc. |

- **`tests/integration/test_api_case_profile_approval.py`** — 50 tests en 8 clases:
  - `TestCreateApprove` (13): 201, prefix `advisor_profile_approval_`, case_id/ai_analysis_id/kyc_submission_id correctos, advisor_id desde entity, decision=approve, proposed_profile derivado, approved_profile auto-fill, rationale persistido, is_current=true, GET cuenta 1, case.current_approved_profile_id actualizado.
  - `TestCreateModify` (3): modify con approved_profile válido; current_approved_profile_id apunta al modify; previous approval queda is_current=false.
  - `TestReject` (3): reject sin approved_profile (201, is_current=false); reject con approved_profile → 422; reject NO pisa current_approved_profile_id previo.
  - `TestValidation` (13): missing case (POST/GET) → 404; CLOSED → 409; analysis_id unknown → 422; analysis de otro case → 422 ("belongs to case"); KYC de otro case → 422; proposed/approved_profile inválidos → 422; approve con approved_profile distinto → 422; modify sin approved_profile → 422; rationale whitespace → 422; decision inválida → 422; proposed_profile requerido si no hay AI analysis → 422.
  - `TestAudit` (4): approve emite `advisor_profile_approved`; modify emite `_modified`; reject emite `_rejected`; payload contiene `approval_id` + `decision`; `verify_chain` sigue intacto.
  - `TestRBACPost` (5): 401 / 403 (compliance, viewer) / 201 (advisor, admin).
  - `TestRBACGet` (5): 401 / 200 para los 4 roles válidos.
  - `TestNoRegression` (4): endpoint legacy `/advisor/profile-approval`, `/health`, `/auth/me`, `/ai/filtered-portfolio-demo` siguen funcionando.

- **`tests/unit/test_migrations.py`** — actualizado:
  - `PHASE2_TABLES += advisor_profile_approvals`.
  - `REQUIRED_INDEXES += idx_advisor_profile_approvals_*` (×4).
  - `TOTAL_MIGRATIONS = 4`.
  - `test_schema_migrations_records_0001_with_metadata` valida también la fila `0004`.

**Total tests tras este commit:** 2737 (todos pasando). Δ = +50 integration.

#### Decisiones de diseño

1. **Tabla nueva `advisor_profile_approvals` (no se reusa `records`).** El legacy `/advisor/profile-approval` (Phase 1) sigue persistiendo en `records.record_type='advisor_profile_approval'` con `client_id` scope. El nuevo es case-scoped con FKs a `advisory_cases`, `ai_profile_analyses`, `kyc_submissions`, `advisors`. Los dos storages **coexisten sin conflicto**; deprecación del legacy queda como item 18.
2. **`is_current` mantenido por el endpoint**, no por DB triggers. `approve`/`modify` → llaman `mark_previous_not_current(case_id, exclude_id=new_approval_id)` después del insert; el nuevo queda `is_current=1`. `reject` → se inserta con `is_current=0` directamente. Razón: triggers en SQLite agregan complejidad; la consistencia se garantiza con un único path de escritura (el endpoint).
3. **`reject` NO pisa `current_approved_profile_id` previo.** Decisión documentada: un rechazo nuevo no invalida la última decisión vigente del case. Si el advisor quiere invalidar la aprobación previa, debe emitir un nuevo `modify` o re-aprobar con `approve`. Esto preserva el invariante "current_approved_profile_id apunta siempre al último `is_current=1`".
4. **`reject` inicial (case sin approval previo) deja `current_approved_profile_id=NULL`.** Consistente con la regla anterior: no hay aprobación vigente que reemplazar.
5. **Derivación de `proposed_profile` desde el último análisis del case.** Si el caller no manda `proposed_profile`, el endpoint usa el último `AIProfileAnalysis.preliminary_profile`. Si no hay análisis o el `preliminary_profile` no es válido → 422 con mensaje claro. Reduce la carga sobre el caller (no tiene que copiar el perfil propuesto si confía en la IA).
6. **`kyc_submission_id` heredado del análisis** si no se manda explícito y se eligió un análisis. Trazabilidad: cada approval queda anclada a la KYC vigente al momento del análisis.
7. **`ai_profile_analysis_id` y `kyc_submission_id` son NULL-able** en la tabla. Permite approvals sin análisis previo (cuando el advisor decide a mano sin pasar por IA) o sin KYC linkage (cuando el case no tiene KYC todavía — caso edge documentado).
8. **Cross-resource validation explícita**: `ai_profile_analysis_id` y `kyc_submission_id` deben pertenecer al mismo `case_id` (mensaje "belongs to case"). Mismo patrón que `POST /cases/{id}/ai/profile-analysis` con `kyc_submission_id`.
9. **`model_validator` cruzado se ejecuta a nivel schema CUANDO `proposed_profile` viene en el request.** Cuando `proposed_profile=None`, el endpoint replica la lógica (auto-fill approve, modify requiere approved_profile, reject requiere approved_profile=None) tras la derivación. Esto evita validaciones duplicadas pero garantiza coverage en ambos paths.
10. **Mismo mapping decision → event_type que el dominio Phase 1.** `approve` → `advisor_profile_approved`, `modify` → `advisor_profile_modified`, `reject` → `advisor_profile_rejected`. Coherente con los strings del audit chain.
11. **AuditEvent payload incluye solo metadata.** No se duplica el `result_json` del análisis ni el `payload_json` del KYC. El advisor que audita el chain puede navegar a los recursos por sus IDs (`approval_id`, `ai_profile_analysis_id`, `kyc_submission_id`).
12. **Soft FK lookup para `advisor_id`** (mismo patrón que `case_created`, `kyc_submitted`, `ai_profile_analyzed`). Si el `advisor.advisor_id` del token existe como entity → se usa; si no → `None`.
13. **Reusa `_ADVISOR_VALID_PROFILES` y `_ADVISOR_VALID_DECISIONS` de schemas.py.** Mantiene el mismo conjunto válido entre legacy y case-scoped (5 perfiles, 3 decisiones). Si Phase 2 quisiera diverger, hay que duplicar (no se hace en este commit).
14. **CLOSED case → 409** (mismo patrón que KYC y AI profile analysis). Tras cierre formal no se aceptan más decisiones.
15. **`mark_previous_not_current` con `exclude_id` opcional** permite dos casos de uso: invalidar todas las previas excepto la recién creada (camino productivo) y "limpiar" todas las is_current=1 (uso futuro / scripts admin).

#### Tabla de RBAC actualizada (nuevos endpoints)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `POST /cases/{id}/profile-approval` | ✅ 201 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /cases/{id}/profile-approval` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |

#### Lo que NO está en este commit

- **No hay case-scoped universe filter ni portfolio proposal todavía** (items 16, 17).
- **No hay case-scoped override-approval todavía.** El legacy `/advisor/override-approval` sigue siendo client-scoped (Phase 1). Item 17.
- **El endpoint legacy `/advisor/profile-approval` (Phase 1) sigue vivo** sin migración / deprecación. Item 18. Coexiste sin conflicto: storages distintos, paths distintos, schemas distintos.
- **Firm-level access control pendiente** (item 12).
- **No hay UI Case Workbench** (item 19).
- **No hay endpoint de `/cases/{id}/profile-approval/{approval_id}` (detail).** Para inspeccionar un approval específico, el caller usa GET list y filtra. Si crece la necesidad, se puede agregar sin cambios de schema.
- **`mark_previous_not_current` no genera AuditEvent.** La invalidación implícita queda registrada vía `is_current=0` en la tabla y vía el nuevo evento `advisor_profile_approved/_modified` que indica que hubo decisión nueva. Si compliance necesita un evento explícito de "invalidación", se puede agregar.

---

## Fase 2 — CaseInvestmentPreference + CaseUniverseFilterRun ✅ (Commit 11)

### Estado actual

Undécimo commit de Fase 2 — bloque combinado que registra preferencias case-scoped (manuales o IA-extraídas) y corre el `PreferenceFilterEngine` sobre el universo CSV para producir un snapshot persistido por case.

#### Archivos creados / modificados

- **`migrations/0005_case_investment_preferences_and_universe_filters.sql`** — nueva migración:
  - Tabla `case_investment_preferences(preference_id PK, case_id NOT NULL FK→advisory_cases, source NOT NULL, natural_language_preferences NULL, structured_preferences_json NOT NULL, ai_request_log_id NULL FK→ai_request_logs, created_by_advisor_id NULL FK→advisors, created_at_utc, is_current INTEGER DEFAULT 1)` + 3 índices.
  - Tabla `case_universe_filter_runs(filter_run_id PK, case_id NOT NULL FK→advisory_cases, preference_id NULL FK→case_investment_preferences, source_universe NOT NULL, eligible_instruments_json, exclusions_json, applied_filters_json, warnings_json, eligible_count INT, excluded_count INT, total_count INT, created_by_advisor_id NULL FK→advisors, created_at_utc, is_current INTEGER DEFAULT 1)` + 3 índices.

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — ampliado con:
  - `ALLOWED_INVESTMENT_PREFERENCE_SOURCES = {"manual", "ai", "imported"}`.
  - `SQLiteCaseInvestmentPreferenceRepository` con `create`, `get`, `list_by_case`, `get_current_for_case` (devuelve el `is_current=1` más reciente del case), `mark_previous_not_current(case_id, exclude_id=None)`. IDs `case_investment_preference_NNNNNN`. `structured_preferences_json` en canonical.
  - `SQLiteCaseUniverseFilterRunRepository` con `create`, `get`, `list_by_case`, `mark_previous_not_current`. IDs `case_universe_filter_run_NNNNNN`. Listas envueltas en `{"items": [...]}` antes del canonical JSON (consistente y deserializable directo).

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con:
  - `CaseInvestmentPreferenceCreateRequest`: `natural_language_preferences` opt, `structured_preferences` opt (dict), `source="manual"`. `model_validator` exige al menos uno de los dos inputs. `source` validado contra `_ALLOWED_INVESTMENT_PREFERENCE_SOURCES`.
  - `CaseInvestmentPreferenceResponse`, `CaseInvestmentPreferenceListResponse`.
  - `CaseUniverseFilterRunCreateRequest`: `preference_id` opt, `source_universe="sample_instrument_universe.csv"`.
  - `CaseUniverseFilterRunResponse`, `CaseUniverseFilterRunListResponse`.

- **`src/risk_first_advisory/api_layer/main.py`** — agregado:
  - Constante `_AI_LOG_PROMPT_CASE_INVESTMENT_PREFS = "case_investment_preferences_v1"`.
  - Helper `_convert_ai_preferences_to_structured(ai_result)` — filtra al subset de keys que `PreferenceFilterEngine` entiende (mismo `_AI_FILTER_PREFERENCE_KEYS` reutilizado).
  - Helper `_serialize_instrument_for_filter_run(inst)` — mismo shape que `InstrumentResponse` para coherencia con endpoints legacy.
  - 4 endpoints:

  | Endpoint | RBAC | Descripción |
  |---|---|---|
  | `POST /cases/{case_id}/investment-preferences` | advisor, admin | Persiste preferencia. Si solo NLP, llama al extractor IA (+ AIRequestLog con `case_id`). Si solo structured o ambos, no llama IA. Marca previas `is_current=0`. AuditEvent `investment_preferences_recorded`. |
  | `GET /cases/{case_id}/investment-preferences` | admin/advisor/compliance/viewer | Lista ordenada por `created_at_utc` asc. |
  | `POST /cases/{case_id}/universe-filter` | advisor, admin | Resuelve `preference_id` (explícita o current). Carga CSV. Aplica `PreferenceFilterEngine`. Persiste snapshot completo. Marca runs previos `is_current=0`. AuditEvent `universe_filtered`. |
  | `GET /cases/{case_id}/universe-filter` | admin/advisor/compliance/viewer | Lista runs ordenados por `created_at_utc` asc. |

- **`tests/integration/test_api_case_investment_preferences_universe_filter.py`** — 53 tests en 10 clases:
  - `TestPreferenceManualStructured` (9): 201, prefix, case_id, source=manual, structured round-trip, `ai_request_log_id=None`, `is_current=true`, GET lista 1, segundo POST marca primero `is_current=false`.
  - `TestPreferenceNaturalLanguageAI` (7): 201; AIRequestLog con `case_id` + `prompt_version=case_investment_preferences_v1`; `source` promovido a `"ai"` cuando solo viene NLP; structured persisted desde IA result; texto libre `xyz123` NO aparece en `input_redacted`; falla IA → 502; falla IA no crea preference.
  - `TestPreferenceBothInputs` (1): cuando vienen ambos → structured manda, no se llama IA, `source` queda `manual`, texto se guarda como contexto.
  - `TestPreferenceValidation` (6): missing case → 404; CLOSED → 409; sin inputs → 422; NLP whitespace → 422; structured no dict → 422; source inválido → 422.
  - `TestPreferenceAudit` (2): `investment_preferences_recorded` aparece; `verify_chain` intact.
  - `TestPreferenceRBAC` (5): POST 401/403 (compliance, viewer); GET 200 (compliance, viewer).
  - `TestFilterCreate` (8): sin preference → 409; con manual → 201; prefix `case_universe_filter_run_`; counts consistentes (`eligible + excluded == total`); `total_count > 0`; `applied_filters` no vacío; GET lista 1; segundo run marca primero `is_current=false`.
  - `TestFilterValidation` (5): missing case → 404; CLOSED → 409; preference de otro case → 422 ("belongs to case"); preference unknown → 422; source_universe whitespace → 422.
  - `TestFilterAudit` (2): `universe_filtered` con payload metadata; `verify_chain` intact.
  - `TestFilterRBAC` (4): POST 401/403; GET 200 (compliance, viewer).
  - `TestNoRegression` (4): `/ai/filter-universe-demo`, `/ai/filtered-portfolio-demo`, `/health`, `/auth/me`.

- **`tests/unit/test_migrations.py`** — actualizado: `PHASE2_TABLES += case_investment_preferences, case_universe_filter_runs`; `REQUIRED_INDEXES += 6 nuevos`; `TOTAL_MIGRATIONS = 5`; assert fila `0005` en schema_migrations.

**Total tests tras este commit:** 2790 (todos pasando). Δ = +53 integration.

#### Decisiones de diseño

1. **Una sola migration (0005) para las dos tablas.** Van siempre juntas en el flujo (preferencia → filter run); separarlas en dos migrations agregaría ruido sin ganar nada (no se va a aplicar una sin la otra).

2. **`structured_preferences_json` es la fuente de verdad.** Cuando el caller manda ambos inputs, el texto natural se preserva en `natural_language_preferences` como contexto, pero el filter engine usa solo `structured_preferences`. No se llama a IA cuando hay structured.

3. **`source` se promueve automáticamente** a `"ai"` cuando el caller deja `source="manual"` (default) pero solo manda `natural_language_preferences`. Razón: el `source` refleja el ORIGEN real de las preferencias estructuradas, no el intent del caller. Si pasaron por la IA, son `ai`; si las dictó el advisor directamente, son `manual`; `imported` queda para futuro (CSV bulk, sistema externo).

4. **Solo NLP → llama IA + AIRequestLog**. Reutiliza el helper existente `_persist_ai_request_log` (Commit 7) con `case_id` poblado y `prompt_version=case_investment_preferences_v1`. La falla de IA es 502 + AIRequestLog con `validation_status=api_error`; NO se crea preference. Consistente con `/cases/{id}/ai/profile-analysis` (Commit 9).

5. **`_convert_ai_preferences_to_structured` filtra a `_AI_FILTER_PREFERENCE_KEYS`** (reuso de la constante existente). Esto descarta metadata IA (`confidence`, `advisor_notes`, etc.) que el filter engine no procesa y que tampoco aporta valor a la preference persistida. Si una iteración futura quiere preservar esa metadata, se puede agregar un campo separado sin tocar el schema actual.

6. **`is_current` mantenido por el endpoint** vía `mark_previous_not_current` (mismo patrón que `advisor_profile_approvals` en Commit 10). Cada POST nuevo invalida los previos del case.

7. **`get_current_for_case` con ORDER BY desc + LIMIT 1.** Defensive: aunque por design solo debería haber un `is_current=1` por case en cualquier momento, si hubiera una race condition se devuelve el más reciente.

8. **`eligible_instruments`/`exclusions`/`applied_filters`/`warnings` se envuelven en `{"items": [...]}`** antes de canonical JSON. Razón: `_canonical_json` espera un dict, no una list. Wrapper consistente que mantiene el formato canonical y se deserializa directo en `_row_to_dict`.

9. **`_serialize_instrument_for_filter_run` duplica el shape de `InstrumentResponse`** (no se importa). Coherencia con endpoints legacy sin acoplar el persistence layer a Pydantic schemas. Si el shape cambia, ambos puntos hay que tocarlos — trade-off aceptado.

10. **Filter run requiere preference existente.** Si no se pasa `preference_id`, se usa `get_current_for_case`. Si tampoco hay current → 409 con mensaje explícito "POST a investment-preferences first". Decisión: filter sin preference es operacionalmente ambiguo (¿qué filtra?), mejor obligar al caller a establecer el contexto.

11. **`preference_id` explícito debe pertenecer al case** (validación cross-resource). Mismo patrón que `kyc_submission_id` en AI profile analysis (Commit 9).

12. **`source_universe` libre como string** (default `"sample_instrument_universe.csv"`). Hoy el endpoint solo soporta el fixture CSV; el campo queda preparado para futuro (live data provider, otros CSVs). Si el caller pasa un valor distinto, igual se usa el fixture pero el valor se persiste como metadata — esto se documentará explícitamente cuando se implementen los otros universos.

13. **CLOSED case → 409** en ambos endpoints POST (mismo patrón que KYC / análisis / approval).

14. **AuditEvent payloads solo metadata** (no se duplica `structured_preferences` ni el resultado del filter). Auditor navega por IDs si necesita inspeccionar.

15. **Filter run NO modifica `current_*` de `advisory_cases`.** No hay `current_filter_run_id` en el schema de `advisory_cases` (sería propio del portfolio proposal flow, item 17). El filter es un cálculo derivado; mantener el puntero queda para cuando exista portfolio_selection.

16. **`is_current` se mantiene SOLO en las tablas case-scoped relevantes**, no se propaga al `advisory_cases` puntero. La razón: el filter es ephemeral (se puede regenerar desde la preferencia); la preferencia sí es decisión durable, pero no requiere un puntero en `advisory_cases` porque el caller siempre puede llamar a `GET /cases/{id}/investment-preferences` y filtrar por `is_current=true`.

#### Tabla de RBAC actualizada (nuevos endpoints)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `POST /cases/{id}/investment-preferences` | ✅ 201 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /cases/{id}/investment-preferences` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |
| `POST /cases/{id}/universe-filter` | ✅ 201 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /cases/{id}/universe-filter` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |

#### Lo que NO está en este commit

- **No hay case-scoped portfolio proposal** (item 17). El filter run es el último paso del bloque "data preparation"; la propuesta de portfolio sobre el universo filtrado queda para el próximo commit.
- **`source_universe` solo acepta el fixture CSV en la práctica.** El campo se persiste tal cual viene pero la implementación siempre carga `_INSTRUMENT_UNIVERSE_CSV`. Item 19 (live market data).
- **No hay endpoint detail** `/cases/{id}/investment-preferences/{preference_id}` ni `/cases/{id}/universe-filter/{filter_run_id}`. Si se necesitan, se agregan sin cambios de schema.
- **`mark_previous_not_current` no genera AuditEvent** (mismo principio que en `advisor_profile_approvals`).
- **No se invalidan filter_runs cuando la preference cambia.** Si el advisor crea una preferencia nueva, los filter_runs viejos quedan `is_current=true` hasta que se corra un filter nuevo. Decisión: el caller controla cuándo recalcular; un filter "huérfano" sigue siendo válido como snapshot histórico.
- **No hay reconciliación con AIInvestmentPreferencesResponse legacy.** Los dos endpoints `/ai/investment-preferences` (Phase 1, Commit 7 con logging) y `/cases/{id}/investment-preferences` (Phase 2 Commit 11) coexisten; el primero NO persiste preference como entity, solo devuelve el structured result. Migración / deprecación queda para iteración futura.

---

## Fase 2 — CasePortfolioProposal case-scoped ✅ (Commit 12)

### Estado actual

Duodécimo commit de Fase 2 — generación de propuestas de portfolio dentro del case usando el `PortfolioGenerationCoordinator` existente sobre el universo filtrado del case y el `RiskBudget` derivado del approved profile. Snapshot completo persistido (risk_budget + snapshots + candidates + warnings + status), append-only con `is_current` management.

#### Archivos creados / modificados

- **`migrations/0006_case_portfolio_proposals.sql`** — nueva migración:
  - Tabla `case_portfolio_proposals(proposal_id PK, case_id NOT NULL FK→advisory_cases, filter_run_id NOT NULL FK→case_universe_filter_runs, approved_profile_id NULL FK→advisor_profile_approvals, profile_name NOT NULL, risk_budget_json, snapshots_json, candidates_json, warnings_json, status NOT NULL, created_by_advisor_id NULL FK→advisors, created_at_utc, is_current INTEGER DEFAULT 1)` + 4 índices.

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — ampliado con:
  - `SQLiteCaseUniverseFilterRunRepository.get_current_for_case(case_id)` — devuelve el `is_current=1` más reciente del case (necesario para resolver `filter_run_id` default en el endpoint).
  - `ALLOWED_PORTFOLIO_PROPOSAL_STATUSES = {completed, blocked_insufficient_universe, blocked_insufficient_diversification_capacity, infeasible}`.
  - `SQLiteCasePortfolioProposalRepository` con `create`, `get`, `list_by_case`, `get_current_for_case`, `mark_previous_not_current`. IDs `case_portfolio_proposal_NNNNNN`. `risk_budget_json` como dict canonical; `snapshots_json`/`candidates_json`/`warnings_json` envueltos en `{"items": [...]}` (mismo patrón que filter_runs).

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con:
  - `_ALLOWED_PORTFOLIO_VARIANT_POLICIES = {"standard"}` constant.
  - `CasePortfolioProposalCreateRequest` (`filter_run_id` opt, `approved_profile_id` opt, `variant_policy="standard"` con validator).
  - `CasePortfolioProposalResponse`, `CasePortfolioProposalListResponse`.

- **`src/risk_first_advisory/api_layer/main.py`** — agregado:
  - Helpers `_reconstruct_instrument_from_dict(d)` (reconstruye `FinancialInstrument` desde el snapshot persistido del filter run; preserva trazabilidad sin re-cargar CSV); `_serialize_snapshot_for_proposal(snap)` (mismo shape que `FilteredSnapshotResponse`); `_serialize_candidate_for_proposal(variant_name, portfolio, meta)` (mismo shape que `LivePortfolioCandidateResponse`, weights ordenados mayor→menor con threshold `>1e-6`).
  - 2 endpoints:

  | Endpoint | RBAC | Descripción |
  |---|---|---|
  | `POST /cases/{case_id}/portfolio-proposal` | advisor, admin | Resuelve filter_run + approved_profile (current o explícito), reconstruye instruments, corre adapter → ReturnEstimator → CovarianceEngine → PortfolioGenerationCoordinator, persiste proposal con status, marca previous, emite AuditEvent. |
  | `GET /cases/{case_id}/portfolio-proposal` | admin, advisor, compliance, viewer | Lista proposals ordenadas por `created_at_utc` asc. |

  - Helper interno `_persist_and_return(status, candidates, warnings)` factoriza el insert+mark+audit para las 4 rutas de status (blocked × 2, infeasible × 2 caminos, completed).

- **`tests/integration/test_api_case_portfolio_proposal.py`** — 37 tests en 6 clases:
  - `TestCreate` (13): 201, prefix `case_portfolio_proposal_`, case_id/filter_run_id/approved_profile_id correctos, profile_name=moderado, risk_budget poblado, snapshots no vacío, candidates no vacío en status completed, status válido, is_current=true, GET cuenta 1, segundo POST marca primero `is_current=false`.
  - `TestValidation` (10): missing case (POST/GET) → 404; CLOSED → 409; sin approved profile → 409; sin universe filter → 409; filter_run de otro case → 422 ("belongs to case"); approval de otro case → 422; variant_policy inválido → 422; filter_run unknown → 422; approval unknown → 422.
  - `TestRBACPost` (5): 401, 403 (compliance/viewer), 201 (advisor/admin).
  - `TestRBACGet` (3): 401, 200 (compliance/viewer).
  - `TestAudit` (2): `portfolio_proposal_generated` con payload metadata (proposal_id, candidate_count, status); `verify_chain` intact.
  - `TestNoRegression` (4): `/ai/filtered-portfolio-demo`, `/advisor/profile-approval`, `/health`, `/auth/me`.

- **`tests/unit/test_migrations.py`** — actualizado: `PHASE2_TABLES += case_portfolio_proposals`, `REQUIRED_INDEXES += 4 nuevos`, `TOTAL_MIGRATIONS = 6`, assert fila `0006` en schema_migrations.

**Total tests tras este commit:** 2827 (todos pasando). Δ = +37 integration.

#### Decisiones de diseño

1. **Reconstrucción de `FinancialInstrument` desde el snapshot del filter run** (no se re-carga CSV). Preserva la trazabilidad universe → proposal: si el CSV cambia después del filter run, el proposal sigue usando el universo congelado al momento del filter. Defensivo y correcto incluso si el `source_universe` no fuera un fixture en disco.

2. **`filter_run_id` NOT NULL en la tabla**. Cada propuesta queda anclada al universo filtrado concreto. Sin filter run no hay propuesta — la FK lo refuerza.

3. **`approved_profile_id` NULL-able**. En escenarios edge (case con `advisory_cases.current_approved_profile_id` que apunta a un approval borrado, o flujos futuros donde el profile se setea fuera del approval flow) el proposal puede existir sin approval explícito. Camino productivo siempre lo llena (validamos current_approved_profile_id antes).

4. **`profile_name` derivado del approval con fallback**: `approved_profile or proposed_profile`. En `decision="approve"` ambos coinciden; en `decision="reject"` `approved_profile` es None y caemos al `proposed_profile`. Para `reject` el endpoint NO debería llegar acá normalmente (porque `current_approved_profile_id` no apunta a un reject), pero el fallback evita un crash si el caller pasa explícitamente un `approved_profile_id` de un reject. Si no hay ninguno válido → 422 con mensaje de perfil inválido.

5. **Status alineados con `/ai/filtered-portfolio-demo` legacy**: `completed`, `blocked_insufficient_universe`, `blocked_insufficient_diversification_capacity`, `infeasible`. Mismo set, mismo threshold (`< 3` snapshots usables; `< math.ceil(1/max_single_asset)` para diversificación). Coherencia entre el flujo legacy y el case-scoped.

6. **El proposal SIEMPRE se persiste**, incluso en status blocked/infeasible. Razón: trazabilidad — el advisor necesita ver "intenté generar un portfolio con este filter run y falló por estos warnings". Si el caller solo quiere completed, filtra en GET. Esta decisión es consistente con `/ai/filtered-portfolio-demo` que también persiste todos los estados.

7. **`_persist_and_return` helper interno** para no duplicar el insert+mark+audit pattern entre las 4 ramas de status. Trade-off: el factoring sacrifica linealidad por evitar 4× la misma lógica.

8. **`client_id` opaco al coordinator: `case_id`**. `PortfolioGenerationCoordinator.generate(client_id=case_id, ...)` — el coordinator solo usa client_id como identificador opaco para tracking interno; pasarle `case_id` evita exponer el client_id real del CRM y mantiene la trazabilidad case → portfolio.

9. **Snapshots persistidos incluyen TODOS los del adapter** (no solo los `is_usable`). Razón: el auditor puede inspeccionar qué snapshots fueron descartados como no usables (e.g., missing return/volatility) y por qué (`snap.notes`). El coordinator solo recibe los usables, pero la persistencia preserva el conjunto completo.

10. **`is_current` mantenido por el endpoint** vía `mark_previous_not_current` (mismo patrón que Commits 10/11). Cada POST nuevo invalida los previos del case.

11. **`get_current_for_case` agregado a `SQLiteCaseUniverseFilterRunRepository`** (faltaba; este commit lo necesita para resolver `filter_run_id` default). Mismo patrón que en `case_investment_preferences` y `case_portfolio_proposals`.

12. **Cross-resource validation explícita** para `filter_run_id` y `approved_profile_id` (mensaje "belongs to case"). Mismo patrón que en todos los endpoints case-scoped previos.

13. **CLOSED case → 409** (mismo patrón que KYC / análisis / approval / preferences / filter).

14. **AuditEvent payload solo metadata** (proposal_id, candidate_count, status, profile_name, filter_run_id, approved_profile_id). No duplica risk_budget ni candidates serialized — el auditor navega por `proposal_id`.

15. **NO se actualiza `advisory_cases.current_*` desde este endpoint**. El proposal NO es selección — eso queda para `current_portfolio_selection_id` (item 12 del pending list). `case_portfolio_proposals.is_current=1` indica "última propuesta generada", no "variant seleccionada".

16. **`variant_policy="standard"` solo** en este commit. El validator del schema lo restringe; el endpoint no lo usa todavía (la coordinator policy es implícita: genera DEFENSIVE/BALANCED/GROWTH siempre). Field reservado para extensiones futuras (e.g., generar solo BALANCED, generar 5 variants, etc.).

17. **Imports de portfolio/coordinator dentro de la función** (en vez de top-level). Mismo patrón que `/ai/filtered-portfolio-demo`. Evita penalty de import time en startup para endpoints que no se usan, y mantiene aislamiento entre layers (api_layer no carga portfolio_layer eager).

#### Tabla de RBAC actualizada (nuevos endpoints)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `POST /cases/{id}/portfolio-proposal` | ✅ 201 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /cases/{id}/portfolio-proposal` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |

#### Lo que NO está en este commit

- **No hay selection (item 12).** El proposal genera N candidates (DEFENSIVE/BALANCED/GROWTH); el advisor todavía no elige uno desde el flow case-scoped. `current_portfolio_selection_id` queda `NULL`.
- **No hay case-scoped override-approval (item 13).** Si una variant tiene `risk_budget_exceeded=True` y `requires_advisor_override=True`, el advisor todavía no puede aprobar el override desde el flow case-scoped (sigue siendo via `/advisor/override-approval` legacy client-scoped).
- **No hay case-scoped report generation (item 14).** El proposal se persiste como dict; no se genera markdown/PDF audit-ready por proposal.
- **`source_universe` se hereda del filter_run** (no del POST request). El campo `source_universe` en `case_portfolio_proposals` no existe; se asume que es el del `filter_run` referenciado.
- **Reconstrucción de instrumentos asume shape estable del dict persistido.** Si una migración futura cambia el shape de `case_universe_filter_runs.eligible_instruments_json`, hay que adaptar `_reconstruct_instrument_from_dict`. Hoy no hay versionado del shape.
- **No hay reconciliación con `/advisor/portfolio-selection` legacy** (Phase 1, client-scoped). Coexisten sin conflicto; deprecación queda para item 22.
- **`variant_policy` es campo reservado sin uso real**. Solo acepta `"standard"`. Futuras políticas (e.g., "growth_only", "5_variants") requieren cambios en el endpoint.
- **No hay endpoint detail** `/cases/{id}/portfolio-proposal/{proposal_id}`. GET list devuelve todos; se filtra en cliente. Si crece la necesidad, agregar sin schema changes.
- **Cross-validation entre filter_run y approved_profile**: el endpoint NO valida que el filter_run se haya hecho DESPUÉS o ANTES del approval. Decisión: temporalmente independientes. Si el advisor quiere coherencia, debe regenerar el filter después de cambiar el approval. Documentar este matiz en UX cuando exista el workbench.

---

## Fase 2 — CaseOverrideApproval case-scoped ✅ (Commit 13)

### Estado actual

Decimotercer commit de Fase 2 — decisión humana del asesor sobre una variante de portfolio que excede el RiskBudget aprobado y requiere advisor override (típicamente GROWTH). Anclado a un `CasePortfolioProposal` concreto y a un `candidate_variant` específico.

#### Archivos creados / modificados

- **`migrations/0007_case_override_approvals.sql`** — nueva migración:
  - Tabla `case_override_approvals(override_approval_id PK, case_id NOT NULL FK→advisory_cases, proposal_id NOT NULL FK→case_portfolio_proposals, candidate_variant NOT NULL, decision NOT NULL, reason_codes_json, exceeded_constraints_json, rationale NOT NULL, source NOT NULL, advisor_id NULL FK→advisors, created_at_utc, is_current INTEGER DEFAULT 1)` + 3 índices.

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — ampliado con:
  - `ALLOWED_OVERRIDE_APPROVAL_DECISIONS = {"approve", "reject"}`.
  - `SQLiteCaseOverrideApprovalRepository` con `create`, `get`, `list_by_case`, `get_current_for_case`, `mark_previous_not_current`. IDs `case_override_approval_NNNNNN`. `reason_codes_json` y `exceeded_constraints_json` envueltos en `{"items": [...]}` (mismo patrón).

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con:
  - `_ALLOWED_OVERRIDE_VARIANTS = {DEFENSIVE, BALANCED, GROWTH}`, `_ALLOWED_OVERRIDE_DECISIONS = {approve, reject}`.
  - `CaseOverrideApprovalCreateRequest` con validators (variant en allowlist, decision en allowlist, rationale/source no whitespace, reason_codes/exceeded_constraints validados via `_validate_str_list_no_empty` reutilizado).
  - `CaseOverrideApprovalResponse`, `CaseOverrideApprovalListResponse`.

- **`src/risk_first_advisory/api_layer/main.py`** — agregado:
  - Constante `_OVERRIDE_EVENT_BY_DECISION` mapping `approve/reject` → `advisor_override_approved/_rejected`.
  - Helper `_candidate_requires_override(candidate_dict)` — inspecciona `metadata.requires_advisor_override` del dict persistido por el proposal.
  - 2 endpoints:

  | Endpoint | RBAC | Descripción |
  |---|---|---|
  | `POST /cases/{case_id}/override-approval` | advisor, admin | Resuelve proposal (current o explícito), valida que sea `status=completed`, busca el candidate por variant, exige que requiera override, persiste approval + mark_previous_not_current + AuditEvent. |
  | `GET /cases/{case_id}/override-approval` | admin, advisor, compliance, viewer | Lista approvals ordenadas por `created_at_utc` asc. |

- **`tests/integration/test_api_case_override_approval.py`** — 41 tests en 7 clases:
  - `TestCreateApprove` (12): guardrail que el fixture genera al menos un override-requiring variant (rompe rápido si la premisa cambia); 201; prefix `case_override_approval_`; proposal_id/candidate_variant/decision/reason_codes/exceeded_constraints/advisor_id correctos; is_current=true; GET cuenta 1.
  - `TestReject` (1): reject → 201.
  - `TestCurrent` (1): segundo POST marca primero `is_current=false`.
  - `TestValidation` (13): missing case (POST/GET) → 404; CLOSED → 409; sin proposal → 409 ("no portfolio proposal"); proposal de otro case → 422 ("belongs to case"); proposal unknown → 422; candidate ausente del proposal → 422 (skippeable si el fixture genera los 3); candidate sin override required → 422 ("does not require advisor override"); decision/rationale/source/reason_codes/exceeded_constraints inválidos → 422.
  - `TestRBACPost` (5): 401, 403 (compliance/viewer), 201 (advisor/admin).
  - `TestRBACGet` (3): 401, 200 (compliance/viewer).
  - `TestAudit` (3): approve emite `advisor_override_approved`; reject emite `advisor_override_rejected`; payload contiene `override_approval_id`/`candidate_variant`/`decision`; `verify_chain` intact.
  - `TestNoRegression` (4): `/advisor/override-approval` legacy, `/ai/filtered-portfolio-demo`, `/health`, `/auth/me`.

- **`tests/unit/test_migrations.py`** — actualizado: `PHASE2_TABLES += case_override_approvals`; `REQUIRED_INDEXES += 3 nuevos`; `TOTAL_MIGRATIONS = 7`; assert fila `0007` en schema_migrations.

**Total tests tras este commit:** 2868 (todos pasando). Δ = +41 integration.

#### Decisiones de diseño

1. **`proposal_id` NOT NULL en la tabla**. Cada override approval queda anclado a una propuesta concreta. Sin proposal no hay candidate sobre el cual decidir.

2. **`candidate_variant` se valida contra el proposal en runtime, no solo schema**. El schema acepta `{DEFENSIVE, BALANCED, GROWTH}` (allowlist estática), pero el endpoint exige adicionalmente que el variant esté presente en `proposal.candidates`. Si el proposal no generó esa variant (e.g., infeasibility puntual) → 422.

3. **422 si el candidate NO requiere override** (decisión documentada). Política: override approval es para los casos donde la variant excede el budget aprobado. Si una variant ya respeta el budget, no hay nada que aprobar/rechazar como override. El endpoint legacy permite cualquier candidate; el case-scoped es más estricto.

4. **`proposal.status` debe ser `"completed"`**. Override sobre proposals blocked/infeasible no tiene sentido (no hay candidates). 409 con mensaje explícito.

5. **`is_current` a nivel case** (no por proposal_id ni candidate_variant). Decisión simple: un override approval vigente por case. Si el advisor quiere revisar dos variants del mismo proposal en paralelo, el segundo POST invalida el primero. La granularidad fina queda para futuro si compliance la pide.

6. **`_candidate_requires_override` confía en `metadata.requires_advisor_override`** poblado por `_serialize_candidate_for_proposal` (Commit 12). No re-evalúa la lógica del coordinator — usa el snapshot persistido como fuente de verdad.

7. **`reason_codes` y `exceeded_constraints` los declara el caller**, no se derivan automáticamente del candidate. Razón: el advisor puede declarar reason codes adicionales que no aparecen en el candidate metadata (e.g., contexto del cliente). Si el caller no manda nada, queda lista vacía.

8. **Reusa `_validate_str_list_no_empty`** de schemas.py (existente desde Phase 1 `/advisor/override-approval`). Mismo comportamiento: cada item debe ser string no vacío.

9. **Audit event mapping con dict literal** (`_OVERRIDE_EVENT_BY_DECISION`), mismo patrón que profile approval (Commit 10).

10. **AuditEvent payload solo metadata** (override_approval_id, proposal_id, candidate_variant, decision, advisor_id). No duplica reason_codes / exceeded_constraints — auditor navega por `override_approval_id` si necesita el detalle.

11. **Soft FK lookup para `advisor_id`** (mismo patrón que todos los commits previos): si `advisor.advisor_id` del token existe como entity → se usa; si no → None.

12. **Tabla coexiste con `records` legacy.** El endpoint `/advisor/override-approval` Phase 1 (client_id-scoped, sobre `records.record_type='advisor_override_approval'`) sigue vivo y no entra en conflicto. Deprecación queda para item 22.

13. **`mark_previous_not_current(exclude_id=new_id)`** después del insert para evitar invalidar el approval recién creado. Mismo patrón que profile_approvals (Commit 10).

14. **Test fixture usa `moderado` profile**. La razón: bajo el universo CSV actual, GROWTH bajo `moderado` excede el budget y `requires_advisor_override=True`. Bajo `conservador`, el optimizer mantiene todas las variants dentro del budget (no se requiere override) — `conservador` ya es muy restrictivo, no hay donde "exceder más". El guardrail `test_proposal_has_at_least_one_override_variant` rompe rápido si esta premisa cambia.

#### Tabla de RBAC actualizada (nuevos endpoints)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `POST /cases/{id}/override-approval` | ✅ 201 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /cases/{id}/override-approval` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |

#### Lo que NO está en este commit

- **No hay portfolio selection todavía** (item 13). El override approval autoriza al advisor a presentar la variant exceeding-budget al cliente, pero el "elegirla" como final queda para el endpoint de selection (item 13).
- **`current_override_approval_id` NO existe en `advisory_cases`.** El puntero no se materializa en la tabla del case porque no es necesario para portfolio selection (que apuntará a la variant elegida, no al override).
- **No hay reconciliación con `/advisor/override-approval` legacy** (Phase 1, client-scoped). Coexisten; deprecación queda para item 22.
- **Override approvals huérfanos**: si el proposal subyacente cambia (nuevo proposal), el override approval previo queda `is_current=false` pero sigue referenciando el proposal_id viejo (FK válido). El nuevo flow debe re-aprobar override contra el proposal nuevo si quiere mantener consistencia. Documentado para UX.
- **No se valida que `reason_codes` / `exceeded_constraints` coincidan con el candidate**. El advisor puede declarar reason codes que NO aparecen en `candidate.reason_codes` (uso intencional: documentación adicional del advisor). Si compliance requiere validación cruzada, se agrega en una iteración futura.
- **No hay endpoint detail** `/cases/{id}/override-approval/{override_approval_id}`. GET list devuelve todos; filtrar en cliente.
- **No hay actor_role explícito en el payload** del response (solo `advisor_id`). El `actor_role` se preserva en el audit event vía `_pick_actor_role`. Si el caller necesita el rol en el response, se agrega en una iteración futura.

---

## Fase 2 — CasePortfolioSelection case-scoped ✅ (Commit 14)

### Estado actual

Decimocuarto commit de Fase 2 — decisión final del asesor sobre qué variant del proposal se presenta al cliente. Cierra el loop entre `CasePortfolioProposal`, `CaseOverrideApproval` y `advisory_cases.current_portfolio_selection_id` + status `PORTFOLIO_SELECTED`.

#### Archivos creados / modificados

- **`migrations/0008_case_portfolio_selections.sql`** — nueva migración:
  - Tabla `case_portfolio_selections(selection_id PK, case_id NOT NULL FK→advisory_cases, proposal_id NOT NULL FK→case_portfolio_proposals, override_approval_id NULL FK→case_override_approvals, selected_variant NOT NULL, selected_candidate_json, rationale, source, advisor_id NULL FK→advisors, created_at_utc, is_current INTEGER DEFAULT 1)` + 4 índices.

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — ampliado con:
  - `SQLiteAdvisoryCaseRepository.update_current_portfolio_selection(case_id, selection_id | None)` — setter directo del puntero (mismo patrón que `update_current_approved_profile` y `update_current_kyc_submission`).
  - `SQLiteCasePortfolioSelectionRepository` con `create`, `get`, `list_by_case`, `get_current_for_case`, `mark_previous_not_current`. IDs `case_portfolio_selection_NNNNNN`. `selected_candidate_json` como dict canonical (snapshot completo del candidate elegido al momento de la selección).

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con:
  - `_ALLOWED_SELECTION_VARIANTS = {DEFENSIVE, BALANCED, GROWTH}`.
  - `CasePortfolioSelectionCreateRequest` (`proposal_id` opt, `selected_variant`, `override_approval_id` opt, `rationale`, `source="manual"`) con validators (variant allowlist, rationale/source no whitespace, IDs no empty).
  - `CasePortfolioSelectionResponse`, `CasePortfolioSelectionListResponse`.

- **`src/risk_first_advisory/api_layer/main.py`** — agregado:
  - 2 endpoints:

  | Endpoint | RBAC | Descripción |
  |---|---|---|
  | `POST /cases/{case_id}/portfolio-selection` | advisor, admin | Resuelve proposal + candidate. Si requires_override: exige override aprobado válido (matching proposal + variant + decision=approve). Si no requires_override: rechaza override_approval_id explícito. Persiste selection + mark_previous + actualiza puntero + transiciona status (IN_PROGRESS → PORTFOLIO_SELECTED). AuditEvent `portfolio_selected`. |
  | `GET /cases/{case_id}/portfolio-selection` | admin, advisor, compliance, viewer | Lista selections ordenadas por `created_at_utc` asc. |

- **`tests/integration/test_api_case_portfolio_selection.py`** — 45 tests en 8 clases:
  - `TestCreateNoOverride` (11): variant que no requiere override; selection_id prefix; proposal_id/selected_variant correctos; selected_candidate con weights y expected_return; override_approval_id=None; advisor_id desde entity; is_current=true; GET cuenta 1; case.current_portfolio_selection_id actualizado; case.status=PORTFOLIO_SELECTED.
  - `TestCreateWithOverride` (3): variant que requiere override sin override → 409 ("requires an approved override"); con override explícito → 201; con current approved override (id omitido) → 201.
  - `TestCurrent` (2): segunda selection marca primera `is_current=false`; puntero del case apunta a la última.
  - `TestValidation` (15): missing case (POST/GET) → 404; CLOSED → 409; sin proposal → 409; proposal de otro case → 422; selected_variant ausente en proposal → 422; override con decision=reject → 409; override de otro case → 422; override de otro proposal → 422; override para otro variant → 422; non-override variant con override_approval_id → 422; rationale/source whitespace → 422; selected_variant inválido (allowlist) → 422; proposal_id unknown → 422.
  - `TestRBACPost` (5): 401, 403 (compliance/viewer), 201 (advisor/admin).
  - `TestRBACGet` (3): 401, 200 (compliance/viewer).
  - `TestAudit` (2): `portfolio_selected` con payload metadata; `verify_chain` intact.
  - `TestNoRegression` (4): `/advisor/portfolio-selection` legacy, `/ai/filtered-portfolio-demo`, `/health`, `/auth/me`.

- **`tests/unit/test_migrations.py`** — actualizado: `PHASE2_TABLES += case_portfolio_selections`; `REQUIRED_INDEXES += 4 nuevos`; `TOTAL_MIGRATIONS = 8`; assert fila `0008`.

**Total tests tras este commit:** 2913 (todos pasando). Δ = +45 integration.

#### Decisiones de diseño

1. **`proposal_id` NOT NULL** en la tabla. Una selection sin proposal no tiene sentido — el candidate vive en el proposal.

2. **`override_approval_id` NULL-able** porque solo aplica para variants que requieren override. Variants dentro del budget no necesitan override.

3. **Validación cross-resource de override en 3 dimensiones**: case_id + proposal_id + candidate_variant + decision=approve. Cualquier mismatch → 422 (excepto reject que es 409: el override existe y es válido, pero su decision no permite la selección).

4. **Si el candidate NO requiere override y el caller pasa `override_approval_id` → 422**. Política estricta: el caller debe ser explícito sobre que sabe que el variant no requiere override. Evita usos incorrectos.

5. **Si el candidate requiere override y NO se pasa `override_approval_id`**: el endpoint busca el `current` override approval del case y exige que coincida (proposal + variant + decision=approve). Si no encuentra → 409. Permite flujos donde el advisor aprobó override antes y ahora selecciona sin re-pasar el ID explícitamente.

6. **`selected_candidate_json` persiste el candidate completo** al momento de la selección. Snapshot independiente del proposal: si el proposal se regenera (nuevo proposal_id, candidates cambian), la selection conserva la foto del candidate original. Trazabilidad clave para compliance.

7. **Status transition explícita**: `IN_PROGRESS → PORTFOLIO_SELECTED` vía `update_status` (FSM). Si ya está en `PORTFOLIO_SELECTED` (re-selección), no-op (idempotente). Si está en `DRAFT` (path no productivo), no transicionamos. `CLOSED` ya rechazado al inicio.

8. **`is_current` a nivel case**. Cada nueva selection invalida las previas. Política simple: una selection vigente por case. Granularidad fina (por proposal o por variant) queda para futuro si compliance lo pide.

9. **`current_portfolio_selection_id` se actualiza vía setter directo** (no FSM). Mismo patrón que `current_kyc_submission_id` y `current_approved_profile_id` (commits 8 y 10).

10. **CLOSED case → 409** (patrón consistente con todos los endpoints case-scoped previos).

11. **Reusa `_candidate_requires_override` helper** (definido en Commit 13). Misma fuente de verdad para "este candidate requiere override".

12. **AuditEvent payload solo metadata** (selection_id, proposal_id, override_approval_id, selected_variant, advisor_id). El `selected_candidate` completo vive en la tabla; auditor navega por `selection_id`.

13. **Soft FK lookup para `advisor_id`** (patrón consistente).

14. **Tabla coexiste con `records` legacy** (`record_type='advisor_portfolio_selection'`, client-scoped, Phase 1) sin conflicto. Deprecación queda para iteración futura.

15. **Distinción 409 vs 422 en validaciones de override**:
   - `proposal_id` / `candidate_variant` no encuentran un match → 422 (request payload tiene una referencia inválida).
   - `decision='reject'` o "no hay override válido current" → 409 (el recurso existe pero no permite la selección por estado).
   - Mismo principio: 422 para "request payload roto", 409 para "estado del recurso no compatible".

16. **`get_current_for_case` agregado a `SQLiteCasePortfolioSelectionRepository`** para futuro (e.g., report generation pickeará la selection current).

17. **Test fixture usa `moderado`** (consistente con Commit 13) para garantizar que GROWTH requiera override y poder testear ambos paths (con y sin override).

#### Tabla de RBAC actualizada (nuevos endpoints)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `POST /cases/{id}/portfolio-selection` | ✅ 201 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /cases/{id}/portfolio-selection` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |

#### Lo que NO está en este commit

- **No hay case-scoped report generation** (item 14). La selection define la cartera final pero no se genera markdown / PDF audit-ready desde el case flow todavía.
- **No hay case summary endpoint** (e.g., `GET /cases/{id}/summary` con KYC + analysis + approval + preferences + filter + proposal + override + selection en un solo response). Cada recurso se consulta separado.
- **No hay validación de lifecycle formal**. El advisor puede hacer POST a `/portfolio-selection` en un case que está `DRAFT` (sin KYC, sin proposal, etc.) — el endpoint rechazará por "no proposal" (409), pero no hay un validator que diga "el case no está listo para selection". La FSM de status implícita lo cubre parcialmente.
- **Re-selección sobre proposal viejo**: si el advisor cambia de opinión y quiere seleccionar otro variant del MISMO proposal, basta con un nuevo POST (mark_previous_not_current). Si quiere usar otro proposal, debe pasar `proposal_id` explícito. No hay UX guidance todavía.
- **`current_portfolio_selection_id` apunta solo al último**; el caller debe filtrar el listado por `is_current=true` si quiere ese subset. Simplificación: no agregamos un endpoint dedicated `/current` ya que `GET /cases/{id}` ya expone el puntero.
- **No hay endpoint detail** `/cases/{id}/portfolio-selection/{selection_id}`. GET list devuelve todos; filtrar en cliente.
- **No reconciliación con `/advisor/portfolio-selection` legacy** (Phase 1, client-scoped). Coexisten sin conflicto.
- **No reconciliación con override approvals huérfanos**: si una override approval queda referenciada por una selection vieja (is_current=false) y luego se genera un nuevo proposal sin override, la selection vieja sigue válida en su snapshot. El nuevo flow debe re-aprobar override si quiere mantener una selection vigente con override.

---

## Fase 2 — CaseReport case-scoped ✅ (Commit 15)

### Estado actual

Decimoquinto commit de Fase 2 — cierra el flujo case-scoped end-to-end. El asesor puede generar un reporte Markdown determinístico que consolida la selección final del case, listo para presentar al cliente (o exportar a PDF en un commit futuro).

#### Archivos creados / modificados

- **`migrations/0009_case_reports.sql`** — nueva migración:
  - Tabla `case_reports(report_id PK, case_id NOT NULL FK→advisory_cases, portfolio_selection_id NULL FK→case_portfolio_selections, portfolio_proposal_id NULL FK→case_portfolio_proposals, report_type NOT NULL, status NOT NULL, version INT NOT NULL, markdown TEXT, metadata_json, generated_by_advisor_id NULL FK→advisors, created_at_utc, is_current INTEGER DEFAULT 1, UNIQUE(case_id, version))` + 4 índices.

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — `SQLiteCaseReportRepository` con `create`, `get`, `list_by_case`, `get_current_for_case`, `mark_previous_not_current`. IDs `case_report_NNNNNN`. `version = MAX(version)+1` por case (mismo patrón que KYC submissions). `markdown` se persiste como TEXT plano; `metadata_json` en canonical JSON.

- **`src/risk_first_advisory/reporting_layer/case_markdown_report.py`** — nuevo módulo:
  - `CaseMarkdownReportGenerator.generate(case_data, selection_data, proposal_data=None, approval_data=None, override_data=None, generated_at_utc=None) → (markdown, metadata)`.
  - Sin side-effects (puro). Devuelve tuple para que el endpoint persista ambos.
  - Secciones: título, metadata, perfil aprobado, variante seleccionada, métricas, distribución de pesos (ordenada determinísticamente), override approval (si aplica), disclaimers.
  - 4 disclaimers explícitos: NO es recomendación automática, requiere revisión advisor, datos pueden ser proxy/demo, IA NO aprueba la recomendación final.

- **`src/risk_first_advisory/reporting_layer/__init__.py`** — exporta `CaseMarkdownReportGenerator`.

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con:
  - `_ALLOWED_REPORT_TYPES = {portfolio_recommendation}`, `_ALLOWED_REPORT_STATUSES = {draft, final}`.
  - `CaseReportCreateRequest` (`portfolio_selection_id` opt, `report_type="portfolio_recommendation"`, `status="draft"`).
  - `CaseReportResponse` (incluye `markdown` completo + `metadata` dict).
  - `CaseReportListResponse`.

- **`src/risk_first_advisory/api_layer/main.py`** — agregado:
  - Import `CaseMarkdownReportGenerator` desde reporting_layer.
  - 3 endpoints:

  | Endpoint | RBAC | Descripción |
  |---|---|---|
  | `POST /cases/{case_id}/reports` | advisor, admin | Resuelve selection (explícita o current), carga proposal/approval/override, genera markdown, persiste con version siguiente, mark_previous_not_current, AuditEvent `report_generated`. |
  | `GET /cases/{case_id}/reports` | admin, advisor, compliance, viewer | Lista reports ordenados por version asc. |
  | `GET /cases/{case_id}/reports/{report_id}` | admin, advisor, compliance, viewer | Detalle; 404 si reporte no existe O pertenece a otro case (no exponemos IDs cross-case). |

- **`tests/integration/test_api_case_reports.py`** — 45 tests en 7 clases:
  - `TestCreate` (18): 201; prefix `case_report_`; version=1; case_id/selection_id/proposal_id correctos; report_type default + status draft + status=final supported; markdown no vacío + contiene case_id + selected_variant + disclaimer IA/advisor; metadata dict con campos clave; is_current=true; GET list 1; GET single OK; segundo POST → version 2 + previous is_current=false.
  - `TestValidation` (11): missing case POST/GET-list/GET-single → 404; sin selection → 409; selection de otro case → 422; selection unknown → 422; report_type/status inválidos → 422; CLOSED → 409; report missing → 404; report de otro case → 404.
  - `TestRBACPost` (5): 401, 403 (compliance/viewer), 201 (advisor/admin).
  - `TestRBACGet` (6): 401 list y single; compliance/viewer 200 en ambos.
  - `TestAudit` (2): `report_generated` con payload (report_id, version); `verify_chain` intact.
  - `TestNoRegression` (3): `/ai/filtered-portfolio-demo`, `/health`, `/auth/me`.

- **`tests/unit/test_migrations.py`** — actualizado: `PHASE2_TABLES += case_reports`; `REQUIRED_INDEXES += 4 nuevos`; `TOTAL_MIGRATIONS = 9`; assert fila `0009`.

**Total tests tras este commit:** 2958 (todos pasando). Δ = +45 integration.

#### Decisiones de diseño

1. **Nuevo generator en `reporting_layer`** (`CaseMarkdownReportGenerator`), no se reusan los existentes (`MarkdownReportGenerator` espera `AdvisoryWorkflowResult` legacy; `AIFilteredPortfolioReportGenerator` espera un payload distinto). Ventaja: el generator case-scoped trabaja con dicts plain del repo layer sin tener que mapear a/desde domain objects.

2. **Generator es puro** (sin IO, sin DB). El endpoint arma el contexto (case + selection + proposal + approval + override), invoca `generate`, y persiste. Esto hace al generator testeable directamente sin DB.

3. **`generate` devuelve `(markdown, metadata)` tuple**. El metadata dict captura IDs y atributos clave (selection_id, proposal_id, approved_profile, selected_variant, expected_return_annual, volatility_annual, asset_count, generated_at_utc) para que el endpoint los persista sin re-derivar.

4. **`version` monotónica por `case_id` (UNIQUE(case_id, version))**. Cada POST nuevo incrementa `version`. Mismo patrón que `kyc_submissions` (Commit 8). Race condition concurrente → `EntityConflictError` (UNIQUE) → 409.

5. **`markdown` como TEXT plano**, NO en canonical JSON. Razón: es texto ya formateado; envolverlo en JSON agregaría una capa innecesaria. `metadata_json` sí en canonical JSON (es un dict estructurado).

6. **Política de resolución de `portfolio_selection_id`**:
   - Explícito en request → debe pertenecer al case (422 si no).
   - Omitido → usa `case.current_portfolio_selection_id` (puntero materializado en Commit 14).
   - Si no hay current → 409 con mensaje "POST a portfolio-selection first".

7. **proposal/approval/override son enrichments opcionales**. El endpoint los carga "best effort" para enriquecer el markdown: si la FK del proposal está rota (caso edge defensivo), el report igual se genera con el snapshot `selected_candidate` que vive en la selection.

8. **CLOSED case → 409** (patrón consistente con todos los endpoints case-scoped previos).

9. **GET single con cross-case isolation**: si el `report_id` pertenece a otro `case_id`, devolvemos **404** (no 403). Razón: no exponer la existencia de IDs entre cases. Mismo principio que la mayoría de APIs REST con scope multi-tenant.

10. **`portfolio_selection_id` y `portfolio_proposal_id` NULL-able en la tabla** (FK opcional). Aunque el endpoint productivo siempre los puebla, el repo permite reports sin esos vínculos (e.g., backfill / scripts internos). Defensa contra over-coupling.

11. **AuditEvent payload solo metadata** (report_id, version, type, status, IDs vinculados). El markdown completo NO se duplica en el audit chain; auditor navega por `report_id` para inspeccionar.

12. **Soft FK lookup para `generated_by_advisor_id`** (patrón consistente con todos los commits previos).

13. **Disclaimers como constante module-level** (`_DISCLAIMERS`). Cambiarlos requiere edit explícito, lo que es bueno: son compliance-relevant. Si una iteración futura quiere disclaimers por firm o por jurisdiction, se parametriza vía argumento al `generate`.

14. **`generated_at_utc` inyectable** en `generate()` (default = `datetime.now(timezone.utc)`). Útil para tests que quieran determinismo total; el endpoint productivo no lo inyecta.

15. **Distribución de pesos ordenada determinísticamente**: `(-weight desc, ticker asc)`. Hace el markdown reproducible byte-a-byte si los inputs son idénticos.

16. **`status` enum mínimo `{draft, final}`**. Workflow más rico (e.g., `draft → reviewed → final → sent`) queda como item 17 del pending list.

17. **No PDF en este commit** (item 15). El markdown es el formato canónico; PDF rendering es una transformación separada (futuro: WeasyPrint, mdpdf, o un servicio externo).

#### Tabla de RBAC actualizada (nuevos endpoints)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `POST /cases/{id}/reports` | ✅ 201 | ✅ 201 | ❌ 403 | ❌ 403 | ❌ 401 |
| `GET /cases/{id}/reports` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |
| `GET /cases/{id}/reports/{report_id}` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |

#### Lo que NO está en este commit

- **No PDF** (item 15). El reporte solo se entrega en markdown.
- **No branding/customization** (item 16). Disclaimers y estructura del markdown son fijos.
- **No lifecycle formal de reports** (item 17). `status` solo distingue `draft` vs `final`; no hay workflow `reviewed → sent → archived` con AuditEvents por transición.
- **No case summary endpoint** (item 18). Cada recurso del case se consulta separado.
- **No download endpoint** (`GET /cases/{id}/reports/{report_id}/download`). El markdown viene en el response JSON; si crece la necesidad de descarga directa con `Content-Type: text/markdown`, se agrega sin cambios de schema.
- **El report NO actualiza el case status**. Generar el reporte no cambia `advisory_cases.status` (sigue en `PORTFOLIO_SELECTED`). La transición a `CLOSED` queda como decisión explícita del advisor vía `PATCH /cases/{id}/status`.
- **No reconciliación con `records` legacy** (`record_type='markdown_report'`, client_id-scoped). Coexisten sin conflicto; deprecación queda para iteración futura.
- **No hay endpoint para regenerar reporte automáticamente** cuando la selection cambia. El advisor debe POST manual a `/reports` para generar la version nueva.
- **No firm-level scoping** sobre estos endpoints (consistente con el resto del sistema).

---

## Fase 2 — Case Summary endpoint ✅ (Commit 16)

### Estado actual

Decimosexto commit de Fase 2 — endpoint sintetizador que devuelve el estado completo de un `AdvisoryCase` en un solo response. Pensado como base para el futuro Case Workbench frontend (item 19): hidratar la vista del caso sin múltiples round-trips.

#### Archivos creados / modificados

- **`src/risk_first_advisory/persistence_layer/entity_repository.py`** — ampliado con:
  - `SQLiteAdvisorProfileApprovalCaseRepository.get_current_for_case(case_id)` (era el único repo case-scoped que NO lo tenía; ahora los 7 lo exponen).

- **`src/risk_first_advisory/api_layer/schemas.py`** — ampliado con:
  - `CaseWorkflowProgressResponse` (9 flags `has_*` + `next_recommended_action` + `completion_ratio`).
  - `CaseAuditSummaryResponse` (`is_intact`, `total_events`, `first_broken_sequence`, `message`).
  - `CaseAISummaryResponse` (`ai_logs_count`, `latest_ai_log_id`, `latest_validation_status`).
  - `CaseSummaryResponse` (case + firm/client/advisor + 9 `current_*` entities + audit + ai + progress).

- **`src/risk_first_advisory/api_layer/main.py`** — agregado:
  - Constantes `_PROGRESS_STEPS_TOTAL = 9`, `_PROGRESS_STEPS_BASE = 8`.
  - Helpers puros: `_proposal_has_override_required`, `_compute_next_recommended_action`, `_compute_completion_ratio`.
  - Endpoint `GET /cases/{case_id}/summary` con resolución best-effort de cada entidad relacionada.

- **`tests/integration/test_api_case_summary.py`** — 39 tests en 6 clases:
  - `TestEmptyCase` (11): case recién creado; case/firm/client/advisor presentes; todos `current_*` None; flags `has_*` False; `next_action=submit_kyc`; `completion_ratio=0.0`; audit con `case_created` intact; `ai_logs_count=0`.
  - `TestFullWorkflow` (10): pipeline completo (KYC → analysis → approval → prefs → filter → proposal → override → selection → report); todos `current_*` presentes; `version=1` en report; `has_report=True`; `next_action=ready_for_review`; `completion_ratio=1.0`; audit intact; AI logs > 0; CLOSED transition cambia `next_action` a `"closed"`.
  - `TestIntermediateStates` (7): después de cada paso del workflow, `next_recommended_action` apunta al siguiente paso correcto (`submit_kyc → run_ai_profile_analysis → approve_profile → record_investment_preferences → run_universe_filter → generate_portfolio_proposal → review_override OR select_portfolio → generate_report`).
  - `TestAuditBroken` (1): mutar `payload_json` directamente en DB → `summary.audit.is_intact=false` + `first_broken_sequence` poblado.
  - `TestRBAC` (5): 401 sin token; 200 para los 4 roles válidos (incluye viewer).
  - `TestValidation` (1): case inexistente → 404.
  - `TestNoRegression` (4): `/reports`, `/portfolio-selection`, `/health`, `/auth/me` siguen funcionando.

**Total tests tras este commit:** 2997 (todos pasando). Δ = +39 integration.

#### Decisiones de diseño

1. **Single store / single connection**. Todas las queries se ejecutan dentro de un único `with SQLiteEntityStore(db_path) as store`. Esto evita N round-trips al filesystem y mantiene el endpoint rápido incluso con full workflow.

2. **Best-effort loading**: si una entidad relacionada no existe (e.g., FK colgada por inconsistencia, o el flow está incompleto), se devuelve `None` en lugar de fallar. La única condición que rompe el endpoint es `case_id` inexistente (404).

3. **Fallback chain para `current_*`**: por cada entidad case-scoped, el endpoint intenta primero el puntero materializado (`case.current_kyc_submission_id`, etc.), luego `get_current_for_case` (busca `is_current=1`), y finalmente "último por created_at/version" del listado completo. Esto cubre casos edge donde el puntero no está sincronizado o el flag `is_current` no se mantuvo.

4. **9 pasos en el workflow** (kyc, ai_profile, approval, prefs, filter, proposal, override*, selection, report). El override es **condicional**: solo cuenta hacia el denominator cuando el proposal contiene candidates que requieren override. `completion_ratio` se ajusta dinámicamente — un case sin candidates que requieran override puede llegar a 1.0 con 8 pasos completados.

5. **`next_recommended_action` determinístico**: cascade de `if/elif` que sigue el orden natural del workflow. CLOSED tiene prioridad absoluta sobre todo lo demás.

6. **`_proposal_has_override_required` reusa `_candidate_requires_override`** (definido en Commit 13). Misma fuente de verdad para "candidate requires override".

7. **AI logs count vía `len(list_by_case)`**, no un `count(*)` SQL. A esta escala el overhead es despreciable; mantenerlo en el repo sin agregar un método nuevo simplifica.

8. **`latest_ai_log_id` = último por orden ascendente** (la repo devuelve `created_at_utc ASC, request_id ASC`; el último elemento es el más reciente).

9. **`audit.message` se exporta tal cual viene del verificador**. Útil para debugging desde el frontend; no se sanitiza.

10. **RBAC abierto a los 4 roles válidos** (admin/advisor/compliance/viewer). El summary es read-only y no expone datos sensibles más allá de lo que cada endpoint individual ya expone. El frontend Case Workbench lo usará desde cualquier rol autorizado.

11. **No nuevas migrations**. Reutiliza todas las tablas existentes (0001..0009). El único cambio en el persistence layer es agregar `get_current_for_case` a `SQLiteAdvisorProfileApprovalCaseRepository` (paridad con los demás case-scoped repos).

12. **Helpers extraídos como funciones puras** (`_compute_next_recommended_action`, `_compute_completion_ratio`, `_proposal_has_override_required`). Testeable directo sin DB; reusable si una iteración futura quiere generar progress badges en otros endpoints (e.g., `GET /cases` con flags por case en el listado).

13. **`completion_ratio` redondeado a 2 decimales** (`round(x, 2)`). Lo suficiente para mostrar en UI sin oscilaciones de punto flotante.

14. **`CaseAuditSummaryResponse` NO incluye `checked_at_utc`** (el listado `audit/verify` sí lo expone). Decisión: el summary es snapshot del momento de la request; el caller puede usar la hora del HTTP response. Si el frontend lo necesita explícito, se agrega sin cambios de schema mayores.

15. **No `warnings` en el response**. Si una entidad relacionada falta por inconsistencia, queda `None` silenciosamente. Decisión simple: el frontend puede inferir el estado del workflow desde `progress.*`; warnings agregarían ruido sin ganar info accionable. Si compliance pide explícito, se agrega.

16. **AdvisorIdentity del token NO se incluye en el response** (eso lo da `/auth/me`). El summary es del case, no del caller.

#### Tabla de RBAC actualizada (nuevo endpoint)

| Endpoint | `advisor` | `admin` | `compliance` | `viewer` | sin token |
|---|---|---|---|---|---|
| `GET /cases/{id}/summary` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 | ❌ 401 |

#### Lo que NO está en este commit

- **No UI Case Workbench** (item 19). El endpoint existe; queda implementar el frontend que lo consume.
- **No reemplaza lifecycle enforcement formal**. `next_recommended_action` es una recomendación al UI, no un check del backend. El backend sigue aceptando POST a cualquier endpoint case-scoped si las precondiciones de cada uno se cumplen.
- **No firm-level access control**. Cualquier token válido con rol adecuado puede ver el summary de cualquier case (consistente con el resto de los endpoints case-scoped).
- **No cacheo del response**. Cada GET dispara queries frescas. A esta escala (SQLite local, 1-7 entidades case-scoped) el costo es despreciable; si Phase 3 requiere optimización, se puede agregar un cache con invalidation por AuditEvent.
- **No streaming / pagination**. El response puede ser grande (especialmente con `current_portfolio_proposal.candidates` que incluye snapshots completos). Si esto se vuelve un problema operativo, se puede agregar `?fields=` o response slim sin cambiar el endpoint principal.
- **No diff entre versions**. El summary solo expone los `current_*`. Si compliance pide ver "qué cambió" entre dos snapshots, se agrega un endpoint dedicado (no entra en el scope del summary).
- **No KPIs agregados** (e.g., volatilidad histórica del case, latencia AI promedio, etc.). El summary es estado, no analítica. Métricas agregadas quedan para un dashboard dedicado.

---

## Fase 2 — Case workflow smoke check ✅ (Commit 17)

### Estado actual

Decimoséptimo commit de Fase 2 — **candado de cierre**. Script ejecutable que valida end-to-end el workflow case-scoped completo, sin necesidad de servidor uvicorn ni OpenAI real. Sirve como verificación final antes de levantar el frontend Case Workbench (item 20).

#### Archivos creados / modificados

- **`scripts/run_case_workflow_smoke_check.py`** — nuevo script:
  - Usa FastAPI TestClient (no requiere uvicorn).
  - Crea DB temporal vía `tempfile.mkdtemp` (`--db-path` permite override; `--keep-db` evita cleanup).
  - Aplica migrations 0001..0009 automáticamente.
  - Stubea `OpenAIProfileClient` con un mock determinístico (`preliminary_profile=moderado`, `confidence=0.82`, sin contradicciones).
  - Stubea `DEFAULT_DB_PATH` y `ADVISOR_TOKENS_FILE` para no tocar dev DB / tokens locales.
  - Ejecuta 14 pasos en orden: migrate → install stubs → entities → KYC → analysis → approval → preferences → universe filter → proposal → override → selection → report → summary → audit verify.
  - Reconfigura `sys.stdout`/`sys.stderr` a UTF-8 con `errors='replace'` (mismo patrón que `scripts/migrate.py`) para evitar UnicodeEncodeError en consolas Windows cp1252.
  - Expone función pública `run_case_workflow_smoke_check(db_path=None, debug=False) → SmokeCheckResult` para tests programáticos y `main(argv=None) → int` para uso CLI / pytest.
  - Imprime cada paso con header `==` y check ✓/✗ por aserción.
  - Validaciones explícitas: status codes 201, IDs con prefijos correctos, version=1 para KYC/report, `proposal.status="completed"`, `universe filter eligible_count > 0`, transición a `PORTFOLIO_SELECTED`, `completion_ratio=1.0`, `next_action="ready_for_review"`, `audit.is_intact=True`, `total_events >= 7`.
  - Exit 0 si todo pasa; exit 1 si al menos una aserción falla.

- **`tests/integration/test_case_workflow_smoke_check_script.py`** — 19 tests en 5 clases:
  - `TestRunFunction` (8): `run_case_workflow_smoke_check(db_path=...)` devuelve PASS, `case_id` + `report_id` con prefijos, audit intact, `completion_ratio=1.0`, `next_action=ready_for_review`, sin failures, usa el `db_path` dado.
  - `TestMainEntrypoint` (2): `main(['--db-path', ...])` exit 0; `--keep-db` preserva la DB.
  - `TestOutput` (4): stdout contiene "PASS", el case_id, el report_id, palabras "audit"/"intact".
  - `TestNoExternalDeps` (2): sin `OPENAI_API_KEY` en el entorno pasa igual; NO toca `data/demo_api.db` (mtime no cambia).
  - `TestImportable` (3): función + main + dataclass disponibles para import.

- **`docs/TODO_DESIGN_NOTES.md`** — esta sección + pending list actualizado (item 16 hecho, items 17-20 renumerados).

**Total tests tras este commit:** 3016 (todos pasando). Δ = +19 integration.

#### Decisiones de diseño

1. **TestClient + temp DB, no uvicorn**. El script es candado de testing, no smoke test de deploy. Usar TestClient elimina toda la complejidad de orquestar uvicorn + esperar al puerto + cleanup de procesos.

2. **`tempfile.mkdtemp` por default; `--db-path` override**. El usuario casual ejecuta sin args y obtiene una DB throwaway; el debugger pasa `--db-path` para inspeccionar. Cleanup automático solo si no se pasó `--db-path` y no se pasó `--keep-db`.

3. **OpenAI stubeado via `_get_openai_profile_client` monkeypatch directo**. Mismo patrón que los tests integration. El stub es estructuralmente válido para `OpenAIProfileClient.analyze_kyc` (campo `choices[0].message.content` con JSON parseable que pasa los validators).

4. **Profile `moderado`** en el mock → bajo el fixture universe, GROWTH típicamente requiere override. El smoke check **prefiere el variant que requiere override** cuando existe, para ejercitar el path completo (override approval + selection con override_approval_id).

5. **Política override-first**: si el proposal tiene cualquier candidate con `requires_advisor_override=True`, el script aprueba override sobre ese variant y lo selecciona. Razón: el summary computa `has_override_requirement` a nivel proposal; para alcanzar `completion_ratio=1.0` y `next_action=ready_for_review` con el smoke check, hay que cerrar el override loop aunque podamos elegir un variant más conservador. Además ejercita el path productivo más interesante.

6. **Función pública + `main()` separados**. `run_case_workflow_smoke_check()` devuelve `SmokeCheckResult` (dataclass) para que los tests asserten sobre campos. `main()` envuelve la función + parsea CLI args + maneja exit code + cleanup de tempdir.

7. **Stubs aplicados via setting de atributo + env var**, NO monkeypatch (que requeriría fixture). Trade-off: el script muta state global (env var, atributos del módulo). Aceptable porque corre como proceso aislado o, en tests, dentro de su propio tmp_path con cleanup automático.

8. **`sys.stdout.reconfigure(encoding='utf-8', errors='replace')`** al inicio. Sin esto el script crashea en consolas Windows default cp1252 al imprimir ▶ ✓ ✗. Mismo patrón ya usado en `scripts/migrate.py`.

9. **14 pasos numerados** en el output. Facilita identificar dónde falla cuando falla.

10. **Aserciones inline via `_expect(failures, condition, label, expected, actual)`**. No usa `assert` (que rompe en el primer fallo); acumula failures y al final imprime todos. Esto permite ver el primer fallo + cuántos más vinieron, sin re-correr.

11. **Tests del script via función directa, no subprocess**. Razón: subprocess agrega complejidad (env, path, encoding) y los CI a veces no liberan el handle de la DB SQLite al terminar el proceso. Function-direct es más simple, más rápido y suficiente para validar la lógica.

12. **`TestNoExternalDeps.test_does_not_touch_dev_db`** valida un invariante crítico: ningún test/script debe modificar `data/demo_api.db`. Si el smoke check accidentalmente importara algo que escribiera a esa ruta, este test rompe.

13. **`SmokeCheckResult` dataclass público** — los campos (`passed`, `case_id`, `report_id`, `audit_intact`, `completion_ratio`, `next_action`, `db_path`, `failures`) son lo que el caller necesita para construir su propio reporting/dashboard si quiere wrapping del script.

#### Cómo correrlo

```
# Smoke check end-to-end (sin args = DB temporal con cleanup auto):
python scripts/run_case_workflow_smoke_check.py

# Preservar DB para inspección:
python scripts/run_case_workflow_smoke_check.py --keep-db

# DB en path específico (no se borra al terminar):
python scripts/run_case_workflow_smoke_check.py --db-path data/smoke_inspection.db

# Con traceback completo en fallas:
python scripts/run_case_workflow_smoke_check.py --debug
```

Exit code:
- `0` = PASS — el flujo case-scoped funciona end-to-end.
- `1` = FAIL — al menos una aserción no se cumplió; revisar las líneas con ✗.

#### Lo que NO está en este commit

- **No reemplaza el test suite completo.** El smoke check valida el happy path; los tests integration cubren edge cases, RBAC, validation y regresiones puntuales.
- **No valida frontend** (item 20 — UI Case Workbench).
- **No valida live market data** ni live OpenAI; ambos siguen mockeados.
- **No mide latencia / performance**. Es funcional, no benchmark.
- **No corre como parte de CI automáticamente** (queda como invocación manual o se agrega a un workflow GH Actions en un commit futuro).
- **No instala el paquete ni gestiona venv**: asume que `python scripts/run_case_workflow_smoke_check.py` se invoca desde el repo root con dependencies ya instaladas (mismo supuesto que los otros scripts).
- **No valida concurrencia** (multiple cases en paralelo). El smoke check es secuencial.
- **No emite métricas**: solo PASS/FAIL + counts. Si Phase 3 quiere telemetría más rica, se puede serializar `SmokeCheckResult` a JSON sin cambiar la lógica.