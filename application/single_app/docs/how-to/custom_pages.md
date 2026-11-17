# Create Custom Pages

Custom Pages let deployment teams add trusted pages under `/custom` without editing the core SimpleChat route table. Use this guide for the built-in Request Access page and the three supported patterns: simple HTML, static HTML/CSS/JS, and Python-backed Jinja/API pages.

Custom Pages are trusted deployment-time content. They are not runtime user uploads. Static page metadata is stored in the `custom_pages` Cosmos container, while files live in the deployed artifact under `application/single_app/custom_pages/`.

## Before You Start

1. Deploy files under `application/single_app/custom_pages/` in the matching folders: `html`, `css`, `js`, `assets`, `json`, and `python`.
2. Enable Custom Pages in Admin Settings > Custom Pages.
3. Acknowledge the restart requirement when enabling the feature from a disabled state.
4. Restart the App Service or local Flask process after deploying new files or Python-backed pages.

The canonical route format is `/custom/<slug>`. Static-looking aliases such as `/custom/<slug>.html` are also supported.

## Built-In Request Access Page

SimpleChat includes a practical static page that helps signed-in users request the base `User` role. It is not automatically inserted into Cosmos DB. Admins can instantiate it from Admin Settings > Custom Pages by selecting **Add Request Access Page**.

The one-click action creates static page metadata and enables the access-denied button on the home page for signed-in users who do not yet have an app role.

Request Access metadata:

| Field | Value |
| --- | --- |
| Slug | `request-access` |
| Title | `Request SimpleChat Access` |
| Description | `A signed-in access request page for users who need the base User role.` |
| Navigation Label | `Request Access` |
| Bootstrap Icon | `bi-person-plus` |
| Order | `5` |
| Access Level | `Any signed-in user` |
| Allowed Roles | leave blank |
| HTML File | `request-access.html` |
| CSS Files | add `request-access.css` |
| JavaScript Files | no files |
| Asset Files | no files |
| JSON Files | no files |
| Enabled | on |
| Show in Navigation | off |
| Open in New Tab | off |

The page opens the user's email client with:

- To: `accessrequest@example.com`
- Subject: `SimpleChat Access Request`
- Body: `Please grant me the user role in simplechat so that I may start using this wonderful tool`

## Access Levels

Static page metadata has an Access Level field:

- `App users only`: requires the signed-in user to have `User` or `Admin` before page-specific roles are checked.
- `Any signed-in user`: requires login, but does not require the base app role before page-specific roles are checked.

Use `Any signed-in user` sparingly. It is intended for bootstrap flows like Request Access. Most custom pages should stay `App users only`.

## Pattern 1: Simple HTML Page

Use this when the page only needs trusted HTML and Bootstrap classes already available from the SimpleChat shell.

Place the HTML fragment in `application/single_app/custom_pages/html/`.

Example file: `example-simple.html`

Sample source: `docs/how-to/custom_pages_examples/simple-html/example-simple.html`

Metadata editor values:

| Field | Value |
| --- | --- |
| Slug | `example-simple` |
| Title | `Simple HTML Example` |
| Description | `A minimal custom page loaded from a trusted HTML fragment.` |
| Navigation Label | `Simple HTML` |
| Bootstrap Icon | `bi-file-earmark-text` |
| Order | `10` |
| Allowed Roles | leave blank for all signed-in users, or use a role such as `User` |
| HTML File | `example-simple.html` |
| CSS Files | no files |
| JavaScript Files | no files |
| Asset Files | no files |
| JSON Files | no files |
| Enabled | on |
| Show in Navigation | on |
| Open in New Tab | off |

After saving metadata, test `/custom/example-simple` and `/custom/example-simple.html`.

## Pattern 2: Static HTML, CSS, and JavaScript Page

Use this when a static page needs page-specific styling or client-side behavior.

Place files in these folders:

- HTML in `application/single_app/custom_pages/html/`
- CSS in `application/single_app/custom_pages/css/`
- JavaScript modules in `application/single_app/custom_pages/js/`
- Images and other static files in `application/single_app/custom_pages/assets/`
- JSON data in `application/single_app/custom_pages/json/`

Example files:

- `html/example-static.html`
- `css/example-static.css`
- `js/example-static.js`
- `assets/cat.mp4`

Sample source folder: `docs/how-to/custom_pages_examples/static-html-css-js/`

Metadata editor values:

