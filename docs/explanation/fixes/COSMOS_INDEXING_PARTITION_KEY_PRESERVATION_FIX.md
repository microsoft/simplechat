# Cosmos indexing partition-key preservation fix

Version: **0.261.396**

## Fixed in version: **0.261.396**

The application version is tracked in `application/single_app/config.py`.

## Issue and root cause

Applying missing composite indexes could return HTTP 500 with the generic message
"One or more maintenance steps failed." Cosmos rejected the underlying container
replacements with "Document collection partition key cannot be changed."

Index maintenance constructed `PartitionKey(path=...)` instead of retaining the
partition-key definition returned by the existing container. The pinned Python SDK
defaults that constructor to version 2. Legacy containers can omit the version,
so even an unchanged path could submit different immutable metadata.

The V2 admin panel immediately refreshed read-only status after an apply attempt.
A successful inspection then replaced the failed apply counts with zero failures,
making the failure alert and the counters appear contradictory.

## Technical changes

`application/single_app/functions_cosmos_indexing.py` now validates and preserves
the actual partition-key mapping, including paths, kind, explicit versions, and
omitted version fields. Missing or malformed definitions fail before submission
rather than guessing a new key. ETag conflicts still trigger bounded re-reads and
re-merges; existing composite indexes, included/excluded paths, TTLs, and full-text
policies remain intact.

`application/single_app/functions_app_maintenance.py` retains the last index apply
result separately from current report-only inspection. Later inspections and
unrelated maintenance runs do not overwrite that result. A successful apply retry
replaces it. Known indexing failures have stable codes and user-safe explanations;
historical raw indexing errors are sanitized before browser responses.

The classic maintenance JavaScript and Cosmos template, and the V2
`CosmosMaintenancePanel.tsx` and `scaleMaintenance.ts`, display the last apply result
separately. Administrators can see affected containers, submitted and failed counts,
and a run reference. Errors from other maintenance steps are not described as an
index update failure. Refresh failures remain visible. Provider errors are not used
as UI copy, and dynamic text is rendered through text nodes or React text children.

## Upgrade and operational impact

Upgrade all application workers and the scheduler to the fixed version, then retry
**Apply missing indexes**. Existing deployments do not self-correct while running the
unpatched application. Scheduled application remains controlled by existing
maintenance and index-apply settings; this change does not enable index writes.

No database migration, container recreation, or deployment-script modification is
needed for this defect. The fix supports legacy, explicit version-1, version-2, and
hierarchical partition keys. Forcing version 2 in deployment templates would not
repair existing containers and is deliberately not part of this fix.

Successfully submitted updates are not rolled back if another container fails.
A retry applies only indexes still missing. Cosmos can continue index transformation
after a successful submission. Access failures or other service errors are separate
problems and still require investigation.

## Validation and regression coverage

`functional_tests/test_cosmos_wave3a_indexing_maintenance.py` exercises the real
pinned SDK's replacement request construction offline, with no live Azure writes.
It covers omitted and explicit versions, hierarchical paths, malformed metadata,
ETag retries, additive policy preservation, no-op repeat application, safe historical
errors, partial failure, and durable results across read-only/background runs.
Its point-operation doubles return the installed SDK's `CosmosDict`.

`ui_tests/test_v2_admin_scale_settings.py` covers failed apply results surviving a
refresh and unrelated cleanup, successful retry, partial success, non-JSON errors,
failure in another maintenance step, refresh failure, desktop/mobile layout, and
safe classic rendering using the actual Cosmos pane and JavaScript.

Before the fix, the reconstructed SDK key included version 2 for a legacy
definition. After the fix, the SDK request retains that definition exactly, and
both admin interfaces distinguish the last apply result from current inspection.
Live application and database changes require a separate deployment and retry.

The changed maintenance suite passes with the repository's network guard enabled.
The targeted Scale logic/parity suites, all Scale browser tests, admin route policy
checks, TypeScript build, and documentation coverage/quality checks also pass.
The repository-wide Cosmos contract gate remains blocked by 53 inherited review
gaps in `functions_documents.py` and `functions_settings.py`; these also occur
against the unchanged HEAD baseline. The older standalone Wave 1 harness fails
because its fake configuration omits the already-required activity-log container.
Neither unrelated baseline issue is repaired by this change.
