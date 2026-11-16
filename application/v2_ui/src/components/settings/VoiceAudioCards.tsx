// VoiceAudioCards.tsx
// The voice and audio cards on the Preferences tab: completion sounds, spoken replies and the
// microphone.
//
// Each card mirrors a section of the classic profile page and saves to the same preference
// keys, so the two interfaces stay in step. Unlike classic there is no Save button: a change
// is written as it is made, like every other preference here.

import { useEffect, useState } from 'react';
import { Loader2, Mic, Play, Square, Volume2, BellRing } from 'lucide-react';
import { api } from '../../lib/apiClient';
import {
    COMPLETION_AUDIO_SOUNDS,
    COMPLETION_AUDIO_VOLUME_MAX,
    COMPLETION_AUDIO_VOLUME_MIN,
    previewCompletionSound,
    readCompletionAudioPreferences,
} from '../../lib/completionAudio';
import {
    TTS_SPEED_MAX,
    TTS_SPEED_MIN,
    TTS_SPEED_STEP,
    normalizeTtsSpeed,
    speak,
    stopSpeech,
    useSpeechState,
} from '../../lib/speechPlayback';
import type { UserSettings } from '../../lib/userSettings';
import { toast } from '../../stores/toastStore';
import { Toggle } from '../ui/primitives';
import { SettingsCard } from './SettingsCard';

const SELECT_CLASS =
    'mt-1.5 w-full max-w-xs rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1';
const BUTTON_CLASS =
    'inline-flex items-center gap-1.5 rounded-lg border border-edge px-2.5 py-1.5 text-sm font-medium text-text-1 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50';

type Update = (partial: UserSettings) => void;

export function CompletionAudioCard({ settings, update }: { settings: UserSettings; update: Update }) {
    const preferences = readCompletionAudioPreferences(settings);
    const [previewFailed, setPreviewFailed] = useState(false);

    const preview = async () => {
        setPreviewFailed(!(await previewCompletionSound(preferences.soundId, preferences.volume)));
    };

    return (
        <SettingsCard
            title="Reply completion sounds"
            Icon={BellRing}
            status={preferences.enabled && !preferences.muted ? 'ready' : 'off'}
            description="A short sound when a reply finishes while you are looking elsewhere: another tab, another window, another page, or another conversation. Shared with the classic interface."
        >
            <div className="admin-switch-grid">
                <div className="py-2 first:pt-0">
                    <Toggle
                        checked={preferences.enabled}
                        onChange={(next) => update({ chatCompletionAudioEnabled: next })}
                        label="Play completion sounds"
                    />
                </div>
                <div className="py-2">
                    <Toggle
                        checked={preferences.muted}
                        disabled={!preferences.enabled}
                        onChange={(next) => update({ chatCompletionAudioMuted: next })}
                        label="Mute for now"
                        description="Silence the sounds without losing your choice of sound and volume."
                    />
                </div>
            </div>

            <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <label className="block">
                    <span className="block text-sm font-medium text-text-1">Sound</span>
                    <div className="flex flex-wrap items-center gap-2">
                        <select
                            value={preferences.soundId}
                            onChange={(event) => update({ chatCompletionAudioSound: event.target.value })}
                            className={SELECT_CLASS}
                        >
                            {COMPLETION_AUDIO_SOUNDS.map((sound) => (
                                <option key={sound.id} value={sound.id}>
                                    {sound.label}
                                </option>
                            ))}
                        </select>
                        <button type="button" onClick={() => void preview()} className={`${BUTTON_CLASS} mt-1.5`}>
                            <Play size={14} aria-hidden="true" />
                            Preview
                        </button>
                    </div>
                </label>

                <label className="block">
                    <span className="block text-sm font-medium text-text-1">
                        Volume <span className="font-normal text-text-3">{preferences.volume} of {COMPLETION_AUDIO_VOLUME_MAX}</span>
                    </span>
                    <input
                        type="range"
                        min={COMPLETION_AUDIO_VOLUME_MIN}
                        max={COMPLETION_AUDIO_VOLUME_MAX}
                        step={1}
                        value={preferences.volume}
                        onChange={(event) => update({ chatCompletionAudioVolume: Number(event.target.value) })}
                        className="mt-3 w-full max-w-xs accent-[var(--accent)]"
                    />
                </label>
            </div>
            {previewFailed && (
                <p className="mt-2 text-xs text-warn">
                    This browser would not play the sound. Check that the tab is not muted.
                </p>
            )}
        </SettingsCard>
    );
}

interface TtsVoice {
    name: string;
    display_name?: string;
    gender?: string;
    language?: string;
    locale?: string;
}

