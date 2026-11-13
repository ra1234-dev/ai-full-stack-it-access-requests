# AI Full Stack Challenge — IT Access Requests

The task is in CHALLENGE.md. Replace this file with your own README, as CHALLENGE.md asks.
#test comment from Ram

<!-- test comment -->

In class, start with `docs/00-prerequisites.md` and follow the files in `docs/` in order.

Run the mock test suite from the repository root (Python 3.10+):

```bash
env -u API_KEY python3 -m unittest discover -s tests -v
```

Step 1 provides `access_intake.providers.Provider` and `MockProvider`. The mock
reads saved replies from `tests/mock_responses/`; it needs no credentials or
network. A schedule contains fixture stems such as `complete-001`, exceptions
to raise, or `ControlledResponse` entries with arrival/release events for
deterministic concurrency checks. Requests and call counts remain inspectable
after failures. The caller must release controlled responses during cleanup.
