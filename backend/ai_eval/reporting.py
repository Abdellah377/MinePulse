"""Human- and machine-readable evaluation report formatting."""

from __future__ import annotations

from ai_eval.contracts import EvaluationReport


def format_report(report: EvaluationReport) -> str:
    lines = [
        f"CASE: {report.case_id}",
        f"OUTCOME: {report.outcome.value}",
        f"MODE: {report.reasoning_mode}",
        f"INVESTIGATION: {report.investigation_id or 'not persisted'}",
        f"PROVIDER/MODEL: {report.provider or 'unknown'} / {report.model or 'unknown'}",
        f"STATUS: {report.status}; ITERATIONS: {report.iteration_count}",
        f"PIPELINE: {'PASS' if report.pipeline_correct else 'FAIL'}",
        "QUALITY LEVELS: "
        + ", ".join(
            f"{name}={'NOT_SCORED' if value is None else 'PASS' if value else 'FAIL'}"
            for name, value in report.quality_levels.items()
        ),
        (
            "REASONING CHECKS: "
            f"{report.reasoning_checks_passed}/{report.reasoning_checks_total} "
            "(mocked mode does not measure model quality)"
            if report.reasoning_mode == "MOCKED_PIPELINE"
            else f"REASONING CHECKS: {report.reasoning_checks_passed}/{report.reasoning_checks_total}"
        ),
        "EVIDENCE:",
    ]
    lines.extend(
        f"  - {item.evidence_id} [{item.kind.value}/{item.status}] "
        f"{item.source_tool} -> {item.source_service}"
        for item in report.evidence
    )
    lines.append("CHECKS:")
    lines.extend(
        f"  - {'PASS' if item.passed else 'FAIL'} {item.check_id}: {item.message}"
        for item in report.checks
    )
    if report.data_quality_warnings:
        lines.append("DATA QUALITY WARNINGS:")
        lines.extend(f"  - {warning}" for warning in report.data_quality_warnings)
    if report.evidence_request_history:
        lines.append("EVIDENCE REQUESTS:")
        lines.extend(
            "  - "
            f"{item['request']['request_type']} -> {item['outcome']} "
            f"({item['request']['reason']})"
            for item in report.evidence_request_history
        )
    if report.conclusion:
        lines.append(f"CONCLUSION: {report.conclusion.get('summary')}")
        lines.append(f"RELIABLE ROOT CAUSE: {report.root_cause_reliable}")
    if report.recommendation:
        lines.append(f"RECOMMENDATION: {report.recommendation.get('description')}")
    if report.human_review_notes:
        lines.append(f"HUMAN REVIEW: {report.human_review_notes}")
    return "\n".join(lines)
