# V2 Custom Color Schemes and Theme Cards

## Overview

Administrators can set the colors the modern (V2) interface uses in light mode and dark mode. Users can also build a custom color mode of their own, unless an administrator turns that off (it is on by default). A custom color mode can be shared as a **Theme Card**: a PNG image with the mode's name, a stripe of its colors and a colored QR code. Dropping the card into SimpleChat on any site imports the same colors.

- **Version:** 0.261.452
- **Sidebar cycle enhancement implemented in version: 0.261.459** (`application/single_app/config.py`).
- **Scope:** V2 interface only. Classic interface colors are unchanged, but its shared `darkModeEnabled` preference stays in step with the base the user's mode resolves to.
- **Dependencies:**
  - Pinned npm packages `qrcode-generator@1.4.4` (draws the QR code) and `jsqr@1.4.0` (reads it back).
  - No new Python dependencies.
- **Design:** Option A, a color table with a live preview. Screenshots are in `docs/mockups/color_customization/v2/`.

## Technical Specifications

### Palette

Every scheme and mode is a palette of exactly eleven colors, each a plain `#RRGGBB` value:

| Token | Used for |
|-------|----------|
| `accent` | Buttons, links, your messages, focus ring |
| `onAccent` | Labels on accent buttons |
| `backdrop` | Page background |
| `panel` | Cards, sidebar, composer, dialogs |
| `border` | Lines between areas |
| `text1` / `text2` | Primary and secondary text |
| `ok` / `warn` / `danger` / `info` | Status colors |

The rest of the V2 design tokens in `theme.css` are derived from these eleven in `colorScheme.ts` (`paletteDeclarations`): hover shades, translucent glass surfaces, soft status fills and backdrop tints. Keeping the set small means the server can validate everything a person sets.

### Settings

| Setting | Where | Default | Meaning |
|---------|-------|---------|---------|
| `v2_color_scheme` | Admin | `null` | `null` keeps the SimpleChat default palette; otherwise `{light: Palette, dark: Palette}` |
| `allow_user_custom_color_modes` | Admin | `true` | Users may pick **Custom** and save their own palette |
| `allow_user_theme_cards` | Admin | `true` | Users may share and import Theme Cards |
| `require_readable_custom_colors` | Admin | `true` | A custom mode whose text is below 4.5:1 cannot be saved |
| `v2ColorMode` | User | — | `light`, `dark`, `system` or `custom` |
| `v2CustomColorMode` | User | — | `{name, base: 'light'\|'dark', colors: Palette}` |

None of the admin keys contain a sensitive term, so `sanitize_settings_for_user()` passes them to the V2 bootstrap `settings`. That is how the interface receives them.

### Validation

`application/single_app/functions_color_schemes.py` owns the rules and is used on every save path:

- **Admin save:** `PATCH /api/v2/admin/settings` → `normalize_admin_settings_updates` → `_COMPONENT_VALUE_VALIDATORS["v2_color_scheme"]` → `normalize_color_scheme`.
- **User save:** `POST /api/user/settings` → `normalize_color_mode` and `normalize_custom_color_mode`.
  - The route refuses `custom` while `allow_user_custom_color_modes` is off.
  - It enforces contrast while `require_readable_custom_colors` is on.
- **What is refused:**
  - Unknown or missing tokens.
  - Anything that isn't a six-digit hex color, such as CSS expressions, `url(…)` or short hex.
  - Names longer than 40 characters. Control characters are removed from names.
- **Contrast** is judged on the ratio as it is shown, to one decimal place. A pair displayed as "4.5:1" therefore always passes; the SimpleChat default accent is 4.48:1 on white.

### Applying colors

- **Runtime:** `useColorSchemeRuntime` (called in `App.tsx`) combines the administrator's scheme with the user's custom mode. The custom mode is used only when it's selected and still allowed. The result is written to a single `<style id="sc-color-scheme">` using `textContent`. Its `html:root` and `html.dark` selectors outrank the rules in `theme.css`.
- **No flash on load:** the generated CSS is cached in `localStorage` (`simplechat.v2.color-css`), and the inline script in `index.html` applies it before the first paint, just as the theme class is applied.
- **Color mode state:** `uiStore` adds `colorMode` and `customColorMode`.
  - `system` follows `prefers-color-scheme` and updates live.
  - The sidebar button cycles Light -> Dark -> Custom -> Light when a saved custom palette exists and the administrator allows it; otherwise it switches only between Light and Dark. Custom is a distinct step whether its base is light or dark.
  - The button names the next mode. **Custom mode** uses the same palette icon as Custom in Settings; the collapsed rail's tooltip names the next action.
  - From Match system, the button enters the cycle using the current resolved appearance. Match system remains available in Settings.

### Theme Card format

