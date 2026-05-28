# Risk-First Advisory

Motor backend de asesoría financiera supervisada. La IA propone, el asesor decide.

El workflow es risk-first: suitability, governance, ESG, data quality y portfolio feasibility se verifican antes de generar carteras. El resultado se persiste en SQLite y se expone vía FastAPI con un frontend estático de demo.

---

## Estado actual

- **3016 tests, todos verdes** (unit + integration)
- **Fase 0 cerrada:** `/ai/filtered-portfolio-demo` devuelve `report_markdown` auditable y persiste el resultado completo (payload + reporte) en SQLite.
- **Fase 1 cerrada — advisor pilot scaffold:** scaffold Bearer-token de auth + 3 endpoints legacy del asesor (`/advisor/profile-approval`, `/advisor/override-approval`, `/advisor/portfolio-selection`) client_id-scoped sobre `records`.
- **Fase 2 cerrada — workflow case-scoped backend ✅:** flujo completo end-to-end de un `AdvisoryCase`, con 9 migrations, ~20 endpoints case-scoped nuevos, AuditEvent hash chain por case, AIRequestLog con redacción de PII, RBAC por rol (admin / advisor / compliance / viewer), y smoke check ejecutable (`python scripts/run_case_workflow_smoke_check.py`). Esto NO incluye frontend nuevo para el flujo case-scoped — el legacy sigue mostrando solo los endpoints de Fase 0/1.
- **Próximo: Fase 3 — plug-and-play local + Case Workbench frontend** (UI que consuma `/cases/{id}/summary`, seed demo data, bootstrap script).
- **OpenAI** requerido solo para los endpoints `/ai/*` legacy; el flujo case-scoped soporta `POST /cases/{id}/ai/profile-analysis` también, pero los tests y el smoke check usan mocks determinísticos.
- **yfinance** requerido para `/live/portfolio-demo` (legacy).
- **Universo CSV** (`tests/fixtures/universe/sample_instrument_universe.csv`, 20 instrumentos) para todos los flujos demo, incluyendo `POST /cases/{id}/universe-filter`.
- Sin Bloomberg ni provider de datos productivo (out-of-scope MVP — pendiente Fase 4).
- Sin PostgreSQL (SQLite local).
- **Auth development-only:** Bearer token con mapa configurable vía YAML (`config/advisor_tokens.yaml` o `ADVISOR_TOKENS_FILE` env var). Sin JWT, sin IdP, sin rotación, sin firm-level access control. Exclusivamente desarrollo local — ver sección "Auth scaffold".
- **Esto NO es production-ready.** No es asesoramiento financiero. No reemplaza al asesor humano. Ver `docs/COMPLIANCE_NOTES.md` para límites detallados.

---

## Capas implementadas

| Capa | Módulo | Descripción |
|---|---|---|
| KYC | `kyc` | `KYCData`, `FinancialGoal`, `ESGProfile`, `AuditTrail` |
| IA — perfil | `ai_layer` | `OpenAIProfileClient` — análisis KYC, detección de contradicciones, follow-up, perfil revisado |
| IA — preferencias | `ai_layer` | `OpenAIProfileClient.extract_investment_preferences()` — texto libre → restricciones estructuradas |
| Humana | `human_layer` | `ScriptedAdvisorInterface` — decisiones por fixture (workflow completo) |
| Reglas | `rules_layer` | Governance, suitability, ESG, data quality, risk budget |
| Universo | `universe_layer` | `CSVInstrumentUniverseProvider` + `PreferenceFilterEngine` — filtro determinístico de universo de instrumentos |
| Datos | `data_layer` | `MockMarketDataProvider` (fixtures YAML) + `InstrumentMarketDataAdapter` (CSV → snapshots proxy) |
| Portfolio | `portfolio_layer` | Optimizador, feasibility checker, generación de variantes DEFENSIVE/BALANCED/GROWTH con metadata de override |
| Workflow | `workflow_layer` | `AdvisoryWorkflowCoordinator` — orquesta el flujo completo con `MockAIClient` |
| Reporting | `reporting_layer` | `MarkdownReportGenerator` — genera reporte `.md` con metadata de variantes |
| Persistencia | `persistence_layer` | SQLite + repositorios in-memory |
| Config | `config_layer` | Loader auditable de `config/risk_profiles.yaml` y `config/achievable_returns.yaml` (supuestos de RiskBudget y retornos alcanzables externalizados) |
| API | `api_layer` | FastAPI: ~50 endpoints — legacy (auth, decisiones del asesor, ejecución, recuperación, demo IA y demo portfolio) + workflow case-scoped Fase 2 |

---

## Endpoints case-scoped (Fase 2)

El backend expone el flujo completo `firm → advisor → client → case → KYC → AI profile analysis → profile approval → preferences → universe filter → portfolio proposal → override approval → portfolio selection → report` con AuditEvent hash chain y AIRequestLog persistente. Endpoints principales (todos requieren Bearer token; ver "Auth scaffold"):

| Endpoint | RBAC | Qué hace |
|---|---|---|
| `POST/GET /cases` | advisor, admin (POST) / any (GET) | CRUD del `AdvisoryCase` |
| `POST/GET /cases/{case_id}/kyc` | advisor, admin (POST) / any (GET) | KYC versionado por case |
| `POST/GET /cases/{case_id}/ai/profile-analysis` | advisor, admin (POST) / any (GET) | Análisis IA de perfil sobre la última KYC |
| `POST/GET /cases/{case_id}/profile-approval` | advisor, admin (POST) / any (GET) | Decisión del asesor: approve / modify / reject |
| `POST/GET /cases/{case_id}/investment-preferences` | advisor, admin (POST) / any (GET) | Preferencias manuales o AI-extracted |
| `POST/GET /cases/{case_id}/universe-filter` | advisor, admin (POST) / any (GET) | `PreferenceFilterEngine` sobre el universo CSV |
| `POST/GET /cases/{case_id}/portfolio-proposal` | advisor, admin (POST) / any (GET) | Genera variants DEFENSIVE / BALANCED / GROWTH |
| `POST/GET /cases/{case_id}/override-approval` | advisor, admin (POST) / any (GET) | Override del advisor para variants exceeding-budget |
| `POST/GET /cases/{case_id}/portfolio-selection` | advisor, admin (POST) / any (GET) | Selección final; transiciona case a `PORTFOLIO_SELECTED` |
| `POST/GET /cases/{case_id}/reports` | advisor, admin (POST) / any (GET) | Markdown report determinístico, versionado |
| `GET /cases/{case_id}/summary` | any rol válido | Full case state en un solo response (base para Case Workbench) |
| `GET /cases/{case_id}/audit` | any rol válido | Lista de AuditEvents del case |
| `GET /cases/{case_id}/audit/verify` | admin, compliance | Verifica integridad del hash chain |
| `GET /cases/{case_id}/ai-logs` | admin, compliance | Lista de AIRequestLog del case (input redactado) |
| `GET /admin/ai-logs` y `GET /admin/ai-logs/{id}` | admin, compliance | Cross-case audit de llamadas IA |

