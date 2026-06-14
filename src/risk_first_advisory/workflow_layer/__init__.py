"""Capa D — orquestación de workflow.

Contiene AdvisoryWorkflowCoordinator: la fachada productiva que ejecuta
el flujo completo de asesoría (KYC → IA → asesor → filtros → portfolios)
sin acoplarse a ninguna UI específica (consola, FastAPI, notebook, batch).

scripts/run_demo.py es solo una interfaz de consola sobre este workflow.
Otras interfaces (FastAPI, web, report) deben usar este coordinator y NO
reimplementar el flujo manualmente.
"""

from risk_first_advisory.workflow_layer.advisory_workflow import (
    RC_DATA_MISSING,
    RC_DATA_QUALITY_FAILED,
    RC_ESG_BLOCKED,
    RC_ESG_WARNING,
    RC_GOAL_FEASIBILITY_BLOCKED,
    RC_PORTFOLIO_EMPTY_FINAL_UNIVERSE,
    RC_PORTFOLIO_FEASIBILITY_WARNING,
    RC_PORTFOLIO_GENERATION_BLOCKED,
    RC_SUITABILITY_LIMITED,
    AdvisoryWorkflowCoordinator,
    AdvisoryWorkflowResult,
    AdvisoryWorkflowStatus,
)

__all__ = [
    "AdvisoryWorkflowCoordinator",
    "AdvisoryWorkflowResult",
    "AdvisoryWorkflowStatus",
    "RC_DATA_MISSING",
    "RC_DATA_QUALITY_FAILED",
    "RC_ESG_BLOCKED",
    "RC_ESG_WARNING",
    "RC_GOAL_FEASIBILITY_BLOCKED",
    "RC_PORTFOLIO_EMPTY_FINAL_UNIVERSE",
    "RC_PORTFOLIO_FEASIBILITY_WARNING",
    "RC_PORTFOLIO_GENERATION_BLOCKED",
    "RC_SUITABILITY_LIMITED",
]
