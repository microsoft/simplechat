// completionAudio.ts
// A short sound when an assistant reply finishes somewhere the reader isn't looking.
//
// Mirrors the classic interface (static/js/completion-audio-cues.js) and shares its
// preferences, so a choice made on either profile page holds on both:
//
// - It plays only when the administrator turned on `enable_chat_completion_audio_cues`, the
//   user turned cues on (they are off until chosen, as in classic) and has not muted them.
// - It plays only when the reply is out of sight: the tab is hidden, the window is not
//   focused, the chat page is not showing, or another conversation is open there.
// - Never for a reply the safety filter replaced, and never twice for one reply.
// - The sounds are the local files classic plays, at the volume chosen on a 1-10 scale.

import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUserSettingsStore } from '../stores/userSettingsStore';
import type { CompletedReply } from './replyEvents';

export const COMPLETION_AUDIO_SOUNDS = [
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
] as const;

export type CompletionAudioSoundId = (typeof COMPLETION_AUDIO_SOUNDS)[number]['id'];

export const DEFAULT_COMPLETION_AUDIO_SOUND: CompletionAudioSoundId = 'aurora';
export const DEFAULT_COMPLETION_AUDIO_VOLUME = 5;
export const COMPLETION_AUDIO_VOLUME_MIN = 1;
export const COMPLETION_AUDIO_VOLUME_MAX = 10;

const SOUND_IDS = new Set<string>(COMPLETION_AUDIO_SOUNDS.map((sound) => sound.id));
const HANDLED_LIMIT = 200;

export interface CompletionAudioPreferences {
    enabled: boolean;
    muted: boolean;
    soundId: CompletionAudioSoundId;
    volume: number;
}

export function normalizeCompletionSound(value: unknown): CompletionAudioSoundId {
    const id = typeof value === 'string' ? value.trim().toLowerCase() : '';
    return SOUND_IDS.has(id) ? (id as CompletionAudioSoundId) : DEFAULT_COMPLETION_AUDIO_SOUND;
}

export function normalizeCompletionVolume(value: unknown): number {
    const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
    if (!Number.isFinite(parsed)) {
        return DEFAULT_COMPLETION_AUDIO_VOLUME;
    }
    return Math.min(COMPLETION_AUDIO_VOLUME_MAX, Math.max(COMPLETION_AUDIO_VOLUME_MIN, Math.round(parsed)));
}

/** The stored preferences, read the way classic reads them. */
export function readCompletionAudioPreferences(settings: Record<string, unknown>): CompletionAudioPreferences {
    return {
        enabled: settings.chatCompletionAudioEnabled === true,
        muted: settings.chatCompletionAudioMuted === true,
        soundId: normalizeCompletionSound(settings.chatCompletionAudioSound),
        volume: normalizeCompletionVolume(settings.chatCompletionAudioVolume),
    };
}

export function completionSoundUrl(soundId: string): string {
    return `/static/audio/completion-cues/${normalizeCompletionSound(soundId)}.wav`;
}

let previewAudio: HTMLAudioElement | null = null;
let cueAudio: HTMLAudioElement | null = null;
const handledReplies = new Set<string>();

async function playSound(soundId: string, volume: number): Promise<HTMLAudioElement | null> {
    const audio = new Audio(completionSoundUrl(soundId));
    audio.volume = normalizeCompletionVolume(volume) / COMPLETION_AUDIO_VOLUME_MAX;
    try {
        await audio.play();
        return audio;
    } catch {
        // The browser refused (no interaction yet) or the file failed: a cue is a courtesy,
        // so it is dropped rather than retried later, out of context.
        return null;
    }
}

/** Play a sound from the settings page, replacing any preview still playing. */
export async function previewCompletionSound(soundId: string, volume: number): Promise<boolean> {
    previewAudio?.pause();
    previewAudio = await playSound(soundId, volume);
    return previewAudio !== null;
}

function adminAllowsCompletionAudio(): boolean {
    return useBootstrapStore.getState().data?.features?.enable_chat_completion_audio_cues === true;
}

function replyKey(reply: CompletedReply): string {
    return `${reply.conversationId}:${reply.messageId ?? reply.runId ?? ''}`;
}

export interface CompletionCueContext {
    /** Whether the chat page is showing, in a visible and focused window. */
    chatPageWatched: () => boolean;
    /** The conversation open on the chat page, if any. */
    activeConversationId: () => string | null;
}

/**
 * Decide whether a finished reply should sound, given the reader's preferences and what
 * they are looking at. Exported so the rule can be tested without playing anything.
 */
export function shouldPlayCompletionCue(
    reply: CompletedReply,
    preferences: CompletionAudioPreferences,
    adminEnabled: boolean,
    watchingConversation: boolean,
): boolean {
    if (!adminEnabled || !preferences.enabled || preferences.muted || reply.blocked) {
        return false;
    }
    return !watchingConversation;
}

/** Build the completed-reply listener that plays the cue. */
export function createCompletionCueListener(context: CompletionCueContext): (reply: CompletedReply) => void {
    return (reply) => {
        const { settings, loading, error } = useUserSettingsStore.getState();
        if (loading || error) {
            return;
        }
        const preferences = readCompletionAudioPreferences(settings);
        const watching = context.chatPageWatched() && context.activeConversationId() === reply.conversationId;
        if (!shouldPlayCompletionCue(reply, preferences, adminAllowsCompletionAudio(), watching)) {
            return;
        }
        const key = replyKey(reply);
        if (handledReplies.has(key)) {
            return;
        }
        handledReplies.add(key);
        if (handledReplies.size > HANDLED_LIMIT) {
            const oldest = handledReplies.values().next().value;
            if (oldest !== undefined) {
                handledReplies.delete(oldest);
            }
        }
        // One cue at a time: replies finishing together sound once, not as a pile-up.
        if (cueAudio && !cueAudio.paused && !cueAudio.ended) {
            return;
        }
        void playSound(preferences.soundId, preferences.volume).then((audio) => {
            cueAudio = audio;
        });
    };
}