Detalles, semántica de `is_current` y decisiones de diseño en `docs/TODO_DESIGN_NOTES.md`.

---

## MVP Flows

El frontend estático expone cinco flujos de demo de forma visual. Todos requieren el backend FastAPI corriendo localmente.

### 1. AI Profile Demo — `POST /ai/profile-demo`

Analiza un formulario KYC con OpenAI. Detecta contradicciones entre campos, propone un perfil preliminar y genera preguntas de follow-up para el asesor.

- Input: `KYCData` estructurado + `client_id`
- Output: `preliminary_profile`, `confidence`, `contradictions`, `follow_up_questions`, `advisor_notes`
- **La IA no aprueba el perfil.** Solo el asesor puede hacerlo.

### 2. AI Profile Follow-up — `POST /ai/profile-follow-up`

Segunda ronda de análisis. El asesor responde las preguntas de follow-up y la IA revisa su propuesta de perfil.

- Input: KYC original + análisis previo + respuestas del asesor a las preguntas
- Output: `revised_profile`, `confidence` actualizada, `remaining_contradictions`, `profile_change_reason`

### 3. Live Portfolio Demo — `POST /live/portfolio-demo`

Descarga datos históricos de ETFs reales desde yfinance y genera hasta 3 portfolios candidatos (DEFENSIVE / BALANCED / GROWTH) para el perfil seleccionado.

- No usa IA. No usa KYC. El perfil se selecciona directamente.
- Universo fijo: 11 ETFs (BIL, SHV, AGG, BND, IEF, VTI, SPY, VEA, VWO, HYG, GLD)
- Requiere internet. Puede tardar 5–15 segundos.

### 4. AI Universe Filter Demo — `POST /ai/filter-universe-demo`

Extrae preferencias de inversión desde texto libre (OpenAI) y las aplica sobre el universo CSV para filtrar instrumentos elegibles.

- Input: `client_id` + texto libre de preferencias
- Output: instrumentos elegibles, excluidos con razones, filtros aplicados, warnings
- No genera portfolios. Solo filtra.

### 5. AI Filtered Portfolio Demo — `POST /ai/filtered-portfolio-demo`

Pipeline completo de cuatro pasos: texto libre → preferencias → filtro → snapshots → portfolios candidatos.

Ver sección detallada más abajo.

---

## AI Filtered Portfolio Demo

### Pipeline

```
texto libre del cliente
       │
       ▼
OpenAIProfileClient.extract_investment_preferences()
       │  preferencias estructuradas
       ▼
PreferenceFilterEngine.apply(universe_csv, preferences)
       │  instrumentos elegibles / excluidos
       ▼
InstrumentMarketDataAdapter.to_many(eligible_instruments)
       │  snapshots proxy (ytm/coupon → expected_return_annual)
       ▼
ReturnEstimator + CovarianceEngine
       │  retornos estimados + matriz de covarianza
       ▼
PortfolioGenerationCoordinator.generate(snapshots, risk_budget)
       │
       ▼
DEFENSIVE / BALANCED / GROWTH  (o status bloqueado)
```

### Endpoint

```
POST /ai/filtered-portfolio-demo
```

### Input ejemplo

```json
{
  "client_id": "CLI-PREF-PORT-001",
  "profile": "moderado",
  "natural_language_preferences": "Solo quiero invertir en ONs hard dollar argentinas disponibles en Balanz y evitar energia."
}
```

Campos opcionales: `kyc_context`, `previous_profile_analysis`.

### Output esperado

```json
{
  "client_id": "CLI-PREF-PORT-001",
  "profile": "moderado",
  "status": "completed",
  "message": "Portfolio generation completed successfully.",
  "preferences": {
    "allowed_instrument_types": ["CORPORATE_BOND"],
    "currency": "USD",
    "country": "Argentina",
    "entity": "Balanz",
    "hard_dollar_only": true,
    "avoid_sectors": ["Energy"],
    "confidence": 0.92,
    "..."  : "..."
  },
  "eligible_count": 9,
  "excluded_count": 11,
  "eligible_instruments": ["..."],
  "exclusions": ["..."],
  "applied_filters": ["instrument_type:CORPORATE_BOND", "currency:USD", "..."],
  "warnings": [],
  "snapshots": ["..."],
  "snapshot_count": 9,
  "candidates": ["..."],
  "candidate_count": 2,
  "report_markdown": "# Risk-First Advisory — AI Filtered Portfolio Report\n\n## 1. Executive Summary ...",
  "record_id": "ai_filtered_portfolio_000001",
  "report_record_id": "report_000001"
}
```

### Reporte Markdown auditable

Cada respuesta de `/ai/filtered-portfolio-demo` — **bajo cualquier `status`** (`completed`, `blocked_insufficient_universe`, `blocked_insufficient_diversification_capacity`, `infeasible`) — incluye:

- **`report_markdown`** — string Markdown determinístico con 10 secciones: Executive Summary, Natural Language Preferences, AI Extracted Preferences, Applied Universe Filters, Eligible Instruments, Exclusions, Portfolio-Ready Snapshots, Candidate Portfolios, Advisor Override y Limitations & Disclaimers. Generado por `AIFilteredPortfolioReportGenerator`. Mismo payload → mismo reporte.
- **`record_id`** — identificador del registro `ai_filtered_portfolio_NNNNNN` en SQLite con el payload completo de la respuesta y metadata (`client_id`, `profile`, `status`, `candidate_count`, `endpoint`).
- **`report_record_id`** — identificador del `MarkdownReport` (`report_NNNNNN`) en SQLite con `title`, `content` (el mismo `report_markdown`), `client_id` y `generated_at_utc`.

El reporte Markdown es **para revisión del asesor**. No es un documento comercial para el cliente. No hay PDF ni firma digital en esta fase. El reporte vive sólo en el record store SQLite — no se escribe `.md` a disco. El frontend ofrece un botón **"Copy Markdown Report"** para copiar el reporte al portapapeles.

### Status posibles

