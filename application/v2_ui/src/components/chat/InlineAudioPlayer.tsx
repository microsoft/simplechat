// InlineAudioPlayer.tsx
// A compact player for an audio recording linked in a chat message.
//
// Collapsed, it is a single line: play/pause, the recording's title, elapsed and total time, and
// a thin progress line. Pressing play (or the chevron) expands it to add a seek slider, stop,
// volume and mute, and playback speed. It stays in the message rather than floating over the
// thread, so a briefing that cites several recordings keeps each one beside the text about it.
//
// Built from <span>, <button> and <input> only: links sit inside <p> and <li> elements, where
// block elements would be invalid HTML.

import { useCallback, useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { AudioLines, ChevronDown, ExternalLink, Pause, Play, Square, Volume2, VolumeX } from 'lucide-react';
import { claimPlayback, formatMediaTime, PLAYBACK_RATES, safeMediaUrl } from '../../lib/inlineMedia';
import { InlineMediaFallback } from './InlineMediaFallback';

const ICON_BUTTON =
    'inline-flex size-8 shrink-0 items-center justify-center rounded-full text-text-2 transition-colors ' +
    'hover:bg-surface-2 hover:text-text-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent';

export function InlineAudioPlayer({ src, title }: { src: string; title: string }) {
    const audioRef = useRef<HTMLAudioElement>(null);
    const [playing, setPlaying] = useState(false);
    const [expanded, setExpanded] = useState(false);
    const [position, setPosition] = useState(0);
    const [duration, setDuration] = useState(0);
    const [volume, setVolume] = useState(1);
    const [muted, setMuted] = useState(false);
    const [rateIndex, setRateIndex] = useState(0);
    const [failed, setFailed] = useState(false);

    useEffect(() => {
        const audio = audioRef.current;
        if (audio) {
            audio.volume = volume;
            audio.muted = muted;
        }
    }, [volume, muted]);

    useEffect(() => {
        const audio = audioRef.current;
        if (audio) {
            audio.playbackRate = PLAYBACK_RATES[rateIndex];
        }
    }, [rateIndex]);

    const togglePlay = useCallback(() => {
        const audio = audioRef.current;
        if (!audio) {
            return;
        }
        if (!audio.paused) {
            audio.pause();
            return;
        }
        claimPlayback(audio);
        setExpanded(true);
        audio.play().catch(() => setFailed(true));
    }, []);

    const stop = useCallback(() => {
        const audio = audioRef.current;
        if (!audio) {
            return;
        }
        audio.pause();
        audio.currentTime = 0;
        setPosition(0);
    }, []);

    const seek = useCallback((seconds: number) => {
        const audio = audioRef.current;
        if (audio && Number.isFinite(seconds)) {
            audio.currentTime = seconds;
            setPosition(seconds);
        }
    }, []);

    const readDuration = useCallback(() => {
        const value = audioRef.current?.duration ?? 0;
        setDuration(Number.isFinite(value) ? value : 0);
    }, []);

    if (failed) {
        return <InlineMediaFallback kind="audio" src={src} title={title} />;
    }

    const progress = duration > 0 ? Math.min(100, (position / duration) * 100) : 0;
    const rate = PLAYBACK_RATES[rateIndex];

    return (
        <span
            role="group"
            aria-label={`Audio: ${title}`}
            className="my-2 block w-full max-w-xl rounded-xl border border-edge bg-surface-sunken px-2 py-1.5 text-text-1"
        >
            <audio
                ref={audioRef}
                src={safeMediaUrl(src) ?? undefined}
                preload="metadata"
                onPlay={(event) => {
                    claimPlayback(event.currentTarget);
                    setPlaying(true);
                }}
                onPause={() => setPlaying(false)}
                onEnded={() => setPlaying(false)}
                onTimeUpdate={(event) => setPosition(event.currentTarget.currentTime)}
                onLoadedMetadata={readDuration}
                onDurationChange={readDuration}
                onError={() => setFailed(true)}
            />
            <span className="flex items-center gap-1.5">
                <button
                    type="button"
                    onClick={togglePlay}
                    aria-label={playing ? `Pause ${title}` : `Play ${title}`}
                    title={playing ? 'Pause' : 'Play'}
                    className={clsx(ICON_BUTTON, 'bg-accent text-on-accent hover:bg-accent hover:text-on-accent hover:opacity-90')}
                >
                    {playing ? <Pause size={15} /> : <Play size={15} className="translate-x-px" />}
                </button>
                <AudioLines size={14} className="shrink-0 text-text-3" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium" title={title}>
                    {title}
                </span>
                <span className="shrink-0 font-mono text-xs text-text-3 tabular-nums" aria-live="off">
                    {formatMediaTime(position)} / {duration > 0 ? formatMediaTime(duration) : '--:--'}
                </span>
                <button
                    type="button"
                    onClick={() => setExpanded((value) => !value)}
                    aria-expanded={expanded}
                    aria-label={expanded ? 'Hide player controls' : 'Show player controls'}
                    title={expanded ? 'Fewer controls' : 'More controls'}
                    className={ICON_BUTTON}
                >
                    <ChevronDown size={15} className={clsx('transition-transform', expanded && 'rotate-180')} />
                </button>
            </span>

            {!expanded && (
                <span className="mx-1 mt-1 block h-0.5 overflow-hidden rounded-full bg-edge" aria-hidden="true">
                    <span className="block h-full bg-accent" style={{ width: `${progress}%` }} />
                </span>
            )}

            {expanded && (
                <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 px-1">
                    <input
                        type="range"
                        min={0}
                        max={duration || 0}
                        step={0.1}
                        value={Math.min(position, duration || 0)}
                        onChange={(event) => seek(Number(event.target.value))}
                        disabled={!duration}
                        aria-label={`Seek ${title}`}
                        aria-valuetext={`${formatMediaTime(position)} of ${formatMediaTime(duration)}`}
                        className="h-1.5 min-w-[10rem] flex-1 cursor-pointer accent-[var(--accent)] disabled:cursor-not-allowed"
                    />
                    <button type="button" onClick={stop} aria-label={`Stop ${title}`} title="Stop" className={ICON_BUTTON}>
                        <Square size={13} />
                    </button>
                    <button
                        type="button"
                        onClick={() => setMuted((value) => !value)}
                        aria-pressed={muted}
                        aria-label={muted ? 'Unmute' : 'Mute'}
                        title={muted ? 'Unmute' : 'Mute'}
                        className={ICON_BUTTON}
                    >
                        {muted || volume === 0 ? <VolumeX size={15} /> : <Volume2 size={15} />}
                    </button>
                    <input
                        type="range"
                        min={0}
                        max={1}
                        step={0.05}
                        value={muted ? 0 : volume}
                        onChange={(event) => {
                            setVolume(Number(event.target.value));
                            setMuted(false);
                        }}
                        aria-label="Volume"
                        className="h-1.5 w-20 cursor-pointer accent-[var(--accent)]"
                    />
                    <button
                        type="button"
                        onClick={() => setRateIndex((index) => (index + 1) % PLAYBACK_RATES.length)}
                        aria-label={`Playback speed ${rate}x. Change speed`}
                        title="Playback speed"
                        className="inline-flex h-7 shrink-0 items-center rounded-full px-2 font-mono text-xs text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        {rate}x
                    </button>
                    <a
                        href={safeMediaUrl(src) ?? undefined}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Open the recording in a new tab"
                        aria-label={`Open ${title} in a new tab`}
                        className={ICON_BUTTON}
                    >
                        <ExternalLink size={14} />
                    </a>
                </span>
            )}
        </span>
    );
}