```
SCTHEME1.<payload>.<checksum>
payload  = base64url(JSON {"v":1,"n":name,"b":"light"|"dark","c":{token:"RRGGBB",…}})
checksum = base64url(first 16 bytes of SHA-256("SCTHEME1." + payload))
```

- **Open checksum:** the checksum is unkeyed on purpose, so a card made on one SimpleChat deployment imports on any other. It catches a card edited after it was made. It is not a signature, so every value is still validated before it is saved.
- **Two copies of the code:** the code is drawn as the QR code (error correction M, modules in the palette's colors darkened to stay readable on white). It is also written into the PNG as a `tEXt` chunk with the keyword `simplechat-theme`.
- **Import order:** the PNG chunk is read first. If it's missing, for example in a screenshot or a recompressed copy, the QR code is read with jsQR.
- **Privacy:** the image never leaves the browser. Only the eleven validated colors are saved.

### Files

| File | Purpose |
|------|---------|
| `application/single_app/functions_color_schemes.py` | Validation, contrast, Theme Card format |
| `application/single_app/admin_settings_fields.py` | Appearance section fields and validator registration |
| `application/single_app/functions_settings.py` | Defaults |
| `application/single_app/route_backend_users.py` | User preference allowlist and validation |
| `application/v2_ui/src/lib/colorScheme.ts` | Palette types, defaults, CSS generation, Theme Card code |
| `application/v2_ui/src/lib/themeCardImage.ts` | Card drawing, PNG `tEXt` chunk, QR reading |
| `application/v2_ui/src/lib/useColorSchemeRuntime.ts` | Applies the active colors app-wide |
| `application/v2_ui/src/stores/uiStore.ts` | `colorMode`, `customColorMode` |
| `application/v2_ui/src/components/admin/ColorSchemeEditor.tsx` | Admin color table |
| `application/v2_ui/src/components/settings/ColorModeCard.tsx` | User color mode card |
| `application/v2_ui/src/components/appearance/` | Shared controls and the Theme Card dialogs |

## Usage

### Administrators

1. Open **Admin Settings › Appearance › Appearance**.
2. Under **Color scheme**, change any color in the Light or Dark column. Use the swatch or type a hex value. The previews update as you go.
3. Each color that carries text shows a contrast badge. A low-contrast warning suggests a nearby readable color, but it doesn't stop you from saving.
4. **Import Theme Card** fills the column the card was made for. **Reset to SimpleChat default** returns to the shipped colors.
5. Save with the page's Save bar. Everyone's interface repaints.
6. Use the three switches below the table to control user color modes.

### Users

1. Open **Settings › Preferences › Color mode** and choose **Light**, **Dark**, **Match system** or **Custom**.
2. **Custom**:
   - Name the mode and choose a Light or Dark starting point, which starts from the organization's colors.
   - Adjust colors in the table, watch the preview, then choose **Save my color mode**.
3. **Share as Theme Card** downloads the card image. **Copy as text code** copies the code instead.
4. **Import Theme Card** accepts a PNG, JPG or WebP up to 2 MB, or a pasted text code. The card is checked and previewed, and nothing changes until you save.

After saving a custom mode, use the button above your account in the sidebar to
cycle **Light -> Dark -> Custom -> Light** without reopening Settings. Switching
away does not erase your palette. Custom is skipped if no valid palette is saved
or your administrator disables custom modes. The selection saves as an account
preference and works in expanded, collapsed, and mobile navigation.

## Testing and Validation

- `functional_tests/test_color_schemes_validation.py`: palette, scheme, custom mode and contrast rules, including injection attempts.
- `ui_tests/test_v2_sidebar_color_mode_cycle.py`: sidebar cycling with light/dark custom bases, unavailable palettes, administrator policy, Match system, palette icon, keyboard activation, persistence, and expanded/collapsed/mobile navigation.
- `functional_tests/test_theme_card_code_format.py`:
  - A code made by the browser decodes on the server, and the Python encoder reproduces it exactly.
  - Edited cards and cards carrying unsafe values are refused.
- `functional_tests/test_color_schemes_admin_settings.py`: schema fields, admin PATCH validation, defaults and user route wiring.
- `functional_tests/test_v2_admin_appearance_parity.py` records the four settings as V2-only, each with the code that reads it.
- **End-to-end** against the V2 dev server, all passing:
  - A saved custom mode recolors the whole app with no flash on reload.
  - A downloaded card imports from the original PNG and from a 60% JPEG with its metadata stripped (the QR path).
  - An edited card is refused.
  - The server rejects CSS in a color.
  - Turning custom modes off hides **Custom**, stops applying custom colors and refuses the setting.

**Limitations**

- A heavily cropped or blurred photo of a card may not scan. The original PNG always imports.
- Classic interface colors are not affected.
