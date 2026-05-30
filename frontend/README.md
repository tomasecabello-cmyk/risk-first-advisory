# Frontend — Risk-First Advisory Dev UI

Página HTML estática para probar visualmente el backend sin usar terminal ni curl.

Estructura (Phase 3 frontend split — sin build step ni dependencias):

```
frontend/
├── index.html              # solo HTML estructural (cards + forms)
├── css/
│   └── base.css            # estilos compartidos (reset, layout, cards, pills, forms)
└── js/
    ├── common.js           # helpers globales (el, formatJSON, escapeHTML, apiError, statusPill, ...)
    ├── legacy-demo.js      # cards Phase 0/1: health, workflow, AI demos, advisor decisions, persisted
    ├── case-dashboard.js   # card "Case Dashboard — Phase 2" (cd-* / cd*)
    └── case-workbench.js   # card "Case Workbench — Phase 2 Workflow" (cw-* / cw*)
```

**Sin frameworks. Sin CDN. Sin dependencias.** Scripts cargados en orden clásico (no ES modules) para preservar los `onclick="..."` handlers globales del HTML. `case-dashboard.js` debe cargarse antes que `case-workbench.js` porque el Workbench reusa helpers `cd*` (`cdToken`, `cdAuthHeaders`, `cdApiFetch`, `cdNullIfBlank`).

---

## Requisitos

El backend FastAPI debe estar corriendo localmente. Sin él, el frontend no puede hacer ninguna request.

---

## Cómo iniciar el backend

Desde el directorio raíz del proyecto, con el virtualenv activado:

```powershell
cd C:\Users\maria\risk-first-advisory
.\.venv\Scripts\Activate.ps1
uvicorn risk_first_advisory.api_layer.main:app --reload
```

El backend queda disponible en:

```
http://127.0.0.1:8000
```

Documentación interactiva del backend:
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

---

## Cómo abrir el frontend

### Opción A — Directo desde el navegador (puede fallar por CORS)

Abrir el archivo directamente:

```
frontend/index.html
```

O hacer doble clic en el explorador de archivos.

**Limitación:** algunos navegadores bloquean requests `fetch()` cuando la página se sirve desde `file://` (política CORS de origen cruzado entre `file://` y `http://`). Si las requests fallan con error de CORS, usar la Opción B.

### Opción B — Servidor HTTP local (recomendado)

Servir el frontend con Python desde el directorio raíz del proyecto:

```powershell
python -m http.server 5500 -d frontend
```

Luego abrir en el navegador:

```
http://127.0.0.1:5500
```

Esta opción evita los problemas de CORS porque la página se sirve desde `http://` y hace requests a `http://`, sin cruce de esquemas.

---

## Endpoints que consume

| Sección | Método | Ruta | Descripción |
|---|---|---|---|
| API Health | `GET` | `/health` | Verifica que el backend responde |
| Scripted Workflow Demo | `POST` | `/workflow/run` | **Scripted deterministic demo.** Usa MockAIClient + ScriptedAdvisorInterface. No llama OpenAI ni involucra a un asesor real. Sirve para validar pipeline, persistencia, audit y reporte. |
| Live Portfolio Demo | `POST` | `/live/portfolio-demo` | Portfolios reales con datos de yfinance |
| AI Profile Demo | `POST` | `/ai/profile-demo` | Análisis KYC con OpenAI (requiere API key) |
| AI Profile Follow-up | `POST` | `/ai/profile-follow-up` | Segunda ronda de análisis con respuestas del cliente |
| AI Universe Filter Demo | `POST` | `/ai/filter-universe-demo` | Lenguaje natural → OpenAI → filtro de universo (requiere API key) |
| AI Filtered Portfolio Demo | `POST` | `/ai/filtered-portfolio-demo` | Lenguaje natural → OpenAI → filtro → snapshots → portfolios candidatos (requiere API key) |
| Persisted Workflows | `GET` | `/workflow` | Lista todos los workflows |
| Persisted Workflows | `GET` | `/workflow?client_id=...` | Filtra workflows por cliente |
| **Case Dashboard (Phase 2)** | `GET` | `/auth/me` | Verifica el token activo |
| **Case Dashboard (Phase 2)** | `GET`/`POST` | `/firms` | Lista/crea firms |
| **Case Dashboard (Phase 2)** | `GET`/`POST` | `/advisors` | Lista/crea advisors |
| **Case Dashboard (Phase 2)** | `GET`/`POST` | `/clients` | Lista/crea clients |
| **Case Dashboard (Phase 2)** | `GET`/`POST` | `/cases` | Lista/crea cases |
| **Case Dashboard (Phase 2)** | `GET` | `/cases/{case_id}/summary` | Estado completo del case seleccionado |
| **Case Workbench (profile steps)** | `GET` | `/cases/{case_id}/summary` | Refresh del state después de cada paso |
| **Case Workbench (profile steps)** | `POST` | `/cases/{case_id}/kyc` | Submit KYC submission para el case |
| **Case Workbench (profile steps)** | `POST` | `/cases/{case_id}/ai/profile-analysis` | Análisis IA sobre el current KYC |
| **Case Workbench (profile steps)** | `POST` | `/cases/{case_id}/profile-approval` | Decisión del advisor (approve/modify/reject) |
| **Case Workbench (portfolio/report)** | `POST` | `/cases/{case_id}/investment-preferences` | Preferences (manual JSON o NLP→IA) |
| **Case Workbench (portfolio/report)** | `POST` | `/cases/{case_id}/universe-filter` | Filter run sobre CSV |
| **Case Workbench (portfolio/report)** | `POST` | `/cases/{case_id}/portfolio-proposal` | Generación de candidates |
| **Case Workbench (portfolio/report)** | `POST` | `/cases/{case_id}/override-approval` | Decisión de override para variants exceeding-budget |
| **Case Workbench (portfolio/report)** | `POST` | `/cases/{case_id}/portfolio-selection` | Selección final del advisor |
| **Case Workbench (portfolio/report)** | `POST` | `/cases/{case_id}/reports` | Genera markdown report determinístico |
| **Case Workbench (audit & logs)** | `GET` | `/cases/{case_id}/audit` | Lista de AuditEvents del case (hash chain) |
| **Case Workbench (audit & logs)** | `GET` | `/cases/{case_id}/audit/verify` | Verifica integridad del hash chain (admin/compliance) |
| **Case Workbench (audit & logs)** | `GET` | `/cases/{case_id}/ai-logs` | AIRequestLogs del case con input redactado (admin/compliance) |

