# Handoff — próxima sesión (estado al 2026-07-08, tarde)

## Qué pasó en la última sesión

Los 3 ítems de deuda técnica del plan, commiteados por separado:

1. **Quirk `review_override` cerrado** (DD-015, commit `9ff3915`): el requisito
   de override del summary se evalúa contra la SELECCIÓN vigente
   (`_override_requirement_for_progress`); sin selección se mantiene la guía a
   nivel proposal. El smoke check ahora ejercita el path del quirk (aprueba el
   override de GROWTH pero selecciona BALANCED) y exige `completion_ratio == 1.0`.
2. **Saltos de ratio CEDEAR** (DD-014 ext., commit `fff8c40`):
   `providers.adjust_ratio_jumps` — detección de retornos diarios absurdos y
   AISLADOS (|r| > 40% + outlier MAD + vecinos normales) y corrección por
   back-scaling del prefijo, auditada por salto (warnings del proposal + notes
   del snapshot). > `RATIO_JUMP_MAX=5` saltos ⇒ serie descartada. Se aplica
   sobre la serie YA en USD, en ambos consumidores (estimador conjunto y
   provider per-ticker). Medido: IBM 137%→64%, NFLX 149%→45%, MELI 86%→46%.
   Detectó además un artefacto común de data912 (2023-08-03/04, soberanos
   +60-69% el mismo día con CCL suave).
3. **YTM como view de BL** (DD-014 ext., commit `5a7b659`):
   `estimate_joint_moments(views=...)` — la API pasa el `ytm` del universo como
   view para renta fija. Medido: GD30 μ_hist −4.3% → μ_BL +10.5% (YTM 11.5%),
   21 bonos con view.

## Pendientes que dejó esta sesión (ya en ROADMAP, sección deuda técnica)

- **Falsos positivos del ratio-jump en días de evento genuinos**: el rally
  post-elecciones 2025-10-27 (BHIP/SUPV/METR +43-46% reales) se recorta de más
  → subestima levemente σ de esos tickers. Refinar con señal cross-sectional.
- **VIST y XLB llegan con 1 observación** en la ventana 3y del caché (quedan
  excluidos con razón auditada, pero deberían tener serie) — revisar fetch/caché.

## Cómo correr la demo

```powershell
python scripts/build_arg_universe.py --warm     # 1 vez por día (~2-3 min)
$env:RFA_DEMO_MODE="1"; $env:RFA_LIVE_DATA="1"
python -m uvicorn risk_first_advisory.api_layer.main:app --port 8000
python -m http.server 5500 -d frontend          # otra terminal → http://127.0.0.1:5500
```

## Convenciones que muerden (el resto está en CLAUDE.md)

- Gates antes de commitear Python: `pytest -q` (~2570) + smoke check + `ruff` +
  `mypy` (0/0). Commits en español, mensaje vía archivo (`git commit -F`).
- Verificación quant en vivo: server con tokens de seed
  (`$env:ADVISOR_TOKENS_FILE="data/_seed_tokens.yaml"` → `Bearer seed-admin` /
  `Bearer seed-advisor`) + flujo httpx e inspección del proposal persistido
  (plantilla `drive_flow.py` del scratchpad de esta sesión; imprime warnings,
  snapshots con notes y candidates).
- El summary del proposal NO trae `stale` en los snapshots serializados
  (`_serialize_snapshot_for_proposal`): ticker/μ/σ/duration/liquidity/notes.
- Los pendientes nuevos van a `docs/ROADMAP.md`, no a TODOs nuevos.
- `GET /cases/{id}/audit/verify` requiere rol compliance/admin.
