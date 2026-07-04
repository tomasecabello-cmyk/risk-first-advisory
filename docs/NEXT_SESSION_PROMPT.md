# Próxima sesión — Risk Number Slice 4 (reporte + pregunta de trade-off)

> **Para la sesión nueva:** leé este doc entero antes de codear. Contexto completo en
> `docs/RISK_NUMBER_DESIGN.md` (estado ACTIVO, Slices 1-3 hechos + revisión DD-012)
> y `docs/DESIGN_DECISIONS.md` (DD-012). Los invariantes en `docs/INVARIANTS.md`
> son contratos de compliance — leerlos antes de tocar api_layer/reporting_layer.

## Estado al cierre de la sesión anterior (2026-07-03, commits hasta `e341596`)

El Risk Number 0-100 (enfoque A, diferenciado de Nitrogen) está completo de punta a
punta salvo dos piezas:

- `ai_layer/risk_number.py` — núcleo puro, 42 tests. Anchors derivados del YAML
  (DD-012), número del cliente = operativo `min(tolerancia, capacidad)`,
  alineación por puntos, señal informativa sin flag de override.
- API: `POST /cases/{id}/ai/profile-analysis` → `risk_number` (ClientRiskNumber);
  `POST /cases/{id}/portfolio-proposal` → `risk_number` + `risk_alignment` por
  candidato (con `client_kyc_submission_id` trazable).
- Frontend demo guiada: card del cliente (paso 3) + columna "Nº riesgo" con pill
  de alineación (paso 5).

## Tarea A — Sección Risk Number en el reporte markdown

**Dónde:** `reporting_layer/` (`CaseMarkdownReportGenerator`) + el endpoint de
reporte en `api_layer/main.py` (~línea 6050-6100, buscar `capacity_data`).

**Patrón a seguir (exacto):** el reporte ya recibe `capacity_data` — el endpoint
carga el KYC vigente del case y computa `deterministic_assessment` +
`capacity_gap_from_kyc`, y el generator lo FORMATEA. Hacer lo mismo:

1. En el endpoint de reporte, computar `client_risk_number(kyc_payload)` (import
   de `ai_layer.risk_number`) junto al `capacity_data` existente y pasarlo al
   generator (p.ej. dentro de `capacity_data` o un arg nuevo `risk_number_data`).
2. Los números POR CARTERA ya están PERSISTIDOS dentro de
   `proposal_data["candidates"][i]["risk_number"]` y `["risk_alignment"]` — el
   generator los lee del snapshot, NO los recalcula (I-013/I-020: los reports
   formatean, nunca recalculan; el cliente sí se recomputa del KYC persistido,
   igual que capacity_data — ese patrón ya está aceptado).
3. Sección sugerida: "## Risk Number" con el número del cliente (operativo +
   tolerancia + techo), el número de la cartera SELECCIONADA y su alineación
   (status + explicación). Tolerante: si el proposal es viejo y no tiene
   `risk_number`, la sección se omite o dice "no disponible" — nunca rompe.
4. Tests: seguir el patrón de los tests existentes del report generator
   (Grep `capacity` en `tests/` para encontrarlos). Casos: con datos completos,
   proposal legacy sin risk_number, case sin KYC.

**Gotcha:** el generator NO importa nada de api_layer ni llama motores — recibe
dicts ya computados. Mantener eso.

## Tarea B — Pregunta de trade-off en el KYC (activa el cross-check)

**Qué es:** hoy `client_risk_number` es willingness-only (`tradeoff_number`/`gamma`
= None). La segunda elicitación es una pregunta de certainty equivalent: "tenés
una apuesta 50/50 de ganar G o perder L; ¿qué monto SEGURO te resulta
indiferente?" → γ CRRA → número → cross-check de divergencia (≥20 puntos = señal
con preguntas de confirmación). El core ya existe y está testeado
(`crra_gamma_from_certainty_equivalent`, `tradeoff_risk_number`,
`client_risk_number(payload, tradeoff=...)`) — solo falta capturar el dato.

