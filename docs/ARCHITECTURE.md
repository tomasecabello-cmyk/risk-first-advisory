# Architecture — risk-first-advisory

**Estado:** M1 completo. Fase 2 cerrada como workflow case-scoped backend (ver sección "Fase 2 — case-scoped entities y workflow" al final). Fase 3 **cerrada como local/demo plug-and-play** ✅: Case Dashboard + Case Workbench (15 paneles end-to-end) + frontend separado en `frontend/index.html` + `frontend/css/base.css` + `frontend/js/{common,legacy-demo,case-dashboard,case-workbench}.js` (scripts clásicos, sin build step) + `scripts/bootstrap_local_demo.py` como entrypoint dev/demo (migrate + seed + check + imprime URLs / tokens / comandos). **Esto NO significa production-ready ni piloto B2B vendible** — ver `README.md` → "Phase 3 local demo readiness" para scope exacto. **Fase 4 próxima**: pilot readiness / hardening (market data, PDF, firm-level access, production auth, backup/restore, `/health/full` runtime, deployment productivo).

---

## Capas del sistema

El sistema se organiza en capas verticales. Cada capa tiene responsabilidades acotadas y depende solo de las capas inferiores (KYC, modelos de dominio) o de abstracciones bien definidas.

```
┌─────────────────────────────────────────────────────────┐
│  reporting_layer         (formatea resultados)          │
├─────────────────────────────────────────────────────────┤
│  workflow_layer          (orquesta el flujo completo)   │
├─────────────────────────────────────────────────────────┤
│  portfolio_layer         (feasibility + optimización)   │
├────────────────────┬────────────────────────────────────┤
│  rules_layer       │  data_layer                        │
│  (governance,      │  (market data, DQ, returns,        │
│   suitability,     │   covariance)                      │
│   ESG, feasibility,│                                    │
│   risk budget)     │                                    │
├────────────────────┴────────────────────────────────────┤
│  human_layer             (advisor interface, audit)     │
├─────────────────────────────────────────────────────────┤
│  ai_layer                (mock AI client)               │
├─────────────────────────────────────────────────────────┤
│  kyc / models            (datos del cliente, RiskBudget)│
└─────────────────────────────────────────────────────────┘
```

---

## Descripción de cada capa

### `kyc`
- **Qué hace:** define los modelos de datos del cliente (`KYCData`, `FinancialGoal`, `ESGProfile`, `ESGExclusion`, `ESGPreference`).
- **Qué NO hace:** no calcula perfiles, no evalúa riesgo, no persiste datos.
- **Invariante clave:** `declared_return_expectation_pct` está en `KYCData` solo como dato informativo; no determina el perfil de riesgo ni el objetivo de retorno del optimizador.

### `ai_layer`
- **Qué hace:** propone un `PreliminaryProfile` (nombre de perfil, dimensión vinculante, contradicciones detectadas, preguntas de follow-up). Actualmente implementado como `MockAIClient` con respuestas scripted.
- **Qué NO hace:** no aprueba perfiles, no genera portfolios, no accede a datos de mercado, no toma decisiones vinculantes.
- **Invariante clave:** la IA propone; el asesor decide. `advisor_review_required` siempre es `True` en `PreliminaryProfile`.

### `human_layer`
- **Qué hace:** `ScriptedAdvisorInterface` simula las decisiones del asesor (respuestas al follow-up, aprobación de perfil). `AuditTrail` registra todos los eventos de la sesión en orden cronológico.
- **Qué NO hace:** no evalúa riesgo, no construye portfolios.
- **Invariante clave:** el `AuditTrail` es append-only y queda cerrado al final de la sesión. Una vez cerrado, no acepta nuevos registros.

### `rules_layer`
Contiene cuatro sub-módulos independientes:

