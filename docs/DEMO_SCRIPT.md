# Risk-First Advisory — MVP Demo Script

Guía de recorrido de demo de 5–7 minutos para mostrar el producto a un asesor financiero o potencial usuario.

Hay **tres caminos de demo**:

- **A. Demo visual completa (recomendada).** Bootstrap local + frontend con Case Dashboard + Case Workbench (15 paneles del flujo case-scoped). Es el camino que el dev/asesor/mentor debería ver primero. Ver sección "Camino A — Demo visual completa" abajo.
- **B. Smoke check backend end-to-end.** Ejecutable de consola que valida `firm → … → report → summary → audit verify`. Sin frontend, sin OpenAI real, sin uvicorn. Útil como "candado" de Fase 2 o como verificación rápida en CI. Ver "Camino B — Smoke check backend".
- **C. Seed-only / cards legacy.** Para demos rápidas de las cards Fase 0/1 (`/ai/profile-demo`, `/live/portfolio-demo`, etc.) o cuando solo se necesitan las entidades demo sin levantar el frontend. Ver "Camino C — Cards legacy / seed-only".

> **OPENAI_API_KEY**: NO es necesaria para los caminos A (Workbench), B (smoke), ni C (seed). Solo los endpoints `/ai/*` reales del Workbench (AI Profile Analysis, AI Investment Preferences NLP) y las cards AI legacy (Fase 0/1) la requieren. El smoke check y los tests usan mocks determinísticos.

---

## Objetivo de la demo

Mostrar cómo el sistema transforma KYC estructurado y preferencias en lenguaje natural en portfolios candidatos con trazabilidad completa — sin que la IA tome ninguna decisión de inversión.

El eje central:

> **La IA interpreta. El motor filtra. El optimizador calcula. El asesor decide.**

---

## Requisitos previos

| Requisito | Comando / verificación |
|---|---|
| Python virtualenv activado | `.\.venv\Scripts\Activate.ps1` |
| Backend FastAPI corriendo con API key | Ver comandos de inicio más abajo |
| Frontend servido localmente | `python -m http.server 5500 -d frontend` |
| Smoke check offline | `python scripts/run_mvp_smoke_check.py` |

> El smoke check **no** requiere OpenAI ni internet. Los pasos del frontend **sí** requieren OPENAI_API_KEY para los demos de IA.

---

## Camino A — Demo visual completa (recomendada)

**Esta es la guía principal: bootstrap + backend + frontend + Workbench.**

### Pre-step — bootstrap (1 comando)

```powershell
cd C:\Users\maria\risk-first-advisory
.\.venv\Scripts\Activate.ps1
python scripts/bootstrap_local_demo.py
```

Hace migrate + seed + valida los archivos del frontend + detecta config (tokens YAML, OPENAI_API_KEY) e imprime los comandos exactos de los pasos siguientes + tokens recomendados. Idempotente. Output al final:

```
PASS — local demo environment is ready
```

Crea `firm_demo_local`, `advisor_demo_local`, `client_demo_local`, `case_demo_local` listos para abrir en el Workbench.

### Terminal 1 — Backend

```powershell
cd C:\Users\maria\risk-first-advisory
.\.venv\Scripts\Activate.ps1
python -m uvicorn risk_first_advisory.api_layer.main:app --reload
```

Opcional, solo si vas a usar las cards `/ai/*` legacy (Fase 0/1) o el panel "AI Profile Analysis" del Workbench contra OpenAI real:

```powershell
$env:OPENAI_API_KEY="sk-..."
```

El backend queda en `http://127.0.0.1:8000`. Swagger UI: `http://127.0.0.1:8000/docs`.

### Terminal 2 — Frontend

```powershell
cd C:\Users\maria\risk-first-advisory
.\.venv\Scripts\Activate.ps1
python -m http.server 5500 -d frontend
```

Abrir en el navegador: **`http://127.0.0.1:5500`**

### En el navegador

