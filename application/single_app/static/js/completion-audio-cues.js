// completion-audio-cues.js

(function() {
    'use strict';

    const soundCatalog = [
        { id: 'aurora', label: 'Aurora' },
        { id: 'bell', label: 'Bell' },
        { id: 'bloom', label: 'Bloom' },
        { id: 'chime', label: 'Chime' },
        { id: 'crystal', label: 'Crystal' },
        { id: 'glimmer', label: 'Glimmer' },
        { id: 'marimba', label: 'Marimba' },
        { id: 'pulse', label: 'Pulse' },
        { id: 'spark', label: 'Spark' },
        { id: 'summit', label: 'Summit' },
    ];
    const soundIds = new Set(soundCatalog.map(sound => sound.id));
    const defaultSoundId = soundCatalog[0].id;
    const defaultVolume = 5;
    const handledEventsStorageKey = 'simplechat-handled-completion-audio-events';
    const completionBaselineStorageKey = 'simplechat-completion-audio-baseline-ready';
    const completionBaselineStartedAtStorageKey = 'simplechat-completion-audio-baseline-started-at';
    const completionPreferencesStorageKey = 'simplechat-completion-audio-preferences';
    const maxHandledEvents = 200;
    const fallbackHandledEventKeysByUser = new Map();
    const fallbackBaselineUsers = new Set();
    let playbackQueue = Promise.resolve();
    let previewAudio = null;

    function getCurrentUserStorageSuffix() {
        const currentUserId = String(
            window.userContext?.id
            || window.current_user_id
            || 'anonymous'
        ).trim();
        return encodeURIComponent(currentUserId || 'anonymous');
    }

    function getUserStorageKey(baseKey) {
        return `${baseKey}:${getCurrentUserStorageSuffix()}`;
    }

    function readStoredHandledEventKeys() {
        try {
            const parsedValue = JSON.parse(
                localStorage.getItem(getUserStorageKey(handledEventsStorageKey)) || '[]'
            );
            return Array.isArray(parsedValue) ? parsedValue : [];
        } catch (error) {
            console.warn('Unable to read completion audio event history:', error);
            return fallbackHandledEventKeysByUser.get(getCurrentUserStorageSuffix()) || [];
        }
    }

    function writeStoredHandledEventKeys(eventKeys) {
        const boundedKeys = eventKeys.slice(-maxHandledEvents);
        fallbackHandledEventKeysByUser.set(
            getCurrentUserStorageSuffix(),
            boundedKeys
        );
        try {
            localStorage.setItem(
                getUserStorageKey(handledEventsStorageKey),
                JSON.stringify(boundedKeys)
            );
        } catch (error) {
            console.warn('Unable to persist completion audio event history:', error);
        }
    }

    function isBaselineReady() {
        try {
            return localStorage.getItem(
                getUserStorageKey(completionBaselineStorageKey)
            ) === 'true';
        } catch (error) {
            console.warn('Unable to read completion audio baseline state:', error);
            return fallbackBaselineUsers.has(getCurrentUserStorageSuffix());
        }
    }

    function markBaselineReady() {
        fallbackBaselineUsers.add(getCurrentUserStorageSuffix());
        try {
            localStorage.setItem(
                getUserStorageKey(completionBaselineStorageKey),
                'true'
            );
        } catch (error) {
            console.warn('Unable to persist completion audio baseline state:', error);
        }
    }

    function clearBaselineReady() {
        fallbackBaselineUsers.delete(getCurrentUserStorageSuffix());
        try {
            localStorage.removeItem(getUserStorageKey(completionBaselineStorageKey));
            localStorage.removeItem(
                getUserStorageKey(completionBaselineStartedAtStorageKey)
            );
        } catch (error) {
            console.warn('Unable to clear completion audio baseline state:', error);
        }
    }

    function getBaselineStartedAt() {
        try {
            return localStorage.getItem(
                getUserStorageKey(completionBaselineStartedAtStorageKey)
            );
        } catch (error) {
            console.warn('Unable to read completion audio baseline timestamp:', error);
            return null;
        }
    }

    function startBaselineWindow(startedAt = null) {
        if (getBaselineStartedAt()) {
            return;
        }

        const parsedStartedAt = Date.parse(String(startedAt || ''));
        const normalizedStartedAt = Number.isFinite(parsedStartedAt)
            ? new Date(parsedStartedAt).toISOString()
            : new Date().toISOString();
        try {
            localStorage.setItem(
                getUserStorageKey(completionBaselineStartedAtStorageKey),
                normalizedStartedAt
            );
        } catch (error) {
            console.warn('Unable to persist completion audio baseline timestamp:', error);
        }
    }

    function normalizeVolume(value) {
        const parsedVolume = Number.parseInt(value, 10);
        if (!Number.isInteger(parsedVolume)) {
            return defaultVolume;
        }
        return Math.min(10, Math.max(1, parsedVolume));
    }

    function normalizeSoundId(value) {
        const normalizedValue = String(value || '').trim().toLowerCase();
        return soundIds.has(normalizedValue) ? normalizedValue : defaultSoundId;
    }

    function getPreferences() {
        const userSettings = window.simplechatUserSettings || {};
        return {
            adminEnabled: window.appSettings?.enable_chat_completion_audio_cues === true,
            enabled: userSettings.chatCompletionAudioEnabled === true,
            muted: userSettings.chatCompletionAudioMuted === true,
            soundId: normalizeSoundId(userSettings.chatCompletionAudioSound),
            volume: normalizeVolume(userSettings.chatCompletionAudioVolume),
        };
    }

    function updatePreferences(preferences) {
        window.simplechatUserSettings = {
            ...(window.simplechatUserSettings || {}),
            ...preferences,
        };
        const normalizedPreferences = getPreferences();
        const synchronizedPreferences = {
            chatCompletionAudioEnabled: normalizedPreferences.enabled,
            chatCompletionAudioMuted: normalizedPreferences.muted,
            chatCompletionAudioSound: normalizedPreferences.soundId,
            chatCompletionAudioVolume: normalizedPreferences.volume,
        };
        try {
            localStorage.setItem(
                getUserStorageKey(completionPreferencesStorageKey),
                JSON.stringify(synchronizedPreferences)
            );
        } catch (error) {
            console.warn('Unable to synchronize completion audio preferences:', error);
        }
    }

    function setAdminEnabled(enabled, updatedAt = null) {
        const wasEnabled = window.appSettings?.enable_chat_completion_audio_cues === true;
        window.appSettings = {
            ...(window.appSettings || {}),
            enable_chat_completion_audio_cues: enabled === true,
            chat_completion_audio_cues_updated_at: updatedAt || null,
        };
        if (!enabled) {
            clearBaselineReady();
        } else if (!wasEnabled) {
            startBaselineWindow(updatedAt);
        } else if (!isBaselineReady()) {
            startBaselineWindow();
        }
    }

    function refreshAdminEnabled() {
        return fetch('/api/notifications/chat-completion-audio-status', {
            headers: {
                'Accept': 'application/json',
            },
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Completion audio status returned HTTP ${response.status}.`);
                }
                return response.json();
            })
            .then(data => {
                setAdminEnabled(data.enabled === true, data.updated_at);
                return data.enabled === true;
            });
    }

    function getEventMessageId(completionEvent) {
        return String(
            completionEvent?.messageId
            || completionEvent?.message_id
            || completionEvent?.metadata?.message_id
            || ''
        ).trim();
    }

    function getEventConversationId(completionEvent) {
        return String(
            completionEvent?.conversationId
            || completionEvent?.conversation_id
            || completionEvent?.metadata?.conversation_id
            || completionEvent?.link_context?.conversation_id
            || ''
        ).trim();
    }

    function getCompletionEventKey(completionEvent) {
        const messageId = getEventMessageId(completionEvent);
        if (messageId) {
            return `message:${messageId}`;
        }

        const notificationId = String(
            completionEvent?.notificationId
            || completionEvent?.notification_id
            || completionEvent?.id
            || ''
        ).trim();
        return notificationId ? `notification:${notificationId}` : '';
    }

    function rememberCompletionEvent(completionEvent) {
        const eventKey = getCompletionEventKey(completionEvent);
        if (!eventKey) {
            return false;
        }

        const handledEventKeys = readStoredHandledEventKeys();
        if (handledEventKeys.includes(eventKey)) {
            return false;
        }

        handledEventKeys.push(eventKey);
        writeStoredHandledEventKeys(handledEventKeys);
        return true;
    }

    function shouldPlayCompletionEvent(completionEvent) {
        const preferences = getPreferences();
        if (
            !preferences.adminEnabled
            || !preferences.enabled
            || preferences.muted
        ) {
            return false;
        }

        const completedConversationId = getEventConversationId(completionEvent);
        const activeConversationId = String(window.currentConversationId || '').trim();
        const documentInactive = document.visibilityState !== 'visible';
        const windowUnfocused = typeof document.hasFocus === 'function'
            ? !document.hasFocus()
            : false;

        return (
            documentInactive
            || windowUnfocused
            || !activeConversationId
            || activeConversationId !== completedConversationId
        );
    }

    function getSoundUrl(soundId) {
        return `/static/audio/completion-cues/${normalizeSoundId(soundId)}.wav`;
    }

    function playAudio(soundId, volume) {
        return new Promise((resolve, reject) => {
            const audio = new Audio(getSoundUrl(soundId));
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

            audio.volume = normalizeVolume(volume) / 10;
            audio.addEventListener('ended', () => settle(resolve, true), { once: true });
            audio.addEventListener(
                'error',
                () => settle(reject, new Error('Completion audio asset could not be played.')),
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

    function enqueueCompletionSound(preferences) {
        playbackQueue = playbackQueue
            .catch(() => undefined)
            .then(() => playAudio(preferences.soundId, preferences.volume))
            .catch(error => {
                console.warn('Completion audio playback was blocked or failed:', error);
            });
        return playbackQueue;
    }

    function handleClaimedCompletion(completionEvent) {
        if (!shouldPlayCompletionEvent(completionEvent)) {
            return Promise.resolve(false);
        }

        return enqueueCompletionSound(getPreferences()).then(() => true);
    }

    function handleCompletion(completionEvent, options = {}) {
        const eventKey = getCompletionEventKey(completionEvent);
        if (!eventKey) {
            return Promise.resolve(false);
        }

        const claimCompletion = () => {
            if (options.refreshAdminGate === true) {
                return refreshAdminEnabled()
                    .then(() => {
                        if (!rememberCompletionEvent(completionEvent)) {
                            return false;
                        }
                        return handleClaimedCompletion(completionEvent);
                    })
                    .catch(error => {
                        console.warn(
                            'Unable to verify completion audio admin status:',
                            error
                        );
                        return false;
                    });
            }
            if (!rememberCompletionEvent(completionEvent)) {
                return false;
            }
            return handleClaimedCompletion(completionEvent);
        };
        const lockManager = typeof navigator !== 'undefined'
            ? navigator.locks
            : null;
        if (lockManager?.request) {
            const lockName = [
                'simplechat-completion-audio',
                getCurrentUserStorageSuffix(),
                eventKey,
            ].join(':');
            return lockManager.request(lockName, claimCompletion);
        }

        return Promise.resolve(claimCompletion());
    }

    function processPolledEvents(completionEvents) {
        const normalizedEvents = Array.isArray(completionEvents)
            ? completionEvents
            : [];

        if (!isBaselineReady()) {
            startBaselineWindow();
            const baselineStartedAt = Date.parse(getBaselineStartedAt() || '');
            const playbackResults = [];
            const chronologicalEvents = [...normalizedEvents].reverse();
            return chronologicalEvents.reduce(
                (chain, completionEvent) => chain.then(() => {
                    const completedAt = Date.parse(
                        String(completionEvent?.created_at || '')
                    );
                    if (
                        Number.isFinite(completedAt)
                        && Number.isFinite(baselineStartedAt)
                        && completedAt > baselineStartedAt
                    ) {
                        return handleCompletion(completionEvent).then(result => {
                            playbackResults.push(result);
                        });
                    }
                    rememberCompletionEvent(completionEvent);
                    return undefined;
                }),
                Promise.resolve()
            ).then(() => {
                markBaselineReady();
                return playbackResults;
            });
        }

        const playbackResults = [];
        const chronologicalEvents = [...normalizedEvents].reverse();
        return chronologicalEvents.reduce(
            (chain, completionEvent) => chain.then(() => (
                handleCompletion(completionEvent).then(result => {
                    playbackResults.push(result);
                })
            )),
            Promise.resolve()
        ).then(() => playbackResults);
    }

    function previewSound(soundId, volume) {
        if (previewAudio) {
            previewAudio.pause();
            previewAudio.currentTime = 0;
        }

        previewAudio = new Audio(getSoundUrl(soundId));
        previewAudio.volume = normalizeVolume(volume) / 10;
        try {
            const playResult = previewAudio.play();
            return playResult && typeof playResult.catch === 'function'
                ? playResult
                : Promise.resolve();
        } catch (error) {
            return Promise.reject(error);
        }
    }

    function resetTestState() {
        fallbackHandledEventKeysByUser.delete(getCurrentUserStorageSuffix());
        fallbackBaselineUsers.delete(getCurrentUserStorageSuffix());
        try {
            localStorage.removeItem(getUserStorageKey(handledEventsStorageKey));
            localStorage.removeItem(getUserStorageKey(completionBaselineStorageKey));
            localStorage.removeItem(
                getUserStorageKey(completionBaselineStartedAtStorageKey)
            );
        } catch (error) {
            console.warn('Unable to reset completion audio test state:', error);
        }
    }

    function initializePreferenceSync() {
        const initialPreferences = normalizeChatCompletionPreferences(
            window.simplechatUserSettings || {}
        );
        updatePreferences(initialPreferences);
        window.addEventListener('storage', event => {
            if (
                event.key !== getUserStorageKey(completionPreferencesStorageKey)
                || !event.newValue
            ) {
                return;
            }
            try {
                const preferences = JSON.parse(event.newValue);
                window.simplechatUserSettings = {
                    ...(window.simplechatUserSettings || {}),
                    ...preferences,
                };
            } catch (error) {
                console.warn('Unable to apply synchronized completion audio preferences:', error);
            }
        });
    }

    function normalizeChatCompletionPreferences(settings) {
        const source = settings || {};
        return {
            chatCompletionAudioEnabled: source.chatCompletionAudioEnabled === true,
            chatCompletionAudioMuted: source.chatCompletionAudioMuted === true,
            chatCompletionAudioSound: normalizeSoundId(
                source.chatCompletionAudioSound
            ),
            chatCompletionAudioVolume: normalizeVolume(
                source.chatCompletionAudioVolume
            ),
        };
    }

    function updateProfileStatus(message, type = 'muted') {
        const statusElement = document.getElementById('completion-audio-preference-status');
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

    function initializeProfileControls() {
        const enabledToggle = document.getElementById('completion-audio-enabled-toggle');
        const mutedToggle = document.getElementById('completion-audio-muted-toggle');
        const soundSelect = document.getElementById('completion-audio-sound-select');
        const volumeRange = document.getElementById('completion-audio-volume-range');
        const volumeValue = document.getElementById('completion-audio-volume-value');
        const previewButton = document.getElementById('preview-completion-audio-btn');
        const saveButton = document.getElementById('save-completion-audio-preferences-btn');
        if (
            !enabledToggle
            || !mutedToggle
            || !soundSelect
            || !volumeRange
            || !volumeValue
            || !previewButton
            || !saveButton
        ) {
            return;
        }

        volumeRange.addEventListener('input', () => {
            volumeValue.textContent = String(normalizeVolume(volumeRange.value));
        });

        previewButton.addEventListener('click', () => {
            previewButton.disabled = true;
            updateProfileStatus('Playing the selected completion sound...', 'info');
            previewSound(soundSelect.value, volumeRange.value)
                .then(() => {
                    updateProfileStatus('Preview played. Save to keep this selection.', 'success');
                })
                .catch(error => {
                    console.warn('Completion sound preview failed:', error);
                    updateProfileStatus(
                        'The browser blocked the preview. Interact with the page and try again.',
                        'danger'
                    );
                })
                .finally(() => {
                    previewButton.disabled = false;
                });
        });

        saveButton.addEventListener('click', () => {
            const preferences = {
                chatCompletionAudioEnabled: enabledToggle.checked,
                chatCompletionAudioMuted: mutedToggle.checked,
                chatCompletionAudioSound: normalizeSoundId(soundSelect.value),
                chatCompletionAudioVolume: normalizeVolume(volumeRange.value),
            };

            saveButton.disabled = true;
            updateProfileStatus('Saving your completion audio preferences...', 'info');
            fetch('/api/user/settings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    settings: preferences,
                }),
            })
                .then(async response => {
                    if (!response.ok) {
                        const data = await response.json().catch(() => ({}));
                        throw new Error(data.error || 'Failed to save completion audio preferences.');
                    }
                    return response.json();
                })
                .then(() => {
                    updatePreferences(preferences);
                    updateProfileStatus(
                        preferences.chatCompletionAudioEnabled
                            ? 'Completion audio preferences saved.'
                            : 'Completion audio remains off until you enable it here.',
                        'success'
                    );
                    if (typeof window.showToastMessage === 'function') {
                        window.showToastMessage('Completion audio preferences saved', 'success');
                    }
                })
                .catch(error => {
                    console.error('Error saving completion audio preferences:', error);
                    updateProfileStatus(error.message, 'danger');
                })
                .finally(() => {
                    saveButton.disabled = false;
                });
        });

        updateProfileStatus(
            enabledToggle.checked
                ? 'Completion cues are enabled for background responses.'
                : 'Completion cues are off by default until you opt in.'
        );
    }

    window.simpleChatCompletionAudio = {
        catalog: soundCatalog.map(sound => ({ ...sound })),
        getPreferences,
        handleCompletion,
        isPollingEnabled: () => {
            const preferences = getPreferences();
            return preferences.adminEnabled;
        },
        previewSound,
        processPolledEvents,
        resetTestState,
        setAdminEnabled,
        shouldPlayCompletionEvent,
        updatePreferences,
    };

    initializePreferenceSync();
    if (getPreferences().adminEnabled && !isBaselineReady()) {
        startBaselineWindow();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeProfileControls);
    } else {
        initializeProfileControls();
    }
})();