---

## Seed demo data (recomendado antes de la primera demo visual)

Para evitar tipear firm/advisor/client/case a mano, correr desde la raíz del repo:

```powershell
python scripts/seed_demo_data.py
```

Crea (o reusa, si ya existen) las 4 entidades base con IDs estables:

- `firm_demo_local`
- `advisor_demo_local`
- `client_demo_local`
- `case_demo_local`

Idempotente — correr múltiples veces es seguro. Aplica migrations si hace falta. Tras esto, el Case Dashboard puede listar todo y el Case Workbench puede abrir `case_demo_local` directamente. El seed **NO** completa KYC/análisis/portfolio/report — para eso usar el Workbench panel por panel o `python scripts/run_case_workflow_smoke_check.py`.

---

## Case Dashboard — Phase 2

Nueva sección al final del index para **visualizar y crear las entidades base del flujo case-scoped**: firms → advisors → clients → cases → summary. Es la primera entrada visual al backend Fase 2; **NO es el Case Workbench completo** (las acciones del workflow — KYC, AI profile analysis, profile approval, investment preferences, universe filter, portfolio proposal, override approval, portfolio selection, report — **todavía no se invocan desde esta UI**).

### Qué permite hoy

1. **Auth token activo** — input Bearer + botón `Check /auth/me` que muestra `advisor_id`, `roles`, `firm_id`.
2. **Firms** — `List` + `Create` (admin only). Auto-propaga el `firm_id` creado a los inputs de advisors/clients/cases.
3. **Advisors** — `List` + `Create` (admin only). Auto-propaga el `advisor_id` a inputs downstream.
4. **Clients** — `List` + `Create` (admin / advisor). Auto-propaga el `client_id`.
5. **Cases** — `List` + `Create` (admin / advisor). Auto-popula `Selected case_id` para el panel de summary.
6. **Quick demo seed** — botón `Create demo firm + advisor + client + case` que ejecuta los 4 POSTs en cascada con IDs explícitos (`firm_demo_local`, `advisor_demo_local`, `client_demo_local`). Maneja `409 duplicate` reusando los IDs existentes.
7. **Case Summary** — input `case_id` + botón `Load Summary` que consume `GET /cases/{case_id}/summary` y muestra una tabla con: case overview, `progress.completion_ratio`, `progress.next_recommended_action`, todos los `has_*` flags, `audit.is_intact`, `ai.ai_logs_count`, `current_report.report_id`, más el JSON completo abajo.

### Qué NO permite todavía (queda para Case Workbench, Fase 3)

- POST `/cases/{id}/kyc` — KYC submission con formulario completo.
- POST `/cases/{id}/ai/profile-analysis`, `/profile-approval`, `/investment-preferences`, `/universe-filter`, `/portfolio-proposal`, `/override-approval`, `/portfolio-selection`, `/reports`.
- GET `/cases/{id}/audit`, `/audit/verify`, `/ai-logs`.

Para ejercitar el workflow case-scoped completo hoy:

```powershell
python scripts/run_case_workflow_smoke_check.py
```

o usar Swagger UI directamente: `http://127.0.0.1:8000/docs`.

### Tokens

La sección usa por default `dev-advisor-token` (fallback hard-coded del backend, rol `advisor`). Para acciones que requieren `admin` (crear firm, crear advisor, seed demo), reemplazar por `dev-admin-token` o por un token cargado vía `config/advisor_tokens.yaml` / `ADVISOR_TOKENS_FILE`. El input es global a la card del Case Dashboard.

