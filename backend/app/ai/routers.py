"""Pure routing decisions for the investigation graph."""

from app.ai.contracts import InvestigationStatus
from app.ai.state import InvestigationState


def route_after_context(state: InvestigationState) -> str:
    return "persist" if state["status"] == InvestigationStatus.FAILED else "gather_initial_evidence"


def route_after_analysis(state: InvestigationState) -> str:
    if state["status"] == InvestigationStatus.FAILED:
        return "persist"
    if state["requested_information"] and state["iteration_count"] < state["max_iterations"]:
        return "gather_requested_evidence"
    return "build_conclusion"


def route_after_conclusion(state: InvestigationState) -> str:
    return "persist" if state["status"] == InvestigationStatus.FAILED else "build_recommendation"
