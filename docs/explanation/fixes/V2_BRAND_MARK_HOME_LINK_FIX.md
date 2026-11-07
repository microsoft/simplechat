# V2 Brand Mark Home Link Fix

## Issue

The V2 navigation rail carried two controls for one destination and none for the one place
everybody clicks.

**Home** sat at the top of the navigation list as an ordinary entry — house icon, "Home"
label — directly beneath the brand area holding the application logo and title. Clicking
the logo did nothing at all, because it was not a link.

Separately, a deployment with no custom logo saw its application title twice. The brand
area fell back to an accent square holding the first letter of the title, and then rendered
the whole title next to it: **S** SimpleChat.

**Fixed in version:** 0.261.052

## Root cause

All three faults are in `application/v2_ui/src/components/layout/Sidebar.tsx`.

### The brand area was never a control

`BrandMark` rendered into a plain `<div>`:

```tsx
<div className="flex min-w-0 items-center gap-2.5">
```

Nothing in the V2 rail linked to `/`, so a **Home** navigation item was added alongside it
when the home page shipped in `0.261.047` rather than making the brand do the job. That
left the destination represented twice: once by a row that said so, and once by a logo that
looked like it should and did not.

### The letter square was gated on the wrong thing

The fallback and the title were decided independently:

```tsx
{branding?.show_logo && logoUrl ? <img .../> : <span>{title.slice(0, 1)}</span>}
{!collapsed && !branding?.hide_app_title && <span>{title}</span>}
```

The square was drawn whenever no logo was configured. The title was drawn whenever there
was room for it and it had not been hidden. Those two conditions are both true in the
default configuration — no custom logo, rail expanded, **Hide Application Title** off —
so the square and the word it abbreviates appeared side by side.

The square exists for the places the title cannot go: the 68px collapsed rail, and a
deployment that has deliberately hidden the title. Its condition should have followed the
title's, not the logo's.

## The fix

The **Home** navigation item is removed and `BrandMark` is now the link to `/`.

The letter square is gated on the title being absent rather than on the logo being absent,
which the component states as three derived flags rather than leaving it to be inferred
from nested conditionals:

```tsx
const logoUrl = branding?.show_logo ? themedLogoUrl : null;
const showTitle = !collapsed && !branding?.hide_app_title;
const showInitial = !logoUrl && !showTitle;
```

### What the brand mark draws

| Custom logo | Rail | Application title | Shows |
|---|---|---|---|
| yes | expanded | shown | logo and title |
| yes | expanded | hidden | logo |
| yes | collapsed | either | logo, capped at 44px wide |
| no | expanded | shown | the title alone |
| no | expanded | hidden | the letter square |
| no | collapsed | either | the letter square |

The fifth row is why the square is kept rather than deleted. With no logo, the title hidden
and the rail expanded, dropping it would leave the brand slot empty and the only home link
in the interface invisible and unclickable.

### Three details in the link

- **`end` is required.** `/` prefixes every other route, so without exact matching the link
  would claim `aria-current="page"` on every page in the application. This was the only
  reason the removed navigation item carried an `end` field, so that field comes off the
  `NavItem` interface with it.
- **The accessible name is the title followed by "home"**, not "Home". Collapsed, the link
  holds only a logo or a letter, both of which are decorative, so it has to name itself or
  it reaches a screen reader unlabelled. Naming it "Home" alone would put the accessible
  name at odds with the visible text when that text reads "SimpleChat", which is what
  WCAG 2.5.3 (Label in Name) is about, and would break speech input.
- **The logo `alt` is now empty.** The link names itself, so alt text would announce the
  application title a second time.

The brand area gains a hover background so it reads as clickable, inset with a negative
margin against its own padding so the logo and title stay on the same left alignment as
everything else in the rail. There is deliberately no active-page highlight: a brand mark
that leads home is a convention that does not usually carry one.

## Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/components/layout/Sidebar.tsx` | **Home** nav item, its `lucide-react` icon import and the `NavItem.end` field removed; `BrandMark` wrapped in a `NavLink to="/" end` that names itself; letter square gated on `showInitial` |
| `application/single_app/config.py` | Version to 0.261.052 |
| `functional_tests/test_v2_brand_mark_home_link.py` | New test |
| `ui_tests/test_v2_appearance_branding_and_nav.py` | Brand coverage extended to the home link and the letter square rule |

## Validation

`functional_tests/test_v2_brand_mark_home_link.py` — 4/4 checks passed. It asserts that
`NAV_ITEMS` carries no Home entry and no `/` route, that the `Home` icon import and the
`NavItem.end` field are gone, that `BrandMark` is a `NavLink to="/"` with `end` and an
accessible name built from the application title, that the logo is decorative, that the
hover affordance and its negative-margin inset are present, and that the letter square is
the element gated on `showInitial = !logoUrl && !showTitle`.

The same test was run against the pre-fix source and failed three of its four checks — the
fourth is the version assertion, which is not source-dependent — so each check covers a
real regression rather than restating the implementation.

Five neighbouring V2 test files that read `Sidebar.tsx` or the branding builders were
re-run and still pass: `test_v2_new_chat_scoping.py` (6/6),
`test_v2_conversation_deep_link.py` (8/8), `test_v2_stats_parity.py` (7/7),
`test_v2_conversation_drawer.py` (8/8) and
`test_v2_bootstrap_branding_and_navigation.py` (8/8).

`npm run typecheck` and `npm run build` both succeed. The compiled bundle contains
`to:"/",end:!0,"aria-label":\`${a} home\`` and `u=!l&&!c` for the letter square, and no
longer contains `label:"Home"`.

### Before and after

| Situation | Before | After |
|---|---|---|
| Clicking the logo or application title | Nothing; it was not a link | Opens the home page |
| Ways to reach `/v2` from the rail | Two — the brand that did not work and a **Home** row | One |
| No custom logo, rail expanded, title shown | **S** SimpleChat | SimpleChat |
| No custom logo, rail collapsed | **S** | Unchanged |
| No custom logo, title hidden | **S** | Unchanged |
| Custom logo configured | Logo, plus title when there is room | Unchanged |
| Screen reader on the collapsed rail | "Home, link", plus an unnamed brand image | "SimpleChat home, link" |
| `aria-current` on the brand link | n/a | Set on `/v2` only |

## Related

- Feature documentation: [REACT_V2_UI.md](../features/REACT_V2_UI.md),
  [V2_HOME_PAGE.md](../features/V2_HOME_PAGE.md)
- The change that introduced the **Home** nav item this replaces:
  [V2_APPEARANCE_PARITY_FIX.md](V2_APPEARANCE_PARITY_FIX.md)
