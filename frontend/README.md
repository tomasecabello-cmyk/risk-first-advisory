# Frontend — Risk-First Advisory Dev UI

Página HTML estática para probar visualmente el backend sin usar terminal ni curl.

Un solo archivo: `index.html`. Sin frameworks. Sin CDN. Sin dependencias.

---

## Requisitos

El backend FastAPI debe estar corriendo localmente. Sin él, el frontend no puede hacer ninguna request.

---

## Cómo iniciar el backend

Desde el directorio raíz del proyecto, con el virtualenv activado:

```powershell
cd C:\Users\maria\risk-first-advisory
.\.venv\Scripts\Activate.ps1
uvicorn risk_first_advisory.api_layer.main:app --reload
```

El backend queda disponible en:

```
http://127.0.0.1:8000
```

Documentación interactiva del backend:
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

---

## Cómo abrir el frontend

### Opción A — Directo desde el navegador (puede fallar por CORS)

Abrir el archivo directamente:

```
frontend/index.html
```

O hacer doble clic en el explorador de archivos.

**Limitación:** algunos navegadores bloquean requests `fetch()` cuando la página se sirve desde `file://` (política CORS de origen cruzado entre `file://` y `http://`). Si las requests fallan con error de CORS, usar la Opción B.

### Opción B — Servidor HTTP local (recomendado)

Servir el frontend con Python desde el directorio raíz del proyecto:

```powershell
python -m http.server 5500 -d frontend
```

Luego abrir en el navegador:

```
http://127.0.0.1:5500
```

Esta opción evita los problemas de CORS porque la página se sirve desde `http://` y hace requests a `http://`, sin cruce de esquemas.

---

## Endpoints que consume

| Sección | Método | Ruta | Descripción |
|---|---|---|---|
| API Health | `GET` | `/health` | Verifica que el backend responde |
| Scripted Workflow Demo | `POST` | `/workflow/run` | **Scripted deterministic demo.** Usa MockAIClient + ScriptedAdvisorInterface. No llama OpenAI ni involucra a un asesor real. Sirve para validar pipeline, persistencia, audit y reporte. |
| Live Portfolio Demo | `POST` | `/live/portfolio-demo` | Portfolios reales con datos de yfinance |
| AI Profile Demo | `POST` | `/ai/profile-demo` | Análisis KYC con OpenAI (requiere API key) |
| AI Profile Follow-up | `POST` | `/ai/profile-follow-up` | Segunda ronda de análisis con respuestas del cliente |
| AI Universe Filter Demo | `POST` | `/ai/filter-universe-demo` | Lenguaje natural → OpenAI → filtro de universo (requiere API key) |
| AI Filtered Portfolio Demo | `POST` | `/ai/filtered-portfolio-demo` | Lenguaje natural → OpenAI → filtro → snapshots → portfolios candidatos (requiere API key) |
| Persisted Workflows | `GET` | `/workflow` | Lista todos los workflows |
| Persisted Workflows | `GET` | `/workflow?client_id=...` | Filtra workflows por cliente |

---

## Secciones del formulario

### API Health
Botón "Check API" — llama `GET /health` y muestra la respuesta. Útil para verificar que el backend está corriendo antes de ejecutar el workflow.

### Scripted Workflow Demo

> **Endpoint scripted determinístico.** Usa `MockAIClient` (perfil preprogramado `moderado`, sin contradicciones, sin follow-up) y `ScriptedAdvisorInterface` (aprobación automática). **No llama OpenAI** y **no involucra a un asesor humano real**. Pensado para validar el pipeline determinístico — governance → suitability → ESG → data quality → optimizer — junto con persistencia en SQLite, audit trail y reporte Markdown. No usar como flujo productivo de asesoría real. Los demos de IA real son `/ai/profile-demo`, `/ai/profile-follow-up`, `/ai/filter-universe-demo` y `/ai/filtered-portfolio-demo`.

Formulario con todos los campos de `KYCData` y `FinancialGoal`. Valores por defecto razonables para un perfil moderado. Campos opcionales pueden dejarse en blanco.

