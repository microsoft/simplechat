---
layout: latest-release-feature
title: Feedback & Safety Violation Archive / Delete Lifecycle
description: Admins can archive, restore, or permanently delete feedback and safety records with audit-aware controls.
section: Latest Release
generated_from_catalog: true
---

Current release version for Feedback & Safety Violation Archive / Delete Lifecycle: **0.261.001**

Feedback Review and Safety Violation records now support archive, unarchive, and permanent delete actions. Archived records are hidden from user profile history, deletions require confirmation, violations with pending remediation approvals cannot be deleted, and lifecycle actions create audit records.

## Why It Matters

This matters because moderation and feedback queues can be retained, cleaned up, and audited with clearer lifecycle rules.

## How to Try It

1. Open Admin Settings > Safety and review active Safety Violation records before archiving or deleting anything.
2. Use archive when records should leave user profile history but remain recoverable for administrative review.
3. Resolve pending remediation approvals before attempting permanent deletion of safety violations.
4. Review audit records after lifecycle actions to confirm the administrative history is complete.

## Where to Find It

- **Open Safety** &mdash; Manage safety violation archive and delete lifecycle.
- **Open Send Feedback** &mdash; Review feedback records affected by archive and delete lifecycle controls.