### Disclaimers visibles en la UI

- "Phase 2 backend workflow — local/dev UI"
- "NOT production-ready"
- "case-scoped flow"
- "full workbench pending"

---

## Case Workbench — Phase 2 Workflow

Card al final del index (después del Case Dashboard) que cubre **el workflow case-scoped completo + audit/compliance review** en 15 secciones agrupadas en 3 bloques:

### Bloque A — Profile steps (1–4)

1. **Cargar summary** del `case_id` activo (`GET /cases/{case_id}/summary`).
2. **Submit KYC** con formulario completo (`POST /cases/{case_id}/kyc`).
3. **Run AI Profile Analysis** (`POST /cases/{case_id}/ai/profile-analysis`).
4. **Advisor Profile Approval** (`POST /cases/{case_id}/profile-approval`) con decisión approve/modify/reject.

### Bloque B — Portfolio/report steps (5–11)

5. **Investment Preferences** (`POST /cases/{case_id}/investment-preferences`) — modo manual con JSON, o NLP opcional para extracción IA.
6. **Universe Filter** (`POST /cases/{case_id}/universe-filter`) — aplica `PreferenceFilterEngine` sobre el CSV; muestra eligible/excluded counts + top 5 instruments.
7. **Portfolio Proposal** (`POST /cases/{case_id}/portfolio-proposal`) — tabla de candidates con E[ret], vol, requires_advisor_override.
8. **Override Approval** (`POST /cases/{case_id}/override-approval`) — preselecciona variant que requiere override desde el current proposal.
9. **Portfolio Selection** (`POST /cases/{case_id}/portfolio-selection`) — preselecciona variant según override approval + non-override candidates; transiciona case a `PORTFOLIO_SELECTED`.
10. **Report Generation** (`POST /cases/{case_id}/reports`) — markdown determinístico con metadata.
11. **Compact final summary** — re-render del state combinado con flags portfolio/report.

### Bloque C — Audit & Compliance (12–15)

12. **Audit Trail** (`GET /cases/{case_id}/audit`) — tabla con `sequence`, `event_type`, `actor_role`, `actor_advisor_id`, `created_at_utc`, y `previous_hash` / `payload_hash` / `event_hash` truncados (hover = hash completo).
13. **Audit Verification** (`GET /cases/{case_id}/audit/verify`) — recomputa el hash chain y reporta `is_intact`, `total_events`, `first_broken_sequence`, `message`. Pill verde (INTACT) o roja (BROKEN). **Requiere rol `admin` o `compliance`** (advisor recibe 403).
14. **AI Request Logs** (`GET /cases/{case_id}/ai-logs`) — tabla con `request_id`, `endpoint`, `model`, `prompt_version`, `validation_status` (pill verde/roja), `latency_ms`, `created_at_utc`, `error_message`. Latest log expone `input_redacted` (sanitizado por backend) y `raw_response` (con warning de "no necesariamente redactado — revisar antes de exportar"). **Requiere rol `admin` o `compliance`**.
15. **Compliance Snapshot** — vista combinada `summary` + `audit/verify` + `ai-logs` (3 GETs en paralelo). Sub-requests fallidas se reportan como pills "skipped (HTTP X)" sin abortar el resto. Útil para handoff a compliance review en un solo paso.

### Privacidad

- **`input_redacted`** se muestra tal cual viene del backend — la redacción es responsabilidad del repo (`SQLiteAIRequestLogRepository`), no del frontend.
- **`raw_response`** se incluye en el panel pero **con warning visible**: no compartir exportes sin revisar.
- **El frontend NO agrega lógica de redacción** — para mantener al backend como única fuente de verdad de qué se sanitiza.
- **Export package compliance-ready (ZIP)** y **PDF export del report** siguen pendientes en Fase 3.

### Auto-refresh

- Cada POST exitoso (KYC, análisis, approval, preferences, filter, proposal, override, selection, report) llama `cwRefreshAfterPost`, que hace **una sola** GET al summary y re-renderiza el summary panel + final panel si están visibles.
- **Audit panel, audit verify y AI logs panels NO se auto-refrescan** después de cada POST — son carga manual con sus botones (decisión: evitar polling agresivo / requests innecesarias). El botón "Refresh Compliance Snapshot" recarga los tres GETs en paralelo cuando el usuario lo pide.

### Manejo de errores

Cada panel renderiza mensajes específicos por status:
- **400**: `OPENAI_API_KEY` no configurada (análisis IA / preferences NLP).
- **401**: token inválido o ausente.
- **403**: el token no tiene rol requerido — verify y ai-logs requieren `admin`/`compliance`; POSTs requieren `admin`/`advisor`.
- **404**: `case_id` (o report_id en GET single) inexistente.
- **409**: case `CLOSED`; sin KYC para análisis; sin investment_preferences para filter; sin proposal para override/selection; sin selection para report; override con decision=reject al seleccionar.
- **422**: validation fail (rangos KYC, coherencia approve/modify/reject, cross-resource mismatch entre IDs).
- **502**: la llamada IA falló — ver AI Request Logs panel para el log `api_error`.

