-- ─────────────────────────────────────────────────────────────────────────────
-- 0010 — considered_alternatives en case_portfolio_selections
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Auditoría de compliance 2026-07-17: la selección exige `rationale` libre
-- pero no registra POR QUÉ se descartaron las otras variantes del proposal.
-- La doctrina de "reasonably available alternatives" (Reg BI care obligation,
-- usada como referencia adaptada — ver ROADMAP) pide documentar las
-- alternativas consideradas, no solo la elegida.
--
-- considered_alternatives_json: lista JSON de objetos
--     {"variant": "GROWTH", "reason_rejected": "..."}
-- OPCIONAL (NULL-able):
--   - NULL     → el asesor no documentó alternativas (filas históricas y
--                selecciones sin el campo). Distinto de lista vacía.
--   - "[]"     → documentó explícitamente que no consideró otras variantes.
-- La API valida: variant ∈ candidates del proposal, ≠ selected_variant,
-- sin duplicados, reason_rejected no vacío.
--
-- No incluir BEGIN/COMMIT explícitos.
-- ─────────────────────────────────────────────────────────────────────────────


ALTER TABLE case_portfolio_selections
    ADD COLUMN considered_alternatives_json TEXT;
