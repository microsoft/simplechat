// test_v2_voice_dictation_logic.mjs
// Version: 0.261.386
// Implemented in: 0.261.386
// Executes the real V2 voice dictation module (voice.ts) in Node: WAV encoding, PCM chunk
// concatenation and resampling, RMS and 5-bar level metering, pause-aware progressive segment
// flushing, dictated text appending/rollback, and cancellable /api/speech/transcribe-chat requests.

import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import './test_support/tsResolve.mjs';

// Provide a minimal zustand store stub when node_modules is not installed in a fresh worktree
// so voice.ts -> apiClient.ts -> appSessionStore.ts can load without external packages.
registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier === 'zustand') {
            return { url: 'data:text/javascript,export const create = (fn) => { let state = {}; const set = (u) => { state = typeof u === "function" ? { ...state, ...u(state) } : { ...state, ...u }; }; const get = () => state; state = fn(set, get); const store = (sel) => sel ? sel(state) : state; store.getState = get; store.setState = set; return store; };', shortCircuit: true };
        }
        return nextResolve(specifier, context);
    },
});

const {
    MAX_SEGMENT_SECONDS,
    PAUSE_FLUSH_MIN_SECONDS,
    PAUSE_SILENCE_SECONDS,
    SPEECH_RMS_THRESHOLD,
    TARGET_SAMPLE_RATE,
    appendDictatedText,
    computeAudioLevelBars,
    computeRms,
    encodeWav,
    pcmChunksToWav,
    resample,
    revertDictatedSegments,
    shouldFlushSpeechSegment,
    transcribeAudio,
} = await import('../application/v2_ui/src/lib/voice.ts');

async function testWavEncodingAndPcmConcatenation() {
    const chunkA = new Float32Array(16000).fill(0.25);
    const chunkB = new Float32Array(16000).fill(-0.25);
    const wav = pcmChunksToWav([chunkA, chunkB], 32000);
    assert.equal(wav.type, 'audio/wav');

    const buffer = await wav.arrayBuffer();
    const view = new DataView(buffer);
    // 32,000 input samples at 32 kHz (1s) resampled to 16 kHz = 16,000 samples = 32,000 bytes + 44 header bytes.
    assert.equal(buffer.byteLength, 44 + 16000 * 2);
    assert.equal(view.getUint32(24, true), TARGET_SAMPLE_RATE);
    assert.equal(view.getUint16(22, true), 1); // mono
    assert.equal(view.getUint16(34, true), 16); // 16-bit PCM

    const direct = encodeWav(resample(new Float32Array([0, 0.5, -0.5, 1]), 16000, 16000), 16000);
    assert.equal(direct.size, 44 + 4 * 2);
}

function testRmsAndAudioLevelBars() {
    const silence = new Float32Array(512).fill(0);
    assert.equal(computeRms(silence), 0);
    const silentBars = computeAudioLevelBars(0, 5);
    assert.equal(silentBars.length, 5);
    assert.ok(silentBars.every((height) => height === 0.25));

    const speech = new Float32Array(512).fill(0.08);
    const rms = computeRms(speech);
    assert.ok(rms > SPEECH_RMS_THRESHOLD);
    const activeBars = computeAudioLevelBars(rms, 5);
    assert.equal(activeBars.length, 5);
    assert.ok(activeBars.some((height) => height > 0.6));
    assert.ok(activeBars.every((height) => height >= 0.25 && height <= 1));
}

function testProgressiveSegmentFlushRules() {
    // Silence alone never flushes, even past MAX_SEGMENT_SECONDS.
    assert.equal(
        shouldFlushSpeechSegment({
            durationSec: MAX_SEGMENT_SECONDS + 5,
            silenceSec: MAX_SEGMENT_SECONDS + 5,
            hasSpeech: false,
        }),
        false,
    );

    // Speech shorter than PAUSE_FLUSH_MIN_SECONDS does not flush on a brief pause.
    assert.equal(
        shouldFlushSpeechSegment({
            durationSec: PAUSE_FLUSH_MIN_SECONDS - 0.5,
            silenceSec: PAUSE_SILENCE_SECONDS + 0.2,
            hasSpeech: true,
        }),
        false,
    );

    // Once at least PAUSE_FLUSH_MIN_SECONDS of speech is recorded, a natural pause flushes.
    assert.equal(
        shouldFlushSpeechSegment({
            durationSec: PAUSE_FLUSH_MIN_SECONDS + 0.5,
            silenceSec: PAUSE_SILENCE_SECONDS,
            hasSpeech: true,
        }),
        true,
    );

    // Continuous speech without a pause flushes at MAX_SEGMENT_SECONDS.
    assert.equal(
        shouldFlushSpeechSegment({
            durationSec: MAX_SEGMENT_SECONDS,
            silenceSec: 0,
            hasSpeech: true,
        }),
        true,
    );
}

function testAppendAndRevertDictatedText() {
    let text = 'Initial note:';
    const segments = ['first dictated phrase,', 'second dictated phrase.'];
    for (const segment of segments) {
        text = appendDictatedText(text, segment);
    }
    assert.equal(text, 'Initial note: first dictated phrase, second dictated phrase.');

    // Cancelling the session reverts all segments inserted during that session.
    const reverted = revertDictatedSegments(text, 'Initial note:', segments);
    assert.equal(reverted, 'Initial note:');

    // Starting from an empty composer also reverts cleanly to empty string.
    let fromEmpty = '';
    fromEmpty = appendDictatedText(fromEmpty, 'Run this workflow every weekday');
    fromEmpty = appendDictatedText(fromEmpty, 'at 8 AM.');
    assert.equal(
        revertDictatedSegments(fromEmpty, '', ['Run this workflow every weekday', 'at 8 AM.']),
        '',
    );
}

async function testTranscribeAudioEndpointAndCancellation() {
    const originalFetch = globalThis.fetch;
    try {
        let capturedUrl = '';
        let capturedSignal = null;
        let capturedFile = null;

        globalThis.fetch = async (url, init = {}) => {
            capturedUrl = String(url);
            capturedSignal = init.signal ?? null;
            capturedFile = init.body?.get?.('audio') ?? null;
            return new Response(
                JSON.stringify({ success: true, text: 'Transcribed segment text' }),
                { status: 200, headers: { 'Content-Type': 'application/json' } },
            );
        };

        const controller = new AbortController();
        const wav = encodeWav(new Float32Array(160), TARGET_SAMPLE_RATE);
        const okResult = await transcribeAudio(wav, controller.signal);
        assert.equal(okResult.success, true);
        assert.equal(okResult.text, 'Transcribed segment text');
        assert.ok(capturedUrl.endsWith('/api/speech/transcribe-chat'));
        assert.equal(capturedSignal, controller.signal);
        assert.ok(capturedFile instanceof Blob);

        // Verify error payload handling.
        globalThis.fetch = async () =>
            new Response(
                JSON.stringify({ success: false, error: 'No speech could be recognized' }),
                { status: 400, headers: { 'Content-Type': 'application/json' } },
            );
        const failResult = await transcribeAudio(wav);
        assert.equal(failResult.success, false);
        assert.equal(failResult.error, 'No speech could be recognized');
    } finally {
        globalThis.fetch = originalFetch;
    }
}

await testWavEncodingAndPcmConcatenation();
testRmsAndAudioLevelBars();
testProgressiveSegmentFlushRules();
testAppendAndRevertDictatedText();
await testTranscribeAudioEndpointAndCancellation();
console.log('All V2 voice dictation logic checks passed.');
