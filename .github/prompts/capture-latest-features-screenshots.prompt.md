---
name: "Capture Latest Features Screenshots"
description: "Use when replacing branded Screenshot pending placeholders in the in-app Latest Features cards with real captures from a running SimpleChat deployment, including PII blurring, caption reconciliation, and publishing the cards."
argument-hint: "Deployment URL, working branch, release id (e.g. release_260), optional subset of cards"
agent: "agent"
---

# Capture Latest Features Screenshots

`update-latest-features.prompt.md` creates Latest Features cards with placeholder
images and ships them hidden. This prompt is the sequel: replace those placeholders
with real captures and publish the cards.

Read `application/single_app/support_menu_config.py` before editing. Do not guess
its structure.

## Inputs To Gather

Ask only for what is missing:

- Deployment URL and whether a signed-in admin browser session already exists.
- Working branch. Never commit to `Development`; it is protected.
- Release id prefix, for example `release_260`.
- Whether admin settings may be **saved**, or must only be simulated. Default to
  simulate-only.
- Whether user-level data may be created (personal actions, agents, conversations).
- Any conversation or workspace whose content is unsuitable for public docs.

## Hard Constraints

- **Never save an admin setting** unless explicitly authorized. To photograph a
  pane that needs configuration, set the toggle and fill simulated values in the
  DOM, capture, then reload the page without saving. Verify afterwards that the
  values reverted.
- **Blur PII** before the image is written: profile blocks, conversation lists,
  personal scope names, real hostnames, storage account names, tenant names.
- **Never show a real secret.** If a value must be typed to make a feature work,
  read it inside the browser and assign it directly to the field so it never
  appears in the transcript.
- **No unsuitable content.** Scroll away from or avoid conversations containing
  political, personal, or customer material.
- Some features genuinely cannot be photographed. Do not fabricate a screenshot;
  see "Cards That Cannot Be Captured".

## Browser Setup

- Use the Playwright MCP browser. The VS Code integrated browser ignores
  `setViewportSize`.
- Capture at **1920x1080**. Confirm `window.innerWidth` before each capture; the
  window can drift.
- Inline screenshot previews are display-scaled. Trust the source size the tool
  prints, or check with Pillow.

## Processing Pipeline

Every capture must be processed, never copied by hand. Recreate the helper at
`artifacts/tmp/shotkit.py` if it is missing — `artifacts/tmp/` is gitignored, so
it does not survive between sessions.

```powershell
& .venv\Scripts\python.exe artifacts\tmp\shotkit.py `
  --src ".playwright-mcp\<capture>.png" --name <target_name> --boxes "x,y,w,h;..."
```

The helper must:

1. Refuse to run if no placeholder exists at the target path.
2. For each box, crop the region, downscale by 12 with `BILINEAR`, upscale back
   with `NEAREST`, then apply `GaussianBlur(radius=6)`. Downscale-then-upscale
   destroys text rather than softening it.
3. Resize the whole image to **1280x720** with `LANCZOS`.
4. Write to `application/single_app/static/images/features/<name>.png`.
5. Mirror to `docs/images/latest-release/<name>.png` **unless** the name starts
   with `admin_`.

Boxes are in the coordinate space of the source image, not the 1280x720 output.
Measure them live rather than assuming; layout shifts with font size and zoom.

For a PII string inside a paragraph, use a `Range` over the text node and
`getClientRects()` to get one box per wrapped line.

## Capture Techniques

These are proven against this app:

- **Font size**: `document.documentElement.setAttribute('data-font-size','l')`
  (`xs|s|m|l|xl`) changes the UI without saving. Use `l` for chat, `m` for dense
  modals — `l` makes wizard cards wrap badly.
- **Legibility**: `document.documentElement.style.zoom='1.45'` for small modals,
  reset with `=''`. Above ~1.5 the modal footer and floating controls fall off
  the viewport.
- **Scrolling**: `window.scrollTo` often does nothing. Find the real scroller by
  walking for `scrollHeight > clientHeight` — chat is `#chat-messages-container`,
  not `#chatbox`; modals scroll on `.modal.show` itself.
- **Form values**: set through the native setter, then dispatch `input` and
  `change`:
  `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,v)`
- **Showing all options of a `<select>`**: set `size`, plus
  `style.setProperty('height','auto','important')` and `background-image:none`.
