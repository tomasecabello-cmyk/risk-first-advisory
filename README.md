# Risk-First Advisory

Motor backend de asesoría financiera supervisada. La IA propone, el asesor decide.

El workflow es risk-first: suitability, governance, ESG, data quality y portfolio feasibility se verifican antes de generar carteras. El resultado se persiste en SQLite y se expone vía FastAPI.

## Estado actual

- Milestone M1/M2-prep — backend core completo
- **1007 tests, todos verdes**
- Sin IA real (MockAIClient)
- Sin Bloomberg (MockMarketDataProvider)
- Sin frontend
- Sin autenticación
- Sin PostgreSQL (SQLite en local)

## Capas implementadas

| Capa | Módulo | Descripción |
|---|---|---|
| KYC | `kyc` | `KYCData`, `FinancialGoal`, `ESGProfile`, `AuditTrail` |
| IA | `ai_layer` | `MockAIClient` — respuestas predeterminadas por fixture |
| Humana | `human_layer` | `ScriptedAdvisorInterface` — decisiones por fixture |
| Reglas | `rules_layer` | Governance, suitability, ESG, data quality |
| Datos | `data_layer` | `MockMarketDataProvider` — precios por fixture YAML |
| Portfolio | `portfolio_layer` | Optimizador, feasibility checker, generación de variantes con metadata de override |
| Workflow | `workflow_layer` | `AdvisoryWorkflowCoordinator` — orquesta todo el flujo |
| Reporting | `reporting_layer` | `MarkdownReportGenerator` — genera reporte `.md` con metadata de variantes visible |
| Persistencia | `persistence_layer` | SQLite + repositorios in-memory |
| API | `api_layer` | FastAPI: 9 endpoints — ejecución, recuperación y listado de registros |

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

## Correr tests

```powershell
python -m pytest
```

Suite completa (unit + integration): ~7 segundos.

```powershell
# Solo tests de API
python -m pytest tests/integration/test_api_demo.py -v

# Solo tests de persistencia SQLite
python -m pytest tests/integration/test_sqlite_persistence.py -v

# Solo tests unitarios
python -m pytest tests/unit/ -v
```

## Demo por consola

Ejecuta el workflow completo con fixtures y muestra el resultado en terminal:

```powershell
python scripts/run_demo.py
```

Genera:
- `reports/demo_advisory_report.md` — reporte Markdown del workflow

## API FastAPI

Iniciar servidor:

```powershell
uvicorn risk_first_advisory.api_layer.main:app --reload
```

Documentación interactiva con el servidor corriendo:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

### Endpoints disponibles

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Estado del backend |
| `POST` | `/demo/run` | Ejecuta workflow demo con fixtures |
| `POST` | `/workflow/run` | Ejecuta workflow con payload JSON |
| `GET` | `/workflow/{record_id}` | Recupera un workflow por ID |
| `GET` | `/reports/{record_id}` | Recupera un reporte por ID |
| `GET` | `/audit/{record_id}` | Recupera un audit trail por ID |
| `GET` | `/workflow` | Lista todos los workflows (filtrable por `client_id`) |
| `GET` | `/reports` | Lista todos los reportes (filtrable por `client_id`) |
| `GET` | `/audit` | Lista todos los audit trails (filtrable por `client_id`) |

### GET /health

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/health
```

```json
{"status": "ok", "service": "risk-first-advisory"}
```

### POST /demo/run

Ejecuta el workflow demo con fixtures, genera reporte Markdown y persiste en SQLite.

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/demo/run
```

### POST /workflow/run

Ejecuta el workflow con KYCData y FinancialGoal enviados por JSON. Usa `MockAIClient` y `ScriptedAdvisorInterface` por defecto. La respuesta incluye los IDs de los registros persistidos.

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

Respuesta (campos principales):

```json
{
  "status": "blocked_by_portfolio_feasibility",
  "client_id": "CLI-001",
  "approved_profile_name": "moderado",
  "has_portfolios": false,
  "reason_codes": ["..."],
  "warnings": ["..."],
  "final_optimizer_tickers": ["BIL", "SHV", "..."],
  "portfolio_feasibility_status": "infeasible",
  "candidate_count": 0,
  "report_path": "C:\\...\\reports\\workflow_CLI-001.md",
  "records": {
    "workflow_record_id": "workflow_000001",
    "audit_record_id": "audit_000001",
    "report_record_id": "report_000001"
  }
}
```

Los IDs devueltos en `records` permiten recuperar los registros persistidos vía GET.

### GET /workflow/{record_id} · GET /reports/{record_id} · GET /audit/{record_id}

Recuperan un registro persistido por su ID. Devuelven 404 si no existe.

```powershell
curl.exe http://127.0.0.1:8000/workflow/workflow_000001
curl.exe http://127.0.0.1:8000/reports/report_000001
curl.exe http://127.0.0.1:8000/audit/audit_000001
```

