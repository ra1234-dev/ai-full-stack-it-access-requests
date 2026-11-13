# Resubmission repair record — 2026-11-13

This is a new repair record, not a reconstruction of earlier ownership evidence.
The grader's `feedback.md` reports 15/36 artifact checkpoints and no evidence for
20 ownership checkpoints. An agent cannot guarantee 80 points or manufacture
personal decisions/session evidence.

## User decisions actually expressed in this session

- User requested reading feedback and all challenge instructions and fixing the work
  toward at least 80 points.
- Asked whether the proposed CLI/shared SQLite design fits the operators, the user
  replied **“shared SQLite is fine”**. This explicitly accepts shared SQLite; it
  does not supply a personal rationale or independently choose every CLI detail.
- Asked to review IT-019's requested new permission `read` and production routing
  to Security Review, the user replied **“I agree”**. The source says “change my
  current Beacon access in production from write to read”; policy rule 4 includes
  production. The source reasoning here was offered by the agent and accepted,
  not independently authored by the user.
- Asked to review retaining IT-006's legitimate read permission while flagging its
  injection and retaining IT-014's explicit reversed dates while clarifying them,
  the user replied **“I agree”**. This resolves Q-16/Q-18 for this implementation.
  It does not claim a general policy-owner ruling beyond this exercise.

## Agent implementation choices and reasons

- Finish the existing plan's missing steps rather than replace working validation.
  Baseline: 28 tests passed; no runnable entry point or current outputs existed.
- Use a CLI and one SQLite database on a shared host: short transactions and WAL
  let operators inspect completed work while model calls run outside the DB lock.
- Register immutable source bytes/settings and set the latest pointer before
  extraction. Tokens fence expired workers; old completions stay history and never
  repoint the current document. Terminal extraction and route are stored together.
- Use native Responses `text.format` strict JSON Schema with separate instructions
  and untrusted user message. Treat schema compliance and factual correctness as
  separate gates; refusals and incomplete responses never reach extraction parsing.
- Apply the five policy rules in order in deterministic Python; human reviewers
  retain all approval authority. Keep explicit conflicting facts unresolved.
- Re-extract on any relevant code/config/policy/source change rather than implement
  the plan's optional policy-only extraction reuse. This costs calls but keeps
  provenance simple. There are no automatic network retries.
- Keep mock replies separate from the pre-existing independent expectation files.
  Manually authored corpus mocks use source facts and purpose excerpts. A perfect
  mock score validates wiring, not language-model quality or an improved prompt.
- Keep both export files in an immutable generation and switch one symlink. POSIX
  destination locks serialize publication. Readers needing two files pin current.
- Save real failing test runs before implementation. The first six repair tests
  failed due to missing app modules/CLI. Additional HTTP tests caught 429/503
  becoming generic errors; safe categories were then implemented. The accuracy
  comparator and POST construction tests already passed on their first run;
  they were not artificially made to fail. No test-first commits were fabricated.

## Evidence and remaining human work

`repair-test-first.txt`, `repair-additional-test-first.txt` and
`repair-test-run.txt` are actual observed runs. Source-derived expectations predate
this repair. Review the purpose rubric and issue coverage yourself; an exact scalar
score does not prove faithful purpose summaries. Review the diff, record any
corrections and why you made them in your captured session, and inspect at least
two validation rows. Commit/push and session association are separate submission
steps; this document does not establish that either happened.

The final generated-change review used `git diff` and `git diff --no-index` to
inspect tracked and new source. It caught a native-response gate that assumed a
missing message status meant completed. A regression case failed before the fix
(`repair-native-status-test-first.txt`); the adapter now requires explicit completed
status on output messages and rejects missing status. This was an agent-found
review correction, not a user-authored discovery.