Al ejecutar:
- Muestra un resumen estructurado: status, perfil aprobado, portfolios generados, tickers, reason codes, warnings, IDs persistidos.
- La respuesta JSON incluye los campos `execution_mode="scripted_demo"`, `ai_source="mock_scripted"`, `advisor_source="scripted_auto_approve"`, `is_production_ready=false` y `warning` declarando explícitamente la naturaleza scripted del endpoint.
- La lista `warnings` siempre incluye el aviso scripted además de los warnings naturales del workflow.
- Muestra el JSON completo de la respuesta en un bloque colapsable.

### Live Portfolio Demo
Descarga datos históricos reales de ETFs vía **yfinance** y genera hasta 3 portfolios candidatos (DEFENSIVE / BALANCED / GROWTH) para el perfil seleccionado.

Selectores:
- **profile** — perfil de riesgo aprobado (conservador → agresivo)
- **period** — período histórico de descarga (1y / 2y / 3y / 5y)
- **interval** — frecuencia de datos (1d daily / 1wk weekly)

Al ejecutar:
- Muestra un summary: status, tickers usables/fallidos, DQ warnings.
- Por cada variante generada: retorno esperado, volatilidad, risk score, barra de pesos, metadata de risk budget.
- Si GROWTH requiere advisor override (siempre relaja `max_volatility`), se muestra un banner de advertencia con los constraints excedidos.
- Si `status=insufficient_data` o `status=infeasible`, se muestra el mensaje de error en lugar de portfolios.
- Muestra el JSON completo colapsable.

**Notas importantes:**
- Usa datos **gratuitos de Yahoo Finance** vía yfinance. No es una fuente de producción.
- La descarga puede tardar **5–15 segundos** según la velocidad de conexión.
- **Requiere conexión a internet.** Sin ella, todos los snapshots fallan y el status será `insufficient_data`.
- **No persiste resultados** en SQLite ni genera reporte Markdown.
- **No usa IA** ni KYC del cliente. El perfil se selecciona directamente.
- Los parámetros del Risk Budget (volatilidades, límites de asset class) se toman directamente de `PROFILE_BASE_PARAMS` sin ajustes de KYC.
- El universo fijo es 11 ETFs: BIL, SHV, AGG, BND, IEF, VTI, SPY, VEA, VWO, HYG, GLD.

### AI Profile Demo

Llama a `POST /ai/profile-demo` usando el **OpenAIProfileClient** del backend.

**Requiere OPENAI_API_KEY** en la terminal donde corre uvicorn. Sin la key, el endpoint devuelve HTTP 400 y el frontend muestra el mensaje de error con el comando de inicio correcto.

Para iniciar el backend con la key:

**PowerShell:**
```powershell
$env:OPENAI_API_KEY="your_key_here"
uvicorn risk_first_advisory.api_layer.main:app --reload
```

> ⚠ No subir la key a Git. No crear `.env`. No hardcodear secretos.

Si la key no está configurada, el frontend muestra:
> "OPENAI_API_KEY is not configured in the backend terminal."

Si el endpoint devuelve 502, el frontend muestra:
> "AI profile analysis failed. Check backend logs or API key."

**Características de esta demo:**
- Usa `OpenAIProfileClient` con modelo `gpt-4o-mini`, `temperature=0.2`.
- Analiza coherencia del KYC y detecta contradicciones entre campos.
- Devuelve: `preliminary_profile`, `confidence`, `contradictions`, `follow_up_questions`, `advisor_notes`.
- **No persiste** resultados en SQLite ni genera reporte Markdown.
- **No aprueba** el perfil final — solo el asesor humano puede hacerlo.
- **No genera** portfolios ni asset allocations.
- **No recomienda** productos, tickers ni ETFs.
- **No usa** `declared_return_expectation_pct` para construir el perfil (es información para el asesor, no para la IA).

Los valores por defecto del formulario corresponden al test manual con KYC contradictorio:
- `risk_tolerance_score=4` (bajo) pero `risk_capacity_score=8` (alto) → contradicción intencionada.
- `liquidity_need_score=7` (alta liquidez) con horizonte de 15 años → tensión detectada por la IA.

