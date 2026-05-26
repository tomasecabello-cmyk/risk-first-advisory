-- ─────────────────────────────────────────────────────────────────────────────
-- 0002 — KYC submissions (case-scoped, versioned)
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Cada AdvisoryCase puede tener N submissions de KYC. La versión más reciente
-- queda referenciada por advisory_cases.current_kyc_submission_id (FK
-- declarada en 0001 pero sin enforcement explícito porque la tabla no existía
-- todavía).
--
-- INVARIANTES:
--   - version es monotónica por case_id (UNIQUE(case_id, version)).
--   - payload_hash = sha256(canonical JSON del payload original).
--   - payload_json se persiste en formato canonical (sort_keys, separators
--     compactos) para que el hash sea reproducible.
--   - No expone update / delete a nivel API: cada modificación es una nueva
--     submission con version siguiente.
--
-- IMPORTANTE para futuras migraciones:
--   - No incluir BEGIN / COMMIT explícitos: el runner (scripts/migrate.py)
--     envuelve cada archivo en su propia transacción.
-- ─────────────────────────────────────────────────────────────────────────────


CREATE TABLE kyc_submissions (
    kyc_submission_id        TEXT PRIMARY KEY,
    case_id                  TEXT NOT NULL,
    version                  INTEGER NOT NULL,
    submitted_by_advisor_id  TEXT,
    payload_json             TEXT NOT NULL,
    payload_hash             TEXT NOT NULL,
    created_at_utc           TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES advisory_cases(case_id),
    FOREIGN KEY (submitted_by_advisor_id) REFERENCES advisors(advisor_id),
    UNIQUE (case_id, version)
);

CREATE INDEX idx_kyc_submissions_case_id
    ON kyc_submissions(case_id);

CREATE INDEX idx_kyc_submissions_submitted_by_advisor_id
    ON kyc_submissions(submitted_by_advisor_id);
