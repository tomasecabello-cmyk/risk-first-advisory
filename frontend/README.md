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
| Run Workflow | `POST` | `/workflow/run` | Ejecuta el workflow con el formulario |
| Live Portfolio Demo | `POST` | `/live/portfolio-demo` | Portfolios reales con datos de yfinance |
| AI Profile Demo | `POST` | `/ai/profile-demo` | Análisis KYC con OpenAI (requiere API key) |
| Persisted Workflows | `GET` | `/workflow` | Lista todos los workflows |
| Persisted Workflows | `GET` | `/workflow?client_id=...` | Filtra workflows por cliente |

---

## Secciones del formulario

### API Health
Botón "Check API" — llama `GET /health` y muestra la respuesta. Útil para verificar que el backend está corriendo antes de ejecutar el workflow.

### Run Workflow
Formulario con todos los campos de `KYCData` y `FinancialGoal`. Valores por defecto razonables para un perfil moderado. Campos opcionales pueden dejarse en blanco.

Al ejecutar:
- Muestra un resumen estructurado: status, perfil aprobado, portfolios generados, tickers, reason codes, warnings, IDs persistidos.
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

### Persisted Workflows
Lista los workflows guardados en SQLite. Permite filtrar por `client_id`. Muestra tabla con `record_id`, `client_id`, `status` y `created_at_utc`.

---

## Limitaciones

- **Sin autenticación.** Este frontend es solo para desarrollo local.
- **Sin producción.** No usar contra un backend expuesto en red pública.
- **Frontend estático de demo.** No persiste estado entre recargas.
- **CORS.** Si el navegador bloquea requests desde `file://`, usar `python -m http.server 5500 -d frontend`.
- **AI Profile Demo requiere OPENAI_API_KEY.** Sin la key, el endpoint responde HTTP 400. La sección Live Portfolio Demo descarga datos reales de Yahoo Finance (requiere internet).
- **SQLite local.** Los IDs de workflow (`workflow_000001`, etc.) son secuenciales por sesión de backend. Se resetean si el servidor se reinicia sin persistencia previa.
- **No cubre todos los endpoints.** Solo consume `/health`, `/workflow/run`, `/live/portfolio-demo`, `/ai/profile-demo` y `GET /workflow`. Los endpoints `/reports`, `/audit` y los GET por ID están disponibles en el backend pero no en este frontend. Usar `curl` o Swagger UI para esos.
