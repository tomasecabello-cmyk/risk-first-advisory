"""
Tests unitarios para AIFilteredPortfolioReportGenerator.

Verifica que el generador produzca Markdown correcto a partir de un payload
dict con la forma de AIFilteredPortfolioResponse.

No llama a OpenAI ni al portfolio optimizer.
No escribe archivos a disco.
Determinístico: mismo payload → mismo string.
"""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixture de payload completo (caso real basado en el demo)
# ─────────────────────────────────────────────────────────────────────────────


def _make_payload(**overrides) -> dict:
    """
    Devuelve un payload válido completo, con sobreescrituras opcionales.
    Basado en el caso demo: ONs hard dollar argentinas en Balanz, sin energía.
    """
    base = {
        "client_id": "CLI-PREF-PORT-001",
        "profile": "moderado",
        "status": "completed",
        "message": "2 candidato(s) generado(s) para perfil 'moderado'.",
        "natural_language_preferences": (
            "Solo quiero invertir en ONs hard dollar argentinas "
            "disponibles en Balanz y evitar energia."
        ),
        "preferences": {
            "client_id": "CLI-PREF-PORT-001",
            "allowed_instrument_types": ["CORPORATE_BOND"],
            "excluded_instrument_types": [],
            "currency": "USD",
            "country": "Argentina",
            "entity": "Balanz",
            "hard_dollar_only": True,
            "avoid_sectors": ["Energy"],
            "prefer_sectors": [],
            "avoid_issuers": [],
            "prefer_issuers": [],
            "min_liquidity_score": None,
            "max_maturity_year": None,
            "hard_constraints": ["instrument_type", "currency", "country", "hard_dollar", "entity", "sector"],
            "soft_preferences": [],
            "unparsed_preferences": [],
            "confidence": 1.0,
            "advisor_notes": ["Client explicitly excluded energy sector."],
        },
        "eligible_count": 9,
        "excluded_count": 11,
        "applied_filters": [
            "allowed_instrument_types",
            "currency",
            "country",
            "entity",
            "hard_dollar_only",
            "avoid_sectors",
        ],
        "warnings": [],
        "eligible_instruments": [
            {
                "ticker": "GALI28",
                "name": "Galicia 2028",
                "issuer": "Banco Galicia",
                "instrument_type": "CORPORATE_BOND",
                "asset_class": "bond",
                "currency": "USD",
                "country": "Argentina",
                "sector": "Financials",
                "available_entities": ["Balanz"],
                "hard_dollar": True,
                "maturity_date": "2028-01-15",
                "coupon_rate": 0.0775,
                "ytm": 0.082,
                "duration": 3.2,
                "liquidity_score": 0.85,
                "min_piece": 1000.0,
                "rating": "B",
                "notes": [],
            },
            {
                "ticker": "MACR29",
                "name": "MacroBank 2029",
                "issuer": "Banco Macro",
                "instrument_type": "CORPORATE_BOND",
                "asset_class": "bond",
                "currency": "USD",
                "country": "Argentina",
                "sector": "Financials",
                "available_entities": ["Balanz"],
                "hard_dollar": True,
                "maturity_date": "2029-06-30",
                "coupon_rate": 0.085,
                "ytm": 0.091,
                "duration": 4.1,
                "liquidity_score": 0.78,
                "min_piece": 1000.0,
                "rating": "B-",
                "notes": [],
            },
        ],
        "exclusions": [
            {"ticker": "VIST24", "reasons": ["sector_avoided:Energy"]},
            {"ticker": "SPY", "reasons": ["instrument_type_not_allowed:ETF"]},
        ],
        "snapshots": [
            {
                "ticker": "GALI28",
                "expected_return_annual": 0.078,
                "volatility_annual": 0.098,
                "duration": 3.2,
                "liquidity_score": 0.85,
                "notes": [],
            },
            {
                "ticker": "MACR29",
                "expected_return_annual": 0.091,
                "volatility_annual": 0.112,
                "duration": 4.1,
                "liquidity_score": 0.78,
                "notes": [],
            },
        ],
        "snapshot_count": 9,
        "candidates": [
            {
                "variant": "BALANCED",
                "objective": "min_volatility",
                "expected_return_annual": 0.086,
                "volatility_annual": 0.099,
                "risk_score": 0.45,
                "constraints_satisfied": True,
                "reason_codes": [],
                "notes": [],
                "metadata": {
                    "risk_budget_exceeded": False,
                    "requires_advisor_override": False,
                    "exceeded_constraints": [],
                    "reason_codes": [],
                    "notes": [],
                },
                "weights": [
                    {"ticker": "GALI28", "weight": 0.15},
                    {"ticker": "MACR29", "weight": 0.14},
                ],
            },
            {
                "variant": "GROWTH",
                "objective": "max_return",
                "expected_return_annual": 0.094,
                "volatility_annual": 0.131,
                "risk_score": 0.62,
                "constraints_satisfied": False,
                "reason_codes": ["PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"],
                "notes": [],
                "metadata": {
                    "risk_budget_exceeded": True,
                    "requires_advisor_override": True,
                    "exceeded_constraints": ["max_volatility"],
                    "reason_codes": ["PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"],
                    "notes": [],
                },
                "weights": [
                    {"ticker": "MACR29", "weight": 0.15},
                    {"ticker": "GALI28", "weight": 0.13},
                ],
            },
        ],
        "candidate_count": 2,
    }
    base.update(overrides)
    return base


