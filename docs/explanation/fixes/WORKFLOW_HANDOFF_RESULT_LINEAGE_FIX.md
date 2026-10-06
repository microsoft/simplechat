# Workflow Hand-off Result Lineage Fix

**Version: 0.261.252**

Fixed in version: **0.261.252**, recorded in
`application/single_app/config.py`.

This affects the React V2 branch (`paullizer-react-v2-ui`) and deployments built
from it. It follows up
[#1640](https://github.com/microsoft/simplechat/pull/1640), which added workflow
hand-off from chat, and is part of
[#1549](https://github.com/microsoft/simplechat/issues/1549) and
[#1543](https://github.com/microsoft/simplechat/issues/1543). Hand-off is behind
the **Hand Off Large Work From Chat** setting
(`enable_chat_orchestration_workflow_handoff`), which is off by default.

## Issue

The workflow result reader read a chat hand-off's report without re-proving
where the report's inputs came from.

When a hand-off run finishes, workflow result delivery reads the run's one
output, the report node's text, and posts it into the conversation. The reader
checked the report's stored result: its node identity against the saved
workflow, its text output against the run's receipt, and the completion rule.
It never checked the report's consumed-input receipts, which name the parent
results the report was written from.

So a stored report whose receipts didn't chain to real results of the run still
read as available. A report saved again with `consumed_inputs` set to
`[{"malformed_receipt": true}]`, under its own valid hash, read with
`available: true` and its full text. The shared node lineage authorizer refuses
the same result with `analysis_lineage_invalid`. A missing or damaged parent
result didn't stop the read either.

The reader's general path, for runs that aren't structured, walks this lineage
for every task row before it reads any result. The hand-off feature doc said the
hand-off read did the same.

## Root cause

Phase 7a added `_read_handoff_result()` to
`functions_workflow_result_reader.py`, a narrow path that opens only a hand-off
run's report. It loads the report's manifest with `load_node_result()`, which
recomputes the node identity from the saved workflow, so an edited or
re-enabled workflow already failed closed before any load. The general path's
lineage check, `authorize_workflow_run_read()`, walks every task row, and the
hand-off path didn't replace it with a check of its own report. Nothing walked
the report's lineage.

## Changes

### The hand-off read walks the report's lineage

After the manifest, identity, output and completion checks, and before the
result is described or excerpted, `_read_handoff_result()` now calls the shared
node lineage authorizer:

```python
_guarded("authorize", lambda: authorize_workflow_node_result_read(
    workflow, run_id, producer, receipt["result_ref"], reader_user_id=user_id,
    manifest=manifest, load_result=loader, include_sources=False,
))
```

- The walk proves that each result belongs to this workflow and run, that its
  hashes and references match, and that each consumed-input receipt chains to a
  real parent result. It also covers selected producers, iteration paths, repeat
  state and frozen loops.
- It walks the saved workflow, the same definition `load_node_result()` checks
  the report's identity against. An edited or re-enabled workflow still fails
  closed before any load.
- It runs for the descriptor-only read and the excerpt read alike. A stored chat
  context that refers to the report is read the descriptor-only way, so it's
  re-proved too.
- It reuses the reader's manifest memo and the report manifest the reader has
  already loaded.
- `include_sources=False` skips keeping the list of contributing sources, which
  the reader doesn't use. The walk never re-resolves sources either way.
- `read_workflow_result()` passes its `user_id`, which it has already matched to
  the workflow's owner.

Failures are logged at stage `authorize` and map to the same codes the general
path uses:

| Failure | Code |
| --- | --- |
| A receipt that doesn't chain, or a parent whose output disagrees with the receipt | `workflow_result_invalid` |
| A parent whose stored bytes don't match its hash | `workflow_result_invalid` |
| A missing parent result | `workflow_result_not_found` (404) |

The authorizer itself didn't change.

### Recaptured hand-off off-golden

`functional_tests/test_orchestration_workflow_handoff_off_golden.py` checks that
planning is byte-identical when hand-off is unavailable. On V2 after #1640
merged, 4 of its 10 cases failed: the `absent`, `false`, `on` and `string` cases
of `test_planning_is_byte_identical_when_handoff_is_unavailable`.

Its fixture was captured on f1aeef13d (0.261.233), before
[#1641](https://github.com/microsoft/simplechat/pull/1641) added file merging
and changed the planner's content. The Phase 7a branch's last commit,
5a625599c, recaptured the fixture with `--write-golden` on unmodified V2
a5a5b1c5 (0.261.248), but it wasn't pushed before #1640 merged.

This fix cherry-picks that commit unchanged with `git cherry-pick -x`. It changes
only the test's `CAPTURED_FROM` value and docstring line, and the JSON fixture,
whose blob is `f93f8e4c3dcc263cc5a71186f2cecc8c60574098`. A separate recapture
on a fresh worktree at a5a5b1c5 produced the same bytes. The test's
regeneration instructions didn't change.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_workflow_result_reader.py` | The hand-off read walks the report's lineage. |
| `functional_tests/test_workflow_handoff_result_reader.py` | A fixture with real lineage, and the tests below. |
| `functional_tests/test_orchestration_workflow_handoff_off_golden.py`, `functional_tests/test_support/orchestration_workflow_handoff_off_golden.json` | The recaptured fixture. |
| `functional_tests/test_workflow_handoff_builder.py` | The Phase 4 schema digest pin, refreshed to the a5a5b1c53 value. |
| `docs/explanation/features/CHAT_ORCHESTRATION_WORKFLOW_HANDOFF.md` | The reader's checks, the performance note, and the files and test tables. |
| `docs/explanation/release_notes.md` | 0.261.252. |
| `application/single_app/config.py` | Version `0.261.252`. |

## Validation

### Tests

`functional_tests/test_workflow_handoff_result_reader.py` uses the real hand-off
builder, result contract, node identity, lineage authorizer and reader, with
fake containers and an in-memory result store. Nothing on the lineage path is
stubbed. The new tests:

- A report with a malformed consumed-input receipt is refused with
  `workflow_result_invalid` for the excerpt read, the descriptor-only read and a
  stored chat context. Only the report's manifest is loaded; its text and pages
  never are. With the walk removed, the same report reads as available.
- A report with real lineage reads. Its parent is a real `collect` node result,
  built and saved through the runner's result contract, and its receipt comes
  from opening that result as the report's `findings` input. The read loads the
  report's manifest, the parent, then the report's text, and returns the exact
  report text. With the walk removed, the result is identical and only the
  parent's load disappears, so the walk is really exercised.
- A descriptor-only read of that report loads its manifest and the parent, and no
  section or page.
- A missing parent is refused with `workflow_result_not_found` (404) at stage
  `authorize`. The general path returns the same code, status and stage for the
  same failure.
- A parent whose output reference disagrees with the receipt, from either side,
  is refused with `workflow_result_invalid`. So is a parent whose stored bytes
  don't match its hash, checked with the result store's own hash verification.
- On the fixture with real lineage, a definition edit, turning the workflow on,
  an alert change or a Run as change is refused before any load, as on the
  original fixture.

Each of these deliberate breaks makes tests fail, except one equivalent change:

| Break | Result |
| --- | --- |
| No lineage walk | 7 tests fail |
| Walk only for excerpt reads | 6 tests fail, the descriptor-only refusals |
| `include_sources=True` | No test fails. The change is equivalent: the reader discards the authorizer's access summary. |
| Failures logged at stage `manifest` | 5 tests fail, on the logged stage |

`functional_tests/test_workflow_handoff_end_to_end.py` runs 3-document and
200-document hand-offs through the real durable runtime, runner and reader. A
temporary probe, not committed, confirmed that each report read walks the
lineage once and the walk succeeds. With the walk removed, the 3-document read
drops from 27 node-result loads to 2, and the 200-document read from 1,409 to
2.

### Phase 4 digest pin

`functional_tests/test_workflow_handoff_builder.py` pins digests of the Phase 4
blueprint schema, payloads, validation and dry run, to prove hand-off left them
unchanged. Its `test_the_phase_4_blueprint_and_payloads_are_unchanged` failed at
15feec650 because the schema pin predated
[#1641](https://github.com/microsoft/simplechat/pull/1641), which added the
`merge` task schema. The pin now holds the value V2 computes at a5a5b1c53, after
#1641 and before hand-off merged, so the test still proves hand-off didn't change
the Phase 4 schema. The other four pins are unchanged.

### Before and after

| Before | After |
| --- | --- |
| A report whose consumed-input receipts don't chain to the run's results is read and posted to chat. | It's refused with `workflow_result_invalid` before its text is loaded. |
| A missing or damaged parent result doesn't stop the read. | A missing parent is `workflow_result_not_found`; a damaged one is `workflow_result_invalid`. |
| A hand-off's report read loads the report's manifest and text. | It also walks the report's lineage. The 200-document read makes 1,409 node-result loads, about 1.7 seconds with the in-memory store. |
| The hand-off off-golden failed 4 of 10 cases. | It passes 10 of 10 under pytest, optimized pytest, and as a normal or optimized script. |

## Limitations

- Every read walks the report's lineage again; nothing is cached between reads,
  as on the general path. Each load is a separate read from the result store,
  about seven per document in the 200-document test.
- The walk doesn't check a report's consumed inputs against the inputs the
  compiled flow declares. That's how the shared authorizer works, and it's
  unchanged.

## Related

- [Chat orchestration workflow hand-off](../features/CHAT_ORCHESTRATION_WORKFLOW_HANDOFF.md#result-reading-and-delivery)
- [Workflow saved result source re-check fix](WORKFLOW_SAVED_RESULT_SOURCE_RECHECK_FIX.md)
