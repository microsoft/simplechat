// voice.ts
// Voice input and output helpers.
//
// Input captures 16 kHz mono WAV segments (progressively while speaking, plus a MediaRecorder
// fallback) and uploads them to /api/speech/transcribe-chat. Output plays the audio stream
// returned by /api/chat/tts.

import { apiUrl, API_BASE } from './apiClient';

const CREDENTIALS_MODE: RequestCredentials = API_BASE ? 'include' : 'same-origin';

/** Azure Speech works best at 16 kHz mono, matching the existing client. */
export const TARGET_SAMPLE_RATE = 16000;

/** RMS threshold above which a PCM frame is treated as active speech rather than silence. */
export const SPEECH_RMS_THRESHOLD = 0.012;

/** Minimum segment duration (seconds) before a natural pause flushes a background clip. */
export const PAUSE_FLUSH_MIN_SECONDS = 6;

/** Natural pause duration (seconds) that triggers a background segment flush. */
export const PAUSE_SILENCE_SECONDS = 0.55;

/** Maximum continuous segment duration (seconds) before flushing while speaking. */
export const MAX_SEGMENT_SECONDS = 12;

const BAR_WEIGHTS = [0.65, 0.9, 1.0, 0.8, 0.92];

function writeString(view: DataView, offset: number, value: string) {
    for (let index = 0; index < value.length; index += 1) {
        view.setUint8(offset + index, value.charCodeAt(index));
    }
}

/**
 * Encode mono float samples as a 16-bit PCM WAV.
 *
 * MediaRecorder rarely produces WAV directly (Chrome gives WebM/Opus), so the recording is
 * decoded and re-encoded rather than uploaded in whatever container the browser chose.
 */
export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true); // PCM chunk size
    view.setUint16(20, 1, true); // PCM format
    view.setUint16(22, 1, true); // mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true); // byte rate
    view.setUint16(32, 2, true); // block align
    view.setUint16(34, 16, true); // bits per sample
    writeString(view, 36, 'data');
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let index = 0; index < samples.length; index += 1) {
        const clamped = Math.max(-1, Math.min(1, samples[index]));
        view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
        offset += 2;
    }

    return new Blob([view], { type: 'audio/wav' });
}

/** Downsample by simple decimation with averaging, which is adequate for speech. */
export function resample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
    if (fromRate === toRate) {
        return input;
    }
    const ratio = fromRate / toRate;
    const output = new Float32Array(Math.floor(input.length / ratio));
    for (let index = 0; index < output.length; index += 1) {
        const start = Math.floor(index * ratio);
        const end = Math.min(Math.floor((index + 1) * ratio), input.length);
        let total = 0;
        for (let position = start; position < end; position += 1) {
            total += input[position];
        }
        output[index] = end > start ? total / (end - start) : 0;
    }
    return output;
}

/** Concatenate PCM frames and encode as a 16 kHz mono WAV blob. */
export function pcmChunksToWav(chunks: readonly Float32Array[], sampleRate: number): Blob {
    let totalLength = 0;
    for (const chunk of chunks) {
        totalLength += chunk.length;
    }
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of chunks) {
        merged.set(chunk, offset);
        offset += chunk.length;
    }
    return encodeWav(resample(merged, sampleRate, TARGET_SAMPLE_RATE), TARGET_SAMPLE_RATE);
}

/** Compute root-mean-square amplitude (0..1) of a mono PCM frame. */
export function computeRms(samples: ArrayLike<number>): number {
    if (samples.length === 0) {
        return 0;
    }
    let sumSquares = 0;
    for (let index = 0; index < samples.length; index += 1) {
        const value = samples[index];
        sumSquares += value * value;
    }
    return Math.sqrt(sumSquares / samples.length);
}

/** Convert an RMS level into normalized bar heights (0.25..1.0) for the live audio meter. */
export function computeAudioLevelBars(rms: number, count = 5): number[] {
    const normalized = Math.min(1, Math.max(0, (rms - 0.004) / 0.12));
    const bars: number[] = [];
    for (let index = 0; index < count; index += 1) {
        const weight = BAR_WEIGHTS[index % BAR_WEIGHTS.length];
        const height = 0.25 + normalized * 0.75 * weight;
        bars.push(Number(Math.min(1, Math.max(0.25, height)).toFixed(3)));
    }
    return bars;
}

