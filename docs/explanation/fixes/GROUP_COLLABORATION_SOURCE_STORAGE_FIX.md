# Group Collaboration Source Storage Fix (v0.261.024)

Fixed in version: **0.261.024**

Related issue: [#1472](https://github.com/microsoft/simplechat/issues/1472).

The application patch version in `application\single_app\config.py` changes from
**0.261.023** to **0.261.024** for this Development/v1 fix.

## Issue

Adding the first participant to an existing group-scoped single-user conversation
could return `404 Conversation not found`, even while its owner could still open
the conversation and read its history.

V1 sends this invitation to the existing endpoint:

```text
POST /api/collaboration/conversations/from-group/<conversation_id>/members
```

The failure occurred during source lookup, before the selected invitee was
evaluated. It did not necessarily mean the conversation had been deleted.

## Root cause

Normal conversation creation writes to `conversations`, with history in
`messages`. Group knowledge or a group agent can later establish primary group
context and classify the same record as `group-single-user` without moving either
record set.

Group collaboration conversion assumed a different physical layout:
`group_conversations` and `group_messages`. The lookup, history copier, original
source update, and collaboration source links all followed that assumption.
Changing only the lookup would have left the copied history and later source
operations pointed at the wrong containers.

## Implementation

`ensure_group_collaboration_for_legacy_conversation()` now keeps the source
conversation container, existing message copier, and source-link field together
through conversion.

Legacy group storage remains authoritative. Only a
`CosmosResourceNotFoundError` from that lookup permits a regular-storage lookup.
Authorization failures, throttling, service failures, and other exceptions do not
trigger another-store retry. If both containers lack the record, the endpoint
still returns the existing 404.

| Original layout | History copier | Link on the collaborative conversation |
| --- | --- | --- |
| `conversations` / `messages` | `_copy_legacy_personal_messages_to_collaboration()` | `source_conversation_id` |
| `group_conversations` / `group_messages` | `_copy_legacy_group_messages_to_collaboration()` | `legacy_source_conversation_id`, with `legacy_source_scope = 'group'` |

Both paths create a group collaboration. Reusing the regular-storage copier does
not change the conversation's group access rules. It preserves the distinction
between group workspace context and `source_conversation_scope = 'group'` message
provenance, which specifically selects the legacy group message store.

Conversion preserves the existing title, context, tags, classification,
citation-tracking fields, strict mode, summary, and scope locks. The existing
copiers preserve supported message content and metadata, chronological ordering,
uploaded-content attribution, artifact filtering, and generated-image message
associations. Message counts and previews continue to derive from the copied
transcript.

The original is hidden and back-linked in its actual container. Cache
invalidation runs after the hidden source and completed collaboration have been
persisted, preventing cached conversation lists from retaining the pre-conversion
state.

### Source lifecycle

For a regular-stored original, the existing shared AI source helper reuses
`source_conversation_id` and its history instead of creating an empty backing
conversation. Repeat invitations still reuse the collaboration after that helper
updates the backing record's chat type and kind.

Legacy group originals retain their existing separate AI backing-source behavior.
The existing masking, deletion, archival, and retention helpers use the matching
source links and message provenance without new storage schemas or migrations.
Cleanup continues to enforce its source ownership and backward-link guards.

### Preserved restrictions and API contract

- Only the source conversation owner can convert an eligible group conversation.
- The owner must still hold a current allowed group role, and the group's status
  must allow chat. Existing chat permissions for active, locked, and
  upload-disabled groups remain unchanged; inactive groups remain rejected.
- Invitees must already be current group members. This flow does not add people
  to a group workspace or allow arbitrary directory users into the conversation.
- Rejected ownership, group, or invitee requests do not copy history or write
  conversion state.
- New conversions return 201 with `created: true`; subsequent invitations reuse
  the collaboration and return 200 with `created: false`. Response fields and
  creation/invitation events are unchanged.

## Files changed

- `application\single_app\functions_collaboration.py`: paired source selection,
  existing copier/link selection, original-container update, and final cache
  invalidation.
- `application\single_app\config.py`: application patch version.
- `functional_tests\test_group_collaboration_source_storage_fix.py`: isolated
  behavioral regressions using actual production helpers and the v1 route.
- `docs\explanation\features\GROUP_COLLABORATION_MEMBER_INVITE_FIX_PLAN.md`:
  distinguish this implemented backend fix from the historical UI proposals.

The route module, personal conversion implementation, and downstream cleanup
helpers are unchanged.

## Validation

The new regression first reproduced the exact 404 through the actual v1
conversion handler against a regular-stored group conversation before the
production fix.

Run the focused behavioral coverage with:

```powershell
python -m pytest -q .\functional_tests\test_group_collaboration_source_storage_fix.py
```

The regression executes the production conversion, participant normalization,
group role/status checks, source bridge, metadata synchronization, masking, and
cleanup helpers against partition-aware in-memory stores. Flask request-context
dispatch exercises the existing route without application startup, Azure clients,
or deployed services.

Coverage includes both layouts, all existing allowed group roles and chat
statuses, empty and populated histories, repeated invitations, current membership
revalidation, personal conversion compatibility, lookup priority, no-mutation
rejections, service-error responses, and manual/retention/archive cleanup that
leaves unrelated records untouched.

The new regression passes **18 tests and 106 subtests** under pytest. The combined
conversion, participant, image-proposal, shared-AI, retention, route-policy, and
documentation run completed with **60 tests and 106 subtests passing**, plus the
one pre-existing uploaded-image regression failure described below.

| Scenario | Before | After |
| --- | --- | --- |
| First group invitation for a regular-stored source | 404 before copying history | 201, with preserved transcript and a linked, hidden regular source |
| Legacy group-store conversion | Supported | Remains supported with its existing source conventions |
| Another invitation after conversion | Reuse required | 200, same collaboration, no transcript copy |
| Missing source in both stores | 404 | Same 404 |
| Non-not-found source storage error | Must surface as an error | No cross-store fallback or false success |

One related pre-existing regression,
`test_collaboration_legacy_message_conversion.py::test_uploaded_image_conversion_preserves_user_sender`,
already fails on the Development baseline: it expects the older uploaded-image
role/content representation rather than the model's current image representation.
That model and test are unchanged. The new conversion coverage checks preservation
of the current uploaded-image sender metadata, provenance, and associations.

## Scope and impact

Owners can share affected group-scoped conversations without moving stored data
or losing the original history. Existing group authorization and participant
restrictions remain in place.

This change is limited to the Development/v1 backend, regression coverage, and
documentation. It makes no React/v2 implementation or parity claim and includes no
UI wording changes, new routes/settings, deployment changes, or data migration.
The broader proposals in the
[historical group invitation plan](../features/GROUP_COLLABORATION_MEMBER_INVITE_FIX_PLAN.md)
are not represented as completed by this fix.
