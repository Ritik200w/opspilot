import hashlib
from datetime import UTC, datetime

from app.models.enums import Severity

_SEVERITY_ALIASES: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "page": Severity.CRITICAL,
    "high": Severity.CRITICAL,
    "error": Severity.CRITICAL,
    "warning": Severity.WARNING,
    "warn": Severity.WARNING,
    "medium": Severity.WARNING,
    "info": Severity.INFO,
    "low": Severity.INFO,
    "none": Severity.INFO,
}

# Unknown or missing severity labels are treated as warnings: visible, but not paging-level.
DEFAULT_SEVERITY = Severity.WARNING


def parse_severity(value: str | None) -> Severity:
    if value is None:
        return DEFAULT_SEVERITY
    return _SEVERITY_ALIASES.get(value.strip().lower(), DEFAULT_SEVERITY)


def stable_hash(*parts: str) -> str:
    """sha256 over the parts, NUL-separated so ("ab", "c") and ("a", "bc") differ."""
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def make_dedup_key(source: str, *parts: str) -> str:
    return f"{source}:{stable_hash(*parts)}"


def to_utc(value: datetime) -> datetime:
    """Naive datetimes are assumed to be UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
