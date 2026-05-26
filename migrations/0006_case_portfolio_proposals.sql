-- ─────────────────────────────────────────────────────────────────────────────
-- 0006 — Case-scoped portfolio proposals
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Snapshot completo de una propuesta de portfolio generada para un case:
-- usa el approved_profile y el filter_run vigentes (o explícitos) para
-- construir un RiskBudget y correr el PortfolioGenerationCoordinator.
--
-- INVARIANTES:
--   - filter_run_id es NOT NULL: cada propuesta queda anclada a un universo
--     filtrado concreto. Trazabilidad universe → proposal es central.
--   - approved_profile_id es NULL-able: en escenarios edge (case con profile
--     directamente seteado fuera del flow de approval) la propuesta puede
--     existir sin approval explícito. El camino productivo siempre la llena.
--   - is_current refleja "esta es la propuesta vigente del case"; cada
--     nuevo POST marca las previas =0.
--   - status ∈ {completed, blocked_insufficient_universe,
--     blocked_insufficient_diversification_capacity, infeasible}.
--   - risk_budget_json, snapshots_json, candidates_json, warnings_json se
--     persisten en canonical JSON para reproducibilidad.
--
-- No incluir BEGIN/COMMIT explícitos.
-- ─────────────────────────────────────────────────────────────────────────────


CREATE TABLE case_portfolio_proposals (
    proposal_id            TEXT PRIMARY KEY,
    case_id                TEXT NOT NULL,
    filter_run_id          TEXT NOT NULL,
    approved_profile_id    TEXT,
    profile_name           TEXT NOT NULL,
    risk_budget_json       TEXT NOT NULL,
    snapshots_json         TEXT NOT NULL,
    candidates_json        TEXT NOT NULL,
    warnings_json          TEXT NOT NULL,
    status                 TEXT NOT NULL,
    created_by_advisor_id  TEXT,
    created_at_utc         TEXT NOT NULL,
    is_current             INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (case_id) REFERENCES advisory_cases(case_id),
    FOREIGN KEY (filter_run_id) REFERENCES case_universe_filter_runs(filter_run_id),
    FOREIGN KEY (approved_profile_id) REFERENCES advisor_profile_approvals(approval_id),
    FOREIGN KEY (created_by_advisor_id) REFERENCES advisors(advisor_id)
);

CREATE INDEX idx_case_portfolio_proposals_case_id
    ON case_portfolio_proposals(case_id);

CREATE INDEX idx_case_portfolio_proposals_filter_run_id
    ON case_portfolio_proposals(filter_run_id);

CREATE INDEX idx_case_portfolio_proposals_approved_profile_id
    ON case_portfolio_proposals(approved_profile_id);

CREATE INDEX idx_case_portfolio_proposals_created_by_advisor_id
    ON case_portfolio_proposals(created_by_advisor_id);