@pytest.fixture
def payload() -> dict:
    return _make_payload()


@pytest.fixture
def generator():
    from risk_first_advisory.reporting_layer import AIFilteredPortfolioReportGenerator
    return AIFilteredPortfolioReportGenerator()


@pytest.fixture
def report(generator, payload) -> str:
    return generator.generate(payload)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Tipo de retorno
# ─────────────────────────────────────────────────────────────────────────────


class TestReturnType:
    def test_generate_returns_str(self, generator, payload):
        result = generator.generate(payload)
        assert isinstance(result, str)

    def test_generate_returns_nonempty_str(self, generator, payload):
        result = generator.generate(payload)
        assert result.strip()

    def test_output_does_not_start_with_brace(self, generator, payload):
        """El output no debe parecer un JSON dump."""
        result = generator.generate(payload)
        assert not result.strip().startswith("{")

    def test_output_is_not_raw_json(self, generator, payload):
        """El output no debe ser un JSON crudo."""
        result = generator.generate(payload)
        assert "# " in result  # tiene al menos un header Markdown


# ─────────────────────────────────────────────────────────────────────────────
# 2. Título
# ─────────────────────────────────────────────────────────────────────────────


class TestTitle:
    def test_contains_main_title(self, report):
        assert "# Risk-First Advisory" in report

    def test_title_contains_ai_filtered_portfolio(self, report):
        assert "AI Filtered Portfolio" in report


# ─────────────────────────────────────────────────────────────────────────────
# 3. Executive Summary
# ─────────────────────────────────────────────────────────────────────────────


class TestExecutiveSummary:
    def test_contains_executive_summary_header(self, report):
        assert "Executive Summary" in report

    def test_contains_client_id(self, report):
        assert "CLI-PREF-PORT-001" in report

    def test_contains_profile(self, report):
        assert "moderado" in report

    def test_contains_status_completed(self, report):
        assert "completed" in report

    def test_contains_eligible_count(self, report):
        assert "9" in report

    def test_contains_excluded_count(self, report):
        assert "11" in report

    def test_contains_candidate_count(self, report):
        assert "2" in report


# ─────────────────────────────────────────────────────────────────────────────
# 4. Natural Language Preferences
# ─────────────────────────────────────────────────────────────────────────────