### Token

Reusa el mismo input `Bearer token` del Case Dashboard (no hay un segundo campo). Cambios al token en el Dashboard afectan automáticamente al Workbench. Para verify + AI logs cambiar a `dev-admin-token` o `dev-compliance-token`.

### Lo que NO incluye este Workbench

- **Auto-refresh** del audit y AI logs panels después de cada POST (manual por design — ver "Auto-refresh" arriba).
- **PDF export** del report (solo markdown).
- **Compliance export package** (ZIP con report + audit + logs sanitizados).
- **Frontend refactor / split** (sigue siendo single-file HTML + vanilla JS).

Para ejercitar el workflow completo hoy sin UI:

```powershell
python scripts/run_case_workflow_smoke_check.py
```

o usar Swagger UI directamente: `http://127.0.0.1:8000/docs`.

---

## Secciones del formulario

### API Health
Botón "Check API" — llama `GET /health` y muestra la respuesta. Útil para verificar que el backend está corriendo antes de ejecutar el workflow.

### Scripted Workflow Demo

> **Endpoint scripted determinístico.** Usa `MockAIClient` (perfil preprogramado `moderado`, sin contradicciones, sin follow-up) y `ScriptedAdvisorInterface` (aprobación automática). **No llama OpenAI** y **no involucra a un asesor humano real**. Pensado para validar el pipeline determinístico — governance → suitability → ESG → data quality → optimizer — junto con persistencia en SQLite, audit trail y reporte Markdown. No usar como flujo productivo de asesoría real. Los demos de IA real son `/ai/profile-demo`, `/ai/profile-follow-up`, `/ai/filter-universe-demo` y `/ai/filtered-portfolio-demo`.

Formulario con todos los campos de `KYCData` y `FinancialGoal`. Valores por defecto razonables para un perfil moderado. Campos opcionales pueden dejarse en blanco.

Al ejecutar:
- Muestra un resumen estructurado: status, perfil aprobado, portfolios generados, tickers, reason codes, warnings, IDs persistidos.
- La respuesta JSON incluye los campos `execution_mode="scripted_demo"`, `ai_source="mock_scripted"`, `advisor_source="scripted_auto_approve"`, `is_production_ready=false` y `warning` declarando explícitamente la naturaleza scripted del endpoint.
- La lista `warnings` siempre incluye el aviso scripted además de los warnings naturales del workflow.
- Muestra el JSON completo de la respuesta en un bloque colapsable.

### Live Portfolio Demo
Descarga datos históricos reales de ETFs vía **yfinance** y genera hasta 3 portfolios candidatos (DEFENSIVE / BALANCED / GROWTH) para el perfil seleccionado.

Selectores:
- **profile** — perfil de riesgo aprobado (conservador → agresivo)
- **period** — período histórico de descarga (1y / 2y / 3y / 5y)
- **interval** — frecuencia de datos (1d daily / 1wk weekly)

Al ejecutar:
- Muestra un summary: status, tickers usables/fallidos, DQ warnings.
- Por cada variante generada: retorno esperado, volatilidad, risk score, barra de pesos, metadata de risk budget.
- Si GROWTH requiere advisor override (siempre relaja `max_volatility`), se muestra un banner de advertencia con los constraints excedidos.
- Si `status=insufficient_data` o `status=infeasible`, se muestra el mensaje de error en lugar de portfolios.
- Muestra el JSON completo colapsable.

**Notas importantes:**
- Usa datos **gratuitos de Yahoo Finance** vía yfinance. No es una fuente de producción.
- La descarga puede tardar **5–15 segundos** según la velocidad de conexión.
- **Requiere conexión a internet.** Sin ella, todos los snapshots fallan y el status será `insufficient_data`.
- **No persiste resultados** en SQLite ni genera reporte Markdown.
- **No usa IA** ni KYC del cliente. El perfil se selecciona directamente.
- Los parámetros del Risk Budget (volatilidades, límites de asset class) se toman directamente de `PROFILE_BASE_PARAMS` sin ajustes de KYC.
- El universo fijo es 11 ETFs: BIL, SHV, AGG, BND, IEF, VTI, SPY, VEA, VWO, HYG, GLD.

### AI Profile Demo

Llama a `POST /ai/profile-demo` usando el **OpenAIProfileClient** del backend.

**Requiere OPENAI_API_KEY** en la terminal donde corre uvicorn. Sin la key, el endpoint devuelve HTTP 400 y el frontend muestra el mensaje de error con el comando de inicio correcto.

Para iniciar el backend con la key:

**PowerShell:**
```powershell
$env:OPENAI_API_KEY="your_key_here"
uvicorn risk_first_advisory.api_layer.main:app --reload
```

> ⚠ No subir la key a Git. No crear `.env`. No hardcodear secretos.

Si la key no está configurada, el frontend muestra:
> "OPENAI_API_KEY is not configured in the backend terminal."

