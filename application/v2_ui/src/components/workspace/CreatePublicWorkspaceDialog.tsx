// CreatePublicWorkspaceDialog.tsx
// The create-a-public-workspace form on the public directory page.
//
// Unlike the group create dialog, the route behind this form is the classic
// POST /api/public_workspaces, which validates nothing: it stores whatever name it is given and
// only defaults a missing one. So this dialog invents no field rules the server does not enforce --
// no length ceiling, no control-character rule -- and its one client-side check is a form nicety:
// a name must be typed, because creating a silently "Untitled Workspace" reads as the form losing
// the request. Every real acceptance or refusal is the server's, and a server refusal keeps the
// draft so a policy answer never eats the typed name.

import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';

const INPUT_CLASS = 'w-full min-w-0 rounded-xl border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60';

export function CreatePublicWorkspaceDialog({
    submitting, serverError, singular, lowerSingular, onSubmit, onClose,
}: {
    submitting: boolean;
    serverError: string;
    singular: string;
    lowerSingular: string;
    onSubmit: (name: string, description: string) => void;
    onClose: () => void;
}) {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [clientError, setClientError] = useState('');

    const submit = () => {
        if (!name.trim()) {
            setClientError(`Enter a ${lowerSingular} name.`);
            return;
        }
        setClientError('');
        onSubmit(name.trim(), description.trim());
    };

    const error = clientError || serverError;
    return (
        <Modal title={`Create a ${lowerSingular}`}
            description={`You will own the new ${lowerSingular} and can invite members afterwards.`}
            onClose={submitting ? () => undefined : onClose}
            footer={(
                <>
                    <GlassButton size="sm" disabled={submitting} onClick={onClose}>Cancel</GlassButton>
                    <GlassButton size="sm" variant="primary" disabled={submitting} onClick={submit}>
                        {submitting ? <Loader2 size={14} className="animate-spin" /> : null}Create {lowerSingular}
                    </GlassButton>
                </>
            )}>
            <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); submit(); }}>
                <label className="block space-y-1 text-xs text-text-2">
                    <span>{singular} name</span>
                    <input className={INPUT_CLASS} value={name} disabled={submitting} autoFocus
                        aria-label={`${singular} name`}
                        onChange={(event) => { setName(event.target.value); setClientError(''); }} />
                </label>
                <label className="block space-y-1 text-xs text-text-2">
                    <span>Description <span className="text-text-3">(optional)</span></span>
                    <textarea className={`${INPUT_CLASS} min-h-20 resize-y`} value={description} disabled={submitting}
                        aria-label={`${singular} description`}
                        onChange={(event) => { setDescription(event.target.value); setClientError(''); }} />
                </label>
                {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
            </form>
        </Modal>
    );
}
