// AiNotice.tsx
// The administrator-configured notice below the composer.
//
// Reproduces `chat-ai-notice.js`. Where it is stored depends on how often it may be
// dismissed, and the four frequencies are not interchangeable:
//
//   non_dismissible  Always visible, no dismiss control at all.
//   every_session    A browser-session fact, so it stays in sessionStorage.
//   daily / once     Must outlive the tab, so the server records the dismissal and decides
//                    on the next load whether it still applies.
//
// Nothing is rendered when the administrator has not configured a notice. The interface
// deliberately does not substitute a generic disclaimer of its own: an organisation that
// turned the notice off did so on purpose, and the classic interface honours that.

import { useState } from 'react';
import { Info, X } from 'lucide-react';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useToastStore } from '../../stores/toastStore';
import { dismissAiNotice } from '../../lib/endpoints';
import {
    aiNoticeSessionKey,
    dismissNoticeForSession,
    isNoticeDismissedForSession,
} from '../../lib/notices';

export function AiNotice() {
    const notice = useBootstrapStore((state) => state.data?.notices?.ai);
    const pushToast = useToastStore((state) => state.push);

    // Read once at mount rather than on every render: this sits inside the composer, which
    // re-renders on each keystroke, and session storage is a synchronous browser call.
    // `every_session` is the only frequency stored here; the daily and once windows are
    // already resolved on the payload, and non_dismissible is never dismissed at all.
    const [dismissed, setDismissed] = useState(
        () =>
            notice?.frequency === 'every_session' &&
            isNoticeDismissedForSession(aiNoticeSessionKey(notice.hash)),
    );
    const [saving, setSaving] = useState(false);

    if (!notice?.enabled || !notice.message || notice.dismissed || dismissed) {
        return null;
    }

    const dismissible = notice.frequency !== 'non_dismissible';

    const onDismiss = async () => {
        if (notice.frequency === 'every_session') {
            if (!dismissNoticeForSession(aiNoticeSessionKey(notice.hash))) {
                pushToast('error', 'This browser cannot save the session dismissal.');
                return;
            }
            setDismissed(true);
            return;
        }

        // Stays visible until the write lands. Hiding first would tell the user the notice
        // is gone for the day when it may be back on the next page load.
        setSaving(true);
        try {
            await dismissAiNotice(notice.hash, notice.frequency);
            setDismissed(true);
        } catch {
            pushToast('error', 'The AI notice could not be dismissed. Please try again.');
        } finally {
            setSaving(false);
        }
    };

    return (
        <section
            aria-label="AI notice"
            aria-live="polite"
            className="mt-2 flex items-start gap-2 px-2"
        >
            <Info size={13} className="mt-[3px] shrink-0 text-accent" aria-hidden="true" />
            {/* `whitespace-pre-line` because normalize_ai_notice_message keeps the line
                breaks an administrator typed, and the classic notice renders them. */}
            <p className="min-w-0 flex-1 text-[11px] leading-relaxed whitespace-pre-line text-text-3">
                {notice.message}
            </p>
            {dismissible && (
                <button
                    type="button"
                    onClick={() => void onDismiss()}
                    disabled={saving}
                    aria-label="Dismiss the AI notice"
                    title="Dismiss"
                    className="mt-[1px] shrink-0 rounded-md p-0.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-40"
                >
                    <X size={12} />
                </button>
            )}
        </section>
    );
}
