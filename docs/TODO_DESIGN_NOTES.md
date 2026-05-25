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
- **RBAC por rol:** actualmente cualquier token demo (advisor o compliance) puede registrar cualquier decisión. Fase 2: restringir endpoints de decisión a `roles=["advisor"]`; compliance solo retrieval.
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

1. Tokens de advisor configurables (YAML/env, no hard-coded).
2. RBAC enforcement en endpoints `/advisor/*` existentes.
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
- **RBAC enforcement** — `AdvisorIdentity.roles` ya viene del loader, pero ningún endpoint chequea roles todavía. Próximo commit: helper `require_roles(["advisor"])` aplicado a los `/advisor/*`.
- **Multi-tenant real** — `firm_id` viaja en la identity, pero ningún endpoint filtra recursos por `firm_id`. Llega con las entidades de Fase 2 (Client/AdvisoryCase).
- **Persistencia de tokens en la nueva tabla `advisors`** — el loader sigue siendo file-backed. Cuando exista `AdvisorRepository`, los tokens van a salir de DB; el loader YAML pasará a ser una forma de seed inicial.
- **Auto-creación de `config/advisor_tokens.yaml` desde `.example`** — el operador lo hace manualmente. Un script de bootstrap puede llegar después.