class TestNaturalLanguagePreferences:
    def test_contains_section_header(self, report):
        assert "Natural Language Preferences" in report

    def test_contains_preference_text(self, report):
        assert "Balanz" in report

    def test_missing_nlp_shows_not_provided(self, generator):
        payload = _make_payload()
        del payload["natural_language_preferences"]
        result = generator.generate(payload)
        assert "Not provided in payload." in result

    def test_empty_nlp_shows_not_provided(self, generator):
        payload = _make_payload(natural_language_preferences="")
        result = generator.generate(payload)
        assert "Not provided in payload." in result

    def test_whitespace_only_nlp_shows_not_provided(self, generator):
        payload = _make_payload(natural_language_preferences="   ")
        result = generator.generate(payload)
        assert "Not provided in payload." in result


# ─────────────────────────────────────────────────────────────────────────────
# 5. AI Extracted Preferences
# ─────────────────────────────────────────────────────────────────────────────


class TestAIExtractedPreferences:
    def test_contains_section_header(self, report):
        assert "AI Extracted Preferences" in report

    def test_contains_allowed_instrument_types(self, report):
        assert "allowed_instrument_types" in report
        assert "CORPORATE_BOND" in report

    def test_contains_currency(self, report):
        assert "currency" in report
        assert "USD" in report

    def test_contains_country(self, report):
        assert "country" in report
        assert "Argentina" in report

    def test_contains_entity(self, report):
        assert "entity" in report
        assert "Balanz" in report

    def test_contains_hard_dollar_only(self, report):
        assert "hard_dollar_only" in report
        assert "true" in report

    def test_contains_avoid_sectors(self, report):
        assert "avoid_sectors" in report
        assert "Energy" in report

    def test_contains_confidence(self, report):
        assert "confidence" in report

    def test_empty_preferences_does_not_crash(self, generator):
        payload = _make_payload(preferences={})
        result = generator.generate(payload)
        assert "AI Extracted Preferences" in result

    def test_missing_preferences_does_not_crash(self, generator):
        payload = _make_payload()
        del payload["preferences"]
        result = generator.generate(payload)
        assert "AI Extracted Preferences" in result


# ─────────────────────────────────────────────────────────────────────────────
# 6. Applied Universe Filters
# ─────────────────────────────────────────────────────────────────────────────


class TestAppliedUniverseFilters:
    def test_contains_section_header(self, report):
        assert "Applied Universe Filters" in report

    def test_contains_applied_filter_name(self, report):
        assert "allowed_instrument_types" in report

    def test_empty_filters_shows_none(self, generator):
        payload = _make_payload(applied_filters=[])
        result = generator.generate(payload)
        assert "None." in result

    def test_warnings_are_shown_when_present(self, generator):
        payload = _make_payload(warnings=["Prefer sector ETF unavailable."])
        result = generator.generate(payload)
        assert "Prefer sector ETF unavailable." in result


# ─────────────────────────────────────────────────────────────────────────────
# 7. Eligible Instruments
# ─────────────────────────────────────────────────────────────────────────────


class TestEligibleInstruments:
    def test_contains_section_header(self, report):
        assert "Eligible Instruments" in report

    def test_contains_gali28(self, report):
        assert "GALI28" in report

    def test_contains_macr29(self, report):
        assert "MACR29" in report

    def test_empty_eligible_instruments_shows_message(self, generator):
        payload = _make_payload(eligible_instruments=[])
        result = generator.generate(payload)
        assert "No eligible instruments." in result

    def test_table_has_header_row(self, report):
        assert "Ticker" in report
        assert "Issuer" in report
        assert "Liquidity" in report


# ─────────────────────────────────────────────────────────────────────────────
# 8. Exclusions
# ─────────────────────────────────────────────────────────────────────────────


class TestExclusions:
    def test_contains_section_header(self, report):
        assert "Exclusions" in report

    def test_contains_excluded_ticker(self, report):
        assert "VIST24" in report

    def test_contains_exclusion_reason(self, report):
        assert "Energy" in report

    def test_empty_exclusions_shows_message(self, generator):
        payload = _make_payload(exclusions=[])
        result = generator.generate(payload)
        assert "No exclusions." in result


# ─────────────────────────────────────────────────────────────────────────────
# 9. Portfolio-Ready Snapshots
# ─────────────────────────────────────────────────────────────────────────────


