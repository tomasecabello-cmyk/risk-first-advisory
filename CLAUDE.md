# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Risk-First Advisory is a supervised financial-advisory engine: the AI proposes, the
advisor decides. A risk-first workflow (suitability, governance, ESG, data quality,
portfolio feasibility) is verified before any portfolio is generated. Python/FastAPI +
SQLite backend with a static (no-build) HTML/CSS/JS demo frontend. Not production-ready;
local demo only.

## Commands

Windows PowerShell. Use the venv at `.venv`.

```powershell
.\.venv\Scripts\Activate.ps1          # activate (create once: python -m venv .venv; pip install -e ".[dev]")

python -m pytest -q                    # full suite (~3100 tests)
python -m pytest tests/unit/test_risk_gap.py -q              # one file
python -m pytest tests/unit/test_risk_gap.py::test_name -q   # one test
ruff check src tests scripts           # lint (large pre-existing backlog — see note below)
mypy src                               # types (strict=false; ~5 pre-existing errors)

python scripts/bootstrap_local_demo.py            # migrate + seed + validate (idempotent, no API key)
python scripts/migrate.py                          # apply migrations only
python scripts/seed_demo_data.py                   # seed demo firm/advisor/client/case
python scripts/run_case_workflow_smoke_check.py    # end-to-end via TestClient, mocked AI, no server, no key. Exit 0 = PASS

python -m uvicorn risk_first_advisory.api_layer.main:app --reload   # backend on :8000 (Swagger at /docs)
python -m http.server 5500 -d frontend                              # static frontend on :5500
```

- **`ruff` / `mypy` have a large pre-existing backlog** (hundreds of ruff findings, ~5 mypy). They are configured (`pyproject.toml`) but not a passing gate. New code should be clean; do not try to fix the whole backlog in an unrelated change.
- **`OPENAI_API_KEY`** is required only for the real `/ai/*` and `/cases/{id}/ai/profile-analysis` paths. Tests and the smoke check use deterministic mocks.
- **`RFA_DEMO_MODE=1`** before uvicorn activates a deterministic, key-free profile client so the guided demo (incl. the Risk Gap step) runs without `OPENAI_API_KEY`. Without the env var the case AI endpoint still requires a real key.
- Frontend API base is hardcoded to `http://127.0.0.1:8000` in `frontend/js/common.js`. Run the backend on 8000.

## Architecture

Layered package `src/risk_first_advisory/`. Data flows through layers in a fixed order; the
order is compliance-significant, not incidental.

- **`kyc/`** — `KYCData`, `FinancialGoal`, `ESGProfile` (the standardized client inputs).
- **`ai_layer/`** — `OpenAIProfileClient` (real OpenAI; interprets KYC, flags contradictions, proposes a *preliminary* profile — never approves), `MockAIClient` (scripted, for tests/smoke), `risk_gap.py` (pure deterministic mapper: contradictions → Risk Gap flag).
- **`rules_layer/`** — governance, instrument suitability, ESG, `goal_feasibility`, `risk_budget`, `reason_codes`.
- **`universe_layer/`** — preference + eligibility filters over the instrument universe.
- **`portfolio_layer/`** — feasibility checker then optimizer (the optimizer only sees the already-filtered tickers; it makes no governance/ESG/suitability decisions).
- **`reporting_layer/`** — Markdown report generators (they format already-computed snapshots; they never recalculate or call the optimizer/OpenAI).
- **`workflow_layer/`** — `AdvisoryWorkflowCoordinator` orchestrates the legacy end-to-end flow.
- **`persistence_layer/`** — SQLite entity store + per-entity repositories (case-scoped data).
- **`api_layer/`** — `main.py` (FastAPI app, ~all endpoints) + `schemas.py` (Pydantic). `main.py` is large; navigate by endpoint path.
- **`config_layer/`** — risk assumptions, advisor token map. **`human_layer/`** — scripted advisor interface. **`engine.py`** — top-level wiring.

