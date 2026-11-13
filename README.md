# IT access-request intake

A Python CLI turns message exports into a durable human-review queue. SQLite stores
original source bytes, current attempt pointers, pending work and attempt history.
The real provider is OpenAI Responses with native strict JSON Schema output. An
explicit offline mock mode makes the demonstration and tests reproducible.

## Setup

Run from the repository root with Python 3.10+ (verified here on Python 3.12).
Create an isolated environment and install the complete pinned dependency set:

```bash
python3 -m venv --without-pip .venv
python3 -m pip --python .venv/bin/python install -r requirements.lock
source .venv/bin/activate
```

The host needs system pip 22.3+ (`--python` support); on hosts with ensurepip,
`python3 -m venv .venv` and `.venv/bin/python -m pip install -r requirements.lock`
are equivalent. No model key is needed for the following offline walkthrough.

## Start intake and inspect work

```bash
python3 -m access_intake intake materials/requests --provider mock --db var/intake.sqlite
python3 -m access_intake intake tests/fixtures/exports/IT-001-paraphrase.json --provider mock --db var/intake.sqlite
python3 -m access_intake queue --db var/intake.sqlite
python3 -m access_intake pending --db var/intake.sqlite
python3 -m access_intake history IT-001.json --db var/intake.sqlite
python3 -m access_intake resume --db var/intake.sqlite
python3 -m access_intake export --db var/intake.sqlite --output deliverables
python3 -m access_intake accuracy --db var/intake.sqlite --output deliverables/accuracy.md
python3 -m access_intake request-evidence --output deliverables/request-evidence.json
```

Intake accepts directories or individual JSON exports. A directory is a flat batch
of `*.json`; duplicate basenames and invalid exports reject the batch before it is
registered. It reads full decoded messages without truncation and hashes original
bytes. Basenames are independent document identities; leading `IT-<digits>` in a
filename is compared with the message identifier. Export metadata supplies no facts.

Run `queue` and `pending` from another terminal against the same database while
intake runs. Default concurrency is 4 workers (`--workers 1` through `32`). Each
result commits independently with its route; a slow message does not hide completed
work. `pending` shows pending/running attempts and lease expiry. `queue` contains
current terminal results only. A newer pending revision supersedes its earlier
current result; the earlier result remains in `history`.

An unchanged intake makes no new call or attempt, including unchanged errors.
Source-byte, provider/model/options, prompt, schema, policy or code changes create
new attempts. Omitted files stay registered. `--force` deliberately retries all
files in a batch. Resume processes pending/expired work; it does not retry terminal
errors or steal unexpired claims. Inspect errors in `queue`, then run their exact
`error.retry_command`, for example:

```bash
python3 -m access_intake retry IT-001.json --db var/intake.sqlite
python3 -m access_intake refresh --db var/intake.sqlite
```

Retry uses the stored source bytes and provider configuration, with current code
and policy. Refresh re-extracts all registered current documents using their saved
provider settings and current implementation/policy. It is conservative: a policy
change also makes another extraction call. Use intake with new options to change
model settings. Nothing automatically approves or grants access.

The mock adapter matches decoded message text to saved replies in
`tests/mock_responses/corpus/`. It supports the 20 exports and both authored
paraphrases. An unknown/edited message produces a visible provider error; use the
real provider to extract fresh wording. It never reads expectations during intake.
Mock accuracy measures fixture plumbing, not a language model's quality.

## Real provider

The implemented supported configuration is OpenAI Responses, model
`gpt-4.1-mini-2025-04-14`, temperature 0, 2500 output tokens, 60-second socket
request timeout, and `store=false`. Account/model access and live quality were not
tested. Obtain the facilitator-supplied key through your environment as `API_KEY`;
do not put it in a command argument, config file or repository. No live call is
needed to reproduce the submitted outputs.

```bash
python3 -m access_intake intake materials/requests --provider openai --model gpt-4.1-mini-2025-04-14 --timeout 60 --max-output-tokens 2500 --workers 4 --db var/live.sqlite
python3 -m access_intake queue --db var/live.sqlite
python3 -m access_intake export --db var/live.sqlite --output deliverables-live
```

