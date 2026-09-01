// VoiceInput.tsx
// Push-to-record voice input.
//
// Records with MediaRecorder, converts to the 16 kHz mono WAV the transcription endpoint
// expects, and inserts the returned text into the composer. Recording is an explicit
// start/send/cancel flow rather than auto-send, so a misheard phrase can be discarded.

import { useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Check, Loader2, Mic, X } from 'lucide-react';
import { blobToWav, transcribeAudio } from '../../lib/voice';

type RecordingState = 'idle' | 'recording' | 'transcribing';

export function VoiceInput({ onTranscribed }: { onTranscribed: (text: string) => void }) {
    const [state, setState] = useState<RecordingState>('idle');
    const [error, setError] = useState<string | null>(null);
    const [elapsed, setElapsed] = useState(0);

    const recorderRef = useRef<MediaRecorder | null>(null);
    const chunksRef = useRef<Blob[]>([]);
    const streamRef = useRef<MediaStream | null>(null);
    const timerRef = useRef<number | null>(null);
    // Set when the user cancels, so the stop handler knows to discard rather than upload.
    const discardRef = useRef(false);

    const cleanup = () => {
        if (timerRef.current !== null) {
            window.clearInterval(timerRef.current);
            timerRef.current = null;
        }
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        recorderRef.current = null;
        chunksRef.current = [];
        setElapsed(0);
    };

    const start = async () => {
        setError(null);
        discardRef.current = false;

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
            });
            streamRef.current = stream;

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
                cleanup();

                if (discarded || chunks.length === 0) {
                    setState('idle');
                    return;
                }

                setState('transcribing');
                try {
                    const wav = await blobToWav(new Blob(chunks, { type: chunks[0].type }));
                    const result = await transcribeAudio(wav);
                    if (result.success && result.text) {
                        onTranscribed(result.text);
                    } else {
                        setError(result.error || 'Nothing was transcribed.');
                    }
                } catch (transcribeError) {
                    setError(
                        transcribeError instanceof Error
                            ? transcribeError.message
                            : 'Could not transcribe the recording.',
                    );
                } finally {
                    setState('idle');
                }
            };

            recorder.start();
            setState('recording');
            timerRef.current = window.setInterval(
                () => setElapsed((seconds) => seconds + 1),
                1000,
            );
        } catch (startError) {
            cleanup();
            setState('idle');
            setError(
                startError instanceof Error && startError.name === 'NotAllowedError'
                    ? 'Microphone access was denied.'
                    : 'Could not start recording.',
            );
        }
    };

    const finish = (discard: boolean) => {
        discardRef.current = discard;
        recorderRef.current?.stop();
    };

    if (state === 'recording') {
        return (
            <div className="inline-flex items-center gap-1 rounded-xl border border-danger bg-danger-soft px-2">
                <span
                    aria-hidden="true"
                    className="h-2 w-2 animate-pulse rounded-full bg-danger"
                />
                <span className="font-mono text-xs text-danger tabular-nums">
                    {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}
                </span>
                <button
                    type="button"
                    onClick={() => finish(true)}
                    aria-label="Cancel recording"
                    title="Cancel recording"
                    className="rounded-md p-1.5 text-text-3 hover:text-text-1"
                >
                    <X size={15} />
                </button>
                <button
                    type="button"
                    onClick={() => finish(false)}
                    aria-label="Send recording"
                    title="Send recording"
                    className="rounded-md p-1.5 text-accent hover:bg-surface-2"
                >
                    <Check size={15} />
                </button>
            </div>
        );
    }

    return (
        <button
            type="button"
            onClick={() => void start()}
            disabled={state === 'transcribing'}
            aria-label="Voice input"
            title={error ?? 'Voice input'}
            className={clsx(
                'inline-flex h-9 w-9 items-center justify-center rounded-xl border',
                'bg-surface-1 transition-colors disabled:opacity-60',
                error
                    ? 'border-danger text-danger'
                    : 'border-edge text-text-2 hover:bg-surface-2 hover:text-text-1',
            )}
        >
            {state === 'transcribing' ? (
                <Loader2 size={16} className="animate-spin" />
            ) : (
                <Mic size={16} />
            )}
        </button>
    );
}