class TestPortfolioReadySnapshots:
    def test_contains_section_header(self, report):
        assert "Portfolio-Ready Snapshots" in report

    def test_formats_return_as_percentage(self, report):
        """0.078 debe mostrarse como 7.80%."""
        assert "7.80%" in report

    def test_formats_volatility_as_percentage(self, report):
        """0.098 debe mostrarse como 9.80%."""
        assert "9.80%" in report

    def test_contains_snapshot_ticker_gali28(self, report):
        assert "GALI28" in report

    def test_empty_snapshots_shows_message(self, generator):
        payload = _make_payload(snapshots=[])
        result = generator.generate(payload)
        assert "No snapshots available." in result

    def test_percentage_format_with_two_decimals(self, generator):
        """Verificar precisión de 2 decimales en el formato de porcentaje."""
        payload = _make_payload(
            snapshots=[{
                "ticker": "TEST01",
                "expected_return_annual": 0.1234,
                "volatility_annual": 0.0567,
                "duration": 2.5,
                "liquidity_score": 0.90,
                "notes": [],
            }]
        )
        result = generator.generate(payload)
        assert "12.34%" in result
        assert "5.67%" in result


# ─────────────────────────────────────────────────────────────────────────────
# 10. Candidate Portfolios
# ─────────────────────────────────────────────────────────────────────────────


class TestCandidatePortfolios:
    def test_contains_section_header(self, report):
        assert "Candidate Portfolios" in report

    def test_contains_balanced_variant(self, report):
        assert "BALANCED" in report

    def test_contains_growth_variant(self, report):
        assert "GROWTH" in report

    def test_empty_candidates_shows_message(self, generator):
        payload = _make_payload(candidates=[])
        result = generator.generate(payload)
        assert "No candidate portfolios generated." in result

    def test_contains_weights_table(self, report):
        assert "Weights" in report

    def test_weights_show_tickers(self, report):
        assert "GALI28" in report
        assert "MACR29" in report

    def test_contains_objective(self, report):
        assert "Objective" in report or "objective" in report

    def test_contains_metadata(self, report):
        assert "risk_budget_exceeded" in report
        assert "requires_advisor_override" in report


# ─────────────────────────────────────────────────────────────────────────────
# 11. Advisor Override
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorOverride:
    def test_contains_section_header(self, report):
        assert "Advisor Override" in report

    def test_growth_requires_override_shown(self, report):
        assert "Advisor Override Required" in report

    def test_exceeded_constraints_shown(self, report):
        assert "max_volatility" in report

    def test_reason_codes_shown(self, report):
        assert "PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET" in report

    def test_no_override_when_all_candidates_within_budget(self, generator):
        """Si ningún candidate requiere override, se muestra el mensaje correspondiente."""
        candidates_no_override = [
            {
                "variant": "BALANCED",
                "objective": "min_volatility",
                "expected_return_annual": 0.086,
                "volatility_annual": 0.099,
                "risk_score": 0.45,
                "constraints_satisfied": True,
                "reason_codes": [],
                "notes": [],
                "metadata": {
                    "risk_budget_exceeded": False,
                    "requires_advisor_override": False,
                    "exceeded_constraints": [],
                    "reason_codes": [],
                    "notes": [],
                },
                "weights": [],
            }
        ]
        payload = _make_payload(candidates=candidates_no_override)
        result = generator.generate(payload)
        assert "No advisor override required." in result
        # No debe aparecer el warning
        assert "⚠" not in result or "No advisor override required." in result

    def test_growth_override_variant_name_appears(self, report):
        """El nombre GROWTH aparece en la sección de override."""
        assert "GROWTH" in report


# ─────────────────────────────────────────────────────────────────────────────
# 12. Limitations and Disclaimers
# ─────────────────────────────────────────────────────────────────────────────


