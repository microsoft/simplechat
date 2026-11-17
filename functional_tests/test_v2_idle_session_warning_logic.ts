// test_v2_idle_session_warning_logic.ts
//
// Runtime test for the V2 idle-session warning: the thresholds, the activity and heartbeat
// throttles, the warning's countdown and the ways it ends. The controller is run against a
// fake clock and fake timers, so a thirty-minute timeout takes microseconds and every boundary
// can be asserted to the millisecond.
// Version: 0.261.445
// Implemented in: 0.261.445
//
// The judgement calls here do not show in a screenshot: that the warning opens at the same
// minute classic opens it, that continued activity is reported to the server once a minute and
// never later than the warning it would otherwise miss, that input cannot quietly dismiss a
// warning that is already due, that another tab's activity does, that a laptop waking from
// sleep signs out instead of extending, and that a heartbeat the server refuses hands the
// session to the sign-in notice instead of signing out.
//
// Run by test_v2_idle_session_warning.py, which bundles this with the esbuild Vite already
// brings in and executes it under node.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
    ACTIVITY_THROTTLE_MS,
    CLOSED_VIEW,
    DEFAULT_WARNING_MESSAGE,
    IDLE_HEARTBEAT_ENDPOINT,
    IDLE_SIGN_OUT_PATH,
    SHARED_ACTIVITY_KEY,
    STAY_SIGNED_IN_FAILED_MESSAGE,
    WARNING_MESSAGE_MAX_LENGTH,
    countdownAnnouncement,
    createIdleSessionController,
    formatRemaining,
    idlePhase,
    parseSharedActivity,
    resolveIdlePolicy,
    secondsUntilSignOut,
    type IdlePolicy,
    type IdleSessionController,
    type IdleSessionHost,
    type IdleSessionView,
} from '../application/v2_ui/src/lib/idleSession';
import type { IdleTimeoutBootstrap } from '../application/v2_ui/src/lib/types';

const MINUTE = 60_000;
const SECOND = 1000;
const START = Date.UTC(2026, 0, 5, 9, 0, 0);

const checks: [string, () => void | Promise<void>][] = [];
function check(name: string, fn: () => void | Promise<void>) {
    checks.push([name, fn]);
}

/** Let promise continuations run, which is all the controller's awaits need. */
const flush = () => new Promise<void>((resolve) => setImmediate(resolve));

type HeartbeatBehaviour = 'ok' | 'fail' | 'session-ended';

class FakeHost implements IdleSessionHost {
    clock = START;
    private nextTimer = 1;
    private timers = new Map<number, { at: number; callback: () => void }>();
    heartbeats: number[] = [];
    signOuts: number[] = [];
    delays: number[] = [];
    shared: string | null = null;
    sharedWrites: string[] = [];
    ended = false;
    behaviour: HeartbeatBehaviour = 'ok';

    now() {
        return this.clock;
    }

    setTimer(callback: () => void, delayMs: number) {
        this.delays.push(delayMs);
        const id = this.nextTimer++;
        this.timers.set(id, { at: this.clock + delayMs, callback });
        return id;
    }

    clearTimer(handle: unknown) {
        this.timers.delete(handle as number);
    }

    async sendHeartbeat() {
        this.heartbeats.push(this.clock);
        if (this.behaviour === 'fail') {
            throw new Error('network down');
        }
        if (this.behaviour === 'session-ended') {
            this.ended = true;
            throw new Error('session ended');
        }
    }

    sessionEnded() {
        return this.ended;
    }

    signOut() {
        this.signOuts.push(this.clock);
    }

    readSharedActivity() {
        return this.shared;
    }

    writeSharedActivity(value: string) {
        this.shared = value;
        this.sharedWrites.push(value);
    }

    pendingTimers() {
        return this.timers.size;
    }

    /** Move time forward, running each timer when its time comes. */
    advance(ms: number) {
        const target = this.clock + ms;
        for (;;) {
            const due = [...this.timers.entries()]
                .filter(([, timer]) => timer.at <= target)
                .sort((a, b) => a[1].at - b[1].at || a[0] - b[0])[0];
            if (!due) {
                break;
            }
            this.timers.delete(due[0]);
            this.clock = Math.max(this.clock, due[1].at);
            due[1].callback();
        }
        this.clock = target;
    }

