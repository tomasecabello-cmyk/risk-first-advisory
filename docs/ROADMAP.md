# ROADMAP — pendientes consolidados

> Único backlog vivo del proyecto. Consolida los pendientes que estaban dispersos en
> `TODO_DESIGN_NOTES.md`, `UX_REDESIGN_PLAN.md` y `NEXT_SESSION_PROMPT.md` (borrados en la
> limpieza 2026-07; su historia está en git). Lo cerrado no se lista: eso ya lo cuentan
> `DESIGN_DECISIONS.md` y el log de commits.

## Universo dinámico pleno (Fase 3 de producto)

- Generación on-demand por request (hoy: CSV pre-generado por `scripts/build_arg_universe.py`).
- "Bróker" como filtro de disponibilidad (`available_entities` ya está en el schema).
- Bonos peso ARS-nativos (Lecaps/CER) — hoy fuera de alcance por ruido de devaluación (marco USD/CCL).
- **Correlaciones/μ reales en modo fixture**: el path live ya estima Σ con Ledoit-Wolf
  y μ con Black-Litterman sobre series alineadas (DD-014, `data_layer/estimation.py`),
  con el YTM del universo como view de BL para renta fija (ext. 2026-07-08);
  `CovarianceEngine` (correlaciones mock por asset_class) queda solo como motor del
  modo fixture y fallback sin red.
- La demo debe correr SIEMPRE con `RFA_LIVE_DATA=1` (el CSV solo cubre renta fija con precio).

## Fase 4 — pilot readiness (asesor piloto real; no producción aún)

- Firm-level access control (`firm_id` en token + filtrado en todos los `/cases/*`).
- Auth productiva: JWT/OIDC/IdP, rotación/revocación de tokens; share-link de cliente acotado a un `case_id`.
- Market data provider productivo con SLA de frescura + manual universe upload (admin endpoint).
- PDF/branding del report; lifecycle formal (draft → reviewed → final → sent).
- Compliance export package (ZIP: report + audit trail + AI logs sanitizados).
- Backup/restore de la DB (hoy solo `scripts/backup_db.py` manual) o migración a PostgreSQL multi-tenant.
- `/health/full` runtime endpoint (migrations + tokens + fixtures desde el backend en marcha).
- Deployment productivo (Docker/CI/CD/observabilidad) + checklist legal/compliance + runbook.
- Cifrado at-rest + retention/pruning de `ai_request_logs`, `kyc_submissions`, etc.
- Anclaje externo del audit chain (timestamping authority) contra DBA malicioso.

## Deuda técnica / diseño (menor, sin urgencia)

- **Endpoints legacy `/advisor/*`**: no integran AuditEvent; validación cruzada de records
  incompleta (`candidate_variant` vs proposal real, override coherente con selección);
  contrato del dominio (`human_layer.override_approval`) más estricto que los schemas API —
  unificar cuando el override se dispare desde un workflow corriendo; faltan GETs de
  retrieval por record_id. (El flujo case-scoped `/cases/*` NO tiene estos huecos.)
- **`ESGPreference.target`**: agregar campo opcional para `prefer_tag`/`avoid_tag`
  (hoy devuelven warning `ESG_DATA_INCOMPLETE`).
- **Diversification pre-check**: `usable < ceil(1/max_single_asset)` es conservador;
  revisar si bloquea portfolios que el optimizador resolvería con concentraciones asimétricas.
- **Cache de extracción de preferencias OpenAI** (`hash(texto)` + TTL) para no re-llamar
  con texto idéntico.
- **Firma digital** del rationale del asesor (hoy texto libre sin identidad verificada).
- **Ratio jumps en `LiveMarketDataProvider` (per-ticker)**: el path per-ticker no ve el
  cross-section, así que ajusta incondicionalmente también en días de evento genuinos
  (la Σ del proposal la produce el estimador conjunto, que sí exime — impacto acotado a
  los snapshots per-ticker del path legacy/fallback).

## Auditoría de compliance (2026-07-17 — skills compliance@finance-skills)

> Diagnóstico contra práctica estándar (FINRA 2111/2090, CIP/CDD, Reg BI) usada como
> referencia de doctrina, ADAPTADA: esto es un demo local ARG, `docs/INVARIANTS.md`
> manda, y el marco regulatorio real del piloto sería CNV/UIF, no SEC/FINRA.
> Lo que ya cubre bien el motor (sin gap): rationale obligatorio en
> approval/selection/override, tope determinístico de capacidad con
> `framework_override_acknowledged`, matriz de suitability con default conservador
> `SUITABILITY_RULE_MISSING`, audit chain, separación IA-propone/asesor-decide.

### Suitability / perfil del cliente

- **Análisis de concentración a nivel cliente**: el KYC ya captura held-away,
  pasivos y tax status como campos informativos (DD-017 ext. 2026-08-04); falta
  que el proposal USE esos datos (p.ej. warning de concentración si la cartera
  propuesta duplica exposición que el cliente ya tiene afuera).
