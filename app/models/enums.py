from enum import StrEnum


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


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
