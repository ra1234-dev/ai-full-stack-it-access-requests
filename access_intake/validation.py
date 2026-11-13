"""Schema and source-evidence gates for extracted request facts.

Source checks recognize the explicit constructions in the supplied corpus.
They are deterministic validation guards, not a general language extractor.
"""

from collections.abc import Mapping
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator

from .exports import SourceDocument


SCHEMA = json.loads(
    (Path(__file__).resolve().parents[1] / "snapshot.schema.json").read_text(encoding="utf-8")
)
# The supplied schema has no $schema; select its dialect explicitly.
Draft202012Validator.check_schema(SCHEMA)
_VALIDATOR = Draft202012Validator(SCHEMA)
_SCALARS = tuple(field for field in SCHEMA["properties"] if field not in {"issues", "supporting_quotes"})
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ISSUE_FIELDS = {
    "request_id": r"\brequest[_ -]?(?:id|identifier)\b|\bidentifier\b",
    "request_date": r"\brequest[_ -]?date\b|\bsubmission date\b|\bsubmitted date\b",
    "kind": r"\bkind\b|\brequest type\b",
    "requester": r"\brequester\b|\brequesting person\b",
    "team": r"\bteam\b|\bdepartment\b",
    "system": r"\bsystem\b|\bapplication\b",
    "environment": r"\benvironment\b",
    "permission": r"\bpermission\b|\baccess level\b",
    "business_purpose": r"\bbusiness[_ -]?purpose\b|\bpurpose\b|\bbusiness reason\b",
    "start_date": r"\bstart[_ -]?date\b|\bstart\b.{0,30}\bdates?\b",
    "end_date": r"\bend[_ -]?date\b|\bend\b.{0,30}\bdates?\b",
    "manager": r"\bmanager\b|\bboss\b",
}
_ENVIRONMENT = re.compile(
    r"\bin\s+(staging|production)\b"
    r"|\bfor\s+the\s+(staging|production)\s+environment\b"
    r"|\benvironment\s+is\s+(?:actually\s+)?(staging|production)\b"
    r"|\b(staging|production)\s+(?:read|write|admin)\s+access\b",
    re.IGNORECASE,
)


class ValidationError(ValueError):
    """A safe, categorized rejection with no raw response or source payload."""

    def __init__(self, category: str, explanation: str) -> None:
        self.category = category
        self.explanation = explanation
        super().__init__(explanation)


def validate_schema(extraction: Any) -> None:
    """Check only the supplied schema, without imposing business semantics."""
    if not _VALIDATOR.is_valid(extraction):
        raise ValidationError("schema", "Extraction does not conform to snapshot.schema.json.")


def issue_explains(issues: list[str], field: str) -> bool:
    """Recognize field references in free-form issue explanations.

    Grouped descriptions and common field labels are supported. This cannot
    establish the truth of an explanation or recognize arbitrary paraphrases.
    """
    return any(re.search(_ISSUE_FIELDS[field], issue, re.IGNORECASE) for issue in issues)


def instruction_override(message: str) -> str | None:
    """Recognize the explicit override marker used by the supplied example."""
    match = re.search(r"SYSTEM OVERRIDE:.*", message, re.DOTALL)
    return match.group(0) if match else None


def source_conflicts(message: str) -> dict[str, list[str]]:
    """Find explicit environment/manager contradictions in supported wording.

    A labelled environment correction replaces preceding environment claims.
    Other correction vocabularies and arbitrary conflict detection are outside
    the verified language boundary.
    """
    conflicts = {}
    correction = re.search(
        r"Correction:\s*environment is (?:actually )?(staging|production)\b", message, re.IGNORECASE
    )
    if not correction:
        matches = list(_ENVIRONMENT.finditer(message))
        values = {next(group for group in match.groups() if group).lower() for match in matches}
        if len(values) > 1:
            conflicts["environment"] = [match.group(0) for match in matches]

    managers = list(re.finditer(
        r"\b(?:My manager is|The manager for this request is|My boss is)\s+([^.!?\n]+)",
        message, re.IGNORECASE,
    ))
    if len({match.group(1).strip().casefold() for match in managers}) > 1:
        conflicts["manager"] = [match.group(0) for match in managers]
    return conflicts


def validate_extraction(document: SourceDocument, extraction: Any) -> None:
    """Check schema, exact quotes, null explanations and supported source rules."""
    validate_schema(extraction)
    quotes = extraction["supporting_quotes"]
    issues = extraction["issues"]
    if any(quote not in document.message for quote in quotes):
        raise ValidationError("evidence", "A supporting quote is not an exact substring of the decoded message.")

    for field in _SCALARS:
        if extraction[field] is None and not issue_explains(issues, field):
            raise ValidationError("semantic", f"Unresolved {field} needs a relevant issue explanation.")
    for field in ("request_date", "start_date", "end_date"):
        value = extraction[field]
        if value is not None and not _DATE.fullmatch(value):
            raise ValidationError("semantic", f"Resolved {field} must use YYYY-MM-DD.")

    for field, alternatives in source_conflicts(document.message).items():
        if extraction[field] is not None or not issue_explains(issues, field):
            raise ValidationError("semantic", f"Conflicting {field} must remain null with an explanation.")
        if any(not any(alternative in quote for quote in quotes) for alternative in alternatives):
            raise ValidationError("evidence", f"Conflicting {field} alternatives must both be retained in exact quotes.")

    override = instruction_override(document.message)
    if override:
        if not any(override in quote for quote in quotes):
            raise ValidationError("evidence", "The attempted instruction override must remain in exact source evidence.")
        if not any(re.search(r"\boverride\b|\binstruction\b|\binjection\b", issue, re.IGNORECASE) for issue in issues):
            raise ValidationError("semantic", "The attempted instruction override needs an issue explanation.")


def validate_reply(document: SourceDocument, reply: Any) -> dict[str, Any]:
    """Gate the internal normalized envelope before parsing extraction content."""
    if not isinstance(reply, Mapping):
        raise ValidationError("malformed_envelope", "Provider reply must be an object with completion status.")
    status = reply.get("status")
    if status == "incomplete":
        raise ValidationError("incomplete", "Provider response is incomplete; no extraction was accepted.")
    if status == "failed":
        raise ValidationError("provider_error", "Provider reported a failed response.")
    if status != "completed":
        raise ValidationError("malformed_envelope", "Provider reply has no supported terminal completion status.")
    refusal = reply.get("refusal")
    if refusal is not None and not isinstance(refusal, str):
        raise ValidationError("malformed_envelope", "Provider refusal metadata has an invalid type.")
    if refusal:
        raise ValidationError("refusal", "Provider refused the request; no extraction was accepted.")
    if ("extraction" in reply) == ("output_text" in reply):
        raise ValidationError("malformed_envelope", "Completed reply must carry exactly one extraction payload.")
    if "output_text" in reply:
        if not isinstance(reply["output_text"], str):
            raise ValidationError("malformed_envelope", "Provider output_text must be a string.")
        try:
            extraction = json.loads(reply["output_text"])
        except json.JSONDecodeError as exc:
            raise ValidationError("malformed_json", "Provider extraction text is not valid JSON.") from exc
    else:
        extraction = reply["extraction"]
    validate_extraction(document, extraction)
    return extraction