Si el endpoint devuelve 502, el frontend muestra:
> "AI profile analysis failed. Check backend logs or API key."

**Características de esta demo:**
- Usa `OpenAIProfileClient` con modelo `gpt-4o-mini`, `temperature=0.2`.
- Analiza coherencia del KYC y detecta contradicciones entre campos.
- Devuelve: `preliminary_profile`, `confidence`, `contradictions`, `follow_up_questions`, `advisor_notes`.
- **No persiste** resultados en SQLite ni genera reporte Markdown.
- **No aprueba** el perfil final — solo el asesor humano puede hacerlo.
- **No genera** portfolios ni asset allocations.
- **No recomienda** productos, tickers ni ETFs.
- **No usa** `declared_return_expectation_pct` para construir el perfil (es información para el asesor, no para la IA).

Los valores por defecto del formulario corresponden al test manual con KYC contradictorio:
- `risk_tolerance_score=4` (bajo) pero `risk_capacity_score=8` (alto) → contradicción intencionada.
- `liquidity_need_score=7` (alta liquidez) con horizonte de 15 años → tensión detectada por la IA.

**Copiar perfil al Live Portfolio Demo:**
El resultado incluye el botón "↓ Use this profile in Live Portfolio Demo". Al hacer click:
- Copia `preliminary_profile` al selector de la sección Live Portfolio Demo.
- Hace scroll suave hacia esa sección.
- No ejecuta el portfolio automáticamente — el asesor decide cuándo presionar "Run Live Portfolio".
- Si el perfil sugerido no existe como opción, muestra un error claro sin romper la página.
- **No implica aprobación.** Es solo un helper de navegación para el asesor.

**Flujo de dos rondas — Follow-up:**

Si la IA detecta contradicciones o incertidumbre, devuelve `follow_up_questions` (lista no vacía). En ese caso el frontend muestra automáticamente un formulario de respuestas:

1. **Ronda 1 — Análisis KYC inicial** (`POST /ai/profile-demo`):
   - Completa el formulario KYC y presiona "Analyze with AI".
   - El resultado muestra: `preliminary_profile`, `confidence`, `contradictions`, `follow_up_questions`, `advisor_notes`.
   - Si hay follow-up questions, aparece el formulario de respuestas debajo.

2. **Ronda 2 — Follow-up** (`POST /ai/profile-follow-up`):
   - Escribe una respuesta en cada textarea (todas son obligatorias).
   - Presiona "Submit Follow-up Answers".
   - El spinner "Calling OpenAI follow-up analysis…" aparece mientras espera.
   - El resultado se muestra en un bloque verde (borde `#86efac`) debajo del primer resultado:
     - `revised_profile` — perfil revisado (pill verde).
     - `confidence` — barra de confianza actualizada.
     - `profile_change_reason` — caja verde con el razonamiento de la revisión.
     - `remaining_contradictions` — cards de severidad con las contradicciones no resueltas (vacío = todas resueltas).
     - `advisor_notes` — notas finales para el asesor (lista numerada).
     - Botón "↓ Use revised profile in Live Portfolio Demo" — copia `revised_profile` al selector.

3. **Ejecutar un nuevo análisis KYC** limpia el resultado de follow-up y reinicia el estado global.

**Manejo de errores del follow-up:**
- HTTP 400 → OPENAI_API_KEY no configurado (mismo mensaje que ronda 1).
- HTTP 502 → Fallo en el análisis (logs del backend / API key).
- HTTP 422 → Errores de validación Pydantic (detalle expandido).
- Error de red → Mensaje con instrucciones de uvicorn.

### AI Universe Filter Demo

Llama a `POST /ai/filter-universe-demo` — pipeline combinado de dos pasos:

1. **Paso 1 — Extracción de preferencias (OpenAI):** el texto libre del cliente se envía a `OpenAIProfileClient.extract_investment_preferences()`. La IA devuelve un JSON estructurado con tipos de instrumento permitidos/excluidos, moneda, país, entidad, sectores a evitar, hard dollar, etc.

2. **Paso 2 — Filtro determinístico (universe_layer):** las preferencias extraídas se aplican sobre `tests/fixtures/universe/sample_instrument_universe.csv` usando `PreferenceFilterEngine`. El resultado indica qué instrumentos pasan todos los filtros activos y cuáles son excluidos, con razones por ticker.

**Requiere OPENAI_API_KEY** en la terminal donde corre uvicorn. Sin la key, el endpoint devuelve HTTP 400 y el frontend muestra el mensaje de error con el comando de inicio correcto.