`API_KEY` is the only credential environment variable. Model, endpoint, timeout,
token limit, worker count and database path use explicit CLI flags. `--endpoint`
defaults to `https://api.openai.com/v1/responses` and requires HTTPS without embedded
credentials. Only configure a trusted provider endpoint: the adapter sends the
key there. The prompt stays in `instructions`; the untrusted message stays in
user input. The exact schema is sent in `text.format` with `type=json_schema` and
`strict=true`. Completion/refusal is checked before JSON parsing, schema and
source-evidence validation. HTTP 429, 5xx, timeout, malformed, refused and incomplete
responses produce safe error records. There are no hidden retries. Intake exits
successfully when attempts have been recorded even if individual records have
status `error`; always inspect queue/pending.

Protocol references checked for this repair: [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Responses request/response reference](https://developers.openai.com/api/reference/resources/responses/methods/create),
[GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
The challenge asks for native schema configuration; function calling is not needed
to grant access or execute tools, and this application executes neither.

## Tests and accuracy

```bash
env -u API_KEY python3 -m unittest discover -s tests -v
python3 -m access_intake accuracy --records deliverables/extractions.jsonl --output /tmp/intake-accuracy.md
```

Tests use saved replies or fake HTTP transport, without a key or live network.
Expected facts in `tests/expectations/` were authored from source messages and
policy before this repair. Accuracy fixes the denominator at 21 × 11 = 231 scalar
comparisons, including nulls; failed/missing results score 11 mismatches. Purpose
meaning and issue completeness require source-based human review and are reported
separately. Three formerly open fields use explicitly agreed interpretations:
IT-006 keeps legitimate read permission and flags the injection; IT-014 keeps
explicit reversed dates and routes to clarification. See
[accuracy](deliverables/accuracy.md) and [verification](deliverables/verification.md).

## Shared operation, recovery and limits

Use one authoritative SQLite database on a local disk on one Linux/macOS host.
Regional operators connect to that host (for example through SSH) and use the same
absolute `--db` path. SQLite WAL, immediate write transactions, attempt ownership
tokens and generation pointers protect overlapping operators; an older completion
cannot overwrite a newer registered revision. Queue reads are a consistent SELECT.
Do not deploy SQLite on network filesystems or run separate replicas as if shared.
The database/source history contains message data; use appropriate host access.

After a killed process, running claims expire after the configured request timeout
plus 30 seconds. Run resume after expiry; durable completed work is reused. A crash
after the external call but before commit can repeat that call. Expired/reclaimed
ownership tokens fence late workers. Exactly-once provider calls are not promised.
The HTTP timeout is a socket timeout, not a guaranteed end-to-end wall-clock bound.
Resume is for the same application/configuration version; after a deployment, use
intake or refresh to establish attempts with the current implementation fingerprint.

Expected workloads are 200–400 messages/day and occasional 2,000-message batches.
Worker concurrency is bounded and SQLite writes are short; no live throughput,
rate quota or multi-region performance guarantee has been measured. There is no
automatic backoff: inspect rate-limit errors, reduce workers and retry later.
Deterministic quote/conflict/override guards cover the supplied source constructions;
they are not universal language-understanding or prompt-injection detection.
The real model must still be evaluated with the source-grounded procedure.

Export writes one immutable generation from a single database snapshot and atomically
switches `deliverables/current`. Stable extraction and queue paths are symlinks
through it. A reader needing both files must resolve `current` once and read both
files in that resolved directory; independent reads can straddle publication.
Publication is serialized with a destination file lock. Earlier generations remain
under `.snapshots/`; pending work and full history remain in SQLite, separate from
terminal deliverables. Back up the database with SQLite's backup API, not by copying
an actively written database alone. Export publication after abrupt host power loss
and 2,000-document capacity were not tested. POSIX file locking/symlinks are required.

## Submission and human review

[Repair decisions](planning/repair-decisions.md) distinguish your actual choices
from agent recommendations. [Validation](planning/validation.md) maps requirements
to reproducible evidence; it is an agent assessment for your review. The original
audit is retained as `planning/validation-before-repair.md`.

Review `git diff` and the new files, run the commands yourself, then commit and push
the application, deliverables and facilitator-required session capture to `main`.
Entire is enabled, but its active session/commit association still needs verification
through the facilitator's setup. Do not substitute an agent-authored decision file
for your own session record. Submit only your root repository link in Classroom.