| `status` | Significado |
|---|---|
| `completed` | Portfolios generados correctamente |
| `blocked_insufficient_universe` | Menos de 3 snapshots usables (universo filtrado demasiado pequeño) |
| `blocked_insufficient_diversification_capacity` | Snapshots usables < `ceil(1 / max_single_asset)` del perfil (p.ej. `moderado` requiere ≥ 7) |
| `infeasible` | El optimizador no encontró solución factible con los constraints del risk budget |

### Rol de la IA vs. motor determinístico

| Componente | Qué hace | Qué NO hace |
|---|---|---|
| OpenAI (`extract_investment_preferences`) | Estructura las preferencias del cliente en texto libre en un JSON con tipos de instrumento, moneda, entidad, sectores, restricciones | **No filtra instrumentos. No calcula pesos. No aprueba el perfil.** |
| `PreferenceFilterEngine` | Aplica las preferencias estructuradas al CSV de instrumentos de forma determinística y reproducible | No interpreta texto libre. No hace excepciones. |
| `PortfolioGenerationCoordinator` | Genera variantes DEFENSIVE / BALANCED / GROWTH respetando el `RiskBudget` del perfil | No ajusta restricciones aprobadas. No relaja el budget automáticamente. |
| Asesor | Aprueba el perfil final. Revisa GROWTH si requiere override. | La IA nunca reemplaza esta decisión. |

### GROWTH con advisor override

Cuando la variante GROWTH excede `max_volatility` del `RiskBudget` aprobado, el sistema **no la silencia**. En cambio, la marca explícitamente:

```json
{
  "variant": "GROWTH",
  "metadata": {
    "risk_budget_exceeded": true,
    "requires_advisor_override": true,
    "exceeded_constraints": ["max_volatility"],
    "reason_codes": ["PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"]
  }
}
```

El frontend muestra un banner de advertencia amarillo con los constraints excedidos. El asesor debe revisar y aprobar explícitamente antes de presentar GROWTH al cliente.

---

## Auth scaffold (Fase 1, refinado en Fase 2)

> ⚠ **DEVELOPMENT-ONLY.** El módulo `api_layer/auth.py` implementa una resolución de identidad por Bearer token. Sigue sin ser apto para producción: no firma JWT, no rota, no es multi-tenant, no carga `.env`. La novedad de Fase 2 es que los tokens YA NO viven hardcoded en `auth.py` — se resuelven desde un loader YAML configurable + fallback dev-only.

### Resolución de tokens (Fase 2)

`config_layer/advisor_tokens.get_default_advisor_tokens()` aplica este orden:

1. **ENV var `ADVISOR_TOKENS_FILE`** (si está set y no vacío) → carga ese YAML.
2. **`config/advisor_tokens.yaml`** (si existe) → carga ese archivo.
3. **Fallback hardcoded dev-only** → los dos tokens demo de la tabla de abajo. Siempre disponible para tests y demos.

Cuando se usa (1) o (2), el archivo **reemplaza completamente** al fallback — los `dev-*` tokens dejan de resolver. No hay merge. Schema inválido en el archivo configurado → la request termina en 500 (fail-loud), no en 401 silente.

### Archivos

| Archivo | En git | Para qué |
|---|---|---|
| `config/advisor_tokens.yaml.example` | ✅ commiteado | Plantilla con los dos tokens demo. Documenta schema y política. |
| `config/advisor_tokens.yaml` | ❌ **gitignored** | Donde el operador pone los tokens reales del entorno. |

### Schema (validado por el loader, fail-loud)

```yaml
tokens:
  <opaque-token-string>:
    advisor_id:   <str no vacío>
    display_name: <str no vacío>
    firm_id:      <str no vacío | null>
    roles:        [<role>, ...]   # no vacía
```

Roles permitidos: `advisor`, `compliance`, `admin`, `viewer`. Cualquier otro valor → `ValueError`. Campos desconocidos por entrada → `ValueError`. `bool` donde se espera `str` → `ValueError`.

### Tokens demo (fallback)

| Token (header `Authorization: Bearer <token>`) | `advisor_id` | `roles` |
|---|---|---|
| `dev-advisor-token` | `ADV-001` | `["advisor"]` |
| `dev-compliance-token` | `CMP-001` | `["compliance"]` |

### Dependencias FastAPI

`api_layer/auth.py` expone dos dependencias para que los próximos endpoints de aprobación / override puedan resolver al asesor:

- `get_current_advisor_required` — siempre exige `Authorization: Bearer <token>` válido; 401 en caso contrario. Usar en endpoints donde la identidad del asesor es obligatoria (firma de override, selección de variante, etc.).
- `get_current_advisor_optional` — devuelve `AdvisorIdentity | None`. Si el header no está, devuelve `None`. Si está presente pero es inválido, 401. Usar en endpoints que pueden seguir funcionando de forma anónima pero quieren aprovechar la identidad cuando exista.

### Endpoint diagnóstico

```
GET /auth/me
Authorization: Bearer dev-advisor-token

200 OK
{
  "advisor_id": "ADV-001",
  "display_name": "Demo Advisor",
  "firm_id": null,
  "roles": ["advisor"]
}
```

Errores de auth siempre devuelven el mismo detalle genérico para no filtrar información:

```
401 Unauthorized
WWW-Authenticate: Bearer
{ "detail": "Invalid or missing advisor authentication token." }
```

### No regresión en Fase 1

Los siguientes endpoints siguen funcionando **sin token**:
- `GET /health`
- `POST /demo/run`, `POST /workflow/run`
- `POST /live/portfolio-demo`
- `POST /universe/filter-demo`
- `POST /ai/profile-demo`, `/ai/profile-follow-up`, `/ai/investment-preferences`, `/ai/filter-universe-demo`, `/ai/filtered-portfolio-demo`
- `GET /workflow`, `/reports`, `/audit`, y sus variantes por `record_id`

La protección se aplicará endpoint por endpoint en próximas tareas de Fase 1 (advisor override, selección de variante, etc.).

### Advisor profile approval — `POST /advisor/profile-approval`

> ⚠ Development-only. Usa el auth scaffold de arriba. No tiene RBAC: cualquier token demo válido (advisor o compliance) puede registrar una decisión. RBAC más estricto queda para tareas posteriores.

Primer acto formal del asesor: registrar una decisión sobre un perfil propuesto (por la IA o por el sistema).

#### Request body

| Campo | Tipo | Reglas |
|---|---|---|
| `client_id` | str | min_length=1 |
| `proposed_profile` | str | uno de: `conservador`, `moderado-defensivo`, `moderado`, `moderado-agresivo`, `agresivo` |
| `decision` | str | uno de: `approve`, `modify`, `reject` |
| `approved_profile` | str \| null | reglas cruzadas, ver abajo |
| `rationale` | str | min_length=1, sin solo-whitespace |
| `source` | str | default `"manual"` |
| `related_record_id` | str \| null | opcional — para enlazar con `ai_filtered_portfolio_NNNNNN` u otro record |