**Copiar perfil al Live Portfolio Demo:**
El resultado incluye el botón "↓ Use this profile in Live Portfolio Demo". Al hacer click:
- Copia `preliminary_profile` al selector de la sección Live Portfolio Demo.
- Hace scroll suave hacia esa sección.
- No ejecuta el portfolio automáticamente — el asesor decide cuándo presionar "Run Live Portfolio".
- Si el perfil sugerido no existe como opción, muestra un error claro sin romper la página.
- **No implica aprobación.** Es solo un helper de navegación para el asesor.

**Flujo de dos rondas — Follow-up:**

Si la IA detecta contradicciones o incertidumbre, devuelve `follow_up_questions` (lista no vacía). En ese caso el frontend muestra automáticamente un formulario de respuestas:

1. **Ronda 1 — Análisis KYC inicial** (`POST /ai/profile-demo`):
   - Completa el formulario KYC y presiona "Analyze with AI".
   - El resultado muestra: `preliminary_profile`, `confidence`, `contradictions`, `follow_up_questions`, `advisor_notes`.
   - Si hay follow-up questions, aparece el formulario de respuestas debajo.

2. **Ronda 2 — Follow-up** (`POST /ai/profile-follow-up`):
   - Escribe una respuesta en cada textarea (todas son obligatorias).
   - Presiona "Submit Follow-up Answers".
   - El spinner "Calling OpenAI follow-up analysis…" aparece mientras espera.
   - El resultado se muestra en un bloque verde (borde `#86efac`) debajo del primer resultado:
     - `revised_profile` — perfil revisado (pill verde).
     - `confidence` — barra de confianza actualizada.
     - `profile_change_reason` — caja verde con el razonamiento de la revisión.
     - `remaining_contradictions` — cards de severidad con las contradicciones no resueltas (vacío = todas resueltas).
     - `advisor_notes` — notas finales para el asesor (lista numerada).
     - Botón "↓ Use revised profile in Live Portfolio Demo" — copia `revised_profile` al selector.

3. **Ejecutar un nuevo análisis KYC** limpia el resultado de follow-up y reinicia el estado global.

**Manejo de errores del follow-up:**
- HTTP 400 → OPENAI_API_KEY no configurado (mismo mensaje que ronda 1).
- HTTP 502 → Fallo en el análisis (logs del backend / API key).
- HTTP 422 → Errores de validación Pydantic (detalle expandido).
- Error de red → Mensaje con instrucciones de uvicorn.

### AI Universe Filter Demo

Llama a `POST /ai/filter-universe-demo` — pipeline combinado de dos pasos:

1. **Paso 1 — Extracción de preferencias (OpenAI):** el texto libre del cliente se envía a `OpenAIProfileClient.extract_investment_preferences()`. La IA devuelve un JSON estructurado con tipos de instrumento permitidos/excluidos, moneda, país, entidad, sectores a evitar, hard dollar, etc.

2. **Paso 2 — Filtro determinístico (universe_layer):** las preferencias extraídas se aplican sobre `tests/fixtures/universe/sample_instrument_universe.csv` usando `PreferenceFilterEngine`. El resultado indica qué instrumentos pasan todos los filtros activos y cuáles son excluidos, con razones por ticker.

**Requiere OPENAI_API_KEY** en la terminal donde corre uvicorn. Sin la key, el endpoint devuelve HTTP 400 y el frontend muestra el mensaje de error con el comando de inicio correcto.

**Características:**
- Muestra preferencias estructuradas detectadas por la IA: `allowed_instrument_types`, `excluded_instrument_types`, `currency`, `country`, `entity`, `hard_dollar_only`, `avoid_sectors`, `prefer_sectors`, `avoid_issuers`, `prefer_issuers`, `min_liquidity_score`, `max_maturity_year`, `hard_constraints`, `soft_preferences`, `unparsed_preferences`, `advisor_notes`, `confidence`.
- Tabla de **instrumentos elegibles** con acento visual verde: ticker, name, issuer, type, asset class, currency, country, sector, hard dollar, maturity, YTM, duration, liquidity score, rating.
- Tabla de **instrumentos excluidos** con acento visual rojo: ticker + chips con las razones de exclusión (`not_available_at_entity:X`, `instrument_type_not_allowed:X`, `sector_avoided:X`, etc.).
- Lista de **filtros aplicados** como chips.
- Lista de **warnings** (prefer_* hints, claves desconocidas, fechas de vencimiento faltantes).
- JSON completo colapsable.

