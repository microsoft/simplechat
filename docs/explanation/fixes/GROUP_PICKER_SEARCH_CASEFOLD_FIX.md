# Group Picker Search Casefold Fix

Fixed/Implemented in version: **0.261.162**

## Issue

Searching your own groups was case-sensitive and matched names only. Typing
"research" didn't find "Research Group", and a word from a group's description
found nothing.

Every list of the signed-in user's own groups searches through the same route,
`GET /api/groups?search=`:

- the V2 group picker, **Search your groups**, on the group workspace page;
- the V2 Settings **Groups** tab;
- the classic **My Groups** page;
- the classic profile page's **Groups** tab.

The V2 group directory, the admin group search and the public workspace lists
already ignore case and match descriptions. So the same term found a group in
one list and not in another. With more than one page of groups, a group the
search can't find is reachable only by paging to it.

The M8 group journeys found it, and it was pinned in 0.261.161 as the strict
`xfail` `test_j2_picker_search_is_case_sensitive_XFAIL`.

## Root cause

`functions_group.search_groups`, which the route calls for a search, filtered
with `CONTAINS(c.name, @search)`. Cosmos DB's `CONTAINS` is case-sensitive
unless told otherwise, and the filter never read the description. The admin
search in the same module, `search_all_groups`, already lowercased both sides.

## Fix

`search_groups` lowercases the trimmed term. Inside the existing membership
check, it now uses the same filter as `search_all_groups`:

```sql
AND (CONTAINS(LOWER(c.name), @search)
     OR (IS_DEFINED(c.description) AND CONTAINS(LOWER(c.description), @search)))
```

- A group with no description, or a description that isn't text, can still
  match by name.
- An empty term still lists every group the user belongs to, because the route
  calls `get_user_groups` for that.
- Paging, `total_count` and the returned fields are unchanged.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_group.py` | `search_groups` ignores case and matches the description. A duplicated `query = query =` assignment is also removed. |
| `functional_tests/test_support/group_directory_harness.py` | The fake groups container expects the new query and models its filter. |
| `ui_tests/fixtures/group_journeys.py` | The journeys fixture's `/api/groups` search models the new filter. |
| `functional_tests/test_group_picker_fixture_parity.py` | The case-sensitivity pin becomes a parity test for the new behaviour. |
| `ui_tests/test_v2_group_journeys.py` | The J2 strict `xfail` becomes a passing journey. |

## Testing

- **Fixture parity.** In `functional_tests/test_group_picker_fixture_parity.py`,
  `test_list_search_ignores_case_and_matches_descriptions_like_the_server`
  replaces the case-sensitivity pin. On the real route and in the journeys
  fixture, each of these finds the same group:
  - a lowercase fragment of a name;
  - an uppercase word found only in a description;
  - a term with surrounding spaces.

  A term in neither field finds nothing on either side.
- **Query model.** The harness still refuses any groups query it doesn't model.
  So a later change to the filter fails every suite that uses it until the model
  is reviewed.
- **Browser journey.** `test_j2_picker_search_ignores_case_and_matches_descriptions`,
  formerly the strict `xfail`, drives the built V2 app. The target group sits
  off the picker's first page among 1,003 groups. A lowercase name reaches it,
  and so does a word found only in its description.
- **Mutation checks.**
  - Restoring the old server query fails the parity test.
  - Restoring the old journeys fixture fails the parity test and the J2 journey.

## Validation

| Search | Before | After |
| --- | --- | --- |
| `research` for "Research Group" | No match | Match |
| A word from a group's description only | No match | Match |
| `Research` for "Research Group" | Match | Match |
| A term in neither the name nor the description | No match | No match |

Results:

- The 22 functional suites that use the group harnesses: 1,905 tests passed.
- The journeys suite: 45 passed on each run, with no `xfail` left.
- The broken access control check passes on `functions_group.py`.

## Related

- [V2 Group Workspace Journeys](../features/V2_GROUP_WORKSPACE_JOURNEYS.md), which
  found the issue.
