// test_v2_user_agreement_gate_logic.ts
//
// Runtime test for the V2 user agreement client: how a scope is named to the server, when an upload is
// asked about at all, how an answer is read, what the two routes are sent, and, for the gate hook, when
// `pending` is raised and that it is lowered on every way a gate can end.
// Version: 0.261.448
// Implemented in: 0.261.448
//
// The judgement calls here do not show in a screenshot: that chat and personal uploads name the
// workspace `default` exactly as classic does (so a once-a-day acceptance made in either interface
// counts in the other), that a group or public upload without a workspace id is refused rather than
// skipped, that an answer which cannot be read is a failed check and never "no agreement", and that an
// acceptance counts only when the server says it was recorded. Each is executed here.
//
// So is the other half of the composer's Send hold. A file waits on the agreement before it has a chip,
// and the composer holds Send from `pending` alone for that wait. If `pending` were ever raised for a gate
// that was answered at once, Send would flicker; if it stayed raised after a gate ended, Send would stay
// held for good. The hook runs here, as it ships, on the small hooks runtime in
// test_support/miniReactHooks.ts, which the bundle aliases in place of `react`.
//
// And the time limit. A check or an acceptance that never answers is a failure after twenty seconds, not a
// wait without end. The limit's own timer is the only one the checks take over (limitClock), so nothing
// here waits twenty seconds: the time is let run out, and what the request, the hook and the message do
// next is executed.
//
// Run by test_v2_user_agreement_gate.py, which bundles this with the esbuild Vite already brings in and
// executes it under node. `fetch` is replaced so no request leaves the process.

import assert from 'node:assert/strict';
import { ApiError } from '../application/v2_ui/src/lib/apiClient';
import {
    ACCEPT_FAILED_MESSAGE,
    AGREEMENT_PENDING_MESSAGE,
    CHAT_AGREEMENT_SCOPE,
    CHECK_FAILED_MESSAGE,
    USER_AGREEMENT_ACCEPT_PATH,
    USER_AGREEMENT_CHECK_PATH,
    USER_AGREEMENT_REQUEST_TIMEOUT_MS,
    UserAgreementTimeoutError,
    acceptUserAgreement,
    agreementFailureMessage,
    agreementGateDecision,
    agreementWorkspaceId,
    checkUserAgreement,
    parseUserAgreementCheck,
    userAgreementAcceptBody,
    userAgreementCheckPath,
    userAgreementSwitchedOn,
    workspaceAgreementScope,
} from '../application/v2_ui/src/lib/userAgreement';
import { useUserAgreementGate, type UserAgreementGate } from '../application/v2_ui/src/lib/useUserAgreementGate';
import { useBootstrapStore } from '../application/v2_ui/src/stores/bootstrapStore';
import { renderHook, type RenderedHook } from './test_support/miniReactHooks';

const checks: [string, () => void | Promise<void>][] = [];
function check(name: string, fn: () => void | Promise<void>) {
    checks.push([name, fn]);
}

interface Call {
    url: string;
    init: RequestInit;
}

function mockFetch(responder: (call: Call) => Response | Promise<Response>): Call[] {
    const calls: Call[] = [];
    globalThis.fetch = (async (url: string | URL | Request, init: RequestInit = {}) => {
        const call = { url: String(url), init };
        calls.push(call);
        return responder(call);
    }) as typeof fetch;
    return calls;
}

function json(payload: unknown, status = 200): Response {
    return new Response(JSON.stringify(payload), { status, headers: { 'content-type': 'application/json' } });
}

/** Let the event loop turn until `condition` holds, so a request that starts after a few awaits can be waited for. */
async function until(condition: () => boolean, what: string): Promise<void> {
    for (let turn = 0; turn < 200; turn += 1) {
        if (condition()) {
            return;
        }
        await new Promise<void>((resolve) => setImmediate(resolve));
    }
    throw new Error(`gave up waiting for ${what}`);
}

/**
 * Takes over the time limit a check or an acceptance sets, and only that one: any other timer is the real thing.
 * A test lets the time run out with `expire()`, and sees with `armed` whether a limit is still running.
 */
function limitClock() {
    const realSet = globalThis.setTimeout;
    const realClear = globalThis.clearTimeout;
    const limits = new Map<number, () => void>();
    const delays: unknown[] = [];
    let next = 0;
    globalThis.setTimeout = ((handler: () => void, delay?: number, ...rest: unknown[]) => {
        if (delay === USER_AGREEMENT_REQUEST_TIMEOUT_MS) {
            next += 1;
            limits.set(next, handler);
            delays.push(delay);
            return next as unknown as ReturnType<typeof setTimeout>;
        }
        return realSet(handler, delay, ...rest);
    }) as typeof setTimeout;
    globalThis.clearTimeout = ((id?: ReturnType<typeof setTimeout>) => {
        if (typeof id === 'number' && limits.has(id)) {
            limits.delete(id);
            return;
        }
        realClear(id);
    }) as typeof clearTimeout;
    return {
        /** Limits that were set and have neither fired nor been cleared. */
        get armed() {
            return limits.size;
        },
        /** Every limit that was ever set, by the delay it was given. */
        get delays() {
            return delays;
        },
        /** Let the time run out. */
        expire() {
            for (const [id, handler] of [...limits]) {
                limits.delete(id);
                handler();
            }
        },
        restore() {
            globalThis.setTimeout = realSet;
            globalThis.clearTimeout = realClear;
        },
    };
}

