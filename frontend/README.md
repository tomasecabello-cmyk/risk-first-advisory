# Frontend — Risk-First Advisory

UI estática por roles para el backend FastAPI. **Sin build step, sin frameworks, sin
CDN, sin dependencias** — HTML + `css/base.css` + JS clásico (no ES modules, para
preservar los handlers `onclick="..."` globales).

## Mapa de páginas

| Página | Rol | Qué hace | Scripts (en orden) |
|---|---|---|---|
| `index.html` | Hub | Hero + 3 tarjetas de rol + "cómo funciona" + links a Metodología y Modo dev | — |
| `client.html` | Cliente | Wizard de 4 pasos (Tus datos / Cuestionario / Escenarios / Plata real) con barra de progreso; al enviar: prepara caso + KYC + análisis IA y muestra la primera lectura (Risk Number, capacidad, inconsistencias) | `common`, `case-workbench`, `investor-demo`, `client` |
| `advisor.html` | Asesor | Bandeja agrupada por cliente → revisión de respuestas crudas → aprueba/modifica/rechaza perfil → propuesta → selección → reporte → auditoría + **informe del asesor editable y auditado** (cada Guardar = evento `advisor_note` versionado, append-only) | `common`, `case-dashboard`, `case-workbench`, `investor-demo`, `advisor` |
| `compliance.html` | Compliance | Selector de caso + snapshot + verificación del hash chain + audit trail + AI logs (solo lectura; requiere rol compliance) | `common`, `case-dashboard`, `case-workbench`, `compliance` |
| `methodology.html` | — | Fundamento del Risk Gap y del Risk Number (fórmulas + comparación con Nitrogen) | — |
| `advanced.html` | Dev | Modo técnico crudo: Dashboard (CRUD de entidades) + Workbench (15 paneles) + JSON/endpoints. Linkeado solo desde el footer | `common`, `case-dashboard`, `case-workbench` |

## Cómo correr

Ver "Demo en 5 minutos" del `README.md` raíz. Resumen: `bootstrap_local_demo.py` →
`build_arg_universe.py --warm` → uvicorn en :8000 con `RFA_DEMO_MODE=1` y
`RFA_LIVE_DATA=1` → `python -m http.server 5500 -d frontend` → `http://127.0.0.1:5500`.

La base de la API está hardcodeada a `http://127.0.0.1:8000` en `js/common.js`.
Servir siempre por HTTP (no `file://`, lo bloquea CORS).

## Arquitectura del JS

```
js/
├── common.js         # helpers globales (escapeHTML, formatJSON, apiError, ...)
├── case-dashboard.js # CRUD de entidades + summary (prefijo cd*) — debe cargar antes que case-workbench
├── case-workbench.js # workflow case-scoped en 15 paneles (prefijo cw*; reusa helpers cd*)
├── investor-demo.js  # motor de la demo guiada (prefijo idemo*): builders de KYC, análisis, carteras, reporte
├── client.js         # wizard del cliente (reusa idemo*/cw* por carga)
├── advisor.js        # bandeja + revisión + decisión + informe auditado (reusa idemo*/cw*)
└── compliance.js     # snapshot/verify/audit/ai-logs (reusa cd*)
```

Reglas que muerden:

- **Los builders `idemo*` y `cw*` son la fuente de verdad compartida.** Los JS por
  rol (`client/advisor/compliance.js`) los reusan por carga; NO duplicar ni bifurcar
  esos builders. Todos son DOM-guardeados (no fallan si su card no está en la página).
- **Orden de carga**: `common` → `case-dashboard` → `case-workbench` → (`investor-demo`)
  → JS del rol.
- **Traspaso de estado entre páginas**: `window.idemoState` se pierde al navegar; el
  handoff cliente↔asesor va por la lista de casos persistida +
  `localStorage.rfaLastCaseId` (último caso creado por el cliente).
- **Bilingüe**: copy en español; identificadores técnicos (`case_id`, endpoints,
  roles, reason_codes, `DEFENSIVE`/`BALANCED`/`GROWTH`) en inglés.
- **Sin auth de cliente real**: `client.html` es un reencuadre de demo — usa el token
  de asesor por detrás. La auth real de cliente es Fase de producción
  (`docs/ROADMAP.md`).
- **Redacción de PII**: el frontend muestra `input_redacted` tal cual viene del
  backend y NO agrega lógica de redacción propia (única fuente de verdad: el repo
  SQLite). `raw_response` se muestra con warning.

## Tokens

| Token (fallback dev) | Rol | Alcanza para |
|---|---|---|
| `dev-advisor-token` | advisor | Todo el workflow (KYC → reporte) |
| `dev-compliance-token` | compliance | Audit verify + AI logs |

No hay `dev-admin-token` en el fallback: crear firms/advisors desde `advanced.html`
requiere un `config/advisor_tokens.yaml` propio con rol `admin`. El seed del
bootstrap no lo necesita.

## Verificación del frontend

- `node --check frontend/js/<archivo>.js` por cada JS tocado.
- curl de cada página (HTTP 200).
- Harness Node: cargar los JS con stubs de `window`/`document`/`escapeHTML` +
  respuestas reales de la API capturadas por curl (el daemon de browser headless
  muere entre llamadas en este sandbox Windows; si se usa, sacar varias screenshots
  dentro de UN solo bloque).

**No production-ready.** UI para demo local — no exponerla en red pública ni cargar
PII real.
