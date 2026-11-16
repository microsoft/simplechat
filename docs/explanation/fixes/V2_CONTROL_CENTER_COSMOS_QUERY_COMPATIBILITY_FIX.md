# V2 Control Center Cosmos Query Compatibility Fix

**Fixed in version:** 0.261.292

## Issue

In the V2 Control Center, the Dashboard showed "Failed to retrieve dashboard insights." Users showed "Unable to retrieve users." Groups showed "Unable to retrieve groups." Every call to these endpoints returned HTTP 500:

- `GET /api/v2/control-center/dashboard/summary`
- `GET /api/v2/control-center/dashboard/insights`
- `GET /api/v2/control-center/users` (and `users/export.csv`)
- `GET /api/v2/control-center/groups` (and group detail, `groups/export.csv` and filter-based bulk status)

Public Workspaces and Activity Logs loaded normally.

## Root cause

For every failed request, Application Insights recorded the route's `[CONTROL_CENTER] ... failed` event with `error_type=CosmosHttpResponseError`. Cosmos DB answered those queries with HTTP 400 because they used three shapes that the azure-cosmos Python SDK cannot run across partitions.

1. **Cross-partition `GROUP BY`.** Before it runs a cross-partition query, the Python SDK asks the gateway for a query plan and lists the query features it can execute: Aggregate, CompositeAggregate, Distinct, MultipleOrderBy, OffsetAndLimit, OrderBy, Top and a few others. `GroupBy` is not on that list, even in the newest SDK, so the gateway rejects any query that needs it. Upgrading the SDK does not help. The request traces for the groups list show that the query-plan request itself returned 400. These queries used it:
   - Dashboard summary: group and public-workspace status counts, document uploads by workspace type.
   - Dashboard insights: tokens by day and model, top token consumers, top activity, login heatmap.
   - Groups inventory (`load_group_inventory`): document counts, all-time token totals, latest activity.
2. **`COUNT` over a `DISTINCT` subquery.** `SELECT VALUE COUNT(1) FROM (SELECT DISTINCT c.user_id ...)` needs the `DCount` feature, which the Python SDK also does not list. The dashboard active-user, DAU, WAU and MAU counts used it.
3. **Two-property `ORDER BY` without a composite index.** The Users list and export ordered by `<sort property>, c.id`. A multi-property `ORDER BY` needs a matching composite index, and the `user_settings` container has none. Expected composite indexes are applied only when an administrator enables App Maintenance indexing. The query plan succeeded, but the partition rejected the query.

The functional tests did not catch any of these. Their fake containers accepted any SQL, and some tests asserted that the `GROUP BY` text was present.

Activity Logs failed twice at the same time for a different, already documented reason: it needs the `activity_logs` composite index from App Maintenance. Once a manual maintenance run applied that index, Activity Logs worked, so it needs no change here.

## Resolution

The response contracts are unchanged. Each unsupported query is replaced with a shape that already works in production in this application.

| Area | Before | After |
|---|---|---|
| Active users, DAU, WAU, MAU | `COUNT(1)` over a `DISTINCT` subquery | `SELECT DISTINCT VALUE c.user_id`, counted in Python |
| Document uploads by workspace type | `GROUP BY c.workspace_type` | Three `SELECT VALUE COUNT(1)` queries: all, `group` and `public`. Personal is the remainder, matching the previous rule that any other or missing type counts as personal |
| Group and public-workspace status counts | `GROUP BY c.status` | `SELECT VALUE c.status`, tallied in Python and normalized by the existing `_dashboard_status_counts` |
| Dashboard insights | Six `GROUP BY` queries | Two streamed projections aggregated in Python: one over the filtered token records and one over the activity window |
| Groups inventory | Three `GROUP BY` aggregates | Three streamed projections (document group IDs, group token records, coalesced group ID and timestamp) aggregated in Python. The inventory still uses four batched queries and the 90-second snapshot |
| Users list and export | `ORDER BY <sort>, c.id` | Users with a recorded sort value are ordered by that single property. Users without one follow, ordered by `c.id`. This is the same approach as Public Workspaces, and the automatic index serves both queries |

### Behavior notes

- **Login heatmap:** each cell now totals every login in the period for that UTC weekday and hour. Before, the API returned one cell per date and hour, and the UI's lookup showed only the first matching date, so a 30-day range undercounted repeated weekdays. The response shape is unchanged.
- **Ranking ties:** top token consumers and top activity rankings are ordered by ID when totals tie, so repeated loads list them the same way.
- **Users ordering:** accounts with no recorded value for the sort column are listed last in either direction, in ID order. As in Public Workspaces, equal recorded values have no guaranteed secondary order.
- **Users export:** the export runs its first query before streaming starts. A storage failure now returns the JSON error instead of a CSV that contains only the header row.
- **Token values:** dashboard token totals add numeric values only. A non-numeric value counts as zero instead of making the whole aggregate undefined.
- **Cost:** in-application aggregation reads the same documents the `GROUP BY` queries would have read, returning narrow projections. Dashboard responses keep their 90-second cache, and the groups inventory keeps its 90-second snapshot.

## Files modified

- `application/single_app/route_backend_control_center.py`: dashboard summary and insights helpers, and Users paging and export helpers.
- `application/single_app/functions_control_center_groups.py`: `load_group_inventory`.
- `application/single_app/config.py`: version 0.261.292.
- `functional_tests/test_support/cosmos_query_guard.py` (new): rejects `GROUP BY`, `COUNT` over `DISTINCT` values, and multi-property `ORDER BY` without a declared composite index.
- `functional_tests/test_v2_control_center_cosmos_query_compatibility.py` (new): scans every SQL string in the V2 Control Center code paths through the guard. The activity-log `ORDER BY` passes only because `config.py` declares its composite index.
- `functional_tests/test_v2_control_center_dashboard.py`, `functional_tests/test_v2_control_center_users.py` and `functional_tests/test_v2_control_center_groups.py`: the fakes now pass every query through the guard. The tests run the real routes and aggregation helpers.

## Validation

- `python -m pytest functional_tests/test_v2_control_center_dashboard.py functional_tests/test_v2_control_center_users.py functional_tests/test_v2_control_center_groups.py functional_tests/test_v2_control_center_cosmos_query_compatibility.py`: all pass.
- Each new test fails on the code before this fix. On the previous route module, the compatibility scan reports 13 unsupported query sites: the Users list and export, dashboard summary and dashboard insights. The dashboard and Users route tests receive HTTP 500, and the groups aggregation test rejects the `GROUP BY` document count.
- Route-level dashboard and Users tests drive the real Flask handlers with fake containers that reject unsupported queries. The Users test checks a page that ends the recorded population and continues into the missing one, both sort directions, page clamping and export order.

## Related changes in this release

The V2 Data health section was removed in the same release, together with the activity-log backfill APIs that only it used: `GET /api/admin/control-center/migrate/status` and `POST /api/admin/control-center/migrate/all`. See [V2 Control Center](../features/V2_CONTROL_CENTER.md) and [Activity Log Migration Prompt Fix](ACTIVITY_LOG_MIGRATION_PROMPT_FIX.md).

## Follow-up in 0.261.296

Groups still failed after this fix. The inventory's latest-activity query also read the nested `group` object as `c.group.group_id`, and `GROUP` is a reserved Cosmos SQL keyword, so Cosmos rejected the query with the same HTTP 400. See [V2 Control Center Reserved Keyword Query Fix](V2_CONTROL_CENTER_RESERVED_KEYWORD_QUERY_FIX.md).
