---
applyTo: '**'
---

# Documentation Coverage

## Why this exists

The documentation site is kept in sync with the application by a generated
inventory plus tests. Before this was in place, coverage decayed silently: the
app had 111 capability toggles, 18 admin settings tabs, 27 action plugins, and
47 chat controls while the docs described roughly a dozen capabilities and had
no per-tab, per-action, or per-control reference at all.

## The rule

When a change adds or renames any of the following, the same change must update
the documentation:

| You added or renamed | Document it in |
|---|---|
| An `enable_*` settings key | The relevant `docs/admin/<tab>.md` settings table, and claim the key in `docs/_data/features.yml` |
| An admin settings tab | A new `docs/admin/<tab-id>.md` page |
| A Semantic Kernel action plugin | A new `docs/reference/actions/<slug>.md` page |
| A chat UI control | `docs/reference/chat-controls.md` |
| A user-facing app page or major surface | A guide under `docs/guides/` |

## Regenerating the inventory

The application surface inventory is generated, not hand-written:

```powershell
python .\scripts\build_docs_inventory.py
```

This writes `docs/_data/app_surface.yml`. Commit the regenerated file with your
change. The inventory deliberately does not record the application version, so
it only changes when the application surface actually changes.

## Verifying

```powershell
python .\functional_tests\test_docs_app_surface_coverage.py
python .\functional_tests\test_docs_site_quality.py
```

The coverage test fails when any inventory item is undocumented, and when the
committed inventory is stale relative to the application.

## Internal-only flags

A settings key that has no admin-facing UI and is purely an internal rollout,
telemetry, or tuning switch may be exempted. Add it to `CAPABILITY_EXEMPTIONS`
in `functional_tests/test_docs_app_surface_coverage.py` **with a written
justification**. Exemptions are themselves checked for staleness, so a flag that
is later removed from the application will fail the test until the exemption is
deleted.

Do not use an exemption to avoid writing documentation for a user-facing
capability.

## Screenshots and videos

Documentation pages declare media slots that render a visible placeholder card
until the asset exists. To add a screenshot, save the file at the exact path the
placeholder names, for example `docs/images/admin/general-tab.png`. No YAML or
code change is required.

Videos are never committed to the repository. Upload the recording to YouTube or
Microsoft Stream, save a poster frame under `docs/images/video-posters/`, and add
the watch URL to the slot in `docs/_data/media.yml`.

Outstanding media is listed at `/contributing/media-status/`. Missing media does
not fail the build, so it never blocks a change, but it stays visible.

## Writing quality

Documentation pages must explain **what a capability does and why someone would
use it**, not restate control names.

Do not write:

- "Turns X on or off" or "Sets X" as a description.
- The same boilerplate paragraph across multiple sections or pages.
- Procedures that only describe using a form, such as "Open the page, change the
  fields, save".
- Prerequisites that would apply to any page.

Never invent a setting, default, field, or behavior. A shorter accurate page is
better than a longer speculative one.

## Page structure

Write plain markdown with real `##` and `###` headings. The site generates its
"On this page" table of contents and heading anchors from rendered `h2`/`h3`
elements, so pages authored as HTML card markup get neither. Do not add
`<section>`, `<div>`, or card/badge markup to documentation pages.

## Browser assets

The documentation site loads no third-party assets. Everything is vendored under
`docs/assets/vendor/` and pinned by version. Do not add a CDN `<script>`,
`<link>`, `@import`, or webfont URL to any docs layout, include, stylesheet, or
page. See `local_browser_assets.instructions.md`.
