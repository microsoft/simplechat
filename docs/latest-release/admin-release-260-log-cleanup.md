---
layout: latest-release-feature
title: File Processing Log Cleanup
description: Admins can remove old file-processing logs by retention window or purge all logs with confirmation and activity logging.
section: Latest Release
generated_from_catalog: true
---

Current release version for File Processing Log Cleanup: **0.261.001**

Cleanup controls can permanently delete file-processing logs older than a configurable retention period measured in days, weeks, or months. Admins can also purge all logs, with confirmation dialogs, exact counts, and admin activity logging for each cleanup action.

## Why It Matters

This matters because log growth can be controlled while preserving deliberate confirmation and auditability for destructive cleanup.

## How to Try It

1. Open Admin Settings > Logging and review current file-processing log volume.
2. Choose a retention period in days, weeks, or months that matches tenant support and audit needs.
3. Review the exact count shown in the confirmation dialog before deleting old logs.
4. Use purge-all only for intentional reset scenarios and confirm the admin activity log afterward.

## Where to Find It

- **Open Logging** &mdash; Configure and run file-processing log cleanup.
