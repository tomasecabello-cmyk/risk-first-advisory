-- ─────────────────────────────────────────────────────────────────────────────
-- 0008 — Case-scoped portfolio selections
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Decisión final del asesor: cuál variant del proposal se presenta al cliente.
-- Vincula:
--   - proposal_id      → la propuesta de la cual se elige la variant.
--   - override_approval_id (NULL) → solo presente si la variant elegida
--     requería override y fue aprobada.
--
-- INVARIANTES:
--   - proposal_id NOT NULL: cada selection se ancla a una proposal concreta.
--   - selected_variant ∈ {DEFENSIVE, BALANCED, GROWTH} (API restringe; tabla
--     guarda string libre por flexibilidad de migraciones).
--   - selected_candidate_json: snapshot completo del candidate elegido al
--     momento de la selección (peso por peso, metadata incluida). Trazabilidad
--     independiente del proposal: si el proposal se regenera, la selección
--     conserva la foto del candidate original.
--   - override_approval_id NULL-able: variants que no requieren override
--     no necesitan approval. El endpoint valida coherencia (variant que
--     requiere override DEBE tener override aprobado; variant que no, NO
--     debe tener override).
--   - is_current: una selección vigente por case. Cada nueva POST invalida
--     las previas del case.
--
-- COEXISTENCIA:
--   Tabla coexiste con `records.record_type='advisor_portfolio_selection'`
--   (legacy Phase 1 client-scoped). Sin conflicto.
--
-- No incluir BEGIN/COMMIT explícitos.
-- ─────────────────────────────────────────────────────────────────────────────


CREATE TABLE case_portfolio_selections (
    selection_id            TEXT PRIMARY KEY,
    case_id                 TEXT NOT NULL,
    proposal_id             TEXT NOT NULL,
    override_approval_id    TEXT,
    selected_variant        TEXT NOT NULL,
    selected_candidate_json TEXT NOT NULL,
    rationale               TEXT NOT NULL,
    source                  TEXT NOT NULL,
    advisor_id              TEXT,
    created_at_utc          TEXT NOT NULL,
    is_current              INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (case_id) REFERENCES advisory_cases(case_id),
    FOREIGN KEY (proposal_id) REFERENCES case_portfolio_proposals(proposal_id),
    FOREIGN KEY (override_approval_id) REFERENCES case_override_approvals(override_approval_id),
    FOREIGN KEY (advisor_id) REFERENCES advisors(advisor_id)
);

CREATE INDEX idx_case_portfolio_selections_case_id
    ON case_portfolio_selections(case_id);

CREATE INDEX idx_case_portfolio_selections_proposal_id
    ON case_portfolio_selections(proposal_id);

CREATE INDEX idx_case_portfolio_selections_override_approval_id
    ON case_portfolio_selections(override_approval_id);

CREATE INDEX idx_case_portfolio_selections_advisor_id
    ON case_portfolio_selections(advisor_id);
