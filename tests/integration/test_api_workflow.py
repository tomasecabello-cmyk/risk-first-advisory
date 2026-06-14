"""
Tests de integración para POST /workflow/run.

Usa TestClient (síncrono) de FastAPI.
Monkeypatcha DEFAULT_DB_PATH y DEFAULT_WORKFLOW_REPORT_DIR para que los
tests no toquen data/demo_api.db ni reports/ del proyecto.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ─────────────────────────────────────────────────────────────────────────────
# Payload válido de referencia
# ─────────────────────────────────────────────────────────────────────────────

_VALID_PAYLOAD: dict = {
    "client_id": "test_client_01",
    "advisor_id": "ADV-TEST-001",
    "kyc_data": {
        "risk_tolerance_score": 6,
        "risk_capacity_score": 7,
        "liquidity_need_score": 3,
        "investment_horizon_years": 10,
        "investment_experience": "moderada",
        "income_stability": "stable",
        "net_worth": 500_000.0,
        "liquid_net_worth": 200_000.0,
        "max_acceptable_drawdown_pct": 25.0,
    },
    "financial_goal": {
        "initial_amount": 100_000.0,
        "target_amount": 200_000.0,
        "horizon_years": 10,
        "annual_contribution": 5_000.0,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """
    TestClient con DB y directorio de reportes apuntando a tmp_path.
    """
    import risk_first_advisory.api_layer.main as main_module

    monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", tmp_path / "wf_test.db")
    monkeypatch.setattr(main_module, "DEFAULT_WORKFLOW_REPORT_DIR", tmp_path / "reports")
    return TestClient(main_module.app)


@pytest.fixture
def workflow_response(client: TestClient) -> dict:
    """Ejecuta POST /workflow/run una vez y cachea la respuesta."""
    response = client.post("/workflow/run", json=_VALID_PAYLOAD)
    assert response.status_code == 200, response.text
    return response.json()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: código de estado y campos de respuesta
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflowRunResponse:
    def test_returns_200_with_valid_payload(self, client: TestClient):
        response = client.post("/workflow/run", json=_VALID_PAYLOAD)
        assert response.status_code == 200

    def test_returns_client_id_from_request(self, workflow_response: dict):
        assert workflow_response["client_id"] == _VALID_PAYLOAD["client_id"]

    def test_returns_status_as_string(self, workflow_response: dict):
        assert isinstance(workflow_response["status"], str)
        assert workflow_response["status"]

    def test_returns_approved_profile_name_non_empty(self, workflow_response: dict):
        name = workflow_response["approved_profile_name"]
        assert isinstance(name, str)
        assert name.strip()

    def test_returns_reason_codes_as_list(self, workflow_response: dict):
        assert isinstance(workflow_response["reason_codes"], list)

    def test_returns_warnings_as_list(self, workflow_response: dict):
        assert isinstance(workflow_response["warnings"], list)

    def test_returns_final_optimizer_tickers_as_list(self, workflow_response: dict):
        assert isinstance(workflow_response["final_optimizer_tickers"], list)

    def test_returns_has_portfolios_bool(self, workflow_response: dict):
        assert isinstance(workflow_response["has_portfolios"], bool)

    def test_returns_candidate_count_int(self, workflow_response: dict):
        assert isinstance(workflow_response["candidate_count"], int)

    def test_returns_portfolio_feasibility_status_string_or_none(
        self, workflow_response: dict
    ):
        pf = workflow_response.get("portfolio_feasibility_status")
        assert pf is None or isinstance(pf, str)

    def test_returns_report_path_string(self, workflow_response: dict):
        assert isinstance(workflow_response["report_path"], str)
        assert workflow_response["report_path"]


# ─────────────────────────────────────────────────────────────────────────────
# Tests: records de persistencia
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflowRunRecords:
    def test_returns_records_object(self, workflow_response: dict):
        assert "records" in workflow_response
        assert isinstance(workflow_response["records"], dict)

    def test_records_has_workflow_record_id(self, workflow_response: dict):
        records = workflow_response["records"]
        assert "workflow_record_id" in records
        assert records["workflow_record_id"].startswith("workflow_")

    def test_records_has_report_record_id(self, workflow_response: dict):
        records = workflow_response["records"]
        assert "report_record_id" in records
        assert records["report_record_id"].startswith("report_")

    def test_audit_record_id_is_string_or_none(self, workflow_response: dict):
        audit_id = workflow_response["records"].get("audit_record_id")
        assert audit_id is None or (
            isinstance(audit_id, str) and audit_id.startswith("audit_")
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tests: persistencia real en SQLite
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflowRunPersistence:
    def test_sqlite_db_is_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        db_path = tmp_path / "check.db"
        monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", db_path)
        monkeypatch.setattr(
            main_module, "DEFAULT_WORKFLOW_REPORT_DIR", tmp_path / "reports"
        )

        tc = TestClient(main_module.app)
        response = tc.post("/workflow/run", json=_VALID_PAYLOAD)
        assert response.status_code == 200
        assert db_path.exists()

    def test_workflow_record_retrievable_from_sqlite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLitePersistenceStore,
            SQLiteWorkflowRunRepository,
        )

        db_path = tmp_path / "verify.db"
        monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", db_path)
        monkeypatch.setattr(
            main_module, "DEFAULT_WORKFLOW_REPORT_DIR", tmp_path / "reports"
        )

        tc = TestClient(main_module.app)
        data = tc.post("/workflow/run", json=_VALID_PAYLOAD).json()
        workflow_id = data["records"]["workflow_record_id"]

        with SQLitePersistenceStore(db_path) as store:
            store.init_schema()
            rec = SQLiteWorkflowRunRepository(store).get_workflow_result(workflow_id)
        assert rec.record_id == workflow_id

    def test_report_file_is_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        report_dir = tmp_path / "reports"
        monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", tmp_path / "a.db")
        monkeypatch.setattr(main_module, "DEFAULT_WORKFLOW_REPORT_DIR", report_dir)

        tc = TestClient(main_module.app)
        tc.post("/workflow/run", json=_VALID_PAYLOAD)

        client_id = _VALID_PAYLOAD["client_id"]
        report_file = report_dir / f"workflow_{client_id}.md"
        assert report_file.exists()
        content = report_file.read_text(encoding="utf-8")
        assert "# Risk-First Advisory Report" in content

    def test_two_calls_generate_distinct_ids(self, client: TestClient):
        r1 = client.post("/workflow/run", json=_VALID_PAYLOAD).json()
        r2 = client.post("/workflow/run", json=_VALID_PAYLOAD).json()
        assert (
            r1["records"]["workflow_record_id"]
            != r2["records"]["workflow_record_id"]
        )
        assert (
            r1["records"]["report_record_id"] != r2["records"]["report_record_id"]
        )

    def test_second_call_increments_workflow_id(self, client: TestClient):
        r1 = client.post("/workflow/run", json=_VALID_PAYLOAD).json()
        r2 = client.post("/workflow/run", json=_VALID_PAYLOAD).json()
        n1 = int(r1["records"]["workflow_record_id"].split("_")[1])
        n2 = int(r2["records"]["workflow_record_id"].split("_")[1])
        assert n2 == n1 + 1


# ─────────────────────────────────────────────────────────────────────────────
# Tests: validación de entrada (422)
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflowRunValidation:
    def test_missing_client_id_returns_422(self, client: TestClient):
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "client_id"}
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_empty_client_id_returns_422(self, client: TestClient):
        payload = {**_VALID_PAYLOAD, "client_id": ""}
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_missing_advisor_id_returns_422(self, client: TestClient):
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "advisor_id"}
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_horizon_years_zero_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "financial_goal": {**_VALID_PAYLOAD["financial_goal"], "horizon_years": 0},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_horizon_years_negative_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "financial_goal": {**_VALID_PAYLOAD["financial_goal"], "horizon_years": -5},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_risk_tolerance_score_zero_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "risk_tolerance_score": 0},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_risk_tolerance_score_eleven_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "risk_tolerance_score": 11},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_invalid_experience_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "investment_experience": "guru"},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_negative_net_worth_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "net_worth": -1.0},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_negative_annual_contribution_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "financial_goal": {
                **_VALID_PAYLOAD["financial_goal"],
                "annual_contribution": -100.0,
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_target_below_initial_no_contributions_returns_422(
        self, client: TestClient
    ):
        payload = {
            **_VALID_PAYLOAD,
            "financial_goal": {
                "initial_amount": 200_000.0,
                "target_amount": 100_000.0,
                "horizon_years": 10,
                "annual_contribution": 0.0,
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Tests: serialización
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflowRunSerialization:
    def test_response_is_json_serializable(self, workflow_response: dict):
        json.dumps(workflow_response)

    def test_response_has_no_raw_enum_repr(self, workflow_response: dict):
        serialized = json.dumps(workflow_response)
        assert "AdvisoryWorkflowStatus" not in serialized
        assert "PortfolioFeasibilityStatus" not in serialized
        assert "<" not in serialized

    def test_status_is_lowercase_value(self, workflow_response: dict):
        status = workflow_response["status"]
        assert status == status.lower() or "_" in status
        assert "AdvisoryWorkflowStatus" not in status

    def test_all_list_fields_contain_only_strings(self, workflow_response: dict):
        for field in ("reason_codes", "warnings", "final_optimizer_tickers"):
            for item in workflow_response[field]:
                assert isinstance(item, str), f"{field} contiene no-string: {item!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: open fields opcionales
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflowRunOptionalFields:
    def test_optional_open_fields_accepted(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "open_investment_goal": "Quiero crecer mi capital a largo plazo.",
                "open_risk_reaction": "Me incomoda ver caídas grandes.",
                "open_past_experience": "Tuve fondos de renta fija.",
                "open_concerns": "Inflación y tipo de cambio.",
                "declared_return_expectation_pct": 8.5,
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_english_experience_aliases_accepted(self, client: TestClient):
        for exp in ("none", "basic", "moderate", "advanced", "expert"):
            payload = {
                **_VALID_PAYLOAD,
                "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "investment_experience": exp},
            }
            response = client.post("/workflow/run", json=payload)
            assert response.status_code == 200, f"experience={exp!r} debería ser 200"

    def test_capital_preservation_goal_accepted(self, client: TestClient):
        # target == initial con annual_contribution == 0 es preservación válida.
        payload = {
            **_VALID_PAYLOAD,
            "financial_goal": {
                "initial_amount": 100_000.0,
                "target_amount": 100_000.0,
                "horizon_years": 5,
                "annual_contribution": 0.0,
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Tests: campo age en KYCDataRequest
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflowRunAge:
    """
    Verifica que el campo 'age' en kyc_data sea aceptado, validado y propagado
    correctamente a KYCData en lugar del valor hardcodeado anterior (40).
    """

    def test_age_explicit_value_accepted(self, client: TestClient):
        """age explícito dentro del rango válido devuelve 200."""
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "age": 55},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_age_minimum_boundary_accepted(self, client: TestClient):
        """age=18 (mínimo) devuelve 200."""
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "age": 18},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_age_maximum_boundary_accepted(self, client: TestClient):
        """age=120 (máximo) devuelve 200."""
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "age": 120},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_age_below_minimum_returns_422(self, client: TestClient):
        """age=17 (< 18) devuelve 422."""
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "age": 17},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_age_above_maximum_returns_422(self, client: TestClient):
        """age=121 (> 120) devuelve 422."""
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "age": 121},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_age_zero_returns_422(self, client: TestClient):
        """age=0 devuelve 422."""
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "age": 0},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_omitting_age_uses_default_and_returns_200(self, client: TestClient):
        """
        Backward compatibility: payload sin 'age' usa default=40
        y devuelve 200 sin errores.
        """
        # _VALID_PAYLOAD no incluye 'age' — debe seguir funcionando.
        response = client.post("/workflow/run", json=_VALID_PAYLOAD)
        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Tests: scripted-demo disclosure metadata
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflowRunScriptedDemoMetadata:
    """
    /workflow/run usa MockAIClient + ScriptedAdvisorInterface por defecto.
    La respuesta DEBE declarar explícitamente esa naturaleza scripted para
    que ningún consumidor (frontend, integración externa, asesor) lo
    confunda con un flujo de IA real o de aprobación real del asesor.
    """

    def test_execution_mode_is_scripted_demo(self, workflow_response: dict):
        assert workflow_response["execution_mode"] == "scripted_demo"

    def test_ai_source_is_mock_scripted(self, workflow_response: dict):
        assert workflow_response["ai_source"] == "mock_scripted"

    def test_advisor_source_is_scripted_auto_approve(self, workflow_response: dict):
        assert workflow_response["advisor_source"] == "scripted_auto_approve"

    def test_is_production_ready_is_false(self, workflow_response: dict):
        # Tipo bool explícito (no truthy): el contrato distingue false de None/0/"".
        assert workflow_response["is_production_ready"] is False

    def test_warning_field_is_non_empty_string(self, workflow_response: dict):
        warning = workflow_response["warning"]
        assert isinstance(warning, str)
        assert warning.strip()

    def test_warning_mentions_mock_and_scripted(self, workflow_response: dict):
        warning = workflow_response["warning"]
        assert "MockAIClient" in warning
        assert "ScriptedAdvisorInterface" in warning

    def test_warning_also_appended_to_warnings_list(self, workflow_response: dict):
        """
        El mismo aviso del campo `warning` debe estar también en `warnings`,
        para que clientes que solo leen la lista vean el indicador scripted.
        """
        assert workflow_response["warning"] in workflow_response["warnings"]

    def test_warnings_list_has_at_least_the_scripted_warning(
        self, workflow_response: dict
    ):
        assert len(workflow_response["warnings"]) >= 1

    def test_metadata_fields_are_stable_across_calls(self, client: TestClient):
        """
        La metadata scripted-demo no depende del payload: dos llamadas
        distintas devuelven los mismos valores para los 5 campos.
        """
        r1 = client.post("/workflow/run", json=_VALID_PAYLOAD).json()
        payload2 = {
            **_VALID_PAYLOAD,
            "client_id": "test_client_02",
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "risk_tolerance_score": 3},
        }
        r2 = client.post("/workflow/run", json=payload2).json()

        for key in (
            "execution_mode",
            "ai_source",
            "advisor_source",
            "is_production_ready",
            "warning",
        ):
            assert r1[key] == r2[key], f"campo {key!r} cambió entre llamadas"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: nuevos KYC fields (Fase 1.5 — quitar defaults silenciosos)
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflowRunExtendedKYCFields:
    """
    /workflow/run ahora acepta jurisdiction, preferred_currency,
    investment_objective, prefers_simple_products, annual_income_usd y
    ESG fields. Cubre tanto los happy paths con valores explícitos como las
    validaciones 422 y backward compatibility con el payload mínimo.
    """

    # ── happy paths ────────────────────────────────────────────────────

    def test_jurisdiction_explicit_value_accepted(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "jurisdiction": "MX"},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_preferred_currency_explicit_value_accepted(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "preferred_currency": "EUR"},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_investment_objective_growth_accepted(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "investment_objective": "growth"},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_investment_objective_capital_preservation_accepted(
        self, client: TestClient
    ):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "investment_objective": "capital_preservation",
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_prefers_simple_products_true_accepted(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "prefers_simple_products": True,
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_annual_income_usd_explicit_value_accepted(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "annual_income_usd": 120_000.0,
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_annual_income_usd_zero_accepted(self, client: TestClient):
        """annual_income_usd=0 es válido (cliente sin ingresos declarados)."""
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "annual_income_usd": 0.0},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_esg_strictness_strict_accepted(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "esg_strictness_level": "strict",
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_esg_exclusions_propagated(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "esg_exclusions": [
                    {
                        "excluded_item": "tobacco",
                        "exclusion_type": "sector",
                        "source": "client_explicit",
                        "rationale": "Convicción personal del cliente.",
                    }
                ],
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_esg_preferences_propagated(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "esg_preferences": [
                    {
                        "preference_type": "low_carbon",
                        "weight": 0.6,
                        "minimum_threshold": 50.0,
                    }
                ],
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    def test_full_extended_kyc_payload_accepted(self, client: TestClient):
        """Smoke: todos los campos nuevos juntos."""
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "jurisdiction": "MX",
                "preferred_currency": "EUR",
                "investment_objective": "growth",
                "prefers_simple_products": True,
                "annual_income_usd": 200_000.0,
                "esg_strictness_level": "light",
                "esg_exclusions": [{
                    "excluded_item": "fossil_fuels",
                    "exclusion_type": "sector",
                    "source": "client_explicit",
                }],
                "esg_preferences": [{
                    "preference_type": "low_carbon",
                    "weight": 0.5,
                }],
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 200

    # ── validation errors → 422 ────────────────────────────────────────

    def test_jurisdiction_empty_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "jurisdiction": ""},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_jurisdiction_whitespace_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "jurisdiction": "   "},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_preferred_currency_empty_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "preferred_currency": ""},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_preferred_currency_whitespace_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "preferred_currency": "   ",
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_investment_objective_invalid_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "investment_objective": "speculative",
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_annual_income_usd_negative_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {**_VALID_PAYLOAD["kyc_data"], "annual_income_usd": -1.0},
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_esg_strictness_invalid_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "esg_strictness_level": "extreme",
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_esg_exclusion_invalid_type_returns_422(self, client: TestClient):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "esg_exclusions": [{
                    "excluded_item": "tobacco",
                    "exclusion_type": "made_up_type",
                    "source": "client_explicit",
                }],
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_esg_exclusion_empty_excluded_item_returns_422(
        self, client: TestClient
    ):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "esg_exclusions": [{
                    "excluded_item": "",
                    "exclusion_type": "sector",
                    "source": "client_explicit",
                }],
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    def test_esg_preference_weight_out_of_range_returns_422(
        self, client: TestClient
    ):
        payload = {
            **_VALID_PAYLOAD,
            "kyc_data": {
                **_VALID_PAYLOAD["kyc_data"],
                "esg_preferences": [{
                    "preference_type": "low_carbon",
                    "weight": 1.5,
                }],
            },
        }
        response = client.post("/workflow/run", json=payload)
        assert response.status_code == 422

    # ── backward compatibility ────────────────────────────────────────

    def test_legacy_payload_without_new_fields_still_returns_200(
        self, client: TestClient
    ):
        """El payload _VALID_PAYLOAD original (sin los nuevos campos) sigue OK."""
        # _VALID_PAYLOAD no incluye jurisdiction, preferred_currency, etc.
        response = client.post("/workflow/run", json=_VALID_PAYLOAD)
        assert response.status_code == 200

    def test_legacy_payload_uses_historical_defaults(self, client: TestClient):
        """
        El payload viejo debe seguir produciendo workflow exitoso con los
        mismos defaults históricos (jurisdiction=AR, currency=USD,
        objective=balanced, etc.). Verificado indirectamente: el status
        debe ser uno de los valores válidos del workflow normal, no error.
        """
        response = client.post("/workflow/run", json=_VALID_PAYLOAD)
        assert response.status_code == 200
        data = response.json()
        # El workflow scripted-demo produce completed o status comparable;
        # lo importante es que el approved_profile_name sea no vacío
        # (signo de que el pipeline corrió end-to-end con los defaults).
        assert isinstance(data["approved_profile_name"], str)
        assert data["approved_profile_name"].strip()
