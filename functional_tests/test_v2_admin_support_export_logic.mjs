// test_v2_admin_support_export_logic.mjs
// Version: 0.261.426
// Implemented in: 0.261.426

import assert from 'node:assert/strict';
import {
    buildSupportRequest, supportDefaults, supportExportPath, supportJobActive,
} from '../application/v2_ui/src/lib/supportExports.ts';

const form = supportDefaults(new Date('2026-11-10T12:00:00Z'));
assert.throws(() => buildSupportRequest(form), /Select one/);
form.user_id = 'owner';
form.sources = ['activity'];
const request = buildSupportRequest(form);
assert.equal(Date.parse(request.end) - Date.parse(request.start), 3_600_000);
assert.equal('narrow_range' in request, false);
assert.equal(supportExportPath('../unsafe', 'download'), '/api/admin/support-exports/..%2Funsafe/download');
assert.equal(supportJobActive('waiting_for_consent'), true);
assert.equal(supportJobActive('ready'), false);
assert.throws(() => buildSupportRequest({ ...form, before_minutes: '' }), /whole minutes/);
assert.throws(() => buildSupportRequest({ ...form, all_users: true, conversation_ids: ['one'] }), /All-users/);
const previous = process.env.TZ;
try {
    process.env.TZ = 'America/New_York';
    assert.throws(() => buildSupportRequest({ ...form, start: '2026-11-01T01:30', end: '2026-11-01T03:00' }), /repeats/);
    assert.throws(() => buildSupportRequest({ ...form, start: '2026-03-08T02:30', end: '2026-03-08T04:00' }), /valid local/);
} finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
}
console.log('Support export request, path, state, and DST contracts passed.');
