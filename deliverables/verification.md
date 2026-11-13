# Verification and handover

Observation date: 2026-11-13. All observations here use saved mock replies or fake
HTTP transport, without `API_KEY` or a live model call. Configuration: Python 3.12,
requirements.lock, SQLite WAL on one local Linux filesystem, default 4-worker
intake, corpus fixture hashes recorded in each extraction. Real request evidence
is constructed for OpenAI gpt-4.1-mini-2025-04-14, temperature 0, 2500 output tokens,
strict JSON Schema, store=false; it is not a recorded live request/response.

## Commands and intended comparisons

From the root, after README setup/activation:

```bash
env -u API_KEY python3 -m unittest discover -s tests -v
python3 -m access_intake intake materials/requests --provider mock --db var/intake.sqlite
python3 -m access_intake intake tests/fixtures/exports/IT-001-paraphrase.json --provider mock --db var/intake.sqlite
python3 -m access_intake queue --db var/intake.sqlite
python3 -m access_intake pending --db var/intake.sqlite
python3 -m access_intake resume --db var/intake.sqlite
python3 -m access_intake export --db var/intake.sqlite --output deliverables
python3 -m access_intake accuracy --db var/intake.sqlite --output deliverables/accuracy.md
python3 -m access_intake request-evidence --output deliverables/request-evidence.json
```

Inspect 21 current records, no pending work, zero error records in this saved-reply
example. For each record, compare its original-byte hash with the source file,
its schema and exact quotes with the decoded message, and status/owner/action with
the ordered office policy. Queue and JSONL document, source, attempt and route must
agree. Run unchanged intake again: attempt IDs and provider-call count remain
unchanged. Run retry deliberately: history grows and the current attempt changes.

For a separate fresh source copy and new virtualenv, run:

```bash
python3 tools/verify_checkout.py
```

This installs the pinned dependencies. For an offline rerun after downloading the
wheels: `python3 tools/verify_checkout.py --wheels /tmp/access-intake-wheels`.
The observed clean run used those exact pinned wheels, downloaded from PyPI,
without any existing environment, database, outputs or Git metadata in the copy.
It verified README setup, all tests, intake, queue/pending, resume, export, accuracy,
request evidence, unchanged-attempt reuse and retry/history. The raw observed run
is `planning/repair-clean-checkout.txt`. This proves a clean source-copy workflow;
it does not establish that uncommitted files have been pushed to the fork.

## Automated evidence

| Case | Assertions and evidence |
|---|---|
| Whole corpus and paraphrase | `ApplicationTests.test_policy_corpus_and_paraphrase`: source-derived scalar facts and ordered route for all 21; exact quote validity and error=null. |
| Schema, evidence and malformed output | `ReplyValidationContract` covers missing/extra/wrong-type fields, enums, unsupported quotes, null explanations, conflicts, malformed envelopes/JSON, refusal and incomplete statuses. |
| Source identity, metadata, 200 words | `ExportAndOracleContract` checks original bytes/hashes, independent messages, invalid inputs, full decoded text, oracle annotations and both authored paraphrases. |
| Unchanged/new/changed/settings/omitted source | `ApplicationTests.test_reuse_change_settings_omission_and_failed_retry`: unchanged call count, no withdrawal by omission, new hash for changed bytes, new call for settings change. |
| Failure after success | Same test forces a timeout on a later retry: current extraction=null/error; prior success and hash remain in history. |
| Slow work within one batch | `WorkerVisibilityTests.test_one_batch_publishes_fast_work_before_slow_work`: a barrier holds IT-001 while IT-002 commits and remains inspectable; after release both finish. |
| Overlapping operators and revisions | `ApplicationTests.test_slow_and_overlapping_operators_latest_revision_wins`: duplicate work is not claimed twice, another request completes, old-generation completion cannot replace new-generation current. |
| Interrupted worker | `ApplicationTests.test_expired_claim_resume_and_snapshot_consistency`: an expired running claim is resumed; finished work has consistent extraction/queue IDs, hashes, attempt and route. This simulates abandonment; it is not a killed-host experiment. |
| Real HTTP request construction | `TransportTests.test_real_http_transport_builds_post_and_sets_timeout_without_network`: actual urllib transport builds POST, Authorization header, native schema and configured timeout; fake urlopen returns the saved reply. |
| Provider protocol gates/redaction | `ProviderAdapterTests.test_native_schema_request_and_response_gates`: strict native schema, model ID, untrusted message separation, redacted evidence, refusal/incomplete/malformed replies. |
| Rate limit, unavailable and auth errors | `TransportTests.test_rate_limits_and_unavailability_are_safe_and_retryable`: HTTP 429/503/401 use safe categories, one call, null extraction, no synthetic secret in results. |
| CLI | `ApplicationTests.test_cli_clean_workflow_and_retry_command`: real subprocess intake, queue, pending, resume, retry, history and export against a temporary DB. |
| Honest comparison | `AccuracyTests.test_fixed_denominator_missing_outputs_and_wrong_fact`: no-output penalty, deliberate wrong permission mismatch, whole-document mismatch, duplicate rejection. |

