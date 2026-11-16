# V2 Sidebar Navigation Links Fix (v0.261.290)

## Issue

Every primary link in the V2 left rail opened the classic interface instead of its V2
page. The affected links were Chats, Agents, My Workspace, Group Workspaces, Public
Workspaces, Approval requests and Content review. For example, clicking **My Workspace** on
`/v2/chat` did a full page load to `/workspace`, which is the classic workspace page. The
link's highlight in the rail also never matched the open page. Tracked in
[#1698](https://github.com/microsoft/simplechat/issues/1698).

Fixed in version: **0.261.290**, tracked in `application/single_app/config.py`.

## Root cause

`Sidebar.tsx` built each rail link with:

```tsx
to={safeSameOriginUrl(item.to, window.location.origin) ?? '/'}
```

`safeSameOriginUrl` in `lib/adminOperations.ts` returns a full URL, such as
`https://host/workspace`. It was written for the admin endpoint links, which really need a
full address. React Router's `Link` routes an absolute URL inside the application only when
its path is under the router's basename. The V2 basename is `/v2`, and `/workspace` is not
under it. React Router therefore treated each rail link as external. It rendered a plain
`<a href="https://host/workspace">` without its click handler, so the browser loaded the
classic Flask route at that path. `NavLink` also never marked the link as current.

Two parallel changes had each fixed an XSS sink check finding on the same line,
`to={item.to}`. One used a relative allowlist helper, `safeNavHref`, in #1687. The other
used `safeSameOriginUrl`. A later merge kept the second change. Both helper names match the
checker's approved `safe*Href` and `safe*Url` patterns, so CI passed. The Playwright test
that clicks **Chats** and waits for `/v2/chat` would have failed, but UI tests skip when no
deployment is configured.

The same name made this easy to get wrong. `safeSameOriginUrl` in `lib/apiClient.ts` returns
a relative path, while the `lib/adminOperations.ts` function of the same name returns a full
URL.

## Technical details

### Files modified

- `application/v2_ui/src/components/layout/Sidebar.tsx`: brings back `safeNavHref(value)`.
  It returns the path unchanged when the path is one of the rail's own `NAV_ITEMS`
  destinations, and `/chat` otherwise. The links now use `to={safeNavHref(item.to)}`, so
  they stay relative to `/v2` and still pass the XSS sink check. The unused
  `lib/adminOperations` import is removed.
- `application/single_app/config.py`: version `0.261.290`.

Custom Pages, External Links, Latest Features and **Back to classic UI** are deliberately
plain anchors to server-rendered or third-party pages, and they are unchanged. The
workspace section rail is also unchanged. It already passes its links through
`normalizeWorkspaceUrl`, which returns only a pathname.

### Tests

`functional_tests/test_v2_sidebar_primary_nav_stays_in_v2.py` has 5 cases. It checks that:

- every rail destination is a root-relative path with a matching route in `App.tsx`;
- the rail's `NavLink` uses `safeNavHref(item.to)`, does not use the page origin, and does
  not import from `lib/adminOperations`;
- `safeNavHref` returns the allowlisted path unchanged and never builds a URL;
- no `to=` prop in any V2 `.tsx` file is built from `location.origin` or
  `safeSameOriginUrl`. The only exception is `normalizeWorkspaceUrl`, and the test confirms
  it still returns only `target.pathname`;
- the application version is at least `0.261.290`.

Three of the five cases fail against the code before the fix.

`ui_tests/test_v2_sidebar_primary_nav_links.py` has 7 cases, one per rail link. Starting
from the V2 home page, each case checks three things after clicking the link:

- The link's `href` is `/v2/<route>`.
- The page stays in the single-page application. A marker set on `window` survives, which a
  document load would wipe.
- The address lands on the V2 route and the link gets `aria-current="page"`.

All seven fail before the fix. Like the other V2 UI tests, it needs `SIMPLECHAT_UI_BASE_URL`
and an authenticated storage state.

## Impact

V2 users can move around the interface from the rail again without being sent to the
classic interface. The open page is highlighted in the rail again.

## Validation

- Before: each rail link's `href` was a full URL outside `/v2`, such as
  `http://127.0.0.1:5174/workspace`. Clicking it reloaded the document at the classic path,
  and no link was marked current.
- After: each `href` is `/v2/<route>`. Clicking a link routes inside the SPA without a
  reload, from both the home page and the chat page, and highlights the link. Approval
  requests then settles on its default category, `/v2/approvals/all`.
- To check this locally, the Vite dev server ran against a stub `/api/v2/bootstrap`. The UI
  test passed 7 of 7 with the fix and failed 7 of 7 with the previous `Sidebar.tsx`.

## Related

- [V2 Terms of Use and Approval Requests](../features/V2_TERMS_AND_APPROVALS.md)
- [Workspace Notification Links Fix](WORKSPACE_NOTIFICATION_LINKS_FIX.md)
