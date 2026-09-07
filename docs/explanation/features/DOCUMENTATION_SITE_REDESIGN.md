# Documentation Site Redesign

## Overview

The documentation site at <https://microsoft.github.io/simplechat/> was rebuilt to
fix search, navigation, page complexity, mobile support, and content coverage,
and to add a maintainable place for screenshots and videos.

**Implemented in version:** 0.250.230

## The problems this addressed

Every item below was measured against the live site or the `docs/` tree before
the work started.

### Search was unusable

| Measurement | Value |
| --- | --- |
| Entries in `search.json` | 986 |
| Entries that were internal engineering notes | 830 (84%) |
| Entries with an empty description | 867 (88%) |
| Entries carrying page body text | 0 |
| Entries titled with a raw filename | 37 |

Search matched a substring against page titles only. Because 594 bug-fix notes
and 236 versioned feature notes were published, a query for "agent" returned 83
mostly-internal results such as `ACR_BUILD_WORKFLOW_FOR_DEPLOYERS`.

Search was also entirely absent on phones: `main.scss` set
`.docs-topbar-search { display: none; }` and only revealed it at `min-width: 768px`.

### Pages were visually complex and had no on-page navigation

Landing pages were hand-written HTML card markup with **zero markdown headings**.

| Page | HTML blocks | Markdown headings |
| --- | --- | --- |
| `index.md` | 82 | 0 |
| `features.md` | 119 | 0 |
| `faqs.md` | 138 | 0 |
| `setup_instructions.md` | 101 | 0 |

The "On this page" table of contents and heading anchors are generated from
`.docs-prose h2[id]` elements, so these pages had neither.

### Navigation contradicted itself

A four-item top bar did not match the five sidebar groups. Navigation covered 27
URLs while roughly 130 published pages were unreachable from it, including every
`latest-release/` page. Internal theme documentation (`/README-THEME/` and
`/theme-documentation/`) was published publicly.

### The site did not work on phones

| Measurement | Value |
| --- | --- |
| Media queries in 1,947 lines of CSS | 8 |
| Breakpoint values, inconsistently mixed | `768px`, `767.98px`, `991.98px`, `575.98px` |
| `overflow-x` declarations | 1 |
| Table containment rules | 1 |
| Images with `loading="lazy"` | 0 of 210 (41.5 MB) |

`sidebar.js` also hardcoded `DESKTOP_BREAKPOINT = 992` separately from the CSS.

A pre-existing desktop bug compounded this: `.docs-main-content` combined
`width: 100%` with `margin-left: var(--sidebar-width)`, overflowing every desktop
viewport horizontally by exactly the sidebar width.

### Content coverage was incomplete

The application exposes 111 capability toggles, 18 admin settings tabs, 27 action
plugins, 47 chat controls, and 28 user-facing pages. The features page described
roughly a dozen capabilities, and there was no per-tab admin guidance, no action
reference, and no chat interface reference.

There was also no convention for screenshots beyond two folders wired into a
single layout, and videos were effectively unused (2 incidental references).

## What changed

### Search

- Engineering notes under `docs/explanation/features/` and
  `docs/explanation/fixes/` are excluded from the Jekyll build. They remain in
  the repository and readable on GitHub.
- `search.json` was replaced with `search-index.json`, which indexes page body
  text, headings, section, and audience, and guarantees a description for every
  entry.
- Search is powered by Lunr, vendored locally at
  `docs/assets/js/vendor/lunr-2.3.9/`.
- Added a `/search/` results page with section filters, result counts, and
  highlighted excerpts, plus a top bar typeahead, `Ctrl+K` and `/` shortcuts,
  arrow-key navigation, and a full-screen mobile search sheet.

| Search index | Before | After |
| --- | --- | --- |
| Entries | 986 | 165 |
| Engineering notes | 830 | 0 |
| Entries with no description | 867 | 0 |
| Entries with body text | 0 | all content pages |
| Filename titles | 37 | 0 |
| Reachable on mobile | No | Yes |

### Media placeholder system

`docs/_includes/media.html` renders a screenshot or video slot. When the asset
file does not exist it renders a visible card naming the exact path to create.
When someone adds the file at that path, the placeholder is replaced
automatically on the next build, with no YAML or code change.

- Images: `docs/images/<group>/<slug>.png`, lazy-loaded, intrinsically sized,
  click to enlarge.
- Videos: a local poster card that links out to YouTube or Microsoft Stream. No
  iframes and no committed MP4 files. A slot with no URL renders a "Video
  planned" state.
- `/contributing/media-status/` lists every registered slot and whether it is
  filled, as a capture worklist.
- Slots can be registered in `docs/_data/media.yml` for tracking, or used inline
  with `src`, `alt`, and `capture` for one-off images.

### Information architecture

Top bar and sidebar now expose the same six sections: Start, Guides, Features,
Administration, Deploy and operate, Reference. Navigation coverage went from 27
URLs to 67, all verified to resolve.

Path-scoped Jekyll defaults were fixed. They previously used collection names as
the `type`, so they never applied and every page fell back to a generic "Docs"
section, which is why search facets were meaningless.

### Responsive design

- One canonical breakpoint scale (`576 / 768 / 992 / 1200`), exported to
  JavaScript through the `--docs-breakpoint-lg` custom property so `sidebar.js`
  no longer hardcodes it.
- Tables and code blocks are contained in horizontal scroll regions.
- Card grids use `repeat(auto-fit, minmax(min(100%, 280px), 1fr))`.
- Minimum 44px tap targets, focus trap and focus restore on the mobile drawer
  and search sheet.
