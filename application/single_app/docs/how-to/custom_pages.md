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

## Role Behavior

Leave Allowed Roles blank to allow any signed-in user. Use role names such as `User` to restrict access. `Admin` satisfies `User` because `User` is the base application role. For any other role, every user, including admins, must have at least one exact matching role in their current SimpleChat session. A role name that does not exist in the app registration will not appear in user tokens, so it will deny access unless the role is otherwise present in the session.

## Troubleshooting

- If a static page does not appear in navigation, verify the metadata is enabled and `Show in Navigation` is on.
- If a static page returns `Not Found`, verify the slug, HTML file name, feature toggle, and App Service restart state.
- If CSS or JavaScript does not load, verify the file is listed in metadata and exists in the matching folder.
- If a Python-backed page does not appear, restart the App Service after deploying the Python file.
- If `/custom/<slug>` works but `/custom/<slug>.html` does not, restart the app to load the latest route registration.