# test_chat_completion_audio_cues.py
"""
Functional test for configurable AI response completion audio cues.
Version: 0.250.103
Implemented in: 0.250.103

This test validates local assets, settings and route wiring, and executable
browser behavior for foreground suppression, background playback, volume
mapping, concurrent completions, and duplicate prevention.
"""

import json
import hashlib
import subprocess
import sys
import wave
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
AUDIO_DIR = APP_DIR / "static" / "audio" / "completion-cues"
RUNTIME_JS = APP_DIR / "static" / "js" / "completion-audio-cues.js"
NOTIFICATIONS_JS = APP_DIR / "static" / "js" / "notifications.js"
STREAMING_JS = APP_DIR / "static" / "js" / "chat" / "chat-streaming.js"
SETTINGS_PY = APP_DIR / "functions_settings.py"
USERS_ROUTE_PY = APP_DIR / "route_backend_users.py"
NOTIFICATIONS_ROUTE_PY = APP_DIR / "route_backend_notifications.py"
ADMIN_ROUTE_PY = APP_DIR / "route_frontend_admin_settings.py"
ADMIN_TEMPLATE = APP_DIR / "templates" / "admin_settings.html"
PROFILE_TEMPLATE = APP_DIR / "templates" / "profile.html"
BASE_TEMPLATE = APP_DIR / "templates" / "base.html"
CHATS_TEMPLATE = APP_DIR / "templates" / "chats.html"


EXPECTED_SOUND_IDS = [
    "aurora",
    "bell",
    "bloom",
    "chime",
    "crystal",
    "glimmer",
    "marimba",
    "pulse",
    "spark",
    "summit",
]


def read_text(path):
    """Read a UTF-8 source file."""
    return path.read_text(encoding="utf-8")


def test_local_audio_assets():
    """Validate exactly ten readable, non-empty, locally bundled WAV cues."""
    wav_files = sorted(AUDIO_DIR.glob("*.wav"))
    assert [path.stem for path in wav_files] == EXPECTED_SOUND_IDS
    assert (AUDIO_DIR / "LICENSE.txt").exists()

    asset_hashes = set()
    for wav_path in wav_files:
        asset_hashes.add(hashlib.sha256(wav_path.read_bytes()).hexdigest())
        with wave.open(str(wav_path), "rb") as cue:
            assert cue.getnchannels() == 1
            assert cue.getsampwidth() == 2
            assert cue.getframerate() == 44100
            assert cue.getnframes() > 0
    assert len(asset_hashes) == len(EXPECTED_SOUND_IDS)


def test_settings_and_ui_contracts():
    """Validate admin gating and normalized user preference persistence wiring."""
    settings_source = read_text(SETTINGS_PY)
    users_route_source = read_text(USERS_ROUTE_PY)
    notifications_route_source = read_text(NOTIFICATIONS_ROUTE_PY)
    admin_route_source = read_text(ADMIN_ROUTE_PY)
    admin_template_source = read_text(ADMIN_TEMPLATE)
    profile_template_source = read_text(PROFILE_TEMPLATE)
    base_template_source = read_text(BASE_TEMPLATE)
    chats_template_source = read_text(CHATS_TEMPLATE)

    assert "'enable_chat_completion_audio_cues': False" in settings_source
    assert '"chatCompletionAudioEnabled": source.get("chatCompletionAudioEnabled") is True' in settings_source
    assert '"chatCompletionAudioMuted": source.get("chatCompletionAudioMuted") is True' in settings_source
    assert "DEFAULT_CHAT_COMPLETION_AUDIO_VOLUME = 5" in settings_source
    assert "min(10, max(1, volume))" in settings_source
    assert "CHAT_COMPLETION_AUDIO_SOUND_IDS" in users_route_source
    assert "Completion audio volume must be between 1 and 10" in users_route_source

    assert "enable_chat_completion_audio_cues" in admin_route_source
    assert 'id="enable_chat_completion_audio_cues"' in admin_template_source
    assert "{% if app_settings.enable_chat_completion_audio_cues %}" in profile_template_source
    assert 'id="completion-audio-enabled-toggle"' in profile_template_source
    assert 'id="completion-audio-muted-toggle"' in profile_template_source
    assert 'id="completion-audio-sound-select"' in profile_template_source
    assert 'id="completion-audio-volume-range"' in profile_template_source
    assert "completion-audio-cues.js" in base_template_source
    assert "...(window.appSettings || {})" in chats_template_source

    assert '@bp.route("/api/notifications/chat-completions", methods=["GET"])' in notifications_route_source
    assert '@bp.route("/api/notifications/chat-completion-audio-status", methods=["GET"])' in notifications_route_source
    assert "@swagger_route(security=get_auth_security())" in notifications_route_source
    assert "get_recent_chat_response_notifications" in notifications_route_source
    assert "'chat_completion_audio_enabled': completion_audio_enabled" in notifications_route_source
    assert "getUserStorageKey(handledEventsStorageKey)" in read_text(RUNTIME_JS)
    assert "navigator.locks" in read_text(RUNTIME_JS)