check('chat and personal uploads name the workspace `default`, as classic does', () => {
    assert.equal(agreementWorkspaceId({ type: 'chat' }), 'default');
    assert.equal(agreementWorkspaceId({ type: 'personal' }), 'default');
    // An id handed to either is ignored: both interfaces must record the same workspace.
    assert.equal(agreementWorkspaceId({ type: 'chat', id: 'conv-1' }), 'default');
    assert.equal(agreementWorkspaceId({ type: 'personal', id: 'viewer-1' }), 'default');
});

check('group and public uploads name their own workspace, and one without an id is refused', () => {
    assert.equal(agreementWorkspaceId({ type: 'group', id: 'group-a' }), 'group-a');
    assert.equal(agreementWorkspaceId({ type: 'public', id: '  public-a ' }), 'public-a');
    for (const scope of [{ type: 'group' }, { type: 'public', id: '' }, { type: 'group', id: '   ' }] as const) {
        assert.throws(() => agreementWorkspaceId(scope), /workspace id is required/, JSON.stringify(scope));
    }
});

check('the explorer scope maps to the route scope, personal without an id', () => {
    assert.deepEqual(workspaceAgreementScope({ kind: 'personal' }), { type: 'personal' });
    assert.deepEqual(workspaceAgreementScope({ kind: 'group', id: 'group-a' }), { type: 'group', id: 'group-a' });
    assert.deepEqual(workspaceAgreementScope({ kind: 'public', id: 'public-a' }), { type: 'public', id: 'public-a' });
    assert.ok(Object.isFrozen(CHAT_AGREEMENT_SCOPE));
    assert.deepEqual({ ...CHAT_AGREEMENT_SCOPE }, { type: 'chat' });
});

check('the check URL carries the three parameters classic sends, encoded', () => {
    assert.equal(
        userAgreementCheckPath({ type: 'chat' }),
        '/api/user_agreement/check?workspace_type=chat&workspace_id=default&action_context=file_upload',
    );
    assert.equal(
        userAgreementCheckPath({ type: 'group', id: 'group-a' }),
        '/api/user_agreement/check?workspace_type=group&workspace_id=group-a&action_context=file_upload',
    );
    // An id is data, never part of the query's structure.
    assert.equal(
        userAgreementCheckPath({ type: 'public', id: 'a&workspace_type=chat b' }),
        '/api/user_agreement/check?workspace_type=public&workspace_id=a%26workspace_type%3Dchat+b&action_context=file_upload',
    );
    assert.ok(userAgreementCheckPath({ type: 'personal' }).startsWith(`${USER_AGREEMENT_CHECK_PATH}?`));
});

check('the acceptance body carries the same three fields', () => {
    assert.deepEqual(userAgreementAcceptBody({ type: 'personal' }), {
        workspace_type: 'personal', workspace_id: 'default', action_context: 'file_upload',
    });
    assert.deepEqual(userAgreementAcceptBody({ type: 'public', id: 'public-a' }), {
        workspace_type: 'public', workspace_id: 'public-a', action_context: 'file_upload',
    });
});

check('only an explicit off, or no value, means the administrator has not switched it on', () => {
    for (const settings of [undefined, null, {}, { enable_user_agreement: false }, { enable_user_agreement: null }]) {
        assert.equal(userAgreementSwitchedOn(settings), false, JSON.stringify(settings));
    }
    // Anything else is possibly on, so the server decides rather than a guess made here.
    for (const value of [true, 'true', 'yes', 1, 0, '', {}]) {
        assert.equal(userAgreementSwitchedOn({ enable_user_agreement: value }), true, JSON.stringify(value));
    }
});

check('nothing is asked when there is nothing to upload, or when the feature is off', () => {
    const on = { enable_user_agreement: true };
    assert.equal(agreementGateDecision(on, 0), 'nothing');
    assert.equal(agreementGateDecision(on, -1), 'nothing');
    assert.equal(agreementGateDecision(on, Number.NaN), 'nothing');
    assert.equal(agreementGateDecision({}, 0), 'nothing');
    assert.equal(agreementGateDecision({}, 3), 'proceed');
    assert.equal(agreementGateDecision(undefined, 1), 'proceed');
    assert.equal(agreementGateDecision({ enable_user_agreement: false }, 2), 'proceed');
    assert.equal(agreementGateDecision(on, 1), 'check');
    assert.equal(agreementGateDecision(on, 12), 'check');
});

