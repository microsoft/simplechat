# V2 public source discovery fix

Fixed/Implemented in version: **0.261.372**, tracked in
`application/single_app/config.py`.

## Issue and root cause

V2 reused classic public-workspace visibility preferences in source discovery
and downstream source validation. A nonempty classic visibility map excludes
every workspace not explicitly true. A reader could therefore open a processed
public guide in its workspace, yet get no match for its exact filename in V2.
This conflicts with V2's contract: all eligible public workspaces are searchable.

The reported FED-06 and FED-07 journeys stopped before message submission.
Failure-window public requests returned HTTP 200 in 244 ms and 771 ms.
Read-only investigation reproduced an empty ordinary picker and an enabled
matching source in All public workspaces for the same account. Its workspace
was active; its classic custom map omitted that workspace. Historical response
bodies and the failure-time preference map were not recorded, so the current
reproduction is not an exact reconstruction of historical settings.

Previous fixes corrected filename/title pagination and absent workspace status.
Neither removed classic curation from V2. Selecting All as a workaround was also
insufficient: that mode is public-only, while FED-07 requires mixed sources.

## Technical changes

`public_source_policy.py` separates V2 all-available discovery from classic
legacy-visible discovery. Native V2 requests and explicitly marked first-party
V2 calls select the former. The marker is not authorization: the server still
resolves workspace eligibility for the authenticated user.

`functions_public_workspaces.py::get_public_source_workspace_ids` owns policy-aware
resolution. Shared bootstrap, chat admission, search/document resolution,
references, workflow, prompt, tabular and citation consumers use that policy
instead of treating a classic preference as an access boundary.
Public document/tag listing continues filtering before pagination.

The policy survives admitted orchestration seeds, checkpoints, retry metadata,
agent worker identity and workflow execution. Explicit document selections,
workspace locks, publication approval, screening, current availability and group
membership checks remain restrictive. A mixed turn stays mixed; public-only All
is still a separate choice.

The React directory no longer writes visibility preferences or offers switches,
bulk show/hide or saved visibility lists. Documents offers Current context and
All public workspaces. Old V2 Visible links normalize to All.

## Compatibility and impact

Classic retains its controls, saved maps/lists and visible-only behavior.
There is no data migration or automatic preference repair. V2 reads all eligible
public sources even when classic omits or hides them. No new configuration
toggle, Azure resource, browser dependency or tenant permission is required.

Unavailable workspaces or content do not become searchable. Explicitly selected
source sets do not widen. Existing durable records without the new policy retain
their legacy execution contract unless newly admitted under V2 semantics.

## Validation

`functional_tests/test_v2_public_source_discovery_policy.py` covers preference
variants, classic/V2 isolation, mixed admission, complete public search scope,
explicit narrowing, worker cleanup, agent bridging and retry selection.
Existing public-scope, status, publication, reference, workflow and source-reader
regressions exercise the associated boundaries.

Browser regressions in `ui_tests/` use synthetic HTTP, not production model
requests. They cover the ordinary picker, mixed references, removal of curation
controls and compatibility with old V2 aggregate links.

The focused backend and workflow suites, browser regressions, build and
documentation checks pass. The unfiltered storage-contract runner still has
three citation-count assertion failures reproduced against unchanged
**0.261.370** application code. Those unrelated internal test expectations
were not changed as part of this fix. With only those three exact cases
deselected, the remaining offline storage suite passed **1,377 tests and 144
subtests**. The inventory covers **1,067 owners and 414 doubles**, with no
review gaps. This is not an unfiltered green gate.

The deployed FED-06/FED-07 answer and citation acceptance criteria require a
separately authorized post-deployment rerun. A local regression or read-only
picker check is not represented as that live acceptance result. Harness
findings are recorded separately and no federal harness changes are part of
this fix.