def test_completion_event_wiring():
    """Validate polling and successful-stream hooks share the audio manager."""
    notifications_source = read_text(NOTIFICATIONS_JS)
    streaming_source = read_text(STREAMING_JS)

    assert "/api/notifications/chat-completions?limit=50" in notifications_source
    assert "completionAudio.processPolledEvents" in notifications_source
    assert "refreshCompletionEvents: loadChatCompletionEvents" in notifications_source
    assert "function notifySuccessfulStreamingCompletion(finalData)" in streaming_source
    assert "window.simpleChatCompletionAudio.handleCompletion" in streaming_source
    assert "refreshAdminGate: true" in streaming_source
    assert streaming_source.count("notifySuccessfulStreamingCompletion(finalData);") == 1
    finalize_source = streaming_source.split(
        "function finalizeStreamingMessage(",
        maxsplit=1,
    )[1]
    assert (
        finalize_source.index("notifySuccessfulStreamingCompletion(finalData);")
        < finalize_source.index("if (!messageElement) return;")
    )


def test_browser_runtime_behavior():
    """Execute the browser manager in Node with deterministic DOM and Audio fakes."""
    node_harness = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const storage = new Map();
const playedAudio = [];

global.localStorage = {
    getItem: key => storage.has(key) ? storage.get(key) : null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
};
global.navigator = {
    locks: {
        request: async (_name, callback) => callback(),
    },
};
global.document = {
    readyState: 'complete',
    visibilityState: 'visible',
    hasFocus: () => true,
    getElementById: () => null,
    addEventListener: () => undefined,
};
global.window = {
    appSettings: { enable_chat_completion_audio_cues: true },
    simplechatUserSettings: {
        chatCompletionAudioEnabled: true,
        chatCompletionAudioMuted: false,
        chatCompletionAudioSound: 'aurora',
        chatCompletionAudioVolume: 7,
    },
    currentConversationId: 'active-conversation',
    setTimeout,
    clearTimeout,
    addEventListener: () => undefined,
};
global.Audio = class FakeAudio {
    constructor(url) {
        this.url = url;
        this.volume = 1;
        this.listeners = {};
    }
    addEventListener(name, callback) {
        this.listeners[name] = callback;
    }
    pause() {}
    play() {
        playedAudio.push({ url: this.url, volume: this.volume });
        queueMicrotask(() => {
            if (this.listeners.ended) {
                this.listeners.ended();
            }
        });
        return Promise.resolve();
    }
};
global.fetch = async () => {
    throw new Error('simulated status failure');
};

eval(source);
const manager = window.simpleChatCompletionAudio;