| Sub-módulo | Responsabilidad |
|---|---|
| `product_governance` | Filtra instrumentos por perfil aprobado (`ApprovedProductUniverse`). |
| `instrument_suitability` | Evalúa si cada tipo de instrumento es ALLOWED / LIMITED / NOT_ALLOWED para el perfil. |
| `esg_compliance` | Aplica exclusiones duras y preferencias blandas ESG. Devuelve COMPLIANT / SOFT_WARNING / BLOCKED / UNKNOWN. |
| `goal_feasibility` | Evalúa si el `FinancialGoal` es alcanzable dado el perfil aprobado. Puede bloquear la generación de portfolios. |
| `risk_budget_builder` | Construye el `RiskBudget` (límites cuantitativos) a partir del perfil aprobado y el KYC. |

- **Qué NO hace:** no optimiza, no accede a datos de mercado en tiempo real, no decide qué comprar.

### `data_layer`
| Sub-módulo | Responsabilidad |
|---|---|
| `market_data` | Provee snapshots de mercado por ticker (`MockMarketDataProvider`). Si un ticker no tiene snapshot, devuelve `None`. |
| `data_quality` | Evalúa si el snapshot es utilizable: detecta datos stale, campos críticos faltantes, liquidez baja, volatilidad cero en non-cash. |
| `return_estimator` | Estima retornos esperados anuales por ticker a partir del snapshot y los resultados de ESG/DQ. |
| `covariance` | Construye la matriz de covarianza a partir de los snapshots finales. |

- **Qué NO hace:** no filtra por suitability, no evalúa ESG, no optimiza.

### `portfolio_layer`
| Sub-módulo | Responsabilidad |
|---|---|
| `feasibility` | `PortfolioFeasibilityChecker`: evalúa si el universo final + RiskBudget permiten construir una cartera matemáticamente válida, antes de invocar al optimizador. |
| `optimizer` | `PortfolioOptimizer`: optimización long-only (MIN_VARIANCE, MAX_UTILITY, MAX_RETURN) usando scipy/SLSQP. Recibe instrumentos ya filtrados y validados. |
| `generation` | `PortfolioGenerationCoordinator`: genera hasta 3 variantes (DEFENSIVE, BALANCED, GROWTH). Corre el pre-check de factibilidad por variante antes de llamar al optimizer. |

- **Qué NO hace:** no evalúa governance, suitability, ESG ni data quality. Recibe el universo final limpio.

### `workflow_layer`
- **Qué hace:** `AdvisoryWorkflowCoordinator` orquesta el flujo completo de punta a punta. Es la fuente única de verdad del negocio. Devuelve `AdvisoryWorkflowResult` con todos los estados intermedios y terminales.
- **Qué NO hace:** no relaja el `RiskBudget` aprobado, no decide suitability, no accede a datos externos.
- **Invariante clave:** cualquier UI, script, o report generator debe consumir el coordinator; **nunca reimplementar el orden de capas**.

### `reporting_layer`
- **Qué hace:** `MarkdownReportGenerator` convierte un `AdvisoryWorkflowResult` en un informe Markdown (`MarkdownReport`). Puede guardarse a disco.
- **Qué NO hace:** no recalcula nada, no toma decisiones, no valida perfiles. Solo formatea lo que ya existe en el resultado.

---

## Flujo principal (M1 completo)