check('an answer is read only when it clearly says whether an agreement applies', () => {
    assert.deepEqual(
        parseUserAgreementCheck({ needsAgreement: true, agreementText: '## Terms', enableDailyAcceptance: true }),
        { needsAgreement: true, agreementText: '## Terms', enableDailyAcceptance: true },
    );
    assert.deepEqual(
        parseUserAgreementCheck({ needsAgreement: false, agreementText: '', enableDailyAcceptance: true, alreadyAcceptedToday: true }),
        { needsAgreement: false, agreementText: '', enableDailyAcceptance: true },
    );
    // Optional fields fall back safely; a daily flag is only ever an explicit true.
    assert.deepEqual(parseUserAgreementCheck({ needsAgreement: true }), {
        needsAgreement: true, agreementText: '', enableDailyAcceptance: false,
    });
    assert.equal(parseUserAgreementCheck({ needsAgreement: true, enableDailyAcceptance: 'yes' }).enableDailyAcceptance, false);
    assert.equal(parseUserAgreementCheck({ needsAgreement: true, agreementText: 42 }).agreementText, '');
});

check('an unreadable answer is never "no agreement"', () => {
    for (const payload of [undefined, null, [], '<html>proxy error</html>', {}, { error: 'x' },
        { needsAgreement: 'false' }, { needsAgreement: 0 }, { needsAgreement: null }, { NeedsAgreement: false }]) {
        assert.throws(() => parseUserAgreementCheck(payload), /unexpected answer/, JSON.stringify(payload));
    }
});

check('the check is a no-store GET of the check route, and resolves the parsed answer', async () => {
    const calls = mockFetch(() => json({ needsAgreement: true, agreementText: '## Terms', enableDailyAcceptance: true }));
    const answer = await checkUserAgreement({ type: 'group', id: 'group-a' });
    assert.deepEqual(answer, { needsAgreement: true, agreementText: '## Terms', enableDailyAcceptance: true });
    assert.equal(calls.length, 1);
    assert.equal(
        calls[0].url,
        '/api/user_agreement/check?workspace_type=group&workspace_id=group-a&action_context=file_upload',
    );
    assert.equal(calls[0].init.method, 'GET');
    assert.equal(calls[0].init.cache, 'no-store');
    assert.equal(calls[0].init.body, undefined);
});

check('a check that fails or cannot be read rejects instead of resolving "no agreement"', async () => {
    const answers: (() => Response)[] = [
        () => json({ error: 'Internal error' }, 500),
        () => json({ error: 'workspace_id and workspace_type are required' }, 400),
        () => json({ error: 'Unauthorized' }, 401),
        () => json({ unrelated: true }),
        () => new Response('<html>Bad gateway</html>', { status: 200, headers: { 'content-type': 'text/html' } }),
    ];
    for (const answer of answers) {
        mockFetch(() => answer());
        await assert.rejects(() => checkUserAgreement({ type: 'personal' }));
    }
    mockFetch(() => {
        throw new TypeError('Failed to fetch');
    });
    await assert.rejects(() => checkUserAgreement({ type: 'chat' }), /Failed to fetch/);
});

check('a group check without a workspace id never reaches the network', async () => {
    const calls = mockFetch(() => json({ needsAgreement: false }));
    await assert.rejects(() => checkUserAgreement({ type: 'group' }), /workspace id is required/);
    assert.equal(calls.length, 0);
});

check('the acceptance is a JSON POST to the accept route and counts only on success: true', async () => {
    const calls = mockFetch(() => json({ success: true, message: 'User agreement acceptance recorded' }));
    await acceptUserAgreement({ type: 'public', id: 'public-a' });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, USER_AGREEMENT_ACCEPT_PATH);
    assert.equal(calls[0].init.method, 'POST');
    assert.deepEqual(JSON.parse(String(calls[0].init.body)), {
        workspace_type: 'public', workspace_id: 'public-a', action_context: 'file_upload',
    });
    const headers = new Headers(calls[0].init.headers);
    assert.equal(headers.get('content-type'), 'application/json');
});

check('an acceptance the server did not confirm rejects', async () => {
    const answers: (() => Response)[] = [
        () => json({ success: false, error: 'Failed to record acceptance' }, 500),
        () => json({ success: false }),
        () => json({}),
        () => json({ success: 'true' }),
        () => json(null),
        () => new Response('ok', { status: 200, headers: { 'content-type': 'text/plain' } }),
    ];
    for (const answer of answers) {
        mockFetch(() => answer());
        await assert.rejects(() => acceptUserAgreement({ type: 'chat' }));
    }
});

