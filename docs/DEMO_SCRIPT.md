# Risk-First Advisory — MVP Demo Script

Guía de recorrido de demo de 5–7 minutos para mostrar el producto a un asesor financiero o potencial usuario.

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

## Inicio rápido

### Terminal 1 — Backend con IA

```powershell
cd C:\Users\maria\risk-first-advisory
.\.venv\Scripts\Activate.ps1
$env:OPENAI_API_KEY="your_key_here"
uvicorn risk_first_advisory.api_layer.main:app --reload
```

El backend queda disponible en `http://127.0.0.1:8000`.
Swagger UI: `http://127.0.0.1:8000/docs`

### Terminal 2 — Frontend

```powershell
python -m http.server 5500 -d frontend
```

Abrir en el navegador: **`http://127.0.0.1:5500`**

### Verificación offline (sin API key, sin internet)

```powershell
python scripts/run_mvp_smoke_check.py
```

Output esperado:

```
PASS — MVP smoke check completed successfully
```

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
| Sin autenticación | El frontend y la API son acceso libre (solo para desarrollo local) | Pendiente (pre-producción) |

---

## Próximos pasos sugeridos

1. ~~**Reporte del AI Filtered Portfolio**~~ — ✅ Cerrado en Fase 0. `report_markdown` se genera con `AIFilteredPortfolioReportGenerator` y se persiste en SQLite (`report_record_id`).

2. ~~**Persistencia y audit trail del flujo filtrado**~~ — ✅ Cerrado en Fase 0. La respuesta completa se persiste como record `ai_filtered_portfolio` (`record_id`).

3. **Carga de universo real** — reemplazar el CSV de demo por un universo actualizado de ONs, bonos soberanos y ETFs con datos de mercado reales.

4. **Auth básica** — API key o JWT para todos los endpoints antes de cualquier exposición en red no local.

5. **Firma/approval del advisor override** — endpoint o UI donde el asesor confirme explícitamente la aceptación de GROWTH fuera del budget, con registro en audit trail.

6. **Selección de variante** — endpoint donde el asesor seleccione qué variante (DEFENSIVE/BALANCED/GROWTH) presentar al cliente, con registro en audit trail.

---

## Referencia rápida

| Demo | Endpoint | Requiere OpenAI |
|---|---|---|
| Health check | `GET /health` | No |
| AI Profile Demo | `POST /ai/profile-demo` | Sí |
| AI Profile Follow-up | `POST /ai/profile-follow-up` | Sí |
| AI Universe Filter | `POST /ai/filter-universe-demo` | Sí |
| AI Filtered Portfolio | `POST /ai/filtered-portfolio-demo` | Sí |
| Smoke check offline | `python scripts/run_mvp_smoke_check.py` | No |
