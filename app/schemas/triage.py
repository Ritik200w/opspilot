"""Structured triage output from Claude, and a tolerant parser for it.

Claude is asked (see ``prompts/triage_v1.md``) to return a single JSON object.
The model's output is untrusted and may be malformed, so :func:`parse_triage_output`
is forgiving about wrapping (markdown fences, surrounding prose) but strict about
the shape: anything that does not validate raises :class:`MalformedTriageOutput`,
which the caller records as an analysis error instead of crashing.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models.enums import FixRisk, Severity


class MalformedTriageOutput(ValueError):
    """Raised when Claude's output is not valid JSON of the expected shape."""


class ProposedFix(BaseModel):
    """A single fix Claude proposes. Maps to a ``fix_proposals`` row."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    risk: FixRisk


class TriageResult(BaseModel):
    """Validated triage output for one analysis run."""

    model_config = ConfigDict(extra="ignore")

    root_cause: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    severity_suggestion: Severity
    fix: ProposedFix


def _strip_fences(text: str) -> str:
    """Drop a surrounding ```json ... ``` fence if the model added one."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped[3:]
    if body[:4].lower() == "json":
        body = body[4:]
    fence_end = body.rfind("```")
    if fence_end != -1:
        body = body[:fence_end]
    return body.strip()


def _loads(text: str) -> Any:  # noqa: ANN401 - returns arbitrary parsed JSON
    candidate = _strip_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} span in case of surrounding prose.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(candidate[start : end + 1])


def parse_triage_output(text: str) -> TriageResult:
    """Parse and validate Claude's raw text into a :class:`TriageResult`.

    Raises :class:`MalformedTriageOutput` if the text is not valid JSON or does
    not match the expected schema.
    """
    try:
        data = _loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedTriageOutput(f"not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MalformedTriageOutput(f"expected a JSON object, got {type(data).__name__}")
    try:
        return TriageResult.model_validate(data)
    except ValidationError as exc:
        raise MalformedTriageOutput(f"schema validation failed: {exc}") from exc