- En la card **"Case Dashboard — Phase 2"** escribir `case_demo_local` en "Selected case_id" (sección 7) y clic en **"Load Summary"** para abrir el case que dejó el seed.
- En la card **"Case Workbench — Phase 2 Workflow"** escribir el mismo `case_demo_local` en la sección 1 y clic en **"Load Summary"** o **"Use selected case from Dashboard"**. Recorrer los pasos 2–10 (KYC → AI analysis → approval → preferences → universe filter → portfolio proposal → override → selection → report). Para los paneles 12–14 (audit trail / verify / AI logs / compliance snapshot) cambiar el token a `dev-compliance-token` en el input del Dashboard.

### Si OPENAI_API_KEY no está configurada

El paso "AI Profile Analysis" del Workbench (sección 3) fallará con HTTP 400 al hacer POST. **Alternativas**:

- Usar el camino B (smoke check) para validar el flujo end-to-end con OpenAI mockeado (no requiere API key).
- Configurar `OPENAI_API_KEY` y reiniciar el backend.

El resto del Workbench (KYC, profile approval, preferences manual, universe filter, portfolio proposal, override, selection, report, audit, AI logs) funciona sin OPENAI_API_KEY.

---

## Camino B — Smoke check backend

Validar el flujo case-scoped completo sin frontend, sin OpenAI, sin uvicorn corriendo:

```powershell
cd C:\Users\maria\risk-first-advisory
.\.venv\Scripts\Activate.ps1
python scripts/run_case_workflow_smoke_check.py
```

Corre 14 pasos sobre una DB SQLite temporal: migrate → seed entities → KYC → AI analysis (mockeado) → approval → preferences → filter → proposal → override → selection → report → summary → audit verify. Exit 0 = PASS. Detalle de cada paso en sección "Case-scoped backend workflow smoke check (Fase 2)" más abajo.

Útil como "candado" de Fase 2 antes de cualquier release o como verificación rápida cuando algo del frontend no responde.

---

## Camino C — Cards legacy / seed-only

### Solo cards legacy (Fase 0/1)

Si solo querés mostrar las cards `/ai/profile-demo`, `/live/portfolio-demo`, `/ai/filtered-portfolio-demo`, etc., el bootstrap del camino A es opcional. Alcanza con backend + frontend:

```powershell
# Terminal 1
python -m uvicorn risk_first_advisory.api_layer.main:app --reload

# Terminal 2
python -m http.server 5500 -d frontend
```

### Solo seed (sin chequeos del entorno)

Si ya corriste el bootstrap antes y solo querés re-asegurar las entidades demo:

```powershell
python scripts/seed_demo_data.py
```

Idempotente: las 4 entidades se reusan si ya existen.

### Verificación offline del MVP legacy

El smoke check legacy (anterior a Fase 2) valida el pipeline de portfolios sin frontend ni OpenAI ni internet:

```powershell
python scripts/run_mvp_smoke_check.py
```

Output esperado: `PASS — MVP smoke check completed successfully`.

---

## Demo flow principal

### Paso 1 — Health check *(~15 segundos)*

**Sección:** API Health

1. Presionar el botón **"Check API"**.
2. Mensaje esperado:

```json
{"status": "ok", "service": "risk-first-advisory"}
```

**Punto clave:** el backend FastAPI está corriendo. Todos los endpoints están disponibles.

---

### Paso 2 — AI Profile Demo *(~60 segundos)*

**Sección:** AI Profile Demo — `POST /ai/profile-demo`

1. Usar los **valores por defecto del formulario** (KYC contradictorio intencionado):
   - `risk_tolerance_score = 4` (bajo)
   - `risk_capacity_score = 8` (alto)
   - `liquidity_need_score = 7` (alta liquidez)
   - `investment_horizon_years = 15`
   - `max_acceptable_drawdown_pct = 10`
   - Textos abiertos: preocupación por caídas, vendió en baja anterior

2. Presionar **"Analyze KYC with AI"** y esperar la respuesta de OpenAI.

3. Mostrar:
   - **`preliminary_profile`** — perfil propuesto por la IA (ej. `conservador` o `moderado-defensivo`)
   - **`confidence`** — barra de confianza; si hay contradicciones será baja
   - **`contradictions`** — cards por campo con severidad alta/media/baja (ej. "risk_tolerance bajo pero risk_capacity alto")
   - **`follow_up_questions`** — preguntas específicas que la IA propone para resolver las contradicciones
   - **`advisor_notes`** — observaciones para el asesor