| Field | Value |
| --- | --- |
| Slug | `example-static` |
| Title | `Static HTML with CSS/JS Example` |
| Description | `A custom static page with deployed HTML, CSS, and JavaScript.` |
| Navigation Label | `Static Example` |
| Bootstrap Icon | `bi-window` |
| Order | `20` |
| Allowed Roles | leave blank for all signed-in users, or use a role such as `User` |
| HTML File | `example-static.html` |
| CSS Files | add `example-static.css` |
| JavaScript Files | add `example-static.js` |
| Asset Files | add `cat.mp4` |
| JSON Files | add only JSON or CSV files the page must fetch through `/custom/assets/...` |
| Enabled | on |
| Show in Navigation | on |
| Open in New Tab | off |

The metadata designer stores CSS, JavaScript, asset, and JSON references as arrays. Add one file at a time in the modal so the page only serves files explicitly declared by metadata.

## Pattern 3: Python-Backed Jinja Page with Backend API

Use this when the page needs server-side rendering, access to request context, or a custom backend operation.

Place the Python extension in `application/single_app/custom_pages/python/`. The extension must subclass `CustomPageExtension` and provide metadata with a unique `slug`. It can render a template from `custom_pages/html/` and handle API operations through `/api/custom/<slug>/<operation>`.

Example files:

- `python/example_python_dashboard.py`
- `html/example-python-dashboard.html`
- `css/example-python-dashboard.css`
- `js/example-python-dashboard.js`

Sample source folder: `docs/how-to/custom_pages_examples/python-jinja-api/`

Do not create Python-backed pages in the metadata editor. Python-backed pages are discovered from code at app startup. Restart the App Service after deploying or changing Python-backed page files.

The example page appears at `/custom/example-python-dashboard`, and its sample API endpoint is `/api/custom/example-python-dashboard/status`.

### Showing a Python-backed page in V2

A Python-backed page owns its entire response, so V2 cannot assume it renders without the classic navigation. By default V2 therefore does not frame it and offers **Open in a new tab** instead. To have V2 show the page in its own content area, the extension opts in:

```python
class ExamplePythonDashboard(CustomPageExtension):
    supports_embed = True

    def render(self, context):
        ...
        return render_template_string(
            template_source,
            embed=context["embed"],
            ...
        )
```

`context["embed"]` is `True` when V2 asks for the chrome-less copy (`/custom/<slug>?embed=1`) and `False` otherwise. It is never `True` for an extension that did not set `supports_embed = True`. When it is `True`, return a page without the classic navigation. The simplest way is a template that extends the embed base for V2 and the classic base for everything else:

```jinja
{% extends "custom_page_embed_base.html" if embed else "base.html" %}
```

`custom_page_embed_base.html` offers the same blocks as `base.html`: `title`, `head`, `content`, and `scripts`. It also offers `page_title`, the title shown in the slim bar when the page is opened on its own. The example in `docs/how-to/custom_pages_examples/python-jinja-api/` opts in this way. Open `/v2/custom/<slug>` after deploying a change, because an extension that sets the flag but still renders the classic navigation would draw it inside V2.

## Custom Pages in the V2 Interface

Available from version 0.261.445.

SimpleChat has the classic interface and the V2 interface under `/v2`. Custom Pages are server-rendered pages, so they are not rebuilt in V2. V2 shows each one inside its own content area instead, with its navigation rail still on screen. Choosing **Handbook** in the V2 rail opens `/v2/custom/handbook`, and the page itself is still served from `/custom/handbook`. The classic interface is unchanged.

### What V2 shows

V2 loads a chrome-less copy of the page from `/custom/<slug>?embed=1` into a same-origin frame. Only the exact value `embed=1` asks for it.

The chrome-less copy is a standalone document with:

- your page HTML, in the same trusted position it has in the classic shell
- the CSS files declared in the metadata, in the declared order, and the JavaScript modules declared in the metadata
- the Bootstrap 5 stylesheet and script bundle, Bootstrap Icons, jQuery, and `window.showToast(message, variant)`, all served from `/static`

It has no classic navigation, top bar, sidebar, notification polling, idle warning, or title banner. The V2 page header shows the navigation label, so a title inside the frame would repeat it. It also does not load the classic application stylesheet or the other classic scripts, and it does not define `window.appSettings` or `window.userContext`. A page that needs data should fetch it from its own API. A page that depends on more of the classic shell can be set to **Open in New Tab**.

The V2 page header has an **Open in a new tab** action. It opens `/custom/<slug>?embed=1` on its own, so you see the same chrome-less document without the V2 frame around it, with a slim bar that links back. It does not open `/custom/<slug>`, because once the modern interface is in use the server sends that address back to `/v2/custom/<slug>` for a page V2 can show.

### Theme

