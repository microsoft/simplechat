---
layout: page
title: "Use the V2 Control Center"
description: "Review usage trends and manage users, groups, public workspaces and activity in the V2 Control Center."
section: "Guides"
audience: admin
---

## What the Control Center provides

The V2 Control Center is a separate administration pane for users assigned Control Center access. It is kept out of the primary workspace navigation and appears in **Account → Control Center** when at least one Control Center capability is available to you.

The section rail is filtered to your permissions. The Dashboard is available to dashboard readers and Control Center administrators. Users, Groups and Public Workspaces have native V2 management.

## Manage users

Open **Users** to find accounts by email or display name, filter by access, upload permission, recent login, or document ownership, and sort usage columns. Accounts without a recorded value for the sort column, such as users whose metrics have not been refreshed yet, are listed after the others in either direction. Filters and sorting are reflected in the URL, so a filtered view can be bookmarked or opened from a Dashboard drill-through. The list reports when its cached usage metrics were calculated and how many accounts on the current page have not yet received a metrics refresh.

Select rows to allow or deny access or uploads. Selection can include all users matching the current filters across pages, with an option to exclude individual accounts. Restrictions may have an optional expiry. Open a user to review the account, recent activity, group and public-workspace memberships, and ownership. Changes reconcile against the server and report failures rather than leaving the list in an optimistic-only state.

Deleting all documents for a user requires a reason and submits an approval request; it does not perform deletion immediately. **Export CSV** downloads the full filtered result set rather than only the current page. The Activity tab links to Activity Logs with the selected `user_id`.

## Review dashboard activity

Choose a 7-, 30-, or 90-day period, or set an inclusive custom UTC date range of up to 366 days. Summary cards show user and workspace counts, period activity, token usage, and pending approvals when that count is available. Counts that have no historical snapshots are labeled as current status instead of showing a misleading period delta.

The charts use recorded logins, conversation creation, document creation by workspace type, token usage type, token models, and workspace activity. Select chart points or KPI cards to open the related section with query filters. Use **Export** to download trend data as CSV, or **Chat with these trends** to start a conversation containing the selected trend data. Token filters apply to token totals and token charts; they do not change login, conversation, or upload counts.

The login heatmap totals the logins for each UTC weekday and hour across the selected period, with Monday as weekday zero, so it shows recurring busy times rather than a single day. Charts include data tables for screen-reader and text-based access. Dashboard summaries are cached for 90 seconds; choose **Refresh** to bypass the cache.

## Manage groups

Group management was implemented in **0.261.282**. Open **Groups** to locate shared workspaces by name, description, owner, status, member-count range, document presence, creation date or last activity. Sort by name, owner, members, documents, tokens or activity to prioritize a review. Counts and all-time tokens use a server snapshot, timestamped in the list and cached for 90 seconds. **Refresh groups** rebuilds that snapshot. Export downloads all matching groups, not just the visible page.

Select a group to inspect its Overview, Members, Ownership, Status, Retention, Activity and Documents tabs. Owner/member links open the corresponding user details. Activity shows the most recent 20 records, offers their raw JSON and a CSV of that subset, and links to Activity Logs with the group scope.

Select rows, then optionally select all matches across pages, to apply a bulk status. Bulk updates are limited to 500 groups. Locked and inactive changes require a reason and record each actual transition in the status history. Locked groups keep document viewing and chat but disallow document changes; upload-disabled groups prohibit uploads; inactive groups are unavailable. Individual failures remain visible after the list refreshes.

Use **Add member** to search the directory, or **Import CSV** to add up to 1,000 people using `userId,displayName,email,role`. Confirm the CSV identities before importing: the Control Center admin flow uses the supplied ID, name and email. The import reports added, already-member and failed rows, and lets you retry failures.

Changing member roles, removing members and saving retention still require group Owner/Admin membership; full Control Center access alone is not enough. The UI explains unavailable controls. Retention additionally requires enabled group retention and accepts organization defaults, no automatic deletion, or a permitted day count.

