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

Choose a 7-, 30- or 90-day range, or a custom inclusive UTC date range of up to 366 days. The page answers the usual questions in order, one section each.

### Directory

Current totals for users, blocked users, groups, public workspaces and pending approvals. The date range does not change them. Groups and public workspaces list any that are locked, have uploads disabled or are inactive, so the ones that need attention stand out.

### Sign-ins

Every figure here counts a person once, however often they signed in:

- **Signed-in users**: people who signed in at least once in the range, compared with the previous range of the same length.
- **Daily active users**: people who signed in on the range's end date.
- **Weekly active users**: people who signed in during the 7 days ending on the end date.
- **Monthly active users**: people who signed in during the 30 days ending on the end date.

The daily chart counts sign-ins, so a person who signs in twice counts twice. The weekday-and-hour table totals every sign-in in the range by UTC weekday and hour, which shows recurring busy times rather than one day.

### Conversations and documents

Conversations created, document uploads by personal, group and public workspace, and uploads whose processing failed, each with a daily chart where there is activity.

### Token usage

The token filters sit at the top of this section and change only the figures in it: tokens used, tokens by usage type, tokens by model and the top token consumers. Sign-ins, conversations and uploads are not filtered, because the filters describe token records. **Clear filters** returns to every token record in the range.

Rankings show each user's display name and email, and each group's or public workspace's name. Point at a name to see its ID. A ranked group or workspace that has since been deleted is shown as **Deleted group** or **Deleted public workspace**.

### Most active

The users, groups and public workspaces with the most activity records in the range, such as sign-ins, conversations, uploads, token use and administrative actions. Token filters do not apply here.

### Drill through, export and refresh

Select a point in a chart to open Activity Logs for that day: a sign-in point opens sign-ins, a segment of a stacked bar opens that series, and token charts keep the token filters. Figures and names link to the Users, Groups, Public Workspaces or Activity Logs sections only when your Control Center permissions include that section. Charts include data tables for screen-reader and text-based access.

**Export** downloads the range's trend data as CSV. Dashboard figures are cached for 90 seconds; choose **Refresh** to recalculate them.

## Chat with the dashboard

Choose **Chat with this dashboard** to ask questions about the usage data in chat. When it is set up, it opens a new chat with orchestration turned on and a prompt that describes the dashboard's date range and token filters. Read or change the prompt, then send it. The answer comes from the [Control Center action]({{ '/reference/actions/control-center/' | relative_url }}), which reads the same data as the dashboard, so figures match the dashboard for the same dates.

When something is missing, a checklist marks each requirement **Ready** or **Needs set-up** and says what to do. Administrators get a link to the setting; anyone else is told what to ask an administrator for. Choose **Check again** after a change.

| Requirement | Where it is set |
| --- | --- |
| Agents and actions are turned on | **Enable Agents** in **Admin Settings › Agents & Actions › Agent Runtime** |
| Chat Orchestration is turned on | **Enable Chat Orchestration** in **Admin Settings › Orchestration** |
| Orchestration can use actions | **Enable Action Access** in **Admin Settings › Orchestration › Capabilities**, with **Use an action** allowed in the capability list |
| A Control Center action is set up for you | A global Control Center action in **Admin Settings › Agents & Actions › Global Actions**, turned on, offered in chat when Workspace Mode is on, and allowed for you by governance |
| Your account can use chat | The **User** or **Admin** app role; listed only when your account has neither |

The action only answers for people who can view the Control Center dashboard, so the chat works for administrators and dashboard readers alike, and it cannot change anything.

## Manage groups

Group management was implemented in **0.261.282**. Open **Groups** to locate shared workspaces by name, description, owner, status, member-count range, document presence, creation date or last activity. Sort by name, owner, members, documents, tokens or activity to prioritize a review. Counts and all-time tokens use a server snapshot, timestamped in the list and cached for 90 seconds. **Refresh groups** rebuilds that snapshot. Export downloads all matching groups, not just the visible page.

Select a group to inspect its Overview, Members, Ownership, Status, Retention, Activity and Documents tabs. Owner/member links open the corresponding user details. Activity shows the most recent 20 records, offers their raw JSON and a CSV of that subset, and links to Activity Logs with the group scope.

