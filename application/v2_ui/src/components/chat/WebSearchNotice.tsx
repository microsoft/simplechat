// WebSearchNotice.tsx
// The banner shown above the composer while web search is armed.
//
// Reproduces the notice in `chats.html` and `chat-input-actions.js`: it appears only while
// the Web toggle is on, because the point is to warn about *this* message leaving the
// tenant, and a banner that is always present stops being read. Turning web search off
// hides it again without consuming the dismissal.

import { Info, X } from 'lucide-react';
import { useState } from 'react';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    WEB_SEARCH_NOTICE_SESSION_KEY,
    dismissNoticeForSession,
    isNoticeDismissedForSession,
} from '../../lib/notices';

export function WebSearchNotice({ active }: { active: boolean }) {
    const notice = useBootstrapStore((state) => state.data?.notices?.web_search);

    // Seeded from session storage so a dismissal survives switching conversations, which
    // remounts the composer.
    const [dismissed, setDismissed] = useState(() =>
        isNoticeDismissedForSession(WEB_SEARCH_NOTICE_SESSION_KEY),
    );

    if (!notice?.enabled || !notice.text || !active || dismissed) {
        return null;
    }

    return (
        <div
            role="note"
            aria-live="polite"
            className="mb-2 flex items-start gap-2 rounded-xl border border-edge bg-info-soft px-3 py-2"
        >
            <Info size={15} className="mt-0.5 shrink-0 text-info" aria-hidden="true" />
            <p className="min-w-0 flex-1 text-xs leading-relaxed text-text-2">{notice.text}</p>
            <button
                type="button"
                onClick={() => {
                    // A refused write still hides it here: the notice is tied to the
                    // toggle, so it comes back the next time web search is armed.
                    dismissNoticeForSession(WEB_SEARCH_NOTICE_SESSION_KEY);
                    setDismissed(true);
                }}
                aria-label="Dismiss the web search notice"
                title="Dismiss"
                className="shrink-0 rounded-md p-0.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
            >
                <X size={14} />
            </button>
        </div>
    );
}