**Punto clave:** la IA detecta las tensiones del KYC y pide más información antes de proponer un perfil con alta confianza. **No decide — propone.**

---

### Paso 3 — AI Profile Follow-up *(~45 segundos)*

**Sección:** Answer Follow-up Questions (aparece automáticamente si hay preguntas)

1. Responder cada pregunta en los textareas. Ejemplos de respuestas que llevan a mayor confianza o perfil más agresivo:
   - "En realidad tengo un fondo de emergencia separado y puedo mantener la inversión los 15 años sin tocarla."
   - "El 8 de capacidad refleja mi situación patrimonial real, aunque reaccioné mal en el pasado."

2. Presionar **"Submit Follow-up Answers"**.

3. Mostrar:
   - **`revised_profile`** — perfil revisado tras las respuestas (puede subir a `moderado` o `moderado-agresivo`)
   - **`confidence`** actualizada — debería ser más alta
   - **`profile_change_reason`** — razonamiento de la IA para el cambio
   - **`remaining_contradictions`** — las que no se resolvieron (vacío = todas resueltas)

**Punto clave:** el proceso es iterativo. La IA refina su propuesta con información adicional del cliente. El asesor sigue teniendo la decisión final sobre el perfil aprobado.

---

### Paso 4 — AI Universe Filter Demo *(~45 segundos)*

**Sección:** AI Universe Filter Demo — `POST /ai/filter-universe-demo`

1. Usar los valores por defecto:
   - `client_id`: `CLI-PREF-001`
   - `natural_language_preferences`:
     ```
     Solo quiero invertir en ONs hard dollar argentinas disponibles en Balanz y evitar energia.
     ```

2. Presionar **"Filter Universe with AI"**.

3. Mostrar:
   - **Preferences Detected by AI:**
     - `allowed_instrument_types: [CORPORATE_BOND]`
     - `currency: USD`
     - `country: Argentina`
     - `entity: Balanz`
     - `hard_dollar_only: true`
     - `avoid_sectors: [Energy]`
   - **Filtros aplicados** — chips con cada criterio activo
   - **Eligible Instruments** — tabla verde con los instrumentos que pasan todos los filtros (ej. GALI28, MACR29, PAMP27, etc.)
   - **Excluded Instruments** — tabla roja con razón de exclusión por ticker (ej. `instrument_type_not_allowed:ETF`, `sector_avoided:Energy`, `not_available_at_entity:Balanz`)

**Punto clave:** la IA no filtra — solo convierte el texto en un dict estructurado. El filtro es **100% determinístico**: mismas preferencias → mismo resultado siempre. Cada exclusión tiene razón auditable.

---

### Paso 5 — AI Filtered Portfolio Demo *(~60 segundos)*

**Sección:** AI Filtered Portfolio Demo — `POST /ai/filtered-portfolio-demo`

1. Usar:
   - `client_id`: `CLI-PREF-PORT-001`
   - `profile`: `moderado`
   - `natural_language_preferences`:
     ```
     Solo quiero invertir en ONs hard dollar argentinas disponibles en Balanz y evitar energia.
     ```

2. Presionar **"Generate AI Filtered Portfolio"**.

3. Mostrar el resumen:

   | Campo | Valor esperado |
   |---|---|
   | `status` | `completed` |
   | `eligible_count` | 9 |
   | `excluded_count` | 11 |
   | `snapshot_count` | 9 |
   | `candidate_count` | 2 |

4. Mostrar **Preferences Detected** — mismas que en el paso anterior, generadas en tiempo real por OpenAI.

5. Mostrar **Market Data Snapshots** — tabla con `expected_return_annual`, `volatility_annual`, `duration`, `liquidity_score` por ticker. Estos datos son proxy derivados del YTM y cupón del CSV.

6. Mostrar **Candidate Portfolios:**
   - **BALANCED** — respeta estrictamente el `RiskBudget` del perfil `moderado`. Retorno ~8.6%, volatilidad ~9.9%, 7 activos.
   - **GROWTH** — maximiza retorno. Excede `max_volatility`. Ver siguiente paso.

