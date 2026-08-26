"""LangGraph construction for one bounded MinePulse investigation."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.ai.contracts import InvestigationStatus, InvestigationTrigger
from app.ai.nodes import InvestigationNodes, InvestigationRuntime
from app.ai.routers import (
    route_after_analysis,
    route_after_conclusion,
    route_after_context,
    route_after_evidence,
)
from app.ai.state import InvestigationState

GRAPH_VERSION = "1.1.0"


def build_investigation_graph(runtime: InvestigationRuntime):
    nodes = InvestigationNodes(runtime)
    graph = StateGraph(InvestigationState)
    graph.add_node("resolve_context", nodes.resolve_context)
    graph.add_node("gather_initial_evidence", nodes.gather_initial_evidence)
    graph.add_node("analyze", nodes.analyze)
    graph.add_node("gather_requested_evidence", nodes.gather_requested_evidence)
    graph.add_node("build_conclusion", nodes.build_conclusion)
    graph.add_node("build_recommendation", nodes.build_recommendation)
    graph.add_node("persist", nodes.persist)

    graph.add_edge(START, "resolve_context")
    graph.add_conditional_edges(
        "resolve_context",
        route_after_context,
        {
            "gather_initial_evidence": "gather_initial_evidence",
            "persist": "persist",
        },
    )
    graph.add_conditional_edges(
        "gather_initial_evidence",
        route_after_evidence,
        {
            "analyze": "analyze",
            "persist": "persist",
        },
    )
    graph.add_conditional_edges(
        "analyze",
        route_after_analysis,
        {
            "gather_requested_evidence": "gather_requested_evidence",
            "build_conclusion": "build_conclusion",
            "persist": "persist",
        },
    )
    graph.add_conditional_edges(
        "gather_requested_evidence",
        route_after_evidence,
        {
            "analyze": "analyze",
            "persist": "persist",
        },
    )
    graph.add_conditional_edges(
        "build_conclusion",
        route_after_conclusion,
        {
            "build_recommendation": "build_recommendation",
            "persist": "persist",
        },
    )
    graph.add_edge("build_recommendation", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def initial_state(
    trigger: InvestigationTrigger,
    *,
    max_iterations: int,
    provider: str,
    model: str,
) -> InvestigationState:
    return InvestigationState(
        investigation_id=str(uuid4()),
        trigger=trigger,
        operational_context=None,
        evidence=[],
        diagnosis=None,
        hypotheses=[],
        requested_information=[],
        evidence_request_history=[],
        contradictions=[],
        conclusion=None,
        recommendation=None,
        iteration_count=0,
        max_iterations=max_iterations,
        iteration_limit_reached=False,
        evidence_expansion_exhausted=False,
        status=InvestigationStatus.PENDING,
        error=None,
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        graph_version=GRAPH_VERSION,
        provider=provider,
        model=model,
    )
