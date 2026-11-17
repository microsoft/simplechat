// FileSyncTargetManager.tsx
// Set up File Sync sources for a user, a group or a public workspace, from Admin Settings.
//
// The classic File Sync card has a block for each kind of workspace: search for who to act for,
// or paste their ID, then open that target's sources. This is the same three blocks. Choosing a
// target opens the file sources workbench a workspace's own manager uses, over the administrator
// routes that name the target, so the editor, the connection test, folder browsing, Sync now,
// run history and deletion behave exactly as they do there.
//
// It acts on the saved settings, because the server decides from those which kinds of workspace
// may use File Sync, and it writes through its own routes rather than the page's Save: a source
// is a record, not a setting. A kind of workspace whose switch is off, or is on only in the
// unsaved draft, says so instead of offering a manager the server would refuse.

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, Check, FolderSync, Loader2, Search } from 'lucide-react';
import {
    ADMIN_FILE_SYNC_SCOPES,
    createAdminFileSourceWorkbench,
    describeCandidate,
    searchTargets,
    targetIdFrom,
    targetSearchQuery,
    unavailableReason,
    type AdminFileSyncScopeInfo,
    type AdminFileSyncTarget,
    type FileSyncAvailability,
    type FileSyncTargetCandidate,
} from '../../lib/adminFileSyncTargets';
import { FileSourcesWorkbenchSection } from '../../pages/workspace/GroupFileSourcesSection';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import { inputClass } from './fields';
import { ReadoutRow } from './ReadoutRow';

type SearchState =
    | { phase: 'idle' }
    | { phase: 'hint'; message: string }
    | { phase: 'searching' }
    | { phase: 'results'; items: FileSyncTargetCandidate[] }
    | { phase: 'error'; message: string };

function TargetPicker({
    info,
    reason,
    onManage,
}: {
    info: AdminFileSyncScopeInfo;
    reason: string | null;
    onManage: (target: AdminFileSyncTarget) => void;
}) {
    const headingId = useId();
    const queryId = useId();
    const idInputId = useId();
    const selectionId = useId();
    const idErrorId = useId();
    const requestRef = useRef<AbortController | null>(null);

    const [query, setQuery] = useState('');
    const [search, setSearch] = useState<SearchState>({ phase: 'idle' });
    const [targetId, setTargetId] = useState('');
    const [targetLabel, setTargetLabel] = useState('');
    const [idError, setIdError] = useState<string | null>(null);

    useEffect(() => () => requestRef.current?.abort(), []);

    const unavailable = reason !== null;

    const runSearch = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const parsed = targetSearchQuery(query);
        if ('error' in parsed) {
            setSearch({ phase: 'hint', message: parsed.error });
            return;
        }
        // A newer search replaces an older one still in flight, so a slow answer cannot
        // overwrite the matches for what was typed last.
        requestRef.current?.abort();
        const controller = new AbortController();
        requestRef.current = controller;
        setSearch({ phase: 'searching' });
        try {
            const items = await searchTargets(info.scope, parsed.query, controller.signal);
            if (!controller.signal.aborted) {
                setSearch({ phase: 'results', items });
            }
        } catch (cause) {
            if (!controller.signal.aborted) {
                setSearch({
                    phase: 'error',
                    message: cause instanceof Error ? cause.message : 'The search could not be completed.',
                });
            }
        }
    };

    const choose = (candidate: FileSyncTargetCandidate) => {
        setTargetId(candidate.id);
        setTargetLabel(describeCandidate(candidate));
        setIdError(null);
    };

    const manage = () => {
        const parsed = targetIdFrom(targetId);
        if ('error' in parsed) {
            setIdError(parsed.error);
            return;
        }
        setIdError(null);
        onManage({ scope: info.scope, id: parsed.id, label: targetLabel || parsed.id });
    };

    const selection = !targetId.trim()
        ? `No ${info.noun} selected.`
        : targetLabel ? `Selected: ${targetLabel}` : `Target ID: ${targetId.trim()}`;

    return (
        <section
            aria-labelledby={headingId}
            className="min-w-0 rounded-xl border border-edge bg-surface-1 p-3"
        >
            <h4 id={headingId} className="text-sm font-semibold text-text-1">{info.heading}</h4>
            {reason ? <p className="mt-1 text-xs text-text-3">{reason}</p> : null}

            <form onSubmit={(event) => void runSearch(event)} className="mt-2 flex flex-wrap items-end gap-2">
                <div className="min-w-0 flex-1 basis-40">
                    <label htmlFor={queryId} className="mb-1 block text-xs text-text-2">{info.searchLabel}</label>
                    <input
                        id={queryId}
                        type="search"
                        value={query}
                        disabled={unavailable}
                        placeholder={info.searchPlaceholder}
                        autoComplete="off"
                        onChange={(event) => setQuery(event.target.value)}
                        className={inputClass}
                    />
                </div>
                <GlassButton type="submit" size="sm" variant="subtle" disabled={unavailable || search.phase === 'searching'}>
                    {search.phase === 'searching'
                        ? <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                        : <Search size={14} aria-hidden="true" />}
                    Search
                </GlassButton>
            </form>

            <div className="mt-2 text-xs" aria-live="polite">
                {search.phase === 'hint' ? <p className="text-text-3">{search.message}</p> : null}
                {search.phase === 'searching' ? <p className="text-text-3">Searching…</p> : null}
                {search.phase === 'results' && search.items.length === 0 ? (
                    <p className="text-text-3">No matching {info.noun}s found. You can still paste an ID below.</p>
                ) : null}
                {search.phase === 'results' && search.items.length > 0 ? (
                    <p className="text-text-3">
                        {search.items.length} match{search.items.length === 1 ? '' : 'es'}. Choose one.
                    </p>
                ) : null}
            </div>
            {search.phase === 'error' ? (
                <p role="alert" className="mt-1 flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {search.message}
                </p>
            ) : null}
            {search.phase === 'results' && search.items.length > 0 ? (
                <ul aria-label={`Matching ${info.noun}s`} className="mt-1 max-h-52 space-y-1 overflow-y-auto">
                    {search.items.map((candidate) => {
                        const chosen = candidate.id === targetId.trim();
                        return (
                            <li key={candidate.id}>
                                <button
                                    type="button"
                                    aria-pressed={chosen}
                                    onClick={() => choose(candidate)}
                                    className={clsx(
                                        'flex w-full items-start gap-2 rounded-lg border px-2.5 py-1.5 text-left',
                                        'transition-colors hover:bg-surface-2',
                                        chosen ? 'border-accent bg-accent/5' : 'border-edge',
                                    )}
                                >
                                    <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                                        <span className="block text-sm font-medium text-text-1">{candidate.title}</span>
                                        <span className="block text-xs text-text-3">{candidate.subtitle || candidate.id}</span>
                                    </span>
                                    {chosen ? <Check size={14} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" /> : null}
                                </button>
                            </li>
                        );
                    })}
                </ul>
            ) : null}

            <div className="mt-3">
                <label htmlFor={idInputId} className="mb-1 block text-xs text-text-2">{info.idLabel}</label>
                <div className="flex flex-wrap gap-2">
                    <input
                        id={idInputId}
                        type="text"
                        value={targetId}
                        disabled={unavailable}
                        autoComplete="off"
                        spellCheck={false}
                        aria-invalid={idError ? true : undefined}
                        aria-describedby={clsx(selectionId, idError && idErrorId)}
                        onChange={(event) => {
                            setTargetId(event.target.value);
                            setTargetLabel('');
                            setIdError(null);
                        }}
                        className={clsx(inputClass, 'min-w-0 flex-1 basis-40', idError && 'border-danger')}
                    />
                    <GlassButton
                        type="button"
                        size="sm"
                        variant="primary"
                        disabled={unavailable || !targetId.trim()}
                        onClick={manage}
                    >
                        <FolderSync size={14} aria-hidden="true" />
                        Manage sources
                    </GlassButton>
                </div>
                <p id={selectionId} className="mt-1 text-xs text-text-3 [overflow-wrap:anywhere]" aria-live="polite">
                    {selection}
                </p>
                {idError ? (
                    <p id={idErrorId} role="alert" className="mt-1 flex items-start gap-1.5 text-xs text-danger">
                        <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                        {idError}
                    </p>
                ) : null}
            </div>
        </section>
    );
}

