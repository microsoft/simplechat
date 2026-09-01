// voice.ts
// Voice input and output helpers.
//
// Input records with MediaRecorder and converts to 16 kHz mono WAV before upload, which
// is what /api/speech/transcribe-chat expects. Output plays the audio stream returned by
// /api/chat/tts.

import { apiUrl, API_BASE } from './apiClient';

const CREDENTIALS_MODE: RequestCredentials = API_BASE ? 'include' : 'same-origin';

/** Azure Speech works best at 16 kHz mono, matching the existing client. */
const TARGET_SAMPLE_RATE = 16000;

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
function encodeWav(samples: Float32Array, sampleRate: number): Blob {
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
function resample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
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

export async function transcribeAudio(wav: Blob): Promise<TranscriptionResult> {
    const formData = new FormData();
    // Field name and filename match what the route reads.
    formData.append('audio', wav, 'recording.wav');

    const response = await fetch(apiUrl('/api/speech/transcribe-chat'), {
        method: 'POST',
        credentials: CREDENTIALS_MODE,
        body: formData,
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
export async function synthesizeSpeech(text: string, voice?: string): Promise<string> {
    const response = await fetch(apiUrl('/api/chat/tts'), {
        method: 'POST',
        credentials: CREDENTIALS_MODE,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(voice ? { text, voice } : { text }),
    });

    if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(payload.error || `Speech synthesis failed (${response.status})`);
    }

    return URL.createObjectURL(await response.blob());
}