Respuesta:

```json
{
  "record_id": "workflow_000001",
  "record_type": "workflow_run",
  "created_at_utc": "2026-05-19T04:00:00Z",
  "payload": { "status": "...", "client_id": "CLI-001", "..." : "..." },
  "metadata": { "client_id": "CLI-001", "source_type": "workflow_result", "..." : "..." }
}
```

### GET /workflow · GET /reports · GET /audit

Listan todos los registros. Aceptan query param opcional `client_id` para filtrar.

```powershell
# Todos los workflows
curl.exe http://127.0.0.1:8000/workflow

# Filtrados por cliente
curl.exe "http://127.0.0.1:8000/workflow?client_id=CLI-001"
curl.exe "http://127.0.0.1:8000/reports?client_id=CLI-001"
curl.exe "http://127.0.0.1:8000/audit?client_id=CLI-001"

# Todos los reportes y audit trails
curl.exe http://127.0.0.1:8000/reports
curl.exe http://127.0.0.1:8000/audit
```

Respuesta:

```json
{
  "count": 2,
  "records": [
    { "record_id": "workflow_000001", "..." : "..." },
    { "record_id": "workflow_000002", "..." : "..." }
  ]
}
```

Los registros se devuelven en orden de inserción. `count` siempre coincide con `len(records)`.

## Archivos generados localmente

| Archivo | Cuándo se genera | Contenido |
|---|---|---|
| `reports/demo_advisory_report.md` | `scripts/run_demo.py` | Reporte Markdown del workflow demo |
| `reports/demo_api_report.md` | `POST /demo/run` | Reporte Markdown vía API |
| `reports/workflow_<client_id>.md` | `POST /workflow/run` | Reporte Markdown por cliente |
| `data/demo_api.db` | `POST /demo/run` o `POST /workflow/run` | SQLite compartido con workflow, audit y report records |

Estos archivos están en `.gitignore`. Los record IDs (`workflow_000001`, `audit_000001`, etc.) se generan localmente en SQLite y son secuenciales por prefijo. El SQLite local es para desarrollo y demo — no está diseñado para producción.

## Fixtures de prueba

Los fixtures están en `tests/fixtures/`:

| Directorio | Contenido |
|---|---|
| `kyc_profiles/` | Perfiles KYC en JSON (e.g. `contradictorio_alta_severidad.json`) |
| `universes/` | Universos de productos aprobados en YAML |
| `suitability/` | Matriz de suitability en YAML |
| `esg/` | Metadata ESG de instrumentos en YAML |
| `market_data/` | Precios y datos de mercado en YAML |

## Portfolio: variantes y metadata de override

Cada ejecución del workflow puede generar hasta tres variantes de cartera candidata:

| Variante | Objetivo | Relación con RiskBudget aprobado |
|---|---|---|
| `DEFENSIVE` | Mínima varianza | Más conservadora que el perfil aprobado |
| `BALANCED` | Máxima utilidad | Respeta estrictamente el RiskBudget aprobado — recomendación base |
| `GROWTH` | Máximo retorno | Puede exceder `max_volatility` del RiskBudget aprobado |

Cuando `GROWTH` excede el RiskBudget aprobado, `PortfolioCandidateSet` almacena en su campo `metadata` un `PortfolioVariantMetadata` con:

- `risk_budget_exceeded: true`
- `requires_advisor_override: true`
- `exceeded_constraints: [max_volatility]`
- `reason_codes: [PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET]`

El reporte Markdown muestra esa metadata por variante bajo **Variant Metadata**, incluyendo:
- `risk_budget_exceeded`
- `requires_advisor_override`
- `exceeded_constraints`
- `reason_codes`
- `notes`

Si no existe metadata explícita para una variante, el reporte muestra defaults seguros (`false` / `None`) sin romper.

## Principios del sistema

1. La IA no recomienda inversiones ni decide pesos de cartera.
2. El asesor valida perfil, resuelve contradicciones y aprueba carteras.
3. El universo nace de governance, no del proveedor de datos.
4. El perfil surge de tolerancia + capacidad — nunca de la necesidad de retorno.
5. `preliminary_profile` (propuesto por IA) y `approved_profile` (validado por asesor) son conceptos distintos.
6. Solo `ApprovedPortfolio` puede presentarse al cliente.
7. Todo motivo cita un `ReasonCode`. Todo evento queda en audit trail.
8. Si `GROWTH` excede el RiskBudget aprobado, ese exceso no queda oculto — queda marcado, auditado y visible en el reporte.

## Compliance

Este software no constituye recomendación de inversión. Es una herramienta de soporte para asesores financieros matriculados, que mantienen la responsabilidad profesional sobre toda decisión presentada al cliente.

Los retornos esperados son estimaciones técnicas, no predicciones ni garantías.