async function run() {
    manager.resetTestState();
    const futureCompletion = new Date(Date.now() + 1000).toISOString();
    await manager.processPolledEvents([
        {
            id: 'fresh-before-first-poll',
            created_at: futureCompletion,
            metadata: {
                message_id: 'fresh-before-first-poll',
                conversation_id: 'other'
            }
        },
    ]);
    const freshFirstPollCount = playedAudio.length;
    playedAudio.splice(0, playedAudio.length);

    manager.resetTestState();
    await manager.processPolledEvents([
        { id: 'historical', metadata: { message_id: 'old', conversation_id: 'other' } },
    ]);
    const afterBaseline = playedAudio.length;

    const foregroundResult = await manager.handleCompletion({
        messageId: 'foreground',
        conversationId: 'active-conversation',
    });
    const afterForeground = playedAudio.length;

    const backgroundResult = await manager.handleCompletion({
        messageId: 'background',
        conversationId: 'other-conversation',
    });
    const afterBackground = playedAudio.length;
    await manager.handleCompletion({
        messageId: 'background',
        conversationId: 'other-conversation',
    });
    const afterDuplicate = playedAudio.length;

    document.visibilityState = 'hidden';
    const hiddenResult = await manager.handleCompletion({
        messageId: 'hidden-active',
        conversationId: 'active-conversation',
    });
    const afterHidden = playedAudio.length;

    document.visibilityState = 'visible';
    document.hasFocus = () => false;
    const unfocusedResult = await manager.handleCompletion({
        messageId: 'unfocused-active',
        conversationId: 'active-conversation',
    });
    const afterUnfocused = playedAudio.length;

    document.hasFocus = () => true;
    manager.updatePreferences({ chatCompletionAudioMuted: true });
    await manager.handleCompletion({
        messageId: 'muted',
        conversationId: 'other-conversation',
    });
    const afterMuted = playedAudio.length;

    manager.updatePreferences({ chatCompletionAudioMuted: false });
    await manager.processPolledEvents([
        { id: 'second', metadata: { message_id: 'concurrent-2', conversation_id: 'two' } },
        { id: 'first', metadata: { message_id: 'concurrent-1', conversation_id: 'one' } },
    ]);
    const afterConcurrent = playedAudio.length;

    manager.setAdminEnabled(false);
    await manager.handleCompletion({
        messageId: 'disabled-period-claimed',
        conversationId: 'other-conversation',
    });
    const afterAdminDisabled = playedAudio.length;

    manager.setAdminEnabled(true);
    await manager.processPolledEvents([
        {
            id: 'disabled-period-event',
            metadata: {
                message_id: 'disabled-period-unseen',
                conversation_id: 'other-conversation'
            }
        },
    ]);
    const afterReenableBaseline = playedAudio.length;
    await manager.handleCompletion({
        messageId: 'post-reenable',
        conversationId: 'other-conversation',
    });
    const afterPostReenable = playedAudio.length;

    const failedRefreshResult = await manager.handleCompletion({
        messageId: 'status-retry',
        conversationId: 'other-conversation',
    }, {
        refreshAdminGate: true,
    });
    const afterFailedRefresh = playedAudio.length;
    await manager.handleCompletion({
        messageId: 'status-retry',
        conversationId: 'other-conversation',
    });
    const afterStatusRetry = playedAudio.length;

    console.log(JSON.stringify({
        afterBaseline,
        freshFirstPollCount,
        foregroundResult,
        afterForeground,
        backgroundResult,
        afterBackground,
        afterDuplicate,
        hiddenResult,
        afterHidden,
        unfocusedResult,
        afterUnfocused,
        afterMuted,
        afterConcurrent,
        afterAdminDisabled,
        afterReenableBaseline,
        afterPostReenable,
        failedRefreshResult,
        afterFailedRefresh,
        afterStatusRetry,
        volumes: playedAudio.map(item => item.volume),
        urls: playedAudio.map(item => item.url),
    }));
}

run().catch(error => {
    console.error(error);
    process.exit(1);
});
"""
    result = subprocess.run(
        ["node", "-e", node_harness, str(RUNTIME_JS)],
        check=True,
        capture_output=True,
        text=True,
    )
    runtime_result = json.loads(result.stdout.strip().splitlines()[-1])

    assert runtime_result["freshFirstPollCount"] == 1
    assert runtime_result["afterBaseline"] == 0
    assert runtime_result["foregroundResult"] is False
    assert runtime_result["afterForeground"] == 0
    assert runtime_result["backgroundResult"] is True
    assert runtime_result["afterBackground"] == 1
    assert runtime_result["afterDuplicate"] == 1
    assert runtime_result["hiddenResult"] is True
    assert runtime_result["afterHidden"] == 2
    assert runtime_result["unfocusedResult"] is True
    assert runtime_result["afterUnfocused"] == 3
    assert runtime_result["afterMuted"] == 3
    assert runtime_result["afterConcurrent"] == 5
    assert runtime_result["afterAdminDisabled"] == 5
    assert runtime_result["afterReenableBaseline"] == 5
    assert runtime_result["afterPostReenable"] == 6
    assert runtime_result["failedRefreshResult"] is False
    assert runtime_result["afterFailedRefresh"] == 6
    assert runtime_result["afterStatusRetry"] == 7
    assert runtime_result["volumes"] == [0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7]
    assert all(url.startswith("/static/audio/completion-cues/") for url in runtime_result["urls"])


def main():
    """Run all completion audio functional checks."""
    tests = [
        test_local_audio_assets,
        test_settings_and_ui_contracts,
        test_completion_event_wiring,
        test_browser_runtime_behavior,
    ]
    for test in tests:
        test()
        print(f"Passed: {test.__name__}")
    return True


if __name__ == "__main__":
    try:
        success = main()
    except Exception as error:
        print(f"Failed: {error}")
        raise
    sys.exit(0 if success else 1)
