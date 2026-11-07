# Unified Sources and saved findings

Fixed/Implemented in version: **0.261.419**.
Application version: `application/single_app/config.py`.

## Issue and root cause

V2 rendered retained Analyze results automatically inside the assistant's answer
bubble. Labels came from internal execution-step titles, while counts, validation
terminology, arbitrary record fields, and follow-up controls competed with the
readable answer. Citations already had a separate per-message Sources inspector.
The saved result was useful; the duplicate, implementation-oriented presentation
was not.

## Changes and impact

`MessageList.tsx` no longer inserts the analysis reader in the answer bubble.
The existing Sources action opens `MessageInspector.tsx`, with answer citations
and saved findings alongside each other on desktop and stacked on narrow screens.
Citation counts, saved finding counts, and contributing-source counts remain
separate. No additional toolbar action, drawer mode, endpoint, or model pass was
introduced. Document citations reuse the existing citation viewer with recorded
identities rather than filename matching.

`AnalysisResult.tsx` loads up to 25 complete records only while Sources is open.
Numbered findings disclose their full values; Supporting passages reads only
that finding's saved evidence references. Analysis limits retains validation
explanations and saved issues. Multiple reviews have neutral numbered labels.
Internal step labels and the bounded diagnostic JSON link belong to Details.
Incomplete or unavailable reviews retain brief answer-level notices.

The existing conversation-bound authorization, masking, pagination, retries,
abort-on-navigation behavior, and stale-result handling remain in place.
Ask about this saved review still selects the whole saved result and disables
fresh source retrieval. It does not create record-scoped follow-up context.
Classic chat, conversation Documents/Plan, and the answer's generated prose are
unchanged.

`functions_orchestration_execution.py` emits content-free publication diagnostics
only after saved-message read-back verification. `functions_appinsights.py`
preserves the approved message/producer hashes and analysis codes. The established
debug helper gates both console and configured App Insights output. Ordinary
execution-outcome logging remains unchanged.

## Evidence interpretation

Structural validation does not establish factual correctness or exhaustive
coverage. Source observations are not reconciled values. Saved findings are not
native comment records, and successful body analysis does not prove that native
comments were extracted. The UI does not infer unavailable comment details from
answer prose or absent metadata.

The investigated conversation's telemetry established four saved body findings
and six exact passage matches, not four comments. The exact record bodies were
not exported during investigation, and the cause of the missing individual
comment records remains unproven. This fix changes presentation and correlation,
not native Word comment extraction.

## Validation

`ui_tests/test_chat_saved_analysis.py` exercises both interfaces, retained plural
reviews, safe text, pagination, supporting passages, downloads, saved-review
follow-ups, revocation, masking, stale pointers, retries, and late responses.
V2-specific scenarios cover an answer-first initial state, the single Sources
destination, Details-only diagnostics, keyboard interaction, identical source
filenames with distinct document identities, and 390/1280-pixel light/dark layouts.
The four viewport/theme scenarios also measure saved-finding text contrast against
the rendered background, requiring at least 4.5:1. Conflicting recorded citation
identities remain non-clickable rather than opening an ambiguous document.

`functional_tests/test_orchestration_analysis_citation_delivery.py` exercises
real native producers and publication with deterministic external services. It
checks debug-off/on console and App Insights behavior, sanitized hashes/counts,
and absence of publication diagnostics when persistence fails. Related saved
analysis route, diagnostic, retained-publication, and telemetry tests protect the
existing contracts.

Local validation passed: 74 saved-analysis browser cases, the final six
Sources-focused browser cases after the contrast checks, the production build,
and 161 network-blocked owner-contract cases covering all five storage owners
in the changed execution module. Documentation surface coverage passed all seven
checks; site quality passed all six checks. The repository-wide storage-contract
run was stopped in favor of these affected-owner checks; no full-suite pass is
claimed.

These are local fixture checks, not a deployment or a rerun of the investigated
conversation. See [the user guide](../../guides/analyze-results.md) and
[logging reference](../../reference/logging-tags.md).

The design detector's remaining warnings refer to the unchanged collaborative
typing-dot animation and a literal `<img>` in an explanatory comment, not to the
new Sources controls. The image component itself has a real source and an error
handler; neither unrelated surface was changed.
