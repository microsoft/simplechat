// test_v2_group_membership_logic.mjs
// Version: 0.261.155
// Implemented in: 0.261.155
// Executes the real V2 group membership adapter (lib/groupMembership.ts): the strict envelope
// readers, the request each client call sends, the people search reader, the refusal helpers and
// the classic-format CSV parser, with controlled HTTP.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const membership = await import('../application/v2_ui/src/lib/groupMembership.ts');
const { ApiError } = await import('../application/v2_ui/src/lib/apiClient.ts');
const {
    createGroupMembershipClient, fallbackMemberText, isAccessChangedError, isTerminalMembershipError,
    memberDisplayName, memberListParams, membershipErrorCode, membershipErrorMessage, parseMemberCsv,
    readJoinRequests, readMemberListPage, searchDirectoryUsers, MembershipResponseError,
} = membership;

const originalFetch = globalThis.fetch;
let calls = [];
let answer = () => json({});
let checks = 0;

function json(body, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

globalThis.fetch = async (path, options = {}) => {
    const headers = options.headers ?? {};
    calls.push({
        path: String(path), method: options.method ?? 'GET', body: options.body ?? null,
        contentType: headers['Content-Type'] ?? null,
    });
    return answer(calls.at(-1));
};

async function check(name, run) {
    calls = [];
    answer = () => json({});
    await run();
    checks += 1;
    console.log(`ok ${name}`);
}

function row(userId, role = 'User', actions = ['change_role', 'remove']) {
    return { userId, displayName: `Name ${userId}`, email: `${userId}@example.test`, role, member_actions: actions };
}

function envelope(overrides = {}) {
    return {
        members: [row('owner', 'Owner', []), row('member')],
        page: 1, page_size: 20, total_count: 2,
        membership_management: { schema_version: 1, operations: ['add_member', 'review_requests'] },
        ...overrides,
    };
}

async function rejects(promise, type) {
    await assert.rejects(promise, (error) => error instanceof type);
}

try {
    await check('a valid member list is read, and unknown hint names are dropped rather than trusted', () => {
        const page = readMemberListPage(envelope({
            members: [row('member', 'User', ['remove', 'promote_to_owner', 'change_role'])],
            membership_management: { schema_version: 1, operations: ['delete_group', 'leave'] },
        }));
        assert.deepEqual(page.members[0].actions, ['change_role', 'remove']);
        assert.deepEqual(page.operations, ['leave']);
        assert.equal(page.pageSize, 20);
        assert.equal(page.totalCount, 2);
    });

    await check('a malformed list envelope, hint or row is a load error, never a partial list', () => {
        for (const broken of [
            null, [], envelope({ members: 'rows' }), envelope({ page: 0 }), envelope({ page_size: 1.5 }),
            envelope({ total_count: -1 }), envelope({ membership_management: undefined }),
            envelope({ membership_management: { schema_version: 2, operations: [] } }),
            envelope({ membership_management: { schema_version: 1, operations: 'add_member' } }),
            envelope({ membership_management: { schema_version: 1, operations: [1] } }),
            envelope({ members: [{ ...row('a'), member_actions: undefined }] }),
            envelope({ members: [{ ...row('a'), member_actions: [7] }] }),
            envelope({ members: [{ ...row('a'), role: 'Superuser' }] }),
            envelope({ members: [{ ...row('a'), userId: '' }] }),
            envelope({ members: [{ ...row('a'), displayName: null }] }),
            envelope({ members: [row('same'), row('same', 'Admin')] }),
        ]) {
            assert.throws(() => readMemberListPage(broken), MembershipResponseError);
        }
    });

    await check('the request list is read strictly', () => {
        const list = readJoinRequests({ requests: [{ userId: 'a', displayName: 'A', email: 'a@x.test' }], total_count: 1 });
        assert.deepEqual(list.requests, [{ userId: 'a', displayName: 'A', email: 'a@x.test' }]);
        for (const broken of [
            { requests: {}, total_count: 0 }, { requests: [], total_count: '0' },
            { requests: [{ displayName: 'A', email: '' }], total_count: 1 },
            { requests: [{ userId: 'a', displayName: 'A', email: '' }, { userId: 'a', displayName: 'B', email: '' }], total_count: 2 },
        ]) {
            assert.throws(() => readJoinRequests(broken), MembershipResponseError);
        }
    });

    await check('the list query carries only the documented parameters', () => {
        assert.equal(memberListParams({ search: '  ada  ', role: 'Admin', page: 2, pageSize: 20 }),
            'search=ada&role=Admin&page=2&page_size=20');
        assert.equal(memberListParams({ search: '   ', role: null, page: 1, pageSize: 20 }), 'page=1&page_size=20');
    });

    await check('every client call sends exactly the documented method, path and body', async () => {
        const client = createGroupMembershipClient('group a');
        answer = (call) => {
            if (call.path.includes('/requests/') && call.path.endsWith('/approve')) return json({ member: row('u 1'), already_member: false });
            if (call.path.endsWith('/reject')) return json({ userId: 'u 1' });
            if (call.path.endsWith('/owner')) return json({ owner: row('u 1', 'Owner', []), changed: true });
            if (call.method === 'PATCH') return json({ member: row('u 1', 'Admin'), changed: true });
            if (call.method === 'DELETE') return json({ userId: 'u 1', left: false });
            if (call.method === 'POST') return json({ member: row('u 1') }, 201);
            if (call.path.includes('/requests')) return json({ requests: [], total_count: 0 });
            return json(envelope());
        };
        await client.list({ search: 'x', role: null, page: 1, pageSize: 20 });
        await client.requests();
        await client.add({ userId: 'u 1', displayName: 'U', email: 'u@x.test', role: 'Admin' });
        await client.changeRole('u 1', 'Admin');
        await client.remove('u 1');
        await client.approve('u 1');
        await client.reject('u 1');
        await client.transfer('u 1');
        const base = '/api/groups/group%20a/membership';
        assert.deepEqual(calls.map(({ method, path, body, contentType }) => [method, path, body, contentType]), [
            ['GET', `${base}/members?search=x&page=1&page_size=20`, null, null],
            ['GET', `${base}/requests`, null, null],
            ['POST', `${base}/members`, JSON.stringify({ userId: 'u 1', displayName: 'U', email: 'u@x.test', role: 'Admin' }), 'application/json'],
            ['PATCH', `${base}/members/u%201`, JSON.stringify({ role: 'Admin' }), 'application/json'],
            ['DELETE', `${base}/members/u%201`, null, null],
            ['POST', `${base}/requests/u%201/approve`, null, null],
            ['POST', `${base}/requests/u%201/reject`, null, null],
            ['PUT', `${base}/owner`, JSON.stringify({ userId: 'u 1' }), 'application/json'],
        ]);
    });

    await check('a write answer that names someone else, or lacks its outcome, is an unknown outcome', async () => {
        const client = createGroupMembershipClient('group-a');
        answer = () => json({ member: row('someone-else'), changed: true });
        await rejects(client.changeRole('u-1', 'Admin'), MembershipResponseError);
        answer = () => json({ userId: 'u-1' });
        await rejects(client.remove('u-1'), MembershipResponseError);
        answer = () => json({ member: row('u-1') });
        await rejects(client.approve('u-1'), MembershipResponseError);
        answer = () => json({ owner: row('u-1', 'Admin'), changed: true });
        await rejects(client.transfer('u-1'), MembershipResponseError);
        answer = () => json({ member: { ...row('u-1'), role: 'Superuser' } }, 201);
        await rejects(client.add({ userId: 'u-1', displayName: '', email: '', role: 'User' }), MembershipResponseError);
        assert.throws(() => createGroupMembershipClient('bad/id'));
    });

    await check('refusals keep the server text and code; anything else is the caller fallback', async () => {
        const client = createGroupMembershipClient('group-a');
        answer = () => json({ error: 'That person is already a member of this group.', error_code: 'already_member' }, 409);
        const refusal = await client.add({ userId: 'u-1', displayName: '', email: '', role: 'User' }).catch((error) => error);
        assert.ok(refusal instanceof ApiError);
        assert.equal(membershipErrorCode(refusal), 'already_member');
        assert.equal(membershipErrorMessage(refusal, 'fallback'), 'That person is already a member of this group.');
        answer = () => new Response('<html>gateway</html>', { status: 502, headers: { 'Content-Type': 'text/html' } });
        const gateway = await client.remove('u-1').catch((error) => error);
        assert.equal(membershipErrorCode(gateway), null);
        assert.equal(membershipErrorMessage(gateway, 'fallback'), 'fallback');
        assert.equal(membershipErrorMessage(new TypeError('Failed to fetch'), 'fallback'), 'fallback');
        const coded = (code, status = 403) => new ApiError('x', status, { error: 'x', error_code: code });
        for (const code of ['membership_permission', 'not_a_member', 'group_not_found', 'group_status_unavailable', 'owner_only']) {
            assert.equal(isTerminalMembershipError(coded(code)), true, code);
        }
        for (const code of ['group_write_conflict', 'user_not_found', 'already_member', 'member_not_found', 'no_pending_request']) {
            assert.equal(isTerminalMembershipError(coded(code)), false, code);
        }
        assert.equal(isTerminalMembershipError(new ApiError('expired', 401, null)), true);
        assert.deepEqual(
            ['membership_permission', 'not_a_member', 'owner_only', 'group_not_found', 'group_write_conflict', 'owner_target']
                .map((code) => isAccessChangedError(coded(code))),
            [true, true, true, true, false, false],
        );
    });

    await check('the people search skips unusable entries and refuses a non-array answer', async () => {
        assert.deepEqual(await searchDirectoryUsers('   '), []);
        assert.equal(calls.length, 0, 'An empty term is never sent.');
        answer = () => json([
            { id: 'u-1', displayName: 'Ada', email: 'ada@x.test' }, { displayName: 'No id' },
            { id: 'u-1', displayName: 'Duplicate', email: '' }, { id: 'u-2', displayName: null, email: null },
        ]);
        assert.deepEqual(await searchDirectoryUsers(" o'hare "), [
            { id: 'u-1', displayName: 'Ada', email: 'ada@x.test' }, { id: 'u-2', displayName: '', email: '' },
        ]);
        assert.equal(calls.at(-1).path, "/api/userSearch?query=o'hare");
        answer = () => json({ value: [] });
        await rejects(searchDirectoryUsers('ada'), MembershipResponseError);
    });

    await check('fallback details the server would refuse are sent empty', () => {
        assert.equal(fallbackMemberText('  Ada Lovelace '), 'Ada Lovelace');
        assert.equal(fallbackMemberText('Bad\u0007Name'), '');
        assert.equal(fallbackMemberText('x'.repeat(256)), 'x'.repeat(256));
        assert.equal(fallbackMemberText('x'.repeat(257)), '');
        assert.equal(fallbackMemberText('\u{1F600}'.repeat(256)), '\u{1F600}'.repeat(256), 'Code points, not UTF-16 units.');
        assert.equal(memberDisplayName({ displayName: ' ', email: 'e@x.test', userId: 'u' }), 'e@x.test');
        assert.equal(memberDisplayName({ displayName: '', email: '', userId: 'u' }), 'u');
    });

    await check('the CSV parser follows the classic format, rules and messages', () => {
        const guid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
        const ok = parseMemberCsv(`\ufeffuserId,displayName,email,role\r\n${guid(1)},Ada,ada@x.test,USER\r\n\r\n${guid(2)}, Bob ,bob@x.test,document_manager\n${guid(3)},Cy,cy@x.test,admin\n`);
        assert.deepEqual(ok.errors, []);
        assert.deepEqual(ok.rows.map(({ row, userId, displayName, role }) => [row, userId, displayName, role]), [
            [2, guid(1), 'Ada', 'User'], [3, guid(2), 'Bob', 'DocumentManager'], [4, guid(3), 'Cy', 'Admin'],
        ]);
        assert.deepEqual(parseMemberCsv('userId,displayName,email,role\n').errors,
            ['CSV must contain at least a header row and one data row']);
        assert.deepEqual(parseMemberCsv('id,name,email,role\nx,y,z,user').errors,
            ['Invalid header. Expected: userId,displayName,email,role']);
        const many = ['userId,displayName,email,role', ...Array.from({ length: 1001 }, (_, i) => `${guid(i)},N,n@x.test,user`)];
        assert.deepEqual(parseMemberCsv(many.join('\n')).errors, ['Too many rows. Maximum 1,000 members allowed (found 1001)']);
        assert.equal(parseMemberCsv(many.slice(0, 1001).join('\n')).rows.length, 1000);
        const bad = parseMemberCsv([
            'userId,displayName,email,role',
            `${guid(1)},"Smith, Ada",ada@x.test,user`, `${guid(2)},,b@x.test,user`, 'not-a-guid,N,n@x.test,user',
            `${guid(3)},N,not-an-email,user`, `${guid(4)},N,n@x.test,owner`, `${guid(5)},N,n@x.test,constructor`,
            `${guid(6)},Fine,fine@x.test,user`,
        ].join('\n'));
        assert.deepEqual(bad.rows, [], 'Any problem refuses the whole file, as the classic page does.');
        assert.deepEqual(bad.errors, [
            'Row 2: Expected 4 columns, found 5', 'Row 3: All fields are required',
            'Row 4: Invalid GUID format for userId', 'Row 5: Invalid email format',
            "Row 6: Invalid role 'owner'. Must be: user, admin, or document_manager",
            "Row 7: Invalid role 'constructor'. Must be: user, admin, or document_manager",
        ]);
    });

    console.log(`${checks} group membership logic checks passed.`);
} finally {
    globalThis.fetch = originalFetch;
}
