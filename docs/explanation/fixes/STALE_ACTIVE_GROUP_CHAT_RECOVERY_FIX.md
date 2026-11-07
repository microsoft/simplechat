# Stale active-group chat recovery

Fixed/Implemented in version: **0.261.371**

Issue: [#1816](https://github.com/microsoft/simplechat/issues/1816)

## Issue and root cause

A user's saved `settings.activeGroupOid` could still reference a group after
their membership ended or the group was deleted. During per-user Semantic
Kernel initialization, optional group-agent discovery called the strict
`require_active_group` helper. It caught the `ValueError` for no selected group,
but not the `PermissionError` for revoked membership or the `LookupError` for a
deleted group. Unrelated personal/global-agent chat could therefore fail before
producing any response, appearing as an interrupted stream.

V2 filtered stale IDs out of its scope response without repairing the saved
preference. Legacy chat could also display the former group's name from that
preference. Users with no other groups could not repair this by selecting a
replacement.

## Recovery behavior

Legacy chat page loading, V2 bootstrap/scope reads, and the shared ordinary-chat
request boundary now reconcile the optional active group. Optional group-agent
discovery uses the same resolver.

- A missing selection stays unselected without a repair write.
- A valid Owner, Admin, DocumentManager, or User role preserves the selection.
- A confirmed missing group or revoked membership clears the preference to JSON
  `null`. No replacement group or agent is automatically selected.
- Ordinary model-only and authorized personal/global-agent chat can continue
  without any group membership, including the next send from an already-open tab.
- An explicitly selected, authorized agent from another group retains its own
  group scope; it does not depend on the unrelated active preference.
- Required-group operations still use strict authorization. Repair does not
  grant access to former group agents, actions, documents, or conversations.

Membership lookup failures remain errors rather than evidence of revocation.
They do not erase the preference. Once loss of membership has been confirmed,
a failed settings repair is logged and the stale value is masked for that
request. Later requests retry persistence.

## Persistence and cache boundaries

The group owner delegates repair to a dedicated settings-owner compare-and-clear
operation, rather than the general settings updater, which can initialize agent
defaults. The operation authorizes the settings owner, reads fresh storage,
compares the saved ID, and conditionally replaces the document using its ETag.
It preserves unrelated fields and will not clear a newer group selection from
another tab. Conflicts are retried at most three times; missing records are not
created and missing ETags never trigger unconditional writes.

Request-local settings and lightweight UI caches are reconciled after repair.
There is no bulk migration or cross-user write during membership removal.
Group membership and user preferences are separate documents, so resource-use
authorization remains necessary after preference reconciliation.

## Files and version tracking

- `application/single_app/functions_group.py`: optional active-group resolver;
  strict group authorization is unchanged.
- `application/single_app/functions_settings.py`: conditional, owner-authorized
  repair and cache handling.
- `application/single_app/semantic_kernel_loader.py`: optional group-agent
  discovery no longer aborts unrelated agent loading.
- `application/single_app/route_backend_chats.py`: shared chat reconciliation.
- `application/single_app/route_frontend_chats.py`: authorized legacy page state.
- `application/single_app/route_backend_v2.py`: durable V2 bootstrap/scope repair.
- `application/single_app/config.py`: application version **0.261.371**.

No browser runtime dependency, new API field, route, feature toggle, or deployment
configuration is added.

## Validation

`functional_tests/test_stale_active_group_recovery.py` reproduces the original
loader exception and covers real settings/group owners with SDK-shaped Cosmos
responses, ETags, role validation, caches, concurrent preferences, lookup
failures, repair failures, and bounded retries. Fresh normal and optimized
Python processes run the actual web application with external I/O doubled and
network access blocked.

The runtime suite also exercises the legacy page, V2 bootstrap/scope, and
streaming/non-streaming chat. Model replies are synthetic; the tests do not
claim live Azure provider availability.

`ui_tests/test_chat_stale_active_group_recovery.py` drives both production
clients through the real offline Flask routes, including revoked membership
after the page has loaded. It checks a completed assistant response and
persisted cleanup rather than only the absence of an exception. It uses the
shared local/Azure Playwright connection fixture and synthetic user records.

Before the fix, the regression raises `PermissionError` during Semantic Kernel
loading. After the fix, no-group chat completes and stale selections are cleared
without changing permissions or unrelated preferences.

### Recorded results

Validation used application-pinned Cosmos SDK **4.9.0** and isolated Python
dependencies. The consolidated command below passed **28 tests**:

```powershell
python -m pytest -q functional_tests\test_stale_active_group_recovery.py functional_tests\test_v2_scope_and_bootstrap_timings.py functional_tests\test_group_agent_endpoint_scope_resolution.py functional_tests\test_chat_v1_page_bootstrap.py ui_tests\test_chat_stale_active_group_recovery.py
```

The three route-policy scripts passed **28 checks**; documentation surface
coverage and site quality passed **13 checks**. The V2 production build,
changed-line authorization/XSS checks, Python syntax, and whitespace checks
also passed. The reviewed Cosmos inventory has **zero gaps**.

The broader SDK runtime gate is not green: after **601 passing checks** in its
continuation run, it stopped at
`test_selected_result_citations_reach_headless_message_cache_and_delivery[evidence-execute]`,
which expects one citation but receives two. The identical failure was reproduced
against an untouched archive of the starting commit, version **0.261.370**.
Separately, the existing `test_user_ui_settings_cache_contract` expects the
already-absent `APP_SETTINGS_CACHE_VERSION_DOC_ID` marker. These unrelated
baseline failures were not changed as part of this fix.
