// idle-logout-warning.js

(function () {
    'use strict';

    const defaultConfig = {
        enabled: false,
        timeoutMinutes: 30,
        warningMinutes: 28,
        heartbeatUrl: '/api/session/heartbeat',
        localLogoutUrl: '/logout/local',
        fullSsoLogoutUrl: '/logout',
        logoutUrl: '/logout'
    };

    const mergedConfig = Object.assign({}, defaultConfig, window.idleLogoutConfig || {});

    if (!mergedConfig.enabled) {
        return;
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (typeof bootstrap === 'undefined' || !bootstrap.Modal) {
            return;
        }

        const warningModalElement = document.getElementById('idleTimeoutWarningModal');
        const countdownElement = document.getElementById('idleTimeoutCountdown');
        const staySignedInButton = document.getElementById('idleStaySignedInButton');
        const logoutNowButton = document.getElementById('idleLogoutNowButton');

        if (!warningModalElement || !countdownElement || !staySignedInButton || !logoutNowButton) {
            return;
        }

        const timeoutMinutes = Number(mergedConfig.timeoutMinutes);
        const warningMinutes = Number(mergedConfig.warningMinutes);

        if (!Number.isFinite(timeoutMinutes) || timeoutMinutes <= 0) {
            return;
        }

        if (!Number.isFinite(warningMinutes) || warningMinutes < 0 || warningMinutes >= timeoutMinutes) {
            return;
        }

        const timeoutMs = timeoutMinutes * 60 * 1000;
        const warningMs = warningMinutes * 60 * 1000;
        const warningModal = bootstrap.Modal.getOrCreateInstance(warningModalElement);

        let warningTimer = null;
        let logoutTimer = null;
        let countdownInterval = null;
        let logoutDeadlineMs = null;
        let isRefreshingSession = false;
        let pendingUserInitiatedRefresh = false;
        let lastActivityResetAt = 0;
        let lastServerHeartbeatAt = 0;

        const HEARTBEAT_MIN_INTERVAL_MS = Math.min(60000, timeoutMs / 2);

        const activityEvents = [
            'mousedown',
            'mousemove',
            'keydown',
            'scroll',
            'touchstart',
            'click'
        ];

        function clearTimers() {
            if (warningTimer) {
                clearTimeout(warningTimer);
                warningTimer = null;
            }

            if (logoutTimer) {
                clearTimeout(logoutTimer);
                logoutTimer = null;
            }
        }

        function stopCountdown() {
            if (countdownInterval) {
                clearInterval(countdownInterval);
                countdownInterval = null;
            }
        }

        function updateCountdown() {
            if (!logoutDeadlineMs) {
                return;
            }

            const remainingMs = Math.max(0, logoutDeadlineMs - Date.now());
            const remainingSeconds = Math.ceil(remainingMs / 1000);
            countdownElement.textContent = String(remainingSeconds);
        }

        function startCountdown() {
            stopCountdown();
            updateCountdown();
            countdownInterval = setInterval(updateCountdown, 1000);
        }

        function hideWarningModal() {
            if (warningModalElement.classList.contains('show')) {
                warningModal.hide();
            }
            stopCountdown();
        }

        function logoutNow() {
            clearTimers();
            stopCountdown();
            const logoutTarget = mergedConfig.localLogoutUrl || mergedConfig.fullSsoLogoutUrl || mergedConfig.logoutUrl;
            window.location.href = logoutTarget;
        }

        function scheduleIdleTimers() {
            clearTimers();
            logoutDeadlineMs = Date.now() + timeoutMs;

            warningTimer = setTimeout(function () {
                warningModal.show();
                startCountdown();
            }, warningMs);

            logoutTimer = setTimeout(logoutNow, timeoutMs);
        }

        async function refreshServerSession(forceLogoutOnFailure, userInitiated) {
            if (isRefreshingSession) {
                if (userInitiated) {
                    pendingUserInitiatedRefresh = true;
                    staySignedInButton.disabled = true;
                }
                return;
            }

            isRefreshingSession = true;
            const isUserInitiatedRefresh = Boolean(userInitiated);
            if (isUserInitiatedRefresh) {
                staySignedInButton.disabled = true;
            }

            try {
                const response = await fetch(mergedConfig.heartbeatUrl, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: '{}'
                });

                if (!response.ok) {
                    let requiresReauth = response.status === 401 || response.status === 403;

                    if (!requiresReauth) {
                        try {
                            const responseBody = await response.clone().json();
                            requiresReauth = Boolean(responseBody && responseBody.requires_reauth);
                        } catch (_parseError) {
                            requiresReauth = false;
                        }
                    }

                    if (forceLogoutOnFailure || requiresReauth) {
                        logoutNow();
                    }
                    return;
                }

                lastServerHeartbeatAt = Date.now();

                if (isUserInitiatedRefresh) {
                    hideWarningModal();
                    scheduleIdleTimers();
                }
            } catch (error) {
                console.error('Session heartbeat failed:', error);
                if (forceLogoutOnFailure) {
                    logoutNow();
                }
            } finally {
                isRefreshingSession = false;
                if (isUserInitiatedRefresh) {
                    staySignedInButton.disabled = false;
                }

                if (pendingUserInitiatedRefresh) {
                    pendingUserInitiatedRefresh = false;
                    fireAndForgetSessionRefresh(true, true);
                }
            }
        }

        function fireAndForgetSessionRefresh(forceLogoutOnFailure, userInitiated) {
            void refreshServerSession(forceLogoutOnFailure, userInitiated).catch(function (error) {
                console.error('Unexpected session refresh error:', error);
                if (forceLogoutOnFailure) {
                    logoutNow();
                }
            });
        }

        staySignedInButton.addEventListener('click', function () {
            fireAndForgetSessionRefresh(true, true);
        });

        logoutNowButton.addEventListener('click', function () {
            logoutNow();
        });

        warningModalElement.addEventListener('hidden.bs.modal', function () {
            stopCountdown();
        });

        activityEvents.forEach(function (eventName) {
            document.addEventListener(eventName, handleUserActivity);
        });

        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) {
                handleUserActivity();
            }
        });

        scheduleIdleTimers();

        function handleUserActivity() {
            const now = Date.now();

            if (now - lastActivityResetAt < 1000) {
                return;
            }

            lastActivityResetAt = now;

            if (warningModalElement.classList.contains('show')) {
                hideWarningModal();
            }

            scheduleIdleTimers();

            if ((now - lastServerHeartbeatAt) >= HEARTBEAT_MIN_INTERVAL_MS) {
                fireAndForgetSessionRefresh(false, false);
            }
        }
    });
})();