check('a request carries a signal of its own, which the caller can still abort while it is out', async () => {
    const clock = limitClock();
    try {
        const controller = new AbortController();
        const network = heldFetch();
        const pending = checkUserAgreement({ type: 'chat' }, controller.signal);
        await until(() => network.calls.length === 1, 'the request');
        const given = network.calls[0].init.signal as AbortSignal;
        assert.ok(given instanceof AbortSignal);
        assert.notEqual(given, controller.signal, 'the limit needs a controller of its own');
        assert.equal(given.aborted, false);
        controller.abort();
        // The gate abandons a request this way when its owner goes away.
        assert.equal(given.aborted, true);
        await assert.rejects(pending, (error: Error) => error.name === 'AbortError');
        assert.equal(clock.armed, 0, 'no limit is left running once the request is over');
    } finally {
        clock.restore();
    }
});

check('a failure is worded so that no one thinks the upload went ahead', () => {
    assert.match(CHECK_FAILED_MESSAGE, /nothing was uploaded/);
    assert.match(ACCEPT_FAILED_MESSAGE, /nothing was uploaded/);
    assert.equal(agreementFailureMessage('check', new Error('Failed to fetch')), CHECK_FAILED_MESSAGE);
    assert.equal(agreementFailureMessage('accept', new Error('boom')), ACCEPT_FAILED_MESSAGE);
    assert.equal(
        agreementFailureMessage('check', new ApiError('Internal error', 503, null)),
        `${CHECK_FAILED_MESSAGE} (status 503)`,
    );
    // The server's own text is never echoed into the dialog.
    assert.ok(!agreementFailureMessage('accept', new ApiError('SELECT * FROM c leaked', 500, null)).includes('SELECT'));
});

// The gate hook ----------------------------------------------------------------------------------------

const CHAT = { type: 'chat' } as const;
const NO_AGREEMENT = { needsAgreement: false, agreementText: '', enableDailyAcceptance: false };
const AGREEMENT = { needsAgreement: true, agreementText: '## Terms', enableDailyAcceptance: false };

function switchOn(): void {
    useBootstrapStore.setState({ data: { settings: { enable_user_agreement: true } } as never });
}

function chatFile(name = 'policy.txt'): File {
    return new File(['Quarterly policy text.'], name, { type: 'text/plain' });
}

/** A fetch that answers only when the test says so, in the order the requests were made. */
function heldFetch() {
    const held: { resolve: (response: Response) => void }[] = [];
    const calls = mockFetch((call) => new Promise<Response>((resolve, reject) => {
        const aborted = () => new DOMException('The operation was aborted.', 'AbortError');
        // As fetch does: a signal that is already aborted rejects at once.
        if (call.init.signal?.aborted) {
            reject(aborted());
            return;
        }
        const entry = { resolve };
        held.push(entry);
        call.init.signal?.addEventListener('abort', () => {
            const at = held.indexOf(entry);
            if (at >= 0) {
                held.splice(at, 1);
            }
            reject(aborted());
        });
    }));
    return {
        calls,
        waiting: () => held.length,
        answer: (payload: unknown, status = 200) => {
            const next = held.shift();
            assert.ok(next, 'no request was waiting to be answered');
            next.resolve(json(payload, status));
        },
    };
}

type Gate = RenderedHook<UserAgreementGate>;

/** The values `pending` took across the renders, with repeats folded, so a dip shows as a dip. */
function timeline(gate: Gate): boolean[] {
    return gate.renders.map((render) => render.pending).filter((value, index, all) => index === 0 || value !== all[index - 1]);
}

function openGate(): { gate: Gate; network: ReturnType<typeof heldFetch> } {
    switchOn();
    const network = heldFetch();
    return { gate: renderHook(() => useUserAgreementGate()), network };
}

check('pending is never raised for a gate that is answered at once: the switch is off, or there is nothing to upload', async () => {
    const calls = mockFetch(() => json(AGREEMENT));
    for (const settings of [undefined, {}, { enable_user_agreement: false }, { enable_user_agreement: null }]) {
        useBootstrapStore.setState({ data: { settings } as never });
        const gate = renderHook(() => useUserAgreementGate());
        assert.equal(await gate.current.confirm(CHAT, [chatFile()]), true, JSON.stringify(settings));
        assert.equal(await gate.current.confirm(CHAT, []), false, 'nothing to upload');
        await gate.flush();
        // Nothing changed state, so nothing rendered again: Send cannot have flickered.
        assert.equal(gate.renders.length, 1, JSON.stringify(settings));
        assert.equal(gate.current.pending, false);
        gate.unmount();
    }
    switchOn();
    const gate = renderHook(() => useUserAgreementGate());
    assert.equal(await gate.current.confirm(CHAT, []), false, 'switched on, but nothing to upload');
    await gate.flush();
    assert.equal(gate.renders.length, 1);
    assert.equal(calls.length, 0, 'nothing was asked of the server');
});

