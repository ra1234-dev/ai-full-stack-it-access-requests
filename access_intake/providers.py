"""Injectable providers and a deterministic, file-backed offline provider."""

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from threading import Event, Lock
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Provider(Protocol):
    """Boundary between intake processing and the response source."""

    response_source: str

    def extract(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Return a provider envelope or raise a provider exception."""
        ...


@dataclass(frozen=True)
class ControlledResponse:
    """Signal arrival, then wait for release before reading the named fixture.

    The caller owns both events and must release waiting calls during cleanup.
    Other scheduled calls can proceed while this response waits.
    """

    fixture: str
    started: Event
    release: Event


class MockProvider:
    """Consume one scheduled fixture name, exception or barrier per call.

    Calls reserve their schedule slot and capture a deep copy of the request
    under a lock. Waiting and file reads happen outside that lock. Captures and
    call counts include failed calls, including calls after schedule exhaustion.
    Fixtures are loaded afresh so mutations of a reply cannot affect later calls.
    This provider never reads credentials or opens network connections.
    """

    response_source = "mock"

    def __init__(
        self,
        responses_dir: str | Path,
        *,
        schedule: Iterable[str | Exception | ControlledResponse],
    ) -> None:
        self._responses_dir = Path(responses_dir)
        self._schedule = tuple(schedule)
        self._requests: list[dict[str, Any]] = []
        self._lock = Lock()

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self._requests)

    @property
    def requests(self) -> list[dict[str, Any]]:
        """Return an isolated snapshot of captured requests in reservation order."""
        with self._lock:
            return deepcopy(self._requests)

    def extract(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            index = len(self._requests)
            self._requests.append(deepcopy(dict(request)))
            if index >= len(self._schedule):
                raise RuntimeError("Mock response schedule exhausted")
            response = self._schedule[index]

        if isinstance(response, Exception):
            raise response
        if isinstance(response, ControlledResponse):
            response.started.set()
            response.release.wait()
            name = response.fixture
        else:
            name = response

        # A schedule names fixture stems within the configured directory.
        if not isinstance(name, str) or not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError("Mock fixture name must be a nonempty filename stem")
        return json.loads((self._responses_dir / f"{name}.json").read_text(encoding="utf-8"))


class FixtureProvider:
    """Offline demonstration only: a reviewed message selects a saved mock reply.

    Unknown or edited messages fail explicitly; this is not a language extractor.
    Metadata-only changes can reuse a fixture if the decoded message is identical.
    """
    response_source = 'mock'

    def __init__(self, responses_dir=None):
        self.directory = Path(responses_dir or Path(__file__).resolve().parents[1] / 'tests/mock_responses/corpus')

    def configuration(self):
        import hashlib
        digest = hashlib.sha256()
        for path in sorted(self.directory.glob('*.json')):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        return {'provider': 'mock', 'fixtures_sha256': digest.hexdigest()}

    def extract(self, request):
        for path in sorted(self.directory.glob('*.json')):
            fixture = json.loads(path.read_text(encoding='utf-8'))
            if fixture['source_message'] == request['message']:
                return deepcopy(fixture['reply'])
        raise ValueError('No saved mock response for this message. Use the live provider for fresh input.')
