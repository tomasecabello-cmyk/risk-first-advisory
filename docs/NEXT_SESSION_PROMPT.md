# Handoff — próxima sesión (estado al 2026-07-08)

## Qué pasó en la última sesión

**Loop con el cliente cerrado** (commits "Loop cliente 1/3".."3/3") y
**estimación live LW+BL** (commit `191af3f`, DD-014):

- `client.html`: estado "esperando a tu asesor", vista read-only del caso
  (una llamada a `GET /cases/{id}/summary`), comentario del asesor
  (última `advisor_note` del audit) y export PDF (`window.print()`).
  Builders `idemo*`/`cw*` reusados por carga; los `<button>` se remueven del DOM.
- `data_layer/estimation.py` (portado de markowitz-optimizer): en el path live
  (`RFA_LIVE_DATA=1`) Σ = **Ledoit-Wolf** sobre series alineadas (ARS→USD CCL) y
  μ = **Black-Litterman** (prior equal-weight + media histórica como view).
  Sanity bound de vol (>300% = serie corrupta, descartada con razón auditada).
  `PortfolioGenerationInfeasibleError` persiste el diagnóstico por variante en
  los `warnings` del proposal (min_achievable_volatility vs budget + sugerencias).
- Resultado medido: piso de vol solo-ARG ~30% → ~9.7%; "moderado" solo-ARG pasó
  de infeasible a `completed` (100% instrumentos AR); GD29 μ 40%→10.4%, vol 61%→19.6%.
- Modo fixture intacto: `CovarianceEngine` (mock) sigue para tests/smoke y fallback.

## Próximo paso recomendado (en orden)

1. **Quirk `review_override`** (chico, backend — deuda técnica del ROADMAP):
   si el proposal tiene una variante con override pero el asesor selecciona una
   SIN override, `next_recommended_action` queda clavado en `review_override` y
   `completion_ratio` nunca llega a 1.0. Decidir si `has_override_requirement`
   debe evaluarse contra la SELECCIÓN y ajustar summary + smoke check + tests.
2. **Saltos de ratio en series CEDEAR** (quant, completa DD-014): el sanity
   bound ataja vol >300%, pero IBM (~137%) y NFLX (~149%) tienen saltos de ratio
   dentro del umbral que inflan σ. Detectar el salto (retorno diario absurdo
   aislado, p.ej. |r| > 40%) y ajustar/recortar la serie en el provider.
3. Si sobra: **YTM como view de Black-Litterman** para renta fija (hoy la view
   es la media histórica también para bonos).

## Cómo correr la demo

```powershell
python scripts/build_arg_universe.py --warm     # 1 vez por día (~2-3 min)
$env:RFA_DEMO_MODE="1"; $env:RFA_LIVE_DATA="1"
python -m uvicorn risk_first_advisory.api_layer.main:app --port 8000
python -m http.server 5500 -d frontend          # otra terminal → http://127.0.0.1:5500
```

Loop completo: perfil en `client.html` → flujo del asesor en `advisor.html`
(incluida la nota del informe) → volver a `client.html` → "Ver el estado de mi caso".

## Convenciones que muerden (el resto está en CLAUDE.md)

- Gates antes de commitear Python: `pytest -q` (~2553) + smoke check + `ruff` +
  `mypy` (0/0). Frontend: `node --check` + curl 200 + harness Node.
- Commits en español, mensaje vía archivo (`git commit -F <archivo>` en scratchpad).
- Los builders `idemo*` / `cw*` del frontend son compartidos: reusar por carga, no
  duplicar ni tocar.
- El browser headless muere entre llamadas en este sandbox Windows: verificar
  frontend con el patrón Node (stubs + respuestas reales por curl).
- Verificación quant en vivo: flujo por API con httpx contra el server
  (`drive_flow.py` / `arg_only_flow.py` de scratchpad como plantilla) e
  inspección del proposal persistido (warnings incluidos).
- Los pendientes nuevos van a `docs/ROADMAP.md`, no a TODOs nuevos.
- `GET /cases/{id}/audit/verify` requiere rol compliance/admin —
  `dev-advisor-token` da 403 (esperado, no es un bug).
