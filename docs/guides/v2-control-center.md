---
layout: page
title: "Use the V2 Control Center"
description: "Open the permission-aware Control Center pane and check activity-log data only when needed."
section: "Guides"
audience: admin
---

## What the Control Center provides

The V2 Control Center is a separate administration pane for users assigned Control Center access. It is kept out of the primary workspace navigation and appears in **Account → Control Center** when at least one Control Center capability is available to you.

The section rail is filtered to your permissions. Dashboard, user and group management, public workspaces, and activity logs are being delivered in phases. Until a section is available in V2, open the classic Control Center from its placeholder.

## Check activity-log data health

The **Data health** section is available to users with maintenance access. Its backfill is a legacy repair operation for conversation and document creation events; ordinary application workflows already write activity logs, so the backfill is normally unnecessary.

1. Select **Data health** and choose **Check activity-log status** to request the current legacy-flag counts. The check is not performed automatically when the page opens.
2. Read the results carefully: they count records missing a legacy flag and do not establish that their activity events are absent.
3. Use **Run backfill** only when you have a known need. Confirm the operation in the dialog. The backfill checks the relevant user's activity-log partition and skips existing creation records.

The status and backfill APIs remain protected by the Control Center maintenance permission. Running a backfill may take time on large datasets.

## Permission model

The V2 pane uses the same server-side role and setting rules as the existing Control Center endpoints. A dashboard reader can see only the dashboard section when the dashboard-reader role setting is enabled. Management, activity-log, and maintenance sections require full Control Center access. Hiding a section in the browser is not an authorization boundary; the APIs enforce their own access checks.

## Related

- [V2 Control Center foundation](../explanation/features/V2_CONTROL_CENTER.md)
- [Operate SimpleChat day to day](admin-operate-simplechat.md)
