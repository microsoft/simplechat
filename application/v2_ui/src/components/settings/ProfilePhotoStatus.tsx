// ProfilePhotoStatus.tsx
// Says how "Refresh photo" on the Settings page went: a new photo, no photo, or a failure.
//
// The status region is always on the page, empty until there is something to say, because a
// screen reader announces a change inside a live region that already exists and often says
// nothing for one that arrives with its text. A failure is an alert instead: it needs reading
// now, and an alert is announced when it appears. The text is one of the fixed sentences in
// profileImage.ts, never anything the server returned.
//
// The words are in the ordinary text colour and the outcome is carried by an icon, as the
// toasts do it: coloured text would sit on the page's tinted background below the contrast
// that small text needs, and colour alone would not say which outcome it was.

import { CircleAlert, CircleCheck, Info } from 'lucide-react';
import { clsx } from 'clsx';
import type { ProfilePhotoMessage } from '../../lib/useProfilePhotoRefresh';

const BAND = 'flex shrink-0 items-start gap-2 border-b border-edge px-4 py-2 text-sm text-text-1 md:px-5';

const TONE_ICON = {
    success: { Icon: CircleCheck, className: 'text-ok' },
    info: { Icon: Info, className: 'text-accent' },
    error: { Icon: CircleAlert, className: 'text-danger' },
} as const;

function Said({ message }: { message: ProfilePhotoMessage }) {
    const { Icon, className } = TONE_ICON[message.tone];
    return (
        <>
            <Icon size={16} aria-hidden="true" className={clsx('mt-0.5 shrink-0', className)} />
            <span className="min-w-0 break-words">{message.text}</span>
        </>
    );
}

export function ProfilePhotoStatus({ message }: { message: ProfilePhotoMessage | null }) {
    const said = message && message.tone !== 'error' ? message : null;
    return (
        <>
            <div
                role="status"
                aria-live="polite"
                data-testid="v2-settings-photo-status"
                className={said ? BAND : 'sr-only'}
            >
                {said ? <Said message={said} /> : null}
            </div>
            {message?.tone === 'error' ? (
                <p role="alert" data-testid="v2-settings-photo-error" className={BAND}>
                    <Said message={message} />
                </p>
            ) : null}
        </>
    );
}