- **Action wizard**: the type picker is paginated. Type into its search box to
  filter instead of hunting for a card on page 2.
- **Blocked clicks**: use `browser_evaluate` with `el.click()`.
- **Stray profile dropdown** covering the sidebar:
  `document.querySelector('.dropdown-menu.show')?.classList.remove('show')`.
- **Real focus rings**: `:focus-visible` only appears for genuine key presses.
  Focus a neighbour via JS, then press Tab or Shift+Tab.
- **Conversations**: `.conversation-item[data-conversation-id]`, which carries
  `data-conversation-title`. Wait ~4s after load.
- **Admin nav**: a two-level accordion of `.admin-nav-tab` links, all `href="#"`.
  Hash URLs do not work; click the tab, then scroll to the section id.

## Failure-State Screenshots

When a card needs a "this went wrong" image, prefer a failure the server
validates locally over one that requires a network timeout. Unreachable hosts can
hang for minutes behind long SSE read timeouts. A rejected endpoint format
returns instantly and names the specific problem, which is what the caption
usually promises anyway.

## Captions Must Match The Image

A caption that promises something the screenshot does not show is worse than a
shorter caption. When the reachable UI cannot produce the promised image, change
the caption rather than forcing the shot.

Captions live in **two hand-maintained places that must stay in sync**:

- `application/single_app/support_menu_config.py` — the `images=[...]` list.
- `docs/_data/latest_release_features.yml` — `title`, `caption`, `label`, `alt`,
  and `image_alt`. This file is **not generated**; edit it in parallel.

Also drop "screenshot placeholder" from `alt` text on galleries you finish, since
screen readers otherwise announce a real capture as a placeholder.

## Cards That Cannot Be Captured

If a card documents something with no photographable surface — an environment
variable, or controls that only appear once real records exist — do not ship a
placeholder. Pass `include_media=False` to `_latest_feature_card(...)`, delete the
orphaned placeholder files, remove the id from the image map in
`functional_tests/test_admin_latest_features_tab.py`, and add it to
`ADMIN_FEATURES_WITHOUT_SCREENSHOTS` so the omission stays deliberate.

If a gallery ends up with fewer usable images than slots, reduce the gallery and
renumber the files rather than repeating one image under two captions.

## Verifying Progress

Detect remaining placeholders by **file size**, not by unique colour count. A flat
real screenshot — a white card with black text — can have under 1000 colours and
will be misreported. Placeholders are roughly 19 KB; real captures are 50 KB and up.

```powershell
& .venv\Scripts\python.exe -c "import os; d=r'application/single_app/static/images/features'; [print(os.path.getsize(os.path.join(d,f)), f) for f in sorted(os.listdir(d)) if 'release_260_' in f]"
```

## Finish-Up

Only once every end-user image for the release is real:

1. Remove resolved entries from `docs/_data/media_pending.yml`. Leave a `note` on
   anything still outstanding explaining why it could not be captured.
2. Remove the default-hidden loop in
   `get_default_support_latest_features_visibility()` so the cards publish, and
   flip the matching assertion in `test_admin_latest_features_tab.py`.
3. Update `docs/explanation/features/v<version>/LATEST_FEATURES_RELEASE_*.md` if it
   still describes the placeholder rollout.
4. Bump `VERSION` in `application/single_app/config.py`. Screenshot-only passes do
   not need a bump; changing `support_menu_config.py` does.
5. Run:
   - `functional_tests/test_admin_latest_features_tab.py`
   - `functional_tests/test_latest_release_docs_structure.py`
   - `functional_tests/test_docs_app_surface_coverage.py`
6. Commit and push each batch as you go, then open the PR.

`test_docs_site_quality.py` fails on `docs/_site` unless a Jekyll build is
present. Confirm whether a failure reproduces on `Development` before treating it
as yours.

## Working Notes

- Run one command per terminal invocation. Multi-line PowerShell loops get
  mangled by the terminal wrapper and silently produce no output.
- Keep raw captures in `.playwright-mcp/`; only processed images belong in git.
- Report the mapping when a capture lands in a different slot than its filename
  suggests, so the reviewer can follow the reasoning.

## Output Expectations

Summarize at the end:

- Which images were captured, and any that were remapped or reframed.
- Which captions changed, and why the original could not be shown.
- What was blurred.
- Remaining placeholders and what each one needs.
- Test results, separating pre-existing failures from new ones.