The frame follows the V2 theme. It reads `simplechat.v2.theme` and then `simplechat-theme` from local storage before it first paints, and V2 sends it a message when the reader switches theme. Style with Bootstrap's CSS variables, such as `var(--bs-body-bg)`, or with `[data-bs-theme="dark"]` selectors. Script that must react to a change can watch the `data-bs-theme` attribute on the `<html>` element. The frame accepts the theme message only from its parent window and its own origin.

### Which pages open in V2

V2 lists only the pages the signed-in user can open. The server filters them by the Enabled setting, access level, and allowed roles, and still answers 403 or 404 for the address itself.

| Page | In the V2 rail and at `/v2/custom/<slug>` |
| --- | --- |
| Static page | Opens in V2 |
| Python-backed page that sets `supports_embed = True` | Opens in V2 |
| Python-backed page that does not | Rail link opens the classic page. `/v2/custom/<slug>` explains that the page opens in a new tab. |
| Page with **Open in New Tab** on | Rail link opens the classic page in a new tab. `/v2/custom/<slug>` explains that the page opens in a new tab. |
| Slug that is not in the user's list, including a page with **Show in Navigation** off | "Page not available". A page that is hidden from navigation is still reachable at its classic address, `/custom/<slug>`. |

If the frame cannot show the page, V2 keeps it hidden and shows "This page could not be loaded" with **Try again** and **Open in a new tab**. That covers a 403, a 404, a server error, and an expired session. The browser fires the frame's load event for those responses too, so V2 waits for the page to report that it rendered. The chrome-less document does this by itself, so pages need no code for it. **Open in a new tab** opens `/custom/<slug>?embed=1` on its own, so you see the page's real response instead of the frame's hidden one.

### Pages for people without the app role

V2 requires the `User` or `Admin` role, so someone who is signed in without it, such as a visitor to the Request Access page, cannot open `/v2`. When the modern interface is in use, a page with access level **Any signed-in user** is therefore served at `/custom/<slug>` as a full chrome-less page, with a slim bar that links back. The link goes to V2 for someone with the app role and to the home page for someone without it. In the classic interface these pages are unchanged.

### Links, popups, and the frame

- A link inside the page that names a classic page, such as `/chats`, loads that page inside the frame. Give links that should leave the page `target="_blank"`.
- The frame is sandboxed so that a page cannot replace the whole application: it allows scripts, same-origin access, forms, popups, downloads, and dialogs, and withholds top-level navigation, so a link with `target="_top"` does nothing. The sandbox is a guard rail rather than a boundary. Pages are trusted deployment code that runs with the user's session, and a page that can run scripts with same-origin access can lift a sandbox from the inside.
- Only the chrome-less document can be framed, and only by SimpleChat itself. The server relaxes `X-Frame-Options` from `DENY` to `SAMEORIGIN` for that one response, and the `Content-Security-Policy` frame-ancestors rule is unchanged. Deployments that enable Teams SSO send no `X-Frame-Options` and are not affected.
- V2 and the server must share an origin. When the V2 interface is hosted separately from the server, pages open in a new tab instead of in a frame.

## Role Behavior

Leave Allowed Roles blank to allow any signed-in user. Use role names such as `User` to restrict access. `Admin` satisfies `User` because `User` is the base application role. For any other role, every user, including admins, must have at least one exact matching role in their current SimpleChat session. A role name that does not exist in the app registration will not appear in user tokens, so it will deny access unless the role is otherwise present in the session.

## Troubleshooting

- If a static page does not appear in navigation, verify the metadata is enabled and `Show in Navigation` is on.
- If a static page returns `Not Found`, verify the slug, HTML file name, feature toggle, and App Service restart state.
- If CSS or JavaScript does not load, verify the file is listed in metadata and exists in the matching folder.
- If a Python-backed page does not appear, restart the App Service after deploying the Python file.
- If `/custom/<slug>` works but `/custom/<slug>.html` does not, restart the app to load the latest route registration.
- If V2 shows "This page could not be loaded", choose **Open in a new tab** on the message, which opens `/custom/<slug>?embed=1` on its own. A 403 means the access level or allowed roles do not match the user, a 404 means the page is disabled or Custom Pages is off, and a sign-in page means the session has expired.
- If V2 says a page opens in a new tab and it is Python-backed, set `supports_embed = True` on the extension and render without the classic navigation when `context["embed"]` is `True`.
- If a page works in the classic interface but a script fails in V2, check whether it relies on a classic global such as `window.appSettings`. The chrome-less document provides Bootstrap, Bootstrap Icons, jQuery, and `window.showToast`, and nothing else from the classic shell.