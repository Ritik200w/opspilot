"""Strip secrets and obvious sensitive values from collected context.

Applied to logs (and any other collected data) before they are stored in
context_snapshots or sent anywhere (Claude, Slack). This is best-effort defence
in depth, not a guarantee: it targets the common shapes (tokens, passwords,
emails, API keys, private keys), never every possible secret.
"""

import re
from typing import Any

REDACTED = "[REDACTED]"
REDACTED_EMAIL = "[REDACTED_EMAIL]"
REDACTED_KEY = "[REDACTED_PRIVATE_KEY]"

# Keys whose value is sensitive regardless of content, used for both text
# ("password=...") and structured data ({"password": "..."}).
_SENSITIVE_KEY = re.compile(
    r"(?i)(pass(?:word|wd)?|pwd|secret|token|api[_-]?key|apikey|access[_-]?key"
    r"|secret[_-]?key|private[_-]?key|auth(?:orization|[_-]?token)?|credential|session[_-]?id)"
)

# (compiled pattern, replacement) applied in order to free text. Order matters:
# token-shaped values are redacted before the generic key=value rule, which would
# otherwise stop at the first space and leak the rest (e.g. "Bearer <token>").
_TEXT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # PEM private key blocks (multi-line).
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        REDACTED_KEY,
    ),
    # Authorization: Bearer <token> / Basic <token>
    (
        re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]+"),
        r"\1 " + REDACTED,
    ),
    # JSON Web Tokens.
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
        REDACTED,
    ),
    # AWS access key IDs.
    (
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        REDACTED,
    ),
    # Credentials embedded in connection strings: scheme://user:password@host
    (
        re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://[^:\s/@]+:)[^@\s/]+(@)"),
        r"\1" + REDACTED + r"\2",
    ),
    # key=value / "key": "value" style secrets, keeping the key name.
    (
        re.compile(
            r'(?i)("?\b(?:pass(?:word|wd)?|pwd|secret|token|api[_-]?key|apikey|access[_-]?key'
            r"|secret[_-]?key|private[_-]?key|authorization|auth[_-]?token|credential"
            r'|session[_-]?id)\b"?\s*[:=]\s*)'
            r'("[^"]*"|\'[^\']*\'|[^\s,;}]+)'
        ),
        r"\1" + REDACTED,
    ),
    # Email addresses (last, so it does not eat credentials handled above).
    (
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        REDACTED_EMAIL,
    ),
]


def redact_text(text: str) -> str:
    """Redact secrets and sensitive values from a single string."""
    for pattern, replacement in _TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_value(value: Any) -> Any:  # noqa: ANN401 - intentionally walks arbitrary JSON
    """Recursively redact strings inside JSON-like data.

    A dict value under a sensitive key name is replaced wholesale; everything
    else is walked and any string run through :func:`redact_text`.
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: _redact_entry(key, item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    return value


def _redact_entry(key: Any, item: Any) -> Any:  # noqa: ANN401 - arbitrary JSON
    if isinstance(key, str) and _SENSITIVE_KEY.search(key):
        return REDACTED
    return redact_value(item)
