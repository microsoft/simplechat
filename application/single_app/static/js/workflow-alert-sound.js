// workflow-alert-sound.js
// Workflow alert sounds for the classic pages, played from local files, so that only one tab in a
// browser sounds. Classic shares the Web Lock and the "sounded once" record with the V2 frame
// (application/v2_ui/src/lib/workflowAlertSound.ts), so classic and V2 tabs take turns too.
//
// - Alerts that need acknowledgment and repeat keep one loop going, every five seconds, in the
//   tone of the loudest of them, until none is left. The loop holds the lock while it sounds, so
//   another tab stays quiet. Each tick checks the administrator's and the device's switches, so
//   turning sound off silences it at once and turning it back on resumes it.
// - "Play once" is a one-off. It is checked and recorded for the whole browser under the lock,
//   so another tab doesn't chime for the same alert, and it skips while another sound holds it.
// - A sound the browser refuses (autoplay) is kept, and the next click or key press, or Enable
//   sound, tries it again. A refused loop gives up the lock, so a tab that may play takes over.

(function() {
    'use strict';

    const WORKFLOW_ALERT_SOUND_REPEAT_MS = 5000;
    const playSoundsStorageKey = 'simplechat.workflowAlerts.playSounds';
    const soundedOnceStorageKey = 'simplechat.workflowAlerts.soundedOnce';
    const soundedOnceTtlMs = 25 * 60 * 60 * 1000;
    const soundedOnceMax = 500;
    const lockName = 'simplechat.workflowAlertSound';
    const priorityRank = { info: 0, low: 1, medium: 2, high: 3, critical: 4 };

    // Pending alerts that repeat until acknowledged, by id.
    const repeatingAlerts = new Map();
    // One-off sounds the browser refused, by id, tried again on the next click or key press.
    const refusedOnceAlerts = new Map();
    // One-off sounds this page has started, so an alert read again doesn't chime again.
    const triedOnceIds = new Set();
    let adminSoundsEnabled = true;
    let loopTimer = null;
    // The browser refused the loop's tone, and it hasn't played since.
    let loopRefused = false;
    let loopReleaseLock = null;
    let loopLockPending = false;
    let loopTickPending = false;
    let retryInFlight = false;

    function normalizeId(notificationId) {
        return String(notificationId || '').trim();
    }

    function normalizePriority(priority) {
        const normalizedPriority = String(priority || '').trim().toLowerCase();
        return Object.prototype.hasOwnProperty.call(priorityRank, normalizedPriority) ? normalizedPriority : 'medium';
    }

    function normalizeSoundMode(sound) {
        const normalizedSound = String(sound || 'off').trim().toLowerCase();
        return ['once', 'repeat'].includes(normalizedSound) ? normalizedSound : 'off';
    }

    function getNotificationPriority(notification) {
        return normalizePriority(
            notification?.priority
            || notification?.metadata?.priority
        );
    }

    function getNotificationSoundMode(notification) {
        return normalizeSoundMode(
            notification?.sound
            || notification?.metadata?.sound
        );
    }

    function isDeviceEnabled() {
        try {
            return localStorage.getItem(playSoundsStorageKey) !== 'false';
        } catch (error) {
            console.warn('Unable to read workflow alert sound preference:', error);
            return true;
        }
    }

    function setDeviceEnabled(enabled) {
        try {
            localStorage.setItem(playSoundsStorageKey, enabled ? 'true' : 'false');
        } catch (error) {
            console.warn('Unable to save workflow alert sound preference:', error);
        }
        updateProfileControls();
        announceState();
    }

    function canPlay() {
        return adminSoundsEnabled === true && isDeviceEnabled();
    }

    function isBlocked() {
        return canPlay() && (loopRefused || refusedOnceAlerts.size > 0);
    }

    function getSoundUrl(priority) {
        const normalizedPriority = normalizePriority(priority);
        if (normalizedPriority === 'critical') {
            return '/static/audio/workflow-alerts/alarm.wav';
        }
        if (normalizedPriority === 'high' || normalizedPriority === 'medium') {
            return '/static/audio/workflow-alerts/urgent.wav';
        }
        return '/static/audio/workflow-alerts/chime.wav';
    }

    function announceState() {
        window.dispatchEvent(new CustomEvent('workflow-alert-sound-state-changed', {
            detail: {
                blocked: isBlocked(),
                deviceEnabled: isDeviceEnabled(),
                adminEnabled: adminSoundsEnabled,
            },
        }));
    }

    function isRefusal(error) {
        return Boolean(error) && error.name === 'NotAllowedError';
    }

    // Resolves once the tone starts. Rejects only when the browser refuses to play it; a file that
    // can't be played is not a refusal, since there is nothing to enable or retry.
    function startPlayback(priority) {
        let playResult;
        try {
            playResult = new Audio(getSoundUrl(priority)).play();
        } catch (error) {
            playResult = Promise.reject(error);
        }
        return Promise.resolve(playResult).catch(error => {
            if (isRefusal(error)) {
                throw error;
            }
            console.warn('Workflow alert sound could not be played:', error);
        });
    }

    function getLockManager() {
        const lockManager = typeof navigator !== 'undefined' ? navigator.locks : null;
        return lockManager && typeof lockManager.request === 'function' ? lockManager : null;
    }

    function readSoundedOnce() {
        try {
            const parsed = JSON.parse(localStorage.getItem(soundedOnceStorageKey) || '{}');
            return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
        } catch (error) {
            return {};
        }
    }

    function hasSoundedOnce(notificationId) {
        const soundedAt = readSoundedOnce()[notificationId];
        return typeof soundedAt === 'number' && Date.now() - soundedAt < soundedOnceTtlMs;
    }

    function markSoundedOnce(notificationId) {
        try {
            const now = Date.now();
            const kept = Object.entries(readSoundedOnce())
                .filter(([, soundedAt]) => typeof soundedAt === 'number' && now - soundedAt < soundedOnceTtlMs)
                .sort((left, right) => right[1] - left[1])
                .slice(0, soundedOnceMax - 1);
            localStorage.setItem(
                soundedOnceStorageKey,
                JSON.stringify(Object.fromEntries([[notificationId, now], ...kept]))
            );
        } catch (error) {
            console.warn('Unable to record a workflow alert sound:', error);
        }
    }

    // Checked and recorded under the lock, so two tabs can't both decide to chime. A one-off never
    // interrupts a loop: while this tab's loop, or another tab's sound, holds the lock it skips.
    function playOnce(notification) {
        const notificationId = normalizeId(notification?.id);
        if (!notificationId || !canPlay()) {
            return Promise.resolve(false);
        }

        const run = () => {
            if (hasSoundedOnce(notificationId)) {
                // Another tab chimed it, so there is nothing left here to enable.
                if (refusedOnceAlerts.delete(notificationId)) {
                    announceState();
                }
                return false;
            }
            return startPlayback(getNotificationPriority(notification))
                .then(() => {
                    markSoundedOnce(notificationId);
                    refusedOnceAlerts.delete(notificationId);
                    return true;
                })
                .catch(error => {
                    console.warn('Workflow alert sound playback was blocked:', error);
                    refusedOnceAlerts.set(notificationId, notification);
                    return false;
                })
                .finally(announceState);
        };
        // Another sound holds the lock, so the browser may sound and this one would only talk over it.
        const skip = () => {
            if (refusedOnceAlerts.delete(notificationId)) {
                announceState();
            }
            return false;
        };

        const lockManager = getLockManager();
        if (!lockManager) {
            return Promise.resolve().then(run);
        }
        if (loopReleaseLock) {
            return Promise.resolve().then(skip);
        }
        return lockManager.request(lockName, { ifAvailable: true }, lock => (lock ? run() : skip()))
            .catch(error => {
                console.warn('Unable to acquire workflow alert sound lock:', error);
                return false;
            });
    }

    function acquireLoopLock() {
        const lockManager = getLockManager();
        if (!lockManager || loopReleaseLock) {
            return Promise.resolve(true);
        }
        if (loopLockPending) {
            return Promise.resolve(false);
        }

        loopLockPending = true;
        return new Promise(resolve => {
            lockManager.request(lockName, { ifAvailable: true }, lock => {
                loopLockPending = false;
                if (!lock) {
                    resolve(false);
                    return undefined;
                }
                // Held until the loop stops or the browser refuses it.
                return new Promise(release => {
                    loopReleaseLock = () => {
                        loopReleaseLock = null;
                        release();
                    };
                    resolve(true);
                });
            }).catch(error => {
                loopLockPending = false;
                console.warn('Unable to acquire workflow alert sound lock:', error);
                resolve(false);
            });
        });
    }

    function releaseLoopLock() {
        if (loopReleaseLock) {
            loopReleaseLock();
        }
    }

    function loudestRepeatingPriority() {
        let loudest = null;
        repeatingAlerts.forEach(notification => {
            const priority = getNotificationPriority(notification);
            if (loudest === null || priorityRank[priority] > priorityRank[loudest]) {
                loudest = priority;
            }
        });
        return loudest;
    }

    function playLoopTone() {
        loopTickPending = true;
        return acquireLoopLock()
            .then(hasLock => {
                if (!hasLock) {
                    // Another tab is sounding, so nothing here waits for a click.
                    if (loopRefused) {
                        loopRefused = false;
                        announceState();
                    }
                    return undefined;
                }
                const priority = loudestRepeatingPriority();
                if (priority === null) {
                    releaseLoopLock();
                    return undefined;
                }
                return startPlayback(priority).then(
                    () => {
                        if (loopRefused) {
                            loopRefused = false;
                            announceState();
                        }
                    },
                    error => {
                        console.warn('Workflow alert sound playback was blocked:', error);
                        // Let go of the lock, so a tab that may play takes over.
                        loopRefused = true;
                        releaseLoopLock();
                        announceState();
                    }
                );
            })
            .finally(() => {
                loopTickPending = false;
            });
    }

    function tick() {
        if (!repeatingAlerts.size) {
            stopLoop();
            return;
        }
        if (loopRefused || loopTickPending || !canPlay()) {
            return;
        }
        playLoopTone();
    }

    function startLoop() {
        if (loopTimer !== null) {
            return;
        }
        loopRefused = false;
        loopTimer = window.setInterval(tick, WORKFLOW_ALERT_SOUND_REPEAT_MS);
        tick();
    }

    function stopLoop() {
        if (loopTimer !== null) {
            window.clearInterval(loopTimer);
            loopTimer = null;
        }
        loopRefused = false;
        releaseLoopLock();
    }

    function play(notification, options = {}) {
        const notificationId = normalizeId(notification?.id);
        if (!notificationId) {
            return Promise.resolve(false);
        }

        const mode = normalizeSoundMode(options.mode || getNotificationSoundMode(notification));
        if (mode === 'repeat') {
            repeatingAlerts.set(notificationId, notification);
            startLoop();
            return Promise.resolve(true);
        }
        if (mode === 'once' && !triedOnceIds.has(notificationId)) {
            triedOnceIds.add(notificationId);
            return playOnce(notification);
        }
        return Promise.resolve(false);
    }

    function stop(notificationId) {
        const normalizedId = normalizeId(notificationId);
        if (!normalizedId) {
            return;
        }

        repeatingAlerts.delete(normalizedId);
        refusedOnceAlerts.delete(normalizedId);
        if (!repeatingAlerts.size) {
            stopLoop();
        }
        announceState();
    }

    function stopAll() {
        repeatingAlerts.clear();
        refusedOnceAlerts.clear();
        stopLoop();
        announceState();
    }

    // Called from a click or key press. Acts only while a sound waits for one, so a sound that is
    // already playing is never started again, and Enable sound stays up until a retried sound
    // plays, so it never vanishes under the pointer or flickers on another refusal.
    function retryBlockedPlayback() {
        if (retryInFlight || !isBlocked()) {
            return;
        }

        retryInFlight = true;
        const attempts = [];
        if (loopRefused && repeatingAlerts.size && !loopTickPending) {
            attempts.push(playLoopTone());
        }
        Array.from(refusedOnceAlerts.values()).forEach(notification => {
            attempts.push(playOnce(notification));
        });
        Promise.allSettled(attempts).finally(() => {
            retryInFlight = false;
        });
    }

    function setAdminEnabled(enabled) {
        const nextEnabled = enabled === true;
        if (adminSoundsEnabled === nextEnabled) {
            return;
        }
        adminSoundsEnabled = nextEnabled;
        announceState();
        updateProfileControls();
    }

    function updateProfileStatus(message, type = 'muted') {
        const statusElement = document.getElementById('workflow-alert-sound-device-status');
        if (!statusElement) {
            return;
        }

        const classMap = {
            danger: 'text-danger',
            info: 'text-info',
            muted: 'text-muted',
            success: 'text-success',
        };
        statusElement.className = `preference-status small ${classMap[type] || classMap.muted}`;
        statusElement.textContent = message;
    }

    function updateProfileControls() {
        const toggle = document.getElementById('workflow-alert-sound-device-toggle');
        if (!toggle) {
            return;
        }

        toggle.checked = isDeviceEnabled();
        updateProfileStatus(
            toggle.checked
                ? 'Workflow alert sounds can play on this device when admins allow them.'
                : 'Workflow alert sounds are muted on this device.',
            toggle.checked ? 'success' : 'muted'
        );
    }

    function initializeProfileControls() {
        const toggle = document.getElementById('workflow-alert-sound-device-toggle');
        if (!toggle) {
            return;
        }

        updateProfileControls();
        toggle.addEventListener('change', () => {
            setDeviceEnabled(toggle.checked);
            updateProfileStatus(
                toggle.checked
                    ? 'Workflow alert sounds are enabled on this device.'
                    : 'Workflow alert sounds are muted on this device.',
                toggle.checked ? 'success' : 'muted'
            );
        });
    }

    window.simpleChatWorkflowAlertSound = {
        WORKFLOW_ALERT_SOUND_REPEAT_MS,
        get blocked() {
            return isBlocked();
        },
        get adminEnabled() {
            return adminSoundsEnabled;
        },
        isDeviceEnabled,
        play,
        retryBlockedPlayback,
        setAdminEnabled,
        setDeviceEnabled,
        stop,
        stopAll,
    };

    window.addEventListener('pointerdown', retryBlockedPlayback);
    window.addEventListener('keydown', retryBlockedPlayback);
    // The device switch is shared by every tab, classic and V2.
    window.addEventListener('storage', event => {
        if (event.key === playSoundsStorageKey) {
            updateProfileControls();
            announceState();
        }
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeProfileControls);
    } else {
        initializeProfileControls();
    }
})();
