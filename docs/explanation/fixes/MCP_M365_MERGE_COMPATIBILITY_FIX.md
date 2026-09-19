# MCP and Microsoft 365 merge compatibility (v0.261.036)

Fixed/Implemented in version: **0.261.036**

Related version update: `application/single_app/config.py`, from `0.261.035`
to `0.261.036`. Refs #1493 and PR #1497.

## Issue and root cause

Merging the updated Development branch brought remote-only MCP transport rules,
trusted action origins, and record-level legacy-action management into the
Microsoft 365 action and model-budget work. Both changes touched action saves,
migration, validation, loader preparation, and the action editor.

Choosing either side wholesale would lose protections: combined Microsoft Graph
actions could be recreated, MCP provenance could be discarded, or retired stdio
records could be executed or silently removed. Scope preparation also strips
Cosmos metadata, so conditional enable/disable writes must retain the original
record's ETag separately.

## Resolution

- Personal, group, and global saves keep MCP's server-bound origins and
  authorization-before-secret-hydration behavior. They also retain M365's
  delegated-only validation and exact live-ID checks for legacy Graph edits.
- M365 source-specific type validation runs before general MCP alias
  normalization, preventing whitespace or alias spelling from bypassing it.
- The loader applies M365 capability and consent preflight before per-action
  credential preparation, while preserving trusted MCP origins.
- The action editor retains both remote-MCP validation and M365/legacy Graph
  checks.
- Personal migration uses Development's structured per-record outcomes.
  Historical Graph creation remains limited to the trusted stored snapshot and
  its atomic, durable migration receipt. Retired stdio records remain available
  for management, and malformed or conflicting records remain for review.
  Replaying historical Graph settings cannot recreate a deleted action.
- Migration receipts remain hidden from every action lookup and cannot be
  replaced through an action save. Global enable/disable preserves the original
  ETag after scope preparation.

The merge also retains the incoming cross-cloud account-selection, CSV encoding,
group-upload authorization, and filename-rendering changes. The model catalog,
budget propagation, and capacity editor work from `0.261.035` remain intact.

## Validation

The combined action lifecycle, settings ingress, loader preflight, MCP
authorization, route security, and legacy-management regressions exercise both
sets of behavior. Added coverage combines a historical Graph migration with a
retired MCP record, verifies replay protection, checks conditional global
updates, and proves M365 preflight does not discard MCP provenance.

Targeted model-budget, cold-import, browser, route-policy, documentation, syntax,
and static guardrail checks cover the merged surfaces. No new Microsoft 365
permission or deployment configuration is required by this compatibility fix.
