"""
Unit tests for AI request log redaction + input hashing.

No DB, no HTTP — solo helpers de `entity_repository`.

Cubre:
    - client_id → hash corto.
    - Texto libre (open_*, natural_language_preferences, kyc_context,
      previous_profile_analysis) reemplazado por `<REDACTED:text_N_chars>`.
    - Campos estructurados (scores, montos, currency, etc.) conservados en
      claro.
    - API keys (sk-..., Bearer ...) siempre redactadas.
    - input_hash determinístico (sort_keys, no whitespace, ensure_ascii=False).
"""

from __future__ import annotations

import hashlib
import json

import pytest

from risk_first_advisory.persistence_layer.entity_repository import (
    compute_input_hash,
    redact_ai_input,
    redact_ai_output,
)

# ─────────────────────────────────────────────────────────────────────────────
# client_id redaction
# ─────────────────────────────────────────────────────────────────────────────


class TestClientIdRedaction:
    def test_client_id_is_hashed(self) -> None:
        out = redact_ai_input({"client_id": "C-12345"})
        assert out["client_id"].startswith("client_")
        assert out["client_id"] != "C-12345"

    def test_client_id_hash_is_short(self) -> None:
        out = redact_ai_input({"client_id": "C-12345"})
        # formato: client_<8 hex chars>
        assert len(out["client_id"]) == len("client_") + 8

    def test_client_id_hash_is_deterministic(self) -> None:
        a = redact_ai_input({"client_id": "C-XYZ"})
        b = redact_ai_input({"client_id": "C-XYZ"})
        assert a["client_id"] == b["client_id"]

    def test_different_client_ids_yield_different_hashes(self) -> None:
        a = redact_ai_input({"client_id": "A"})
        b = redact_ai_input({"client_id": "B"})
        assert a["client_id"] != b["client_id"]


# ─────────────────────────────────────────────────────────────────────────────
# Free-text redaction
# ─────────────────────────────────────────────────────────────────────────────


class TestFreeTextRedaction:
    def test_natural_language_preferences_redacted(self) -> None:
        out = redact_ai_input(
            {"natural_language_preferences": "solo ONs hard dollar argentinas"}
        )
        assert "natural_language_preferences" in out
        assert out["natural_language_preferences"].startswith("<REDACTED:text_")
        assert "ONs" not in out["natural_language_preferences"]

    def test_open_investment_goal_redacted(self) -> None:
        out = redact_ai_input(
            {"open_investment_goal": "Quiero ahorrar para la jubilación."}
        )
        assert out["open_investment_goal"].startswith("<REDACTED:text_")

    def test_open_risk_reaction_redacted(self) -> None:
        out = redact_ai_input({"open_risk_reaction": "Me asusta perder mucho."})
        assert out["open_risk_reaction"].startswith("<REDACTED:text_")

    def test_open_past_experience_redacted(self) -> None:
        out = redact_ai_input(
            {"open_past_experience": "Tuve una mala experiencia en 2008."}
        )
        assert out["open_past_experience"].startswith("<REDACTED:text_")

    def test_open_concerns_redacted(self) -> None:
        out = redact_ai_input(
            {"open_concerns": "Me preocupa quedarme sin liquidez."}
        )
        assert out["open_concerns"].startswith("<REDACTED:text_")

    def test_held_away_notes_redacted(self) -> None:
        """Contexto patrimonial informativo (DD-017 ext.): texto libre corto
        que nombra bancos/brokers — debe redactarse por clave explícita, no
        depender de la heurística de longitud."""
        out = redact_ai_input({"held_away_notes": "PF en Banco Galicia"})
        assert out["held_away_notes"].startswith("<REDACTED:text_")
        assert "Galicia" not in out["held_away_notes"]

    def test_tax_status_redacted(self) -> None:
        out = redact_ai_input({"tax_status": "Monotributista, residente AR"})
        assert out["tax_status"].startswith("<REDACTED:text_")

    def test_held_away_amounts_preserved(self) -> None:
        """Los montos son numéricos: se conservan igual que net_worth."""
        out = redact_ai_input(
            {"held_away_investments_usd": 120_000.0, "total_liabilities_usd": 30_000.0}
        )
        assert out["held_away_investments_usd"] == 120_000.0
        assert out["total_liabilities_usd"] == 30_000.0

    def test_redaction_includes_length(self) -> None:
        original = "abc def ghi"
        out = redact_ai_input({"open_concerns": original})
        # `<REDACTED:text_11_chars>` para "abc def ghi"
        assert f"text_{len(original)}_chars" in out["open_concerns"]

    def test_kyc_context_dict_recurses(self) -> None:
        out = redact_ai_input(
            {
                "kyc_context": {
                    "age": 40,
                    "open_concerns": "Texto libre del cliente",
                }
            }
        )
        # kyc_context se reemplaza por dict redacted (no string).
        # Nota: la política actual hace `<REDACTED:text_N_chars>` para
        # kyc_context cuando es str; para dict recursamos.
        assert isinstance(out["kyc_context"], dict)
        assert out["kyc_context"]["open_concerns"].startswith("<REDACTED:text_")
        assert out["kyc_context"]["age"] == 40


