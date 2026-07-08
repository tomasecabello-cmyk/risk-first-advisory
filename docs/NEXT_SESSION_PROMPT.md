# Handoff — próxima sesión (estado al 2026-07-07, tarde)

## Qué pasó en la última sesión

**Loop con el cliente cerrado** — los 3 ítems de corto plazo del ROADMAP,
en 3 commits ("Loop cliente 1/3".."3/3") + un refresh del universo:

- `client.html` ya no deja ciego al cliente: estado "esperando a tu asesor"
  tras enviar, banner al volver con un caso en curso (`localStorage.rfaLastCaseId`),
  y vista read-only del caso hidratada con **una** llamada a `GET /cases/{id}/summary`
  (cartera elegida, variantes consideradas en `<details>`, reporte final).
- Los builders `idemo*`/`cw*` se reusaron por carga SIN tocarlos; los `<button>`
  de acción del asesor que traen se remueven del DOM tras el render (I-001 intacto).
- La última `advisor_note` (AuditEvent) aparece como "Comentario de tu asesor".
- Export PDF client-side: botón "Descargar PDF" → `window.print()` con
  `<style media="print">` inline en `client.html` (con la vista abierta se
  imprime solo el caso; los `<details>` se abren antes de imprimir).
- Sigue sin auth de cliente real: reencuadre de demo, mismo token por detrás.
- Universo refrescado (`--warm` del día) commiteado como fixture.

Verificación usada (sirve de plantilla): harness Node en scratchpad con stubs de
DOM/fetch + JSONs **reales** de `/summary` y `/audit` capturados de un flujo
completo contra el server vivo (6 escenarios, incluye strip de botones y print).

## Próximo paso recomendado

Elegir del ROADMAP (único backlog):

1. **Chico, backend**: el quirk anotado en deuda técnica —
   `next_recommended_action` queda clavado en `review_override` (y
   `completion_ratio` < 1.0) si el asesor selecciona una variante sin override
   cuando el proposal contiene una que sí lo requiere. Decidir si
   `has_override_requirement` debe computarse contra la **selección** y ajustar
   summary + smoke check + tests.
2. **Grande, Fase 3**: universo dinámico pleno — generación on-demand del universo,
   bróker como filtro de disponibilidad, YTM como view de Black-Litterman para renta
   fija. (Las correlaciones reales ya están: DD-014, Σ Ledoit-Wolf + μ Black-Litterman
   en el path live, portados de markowitz-optimizer el 2026-07-07.)

## Cómo correr la demo

```powershell
python scripts/build_arg_universe.py --warm     # 1 vez por día (~2-3 min)
$env:RFA_DEMO_MODE="1"; $env:RFA_LIVE_DATA="1"
python -m uvicorn risk_first_advisory.api_layer.main:app --port 8000
python -m http.server 5500 -d frontend          # otra terminal → http://127.0.0.1:5500
```

Para ver el loop completo del cliente: enviar perfil en `client.html`, completar
el flujo como asesor en `advisor.html` (incluida la nota del informe), y volver a
`client.html` → "Ver el estado de mi caso".

## Convenciones que muerden (el resto está en CLAUDE.md)

- Gates antes de commitear Python: `pytest -q` (~2537) + smoke check + `ruff` +
  `mypy` (0/0). Frontend: `node --check` + curl 200 + harness Node.
- Commits en español, mensaje vía archivo (`git commit -F <archivo>` en scratchpad).
- Los builders `idemo*` / `cw*` del frontend son compartidos: reusar por carga, no
  duplicar ni tocar.
- El browser headless muere entre llamadas en este sandbox Windows: verificar
  frontend con el patrón Node (stubs + respuestas reales por curl).
- Los pendientes nuevos van a `docs/ROADMAP.md`, no a TODOs nuevos.
- `GET /cases/{id}/audit/verify` requiere rol compliance/admin —
  `dev-advisor-token` da 403 (esperado, no es un bug).
