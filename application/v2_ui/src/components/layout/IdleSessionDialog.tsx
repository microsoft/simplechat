// IdleSessionDialog.tsx
// The warning shown shortly before the server signs an idle user out, with a live countdown and
// the two ways to answer it: "Stay signed in" refreshes the session and "Logout now" ends it.
// At zero the page signs the user out on its own (see idleSession.ts).
//
// Classic shows the same Session Expiring Soon dialog (base.html). This one is a real alert
// dialog: it takes focus when it opens, keeps Tab inside itself, and ignores Escape and clicks
// outside it, because the only valid answers are the two buttons. It is drawn above every other
// dialog and swallows Escape on the way in, so a dialog underneath is not closed by a key press
// meant for this one. The countdown is read out when the dialog opens and then only as it
// crosses a minute, half a minute and ten seconds; announcing every second would make it
// unusable with a screen reader.
//
// The administrator's sentence is plain text and is rendered as text.

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { Clock, Loader2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import {
    countdownAnnouncement,
    formatRemaining,
    resolveIdlePolicy,
    type IdleSessionView,
} from '../../lib/idleSession';
import { useIdleSessionRuntime } from '../../lib/idleSessionRuntime';
import { useBootstrapStore } from '../../stores/bootstrapStore';

export function IdleSessionDialog({
    message,
    view,
    onStay,
    onSignOut,
}: {
    message: string;
    view: IdleSessionView;
    onStay: () => void;
    onSignOut: () => void;
}) {
    const titleId = useId();
    const descriptionId = useId();
    const panelRef = useRef<HTMLDivElement>(null);
    // Read while rendering, before the Stay button's autoFocus has moved focus into the dialog.
    const [opener] = useState<HTMLElement | null>(() => {
        const active = document.activeElement;
        return active instanceof HTMLElement && active !== document.body ? active : null;
    });
    const previousSeconds = useRef<number | null>(null);
    const [announcement, setAnnouncement] = useState('');

    useEffect(() => {
        const spoken = countdownAnnouncement(previousSeconds.current, view.secondsRemaining);
        previousSeconds.current = view.secondsRemaining;
        if (spoken) {
            setAnnouncement(spoken);
        }
    }, [view.secondsRemaining]);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            const panel = panelRef.current;
            if (event.key !== 'Tab' || !panel) {
                return;
            }
            const buttons = [...panel.querySelectorAll<HTMLElement>('button')];
            const first = buttons[0];
            const last = buttons[buttons.length - 1];
            if (!first || !last) {
                return;
            }
            const active = document.activeElement;
            if (!panel.contains(active)) {
                event.preventDefault();
                (event.shiftKey ? last : first).focus();
            } else if (event.shiftKey && active === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && active === last) {
                event.preventDefault();
                first.focus();
            }
        };
        // Capture, so Escape is stopped before a dialog underneath hears it.
        window.addEventListener('keydown', onKeyDown, true);
        return () => window.removeEventListener('keydown', onKeyDown, true);
    }, []);

    // Hand focus back to where it was once the warning goes, as every other dialog does.
    useEffect(() => () => {
        const active = document.activeElement;
        if (opener?.isConnected && (!active || active === document.body)) {
            opener.focus({ preventScroll: true });
        }
    }, [opener]);

    return createPortal(
        <div
            className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4"
            data-testid="v2-idle-session-overlay"
            // A click outside the panel is not an answer, and must not pull focus out of it.
            onMouseDown={(event) => {
                if (event.target === event.currentTarget) {
                    event.preventDefault();
                }
            }}
        >
            <div
                ref={panelRef}
                role="alertdialog"
                aria-modal="true"
                aria-labelledby={titleId}
                aria-describedby={descriptionId}
                tabIndex={-1}
                data-testid="v2-idle-session-dialog"
                className="glass-modal flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-2xl outline-none"
            >
                <div className="flex items-center gap-3 border-b border-edge px-4 py-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-warn-soft text-warn">
                        <Clock size={18} aria-hidden="true" />
                    </span>
                    <h2 id={titleId} className="text-sm font-semibold text-text-1">
                        Session expiring soon
                    </h2>
                </div>

                <div id={descriptionId} className="space-y-2 overflow-y-auto px-4 py-3 text-sm text-text-1">
                    <p className="break-words" data-testid="v2-idle-session-message">{message}</p>
                    <p>
                        You will be signed out in{' '}
                        <strong data-testid="v2-idle-session-countdown">
                            {formatRemaining(view.secondsRemaining)}
                        </strong>{' '}
                        unless you continue your session.
                    </p>
                </div>

                {view.error ? (
                    <p role="alert" className="px-4 pb-2 text-xs text-danger" data-testid="v2-idle-session-error">
                        {view.error}
                    </p>
                ) : null}

                {/* The countdown, spoken at a few marks only. */}
                <div role="status" aria-live="polite" className="sr-only" data-testid="v2-idle-session-announcement">
                    {announcement}
                </div>

                <div className="flex flex-col gap-2 border-t border-edge px-4 py-3 sm:flex-row sm:justify-end">
                    <GlassButton
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="w-full justify-center sm:w-auto"
                        onClick={onSignOut}
                        data-testid="v2-idle-session-sign-out"
                    >
                        Logout now
                    </GlassButton>
                    {/* aria-disabled rather than disabled while the server answers, so focus
                        stays on the button instead of falling to the page behind the dialog. */}
                    <GlassButton
                        type="button"
                        variant="primary"
                        size="sm"
                        autoFocus
                        aria-busy={view.staying || undefined}
                        aria-disabled={view.staying || undefined}
                        className={clsx('w-full justify-center sm:w-auto', view.staying && 'cursor-wait opacity-70')}
                        onClick={() => {
                            if (!view.staying) {
                                onStay();
                            }
                        }}
                        data-testid="v2-idle-session-stay"
                    >
                        {view.staying ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
                        Stay signed in
                    </GlassButton>
                </div>
            </div>
        </div>,
        document.body,
    );
}

/**
 * Runs the idle-session warning and draws its dialog.
 *
 * Mounted once, inside the shell, so it exists only for a loaded session. Reads the timeout
 * from bootstrap. The values are taken as primitives so a bootstrap read that brings the same
 * numbers back does not restart the clock; a changed number does.
 */
export function IdleSessionDialogHost() {
    const idle = useBootstrapStore((state) => state.data?.session?.idle_timeout);
    const enabled = idle?.enabled;
    const timeoutMinutes = idle?.timeout_minutes;
    const warningMinutes = idle?.warning_minutes;
    const warningMessage = idle?.warning_message;
    const policy = useMemo(
        () => resolveIdlePolicy({
            enabled,
            timeout_minutes: timeoutMinutes,
            warning_minutes: warningMinutes,
            warning_message: warningMessage,
        }),
        [enabled, timeoutMinutes, warningMinutes, warningMessage],
    );
    const { view, stay, signOutNow } = useIdleSessionRuntime(policy);

    if (!policy || !view.open) {
        return null;
    }
    return <IdleSessionDialog message={policy.warningMessage} view={view} onStay={stay} onSignOut={signOutNow} />;
}