```
KYCData + FinancialGoal
        │
        ▼
[M1: ai_layer] ─── propone PreliminaryProfile (perfil, contradicciones)
        │
        ▼ (si contradicción alta)
[M1: follow-up] ── asesor responde preguntas → IA revisa → PreliminaryProfile revisado
        │
        ▼
[M1: human_layer] ─ asesor aprueba → ApprovedProfile + AuditTrail cerrado
        │
        ▼
[rules_layer: GoalFeasibilityEngine]
        │  BLOQUEADO → BLOCKED_BY_GOAL_FEASIBILITY
        │
        ▼ (viable)
[rules_layer: RiskBudgetBuilder] → RiskBudget
        │
        ▼
[rules_layer: ProductGovernance] → governance_passed_tickers
        │
        ▼
[rules_layer: InstrumentSuitability] → suitability_passed_tickers (ALLOWED + LIMITED)
        │
        ▼
[rules_layer: ESGComplianceChecker] → esg_blocked_tickers excluidos, esg_passed con warnings
        │
        ▼
[data_layer: MockMarketDataProvider] → excluye tickers sin snapshot
        │
        ▼
[data_layer: DataQualityGate] → data_quality_failed_tickers excluidos
        │
        ▼  (final_optimizer_tickers)
        │  VACÍO → BLOCKED_BY_EMPTY_UNIVERSE
        │
        ▼ (no vacío)
[data_layer: ReturnEstimator + CovarianceEngine]
        │
        ▼
[portfolio_layer: PortfolioFeasibilityChecker]
        │  INFEASIBLE → BLOCKED_BY_PORTFOLIO_FEASIBILITY
        │
        ▼ (feasible o warning)
[portfolio_layer: PortfolioGenerationCoordinator]
        │  → PortfolioCandidateSet (DEFENSIVE, BALANCED, GROWTH)
        │  ValueError → BLOCKED_BY_PORTFOLIO_FEASIBILITY
        │
        ▼
AdvisoryWorkflowResult (COMPLETED / COMPLETED_WITH_WARNINGS)
        │
        ▼
[reporting_layer: MarkdownReportGenerator] → MarkdownReport (solo formatea)
```

---

## `run_demo.py` vs `AdvisoryWorkflowCoordinator`

| | `run_demo.py` | `AdvisoryWorkflowCoordinator` |
|---|---|---|
| **Rol** | Script de consola para demostración | Fachada productiva del negocio |
| **Responsabilidad** | Cargar fixtures, invocar el coordinator, imprimir resultado, generar reporte | Orquestar el flujo completo |
| **Ajustes al RiskBudget** | Ninguno (eliminado) | Ninguno (política productiva) |
| **Reimplementa pipeline** | No — delega 100% al coordinator | Es el pipeline |
| **Bloques bloqueados** | Muestra diagnóstico legible | Devuelve `AdvisoryWorkflowStatus` bloqueado con `reason_codes` |

**Por qué el workflow es la fuente única de verdad:** cualquier otro consumidor (FastAPI, notebook, batch job, report generator) que reimplemente el orden de filtros corre el riesgo de producir resultados inconsistentes con el criterio de compliance aprobado. El coordinator es el único punto donde governance → suitability → ESG → data quality → feasibility → portfolio se aplican en el orden correcto y con la política de bloqueo correcta.

---

## Fase 2 — case-scoped entities y workflow

Fase 2 introduce una capa de **entidades persistentes** sobre SQLite que extienden el modelo legacy (que usa la tabla `records` client-scoped) sin reemplazarlo. Las dos capas coexisten:

- **Legacy (`records`)**: workflow client_id-scoped, sin case linkage. Sigue vivo y soporta los endpoints `/workflow/run`, `/ai/filtered-portfolio-demo`, `/advisor/profile-approval`, `/advisor/override-approval`, `/advisor/portfolio-selection` (Fase 0/1).
- **Case-scoped (Fase 2)**: entidades nuevas con FKs explícitas, scope por `case_id`, AuditEvent hash chain, AIRequestLog con redacción, RBAC por rol. Soporta el workflow completo a través de `/cases/*`.

### Modelo de entidades (jerarquía)

