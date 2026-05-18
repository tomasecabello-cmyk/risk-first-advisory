# Risk-First Advisory Report

## Client

- **Client ID:** FIX-004
- **Advisor ID:** ADV-DEMO-001
- **Session ID:** SES-20260518-151708

## Workflow Status

- **Status:** `blocked_by_portfolio_feasibility`
- **Completed:** No
- **Warnings:** 5

## Approved Profile

- **Profile:** moderado
- **Advisor comment:** Tras follow-up, la tolerancia real del cliente es mayor a la declarada inicialmente. Su comportamiento documentado durante 2020 confirma que sostiene posiciones bajo estrés. Se aprueba moderado en lugar de moderado-defensivo.
- **AI initial proposal:** moderado-defensivo
- **AI revised proposal:** moderado
- **Advisor modified:** Yes
- **Follow-up rounds:** 1

## Goal Feasibility

- **Status:** viable
- **Required return:** 4.94%
- **Achievable return:** 7.00%
- **Gap:** -2.06%
- **Blocks portfolio generation:** No
- **Reason:** El retorno requerido (4.9%) se encuentra dentro del rango alcanzable para el perfil 'moderado' (7.0%). El objetivo es financieramente viable con margen suficiente.

*Los retornos futuros no están garantizados. Este análisis usa supuestos técnicos de mercado y no constituye predicción.*

## Risk Budget

- **Profile:** moderado
- **Target volatility:** 4.00%
- **Max volatility:** 5.33%
- **Max drawdown:** -8.00%
- **Min liquidity:** 20.00%
- **Max equity:** 40.00%
- **Max high yield:** 10.00%
- **Max single asset:** 15.00%
- **Max sector exposure:** 30.00%
- **Max duration:** 5.0 years
- **Complex products allowed:** No
- **Preferred currency:** USD

**Notes:**
  - min_liquidity ajustado a 20.00% según necesidad de liquidez declarada en KYC.
  - max_drawdown ajustado a -8.00% porque la tolerancia emocional del cliente (8.0%) es menor al drawdown previo.
  - target_volatility y max_volatility reducidos proporcionalmente (factor 0.533).

## Universe Summary

| Stage | Tickers |
|---|---|
| Governance passed | 7 (BIL, SHV, AGG, IEF, VTI, VEA, HYG) |
| Suitability passed | 7 (BIL, SHV, AGG, IEF, VTI, VEA, HYG) |
| ESG blocked | 0 (none) |
| Data quality failed | 0 (none) |
| **Final optimizer universe** | **4 (BIL, AGG, VEA, HYG)** |

## Portfolio Feasibility

- **Status:** infeasible
- **Is feasible:** No
- **Asset count:** 4
- **Required min single-asset cap:** 25.00%
- **Actual max single asset:** 15.00%
- **Min achievable volatility:** N/A
- **Max allowed volatility:** 5.33%

**Failed checks:**
  - PORTFOLIO_MAX_SINGLE_ASSET_TOO_LOW

**Suggested actions:**
  - Aumentar max_single_asset, ampliar universo o permitir posición residual en cash.

## Candidate Portfolios

No portfolios generated.

## Warnings and Reason Codes

**Reason codes:**
  - SUITABILITY_LIMITED
  - ESG_WARNING
  - DATA_MISSING
  - PORTFOLIO_GENERATION_BLOCKED

**Warnings:**
  - Suitability LIMITED para HYG (max_allocation=0.1).
  - ESG UNKNOWN para BIL: sin metadata ESG.
  - ESG UNKNOWN para SHV: sin metadata ESG.
  - ESG UNKNOWN para IEF: sin metadata ESG.
  - ESG UNKNOWN para VTI: sin metadata ESG.

**Notes:**
  - Sin market data para SHV → excluido del universo final.
  - Sin market data para IEF → excluido del universo final.
  - Sin market data para VTI → excluido del universo final.
  - El RiskBudget aprobado no es factible con el universo final. Política productiva: el workflow NO relaja max_single_asset ni max_volatility automáticamente.
  - failed_check: PORTFOLIO_MAX_SINGLE_ASSET_TOO_LOW
  - Sugerencia: Aumentar max_single_asset, ampliar universo o permitir posición residual en cash.

## Audit Trail

- **Session ID:** SES-20260518-151708
- **Closed:** Yes
- **Events (7):**
  1. `session_started`
  2. `ai_output_initial`
  3. `follow_up_cycle_1_started`
  4. `follow_up_cycle_1_completed`
  5. `ai_output_revised`
  6. `advisor_profile_approval`
  7. `session_closed`

## Disclaimer

*This report is for advisory support only. It does not constitute a guarantee of performance. Final suitability and implementation decisions remain under advisor supervision.*