#### Reglas cruzadas por `decision`

| Decision | `approved_profile` esperado | Comportamiento |
|---|---|---|
| `approve` | `None` o igual a `proposed_profile` | Si es `None`, el endpoint completa `approved_profile = proposed_profile` y lo devuelve. Si es distinto al propuesto → 422 (usar `modify` en ese caso). |
| `modify` | str válido, obligatorio | Permite cambiar el perfil aprobado. Aceptado aún si coincide con `proposed_profile` (el asesor lo declara explícitamente). |
| `reject` | DEBE ser `None` | Si viene cualquier valor → 422. |

#### Ejemplo — approve

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/advisor/profile-approval `
  -H "Authorization: Bearer dev-advisor-token" `
  -H "Content-Type: application/json" `
  -d '{
    "client_id": "CLI-001",
    "proposed_profile": "moderado",
    "decision": "approve",
    "rationale": "Perfil consistente con KYC del cliente."
  }'
```

Response:

```json
{
  "record_id": "advisor_profile_approval_000001",
  "client_id": "CLI-001",
  "advisor_id": "ADV-001",
  "advisor_display_name": "Demo Advisor",
  "firm_id": null,
  "proposed_profile": "moderado",
  "decision": "approve",
  "approved_profile": "moderado",
  "rationale": "Perfil consistente con KYC del cliente.",
  "source": "manual",
  "related_record_id": null,
  "created_at_utc": "2026-05-24T12:34:56Z",
  "status": "recorded"
}
```

#### Errores

- `401` — sin token, token inválido, o header malformado.
- `422` — request body inválido (Pydantic), o regla cruzada violada (ej. `decision=approve` con `approved_profile` distinto al propuesto).
- `500` — `"Advisor profile approval persistence failed."` si SQLite falla.

#### Persistencia

Cada decisión se persiste como record SQLite con `record_type="advisor_profile_approval"` y metadata mínima (`client_id`, `advisor_id`, `decision`, `proposed_profile`, `approved_profile`, `endpoint`, `source_type`). El payload JSON contiene los mismos campos de la response salvo `record_id`, `created_at_utc` y `status`. Aún no hay endpoint de retrieval genérico (`GET /advisor/profile-approval/{record_id}`) — se agregará en una tarea posterior.

### Advisor override approval — `POST /advisor/override-approval`

> ⚠ Development-only. Mismo auth scaffold (Bearer token). Sin RBAC: cualquier token demo (advisor o compliance) puede registrar. **No valida todavía contra existencia real del candidate** — el asesor declara reason_codes y exceeded_constraints explícitamente.

Segundo acto formal del asesor: registrar la decisión sobre una variante de portfolio (típicamente `GROWTH`) que excede el RiskBudget aprobado y requiere advisor override.

#### Request body

| Campo | Tipo | Reglas |
|---|---|---|
| `client_id` | str | min_length=1 |
| `related_record_id` | str \| null | opcional — típicamente `ai_filtered_portfolio_NNNNNN` |
| `candidate_variant` | str | uno de: `DEFENSIVE`, `BALANCED`, `GROWTH` (mayúsculas estrictas) |
| `decision` | str | uno de: `approve`, `reject` |
| `reason_codes` | list[str] | default `[]`; items no vacíos |
| `exceeded_constraints` | list[str] | default `[]`; items no vacíos |
| `rationale` | str | min_length=1, sin solo-whitespace |
| `source` | str | default `"manual"` |

Para `approve` se aceptan `reason_codes` y `exceeded_constraints` vacíos (sin warning). Para `reject`, ambos campos se conservan en el record para mantener trazabilidad de por qué se planteó el override originalmente.

#### Ejemplo — approve GROWTH

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/advisor/override-approval `
  -H "Authorization: Bearer dev-advisor-token" `
  -H "Content-Type: application/json" `
  -d '{
    "client_id": "CLI-001",
    "related_record_id": "ai_filtered_portfolio_000001",
    "candidate_variant": "GROWTH",
    "decision": "approve",
    "reason_codes": ["PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"],
    "exceeded_constraints": ["max_volatility"],
    "rationale": "Cliente acepta exceder vol max para alcanzar retorno objetivo."
  }'
```

Response:

```json
{
  "record_id": "advisor_override_approval_000001",
  "client_id": "CLI-001",
  "advisor_id": "ADV-001",
  "advisor_display_name": "Demo Advisor",
  "firm_id": null,
  "candidate_variant": "GROWTH",
  "decision": "approve",
  "reason_codes": ["PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"],
  "exceeded_constraints": ["max_volatility"],
  "rationale": "Cliente acepta exceder vol max para alcanzar retorno objetivo.",
  "source": "manual",
  "related_record_id": "ai_filtered_portfolio_000001",
  "created_at_utc": "2026-05-24T12:34:56Z",
  "status": "recorded"
}
```

#### Errores

- `401` — sin token, token inválido o header malformado.
- `422` — campos requeridos faltantes, valores fuera de enum, rationale vacío, items vacíos en listas.
- `500` — `"Advisor override approval persistence failed."` si SQLite falla.

#### Persistencia

Cada decisión se persiste como record SQLite con `record_type="advisor_override_approval"` y metadata mínima (`client_id`, `advisor_id`, `decision`, `candidate_variant`, `related_record_id`, `endpoint`, `source_type`). El payload completo (incluido rationale, reason_codes y exceeded_constraints) queda en el campo JSON. No hay endpoint de retrieval genérico todavía.

#### Relación con el dominio

El módulo `human_layer.override_approval` ya contenía un objeto de dominio `AdvisorOverrideApproval` (con enums, comment mínimo 20 caracteres y validación contra `PortfolioVariantMetadata` viva) pensado para integración con workflow. Ese modelo **no se modifica**: el endpoint API usa schemas Pydantic independientes y más laxos (rationale ≥ 1 carácter, sin validación contra metadata viva) porque registra una decisión ya tomada en lugar de calcularla. La conciliación dominio ↔ API queda para una tarea de integración futura.

### Advisor portfolio selection — `POST /advisor/portfolio-selection`

> ⚠ Development-only. Mismo auth scaffold (Bearer token). Sin RBAC: cualquier token demo (advisor o compliance) puede registrar. **No valida todavía contra existencia real** del `related_record_id` (portfolio candidate) ni del `override_approval_record_id`.

Tercer acto formal del asesor: registrar la selección final de la variante que se va a presentar al cliente.