    /** Time passes with no timer running: the machine slept. */
    sleep(ms: number) {
        this.clock += ms;
    }
}

function policy(timeoutMinutes = 30, warningMinutes = 28): IdlePolicy {
    const resolved = resolveIdlePolicy({
        enabled: true,
        timeout_minutes: timeoutMinutes,
        warning_minutes: warningMinutes,
        warning_message: 'Still there?',
    });
    assert.ok(resolved, 'the policy should resolve');
    return resolved;
}

function setup(timeoutMinutes = 30, warningMinutes = 28) {
    const host = new FakeHost();
    const views: IdleSessionView[] = [];
    const controller: IdleSessionController = createIdleSessionController(
        policy(timeoutMinutes, warningMinutes), host, (view) => views.push(view),
    );
    controller.start();
    return { host, controller, views };
}

// ---- policy ----------------------------------------------------------------------------

check('a disabled or missing timeout runs nothing', () => {
    assert.equal(resolveIdlePolicy(undefined), null);
    assert.equal(resolveIdlePolicy(null), null);
    assert.equal(resolveIdlePolicy({}), null);
    assert.equal(resolveIdlePolicy({ enabled: false, timeout_minutes: 30, warning_minutes: 28 }), null);
});

check('values the classic page refuses to act on run nothing', () => {
    const base = { enabled: true, timeout_minutes: 30, warning_minutes: 28 };
    assert.ok(resolveIdlePolicy(base));
    assert.equal(resolveIdlePolicy({ ...base, timeout_minutes: 0 }), null, 'no timeout');
    assert.equal(resolveIdlePolicy({ ...base, timeout_minutes: -5 }), null, 'negative timeout');
    assert.equal(resolveIdlePolicy({ ...base, timeout_minutes: Number.NaN }), null, 'NaN timeout');
    assert.equal(resolveIdlePolicy({ ...base, warning_minutes: 31 }), null, 'warning after the sign-out');
    assert.equal(resolveIdlePolicy({ ...base, warning_minutes: -1 }), null, 'negative warning');
    assert.equal(resolveIdlePolicy({ enabled: true, timeout_minutes: 30 }), null, 'warning missing');
    assert.equal(resolveIdlePolicy({ enabled: true, timeout_minutes: '30' as unknown as number, warning_minutes: 28 }), null,
        'numbers are not guessed from strings');
});

check('the policy carries the classic thresholds in milliseconds', () => {
    const resolved = policy(30, 28);
    assert.equal(resolved.timeoutMs, 30 * MINUTE);
    assert.equal(resolved.warningMs, 28 * MINUTE);
    assert.equal(resolved.warningEnabled, true);
    assert.equal(resolved.heartbeatIntervalMs, MINUTE, 'a heartbeat at most every minute');
    assert.equal(policy(10, 9).heartbeatIntervalMs, MINUTE);
});

check('a warning time equal to the timeout turns the dialog off', () => {
    const resolved = policy(30, 30);
    assert.equal(resolved.warningEnabled, false);
    assert.equal(idlePhase(resolved, 29 * MINUTE + 59 * SECOND), 'active');
    assert.equal(idlePhase(resolved, 30 * MINUTE), 'expired');
});

check('the heartbeat gap is half the timeout when that is under a minute', () => {
    const resolved = resolveIdlePolicy({ enabled: true, timeout_minutes: 1, warning_minutes: 0.5 });
    assert.ok(resolved);
    assert.equal(resolved.heartbeatIntervalMs, 30 * SECOND);
});

