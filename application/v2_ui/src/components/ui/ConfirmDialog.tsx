// ConfirmDialog.tsx
// A yes/no gate in front of an action that cannot be taken back.
//
// Exists because the chat rail's delete had no gate at all: one click on a menu item
// destroyed a conversation and every message in it, with no undo and no warning. That is
// tolerable nowhere, and unacceptable once the same click can apply to a dozen rows at
// once.
//
// Deliberately not a generic "are you sure". The caller supplies the sentence describing
// what will actually happen, because the honest wording differs per case — a shared
// conversation the user can only step out of is not being deleted, and saying so would be
// a lie the user cannot check afterwards.

import { Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';
import { Modal } from './Modal';
import { GlassButton } from './primitives';

export function ConfirmDialog({
    title,
    description,
    confirmLabel,
    confirmIcon,
    cancelLabel = 'Cancel',
    busy = false,
    tone = 'danger',
    children,
    onConfirm,
    onClose,
}: {
    title: string;
    description?: string;
    confirmLabel: string;
    confirmIcon?: ReactNode;
    cancelLabel?: string;
    busy?: boolean;
    tone?: 'danger' | 'primary';
    /** Extra detail below the description, such as a list of what is affected. */
    children?: ReactNode;
    onConfirm: () => void;
    onClose: () => void;
}) {
    return (
        <Modal
            title={title}
            description={description}
            onClose={onClose}
            footer={
                <>
                    <GlassButton variant="ghost" size="sm" onClick={onClose} disabled={busy}>
                        {cancelLabel}
                    </GlassButton>
                    <GlassButton
                        variant={tone === 'danger' ? 'danger' : 'primary'}
                        size="sm"
                        disabled={busy}
                        onClick={onConfirm}
                    >
                        {busy ? <Loader2 size={14} className="animate-spin" /> : confirmIcon}
                        {confirmLabel}
                    </GlassButton>
                </>
            }
        >
            {children ?? (
                <p className="text-xs text-text-2">This cannot be undone.</p>
            )}
        </Modal>
    );
}