#### Request body

| Campo | Tipo | Reglas |
|---|---|---|
| `client_id` | str | min_length=1 |
| `related_record_id` | str \| null | opcional — típicamente `ai_filtered_portfolio_NNNNNN` |
| `selected_variant` | str | uno de: `DEFENSIVE`, `BALANCED`, `GROWTH` (mayúsculas estrictas) |
| `rationale` | str | min_length=1, sin solo-whitespace |
| `override_approval_record_id` | str \| null | opcional — típicamente `advisor_override_approval_NNNNNN`; recomendado cuando se selecciona `GROWTH` |
| `source` | str | default `"manual"` |

#### Warnings

La response incluye un campo `warnings: list[str]`:
- Si `selected_variant == "GROWTH"` y `override_approval_record_id` es `null` → se agrega:
  `"GROWTH selected without linked override approval record."`
- En todos los demás casos → lista vacía.

El warning **no bloquea** la selección; solo deja un rastro auditable para que compliance pueda detectarlo en revisión posterior (también queda persistido en el payload del record).

#### Ejemplo — GROWTH con override link

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/advisor/portfolio-selection `
  -H "Authorization: Bearer dev-advisor-token" `
  -H "Content-Type: application/json" `
  -d '{
    "client_id": "CLI-001",
    "related_record_id": "ai_filtered_portfolio_000001",
    "selected_variant": "GROWTH",
    "rationale": "Cliente acepta perfil más agresivo tras revisión.",
    "override_approval_record_id": "advisor_override_approval_000001"
  }'
```

Response:

```json
{
  "record_id": "advisor_portfolio_selection_000001",
  "client_id": "CLI-001",
  "advisor_id": "ADV-001",
  "advisor_display_name": "Demo Advisor",
  "firm_id": null,
  "selected_variant": "GROWTH",
  "rationale": "Cliente acepta perfil más agresivo tras revisión.",
  "related_record_id": "ai_filtered_portfolio_000001",
  "override_approval_record_id": "advisor_override_approval_000001",
  "source": "manual",
  "warnings": [],
  "created_at_utc": "2026-05-24T12:34:56Z",
  "status": "recorded"
}
```

#### Errores

- `401` — sin token, token inválido o header malformado.
- `422` — `selected_variant` fuera de enum, `rationale` vacío/whitespace, `client_id` vacío, campos requeridos faltantes.
- `500` — `"Advisor portfolio selection persistence failed."` si SQLite falla.

#### Persistencia

Cada selección se persiste como record SQLite con `record_type="advisor_portfolio_selection"` y metadata mínima (`client_id`, `advisor_id`, `selected_variant`, `related_record_id`, `override_approval_record_id`, `endpoint`, `source_type`). El payload JSON contiene todos los campos de la response salvo `record_id`, `created_at_utc` y `status` — incluido el `warnings` calculado, para que compliance pueda filtrar selecciones de `GROWTH` sin override link sin recalcular la regla.

---

## Supuestos críticos en config YAML (Fase 1.6)

> ⚠ **Demo assumptions.** Los archivos bajo `config/` son supuestos internos para el demo del MVP. **No reemplazan** un CMA (Capital Market Assumptions) formal ni la decisión de un comité de inversiones. Para un piloto productivo, una firma debe revisarlos y aprobarlos formalmente.

### Archivos

| Archivo | Contenido | Consumido por |
|---|---|---|
| `config/risk_profiles.yaml` | 5 perfiles × 11 parámetros base (`target_volatility`, `max_volatility`, `max_drawdown`, `max_equity`, `max_high_yield`, `max_single_asset`, `max_sector_exposure`, `max_duration`, `min_liquidity`, `preferred_currency`, `complex_products_allowed`) | `rules_layer/risk_budget_builder.PROFILE_BASE_PARAMS` |
| `config/achievable_returns.yaml` | 5 perfiles → retorno anual esperado (decimal) | `rules_layer/goal_feasibility.DEFAULT_ACHIEVABLE_RETURNS` |

### Loader

`src/risk_first_advisory/config_layer/risk_assumptions.py` expone:

- `load_risk_profile_params(path=None)` y `load_achievable_returns(path=None)` — carga + validación estricta. `ValueError` si faltan perfiles, sobran perfiles, faltan campos, los tipos no coinciden, o `complex_products_allowed`/numéricos son del tipo equivocado (con bool-guard explícito porque `isinstance(True, int) == True`).
- `get_default_risk_profile_params()` y `get_default_achievable_returns()` — wrappers cacheados que devuelven copia profunda (evita mutación accidental del cache compartido). Son los que consumen `RiskBudgetBuilder` y `GoalFeasibilityEngine` al importar.
- `DEFAULT_RISK_PROFILES_PATH`, `DEFAULT_ACHIEVABLE_RETURNS_PATH`, `EXPECTED_PROFILES`, `REQUIRED_PROFILE_FIELDS` — constantes públicas para tests / herramientas.

### Política de validación

| Regla | Comportamiento |
|---|---|
| Perfiles esperados | Exactamente los 5: `conservador`, `moderado-defensivo`, `moderado`, `moderado-agresivo`, `agresivo`. Faltantes → `ValueError`. Extras desconocidos → `ValueError`. |
| Campos requeridos por perfil | Los 11 listados arriba. Faltantes → `ValueError`. |
| Campos numéricos (`target_volatility`, `max_drawdown`, etc.) | `int` o `float`. **`bool` rechazado explícitamente** (`isinstance(True, int) == True` en Python). |
| `complex_products_allowed` | Debe ser `bool` real (no `0`/`1`, no `"yes"`/`"no"`). |
| `preferred_currency` | `str` no vacío ni solo-whitespace. |
| Retornos alcanzables | `int|float`, no `bool`. Se convierten a `float`. |
| YAML inválido / archivo vacío | `ValueError` con path y razón. |
| Archivo inexistente | `FileNotFoundError`. |

### Cómo cambiar los supuestos

1. Editar el archivo YAML correspondiente bajo `config/`.
2. Correr `pytest tests/unit/test_risk_assumptions_config.py` — falla si el schema rompe.
3. Correr `pytest -q` completo — los tests de regresión de `RiskBudgetBuilder` y `GoalFeasibilityEngine` detectan cambios numéricos.
4. Para un piloto productivo: cada cambio debe ir acompañado de revisión del comité de inversiones de la firma, justificación documentada en el PR y aprobación de compliance. **El sistema no enforce este flujo** — depende del proceso de la firma alrededor de git.

---

## Setup (Windows PowerShell)