check('the warning message is the administrator text, trimmed and capped, with a default', () => {
    const make = (warning_message: unknown) => resolveIdlePolicy({
        enabled: true, timeout_minutes: 30, warning_minutes: 28, warning_message: warning_message as string,
    });
    assert.equal(make('  Please confirm you are here.  ')?.warningMessage, 'Please confirm you are here.');
    assert.equal(make('')?.warningMessage, DEFAULT_WARNING_MESSAGE);
    assert.equal(make('   ')?.warningMessage, DEFAULT_WARNING_MESSAGE);
    assert.equal(make(undefined)?.warningMessage, DEFAULT_WARNING_MESSAGE);
    assert.equal(make(42)?.warningMessage, DEFAULT_WARNING_MESSAGE);
    assert.equal(make('x'.repeat(500))?.warningMessage.length, WARNING_MESSAGE_MAX_LENGTH);
    assert.equal(make('<b>bold</b>')?.warningMessage, '<b>bold</b>', 'markup is kept as text, not interpreted here');
});

check('the phases change at the classic boundaries', () => {
    const resolved = policy(30, 28);
    assert.equal(idlePhase(resolved, 0), 'active');
    assert.equal(idlePhase(resolved, 28 * MINUTE - 1), 'active');
    assert.equal(idlePhase(resolved, 28 * MINUTE), 'warning');
    assert.equal(idlePhase(resolved, 30 * MINUTE - 1), 'warning');
    assert.equal(idlePhase(resolved, 30 * MINUTE), 'expired');
    assert.equal(idlePhase(resolved, 9 * 60 * MINUTE), 'expired');
});

check('the countdown rounds up, as classic does', () => {
    const resolved = policy(30, 28);
    assert.equal(secondsUntilSignOut(resolved, 28 * MINUTE), 120);
    assert.equal(secondsUntilSignOut(resolved, 28 * MINUTE + 1), 120);
    assert.equal(secondsUntilSignOut(resolved, 28 * MINUTE + 1000), 119);
    assert.equal(secondsUntilSignOut(resolved, 30 * MINUTE - 500), 1);
    assert.equal(secondsUntilSignOut(resolved, 30 * MINUTE), 0);
    assert.equal(secondsUntilSignOut(resolved, 31 * MINUTE), 0);
});

check('the countdown is worded for a person', () => {
    assert.equal(formatRemaining(120), '2 minutes');
    assert.equal(formatRemaining(61), '1 minute 1 second');
    assert.equal(formatRemaining(60), '1 minute');
    assert.equal(formatRemaining(45), '45 seconds');
    assert.equal(formatRemaining(1), '1 second');
    assert.equal(formatRemaining(0), '0 seconds');
    assert.equal(formatRemaining(-4), '0 seconds');
});

check('the countdown is announced at a few marks, not every second', () => {
    assert.equal(countdownAnnouncement(null, 120), null, 'opening is covered by the dialog description');
    assert.equal(countdownAnnouncement(120, 119), null);
    assert.equal(countdownAnnouncement(61, 60), 'You will be signed out in 1 minute.');
    assert.equal(countdownAnnouncement(31, 30), 'You will be signed out in 30 seconds.');
    assert.equal(countdownAnnouncement(11, 10), 'You will be signed out in 10 seconds.');
    assert.equal(countdownAnnouncement(10, 9), null);
    assert.equal(countdownAnnouncement(65, 25), 'You will be signed out in 25 seconds.', 'a skipped tick still announces once');
    assert.equal(countdownAnnouncement(30, 90), null, 'a reset is not an announcement');
    let announced = 0;
    for (let seconds = 120; seconds > 0; seconds -= 1) {
        if (countdownAnnouncement(seconds + 1, seconds)) {
            announced += 1;
        }
    }
    assert.equal(announced, 3);
});

check('a shared activity time is trusted only when it is plausible', () => {
    const now = START;
    assert.equal(parseSharedActivity(null, now), null);
    assert.equal(parseSharedActivity('', now), null);
    assert.equal(parseSharedActivity('abc', now), null);
    assert.equal(parseSharedActivity('0', now), null);
    assert.equal(parseSharedActivity('-5', now), null);
    assert.equal(parseSharedActivity(String(now - MINUTE), now), now - MINUTE);
    assert.equal(parseSharedActivity(String(now + 2 * SECOND), now), now, 'a little ahead reads as now');
    assert.equal(parseSharedActivity(String(now + 10 * MINUTE), now), null, 'far ahead cannot hold the session open');
    assert.equal(parseSharedActivity('9e15', now), null);
});

