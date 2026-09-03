# Chat Group Upload Owner Role Fix

## Issue

Owners of group-scoped conversations were told that no group workspace was available for upload, even though owners are permitted to upload group documents.

## Root Cause

The chat page passed group IDs and names to the upload JavaScript but omitted each user's resolved group role. The client therefore treated owners as users without a group upload role before the upload request was sent.

## Version

Fixed/Implemented in version: **0.261.029**

The application version was updated in `application/single_app/config.py`.

## Technical Details

The chat bootstrap payload now includes `userRole` for each group. This allows the existing `Owner`, `Admin`, and `DocumentManager` upload allowlist to operate correctly. Server-side group membership, status, and upload-role validation remain authoritative.

## Validation

The group upload handoff functional test includes a contract assertion that the resolved role is passed to the frontend. The full existing test currently has two unrelated stale assertions for older frontend/search contracts; the route syntax and version/role contract were validated separately.
