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

Step 2 provides `access_intake.exports.read_export(path)` and
`read_exports(paths)`. Each input must be a readable UTF-8 JSON object with a
`message` string. The reader preserves the original bytes, computes their
lowercase SHA-256 hash, and keeps the complete decoded message separate from
display metadata. It does not truncate 200-word messages or infer facts from
subjects or export timestamps.

Document identity is the basename, including `.json`. Files with different
names remain independent even when their messages state the same request ID.
For the supplied filename convention, `IT-001.json`, `IT-001-followup.json`
and `IT-001-paraphrase.json` each have filename identifier `IT-001`; that
identifier is kept separate from any identifier stated in the message.
Unrecognized filename conventions have no filename identifier.

`read_exports` preserves input order and rejects duplicate basenames across
the batch. Unreadable files, invalid UTF-8/JSON, non-object JSON, missing or
non-string messages, and duplicate basenames raise `InvalidExportError` with
the document filename and a reason. Correct the export or duplicate filename
before submitting the batch again; an invalid batch returns no partial list.

Independent expectations for the 20 supplied exports and one authored
paraphrase are in `tests/expectations/`. Each scalar has source quotes or an
absence explanation, with policy annotations and purpose rubrics. The
paraphrase and its 200-word variant are in `tests/fixtures/exports/`; their
saved mock replies are `tests/mock_responses/paraphrase-001.json` and
`paraphrase-200.json`. These tests check reading and fixture consistency;
they do not measure model extraction quality. IT-006 permission (Q-16) and
IT-014 date representation (Q-18) remain explicitly pending policy decisions.
