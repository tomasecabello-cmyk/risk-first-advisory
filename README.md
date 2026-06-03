# Risk-First Advisory

Motor backend de asesoría financiera supervisada. La IA propone, el asesor decide.

El workflow es risk-first: suitability, governance, ESG, data quality y portfolio feasibility se verifican antes de generar carteras. El resultado se persiste en SQLite y se expone vía FastAPI con un frontend estático de demo.

---

## Estado actual

- **3087 tests, todos verdes** (unit + integration)
- **Fase 0 cerrada:** `/ai/filtered-portfolio-demo` devuelve `report_markdown` auditable y persiste el resultado completo (payload + reporte) en SQLite.
- **Fase 1 cerrada — advisor pilot scaffold:** scaffold Bearer-token de auth + 3 endpoints legacy del asesor (`/advisor/profile-approval`, `/advisor/override-approval`, `/advisor/portfolio-selection`) client_id-scoped sobre `records`.
- **Fase 2 cerrada — workflow case-scoped backend ✅:** flujo completo end-to-end de un `AdvisoryCase`, con 9 migrations, ~20 endpoints case-scoped nuevos, AuditEvent hash chain por case, AIRequestLog con redacción de PII, RBAC por rol (admin / advisor / compliance / viewer), y smoke check ejecutable (`python scripts/run_case_workflow_smoke_check.py`). Esto NO incluye frontend nuevo para el flujo case-scoped — el legacy sigue mostrando solo los endpoints de Fase 0/1.
- **Fase 3 cerrada como local/demo plug-and-play ✅:** Case Dashboard + Case Workbench end-to-end (15 paneles: KYC → AI Profile Analysis → Profile Approval → Investment Preferences → Universe Filter → Portfolio Proposal → Override Approval → Portfolio Selection → Report Generation → Final Summary → **Audit Trail + Audit Verification + AI Request Logs + Compliance Snapshot**), auto-refresh del summary tras cada POST (audit/logs panels son load manual), frontend separado en `css/base.css` + `js/common.js` + `js/legacy-demo.js` + `js/case-dashboard.js` + `js/case-workbench.js` (sin build step), seed demo data idempotente (`scripts/seed_demo_data.py`), bootstrap local en un comando (`scripts/bootstrap_local_demo.py` — migrate + seed + checks + imprime instrucciones; `--check-only` / `--skip-*` / `--run-smoke`), plug-and-play docs completos (sección "Local plug-and-play demo" más abajo) y limpieza de copy obsoleto del frontend. **Esto NO significa production-ready ni piloto B2B vendible** — ver sección "Phase 3 local demo readiness" abajo para el scope exacto.
- **Fase 4 próxima — pilot readiness / hardening:** market data provider productivo, manual universe upload, PDF / branding del report, compliance ZIP export package, firm-level access control real, auth productiva (JWT/OIDC/IdP, rotación, revocation), backup/restore (o migración a PostgreSQL si la escala lo pide), cifrado at-rest, retention/pruning policy, anclaje externo del audit chain, `/health/full` runtime, deployment productivo, sign-off legal/compliance formal.
- **OpenAI** requerido solo para los endpoints `/ai/*` legacy; el flujo case-scoped soporta `POST /cases/{id}/ai/profile-analysis` también, pero los tests y el smoke check usan mocks determinísticos.
- **yfinance** requerido para `/live/portfolio-demo` (legacy).
- **Universo CSV** (`tests/fixtures/universe/sample_instrument_universe.csv`, 20 instrumentos) para todos los flujos demo, incluyendo `POST /cases/{id}/universe-filter`.
- Sin Bloomberg ni provider de datos productivo (out-of-scope MVP — pendiente Fase 4).
- Sin PostgreSQL (SQLite local).
- **Auth development-only:** Bearer token con mapa configurable vía YAML (`config/advisor_tokens.yaml` o `ADVISOR_TOKENS_FILE` env var). Sin JWT, sin IdP, sin rotación, sin firm-level access control. Exclusivamente desarrollo local — ver sección "Auth scaffold".
- **Esto NO es production-ready.** No es asesoramiento financiero. No reemplaza al asesor humano. Ver `docs/COMPLIANCE_NOTES.md` para límites detallados.

---

## Phase 3 local demo readiness

