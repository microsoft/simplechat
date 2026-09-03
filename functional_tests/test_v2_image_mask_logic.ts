// test_v2_image_mask_logic.ts
// Behavioural checks for the image mask geometry.
//
// Version: 0.261.056
// Implemented in: 0.261.056
//
// The V2 interface has no unit test runner, so this follows test_v2_diagram_editor_logic.ts:
// bundled with the esbuild Vite already brings in, run under node by test_v2_image_editor.py,
// and skipped when the front-end toolchain is not installed.
//
// Only the geometry is checked here. Node has no canvas, so the rendering itself — and with it
// the transparent-means-edit polarity — is proved end to end against real PNG bytes by
// test_message_image_revisions.py, which is the side that actually has to be right.
//
// What matters here is that the nine-region keyboard picker produces exactly the rectangles a
// drag would. If it did not, the accessible path would be a second implementation with its own
// bugs rather than the same one reached differently.

import {
    MASK_REGION_KEYS,
    MASK_REGION_LABELS,
    containedImageRect,
    hasSelection,
    maskRegionRect,
    normalizeRect,
    pointerToImagePoint,
    type MaskShape,
} from '../application/v2_ui/src/lib/imageMask';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail ?? '');
    }
}

/* ---- the nine-region picker ---- */

check('there are exactly nine regions', MASK_REGION_KEYS.length === 9);
check(
    'every region has a label a screen reader can announce',
    MASK_REGION_KEYS.every((key) => Boolean(MASK_REGION_LABELS[key])),
);

const WIDTH = 1024;
const HEIGHT = 1536;
const rects = MASK_REGION_KEYS.map((key) => maskRegionRect(key, WIDTH, HEIGHT));

check(
    'the regions tile the image exactly, with no seam left by rounding',
    rects.reduce((total, rect) => total + rect.width * rect.height, 0) === WIDTH * HEIGHT,
    rects.reduce((total, rect) => total + rect.width * rect.height, 0),
);

check(
    'no region falls outside the image',
    rects.every(
        (rect) =>
            rect.x >= 0 &&
            rect.y >= 0 &&
            rect.x + rect.width <= WIDTH &&
            rect.y + rect.height <= HEIGHT,
    ),
);

check(
    'no two regions overlap',
    rects.every((a, indexA) =>
        rects.every((b, indexB) => {
            if (indexA >= indexB) {
                return true;
            }
            return (
                a.x + a.width <= b.x ||
                b.x + b.width <= a.x ||
                a.y + a.height <= b.y ||
                b.y + b.height <= a.y
            );
        }),
    ),
);

check(
    'the top-left region starts at the origin',
    maskRegionRect('top-left', 900, 900).x === 0 && maskRegionRect('top-left', 900, 900).y === 0,
);

check(
    'the bottom-right region ends at the far corner',
    (() => {
        const rect = maskRegionRect('bottom-right', 900, 900);
        return rect.x + rect.width === 900 && rect.y + rect.height === 900;
    })(),
);

// A size that does not divide by three is the interesting case: naive arithmetic leaves a
// one-pixel seam between adjacent regions, which shows up as an unedited line in the result.
const AWKWARD = 1025;
const awkward = MASK_REGION_KEYS.map((key) => maskRegionRect(key, AWKWARD, AWKWARD));
check(
    'an awkward size still tiles exactly',
    awkward.reduce((total, rect) => total + rect.width * rect.height, 0) === AWKWARD * AWKWARD,
    awkward.reduce((total, rect) => total + rect.width * rect.height, 0),
);

check(
    'a region selection is the same shape a drag produces',
    (() => {
        const region = maskRegionRect('middle-center', 300, 300);
        const dragged = normalizeRect({ x: 100, y: 100 }, { x: 200, y: 200 }, 300, 300);
        return JSON.stringify(region) === JSON.stringify(dragged);
    })(),
    { region: maskRegionRect('middle-center', 300, 300) },
);

/* ---- dragging ---- */

check(
    'dragging up and left produces the same rectangle as down and right',
    JSON.stringify(normalizeRect({ x: 80, y: 90 }, { x: 20, y: 30 }, 200, 200)) ===
        JSON.stringify(normalizeRect({ x: 20, y: 30 }, { x: 80, y: 90 }, 200, 200)),
);

