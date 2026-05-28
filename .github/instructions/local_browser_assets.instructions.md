---
applyTo: '**/*.html, **/*.js, **/*.css, **/*.py'
---

# Local Browser Runtime Assets

## Critical Requirement

Never load browser runtime JavaScript from the public Internet. If SimpleChat uses a JavaScript library, framework, worker script, module, import map, or plugin runtime in the browser, keep a pinned local copy in the repository and serve it from the SimpleChat app.

This rule also applies to browser companion assets that are required by JavaScript libraries, including CSS, fonts, source maps, worker files, WebAssembly files, dictionaries, and library-managed fallback downloads.

## Required Pattern

- Store third-party browser assets under an appropriate local static path, such as `application/single_app/static/js/<vendor>/` or `application/single_app/static/css/<vendor>/`.
- Reference browser assets with local static paths, preferably through `url_for('static', filename='...')` in templates.
- Pin the library version in the filename, folder name, documentation, or related test when the upstream asset is copied locally.
- Preserve required third-party license or attribution files when vendoring assets.
- Disable library options that auto-download extra browser assets unless those extra assets are also available locally.
- Keep Content Security Policy `script-src` and `style-src` aligned with local assets; do not loosen CSP to allow a CDN for browser runtime code.

## Disallowed Patterns

Do not add runtime browser references to:

- CDN-hosted scripts or modules, such as `cdn.jsdelivr.net`, `unpkg.com`, `cdnjs.cloudflare.com`, `esm.sh`, `skypack.dev`, `code.jquery.com`, or `stackpath.bootstrapcdn.com`.
- Remote CSS for JavaScript-driven widgets when a local copy is expected.
- Library defaults that inject remote `<script>` or `<link>` tags.
- Dynamic imports from public Internet URLs.
- Worker, source map, WASM, dictionary, font, or plugin URLs hosted outside the SimpleChat app.

## Validation Checklist

When adding or changing browser assets:

1. Search templates, static JavaScript, static CSS, and relevant Python-rendered frontend routes for new external asset URLs.
2. Confirm all browser JavaScript dependencies are served from `/static/...` or `url_for('static', ...)`.
3. Add or update a regression test when fixing an external asset dependency.
4. Run a syntax check for changed JavaScript files, such as `node --check <file>`.
5. Run `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check` before finishing.

## Allowed Network Calls

This rule does not prohibit authenticated API calls, application data fetches, server-side Azure service calls, proxied map tile requests, user-requested links, or documentation-only examples. It specifically prohibits loading browser runtime code and required companion assets from public Internet CDNs.