Fase 3 quedó cerrada como **demo local plug-and-play operable desde navegador**. Esta sección documenta con precisión qué entra y qué NO entra en ese cierre, para evitar confusiones operativas o de venta.

### ✅ Qué se puede hacer hoy (in scope)

Tras un `pip install -e .` y un `python scripts/bootstrap_local_demo.py`:

- Ver una UI con **estética institutional-fintech, localizada al español** (hero, story-strip "Qué hace la IA · Qué hace el asesor · Qué controla el sistema · Qué queda auditado", Workbench, Dashboard, botones, mensajes de carga). Los identificadores técnicos del backend (`case_id`, `firm_id`, endpoints, role names, JSON keys, reason_codes) permanecen en inglés. Sin frameworks ni CDN — sigue siendo HTML/CSS/JS estáticos sin build step.
- **Demo de perfil inversor advisor-friendly** (Fase 3.6 polish): card principal al frente con formulario en español de perfil + 8 pasos guiados (Preparar caso → KYC → análisis IA → aprobación → propuesta → selección → reporte → auditoría) y botón "▶ Ejecutar demo guiada" que corre el flujo end-to-end sin exponer Dashboard / firms / advisors / IDs técnicos. Pensado para mostrar el producto a un profesor / asesor no técnico. El Dashboard técnico y el Workbench paso a paso quedan disponibles más abajo como "Modo avanzado".
- Mostrar la demo a un profesor / asesor no técnico siguiendo el panel **"Recorrido recomendado"** (checklist visible de 9 clicks) o el **"Guion de presentación"** colapsable (talk-track de 6 frases ~90 s). Versión extendida en `docs/DEMO_SCRIPT.md` → "Guion advisor-facing — 5 minutos".
- Correr `bootstrap_local_demo` (idempotente; aplica migrations + crea entidades demo + valida frontend + detecta config + imprime los comandos siguientes).
- Levantar el backend FastAPI local (`python -m uvicorn risk_first_advisory.api_layer.main:app --reload`) en `http://127.0.0.1:8000` con Swagger UI en `/docs`.
- Levantar el frontend estático (`python -m http.server 5500 -d frontend`) en `http://127.0.0.1:5500`.
- Abrir el **Case Dashboard** y navegar el CRUD de firms / advisors / clients / cases + cargar `GET /cases/{id}/summary`.
- Abrir el **Case Workbench** sobre `case_demo_local` (creado por el seed) y recorrer el flujo case-scoped end-to-end desde el navegador, **con un step indicator visual de 11 pasos** que se autocolorea (pending / ready / completed) a medida que avanzás: KYC → AI Profile Analysis → Profile Approval → Investment Preferences → Universe Filter → Portfolio Proposal → Override Approval → Portfolio Selection → Report Generation. Los pasos quedan agrupados visualmente en bandas "Profile", "Portfolio inputs", "Portfolio decisions", "Outputs" y "Audit &amp; Compliance".
- Ver la **composición de cada cartera candidata** (Fase 3.6): DEFENSIVE / BALANCED / GROWTH se muestran como cards con tabla `Instrumento · Tipo · Moneda · Peso · Motivo` + barra visual de peso + pill "requiere override" / "dentro del presupuesto". La variante seleccionada muestra su composición final en el panel de selección. El reporte Markdown incluye tabla de composición + tabla comparativa de variantes. **Limitación**: el universo demo (`tests/fixtures/universe/sample_instrument_universe.csv`, 20 instrumentos ficticios) NO es un market data provider productivo — para piloto real va a Fase 4 (live market data + manual universe upload).
- Revisar el **audit trail** (hash chain SHA-256 por case) y verificar su integridad (`/cases/{id}/audit/verify`) desde el panel del Workbench.
- Revisar los **AI request logs** con PII redactada por el backend.
- Generar el **report Markdown determinístico** (4 disclaimers fijos + secciones estándar).
- Correr el smoke check end-to-end sin frontend ni OpenAI (`python scripts/run_case_workflow_smoke_check.py`) con mock determinístico — Exit 0 = PASS.

### ❌ Qué NO incluye este cierre (queda para Fase 4)

Phase 3 cerrada **no** significa ninguna de las siguientes capacidades, todas explícitamente fuera de scope:

