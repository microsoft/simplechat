# Workflow Background Identity Fix

Fixed in version: **0.261.218**

## Issue

A scheduled workflow run that used the SimpleChat action could not finish group and conversation work that a manual run of the same workflow completed:

- `add_user_to_group` and `invite_group_conversation_members` failed with `Could not acquire access token`.
- Groups and conversation messages the run created showed the owner's object ID where their name should be.
- The run then wrote that object ID over the owner's stored display name.

## Root Cause

A scheduled run has no signed-in session, so `_ensure_execution_context` in the workflow runner creates one. That session held only the owner's object ID: `name` was the ID and `preferred_username` was empty.

- Everything that reads the current user's name, such as group creation and conversation messages, recorded the ID.
- `get_user_settings` syncs the session's name into the stored profile when the session user is the profile's owner, so the ID replaced the stored display name.
- `resolve_directory_user` reaches Microsoft Graph with the signed-in user's delegated token unless it is given a user ID together with an email or display name. A scheduled run has no such token. The SimpleChat action's `add_user_to_group` could not pass a user ID, and group conversation invites always resolved each identifier through Graph, even for people who were already members of the group.

A manual "Run now" was unaffected because it reuses the signed-in request's session.

## Technical Details

Files modified:

- `application/single_app/functions_workflow_runner.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/semantic_kernel_plugins/simplechat_plugin.py`
- `application/single_app/config.py`
- `functional_tests/test_workflow_background_identity.py` (new)
- `functional_tests/test_simplechat_agent_group_output.py`

Changes:

- **Run identity.** When the runner creates a session, it reads the owner's stored `display_name` and `email` with the read-only `read_user_settings_snapshot` and uses them for `name` and `preferred_username`. The owner ID comes from the stored workflow, not from a caller. If no profile is stored, or the read fails, the run keeps the previous bare identity; a failed read is logged as a warning. A run inside a request already signed in as the owner reuses that session unchanged, as before. Roles stay `['User']`.
- **Adding members.** `add_user_to_group` accepts `user_id`. Given with an email or display name, it resolves without a directory lookup, exactly as the REST `POST /api/groups/<group_id>/members` route already does. The acting user must still be the group's owner or an admin, which is checked again on the fresh group document.
- **Conversation invites.** `invite_group_conversation_members_for_current_user` first matches each identifier against the group's current owner and members, by user ID, email or display name, ignoring case. An identifier that matches no member, or more than one, falls back to the directory lookup as before. Only current group members can be invited to a group conversation, and that check is unchanged.

## Validation

`functional_tests/test_workflow_background_identity.py` runs the application's own definitions from source:

- A scheduled run's session carries the owner's stored name and email, and the owner's settings are never written.
- An owner with no stored profile keeps the bare identity, and an unavailable settings store falls back to it with a warning.
- A run inside the owner's signed-in request keeps that session. A run inside another member's request acts as the owner.
- A user ID with an email resolves with Graph unavailable.
- Group conversation invites by email, ID or display name reach the right members with Graph unavailable. An ambiguous or non-member identifier is still sent to the directory.

`functional_tests/test_simplechat_agent_group_output.py` checks that `add_user_to_group` passes `user_id` through to the group operation.

Without the fix, every new check fails. Restoring the old bare-ID session values alone fails the two identity checks, and removing the cross-user allowance fails the member-started run check.
