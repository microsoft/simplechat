# Generated Artifact Paging, Truncation, and Guidance Carry-Forward Fix

**Fixed in version: 0.260.011**

## Issue Description

A deployment test of the generated-file work from `0.260.004` through `0.260.010` surfaced three
defects in agent conversations that produced CSV artifacts from a Yamcs telemetry action.

1. **The model denied it could create a file, then the file appeared anyway.** After answering a
   schema clarification with "yes and all columns", the assistant replied *"I cannot create or
   attach a CSV file in this interface"* and listed the columns as prose. The server published the
   CSV regardless, so the user saw a contradiction between the reply and the artifact card.
2. **A 1,000-row file was produced for a window holding roughly 500 distinct samples.** The agent
   called `list_parameter_history` twice, and the server concatenated both responses.
3. **A partial file was published with no indication it was partial.** The source action returned
   500 rows and reported `truncated=True`, and the assistant said so in prose, but the artifact card
   presented a plain 500-row file.

## Root Cause Analysis

### 1. Publication contract resolved, guidance not

Version `0.260.008` added `resolve_pending_generated_file_format` so a reply that only answers a
clarification still *publishes* the originally requested artifact. Guidance injection was never
updated to match. Both chat paths resolved the guidance format from the current user message alone:

```python
requested_format=get_tabular_generated_output_format(user_message)
```

"yes and all columns" contains no format keyword, so `build_generated_file_output_guidance` returned
an empty string and no system message was added. The model was never told that the server attaches
the file, so it fell back to its default belief that it cannot produce attachments — while the
finalizer, which *did* carry the format forward, published the CSV.

### 2. Overlapping pages concatenated

Version `0.260.008` grouped rows by action so paged calls to one action stayed one dataset, using
`.extend()`. The deployment log shows the agent did not page forward; it re-requested the same
window with an earlier stop time:

```
list_parameter_history  start=20:40:57.445  stop=20:55:57.445  row_count=500  truncated=True
list_parameter_history  start=20:40:57.445  stop=20:49:17.445  row_count=500  truncated=True
```

Both calls share a start time, and both were capped at the action's own `max_rows` limit, so the
second response returned the same first 500 samples. Concatenation produced 1,000 rows for roughly
500 distinct samples. The same pattern explains the earlier "901 acquired samples" claim
(500 truncated + 401 overlapping).

### 3. Truncation signal discarded

Action payloads carried `truncated: true`, but nothing read it. `_assistant_content_disclaims_complete_file`
existed for JSON and XML only and matched assistant prose rather than the action's own report, so no
format surfaced source truncation on the artifact.

The 500-row cap itself is the action's configured `max_rows`, not a SimpleChat limit. The fix makes
the cap visible and teaches the model to page past it rather than silently changing plugin behavior.

## Technical Details

### Files Modified

| File | Change |
|------|--------|
| `application/single_app/functions_generated_file_exports.py` | Cross-page row de-duplication, truncation detection and propagation, paging guidance |
| `application/single_app/route_backend_chats.py` | `_resolve_generated_file_guidance_format` helper wired into both chat paths |
| `application/single_app/static/js/chat/chat-messages.js` | `Partial` badge on the generated artifact card |
| `application/single_app/config.py` | Version bump to `0.260.011` |
| `functional_tests/test_generated_csv_uses_authorized_action_rows.py` | Telemetry fixture now uses distinct sample times |

### Code Changes

**Guidance carry-forward.** A new route helper resolves the format the reply owes, falling back to the
pending clarification when the message itself names no format:

```python
def _resolve_generated_file_guidance_format(user_question, conversation_id, user_id):
    requested_format = str(get_tabular_generated_output_format(user_question) or '').strip().lower()
    if requested_format or not conversation_id:
        return requested_format
    pending_format = _resolve_pending_generated_file_format(user_question, conversation_id, user_id)
    return str(pending_format or '').strip().lower()
```

Both the streaming and non-streaming chat paths now call it. In the streaming path it also drives the
payload-suppression decision and the "generating file" status banner, so the answer turn behaves like
the turn that made the original request.

**Cross-page de-duplication.** `_collect_authorized_function_row_groups` now tracks a row signature per
action label. Repeats *inside* one response are kept, because the action counted them as distinct
records; rows an *earlier page of the same action* already contributed are dropped:

```python
page_signatures = set()
for structured_row in structured_rows:
    row_signature = _build_function_result_row_signature(structured_row)
    if row_signature is not None:
        if row_signature in seen_rows:
            continue
        page_signatures.add(row_signature)
    group_rows.append(structured_row)
seen_rows.update(page_signatures)
```

**Truncation disclosure.** `function_results_report_truncated_rows` scans row-contributing action
payloads for `truncated`, `is_truncated`, `was_truncated`, `results_truncated`, or `rows_truncated`.
The flag flows into the export payload, the summary text, and the artifact metadata, and is captured
separately for reach-back rows so a file built from an earlier turn keeps that turn's signal.

**Paging guidance.** CSV, DOCX, and PDF guidance now includes:

> When an action reports that its results were truncated, request the remaining data with a window
> that starts after the last row you already have instead of repeating the original range, and say
> plainly that the data is partial if you cannot retrieve the rest.

JSON and XML are excluded because their guidance requires a payload-only reply.

### Fixture Correction

`TELEMETRY_ROWS` in `test_generated_csv_uses_authorized_action_rows.py` previously derived timestamps
from `index % 60`, so its 900 "samples" were only 60 distinct rows repeated fifteen times. That made
genuine continuation pages indistinguishable from re-reads. Timestamps now roll over into minutes,
which matches the 15-minute high-granularity window the fixture's question asks for.

## Validation

### Test Results

| Suite | Result |
|---|---|
| `test_generated_artifact_paging_and_guidance.py` | 11/11 |
| `test_generated_csv_uses_authorized_action_rows.py` | 15/15 |
| `test_generated_structured_artifact_parity.py` | 8/8 |
| `test_assistant_table_csv_artifact.py` | 36/36 |
| `test_generated_json_xml_exports.py` | 7/7 |
| `test_tabular_passthrough_heterogeneous_rows.py` | 4/4 |
| `test_tabular_background_generated_exports.py` | 8/8 |
| `test_tabular_row_orchestration_scale.py` | 15/15 |
| `route_tests/test_route_blueprint_policy_inventory.py` | 6/6 |
| `route_tests/test_route_unauthenticated_policy_contract.py` | 4/4 |

### Before and After

| Scenario | Before | After |
|---|---|---|
| Answering a schema clarification | No file guidance injected; model denies it can attach files, server publishes anyway | Publication contract injected; reply and artifact agree |
| Two calls re-reading one window | 1,000 rows, roughly half duplicated | Distinct rows only |
| Two calls paging forward | Both pages kept | Both pages kept (unchanged) |
| Action reports `truncated=True` | Silent, file looks complete | `Partial` badge, summary note, `rows_truncated` on the artifact |
| Repeated identical rows in one response | All kept | All kept (unchanged) |

## Known Limitations

- De-duplication compares full row values. A continuation page whose rows differ only in a field the
  action omits from its response would still be treated as a repeat.
- The paging instruction is model guidance, not enforcement. An agent that ignores it still produces
  a truncated dataset, but the file is now labeled partial.
- The per-call row cap belongs to the action's own configuration. Raising it is a plugin
  configuration change, not an application change.

## Related Documentation

- `docs/explanation/fixes/GENERATED_JSON_XML_EXPORTS_FIX.md`
- `docs/explanation/fixes/GENERATED_STRUCTURED_ARTIFACT_INTENT_FIX.md`
