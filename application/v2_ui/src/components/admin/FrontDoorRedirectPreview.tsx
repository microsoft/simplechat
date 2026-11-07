// FrontDoorRedirectPreview.tsx
// Shows the two redirect URIs a Front Door origin produces.
//
// Front Door integration fails in a specific and unhelpful way: sign-in completes at
// Entra and then bounces to a URI that is not registered on the app registration, so the
// user sees a Microsoft error page and the administrator sees nothing at all. The two
// URIs that have to be registered are derived from the origin, so deriving them here and
// making them copyable removes the step where they get typed by hand and get it wrong.

import { useState } from 'react';
import { clsx } from 'clsx';
import { Check, Copy, TriangleAlert } from 'lucide-react';

/** The suffix `config.py` appends for the MSAL callback. */
const OAUTH_REDIRECT_PATH = '/getAToken';

function CopyRow({ label, url }: { label: string; url: string }) {
    const [copied, setCopied] = useState(false);

    const copy = async () => {
        try {
            await navigator.clipboard.writeText(url);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
        } catch {
            // Clipboard access can be refused by permissions policy. The URL is on
            // screen and selectable either way, so there is nothing to recover from.
        }
    };

    return (
        <div className="flex items-center gap-2 py-1">
            <span className="w-28 shrink-0 text-xs text-text-3">{label}</span>
            <code className="min-w-0 flex-1 truncate rounded-md bg-surface-2 px-2 py-1 font-mono text-xs text-text-1">
                {url}
            </code>
            <button
                type="button"
                onClick={() => void copy()}
                title={`Copy the ${label.toLowerCase()} URL`}
                aria-label={`Copy the ${label.toLowerCase()} URL`}
                className="shrink-0 rounded-md p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
            >
                {copied ? <Check size={13} className="text-ok" /> : <Copy size={13} />}
            </button>
        </div>
    );
}

export function FrontDoorRedirectPreview({
    origin,
    label,
    help,
}: {
    origin: string;
    label: string;
    help?: string;
}) {
    const trimmed = origin.trim().replace(/\/+$/, '');
    const usable = /^https?:\/\/[^/\s]+$/.test(trimmed);

    return (
        <div className="py-3">
            <p className="mb-1.5 text-sm font-medium text-text-1">{label}</p>

            {usable ? (
                <div className="rounded-lg border border-edge bg-surface-1 p-2.5">
                    <CopyRow label="Home" url={trimmed} />
                    <CopyRow label="OAuth2" url={`${trimmed}${OAUTH_REDIRECT_PATH}`} />
                </div>
            ) : (
                <p
                    className={clsx(
                        'flex items-start gap-1.5 rounded-lg bg-warn-soft px-2.5 py-1.5',
                        'text-xs text-warn',
                    )}
                >
                    <TriangleAlert size={13} className="mt-0.5 shrink-0" />
                    Enter an origin such as https://your-frontdoor.azurefd.net to see the
                    redirect URIs to register.
                </p>
            )}

            {help ? <p className="mt-1.5 text-xs leading-relaxed text-text-3">{help}</p> : null}
        </div>
    );
}