**Características:**
- Muestra preferencias estructuradas detectadas por la IA: `allowed_instrument_types`, `excluded_instrument_types`, `currency`, `country`, `entity`, `hard_dollar_only`, `avoid_sectors`, `prefer_sectors`, `avoid_issuers`, `prefer_issuers`, `min_liquidity_score`, `max_maturity_year`, `hard_constraints`, `soft_preferences`, `unparsed_preferences`, `advisor_notes`, `confidence`.
- Tabla de **instrumentos elegibles** con acento visual verde: ticker, name, issuer, type, asset class, currency, country, sector, hard dollar, maturity, YTM, duration, liquidity score, rating.
- Tabla de **instrumentos excluidos** con acento visual rojo: ticker + chips con las razones de exclusión (`not_available_at_entity:X`, `instrument_type_not_allowed:X`, `sector_avoided:X`, etc.).
- Lista de **filtros aplicados** como chips.
- Lista de **warnings** (prefer_* hints, claves desconocidas, fechas de vencimiento faltantes).
- JSON completo colapsable.

**Limitaciones / notas:**
- **No genera portfolios.** No calcula pesos ni retornos esperados.
- **No trae datos de mercado.** No llama a yfinance ni Bloomberg.
- **No persiste resultados** en SQLite ni genera reporte Markdown.
- **Universo fijo:** `tests/fixtures/universe/sample_instrument_universe.csv` — 20 instrumentos de muestra (ETF, CORPORATE_BOND, SOVEREIGN_BOND, MONEY_MARKET, CEDEAR).
- Los filtros son determinísticos: mismas preferencias → mismo resultado siempre.
- El filtro `prefer_sectors` / `prefer_issuers` genera un warning pero no excluye instrumentos (solo `avoid_*` excluye).

**Manejo de errores:**
- HTTP 400 → OPENAI_API_KEY no configurada → mensaje con instrucciones de inicio.
- HTTP 502 → Fallo de la IA (respuesta inválida o error de API) → mensaje con instrucción de revisar logs.
- HTTP 500 → CSV del universo no encontrado en el servidor.
- HTTP 422 → Preferencias extraídas por la IA contienen valores inválidos (tipo de instrumento desconocido, liquidity fuera de rango, etc.).
- Error de red → `"API not reachable. Start uvicorn first."`

**Valores por defecto del formulario:**
- `client_id` = `CLI-PREF-001`
- `natural_language_preferences` = `"Solo quiero invertir en ONs hard dollar argentinas disponibles en Balanz y evitar energia."`

Con esta entrada, la IA extrae: `CORPORATE_BOND`, `USD`, `Argentina`, `Balanz`, `hard_dollar_only=true`, `avoid_sectors=[Energy]` — y el filtro devuelve los instrumentos hard-dollar argentinos de Balanz que no son del sector Energy (GALI28 y los nuevos ONs agregados al fixture).

---

### AI Filtered Portfolio Demo

Llama a `POST /ai/filtered-portfolio-demo` — pipeline completo de cuatro pasos:

1. **Paso 1 — Extracción de preferencias (OpenAI):** el texto libre del cliente se envía a `OpenAIProfileClient.extract_investment_preferences()`. La IA devuelve un JSON estructurado con tipos de instrumento permitidos/excluidos, moneda, país, entidad, sectores a evitar, hard dollar, etc.

2. **Paso 2 — Filtro determinístico (universe_layer):** las preferencias extraídas se aplican sobre `tests/fixtures/universe/sample_instrument_universe.csv` usando `PreferenceFilterEngine`.

3. **Paso 3 — Snapshots de mercado:** los instrumentos elegibles se convierten a `MarketDataSnapshot` via `InstrumentMarketDataAdapter`. Solo los snapshots con `expected_return_annual` disponible son usables para optimización.

4. **Paso 4 — Generación de portfolios:** si hay suficientes snapshots usables, `ReturnEstimator` + `CovarianceEngine` + `PortfolioGenerationCoordinator` generan hasta 3 variantes: **DEFENSIVE / BALANCED / GROWTH**.

**Requiere OPENAI_API_KEY** en la terminal donde corre uvicorn. Sin la key, el endpoint devuelve HTTP 400.

**Selectores del formulario:**
- **client_id** — identificador del cliente (default: `CLI-PREF-PORT-001`).
- **profile** — perfil de riesgo (conservador / moderado-defensivo / moderado / moderado-agresivo / agresivo). Determina el `RiskBudget` aplicado al optimizador.
- **natural_language_preferences** — texto libre del cliente con sus preferencias de inversión.

**Resultado cuando `status=completed`:**
- **Resumen:** status, profile, eligible_count, excluded_count, snapshot_count, candidate_count, confianza de la IA.
- **Preferencias detectadas:** todos los campos del resultado de OpenAI (tipos permitidos/excluidos, entity, currency, country, hard_dollar_only, sectores evitados/preferidos, min_liquidity_score, max_maturity_year, hard_constraints, soft_preferences, advisor_notes).
- **Filtros aplicados** — chips con los criterios activos.
- **Warnings** — chips de advertencia (prefer_* hints, claves desconocidas, etc.).
- **Tabla de instrumentos elegibles** — ticker, nombre, emisor, tipo, moneda, país, sector, hard dollar, vencimiento, YTM, duración, liquidez, rating.
- **Tabla de snapshots usables** — ticker, retorno esperado anual, volatilidad anual, duración, liquidez.
- **Portfolios candidatos** — hasta 3 cards (DEFENSIVE / BALANCED / GROWTH), cada una con retorno esperado, volatilidad, risk score, barra de pesos por activo, metadata de risk budget.
  - Si GROWTH requiere `advisor_override` (relaja `max_volatility`), se muestra el banner de advertencia con los constraints excedidos.
