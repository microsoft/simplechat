# Document Source Scope Identity Fix

**Version: 0.261.347**

Fixed/Implemented in version: **0.261.347**, recorded in
`application/single_app/config.py`.

Refs [#1777](https://github.com/microsoft/simplechat/issues/1777).

## Issue and root cause

FED-04 uploaded two policy revisions and approved a document comparison followed
by composition. Both source analyses succeeded, but comparison failed and its
dependent composition was skipped. Application Insights showed a source
authorization failure before the pairwise comparison model call, not a provider
timeout or a failed UI selector.

The shared `get_document_chunks_payload()` function selected `scope_id` using a
conversation-first fallback. Workspace uploads legitimately retain a
`conversation_id`, so their payload could identify a group, public, or personal
source using its upload conversation instead of its authorized workspace
identity. Coverage provenance could remain correct while other result entries
carried the wrong identity. Comparison's recursive evidence checks then refused
those entries. Explicit Analyze manifest matching could reject the same mismatch.

## Changes and impact

`application/single_app/functions_search_service.py` now selects `scope_id`
from the already resolved source scope:

| Resolved scope | Payload identity |
| --- | --- |
| Personal | Document owner's user ID, including approved personal shares |
| Group | Authorized group access path, including approved shared-group access |
| Public | Authorized public workspace ID |
| Chat-only upload | Authorized conversation ID |

The separate conversation association remains available. Owning provenance is
not rewritten to match a shared access path. This fixes the shared retrieval
contract used by Analyze and Compare rather than special-casing FED-04, its
filenames, prompts, or policy values.

No authorization, screening, revision validation, result-completeness rule,
provider selection, automatic retry, or UI acceptance criterion is relaxed.
Failed comparison still skips its required dependent composition. No new
capability, setting, route, file output, or storage migration is introduced.

## Regression coverage

`functional_tests/test_document_source_scope_identity.py` exercises real
retrieval, source authorization, Analyze, Compare, retained results, and
dependent composition. External storage transport, membership/directory I/O,
document chunks, and model responses are isolated. Point-document containers
reuse the existing SDK-shaped Cosmos double.

Coverage includes personal, group, and public sources with and without chat
associations; approved shares; chat-only attachments and foreign-user denial;
manifest mismatch; and revocation, deletion, screening holds, and revision
changes after comparison model work. The executor cases require both comparison
and composition to complete, retain the full comparison, preserve both source
markers, and create no artifacts. A provider-failure control still requires
Failed/Skipped, not fabricated success.

Synthetic policy values exercise 125000 to 150000 and 10 to 7 days, with both
markers reaching the producer and its complete report reaching composition.
Deterministic model replies validate orchestration plumbing, not the quality
of a live provider's arithmetic or citations. Synthetic owner and marker names
are not asserted to be the original live fixture values.

## Validation and limitations

Run the new regressions with application and functional-test directories on
`PYTHONPATH` and network access blocked:

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -m pytest -p test_support.cosmos_network_guard .\functional_tests\test_document_source_scope_identity.py -q
```

The 28 new regression cases pass. The combined retrieval, native analysis,
dependency, and source-authority run reports 300 passing tests, 24 failures, and
14 setup errors. The same 24 failures and 14 errors reproduce in the existing
source-authority suite with unchanged HEAD retrieval code and without the new
test module. They originate in source-free durable recovery/wait fixtures
before their adapters execute; they are not treated as passing validation.
Restoring the repository-pinned application dependencies in a session-local
environment does not change that baseline result.

Excluding only those 38 baseline cases and including the existing chat-upload
storage-owner SDK contract yields **301 passed, 38 deselected**. Documentation
coverage and site-quality checks pass all 13 tests. The reviewed Cosmos
inventory has 1,066 owners, 409 doubles, and zero review gaps; only the two
unchanged chat-upload owners' containing-module fingerprints were regenerated.

After restoring the pinned dependencies, the mandatory network-blocked
`python .\scripts\check_cosmos_response_boundaries.py --run-contracts` gate
passes **1,079 tests and 244 subtests**. Earlier attempts exposed inherited
Flask/Werkzeug incompatibility and a missing Yamcs client; dependency restoration
was limited to the session-local virtual environment, not global packages.

A separate network-blocked optimized-Python probe passes seven explicit checks
for all six workspace/association combinations and approved shared-group
provenance.

Before the fix, an upload conversation could replace a workspace identity,
causing a valid comparison or Analyze manifest to be refused. After the fix,
the payload matches the authorized scope while genuine access, hold, deletion,
revision, and provider failures remain failures.

This change has not been deployed, and the original live FED-04 attempt has
not been rerun. A live acceptance result requires the authorized original
fixtures and harness after deployment; offline tests do not change the original
attempt's failed verdict.

See [Gather / Reason / Render](../features/ORCHESTRATION_GATHER_REASON_RENDER.md)
for the shared source-access and retained-result contracts.
