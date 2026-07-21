# Cosmos Document Feed Streaming Fix

Fixed in version: **0.250.070**

The application version was updated in `application/single_app/config.py` for
this fix.

## Issue

When a container contained many conversation documents, the terminal could
show `Reading web response stream` for an extended period while the active
container still reported zero processed documents. Copying did not begin as
soon as the first source page was available.

## Root Cause

`Get-CosmosDocuments` emitted documents page by page, but both callers used a
PowerShell `foreach ($document in Get-CosmosDocuments ...)` statement. The
`foreach` collection expression evaluated the command output before entering
the loop, which buffered the feed across continuation pages before writes
started.

## Technical Details

Modified files:

- `scripts/Migration-Cosmos.ps1`
- `functional_tests/test_cosmos_all_containers_migration.py`
- `docs/explanation/features/COSMOS_DB_MIGRATION.md`
- `application/single_app/config.py`

Sequential and parallel document consumers now use ordinary
`ForEach-Object` pipelines. Pipeline backpressure pauses source enumeration
while the current document or bounded write batch is processed. The next
continuation page is not requested until processing has advanced through the
current page.

Cosmos REST still returns a page as one JSON response. `Invoke-WebRequest` must
download that page completely before it can be parsed, so the transfer bar can
remain visible briefly. This is bounded by `PageSize` and is not a download of
the complete container.

## Validation

The functional test uses one-document source pages and records REST event
order. It asserts that the first destination document write occurs before the
second source continuation page is requested. It also rejects any return to a
buffering `foreach ($document in Get-CosmosDocuments ...)` expression.

All migration regression tests, PowerShell parsing, Python compilation,
diagnostics, and whitespace checks pass.