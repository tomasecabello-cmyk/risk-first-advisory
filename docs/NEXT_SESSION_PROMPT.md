# Handoff — próxima sesión (estado al 2026-07-06)

> Reemplaza el handoff anterior (Slice 4, ya completo). Leé este doc entero antes de codear.
> Contexto largo pero necesario: la sesión previa cerró el Risk Number, el universo ARG y el
> rediseño del frontend por roles. Falta cerrar el LOOP con el cliente y algunos pendientes.

## ★ PRIORIDAD #1 DE LA PRÓXIMA SESIÓN — LIMPIEZA TOTAL DEL REPO

El usuario quiere **limpiar todo el repo** antes de seguir con features. Referencia que dio:
**https://github.com/DietrichGebert/ponytail** (mirar primero para entender el estándar/estructura
que busca — puede ser un ejemplo de repo limpio, un layout de referencia o una herramienta).

Alcance de la limpieza (a acordar con el usuario al arrancar, pero apuntar a):
- **Docs:** hay muchos `.md` en `docs/` (INVARIANTS, DESIGN_DECISIONS, RISK_*, UX_REDESIGN_PLAN,
  METHODOLOGY_NOTES, este handoff, etc.). Consolidar / indexar / borrar lo obsoleto. El README
  raíz y el `frontend/README.md` tienen partes stale (marcadas como tales) — actualizar.
- **Backlog de lint:** `ruff` tiene cientos de findings pre-existentes y `mypy` ~5. Ver hasta
  dónde vale limpiarlos (CLAUDE.md dice que NO son gate; acordar con el usuario si se ataca).
- **Archivos muertos:** DBs en `data/` (gitignored), scripts sueltos, fixtures viejos, referencias
  a `legacy-demo.js` (ya no existe) en `frontend/README.md`.
- **Estructura:** revisar que la organización de `src/`, `scripts/`, `tests/`, `docs/`, `frontend/`
  sea coherente y esté documentada en un solo lugar (el README raíz + CLAUDE.md).
- **Git:** `.gitignore` tiene un cambio sin commitear de hace varias sesiones — resolverlo.
- Cuidado: NO romper la suite (~2537 tests) ni el smoke check. Limpiar es refactor de bajo riesgo;
  correr los tests después de cada tanda.

**Arrancar la próxima sesión leyendo el repo de referencia (ponytail) + preguntando al usuario
qué entiende por "limpio" (docs, código, estructura, todo) antes de tocar nada.**

Lo de abajo (features pendientes) queda para DESPUÉS de la limpieza, salvo que el usuario diga otra cosa.

## Dónde estamos (qué está HECHO)

**Motor / backend (completo y verificado):**
- **Risk Number 0-100** cliente↔cartera de punta a punta (Slices 1-4). Cliente = operativo
  `min(tolerancia, capacidad)`; cartera = dispersión pura CVaR (μ=0, DD-013). Anclajes
  derivados del YAML (DD-012). Cross-check declarado-vs-trade-off (γ CRRA). Todo en
  `ai_layer/risk_number.py` + wiring en `POST /cases/{id}/ai/profile-analysis` y
  `/portfolio-proposal` + sección en el reporte markdown. Calibración en
  `config/risk_profiles.yaml` + `config/gamma_anchors.yaml`. Pasó 2 code reviews.
- **Universo ARG** `scripts/build_arg_universe.py` (generador reproducible desde data912):
  97 instrumentos líquidos (ETFs US + soberanos hard-dollar + CEDEARs + acciones ARG).
  Escribe `tests/fixtures/universe/live_instrument_universe.csv`. Corré con `--warm` para
  precalentar el caché (~1.5s/instrumento en frío).
- Suite ~2537 tests + smoke check verdes. `docs/DESIGN_DECISIONS.md` (DD-012, DD-013) al día.

**Frontend rediseñado por roles (completo, commits 24cf662, 74c8773, da387ba, 18f9c2a):**
- `index.html` = HUB (hero + 3 tarjetas de rol + "cómo funciona").
- `client.html` = **wizard de 4 pasos** (Tus datos / Cuestionario / Escenarios / Plata real)
  con barra de progreso. Reencuadre de demo (usa token de asesor por detrás). Al enviar:
  prepara+KYC+análisis y muestra su primera lectura (Risk Number, capacidad, inconsistencias).
- `advisor.html` = bandeja **agrupada por cliente** + "Revisión del asesor" (lee las respuestas
  crudas del cliente: cada ítem del cuestionario con la opción elegida + respuestas abiertas) +
  **informe del asesor editable y auditado** (cada Guardar = evento `advisor_note` versionado
  vía `POST /cases/{id}/audit-events`, append-only, hash-chaineado) + flujo de 8 pasos +
  decisión Aprobar/Modificar/Rechazar.