export interface SpeechSegmentState {
    durationSec: number;
    silenceSec: number;
    hasSpeech: boolean;
}

/**
 * Decide whether the current in-progress recording segment should be flushed to the
 * transcription endpoint while recording continues.
 */
export function shouldFlushSpeechSegment(state: SpeechSegmentState): boolean {
    if (!state.hasSpeech) {
        return false;
    }
    if (state.durationSec >= MAX_SEGMENT_SECONDS) {
        return true;
    }
    if (state.durationSec >= PAUSE_FLUSH_MIN_SECONDS && state.silenceSec >= PAUSE_SILENCE_SECONDS) {
        return true;
    }
    return false;
}

/** Append a newly transcribed segment onto existing text with clean spacing. */
export function appendDictatedText(current: string, transcript: string): string {
    const trimmed = transcript.trim();
    if (!trimmed) {
        return current;
    }
    if (!current) {
        return trimmed;
    }
    const needsSpace = !/\s$/.test(current);
    return `${current}${needsSpace ? ' ' : ''}${trimmed}`;
}

/** Roll back text dictated during a cancelled recording session. */
export function revertDictatedSegments(
    current: string,
    baseline: string,
    insertedSegments: readonly string[],
): string {
    if (insertedSegments.length === 0) {
        return current;
    }
    let expected = baseline;
    for (const segment of insertedSegments) {
        expected = appendDictatedText(expected, segment);
    }
    if (current === expected) {
        return baseline;
    }
    const dictatedSuffix = insertedSegments.map((item) => item.trim()).filter(Boolean).join(' ');
    if (dictatedSuffix && current.endsWith(dictatedSuffix)) {
        return current.slice(0, current.length - dictatedSuffix.length).trimEnd();
    }
    return baseline;
}

export async function blobToWav(blob: Blob): Promise<Blob> {
    const audioContext = new AudioContext();
    try {
        const decoded = await audioContext.decodeAudioData(await blob.arrayBuffer());
        const mono = decoded.getChannelData(0);
        return encodeWav(resample(mono, decoded.sampleRate, TARGET_SAMPLE_RATE), TARGET_SAMPLE_RATE);
    } finally {
        void audioContext.close();
    }
}

export interface TranscriptionResult {
    success: boolean;
    text?: string;
    error?: string;
}

export async function transcribeAudio(wav: Blob, signal?: AbortSignal): Promise<TranscriptionResult> {
    const formData = new FormData();
    // Field name and filename match what the route reads.
    formData.append('audio', wav, 'recording.wav');

    const response = await fetch(apiUrl('/api/speech/transcribe-chat'), {
        method: 'POST',
        credentials: CREDENTIALS_MODE,
        body: formData,
        signal,
    });

    if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as TranscriptionResult;
        return { success: false, error: payload.error || `Transcription failed (${response.status})` };
    }

    return (await response.json()) as TranscriptionResult;
}

/**
 * Synthesize speech for a message.
 *
 * The endpoint returns an audio stream rather than JSON, so the response is turned into
 * an object URL for playback.
 */
export async function synthesizeSpeech(text: string, voice?: string, speed?: number): Promise<string> {
    const body: Record<string, unknown> = { text };
    if (voice) {
        body.voice = voice;
    }
    // The route clamps to 0.5-2.0; normal speed is left out so the request stays as it was.
    if (typeof speed === 'number' && Number.isFinite(speed) && Math.abs(speed - 1) > 0.001) {
        body.speed = speed;
    }
    const response = await fetch(apiUrl('/api/chat/tts'), {
        method: 'POST',
        credentials: CREDENTIALS_MODE,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });

    if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(payload.error || `Speech synthesis failed (${response.status})`);
    }

    return URL.createObjectURL(await response.blob());
}
