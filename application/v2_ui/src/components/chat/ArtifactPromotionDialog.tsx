// ArtifactPromotionDialog.tsx
// Where a generated file will be saved, asked before it is sent.
//
// Classic asks first as well, with a confirmation when the conversation settles the destination
// and a chooser when it does not. Adding a file to a workspace is not undone from the chat: a
// personal copy is private to the reader, but a group or public one is a request to that
// workspace's approvers, and the reader should see which workspace that is before it goes.

import { useId, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, TriangleAlert } from 'lucide-react';
import type { PromotionTarget } from '../../lib/generatedArtifactActions';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';

const APPROVAL_NOTE =
    'It becomes available in the workspace once one of its approvers accepts the request.';

export function ArtifactPromotionDialog({
    fileName,
    targets,
    busy,
    error,
    onConfirm,
    onClose,
}: {
    fileName: string;
    targets: readonly PromotionTarget[];
    busy: boolean;
    /** Why the last attempt failed, so the reader can try again without losing their place. */
    error: string | null;
    onConfirm: (target: PromotionTarget) => void;
    onClose: () => void;
}) {
    const [selectedId, setSelectedId] = useState(targets[0]?.id ?? '');
    const name = useId();
    const single = targets.length === 1;
    const selected = targets.find((target) => target.id === selectedId) ?? targets[0];

    if (!selected) {
        return null;
    }

    return (
        <Modal
            title={single ? `Add to ${selected.name}?` : 'Choose workspace'}
            description={
                single
                    ? `${fileName} will be saved to ${selected.name}.`
                    : `Select where to save ${fileName}.`
            }
            // A request in flight cannot be taken back by closing, and its answer needs a place.
            onClose={() => {
                if (!busy) onClose();
            }}
            footer={
                <>
                    <GlassButton variant="ghost" size="sm" onClick={onClose} disabled={busy}>
                        Cancel
                    </GlassButton>
                    <GlassButton
                        variant="primary"
                        size="sm"
                        disabled={busy}
                        onClick={() => onConfirm(selected)}
                    >
                        {busy && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
                        {single ? selected.confirmLabel : 'Add to selected workspace'}
                    </GlassButton>
                </>
            }
        >
            <div className="space-y-3 text-sm text-text-2">
                {single ? (
                    <p>
                        {selected.detail}.{selected.scope !== 'personal' ? ` ${APPROVAL_NOTE}` : ''}
                    </p>
                ) : (
                    <fieldset className="space-y-2" disabled={busy}>
                        <legend className="sr-only">Workspace</legend>
                        {targets.map((target) => (
                            <label
                                key={target.id}
                                className={clsx(
                                    'flex cursor-pointer items-start gap-2 rounded-lg border p-3',
                                    target.id === selected.id
                                        ? 'border-accent bg-accent-soft'
                                        : 'border-edge hover:bg-surface-2',
                                )}
                            >
                                <input
                                    type="radio"
                                    name={name}
                                    value={target.id}
                                    checked={target.id === selected.id}
                                    onChange={() => setSelectedId(target.id)}
                                    className="mt-1"
                                />
                                <span className="min-w-0">
                                    <span className="block font-medium break-words text-text-1">
                                        {target.name}
                                    </span>
                                    <span className="block text-xs text-text-3">{target.detail}</span>
                                </span>
                            </label>
                        ))}
                    </fieldset>
                )}
                {!single && selected.scope !== 'personal' && (
                    <p className="text-xs text-text-3">{APPROVAL_NOTE}</p>
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
        </Modal>
    );
}
