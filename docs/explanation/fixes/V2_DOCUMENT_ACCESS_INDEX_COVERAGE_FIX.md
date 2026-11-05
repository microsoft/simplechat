# V2 document access index coverage fix (v0.261.405)

## Issue and root cause

Fixed/Implemented in version: **0.261.405**, tracked by `VERSION` in
`application/single_app/config.py`.

The V2 source picker was not the only document path using older queries.
Named group/public browsers and Assigned Knowledge maintained separate
source-container discovery. Grounded search also enumerated sources to repair
revision families and build result-cache fingerprints before it could return
a cache hit.

Two read-model mismatches made indexed and source reads disagree: `file_size`
was missing from the index's document projection, and a revision-family ID
was not qualified by its owning workspace. Separately, the Document Search
action referenced `run_document_search` without importing that service alias.

## Changes

### Shared metadata identities and projection rollout

`document_metadata_identity.py` is bootstrap-free. Source and index owners
share owner-qualified family identities and document cache identities that
retain version/screening state and the source revision when recorded.
`functions_document_access_index.py` carries file size and legacy/XSD family
identity inputs through projection and conversion.

Projection schema 4 uses the existing backfill/repair workflow. Older schema
state falls back to sources until maintenance completes; schema-versioned
index caches do not reuse older payloads.

### Workspace and agent discovery

Group/public lists, facets, tags, and counts discover current candidate IDs
through DAI and load only those source records in bounded batches. Screening,
pending publication, ownership/sharing checks, and final response revalidation
remain. An unusable index uses the original scoped source query. A healthy
empty response does not trigger a full-source verification scan.

Assigned Knowledge reuses indexed discovery while preserving its existing
personal/group/global policies and all-public-source semantics. The editor's
display window remains bounded. Runtime target resolution no longer inherits
that display cap, so a configured older document outside the first 1,000 can
still be resolved. Inventory answers retain the exact active count and disclose
when the rendered entries are bounded. Source read failure is an explicit
unavailable response, not an empty successful catalog.

### Search cache and revision repair

Indexed fingerprints read authorized revision identities within access-index
partitions, including historical versions as the source fingerprint did.
Existing Redis read-through caching and scope invalidation are reused; an
uncached DAI read still works without Redis. Unusable DAI scopes retain their
source fingerprint fallback. Disabled result caching performs no fingerprint
or cache-key work.

The new cache policy can return a valid cache hit before repeating source
revision repair, while retaining current result/source screening. Unchanged
successful repair passes can reuse the existing shared index generation.
Changed or unknown state retains the legacy repair path. Repair that changes
visibility or fails bypasses result caching for that pass.

This does not replace content retrieval: Azure AI Search still supplies
passages/vectors, and known-ID history, original files, and source authority
still use their appropriate stores. There is no new freshness service,
external-write tracker, age cutoff, container, or rebuild inside a read request.

### Orchestration and tools

Orchestration planning probes and executing document searches already call the
shared search backend, so they inherit the same changes without a separate
orchestration index layer. Analyze/Compare and native tools keep selected-file
and retained-source bindings and fresh source checks.

The Document Search action imports its existing search service under the alias
it calls. Its regression executes the actual module binding, rather than
injecting the missing alias in the test.

## Files and impact

The implementation changes the shared identity/index/search/cache owners,
group/public document readers, Assigned Knowledge catalog/inventory owners,
the existing agent catalog error boundaries, and the Document Search plugin.
No new Flask routes, browser libraries, configuration toggles, or deployer
changes are introduced.

## Validation

`functional_tests/test_v2_document_index_coverage.py` uses real owners with
network blocked and installed-SDK point mappings. It covers projected size and
family parity, legacy schema identities, all-version fingerprints, indexed
candidate hydration, healthy empty results, schema/backfill/repair/query
fallback, stale share rejection, runtime selection beyond the editor window,
explicit catalog failure, cache hits, disabled caching, generation invalidation,
and the real tool binding.

Existing indexed-read/cache, scoped-reader, source-menu and orchestration
handoff tests cover the related contracts. The Cosmos response-boundary
inventory is refreshed and reviewed with owner-runtime SDK evidence.

The affected index/browser/source-menu selection passes **427 tests** with
network access blocked. The complete SDK contract sweep recorded **1,934 passing
tests** and **431 passing subtests**; its 14 initial Analyze fixture setup errors were caused by
the fixture missing the newly imported `get_cache_settings` cache seam. That
seam is now explicit, and every one of those 14 cases passes in the follow-up.
A focused orchestration Analyze/retention/search-integrity run passes all
**101 tests**, including those 14 cases. The inventory check reports zero review
gaps.

A wider Analyze-fixture sweep passes 563 tests and exposes seven unrelated
test-harness failures: six in `test_saved_analysis_bounded_reports.py` still
patch a removed token-limit helper, and one workflow retry test in
`test_analyze_live_write_fences.py` omits `completeness_policy` from its extracted
namespace. All seven reproduce against an isolated, unchanged `b6c1c8acd`
snapshot. Those pre-existing fixtures are not changed by this fix.

The before/after contract is index-first discovery when the maintained
projection is usable, not elimination of current source authorization or
independent proof of complete index coverage. No live Azure RU or latency
measurement is claimed.