check('pending is raised from the moment a gate is queued, and lowered when no agreement applies', async () => {
    const { gate, network } = openGate();
    const answer = gate.current.confirm(CHAT, [chatFile()]);
    await gate.flush();
    assert.equal(gate.current.pending, true, 'the check is in flight');
    assert.equal(gate.current.prompt, null, 'there is nothing to show yet');
    network.answer(NO_AGREEMENT);
    assert.equal(await answer, true);
    await gate.flush();
    assert.equal(gate.current.pending, false);
    assert.deepEqual(timeline(gate), [false, true, false]);
});

check('two gates that overlap keep pending raised until both have settled', async () => {
    const { gate, network } = openGate();
    const first = gate.current.confirm(CHAT, [chatFile('a.txt')]);
    const second = gate.current.confirm(CHAT, [chatFile('b.txt')]);
    await gate.flush();
    assert.equal(network.waiting(), 1, 'the second gate waits behind the first');
    network.answer(NO_AGREEMENT);
    assert.equal(await first, true);
    await gate.flush();
    assert.equal(gate.current.pending, true, 'the second file is still on its way');
    assert.equal(network.waiting(), 1, 'the second gate now makes its check');
    network.answer(NO_AGREEMENT);
    assert.equal(await second, true);
    await gate.flush();
    assert.equal(gate.current.pending, false);
    assert.deepEqual(timeline(gate), [false, true, false], 'pending never dipped between the two gates');
});

check('pending stays raised while the dialog is open, and Accept lowers it once the acceptance is recorded', async () => {
    const { gate, network } = openGate();
    const answer = gate.current.confirm(CHAT, [chatFile()]);
    await gate.flush();
    network.answer(AGREEMENT);
    await gate.flush();
    assert.equal(gate.current.prompt?.kind, 'agreement');
    assert.equal(gate.current.pending, true, 'the file is waiting on the person');
    gate.current.accept();
    await gate.flush();
    assert.equal(gate.current.prompt?.busy, true);
    assert.equal(gate.current.pending, true, 'the acceptance is still being recorded');
    network.answer({ success: true });
    assert.equal(await answer, true);
    await gate.flush();
    assert.equal(gate.current.prompt, null);
    assert.equal(gate.current.pending, false);
    assert.deepEqual(timeline(gate), [false, true, false]);
});

check('a failed acceptance keeps the dialog and pending until it is accepted again or cancelled', async () => {
    const { gate, network } = openGate();
    const answer = gate.current.confirm(CHAT, [chatFile()]);
    await gate.flush();
    network.answer(AGREEMENT);
    await gate.flush();
    gate.current.accept();
    await gate.flush();
    network.answer({ success: false }, 500);
    await gate.flush();
    assert.equal(gate.current.prompt?.busy, false);
    assert.equal(gate.current.prompt?.error, ACCEPT_FAILED_MESSAGE + ' (status 500)');
    assert.equal(gate.current.pending, true, 'the gate has not ended');
    gate.current.accept();
    await gate.flush();
    network.answer({ success: true });
    assert.equal(await answer, true);
    await gate.flush();
    assert.equal(gate.current.pending, false);
    assert.deepEqual(timeline(gate), [false, true, false]);

    const second = gate.current.confirm(CHAT, [chatFile()]);
    await gate.flush();
    network.answer(AGREEMENT);
    await gate.flush();
    gate.current.accept();
    await gate.flush();
    network.answer({ success: false }, 500);
    await gate.flush();
    gate.current.cancel();
    assert.equal(await second, false, 'a failed acceptance can still be cancelled');
    await gate.flush();
    assert.equal(gate.current.pending, false);
});

check('Cancel lowers pending, and is ignored while an acceptance is being recorded', async () => {
    const { gate, network } = openGate();
    const declined = gate.current.confirm(CHAT, [chatFile()]);
    await gate.flush();
    network.answer(AGREEMENT);
    await gate.flush();
    gate.current.cancel();
    assert.equal(await declined, false);
    await gate.flush();
    assert.equal(gate.current.pending, false);
    assert.equal(gate.current.prompt, null);

    const accepted = gate.current.confirm(CHAT, [chatFile()]);
    let settled = false;
    void accepted.then(() => {
        settled = true;
    });
    await gate.flush();
    network.answer(AGREEMENT);
    await gate.flush();
    gate.current.accept();
    await gate.flush();
    gate.current.cancel();
    await gate.flush();
    assert.equal(settled, false, 'Cancel did not end a gate whose acceptance is in flight');
    assert.equal(gate.current.pending, true);
    network.answer({ success: true });
    assert.equal(await accepted, true);
    await gate.flush();
    assert.equal(gate.current.pending, false);
});

