// CopyValue.tsx
// One way to copy a value to the clipboard, for every Operations control that shares one.
//
// Role values are typed into Entra by hand, health check addresses into a monitoring tool,
// and a PowerShell snippet into a terminal. Each is easy to mistype and each fails in a way
// that is hard to trace back to the typo, so they are copyable wherever they appear. The
// pattern itself was first drawn by the app role roster's role chips; it lives here so the
// copy affordance looks and behaves the same everywhere it is offered.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Check, Copy } from 'lucide-react';

/** Copy text, reporting success so the control can say so. */
function useCopy(value: string): [boolean, () => Promise<void>] {
    const [copied, setCopied] = useState(false);
    const timer = useRef<number | null>(null);

    useEffect(
        () => () => {
            if (timer.current !== null) {
                window.clearTimeout(timer.current);
            }
        },
        [],
    );

    const copy = async () => {
        try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            if (timer.current !== null) {
                window.clearTimeout(timer.current);
            }
            timer.current = window.setTimeout(() => setCopied(false), 1500);
        } catch {
            // Clipboard access can be refused by permissions policy. The value is on screen
            // and selectable either way, so there is nothing to recover from.
        }
    };

    return [copied, copy];
}

/** A small copy button for a value shown beside it. */
export function CopyButton({ value, label }: { value: string; label: string }) {
    const [copied, copy] = useCopy(value);
    return (
        <button
            type="button"
            onClick={() => void copy()}
            title={`Copy ${label}`}
            aria-label={`Copy ${label}`}
            className={clsx(
                'inline-flex shrink-0 items-center justify-center rounded-md p-1.5 text-text-3',
                'transition-colors hover:bg-surface-2 hover:text-text-1',
                'focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none',
            )}
        >
            {copied ? <Check size={13} className="text-ok" aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
            <span className="sr-only" aria-live="polite">
                {copied ? 'Copied' : ''}
            </span>
        </button>
    );
}

/** A value shown as a monospace chip that copies itself when pressed. */
export function CopyChip({ value, label }: { value: string; label?: string }) {
    const [copied, copy] = useCopy(value);
    const description = label ?? value;
    return (
        <button
            type="button"
            onClick={() => void copy()}
            title={`Copy ${description}`}
            aria-label={`Copy ${description}`}
            className={clsx(
                'inline-flex max-w-full items-center gap-1.5 rounded-md bg-surface-2 px-2 py-0.5',
                'font-mono text-xs text-text-2 transition-colors hover:text-text-1',
                'focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none',
            )}
        >
            <span className="truncate">{value}</span>
            {copied ? (
                <Check size={11} className="shrink-0 text-ok" aria-hidden="true" />
            ) : (
                <Copy size={11} className="shrink-0 opacity-60" aria-hidden="true" />
            )}
            <span className="sr-only" aria-live="polite">
                {copied ? 'Copied' : ''}
            </span>
        </button>
    );
}
