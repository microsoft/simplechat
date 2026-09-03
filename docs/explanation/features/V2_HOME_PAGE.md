# V2 Home Page

**Implemented in version: 0.261.047**

## Overview

The V2 React interface now opens on a home page at `/v2`, matching the classic
interface's landing page. It shows the application logo, the administrator's landing
copy, and a link into chat.

Before this, `/v2` redirected straight to the chat page. Three Appearance settings
therefore configured a page that did not exist in V2:

- **Landing Page Text** (`landing_page_text`)
- **Markdown Alignment** (`landing_page_alignment`)
- **Main Page Logo Size** (`landing_page_logo_scale_percent`)

Editing any of them changed the classic home page only, with nothing in the V2
interface to show for it.

## Dependencies

None beyond what the V2 interface already carries. The page renders from the
`branding` block of `/api/v2/bootstrap`, which is fetched once at startup, so
opening the home page costs no additional request. Markdown is rendered with the
already-vendored `react-markdown`.

## Architecture

### Data

`_build_branding` in `route_backend_v2.py` returns the landing fields alongside the
logo and title:

```json
{
  "landing_page_text": "...",
  "landing_page_alignment": "left",
  "landing_page_logo_scale_percent": 100
}
```

Both values are resolved server-side rather than in the browser:

- An unrecognised alignment falls back to `left`, and the logo scale is clamped to
  the range the Admin Settings slider offers, so a settings document edited outside
  the form cannot produce an unusable page.
- The landing copy is passed through as stored, apart from trimming. It is
  deliberately **not** defaulted when empty: `get_settings` merges the seeded
  default into every settings document, so blank copy means an administrator
  cleared it. Restoring default wording would put a statement back on the page —
  including an acceptable-use assertion — that they removed on purpose. The classic
  home page behaves the same way, rendering nothing.

### Rendering

`application/v2_ui/src/pages/HomePage.tsx` renders, in order:

1. The theme-appropriate logo, shown only when **Show Logo** is on and a custom logo
   has been uploaded.
2. The application title, unless **Hide Application Title** is on.
3. The landing copy.
4. A "Start chatting" link to `/v2/chat`.

Landing copy is rendered with `AdminMarkdown`, which is deliberately not the
assistant renderer: that one parses citations, applies masking ranges and hosts
diagram blocks, none of which apply to administrator prose. It also does not enable
`rehype-raw`, so administrator-authored markdown cannot inject script or event
handlers into the page.

The logo size deserves a note. **Main Page Logo Size** is stored as a percentage,
but the classic home page applies the number directly as a pixel height, so `100`
renders a 100px logo. V2 matches that rather than correcting it, because the slider
is calibrated against what an administrator already sees when they drag it.

Only the landing copy is aligned. The logo and the call to action stay centred in
both interfaces, so the alignment setting reads as a choice about the prose.

### Routing

| Route | Renders |
|---|---|
| `/v2` | Home |
| `/v2/chat` | Chat |
| anything unmatched | Redirects to `/v2` |

**Home** was added as the first entry in the navigation rail.

**New chat** is not shown on the home page. It is offered only on the chat page,
because it acts on chat state that is not on screen anywhere else; clicking
**Chats** from the home page starts a fresh chat instead. That behaviour arrived in
`0.261.044` and needed no change here — see
[V2_NEW_CHAT_BUTTON_SCOPING_FIX.md](../fixes/V2_NEW_CHAT_BUTTON_SCOPING_FIX.md).

## Navigation groups

The same change brought the two administrator-configured navigation groups into the
V2 rail, since neither had any representation there:

- **Custom Pages** — trusted pages deployed under `custom_pages`, already filtered
  per page against the caller's roles by `get_custom_pages_nav`.
- **External Links** — administrator-approved links, shown only to callers holding
  the `Admin` or `User` role, matching the gate in `_sidebar_nav.html`.

Each group carries its configured menu name and its "Force Menu Display" flag, and
the rail applies the classic rule: one or two entries render inline as ordinary nav
items, three or more collapse behind the menu name with a count. An administrator
can force the menu at any count.

External links always open in a new tab with `rel="noopener noreferrer"`; they leave
the application, and losing an in-progress conversation to a policy link would be a
poor trade. Custom pages honour their own `open_in_new_tab` metadata.

A link whose URL is not a local path or an `http`/`https` address is dropped before
it reaches the browser. Only the V2 settings PATCH applies that rule on write — the
server-rendered admin form stores any non-empty string — so a `javascript:` URL
already in a settings document would otherwise become an anchor in every user's
rail. The check is therefore applied on the way out as well as on the way in.

A group that is enabled but empty renders nothing rather than an empty heading.

In the collapsed rail there is no room for a heading, so entries stay flat as icons
rather than hiding behind a label nobody can read.

## Configuration

Everything is configured under **Admin Settings > Appearance**:

| Setting | Tab | Effect on the home page |
|---|---|---|
| Application Title | Branding | Heading, unless hidden |
| Hide Application Title | Branding | Hides the heading |
| Show Logo | Branding | Shows the logo |
| Custom Logo (Light/Dark Mode) | Branding | The image shown, per theme |
| Main Page Logo Size | Branding | Logo height in pixels |
| Landing Page Text | Home Page Text | The copy below the title |
| Markdown Alignment | Home Page Text | Alignment of that copy |

Custom Pages and External Links are configured under **Appearance > Pages & Links**.

## Testing and validation

- `functional_tests/test_v2_bootstrap_branding_and_navigation.py` executes the real
  `_build_branding` and `_build_navigation`, covering the landing defaults and
  bounds and the navigation group rules.
- `functional_tests/test_v2_navigation_groups_logic.mjs` executes the client's
  inline-versus-menu and visibility decisions.
- `ui_tests/test_v2_appearance_branding_and_nav.py` covers the rendered home page,
  the logo height, the "Start chatting" link, the Home rail entry and the two
  navigation groups, driven by what bootstrap reports for the deployment under test.

## Known limitations

- The access-denied and signed-out branches of the classic home page have no V2
  equivalent. They cannot be reached: `/v2` is behind `login_required` and
  `user_required`, so a caller who would see either never reaches the SPA.
- When **Show Logo** is on but no custom logo has been uploaded, the classic home
  page falls back to the bundled artwork. V2 shows no logo there and relies on the
  application title instead. See `docs/explanation/fixes/V2_APPEARANCE_PARITY_FIX.md`.
