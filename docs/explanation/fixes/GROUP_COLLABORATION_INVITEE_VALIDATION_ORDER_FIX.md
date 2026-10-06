# Group Collaboration Invitee Validation Order Fix (v0.261.259)

## Overview

Group conversation conversion now proves that every requested invitee is a current member of the source group before reading the conversation's message history. This keeps authorization checks ahead of dependent data access while preserving the existing conversion and invitation behavior.

Fixed in version: **0.261.259**

Related issue: [#1651](https://github.com/microsoft/simplechat/issues/1651)

Dependencies: group membership normalization, group role authorization, and Microsoft 365 history publication.

The application version was updated in `application/single_app/config.py` from `0.261.258` to `0.261.259`.

## Issue Description

An owner converting an eligible legacy group conversation could include an identity that was not a current member of the source group. The request was rejected and no records were changed, but Microsoft 365 publication preparation queried the source message history before participant normalization raised the rejection.

The group document collaboration suite also replaced the workflow-alert safety module with a test stub that no longer matched the production module's exported constants. That mismatch stopped the suite during fixture setup and hid its sharing assertions.

## Root Cause

`ensure_group_collaboration_for_legacy_conversation` passed the raw invitee list into history publication before `create_group_collaboration_conversation_record` normalized those invitees against the current group document. The correct validation existed, but it ran after a dependent transcript read.

Separately, `functions_notifications` gained an import path through `functions_workflow_alerts`, whose safety contract requires three public diagnostic constants. The isolated test stub exported only the sanitizer function.

## Technical Details

### Files Modified

- `application/single_app/functions_collaboration.py`
- `application/single_app/config.py`
- `functional_tests/test_group_collaboration_source_storage_fix.py`
- `functional_tests/test_group_document_collaboration.py`
- `docs/explanation/release_notes.md`

### Code Changes

The conversion path now normalizes requested invitees immediately after it verifies the owner, source conversation, group, current owner role, and active group status. Only the validated participant summaries can reach an existing collaborative conversation, Microsoft 365 publication preparation, conversation record creation, or transcript copying.

The document collaboration fixture now provides the exact workflow-alert diagnostic constants exported by production while retaining its assertion that document sharing must not enter workflow-alert rendering.

No route, response status, or request payload contract changed.

## Testing And Validation

The focused regression command exercises both invalid-invitee storage modes, the V1 route contract, and the document-sharing fixture import path. It completed with 3 tests and 38 subtests passing.

The complete group source-storage suite completed with 20 tests and 106 subtests passing. The targeted document-sharing fixture case passed, editor diagnostics reported no errors, and the broken-access-control guardrail passed for the changed production module. Documentation validation completed with 7 of 7 application-surface checks and 6 of 6 site-quality checks passing.

## Impact Analysis

### Before

- An out-of-group invitee was rejected without mutation, but only after the source transcript was queried.
- The document collaboration suite stopped during fixture setup because its safety stub was incomplete.

### After

- Every invitee is authorized against current group membership before transcript or publication evidence access.
- Rejected conversion requests do not read either possible source message container.
- The document collaboration suite reaches its route, policy, Search, notification, and storage assertions.

## Known Limitations

The fix does not change who may convert a conversation, which groups may be used, or which participant roles are assigned. It only moves the existing invitee normalization to the earliest point after the source group and caller have been authorized.