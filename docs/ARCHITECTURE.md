# Architecture — risk-first-advisory

Estado: M1 completo / M2-prep en curso.

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
