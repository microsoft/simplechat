// CreateGroupDialog.tsx
// The create-a-group form on the directory page.
//
// The dialog mirrors the server's create rules so a name it would refuse is caught before the
// request, but it never invents a rule the server does not enforce: the field limits and the
// messages here match `read_group_creation_fields`. A server refusal (a reviewed 400, or a 403
// when creation is not allowed) is shown verbatim and the draft is kept, because retyping a
// valid name only to lose it to a policy answer reads as the form eating the work.

import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';

const NAME_MAX_LENGTH = 80;
const DESCRIPTION_MAX_LENGTH = 500;
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f-\u009f]/;

const INPUT_CLASS = 'w-full min-w-0 rounded-xl border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60';

function validate(name: string, description: string): string | null {
    const trimmedName = name.trim();
    if (!trimmedName) return 'Enter a group name.';
    if (trimmedName.length > NAME_MAX_LENGTH) return `Group names can be at most ${NAME_MAX_LENGTH} characters.`;
    if (CONTROL_CHARACTERS.test(trimmedName)) return 'Group names cannot contain control characters.';
    if (description.trim().length > DESCRIPTION_MAX_LENGTH) {
        return `Group descriptions can be at most ${DESCRIPTION_MAX_LENGTH} characters.`;
    }
    return null;
}

export function CreateGroupDialog({
    submitting, serverError, onSubmit, onClose,
}: {
    submitting: boolean;
    serverError: string;
    onSubmit: (name: string, description: string) => void;
    onClose: () => void;
}) {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [clientError, setClientError] = useState('');

    const submit = () => {
        const problem = validate(name, description);
        if (problem) {
            setClientError(problem);
            return;
        }
        setClientError('');
        onSubmit(name.trim(), description.trim());
    };

    const error = clientError || serverError;
    return (
        <Modal title="Create a group" description="You will own the new group and can invite members afterwards."
            onClose={submitting ? () => undefined : onClose}
            footer={(
                <>
                    <GlassButton size="sm" disabled={submitting} onClick={onClose}>Cancel</GlassButton>
                    <GlassButton size="sm" variant="primary" disabled={submitting} onClick={submit}>
                        {submitting ? <Loader2 size={14} className="animate-spin" /> : null}Create group
                    </GlassButton>
                </>
            )}>
            <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); submit(); }}>
                <label className="block space-y-1 text-xs text-text-2">
                    <span>Group name</span>
                    <input className={INPUT_CLASS} value={name} disabled={submitting} autoFocus
                        maxLength={NAME_MAX_LENGTH} aria-label="Group name"
                        onChange={(event) => { setName(event.target.value); setClientError(''); }} />
                </label>
                <label className="block space-y-1 text-xs text-text-2">
                    <span>Description <span className="text-text-3">(optional)</span></span>
                    <textarea className={`${INPUT_CLASS} min-h-20 resize-y`} value={description} disabled={submitting}
                        maxLength={DESCRIPTION_MAX_LENGTH} aria-label="Group description"
                        onChange={(event) => { setDescription(event.target.value); setClientError(''); }} />
                </label>
                {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
            </form>
        </Modal>
    );
}