7. Bajar hasta la sección **"Markdown Report (for advisor review)"** y mostrar:
   - El reporte Markdown auditable generado por el backend en el campo `report_markdown`.
   - Botón **"Copy Markdown Report"** — al hacer clic copia el reporte al portapapeles y muestra `"✓ Markdown report copied to clipboard."`.
   - El reporte tiene 10 secciones fijas: Executive Summary, Natural Language Preferences, AI Extracted Preferences, Applied Universe Filters, Eligible Instruments, Exclusions, Portfolio-Ready Snapshots, Candidate Portfolios, Advisor Override y Limitations & Disclaimers.
   - En el bloque de **summary** señalar los IDs persistidos:
     - `record_id` — ej. `ai_filtered_portfolio_000001`
     - `report_record_id` — ej. `report_000001`
   - Mensaje al asesor: *"Este reporte queda en SQLite junto con el payload completo. Cualquier revisión posterior puede recuperarlo por `record_id` sin reejecutar OpenAI."*

---

### Paso 6 — Explicar el GROWTH override *(~30 segundos)*

En la card de GROWTH:

1. Señalar el **banner amarillo "⚠ Advisor Override Required"**.
2. Mostrar los campos:
   - `risk_budget_exceeded: true`
   - `requires_advisor_override: true`
   - `exceeded_constraints: [max_volatility]`
   - `reason_codes: [PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET]`

**Mensaje clave para el asesor:**

> GROWTH puede exceder el `max_volatility` del perfil aprobado como alternativa de mayor retorno. El sistema **no la oculta ni la bloquea** — la marca explícitamente para que el asesor pueda evaluarla y decidir si la presenta al cliente. Si decide presentarla, esa decisión queda documentada en el audit trail.
>
> BALANCED es siempre la recomendación base dentro del perfil aprobado.

---

### Paso 7 — Actos formales del asesor *(~90 segundos)*

**Sección:** Advisor Decisions Demo — Phase 1 (debajo del AI Filtered Portfolio Demo)

> ⚠ **Auth scaffold development-only.** Los tokens son hard-coded (`dev-advisor-token`, `dev-compliance-token`). No es identity provider productivo. No reemplaza firma digital ni compliance.

1. **Verificar auth.** Botón **"Check Advisor Auth"** con el token por defecto `dev-advisor-token` → muestra `advisor_id=ADV-001`, `display_name=Demo Advisor`, `roles=[advisor]`.

2. **Profile approval.** Form con valores por defecto:
   - `client_id=CLI-PREF-PORT-001`
   - `proposed_profile=moderado`, `decision=approve`
   - Botón **"Submit Profile Approval"** → muestra `record_id=advisor_profile_approval_NNNNNN`, decisión, perfil aprobado y `created_at_utc`.

3. **Override approval** (típico para GROWTH).
   - Botón **"Use last AIFP"** en `related_record_id` → copia el `record_id` del paso 5 (AI Filtered Portfolio).
   - `candidate_variant=GROWTH`, `decision=approve`, `reason_codes=PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET`, `exceeded_constraints=max_volatility`.
   - Botón **"Submit Override Approval"** → muestra `record_id=advisor_override_approval_NNNNNN`. Este ID se guarda en JS global.

4. **Portfolio selection.**
   - Botón **"Use last AIFP"** en `related_record_id`.
   - Botón **"Use last override"** en `override_approval_record_id` → trae el override aprobado en el paso anterior.
   - `selected_variant=BALANCED` (recomendación base) o `GROWTH` (alternativa con override).
   - Botón **"Submit Portfolio Selection"** → muestra `record_id=advisor_portfolio_selection_NNNNNN`, `warnings=[]` (no warnings si GROWTH viene con override link), `status=recorded`.
   - Si se selecciona `GROWTH` SIN override link, la response devuelve el chip de warning amarillo `"GROWTH selected without linked override approval record."` — útil para mostrar al asesor que ese paso queda pendiente de auditoría.

**Punto clave:** ningún acto del asesor pasa por la IA. Cada decisión (aprobación de perfil, aprobación de override, selección final) queda en SQLite con `record_id` propio, `advisor_id` resuelto desde el Bearer token, `rationale` obligatorio y `created_at_utc` para audit posterior.