- **Tabla de instrumentos excluidos** — ticker + chips con razones de exclusión.
- **JSON completo** colapsable.

**Resultado cuando el portfolio está bloqueado:**
- `status=blocked_insufficient_universe` — menos de 3 snapshots usables (universo filtrado demasiado pequeño para cualquier portfolio).
- `status=blocked_insufficient_diversification_capacity` — snapshots usables < `ceil(1 / max_single_asset)` requerido por el perfil (por ejemplo, perfil `moderado` con `max_single_asset=0.15` requiere al menos 7 activos).
- `status=infeasible` — el optimizador no encontró solución factible con los constraints del risk budget.
- En todos los casos bloqueados se muestra el `message` explicativo en una caja de status destacada (azul para insuficiente, rojo para infeasible).

**Notas importantes:**
- **Requiere OPENAI_API_KEY.** Sin la key, HTTP 400 con instrucciones de inicio.
- **Persiste resultados en SQLite** (Fase 0). Cada respuesta — bajo cualquier `status` — guarda el payload completo como record `ai_filtered_portfolio` (`record_id`) y el reporte como `markdown_report` (`report_record_id`). El frontend muestra ambos IDs en el bloque "Result". **No se escriben archivos `.md` a disco.**
- **Devuelve `report_markdown`** — string Markdown determinístico (10 secciones) generado por `AIFilteredPortfolioReportGenerator`. El frontend lo muestra en una sección colapsable con un botón **"Copy Markdown Report"** que copia el reporte al portapapeles para que el asesor lo pegue donde necesite revisarlo.
- **No aprueba** el perfil final — solo el asesor puede hacerlo.
- Los retornos esperados y volatilidades se calculan desde los campos `ytm` y `coupon_rate` del CSV (instrumentos de renta fija). ETFs, CEDEARs y acciones no tienen snapshots usables en esta demo.
- **Universo fijo:** `tests/fixtures/universe/sample_instrument_universe.csv` — 20 instrumentos de muestra.

**Manejo de errores:**
- HTTP 400 → OPENAI_API_KEY no configurada → mensaje con instrucciones de inicio.
- HTTP 502 → Fallo de la IA (OpenAI) → mensaje con instrucción de revisar logs.
- HTTP 422 → Perfil inválido o campos requeridos faltantes.
- Error de red → `"API not reachable. Start uvicorn first."`

**Valores por defecto del formulario:**
- `client_id` = `CLI-PREF-PORT-001`
- `profile` = `moderado`
- `natural_language_preferences` = `"Solo quiero invertir en ONs hard dollar argentinas disponibles en Balanz y evitar energia."`

Con esta entrada y perfil `moderado`, la IA extrae preferencias de ONs hard dollar argentinas en Balanz sin sector Energía — y el optimizador genera 3 portfolios candidatos con los instrumentos elegibles que tienen datos de mercado usables.

---

### Advisor Decisions Demo — Phase 1

Card nuevo que permite probar desde el navegador los tres actos formales del asesor y el endpoint de diagnóstico de autenticación. Está pensada para acompañar la demo del flujo completo (AI Filtered Portfolio → advisor reviews → final selection) sin tener que usar `curl` o Swagger UI.

> ⚠ **Auth de desarrollo únicamente.** Usa tokens hard-coded del scaffold `api_layer/auth.py`. No es un identity provider productivo. No reemplaza firma digital ni compliance.

#### Endpoints consumidos

| Sección | Método | Ruta |
|---|---|---|
| 1. Advisor token | `GET` | `/auth/me` |
| 2. Profile approval | `POST` | `/advisor/profile-approval` |
| 3. Override approval | `POST` | `/advisor/override-approval` |
| 4. Portfolio selection | `POST` | `/advisor/portfolio-selection` |

#### Tokens demo

Un único input (`advisor_token`) en la parte superior del card se reusa para todas las secciones. Por defecto trae `dev-advisor-token`. Otros tokens reconocidos por el backend:

| Token | `advisor_id` | `roles` |
|---|---|---|
| `dev-advisor-token` | `ADV-001` | `["advisor"]` |
| `dev-compliance-token` | `CMP-001` | `["compliance"]` |

#### Sección 1 — Advisor token

Botón **"Check Advisor Auth"** llama `GET /auth/me` y muestra:
- `advisor_id`
- `display_name`
- `firm_id`
- `roles` como chips

Errores:
- 401 → `"Invalid or missing advisor token."` (mensaje genérico — nunca se ecoa el token).
- Network error → "API not reachable. Start uvicorn first."

#### Sección 2 — Profile approval

