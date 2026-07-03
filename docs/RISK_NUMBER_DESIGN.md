# Risk Number — diseño (enfoque A decidido, Slices 1-3 implementados)

> **Estado:** ACTIVO. El usuario decidió el **enfoque A** (versión diferenciada,
> 2026-07-02) y delegó la elección técnica. **Slices 1, 2 y 3 implementados**
> (2026-07-02/03): `ai_layer/risk_number.py` (módulo puro, sin red) +
> `tests/unit/test_risk_number.py` (30 tests) + wiring en `POST
> /cases/{id}/ai/profile-analysis` (`risk_number` del cliente) y `POST
> /cases/{id}/portfolio-proposal` (`risk_number`/`risk_alignment` por
> candidato). Pendiente: reporte markdown y demo guiada (frontend) — ver §5,
> Slice 3 "queda". El §3 queda como registro de la decisión.

## 0. Empezar acá (para la sesión nueva)

1. Leé este doc entero.
2. Leé `docs/RISK_SCORING_THEORY.md` (§2, §4, §5) — es la fuente del hallazgo de IP de abajo.
3. La decisión A/B/C del §3 la toma el usuario antes de codear. Recomendación: **A**.
4. Recién después, build por slices (§5), arrancando por el módulo puro sin red (Slice 1).

## 1. Qué quiere el usuario

Un **"Risk Number" estilo Nitrogen (ex-Riskalyze)** + un **generador de carteras alineado**.
El valor concreto: un número único e intuitivo para el **cliente** y para la **cartera** en
la **misma escala**, de forma que se puedan **alinear** ("tu número es 62, esta cartera es 68,
va un toque pasada de riesgo"). Decisiones ya tomadas por el usuario:

- **Lado cliente:** las **dos** elicitaciones, cruzadas (Grable-Lytton + pregunta tipo
  trade-off), y la divergencia entre ambas se trata como señal de inconsistencia.
- **Lado cartera:** la **mejor** métrica. Nitrogen usa "rango histórico 95% a 6 meses";
  ver §3 porque ese mapeo específico es justo lo que el repo marcó como a evitar.

Contexto del usuario (de la conversación): el horizonte inmediato es una **defensa académica**
+ pieza de portfolio, con un "eventualmente algo real" en el fondo. Esa bifurcación define la
decisión del §3.

## 2. Hallazgo crítico de IP (leer antes de codear)

`docs/RISK_SCORING_THEORY.md` ya documenta una **decisión deliberada del proyecto**: NO
replicar el método de Nitrogen. Cita textual del §2:

> "Distintivo a evitar: la escala **1–99**, la apuesta en **dólares** 'devastador/aceptable',
> y el mapeo **95% / 6 meses → score**."

Y el §4 ya diseñó (en papel, **no implementado**) una alternativa diferenciada para no
infringir:

| Eje | Nitrogen (evitar) | Alternativa propia (§4) |
|---|---|---|
| Escala de tolerancia | 1–99 | γ (CRRA) / score propio / 5 perfiles |
| Métrica de cartera | rango 95% / 6m | **CVaR / Sortino** |
| Horizonte | 6 meses fijo | **configurable** |
| Feature central | un número | **Risk Gap declarado-vs-revelado + asesor** |

El §5 habla de patentabilidad y FTO antes de comercializar. Conclusión: lo que el usuario
pidió (1-99 estilo Nitrogen) es exactamente lo que el repo marcó como a evitar. **No es
bloqueante para una defensa académica** (no se comercializa nada → no dispara infracción),
**sí es un riesgo real para el "algo real"**.

## 3. DECISIÓN — enfoque (resuelta: A, 2026-07-02)

- **A) Versión diferenciada (§4) — RECOMENDADA.** Número único comparable cliente-vs-cartera,
  pero con **escala propia 0-100** (la que ya devuelve `score_stated_profile`), **CVaR/Sortino**
  a **horizonte configurable**, y el **Risk Gap** como corazón. Mismo valor para el usuario
  (0-100 se siente igual que 1-99), legalmente limpio, consistente con los docs, y **media
  parte ya está hecha**.
- **B) Clon literal de Nitrogen.** 1-99 + apuesta en dólares + mapeo 95%/6m. Sólo para defensa
  académica. Copia el método patentado y contradice el §4. Riesgo de IP si se comercializa.
- **C) Híbrido.** Cálculo diferenciado (CVaR, no infringe) pero mostrado como 1-99 para el
  "feel". Ojo: la escala 1-99 en sí también está en la lista a evitar → no queda 100% limpio.

## 4. Qué ya existe (no arrancar de cero)

