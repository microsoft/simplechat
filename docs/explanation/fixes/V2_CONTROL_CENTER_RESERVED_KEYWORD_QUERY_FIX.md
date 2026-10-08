# V2 Control Center Reserved Keyword Query Fix

**Fixed in version:** 0.261.296

## Issue

After the [V2 Control Center Cosmos Query Compatibility Fix](V2_CONTROL_CENTER_COSMOS_QUERY_COMPATIBILITY_FIX.md) in 0.261.292, the V2 Control Center **Groups** section still showed "Unable to retrieve groups." The same root cause also broke four other queries:

| Where | What the administrator saw |
|---|---|
| `GET /api/v2/control-center/groups` (and `groups/export.csv`, filter-based bulk status) | "Unable to retrieve groups." |
| `GET /api/v2/control-center/groups/<id>` | "Unable to retrieve group details." |
| Activity Logs with a group filter, including **View in Activity Logs** from a group | "Unable to load activity logs. Check the activity-log composite index in App Maintenance, then retry." |
| Activity Logs with **any** search text | The same misleading index message |
| Classic Control Center group activity timeline | No error; member and status-change events were silently missing |

## Root cause

`GROUP` is a reserved keyword in the Cosmos DB for NoSQL query language: it begins `GROUP BY`. In the query grammar a dotted property name must be an identifier, and the only keywords allowed there are `ALL`, `FIRST` and `LAST`. A reserved word as a property, such as `c.group.group_id`, is therefore a syntax error. Cosmos rejects the whole query with HTTP 400 before running it, the same status the 0.261.292 investigation attributed to `GROUP BY`.

Group status-change and member-removal records store their group as a nested `group` object, so several queries read `c.group.group_id`:

- `load_group_inventory` in `functions_control_center_groups.py`: the coalesced group ID used for each group's latest activity. 0.261.292 removed the query's `GROUP BY` but kept this expression, so the Groups list still failed.
- `api_v2_control_center_group_detail`: projected `c.group` and filtered on `c.group.group_id`.
- `activity_query_context` in `functions_control_center_activity.py`: the Activity Logs group filter, and the search field list, which included `group.group_name` and so generated `CONTAINS(c.group.group_name, ...)` for every search.
- The classic group activity timeline in `route_backend_control_center.py`: its first query failed on every call, and the route's `try`/`except` dropped it silently.

The tests did not catch it. The query guard only checked for SDK-unsupported shapes, the search clause is generated at run time, and the Groups test asserted the broken text itself.

## Resolution

Reserved segments are now written with the quoted property accessor, which Cosmos treats exactly like the dotted form:

| Before | After |
|---|---|
| `c.group.group_id` | `c['group']['group_id']` (groups inventory, group detail, classic timeline) or `c['group'].group_id` (activity filter) |
| `c.group` in a `SELECT` list | `c['group']`, still returned as `group` |
| `CONTAINS(c.group.group_name, @search, true)` | `CONTAINS(c['group'].group_name, @search, true)` |

`functions_control_center_activity.py` gains `COSMOS_RESERVED_WORDS` and `cosmos_property_path()`, which brackets any reserved segment of a dotted path. Every generated property reference in the activity query uses it, including the search fields and the new person and workspace filters.

### Related hardening in the same release

- `group_members()` and `group_row()` treat a non-object owner, non-object member entries, non-list role lists and non-text names as missing, so one legacy group document cannot turn the whole list into a 500.
- The V2 group list, group detail and activity query failure logs now record the Cosmos `status_code` alongside the error type. Clients still receive only the generic message.

## Files modified

- `application/single_app/functions_control_center_groups.py`: `NESTED_GROUP_ID`, the bracketed inventory expression, and tolerant `group_members()`/`group_row()`.
- `application/single_app/functions_control_center_activity.py`: `COSMOS_RESERVED_WORDS`, `cosmos_property_path()`, and the bracketed group filter and search fields.
- `application/single_app/route_backend_control_center.py`: the group detail activity query, the classic group activity timeline query, and status codes in the failure logs.
- `functional_tests/test_support/cosmos_query_guard.py`: `reserved_word_problems()` rejects reserved keywords used as dotted property names or aliases; `cosmos_query_problems()` includes it.
- `functional_tests/test_v2_control_center_cosmos_query_compatibility.py`: applies the reserved-word check to every SQL string in `route_backend_control_center.py` and the `functions_control_center_*` modules, classic routes included, and to the generated Activity Logs search and group filters.
- `functional_tests/test_v2_control_center_groups.py` and `functional_tests/test_v2_control_center_activity_logs_queries.py`: assert the bracketed form, run generated queries through the guard, and add a malformed legacy group case.
- `application/single_app/config.py`: version 0.261.296.

## Validation

- `python -m pytest functional_tests/test_v2_control_center_groups.py functional_tests/test_v2_control_center_cosmos_query_compatibility.py functional_tests/test_v2_control_center_activity_logs_queries.py`: all pass.
- With only `functions_control_center_groups.py` reverted, the Groups list, inventory and detail tests fail with "reserved keyword 'group' used as a property name", the guard's report of the production failure.
- The compatibility scan reads more than 60 Control Center query strings and finds no reserved-word property access.

### Before and after

| Request | Before | After |
|---|---|---|
| Groups list | HTTP 500, "Unable to retrieve groups." | Groups with document, token and last-activity totals |
| Group details | HTTP 500 | Details with the 20 most recent activity records, including member and status changes |
| Activity Logs search for any text | HTTP 500 with an index hint | Matching records |
| Activity Logs filtered to a group | HTTP 500 with an index hint | That group's activity |
| Classic group activity timeline | Member and status events missing | Complete timeline |

Existing deployments need no index change or App Maintenance step.