```
Firm (firms)
 └── Advisor (advisors)
       └── Client (clients)
             └── AdvisoryCase (advisory_cases)
                   ├── KYCSubmission           (kyc_submissions, versionado)
                   ├── AIProfileAnalysis       (ai_profile_analyses)
                   ├── AdvisorProfileApproval  (advisor_profile_approvals, is_current)
                   ├── InvestmentPreferences   (case_investment_preferences, is_current)
                   ├── UniverseFilterRun       (case_universe_filter_runs, is_current)
                   ├── PortfolioProposal       (case_portfolio_proposals, is_current)
                   ├── OverrideApproval        (case_override_approvals, is_current)
                   ├── PortfolioSelection      (case_portfolio_selections, is_current)
                   ├── CaseReport              (case_reports, versionado por case)
                   ├── AuditEvent              (audit_events, hash chain por case_id)
                   └── AIRequestLog            (ai_request_logs, indirecto vía case_id)
```

`advisory_cases` mantiene punteros materializados a:
- `current_kyc_submission_id`
- `current_approved_profile_id`
- `current_portfolio_selection_id`

Status FSM del case: `DRAFT → IN_PROGRESS → PORTFOLIO_SELECTED → CLOSED`.

### Flujo completo case-scoped

```
POST /cases                              (case created → AuditEvent case_created)
  │
  ▼
POST /cases/{id}/kyc                     (kyc_submitted; DRAFT → IN_PROGRESS)
  │
  ▼
POST /cases/{id}/ai/profile-analysis     (ai_profile_analyzed; AIRequestLog persistido)
  │
  ▼
POST /cases/{id}/profile-approval        (advisor_profile_approved/_modified/_rejected;
  │                                       actualiza current_approved_profile_id)
  ▼
POST /cases/{id}/investment-preferences  (investment_preferences_recorded; manual o AI-extracted)
  │
  ▼
POST /cases/{id}/universe-filter         (universe_filtered; PreferenceFilterEngine sobre CSV)
  │
  ▼
POST /cases/{id}/portfolio-proposal      (portfolio_proposal_generated;
  │                                       PortfolioGenerationCoordinator)
  ▼ (si algún candidate requiere override)
POST /cases/{id}/override-approval       (advisor_override_approved/_rejected)
  │
  ▼
POST /cases/{id}/portfolio-selection     (portfolio_selected;
  │                                       actualiza current_portfolio_selection_id;
  │                                       IN_PROGRESS → PORTFOLIO_SELECTED)
  ▼
POST /cases/{id}/reports                 (report_generated; markdown determinístico)
  │
  ▼
GET  /cases/{id}/summary                 (full case state — base para Case Workbench)
GET  /cases/{id}/audit/verify            (valida hash chain del case)
```

### Coexistencia legacy vs case-scoped

- Las tablas `records` y `counters` (legacy `SQLitePersistenceStore`) **NO son tocadas** por las migrations Fase 2.
- El runner `scripts/migrate.py` solo crea/usa `schema_migrations` y las tablas case-scoped.
- `SQLiteEntityStore` (Fase 2) y `SQLitePersistenceStore` (legacy) pueden coexistir en el mismo archivo SQLite — comparten `counters` para ID generation (con prefijos distintos), sin colisión.
- Los endpoints legacy NO consultan las tablas case-scoped y viceversa. Los dos workflows están aislados a nivel storage.
- Deprecación / migración del legacy queda fuera del scope Fase 2.

### Audit chain (Fase 2)

Cada `AuditEvent` queda anclado a un `case_id` con `sequence` monotónico (`UNIQUE(case_id, sequence)`). Cada evento incluye:
- `payload_hash` = SHA-256 sobre canonical JSON del payload.
- `previous_hash` = `event_hash` del evento anterior (NULL para `sequence=1`).
- `event_hash` = SHA-256 sobre `(previous_hash, sequence, event_type, actor_advisor_id, actor_role, created_at_utc, payload_hash)` canonical.

`GET /cases/{id}/audit/verify` recomputa toda la cadena y reporta `is_intact` + `first_broken_sequence`. Detecta mutaciones puntuales (un payload, un hash, un sequence gap) pero NO una reescritura completa coordinada (no es blockchain — ver `docs/COMPLIANCE_NOTES.md` sección 0).
