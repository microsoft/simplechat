# Public Directory APIs

## Overview

One native route lists the public workspace directory for the V2 directory page
and the V2 public workspace picker. It sits beside the classic
`GET /api/public_workspaces` and `GET /api/public_workspaces/discover`, which
are unchanged.

Implemented in version **0.261.175**.

## The route

| Method and path | Purpose |
| --- | --- |
| `GET /api/public_workspaces/directory` | One page of every public workspace the caller may discover, with the caller's role in each |

- **Access:** a signed-in user. The route is gated on `enable_public_workspaces`
  and answers GET only.
- **Why this path works beside the classic routes:** a static segment outranks
  the classic `/api/public_workspaces/<ws_id>` converter, so GET reaches this
  route. PATCH, PUT and DELETE still reach the classic workspace routes with the
  id `directory`, which answer 404, because no workspace has that id.
- Responses carry `Cache-Control: no-store`.

### Query

| Parameter | Values |
| --- | --- |
| `search` | Up to 200 characters. Matches the name or description ignoring case, or the exact id |
| `view` | `all` (the default) or `mine`: the workspaces where the caller is Owner, Admin or DocumentManager |
| `page` | A whole number from 1, at most 10000 |
| `page_size` | A whole number from 1 to 100 (default 20) |

Any other parameter, a malformed value, or a request body is refused with 400
`{"error": "The request could not be processed.", "error_code":
"invalid_request"}`.

### Response

```json
{
  "workspaces": [
    {"id": "...", "name": "...", "description": "...",
     "heroColor": "#...", "hasLogo": false, "logoVersion": 1,
     "userRole": "Owner" | "Admin" | "DocumentManager" | "User",
     "membership": "member" | "none",
     "status": "active" | "locked" | "upload_disabled" | "inactive" | "unknown"}
  ],
  "page": 1,
  "page_size": 20,
  "total_count": 42,
  "public_directory": {"schema_version": 1, ...}
}
```

- Rows are sorted by name, ignoring case, then by id.
- **No owner email or id, and no member lists.** The classic list route
  returns every owner's email to any signed-in user (decision 22). V2 no longer
  reads it.
- A status the server doesn't recognize is reported as `unknown`.
- Any other failure is logged with its error type only, under
  `[WORKSPACE_ROUTE]`, and answers 500 `{"error": "The public workspace
  directory request could not be completed. Try again.", "error_code":
  "public_directory_unavailable"}`, with no internal detail.

## Code

- `application/single_app/route_backend_public_directory.py`: the route.
- `application/single_app/functions_public_directory.py`: the query, the
  caller's role, the row projection, search, paging and the error answers.

## Testing

- `functional_tests/test_public_directory_apis.py` and
  `test_public_directory_transport.py`, through
  `test_support/public_directory_harness.py`.
- `functional_tests/test_public_directory_fixture_parity.py` holds the browser
  fixture to the route.
- The route policy tests list it under the `backend_public_directory`
  blueprint.

## Related

- [V2 Public Workspace Directory](V2_PUBLIC_DIRECTORY.md)
- [Group Directory APIs](GROUP_DIRECTORY_APIS.md)