---

### Paso 8 — Smoke check offline *(~15 segundos)*

**En la terminal (sin detener el backend):**

```powershell
python scripts/run_mvp_smoke_check.py
```

Output esperado:

```
============================================================
  RISK-FIRST ADVISORY — MVP Smoke Check
  ...
============================================================
  PASS — MVP smoke check completed successfully
============================================================
```

**Punto clave:** este recorrido completo — universo → filtro → snapshots → risk budget → portfolios — **funciona sin OpenAI, sin internet, sin backend**. Es reproducible, determinístico y verificable en cualquier entorno.

---

## Mensaje comercial

Este sistema **no es un robo-advisor autónomo**. Es un **copiloto para asesores financieros**:

| Componente | Rol |
|---|---|
| **OpenAI** | Interpreta el lenguaje del cliente y estructura sus preferencias en un formato que el motor entiende. No filtra instrumentos. No calcula pesos. No decide nada. |
| **PreferenceFilterEngine** | Aplica las preferencias estructuradas al universo de instrumentos de forma determinística y auditable. Cada exclusión tiene razón explícita. |
| **PortfolioGenerationCoordinator** | Genera variantes de cartera respetando el RiskBudget del perfil aprobado. No relaja restricciones automáticamente. |
| **Asesor** | Aprueba el perfil. Revisa las carteras. Decide si presentar GROWTH al cliente. Firma el override si corresponde. **La IA nunca reemplaza este paso.** |

El sistema garantiza trazabilidad en cada punto: qué datos ingresaron, qué decidió la IA, qué filtró el motor, qué generó el optimizador, y qué aprobó el asesor.

---

## Limitaciones actuales del MVP

| Limitación | Impacto | Estado |
|---|---|---|
| Universo CSV de 20 instrumentos de muestra | No representa el universo real de ONs y bonos disponibles | Demo / pendiente |
| Datos de mercado proxy (YTM/cupón estático) | Los retornos y volatilidades son estimaciones de demo, no precios reales | Demo / pendiente |
| OpenAI no determinístico | El mismo texto puede producir preferencias ligeramente distintas en distintas llamadas | Aceptable en demo |
| ~~Sin persistencia del flujo filtrado~~ | ✅ **Cerrado en Fase 0.** Cada respuesta de `/ai/filtered-portfolio-demo` se persiste en SQLite con `record_id` (payload completo) y `report_record_id` (Markdown report). | Cerrado |
| Sin reporte comercial para el cliente | El `report_markdown` es para revisión del asesor; no es un documento de presentación al cliente. No hay PDF ni firma digital. | Pendiente |
| Sin datos de Bloomberg / proveedor real | Los datos de mercado de producción no están conectados | Out of scope MVP |
| Auth development-only (Fase 1) | Bearer token hard-coded (`dev-advisor-token`, `dev-compliance-token`). Los tres endpoints `/advisor/*` y `/auth/me` requieren token. El resto sigue sin auth. No es producción. | Fase 1 scaffold ✅ — auth productiva pendiente |

---

## Próximos pasos sugeridos

1. ~~**Reporte del AI Filtered Portfolio**~~ — ✅ Cerrado en Fase 0. `report_markdown` se genera con `AIFilteredPortfolioReportGenerator` y se persiste en SQLite (`report_record_id`).

2. ~~**Persistencia y audit trail del flujo filtrado**~~ — ✅ Cerrado en Fase 0. La respuesta completa se persiste como record `ai_filtered_portfolio` (`record_id`).

3. **Carga de universo real** — reemplazar el CSV de demo por un universo actualizado de ONs, bonos soberanos y ETFs con datos de mercado reales.

4. **Auth para producción** — reemplazar el Bearer token hard-coded de Fase 1 (dev-only) por JWT firmado por IdP con RBAC por rol, TTL y multi-tenant. Proteger todos los endpoints antes de cualquier exposición en red no local.

5. ~~**Firma/approval del advisor override**~~ — ✅ Cerrado en Fase 1. `POST /advisor/override-approval` persiste la aprobación del asesor con rationale, reason_codes y exceeded_constraints como `advisor_override_approval_NNNNNN` en SQLite.

