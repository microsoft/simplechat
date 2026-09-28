// test_v2_group_stats_formatter_parity.mjs
// Version: 0.261.165
// Implemented in: 0.261.165
// Runs the V2 group Statistics export's byte formatter (lib/groupStats.ts formatClassicBytes) beside
// the classic Manage group export's own formatBytes (static/js/group/manage_group.js). The two exports
// write the same "Formatted" storage column only if the two functions agree, so every size here must
// format identically on both.
//
// groupStats.ts imports a .tsx chart component that Node can't load, so the function's own source is
// taken from the module and transpiled with the project's TypeScript compiler, rather than importing
// the module whole.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const ts = createRequire(new URL('../application/v2_ui/package.json', import.meta.url))('typescript');

/** The source of a top-level function that opens at column 0 and closes on a line that is exactly `}`. */
function topLevelFunction(path, declaration) {
    const lines = readFileSync(new URL(path, import.meta.url), 'utf8').split(/\r?\n/);
    const start = lines.findIndex((line) => declaration.test(line));
    assert.ok(start >= 0, `${path} defines ${declaration}`);
    const end = lines.findIndex((line, index) => index > start && line === '}');
    assert.ok(end > start, `${declaration} in ${path} closes at column 0`);
    return lines.slice(start, end + 1).join('\n');
}

const v2Source = topLevelFunction('../application/v2_ui/src/lib/groupStats.ts', /^export function formatClassicBytes\(/)
    .replace(/^export /, '');
const v2Script = ts.transpileModule(v2Source, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
const formatClassicBytes = new Function(`${v2Script}\nreturn formatClassicBytes;`)();

const classicSource = topLevelFunction('../application/single_app/static/js/group/manage_group.js', /^function formatBytes\(/);
const classicFormatBytes = new Function(`${classicSource}\nreturn formatBytes;`)();

const sizes = [
    0, 1, 1023, 1024, 1536, 1048576, 1073741824, 5905580032,
    1099511627776, 1125899906842624, 2251799813685248,
];
let checks = 0;
for (const size of sizes) {
    assert.equal(formatClassicBytes(size), classicFormatBytes(size), `${size} bytes formats the same in V2 and classic`);
    checks += 1;
}
assert.equal(formatClassicBytes(1536), '1.5 KB');
checks += 1;

console.log(`${checks} group statistics formatter parity checks passed.`);