**CUIDADO IP (leer `docs/RISK_SCORING_THEORY.md` §2/§3):** NO usar el framing
patentado de Nitrogen ("¿qué pérdida sería devastadora/aceptable?" en dólares).
El certainty equivalent académico (CRRA) es toolkit libre (§3). Mantener el
framing de indiferencia entre apuesta y monto seguro.

**Diseño sugerido:**
1. `KYCDataRequest` (schemas.py): campos opcionales tipados, p.ej.
   `tradeoff_gain_usd: float | None`, `tradeoff_loss_usd: float | None`,
   `tradeoff_certain_amount_usd: float | None` (validados: gain>0, loss>=0,
   -loss < certain < gain — o dejar que el motor valide y el endpoint tolere).
   La riqueza W = `liquid_net_worth` del mismo KYC (no preguntarla de nuevo).
   Respeta I-015 (KYC estandarizado: campos estructurados, no conversación libre).
2. En los DOS puntos que llaman `client_risk_number` (profile-analysis ~línea
   3750 y portfolio-proposal paso 6b), armar `tradeoff={"wealth": liquid_net_worth,
   "gain": ..., "loss": ..., "certain_amount": ...}` si los campos están
   presentes y son válidos; si no, seguir con None como hoy. Tolerante a errores
   (try/except ValueError → tradeoff None), nunca 500.
3. Frontend (`frontend/js/investor-demo.js`): agregar la pregunta al form del
   KYC (paso 2) con montos proporcionales al patrimonio líquido ingresado
   (p.ej. G = 10% del líquido, L = 5%, slider o input para C). La card del
   paso 3 ya renderiza tolerancia combinada y divergencia sin cambios — pero
   verificar que muestre bien el caso `inconsistent=true` (preguntas de
   confirmación del cross-check).
4. Tests: integración profile-analysis con trade-off (consistente e
   inconsistente), y unit del armado del dict tradeoff si se factoriza.

## Tarea C (opcional, chica) — `GAMMA_ANCHORS` a `config/`

Solo si sobra tiempo: mover los anchors de γ a un YAML en `config/` con loader en
`config_layer` (patrón de `risk_assumptions.py`). Los downside ya derivan del
YAML; los de γ son la última calibración hardcodeada.

## Verificación (obligatoria antes de cada commit)

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q                                  # suite completa (~2500)
python scripts/run_case_workflow_smoke_check.py      # end-to-end, exit 0 = PASS
ruff check src tests                                 # solo archivos tocados limpios (hay backlog pre-existente)
mypy src                                             # ~5 errores pre-existentes en main.py, no sumar nuevos
```

Para probar el frontend: el daemon de `browse` muere entre llamadas en esta
máquina (sandbox Windows) — verificar con el patrón Node: capturar respuestas
reales por curl (backend con `RFA_DEMO_MODE=1` + seed `bootstrap_local_demo.py`,
crear case con `firm_demo_local`/`client_demo_local`/`advisor_demo_local`) y
ejecutar los builders de `investor-demo.js` en Node con stubs
(window/document/escapeHTML). Ver ejemplo en la memoria de la sesión 2026-07-03.

## Convenciones que muerden

- Commits en español, mensaje vía archivo (`git commit -F <archivo>`) — el guard
  de la sesión bloquea here-strings de PowerShell.
- No tocar `.gitignore` (cambio pre-existente del usuario sin commitear).
- Bilingüe: UI en español, identificadores en inglés. Docstrings español.
- Actualizar `docs/RISK_NUMBER_DESIGN.md` (estado) y, si hay decisión de diseño
  nueva, entrada DD-NNN en `docs/DESIGN_DECISIONS.md`.
- Todo mutation case-scoped es append-only con AuditEvent (I-021/I-023) — pero
  estas tareas no agregan endpoints nuevos, solo enriquecen respuestas/reporte.
