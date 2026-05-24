# Risk-First Advisory

Motor backend de asesoría financiera supervisada. La IA propone, el asesor decide.

El workflow es risk-first: suitability, governance, ESG, data quality y portfolio feasibility se verifican antes de generar carteras. El resultado se persiste en SQLite y se expone vía FastAPI con un frontend estático de demo.

---

## Estado actual

- **1994 tests, todos verdes** (unit + integration)
- MVP local visual completo — frontend estático en `frontend/index.html`
- Backend FastAPI con 14 endpoints expuestos
- **Fase 0 cerrada:** `/ai/filtered-portfolio-demo` devuelve `report_markdown` auditable y persiste el resultado completo (payload + reporte) en SQLite con `record_id` y `report_record_id`
- **OpenAI** requerido para los endpoints `/ai/*` (API key en la terminal del servidor)
- **yfinance** requerido para `/live/portfolio-demo` (descarga datos históricos de ETFs; requiere internet)
- **Universo CSV** (`tests/fixtures/universe/sample_instrument_universe.csv`, 20 instrumentos) para demo multi-instrumento con renta fija y ETFs
- Sin Bloomberg (datos de mercado reales para producción son out-of-scope del MVP)
- Sin PostgreSQL (SQLite local para persistencia de sesión)
- Sin autenticación (desarrollo local únicamente)

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
| API | `api_layer` | FastAPI: 14 endpoints — ejecución, recuperación, demo IA y demo portfolio |

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

Suite completa (unit + integration): ~40 segundos, 1994 tests.

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
| `data/demo_api.db` | `POST /demo/run`, `POST /workflow/run` o `POST /ai/filtered-portfolio-demo` | SQLite con workflow, audit, report y ai_filtered_portfolio records |

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
| Firma de override del asesor | Endpoint/UI donde el asesor confirme explícitamente la aceptación de GROWTH fuera del budget, con registro en audit trail (ver DD-010) | Alta |
| Selección de variante por asesor | Endpoint para que el asesor seleccione la variante (DEFENSIVE/BALANCED/GROWTH) a presentar al cliente, con registro en audit trail | Alta |
| Expandir universo de instrumentos | Reemplazar el CSV de 20 instrumentos de muestra por un universo real de ONs, ETFs y bonos soberanos con datos actualizados | Media |
| Provider de datos externo | Conectar `InstrumentMarketDataAdapter` a una fuente de datos de producción (Bloomberg, Refinitiv, proveedor local) en lugar de derivar retornos desde ytm/coupon del CSV | Media |
| Autenticación y seguridad | Auth JWT o API key para todos los endpoints; control de acceso por rol (asesor vs. cliente) antes de cualquier exposición en red | Alta (pre-producción) |
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