check('the endpoints are the server routes', () => {
    assert.equal(IDLE_HEARTBEAT_ENDPOINT, '/api/session/heartbeat');
    assert.equal(IDLE_SIGN_OUT_PATH, '/logout/local');
    assert.equal(SHARED_ACTIVITY_KEY, 'simplechat.v2.idleActivity');
    assert.equal(ACTIVITY_THROTTLE_MS, 1000);
});

check('every block the server builds is one the page acts on, with the server\'s own numbers', () => {
    const file = process.env.IDLE_SESSION_SERVER_BLOCKS;
    if (!file) {
        console.log('  skip  server block cross-check (IDLE_SESSION_SERVER_BLOCKS is not set)');
        return;
    }
    const cases = JSON.parse(readFileSync(file, 'utf8')) as { label: string; block: IdleTimeoutBootstrap }[];
    assert.ok(cases.length >= 10, 'the server side should supply a spread of blocks');
    let enabled = 0;
    for (const { label, block } of cases) {
        const resolved = resolveIdlePolicy(block);
        if (!block.enabled) {
            assert.equal(resolved, null, `${label}: a disabled timeout runs nothing`);
            continue;
        }
        enabled += 1;
        assert.ok(resolved, `${label}: the page refused a block the server built`);
        assert.equal(resolved.timeoutMs, block.timeout_minutes * MINUTE, label);
        assert.equal(resolved.warningMs, block.warning_minutes * MINUTE, label);
        assert.equal(resolved.warningEnabled, block.warning_minutes < block.timeout_minutes, label);
        assert.equal(resolved.warningMessage, block.warning_message, `${label}: the sentence passes through unchanged`);
        assert.ok(resolved.warningMs <= resolved.timeoutMs, label);
    }
    assert.ok(enabled >= 8, 'most of the spread should be enabled blocks');
});

// ---- the warning and the sign-out -------------------------------------------------------

check('the warning opens at 28 minutes with two minutes to go and signs out at 30', () => {
    const { host, views } = setup();
    host.advance(28 * MINUTE - 1);
    assert.equal(views.length, 0, 'nothing shown before the warning time');
    host.advance(1);
    assert.deepEqual(views.at(-1), { open: true, secondsRemaining: 120, staying: false, error: null });
    host.advance(SECOND);
    assert.equal(views.at(-1)?.secondsRemaining, 119);
    host.advance(58 * SECOND);
    assert.equal(views.at(-1)?.secondsRemaining, 61);
    host.advance(SECOND);
    assert.equal(views.at(-1)?.secondsRemaining, 60);
    host.advance(59 * SECOND);
    assert.equal(views.at(-1)?.secondsRemaining, 1);
    assert.deepEqual(host.signOuts, [], 'not signed out while a second remains');
    host.advance(SECOND);
    assert.deepEqual(host.signOuts, [START + 30 * MINUTE], 'signed out at the 30th minute, once');
    assert.equal(views.at(-1)?.secondsRemaining, 0, 'and the dialog reads zero while the page leaves');
    host.advance(10 * MINUTE);
    assert.equal(host.signOuts.length, 1, 'and never again');
    assert.equal(host.heartbeats.length, 0, 'no input, so nothing was reported to the server');
});

check('with no warning time the user is signed out at the timeout without a dialog', () => {
    const { host, views } = setup(30, 30);
    host.advance(30 * MINUTE - 1);
    assert.equal(views.length, 0);
    assert.deepEqual(host.signOuts, []);
    host.advance(1);
    assert.deepEqual(host.signOuts, [START + 30 * MINUTE]);
    assert.equal(views.length, 0, 'the dialog never opened');
});

check('timers never exceed what a browser accepts', () => {
    const { host } = setup(100_000, 99_000);
    assert.ok(host.delays.length > 0);
    assert.ok(host.delays.every((delay) => delay >= 1 && delay <= 2_147_483_647), host.delays.join(','));
    host.advance(99_000 * MINUTE - 1);
    assert.deepEqual(host.signOuts, [], 'an early wake-up leaves the user signed in');
});

