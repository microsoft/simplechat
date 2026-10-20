# Generated-output reliability fix

Current version: **0.261.359**

Fixed in version: **0.261.356**

Related version update: `application/single_app/config.py`.

## Issue and root causes

Three independent product defects affected generated outputs:

- Prepared PowerPoint schema, slide-count and geometry failures were raised
  outside composition's recognized output-contract errors. They bypassed its
  existing single corrective call. The model-facing profile also omitted the
  precise title reservation and slide dimensions enforced by preparation.
- V2's shared chat completion handler ignored `image_url`. A successful direct
  image response could therefore leave an assistant message containing
  `Image loading...` until the conversation was reloaded.
- Recovery detail and history requests could return after a newer terminal
  stream event and replace saved publication state with an older
  `pending` / `execution_live` snapshot. Reconciliation could also act on a
  read that became obsolete while its step records were being fetched.

These fixes apply to the shared contracts and completion paths, not to a
particular prompt, marker, slide count, model or provider. The incident's exact
invalid slide coordinates were not available in safe telemetry.

The reported XML download was a separate acceptance-harness false failure.
Independent typed-XML readback reproduced the exact downloaded bytes and
preserved the expected record and scalar types. XML serialization is unchanged.
Harness findings are kept in a separate investigation artifact, not implemented
as application work.

## Technical changes

### Prepared slide validation and bounded correction

`functions_generated_export_contracts.py` owns the slide dimensions and title
rectangle used by the registry schema, preparation adapter and renderer.
`functions_generated_export_registry.py` exposes those constraints to
composition, including slide-count equality, bounds and non-overlap.

`functions_orchestration_services.py` maps only prepared schema, count and
geometry failures to recognized `ResultContractError` codes.
`functions_orchestration_composition.py` supplies safe corrective explanations.
The existing correction allowance remains one additional model call, shared
with other composition corrections. Invalid values are not retained or
published as successful outputs. Budget, access and cancellation checks run
before correction.

Limits, unsupported content, unavailable sources, access failures and renderer
I/O do not become corrective content requests. Rendering still independently
checks text fitting, image validity, geometry and publication requirements.

### V2 image completion

`chatStore.ts` folds nonblocked `image_url` completions into the persisted image
message shape: saved message id, `role: image`, source in `content`, and the
prompt bound to the originating user turn. Legacy image frames, ordinary text,
safety results, thoughts, metadata and model identity retain their behavior.

The common handler covers sends, retry/edit, reattachment and collaborative
streams. Existing saved-id deduplication, conversation ownership and image-source
validation remain authoritative. The existing image bubble, viewer, download
and saved-message reload paths need no special rendering workaround.

### Recovery read freshness

`orchestrationStore.ts` assigns a local revision to authoritative attempt
updates, separately from output receipts and incidental UI state.
`orchestrationController.ts`, `orchestrationResume.ts` and
`OrchestrationMapView.tsx` capture the read-start revision. Stale detail and
list responses cannot regress newer attempt state, and reconciliation does not
make decisions from rejected snapshots or superseded step reads.

A disconnected tracked run whose newer saved state is terminal is checked
again so it can still settle. Pending final publication keeps its existing
polling behavior. Fresh later reads can change eligibility and attempt lineage;
authorization failures remain visible. No read approves, retries or cancels
execution, and the server still revalidates explicit recovery requests.

## Validation

`functional_tests/test_orchestration_compose_output_retry.py` exercises real
composition, retained results and publication with offline model replies.
Schema, count, title-overlap, shape-overlap and bounds errors are corrected
across wide/standard decks, blank/title layouts and variable slide counts.
The resulting PPTX is independently reopened to check its dimensions, count
and complete body content. Repeated invalid output, resource/source/access/I/O
failures and budget/access/cancellation guards produce no unwanted file.

`ui_tests/test_v2_generated_image_completion.py` runs production stores, SSE and
components with mocked HTTP. It checks live rendering, viewer and byte-identical
download, saved reload, supported sources, safety/text/legacy frames, duplicate
echoes, turn-bound prompts, collaborative streams, navigation, retry/edit and
reattachment.

`ui_tests/test_v2_orchestration_recovery.py` gates detail, history, reconciliation
and step reads until after failed/completed/cancelled terminal SSE events.
It checks saved state, available recovery controls, fresh later lineage,
authorization errors and the absence of automatic execution writes. Existing
pending-publication and file-output receipt regressions remain applicable.

Focused validation results:

| Coverage | Result |
| --- | --- |
| Composition correction, dependency runtime, Office/structured renderers and export integration | 612 passed |
| V2 image completion, recovery and file-output browser regressions | 132 passed; five unrelated imported editor cases excluded |
| Image provider routing and output transport | 21 passed |
| Existing Node orchestration progress tests | 18 passed |
| Frontend typecheck and production build | Passed |
| Documentation inventory coverage and site quality | 7/7 and 6/6 checks passed |

Broader pre-existing test-fixture failures were recorded separately and are
not included in these pass counts.

### Review follow-up (0.261.359)

The image-completion test explicitly re-exports its shared Playwright fixtures
through `__all__`. This preserves pytest's name-based fixture discovery,
including the local/Azure connection options, while making the imports visible
to CodeQL's unused-import analysis without suppressing the rule.

Validation uses the existing offline application harness and local Chromium
through the local/Azure-capable Playwright fixtures. No production deployment,
settings change, paid model generation or live acceptance replay is performed.
Passing these deterministic regressions does not guarantee that every future
model-generated deck will satisfy layout constraints within one correction.