Select rows, then optionally select all matches across pages, to apply a bulk status. Bulk updates are limited to 500 groups. Locked and inactive changes require a reason and record each actual transition in the status history. Locked groups keep document viewing and chat but disallow document changes; upload-disabled groups prohibit uploads; inactive groups are unavailable. Individual failures remain visible after the list refreshes.

Use **Add member** to search the directory, or **Import CSV** to add up to 1,000 people using `userId,displayName,email,role`. Confirm the CSV identities before importing: the Control Center admin flow uses the supplied ID, name and email. The import reports added, already-member and failed rows, and lets you retry failures.

Changing member roles, removing members and saving retention still require group Owner/Admin membership; full Control Center access alone is not enough. The UI explains unavailable controls. Retention additionally requires enabled group retention and accepts organization defaults, no automatic deletion, or a permitted day count.

Requesting group deletion, deleting all group documents, taking ownership, or transferring ownership to a member requires a reason and creates an approval request. Nothing is deleted and ownership remains unchanged at submission. Follow **View approval requests** in the result notice to the approvals page.

## Investigate activity

Activity Logs was implemented in **0.261.284** and redesigned in **0.261.296**. Open it from a dashboard chart, a user/workspace activity link, or the section rail. It answers who did what, where and when, with people and workspaces shown by name rather than by ID.

### Narrow the log with filter pills

The row above the log is the investigation. Each pill shows what it is set to and applies as soon as you change it:

- **Search** matches people's names and emails, file names, conversation titles, models and IDs. Typing a person's name finds what they did, even on records that store only their ID.
- **Date** offers today and the last 7, 30 or 90 days, or a custom UTC range of up to 366 days. The default is the last 30 days.
- **Activity** lists the activity types by group, with counts for the current range.
- **Person** finds a SimpleChat user by name, email or user ID. It shows what that person did, including approvals and admin changes they made. To investigate someone who has since been removed from SimpleChat, type their user ID and choose **Filter by user ID**.
- **Workspace** chooses personal, all groups, all public workspaces, or one group or public workspace by name or ID. A removed workspace can be filtered the same way, with **Filter by group ID** or **Filter by public workspace ID**.
- **Add filter** adds a model, token type or recorded status.

Remove one filter with the **×** on its pill, or use **Reset filters**. The URL updates as you go, so bookmarking it keeps the investigation, and a relative range such as "Last 7 days" stays relative. If the page stays open past midnight UTC, **Refresh** moves a relative range to the new day.

### Read and cross-filter the log

Under the filters, a slim trend strip shows how many records match, one bar per UTC day or period, and the most frequent activity types. Select a bar to narrow the dates to it. With the keyboard, Tab to the bars, move between them with the arrow keys and press Enter. Select an activity type to filter by it. **Hide trend** collapses the strip to its count, and the page remembers your choice. For busy ranges the strip says it uses only the newest 5,000 records; do not read those counts as organization-wide totals.

Each row reads as a sentence: the time, the person, the activity, what happened and the workspace. Select a person, an activity or a workspace in any row to filter the log by it. Select the details to open the record. Times show in your local time; hover over a time to see it in UTC, or switch the table to **UTC**. **Compact** fits more rows on screen. Both choices are remembered on your account. The log reads 50 records at a time, newest first; **Refresh** starts over with newly recorded activity.

The record drawer shows what happened, **Who** (with **Show only this person's activity** and **Open in Users**), **Where** (with **Show only this workspace** and the group or workspace), the recorded details, and the record's IDs and approval link. The raw JSON is collapsed at the bottom with **Copy JSON**. Use **Previous** and **Next** to step through the page without closing the drawer.

### Save and reuse views

**Views** opens quick views for recent sign-ins, recent token usage and document processing failures, and your saved views. **Save the current filters as** stores the current filters under a name; saving with an existing name replaces that view. Saved views live on your account, so they are there in any browser, and you can rename or delete them from the same menu. Views you saved in a browser before 0.261.296 move to your account the first time you open Activity Logs in that browser. If your settings cannot be loaded, the menu shows only the quick views until you reload the page, so a save cannot overwrite views it could not read.

### Export

**Export CSV** uses the same filters, not just the visible page, and exports no more than 10,000 activity rows. Next to the stored IDs, the export includes the person's name and email, the activity, a readable summary, and the workspace name. A final `export_limit_reached` row means the limit was reached; narrow the filters to export a smaller complete range. Spreadsheet formula prefixes are escaped. The export includes raw JSON, so handle the downloaded audit information according to your organization's data policies.

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
