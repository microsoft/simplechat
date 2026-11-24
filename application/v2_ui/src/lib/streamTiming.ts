// streamTiming.ts
// Opt-in diagnostics for the existing SSE reader. Never log frame content.

export const STREAM_TIMING_REQUEST_HEADER = 'X-SimpleChat-Stream-Timing';
const STREAM_TIMING_ID_HEADER = 'X-SimpleChat-Stream-Timing-Id';
const SAMPLE_MARKER = /^: sc-timing ([1-9]\d{0,3})\n/;
let requested = false;

export function takeStreamTimingRequest(url: string): boolean {
    if (requested || typeof window === 'undefined' || !window.location ||
        new URLSearchParams(window.location.search).get('stream_timing') !== '1') {
        return false;
    }

    const target = new URL(url, window.location.href);
    if (target.origin !== window.location.origin || target.pathname !== '/api/chat/stream') {
        return false;
    }

    requested = true;
    return true;
}

export function startStreamTiming(response: Response) {
    const runId = response.headers.get(STREAM_TIMING_ID_HEADER);
    if (!runId || !/^[a-f0-9]{16}$/.test(runId)) return undefined;

    const started = performance.now();
    const elapsed = () => Math.round((performance.now() - started) * 100) / 100;
    let readCount = 0;
    let bytesReceived = 0;
    let arrivalMs = 0;

    return {
        read(bytes: number) {
            arrivalMs = elapsed();
            readCount += 1;
            bytesReceived += bytes;
        },
        sample(frame: string) {
            const marker = SAMPLE_MARKER.exec(frame);
            if (marker) {
                console.info('[STREAMING] Timing browser arrival', {
                    diagnostic_run_id: runId,
                    event_sequence: Number(marker[1]),
                    arrival_ms: arrivalMs,
                    read_count: readCount,
                    bytes_received: bytesReceived,
                });
            }
        },
        finish(bodyEnded: boolean) {
            console.info('[STREAMING] Timing browser end', {
                diagnostic_run_id: runId,
                elapsed_ms: elapsed(),
                read_count: readCount,
                bytes_received: bytesReceived,
                body_ended: bodyEnded,
            });
        },
    };
}