- **Production auth.** Tokens son strings opacos en YAML (`config/advisor_tokens.yaml` o `ADVISOR_TOKENS_FILE` env var). Sin JWT, sin IdP, sin OIDC, sin rotación, sin revocation, sin emisión.
- **Firm-level access control completo.** Cualquier token con rol válido ve y opera sobre cualquier case (el `firm_id` existe en las tablas pero no se filtra en los endpoints).
- **PostgreSQL.** Solo SQLite local (`data/demo_api.db`); sin pool de conexiones, sin réplica, sin clustering.
- **Market data provider productivo.** El universe-filter sigue contra el CSV fixture (`tests/fixtures/universe/sample_instrument_universe.csv`, 20 instrumentos); sin SLA de frescura, sin validación contra Bloomberg / Refinitiv / Yahoo en tiempo real (excepto la card legacy `/live/portfolio-demo` que usa yfinance solo para demo).
- **Manual universe upload.** No hay admin endpoint para reemplazar el CSV sin redeploy.
- **PDF / branding del report.** El report es Markdown determinístico; sin render PDF, sin logo de la firm, sin colores corporativos.
- **Compliance export package (ZIP).** Sin bundle automático de report + audit trail + AI logs sanitizados.
- **Backup / restore.** Sin política de backup automático ni runbook de restore; solo `scripts/backup_db.py` manual.
- **Deployment productivo.** Sin Dockerfile, sin compose, sin Helm chart, sin CI/CD pipeline, sin healthcheck `/health/full` runtime, sin observabilidad (logs estructurados / métricas / tracing).
- **Uso con datos reales sensibles.** El sistema está pensado para dev local con datos demo. **No cargar PII real de clientes**: no hay encryption at-rest, no hay retention policy, no hay sign-off legal/compliance formal, los tokens dev viajan en plano por HTTP local. Ver `docs/COMPLIANCE_NOTES.md` para el detalle.
- **Piloto B2B vendible.** Fase 3 cerrada habilita demos a stakeholders internos, mentores, asesores curiosos en una máquina dev — NO habilita un acuerdo comercial con una firma cliente. Para eso hay que cerrar Fase 4 (pilot readiness).

---

## Local plug-and-play demo

Camino recomendado para levantar la demo en local desde cero (Windows PowerShell). Total: ~3 minutos en una máquina típica.

### 1. Activar venv + instalar dependencias (primera vez)

