# V2 UI Live Data Shape Mismatches

## Issue

Two failures appeared the first time the V2 interface ran against a real deployment rather
than local mock data:

1. **The workspace page crashed to a blank screen** with `Minified React error #31:
   object with keys {color, count, name}`.
2. **Opening a conversation logged a 404** for
   `POST /api/conversations/{id}/mark-read`.

Fixed in version: **0.261.004**
Introduced in: 0.261.003

## Root cause

Both stem from the same underlying mistake: the V2 client was written against assumed
payload shapes rather than verified ones, and the local preview fixtures reproduced those
assumptions instead of what the API actually returns. The fixtures agreed with the client,
so the mismatch stayed invisible until real data arrived.

### 1. Workspace crash

`GET /api/documents/tags` returns tag **objects**, not strings.
`build_workspace_tags_from_counts` in `functions_documents.py` documents this directly:

```python
Returns: [{'name': 'tag1', 'count': 5, 'color': '#3b82f6'}, ...]
```

The tag filter chips rendered `{tag}` into JSX. React cannot render a plain object as a
child, so it threw error #31. Because nothing caught it, the error unmounted the entire
React tree and the whole page went blank rather than just the tag row.

### 2. mark-read 404

The conversation feed merges two sources, `legacy` and `collaboration`
(`functions_conversation_feed.py`). Collaboration conversations are stored in a different
container, so the personal endpoint's `read_item` raises `CosmosResourceNotFoundError` and
returns 404. They have their own endpoint,
`/api/collaboration/conversations/{id}/mark-read`.

The V2 client called mark-read unconditionally on every conversation open. The existing
interface does neither of those things: `chat-conversations.js` skips the call entirely
unless the conversation is actually flagged unread, and `chat-collaboration.js` uses the
collaboration endpoint.

### 3. Field names (found while fixing the above)

Reviewing the real payload surfaced two more mismatches that were silently wrong rather
than throwing. The pin indicator and unread dot simply never appeared:

| V2 client used | Server actually returns |
|---|---|
| `pinned` | `is_pinned` |
| `hidden` | `is_hidden` |
| `unread` | `has_unread_assistant_response` |

`/pin` and `/hide` were also being sent a desired state (`{pinned: true}`). Both endpoints
are server-side **toggles** that ignore the body and return the resulting value.

## Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/lib/types.ts` | Corrected `Conversation` field names; added `WorkspaceTag` |
| `application/v2_ui/src/lib/endpoints.ts` | Pin/hide as bodyless toggles; mark-read routes by conversation kind; tags typed as objects |
| `application/v2_ui/src/stores/chatStore.ts` | mark-read only when unread and routed correctly; toggles use the server's returned value |
| `application/v2_ui/src/components/chat/ConversationRail.tsx` | Uses `is_pinned` and `has_unread_assistant_response` |
| `application/v2_ui/src/pages/WorkspacePage.tsx` | `tagName()` normalizes string, object and comma-separated tag shapes |
| `application/v2_ui/src/components/ui/ErrorBoundary.tsx` | New — contains render failures to the content pane |
| `application/v2_ui/src/App.tsx` | Wraps routes in the error boundary, keyed on pathname |

## Defence in depth

Fixing the two symptoms is not enough on its own, because the same class of mistake can
recur anywhere the client meets an unverified payload. Two changes reduce the blast radius:

- **`tagName()` accepts any of the three shapes** a tag legitimately arrives in — object,
  string, or comma-separated string — rather than assuming one.
- **An error boundary wraps the routed content.** A render failure in one view now shows a
  contained message with the error text and a retry, and the navigation rail keeps working.
  Previously any such error blanked the application and left only a minified console trace.

## Validation

Preview fixtures were corrected to match the real API before the fixes were verified, so
the regression test genuinely reproduces the reported failures:

- `/api/documents/tags` returns `{name, count, color}` objects
- conversations use `is_pinned` / `has_unread_assistant_response`
- the personal mark-read endpoint 404s for a collaboration conversation
- `/pin` and `/hide` behave as toggles that ignore the request body

Browser-level results after the fix:

| Check | Result |
|---|---|
| Workspace renders, no React error #31 | Pass |
| No `[object Object]` in the UI | Pass |
| Tag filtering works with object tags | Pass |
| No mark-read for an already-read conversation | Pass |
| Collaboration conversation uses the collaboration endpoint | Pass |
| Personal conversation uses the personal endpoint | Pass |
| No 404 responses | Pass |
| Pin indicator renders | Pass |
| No console errors | Pass |

The existing V2 interaction suite (streaming, reasoning panel, rail collapse, theme
persistence, deep links) and the mid-stream conversation switch suite both still pass, as
do the V2 functional tests.

## Before and after

**Before:** opening the workspace blanked the app with a minified console error and no
in-app explanation. Opening any conversation logged a 404. Pin and unread indicators never
appeared even though the underlying operations worked.

**After:** the workspace renders with working tag filters and counts, mark-read is only
called when there is something to clear and goes to the right endpoint, and pin/unread
state displays correctly. A future render error is contained to the content pane instead of
taking down the interface.