```powershell
cd C:\Users\maria\risk-first-advisory
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Para instalar dependencias de desarrollo (pytest, ruff, mypy):

```powershell
python -m pip install -e ".[dev]"
```

---

## Correr tests

```powershell
python -m pytest
```

Suite completa (unit + integration): ~3 minutos, **3016 tests** (todos verdes).

```powershell
# Solo tests de API
python -m pytest tests/integration/test_api_demo.py -v

# Solo tests del AI Filtered Portfolio Demo
python -m pytest tests/integration/test_api_ai_filtered_portfolio.py -v

# Solo tests unitarios
python -m pytest tests/unit/ -v
```

---

## Offline MVP smoke check

Valida el flujo principal de punta a punta sin OpenAI, sin yfinance, sin backend corriendo y sin frontend. Solo requiere el virtualenv activado.

```powershell
python scripts/run_mvp_smoke_check.py
```

Output esperado:

```
PASS — MVP smoke check completed successfully
```

El script recorre 11 pasos determinísticos:

1. Verifica que el CSV del universo existe (`tests/fixtures/universe/sample_instrument_universe.csv`)
2. Carga el universo con `CSVInstrumentUniverseProvider` (20 instrumentos)
3. Aplica `PreferenceFilterEngine` con preferencias fijas equivalentes a "ONs hard dollar argentinas en Balanz, sin energía"
4. Verifica `eligible_count >= 7`
5. Convierte los elegibles a snapshots con `InstrumentMarketDataAdapter`
6. Verifica `usable_snapshots >= 7`
7. Construye el `RiskBudget` para perfil `moderado` desde `PROFILE_BASE_PARAMS`
8. Verifica `snapshot_count >= ceil(1 / max_single_asset)` (la capacidad de diversificación mínima del perfil)
9. Corre `ReturnEstimator` + `CovarianceEngine`
10. Corre `PortfolioGenerationCoordinator.generate()`
11. Verifica `candidate_count >= 1`

Para más detalle por paso (métricas de cada snapshot, constraints excedidos en GROWTH):

```powershell
python scripts/run_mvp_smoke_check.py --debug
```

Si algún paso falla, el script imprime `FAIL` con la razón y termina con exit code 1.

---

## Case workflow smoke check (Fase 2)

Valida end-to-end **todo el flujo case-scoped** de Fase 2 (firm → advisor → client → case → KYC → AI profile analysis → profile approval → investment preferences → universe filter → portfolio proposal → override approval → portfolio selection → report → summary → audit verify) sin OpenAI real ni servidor uvicorn corriendo. Sirve como candado de cierre antes de levantar el frontend Case Workbench.

```powershell
python scripts/run_case_workflow_smoke_check.py
```

Output esperado al final:

```
PASS — case workflow smoke check completed
    case_id          : case_000001
    report_id        : case_report_000001
    audit intact     : True
    completion ratio : 1.0
    next action      : ready_for_review
```

Opciones:

```powershell
# Preservar la DB temporal para inspección:
python scripts/run_case_workflow_smoke_check.py --keep-db

# DB en path específico (no se borra al terminar):
python scripts/run_case_workflow_smoke_check.py --db-path data/smoke_inspection.db

# Traceback completo en fallas:
python scripts/run_case_workflow_smoke_check.py --debug
```

El script aplica todas las migrations (`0001..0009`) sobre una DB SQLite temporal, monkeypatchea `OpenAIProfileClient` con un mock determinístico (sin red), usa FastAPI TestClient (sin uvicorn) y valida 14 pasos del workflow. Exit code 0 si pasa, 1 si falla.

---

## Demo local — inicio rápido

### Backend

```powershell
# Sin IA (solo endpoints de workflow y live portfolio)
uvicorn risk_first_advisory.api_layer.main:app --reload

# Con IA (habilita /ai/profile-demo, /ai/filter-universe-demo, /ai/filtered-portfolio-demo)
$env:OPENAI_API_KEY="your_key_here"
uvicorn risk_first_advisory.api_layer.main:app --reload
```

Documentación interactiva:
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

### Frontend

```powershell
python -m http.server 5500 -d frontend
```

Abrir en el navegador: `http://127.0.0.1:5500`

> Si se abre `frontend/index.html` directamente desde `file://`, el navegador puede bloquear las requests por CORS. Usar el servidor HTTP local.

### Scripts de consola

```powershell
# Workflow completo con fixtures (MockAIClient + ScriptedAdvisorInterface)
python scripts/run_demo.py

# Demo de filtrado con preferencias de texto libre
python scripts/run_ai_filtered_portfolio_demo.py --preferences "Solo quiero invertir en ONs hard dollar argentinas disponibles en Balanz y evitar energia."
```

---

## API FastAPI — endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Estado del backend |
| `GET` | `/auth/me` | **Fase 1 — scaffold de auth (development-only).** Resuelve la identidad del asesor a partir del header `Authorization: Bearer <token>`. Devuelve 401 si falta o es inválido. Tokens demo hard-coded; no usar en producción. Ver sección "Auth scaffold (Fase 1)". |
| `POST` | `/advisor/profile-approval` | **Fase 1 — primer acto formal del asesor.** Registra la decisión del asesor (`approve` / `modify` / `reject`) sobre un perfil propuesto, con rationale obligatorio. Persiste como record `advisor_profile_approval_NNNNNN`. Requiere Bearer token válido. Sin RBAC todavía (advisor y compliance ambos pueden registrar). |
| `POST` | `/advisor/override-approval` | **Fase 1 — segundo acto formal del asesor.** Registra `approve` / `reject` sobre una variante (típicamente `GROWTH`) que excede el RiskBudget aprobado, con rationale obligatorio + reason_codes + exceeded_constraints. Persiste como record `advisor_override_approval_NNNNNN`. Requiere Bearer token válido. No valida todavía contra existencia real del candidate. |
| `POST` | `/advisor/portfolio-selection` | **Fase 1 — tercer acto formal del asesor.** Registra la selección final de la variante (`DEFENSIVE` / `BALANCED` / `GROWTH`) a presentar al cliente, con rationale obligatorio y enlaces opcionales a `related_record_id` (portfolio candidate) y `override_approval_record_id`. Si `GROWTH` se selecciona sin override link, la response incluye un warning. Persiste como record `advisor_portfolio_selection_NNNNNN`. Requiere Bearer token válido. No valida todavía contra existencia real de los records enlazados. |
| `POST` | `/demo/run` | Ejecuta workflow demo con fixtures |
| `POST` | `/workflow/run` | **Scripted deterministic demo.** Ejecuta el pipeline (governance → suitability → ESG → DQ → optimizer) con `MockAIClient` y `ScriptedAdvisorInterface`. No llama OpenAI ni involucra a un asesor real. Sirve para validar persistencia, audit y reporte. La respuesta incluye `execution_mode="scripted_demo"` y `is_production_ready=false`. |
| `GET` | `/workflow/{record_id}` | Recupera un workflow por ID |
| `GET` | `/reports/{record_id}` | Recupera un reporte por ID |
| `GET` | `/audit/{record_id}` | Recupera un audit trail por ID |
| `GET` | `/workflow` | Lista todos los workflows (filtrable por `client_id`) |
| `GET` | `/reports` | Lista todos los reportes (filtrable por `client_id`) |
| `GET` | `/audit` | Lista todos los audit trails (filtrable por `client_id`) |
| `POST` | `/live/portfolio-demo` | Portfolios con datos reales de yfinance (requiere internet) |
| `POST` | `/universe/filter-demo` | Filtro de universo CSV por preferencias estructuradas |
| `POST` | `/ai/profile-demo` | Análisis KYC con OpenAI (requiere API key) |
| `POST` | `/ai/profile-follow-up` | Segunda ronda de análisis con respuestas del asesor |
| `POST` | `/ai/filter-universe-demo` | Texto libre → OpenAI → filtro de universo |
| `POST` | `/ai/filtered-portfolio-demo` | Texto libre → OpenAI → filtro → snapshots → portfolios |

