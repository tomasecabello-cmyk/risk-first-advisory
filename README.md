# risk-first-advisory

> No optimizamos carteras genéricas: construimos alternativas de inversión desde
> el riesgo real del cliente, con IA supervisada por el asesor y dentro de un
> universo previamente aprobado por la firma.

## Estado

Sprint 0 + Sprint 1 (mínimo). Cimientos para que `pytest` corra verde.

Componentes implementados en esta fase:

- `ReasonCode` — catálogo central de motivos.
- `KYCData`, `FinancialGoal`, `ESGProfile` — modelos del KYC sin
  `return_target_annual_pct` (eliminado para evitar circularidad).
- `Portfolio*` — estados del portfolio (Generated → Approved → ClientSelected).
- `AuditTrail` — registro append-only, inmutable tras `close()`.

Pendiente para próximos sprints:

- Capa de reglas (governance, suitability, ESG, viabilidad).
- Capa cuantitativa (data providers, optimizador, riesgo, costos).
- Capa IA (con `MockAIClient` antes de Anthropic real).
- Capa humana (interfaces del asesor).
- Orquestador `RiskFirstSuitabilityEngine`.

## Principios

1. La IA no recomienda inversiones ni decide pesos de cartera.
2. El asesor valida perfil, resuelve contradicciones y aprueba carteras.
3. El universo nace de governance, no del proveedor de datos.
4. El perfil surge de tolerancia + capacidad — nunca de la necesidad de retorno.
5. `preliminary_profile` (lo que propone la IA) y `approved_profile` (lo que
   valida el asesor) son conceptos distintos. Toda diferencia exige justificación.
6. Solo `ApprovedPortfolio` puede presentarse al cliente.
7. Todo motivo cita un `ReasonCode`. Todo evento queda en audit trail.

## Setup local (Windows)

```cmd
cd C:\Users\maria\risk-first-advisory
.venv\Scripts\activate
pip install -e .[dev]
pytest
```

## Compliance

Este software no constituye recomendación de inversión. Es una herramienta de
soporte para asesores financieros matriculados, que mantienen la responsabilidad
profesional sobre toda decisión presentada al cliente.

Los retornos esperados son estimaciones técnicas, no predicciones ni garantías.