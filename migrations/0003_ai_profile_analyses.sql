-- ─────────────────────────────────────────────────────────────────────────────
-- 0003 — AI profile analyses (case-scoped)
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Cada análisis IA de perfil queda anclado a:
--   - un AdvisoryCase (case_id)
--   - una KYCSubmission concreta del case (kyc_submission_id)
--   - opcionalmente al AIRequestLog que registró la llamada (ai_request_log_id)
--
-- INVARIANTES:
--   - kyc_submission_id es NOT NULL: cada análisis se hace sobre una versión
--     específica del KYC. La trazabilidad versión → análisis es central.
--   - ai_request_log_id es NULL-able: el análisis puede existir sin log si
--     el caller persistió el análisis directamente vía repo (e.g. backfill),
--     pero el camino productivo (endpoint POST) siempre lo vincula.
--   - preliminary_profile y confidence son extractos denormalizados del
--     result_json para indexar y mostrar sin parsear JSON; pueden ser NULL
--     si el análisis falla de forma parcial (no se debería pasar pero
--     defensive).
--   - result_json se persiste canonical (sort_keys, separators compactos).
--
-- IMPORTANTE para futuras migraciones:
--   - No incluir BEGIN / COMMIT explícitos: el runner los envuelve.
-- ─────────────────────────────────────────────────────────────────────────────


CREATE TABLE ai_profile_analyses (
    analysis_id          TEXT PRIMARY KEY,
    case_id              TEXT NOT NULL,
    kyc_submission_id    TEXT NOT NULL,
    ai_request_log_id    TEXT,
    analysis_type        TEXT NOT NULL,
    preliminary_profile  TEXT,
    confidence           REAL,
    result_json          TEXT NOT NULL,
    created_at_utc       TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES advisory_cases(case_id),
    FOREIGN KEY (kyc_submission_id) REFERENCES kyc_submissions(kyc_submission_id),
    FOREIGN KEY (ai_request_log_id) REFERENCES ai_request_logs(request_id)
);

CREATE INDEX idx_ai_profile_analyses_case_id
    ON ai_profile_analyses(case_id);

CREATE INDEX idx_ai_profile_analyses_kyc_submission_id
    ON ai_profile_analyses(kyc_submission_id);

CREATE INDEX idx_ai_profile_analyses_ai_request_log_id
    ON ai_profile_analyses(ai_request_log_id);
