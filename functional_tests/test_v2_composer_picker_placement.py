# test_v2_composer_picker_placement.py
"""
Functional test for viewport-bounded floating composer pickers.
Version: 0.261.327
Implemented in: 0.261.327

Executes the production TypeScript placement helper through the installed esbuild.
Node's explicit checks run identically under normal and optimized Python.
"""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "application" / "v2_ui"


def test_floating_placement_bounds_and_visual_viewport_offsets():
    with tempfile.TemporaryDirectory(prefix="simplechat-picker-") as directory:
        bundle = Path(directory) / "placement.cjs"
        subprocess.run([
            "node", str(UI / "node_modules" / "esbuild" / "bin" / "esbuild"),
            str(UI / "src" / "components" / "ui" / "dropdownPlacement.ts"),
            "--bundle", "--platform=node", "--format=cjs", f"--outfile={bundle}", "--log-level=error",
        ], check=True, capture_output=True, text=True)
        probe = r"""
const assert = require('node:assert/strict');
const {dropdownPlacement: place} = require(process.argv[1]);
const top = place({left: 20, right: 100, top: 20, bottom: 64},
    {left: 0, top: 0, width: 393, height: 852}, 'left');
assert.equal(top.up, false);
assert.equal(top.top, 72);
const bottom = place({left: 280, right: 360, top: 700, bottom: 744},
    {left: 0, top: 0, width: 393, height: 852}, 'right');
assert.equal(bottom.up, true);
assert.equal(bottom.top, 692);
assert.equal(bottom.maxHeight, 320);
for (const width of [16, 24, 96, 320, 360, 393, 430, 1280]) {
    for (const height of [16, 24, 96, 140, 320, 393, 740, 852]) {
        for (const left of [0, 29]) {
            for (const top of [0, 83]) {
                const viewport = {left, top, width, height};
                for (const fraction of [0, .1, .5, .9, 1]) {
                    const trigger = {left: left + width * fraction, right: left + width * fraction + 90,
                        top: top + height * fraction, bottom: top + height * fraction + 44};
                    for (const align of ['left', 'right']) {
                        const p = place(trigger, viewport, align);
                        const margin = Math.min(12, width / 2, height / 2);
                        assert.ok(p.width >= 0 && p.width <= 288);
                        assert.ok(p.left >= left + margin);
                        assert.ok(p.left + p.width <= left + width - margin + .001);
                        assert.ok(p.maxHeight >= 0 && p.maxHeight <= 320);
                        const ceiling = p.up ? p.top - p.maxHeight : p.top;
                        const floor = p.up ? p.top : p.top + p.maxHeight;
                        assert.ok(ceiling >= top + margin - .001, JSON.stringify({p, viewport, trigger}));
                        assert.ok(floor <= top + height - margin + .001, JSON.stringify({p, viewport, trigger}));
                    }
                }
            }
        }
    }
}
"""
        subprocess.run(["node", "-e", probe, str(bundle)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    test_floating_placement_bounds_and_visual_viewport_offsets()