check('a failed check holds the upload with pending raised until it is tried again or cancelled', async () => {
    const { gate, network } = openGate();
    const retried = gate.current.confirm(CHAT, [chatFile()]);
    await gate.flush();
    network.answer({ error: 'Internal error' }, 500);
    await gate.flush();
    assert.equal(gate.current.prompt?.kind, 'unavailable');
    assert.equal(gate.current.pending, true, 'a check that failed is not an answer');
    gate.current.accept();
    await gate.flush();
    assert.equal(gate.current.pending, true, 'the second check is in flight');
    network.answer(NO_AGREEMENT);
    assert.equal(await retried, true);
    await gate.flush();
    assert.equal(gate.current.pending, false);
    assert.deepEqual(timeline(gate), [false, true, false]);

    const cancelled = gate.current.confirm(CHAT, [chatFile()]);
    await gate.flush();
    network.answer({ unexpected: 'shape' });
    await gate.flush();
    assert.equal(gate.current.prompt?.kind, 'unavailable', 'an unreadable answer is a failed check');
    gate.current.cancel();
    assert.equal(await cancelled, false);
    await gate.flush();
    assert.equal(gate.current.pending, false);
});

check('withAgreement does its work only when the gate allows it, and pending is lowered either way', async () => {
    const { gate, network } = openGate();
    const ran: string[][] = [];
    const work = (files: File[]) => {
        ran.push(files.map((file) => file.name));
    };
    const allowed = gate.current.withAgreement(CHAT, [chatFile('a.txt')], work);
    await gate.flush();
    network.answer(NO_AGREEMENT);
    assert.equal(await allowed, true);
    assert.deepEqual(ran, [['a.txt']]);
    await gate.flush();
    assert.equal(gate.current.pending, false);

    const declined = gate.current.withAgreement(CHAT, [chatFile('b.txt')], work);
    await gate.flush();
    network.answer(AGREEMENT);
    await gate.flush();
    gate.current.cancel();
    assert.equal(await declined, false);
    assert.deepEqual(ran, [['a.txt']], 'a declined gate never ran the work');
    await gate.flush();
    assert.equal(gate.current.pending, false);
});

check('unmounting settles every gate, the queued ones too, and makes no state change afterwards', async () => {
    const { gate, network } = openGate();
    const first = gate.current.confirm(CHAT, [chatFile('a.txt')]);
    const second = gate.current.confirm(CHAT, [chatFile('b.txt')]);
    const third = gate.current.confirm(CHAT, [chatFile('c.txt')]);
    await gate.flush();
    network.answer(AGREEMENT);
    await gate.flush();
    assert.equal(gate.current.pending, true);
    assert.equal(network.calls.length, 1, 'the dialog of the first is open; the others wait their turn');
    gate.unmount();
    assert.deepEqual(await Promise.all([first, second, third]), [false, false, false]);
    assert.equal(network.calls.length, 1, 'the gates that were waiting made no request');
    assert.equal(gate.updatesAfterUnmount, 0, 'no state was set once the owner had gone');
    // The count reached zero: when the owner is shown again the flag is read afresh, not left raised.
    await gate.show();
    assert.equal(gate.current.pending, false);
    assert.equal(gate.current.prompt, null);
});

check('unmounting while the check is in flight abandons the request and settles the gate', async () => {
    const { gate, network } = openGate();
    const answer = gate.current.confirm(CHAT, [chatFile()]);
    await gate.flush();
    assert.equal(network.waiting(), 1);
    gate.unmount();
    assert.equal(await answer, false);
    assert.equal(network.waiting(), 0, 'the request was aborted');
    assert.equal(gate.updatesAfterUnmount, 0);
});

check('a gate that settled while the owner was hidden does not leave pending raised when it is shown again', async () => {
    const { gate, network } = openGate();
    const answer = gate.current.confirm(CHAT, [chatFile()]);
    await gate.flush();
    assert.equal(gate.current.pending, true);
    gate.hide();
    assert.equal(await answer, false);
    assert.equal(network.waiting(), 0);
    await gate.show();
    assert.equal(gate.current.pending, false, 'the last render said true; the mount effect corrects it');
    // And it works as before.
    const again = gate.current.confirm(CHAT, [chatFile()]);
    await gate.flush();
    assert.equal(gate.current.pending, true);
    network.answer(NO_AGREEMENT);
    assert.equal(await again, true);
    await gate.flush();
    assert.equal(gate.current.pending, false);
});

check('a gate asked of an owner that has gone settles false without a request and leaves pending down', async () => {
    switchOn();
    const calls = mockFetch(() => json(NO_AGREEMENT));
    const gate = renderHook(() => useUserAgreementGate());
    const { confirm } = gate.current;
    gate.unmount();
    assert.equal(await confirm(CHAT, [chatFile()]), false);
    assert.equal(calls.length, 0);
    assert.equal(gate.updatesAfterUnmount, 0);
    await gate.show();
    assert.equal(gate.current.pending, false);
});

check('a strict-mode remount leaves the gate working and pending down', async () => {
    const { gate, network } = openGate();
    await gate.restartEffects();
    assert.equal(gate.current.pending, false);
    const answer = gate.current.confirm(CHAT, [chatFile()]);
    await gate.flush();
    assert.equal(gate.current.pending, true);
    network.answer(NO_AGREEMENT);
    assert.equal(await answer, true);
    await gate.flush();
    assert.equal(gate.current.pending, false);
});