```powershell
cd C:\Users\maria\risk-first-advisory
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

Si el venv ya existe:

```powershell
cd C:\Users\maria\risk-first-advisory
.\.venv\Scripts\Activate.ps1
```

### 2. Bootstrap local — un solo comando

```powershell
python scripts/bootstrap_local_demo.py
```

Aplica migrations, corre `seed_demo_data`, valida archivos del frontend, detecta configuración (tokens YAML, `OPENAI_API_KEY`) e imprime los comandos exactos de los pasos 3–4. **NO levanta servidores** — solo deja el entorno listo. Idempotente: correr múltiples veces es seguro. No requiere `OPENAI_API_KEY`.

Output esperado al final:

```
PASS — local demo environment is ready
```

### 3. Terminal 1 — backend

```powershell
cd C:\Users\maria\risk-first-advisory
.\.venv\Scripts\Activate.ps1
python -m uvicorn risk_first_advisory.api_layer.main:app --reload
```

Opcional, solo si vas a usar los endpoints `/ai/*` reales desde el frontend (la card AI Profile Demo Phase 0/1, o el panel "AI Profile Analysis" del Workbench contra OpenAI real):

```powershell
$env:OPENAI_API_KEY="sk-..."
```

El backend queda en `http://127.0.0.1:8000` con Swagger en `/docs`. El smoke check (`python scripts/run_case_workflow_smoke_check.py`) usa mock determinístico y NO necesita la API key.

#### Risk Gap sin OPENAI_API_KEY (demo determinística)

Para ver el paso **Risk Gap** (flag de inconsistencia entre el perfil declarado y la respuesta a estrés) en la demo guiada **sin** clave de OpenAI, arrancá el backend con `RFA_DEMO_MODE`:

```powershell
$env:RFA_DEMO_MODE="1"
python -m uvicorn risk_first_advisory.api_layer.main:app --reload
```

Esto activa un cliente de perfil determinístico (sin LLM): si el KYC del cliente expresa pánico ante una caída, el Risk Gap marca `gap_level: medium` y propone preguntas para que el asesor confirme. Es un **flag de inconsistencia, NO una medición del perfil conductual** — ver `docs/METHODOLOGY_NOTES.md`. Sin `RFA_DEMO_MODE` y sin `OPENAI_API_KEY`, el endpoint sigue exigiendo la clave (no hay fallback silencioso en producción).

### 4. Terminal 2 — frontend

```powershell
cd C:\Users\maria\risk-first-advisory
.\.venv\Scripts\Activate.ps1
python -m http.server 5500 -d frontend
```

### 5. Abrir en navegador

| URL | Para qué |
|---|---|
| `http://127.0.0.1:5500` | Frontend dev UI (Case Dashboard + Case Workbench + cards legacy) |
| `http://127.0.0.1:8000/docs` | Swagger UI del backend FastAPI |

### 6. Tokens (input "Bearer token" del Case Dashboard)

Si no escribiste un `config/advisor_tokens.yaml` propio, el backend usa el fallback dev-only con **solo dos tokens**:

| Token | Rol | Para qué |
|---|---|---|
| `dev-advisor-token` | `advisor` | Workflow completo del Case Workbench (KYC, AI analysis, profile approval, preferences, filter, proposal, override, selection, report) |
| `dev-compliance-token` | `compliance` | Audit verify + AI logs panels (sección 13 y 14 del Workbench) |

No hay `dev-admin-token` ni `dev-viewer-token` en el fallback dev — para operaciones admin (crear firms / advisors desde el Dashboard) hay que escribir un `config/advisor_tokens.yaml` con tokens propios y rol `admin`. El **seed demo data** del paso 2 ya creó las entidades base (firm/advisor/client/case) sin necesidad de eso, vía un YAML temporal interno.

### 7. Abrir `case_demo_local` en Dashboard / Workbench

1. En la card **"Case Dashboard — Phase 2"** escribir `case_demo_local` en el campo "Selected case_id" (sección 7 del card) y clic en **"Load Summary"**. Debe devolver `status=DRAFT`, `next_recommended_action=submit_kyc`, todos los flags `has_*=false`.
2. En la card **"Case Workbench — Phase 2 Workflow"** escribir `case_demo_local` en el campo "case_id" (sección 1) y clic en **"Load Summary"** o **"Use selected case from Dashboard"**.
3. Recorrer los pasos 2–10 del Workbench (KYC → AI analysis → approval → preferences → universe filter → portfolio proposal → override approval si aplica → portfolio selection → report). Cada POST exitoso auto-refresca el summary del Workbench.
4. Para audit + AI logs (secciones 12–14): cambiar al token `dev-compliance-token` en el input del Dashboard antes de presionar los botones de "Verify Audit Chain" y "Load AI Logs".

### 8. Validar end-to-end sin frontend (opcional)

```powershell
python scripts/run_case_workflow_smoke_check.py
```

Corre el flujo completo `firm → … → report → summary → audit verify` en una DB SQLite temporal, con OpenAI mockeado. Útil para confirmar que el backend funciona sin tocar la demo DB. Exit 0 = PASS.

### Límites — leer antes de mostrar la demo a alguien

- **NO production-ready.** Esta demo es para desarrollo y pilot interno. No usarla con datos reales sensibles de clientes.
- **SQLite local.** Sin replicación, sin backup automático, sin cifrado at-rest. `data/demo_api.db` vive en plano en filesystem.
- **Auth dev-only.** Tokens son strings opacos en YAML. Sin JWT, sin IdP, sin firm-level isolation completa. Cualquier token con rol válido ve cualquier case (sin filtrado por firma).
- **Market data CSV.** El universe-filter usa `tests/fixtures/universe/sample_instrument_universe.csv` (20 instrumentos). No es un provider live productivo — los retornos esperados son proxy derivados de `ytm`/`coupon_rate`.
- **PDF / branding del report pendientes.** El report es markdown plano sin logo/colores de la firma.
- **Hash chain ≠ blockchain.** El audit chain del case detecta mutaciones puntuales en la DB, pero un admin con acceso directo puede reescribir coherentemente toda la cadena. No hay WORM external storage ni anclaje a timestamping authority. Ver `docs/COMPLIANCE_NOTES.md` sección 0.
- **IA es propuesta, no decisión.** La IA propone perfil + extrae preferencias; el asesor humano aprueba/modifica/rechaza vía endpoints case-scoped explícitos.

Si algo del setup falla, correr el bootstrap con `--debug` para ver tracebacks:

```powershell
python scripts/bootstrap_local_demo.py --debug
```

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

Suite completa (unit + integration): ~5 minutos, **3087 tests** (todos verdes — incluye 15 tests nuevos de holdings/composición de cartera).

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

## Bootstrap local demo (Fase 3 — recomendado para empezar)

Un comando que prepara todo el entorno para demo / dev local: aplica migrations, corre el seed, valida archivos del frontend, detecta configuración (tokens YAML, OPENAI_API_KEY) y imprime los comandos exactos para levantar backend + frontend.

```powershell
python scripts/bootstrap_local_demo.py
```

**No levanta servidores** — solo imprime las instrucciones. El control queda en el dev (evita procesos zombies si se cancela).

Flags principales:

| Flag | Qué hace |
|---|---|
| `--db-path PATH` | DB custom (default: `api_layer.main.DEFAULT_DB_PATH`). Se pasa también al seed. |
| `--check-only` | Solo verifica archivos + config; no toca DB. Útil para CI o para "¿qué falta?" |
| `--skip-migrate` | No aplicar migrations (asume schema actual). |
| `--skip-seed` | No correr `seed_demo_data`. |
| `--run-smoke` | Correr el smoke check end-to-end en una **DB temporal aislada** (no ensucia la DB de demo). |
| `--debug` | Traceback completo en excepciones inesperadas. |

Output (extracto, modo full):

```
[1/5] Checking environment...      ✓
[2/5] Apply migrations...          ✓
[3/5] Seed demo data...            ✓  firm=created, advisor=created, client=created, case=created
[4/5] End-to-end smoke check...    skipped (default)
[5/5] Launch instructions...
    Backend  : python -m uvicorn risk_first_advisory.api_layer.main:app --reload
    Frontend : python -m http.server 5500 -d frontend
    Open     : http://127.0.0.1:8000/docs  +  http://127.0.0.1:5500
    Tokens   : dev-advisor-token, dev-compliance-token
PASS — local demo environment is ready
```

Si no existe `config/advisor_tokens.yaml`, el bootstrap detecta el fallback dev-only (solo `dev-advisor-token` + `dev-compliance-token` — **no hay admin/viewer en el fallback**) y avisa cómo agregarlos si necesitás crear firms / advisors desde el Dashboard.

---

## Seed demo data (Fase 3)

Crea (o reutiliza) las entidades base necesarias para ejercitar el Case Dashboard / Case Workbench sin tipear datos a mano. **Idempotente**: corre múltiples veces sin duplicar nada.

```powershell
python scripts/seed_demo_data.py
```

Crea con IDs estables:

| Entidad | ID | Default name |
|---|---|---|
| Firm | `firm_demo_local` | Demo Advisory Firm |
| Advisor | `advisor_demo_local` | Demo Advisor |
| Client | `client_demo_local` | Demo Client |
| Case | `case_demo_local` | Demo advisory case |

Aplica todas las migrations automáticamente antes de seedear (a menos que se pase `--no-migrate`). Por default usa la DB del backend (`api_layer.main.DEFAULT_DB_PATH` → `data/demo_api.db`); override con `--db-path data/otra.db`.

Output al final:

```
PASS — demo data ready
    firm_id    : firm_demo_local    (created)
    advisor_id : advisor_demo_local (created)
    client_id  : client_demo_local  (created)
    case_id    : case_demo_local    (created)
```

En corridas subsecuentes los estados aparecen como `(reused)`. El script **NO** completa KYC, AI analysis, profile approval, portfolio proposal ni report — para eso usar:

- `python scripts/run_case_workflow_smoke_check.py` (end-to-end batch, sin frontend), o
- el Case Workbench del frontend (recorrer panel por panel después de abrir `case_demo_local`).

### Tokens recomendados para usar después del seed

- `dev-admin-token` — para crear/editar entidades adicionales (firms, advisors, clients) desde el Dashboard.
- `dev-advisor-token` — para correr el workflow case-scoped (KYC, análisis, aprobaciones, etc.) desde el Workbench.
- `dev-compliance-token` — para audit verify + AI logs panels.

El input "Bearer token" del Case Dashboard es global a las cards Phase 2; cambiarlo allí afecta también al Workbench.

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
