// Toaster.tsx
// Renders transient notifications from the toast store.

import { clsx } from 'clsx';
import { CircleAlert, CircleCheck, Info, X } from 'lucide-react';
import { useToastStore, type ToastTone } from '../../stores/toastStore';

const TONE_ICON: Record<ToastTone, typeof Info> = {
    success: CircleCheck,
    error: CircleAlert,
    info: Info,
};

const TONE_CLASS: Record<ToastTone, string> = {
    success: 'text-ok',
    error: 'text-danger',
    info: 'text-accent',
};

export function Toaster() {
    const { toasts, dismiss } = useToastStore();

    if (toasts.length === 0) {
        return null;
    }

    return (
        // `aria-live` so a screen reader announces a result the user cannot see happen.
        <div
            aria-live="polite"
            className="pointer-events-none fixed bottom-4 left-1/2 z-[60] flex w-full max-w-md -translate-x-1/2 flex-col gap-2 px-4"
        >
            {toasts.map((item) => {
                const Icon = TONE_ICON[item.tone];
                return (
                    <div
                        key={item.id}
                        role={item.tone === 'error' ? 'alert' : 'status'}
                        className="glass-modal pointer-events-auto flex items-start gap-2.5 rounded-xl px-3.5 py-2.5"
                    >
                        <Icon size={16} className={clsx('mt-0.5 shrink-0', TONE_CLASS[item.tone])} />
                        <p className="min-w-0 flex-1 text-sm text-text-1">{item.message}</p>
                        <button
                            type="button"
                            onClick={() => dismiss(item.id)}
                            aria-label="Dismiss notification"
                            className="shrink-0 rounded-md p-0.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                        >
                            <X size={14} />
                        </button>
                    </div>
                );
            })}
        </div>
    );
}