- **`ai_layer/grable_lytton.py`** — escala Grable-Lytton 13 ítems, validada (α≈0.77), raw
  **13–47**. Funciones: `score_raw`, `raw_to_tolerance_1_10`, `risk_level_label`. Ya tiene las
  preguntas de ganancia/pérdida tipo prospect theory (q8/q9/q10).
- **`ai_layer/risk_scoring.py`** (M-Engine, puro, sin LLM) — ya separa **willingness** (lo que
  el cliente quiere) de **ability** (lo que su situación soporta), y devuelve `score` **0-100**
  en `score_stated_profile` (effective = `min(willingness, ability)`). Ya tiene `compute_risk_gap`,
  `assess_revealed_signal`, `deterministic_ceiling`, `explain_capacity_gap`.
- **`ai_layer/risk_gap.py`** — flag de inconsistencia declarado-vs-revelado (el diferenciador).
- **Generador de carteras** DEFENSIVE/BALANCED/GROWTH + `RiskBudget` (target_vol, max_vol,
  **max_drawdown**) en `config/risk_profiles.yaml`. Ya genera carteras; les falta el número.
- **Datos reales:** `/live/portfolio-demo` ya usa yfinance (`data_layer/live_market_data.py`,
  `free_market_data.py` — NO leídos aún en detalle).

### Gotcha importante (no obvio)
`data_layer/instrument_market_data.py` (`InstrumentMarketDataAdapter`) **solo produce snapshot
para renta fija** (`CORPORATE_BOND`, `SOVEREIGN_BOND`, `MONEY_MARKET`). Para `ETF`, `STOCK`,
`CEDEAR` devuelve `None` (los retornos son proxy de `ytm`/`coupon`). Es decir: **las acciones/ETF
hoy no entran al optimizador por la vía CSV proxy.** Para scorear riesgo de cartera con datos
reales (CVaR/rango histórico) hay que traer **retornos reales** (yfinance / lógica de markowitz),
no el proxy. Ahí encaja la idea del usuario de "universo igual al de markowitz": el universo real
es el **insumo** del Risk Number de la cartera, no un fin en sí.

## 5. Diseño propuesto (para enfoque A) + plan por slices

**Idea unificadora:** anclar la escala en **riesgo de downside** para que cliente y cartera sean
comparables. La cartera produce un downside real (CVaR/semidesvío a horizonte configurable); el
cliente produce un downside *aceptable* (de G-L y de la pregunta de trade-off). Misma función de
mapeo → mismo número → alineación.

- **Slice 1 — HECHO (2026-07-02).** Módulo nuevo `ai_layer/risk_number.py`
  (puro, sin red, 26 tests en `tests/unit/test_risk_number.py`). Implementación:
  - escala 0–100 en bandas de 20 (los 5 perfiles); anclajes downside→número
    derivados de los `max_drawdown` de `config/risk_profiles.yaml`
    (`DOWNSIDE_ANCHORS`, tuneables por parámetro; mover a `config/` en Slice 3);
  - cartera: `portfolio_risk_number` — CVaR 95% (α configurable) a horizonte
    configurable, paramétrico normal desde (μ,σ) anuales o empírico desde un
    array de retornos;
  - cliente: `client_risk_number` — willingness (G-L vía `score_stated_profile`)
    cruzado con la pregunta de trade-off (`crra_gamma_from_certainty_equivalent`,
    bisección sobre CE; `GAMMA_ANCHORS` γ→número); divergencia entre ambas en
    bandas = señal de inconsistencia con preguntas de confirmación (espíritu
    Risk Gap, no medición conductual);
  - alineación: `align_numbers` / `assess_risk_alignment` — cliente vs techo de
    capacidad (ability) vs cartera; `over_capacity` (por bandas, requiere
    override del asesor) / `over_tolerance` / `aligned` / `under_tolerance`.

  Diseño original del slice (referencia):
  - cliente: willingness (vía G-L) → número; pregunta de trade-off (certainty equivalent → γ CRRA,
    fórmula en `RISK_SCORING_THEORY.md §4`) → número; **cross-check** de divergencia (= un risk gap).
  - cartera: dado un array de retornos (o μ, σ) → CVaR/semidesvío a horizonte configurable →
    número, con mapeo **documentado y tuneable en `config/`**.
  - alineación: cliente vs cartera vs **techo de capacidad** (ability) en la misma escala.
  - tests unitarios deterministas. Sin tocar API/DB/red.