- Fixed the pre-existing desktop horizontal overflow.

### Local browser assets

Removed jQuery, DataTables, marked, DOMPurify, and split.js, none of which the
site used. Vendored Bootstrap 5.3.0, Bootstrap Icons 1.11.3, Prism 1.29.0, Lunr
2.3.9, and the Inter, JetBrains Mono, and Work Sans fonts under
`docs/assets/vendor/` with their licenses. The site now issues zero external
requests, satisfying `local_browser_assets.instructions.md`.

### Content

- 19 administration pages, one per admin settings tab, each covering what the tab
  controls, why it matters, every setting with its default and the governing
  `enable_*` key, prerequisites, real procedures with an outcome to verify, and
  screenshot and video placeholders.
- Task guides under `docs/guides/`, each opening with what the task does and why
  before the steps.
- A chat interface reference and an action reference.
- A data-driven feature catalog where every capability toggle is claimed by
  exactly one entry.
- The 452 KB release notes page was split into per-series pages while preserving
  the `/explanation/release_notes/` permalink the application links to.

## Keeping documentation current

This is the part designed to prevent the coverage from decaying again.

`scripts/build_docs_inventory.py` performs static analysis of the application and
writes `docs/_data/app_surface.yml`:

| Inventory | Source | Count |
| --- | --- | --- |
| `capabilities` | `functions_settings.py` | 111 |
| `admin_tabs` | `templates/admin_settings.html` | 18 |
| `actions` | `semantic_kernel_plugins/*.py` | 27 |
| `chat_controls` | `templates/chats.html` | 47 |
| `app_pages` | `templates/*.html` | 28 |
| `feature_surfaces` | `templates/_*.html` | 21 |

`functional_tests/test_docs_app_surface_coverage.py` then fails when any of those
is undocumented, and verifies the inventory itself is still in sync so a stale
inventory cannot hide a gap. Internal-only flags may be exempted, but each
exemption must carry a written justification and is itself checked for staleness.

The inventory deliberately does not record the application version. SimpleChat
bumps `VERSION` on every change, so embedding it would make the file differ on
every pull request and turn the sync check into noise.

## File structure

```
docs/
  _data/
    app_surface.yml        Generated application inventory
    features.yml           Feature catalog source of truth
    media.yml              Screenshot and video slot registry
  _includes/
    media.html             Auto-resolving media placeholder
  _layouts/
    feature.html           Feature detail page
  assets/
    css/docs-media.scss    Media and placeholder styling
    css/docs-search.scss   Search page and filter styling
    js/media.js            Screenshot lightbox
    js/search.js           Lunr-backed search
    js/vendor/lunr-2.3.9/  Vendored search library
    vendor/                Vendored Bootstrap, Bootstrap Icons, Prism, fonts
  admin/                   One page per admin settings tab
  guides/                  Task guides
  reference/actions/       Action reference
  search-index.json        Content-bearing search index
  search.md                Search results page
  contributing/media-status.md   Screenshot and video worklist

scripts/
  build_docs_inventory.py       Generates app_surface.yml
  generate_feature_pages.py     Generates feature collection stubs
  build_release_notes_pages.py  Splits release notes into series pages

functional_tests/
  test_docs_app_surface_coverage.py
  test_docs_site_quality.py

ui_tests/
  test_docs_site_responsive.js
```

## Testing and validation

`ui_tests/test_docs_site_responsive.js` drives the built site with Playwright at
360x640, 390x844, 768x1024, 1280x800, and 1920x1080, asserting no horizontal
overflow, reachable search and navigation at every size, working search
relevance, a functioning mobile search sheet, rendered media placeholders, and
zero external asset requests. All 100 checks pass.

`ui_tests/check_docs_links.js` walks the built site and verifies every internal
`href` and `src` resolves, resolving relative links against the containing page
rather than only checking absolute URLs. That distinction matters: page moves
break relative links, and a checker that only inspects absolute hrefs reports a
clean run while the site is quietly broken.

The site currently has **zero broken internal links across 31,650 checked**.
Sample-code pages under `custom_pages_examples/` are skipped, because they
reference application runtime paths such as `/custom/assets/...` and unrendered
template variables such as `{{ script_url }}` that only resolve when the sample
runs inside SimpleChat.

Run the suite locally with:

```powershell
cd docs
bundle exec jekyll build
cd _site; python -m http.server 4111    # serve so that /simplechat maps to the built site
node ..\..\ui_tests\test_docs_site_responsive.js
node ..\..\ui_tests\check_docs_links.js ..\..\docs\_site

python .\functional_tests\test_docs_app_surface_coverage.py
python .\functional_tests\test_docs_site_quality.py
```

## Known limitations

- Screenshot and video slots are scaffolded but the assets themselves still need
  to be captured. `/contributing/media-status/` tracks what is outstanding, and
  every unfilled slot renders a visible placeholder rather than failing silently.
- Action reference pages are written to full depth for the ten most-used actions;
  the remaining actions have shorter overview pages.
- A small number of internal capability flags are exempted from the coverage test
  with written justifications.
- Release highlight screenshots are duplicated between
  `application/single_app/static/images/features/` and
  `docs/images/latest-release/`. The application serves its own copy for the
  in-app Latest Features gallery, and GitHub Pages can only publish files inside
  `docs/`, so both copies are required. When a release screenshot is updated,
  update both.