// ---- activity ---------------------------------------------------------------------------

check('activity restarts the clock and moves the warning', () => {
    const { host, controller, views } = setup();
    host.advance(27 * MINUTE);
    controller.activity();
    host.advance(28 * MINUTE - 1);
    assert.equal(views.length, 0, 'the old warning time passed with nothing shown');
    host.advance(1);
    assert.equal(views.at(-1)?.open, true, 'the warning is 28 minutes after the last activity');
    assert.equal(views.at(-1)?.secondsRemaining, 120);
});

check('input is counted once a second', () => {
    const { host, controller } = setup();
    host.advance(5 * MINUTE);
    const before = host.sharedWrites.length;
    controller.activity();
    controller.activity();
    host.advance(ACTIVITY_THROTTLE_MS - 1);
    controller.activity();
    assert.equal(host.sharedWrites.length - before, 1, 'three events inside a second count as one');
    host.advance(1);
    controller.activity();
    assert.equal(host.sharedWrites.length - before, 2, 'the next second counts again');
});

check('the first activity is reported at once and then at most once a minute', async () => {
    const { host, controller } = setup();
    host.advance(10 * MINUTE);
    controller.activity();
    assert.deepEqual(host.heartbeats, [START + 10 * MINUTE], 'reported on the first input');
    for (let seconds = 5; seconds <= 170; seconds += 5) {
        await flush();
        host.advance(5 * SECOND);
        controller.activity();
    }
    await flush();
    // Active for just under three minutes: the first report, then one a minute after the
    // previous one, never more often.
    const gaps = host.heartbeats.slice(1).map((at, index) => at - host.heartbeats[index]);
    assert.ok(gaps.every((gap) => gap >= MINUTE), `gaps under a minute: ${gaps.join(',')}`);
    assert.ok(host.heartbeats.length >= 3 && host.heartbeats.length <= 4, `${host.heartbeats.length} heartbeats`);
});

check('a user who stops right after a throttled input is still reported before the warning is due', async () => {
    const { host, controller } = setup();
    host.advance(10 * MINUTE);
    controller.activity();
    await flush();
    host.advance(30 * SECOND);
    controller.activity();
    assert.equal(host.heartbeats.length, 1, 'throttled: the server was told half a minute ago');
    host.advance(30 * SECOND);
    await flush();
    assert.equal(host.heartbeats.length, 2, 'a trailing report goes out when one is next due');
    assert.equal(host.heartbeats[1], START + 11 * MINUTE);
    // The server's clock is then no earlier than the page's, so the server cannot sign the
    // user out before the page warns them.
    assert.ok(host.heartbeats[1] >= START + 10 * MINUTE + 30 * SECOND);
});

check('two heartbeats are never in flight at once', async () => {
    const { host, controller } = setup();
    let release: () => void = () => undefined;
    host.sendHeartbeat = async () => {
        host.heartbeats.push(host.clock);
        await new Promise<void>((resolve) => { release = resolve; });
    };
    host.advance(10 * MINUTE);
    controller.activity();
    host.advance(2 * MINUTE);
    controller.activity();
    host.advance(2 * MINUTE);
    controller.activity();
    assert.equal(host.heartbeats.length, 1, 'later input waits for the one in flight');
    release();
    await flush();
});

check('a failed heartbeat is tried again by the next input, not by a loop', async () => {
    const { host, controller } = setup();
    host.behaviour = 'fail';
    host.advance(10 * MINUTE);
    controller.activity();
    await flush();
    assert.equal(host.heartbeats.length, 1);
    host.behaviour = 'ok';
    host.advance(ACTIVITY_THROTTLE_MS);
    controller.activity();
    await flush();
    assert.equal(host.heartbeats.length, 2, 'the next input reports again');
    assert.deepEqual(host.signOuts, [], 'a failed background report never signs anyone out');
});

