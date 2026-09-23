# Orchestration file history outage handling

Fixed in version: **0.261.127**

Version reference: `application/single_app/config.py`. Associated work: #1509.

## Issue and root cause

The generated-artifact history dispatcher already refreshed committed file cards
and `metadata.orchestration.outputs` using current actor/conversation access.
Its callers changed the meaning of operational failures:

- `public_history_messages` caught typed authority/screening service failures from
  that dispatcher and returned a successful document-review placeholder.
- The conversation messages endpoint converted an output-storage exception into
  a misleading HTTP 404 response.

A temporary outage therefore looked like a held document or missing
conversation, even though neither access decision had been made.

## Technical changes

`content_screening/access.py` now invokes the generated-artifact dispatcher
after ordinary evidence screening succeeds, outside the catch that constructs
document-review placeholders. The dispatcher continues to own per-file denial
handling. Its operational failures are no longer reclassified.

`route_backend_conversations.py` handles typed file-history authority, integrity
and storage failures at that read boundary. It logs safe exception-type/context
metadata and returns HTTP 503 with `output_status_unavailable`, without provider
diagnostics or stale file cards.

This includes both transient external-configuration service failures and
malformed current-configuration metadata. Neither is proof of revoked access.
The orchestration detail/list, editor and file-retry boundaries preserve the
same distinction; they do not return saved links, silently change a plan, or
report a missing output when current authority cannot be verified. Cancellation
is not classified as a configuration service outage.

Ordinary screening holds, conversation ownership checks and legacy workflow
artifact handling are unchanged. An inaccessible file does not hide an
accessible sibling. Reading history does not call rendering, publication,
delivery finalization or a model, and it does not rewrite saved messages.

## Validation

`functional_tests/test_orchestration_output_history_routes.py` uses the real
authenticated conversation route, public history pipeline, retained-result
reader, output lifecycle and private artifact transport with storage/authority
I/O doubled.

The original failures were reproduced through HTTP: an authority timeout
returned a document-review placeholder with HTTP 200, and an output-store outage
returned HTTP 404. Both now return the safe HTTP 503 response.

The 13 history cases cover current source restrictions, accessible sibling
preservation, immutable saved records, foreign-owner refusal and ten
operational failure types. They pass under normal and optimized Python.
The joined history, orchestration retry/read/editor and real root import matrix
passes 57 cases; 28 selected configuration/history cases also pass under
optimized Python. Earlier unchanged screening and workflow compatibility
coverage passed 81 cases plus 34 subtests.

The full-file access guard reports one unchanged baseline pattern in the
conversation-kind endpoint. The same finding exists at `HEAD`; all added
conversation-route lines pass the existing guard. No unrelated endpoint change
or suppression was added.

These are isolated production-boundary checks, not live cloud validation or a
claim that the complete orchestration harness is enabled.