### Ejemplos de uso

#### POST /ai/filtered-portfolio-demo

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/ai/filtered-portfolio-demo `
  -H "Content-Type: application/json" `
  -d '{
    "client_id": "CLI-PREF-PORT-001",
    "profile": "moderado",
    "natural_language_preferences": "Solo quiero invertir en ONs hard dollar argentinas disponibles en Balanz y evitar energia."
  }'
```

#### POST /workflow/run

> **Scripted demo, not real AI flow.** Este endpoint usa `MockAIClient` (perfil preprogramado `moderado`) y `ScriptedAdvisorInterface` (aprobación automática). No llama OpenAI ni representa la aprobación de un asesor real. La respuesta incluye los campos `execution_mode="scripted_demo"`, `ai_source="mock_scripted"`, `advisor_source="scripted_auto_approve"`, `is_production_ready=false` y un `warning` declarando la naturaleza scripted. Para el flujo de IA real, ver `/ai/profile-demo`, `/ai/profile-follow-up`, `/ai/filter-universe-demo` y `/ai/filtered-portfolio-demo`.

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/workflow/run `
  -H "Content-Type: application/json" `
  -d '{
    "client_id": "CLI-001",
    "advisor_id": "ADV-001",
    "kyc_data": {
      "risk_tolerance_score": 6,
      "risk_capacity_score": 7,
      "liquidity_need_score": 3,
      "investment_horizon_years": 10,
      "investment_experience": "moderada",
      "income_stability": "stable",
      "net_worth": 500000,
      "liquid_net_worth": 200000,
      "max_acceptable_drawdown_pct": 25.0
    },
    "financial_goal": {
      "initial_amount": 100000,
      "target_amount": 200000,
      "horizon_years": 10,
      "annual_contribution": 5000
    }
  }'
```

##### Campos KYC adicionales (Fase 1.5 — opcionales, defaults backward-compatible)

El `kyc_data` acepta también los siguientes campos. Antes, `_build_kyc_data` los hardcodeaba silenciosamente; ahora se reciben del request y se validan.

| Campo | Tipo | Default | Reglas |
|---|---|---|---|
| `age` | int | `40` | `18 ≤ age ≤ 120` |
| `jurisdiction` | str | `"AR"` | min_length=1, sin solo-whitespace |
| `preferred_currency` | str | `"USD"` | min_length=1, sin solo-whitespace |
| `investment_objective` | str | `"balanced"` | uno de: `capital_preservation`, `income`, `balanced`, `growth`, `aggressive_growth` (case-insensitive, se normaliza a lowercase) |
| `prefers_simple_products` | bool | `false` | bool real (Pydantic acepta también truthy/falsy en modo laxo) |
| `annual_income_usd` | float \| null | `null` | si viene, `>= 0`; si es `null`, **fallback histórico**: `max(liquid_net_worth * 0.05, 1.0)` |
| `esg_strictness_level` | str | `"none"` | uno de: `none`, `light`, `strict`, `impact` (case-insensitive) |
| `esg_exclusions` | list[obj] | `[]` | cada item: `excluded_item` (no vacío), `exclusion_type` ∈ {`sector`, `activity`, `issuer`, `country`, `tag`, `controversy`}, `source` (no vacío), `rationale` (opcional) |
| `esg_preferences` | list[obj] | `[]` | cada item: `preference_type` (no vacío), `weight` ∈ `[0.0, 1.0]`, `minimum_threshold` (opcional float) |

Notas:
- El único default que sigue "inventando" valor es `annual_income_usd` cuando es `null`: se deriva del `liquid_net_worth` para no romper payloads viejos. Para evitar el fallback, mandar el valor explícito (incluido `0.0`).
- ESG sigue siendo **básico** intencionalmente: dos listas planas (`esg_exclusions`, `esg_preferences`) + nivel de strictness. No hay `esg_min_score` global porque el dominio (`ESGProfile`) no lo soporta directamente; se modela vía `ESGPreference.minimum_threshold` por preferencia.

Ejemplo con todos los campos nuevos:

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/workflow/run `
  -H "Content-Type: application/json" `
  -d '{
    "client_id": "CLI-002",
    "advisor_id": "ADV-001",
    "kyc_data": {
      "age": 45,
      "risk_tolerance_score": 7,
      "risk_capacity_score": 8,
      "liquidity_need_score": 2,
      "investment_horizon_years": 15,
      "investment_experience": "avanzada",
      "income_stability": "stable",
      "net_worth": 800000,
      "liquid_net_worth": 300000,
      "max_acceptable_drawdown_pct": 30.0,
      "jurisdiction": "MX",
      "preferred_currency": "USD",
      "investment_objective": "growth",
      "prefers_simple_products": false,
      "annual_income_usd": 180000,
      "esg_strictness_level": "light",
      "esg_exclusions": [
        { "excluded_item": "tobacco", "exclusion_type": "sector", "source": "client_explicit", "rationale": "Convicción personal." }
      ],
      "esg_preferences": [
        { "preference_type": "low_carbon", "weight": 0.6, "minimum_threshold": 50.0 }
      ]
    },
    "financial_goal": {
      "initial_amount": 100000,
      "target_amount": 300000,
      "horizon_years": 15,
      "annual_contribution": 8000
    }
  }'