export function FileSyncTargetManager({
    label,
    help,
    availability,
}: {
    label: string;
    help?: string;
    availability: FileSyncAvailability;
}) {
    const [target, setTarget] = useState<AdminFileSyncTarget | null>(null);
    const adapter = useMemo(() => (target ? createAdminFileSourceWorkbench(target) : null), [target]);
    const targetInfo = target ? ADMIN_FILE_SYNC_SCOPES.find((entry) => entry.scope === target.scope) : undefined;

    return (
        <ReadoutRow label={label} help={help} width="full">
            <div className="grid gap-3 lg:grid-cols-3">
                {ADMIN_FILE_SYNC_SCOPES.map((info) => (
                    <TargetPicker
                        key={info.scope}
                        info={info}
                        reason={unavailableReason(info.scope, availability)}
                        onManage={setTarget}
                    />
                ))}
            </div>

            {target && adapter && targetInfo ? (
                <Modal
                    title={`Manage ${targetInfo.noun} sync sources`}
                    description={target.label === target.id ? target.id : `${target.label} (${target.id})`}
                    size="xl"
                    onClose={() => setTarget(null)}
                >
                    <div className="space-y-4">
                        <p className="text-xs text-text-3">
                            Listing and adding sources works for any {targetInfo.noun}. Changing, syncing, testing or
                            deleting a saved source follows the workspace&rsquo;s own role checks, so the server can
                            refuse it for a workspace you do not manage or for another user&rsquo;s personal source.
                            Its reason is shown when it does.
                        </p>
                        <FileSourcesWorkbenchSection
                            key={`${target.scope}:${target.id}`}
                            adapter={adapter}
                            scopeNoun={targetInfo.sectionNoun}
                            documentsLink={null}
                            pathIgnoring={false}
                        />
                    </div>
                </Modal>
            ) : null}
        </ReadoutRow>
    );
}
