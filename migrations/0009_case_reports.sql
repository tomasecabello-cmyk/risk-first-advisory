-- ─────────────────────────────────────────────────────────────────────────────
-- 0009 — Case-scoped advisor reports (markdown)
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Reportes generados por el asesor para presentar al cliente. Vinculan
-- case_id, portfolio_selection_id (el snapshot final) y portfolio_proposal_id
-- (denormalizado para query rápido sin pasar por la selection).
--
-- INVARIANTES:
--   - case_id NOT NULL.
--   - version monotónica por case_id (UNIQUE(case_id, version)). Cada nuevo
--     POST incrementa la version del case.
--   - report_type es libre a nivel DB; la API restringe a
--     {portfolio_recommendation}.
--   - status es libre a nivel DB; la API restringe a {draft, final}.
--   - markdown se persiste como TEXT plano (no canonical JSON; ya es texto).
--   - metadata_json en canonical JSON.
--   - is_current refleja "este es el report vigente del case". Cada nuevo
--     POST marca los previos =0.
--   - Append-only a nivel API; mark_previous_not_current es la única
--     mutación. NO se mutua el markdown una vez generado.
--
-- No incluir BEGIN/COMMIT explícitos.
-- ─────────────────────────────────────────────────────────────────────────────


CREATE TABLE case_reports (
    report_id                TEXT PRIMARY KEY,
    case_id                  TEXT NOT NULL,
    portfolio_selection_id   TEXT,
    portfolio_proposal_id    TEXT,
    report_type              TEXT NOT NULL,
    status                   TEXT NOT NULL,
    version                  INTEGER NOT NULL,
    markdown                 TEXT NOT NULL,
    metadata_json            TEXT NOT NULL,
    generated_by_advisor_id  TEXT,
    created_at_utc           TEXT NOT NULL,
    is_current               INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (case_id) REFERENCES advisory_cases(case_id),
    FOREIGN KEY (portfolio_selection_id) REFERENCES case_portfolio_selections(selection_id),
    FOREIGN KEY (portfolio_proposal_id) REFERENCES case_portfolio_proposals(proposal_id),
    FOREIGN KEY (generated_by_advisor_id) REFERENCES advisors(advisor_id),
    UNIQUE (case_id, version)
);

CREATE INDEX idx_case_reports_case_id
    ON case_reports(case_id);

CREATE INDEX idx_case_reports_portfolio_selection_id
    ON case_reports(portfolio_selection_id);

CREATE INDEX idx_case_reports_portfolio_proposal_id
    ON case_reports(portfolio_proposal_id);

CREATE INDEX idx_case_reports_generated_by_advisor_id
    ON case_reports(generated_by_advisor_id);
