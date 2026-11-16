# Orchestration reasoning-level compatibility

**Version: 0.261.104**

**Fixed in version: 0.261.104**, tracked by `VERSION` in
`application/single_app/config.py`.

## Issue and root cause

Plan edits could fail while Auto or Review -> Run failed during answer generation.
The selected GPT-5.6 Luna deployment rejected `reasoning_effort="minimal"` and
reported the supported levels as None, Low, Medium, High, and XHigh.

Both interfaces used outdated family-based reasoning choices. The V2 picker also
inferred support from a preference key that could be an opaque model UUID.
Orchestration passed the unsupported level to the provider. Initial planning
concealed its failure with a direct-answer fallback, whereas editing correctly
kept the previous plan. Ordinary chat appeared to work because it retried without
the effort parameter; that did not mean Minimal had been honored.

## Runtime policy

`static/json/model_capabilities.json` now carries additive reasoning policies.
`functions_model_capabilities.py` resolves the allowed levels from authorized
canonical model metadata and declared aliases, independently of preference IDs.
Existing non-reasoning and vision capability records are preserved.

| Request | Effective behavior |
| --- | --- |
| Supported explicit level | Send it unchanged, including literal `none`. |
| Unsupported level on a known model | Use its supported application default and show the correction. Luna Minimal becomes Low. |
| No requested level | Omit the parameter; report model default. |
| Unsupported or unknown reasoning support | Do not invent allowed levels. Omit the parameter and explain any discarded explicit choice. |
| Provider rejects `reasoning_effort` | Retry once without that parameter only for the specific SDK HTTP 400 parameter/code rejection. Preserve the model and other valid arguments. |
| Other provider failure | Propagate the failure; do not disguise it as compatibility recovery. |

Low is the application's preferred supported fallback, not a claim about the
provider's default. Model-default mode does not assert which effort the provider
actually used.

`model_endpoint_clients.py`, `functions_orchestration_models.py`, and
`route_backend_chats.py` share this policy. A dedicated planner override keeps its
own policy instead of inheriting the answer model's effort. JSON-format recovery
is separate and only handles a rejected `response_format`.
If both parameters are rejected, the binding remembers the reasoning omission
before attempting recovery. A later JSON-format retry does not resend the
rejected effort or reset its retry allowance. Model-default metadata survives
even when the intermediate retry raises; a different explicit per-call effort
retains its independent policy.

## User-visible behavior and persistence

V2 and classic selectors receive safe `reasoning_capabilities` metadata from
`route_frontend_chats.py`. They retain the existing preference keys and merge
corrected selections after preferences load rather than replacing unrelated
model preferences.

Live updates are merged by model and stage before filtering notices. A later
resolution with no adjustment clears that stage's obsolete warning without
removing a separate planner or answer correction.

Corrections appear in the composer or relevant plan/answer surface. Saved message
and run metadata distinguish:

| Field | Meaning |
| --- | --- |
| `requested_reasoning_effort` | The original requested level. |
| `reasoning_effort` | The effective explicit level, or null for model default. |
| `reasoning_mode` | `explicit` or `model_default`. |
| `reasoning_adjustments` | Safe requested/effective values, reason, canonical model name, and planner/answer stage. |

The orchestration events, editor publication, and hydration projections preserve
these notices. Display metadata does not rewrite immutable historical plans, add
fake revisions, retarget models, or alter approval and concurrency rules. A
failed edit still leaves the previous valid plan intact. Initial planning now
also reports failures instead of manufacturing a successful direct-answer plan.

## Validation and limitations

Canonical policy and provider-error behavior are covered by
`functional_tests/test_model_reasoning_capability_resolution.py` and
`functional_tests/test_orchestration_model_selection.py`. Ordinary streaming and
non-streaming paths are covered by `test_chat_reasoning_runtime.py`; empty-stream
recovery has separate regression coverage. Combined reasoning/JSON rejection
cases exercise both retry orders and require no more than three requests, with
unchanged model identity, messages, and completion budget.

`ui_tests/test_v2_reasoning_controls.py` exercises real composer behavior.
`ui_tests/test_v2_orchestration_plan_editor_backend.py` forwards browser requests
to the real Flask handlers, including stale Luna Minimal, a Web Search edit, and
Run. Provider and storage boundaries are deterministic; these are not live
model-quality evaluations.

No API-version migration or Azure configuration change is required. The code
must still be deployed before an existing hosted application gains this fix.