check('input after the warning is due cannot quietly extend the session', () => {
    const { host, controller, views } = setup();
    // The machine slept through the warning, so no timer has opened it yet.
    host.sleep(29 * MINUTE);
    controller.activity();
    assert.equal(views.at(-1)?.open, true, 'the warning opens instead of the input counting');
    assert.equal(host.heartbeats.length, 0, 'no heartbeat for input that arrived too late');
    assert.deepEqual(host.signOuts, []);
});

check('waking from sleep past the timeout signs out instead of extending', () => {
    const { host, controller } = setup();
    host.sleep(8 * 60 * MINUTE);
    controller.activity();
    assert.deepEqual(host.signOuts, [START + 8 * 60 * MINUTE]);
    assert.equal(host.heartbeats.length, 0);
});

check('input while the warning is open does not dismiss it', () => {
    const { host, controller, views } = setup();
    host.advance(28 * MINUTE);
    assert.equal(views.at(-1)?.open, true);
    host.advance(10 * SECOND);
    controller.activity();
    controller.activity();
    host.advance(ACTIVITY_THROTTLE_MS);
    controller.activity();
    assert.equal(controller.getView().open, true, 'a mouse move, a Tab key or a scroll leaves it open');
    assert.equal(controller.getView().secondsRemaining, 109);
    assert.equal(host.heartbeats.length, 0, 'and reports nothing');
});

// ---- Stay signed in ---------------------------------------------------------------------

check('Stay signed in sends one heartbeat, closes the warning and restarts the clock', async () => {
    const { host, controller, views } = setup();
    host.advance(28 * MINUTE + 30 * SECOND);
    const staying = controller.stay();
    assert.equal(controller.getView().staying, true, 'busy while the server answers');
    await staying;
    assert.deepEqual(host.heartbeats, [START + 28 * MINUTE + 30 * SECOND]);
    assert.deepEqual(views.at(-1), CLOSED_VIEW);
    host.advance(28 * MINUTE - 1);
    assert.equal(controller.getView().open, false, 'the new warning is 28 minutes after the click');
    host.advance(1);
    assert.equal(controller.getView().open, true);
    assert.deepEqual(host.signOuts, []);
});

check('a second click while the server is answering does nothing', async () => {
    const { host, controller } = setup();
    host.advance(28 * MINUTE);
    const first = controller.stay();
    const second = controller.stay();
    await Promise.all([first, second]);
    assert.equal(host.heartbeats.length, 1);
});

check('a failed Stay signed in keeps the warning, says so and lets the user try again', async () => {
    const { host, controller } = setup();
    host.advance(28 * MINUTE);
    host.behaviour = 'fail';
    await controller.stay();
    assert.deepEqual(controller.getView(), {
        open: true, secondsRemaining: 120, staying: false, error: STAY_SIGNED_IN_FAILED_MESSAGE,
    });
    host.advance(30 * SECOND);
    assert.equal(controller.getView().secondsRemaining, 90, 'the countdown keeps running');
    assert.equal(controller.getView().error, STAY_SIGNED_IN_FAILED_MESSAGE);
    host.behaviour = 'ok';
    await controller.stay();
    assert.equal(controller.getView().open, false);
    assert.equal(controller.getView().error, null);
    assert.deepEqual(host.signOuts, []);
});

check('an unanswered Stay signed in still ends at zero', async () => {
    const { host, controller } = setup();
    host.advance(28 * MINUTE);
    host.behaviour = 'fail';
    await controller.stay();
    host.advance(2 * MINUTE);
    assert.deepEqual(host.signOuts, [START + 30 * MINUTE]);
});

check('a heartbeat the server refuses as an ended session hands over to the sign-in notice', async () => {
    const { host, controller, views } = setup();
    host.advance(28 * MINUTE);
    host.behaviour = 'session-ended';
    await controller.stay();
    assert.deepEqual(views.at(-1), CLOSED_VIEW, 'the warning goes');
    host.advance(10 * MINUTE);
    assert.deepEqual(host.signOuts, [], 'and nothing signs the user out behind the notice');
    assert.equal(host.pendingTimers(), 0, 'no timer is left running');
});

