"""Bounded recommendation discussion. Does not start a new investigation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.contracts import (
    DiscussionPostRequest,
    DiscussionRole,
    DiscussionThread,
    RecommendationDiscussionReply,
)
from app.ai.feedback import (
    FeedbackConflict,
    FeedbackNotFound,
    add_message,
    get_discussion,
    list_messages,
)
from app.ai.llm.provider import LLMProvider, create_llm_provider
from app.ai.persistence import get_investigation, record_to_result

MAX_DISCUSSION_HISTORY = 12


def _json_payload(investigation, messages, operator_content: str) -> dict:
    result = record_to_result(investigation)
    history = messages[-MAX_DISCUSSION_HISTORY:]
    return {
        "trigger": result.trigger.model_dump(mode="json"),
        "conclusion": result.conclusion.model_dump(mode="json") if result.conclusion else None,
        "recommendation": (
            result.recommendation.model_dump(mode="json") if result.recommendation else None
        ),
        "evidence": [item.model_dump(mode="json") for item in result.evidence],
        "recentMessages": [
            {"role": row.role, "content": row.content} for row in history
        ],
        "operatorMessage": operator_content,
        "operatorMessageIsNotFact": True,
        "policy": [
            "Operator statements are OPERATOR_INPUT, not FACT.",
            "Current operational facts including ROAD_NETWORK_CONTEXT win.",
            "CLOSED and UNKNOWN roads stay ineligible even if the operator prefers them.",
            "Do not recalculate routes. Do not execute actions. No chain-of-thought.",
        ],
    }


def post_discussion(
    session: Session,
    investigation_id: UUID,
    request: DiscussionPostRequest,
    *,
    provider: LLMProvider | None = None,
) -> DiscussionThread:
    investigation = get_investigation(session, investigation_id)
    if investigation is None:
        raise FeedbackNotFound("investigation")
    if not investigation.recommendation:
        raise FeedbackConflict("recommendation missing")
    add_message(
        session,
        investigation_id,
        role=DiscussionRole.OPERATOR,
        content=request.content,
        actor_label=request.actor_label,
    )
    if request.generate_reply:
        llm = provider or create_llm_provider()
        history = list_messages(session, investigation_id)
        payload = _json_payload(investigation, history[:-1], request.content)
        reply = llm.discuss_recommendation(payload)
        if not isinstance(reply, RecommendationDiscussionReply):
            reply = RecommendationDiscussionReply.model_validate(reply)
        valid_ids = {
            item.get("evidence_id")
            for item in (investigation.evidence or [])
            if isinstance(item, dict) and item.get("evidence_id")
        }
        cited = [item for item in reply.cited_evidence_ids if item in valid_ids]
        add_message(
            session,
            investigation_id,
            role=DiscussionRole.ASSISTANT,
            content=reply.reply,
            cited_evidence_ids=cited,
        )
    return get_discussion(session, investigation_id)
