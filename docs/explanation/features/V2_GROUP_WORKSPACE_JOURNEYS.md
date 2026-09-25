# V2 Group Workspace Journeys

## Overview

The group workspace journeys are the end-to-end browser tests behind the M8
group release gate. Each drives the production V2 build through a path a real
member takes across several sections, rather than one section at a time. The
per-section suites prove each section works on its own. The journeys prove the
workspace holds together when the group, the member's role or the group's status
changes under an open page.

Implemented in version **0.261.161**.

Dependencies: the V2 group workspace shell, every native group section, and the
fixture parity pins that hold each section's test fixture to the real routes.

## What the journeys cover

Every journey the release gate names is either tested here or covered, by name,
by a per-section suite. The coverage table at the top of
`ui_tests/test_v2_group_journeys.py` maps each one to its tests.

The journeys tested in this suite:

- **Activation and reconciliation (J1):** opening a group activates it exactly
  once. When another tab makes a different group active, the page stays on its
  own group, explains the difference, and **Make this group active** activates
  it again, with the exact activation requests asserted.
- **Selector reach (J2):** with more than a thousand groups, a group that
  isn't on the picker's first page opens by its ID and can be reached through
  the picker, and the picker never asks for the whole list at once. From
  0.261.162, a lowercase name or a word from the group's description reaches it
  too.
- **Revoked membership (J3):** when the member is removed mid-session, the page
  says why and the cached documents and authoring content are cleared. An open
  editor's draft freezes group switching rather than being navigated away from
  silently, and nothing is written afterwards.
- **Status changes (J4):** locking the group removes the write controls from
  Documents, Prompts, Identities, Endpoints, File sources and Members after the
  page revalidates, and the header shows the status. An inactive group shows the
  server's reason. From 0.261.165, **Manage group (classic)** appears only in
  an inactive group or one whose status isn't recognized, and never in an
  active one.
- **Role changes (J5):** an Admin demoted to member loses the manager-only
  sections and every write control, and keeps Members without its management
  controls.
- **Deep links (J7):** a link with a stray resource segment opens its section,
  never a classic panel or a view stuck loading. This suite sweeps Prompts,
  Identities, Endpoints and File sources; Documents, Members, the older workflow
  link and an off-page document link are covered by the per-section tests the
  table names.
- **The classic round trip (J8):** a classic link confirms the group before
  leaving V2, and a change made in classic shows in V2 after the page regains
  focus. From 0.261.165 the link is Settings' **Delete group (classic)**.
- **The unsaved-editor guard (J9):** an unsaved draft in any of the eight
  editors (prompt, identity, endpoint, file source, agent, action, workflow
  and, from 0.261.165, the group settings) blocks switching groups and asks
  before leaving the section. **Keep editing** keeps the address, the draft and
  the active group.
- **The role, status and section matrix (J10):** for each of the four roles and
  five statuses, every section is present or locked exactly as the server's
  context says, and the overview lists the locked sections with the server's
  reason.

Chat handoffs (J6), the directory-to-member flow (J11) and the conflict smoke
test (J12) are covered by the per-section suites the table names.

## How it works

The journeys run on one composite fixture, `ui_tests/fixtures/group_journeys.py`,
that combines the directory, membership, prompt, document and authoring
fixtures over a single group store. Every fixture keeps its traps: a request for
personal, admin or classic data that a group page shouldn't make fails the test.

Every expected text, such as a status reason or a refusal, is read from the
fixture constants that the parity pins hold to the server. So when the server's
wording changes, the pin fails first, and the journeys follow the fix.

`functional_tests/test_group_picker_fixture_parity.py` pins the two routes the
picker calls, `GET /api/groups` and `PATCH /api/groups/setActive`, against the
real classic routes. It checks the page size and the uncapped total with more
than a thousand groups, the same group IDs on each page, the search, and every
activation answer (success, missing ID, unknown group and non-member).

## Findings

The suite found one product issue. The V2 group picker, and the Settings
**Groups** tab, search through the classic groups list, whose search was
case-sensitive and matched names only. So "research" didn't find "Research
Group", although the V2 group directory and public workspace search ignore case
and match descriptions too.

It was pinned in 0.261.161 as the strict `xfail`
`test_j2_picker_search_is_case_sensitive_XFAIL` and fixed in 0.261.162; see the
[Group Picker Search Casefold Fix](../fixes/GROUP_PICKER_SEARCH_CASEFOLD_FIX.md).
The test is now `test_j2_picker_search_ignores_case_and_matches_descriptions`,
and it passes.

## Running the suite

Build the V2 SPA first, then run the suite in its own process:

```powershell
cd application\v2_ui; npm run build; cd ..\..
python -m pytest ui_tests\test_v2_group_journeys.py
python -m pytest functional_tests\test_group_picker_fixture_parity.py
```

## Validation and limitations

When it was added, the suite passed 44 tests on three consecutive runs, with
the one strict `xfail` expected, and the picker pin passed 8. From 0.261.162 it
passes all 45, with no `xfail`. From 0.261.165 it also covers the Settings
delete link (J8), the Settings editor (J9) and the unknown-status case of J4.

- J11 checks the join request and the owner's approval separately; the
  requester's picker after approval isn't driven end to end.
- The shared base fixture's `setActive` answer differs from the server for an
  unknown group and a missing ID. The journeys use their own server-accurate
  handler, which the picker pin covers.
