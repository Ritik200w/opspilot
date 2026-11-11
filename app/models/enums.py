from enum import StrEnum


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


SEVERITY_RANK: dict[Severity, int] = {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}


def is_more_severe(candidate: Severity, current: Severity) -> bool:
    return SEVERITY_RANK[candidate] > SEVERITY_RANK[current]


class IncidentStatus(StrEnum):
    OPEN = "open"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    FAILED = "failed"
    RESOLVED = "resolved"


class AlertSource(StrEnum):
    ALERTMANAGER = "alertmanager"
    GENERIC = "generic"


class AlertStatus(StrEnum):
    FIRING = "firing"
    RESOLVED = "resolved"


class ContextKind(StrEnum):
    METRICS = "metrics"
    LOGS = "logs"


class FixRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FixStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