interface TtsVoicesResponse {
    voices?: TtsVoice[];
    default_voice?: string | null;
    source?: string;
    warning?: string | null;
}

const PREVIEW_KEY = 'settings-voice-preview';
const PREVIEW_TEXT = 'Hello! This is how your assistant replies will sound when they are read aloud.';

function voiceLabel(voice: TtsVoice): string {
    const name = voice.display_name || voice.name;
    const gender = voice.gender && voice.gender !== 'Unknown' ? `, ${voice.gender}` : '';
    return `${name} (${voice.locale || voice.language || 'voice'}${gender})`;
}

/** Group voices by language for the picker, keeping the server's order inside each group. */
function groupVoices(voices: TtsVoice[]): [string, TtsVoice[]][] {
    const groups = new Map<string, TtsVoice[]>();
    for (const voice of voices) {
        const language = voice.language || 'Other';
        groups.set(language, [...(groups.get(language) ?? []), voice]);
    }
    return [...groups.entries()];
}

export function SpokenRepliesCard({ settings, update }: { settings: UserSettings; update: Update }) {
    const [voices, setVoices] = useState<TtsVoice[]>([]);
    const [defaultVoice, setDefaultVoice] = useState<string | null>(null);
    const [voicesLoading, setVoicesLoading] = useState(true);
    const [voicesWarning, setVoicesWarning] = useState<string | null>(null);
    const previewState = useSpeechState(PREVIEW_KEY);

    const voice = String(settings.ttsVoice ?? '');
    const speed = normalizeTtsSpeed(settings.ttsSpeed);
    const autoplay = settings.ttsAutoplay === true;

    useEffect(() => {
        const controller = new AbortController();
        api.get<TtsVoicesResponse>('/api/chat/tts/voices', controller.signal)
            .then((response) => {
                setVoices(Array.isArray(response?.voices) ? response.voices : []);
                setDefaultVoice(response?.default_voice ?? null);
                setVoicesWarning(response?.source === 'fallback' ? 'Showing a basic list of voices; the full list could not be loaded.' : null);
            })
            .catch(() => {
                if (!controller.signal.aborted) {
                    setVoicesWarning('The list of voices could not be loaded.');
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) {
                    setVoicesLoading(false);
                }
            });
        return () => controller.abort();
    }, []);

    // Stop a preview that is still playing when the card goes away.
    useEffect(() => () => {
        stopSpeech();
    }, []);

    // A stored voice the list no longer offers stays selectable, so opening the page never
    // silently changes it.
    const storedMissing = voice !== '' && !voices.some((item) => item.name === voice);

    const playPreview = () => {
        if (previewState !== 'idle') {
            stopSpeech();
            return;
        }
        void speak(PREVIEW_KEY, PREVIEW_TEXT, { voice: voice || undefined, speed }).catch((error: unknown) => {
            toast.error(error instanceof Error ? error.message : 'The sample could not be played.');
        });
    };

    return (
        <SettingsCard
            title="Spoken replies"
            Icon={Volume2}
            description="How assistant messages sound when they are read aloud. Use the speaker button on any reply, or let replies read themselves. Shared with the classic interface."
        >
            <div className="grid gap-4 sm:grid-cols-2">
                <label className="block">
                    <span className="block text-sm font-medium text-text-1">Voice</span>
                    <select
                        value={voice}
                        disabled={voicesLoading}
                        onChange={(event) => update({ ttsVoice: event.target.value })}
                        className={SELECT_CLASS}
                    >
                        <option value="">
                            {defaultVoice ? `Default (${defaultVoice})` : 'Default voice'}
                        </option>
                        {storedMissing && <option value={voice}>{voice}</option>}
                        {groupVoices(voices).map(([language, items]) => (
                            <optgroup key={language} label={language}>
                                {items.map((item) => (
                                    <option key={item.name} value={item.name}>
                                        {voiceLabel(item)}
                                    </option>
                                ))}
                            </optgroup>
                        ))}
                    </select>
                    {voicesWarning && <span className="mt-1 block text-xs text-text-3">{voicesWarning}</span>}
                </label>

                <label className="block">
                    <span className="block text-sm font-medium text-text-1">
                        Speed <span className="font-normal text-text-3">{speed.toFixed(1)}x</span>
                    </span>
                    <input
                        type="range"
                        min={TTS_SPEED_MIN}
                        max={TTS_SPEED_MAX}
                        step={TTS_SPEED_STEP}
                        value={speed}
                        onChange={(event) => update({ ttsSpeed: normalizeTtsSpeed(event.target.value) })}
                        className="mt-3 w-full max-w-xs accent-[var(--accent)]"
                    />
                    <span className="flex max-w-xs justify-between text-xs text-text-3">
                        <span>Slower</span>
                        <span>Faster</span>
                    </span>
                </label>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                    type="button"
                    onClick={playPreview}
                    disabled={previewState === 'loading'}
                    className={BUTTON_CLASS}
                >
                    {previewState === 'loading' ? (
                        <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                    ) : previewState === 'playing' ? (
                        <Square size={14} aria-hidden="true" />
                    ) : (
                        <Play size={14} aria-hidden="true" />
                    )}
                    {previewState === 'playing' ? 'Stop sample' : 'Play a sample'}
                </button>
                <span className="text-xs text-text-3">Uses the voice and speed chosen above.</span>
            </div>

            <div className="mt-4 border-t border-edge pt-3">
                <Toggle
                    checked={autoplay}
                    onChange={(next) => update(next ? { ttsAutoplay: true, ttsEnabled: true } : { ttsAutoplay: false })}
                    label="Read replies aloud automatically"
                    description="Each new reply in the conversation you have open is read aloud as soon as it finishes."
                />
            </div>
        </SettingsCard>
    );
}

