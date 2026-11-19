// test_v2_profile_photo_refresh_logic.ts
//
// Runtime test for the V2 "Refresh photo" control: how the server's answer is read, what is said
// when it fails, what the request looks like, and how the new photo enters the settings store.
// Version: 0.261.448
// Implemented in: 0.261.448
//
// The judgement calls here do not show in a screenshot: that "no photo" is an answer and not an
// error, that a failure is reported in fixed words and never in the server's (which for a
// success carry the photograph itself), that the request goes through the API client with its V2
// marker, that a session the server has ended reaches the sign-in notice, and above all that
// the new photo goes into the store without being posted back to the server and without a later
// failed save of some other preference putting the old photo back.
//
// Run by test_v2_profile_photo_refresh.py, which bundles this with the esbuild Vite already
// brings in and executes it under node.

import assert from 'node:assert/strict';
import { ApiError } from '../application/v2_ui/src/lib/apiClient';
import {
    PROFILE_IMAGE_REFRESH_ENDPOINT,
    PROFILE_PHOTO_FAILED_MESSAGE,
    PROFILE_PHOTO_OFFLINE_MESSAGE,
    PROFILE_PHOTO_SESSION_MESSAGE,
    ProfileImageResponseError,
    describeProfileImageFailure,
    readProfileImageRefresh,
    requestProfileImageRefresh,
} from '../application/v2_ui/src/lib/profileImage';
import { useAppSessionStore } from '../application/v2_ui/src/stores/appSessionStore';
import { useUserSettingsStore } from '../application/v2_ui/src/stores/userSettingsStore';

const OLD_IMAGE = 'data:image/jpeg;base64,/9j/OLD-PHOTOGRAPH-BYTES';
const NEW_IMAGE = 'data:image/jpeg;base64,/9j/NEW-PHOTOGRAPH-BYTES';
const LEAK = 'SERVER-DETAIL-THAT-MUST-NOT-REACH-THE-PAGE';

const checks: [string, () => void | Promise<void>][] = [];
function check(name: string, fn: () => void | Promise<void>) {
    checks.push([name, fn]);
}

interface Call {
    url: string;
    method: string;
    body: string | undefined;
    headers: Record<string, string>;
    credentials: string | undefined;
}

let calls: Call[] = [];

function install(answer: (call: Call) => Response | Promise<Response>) {
    calls = [];
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
        const call: Call = {
            url: String(input),
            method: init?.method ?? 'GET',
            body: typeof init?.body === 'string' ? init.body : undefined,
            headers: Object.fromEntries(new Headers(init?.headers as HeadersInit | undefined)),
            credentials: init?.credentials,
        };
        calls.push(call);
        return answer(call);
    }) as typeof fetch;
}

function json(status: number, body: unknown): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function reset() {
    useAppSessionStore.setState({ status: 'ready', viewerId: '', revision: 0 });
    useUserSettingsStore.setState({ settings: {}, saving: false, saveError: null });
}

