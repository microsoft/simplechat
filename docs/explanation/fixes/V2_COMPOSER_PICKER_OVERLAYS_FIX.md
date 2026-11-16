# V2 composer picker clipping fix (0.261.327)

Fixed/Implemented in version: **0.261.327**, recorded in
`application/single_app/config.py`.

## Issue and root cause

Expanded mobile Chat tools deliberately scrolls within `30dvh`. The shared
Dropdown rendered its menu absolutely inside that overflow boundary.
Positioning upward and raising its stacking order did not stop the boundary
from cutting off Agent, Prompt, and other options. A browser regression using
the original Dropdown reproduced an Agent option above the tools rectangle
whose center could not be hit-tested.

## Technical changes

`Dropdown.tsx` has an explicit floating presentation, enabled for all six
composer dropdown variants in `Composer.tsx`. It renders a fixed portal into
the document body, measures the trigger, and delegates bounds to
`dropdownPlacement.ts`. Other Dropdown instances retain inline positioning.
The helper flips toward available space and clamps width, horizontal position,
and height without imposing a minimum height greater than the available space.
It accounts for visual viewport offsets and dimensions, including keyboard or
zoom viewport changes when the browser exposes them.

`DropdownScope.tsx` owns the existing scrolling tools container and coordinates
one active picker. Closing the mobile disclosure, changing conversation,
unmounting or disabling a trigger, collapsing Manual controls, and scrolling a
trigger out of the tools container removes its portal. Window/visual viewport
resize and capture-phase scrolling reposition open menus; listeners and the
trigger resize observer are cleaned up.

Portal pointer events count as inside the menu. Outside pointer dismissal does
not cancel the underlying action. Escape and selection return focus to the
trigger; arrow keys and Home/End traverse choices, and Tab exits. Options retain
listbox selection semantics and checkmarks; Clear selection remains separate
from the options. The menu itself scrolls, keeping clear and hint content
reachable even in short viewports. `theme.css` supplies portal-specific mobile
touch targets because the tools container is no longer its ancestor.

The portal uses layer 40, below the existing layer-50 modal. The real document
picker is mounted through ComposerEditor outside the tools overflow container
and does not need the same change. No new API, permission, setting, dependency,
or deployer change is involved.

## Validation

`ui_tests/test_v2_composer_picker_overlays.py` runs production Composer,
Dropdown, stores, and CSS with strict synthetic HTTP. It covers the six picker
variants, grouped 36-entry Agent/Prompt catalogs, first/last choices, selected
checkmarks, clear, disabled/empty states, switching menus, outside dismissal,
keyboard navigation, disclosure/conversation lifecycle, scroll/resize, dialog
entry, and saved approval/model choices. It measures actual viewport geometry
and option center hit-testing outside the tools boundary at phone widths
320/360/393/430, short landscape, desktop, both themes, and enlarged text.

`functional_tests/test_v2_composer_picker_placement.py` executes the real
TypeScript helper with Node assertions over normal, tiny, offset, and short
viewports. Its operations and assertions remain active under optimized Python.
The original dropdown functional coverage remains in
`functional_tests/test_v2_dropdown_placement.py`.

Related mobile navigation/header/chat, reasoning, approval/model persistence,
and prompt browser tests exercise the existing workflows. Shared test helpers
open Chat tools before reaching mobile pickers; prompt status checks identify
their own status instead of the shell's unrelated live region.

The final picker/mobile/placement runner passed **98 tests**; the independent
reasoning, approval/model, and prompt runner passed **123 tests**. These run
separately because the legacy tests own a synchronous Playwright connection
while the mobile fixtures use pytest's connection. Prebuilding the shared
harness avoids competing fixture builds. The original-Dropdown reproduction
failed the actual Agent-option hit-test as expected; the fixed implementation
passed.

Both TypeScript/Vite builds passed, as did the optimized placement probe.
Documentation surface coverage passed **7/7**, documentation site quality
**6/6**, and V2 local-asset coverage **4/4**. Full-file picker and added-line
application XSS checks, whitespace checks, and the scoped UI mechanical
detector reported no findings. Vite retains its existing large-bundle warning.

Production and harness TypeScript/Vite builds serve only local assets.
Phone/desktop screenshots are test artifacts, not committed application data.
Actual iPhone Safari keyboard, browser chrome, and safe-area behavior remain a
manual physical-device check; Chromium emulation does not certify those cases.
