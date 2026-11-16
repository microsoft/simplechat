// VoiceInput.tsx
// Push-to-record voice input with progressive background transcription and live audio metering.
//
// Captures 16 kHz mono WAV segments while the user speaks (flushing on natural pauses or max
// segment length) and inserts words progressively into the composer. Clicking Check finishes
// the final tail segment; clicking Cancel aborts in-flight transcription and rolls back any
// segments inserted during the cancelled recording session.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { AlertTriangle, Check, Loader2, Mic, X } from 'lucide-react';
import {
    SPEECH_RMS_THRESHOLD,
    TARGET_SAMPLE_RATE,
    blobToWav,
    computeAudioLevelBars,
    computeRms,
    pcmChunksToWav,
    shouldFlushSpeechSegment,
    transcribeAudio,
} from '../../lib/voice';

export type RecordingState = 'idle' | 'recording' | 'transcribing';

const DEFAULT_BARS = [0.3, 0.45, 0.6, 0.4, 0.5];

export interface VoiceInputProps {
    onTranscribed: (text: string) => void;
    /** Called when a recording session begins so the caller can snapshot its draft text. */
    onSessionStart?: () => void;
    /** Called when the user cancels a session that already inserted progressive segments. */
    onCancelSession?: (insertedSegments: readonly string[]) => void;
    /** Reports state changes so the composer can display Listening… / Finishing… inline. */
    onStateChange?: (state: RecordingState) => void;
    /** Disables starting voice input when the surrounding composer cannot accept text. */
    disabled?: boolean;
    /** Compact sizing for Ask AI side-panel footers. */
    compact?: boolean;
    /** Accessible label for the idle microphone button. */
    ariaLabel?: string;
}

