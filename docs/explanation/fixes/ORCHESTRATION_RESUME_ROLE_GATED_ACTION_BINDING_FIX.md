# A run that waited could not be resumed for a caller holding an app role

Fixed in version: **0.261.474**

## Issue

A run that waits on background work (an export, for example) is resumed by a server worker
when that work finishes. In the reruns of 20 November 2026 every such resume failed:

- 0.261.468: 2 runs, `recovery_changed`
- 0.261.472: 2 runs, `recovery_changed`
- 0.261.473: 2 runs, `recovery_changed`, rule `execution_binding_changed`, stage
  `continuation_binding`

On 0.261.473 the log names each part of a run's binding when it is saved and when it is found
changed. For both runs the only part that differed was `binding_part_action_catalog_digest`,
with the same pair of values both times. Plan, inputs, model, memory, agent catalog, settings
and final response all matched.

## Root cause

The action catalog a run is offered depends on the caller's app roles: a Control Center
action is listed only for a caller who may view the Control Center dashboard
(`build_accessible_action_catalog` in `functions_action_catalog.py`).

- During the request, the roles come from the signed-in session, so the catalog lists the
  action for a caller who holds the role.
- The worker that resumes a waiting run has no request and no session. By design it holds no
  role claims (`current_execution_identity`: "background role gates fail closed"), so its
  catalog never lists the action.

The run's binding hashed the whole catalog. The two catalogs differ by that one entry, so the
binding differed and the resume was refused, whether or not the plan used the action.

A next attempt after a failure was not affected: it runs inside a copy of the request context
and keeps the roles.

**This is read from the code and the changed part named in the log, not observed directly.**
The log does not say which catalog entry differed. The catalog's only input that differs
between the request and the worker is the role claims, and the only entries that depend on
them are role-gated. 0.261.474 logs the counts that confirm or contradict this (below).

## Change

### The binding covers the actions that do not depend on a role claim

`bound_action_catalog` in `functions_orchestration_checkpoints.py` returns the catalog without
role-gated entries (`role_gated_action`, the same test the catalog applies before it checks
the caller's roles; a test asserts the two agree), and the binding's action digest is taken
over that list.

The role gate is not changed:

- The worker is still never offered a role-gated action.
- Execution validates the plan against the context's own catalog before any step runs
  (`validate_plan(..., action_refs=...)` in `_execute_dependency_plan`), so a plan step that
  names a role-gated action is rejected on the worker, as before.
- Any other action added, removed or changed still changes the binding and refuses the
  resume.

### Logging

`[ORCHESTRATION_RUNS] Execution binding parts.` also records `action_count`,
`role_gated_action_count` and `agent_count`. If a run's saved line shows
`role_gated_action_count` of 1 or more and it now resumes, the cause above is confirmed. If a
resume is still refused, the changed line names the part as before.

## Files modified

- `application/single_app/functions_orchestration_checkpoints.py`
- `application/single_app/functions_orchestration_recovery.py`
- `functional_tests/test_orchestration_server_continuation.py`
- `application/single_app/config.py`

## Validation

- `test_a_role_gated_action_is_outside_the_binding_and_still_gated`: a request context that
  lists a role-gated action and a worker context that does not have the same binding; adding,
  removing or changing any other action gives a different one.

## Not verified

- **Not run against the deployed application.** The next rerun shows whether a waiting run
  now resumes.
- A run that waits and whose plan uses a role-gated action still cannot be resumed by the
  worker. That is the role gate working as designed, and is not changed here.
- Runs saved by an earlier version are bound to the old digest when the caller's catalog lists
  a role-gated action, so they are not resumed; they run again.
- Two runs on 0.261.472 failed with `context_unavailable` after waiting. That did not occur on
  0.261.473 and is not explained.
