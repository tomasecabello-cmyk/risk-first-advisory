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
  y μ con Black-Litterman sobre series alineadas (DD-014, `data_layer/estimation.py`);
  `CovarianceEngine` (correlaciones mock por asset_class) queda solo como motor del
  modo fixture y fallback sin red. YTM para renta fija sigue pendiente como view de BL.
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
- **Ratio jumps — falsos positivos en días de evento genuinos**: `adjust_ratio_jumps`
  (DD-014, extensión 2026-07-08) recorta días aislados con |r| > 40% también cuando son
  mercado real (medido: rally post-elecciones 2025-10-27, BHIP/SUPV/METR +43-46%),
  subestimando levemente la σ de esos tickers. Refinar con una señal cross-sectional
  (muchos tickers con día grande común y FX/mercado coherentes = evento, no artefacto).
- **Series con historia rota en el universo**: VIST y XLB llegan con 1 observación en
  la ventana 3y del caché (quedan excluidos de la estimación con razón auditada, pero
  deberían tener serie completa) — revisar el fetch/caché de esos tickers.