## Observed results and repairs

- Before this repair, 28 tests passed, but intake could not run and no provider
  integration, persistent queue or submission deliverables existed.
- The first six new acceptance tests failed before implementation; actual log:
  `planning/repair-test-first.txt`. Missing modules/CLI were the cause.
- HTTP-specific tests then exposed generic error categories for 429/503; actual
  failure log: `planning/repair-additional-test-first.txt`. Extraction now maps
  those to rate_limit/provider_unavailable without printing response bodies/keys.
  Tests already passing when added are not represented as observed failures.
- The repaired suite passes **38 tests**; `planning/repair-test-run.txt`.
- Clean source-copy workflow passed; `planning/repair-clean-checkout.txt`.
- Saved-reply comparison: **231/231 scalar comparisons, 21/21 routes, 21 current
  records, zero errors**. Three scalar comparisons use the user-agreed IT-006 and
  IT-014 interpretations. `deliverables/accuracy.md` documents every expectation,
  denominator, mismatch list and source/policy evidence. This is mock wiring
  evidence, not a live model accuracy score.
- Corpus mock purpose summaries were refined against message text to include core
  intent, with whole-message exact evidence preserving alternatives/corrections.
  The agent reviewed source grounding; no independent human purpose-score review
  is claimed. Human review uses the supplied purpose rubrics.

## Operating limits and remaining submission evidence

Use one shared database on one POSIX host/local disk; no multi-host replicated DB,
network-mounted SQLite or Windows symlink/locking support is claimed. Worker count
is bounded; no throughput or cost claim is made for 200–400/day or 2,000-message
batches. The model key/account, live extraction quality and provider quotas were
not tested. There is no automatic backoff or hidden retry. Socket timeouts are not
absolute wall-clock deadlines. After interruption, wait for lease expiry then
resume. After code/config changes, intake/refresh establishes current fingerprints.
External calls can repeat after a crash before commit; late fenced workers cannot
publish results under a reclaimed token.

Publication uses an atomic pointer and two consistent immutable files, serialized
by a destination lock. Readers needing both must pin current once. Readers of two
independent stable paths can straddle publication. Power-loss export durability,
actual process/host-kill recovery, sustained large batches and multi-process export
stress were not experimentally measured; do not infer them from unit tests.
SQLite transactions and generation guards are the implemented protections.

The agent evidence assessment in planning/validation.md awaits the user's own
review. Existing expectations contain historical open-question annotations;
planning/repair-decisions.md records the actual user agreements that resolve them
for this implementation. Neither document invents earlier ownership evidence.
Entire is enabled, but a final commit/session association and remote submission
must still be checked with the facilitator's capture setup. Review the diff, run
the commands yourself, commit and push the required files/session capture, then
submit only the repository root URL through Classroom.

Final source review repair: a native output message without completion metadata
was initially accepted if the response as a whole was completed. The added case
failed before repair (`planning/repair-native-status-test-first.txt`). The adapter
now requires explicit message completion; missing metadata is malformed. The final
38-test run and clean source-copy run include this regression case.
