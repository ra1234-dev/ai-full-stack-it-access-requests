"""Run one provider attempt and turn validation failures into actionable errors."""

from copy import deepcopy
import json
import shlex
from urllib.error import HTTPError
from typing import Any

from .exports import SourceDocument
from .providers import Provider
from . import validation


def extract_document(document: SourceDocument, provider: Provider, *, attempt_id: str) -> dict[str, Any]:
    """Extract once without hidden retries, persistence or success routing.

    A successful result is an intermediate validated extraction. Step 4 adds
    business routing before it can become a terminal review-queue record.
    Provenance identifies the configured response source even on failed calls.
    """
    result = {
        "document_id": document.document_id,
        "source_sha256": document.source_hash,
        "attempt_id": attempt_id,
        "response_source": provider.response_source,
        "provenance": {
            "attempted_response_source": provider.response_source,
            "response_received": False,
        },
        "extraction": None,
        "error": None,
    }
    failure = None
    try:
        reply = provider.extract({
            "document_id": document.document_id,
            "source_sha256": document.source_hash,
            "message": document.message,
        })
    except json.JSONDecodeError:
        failure = validation.ValidationError("malformed_json", "Provider reply is not valid JSON.")
    except TimeoutError:
        failure = validation.ValidationError("timeout", "Provider request timed out; retry this document.")
    except HTTPError as exc:
        category = "rate_limit" if exc.code == 429 else "provider_unavailable" if exc.code >= 500 else "provider_error"
        failure = validation.ValidationError(category, "Provider HTTP request failed; inspect configuration or retry later.")
    except Exception:
        # Never echo provider exceptions: headers, URLs and payloads may contain credentials.
        failure = validation.ValidationError("provider_error", "Provider request failed; retry this document.")
    else:
        result["provenance"]["response_received"] = True
        try:
            result["extraction"] = deepcopy(validation.validate_reply(document, reply))
        except validation.ValidationError as exc:
            failure = exc

    if failure:
        result.update(status="error", owner="IT Service Desk", next_action="retry-extraction")
        result["error"] = {
            "category": failure.category,
            "explanation": failure.explanation,
            "document_id": document.document_id,
            "attempt_id": attempt_id,
            "retry_command": f"python3 -m access_intake retry {shlex.quote(document.document_id)}",
        }
    return result
