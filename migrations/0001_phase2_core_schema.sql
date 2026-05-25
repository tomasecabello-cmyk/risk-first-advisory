-- ─────────────────────────────────────────────────────────────────────────────
-- 0001 — Phase 2 core schema
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Crea las entidades de primera clase de Fase 2:
--   firms, advisors, clients, advisory_cases, audit_events, ai_request_logs.
--
-- INVARIANTES:
--   - NO toca records / counters (esas siguen siendo de SQLitePersistenceStore).
--   - Todas las tablas usan TEXT para IDs (prefijo + opaque, sin autoincrement).
--   - FK declaradas; el enforcement depende de PRAGMA foreign_keys = ON
--     en la conexión que use la app/tests.
--   - is_active / booleans se modelan como INTEGER 0/1 (convención SQLite).
--   - Timestamps son strings ISO-8601 UTC con sufijo "Z" (alineado con
--     SQLitePersistenceStore._now_utc).
--
-- IMPORTANTE para futuras migraciones:
--   - No incluir BEGIN / COMMIT explícitos: el runner (scripts/migrate.py)
--     envuelve cada archivo en su propia transacción y agrega la fila
--     correspondiente en schema_migrations.
--   - Evitar literales con `;` en string literals; el splitter del runner
--     es simple (comments stripped + split por `;`).
-- ─────────────────────────────────────────────────────────────────────────────


-- ─── firms ───────────────────────────────────────────────────────────────────
CREATE TABLE firms (
    firm_id        TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL,
    country        TEXT NOT NULL,
    is_active      INTEGER NOT NULL DEFAULT 1,
    created_at_utc TEXT NOT NULL
);


-- ─── advisors ────────────────────────────────────────────────────────────────
CREATE TABLE advisors (
    advisor_id     TEXT PRIMARY KEY,
    firm_id        TEXT NOT NULL,
    display_name   TEXT NOT NULL,
    email          TEXT NOT NULL,
    roles_json     TEXT NOT NULL,
    is_active      INTEGER NOT NULL DEFAULT 1,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (firm_id) REFERENCES firms(firm_id)
);

CREATE INDEX idx_advisors_firm_id ON advisors(firm_id);


-- ─── clients ─────────────────────────────────────────────────────────────────
CREATE TABLE clients (
    client_id          TEXT PRIMARY KEY,
    firm_id            TEXT NOT NULL,
    primary_advisor_id TEXT NOT NULL,
    display_name       TEXT NOT NULL,
    external_ref       TEXT,
    jurisdiction       TEXT NOT NULL,
    preferred_currency TEXT NOT NULL,
    is_active          INTEGER NOT NULL DEFAULT 1,
    created_at_utc     TEXT NOT NULL,
    FOREIGN KEY (firm_id) REFERENCES firms(firm_id),
    FOREIGN KEY (primary_advisor_id) REFERENCES advisors(advisor_id)
);

CREATE INDEX idx_clients_firm_id ON clients(firm_id);
CREATE INDEX idx_clients_primary_advisor_id ON clients(primary_advisor_id);


-- ─── advisory_cases ──────────────────────────────────────────────────────────
CREATE TABLE advisory_cases (
    case_id                         TEXT PRIMARY KEY,
    firm_id                         TEXT NOT NULL,
    client_id                       TEXT NOT NULL,
    lead_advisor_id                 TEXT NOT NULL,
    status                          TEXT NOT NULL,
    title                           TEXT NOT NULL,
    current_kyc_submission_id       TEXT,
    current_approved_profile_id     TEXT,
    current_portfolio_selection_id  TEXT,
    created_at_utc                  TEXT NOT NULL,
    closed_at_utc                   TEXT,
    FOREIGN KEY (firm_id) REFERENCES firms(firm_id),
    FOREIGN KEY (client_id) REFERENCES clients(client_id),
    FOREIGN KEY (lead_advisor_id) REFERENCES advisors(advisor_id)
);

CREATE INDEX idx_advisory_cases_firm_id ON advisory_cases(firm_id);
CREATE INDEX idx_advisory_cases_client_id ON advisory_cases(client_id);
CREATE INDEX idx_advisory_cases_lead_advisor_id ON advisory_cases(lead_advisor_id);
CREATE INDEX idx_advisory_cases_status ON advisory_cases(status);


-- ─── audit_events ────────────────────────────────────────────────────────────
-- Cadena append-only por caso. previous_hash + event_hash permiten verificar
-- integridad de la secuencia (ver Fase 2 §6 — hash chain).
CREATE TABLE audit_events (
    event_id         TEXT PRIMARY KEY,
    case_id          TEXT NOT NULL,
    sequence         INTEGER NOT NULL,
    event_type       TEXT NOT NULL,
    actor_advisor_id TEXT,
    actor_role       TEXT NOT NULL,
    payload_json     TEXT NOT NULL,
    payload_hash     TEXT NOT NULL,
    previous_hash    TEXT,
    event_hash       TEXT NOT NULL,
    created_at_utc   TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES advisory_cases(case_id),
    FOREIGN KEY (actor_advisor_id) REFERENCES advisors(advisor_id),
    UNIQUE (case_id, sequence)
);

-- Index explícito sobre (case_id, sequence) además del implícito generado por
-- UNIQUE. Costo mínimo y hace explícita la intención de uso: el verificador
-- recorre los eventos de un case en orden de sequence ascendente.
CREATE INDEX idx_audit_events_case_sequence ON audit_events(case_id, sequence);


-- ─── ai_request_logs ─────────────────────────────────────────────────────────
-- Log de cada llamada a OpenAI. input_redacted_json mantiene el payload con
-- PII enmascarada (ver Fase 2 §7); input_hash se computa sobre el original
-- para correlación sin exponer texto libre.
CREATE TABLE ai_request_logs (
    request_id              TEXT PRIMARY KEY,
    case_id                 TEXT,
    requested_by_advisor_id TEXT,
    endpoint                TEXT NOT NULL,
    model                   TEXT NOT NULL,
    prompt_version          TEXT NOT NULL,
    input_redacted_json     TEXT NOT NULL,
    input_hash              TEXT NOT NULL,
    raw_response_json       TEXT,
    validation_status       TEXT NOT NULL,
    latency_ms              INTEGER,
    prompt_tokens           INTEGER,
    completion_tokens       INTEGER,
    error_message           TEXT,
    created_at_utc          TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES advisory_cases(case_id),
    FOREIGN KEY (requested_by_advisor_id) REFERENCES advisors(advisor_id)
);

CREATE INDEX idx_ai_request_logs_case_id ON ai_request_logs(case_id);
CREATE INDEX idx_ai_request_logs_requested_by_advisor_id ON ai_request_logs(requested_by_advisor_id);