```

---

## Portfolio: variantes y metadata de override

Cada ejecución del motor de portfolio genera hasta tres variantes candidatas:

| Variante | Objetivo | Relación con RiskBudget aprobado |
|---|---|---|
| `DEFENSIVE` | Mínima varianza | Más conservadora que el perfil aprobado |
| `BALANCED` | Máxima utilidad | Respeta estrictamente el RiskBudget aprobado — recomendación base |
| `GROWTH` | Máximo retorno | Puede exceder `max_volatility` del RiskBudget aprobado |

Cuando `GROWTH` excede el RiskBudget aprobado, `PortfolioCandidateSet` almacena en `metadata` un `PortfolioVariantMetadata` con `risk_budget_exceeded=True`, `requires_advisor_override=True`, `exceeded_constraints` y `reason_codes`. Este flag se expone en la API, en el reporte Markdown y en el frontend (banner de advertencia).

---

## Archivos generados localmente

| Archivo | Cuándo se genera | Contenido |
|---|---|---|
| `reports/demo_advisory_report.md` | `scripts/run_demo.py` | Reporte Markdown del workflow demo |
| `reports/demo_api_report.md` | `POST /demo/run` | Reporte Markdown vía API |
| `reports/workflow_<client_id>.md` | `POST /workflow/run` | Reporte Markdown por cliente |
| `data/demo_api.db` | `POST /demo/run`, `POST /workflow/run`, `POST /ai/filtered-portfolio-demo`, `POST /advisor/profile-approval`, `POST /advisor/override-approval` o `POST /advisor/portfolio-selection` | SQLite con workflow, audit, report, ai_filtered_portfolio, advisor_profile_approval, advisor_override_approval y advisor_portfolio_selection records |

Estos archivos están en `.gitignore`. Los record IDs son secuenciales por prefijo y se resetean si el servidor se reinicia sin persistencia previa.

---

## Fixtures

| Directorio | Contenido |
|---|---|
| `tests/fixtures/kyc_profiles/` | Perfiles KYC en JSON |
| `tests/fixtures/universes/` | Universos de productos aprobados en YAML |
| `tests/fixtures/suitability/` | Matriz de suitability en YAML |
| `tests/fixtures/esg/` | Metadata ESG en YAML |
| `tests/fixtures/market_data/` | Precios y datos de mercado en YAML |
| `tests/fixtures/universe/sample_instrument_universe.csv` | 20 instrumentos (ETF, CORPORATE_BOND, SOVEREIGN_BOND, MONEY_MARKET, CEDEAR) para demo de filtrado y portfolio |

---

## Próximos pasos

| Área | Descripción | Prioridad |
|---|---|---|
| ~~Reportes AI filtered portfolio~~ | ✅ Cerrado en Fase 0. `POST /ai/filtered-portfolio-demo` devuelve `report_markdown` generado por `AIFilteredPortfolioReportGenerator`. | — |
| ~~Persistencia del flujo filtrado~~ | ✅ Cerrado en Fase 0. La respuesta se persiste en SQLite como record `ai_filtered_portfolio` (con `record_id`) y el reporte como `markdown_report` (con `report_record_id`). | — |
| ~~Firma de override del asesor~~ | ✅ Cerrado en Fase 1. `POST /advisor/override-approval` registra `approve`/`reject` sobre una variante (típicamente GROWTH) con rationale obligatorio, reason_codes y exceeded_constraints. Persiste como `advisor_override_approval_NNNNNN` en SQLite. Auth requerida. | — |
| ~~Selección de variante por asesor~~ | ✅ Cerrado en Fase 1. `POST /advisor/portfolio-selection` registra la variante final (`DEFENSIVE`/`BALANCED`/`GROWTH`) a presentar al cliente, con `related_record_id`, `override_approval_record_id` opcionales y rationale obligatorio. Warning si GROWTH se selecciona sin override link (persistido en payload). Persiste como `advisor_portfolio_selection_NNNNNN`. Auth requerida. | — |
| Expandir universo de instrumentos | Reemplazar el CSV de 20 instrumentos de muestra por un universo real de ONs, ETFs y bonos soberanos con datos actualizados | Media |
| Provider de datos externo | Conectar `InstrumentMarketDataAdapter` a una fuente de datos de producción (Bloomberg, Refinitiv, proveedor local) en lugar de derivar retornos desde ytm/coupon del CSV | Media |
| Auth para producción | Reemplazar el Bearer token hard-coded (Fase 1 dev-only) por JWT firmado por IdP (OIDC/SAML) con RBAC por rol, rotación, TTL y multi-tenant (`firm_id`). Proteger todos los endpoints antes de cualquier exposición en red. | Alta (pre-producción) |
| Reporte profesional | Formato de reporte para presentación al cliente y al asesor; PDF generado desde Markdown o template HTML | Media |
| PostgreSQL y multi-sesión | Migrar SQLite a PostgreSQL para soporte multi-usuario y persistencia entre reinicios del servidor | Media |
| MiFID II / CNBV compliance completo | Cuestionario de idoneidad regulatoria explícito, firma digital del asesor, modelo de conocimiento y experiencia detallado | Baja (M3) |

---

## Principios del sistema

1. La IA no recomienda inversiones ni decide pesos de cartera.
2. El asesor valida el perfil, resuelve contradicciones y aprueba carteras.
3. El universo nace de governance, no del proveedor de datos.
4. El perfil surge de tolerancia + capacidad — nunca de la necesidad de retorno.
5. `preliminary_profile` (propuesto por IA) y `approved_profile` (validado por asesor) son conceptos distintos.
6. Solo `ApprovedPortfolio` puede presentarse al cliente.
7. Todo motivo cita un `ReasonCode`. Todo evento queda en audit trail.
8. Si `GROWTH` excede el RiskBudget aprobado, ese exceso no queda oculto — queda marcado, auditado y visible en el reporte y en el frontend.
9. La IA estructura preferencias del cliente; el motor determinístico filtra el universo. La separación es explícita e inmutable.

---

## Compliance

Este software no constituye recomendación de inversión. Es una herramienta de soporte para asesores financieros matriculados, que mantienen la responsabilidad profesional sobre toda decisión presentada al cliente.

Los retornos esperados son estimaciones técnicas derivadas de datos proxy (YTM, cupón) para el universo de demo. No son predicciones ni garantías. En producción deben reemplazarse por datos de mercado con fuente auditada y SLA de frescura documentado.

Ver `docs/COMPLIANCE_NOTES.md` para el análisis detallado de las decisiones de arquitectura con impacto regulatorio.