Requesting group deletion, deleting all group documents, taking ownership, or transferring ownership to a member requires a reason and creates an approval request. Nothing is deleted and ownership remains unchanged at submission. Follow **View approval requests** in the result notice to the approvals page.

## Investigate activity

Activity Logs was implemented in **0.261.284**. Open it from a dashboard chart, a user/workspace activity link, or the section rail. Choose a UTC date window (default 30 days, maximum 366), select one or more activity-type chips, and narrow by user or workspace ID, model, token type, text or recorded status. **Apply filters** updates the URL so a bookmark preserves the investigation. **More filters** exposes explicit group/public-workspace IDs and status.

The histogram and chip counts describe the filtered records. For busy ranges, they describe only the newest 5,000 matches and clearly say **Sampled**; do not use them as organization-wide totals. Expand the histogram data table to select a UTC bucket and investigate that date window. The table reads 50 records at a time in newest-first order. **Refresh** starts over with newly recorded activity; changing filters resets paging.

Choose **Inspect** for a record's fields and raw JSON. Related links open its recorded user, group, public workspace or approval. The drawer supports Escape and restores keyboard focus to the opener. Use compact density to scan more rows. Saved views preserve applied filters for the signed-in user on this browser, not across devices; removing a saved view does not delete activity.

**Export CSV** uses the same filters, not just the visible page, and exports no more than 10,000 activity rows. A final `export_limit_reached` row means the limit was reached; narrow the filters to export a smaller complete range. Spreadsheet formula prefixes are escaped. The export includes raw JSON, so handle the downloaded audit information according to your organization's data policies.

On an existing deployment, an indexing error requires an administrator to apply the new expected activity-log composite index in **Admin Settings → App Maintenance** and wait for Cosmos index transformation. The activity page does not automatically apply cloud changes. A date cutoff stabilizes forward paging against newer events, but cannot freeze deletes or late/backdated writes; the feed is not a transactional snapshot.

## Manage public workspaces

Public workspace management was implemented in **0.261.283**. Open **Public Workspaces** to find knowledge spaces by name/description, responsible owner and status. Sort and page on the server, bookmark the filtered URL or export matching records (up to 10,000). The list displays recorded metric refresh times. Unavailable metrics are not zero; refresh reloads stored snapshots, while opening details computes live document and token totals.

Managers include the owner, administrators and document managers, not everyone who can read the public collection. Add or import only Admin and DocumentManager roles. Public readers are implicit. Verify CSV identities before import, and review each import outcome.

Select up to 500 workspaces across pages to change status. Locked and inactive changes require a reason. Active both unlocks the workspace and enables uploads; upload-disabled blocks uploads, while inactive makes the workspace unavailable. Failed items stay visible after the list refresh.

The detail drawer shares the Groups tabs and supports status history, recent activity/raw JSON/export, ownership requests and document summaries. Member removal/role changes and retention edits still require workspace Owner/Admin membership. The existing public retention API supports `none` or a permitted numeric day count: inherited fields are left unchanged, and resetting a custom value to organization defaults is not available here.

Individual document deletion, workspace deletion, take-ownership and transfer-to-member workflows request approval on the existing server routes. A submission notice means **requested**, not executed. Its link opens the particular approval with workspace scope. The existing document-deletion executor can report successful deletions while other documents fail; workspace deletion can then proceed after partial cleanup. Review execution logs/results rather than treating the submitted request as completed cleanup.

Activity exports contain only the 20 recent projected records displayed in the drawer. Activity Logs links open the broader investigation with public workspace scope.

## Permission model

The V2 pane uses the same server-side role and setting rules as the existing Control Center endpoints. A dashboard reader can see only the dashboard section when the dashboard-reader role setting is enabled. Management and activity-log sections require full Control Center access. Hiding a section in the browser is not an authorization boundary; the APIs enforce their own access checks.

## Related

- [V2 Control Center foundation](../explanation/features/V2_CONTROL_CENTER.md)
- [Operate SimpleChat day to day](admin-operate-simplechat.md)