check('the wording of a held Send says what is being waited for', () => {
    assert.match(AGREEMENT_PENDING_MESSAGE, /user agreement/i);
    assert.match(AGREEMENT_PENDING_MESSAGE, /attaching your file/i);
});

// The time limit -----------------------------------------------------------------------------------------

check('the limit is one named constant of twenty seconds, set on every request and in no other length', async () => {
    assert.equal(USER_AGREEMENT_REQUEST_TIMEOUT_MS, 20_000);
    const clock = limitClock();
    try {
        mockFetch(() => json({ needsAgreement: false }));
        await checkUserAgreement({ type: 'chat' });
        mockFetch(() => json({ success: true }));
        await acceptUserAgreement({ type: 'chat' });
        assert.deepEqual(clock.delays, [20_000, 20_000]);
    } finally {
        clock.restore();
    }
});

check('a check that never answers fails once the time is up, and its request is abandoned', async () => {
    const clock = limitClock();
    try {
        const network = heldFetch();
        const pending = checkUserAgreement({ type: 'chat' });
        await until(() => network.calls.length === 1, 'the request');
        const given = network.calls[0].init.signal as AbortSignal;
        assert.equal(clock.armed, 1);
        assert.equal(given.aborted, false, 'not before the time is up');
        clock.expire();
        await assert.rejects(pending, (error: Error) => error instanceof UserAgreementTimeoutError);
        assert.equal(given.aborted, true, 'the request is abandoned, not left out');
        assert.equal(network.waiting(), 0);
        assert.equal(clock.armed, 0);
    } finally {
        clock.restore();
    }
});

check('an acceptance that never answers fails once the time is up, and is not an acceptance', async () => {
    const clock = limitClock();
    try {
        const network = heldFetch();
        let outcome = 'pending';
        const pending = acceptUserAgreement({ type: 'chat' }).then(
            () => {
                outcome = 'accepted';
            },
            (error: unknown) => {
                outcome = error instanceof UserAgreementTimeoutError ? 'timed out' : 'failed';
            },
        );
        await until(() => network.calls.length === 1, 'the request');
        assert.equal(outcome, 'pending');
        clock.expire();
        await pending;
        assert.equal(outcome, 'timed out');
        assert.equal(network.waiting(), 0);
    } finally {
        clock.restore();
    }
});

check('a request that answers in time leaves no limit running, and keeps its own answer', async () => {
    const clock = limitClock();
    try {
        mockFetch(() => json({ needsAgreement: true, agreementText: 'T', enableDailyAcceptance: false }));
        assert.deepEqual(await checkUserAgreement({ type: 'chat' }), {
            needsAgreement: true, agreementText: 'T', enableDailyAcceptance: false,
        });
        assert.equal(clock.armed, 0);
        // A failure that is not the clock's is that failure, not a timeout.
        mockFetch(() => json({ error: 'nope' }, 500));
        await assert.rejects(acceptUserAgreement({ type: 'chat' }), (error: Error) => !(error instanceof UserAgreementTimeoutError));
        assert.equal(clock.armed, 0);
        // And a scope that cannot be asked about starts neither a request nor a limit.
        const calls = mockFetch(() => json({ needsAgreement: false }));
        await assert.rejects(checkUserAgreement({ type: 'group' }), /workspace id is required/);
        assert.equal(calls.length, 0);
        assert.equal(clock.delays.length, 2, 'only the two requests that were sent set a limit');
    } finally {
        clock.restore();
    }
});

check('an abort by the caller is not a timeout, whether it comes during the request or before it', async () => {
    const clock = limitClock();
    try {
        const network = heldFetch();
        const during = new AbortController();
        const pending = checkUserAgreement({ type: 'chat' }, during.signal);
        await until(() => network.calls.length === 1, 'the request');
        during.abort();
        await assert.rejects(pending, (error: Error) => error.name === 'AbortError' && !(error instanceof UserAgreementTimeoutError));
        assert.equal(clock.armed, 0);

        const before = new AbortController();
        before.abort();
        await assert.rejects(
            checkUserAgreement({ type: 'chat' }, before.signal),
            (error: Error) => error.name === 'AbortError' && !(error instanceof UserAgreementTimeoutError),
        );
        assert.equal(clock.armed, 0);
    } finally {
        clock.restore();
    }
});

check('a timeout is worded as the failure it is, with the sentence of its phase and how long it waited', () => {
    const timeout = new UserAgreementTimeoutError();
    assert.equal(agreementFailureMessage('check', timeout), `${CHECK_FAILED_MESSAGE} (no answer within 20 seconds)`);
    assert.equal(agreementFailureMessage('accept', timeout), `${ACCEPT_FAILED_MESSAGE} (no answer within 20 seconds)`);
    assert.match(agreementFailureMessage('accept', timeout), /nothing was uploaded/);
    assert.ok(!agreementFailureMessage('check', timeout).includes('status'));
    assert.equal(timeout.name, 'UserAgreementTimeoutError');
});

