---
layout: page
title: "Use the V2 Control Center"
description: "Review usage trends in the V2 Control Center and check activity-log data only when needed."
section: "Guides"
audience: admin
---

## What the Control Center provides

The V2 Control Center is a separate administration pane for users assigned Control Center access. It is kept out of the primary workspace navigation and appears in **Account → Control Center** when at least one Control Center capability is available to you.

The section rail is filtered to your permissions. The Dashboard is available to dashboard readers and Control Center administrators. User and group management, public workspaces, and activity logs are being delivered in phases; open the classic Control Center from those sections' placeholders.

## Review dashboard activity

Choose a 7-, 30-, or 90-day period, or set an inclusive custom UTC date range of up to 366 days. Summary cards show user and workspace counts, period activity, token usage, and pending approvals when that count is available. Counts that have no historical snapshots are labeled as current status instead of showing a misleading period delta.

The charts use recorded logins, conversation creation, document creation by workspace type, token usage type, token models, and workspace activity. Select chart points or KPI cards to open the related section with query filters. Use **Export** to download trend data as CSV, or **Chat with these trends** to start a conversation containing the selected trend data. Token filters apply to token totals and token charts; they do not change login, conversation, or upload counts.

The login heatmap reports UTC hours with Monday as weekday zero. Charts include data tables for screen-reader and text-based access. Dashboard summaries are cached for 90 seconds; choose **Refresh** to bypass the cache.

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