async function settled(error: Promise<unknown>): Promise<unknown> {
    try {
        await error;
    } catch (caught) {
        return caught;
    }
    throw new Error('expected the request to fail');
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

// ---- reading the answer ----------------------------------------------------------------

check('a photo is a new photo, trimmed', () => {
    assert.deepEqual(readProfileImageRefresh({ success: true, message: 'ok', profileImage: `  ${NEW_IMAGE}  ` }),
        { status: 'updated', profileImage: NEW_IMAGE });
});

check('null is the answer "no photo", not an error', () => {
    assert.deepEqual(readProfileImageRefresh({ success: true, message: 'No profile image found', profileImage: null }),
        { status: 'none' });
});

check('anything else is refused without quoting it', () => {
    const refused: unknown[] = [
        null, undefined, 'text', 42, [], {},
        { success: false, profileImage: NEW_IMAGE },
        { success: true },
        { success: true, profileImage: '' },
        { success: true, profileImage: '   ' },
        { success: true, profileImage: { data: NEW_IMAGE } },
        { success: true, profileImage: 12 },
        { profileImage: NEW_IMAGE },
    ];
    for (const payload of refused) {
        assert.throws(
            () => readProfileImageRefresh(payload),
            (error: Error) => {
                assert.ok(error instanceof ProfileImageResponseError, JSON.stringify(payload));
                assert.ok(!error.message.includes('PHOTOGRAPH'), 'the photograph must not be in the error');
                return true;
            },
            JSON.stringify(payload),
        );
    }
});

// ---- the words for a failure ------------------------------------------------------------

check('a failure is described by what failed, never by what the server said', () => {
    assert.equal(describeProfileImageFailure(new TypeError(LEAK)), PROFILE_PHOTO_OFFLINE_MESSAGE);
    assert.equal(describeProfileImageFailure(new ApiError(LEAK, 500, { error: LEAK })), PROFILE_PHOTO_FAILED_MESSAGE);
    assert.equal(describeProfileImageFailure(new ApiError(LEAK, 400, LEAK)), PROFILE_PHOTO_FAILED_MESSAGE);
    assert.equal(describeProfileImageFailure(new Error(LEAK)), PROFILE_PHOTO_FAILED_MESSAGE);
    assert.equal(describeProfileImageFailure(new ProfileImageResponseError()), PROFILE_PHOTO_FAILED_MESSAGE);
    assert.equal(describeProfileImageFailure('a string'), PROFILE_PHOTO_FAILED_MESSAGE);
    assert.equal(
        describeProfileImageFailure(new ApiError(LEAK, 401, { requires_reauth: true })),
        PROFILE_PHOTO_SESSION_MESSAGE,
    );
    for (const message of [PROFILE_PHOTO_FAILED_MESSAGE, PROFILE_PHOTO_OFFLINE_MESSAGE, PROFILE_PHOTO_SESSION_MESSAGE]) {
        assert.ok(!message.includes(LEAK));
    }
});

// ---- the request ------------------------------------------------------------------------

check('the request is one POST to the server route, through the API client, with an empty body', async () => {
    reset();
    install(() => json(200, { success: true, message: 'Profile image updated successfully', profileImage: NEW_IMAGE }));
    const result = await requestProfileImageRefresh();
    assert.deepEqual(result, { status: 'updated', profileImage: NEW_IMAGE });
    assert.equal(calls.length, 1);
    assert.equal(PROFILE_IMAGE_REFRESH_ENDPOINT, '/api/profile/image/refresh');
    assert.equal(calls[0].url, '/api/profile/image/refresh');
    assert.equal(calls[0].method, 'POST');
    assert.equal(calls[0].body, '{}');
    assert.equal(calls[0].headers['content-type'], 'application/json');
    assert.equal(calls[0].headers['x-simplechat-ui'], 'v2', 'the V2 marker the API client adds to every call');
    assert.equal(calls[0].credentials, 'same-origin');
});

check('"no photo" comes back as an answer', async () => {
    reset();
    install(() => json(200, { success: true, message: 'No profile image found', profileImage: null }));
    assert.deepEqual(await requestProfileImageRefresh(), { status: 'none' });
});

check('a server error is an error that does not carry what the server said', async () => {
    reset();
    install(() => json(500, { error: LEAK }));
    const error = await settled(requestProfileImageRefresh());
    assert.ok(error instanceof ApiError && error.status === 500);
    assert.equal(describeProfileImageFailure(error), PROFILE_PHOTO_FAILED_MESSAGE);
    assert.equal(useAppSessionStore.getState().status, 'ready', 'a server fault is not an ended session');
});

check('a session the server ended reaches the sign-in notice and is said in its own words', async () => {
    reset();
    install(() => json(401, { error: 'Session expired', message: LEAK, requires_reauth: true }));
    const error = await settled(requestProfileImageRefresh());
    assert.equal(useAppSessionStore.getState().status, 'required');
    assert.equal(describeProfileImageFailure(error), PROFILE_PHOTO_SESSION_MESSAGE);
});

check('a dropped connection is a network failure', async () => {
    reset();
    install(() => {
        throw new TypeError('Failed to fetch');
    });
    const error = await settled(requestProfileImageRefresh());
    assert.ok(error instanceof TypeError);
    assert.equal(describeProfileImageFailure(error), PROFILE_PHOTO_OFFLINE_MESSAGE);
});

check('a 200 that is not the answer is a failure that does not quote it', async () => {
    reset();
    install(() => new Response(`<html>${NEW_IMAGE}</html>`, { status: 200, headers: { 'content-type': 'text/html' } }));
    const error = await settled(requestProfileImageRefresh());
    assert.ok(error instanceof ProfileImageResponseError);
    assert.ok(!(error as Error).message.includes('PHOTOGRAPH'));
    assert.equal(describeProfileImageFailure(error), PROFILE_PHOTO_FAILED_MESSAGE);
});

// ---- the store --------------------------------------------------------------------------

check('the new photo replaces the old and null clears it, leaving other preferences alone', () => {
    reset();
    useUserSettingsStore.setState({ settings: { profileImage: OLD_IMAGE, fontSizePreference: 'l' } });
    useUserSettingsStore.getState().setProfileImage(NEW_IMAGE);
    assert.deepEqual(useUserSettingsStore.getState().settings, { profileImage: NEW_IMAGE, fontSizePreference: 'l' });
    useUserSettingsStore.getState().setProfileImage(null);
    assert.deepEqual(useUserSettingsStore.getState().settings, { profileImage: null, fontSizePreference: 'l' });
});

check('the photo is not written back to the server', async () => {
    reset();
    install(() => json(200, { message: 'Saved.' }));
    useUserSettingsStore.setState({ settings: { profileImage: OLD_IMAGE } });
    useUserSettingsStore.getState().setProfileImage(NEW_IMAGE);
    await sleep(600);
    await useUserSettingsStore.getState().flush();
    assert.deepEqual(calls, [], 'no save was scheduled for the photo');
    assert.equal(useUserSettingsStore.getState().settings.profileImage, NEW_IMAGE);
});

check('a save pending for another preference goes without the photo and keeps it', async () => {
    reset();
    install(() => json(200, { message: 'Saved.' }));
    useUserSettingsStore.setState({ settings: { profileImage: OLD_IMAGE } });
    useUserSettingsStore.getState().update({ fontSizePreference: 'l' });
    useUserSettingsStore.getState().setProfileImage(NEW_IMAGE);
    await useUserSettingsStore.getState().flush();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, '/api/user/settings');
    assert.deepEqual(JSON.parse(calls[0].body ?? 'null'), { settings: { fontSizePreference: 'l' } });
    assert.equal(useUserSettingsStore.getState().settings.profileImage, NEW_IMAGE);
});

check('a failed save of another preference does not bring the old photo back', async () => {
    reset();
    install(() => json(500, { error: 'nope' }));
    useUserSettingsStore.setState({ settings: { profileImage: OLD_IMAGE, fontSizePreference: 'm' } });
    useUserSettingsStore.getState().update({ fontSizePreference: 'xl' });
    useUserSettingsStore.getState().setProfileImage(NEW_IMAGE);
    await useUserSettingsStore.getState().flush();
    const settings = useUserSettingsStore.getState().settings;
    assert.equal(settings.fontSizePreference, 'm', 'the failed preference is rolled back');
    assert.equal(settings.profileImage, NEW_IMAGE, 'the photo is not');
});

let passed = 0;
for (const [name, fn] of checks) {
    try {
        await fn();
        console.log(`  ok  ${name}`);
        passed += 1;
    } catch (error) {
        console.error(`  FAIL ${name}`);
        console.error(`       ${(error as Error).message}`);
    }
}

console.log(`\nResults: ${passed}/${checks.length} checks passed`);
process.exit(passed === checks.length ? 0 : 1);