check('a check that never answers shows the failure, holds the upload, and Cancel releases it', async () => {
    const clock = limitClock();
    try {
        const { gate, network } = openGate();
        const answer = gate.current.confirm(CHAT, [chatFile()]);
        await gate.flush();
        assert.equal(gate.current.pending, true);
        assert.equal(gate.current.prompt, null, 'nothing is shown while the check is within its time');
        clock.expire();
        await gate.flush();
        assert.equal(gate.current.prompt?.kind, 'unavailable');
        assert.equal(gate.current.prompt?.error, `${CHECK_FAILED_MESSAGE} (no answer within 20 seconds)`);
        assert.equal(gate.current.pending, true, 'a check that gave no answer is not an answer');
        assert.equal(network.waiting(), 0, 'the request was abandoned');
        gate.current.cancel();
        assert.equal(await answer, false);
        await gate.flush();
        assert.equal(gate.current.pending, false);
        assert.equal(gate.current.prompt, null);
    } finally {
        clock.restore();
    }
});

check('Try again after a timed-out check asks again with a fresh limit', async () => {
    const clock = limitClock();
    try {
        const { gate, network } = openGate();
        const answer = gate.current.confirm(CHAT, [chatFile()]);
        await gate.flush();
        clock.expire();
        await gate.flush();
        assert.equal(gate.current.prompt?.kind, 'unavailable');
        gate.current.accept();
        await gate.flush();
        assert.equal(network.waiting(), 1, 'the check was asked again');
        assert.equal(clock.armed, 1, 'and has a limit of its own');
        assert.equal(gate.current.prompt?.busy, true);
        network.answer(NO_AGREEMENT);
        assert.equal(await answer, true);
        await gate.flush();
        assert.equal(gate.current.pending, false);
        assert.equal(clock.armed, 0);
    } finally {
        clock.restore();
    }
});

check('an acceptance that never answers shows the failure, is not reported as accepted, and the dialog can be cancelled', async () => {
    const clock = limitClock();
    try {
        const { gate, network } = openGate();
        let settled = false;
        const answer = gate.current.confirm(CHAT, [chatFile()]);
        void answer.then(() => {
            settled = true;
        });
        await gate.flush();
        network.answer(AGREEMENT);
        await gate.flush();
        gate.current.accept();
        await until(() => network.calls.length === 2, 'the acceptance');
        await gate.flush();
        assert.equal(gate.current.prompt?.busy, true);
        // Cancel is ignored while the acceptance is out, as before: the limit is what ends the wait.
        gate.current.cancel();
        await gate.flush();
        assert.equal(settled, false);
        assert.equal(gate.current.prompt?.busy, true);

        clock.expire();
        await gate.flush();
        assert.equal(gate.current.prompt?.kind, 'agreement', 'the agreement is still being asked');
        assert.equal(gate.current.prompt?.busy, false);
        assert.equal(gate.current.prompt?.error, `${ACCEPT_FAILED_MESSAGE} (no answer within 20 seconds)`);
        assert.equal(settled, false, 'a timed-out acceptance does not let the upload go');
        assert.equal(gate.current.pending, true);

        gate.current.cancel();
        assert.equal(await answer, false);
        await gate.flush();
        assert.equal(gate.current.pending, false);
    } finally {
        clock.restore();
    }
});

check('an acceptance that timed out can be made again, and only then does the upload go', async () => {
    const clock = limitClock();
    try {
        const { gate, network } = openGate();
        const answer = gate.current.confirm(CHAT, [chatFile()]);
        await gate.flush();
        network.answer(AGREEMENT);
        await gate.flush();
        gate.current.accept();
        await until(() => network.calls.length === 2, 'the acceptance');
        clock.expire();
        await gate.flush();
        assert.equal(gate.current.prompt?.busy, false);
        gate.current.accept();
        await until(() => network.calls.length === 3, 'the second acceptance');
        assert.equal(clock.armed, 1, 'each acceptance has a limit of its own');
        network.answer({ success: true });
        assert.equal(await answer, true);
        await gate.flush();
        assert.equal(gate.current.pending, false);
        assert.equal(clock.armed, 0);
    } finally {
        clock.restore();
    }
});

let passed = 0;
for (const [name, fn] of checks) {
    // A gate that never settles would otherwise leave the process waiting on nothing and exit without a word.
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('the check did not finish: something it awaited never settled')), 5000);
    });
    try {
        await Promise.race([Promise.resolve(fn()), timeout]);
        console.log(`  ok  ${name}`);
        passed += 1;
    } catch (error) {
        console.error(`  FAIL ${name}`);
        console.error(`       ${(error as Error).message}`);
    } finally {
        clearTimeout(timer);
    }
}

console.log(`\nResults: ${passed}/${checks.length} checks passed`);
process.exit(passed === checks.length ? 0 : 1);