# ─────────────────────────────────────────────────────────────────────────────
# Structured fields preserved
# ─────────────────────────────────────────────────────────────────────────────


class TestStructuredFieldsPreserved:
    def test_age_preserved(self) -> None:
        out = redact_ai_input({"age": 42})
        assert out["age"] == 42

    def test_scores_preserved(self) -> None:
        out = redact_ai_input(
            {
                "risk_tolerance_score": 7,
                "risk_capacity_score": 8,
                "liquidity_need_score": 3,
            }
        )
        assert out["risk_tolerance_score"] == 7
        assert out["risk_capacity_score"] == 8
        assert out["liquidity_need_score"] == 3

    def test_investment_horizon_preserved(self) -> None:
        out = redact_ai_input({"investment_horizon_years": 15})
        assert out["investment_horizon_years"] == 15

    def test_amounts_preserved(self) -> None:
        out = redact_ai_input(
            {
                "net_worth_usd": 500_000.0,
                "liquid_net_worth_usd": 150_000.0,
                "annual_income_usd": 80_000.0,
            }
        )
        assert out["net_worth_usd"] == 500_000.0
        assert out["liquid_net_worth_usd"] == 150_000.0
        assert out["annual_income_usd"] == 80_000.0

    def test_jurisdiction_currency_preserved(self) -> None:
        out = redact_ai_input(
            {
                "jurisdiction": "AR",
                "preferred_currency": "USD",
                "currency": "USD",
                "country": "Argentina",
                "entity": "Balanz",
            }
        )
        assert out["jurisdiction"] == "AR"
        assert out["preferred_currency"] == "USD"
        assert out["currency"] == "USD"
        assert out["country"] == "Argentina"
        assert out["entity"] == "Balanz"

    def test_investment_objective_preserved(self) -> None:
        out = redact_ai_input({"investment_objective": "balanced"})
        assert out["investment_objective"] == "balanced"

    def test_profile_preserved(self) -> None:
        out = redact_ai_input({"profile": "moderado"})
        assert out["profile"] == "moderado"

    def test_allowed_instrument_types_preserved(self) -> None:
        out = redact_ai_input(
            {"allowed_instrument_types": ["CORPORATE_BOND", "ETF"]}
        )
        assert out["allowed_instrument_types"] == ["CORPORATE_BOND", "ETF"]

    def test_hard_dollar_only_bool_preserved(self) -> None:
        out = redact_ai_input({"hard_dollar_only": True})
        assert out["hard_dollar_only"] is True

    def test_none_values_preserved(self) -> None:
        out = redact_ai_input({"currency": None, "country": None})
        assert out["currency"] is None
        assert out["country"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Safety nets
# ─────────────────────────────────────────────────────────────────────────────


class TestSafetyNets:
    def test_api_key_sk_redacted(self) -> None:
        out = redact_ai_input({"openai_api_key": "sk-aBcDeF1234567890XYZ"})
        # No debe aparecer en el output
        assert "sk-" not in json.dumps(out)
        assert out["openai_api_key"].startswith("<REDACTED:text_")

    def test_api_key_sk_in_nested_dict_redacted(self) -> None:
        out = redact_ai_input(
            {
                "metadata": {
                    "api_key": "sk-aBcDeF1234567890XYZ",
                    "model": "gpt-4o-mini",
                }
            }
        )
        assert "sk-" not in json.dumps(out)

    def test_api_key_sk_in_list_redacted(self) -> None:
        out = redact_ai_input(
            {"secrets": ["sk-aBcDeF1234567890XYZ", "ok-not-a-key"]}
        )
        assert "sk-aBcDeF" not in json.dumps(out)

    def test_bearer_token_redacted(self) -> None:
        out = redact_ai_input(
            {"authorization": "Bearer some-very-long-opaque-token-xyz"}
        )
        # Bearer token también debe ser detectado
        assert "Bearer some-very-long-opaque-token-xyz" not in json.dumps(out)

    def test_long_unknown_string_redacted(self) -> None:
        long_text = "x" * 200
        out = redact_ai_input({"some_unknown_field": long_text})
        assert out["some_unknown_field"].startswith("<REDACTED:text_")

    def test_short_unknown_string_preserved(self) -> None:
        # Strings cortos en claves desconocidas → conservados (no se asume
        # que sean sensibles). Esto evita over-redaction de etiquetas.
        out = redact_ai_input({"some_label": "short"})
        assert out["some_label"] == "short"

    def test_no_mutation_of_input(self) -> None:
        original = {"client_id": "C-X", "age": 40}
        snapshot = dict(original)
        redact_ai_input(original)
        assert original == snapshot

    def test_non_dict_payload_raises(self) -> None:
        with pytest.raises(ValueError):
            redact_ai_input(["not", "a", "dict"])  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# Output redaction — raw_response del modelo (I-022 ext. 2026-07)
# ─────────────────────────────────────────────────────────────────────────────


class TestOutputRedaction:
    """
    La respuesta del modelo puede CITAR el texto libre del cliente
    (contradictions, follow_up_questions, advisor_notes). `redact_ai_output`
    redacta esos campos siempre — incluso elementos cortos de listas — y
    conserva las claves estructuradas (perfil, confidence, flags).
    """

    def test_contradictions_list_fully_redacted(self) -> None:
        out = redact_ai_output(
            {
                "contradictions": [
                    "Dice 'me asusta perder' pero eligió agresivo.",
                    "corto",
                ]
            }
        )
        assert all(
            item.startswith("<REDACTED:text_") for item in out["contradictions"]
        )

    def test_follow_up_questions_redacted(self) -> None:
        out = redact_ai_output(
            {"follow_up_questions": ["¿Confirmás que tolerás -20%?"]}
        )
        assert out["follow_up_questions"][0].startswith("<REDACTED:text_")

    def test_advisor_notes_redacted(self) -> None:
        out = redact_ai_output({"advisor_notes": ["El cliente mencionó a su hija."]})
        assert out["advisor_notes"][0].startswith("<REDACTED:text_")

    def test_profile_change_reason_redacted(self) -> None:
        out = redact_ai_output({"profile_change_reason": "Revisado tras respuestas."})
        assert out["profile_change_reason"].startswith("<REDACTED:text_")

    def test_structured_keys_preserved(self) -> None:
        out = redact_ai_output(
            {
                "preliminary_profile": "moderado",
                "confidence": 0.82,
                "advisor_review_required": True,
            }
        )
        assert out["preliminary_profile"] == "moderado"
        assert out["confidence"] == 0.82
        assert out["advisor_review_required"] is True

    def test_nested_dict_under_redacted_key_preserves_shape(self) -> None:
        out = redact_ai_output(
            {"contradictions": [{"field": "riesgo", "detail": "cita del cliente"}]}
        )
        entry = out["contradictions"][0]
        assert set(entry.keys()) == {"field", "detail"}
        assert entry["detail"].startswith("<REDACTED:text_")

    def test_api_key_in_output_redacted(self) -> None:
        out = redact_ai_output({"debug": "sk-aBcDeF1234567890XYZ"})
        assert "sk-aBcDeF" not in json.dumps(out)

    def test_long_unknown_output_string_redacted(self) -> None:
        out = redact_ai_output({"unexpected_blob": "y" * 120})
        assert out["unexpected_blob"].startswith("<REDACTED:text_")

    def test_no_mutation_of_output_payload(self) -> None:
        original = {"contradictions": ["algo"], "confidence": 0.5}
        snapshot = {"contradictions": ["algo"], "confidence": 0.5}
        redact_ai_output(original)
        assert original == snapshot

    def test_non_dict_output_raises(self) -> None:
        with pytest.raises(ValueError):
            redact_ai_output("not a dict")  # type: ignore[arg-type]


class TestRepositoryRedactsRawResponse:
    """El repositorio redacta raw_response en TODOS los paths de escritura."""

    def test_create_persists_redacted_raw_response(self, tmp_path) -> None:
        from risk_first_advisory.persistence_layer.entity_repository import (
            SQLiteAIRequestLogRepository,
            SQLiteEntityStore,
        )

        with SQLiteEntityStore(tmp_path / "t.db") as store:
            # DDL mínimo de 0001_phase2_core_schema.sql sin FKs (unit test:
            # case_id / requested_by_advisor_id van NULL).
            store._conn.execute(
                """
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
                    created_at_utc          TEXT NOT NULL
                )
                """
            )
            repo = SQLiteAIRequestLogRepository(store)
            data = repo.create(
                endpoint="/test",
                model="test-model",
                prompt_version="v1",
                input_redacted={"age": 40},
                input_hash="deadbeef",
                validation_status="parsed_ok",
                raw_response={
                    "preliminary_profile": "moderado",
                    "contradictions": ["cita literal del cliente"],
                },
            )
            # El dict devuelto ya está redactado
            assert data["raw_response"]["contradictions"][0].startswith(
                "<REDACTED:text_"
            )
            assert data["raw_response"]["preliminary_profile"] == "moderado"
            # Y lo persistido también
            stored = repo.get(data["request_id"])
            assert stored is not None
            assert "cita literal" not in json.dumps(stored["raw_response"])


# ─────────────────────────────────────────────────────────────────────────────
# input_hash
# ─────────────────────────────────────────────────────────────────────────────


class TestInputHash:
    def test_hash_is_sha256_hex(self) -> None:
        h = compute_input_hash({"a": 1, "b": 2})
        # 64 hex chars
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_matches_canonical_sha256(self) -> None:
        payload = {"a": 1, "b": 2}
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert compute_input_hash(payload) == expected

    def test_hash_changes_when_payload_changes(self) -> None:
        a = compute_input_hash({"client_id": "C-X", "age": 40})
        b = compute_input_hash({"client_id": "C-X", "age": 41})
        assert a != b

    def test_hash_stable_under_key_reorder(self) -> None:
        a = compute_input_hash({"a": 1, "b": 2, "c": 3})
        b = compute_input_hash({"c": 3, "b": 2, "a": 1})
        assert a == b

    def test_hash_of_original_not_redacted(self) -> None:
        # Política: input_hash es sobre el original, no el redactado.
        # Así dos inputs con mismo texto libre tienen mismo hash; un cambio
        # del texto cambia el hash aunque el redacted sea idéntico.
        a = compute_input_hash(
            {"client_id": "C-1", "open_concerns": "Texto A"}
        )
        b = compute_input_hash(
            {"client_id": "C-1", "open_concerns": "Texto B"}
        )
        assert a != b

    def test_hash_unicode_handled(self) -> None:
        # ensure_ascii=False: caracteres unicode preservados en canonical.
        h1 = compute_input_hash({"x": "ñoño"})
        h2 = compute_input_hash({"x": "ñoño"})
        assert h1 == h2