Form con:
- `client_id` (default `CLI-PREF-PORT-001`)
- `proposed_profile` (select con los 5 perfiles válidos)
- `decision` (select: `approve` / `modify` / `reject`)
- `approved_profile` (select opcional con los 5 perfiles + "(none)")
- `source` (default `manual`)
- `related_record_id` opcional + botón **"Use last AIFP"** que copia el `record_id` de la última corrida del AI Filtered Portfolio Demo
- `rationale` (textarea, default sugerido en inglés)

Botón **"Submit Profile Approval"** llama `POST /advisor/profile-approval` y muestra `record_id`, `advisor_id`, `decision`, `proposed_profile`, `approved_profile`, `created_at_utc`.

#### Sección 3 — Override approval

Form con:
- `client_id`
- `candidate_variant` (select: `DEFENSIVE` / `BALANCED` / `GROWTH`, default `GROWTH`)
- `decision` (select: `approve` / `reject`, default `approve`)
- `source` (default `manual`)
- `related_record_id` opcional + botón **"Use last AIFP"**
- `reason_codes` (textarea, una línea por reason code, default `PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET`)
- `exceeded_constraints` (textarea, una línea por constraint, default `max_volatility`)
- `rationale` (textarea)

Botón **"Submit Override Approval"** llama `POST /advisor/override-approval` y muestra `record_id`, `advisor_id`, `candidate_variant`, `decision`, `reason_codes` (chips), `exceeded_constraints` (chips), `created_at_utc`.

Al recibir 200, el `record_id` se guarda en una variable global para que la sección 4 pueda enlazarlo.

#### Sección 4 — Portfolio selection

Form con:
- `client_id`
- `selected_variant` (select: `DEFENSIVE` / `BALANCED` / `GROWTH`, default `BALANCED`)
- `source` (default `manual`)
- `related_record_id` opcional + botón **"Use last AIFP"**
- `override_approval_record_id` opcional + botón **"Use last override"** (copia del último override aprobado en la sección 3)
- `rationale` (textarea)

Botón **"Submit Portfolio Selection"** llama `POST /advisor/portfolio-selection` y muestra `record_id`, `advisor_id`, `selected_variant`, `warnings` (chips amarillos si hay), `created_at_utc`, `status`.

Si `selected_variant=GROWTH` y `override_approval_record_id` queda vacío, el backend devuelve el warning `"GROWTH selected without linked override approval record."` y el frontend lo muestra como chip amarillo.

#### Helpers de chaining

Tres variables JavaScript globales mantienen los últimos `record_id` exitosos:
- `lastAIFilteredPortfolioRecordId` — actualizado por el card del AI Filtered Portfolio Demo.
- `lastOverrideApprovalRecordId` — actualizado por la sección 3.
- `lastProfileApprovalRecordId` y `lastPortfolioSelectionRecordId` — guardados pero todavía sin botón consumidor (reservados para integraciones futuras).

Los botones helper muestran un mensaje verde `✓ filled with <record_id>` o rojo `✕ No ... record yet. ...` debajo del input.

#### Errores

- 401 → `"Invalid or missing advisor token."` (idéntico para todos los casos, sin echo del token).
- 422 → caja con el JSON de validación de Pydantic (paths + mensajes).
- 500 → detalle del backend (`"Advisor ... persistence failed."` u otro).
- Otro → `"HTTP NNN"` + JSON crudo.
- Network → `"API not reachable. Start uvicorn first."`

---

### Persisted Workflows
Lista los workflows guardados en SQLite. Permite filtrar por `client_id`. Muestra tabla con `record_id`, `client_id`, `status` y `created_at_utc`.

---

## Limitaciones

- **Auth scaffold development-only.** Los tokens en `Advisor Decisions Demo` están hard-coded en `api_layer/auth.py`. No es un identity provider productivo, no rota, no firma JWT.
- **Sin producción.** No usar contra un backend expuesto en red pública.
- **Frontend estático de demo.** No persiste estado entre recargas (los `lastXxxRecordId` se pierden al refrescar).
- **CORS.** Si el navegador bloquea requests desde `file://`, usar `python -m http.server 5500 -d frontend`.
- **AI Profile Demo, AI Universe Filter Demo y AI Filtered Portfolio Demo requieren OPENAI_API_KEY.** Sin la key, los endpoints responden HTTP 400. La sección Live Portfolio Demo descarga datos reales de Yahoo Finance (requiere internet).
- **SQLite local.** Los IDs son secuenciales por sesión de backend. Se resetean si el servidor se reinicia sin persistencia previa.
- **No cubre todos los endpoints.** Solo consume `/health`, `/auth/me`, `/workflow/run`, `/live/portfolio-demo`, `/ai/profile-demo`, `/ai/profile-follow-up`, `/ai/filter-universe-demo`, `/ai/filtered-portfolio-demo`, `/advisor/profile-approval`, `/advisor/override-approval`, `/advisor/portfolio-selection` y `GET /workflow`. Los endpoints `/universe/filter-demo`, `/reports`, `/audit` y los GET por ID están disponibles en el backend pero no en este frontend. Usar `curl` o Swagger UI para esos.
