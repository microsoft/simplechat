# Admin Settings Navigation and Template Structure Fix

**Fixed in version:** 0.260.004
**Area:** Admin Settings information architecture
**Related plan:** Admin Settings IA redesign (14 groups / 42 tabs), first delivery stage

## Issues

### 1. Latest Features opened on every visit to Admin Settings

Latest Features is a curated release-notes tab, but it behaved like the landing
page. Three separate places forced this:

| Location | Behaviour |
|---|---|
| `templates/admin_settings.html` top-tab strip | First `<li>`, with `class="nav-link active"` |
| Latest Features tab pane | `class="tab-pane fade show active"` |
| `static/js/admin/admin_sidebar_nav.js` | Bootstrapped to `showAdminTab('latest-features')` |

Admins had to click away from it on every visit.

### 2. `admin_settings.html` was a 13,526-line, 1 MB single template

Every one of the 18 tab panes lived in one file. Editing a single card meant
navigating a file large enough to be slow to open and effectively impossible to
review in a diff.

### 3. Global Identities rendered as an unlabelled widget

The `workspace-identities` pane contained only a bare JavaScript mount point:
no heading, no description, and no intro copy, unlike every other tab.

### 4. File Sync had no sidebar submenu

File Sync is roughly 400 lines with 32 inputs and 17 toggles, but it was the
only tab with no sidebar destinations, so its sub-areas could not be reached or
found through the sidebar search.

### 5. The classification banner live preview never ran

The preview script sat between `{% endblock %}` and `{% block scripts %}` in a
child template. Jinja discards content outside blocks in a child template, so
the script was never rendered and the banner preview never updated as an admin
typed.

### 6. The sidebar `sectionMap` had rotted

`scrollToSection` resolves a sidebar target with
`sectionMap[sectionId] || sectionId`, so any entry mapping a key to itself is a
no-op. The map had grown to 72 entries:

- 66 were self-referencing no-ops
- 1 (`control-center-admin-section`) pointed at an element that does not exist
  anywhere in the template
- 2 were never referenced by any sidebar link

Every new section had been added twice, once in the sidebar and once in a map
that did not need it.

### 7. Home Page Text preview reinterpreted editor text as HTML

`showPreview` fell back to assigning the raw editor contents to `innerHTML`
when the Markdown editor had not initialized, despite the comment stating the
intent was to "just show raw text". CodeQL reported this as `js/xss-through-dom`
at high severity: DOM text read from a textarea and written back as HTML.

The Markdown branch also wrote rendered HTML to `innerHTML` without
sanitization, even though the same template already sanitizes the User
Agreement preview with DOMPurify.

## Root causes

Issues 1, 3, and 4 come from incremental growth: tabs were added over time
without a consistent structural contract, so newer surfaces skipped the heading
and sidebar conventions the older ones follow. Issue 2 is the accumulation of
that same growth in one file. Issue 5 is a Jinja block-scoping mistake that is
silent by design, since Jinja drops stray child-template content rather than
raising.

## Changes

### Template split

Each tab pane moved verbatim to `templates/admin/_panes/<pane>.html` and is
pulled back in with `{% include %}`. The parent template keeps:

- the single wrapping `<form id="admin-settings-form">`
- all modals
- the `{% block head %}` and `{% block scripts %}` blocks

Because the form boundary and every `name=` attribute are unchanged, the
submitted payload is identical and `route_frontend_admin_settings.py` needed no
changes. The parent dropped from 13,526 lines to about 2,200.

### Navigation

- Latest Features is last in the top-tab strip and in the sidebar, after Send
  Feedback, and is no longer the default active pane.
- General is the default landing tab in both the markup and the sidebar
  bootstrap.
- File Sync gained a sidebar submenu covering its source-type and
  per-workspace-type areas, which required adding `id` attributes to those
  areas. Existing `data-testid` hooks were left untouched.
- Global Identities gained a heading and description.
- The sidebar `sectionMap` was reduced from 72 entries to the 6 that are real
  aliases, removing the dead `control-center-admin-section` target. A new test
  fails if a no-op, dangling, or unreferenced entry is added back.
- The Home Page Text preview raw fallback now uses `textContent`, and its
  Markdown branch is sanitized with DOMPurify, following the pattern already
  used for the User Agreement preview in the same template. DOMPurify is served
  from the local `static/js/chat/purify.min.js` bundle, so no external asset is
  introduced.

### Test support

Functional tests that read `admin_settings.html` from disk would now see only
the parent shell. A shared helper, `functional_tests/test_support/templates.py`,
inlines Admin Settings partials and leaves every other repository file alone:

```python
from test_support.templates import read_admin_settings_template

template = read_admin_settings_template()
```

The helper deliberately expands only `admin/`-prefixed includes. Expanding
unrelated includes, such as the governance info modal, would pull in their own
tab markup and silently widen assertions that are meant to describe the Admin
Settings panes.

## Files modified

| File | Change |
|---|---|
| `application/single_app/config.py` | Version to 0.260.004 |
| `application/single_app/templates/admin_settings.html` | Split into partials, nav reordered, banner script moved into `{% block scripts %}` |
| `application/single_app/templates/admin/_panes/*.html` | 18 new pane partials |
| `application/single_app/templates/_sidebar_nav.html` | Latest Features moved last, File Sync submenu added |
| `application/single_app/static/js/admin/admin_sidebar_nav.js` | Default tab is General, not Latest Features; `sectionMap` pruned to real aliases |
| `functional_tests/test_support/templates.py` | New composed-template helpers |
| `functional_tests/test_admin_settings_template_composition.py` | New contract test |
| 40 functional test files | Read the composed template through the shared helper |

## Validation

**Non-breaking-change proof.** A fingerprint of every form field name and card
id was captured before the work and compared after each stage:

```
OK   field_names: 461 identical
OK   card_ids: 109 identical
OK   field_name_counts: 451 unique names, counts unchanged
```

The five names that appear more than once are legitimate radio and checkbox
groups (migration mode choices and `file_sync_visible_source_types`).

**Regression proof.** All 75 functional test files that reference
`admin_settings.html` were run against the pre-change baseline and after the
work:

| Stage | Failures |
|---|---|
| Baseline (`origin/Development`) | 32 |
| After template split | 32, identical set |
| After navigation change | 32, identical set |
| After Global Identities and File Sync fixes | 32, identical set |

The 32 failures are pre-existing and unrelated, covering workflow route
registration, Cosmos document-access wiring, and Send Feedback documentation.

**Template validation.** All 20 admin templates parse under Jinja.

## New contract test

`test_admin_settings_template_composition.py` pins the structure:

1. The parent delegates its panes to partials that exist on disk.
2. No partial is orphaned, which would silently drop settings from the page.
3. Composition restores the full card inventory.
4. No functional test references a partial-only card or form field while
   reading `admin_settings.html` uncomposed.

Check 4 is the important one. It caught ten tests that would otherwise have
asserted against an incomplete template, including three that were passing only
because the assertion happened to be satisfied by the parent shell.

## Follow-up

This is the first stage of the wider Admin Settings information architecture
work. Still outstanding:

- the group navigation level above tabs, and re-homing cards into 14 groups
- splitting `system-settings-section`, which mixes upload, chat, session, and
  access-control settings in one card
- a consolidated Security → Access and Roles view mirroring the ten
  `require_member_of_*` toggles that are currently spread across six tabs
- a legacy hash redirect map so old deep links resolve to their new tabs