- **Slice 2 — HECHO (2026-07-03).** El "proveedor de retornos reales para el universo" ya
  existía (`LiveMarketDataProvider`, yfinance/data912, opt-in vía `RFA_LIVE_DATA`) y ya cubre
  equities (a diferencia del proxy CSV de `InstrumentMarketDataAdapter`, que solo cubre renta
  fija — ver §4 "Gotcha"). El gap real era que `risk_number.py` no tenía forma de consumir una
  cartera candidata REAL (pesos del optimizador) junto con esos datos. Se agregó:
  - `portfolio_moments_from_weights(weights, expected_returns, tickers, covariance)` — combina
    pesos (p.ej. `OptimizedPortfolio.weights`) con retornos por ticker (p.ej.
    `ReturnEstimate.adjusted_expected_return_annual`) y una matriz de covarianza anualizada
    (p.ej. `CovarianceMatrix`) → `mu_annual = Σwᵢμᵢ`, `sigma_annual = √(w'Σw)`. NO renormaliza
    pesos faltantes (los reporta en `missing_tickers`, auditable); NO importa tipos de
    `data_layer`/`portfolio_layer` (mantiene `ai_layer/risk_number.py` sin acoplar capas — el
    caller en Slice 3 adapta los objetos a listas planas).
  - `portfolio_risk_number_from_weights(...)` — conveniencia que compone lo anterior con
    `portfolio_risk_number`.
  - 4 tests nuevos (30 en total en `test_risk_number.py`), suite completa sin regresiones.
- **Slice 3 — wiring API HECHO (2026-07-03); reporte/frontend pendiente.** Expuesto en el
  flujo case-scoped, respetando I-013/I-020 (formatea, no recalcula) e I-001/I-016/I-019
  (la IA propone, el asesor decide — este módulo solo informa, ningún endpoint nuevo aprueba
  ni selecciona nada):
  - **Cliente** — `POST /cases/{id}/ai/profile-analysis` computa
    `client_risk_number(kyc_payload)` al lado de `capacity_gap`/`deterministic` (mismo patrón:
    derivado del KYC, `None` en GET/list, el POST lo incluye). Schema `ClientRiskNumber`
    (`api_layer/schemas.py`), campo `risk_number` en `AIProfileAnalysisResponse`.
    `tradeoff_number`/`gamma` quedan `None` — el KYC todavía no tiene la pregunta de trade-off
    (certainty equivalent); cuando se agregue, alimenta directamente `client_risk_number(...,
    tradeoff=...)` sin cambios de firma.
  - **Cartera** — `POST /cases/{id}/portfolio-proposal` computa, por candidato,
    `portfolio_risk_number_from_weights` (con los `return_estimates`/`covariance_matrix` YA
    estimados en el paso 6 del endpoint — nada de red/optimizer adicional) → clave
    `risk_number`; y si el case tiene `current_kyc_submission_id`, `align_numbers` contra el
    número del cliente → clave `risk_alignment`. Ambas quedan `None` si faltan datos (universo
    sin cobertura, case sin KYC) — tolerante, no bloquea la generación de la propuesta. Función
    nueva `_compute_candidate_risk_number` en `api_layer/main.py`, sin schema Pydantic dedicado
    (candidates ya es `list[dict[str, Any]]`, mismo patrón que `diversification`).
  - Tests de integración nuevos: `test_risk_number_present` (profile-analysis),
    `TestCandidateRiskNumber` (portfolio-proposal: presente en todo candidate completed,
    `risk_alignment.override_required ⟺ status == "over_capacity"`, GROWTH ≥ DEFENSIVE en
    universo fixture). 104 tests en los dos archivos de integración afectados, suite completa
    (2486 tests) y smoke check end-to-end sin regresiones.
  - **Pendiente** (fuera de este slice): sección de Risk Number en `CaseMarkdownReportGenerator`
    (mismo patrón que `capacity_data` — recomputar del KYC persistido, I-013/I-020 lo permite);
    card en el frontend (`frontend/js/investor-demo.js`, mismo patrón que
    `idemoCapacityGapCardHTML`); mover `DOWNSIDE_ANCHORS`/`GAMMA_ANCHORS` a `config/` (hoy son
    constantes de módulo documentadas y tuneables por parámetro, pero no versionables sin tocar
    Python); pregunta de trade-off en el KYC (para que `client_risk_number` deje de ser
    willingness-only).

## 6. Punteros
- Teoría + IP: `docs/RISK_SCORING_THEORY.md`
- Invariantes de compliance: `docs/INVARIANTS.md`
- Metodología y framing Risk Gap: `docs/METHODOLOGY_NOTES.md`
- Scoring actual: `ai_layer/risk_scoring.py`, `ai_layer/grable_lytton.py`, `ai_layer/risk_gap.py`
- Universo / datos: `universe_layer/`, `data_layer/instrument_market_data.py`,
  `data_layer/live_market_data.py`, `data_layer/free_market_data.py`
- Universo real de referencia (otro repo, solo de consulta): `markowitz-optimizer`
  `src/markowitz_optimizer/data/providers.py`
