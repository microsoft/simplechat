// AddMemberDialog.tsx
// Add one person to a group: find them in the directory, choose their role, add them.
//
// The search goes through `/api/userSearch`, the people search the classic manage page uses,
// with the caller's own delegated directory access. The server then resolves the chosen person
// by id itself, so the name and email sent with the add are only its fallback for when the
// directory can't be reached. A refusal about the chosen person keeps the dialog open with the
// server's message so another person can be chosen; the page closes it for a refusal that means
// no one can be added here any more.

import { useEffect, useRef, useState } from 'react';
import { Loader2, Search, UserPlus } from 'lucide-react';
import { clsx } from 'clsx';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import {
    ASSIGNABLE_ROLE_OPTIONS, memberDisplayName, membershipErrorMessage, searchDirectoryUsers,
    type AssignableMemberRole, type DirectoryUser,
} from '../../lib/groupMembership';

const INPUT_CLASS = 'w-full min-w-0 rounded-xl border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60';
const SEARCH_DELAY_MS = 300;

function directoryName(user: DirectoryUser): string {
    return memberDisplayName({ displayName: user.displayName, email: user.email, userId: user.id });
}

export function AddMemberDialog({
    submitting, serverError, onSubmit, onClose, roleOptions = ASSIGNABLE_ROLE_OPTIONS, defaultRole = 'User',
}: {
    submitting: boolean;
    serverError: string;
    onSubmit: (user: DirectoryUser, role: AssignableMemberRole) => void;
    onClose: () => void;
    /** The assignable roles offered, defaulting to the group's (User, Document manager, Admin). */
    roleOptions?: readonly { value: AssignableMemberRole; label: string }[];
    /** The role selected first, defaulting to the group's plain User. */
    defaultRole?: AssignableMemberRole;
}) {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<DirectoryUser[]>([]);
    const [searching, setSearching] = useState(false);
    const [searched, setSearched] = useState('');
    const [searchError, setSearchError] = useState('');
    const [selected, setSelected] = useState<DirectoryUser | null>(null);
    const [role, setRole] = useState<AssignableMemberRole>(defaultRole);
    const controller = useRef<AbortController | null>(null);

    // A debounced search. Each new term aborts the one before it, so a slow earlier answer can
    // never replace the results for what is typed now.
    useEffect(() => {
        const term = query.trim();
        controller.current?.abort();
        if (!term) {
            setResults([]);
            setSearching(false);
            setSearched('');
            setSearchError('');
            return undefined;
        }
        const handle = window.setTimeout(() => {
            const current = new AbortController();
            controller.current = current;
            setSearching(true);
            setSearchError('');
            void searchDirectoryUsers(term, current.signal).then((users) => {
                if (current.signal.aborted) return;
                setResults(users);
                setSearched(term);
            }).catch((cause: unknown) => {
                if (current.signal.aborted) return;
                setResults([]);
                setSearched('');
                setSearchError(`The directory search isn't available: ${membershipErrorMessage(cause, 'the request could not be completed.')}`);
            }).finally(() => {
                if (!current.signal.aborted) setSearching(false);
            });
        }, SEARCH_DELAY_MS);
        return () => window.clearTimeout(handle);
    }, [query]);

    useEffect(() => () => controller.current?.abort(), []);

    const submit = () => {
        if (selected && !submitting) onSubmit(selected, role);
    };

    return (
        <Modal title="Add a member" description="Find someone in your organization's directory, then choose their role."
            size="lg" onClose={submitting ? () => undefined : onClose}
            footer={(
                <>
                    <GlassButton size="sm" disabled={submitting} onClick={onClose}>Cancel</GlassButton>
                    <GlassButton size="sm" variant="primary" disabled={submitting || !selected} onClick={submit}>
                        {submitting ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />}Add member
                    </GlassButton>
                </>
            )}>
            <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); submit(); }}>
                <label className="block space-y-1 text-xs text-text-2">
                    <span>Search the directory</span>
                    <span className="relative block">
                        <Search size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3" />
                        <input type="search" className={clsx(INPUT_CLASS, 'pl-9')} value={query} disabled={submitting} autoFocus
                            aria-label="Search the directory" placeholder="Search by name or email"
                            onChange={(event) => setQuery(event.target.value)} />
                    </span>
                </label>
                <div aria-live="polite" className="min-h-5 text-xs text-text-3">
                    {searching ? <span className="inline-flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" />Searching the directory...</span>
                        : searchError ? <span role="alert" className="text-danger">{searchError}</span>
                            : searched && results.length === 0 ? <span>No one in the directory matches that search.</span> : null}
                </div>
                {results.length ? (
                    <ul aria-label="Directory results" className="max-h-60 space-y-1 overflow-y-auto">
                        {results.map((user) => {
                            const name = directoryName(user);
                            const active = selected?.id === user.id;
                            return (
                                <li key={user.id}>
                                    <button type="button" aria-pressed={active} aria-label={`Choose ${name}`} disabled={submitting}
                                        onClick={() => setSelected(user)}
                                        className={clsx(
                                            'flex w-full min-w-0 flex-col items-start rounded-xl border px-3 py-2 text-left transition-colors disabled:opacity-60',
                                            active ? 'border-accent bg-accent-soft' : 'border-edge hover:bg-surface-2',
                                        )}>
                                        <span className="max-w-full break-words text-sm font-medium text-text-1">{name}</span>
                                        {user.email ? <span className="max-w-full break-all text-xs text-text-3">{user.email}</span> : null}
                                    </button>
                                </li>
                            );
                        })}
                    </ul>
                ) : null}
                {selected ? (
                    <p className="break-words text-xs text-text-2">
                        Adding <span className="font-medium text-text-1">{directoryName(selected)}</span>
                    </p>
                ) : null}
                <label className="block space-y-1 text-xs text-text-2">
                    <span>Role</span>
                    <select className={INPUT_CLASS} value={role} disabled={submitting}
                        aria-label="Role for the new member" onChange={(event) => setRole(event.target.value as AssignableMemberRole)}>
                        {roleOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                </label>
                {serverError ? <p role="alert" className="text-sm text-danger">{serverError}</p> : null}
            </form>
        </Modal>
    );
}
