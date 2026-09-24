# Group Details Payload Disclosure Fix

Fixed in version: **0.261.143**

## Issue

`GET /api/groups/<group_id>` returns a group's details to its members. It used to
return the **stored group document itself** to every member, including members
with the ordinary User role. The document holds more than the group's details.
Among other things, it carried:

- **the group's model endpoints.** When Key Vault secret storage is off, their API
  keys, client secrets and bearer tokens are stored inline, so any member could
  read the credentials of every model connection the group's Owners and Admins
  configured. With Key Vault storage on, the Key Vault reference names and each
  connection's configuration were exposed. Neither is otherwise visible to
  ordinary members, and neither respects the custom-endpoint feature flag or
  governance.
- **pending join requests**, with each requester's name and email. The join
  request route shows these to Owners and Admins only.
- the member list, the status history, tag definitions, and the Cosmos system
  fields (`_rid`, `_self`, `_etag`, `_attachments`, `_ts`).

The public workspace details route already avoided this. It returns a projection,
fixed in version 0.241.020 (`PUBLIC_WORKSPACE_DETAILS_DISCLOSURE_FIX.md`). The
group route never received the same treatment.

## Root cause

The route copied the document (`dict(group_doc)`), added a few computed fields,
and removed only the logo image. Anything later added to the group document,
such as model endpoints, reached every member automatically.

## Technical details

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/route_backend_groups.py` | New `build_group_details_payload`, an allow-listed projection; `api_get_group_details` returns it |
| `functional_tests/test_group_details_payload_projection_fix.py` | New regression test |
| `functional_tests/test_group_manage_settings_tab_visibility.py` | Its source check follows the projection's form of `file_downloads_admin_enabled` |

### The projection

The response now contains only the fields the classic group management page
(`static/js/group/manage_group.js`) reads, plus the caller's role:

| Field | Who receives it |
| --- | --- |
| `id`, `name`, `description`, `status`, `createdDate`, `modifiedDate` | Every member |
| `owner` (`id`, `displayName`, `email`) | Every member |
| `admins`, `documentManagers` | Every member, as before. The page derives the caller's role from them |
| `heroColor`, `hasLogo`, `logoVersion` | Every member |
| `disable_file_downloads`, `file_downloads_admin_enabled`, `file_downloads_enabled` | Every member |
| `userRole` | Every member (new) |
| `retention_policy` | Owners and Admins, who manage it |

The route no longer returns model endpoints, pending join requests, the member
list, the status history, tag definitions or Cosmos system fields. Each of these
still has its own route with its own rules:

- model endpoints: `/api/group/model-endpoints` and
  `/api/groups/<group_id>/model-endpoints`, sanitized and feature-gated;
- join requests: `/api/groups/<group_id>/requests`, for Owners and Admins;
- members: `/api/groups/<group_id>/members`.

The V2 interface was not affected. It reads group details from its own
sanitized context route.

## Validation

`functional_tests/test_group_details_payload_projection_fix.py` loads the real
projection and branding helpers from their files. It uses a group document that
carries an inline endpoint secret, pending requests, members, status history, tag
definitions and system fields. It checks four things:

- an ordinary member's payload has exactly the allow-listed keys, and never
  contains the secret;
- Owners and Admins also receive the retention policy, and DocumentManagers
  don't;
- the route returns the projection, and never the stored document;
- every field `manage_group.js` reads from this response is still projected. This
  pin fails if the page starts reading a field the projection doesn't send.

Three of the four tests fail on the code before this fix. The page-contract test
passes on both, because it guards the other direction.

The related suites show identical failing IDs before and after the fix:

- group creation;
- group modals;
- branding;
- the chat bootstrap cache;
- the settings tabs;
- security hardening;
- download-settings visibility;
- route policy.

| Caller | Before | After |
| --- | --- | --- |
| Member (User) | The whole group document, including endpoint credentials when Key Vault is off | The projection, with no credentials, requests or system fields |
| Owner or Admin | The whole group document | The projection plus the retention policy |
| Non-member | 403 | 403 |
