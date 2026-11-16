// speechPlayback.ts
// One reader for spoken replies, shared by every "Read aloud" button and by auto-play.
//
// Only one message is read at a time: starting another stops the first, the way classic's
// chat-tts.js behaves. Keeping the player here rather than inside each button is what lets
// auto-play start a message and have that message's button show it playing and stop it.
//
// The voice and speed come from the user's preferences (ttsVoice, ttsSpeed), shared with the
// classic profile page. Auto-play (ttsAutoplay) reads a reply aloud when it finishes in the
// conversation the reader has open on the chat page.

import { useSyncExternalStore } from 'react';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUserSettingsStore } from '../stores/userSettingsStore';
import type { CompletedReply } from './replyEvents';
import { synthesizeSpeech } from './voice';

export type SpeechState = 'idle' | 'loading' | 'playing';

export const TTS_SPEED_MIN = 0.5;
export const TTS_SPEED_MAX = 2;
export const TTS_SPEED_STEP = 0.1;
export const TTS_SPEED_DEFAULT = 1;

/** The stored speed, clamped to what the route accepts and rounded to the slider's step. */
export function normalizeTtsSpeed(value: unknown): number {
    const parsed = typeof value === 'number' ? value : Number.parseFloat(String(value ?? ''));
    if (!Number.isFinite(parsed)) {
        return TTS_SPEED_DEFAULT;
    }
    const clamped = Math.min(TTS_SPEED_MAX, Math.max(TTS_SPEED_MIN, parsed));
    return Math.round(clamped * 10) / 10;
}

let currentKey: string | null = null;
let currentState: SpeechState = 'idle';
let currentAudio: HTMLAudioElement | null = null;
let currentUrl: string | null = null;
/** Bumped on every start or stop, so a slow synthesis that lost the race is discarded. */
let generation = 0;
const listeners = new Set<() => void>();

function emit(): void {
    for (const listener of [...listeners]) {
        listener();
    }
}

function release(): void {
    currentAudio?.pause();
    currentAudio = null;
    if (currentUrl) {
        URL.revokeObjectURL(currentUrl);
        currentUrl = null;
    }
}

/** Stop whatever is being read. */
export function stopSpeech(): void {
    generation += 1;
    release();
    if (currentKey !== null || currentState !== 'idle') {
        currentKey = null;
        currentState = 'idle';
        emit();
    }
}

export interface SpeakOptions {
    voice?: string;
    speed?: number;
}

/**
 * Read `text` aloud under `key`, stopping anything already being read. Voice and speed
 * default to the user's preferences. Resolves once playback starts; rejects on failure.
 */
export async function speak(key: string, text: string, options: SpeakOptions = {}): Promise<void> {
    stopSpeech();
    const ticket = generation;
    currentKey = key;
    currentState = 'loading';
    emit();

    const { settings } = useUserSettingsStore.getState();
    const voice = options.voice ?? (String(settings.ttsVoice ?? '') || undefined);
    const speed = options.speed ?? normalizeTtsSpeed(settings.ttsSpeed);
    try {
        const url = await synthesizeSpeech(text, voice, speed);
        if (ticket !== generation) {
            URL.revokeObjectURL(url);
            return;
        }
        currentUrl = url;
        const audio = new Audio(url);
        currentAudio = audio;
        const finish = () => {
            if (ticket === generation) {
                stopSpeech();
            }
        };
        audio.onended = finish;
        audio.onerror = finish;
        await audio.play();
        if (ticket === generation) {
            currentState = 'playing';
            emit();
        }
    } catch (error) {
        if (ticket === generation) {
            stopSpeech();
        }
        throw error;
    }
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

/** The playback state of one message (or the settings preview), for its control. */
export function useSpeechState(key: string): SpeechState {
    return useSyncExternalStore(
        subscribe,
        () => (currentKey === key ? currentState : 'idle'),
        () => 'idle',
    );
}

export interface SpeechAutoplayContext {
    /** Whether the chat page is showing in a visible tab. */
    chatPageShowing: () => boolean;
    /** The conversation open on the chat page, if any. */
    activeConversationId: () => string | null;
    /** The plain text of a finished message, or null when it is not loaded. */
    messageText: (conversationId: string, messageId: string) => string | null;
}

/** Whether a finished reply should be read aloud straight away. */
export function shouldAutoplayReply(
    reply: CompletedReply,
    adminEnabled: boolean,
    autoplayOn: boolean,
    inOpenConversation: boolean,
): boolean {
    return adminEnabled && autoplayOn && !reply.blocked && Boolean(reply.messageId) && inOpenConversation;
}

/** Build the completed-reply listener that reads replies aloud when auto-play is on. */
export function createSpeechAutoplayListener(context: SpeechAutoplayContext): (reply: CompletedReply) => void {
    return (reply) => {
        const adminEnabled = useBootstrapStore.getState().data?.features?.enable_text_to_speech === true;
        const { settings, loading, error } = useUserSettingsStore.getState();
        if (loading || error) {
            return;
        }
        const inOpenConversation = context.chatPageShowing()
            && context.activeConversationId() === reply.conversationId;
        if (!shouldAutoplayReply(reply, adminEnabled, settings.ttsAutoplay === true, inOpenConversation)) {
            return;
        }
        const messageId = reply.messageId as string;
        // The finished message reaches the store a moment after it is announced, so look
        // for it briefly, as classic waits for the message's button to render.
        let attempts = 0;
        const tryRead = () => {
            const text = context.messageText(reply.conversationId, messageId);
            if (text && text.trim()) {
                void speak(messageId, text).catch(() => undefined);
                return;
            }
            attempts += 1;
            if (attempts < 10) {
                setTimeout(tryRead, 150);
            }
        };
        tryRead();
    };
}
