"""Read message exports while preserving their original byte identity."""

from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any


class InvalidExportError(ValueError):
    """An unreadable/invalid export or ambiguous batch document identity."""

    def __init__(self, document_id: str, reason: str) -> None:
        self.document_id = document_id
        self.reason = reason
        super().__init__(f"{document_id}: {reason}")


@dataclass(frozen=True)
class SourceDocument:
    """One independent export; metadata supplies display context only.

    filename_request_id follows the supplied IT-number filename convention.
    It is not an extracted request ID: the message may state a different ID.
    """

    document_id: str
    raw_bytes: bytes
    source_hash: str
    message: str
    metadata: dict[str, Any]
    filename_request_id: str | None


def read_export(path: str | Path) -> SourceDocument:
    """Read a UTF-8 JSON object with a message string, without normalization.

    Hash the original bytes before decoding. Preserve the full decoded message,
    including whitespace and newlines; facts will be extracted in later stages.
    """
    path = Path(path)
    document_id = path.name
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InvalidExportError(document_id, "cannot read export file") from exc

    source_hash = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidExportError(document_id, "export must use UTF-8") from exc
    try:
        export = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidExportError(document_id, "export must contain valid JSON") from exc
    if not isinstance(export, dict):
        raise InvalidExportError(document_id, "export must be a JSON object")
    if "message" not in export:
        raise InvalidExportError(document_id, "export is missing message")
    if not isinstance(export["message"], str):
        raise InvalidExportError(document_id, "message must be a string")

    identifier = re.match(r"^(IT-[0-9]+)(?:-|$)", path.stem)
    return SourceDocument(
        document_id=document_id,
        raw_bytes=raw,
        source_hash=source_hash,
        message=export["message"],
        metadata={key: value for key, value in export.items() if key != "message"},
        filename_request_id=identifier.group(1) if identifier else None,
    )


def read_exports(paths: Iterable[str | Path]) -> list[SourceDocument]:
    """Read a flat batch in input order, rejecting duplicate basenames.

    Repeated request IDs and even identical bytes across differently named files
    remain separate documents. No partial batch is returned on invalid input.
    """
    paths = [Path(path) for path in paths]
    seen: set[str] = set()
    for path in paths:
        if path.name in seen:
            raise InvalidExportError(path.name, f"duplicate document basename {path.name}")
        seen.add(path.name)
    return [read_export(path) for path in paths]
