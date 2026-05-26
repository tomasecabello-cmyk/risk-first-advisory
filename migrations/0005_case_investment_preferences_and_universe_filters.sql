-- ─────────────────────────────────────────────────────────────────────────────
-- 0005 — Case-scoped investment preferences + universe filter runs
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Dos tablas combinadas en una sola migration porque van siempre juntas:
-- un universe_filter_run usa unas investment_preferences específicas del case.
--
-- case_investment_preferences:
--   - Preferencias del cliente sobre instrumentos (manual o AI-extracted).
--   - Versionado vía is_current: cada nuevo POST marca las previas =0.
--   - structured_preferences_json es la fuente de verdad para el filter engine.
--   - natural_language_preferences se preserva como contexto (puede ser NULL
--     cuando el caller manda solo structured).
--   - ai_request_log_id NULL si la entrada fue manual (no llamada a IA).
--
-- case_universe_filter_runs:
--   - Resultado de aplicar PreferenceFilterEngine al universo CSV con una
--     preference del case.
--   - is_current refleja "este es el filter vigente"; cada nuevo run marca
--     los anteriores =0.
--   - source_universe identifica el universo fuente (hoy fixture CSV).
--   - Listas se persisten como canonical JSON.
--
-- No incluir BEGIN/COMMIT explícitos.
-- ─────────────────────────────────────────────────────────────────────────────


CREATE TABLE case_investment_preferences (
    preference_id                TEXT PRIMARY KEY,
    case_id                      TEXT NOT NULL,
    source                       TEXT NOT NULL,
    natural_language_preferences TEXT,
    structured_preferences_json  TEXT NOT NULL,
    ai_request_log_id            TEXT,
    created_by_advisor_id        TEXT,
    created_at_utc               TEXT NOT NULL,
    is_current                   INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (case_id) REFERENCES advisory_cases(case_id),
    FOREIGN KEY (ai_request_log_id) REFERENCES ai_request_logs(request_id),
    FOREIGN KEY (created_by_advisor_id) REFERENCES advisors(advisor_id)
);

CREATE INDEX idx_case_investment_preferences_case_id
    ON case_investment_preferences(case_id);

CREATE INDEX idx_case_investment_preferences_ai_request_log_id
    ON case_investment_preferences(ai_request_log_id);

CREATE INDEX idx_case_investment_preferences_created_by_advisor_id
    ON case_investment_preferences(created_by_advisor_id);


CREATE TABLE case_universe_filter_runs (
    filter_run_id              TEXT PRIMARY KEY,
    case_id                    TEXT NOT NULL,
    preference_id              TEXT,
    source_universe            TEXT NOT NULL,
    eligible_instruments_json  TEXT NOT NULL,
    exclusions_json            TEXT NOT NULL,
    applied_filters_json       TEXT NOT NULL,
    warnings_json              TEXT NOT NULL,
    eligible_count             INTEGER NOT NULL,
    excluded_count             INTEGER NOT NULL,
    total_count                INTEGER NOT NULL,
    created_by_advisor_id      TEXT,
    created_at_utc             TEXT NOT NULL,
    is_current                 INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (case_id) REFERENCES advisory_cases(case_id),
    FOREIGN KEY (preference_id) REFERENCES case_investment_preferences(preference_id),
    FOREIGN KEY (created_by_advisor_id) REFERENCES advisors(advisor_id)
);

CREATE INDEX idx_case_universe_filter_runs_case_id
    ON case_universe_filter_runs(case_id);

CREATE INDEX idx_case_universe_filter_runs_preference_id
    ON case_universe_filter_runs(preference_id);

CREATE INDEX idx_case_universe_filter_runs_created_by_advisor_id
    ON case_universe_filter_runs(created_by_advisor_id);
