// test_chat_action_recovery_rendering.mjs
// Version: 0.261.420
// Implemented in: 0.261.420
// Validate the production editor URL boundary; real DOM coverage lives in ui_tests.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../application/single_app/static/js/chat/chat-action-recovery.js', import.meta.url), 'utf8');
const match = source.match(/function safeEditUrl\(value\) \{[\s\S]*?\n\}/);
assert.ok(match, 'The production recovery editor URL boundary must exist.');
const safeEditUrl = vm.runInNewContext(`(${match[0]})`);

const validUrls = [
    ['/v2/workspace/actions/action-1', '/v2/workspace/actions/action-1'],
    ['/v2/admin/actions/action-1', '/v2/admin/actions/action-1'],
    ['/v2/groups/group-1/actions/action-1', '/v2/groups/group-1/actions/action-1'],
    ['/v2/workspace/actions/quoted" & <id>', '/v2/workspace/actions/quoted%22%20%26%20%3Cid%3E'],
    ['/v2/admin/actions/é', '/v2/admin/actions/%C3%A9'],
    ['/v2/groups/space%20group/actions/space%20id%2F%25%22%23%3F',
        '/v2/groups/space%20group/actions/space%20id%2F%25%22%23%3F'],
    ['/v2/groups/group%2D1/actions/action%2D1', '/v2/groups/group-1/actions/action-1'],
    ['/v2/workspace/actions/literal%252F', '/v2/workspace/actions/literal%252F'],
    ['/v2/groups/owner%27s%20group/actions/action%28id%29%21%2A',
        '/v2/groups/owner%27s%20group/actions/action%28id%29%21%2A'],
];
for (const [value, expected] of validUrls) {
    const actual = safeEditUrl(value);
    assert.equal(actual, expected, `Preserve the authorized route and identifier for ${value}`);
    const parsed = new URL(actual, 'https://simplechat.test');
    assert.equal(parsed.origin, 'https://simplechat.test');
    assert.equal(parsed.search, '');
    assert.equal(parsed.hash, '');
}

const invalidUrls = [
    undefined, null, false, 123, [], {},
    { toString() { throw new Error('Recovery URLs must not coerce exception objects.'); } },
    'javascript:window.__injected=true',
    'data:text/html,<script>window.__injected=true</script>',
    '//untrusted.invalid/action', 'https://untrusted.invalid/action',
    '/v2/workspace/actions/', '/v2/groups/group-1/actions/',
    '/v2/workspace/actions/action-1/extra', '/v2/other/actions/action-1',
    '/v2/workspace/actions/action-1?next=javascript:window.__injected=true',
    '/v2/admin/actions/action-1#fragment',
    '/v2/workspace/actions/action-1\\extra',
    '/v2/groups/group\\1/actions/action-1',
    '/v2/workspace/actions/.', '/v2/workspace/actions/..',
    '/v2/workspace/actions/%2E', '/v2/workspace/actions/.%2e',
    '/v2/groups/%2e%2e/actions/action-1',
    '/v2/workspace/actions/bad%ZZ', '/v2/admin/actions/%C0%AE',
    '/v2/groups/bad%/actions/action-1',
    '/v2/workspace/actions/action-1\n', '/v2/admin/actions/action\r1',
    '/v2/groups/group\u0000/actions/action-1',
];
for (const value of invalidUrls) {
    const actual = safeEditUrl(value);
    assert.equal(actual, null, 'Do not expose an invalid or nonlocal editor URL.');
}

const unexpectedError = new Error('Unexpected decoder failure.');
const failingEditUrl = vm.runInNewContext(`(${match[0]})`, {
    decodeURIComponent() {
        throw unexpectedError;
    },
});
assert.throws(() => failingEditUrl('/v2/workspace/actions/action-1'), error => error === unexpectedError);

console.log(`Recovery editor URL contracts passed (${validUrls.length} valid, ${invalidUrls.length} invalid, 1 failure propagation).`);
