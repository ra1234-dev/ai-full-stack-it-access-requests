# AI Full Stack Challenge — IT Access Requests

The task is in CHALLENGE.md. Replace this file with your own README, as CHALLENGE.md asks.
#test comment from Ram

<!-- test comment -->

In class, start with `docs/00-prerequisites.md` and follow the files in `docs/` in order.

Set up from the repository root with Python 3.10+ and a system pip supporting
`--python`. Dependencies are pinned in `requirements.lock`. Using
`--without-pip` also supports hosts where Python's `ensurepip` is unavailable:

```bash
python3 -m venv --without-pip .venv
python3 -m pip --python .venv/bin/python install -r requirements.lock
source .venv/bin/activate
```

Run the mock test suite with this environment activated:

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

Step 3 provides `access_intake.validation.validate_schema`,
`validate_extraction`, `validate_reply`, and
`access_intake.extraction.extract_document(document, provider, attempt_id=...)`.
The supplied schema is validated with pinned `jsonschema` using the explicitly
selected Draft 2020-12 dialect. Schema acceptance is separate from evidence
and semantic acceptance.

The internal mock envelope has `status: completed` and exactly one of
`extraction` or JSON-encoded `output_text`. A refusal or incomplete status
blocks extraction before parsing or validation. This internal format is not a
claim about any real provider protocol; the real adapter belongs to step 8.
Malformed replies, timeouts, provider failures and validation failures produce
null extractions with categorized errors, document/attempt identity and a
retry command. Raw provider exceptions are omitted from those errors.
Provenance records the configured attempted source and whether the provider
returned an envelope; failed mock attempts remain labelled `mock`. There are
no hidden retries. The printed retry command will become executable in step 7.

Evidence checks compare quotes exactly against decoded message text, including
newlines. Null facts require relevant issue explanations; grouped start/end
date explanations are supported. Resolved dates must have the `YYYY-MM-DD`
representation; calendar validity and ambiguous date interpretation are not
verified. Conflict checks recognize explicit environment and manager statements
in the supplied wording, including its labelled environment correction.
Override checks recognize the supplied `SYSTEM OVERRIDE:` marker and require
its full attempted instruction in evidence and an issue explanation. These
guards do not implement general conflict or injection detection, recognize all
possible issue paraphrases, or establish arbitrary scalar/purpose accuracy.
The independent expectations remain the basis for later accuracy evaluation.

At this step, a valid extraction is an intermediate result with `error: null`;
business review routing is added in step 4. Only failures have terminal routing
now: `error / IT Service Desk / retry-extraction`.