check('a background heartbeat that finds the session ended stops the clock', async () => {
    const { host, controller, views } = setup();
    host.advance(10 * MINUTE);
    host.behaviour = 'session-ended';
    controller.activity();
    await flush();
    host.advance(40 * MINUTE);
    assert.deepEqual(host.signOuts, []);
    assert.equal(views.filter((view) => view.open).length, 0);
});

check('the page can sign out now, once', () => {
    const { host, controller } = setup();
    host.advance(28 * MINUTE + 5 * SECOND);
    controller.signOutNow();
    controller.signOutNow();
    assert.deepEqual(host.signOuts, [START + 28 * MINUTE + 5 * SECOND]);
    host.advance(10 * MINUTE);
    assert.equal(host.signOuts.length, 1);
});

// ---- the tab ----------------------------------------------------------------------------

check('coming back to the tab counts as activity while there is time to spare', async () => {
    const { host, controller } = setup();
    host.advance(20 * MINUTE);
    controller.visible();
    await flush();
    assert.deepEqual(host.heartbeats, [START + 20 * MINUTE], 'reported like any activity');
    host.advance(28 * MINUTE - 1);
    assert.equal(controller.getView().open, false, 'the clock restarted when the tab came back');
});

check('coming back to the tab does not dismiss a warning that is already due', () => {
    const { host, controller } = setup();
    host.sleep(29 * MINUTE);
    controller.visible();
    assert.equal(controller.getView().open, true);
    assert.equal(controller.getView().secondsRemaining, 60);
    assert.equal(host.heartbeats.length, 0);
});

check('coming back to the tab after the timeout signs out', () => {
    const { host, controller } = setup();
    host.sleep(31 * MINUTE);
    controller.visible();
    assert.deepEqual(host.signOuts, [START + 31 * MINUTE]);
});

check("another tab's activity closes this tab's warning and moves it", () => {
    const { host, controller } = setup();
    host.advance(28 * MINUTE + 30 * SECOND);
    assert.equal(controller.getView().open, true);
    host.shared = String(host.clock - SECOND);
    controller.sharedActivityChanged();
    assert.equal(controller.getView().open, false);
    host.advance(28 * MINUTE - 2 * SECOND);
    assert.equal(controller.getView().open, false);
    host.advance(2 * SECOND);
    assert.equal(controller.getView().open, true, 'the warning follows the other tab');
    assert.deepEqual(host.signOuts, [], 'an idle tab does not sign out a session in use elsewhere');
});

check("another tab's activity is found by this tab's own timer too", () => {
    const { host, controller } = setup();
    host.advance(20 * MINUTE);
    host.shared = String(host.clock);
    host.advance(8 * MINUTE);
    assert.equal(controller.getView().open, false, 'the warning timer re-reads the shared time before opening');
    host.advance(20 * MINUTE);
    assert.equal(controller.getView().open, true);
});

check('an implausible shared time is ignored', () => {
    const { host, controller } = setup();
    host.advance(28 * MINUTE);
    assert.equal(controller.getView().open, true);
    for (const value of ['garbage', String(host.clock + 60 * MINUTE), '0', '']) {
        host.shared = value;
        controller.sharedActivityChanged();
        assert.equal(controller.getView().open, true, `"${value}" must not hold the session open`);
    }
});

check('pausing for the sign-in notice stops the clock and resuming restarts it from now', () => {
    const { host, controller } = setup();
    host.advance(10 * MINUTE);
    controller.pause();
    host.advance(2 * 60 * MINUTE);
    assert.deepEqual(host.signOuts, []);
    assert.equal(controller.getView().open, false);
    controller.activity();
    controller.visible();
    assert.equal(host.heartbeats.length, 0, 'nothing is reported while the session is over');
    controller.resume();
    host.advance(28 * MINUTE - 1);
    assert.equal(controller.getView().open, false);
    host.advance(1);
    assert.equal(controller.getView().open, true, 'counted from the moment sign-in was confirmed');
});

check('a stopped controller leaves nothing running', () => {
    const { host, controller } = setup();
    host.advance(10 * MINUTE);
    controller.activity();
    controller.stop();
    assert.equal(host.pendingTimers(), 0);
    host.advance(60 * MINUTE);
    assert.deepEqual(host.signOuts, []);
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
