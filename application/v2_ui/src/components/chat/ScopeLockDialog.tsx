// ScopeLockDialog.tsx
// The dialog that locks or unlocks a conversation's workspace scope, and the host that shows it.
//
// One dialog serves every control that offers the lock (see `stores/scopeLockStore.ts`), and it
// is the classic scope lock modal's V2 counterpart: it says what the lock does, lists the
// workspaces it covers, and only then asks. A dialog rather than a bare toggle because unlocking
// widens what the conversation may search, and the classic interface asks first for the same
// reason.
//
// What it offers is decided once, when it opens. Reading the live state instead would flip the
// dialog from "Unlock" to "Lock" the moment the optimistic write lands, under the reader's eyes.

import { useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { Globe, Info, Lock, TriangleAlert, Unlock, User, Users } from 'lucide-react';
import {
    scopeLockCopy,
    type ScopeLockAction,
    type ScopeLockView,
    type ScopeLockWorkspace,
} from '../../lib/scopeLock';
import { useChatStore } from '../../stores/chatStore';
import { useScopeLockStore, useScopeLockView } from '../../stores/scopeLockStore';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';

const WORKSPACE_ICON = {
    personal: User,
    group: Users,
    public: Globe,
} as const;

function WorkspaceList({ label, workspaces }: { label: string; workspaces: ScopeLockWorkspace[] }) {
    if (workspaces.length === 0) {
        return <p className="text-xs text-text-3">No specific workspaces recorded.</p>;
    }
    return (
        <div>
            {label && <p className="mb-1.5 text-xs text-text-3">{label}</p>}
            <ul aria-label="Workspaces" className="space-y-1">
                {workspaces.map((workspace) => {
                    const Icon = WORKSPACE_ICON[workspace.kind];
                    return (
                        <li
                            key={`${workspace.kind}:${workspace.id}`}
                            className="flex items-center gap-2 rounded-lg bg-surface-sunken px-2.5 py-1.5 text-xs text-text-1"
                        >
                            <Icon size={13} className="shrink-0 text-text-3" aria-hidden="true" />
                            <span className="min-w-0 flex-1 break-words">{workspace.name}</span>
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}

function DialogBody({
    view,
    intent,
    error,
}: {
    view: ScopeLockView;
    intent: ScopeLockAction | null;
    error: string | null;
}) {
    const copy = scopeLockCopy(view, intent);
    return (
        <div className="space-y-3 text-sm text-text-2">
            <p>{copy.description}</p>
            <WorkspaceList label={copy.listLabel} workspaces={view.workspaces} />
            {copy.notice && (
                <p
                    className={clsx(
                        'flex items-start gap-2 rounded-lg px-3 py-2 text-xs',
                        copy.noticeTone === 'warn' ? 'bg-warn-soft text-warn' : 'bg-info-soft text-info',
                    )}
                >
                    {copy.noticeTone === 'warn' ? (
                        <TriangleAlert size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                    ) : (
                        <Info size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                    )}
                    <span className="min-w-0 break-words">{copy.notice}</span>
                </p>
            )}
            {error && (
                <p
                    role="alert"
                    className="flex items-start gap-2 rounded-lg bg-danger-soft px-3 py-2 text-xs text-danger"
                >
                    <TriangleAlert size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                    <span className="min-w-0 break-words">{error}</span>
                </p>
            )}
        </div>
    );
}

function ScopeLockDialog({ view }: { view: ScopeLockView }) {
    const [intent] = useState<ScopeLockAction | null>(view.action);
    const conversationId = useChatStore((state) => state.metadata?.conversation_id);
    const pending = useScopeLockStore((state) => state.pending);
    const error = useScopeLockStore((state) => state.error);
    const copy = scopeLockCopy(view, intent);
    const close = () => useScopeLockStore.getState().closeDialog();

    if (!intent) {
        // Nothing can be changed: the dialog is a place to read why.
        return (
            <Modal
                title={copy.title}
                onClose={close}
                footer={
                    <GlassButton variant="primary" size="sm" onClick={close}>
                        Done
                    </GlassButton>
                }
            >
                <DialogBody view={view} intent={intent} error={null} />
            </Modal>
        );
    }

    return (
        <ConfirmDialog
            title={copy.title}
            confirmLabel={copy.confirmLabel}
            confirmIcon={
                pending ? undefined : intent === 'lock' ? (
                    <Lock size={14} aria-hidden="true" />
                ) : (
                    <Unlock size={14} aria-hidden="true" />
                )
            }
            tone="primary"
            busy={pending}
            onConfirm={() => {
                if (conversationId) {
                    void useScopeLockStore.getState().change(conversationId, intent === 'lock');
                }
            }}
            onClose={close}
        >
            <DialogBody view={view} intent={intent} error={error} />
        </ConfirmDialog>
    );
}

/**
 * Shows the dialog when a control has asked for it.
 *
 * Rendered once, beside the lock in the chat header, so it outlives the control that opened it:
 * the Documents picker that offers a shortcut closes as soon as the reader clicks outside it.
 */
export function ScopeLockDialogHost() {
    const open = useScopeLockStore((state) => state.open);
    const view = useScopeLockView();
    const conversationId = useChatStore((state) => state.activeConversationId);

    useEffect(() => {
        // Whatever it was asking about belongs to the conversation just left.
        useScopeLockStore.setState({ open: false, error: null });
    }, [conversationId]);

    useEffect(() => {
        if (open && view.state === 'hidden') {
            useScopeLockStore.setState({ open: false, error: null });
        }
    }, [open, view.state]);

    if (!open || view.state === 'hidden') {
        return null;
    }
    return <ScopeLockDialog view={view} />;
}
