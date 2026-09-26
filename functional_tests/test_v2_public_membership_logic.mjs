// test_v2_public_membership_logic.mjs
// Version: 0.261.179
// Implemented in: 0.261.179
// Executes the real V2 public membership adapter (createPublicMembershipClient in
// lib/groupMembership.ts): the public routes each call sends, the strict envelope readers reused
// from the group client, the public delete answer that carries no `left`, the public-flavoured
// unexpected-answer text, the public assignable roles, and the refusal helpers extended for the
// public error codes. Sits beside test_v2_group_membership_logic.mjs and pins that the two
// clients share one implementation without the public client leaking group vocabulary.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const membership = await import('../application/v2_ui/src/lib/groupMembership.ts');
const { ApiError } = await import('../application/v2_ui/src/lib/apiClient.ts');
const {
    createPublicMembershipClient, isAccessChangedError, isTerminalMembershipError,
    isPublicAssignableMemberRole, membershipErrorCode, membershipErrorMessage,
    PUBLIC_ASSIGNABLE_MEMBER_ROLES, PUBLIC_ASSIGNABLE_ROLE_OPTIONS, MembershipResponseError,
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

function row(userId, role = 'DocumentManager', actions = ['change_role', 'remove']) {
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
    await check('every public client call sends exactly the public method, path and body', async () => {
        const client = createPublicMembershipClient('ws a');
        answer = (call) => {
            if (call.path.includes('/requests/') && call.path.endsWith('/approve')) return json({ member: row('u 1'), already_member: false });
            if (call.path.endsWith('/reject')) return json({ userId: 'u 1' });
            if (call.path.endsWith('/owner')) return json({ owner: row('u 1', 'Owner', []), changed: true });
            if (call.method === 'PATCH') return json({ member: row('u 1', 'Admin'), changed: true });
            if (call.method === 'DELETE') return json({ userId: 'u 1' });
            if (call.method === 'POST') return json({ member: row('u 1') }, 201);
            if (call.path.includes('/requests')) return json({ requests: [], total_count: 0 });
            return json(envelope());
        };
        await client.list({ search: 'x', role: null, page: 1, pageSize: 20 });
        await client.requests();
        await client.add({ userId: 'u 1', displayName: 'U', email: 'u@x.test', role: 'Admin' });
        await client.changeRole('u 1', 'Admin');
        const removed = await client.remove('u 1');
        await client.approve('u 1');
        await client.reject('u 1');
        await client.transfer('u 1');
        assert.deepEqual(removed, { userId: 'u 1', left: false }, 'Public delete synthesises left:false.');
        const base = '/api/public-workspaces/ws%20a/membership';
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

    await check('a public write answer that names someone else, or lacks its outcome, is unknown', async () => {
        const client = createPublicMembershipClient('ws-a');
        answer = () => json({ member: row('someone-else'), changed: true });
        await rejects(client.changeRole('u-1', 'Admin'), MembershipResponseError);
        answer = () => json({ member: row('u-1') });
        await rejects(client.approve('u-1'), MembershipResponseError);
        answer = () => json({ owner: row('u-1', 'Admin'), changed: true });
        await rejects(client.transfer('u-1'), MembershipResponseError);
        answer = () => json({ userId: 'someone-else' });
        await rejects(client.remove('u-1'), MembershipResponseError);
        answer = () => json({ member: { ...row('u-1'), role: 'Superuser' } }, 201);
        await rejects(client.add({ userId: 'u-1', displayName: '', email: '', role: 'Admin' }), MembershipResponseError);
        assert.throws(() => createPublicMembershipClient('bad/id'));
    });

    await check('a malformed public write is refused with the public unexpected-answer text', async () => {
        const client = createPublicMembershipClient('ws-a');
        answer = () => json({ notMember: true }, 201);
        const refusal = await client.add({ userId: 'u-1', displayName: '', email: '', role: 'Admin' }).catch((error) => error);
        assert.ok(refusal instanceof MembershipResponseError);
        assert.match(refusal.message, /public workspace/);
        assert.ok(!/\bgroup\b/i.test(refusal.message), 'The public text never says "group".');
    });

    await check('public refusals keep the server text and code; public terminal codes are terminal', async () => {
        const client = createPublicMembershipClient('ws-a');
        answer = () => json({ error: 'That person is already a member of this workspace.', error_code: 'already_member' }, 409);
        const refusal = await client.add({ userId: 'u-1', displayName: '', email: '', role: 'Admin' }).catch((error) => error);
        assert.ok(refusal instanceof ApiError);
        assert.equal(membershipErrorCode(refusal), 'already_member');
        assert.equal(membershipErrorMessage(refusal, 'fallback'), 'That person is already a member of this workspace.');
        const coded = (code, status = 403) => new ApiError('x', status, { error: 'x', error_code: code });
        for (const code of ['membership_permission', 'not_a_member', 'workspace_not_found', 'public_status_unavailable', 'owner_only']) {
            assert.equal(isTerminalMembershipError(coded(code)), true, code);
        }
        for (const code of ['already_member', 'member_not_found', 'no_pending_request', 'owner_target']) {
            assert.equal(isTerminalMembershipError(coded(code)), false, code);
        }
        assert.equal(isTerminalMembershipError(new ApiError('expired', 401, null)), true);
        assert.deepEqual(
            ['membership_permission', 'not_a_member', 'owner_only', 'workspace_not_found', 'owner_target']
                .map((code) => isAccessChangedError(coded(code))),
            [true, true, true, true, false],
        );
    });

    await check('the public assignable roles are Admin and DocumentManager only, with labels', () => {
        assert.deepEqual([...PUBLIC_ASSIGNABLE_MEMBER_ROLES], ['Admin', 'DocumentManager']);
        assert.deepEqual(PUBLIC_ASSIGNABLE_ROLE_OPTIONS.map((option) => option.value), ['DocumentManager', 'Admin']);
        for (const option of PUBLIC_ASSIGNABLE_ROLE_OPTIONS) {
            assert.ok(option.label.trim(), `${option.value} has a label.`);
            assert.ok(!/^(DocumentManager|User)$/.test(option.label), 'No raw role token leaks as a label.');
        }
        assert.equal(isPublicAssignableMemberRole('Admin'), true);
        assert.equal(isPublicAssignableMemberRole('DocumentManager'), true);
        assert.equal(isPublicAssignableMemberRole('User'), false, 'User is not publicly assignable.');
        assert.equal(isPublicAssignableMemberRole('Owner'), false);
    });

    console.log(`${checks} public membership logic checks passed.`);
} finally {
    globalThis.fetch = originalFetch;
}
