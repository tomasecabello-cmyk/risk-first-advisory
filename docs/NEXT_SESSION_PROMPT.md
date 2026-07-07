# Handoff — próxima sesión (estado al 2026-07-07)

## Qué pasó en la última sesión

**Limpieza total del repo, completa (5 etapas, commits "Limpieza N/5").**

- `ruff` y `mypy` en **cero** y ahora son **gate obligatorio** (ver CLAUDE.md).
  B008 de FastAPI allowlisteado por config (`extend-immutable-calls`).
- Docs consolidadas: se borraron `TODO_DESIGN_NOTES` (184 KB de historia),
  `UX_REDESIGN_PLAN`, `DEMO_SCRIPT` y el handoff viejo. **El único backlog vivo es
  `docs/ROADMAP.md`** — los pendientes van ahí, no en TODOs nuevos.
- `README.md` y `frontend/README.md` reescritos de cero (cortos y al día).
- INVARIANTS (I-011), DD-010, COMPLIANCE_NOTES y ARCHITECTURE sincronizados con lo
  implementado.
- Código muerto fuera: bloque BYMA + `data912_live` en `providers.py`, helpers sin
  uso en `reason_codes.py`, `.pptx` generados destrackeados, worktree/branch viejos.
- Fix real de paso: `fetch_series_cached` con `ttl<=0` ya no puede dar cache hit
  espurio (flake de mtime en Windows).

## Próximo paso recomendado

**Cerrar el loop con el cliente** — ítem 1 de `docs/ROADMAP.md` (el cliente ve las
opciones que el asesor comparte y el reporte final en `client.html`). Después: nota
del asesor en el reporte del cliente (ítem 2) y export PDF (ítem 3).

## Cómo correr la demo

```powershell
python scripts/build_arg_universe.py --warm     # 1 vez por día (~2-3 min)
$env:RFA_DEMO_MODE="1"; $env:RFA_LIVE_DATA="1"
python -m uvicorn risk_first_advisory.api_layer.main:app --port 8000
python -m http.server 5500 -d frontend          # otra terminal → http://127.0.0.1:5500
```

## Convenciones que muerden (el resto está en CLAUDE.md)

- Gates antes de commitear Python: `pytest -q` + smoke check + `ruff` + `mypy` (0/0).
- Commits en español, mensaje vía archivo (`git commit -F <archivo>` en scratchpad).
- Los builders `idemo*` / `cw*` del frontend son compartidos: reusar por carga, no
  duplicar ni tocar.
- Verificar frontend con el patrón Node (stubs + respuestas reales por curl); el
  browser headless muere entre llamadas en este sandbox Windows.
