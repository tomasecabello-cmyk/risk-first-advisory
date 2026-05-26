-- ─────────────────────────────────────────────────────────────────────────────
-- 0007 — Case-scoped advisor override approvals
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Decisión del asesor sobre una variante de portfolio (típicamente GROWTH)
-- que excede el RiskBudget aprobado y requiere advisor override.
--
-- INVARIANTES:
--   - proposal_id es NOT NULL: cada override approval queda anclado a una
--     propuesta concreta. Override sin proposal no tiene sentido — no hay
--     candidate sobre el cual decidir.
--   - candidate_variant ∈ {DEFENSIVE, BALANCED, GROWTH} (la API restringe;
--     la tabla guarda string libre por flexibilidad de migraciones).
--   - decision ∈ {approve, reject} (la API restringe).
--   - reason_codes_json y exceeded_constraints_json se persisten en canonical
--     JSON con wrapper {"items": [...]} (mismo patrón que filter_runs).
--   - is_current refleja "esta es la decisión vigente del case" — cada nuevo
--     POST marca las previas =0. La política se aplica a nivel case (no por
--     proposal_id o candidate_variant) para mantenerlo simple.
--   - Append-only a nivel API: no expone update/delete; mark_previous_not_current
--     es la única mutación.
--
-- NB: tabla coexiste con `records` (legacy SQLitePersistenceStore con
-- record_type='advisor_override_approval', client-scoped). Son storages
-- distintos sin conflicto.
--
-- No incluir BEGIN/COMMIT explícitos.
-- ─────────────────────────────────────────────────────────────────────────────


CREATE TABLE case_override_approvals (
    override_approval_id      TEXT PRIMARY KEY,
    case_id                   TEXT NOT NULL,
    proposal_id               TEXT NOT NULL,
    candidate_variant         TEXT NOT NULL,
    decision                  TEXT NOT NULL,
    reason_codes_json         TEXT NOT NULL,
    exceeded_constraints_json TEXT NOT NULL,
    rationale                 TEXT NOT NULL,
    source                    TEXT NOT NULL,
    advisor_id                TEXT,
    created_at_utc            TEXT NOT NULL,
    is_current                INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (case_id) REFERENCES advisory_cases(case_id),
    FOREIGN KEY (proposal_id) REFERENCES case_portfolio_proposals(proposal_id),
    FOREIGN KEY (advisor_id) REFERENCES advisors(advisor_id)
);

CREATE INDEX idx_case_override_approvals_case_id
    ON case_override_approvals(case_id);

CREATE INDEX idx_case_override_approvals_proposal_id
    ON case_override_approvals(proposal_id);

CREATE INDEX idx_case_override_approvals_advisor_id
    ON case_override_approvals(advisor_id);
