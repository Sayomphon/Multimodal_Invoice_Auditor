"""Versionable mapping from rule results to workflow decision."""

from invoice_auditor.models import AuditDecision, RuleResult, Severity

_RANK = {Severity.INFO: 0, Severity.REVIEW: 1, Severity.REJECT: 2}


def decide(results: list[RuleResult]) -> AuditDecision:
    failed = [result for result in results if result.passed is False]
    if not failed:
        return AuditDecision.PASS
    highest = max((_RANK[result.severity] for result in failed), default=0)
    if highest >= _RANK[Severity.REJECT]:
        return AuditDecision.REJECT
    if highest >= _RANK[Severity.REVIEW]:
        return AuditDecision.REVIEW
    return AuditDecision.PASS

