# V2 Composer Dropdown Placement Fix

## Issue

In the V2 chat page, opening the Model, Agent, Prompt or Reasoning picker rendered the menu
below the trigger. The composer is anchored to the bottom of the viewport, so there was
never enough room there: the list ran past the bottom edge of the window, leaving most or
all of the options invisible and unreachable. The page does not scroll to reveal it, so the
control appeared broken rather than merely awkward.

The effect was worse the shorter the browser window, and worse still for the Reasoning
picker, which sits on the composer's lower row and therefore had the least room of all.

**Fixed in version:** 0.261.011

## Root cause

`Dropdown.tsx` positioned its menu with a fixed downward offset and a fixed height:

```
'glass-modal absolute z-50 mt-2 max-h-80 w-72 overflow-y-auto rounded-2xl p-1.5'
```

`mt-2` with no `top`/`bottom` anchor places the menu immediately after the trigger, and
`max-h-80` lets it claim 320px regardless of whether 320px exists below. Neither value
consults the viewport, so the component had no way to behave differently in the one place
it is actually used.

This was not a styling oversight so much as a missing decision: the component never asked
where it was on the screen.

## The fix

Placement is now measured rather than assumed. On open — and again on resize or scroll
while open — the component reads the trigger's bounding rectangle and compares the space
below it against the space above:

- If there is room for the full menu below, or simply more room below than above, it opens
  downward as before.
- Otherwise it opens upward, anchored with `bottom-full`.

In both cases the menu's height is clamped to the space actually available, with a floor so
a very short viewport cannot collapse it to nothing, and `overflow-y-auto` lets a clamped
menu scroll instead of overflowing.

Keeping the downward preference matters. A hardcoded flip would fix the composer and break
any future use of `Dropdown` near the top of a page, so the component decides per instance
instead of encoding where its callers happen to live today.

The scroll listener is registered with the capture flag, because the composer's ancestors
scroll rather than the document itself; a bubbling listener would miss those events and let
an open menu drift out of position.

## Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/components/ui/Dropdown.tsx` | Measured placement, upward flip, height clamped to available space, re-measure on resize and scroll |
| `application/single_app/config.py` | Version to 0.261.011 |
| `functional_tests/test_v2_dropdown_placement.py` | New test |

`MessageActions` already flipped its own menu for the same reason and was left unchanged.

## Validation

`functional_tests/test_v2_dropdown_placement.py` asserts the menu can render above the
trigger, that placement is derived from `getBoundingClientRect` and the viewport height
rather than hardcoded, that the downward branch still wins when there is room, that the
height is clamped with a usable floor, that the listeners are added and removed in pairs,
and that all four composer pickers still share the component so none is left behind.

Placement was also verified in a real browser against the local preview server at viewport
heights of 520, 700 and 950 pixels. Before the fix the menus extended past the bottom of
the window; after it, every picker — Model, Agent, Prompt and Reasoning — opens upward and
sits entirely within the viewport at all three heights, retaining a usable height of at
least 122 pixels.

| Picker | Before | After (520px viewport) |
|---|---|---|
| Model | Ran past the bottom edge | Opens upward, 262–384px |
| Agent | Ran past the bottom edge | Opens upward, 182–384px |
| Prompt | Ran past the bottom edge | Opens upward, 234–384px |
| Reasoning | Ran past the bottom edge | Opens upward, 304–426px |

## Related

- Feature documentation: `docs/explanation/features/REACT_V2_UI.md`