Two API surfaces:
1. **Legacy MVP demos** — `/ai/*`, `/live/*`, `/workflow/run`. Stateless-ish, use `MockAIClient` via `_DEFAULT_AI_SCRIPT`.
2. **Phase 2 case-scoped workflow** — `/cases/*`, persisted to SQLite (`data/demo_api.db`), 9 migrations in `migrations/`. The flow: firm → advisor → client → case → KYC → AI profile analysis → advisor profile approval → investment preferences → universe filter → portfolio proposal → (override approval) → portfolio selection → report → audit. The advisor-facing guided demo (`frontend/js/investor-demo.js`) drives this flow against `/cases/*`.

**Filter pipeline order (fixed, compliance-significant):** governance → suitability → ESG → market data + data quality. Reordering or skipping is a compliance violation, not a refactor.

**Audit & compliance plumbing (do not weaken):**
- Every case-scoped mutation appends an `AuditEvent` with a SHA-256 hash chain (`previous_hash` + `event_hash` over canonical JSON). `GET /cases/{id}/audit/verify` must return `is_intact=true` after any valid flow.
- `AIRequestLog` redacts PII (`redact_ai_input()`) before persisting any OpenAI payload; API keys redacted everywhere, `client_id` hashed.
- All case-scoped entities are **append-only at the API level** — no update/delete endpoints; state changes are new rows (`is_current` / version bump).

**Auth is dev-only:** Bearer tokens from a YAML map (`config/advisor_tokens.yaml` or `ADVISOR_TOKENS_FILE`), with a built-in dev fallback (`dev-advisor-token`, `dev-compliance-token`). RBAC roles: `admin` / `advisor` / `compliance` / `viewer`. No JWT/IdP, no firm-level access control. NOT production auth.

## Critical invariants (read `docs/INVARIANTS.md` before changing workflow/compliance code)

These are design contracts; violating them breaks compliance/traceability in ways unit
tests may not catch. The highest-stakes ones:

- **AI proposes, advisor decides** (I-001, I-016, I-019): no AI output is binding. A profile becomes approved only via an explicit `POST /cases/{id}/profile-approval`; a portfolio is chosen only via `POST /cases/{id}/portfolio-selection`. Both are human endpoints.
- **No `return_target_annual_pct` in `KYCData`** (I-003): target return is derived from `FinancialGoal` only, never declared in KYC (would create circularity). `declared_return_expectation_pct` exists but is informational only — never an input to profile/risk-budget/feasibility (I-004).
- **Filter order is fixed** (I-014). **Reports format, never recalculate** (I-013, I-020).
- **Audit chain stays verifiable** (I-021); **PII always redacted** in AI logs (I-022); **append-only at API level** (I-023).

The `docs/` folder is the source of truth, keep it in sync when you change behavior:
`INVARIANTS.md` (I-NNN), `DESIGN_DECISIONS.md` (DD-NNN), `REASON_CODES.md`, `ARCHITECTURE.md`,
`COMPLIANCE_NOTES.md` (limits/disclaimers), `PROMPT_DESIGN.md`.

## Conventions

- **Bilingual by design:** user-facing UI copy is Spanish; technical identifiers stay English (`case_id`, `firm_id`, endpoint paths, role names, JSON keys, `reason_codes`, profile enums like `moderado`). Do not translate identifiers.
- **Risk Gap** (`ai_layer/risk_gap.py` + `RiskGap` schema): a *flag of inconsistency* between the declared profile and stress-scenario answers, with confirmation questions for the advisor. It is explicitly NOT a measured "behavioral profile" — keep that framing (see `docs/METHODOLOGY_NOTES.md`).
- SQLite only (`data/demo_api.db`, gitignored). No production market-data provider — the universe is a CSV fixture (`tests/fixtures/universe/`). No remote configured; work happens on `master`.