6. ~~**Selección de variante**~~ — ✅ Cerrado en Fase 1. `POST /advisor/portfolio-selection` registra la variante final (DEFENSIVE/BALANCED/GROWTH) con rationale y enlaces a records de portfolio y override, como `advisor_portfolio_selection_NNNNNN` en SQLite.

---

## Referencia rápida

| Demo | Endpoint | Requiere OpenAI | Requiere Bearer token |
|---|---|---|---|
| Health check | `GET /health` | No | No |
| AI Profile Demo | `POST /ai/profile-demo` | Sí | No |
| AI Profile Follow-up | `POST /ai/profile-follow-up` | Sí | No |
| AI Universe Filter | `POST /ai/filter-universe-demo` | Sí | No |
| AI Filtered Portfolio | `POST /ai/filtered-portfolio-demo` | Sí | No |
| **Advisor auth check** | `GET /auth/me` | No | **Sí** |
| **Advisor profile approval** | `POST /advisor/profile-approval` | No | **Sí** |
| **Advisor override approval** | `POST /advisor/override-approval` | No | **Sí** |
| **Advisor portfolio selection** | `POST /advisor/portfolio-selection` | No | **Sí** |
| MVP smoke check offline | `python scripts/run_mvp_smoke_check.py` | No | No |
| **Case workflow smoke check (Fase 2)** | `python scripts/run_case_workflow_smoke_check.py` | No (mockeado) | No (sin uvicorn) |

---

## Case-scoped backend workflow smoke check (Fase 2)

Si la audiencia es técnica y querés mostrar el flujo case-scoped end-to-end **sin frontend** (la UI Case Workbench es el próximo entregable de Fase 3), correr:

```powershell
python scripts/run_case_workflow_smoke_check.py
```

### Qué hace

Aplica todas las migrations sobre una DB SQLite temporal, monkeypatchea `OpenAIProfileClient` con un mock determinístico, usa FastAPI TestClient (sin uvicorn) y ejercita el flujo completo en 14 pasos:

1. Migrate database (`0001..0009`).
2. Install stubs (DB path + tokens YAML + OpenAI mock).
3. Crear firm + advisor + client + case.
4. POST KYC submission.
5. POST AI profile analysis (mockeado → "moderado").
6. POST profile approval (decision=approve).
7. POST investment preferences (structured manual).
8. POST universe filter.
9. POST portfolio proposal.
10. POST override approval (si algún variant lo requiere).
11. POST portfolio selection (transiciona case a `PORTFOLIO_SELECTED`).
12. POST case report (markdown determinístico).
13. GET case summary (valida `completion_ratio=1.0` + `next_action=ready_for_review`).
14. GET audit/verify (valida `is_intact=true`).

Output esperado al final:

```
PASS — case workflow smoke check completed
    case_id          : case_000001
    report_id        : case_report_000001
    audit intact     : True
    completion ratio : 1.0
    next action      : ready_for_review
```

### Lo que este smoke check NO hace

- **No reemplaza la UI Case Workbench** — la complementa: el smoke check valida que el backend funciona end-to-end; el Workbench (ya disponible) permite recorrer visualmente el mismo flujo + audit / AI logs sobre cualquier `case_id` existente.
- **No requiere OpenAI real ni internet.** El cliente OpenAI está stubeado con un fake determinístico.
- **No requiere uvicorn corriendo.** Usa `fastapi.testclient.TestClient` para invocar la app directamente.
- **No toca la DB dev** (`data/demo_api.db`). Usa una DB temporal (override con `--db-path`).
- **No valida el frontend.** Solo el backend + workflow.
- **No es production smoke** — corre en proceso local, no contra un deploy.

### Opciones útiles

```powershell
# Preservar la DB temporal para inspección manual:
python scripts/run_case_workflow_smoke_check.py --keep-db

# Especificar DB en un path concreto:
python scripts/run_case_workflow_smoke_check.py --db-path data/smoke_inspection.db

# Traceback completo si algo falla:
python scripts/run_case_workflow_smoke_check.py --debug
```

Exit code: `0` si pasa, `1` si al menos una aserción falla.