export function VoiceInput({
    onTranscribed,
    onSessionStart,
    onCancelSession,
    onStateChange,
    disabled = false,
    compact = false,
    ariaLabel = 'Voice input',
}: VoiceInputProps) {
    const [state, setState] = useState<RecordingState>('idle');
    const [error, setError] = useState<string | null>(null);
    const [elapsed, setElapsed] = useState(0);
    const [finishingElapsed, setFinishingElapsed] = useState(0);
    const [bars, setBars] = useState<number[]>(DEFAULT_BARS);

    const recorderRef = useRef<MediaRecorder | null>(null);
    const chunksRef = useRef<Blob[]>([]);
    const streamRef = useRef<MediaStream | null>(null);
    const timerRef = useRef<number | null>(null);
    const finishingTimerRef = useRef<number | null>(null);

    // Web Audio progressive capture state.
    const audioContextRef = useRef<AudioContext | null>(null);
    const processorRef = useRef<ScriptProcessorNode | null>(null);
    const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
    const pcmChunksRef = useRef<Float32Array[]>([]);
    const segmentDurationRef = useRef(0);
    const segmentSilenceRef = useRef(0);
    const segmentHasSpeechRef = useRef(false);
    const hadWebAudioPcmRef = useRef(false);
    const segmentsDispatchedRef = useRef(0);

    // Session lifecycle & resilient retry state.
    const discardRef = useRef(false);
    const abortRef = useRef<AbortController | null>(null);
    const queueRef = useRef<Promise<void>>(Promise.resolve());
    const insertedSegmentsRef = useRef<string[]>([]);
    const retryWavRef = useRef<Blob | null>(null);

    const updateState = (next: RecordingState) => {
        setState(next);
        onStateChange?.(next);
    };

    const stopTimers = () => {
        if (timerRef.current !== null) {
            window.clearInterval(timerRef.current);
            timerRef.current = null;
        }
        if (finishingTimerRef.current !== null) {
            window.clearInterval(finishingTimerRef.current);
            finishingTimerRef.current = null;
        }
    };

    const stopCaptureNodes = () => {
        if (processorRef.current) {
            processorRef.current.onaudioprocess = null;
            try {
                processorRef.current.disconnect();
            } catch {
                // Ignore disconnect errors during teardown.
            }
            processorRef.current = null;
        }
        if (sourceNodeRef.current) {
            try {
                sourceNodeRef.current.disconnect();
            } catch {
                // Ignore disconnect errors during teardown.
            }
            sourceNodeRef.current = null;
        }
        if (audioContextRef.current) {
            void audioContextRef.current.close().catch(() => undefined);
            audioContextRef.current = null;
        }
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        recorderRef.current = null;
    };

    const cleanup = () => {
        stopTimers();
        stopCaptureNodes();
        chunksRef.current = [];
        pcmChunksRef.current = [];
        segmentDurationRef.current = 0;
        segmentSilenceRef.current = 0;
        segmentHasSpeechRef.current = false;
        setElapsed(0);
        setFinishingElapsed(0);
        setBars(DEFAULT_BARS);
    };

    useEffect(() => () => {
        abortRef.current?.abort();
        stopTimers();
        stopCaptureNodes();
    }, []);

    const enqueueSegmentTranscription = (wav: Blob, reportEmptyError: boolean) => {
        const signal = abortRef.current?.signal;
        queueRef.current = queueRef.current.then(async () => {
            if (discardRef.current || signal?.aborted) {
                return;
            }
            try {
                const result = await transcribeAudio(wav, signal);
                if (discardRef.current || signal?.aborted) {
                    return;
                }
                if (result.success && result.text?.trim()) {
                    const text = result.text.trim();
                    insertedSegmentsRef.current.push(text);
                    retryWavRef.current = null;
                    setError(null);
                    onTranscribed(text);
                } else if (reportEmptyError && insertedSegmentsRef.current.length === 0) {
                    retryWavRef.current = wav;
                    setError(result.error || 'Nothing was transcribed.');
                }
            } catch (transcribeError) {
                if (discardRef.current || signal?.aborted) {
                    return;
                }
                retryWavRef.current = wav;
                setError(
                    transcribeError instanceof Error
                        ? transcribeError.message
                        : 'Could not transcribe the recording.',
                );
            }
        });
        return queueRef.current;
    };

    const startFinishingTimer = () => {
        setFinishingElapsed(0);
        if (finishingTimerRef.current !== null) {
            window.clearInterval(finishingTimerRef.current);
        }
        finishingTimerRef.current = window.setInterval(
            () => setFinishingElapsed((seconds) => seconds + 1),
            1000,
        );
    };

    const start = async () => {
        if (disabled) {
            return;
        }
        setError(null);
        retryWavRef.current = null;
        discardRef.current = false;
        insertedSegmentsRef.current = [];
        segmentsDispatchedRef.current = 0;
        hadWebAudioPcmRef.current = false;
        pcmChunksRef.current = [];
        segmentDurationRef.current = 0;
        segmentSilenceRef.current = 0;
        segmentHasSpeechRef.current = false;
        abortRef.current = new AbortController();
        queueRef.current = Promise.resolve();

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
            });
            streamRef.current = stream;
            onSessionStart?.();

            // Set up Web Audio live metering + progressive pause-aware PCM segmentation when supported.
            if (typeof AudioContext !== 'undefined') {
                try {
                    const audioContext = new AudioContext();
                    audioContextRef.current = audioContext;
                    if (typeof audioContext.createMediaStreamSource === 'function'
                        && typeof audioContext.createScriptProcessor === 'function') {
                        const source = audioContext.createMediaStreamSource(stream);
                        const processor = audioContext.createScriptProcessor(4096, 1, 1);
                        sourceNodeRef.current = source;
                        processorRef.current = processor;

                        processor.onaudioprocess = (event) => {
                            if (discardRef.current) {
                                return;
                            }
                            const input = event.inputBuffer.getChannelData(0);
                            const frameCopy = new Float32Array(input.length);
                            frameCopy.set(input);
                            pcmChunksRef.current.push(frameCopy);
                            hadWebAudioPcmRef.current = true;

                            const rms = computeRms(frameCopy);
                            setBars(computeAudioLevelBars(rms));

                            const frameDuration = event.inputBuffer.duration || frameCopy.length / audioContext.sampleRate;
                            segmentDurationRef.current += frameDuration;
                            if (rms >= SPEECH_RMS_THRESHOLD) {
                                segmentHasSpeechRef.current = true;
                                segmentSilenceRef.current = 0;
                            } else {
                                segmentSilenceRef.current += frameDuration;
                            }

                            if (shouldFlushSpeechSegment({
                                durationSec: segmentDurationRef.current,
                                silenceSec: segmentSilenceRef.current,
                                hasSpeech: segmentHasSpeechRef.current,
                            })) {
                                const wav = pcmChunksToWav(pcmChunksRef.current, audioContext.sampleRate);
                                pcmChunksRef.current = [];
                                segmentDurationRef.current = 0;
                                segmentSilenceRef.current = 0;
                                segmentHasSpeechRef.current = false;
                                segmentsDispatchedRef.current += 1;
                                void enqueueSegmentTranscription(wav, false);
                            }
                        };

                        source.connect(processor);
                        if (typeof audioContext.createGain === 'function' && audioContext.destination) {
                            const silentGain = audioContext.createGain();
                            silentGain.gain.value = 0;
                            processor.connect(silentGain);
                            silentGain.connect(audioContext.destination);
                        } else if (audioContext.destination) {
                            processor.connect(audioContext.destination);
                        }
                    }
                } catch {
                    // Fall back cleanly to MediaRecorder-only capture if AudioContext graph setup fails.
                }
            }

            const recorder = new MediaRecorder(stream);
            recorderRef.current = recorder;
            chunksRef.current = [];

            recorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    chunksRef.current.push(event.data);
                }
            };

            recorder.onstop = async () => {
                const chunks = chunksRef.current;
                const discarded = discardRef.current;
                const tailPcm = pcmChunksRef.current;
                const tailHasSpeech = segmentHasSpeechRef.current;
                const hadWebAudio = hadWebAudioPcmRef.current;
                const sampleRate = audioContextRef.current?.sampleRate ?? TARGET_SAMPLE_RATE;
                const priorSegments = segmentsDispatchedRef.current;

                cleanup();

                if (discarded) {
                    updateState('idle');
                    return;
                }

                if (!hadWebAudio && chunks.length === 0) {
                    updateState('idle');
                    return;
                }

                updateState('transcribing');
                startFinishingTimer();

                try {
                    if (hadWebAudio) {
                        if (tailPcm.length > 0 && (tailHasSpeech || priorSegments === 0)) {
                            const tailWav = pcmChunksToWav(tailPcm, sampleRate);
                            segmentsDispatchedRef.current += 1;
                            void enqueueSegmentTranscription(tailWav, priorSegments === 0);
                        }
                    } else if (chunks.length > 0) {
                        const wav = await blobToWav(new Blob(chunks, { type: chunks[0].type }));
                        void enqueueSegmentTranscription(wav, true);
                    }
                    await queueRef.current;
                } catch (transcribeError) {
                    if (!discardRef.current) {
                        setError(
                            transcribeError instanceof Error
                                ? transcribeError.message
                                : 'Could not transcribe the recording.',
                        );
                    }
                } finally {
                    stopTimers();
                    setFinishingElapsed(0);
                    if (!discardRef.current) {
                        updateState('idle');
                    }
                }
            };

            recorder.start();
            updateState('recording');
            timerRef.current = window.setInterval(
                () => setElapsed((seconds) => seconds + 1),
                1000,
            );
        } catch (startError) {
            cleanup();
            updateState('idle');
            setError(
                startError instanceof Error && startError.name === 'NotAllowedError'
                    ? 'Microphone access was denied.'
                    : 'Could not start recording.',
            );
        }
    };

    const cancel = () => {
        discardRef.current = true;
        abortRef.current?.abort();
        const recorder = recorderRef.current;
        if (recorder && recorder.state !== 'inactive') {
            try {
                recorder.stop();
            } catch {
                // Ignore recorder stop errors on cancel.
            }
        }
        cleanup();
        if (insertedSegmentsRef.current.length > 0) {
            onCancelSession?.([...insertedSegmentsRef.current]);
            insertedSegmentsRef.current = [];
        }
        updateState('idle');
    };

    const finish = (discard: boolean) => {
        if (discard) {
            cancel();
            return;
        }
        discardRef.current = false;
        recorderRef.current?.stop();
    };

    const retryLastClip = async () => {
        const wav = retryWavRef.current;
        if (!wav) {
            return;
        }
        setError(null);
        discardRef.current = false;
        abortRef.current = new AbortController();
        queueRef.current = Promise.resolve();
        updateState('transcribing');
        startFinishingTimer();
        try {
            await enqueueSegmentTranscription(wav, true);
        } finally {
            stopTimers();
            setFinishingElapsed(0);
            if (!discardRef.current) {
                updateState('idle');
            }
        }
    };

    if (state === 'recording') {
        return (
            <div
                role="status"
                aria-label="Recording voice input"
                data-testid="voice-input-recording"
                className={clsx(
                    'inline-flex items-center gap-1.5 rounded-xl border border-danger bg-danger-soft px-2.5',
                    compact ? 'h-8 text-[11px]' : 'h-9 text-xs',
                )}
            >
                <span
                    aria-hidden="true"
                    className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-danger"
                />
                <span
                    aria-hidden="true"
                    data-testid="voice-input-waveform"
                    className="inline-flex h-4 items-center gap-0.5 text-danger"
                >
                    {bars.map((height, index) => (
                        <span
                            key={index}
                            style={{ height: `${Math.round(height * 16)}px` }}
                            className="w-0.5 rounded-full bg-current transition-[height] duration-100"
                        />
                    ))}
                </span>
                <span className="font-mono text-xs text-danger tabular-nums">
                    {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}
                </span>
                <button
                    type="button"
                    onClick={() => finish(true)}
                    aria-label="Cancel recording"
                    title="Cancel recording"
                    className="rounded-md p-1 text-text-3 hover:bg-surface-2 hover:text-text-1"
                >
                    <X size={compact ? 14 : 15} />
                </button>
                <button
                    type="button"
                    onClick={() => finish(false)}
                    aria-label="Send recording"
                    title="Finish recording"
                    className="rounded-md bg-surface-2 p-1 text-accent hover:bg-surface-3"
                >
                    <Check size={compact ? 14 : 15} />
                </button>
            </div>
        );
    }

    if (state === 'transcribing') {
        return (
            <div
                role="status"
                aria-live="polite"
                data-testid="voice-input-finishing"
                className={clsx(
                    'inline-flex items-center gap-1.5 rounded-xl border border-accent/50 bg-accent-soft px-2.5 text-accent',
                    compact ? 'h-8 text-[11px]' : 'h-9 text-xs',
                )}
            >
                <Loader2 size={compact ? 13 : 14} className="shrink-0 animate-spin" aria-hidden="true" />
                <span className="font-medium">Finishing…</span>
                <span className="font-mono text-[11px] tabular-nums">
                    {Math.floor(finishingElapsed / 60)}:{String(finishingElapsed % 60).padStart(2, '0')}
                </span>
                <button
                    type="button"
                    onClick={cancel}
                    aria-label="Cancel transcription"
                    title="Cancel transcription"
                    className="rounded-md p-1 text-text-3 hover:bg-surface-2 hover:text-text-1"
                >
                    <X size={compact ? 13 : 14} />
                </button>
            </div>
        );
    }

    if (error && retryWavRef.current) {
        return (
            <div
                role="alert"
                data-testid="voice-input-error-pill"
                className={clsx(
                    'inline-flex items-center gap-1.5 rounded-xl border border-danger/60 bg-danger-soft px-2.5 text-danger',
                    compact ? 'h-8 text-[11px]' : 'h-9 text-xs',
                )}
            >
                <AlertTriangle size={13} className="shrink-0" aria-hidden="true" />
                <span className="font-medium">Last clip failed</span>
                <button
                    type="button"
                    onClick={() => void retryLastClip()}
                    className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] font-semibold text-accent hover:bg-surface-3"
                >
                    Retry
                </button>
                <button
                    type="button"
                    onClick={() => {
                        retryWavRef.current = null;
                        setError(null);
                    }}
                    aria-label="Dismiss voice error"
                    title="Dismiss"
                    className="rounded-md p-1 text-text-3 hover:bg-surface-2 hover:text-text-1"
                >
                    <X size={13} />
                </button>
            </div>
        );
    }

    return (
        <button
            type="button"
            onClick={() => void start()}
            disabled={disabled}
            aria-label={ariaLabel}
            title={error ?? ariaLabel}
            data-testid="voice-input-button"
            className={clsx(
                'inline-flex items-center justify-center rounded-xl border',
                'bg-surface-1 transition-colors disabled:cursor-not-allowed disabled:opacity-60',
                compact ? 'h-8 w-8 rounded-lg' : 'h-9 w-9',
                error
                    ? 'border-danger text-danger'
                    : 'border-edge text-text-2 hover:bg-surface-2 hover:text-text-1',
            )}
        >
            <Mic size={compact ? 15 : 16} />
        </button>
    );
}
