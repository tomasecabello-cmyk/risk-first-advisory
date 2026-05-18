# Risk-First Advisory

Motor backend de asesoría financiera supervisada. La IA propone, el asesor decide.

El workflow es risk-first: suitability, governance, ESG, data quality y portfolio feasibility se verifican antes de generar carteras. El resultado se persiste en SQLite y se expone vía FastAPI.

## Estado actual

- Milestone M1/M2-prep — backend core completo
- **865 tests, todos verdes**
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
| Portfolio | `portfolio_layer` | Optimizador, feasibility checker, generación de variantes |
| Workflow | `workflow_layer` | `AdvisoryWorkflowCoordinator` — orquesta todo el flujo |
| Reporting | `reporting_layer` | `MarkdownReportGenerator` — genera reporte `.md` |
| Persistencia | `persistence_layer` | SQLite + repositorios in-memory |
| API | `api_layer` | FastAPI: `GET /health`, `POST /demo/run` |

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

### GET /health

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/health
```

```json
{"status": "ok", "service": "risk-first-advisory"}
```

### POST /demo/run

Ejecuta el workflow demo con fixtures, genera reporte y persiste en SQLite.

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/demo/run -Method Post
```

O con curl:

```bash
curl -s -X POST http://127.0.0.1:8000/demo/run | python -m json.tool
```

Respuesta (campos principales):

```json
{
  "status": "completed_with_warnings",
  "client_id": "cliente_contradictorio_01",
  "approved_profile_name": "MODERADO",
  "has_portfolios": true,
  "reason_codes": ["..."],
  "warnings": ["..."],
  "final_optimizer_tickers": ["AAPL", "MSFT", "..."],
  "portfolio_feasibility_status": "feasible",
  "candidate_count": 3,
  "report_path": "C:\\...\\reports\\demo_api_report.md",
  "records": {
    "workflow_record_id": "workflow_000001",
    "audit_record_id": "audit_000001",
    "report_record_id": "report_000001"
  }
}
```

### Documentación interactiva

Con el servidor corriendo:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## Archivos generados localmente

| Archivo | Cuándo se genera | Contenido |
|---|---|---|
| `reports/demo_advisory_report.md` | `scripts/run_demo.py` | Reporte Markdown del workflow demo |
| `reports/demo_api_report.md` | `POST /demo/run` | Reporte Markdown vía API |
| `data/demo_api.db` | `POST /demo/run` | SQLite con workflow, audit y report records |

Estos archivos están en `.gitignore`.

## Fixtures de prueba

Los fixtures están en `tests/fixtures/`:

| Directorio | Contenido |
|---|---|
| `kyc_profiles/` | Perfiles KYC en JSON (e.g. `contradictorio_alta_severidad.json`) |
| `universes/` | Universos de productos aprobados en YAML |
| `suitability/` | Matriz de suitability en YAML |
| `esg/` | Metadata ESG de instrumentos en YAML |
| `market_data/` | Precios y datos de mercado en YAML |

## Principios del sistema

1. La IA no recomienda inversiones ni decide pesos de cartera.
2. El asesor valida perfil, resuelve contradicciones y aprueba carteras.
3. El universo nace de governance, no del proveedor de datos.
4. El perfil surge de tolerancia + capacidad — nunca de la necesidad de retorno.
5. `preliminary_profile` (propuesto por IA) y `approved_profile` (validado por asesor) son conceptos distintos.
6. Solo `ApprovedPortfolio` puede presentarse al cliente.
7. Todo motivo cita un `ReasonCode`. Todo evento queda en audit trail.

## Compliance

Este software no constituye recomendación de inversión. Es una herramienta de soporte para asesores financieros matriculados, que mantienen la responsabilidad profesional sobre toda decisión presentada al cliente.

Los retornos esperados son estimaciones técnicas, no predicciones ni garantías.