type MicrophoneStatus = 'checking' | 'granted' | 'denied' | 'prompt' | 'unsupported';

const MICROPHONE_LABELS: Record<MicrophoneStatus, string> = {
    checking: 'Checking…',
    granted: 'Allowed',
    denied: 'Blocked',
    prompt: 'Not decided yet',
    unsupported: 'Not available in this browser',
};

const MICROPHONE_TONES: Record<MicrophoneStatus, string> = {
    checking: 'bg-surface-2 text-text-2',
    granted: 'bg-ok-soft text-ok',
    denied: 'bg-danger-soft text-danger',
    prompt: 'bg-surface-2 text-text-2',
    unsupported: 'bg-surface-2 text-text-3',
};

function microphoneSupported(): boolean {
    return typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia);
}

/**
 * Read the permission without prompting. The Permissions API answers silently where it is
 * supported; where it is not, the state is reported as undecided rather than opening the
 * browser's prompt just by visiting the page.
 */
async function readMicrophonePermission(): Promise<MicrophoneStatus> {
    if (!microphoneSupported()) {
        return 'unsupported';
    }
    try {
        const status = await navigator.permissions.query({ name: 'microphone' as PermissionName });
        return status.state === 'granted' || status.state === 'denied' ? status.state : 'prompt';
    } catch {
        return 'prompt';
    }
}

export function MicrophoneCard() {
    const [status, setStatus] = useState<MicrophoneStatus>('checking');
    const [message, setMessage] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        let permission: PermissionStatus | null = null;
        const refresh = () => {
            void readMicrophonePermission().then((next) => {
                if (!cancelled) {
                    setStatus(next);
                }
            });
        };
        refresh();
        // Follow a change made in the browser's own site settings while the page is open.
        navigator.permissions?.query({ name: 'microphone' as PermissionName })
            .then((result) => {
                permission = result;
                result.addEventListener('change', refresh);
            })
            .catch(() => undefined);
        return () => {
            cancelled = true;
            permission?.removeEventListener('change', refresh);
        };
    }, []);

    const request = async () => {
        setMessage(null);
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            stream.getTracks().forEach((track) => track.stop());
            setStatus('granted');
        } catch (error) {
            const name = error instanceof DOMException ? error.name : '';
            if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
                setStatus('denied');
                setMessage('The browser is blocking the microphone for this site. Allow it in the browser\'s site settings (the icon at the left of the address bar), then come back to this page.');
            } else if (name === 'NotFoundError') {
                setMessage('No microphone was found. Connect one and try again.');
            } else {
                setMessage('The microphone could not be reached.');
            }
        }
    };

    return (
        <SettingsCard
            title="Microphone"
            Icon={Mic}
            description="Dictating a message needs this browser's permission to use your microphone. The browser keeps that permission, not this application."
        >
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-text-2">Permission</span>
                <span
                    data-microphone-status={status}
                    className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${MICROPHONE_TONES[status]}`}
                >
                    {MICROPHONE_LABELS[status]}
                </span>
                {(status === 'prompt' || status === 'denied') && (
                    <button type="button" onClick={() => void request()} className={BUTTON_CLASS}>
                        <Mic size={14} aria-hidden="true" />
                        Allow microphone
                    </button>
                )}
            </div>
            {status === 'granted' && (
                <p className="mt-2 text-xs text-text-3">
                    To take the permission back, use the browser&apos;s site settings (the icon at the left of the
                    address bar) and block the microphone for this site.
                </p>
            )}
            {message && <p className="mt-2 text-xs text-warn">{message}</p>}
        </SettingsCard>
    );
}