- **Reconfirmación de KYC ante eventos de vida**: el TTL por antigüedad ya avisa
  (`KYC_012`/`KYC_STALE`, DD-017 — `RFA_KYC_MAX_AGE_DAYS`, default 365); falta un
  mecanismo para que el asesor marque un evento de vida (jubilación, herencia) que
  exija reconfirmación antes del TTL.
- **Sin registro de negativa a informar**: todos los campos del KYC son obligatorios
  (conservador, bien), pero no se puede documentar "el cliente se negó a responder X"
  — práctica estándar: registrar la negativa y estrechar el universo recomendable.
- **Suitability per-instrument en el case flow (Fase 4)**: la marca de producto
  complejo ya es sistemática (DD-017 ext.: catálogo `rules_layer/complex_products`,
  flag + nota en holdings y report); sigue pendiente evaluar la matriz de
  suitability por instrumento en el pipeline case-scoped (`suitability_status`
  del holding hoy es `None`).

### Identidad y onboarding (para Fase 4 — piloto real)

- **Cliente = `display_name` + jurisdiction**: sin identidad verificable (DNI/CUIT),
  sin screening PEP/sanciones, sin beneficial ownership para cuentas de entidades.
  Para un piloto con asesor real esto es requisito UIF (sujeto obligado), no opcional.
  Va junto al checklist legal/compliance ya listado en Fase 4.
- **Sin trusted contact / persona autorizada** en el modelo de cliente.

### Disclosures y costos (Reg BI como referencia)

- **Costos al cliente no modelados**: los candidates del proposal no llevan
  TER/comisiones/custodia; no se puede comparar variantes por costo total ni incluir
  disclosure de fees en el report. El costo es factor obligatorio del care obligation
  en la práctica estándar; hoy el motor optimiza sin verlo.
- **Sin registro de conflictos de interés de la firma** (productos propios,
  retrocesiones) ni sección de disclosure en el report: los 4 disclaimers fijos de
  I-020 no cubren fees, conflictos ni capacidad en la que actúa el asesor.
- **Sin documento tipo relationship summary** (análogo Form CRS) en onboarding —
  Fase 4, junto con PDF/branding del report.

## Auditoría de seguridad (2026-07-17 — skill security-guidance)

> Revisión de `api_layer/` + `persistence_layer/`. Sin hallazgos de inyección SQL
> (queries parametrizadas) ni de leak de tokens en errores/logs (error policy
> genérica en auth). Severidades para el contexto "demo local que aspira a piloto".

- **[Alta — refuerza ítem existente de Fase 4] Sin firm-level access control**:
  cualquier token con rol advisor lee KYC, casos y AI logs de CUALQUIER firma
  (PII cross-tenant). Ya está en Fase 4; esta auditoría lo confirma como el gap de
  autorización más serio del estado actual.
- **[Media] Tokens en claro en el YAML de advisors**: el archivo de tokens guarda el
  token literal; guardar hash (SHA-256) y comparar por hash — complementa la
  rotación/revocación ya listada en Fase 4.
- **[Baja] CORS con `allow_credentials=True`**: inocuo hoy (orígenes locales fijos);
  revisar la lista de orígenes al desplegar (no pasar nunca a `*`).

## Mejoras metodológicas `data_layer/estimation.py` (2026-07-17 — wealth-management + quant-finance-methods)

> DD-014 (Σ Ledoit-Wolf + μ Black-Litterman) es sólido; esto es afinación con buena
> relación costo/beneficio, no rediseño. Ordenado por prioridad.

- **Guard de solapamiento en el inner join**: la serie más corta recorta la ventana
  común de TODOS los tickers (`concat(...).dropna()`). Descartar, con razón auditada
  (patrón `dropped`), series cuya inclusión reduzca la ventana común por debajo de un
  umbral (p.ej. <60% de la ventana máxima disponible). Costo bajo.
- **`ffill()` sin límite antes del `dropna()`**: días sin cotización (feriados ARG vs
  US) generan retornos 0 espurios que subestiman vol y correlaciones
  (nonsynchronous trading). Mitigación barata: `ffill(limit=2)` o validar las
  correlaciones cross-market con retornos semanales.
- **Target de shrinkage constant-correlation (Ledoit-Wolf 2003)**: para universos
  con mayoría accionaria suele superar al target identidad escalada; fórmula cerrada,
  sin dependencias nuevas. Beneficio moderado.
- **`rf`, `delta`, `tau` hardcodeados en `estimation.py`**: mover a `config_layer`
  para coherencia con `risk_assumptions` (hoy `rf=0.04` vive en el módulo).
- **No recomendado** (costo > beneficio): GARCH/EWMA para la Σ del proposal (horizonte
  de advisory largo; complejidad sin ganancia) y cap-weights como `w_ref` de BL (el
  "portafolio de mercado" de una canasta mixta ARG/US no es observable; equal-weight
  es defendible y está documentado).
