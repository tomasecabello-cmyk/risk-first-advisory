-- ─────────────────────────────────────────────────────────────────────────────
-- 0004 — Case-scoped advisor profile approvals
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Decisión humana del asesor sobre el perfil de riesgo de un AdvisoryCase.
-- Cada decisión queda anclada a:
--   - case_id (obligatorio)
--   - ai_profile_analysis_id (opcional — el análisis sobre el cual se decide)
--   - kyc_submission_id (opcional — la versión KYC vigente al momento)
--   - advisor_id (opcional — entity del advisor que decidió)
--
-- INVARIANTES:
--   - approval_id es opaco con prefijo `advisor_profile_approval_`.
--   - decision ∈ {approve, modify, reject} (la API lo restringe; la tabla lo
--     guarda como string libre por flexibilidad de migraciones futuras).
--   - is_current refleja "esta es la decisión vigente del case" (1) o
--     "fue reemplazada por una nueva approve/modify" (0). Solo approve/modify
--     marcan is_current=1; reject queda is_current=0 desde el insert.
--   - Append-only: no se exponen update/delete via API. Lo único que se
--     muta es is_current (vía mark_previous_not_current) para reflejar la
--     decisión vigente.
--
-- IMPORTANTE: la tabla NO colisiona con `records` (legacy SQLitePersistenceStore
-- usa records.record_type='advisor_profile_approval'). Son storages distintos:
-- esta tabla es case-scoped; el legacy es client_id-scoped.
--
-- No incluir BEGIN/COMMIT explícitos.
-- ─────────────────────────────────────────────────────────────────────────────


CREATE TABLE advisor_profile_approvals (
    approval_id            TEXT PRIMARY KEY,
    case_id                TEXT NOT NULL,
    ai_profile_analysis_id TEXT,
    kyc_submission_id      TEXT,
    advisor_id             TEXT,
    proposed_profile       TEXT NOT NULL,
    decision               TEXT NOT NULL,
    approved_profile       TEXT,
    rationale              TEXT NOT NULL,
    source                 TEXT NOT NULL,
    is_current             INTEGER NOT NULL DEFAULT 1,
    created_at_utc         TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES advisory_cases(case_id),
    FOREIGN KEY (ai_profile_analysis_id) REFERENCES ai_profile_analyses(analysis_id),
    FOREIGN KEY (kyc_submission_id) REFERENCES kyc_submissions(kyc_submission_id),
    FOREIGN KEY (advisor_id) REFERENCES advisors(advisor_id)
);

CREATE INDEX idx_advisor_profile_approvals_case_id
    ON advisor_profile_approvals(case_id);

CREATE INDEX idx_advisor_profile_approvals_ai_profile_analysis_id
    ON advisor_profile_approvals(ai_profile_analysis_id);

CREATE INDEX idx_advisor_profile_approvals_kyc_submission_id
    ON advisor_profile_approvals(kyc_submission_id);

CREATE INDEX idx_advisor_profile_approvals_advisor_id
    ON advisor_profile_approvals(advisor_id);
