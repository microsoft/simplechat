// NotificationBell.tsx
// The bell in the navigation rail, and the panel it opens.
//
// V2 has no top bar, so the bell sits in the rail's header beside the brand mark. Expanded,
// it shows how many notices are unread; collapsed to the icon strip there is no room for a
// number, so a dot says there is something to read and the accessible name says how much.

import { useCallback, useId, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Bell } from 'lucide-react';
import { formatNotificationCount } from '../../lib/notifications';
import { useReducedMotion } from '../../lib/workflowAlertMotion';
import { useNotificationStore } from '../../stores/notificationStore';
import { useWorkflowAlertStore } from '../../stores/workflowAlertStore';
import { NotificationPanel } from './NotificationPanel';
import '../notifications/WorkflowAlertNotice.css';

export function NotificationBell({ collapsed, className }: { collapsed: boolean; className?: string }) {
    const count = useNotificationStore((state) => state.count);
    // Bumped when a workflow alert's notice tucks in here; the bell swings once in answer.
    const ringToken = useWorkflowAlertStore((state) => state.ringToken);
    const reducedMotion = useReducedMotion();
    const [open, setOpen] = useState(false);
    const buttonRef = useRef<HTMLButtonElement>(null);
    const panelId = useId();

    const unread = count ?? 0;
    const label = unread > 0
        ? `Notifications, ${formatNotificationCount(unread)} unread`
        : 'Notifications';

    const close = useCallback((options?: { restoreFocus?: boolean }) => {
        setOpen(false);
        if (options?.restoreFocus !== false) {
            buttonRef.current?.focus();
        }
    }, []);

    return (
        <>
            <button
                ref={buttonRef}
                type="button"
                data-notification-bell=""
                data-unread-count={unread}
                onClick={() => setOpen((isOpen) => !isOpen)}
                aria-label={label}
                aria-expanded={open}
                aria-haspopup="dialog"
                aria-controls={open ? panelId : undefined}
                title={label}
                className={clsx(
                    'relative shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1',
                    open && 'bg-surface-2 text-text-1',
                    className,
                )}
            >
                <span
                    key={ringToken}
                    aria-hidden="true"
                    data-notification-bell-ring={ringToken > 0 && !reducedMotion ? '' : undefined}
                    className={clsx('inline-flex', ringToken > 0 && !reducedMotion && 'wf-bell-swing')}
                >
                    <Bell size={17} aria-hidden="true" />
                </span>
                {unread > 0 && collapsed && (
                    <span
                        aria-hidden="true"
                        data-notification-dot=""
                        className="absolute top-1 right-1 h-2 w-2 rounded-full bg-accent ring-2 ring-surface-solid"
                    />
                )}
                {unread > 0 && !collapsed && (
                    <span
                        aria-hidden="true"
                        data-notification-badge=""
                        className="absolute -top-0.5 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] leading-none font-semibold text-on-accent"
                    >
                        {formatNotificationCount(unread)}
                    </span>
                )}
            </button>
            {open && <NotificationPanel id={panelId} anchorRef={buttonRef} onClose={close} />}
        </>
    );
}
