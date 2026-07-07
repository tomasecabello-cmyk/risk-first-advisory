# Risk-First Advisory

Motor de asesoría financiera supervisada: **la IA propone, el asesor decide**.

Antes de generar ninguna cartera, el workflow verifica riesgo de punta a punta:
suitability, governance de producto, ESG, calidad de datos y factibilidad de
portfolio, en un orden fijo con relevancia de compliance. Cada decisión queda
persistida en SQLite con una cadena de auditoría hash-encadenada.

Backend Python/FastAPI + frontend estático HTML/CSS/JS (sin build, sin frameworks).
**Demo local — NO production-ready.** No es asesoramiento financiero real; ver
`docs/COMPLIANCE_NOTES.md` para los límites.

## Qué hace

- **Perfil de riesgo con IA supervisada**: la IA interpreta el KYC, detecta
  contradicciones (Risk Gap) y propone un perfil *preliminar*; solo el asesor lo
  aprueba/modifica/rechaza vía un endpoint humano explícito.
- **Risk Number 0-100** cliente↔cartera: operativo del cliente =
  `min(tolerancia, capacidad)`; el de cada cartera se deriva de su dispersión (CVaR).
  Fundamento en `docs/RISK_NUMBER_DESIGN.md` y `frontend/methodology.html`.
- **Filtro de universo** por preferencias del cliente (manuales o extraídas por IA
  de texto libre) sobre un universo ARG+US real generado desde data912
  (`scripts/build_arg_universe.py`, 97 instrumentos líquidos).
- **Propuesta de carteras** DEFENSIVE / BALANCED / GROWTH (optimizador
  media-varianza sobre el universo ya filtrado); GROWTH puede exceder el presupuesto
  aprobado solo con override explícito y auditado del asesor.
- **Reporte Markdown determinístico** + audit trail SHA-256 verificable + logs de IA
  con PII redactada.

## Demo en 5 minutos (Windows PowerShell)

```powershell
# 0. Primera vez: venv + deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 1. Migrations + seed + validación (idempotente, sin API key)
python scripts/bootstrap_local_demo.py

# 2. Precalentar el caché de market data (una vez por día, ~2-3 min)
python scripts/build_arg_universe.py --warm

# 3. Backend (Terminal 1) — demo determinística sin OPENAI_API_KEY + universo en vivo
$env:RFA_DEMO_MODE="1"; $env:RFA_LIVE_DATA="1"
python -m uvicorn risk_first_advisory.api_layer.main:app --port 8000

# 4. Frontend (Terminal 2)
python -m http.server 5500 -d frontend
# → abrir http://127.0.0.1:5500
```

Sin `RFA_LIVE_DATA=1` el universo queda solo con renta fija (el CSV no tiene precios
de equities). Sin `RFA_DEMO_MODE=1`, el análisis IA case-scoped requiere
`OPENAI_API_KEY` real.

**El frontend está separado por roles** (ver `frontend/README.md`):
`index.html` (hub) → `client.html` (el cliente completa su perfil, wizard de 4 pasos)
→ `advisor.html` (bandeja por cliente, revisión, aprobación, carteras, informe
auditado) → `compliance.html` (audit trail, verify, AI logs) → `methodology.html`
(fundamento) → `advanced.html` (modo dev).

Tokens dev de fallback: `dev-advisor-token` (workflow) y `dev-compliance-token`
(verify/ai-logs). Operaciones admin requieren `config/advisor_tokens.yaml` propio
(ver `config/advisor_tokens.yaml.example`).

## Verificación

```powershell
python -m pytest -q                                # suite completa (~2537 tests)
python scripts/run_case_workflow_smoke_check.py    # end-to-end sin server ni key. Exit 0 = PASS
ruff check src tests scripts                       # gate: 0 findings
mypy src                                           # gate: 0 errores
```

## Arquitectura (resumen)

Paquete por capas en `src/risk_first_advisory/` — el orden del pipeline es fijo y
compliance-significativo (governance → suitability → ESG → market data + data
quality; ver I-014 en `docs/INVARIANTS.md`):

| Capa | Rol |
|---|---|
| `kyc/` | Inputs estandarizados del cliente (`KYCData`, `FinancialGoal`, `ESGProfile`) |
| `ai_layer/` | Cliente OpenAI (propone, nunca aprueba), mock determinístico, Risk Gap, Risk Number, Grable-Lytton |
| `rules_layer/` | Governance, suitability, ESG, factibilidad de objetivo, risk budget, reason codes |
| `universe_layer/` | Filtros de preferencia + elegibilidad sobre el universo |
| `data_layer/` | Providers de market data (fixtures, CSV, live ARG+US), covarianza, data quality |
| `portfolio_layer/` | Feasibility check → optimizador → variantes con metadata de override |
| `reporting_layer/` | Reportes Markdown (formatean snapshots; nunca recalculan) |
| `workflow_layer/` | Coordinador end-to-end legacy |
| `persistence_layer/` | SQLite + repositorios por entidad (case-scoped, append-only) |
| `api_layer/` | FastAPI (`main.py` + `schemas.py` + `auth.py` RBAC dev-only) |
| `config_layer/` | Supuestos de riesgo y tokens en YAML auditables |

Dos superficies de API:

1. **Demos MVP legacy** — `/ai/*`, `/live/*`, `/workflow/run` (stateless, mock scriptado).
2. **Workflow case-scoped (Fase 2)** — `/cases/*` persistido: firm → advisor →
   client → case → KYC → análisis IA → aprobación de perfil → preferencias → filtro
   de universo → propuesta → (override) → selección → reporte → auditoría.
   Swagger en `http://127.0.0.1:8000/docs`.

Detalle completo en `docs/ARCHITECTURE.md`.

## Documentación

| Doc | Qué es |
|---|---|
| `CLAUDE.md` | Guía operativa del repo (comandos, convenciones, gates) |
| `docs/INVARIANTS.md` | Contratos de diseño I-NNN (leer antes de tocar workflow/compliance) |
| `docs/DESIGN_DECISIONS.md` | Decisiones DD-NNN con contexto y alternativas |
| `docs/ARCHITECTURE.md` | Capas, flujo de datos, superficies de API |
| `docs/RISK_NUMBER_DESIGN.md` | Diseño del Risk Number 0-100 |
| `docs/RISK_SCORING_THEORY.md` | Fundamento teórico del scoring (γ CRRA, CVaR) |
| `docs/METHODOLOGY_NOTES.md` | Encuadre metodológico del Risk Gap |
| `docs/COMPLIANCE_NOTES.md` | Límites, disclaimers y mecanismos auditables |
| `docs/REASON_CODES.md` | Catálogo de reason codes |
| `docs/PROMPT_DESIGN.md` | Diseño de prompts de la IA |
| `docs/ROADMAP.md` | Backlog vivo (pendientes consolidados) |
| `frontend/README.md` | Mapa de páginas por rol + detalle del frontend |

## Límites (leer antes de mostrar la demo)

- **NO production-ready**: SQLite plano, auth dev-only (tokens opacos en YAML, sin
  JWT/IdP, sin aislamiento por firma), sin cifrado at-rest. No cargar PII real.
- **Market data**: universo CSV generado + fuentes gratuitas (data912/yfinance) sin
  SLA. Los retornos esperados son estimaciones, no research.
- **Hash chain ≠ blockchain**: detecta mutaciones puntuales; un admin con acceso
  directo a la DB podría reescribir la cadena completa (anclaje externo pendiente,
  ver `docs/ROADMAP.md`).
- **La IA nunca decide**: perfil y cartera se aprueban solo por endpoints humanos.
