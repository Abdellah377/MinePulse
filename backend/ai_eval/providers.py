"""Deterministic, zero-cost provider test doubles for evaluation runs."""

from __future__ import annotations

from enum import Enum

from app.ai.contracts import (
    ConfidenceLevel,
    DiagnosisStatus,
    DiagnosisResult,
    EvidenceRequest,
    EvidenceRequestType,
    Hypothesis,
    InvestigationConclusion,
    InvestigationRecommendation,
    RecommendationAction,
)
from app.ai.llm.provider import ProviderResponseError


class MockProfile(str, Enum):
    SUCCESS = "SUCCESS"
    REQUEST_MORE_EVIDENCE = "REQUEST_MORE_EVIDENCE"
    INCONCLUSIVE = "INCONCLUSIVE"
    REQUEST_THEN_INCONCLUSIVE = "REQUEST_THEN_INCONCLUSIVE"
    FABRICATED_CITATION = "FABRICATED_CITATION"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"


class DeterministicEvaluationProvider:
    """Schema-valid scripted provider; never used by production or the API.

    The provider sees exactly the payload a real provider sees. It has no case,
    scenario, or ground-truth object. ``concept`` merely makes reports readable;
    mocked reports explicitly state that they do not measure reasoning quality.
    """

    provider_name = "evaluation-mock"
    model_name = "deterministic-no-llm"

    def __init__(
        self,
        *,
        profile: MockProfile = MockProfile.SUCCESS,
        concept: str = "operational condition",
        request_type: EvidenceRequestType | None = None,
    ):
        self.profile = profile
        self.concept = concept
        self.request_type = request_type
        self.seen_payloads: list[dict] = []

    @staticmethod
    def _evidence(payload: dict) -> list[dict]:
        return [item for item in payload.get("evidence", []) if item.get("available")]

    def _support(self, evidence: list[dict]) -> list[str]:
        preferred_tool = {
            EvidenceRequestType.OEM_MAINTENANCE_INDICATORS: "oem_maintenance_indicators",
            EvidenceRequestType.OEM_CONNECTIVITY: "oem_connectivity",
            EvidenceRequestType.EQUIPMENT_TIMELINE: "equipment_timeline",
            EvidenceRequestType.OEM_DIAGNOSTICS: "oem_diagnostics",
            EvidenceRequestType.OEM_ERRORS: "oem_errors",
            EvidenceRequestType.ASSIGNMENTS: "assignments",
        }.get(self.request_type)
        if preferred_tool:
            preferred = [item for item in evidence if item.get("source_tool") == preferred_tool]
            if preferred:
                return [preferred[0]["evidence_id"]]
        relevant = [
            item
            for item in evidence
            if item.get("source_tool") in {"site_alerts", "fleet_snapshot"}
        ]
        return [relevant[0]["evidence_id"]] if relevant else []

    def diagnose(self, payload: dict) -> DiagnosisResult:
        self.seen_payloads.append(payload)
        if self.profile == MockProfile.PROVIDER_FAILURE:
            raise ProviderResponseError("Deliberate evaluation provider failure")
        round_number = payload.get("investigationRound", 1)
        evidence = self._evidence(payload)
        support = self._support(evidence)
        if self.profile == MockProfile.FABRICATED_CITATION:
            support = ["ev-fabricated-by-evaluator"]
        request_more = self.profile in {
            MockProfile.REQUEST_MORE_EVIDENCE,
            MockProfile.REQUEST_THEN_INCONCLUSIVE,
        } and round_number == 1 and self.request_type is not None
        inconclusive = self.profile in {
            MockProfile.INCONCLUSIVE,
            MockProfile.REQUEST_THEN_INCONCLUSIVE,
        }
        can_conclude = not request_more and not inconclusive
        requests = []
        if request_more:
            trigger = payload.get("trigger", {})
            requests.append(
                EvidenceRequest(
                    request_type=self.request_type,
                    equipment_id=trigger.get("equipment_id"),
                    zone_id=trigger.get("zone_id"),
                    reason="Deterministic evaluation requests one approved evidence source.",
                )
            )
        statement = (
            f"Observed {self.concept}; cause remains unconfirmed."
            if inconclusive
            else f"The available evidence supports {self.concept}."
        )
        return DiagnosisResult(
            hypotheses=[
                Hypothesis(
                    statement=statement,
                    supporting_evidence_ids=support,
                    confidence=ConfidenceLevel.LOW if inconclusive else ConfidenceLevel.HIGH,
                    rationale="Deterministic schema and evidence-link evaluation.",
                )
            ],
            requested_information=requests,
            can_conclude=can_conclude,
            confidence=ConfidenceLevel.LOW if inconclusive or request_more else ConfidenceLevel.HIGH,
            confidence_rationale="Mocked pipeline result; model quality was not evaluated.",
            reasoning_summary=statement,
        )

    def build_conclusion(self, payload: dict) -> InvestigationConclusion:
        self.seen_payloads.append(payload)
        diagnosis = payload.get("diagnosis") or {}
        hypotheses = diagnosis.get("hypotheses") or []
        hypothesis = hypotheses[0] if hypotheses else {}
        support = hypothesis.get("supporting_evidence_ids") or []
        hypothesis_id = hypothesis.get("hypothesis_id")
        evidence_by_id = {item["evidence_id"]: item for item in payload.get("evidence", [])}
        fact_ids = [i for i in support if evidence_by_id.get(i, {}).get("kind") == "FACT"]
        metric_ids = [
            i
            for i in support
            if evidence_by_id.get(i, {}).get("kind") in {"DERIVED_METRIC", "MODEL_PREDICTION"}
        ]
        can_conclude = bool(diagnosis.get("can_conclude"))
        return InvestigationConclusion(
            summary=(
                f"Evidence supports {self.concept}."
                if can_conclude
                else f"A {self.concept} is observed, but available evidence is insufficient."
            ),
            diagnosis_status=(
                DiagnosisStatus.PROBABLE if can_conclude else DiagnosisStatus.INCONCLUSIVE
            ),
            root_cause=self.concept if can_conclude else None,
            reliable_root_cause=False,
            observed_fact_evidence_ids=fact_ids,
            derived_metric_evidence_ids=metric_ids,
            supported_hypothesis_ids=[hypothesis_id] if hypothesis_id else [],
            unresolved_uncertainties=[] if can_conclude else ["The cause is not established."],
            confidence=ConfidenceLevel.HIGH if can_conclude else ConfidenceLevel.LOW,
        )

    def build_recommendation(self, payload: dict) -> InvestigationRecommendation:
        self.seen_payloads.append(payload)
        conclusion = payload.get("conclusion") or {}
        reliable = bool(conclusion.get("reliable_root_cause"))
        evidence_ids = (
            conclusion.get("observed_fact_evidence_ids", [])
            + conclusion.get("derived_metric_evidence_ids", [])
        )
        return InvestigationRecommendation(
            action_type=(
                RecommendationAction.INSPECT_EQUIPMENT
                if reliable
                else RecommendationAction.VERIFY_OPERATIONAL_CONDITION
            ),
            description="Have an operator verify the condition before taking any action.",
            rationale="This is a conservative evaluation recommendation.",
            evidence_ids=evidence_ids,
            human_validation_required=True,
        )