**Limitaciones / notas:**
- **No genera portfolios.** No calcula pesos ni retornos esperados.
- **No trae datos de mercado.** No llama a yfinance ni Bloomberg.
- **No persiste resultados** en SQLite ni genera reporte Markdown.
- **Universo fijo:** `tests/fixtures/universe/sample_instrument_universe.csv` — 20 instrumentos de muestra (ETF, CORPORATE_BOND, SOVEREIGN_BOND, MONEY_MARKET, CEDEAR).
- Los filtros son determinísticos: mismas preferencias → mismo resultado siempre.
- El filtro `prefer_sectors` / `prefer_issuers` genera un warning pero no excluye instrumentos (solo `avoid_*` excluye).

**Manejo de errores:**
- HTTP 400 → OPENAI_API_KEY no configurada → mensaje con instrucciones de inicio.
- HTTP 502 → Fallo de la IA (respuesta inválida o error de API) → mensaje con instrucción de revisar logs.
- HTTP 500 → CSV del universo no encontrado en el servidor.
- HTTP 422 → Preferencias extraídas por la IA contienen valores inválidos (tipo de instrumento desconocido, liquidity fuera de rango, etc.).
- Error de red → `"API not reachable. Start uvicorn first."`

**Valores por defecto del formulario:**
- `client_id` = `CLI-PREF-001`
- `natural_language_preferences` = `"Solo quiero invertir en ONs hard dollar argentinas disponibles en Balanz y evitar energia."`

Con esta entrada, la IA extrae: `CORPORATE_BOND`, `USD`, `Argentina`, `Balanz`, `hard_dollar_only=true`, `avoid_sectors=[Energy]` — y el filtro devuelve los instrumentos hard-dollar argentinos de Balanz que no son del sector Energy (GALI28 y los nuevos ONs agregados al fixture).

---

### AI Filtered Portfolio Demo

Llama a `POST /ai/filtered-portfolio-demo` — pipeline completo de cuatro pasos:

1. **Paso 1 — Extracción de preferencias (OpenAI):** el texto libre del cliente se envía a `OpenAIProfileClient.extract_investment_preferences()`. La IA devuelve un JSON estructurado con tipos de instrumento permitidos/excluidos, moneda, país, entidad, sectores a evitar, hard dollar, etc.

2. **Paso 2 — Filtro determinístico (universe_layer):** las preferencias extraídas se aplican sobre `tests/fixtures/universe/sample_instrument_universe.csv` usando `PreferenceFilterEngine`.

3. **Paso 3 — Snapshots de mercado:** los instrumentos elegibles se convierten a `MarketDataSnapshot` via `InstrumentMarketDataAdapter`. Solo los snapshots con `expected_return_annual` disponible son usables para optimización.

4. **Paso 4 — Generación de portfolios:** si hay suficientes snapshots usables, `ReturnEstimator` + `CovarianceEngine` + `PortfolioGenerationCoordinator` generan hasta 3 variantes: **DEFENSIVE / BALANCED / GROWTH**.

**Requiere OPENAI_API_KEY** en la terminal donde corre uvicorn. Sin la key, el endpoint devuelve HTTP 400.

**Selectores del formulario:**
- **client_id** — identificador del cliente (default: `CLI-PREF-PORT-001`).
- **profile** — perfil de riesgo (conservador / moderado-defensivo / moderado / moderado-agresivo / agresivo). Determina el `RiskBudget` aplicado al optimizador.
- **natural_language_preferences** — texto libre del cliente con sus preferencias de inversión.

**Resultado cuando `status=completed`:**
- **Resumen:** status, profile, eligible_count, excluded_count, snapshot_count, candidate_count, confianza de la IA.
- **Preferencias detectadas:** todos los campos del resultado de OpenAI (tipos permitidos/excluidos, entity, currency, country, hard_dollar_only, sectores evitados/preferidos, min_liquidity_score, max_maturity_year, hard_constraints, soft_preferences, advisor_notes).
- **Filtros aplicados** — chips con los criterios activos.
- **Warnings** — chips de advertencia (prefer_* hints, claves desconocidas, etc.).
- **Tabla de instrumentos elegibles** — ticker, nombre, emisor, tipo, moneda, país, sector, hard dollar, vencimiento, YTM, duración, liquidez, rating.
- **Tabla de snapshots usables** — ticker, retorno esperado anual, volatilidad anual, duración, liquidez.
- **Portfolios candidatos** — hasta 3 cards (DEFENSIVE / BALANCED / GROWTH), cada una con retorno esperado, volatilidad, risk score, barra de pesos por activo, metadata de risk budget.
  - Si GROWTH requiere `advisor_override` (relaja `max_volatility`), se muestra el banner de advertencia con los constraints excedidos.
