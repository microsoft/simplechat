// ConfirmActionModal.tsx
// The confirmation in front of an operation that changes a production resource.
//
// Applying Cosmos indexes, deleting stale cache documents, resetting the document access
// backfill and changing throughput all take effect outside SimpleChat, and some cannot be
// undone from here. Each is stated in full before it runs, with the outcome first and the
// caveats after, so the decision is made on what will happen rather than on a button
// label. Everything else on the Scale cards acts without asking.
//
// Only deletions get the danger treatment. A change with lasting side effects keeps the
// primary button and says what the side effects are; an amber button would not pass text
// contrast in either theme, and colour is not where that warning belongs anyway.

import type { ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { AdminModal } from './AdminModal';
import { GlassButton } from '../ui/primitives';

export function ConfirmActionModal({
    title,
    confirmLabel,
    tone = 'primary',
    busy = false,
    cancelLabel = 'Cancel',
    confirmDisabled = false,
    onConfirm,
    onClose,
    children,
}: {
    title: string;
    confirmLabel: string;
    tone?: 'primary' | 'danger';
    busy?: boolean;
    cancelLabel?: string;
    confirmDisabled?: boolean;
    onConfirm: () => void;
    onClose: () => void;
    children: ReactNode;
}) {
    return (
        <AdminModal
            title={title}
            // A request in flight cannot be called back, so the dialog stays until it lands.
            onClose={busy ? () => undefined : onClose}
            footer={
                <>
                    <GlassButton type="button" variant="ghost" size="sm" disabled={busy} onClick={onClose}>
                        {cancelLabel}
                    </GlassButton>
                    <GlassButton
                        type="button"
                        size="sm"
                        variant={tone === 'danger' ? 'danger' : 'primary'}
                        disabled={busy || confirmDisabled}
                        aria-busy={busy || undefined}
                        onClick={onConfirm}
                    >
                        {busy ? <Loader2 size={14} aria-hidden="true" className="animate-spin" /> : null}
                        {confirmLabel}
                    </GlassButton>
                </>
            }
        >
            <div className="space-y-3 text-sm leading-relaxed text-text-2">{children}</div>
        </AdminModal>
    );
}