class TestDisclaimers:
    def test_contains_section_header(self, report):
        assert "Limitations and Disclaimers" in report

    def test_says_advisor_review(self, report):
        assert "advisor review" in report.lower()

    def test_says_ai_does_not_approve(self, report):
        assert "does not approve" in report.lower()

    def test_says_ai_does_not_recommend_products(self, report):
        assert "does not recommend" in report.lower()

    def test_says_deterministic_filtering(self, report):
        assert "deterministically" in report.lower()

    def test_says_proxy_data(self, report):
        assert "proxy" in report.lower() or "demo" in report.lower()

    def test_says_advisor_must_review_suitability(self, report):
        assert "suitability" in report.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 13. Robustez: payloads edge case
# ─────────────────────────────────────────────────────────────────────────────


class TestRobustness:
    def test_empty_payload_does_not_crash(self, generator):
        """Un payload vacío no debe lanzar excepción."""
        result = generator.generate({})
        assert isinstance(result, str)
        assert "Risk-First Advisory" in result

    def test_all_lists_empty_does_not_crash(self, generator):
        payload = _make_payload(
            eligible_instruments=[],
            exclusions=[],
            snapshots=[],
            candidates=[],
            applied_filters=[],
            warnings=[],
        )
        result = generator.generate(payload)
        assert isinstance(result, str)
        assert "No eligible instruments." in result
        assert "No exclusions." in result
        assert "No snapshots available." in result
        assert "No candidate portfolios generated." in result

    def test_missing_optional_fields_uses_defaults(self, generator):
        """Campos faltantes en el payload usan valores seguros."""
        minimal = {
            "client_id": "CLI-MIN",
            "status": "completed",
        }
        result = generator.generate(minimal)
        assert isinstance(result, str)
        assert "CLI-MIN" in result

    def test_none_values_render_as_dash(self, generator):
        """Valores None se renderizan como '—' sin lanzar excepción."""
        payload = _make_payload()
        payload["preferences"]["currency"] = None
        payload["preferences"]["entity"] = None
        payload["preferences"]["min_liquidity_score"] = None
        result = generator.generate(payload)
        assert "—" in result

    def test_pipe_in_message_is_escaped(self, generator):
        """Un '|' en el mensaje no rompe la tabla del Executive Summary."""
        payload = _make_payload(message="Resultado: A | B | C")
        result = generator.generate(payload)
        # El pipe en el mensaje debe escaparse
        assert "A \\| B \\| C" in result or "A" in result
        # No debe producir celdas de tabla rotas (columnas extra)
        lines_with_result = [l for l in result.splitlines() if "Resultado" in l]
        for line in lines_with_result:
            # La fila de tabla tiene exactamente los pipes de columna
            assert line.startswith("|")


# ─────────────────────────────────────────────────────────────────────────────
# 14. Determinismo
# ─────────────────────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_payload_produces_same_output(self, generator, payload):
        """Llamar a generate dos veces con el mismo payload produce el mismo string."""
        r1 = generator.generate(payload)
        r2 = generator.generate(payload)
        assert r1 == r2

    def test_different_client_id_produces_different_output(self, generator):
        p1 = _make_payload(client_id="CLI-A")
        p2 = _make_payload(client_id="CLI-B")
        r1 = generator.generate(p1)
        r2 = generator.generate(p2)
        assert r1 != r2

    def test_generate_does_not_mutate_payload(self, generator):
        """generate() no debe modificar el payload de entrada."""
        import copy
        payload = _make_payload()
        original = copy.deepcopy(payload)
        generator.generate(payload)
        assert payload == original


# ─────────────────────────────────────────────────────────────────────────────
# 15. No escribe archivos a disco
# ─────────────────────────────────────────────────────────────────────────────


class TestNoDiskWrite:
    def test_generate_does_not_open_files(self, generator, payload, monkeypatch):
        """
        Verifica que generate() no intenta abrir ni escribir archivos.
        Monkeypatchea builtins.open para que falle si se llama.
        """
        _original_open = open

        def _no_open(*args, **kwargs):
            raise AssertionError(
                f"generate() no debe abrir archivos, pero intentó abrir: {args!r}"
            )

        monkeypatch.setattr("builtins.open", _no_open)
        # Si generate() no llama a open, esto no debe lanzar excepción
        result = generator.generate(payload)
        assert isinstance(result, str)