- `compliance.html` = selector de caso + snapshot/verify/audit-trail/ai-logs (token compliance).
- `methodology.html` = fundamento + ejemplo concreto del Risk Gap.
- `advanced.html` = Modo dev (andamiaje; fuera del nav de roles, solo en footer).
- JS finos `js/{client,advisor,compliance}.js` que REUSAN los builders `idemo*`/`cw*` por carga
  (no duplican código). CSS additivo en `css/base.css` (chrome por rol, wizard, bandeja).

**Cómo correr la demo (con universo en vivo):**
```powershell
python scripts/build_arg_universe.py --warm     # precalienta el caché (una vez, ~2-3 min)
$env:RFA_DEMO_MODE="1"; $env:RFA_LIVE_DATA="1"
python -m uvicorn risk_first_advisory.api_layer.main:app --port 8000
python -m http.server 5500 -d frontend           # en otra terminal
# abrir http://127.0.0.1:5500
```

## Qué falta (candidatos para la próxima sesión, en orden sugerido)

### A. Cerrar el LOOP con el cliente (alto valor, frontend) — RECOMENDADO EMPEZAR ACÁ
Hoy el cliente envía su perfil y ve su primera lectura, pero **NO ve las opciones que el asesor
le presenta ni el reporte final**. El usuario lo pidió: "el asesor decide cuál y se las muestra
como opciones al cliente". Construir en `client.html`:
- Un estado "esperando a tu asesor" tras enviar (con el `case_id` guardado en
  `localStorage.rfaLastCaseId`).
- Una vista read-only que, dado el caso, muestre: el reporte final (`GET /cases/{id}/reports`)
  y/o las opciones A/B que el asesor eligió (`GET /cases/{id}/portfolio-proposal` +
  `/portfolio-selection`), encuadradas para el cliente.
- Reusar los builders de reporte/cartera que ya existen (`idemoBuildReportPreviewHtml`,
  `idemoBuildPortfolioComparisonHtml`). El handoff cliente↔asesor ya va por la lista de casos
  persistida + `rfaLastCaseId` (ver `frontend/README.md`).
- Ojo: NO hay auth de cliente real, así que es un reencuadre de demo (el cliente "ve" lo que
  el asesor comparte usando el mismo token). Documentarlo con el `client-note` que ya existe.

### B. El informe del asesor alimenta el reporte al cliente (medio, front + quizás back)
Hoy el "informe del asesor" (notas `advisor_note` auditadas) vive solo en la vista del asesor.
Sumarlo al reporte que ve el cliente (la última versión de la nota como "comentario del asesor").
Requiere leer las notas del audit trail en el generador de reporte o en el front.

### C. Export PDF del reporte (medio) — pendiente viejo de `docs/UX_REDESIGN_PLAN.md`
El reporte hoy es markdown en pantalla. Un botón "descargar PDF" (client-side, sin libs externas:
`window.print()` con CSS de impresión, o generar desde el markdown).

### D. Producción (grande, fuera de alcance hasta validar con clientes reales)
Auth real de cliente + share-link acotado a un `case_id`; scoping server-side "mis casos" por
identidad del asesor; Postgres multi-tenant; webfonts. Ver el roadmap de fases en la memoria
del proyecto y `docs/UX_REDESIGN_PLAN.md` (Fase UX-2/3, Fase producción).

## Convenciones que muerden (repetir de sesiones previas)
- Commits en español, mensaje vía archivo (`git commit -F <archivo>` en scratchpad) — el guard
  bloquea here-strings de PowerShell.
- No tocar `.gitignore` (cambio pre-existente del usuario sin commitear).
- Bilingüe: UI en español, identificadores en inglés. Docstrings en español.
- Verificar el frontend con el patrón Node (cargar los JS con stubs de window/document/
  escapeHTML + respuestas reales capturadas por curl) — el daemon de `browse` muere entre
  llamadas en este sandbox Windows (aguanta mejor varias screenshots dentro de UN bloque bash).
- Reuso: los builders `idemo*` (investor-demo.js) y `cw*` (case-workbench.js) son globales y
  DOM-guardeados; reusarlos por carga, NO duplicar ni tocar esos archivos.
- Invariantes de compliance en `docs/INVARIANTS.md` (I-001/I-013/I-017/I-021/I-023). El informe
  del asesor auditado ya respeta I-021 (cadena intacta) e I-023 (append-only).

## Verificación antes de cada commit
```powershell
node --check frontend/js/<archivo>.js         # cada JS tocado
python -m pytest -q                           # si tocaste Python (~2537 tests)
python scripts/run_case_workflow_smoke_check.py   # end-to-end, exit 0 = PASS
```
Frontend: curl de cada página (200) + harness Node con respuestas reales de la API.