- **Tabla de instrumentos excluidos** — ticker + chips con razones de exclusión.
- **JSON completo** colapsable.

**Resultado cuando el portfolio está bloqueado:**
- `status=blocked_insufficient_universe` — menos de 3 snapshots usables (universo filtrado demasiado pequeño para cualquier portfolio).
- `status=blocked_insufficient_diversification_capacity` — snapshots usables < `ceil(1 / max_single_asset)` requerido por el perfil (por ejemplo, perfil `moderado` con `max_single_asset=0.15` requiere al menos 7 activos).
- `status=infeasible` — el optimizador no encontró solución factible con los constraints del risk budget.
- En todos los casos bloqueados se muestra el `message` explicativo en una caja de status destacada (azul para insuficiente, rojo para infeasible).

**Notas importantes:**
- **Requiere OPENAI_API_KEY.** Sin la key, HTTP 400 con instrucciones de inicio.
- **No persiste resultados** en SQLite ni genera reporte Markdown.
- **No aprueba** el perfil final — solo el asesor puede hacerlo.
- Los retornos esperados y volatilidades se calculan desde los campos `ytm` y `coupon_rate` del CSV (instrumentos de renta fija). ETFs, CEDEARs y acciones no tienen snapshots usables en esta demo.
- **Universo fijo:** `tests/fixtures/universe/sample_instrument_universe.csv` — 20 instrumentos de muestra.

**Manejo de errores:**
- HTTP 400 → OPENAI_API_KEY no configurada → mensaje con instrucciones de inicio.
- HTTP 502 → Fallo de la IA (OpenAI) → mensaje con instrucción de revisar logs.
- HTTP 422 → Perfil inválido o campos requeridos faltantes.
- Error de red → `"API not reachable. Start uvicorn first."`

**Valores por defecto del formulario:**
- `client_id` = `CLI-PREF-PORT-001`
- `profile` = `moderado`
- `natural_language_preferences` = `"Solo quiero invertir en ONs hard dollar argentinas disponibles en Balanz y evitar energia."`

Con esta entrada y perfil `moderado`, la IA extrae preferencias de ONs hard dollar argentinas en Balanz sin sector Energía — y el optimizador genera 3 portfolios candidatos con los instrumentos elegibles que tienen datos de mercado usables.

---

### Persisted Workflows
Lista los workflows guardados en SQLite. Permite filtrar por `client_id`. Muestra tabla con `record_id`, `client_id`, `status` y `created_at_utc`.

---

## Limitaciones

- **Sin autenticación.** Este frontend es solo para desarrollo local.
- **Sin producción.** No usar contra un backend expuesto en red pública.
- **Frontend estático de demo.** No persiste estado entre recargas.
- **CORS.** Si el navegador bloquea requests desde `file://`, usar `python -m http.server 5500 -d frontend`.
- **AI Profile Demo, AI Universe Filter Demo y AI Filtered Portfolio Demo requieren OPENAI_API_KEY.** Sin la key, los endpoints responden HTTP 400. La sección Live Portfolio Demo descarga datos reales de Yahoo Finance (requiere internet).
- **SQLite local.** Los IDs de workflow (`workflow_000001`, etc.) son secuenciales por sesión de backend. Se resetean si el servidor se reinicia sin persistencia previa.
- **No cubre todos los endpoints.** Solo consume `/health`, `/workflow/run`, `/live/portfolio-demo`, `/ai/profile-demo`, `/ai/profile-follow-up`, `/ai/filter-universe-demo`, `/ai/filtered-portfolio-demo` y `GET /workflow`. Los endpoints `/universe/filter-demo`, `/reports`, `/audit` y los GET por ID están disponibles en el backend pero no en este frontend. Usar `curl` o Swagger UI para esos.
