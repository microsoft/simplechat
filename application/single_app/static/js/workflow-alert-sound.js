// workflow-alert-sound.js

(function() {
    'use strict';

    const WORKFLOW_ALERT_SOUND_REPEAT_MS = 5000;
    const playSoundsStorageKey = 'simplechat.workflowAlerts.playSounds';
    const lockName = 'simplechat.workflowAlertSound';
    const alertTimers = new Map();
    const activeAlerts = new Map();
    let adminSoundsEnabled = true;
    let blockedPlayback = false;
    let lockHeld = false;
    let releaseLock = null;
    let retryPending = false;

    function normalizePriority(priority) {
        const normalizedPriority = String(priority || '').trim().toLowerCase();
        if (['critical', 'high', 'medium', 'low', 'info'].includes(normalizedPriority)) {
            return normalizedPriority;
        }
        return 'medium';
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
    }

    function shouldAttemptPlayback(notification) {
        return (
            adminSoundsEnabled === true
            && isDeviceEnabled()
            && getNotificationSoundMode(notification) !== 'off'
        );
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
                blocked: blockedPlayback,
                deviceEnabled: isDeviceEnabled(),
                adminEnabled: adminSoundsEnabled,
            },
        }));
    }

    function setBlockedPlayback(blocked) {
        if (blockedPlayback === blocked) {
            return;
        }
        blockedPlayback = blocked;
        announceState();
    }

    function playAudio(priority) {
        return new Promise((resolve, reject) => {
            const audio = new Audio(getSoundUrl(priority));
            let settled = false;
            const playbackTimeout = window.setTimeout(() => {
                settle(resolve, false);
            }, 3000);

            function settle(callback, value) {
                if (settled) {
                    return;
                }
                settled = true;
                window.clearTimeout(playbackTimeout);
                callback(value);
            }

            audio.addEventListener('ended', () => settle(resolve, true), { once: true });
            audio.addEventListener(
                'error',
                () => settle(reject, new Error('Workflow alert sound could not be played.')),
                { once: true }
            );

            try {
                const playResult = audio.play();
                if (playResult && typeof playResult.catch === 'function') {
                    playResult.catch(error => settle(reject, error));
                }
            } catch (error) {
                settle(reject, error);
            }
        });
    }

    function acquireLock() {
        if (lockHeld) {
            return Promise.resolve(true);
        }

        const lockManager = typeof navigator !== 'undefined' ? navigator.locks : null;
        if (!lockManager?.request) {
            lockHeld = true;
            return Promise.resolve(true);
        }

        return new Promise(resolve => {
            lockManager.request(lockName, { ifAvailable: true }, async lock => {
                if (!lock) {
                    resolve(false);
                    return;
                }

                lockHeld = true;
                resolve(true);
                await new Promise(lockResolve => {
                    releaseLock = lockResolve;
                });
                lockHeld = false;
                releaseLock = null;
            }).catch(error => {
                console.warn('Unable to acquire workflow alert sound lock:', error);
                resolve(false);
            });
        });
    }

    function releaseLockIfIdle() {
        if (activeAlerts.size || !releaseLock) {
            return;
        }

        releaseLock();
    }

    function attemptPlayback(notification) {
        if (!shouldAttemptPlayback(notification)) {
            return Promise.resolve(false);
        }

        return acquireLock()
            .then(hasLock => {
                if (!hasLock) {
                    return false;
                }
                return playAudio(getNotificationPriority(notification))
                    .then(() => {
                        setBlockedPlayback(false);
                        return true;
                    })
                    .catch(error => {
                        console.warn('Workflow alert sound playback was blocked or failed:', error);
                        setBlockedPlayback(true);
                        return false;
                    })
                    .finally(releaseLockIfIdle);
            });
    }

    // A repeating alert keeps its loop while it is pending, and every tick checks the admin, device
    // and rule gates, so turning sound off silences it at once and turning it back on resumes it.
    function start(notification, options = {}) {
        const notificationId = String(notification?.id || '').trim();
        if (!notificationId) {
            return Promise.resolve(false);
        }

        const mode = normalizeSoundMode(options.mode || getNotificationSoundMode(notification));
        if (mode === 'off') {
            return Promise.resolve(false);
        }

        activeAlerts.set(notificationId, notification);
        if (mode === 'repeat') {
            if (!alertTimers.has(notificationId)) {
                const timer = window.setInterval(() => {
                    if (activeAlerts.has(notificationId)) {
                        attemptPlayback(notification);
                    }
                }, WORKFLOW_ALERT_SOUND_REPEAT_MS);
                alertTimers.set(notificationId, timer);
            }
            return attemptPlayback(notification);
        }

        return attemptPlayback(notification).finally(() => {
            if (!alertTimers.has(notificationId)) {
                activeAlerts.delete(notificationId);
                releaseLockIfIdle();
            }
        });
    }

    function stop(notificationId) {
        const normalizedId = String(notificationId || '').trim();
        if (!normalizedId) {
            return;
        }

        const timer = alertTimers.get(normalizedId);
        if (timer) {
            window.clearInterval(timer);
            alertTimers.delete(normalizedId);
        }
        activeAlerts.delete(normalizedId);
        releaseLockIfIdle();
    }

    function stopAll() {
        Array.from(alertTimers.keys()).forEach(stop);
        activeAlerts.clear();
        releaseLockIfIdle();
    }

    function retryBlockedPlayback() {
        if (!blockedPlayback || retryPending) {
            return;
        }

        retryPending = true;
        const alerts = Array.from(activeAlerts.values());
        alerts.reduce(
            (chain, notification) => chain.then(() => attemptPlayback(notification)),
            Promise.resolve()
        ).finally(() => {
            retryPending = false;
        });
    }

    function setAdminEnabled(enabled) {
        adminSoundsEnabled = enabled === true;
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
            return blockedPlayback;
        },
        get adminEnabled() {
            return adminSoundsEnabled;
        },
        isDeviceEnabled,
        play: start,
        retryBlockedPlayback,
        setAdminEnabled,
        setDeviceEnabled,
        stop,
        stopAll,
    };

    window.addEventListener('pointerdown', retryBlockedPlayback);
    window.addEventListener('keydown', retryBlockedPlayback);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeProfileControls);
    } else {
        initializeProfileControls();
    }
})();
