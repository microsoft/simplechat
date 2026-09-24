// test_v2_classic_bytes_parity.mjs
//
// Runtime pin for the V2 group Statistics byte formatter (S12).
// Version: 0.261.165
// Implemented in: 0.261.165
//
// The V2 group stats export renders its Storage "Formatted" column with
// formatClassicBytes (application/v2_ui/src/lib/groupStats.ts). The contract
// requires that column to be byte-for-byte the classic Manage group export's
// output, which the classic page produces with formatBytes
// (application/single_app/static/js/group/manage_group.js), pinned by
// functional_tests/test_classic_group_stats_export_fix.py.
//
// This file proves the two formatters agree by behaviour, not by inspection.
// It takes each function out of its module by name -- the same way the classic
// export test's top_level_function extractor does -- and runs both: the classic
// one verbatim, the V2 one with its TypeScript type annotations stripped by the
// UI's own compiler so the body executes exactly as it ships. It then compares
// their output across the range the classic test pins. If either function is
// renamed, removed or drifts, this pin fails.
//
// Run directly with `node functional_tests/test_v2_classic_bytes_parity.mjs`.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const require = createRequire(new URL('../application/v2_ui/package.json', import.meta.url));
const ts = require('typescript');

const MANAGE_GROUP_JS = fileURLToPath(
    new URL('../application/single_app/static/js/group/manage_group.js', import.meta.url),
);
const GROUP_STATS_TS = fileURLToPath(
    new URL('../application/v2_ui/src/lib/groupStats.ts', import.meta.url),
);

// The classic byte-format cases the classic export test pins: 0, 1, 1023,
// 1 KiB, 1.5 KiB, 1 MiB, 5.5 GiB, 1 TiB and 2 PiB. The V2 column must match.
const FORMAT_CASES = [
    [0, '0 B'],
    [1, '1 B'],
    [1023, '1023 B'],
    [1024, '1 KB'],
    [1536, '1.5 KB'],
    [1048576, '1 MB'],
    [5905580032, '5.5 GB'],
    [1099511627776, '1 TB'],
    [2251799813685248, '2048 TB'],
];

/**
 * The source of a module's top-level `function name(...) {...}`, optionally exported, or null
 * when it has none. Every top-level function in both modules opens at column 0 and closes on a
 * line that is exactly `}`, so the first such line after the declaration ends it. This mirrors
 * the classic test's top_level_function extractor so a renamed or removed formatter fails the pin.
 */
function topLevelFunction(source, name) {
    const lines = source.split(/\r?\n/);
    const declaration = new RegExp(`^(export\\s+)?(async\\s+)?function\\s+${name}\\s*\\(`);
    for (let start = 0; start < lines.length; start += 1) {
        if (declaration.test(lines[start])) {
            for (let end = start + 1; end < lines.length; end += 1) {
                if (lines[end] === '}') {
                    return lines.slice(start, end + 1).join('\n');
                }
            }
            throw new Error(`${name} has no closing brace at column 0`);
        }
    }
    return null;
}

/** Evaluate an extracted top-level function declaration and return the function it defines. */
function evaluateFunction(name, declarationSource) {
    const sandbox = {};
    vm.createContext(sandbox);
    new vm.Script(`${declarationSource}\nglobalThis.__extracted = ${name};`).runInContext(sandbox);
    return sandbox.__extracted;
}

function loadClassicFormatBytes() {
    const extracted = topLevelFunction(readFileSync(MANAGE_GROUP_JS, 'utf-8'), 'formatBytes');
    assert.ok(extracted, 'manage_group.js no longer defines a top-level formatBytes');
    return evaluateFunction('formatBytes', extracted);
}

function loadV2FormatClassicBytes() {
    const extracted = topLevelFunction(readFileSync(GROUP_STATS_TS, 'utf-8'), 'formatClassicBytes');
    assert.ok(extracted, 'groupStats.ts no longer defines a top-level formatClassicBytes');
    // Strip the `export` keyword and the TypeScript type annotations with the UI's own compiler,
    // so the runtime body is exactly what ships rather than a hand-copied plain-JS version.
    const withoutExport = extracted.replace(/^export\s+/, '');
    const transpiled = ts.transpileModule(withoutExport, {
        compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
    }).outputText;
    return evaluateFunction('formatClassicBytes', transpiled);
}

const classicFormatBytes = loadClassicFormatBytes();
const formatClassicBytes = loadV2FormatClassicBytes();

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

check('both formatters were taken out of their modules and are callable', () => {
    assert.equal(typeof classicFormatBytes, 'function');
    assert.equal(typeof formatClassicBytes, 'function');
});

for (const [bytes, expected] of FORMAT_CASES) {
    check(`both formatters render ${bytes} as "${expected}"`, () => {
        const classicOutput = classicFormatBytes(bytes);
        const v2Output = formatClassicBytes(bytes);
        assert.equal(classicOutput, expected, `classic formatBytes(${bytes}) drifted`);
        assert.equal(v2Output, expected, `V2 formatClassicBytes(${bytes}) drifted`);
        assert.equal(v2Output, classicOutput, `V2 and classic disagree on ${bytes}`);
    });
}

/* ---------------------------------- runner --------------------------------- */

let failures = 0;
for (const [name, fn] of checks) {
    try {
        fn();
        console.log(`  ok  ${name}`);
    } catch (error) {
        failures += 1;
        console.error(`FAIL  ${name}`);
        console.error(`      ${error.message}`);
    }
}

console.log(`\nResults: ${checks.length - failures}/${checks.length} checks passed`);
process.exit(failures === 0 ? 0 : 1);
