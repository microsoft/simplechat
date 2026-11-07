---
applyTo: '**/*.py'
---

# Cosmos document response boundaries

Point reads and returned create/replace/upsert/patch documents in the application's
pinned Cosmos SDK are `CosmosDict`, a mapping subclass. Query rows and nested JSON
objects are plain dictionaries. `deepcopy(CosmosDict)` preserves its subclass.

Storage owners must normalize a point response **before copying or passing it to
an exact-dictionary/strict JSON contract**, using the bootstrap-free
`normalize_cosmos_document` in `cosmos_document_utils.py`. This helper accepts
`Mapping`, returns a plain top-level dictionary, preserves all fields and `_etag`,
and rejects invalid types with `TypeError`. Translate invalid responses through
the owner's existing failure path. Never normalize arbitrary iterables into a
document, substitute `{}`, strip ETags, or recursively repair domain values.

Keep domain validators strict. Normalization is not authorization, sanitization,
metadata stripping, or permission to replay an uncertain external effect. Raw SDK
responses are compatible with mapping consumers; an exposed wrapper by itself is
not a product defect. Prove a strict downstream mismatch with a runtime regression
before changing otherwise-compatible production code.

New Cosmos test containers use the **installed application's SDK `CosmosDict`**
for point reads and returned write documents by default. Query rows stay plain.
Plain point responses require an explicit compatibility mode. Preserve ETags,
partition routing, conditional updates, failure injection and transaction atomicity.
Domain-level repository mocks do not need to impersonate Cosmos.

## Reviewed inventory and deterministic CI

`functional_tests/cosmos_response_boundaries.json` records point/query calls,
helper references, consumer classifications and evidence by storage function.
It separately inventories Cosmos-shaped inline/shared test containers. It is a
review/change guard, not an interprocedural type checker or proof that every
external service behaves correctly.

After adding/changing a storage boundary or double:

1. Run `python scripts/check_cosmos_response_boundaries.py --refresh`. Changed
   implementations become `review-required`; regeneration never approves them.
2. Review every changed entry's actual consumer. Classify it as
   `normalized-strict`, `sdk-compatible`, `response-unused`, or `not-cosmos`
   with a specific contract and runtime test reference. A `not-cosmos` entry
   needs a concrete explanation of the similarly named non-Cosmos API.
3. New/changed Cosmos doubles must use `sdk-default`; `legacy-inline` records
   document unchanged pre-migration doubles, not permission to introduce another.
   Add a real SDK runtime regression to the inventory's `tests` evidence for
   changed owners. The gate automatically executes owner-runtime and SDK-default
   evidence, in addition to its core contracts, so references are not merely
   checked for existence.
4. Run `python scripts/check_cosmos_response_boundaries.py --run-contracts`.
   This checks the inventory and runs its selected suites with
   `-p test_support.cosmos_network_guard`. Set `PYTHONPATH` to the application
   and functional test directories using the platform's path separator.

Do not copy a classification blindly, point every owner at a utility-only test,
or treat a grep match/count as evidence of a defect. Reviews and references are
invalidated when their implementations disappear or change. Legacy inline
doubles remain explicitly recorded for staged, owner-specific migration.
Unchanged legacy mapping consumers distinguish source review plus SDK API
evidence from owner-runtime SDK coverage. Their source fingerprints form a
closed baseline; a new or changed owner cannot borrow that limited assurance.
Replace its baseline entry with real owner-runtime evidence, rather than
expanding the source-only baseline.
Owner-runtime evidence executes representative real-owner behavior; it does not
claim exhaustive branch coverage for every function in that storage owner.
Existing test-local compatibility seams also have a closed fingerprint baseline.
A new or changed point override needs explicit `fault-injection` runtime evidence,
which the gate executes; it cannot silently retain an old easy response override.

The dedicated `cosmos-response-contract-check.yml` installs the existing pinned
application/test requirements, uses no cloud credentials, and blocks socket/DNS
network access before test collection. New application storage modules and test
doubles cannot bypass it by choosing a new filename.
Tokenizer data needed by the pinned application dependency is warmed during
dependency setup into a workspace-local cache, before network access is blocked.
Tests keep the real context-budget calculation; they do not download assets or
replace budget/token behavior merely to run offline.
