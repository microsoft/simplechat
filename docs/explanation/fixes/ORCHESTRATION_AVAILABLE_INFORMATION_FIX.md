# Orchestration available-information responses fix (v0.261.399)

Fixed/Implemented in version: **0.261.399**, recorded in
`application/single_app/config.py`.

## Issue and root cause

An orchestration could retain useful, source-bound findings but stop its answer
or narrative report because other findings remained unresolved. A complete-only
input refused the retained partial result; partial status then propagated through
preparation, file readiness, finalization, and the React recovery UI. The user
received a partially-completed error and sometimes only a saved-attempt review
action. An unchanged retry could not create the missing information.

Evidence completeness, narrative preparation, and successful delivery were being
treated as the same guarantee. Allowing every partial input, hiding the error
banner, or increasing retries would not resolve that mismatch safely.

The change builds on [PR #1874](https://github.com/microsoft/simplechat/pull/1874),
which separates independent source observations from reconciled records and
preserves inspection of retained analyses.

## Response behavior

Ordinary narrative plans explicitly use the available-information policy. The
answer addresses supported questions and says what cannot be determined from the
available material. Material source disagreement is attributed rather than
silently resolved. The same limitations appear in requested narrative documents,
not just in chat metadata.

Missing facts alone do not produce a partial-completion error or a failed answer
card. Run details describe the retained information as **Results with limits**.
Actual tool, verification, storage, rendering, and publication failures remain
distinct failures; an unread source is not proof that a fact is absent.

## Technical changes

The existing contract and schema owners declare narrative policy before plan
approval. Stored older plans retain their original semantics. Eligible narrative
outputs receive a producer-owned `prepared_narrative_v1` readiness check in their
immutable result manifest.

The result itself can remain partial. The executor recognizes a completed
narrative consumer and the information it actually consumed, rather than
promoting the original source or an unrelated required task to complete. Strict
dataset consumers continue to reject partial inputs.

Composition and native-report verification use the accepted retained findings.
Unresolved candidates remain diagnostic data, not factual model input. A native
report selected as the final answer is checked without rewriting its source
results. The shared checker
preserves application-owned obligations, resolves exact evidence aliases,
separates content preparation from later delivery, and supports bounded
evidence-preserving answer repair. One durable assessment-protocol repair is
available without resetting the answer-correction allowance.

Narrative export adapters, durable output admission, and bootstrap authorization
accept only the attested narrative representations for their explicit profiles.
Every declared character/value must still be consumed and checked before a file
is published. Record counts, schemas, calculations, integrity checks, and exact
export guarantees are unchanged.

Key owners include:

- `functions_orchestration_result_contracts.py`, schema, registry, and planner:
  explicit policy, representation checks, and immutable readiness.
- `functions_task_completeness.py` and orchestration composition: stable
  obligations, exact evidence references, bounded repair, and honest unknowns.
- Orchestration executor, export source, rendering, output store, and bootstrap
  owners: separate response completion from evidence coverage across delivery.
- Orchestration recovery, services, and saved-analysis owners: verified source
  reuse and original analysis identity across linked attempts.
- React orchestration controller, state readers, Run view, recovery notice, and
  deliverable projection: consistent live and saved outcomes.

No new dependency, storage service, administrator setting, or public route is
introduced.

## Existing blocked runs

**Use available information** is offered only when the server can verify reusable
accepted findings and the remaining work is narrative preparation/rendering. The
explicit request creates a linked output-only attempt. It does not reanalyze
sources or replay completed agents, actions, or workflows.

The original plan, native result, and producer identity remain intact. Reused
checkpoint state is validated against its original context and captured digest
before being bound to the approved narrative policy. The copy has its own
checkpoint identity while its original production provenance remains intact,
including across a later ordinary file retry.
Saved-analysis descriptors continue to identify that original producer.

Current retained-result ownership, lineage integrity, external-source
authorization, concurrency, idempotency, and durable budgets still apply.
Unavailable checkpoints and changed context are not repaired by guessing.

## Validation and limitations

`functional_tests/test_orchestration_available_information.py` exercises real
contracts, source analysis, preparation, immutable readers, output admission,
publication, and downloads with external I/O isolated. It covers:

- Supported information with explicit gaps, without promoting partial data.
- Malformed-assessment repair, fixed obligations, and interruption safety.
- Rejection of invented evidence paths, identifier fragments, and dataset
  misuse.
- Actual Markdown, Word, and PDF content containing the qualified answer.
- Native reports, including no accepted findings, with check-only verification.
- Linked continuation without repeated source/model work, changed-request and
  provenance rejection, durable reload, and idempotent retry submission.

`ui_tests/test_v2_orchestration_recovery.py` exercises real React components,
controller, SSE handling, stores, and run details. Coverage includes live and
reloaded normal answers, desktop/mobile states, explicit continuation, rejection
of unverified control flags, and existing genuine failure/recovery behavior.

Local validation includes **182 focused functional tests**, **462 healthy
runtime/contract compatibility tests**, **64 real-SDK owner tests with network
access blocked**, **60 Chromium recovery tests**, and **24 frontend projection
tests**. These selections overlap and are not an aggregate test count. The
production frontend build passes, route policy checks pass **28/28**, and
documentation coverage and site quality pass **7/7** and **6/6**. The reviewed
Cosmos inventory has **1086 owners, 423 doubles, and zero review gaps**.

The broader legacy dependency-recovery and service-source-policy suites are not
reported as green: their **17 failures and 37 passes** reproduce with unchanged
production modules from baseline `13db87662` and with this change. The same
failing test identifiers and assertions were retained; no skips, suppressions,
or weakened production guards were added to hide them.

The full SDK runtime gate is not green. Its normal Windows launch encounters
the command-line length limit (`WinError 206`). Running its exact **184-selector**
selection in-process avoids that limit but stops after nine passes at the
credential-reconstruction case
`test_shared_chat_private_prompt_and_exact_continuation[scenario0]`, whose fresh
child reports "Initial tool boundaries were not retained." The same assertion
reproduces in that actual fresh child with original production modules from
`13db87662`; the baseline overlay is not limited to the parent test process.
No credential guard or test suppression was changed to conceal it.

Model assessments remain model judgments, not proof of factual accuracy. These
offline regressions establish control-flow and boundary behavior, not a live
false-acceptance or false-rejection rate. No production replay, historical
status rewrite, database migration, or deployment is included.
