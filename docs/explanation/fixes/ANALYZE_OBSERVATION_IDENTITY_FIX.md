# Analyze Observation Identity Fix (v0.261.398)

**Fixed/Implemented in version: 0.261.398**

Application version tracking remains in `application/single_app/config.py`.
This fix uses the existing Analyze producer, retained-result storage, and chat
interfaces. It adds no service, storage connection, administrator switch, or
deployment permission.

## Issue and root cause

A narrative review could read every source window, locate every supporting
quotation, and still stop before writing its answer. The failure appeared on a
later step as `input_partial_not_accepted`.

The collector used the source snapshot and model-generated `finding_key` as a
record identity. Two separately supported observations could share that key,
including within the same model response. The finalizer then merged their
public fields as though they described one structured record. Different
`finding` or `explanation` strings were classified as conflicting values, and
both observations were excluded.

The dependency guard correctly refused the resulting partial input. Disabling
that guard would have hidden the missing findings rather than fixed their loss.

## Explicit result semantics

The existing Analyze options now support a versioned distinction:

| Options | Interpretation |
|---|---|
| `analysis-options-v2`, `source_observations` | Each finding records an independently attributed source statement. A subject key may repeat. Supported statements can disagree without the application choosing one as the truth. |
| `analysis-options-v2`, `reconciled_records` | Findings describe structured records. Complementary fields may merge, while incompatible values, required-field failures, and calculation failures remain unresolved. |
| Unversioned options or `analysis-options-v1` | Preserve the existing `narrative_findings` record behavior. Historical requests and results are not silently upgraded. |

Newly generated orchestration plans explicitly select observation semantics
for ordinary narrative Analyze steps when the planner has not declared another
mode. Existing plan edits retain their declared semantics. Classic and workflow
configuration continue to use the shared options normalizer, so explicitly
configured modes are supported without changing unversioned configurations.

For example, a narrative Analyze step can declare:

```json
{
  "analysis_options": {
    "version": "analysis-options-v2",
    "mode": "source_observations"
  }
}
```

Observation mode rejects required reconciled fields and transformation rules.
It exposes the retained `findings` and `coverage`, plus a report when available,
but does not publish the optional reconciled `records` projection. Plan and
runtime output-contract validation reject that projection in observation mode.
Native spreadsheet computation is not replaced by this narrative contract.

## Identity, evidence, and compatibility

Observation identities are computed by the server from the source snapshot,
canonical public values, original evidence anchors, and caveats. They do not
depend on subject labels, window numbers, attempt numbers, or the evidence
matcher's presentation-normalization tier.

Distinct observations remain separate. Exact duplicates and identical replays
remain idempotent. No fuzzy comparison, key-suffix repair, extra adjudication
model, or filename/prompt classifier decides whether two observations survive.
The existing evidence matcher remains unchanged.

Malformed responses, unsupported findings, unavailable or ambiguous evidence,
changed source snapshots, and unfinished source work still fail or remain
partial. Matching a quotation establishes its location, not factual accuracy,
entailment, or an exhaustive review.

The semantic marker is saved in native validation metadata and propagated to
retained results. Native request fingerprints already include normalized
Analyze options, preventing reuse of a checkpoint under a different mode.
Existing saved attempts, record identities, and partial-result policies remain
unchanged.

## Inspecting work after a downstream failure

New orchestration replies can advertise their committed native analyses even
when a later step fails. Each descriptor is bound to the published assistant
message and its authorized producer. Reused work retains the original producer
identity and must match inherited checkpoint provenance.

Both chat interfaces accept plural `saved_analyses` and the existing singular
`saved_analysis`. Each retained analysis has its own step label, validation
notice, record pages, supporting evidence, and diagnostic link. A failed
reply's plural results do not automatically become the next composer context;
the user explicitly selects **Ask about this analysis**.

Counts and semantics come from the verified immutable manifest. Diagnostic
payloads remain separate, bounded, and excluded from canonical model input.
Existing conversation authorization, masking, and digest checks still apply.
Source-document access changes do not withdraw a result that remains readable
through its originating conversation.

This does not backfill old failed messages, turn inspection into completion,
or make an unchanged partial result acceptable to a complete-only consumer.

## Files and validation

The implementation updates the shared Analyze collector/finalizer, producer
guidance, orchestration capability/planner/schema, retained-result projection,
saved readers, terminal publication, and classic/React saved-result rendering.
No database migration or deployer change is required.

Regression coverage includes:

- `functional_tests/test_document_analysis_observation_identity.py`: repeated
  subject keys within/across windows, stable identities, replay deduplication,
  source revisions, caveats, invalid evidence, and preserved strict records.
- `functional_tests/test_orchestration_internal_analysis.py`: complete-only
  consumption, absence of an observation-only `records` alias, and composition
  with completeness verification still enabled.
- `functional_tests/test_orchestration_retained_analysis_publication.py`:
  immutable counts, true partial state, producer/digest authorization, and
  inherited checkpoint provenance.
- `ui_tests/test_chat_saved_analysis.py`: independent retained results in both
  interfaces, live completion/reload, explicit selection, malformed metadata,
  safe rendering, access changes, and responsive layout.
- `functional_tests/test_saved_analysis_cosmos_owner_contract.py`: installed-SDK
  point/write mappings, plain query rows, ETags, actor checks, concurrent changes,
  and existing artifact-binding owners.

The focused final regression run passed **420 tests**, and the classic/React
saved-analysis browser suite passed **68 tests**. Production frontend compilation,
TypeScript/JavaScript checks, and documentation coverage checks passed. Cosmos
boundary review has no outstanding inventory gaps.

Local replay of the incident's verified retained data isolated the identity
collision without changing finding values or evidence. Equivalent fictional
fixtures are used in the repository; private incident payloads are not
committed. The broader SDK test selection is not reported as passing: its
Windows command-line wrapper exceeded the argument limit, and isolated legacy
search-citation and credential-reconstruction failures also reproduce with
unchanged source modules. Separate legacy saved-compose/recovery fixture
failures were likewise reproduced on unchanged HEAD. This fix does not bypass
those failures or relax their production verification.

## User impact

After deployment, a fresh narrative orchestration plan can use the original
request without a prompt workaround. Supported observations no longer
disappear because they share a subject label. A source saying an item is open
and another saying it is closed can both be reported as source claims; the
application does not thereby certify the item's actual state.

See [saved Analyze results](../../guides/analyze-results.md) and
[orchestration recovery](../../admin/orchestration.md#failure-explanations-and-checkpoint-recovery)
for the reading and recovery workflows.