check(
    'a drag beyond the edge is clamped to the image',
    (() => {
        const rect = normalizeRect({ x: -50, y: -50 }, { x: 500, y: 500 }, 100, 100);
        return rect.x === 0 && rect.y === 0 && rect.width === 100 && rect.height === 100;
    })(),
    normalizeRect({ x: -50, y: -50 }, { x: 500, y: 500 }, 100, 100),
);

check(
    'a click without a drag has no area',
    (() => {
        const rect = normalizeRect({ x: 40, y: 40 }, { x: 40, y: 40 }, 100, 100);
        return rect.width === 0 && rect.height === 0;
    })(),
);

/* ---- what counts as a selection ---- */

check('nothing selected is not a selection', hasSelection([]) === false);
check(
    'a zero-area rectangle is not a selection',
    hasSelection([{ kind: 'rect', rect: { x: 5, y: 5, width: 0, height: 0 } }]) === false,
);
check(
    'a rectangle with area is a selection',
    hasSelection([{ kind: 'rect', rect: { x: 0, y: 0, width: 10, height: 10 } }]),
);
check(
    'a single brush point is a selection, since a dab of the brush is deliberate',
    hasSelection([{ kind: 'stroke', stroke: { points: [{ x: 1, y: 1 }], size: 20 } }]),
);
check(
    'an empty stroke is not a selection',
    hasSelection([{ kind: 'stroke', stroke: { points: [], size: 20 } }] as MaskShape[]) === false,
);

/* ---- mapping a pointer onto the picture ---- */

// The bug this guards against: mapping through the element box rather than the drawn picture.
// An image laid out with a full width and a capped height is letterboxed by `object-contain`,
// and mapping through the box compresses every coordinate toward the centre — so the mask ends
// up over the wrong region and the model edits the wrong part of the image, on a paid call.

check(
    'with no letterboxing the mapping is the plain proportional one',
    (() => {
        const point = pointerToImagePoint(50, 50, 100, 100, 1024, 1024);
        return point !== null && Math.abs(point.x - 512) < 0.001 && Math.abs(point.y - 512) < 0.001;
    })(),
    pointerToImagePoint(50, 50, 100, 100, 1024, 1024),
);

check(
    'a square image in a wide box maps through the picture, not the box',
    (() => {
        // 600x414 box, 1024x1024 image: drawn 414x414 centred, so 93px bars left and right.
        const drawn = containedImageRect(600, 414, 1024, 1024);
        if (Math.abs(drawn.width - 414) > 0.001 || Math.abs(drawn.x - 93) > 0.001) {
            return false;
        }
        // The right-hand edge of the *picture* must be the right-hand edge of the image.
        const right = pointerToImagePoint(93 + 414, 207, 600, 414, 1024, 1024);
        return right !== null && Math.abs(right.x - 1024) < 0.001;
    })(),
    containedImageRect(600, 414, 1024, 1024),
);

check(
    'the naive box mapping would have been wrong, which is why this exists',
    (() => {
        // What the element-box mapping produced for the same point.
        const naive = ((93 + 414) / 600) * 1024;
        return Math.abs(naive - 1024) > 150;
    })(),
);

check(
    'a tall image in a short box is letterboxed top and bottom',
    (() => {
        const drawn = containedImageRect(400, 400, 1024, 1536);
        return (
            Math.abs(drawn.height - 400) < 0.001 &&
            Math.abs(drawn.width - 1024 * (400 / 1536)) < 0.001 &&
            drawn.y === 0 &&
            drawn.x > 0
        );
    })(),
    containedImageRect(400, 400, 1024, 1536),
);

check(
    'the centre of the box is the centre of the image whatever the letterboxing',
    (() => {
        const point = pointerToImagePoint(300, 207, 600, 414, 1024, 1024);
        return point !== null && Math.abs(point.x - 512) < 0.001 && Math.abs(point.y - 512) < 0.001;
    })(),
);

check(
    'a degenerate box maps to nothing rather than to NaN',
    pointerToImagePoint(10, 10, 0, 0, 1024, 1024) === null &&
        pointerToImagePoint(10, 10, 100, 100, 0, 0) === null,
);

if (failures > 0) {
    console.log(`\n${failures} check(s) failed`);
    process.exit(1);
}
console.log('\nall image mask checks passed');
