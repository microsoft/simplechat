# Model-assisted answer completeness

Implemented in version: **0.261.382** (`application/single_app/config.py`).
Updated in version: **0.261.399** (`application/single_app/config.py`).

## Purpose

An answer can match its JSON schema while omitting facts the task explicitly
requested. Model-assisted completeness checks address that gap in generated
workflow answers and orchestration content preparation. They are separate from
tool success, schema validation, source coverage, authorization and content safety.

Both checks are enabled by default. They do not enable workflows or orchestration
when those parent capabilities are disabled.

## Checking and correction

The checker receives the scoped instructions, output contract, authoritative
candidate and authorized available evidence. It assesses explicit requirements as
satisfied, missing, unsupported, conflicting or uncertain. Equivalent wording and
formatting are allowed; incidental source properties do not become requirements.

The default sequence is:

1. Check the original candidate.
2. Correct an omission using available evidence, then check again.
3. If needed, correct once more and check the final candidate.

Any passing check ends the sequence immediately. Every corrected candidate is
checked before delivery or another correction. Structural checks run first; an
invalid structure is a failed check, not permission to deliver or bypass the
allowance. Orchestration format, required-visual and completeness repairs share
one allowance rather than running separate repair loops.

Unsupported facts, instruction/schema conflicts and uncertain judgments cannot
certify completion. They do not authorize fabricated data. Invalid checker output,
provider failure and unavailable context produce **Verification unavailable**, not
a successful result. An explicit unknown is acceptable only where the task and
partial-result contract permit it.

### Available-information narrative responses

Implemented in version: **0.261.399**, recorded in
`application/single_app/config.py`.

New ordinary narrative plans explicitly declare `response_policy:
available_information`. A supported answer or a precise explanation of what
cannot be determined handles a requested question; the checker must not require
invented facts or treat limited evidence as an execution failure.

The application supplies stable obligations for requested content, supported
claims, and material limitations before assessment. A checker cannot drop an
obligation to obtain a passing result. It checks prepared content separately
from later file creation or delivery, which retain their own execution checks.
Missing information is explained naturally, without a mandatory generic warning
or coverage appendix.

Within the existing answer-correction allowance, an unsupported assertion may be
removed or replaced by an honest limitation, then checked again. The supported
content and requested scope must be preserved. One malformed assessment can
receive a separate bounded protocol repair without rewriting the candidate;
reservation is persisted before the call, so interruption does not start an
uncounted duplicate repair. Persistent assessment failure remains verification
unavailable, never approval by default.

Evidence aliases resolve real paths and exact identifier values, not substrings
of serialized source prose. Accepted source findings remain distinct from
unresolved diagnostic candidates. A narrative readiness attestation is bound
to the retained result manifest; it does not promote partial source data to
complete data. Exact datasets, calculations, and closed schemas remain strict.

The same distinction permits prepared narrative files to contain supported
information and material gaps while preserving their full-consumption,
integrity, ownership, and publication checks. There is no new administrator
switch.

## Administration

| Setting | Default | Behavior |
| --- | --- | --- |
| `enable_workflow_completeness_check` | On | Check generated workflow task answers before downstream use. |
| `workflow_completeness_max_corrections` | 2 | Answer-only corrective generations per workflow task. |
| `enable_chat_orchestration_completeness_check` | On | Check content preparation and the designated final composition. |
| `chat_orchestration_completeness_max_corrections` | 2 | Shared format, visual and semantic correction allowance per composition. |

Correction limits accept 0-5. Zero still checks but does not correct. Turning a
check off restores previous execution behavior, including orchestration's existing
single format/visual correction. Missing settings on upgrade use the enabled
default; explicit false and zero remain meaningful.

Use the Workflow and Chat Orchestration admin sections in either admin interface.
The orchestration execution interface itself is V2-only.

## Architecture and evidence boundaries

`functions_task_completeness.py` owns strict report validation and the bounded
state machine. Existing workflow and orchestration owners inject tool-free,
authorized model invocation and persistence. No new public API or connector is
introduced.

Workflow integration runs outside the original agent invocation retry loop.
Orchestration integration checks prepared content before retained output
publication and file rendering. Failed tool calls remain failures even if a
candidate claims success. Failed or unverified required results cannot become
eligible downstream inputs.

Corrections cannot call tools. Existing safe read-only transient retries remain
separate; the checker never initiates autonomous replanning or replays a write.
It does not rewrite a file already created by a tool or retroactively undo effects.
Immutable saved analysis and per-document authoritative results are check-only:
their source identities and existing artifacts are never rewritten by answer repair.
An immutable non-Compose report selected as an orchestration's final response is
also checked before delivery without repeating its producer or rewriting its retained output.

Workflow tool evidence is secret-redacted before evaluation. Complete verification
values stay private; browser citation excerpts retain their existing size limits.
Evidence and candidate requests remain context-budgeted. Large evidence that does
not fit is not silently truncated and reported as fully verified.

Durable private checkpoints retain original/corrected candidates, assessment
history, identity hashes and consumed correction counts. A correction is reserved
before its model request. If execution is interrupted at that boundary, it is
reported unavailable rather than issuing an uncounted duplicate correction.
History reads, delivery-only recovery and page refresh do not start model calls.

## Reading outcomes

Run details distinguish **Complete**, **Corrected and complete**, **Incomplete**
and **Verification unavailable** from format validation. Expand **Answer
completeness** for requirement explanations and the number of corrections used.
Older runs without an assessment remain unchecked history.

Public reports expose explanation metadata, not prompts, private candidate
history or evidence payloads. Explanations are untrusted text, not executable HTML.
Telemetry records safe outcome categories, counts and existing correlation fields.

## Validation and limitations

`functional_tests/test_task_completeness_engine.py` covers the bounded state
machine, malformed reports, evidence references, unchanged requirements,
interruption, opt-out and check-only behavior.
`functional_tests/test_task_completeness_runtime.py` exercises actual workflow
result construction and orchestration execution/checkpoint/render boundaries with
offline model replies. UI coverage is in `ui_tests/test_task_completeness_ui.py`.
`functional_tests/test_orchestration_available_information.py` covers ordinary
answers, bounded checker repair, strict-data negative controls, actual narrative
files, immutable native reports, and safe saved-run continuation. The live,
reloaded, desktop, and mobile recovery states are covered by
`ui_tests/test_v2_orchestration_recovery.py`.

The checker adds model calls, latency and token use. It is model-assisted, not a
proof of factual correctness: false positive and false negative assessments remain
possible. It cannot recover facts absent from authorized evidence, inspect binary
deliverables as if they were prepared text, or verify unlimited source collections
within one model context. Existing specialized document/tabular validators remain
in place. Ordinary non-orchestrated chat and historical-run backfilling are not
part of this feature.
