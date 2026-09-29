// WorkflowChangeTracking.tsx
// Change tracking in the workflow editor: highlights for unsaved changes with their author, the
// value before, and a Revert; Removed · Restore rows; and the side panel with the Changes tab.
//
// Everything here is derived from the authoring session: the opened baseline, the draft, and the
// attribution its history keeps. Reverts and restores are new history entries, so Undo and Redo
// stay the editor's only undo stack. Every value renders as a plain-text React node.

import {
    createContext, useContext, useDeferredValue, useEffect, useId, useMemo, useRef, useState, useSyncExternalStore,
    type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type RefObject,
} from 'react';
import { clsx } from 'clsx';
import { AlertTriangle, ArrowRight, FileDiff, PenLine, RotateCcw, Sparkles } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import {
    diffWorkflowChanges, workflowChangeAuthors, workflowChangeItemKey, workflowRunAsConsequence, workflowSaveNeedsConfirmation,
    WORKFLOW_REFERENCE_ORDER_KEY,
    type WorkflowAttribution, type WorkflowChange, type WorkflowChangeAuthor, type WorkflowChangeStamp,
} from '../../lib/workflowChangeTracking';
import type { WorkflowAuthoringSession, WorkflowSessionStep } from './WorkflowAuthoringHistory';

type SessionSnapshot = ReturnType<WorkflowAuthoringSession['getSnapshot']>;

/** What the editor shows about unsaved changes. Null while the editor is read-only. */
export interface WorkflowChangeTracking {
    readonly changes: readonly WorkflowChange[];
    readonly byKey: ReadonlyMap<string, WorkflowChange>;
    /** Every shown added item key, mapped to the outermost added change that contains it. */
    readonly added: ReadonlyMap<string, string>;
    /** Field, order, and placement changes, grouped by the task, block, or reference they belong to. */
    readonly byItem: ReadonlyMap<string, readonly WorkflowChange[]>;
    readonly attribution: WorkflowAttribution;
    /** The draft changed format, so its changes can only be discarded together. */
    readonly converted: boolean;
    /** Saving changes what the Run as account approved, so it has to be approved again. */
    readonly runAsConsequence: boolean;
    /** The workflow has never been saved, so only AI assist changes are pointed out. */
    readonly isNew: boolean;
    readonly steps: readonly WorkflowSessionStep[];
    readonly trimmed: boolean;
    readonly session: WorkflowAuthoringSession;
}

const WorkflowChangeContext = createContext<WorkflowChangeTracking | null>(null);

export function useWorkflowChanges(): WorkflowChangeTracking | null {
    return useContext(WorkflowChangeContext);
}

function aiAuthored(change: WorkflowChange, attribution: WorkflowAttribution): boolean {
    return workflowChangeAuthors(change, attribution).some((stamp) => stamp.author === 'ai');
}

function buildTracking(session: WorkflowAuthoringSession, snapshot: SessionSnapshot): WorkflowChangeTracking {
    const all = diffWorkflowChanges(snapshot.baseline, snapshot.draft);
    const attribution = snapshot.attribution;
    const isNew = !snapshot.baseline.id;
    // Everything in a new workflow is unsaved, so highlighting it all would point out nothing.
    const changes = isNew ? all.changes.filter((change) => aiAuthored(change, attribution)) : all.changes;
    const byKey = isNew ? new Map(changes.map((change) => [change.key, change])) : all.byKey;
    const added = isNew ? new Map([...all.added].filter(([, root]) => byKey.has(root))) : all.added;
    const byItem = new Map<string, WorkflowChange[]>();
    for (const change of changes) {
        if (change.kind === 'added' || change.kind === 'removed') continue;
        const itemKey = workflowChangeItemKey(change.key);
        if (!itemKey) continue;
        const list = byItem.get(itemKey);
        if (list) list.push(change);
        else byItem.set(itemKey, [change]);
    }
    return {
        changes, byKey, added, byItem, attribution, converted: all.converted,
        runAsConsequence: workflowRunAsConsequence(snapshot.baseline, snapshot.draft, all.changes),
        isNew, steps: snapshot.steps, trimmed: snapshot.trimmed, session,
    };
}

/**
 * Provides change tracking to everything inside it. The diff follows the draft one deferred render
 * later, so a keystroke never waits for it, and only the components that read it re-render then.
 */
export function WorkflowChangeTrackingScope({ session, enabled, children }: {
    session: WorkflowAuthoringSession;
    enabled: boolean;
    children: ReactNode;
}) {
    const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot);
    const deferred = useDeferredValue(snapshot);
    const value = useMemo(() => (enabled ? buildTracking(session, deferred) : null), [session, deferred, enabled]);
    return <WorkflowChangeContext.Provider value={value}>{children}</WorkflowChangeContext.Provider>;
}

/** Whether saving the session's current draft needs the Confirm and save step. */
export function workflowSessionSaveNeedsConfirmation(session: WorkflowAuthoringSession): boolean {
    const snapshot = session.getSnapshot();
    if (!snapshot.attribution.size) return false;
    return workflowSaveNeedsConfirmation(diffWorkflowChanges(snapshot.baseline, snapshot.draft).changes, snapshot.attribution);
}

// ---------------------------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------------------------

const PREVIOUS_CLIP = 280;
const SUMMARY_CLIP = 160;

// Literal class names, so Tailwind generates them.
const BADGE_CLASS: Record<WorkflowChangeAuthor, string> = {
    user: 'bg-change-user-soft text-change-user',
    ai: 'bg-change-ai-soft text-change-ai',
};
const FRAME_CLASS: Record<WorkflowChangeAuthor, string> = {
    user: 'border-change-user/50 bg-change-user-soft',
    ai: 'border-change-ai/50 bg-change-ai-soft',
};
const DASHED_CLASS: Record<WorkflowChangeAuthor, string> = {
    user: 'border-change-user/60',
    ai: 'border-change-ai/60',
};

function authorName(author: WorkflowChangeAuthor): string {
    return author === 'ai' ? 'AI assist' : 'you';
}

function authorBadgeText(author: WorkflowChangeAuthor, added = false): string {
    if (added) return author === 'ai' ? 'Added · AI assist' : 'Added · by you';
    return author === 'ai' ? 'AI assist' : 'Edited';
}

function WorkflowChangeBadge({ author, added = false, id }: { author: WorkflowChangeAuthor; added?: boolean; id?: string }) {
    const Icon = author === 'ai' ? Sparkles : PenLine;
    return (
        <span id={id} data-workflow-change-author={author}
            className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold', BADGE_CLASS[author])}>
            <Icon size={12} aria-hidden="true" className="shrink-0" />
            {authorBadgeText(author, added)}
        </span>
    );
}

const FIELD_CONTROL = 'input:not(:disabled):not([type="hidden"]), textarea:not(:disabled), select:not(:disabled)';

/** Focus an element that takes focus itself, or the first field inside it, or its first button. */
export function focusWorkflowChangeTarget(element: HTMLElement | null | undefined): boolean {
    if (!element?.isConnected) return false;
    const target = element.hasAttribute('tabindex') ? element
        : element.querySelector<HTMLElement>(FIELD_CONTROL) ?? element.querySelector<HTMLElement>('button:not(:disabled)');
    if (!target) return false;
    target.focus({ preventScroll: true });
    target.scrollIntoView?.({ block: 'nearest' });
    return document.activeElement === target;
}

/** The plain-text value a field had when the editor opened, behind a Previously toggle. */
function WorkflowPreviousValue({ id, value }: { id: string; value: string }) {
    const [expanded, setExpanded] = useState(false);
    const long = value.length > PREVIOUS_CLIP;
    const shown = long && !expanded ? `${value.slice(0, PREVIOUS_CLIP).trimEnd()}…` : value;
    return (
        <div id={id} className="mt-2 rounded-md bg-surface-sunken p-2 text-xs text-text-2">
            <p className="whitespace-pre-wrap break-words">{shown}</p>
            {long ? (
                <button type="button" aria-expanded={expanded} onClick={() => setExpanded((open) => !open)}
                    className="mt-1 text-xs font-medium text-accent hover:underline">
                    {expanded ? 'Show less' : 'Show more'}
                </button>
            ) : null}
        </div>
    );
}

function PreviouslyToggle({ open, controls, onToggle }: { open: boolean; controls: string; onToggle: () => void }) {
    return (
        <button type="button" aria-expanded={open} aria-controls={open ? controls : undefined} onClick={onToggle}
            className="rounded-md px-1.5 py-0.5 text-xs font-medium text-text-2 hover:bg-surface-2 hover:text-text-1">
            Previously
        </button>
    );
}

// ---------------------------------------------------------------------------------------------
// Inline highlights
// ---------------------------------------------------------------------------------------------

function isFieldChange(change: WorkflowChange | undefined): change is WorkflowChange {
    return Boolean(change && change.kind !== 'added' && change.kind !== 'removed');
}

/** The author of a field inside an added item: its own last author, else whoever added the item. */
function addedFieldStamp(tracking: WorkflowChangeTracking, key: string, itemKey: string, root: string): WorkflowChangeStamp {
    const rootChange = tracking.byKey.get(root);
    return tracking.attribution.get(key) ?? tracking.attribution.get(itemKey) ?? tracking.attribution.get(root)
        ?? (rootChange ? workflowChangeAuthors(rootChange, tracking.attribution)[0] : { author: 'user', origin: 'user' });
}

/** Focus the first control that remains after a highlight goes away. */
function refocusAfterRevert(root: RefObject<HTMLElement | null>, fallback?: HTMLElement | null) {
    requestAnimationFrame(() => {
        if (focusWorkflowChangeTarget(root.current)) return;
        focusWorkflowChangeTarget(fallback);
    });
}

/**
 * Highlights one field with an unsaved change: a frame in the author's color, a text badge naming
 * the author, the value the field had when the editor opened, and its own Revert. A field inside a
 * newly added task or block shows only its author; the whole item is reverted from its header.
 *
 * The highlight never changes the element tree around the field. The same block element holds the
 * children in the same place whether it is highlighted or not; only its attributes change, and the
 * controls are appended after the children. Otherwise children with several controls, such as the
 * schedule, would remount and lose focus, mid-typing, as their highlight appears or goes.
 */
export function WorkflowChangedField({ changeKey, className, children }: {
    changeKey: string;
    className?: string;
    children?: ReactNode;
}) {
    const tracking = useWorkflowChanges();
    const rootRef = useRef<HTMLDivElement>(null);
    const baseId = useId();
    const [open, setOpen] = useState(false);
    const change = tracking?.byKey.get(changeKey);
    const itemKey = workflowChangeItemKey(changeKey);
    const addedRoot = tracking && itemKey && !change ? tracking.added.get(itemKey) : undefined;
    const fieldChange = isFieldChange(change) ? change : undefined;
    useEffect(() => {
        if (!fieldChange) setOpen(false);
    }, [fieldChange]);
    if (children === null || children === undefined || children === false) return null;

    const stamp = !tracking ? undefined
        : fieldChange ? workflowChangeAuthors(fieldChange, tracking.attribution)[0]
            : addedRoot ? addedFieldStamp(tracking, changeKey, itemKey ?? changeKey, addedRoot) : undefined;
    const badgeId = `${baseId}-badge`;
    const noteId = `${baseId}-note`;
    const previousId = `${baseId}-previous`;
    const revert = () => {
        if (!tracking || !fieldChange) return;
        const result = tracking.session.revertChange([fieldChange.key]);
        if (result.status === 'applied') refocusAfterRevert(rootRef);
    };
    return (
        <div ref={rootRef} role={stamp ? 'group' : undefined} aria-labelledby={stamp ? badgeId : undefined}
            data-workflow-change-key={stamp ? changeKey : undefined}
            className={clsx(className, stamp && ['rounded-lg border p-2', FRAME_CLASS[stamp.author]]) || undefined}>
            {children}
            {stamp ? (
                <div className="mt-2" data-workflow-history-controls>
                    <div className="flex flex-wrap items-center gap-2">
                        <WorkflowChangeBadge id={badgeId} author={stamp.author} />
                        <span id={noteId} className="sr-only">
                            {fieldChange ? `Changed by ${authorName(stamp.author)}.` : `Added by ${authorName(stamp.author)}.`}
                        </span>
                        {fieldChange?.revertable ? (
                            <GlassButton type="button" size="sm" variant="subtle" className="h-7 gap-1 px-2 text-xs"
                                aria-describedby={noteId} onClick={revert}>
                                <RotateCcw size={12} aria-hidden="true" /> Revert
                            </GlassButton>
                        ) : null}
                        {fieldChange ? <PreviouslyToggle open={open} controls={previousId} onToggle={() => setOpen((value) => !value)} /> : null}
                    </div>
                    {fieldChange && open ? <WorkflowPreviousValue id={previousId} value={fieldChange.before} /> : null}
                </div>
            ) : null}
        </div>
    );
}

/**
 * A compact highlight for a change that has no single field to frame, such as a block order, a
 * placement, or a block setting edited in its own panel.
 */
export function WorkflowChangeNotice({ changeKey, withOwner = false, className }: {
    changeKey: string;
    /** Name the task, block, or reference too, for a notice listed away from it. */
    withOwner?: boolean;
    className?: string;
}) {
    const tracking = useWorkflowChanges();
    const rootRef = useRef<HTMLDivElement>(null);
    const baseId = useId();
    const [open, setOpen] = useState(false);
    const change = tracking?.byKey.get(changeKey);
    if (!tracking || !isFieldChange(change)) return null;
    const stamp = workflowChangeAuthors(change, tracking.attribution)[0];
    const badgeId = `${baseId}-badge`;
    const noteId = `${baseId}-note`;
    const previousId = `${baseId}-previous`;
    const revert = () => {
        const fallback = rootRef.current?.parentElement?.closest<HTMLElement>('[data-workflow-change-item], section, fieldset');
        const result = tracking.session.revertChange([change.key]);
        if (result.status === 'applied') refocusAfterRevert({ current: null }, fallback);
    };
    return (
        <div ref={rootRef} role="group" aria-labelledby={badgeId} data-workflow-change-key={changeKey} tabIndex={-1}
            data-workflow-history-controls
            className={clsx(className, 'rounded-lg border p-2 text-xs', FRAME_CLASS[stamp.author])}>
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-text-1">
                    {withOwner && change.owner.kind !== 'workflow' ? `${change.ownerLabel} · ${change.label} changed` : `${change.label} changed`}
                </span>
                <WorkflowChangeBadge id={badgeId} author={stamp.author} />
                <span id={noteId} className="sr-only">{`Changed by ${authorName(stamp.author)}.`}</span>
                {change.revertable ? (
                    <GlassButton type="button" size="sm" variant="subtle" className="h-7 gap-1 px-2 text-xs"
                        aria-describedby={noteId} onClick={revert}>
                        <RotateCcw size={12} aria-hidden="true" /> Revert
                    </GlassButton>
                ) : null}
                <PreviouslyToggle open={open} controls={previousId} onToggle={() => setOpen((value) => !value)} />
            </div>
            {open ? <WorkflowPreviousValue id={previousId} value={change.before} /> : null}
        </div>
    );
}

const USER_STAMP: WorkflowChangeStamp = { author: 'user', origin: 'user' };

/**
 * Where focus can go when an item goes away: the next item, the previous one, then the section
 * around them, widening one section at a time. Candidates that go away with the item are skipped.
 */
function itemFocusFallbacks(element: HTMLElement | null): HTMLElement[] {
    const item = element?.closest<HTMLElement>('[data-workflow-change-item]') ?? element;
    const result: HTMLElement[] = [];
    if (!item) return result;
    const outer = (node: HTMLElement) => node.parentElement?.closest<HTMLElement>('fieldset, section') ?? null;
    for (let scope = outer(item); scope; scope = outer(scope)) {
        const items = [...scope.querySelectorAll<HTMLElement>('[data-workflow-change-item]')]
            .filter((other) => other === item || !item.contains(other) && !other.contains(item));
        const index = items.indexOf(item);
        for (const candidate of [items[index + 1], items[index - 1], scope]) if (candidate) result.push(candidate);
    }
    return result;
}

function focusFirstOf(candidates: readonly HTMLElement[]) {
    requestAnimationFrame(() => {
        candidates.some((candidate) => focusWorkflowChangeTarget(candidate));
    });
}

/**
 * The change marker in a task's or block's header. A newly added item says so, and the outermost
 * one offers Revert, which removes it. An edited item shows its authors, plus a notice for each
 * change its view does not frame inline (`unframed`: field names, or 'all').
 */
export function WorkflowItemChangeBadge({ itemKey, unframed, className }: {
    itemKey: string;
    unframed?: 'all' | readonly string[];
    className?: string;
}) {
    const tracking = useWorkflowChanges();
    const rootRef = useRef<HTMLDivElement>(null);
    const baseId = useId();
    if (!tracking) return null;
    const addedRoot = tracking.added.get(itemKey);
    if (addedRoot) {
        const outermost = addedRoot === itemKey;
        const rootChange = tracking.byKey.get(addedRoot);
        const stamp = tracking.attribution.get(itemKey)
            ?? (rootChange ? workflowChangeAuthors(rootChange, tracking.attribution)[0] : USER_STAMP);
        const noteId = `${baseId}-note`;
        const revert = () => {
            const fallbacks = itemFocusFallbacks(rootRef.current);
            const result = tracking.session.revertChange([itemKey]);
            if (result.status === 'applied') focusFirstOf(fallbacks);
        };
        return (
            <div ref={rootRef} data-workflow-history-controls
                {...(outermost ? { 'data-workflow-change-key': itemKey, tabIndex: -1 } : {})}
                className={clsx(className, 'flex flex-wrap items-center gap-2 rounded-lg')}>
                <WorkflowChangeBadge author={stamp.author} added />
                <span id={noteId} className="sr-only">
                    {outermost ? `Added by ${authorName(stamp.author)}. Not saved yet.` : 'Added with the block around it.'}
                </span>
                {outermost && rootChange?.revertable ? (
                    <GlassButton type="button" size="sm" variant="subtle" className="h-7 gap-1 px-2 text-xs"
                        aria-describedby={noteId} onClick={revert}>
                        <RotateCcw size={12} aria-hidden="true" /> Revert
                    </GlassButton>
                ) : null}
            </div>
        );
    }
    const changes = tracking.byItem.get(itemKey);
    if (!changes?.length) return null;
    const stamps = new Map<string, WorkflowChangeStamp>();
    for (const change of changes) {
        for (const stamp of workflowChangeAuthors(change, tracking.attribution)) stamps.set(stamp.author, stamp);
    }
    const authors = [...stamps.values()].sort((left, right) => left.author === right.author ? 0 : left.author === 'ai' ? -1 : 1);
    const notices = changes.filter((change) => unframed === 'all'
        || Boolean(unframed?.includes(change.key.slice(itemKey.length + 1))));
    return (
        <div className={clsx(className, 'space-y-2')}>
            <div className="flex flex-wrap items-center gap-2">
                {authors.map((stamp) => <WorkflowChangeBadge key={stamp.author} author={stamp.author} />)}
                <span className="sr-only">This item has unsaved changes.</span>
            </div>
            {notices.map((change) => <WorkflowChangeNotice key={change.key} changeKey={change.key} />)}
        </div>
    );
}

/** Where Removed · Restore rows sit among the items that remain. */
export type WorkflowRemovedPlacement =
    | { readonly at: 'all' }
    | { readonly at: 'start' }
    | { readonly at: 'after'; readonly id: string }
    | { readonly at: 'end'; readonly siblings: readonly string[]; readonly root?: boolean };

export type WorkflowRemovedList = 'flow' | 'task' | 'reference';

function removedIn(change: WorkflowChange, list: WorkflowRemovedList, regionId: string, placement: WorkflowRemovedPlacement): boolean {
    if (change.kind !== 'removed') return false;
    const kind = change.owner.kind;
    const listed = list === 'reference' ? kind === 'reference' : list === 'task' ? kind === 'task' : kind === 'task' || kind === 'node';
    if (!listed) return false;
    if (placement.at === 'all') return true;
    const anchor = change.anchor;
    // Flow regions have IDs; the task and reference lists use ''. Every present flow region is shown.
    const placed = Boolean(anchor?.regionPresent) && (list === 'flow') === (anchor?.regionId !== '');
    if (anchor && placed && anchor.regionId === regionId) {
        if (placement.at === 'start') return anchor.afterId === null;
        if (placement.at === 'after') return anchor.afterId === placement.id;
        return anchor.afterId !== null && !placement.siblings.includes(anchor.afterId);
    }
    // Its region is gone, or it has no place in this view: it is listed at the end of the root.
    return placement.at === 'end' && Boolean(placement.root) && !placed;
}

/**
 * One added or removed task, block, or reference listed as a row: Removed · Restore puts a removed
 * item back where it was, and Revert takes an added one out again.
 */
function WorkflowItemRow({ change, tracking, onRestored }: {
    change: WorkflowChange;
    tracking: WorkflowChangeTracking;
    onRestored?: (change: WorkflowChange) => void;
}) {
    const rowRef = useRef<HTMLDivElement>(null);
    const baseId = useId();
    const added = change.kind === 'added';
    const authors = changeAuthors(change, tracking.attribution);
    const textId = `${baseId}-text`;
    const act = () => {
        const row = rowRef.current;
        const dialog = row?.closest<HTMLElement>('[role="dialog"]') ?? document.body;
        const fallback = row?.parentElement?.closest<HTMLElement>('fieldset, section') ?? null;
        const nearby = [row?.nextElementSibling, row?.previousElementSibling, fallback]
            .filter((element): element is HTMLElement => element instanceof HTMLElement);
        const result = tracking.session.revertChange([change.key]);
        if (result.status !== 'applied') return;
        if (added) {
            focusFirstOf(nearby);
            return;
        }
        if (onRestored) {
            onRestored(change);
            return;
        }
        requestAnimationFrame(() => {
            const item = dialog.querySelector<HTMLElement>(`[data-workflow-change-item="${CSS.escape(change.key)}"]`);
            if (!focusWorkflowChangeTarget(item)) nearby.some((candidate) => focusWorkflowChangeTarget(candidate));
        });
    };
    return (
        <div ref={rowRef} data-workflow-change-key={change.key} tabIndex={-1} data-workflow-history-controls
            className={clsx('flex flex-wrap items-center gap-2 rounded-lg border p-2',
                added ? FRAME_CLASS[authors[0].author] : ['border-dashed', DASHED_CLASS[authors[0].author]])}>
            <span id={textId} className="min-w-0 flex-1 break-words text-sm text-text-2">{`${change.label} · ${change.ownerLabel}`}</span>
            {authors.map((stamp) => <WorkflowChangeBadge key={stamp.author} author={stamp.author} added={added} />)}
            {change.revertable ? (
                <GlassButton type="button" size="sm" variant="subtle" className="h-7 gap-1 px-2 text-xs"
                    aria-describedby={textId} onClick={act}>
                    <RotateCcw size={12} aria-hidden="true" /> {added ? 'Revert' : 'Restore'}
                </GlassButton>
            ) : null}
        </div>
    );
}

/** Removed · Restore rows for the tasks, blocks, or references removed at one place in a list. */
export function WorkflowRemovedItemRows({ list, regionId = '', placement, heading, onRestored, className }: {
    list: WorkflowRemovedList;
    regionId?: string;
    placement: WorkflowRemovedPlacement;
    heading?: string;
    onRestored?: (change: WorkflowChange) => void;
    className?: string;
}) {
    const tracking = useWorkflowChanges();
    if (!tracking) return null;
    const rows = tracking.changes.filter((change) => removedIn(change, list, regionId, placement));
    if (!rows.length) return null;
    return (
        <div className={clsx(className, 'space-y-2')}>
            {heading ? <p className="text-xs font-medium text-text-2">{heading}</p> : null}
            {rows.map((change) => <WorkflowItemRow key={change.key} change={change} tracking={tracking} onRestored={onRestored} />)}
        </div>
    );
}

/**
 * Changes to the shared references, listed under the reference picker: the order, each changed
 * reference with its Revert, and added or removed references with Revert or Restore.
 */
export function WorkflowReferenceChanges({ className }: { className?: string }) {
    const tracking = useWorkflowChanges();
    if (!tracking) return null;
    const changes = tracking.changes.filter((change) => change.key === WORKFLOW_REFERENCE_ORDER_KEY || change.owner.kind === 'reference');
    if (!changes.length) return null;
    return (
        <div className={clsx(className, 'space-y-2')}>
            {changes.map((change) => change.kind === 'added' || change.kind === 'removed'
                ? <WorkflowItemRow key={change.key} change={change} tracking={tracking} />
                : <WorkflowChangeNotice key={change.key} changeKey={change.key} withOwner />)}
        </div>
    );
}

// ---------------------------------------------------------------------------------------------
// Side panel and the Changes tab
// ---------------------------------------------------------------------------------------------

/** Distinct authors of a change, AI first, one badge each. */
function changeAuthors(change: WorkflowChange, attribution: WorkflowAttribution): WorkflowChangeStamp[] {
    const byAuthor = new Map<WorkflowChangeAuthor, WorkflowChangeStamp>();
    for (const stamp of workflowChangeAuthors(change, attribution)) if (!byAuthor.has(stamp.author)) byAuthor.set(stamp.author, stamp);
    return [...byAuthor.values()];
}

function changeTitle(change: WorkflowChange): string {
    if (change.owner.kind === 'workflow') return change.label;
    if (change.kind === 'added' || change.kind === 'removed') return `${change.label} · ${change.ownerLabel}`;
    return `${change.ownerLabel} · ${change.label}`;
}

function summaryText(value: string): string {
    const text = value.replace(/\s+/g, ' ').trim();
    return text.length > SUMMARY_CLIP ? `${text.slice(0, SUMMARY_CLIP).trimEnd()}…` : text;
}

export interface WorkflowSidePanelTab {
    readonly id: string;
    readonly label: string;
    readonly content: ReactNode;
}

/**
 * The editor's side panel. It is a tab list so the Changes tab can gain siblings, such as Ask AI;
 * tabs follow the APG pattern with automatic activation.
 */
export function WorkflowEditorSidePanel({ id, tabs, className }: {
    id: string;
    tabs: readonly WorkflowSidePanelTab[];
    className?: string;
}) {
    const [selected, setSelected] = useState(tabs[0]?.id ?? '');
    const baseId = useId();
    const tabRefs = useRef(new Map<string, HTMLButtonElement>());
    const active = tabs.find((tab) => tab.id === selected) ?? tabs[0];
    const choose = (index: number) => {
        const tab = tabs[(index + tabs.length) % tabs.length];
        if (!tab) return;
        setSelected(tab.id);
        tabRefs.current.get(tab.id)?.focus();
    };
    const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
        const index = tabs.findIndex((tab) => tab.id === active?.id);
        if (event.key === 'ArrowRight') choose(index + 1);
        else if (event.key === 'ArrowLeft') choose(index - 1);
        else if (event.key === 'Home') choose(0);
        else if (event.key === 'End') choose(tabs.length - 1);
        else return;
        event.preventDefault();
    };
    return (
        <aside id={id} aria-label="Workflow editor side panel" data-workflow-history-controls
            className={clsx(className, 'flex min-h-0 flex-col')}>
            <div role="tablist" aria-label="Side panel" className="flex shrink-0 gap-1 border-b border-edge px-3 pt-2" onKeyDown={onKeyDown}>
                {tabs.map((tab) => {
                    const current = tab.id === active?.id;
                    return (
                        <button key={tab.id} type="button" role="tab" id={`${baseId}-tab-${tab.id}`}
                            ref={(element) => {
                                if (element) tabRefs.current.set(tab.id, element);
                                else tabRefs.current.delete(tab.id);
                            }}
                            aria-selected={current} aria-controls={current ? `${baseId}-panel-${tab.id}` : undefined}
                            tabIndex={current ? 0 : -1} onClick={() => setSelected(tab.id)}
                            className={clsx('-mb-px border-b-2 px-3 py-2 text-sm font-medium',
                                current ? 'border-accent text-text-1' : 'border-transparent text-text-3 hover:text-text-1')}>
                            {tab.label}
                        </button>
                    );
                })}
            </div>
            {active ? (
                <div role="tabpanel" id={`${baseId}-panel-${active.id}`} aria-labelledby={`${baseId}-tab-${active.id}`}
                    className="min-h-0 flex-1 overflow-y-auto p-3">
                    {active.content}
                </div>
            ) : null}
        </aside>
    );
}

/** The footer button that opens and closes the side panel, with the number of unsaved changes. */
export function WorkflowChangesToggle({ id, open, controls, onToggle }: {
    id: string;
    open: boolean;
    controls: string;
    onToggle: () => void;
}) {
    const tracking = useWorkflowChanges();
    if (!tracking) return null;
    const count = tracking.changes.length;
    return (
        <GlassButton id={id} type="button" className="mr-auto shrink-0" aria-label={`Changes (${count} unsaved)`}
            aria-expanded={open} aria-controls={open ? controls : undefined} onClick={onToggle}>
            {/* Below sm an icon stands in for the label so Cancel and Save stay on one line. */}
            <FileDiff size={16} aria-hidden="true" className="sm:hidden" />
            <span className="hidden sm:inline">Changes</span>
            {count ? (
                <span aria-hidden="true" className="rounded-full bg-surface-2 px-2 text-xs font-semibold text-text-1">{count}</span>
            ) : null}
        </GlassButton>
    );
}

function WorkflowChangeRow({ change, tracking, disabled, onJump, onRevert }: {
    change: WorkflowChange;
    tracking: WorkflowChangeTracking;
    disabled: boolean;
    onJump: (change: WorkflowChange) => void;
    onRevert: (change: WorkflowChange) => void;
}) {
    const baseId = useId();
    const titleId = `${baseId}-title`;
    return (
        <li data-workflow-change-row={change.key} className="rounded-lg border border-edge p-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
                <span id={titleId} className="min-w-0 flex-1 break-words font-medium text-text-1">{changeTitle(change)}</span>
                {changeAuthors(change, tracking.attribution).map((stamp) => (
                    <WorkflowChangeBadge key={stamp.author} author={stamp.author} />
                ))}
            </div>
            <p className="mt-1 break-words text-text-2">
                <span className="sr-only">Before: </span>{summaryText(change.before)}
                <ArrowRight size={12} aria-hidden="true" className="mx-1 inline-block align-[-2px]" />
                <span className="sr-only"> After: </span>{summaryText(change.after)}
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
                <GlassButton type="button" size="sm" className="h-7 px-2 text-xs" aria-describedby={titleId}
                    onClick={() => onJump(change)}>
                    Jump
                </GlassButton>
                {change.revertable ? (
                    <GlassButton type="button" size="sm" className="h-7 gap-1 px-2 text-xs" aria-describedby={titleId}
                        disabled={disabled} onClick={() => onRevert(change)}>
                        <RotateCcw size={12} aria-hidden="true" /> {change.kind === 'removed' ? 'Restore' : 'Revert'}
                    </GlassButton>
                ) : null}
            </div>
        </li>
    );
}

function WorkflowOriginBadge({ origin }: { origin: WorkflowSessionStep['origin'] }) {
    if (origin !== 'restore') return <WorkflowChangeBadge author={origin === 'ai' ? 'ai' : 'user'} />;
    return (
        <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-text-2">
            <RotateCcw size={12} aria-hidden="true" className="shrink-0" />
            Restore
        </span>
    );
}

function WorkflowHistoryStepRow({ step, current, disabled, onRestore }: {
    step: WorkflowSessionStep;
    current: boolean;
    disabled: boolean;
    onRestore: () => void;
}) {
    const baseId = useId();
    const labelId = `${baseId}-label`;
    return (
        <li data-workflow-history-step={step.id} className="flex flex-wrap items-center gap-2 rounded-lg px-2 py-1.5 text-xs">
            <span id={labelId} className={clsx('min-w-0 flex-1 break-words', step.applied ? 'text-text-1' : 'text-text-3')}>
                {step.label}
            </span>
            <WorkflowOriginBadge origin={step.origin} />
            {step.turnId ? <span className="text-text-3">{`Turn ${step.turnId.slice(0, 8)}`}</span> : null}
            {current ? <span className="font-medium text-text-2">Current</span>
                : !step.applied ? <span className="text-text-3">Undone</span>
                    : (
                        <GlassButton type="button" size="sm" className="h-7 px-2 text-xs" aria-describedby={labelId}
                            disabled={disabled} onClick={onRestore}>
                            Restore to here
                        </GlassButton>
                    )}
        </li>
    );
}

/**
 * The Changes tab: the save confirmation when AI assist changes are unsaved, every unsaved change
 * with Jump and Revert, and this session's history with Restore to here.
 */
export function WorkflowChangesTab({ confirming, disabled, onConfirmSave, onKeepReviewing, onJump, confirmHeadingRef, listHeadingRef }: {
    confirming: boolean;
    /** Reverts and restores wait while the editor saves or a confirmation is open. */
    disabled: boolean;
    onConfirmSave: () => void;
    onKeepReviewing: () => void;
    onJump: (change: WorkflowChange) => void;
    confirmHeadingRef?: RefObject<HTMLHeadingElement>;
    listHeadingRef?: RefObject<HTMLHeadingElement>;
}) {
    const tracking = useWorkflowChanges();
    const baseId = useId();
    const listRef = useRef<HTMLUListElement>(null);
    const ownHeadingRef = useRef<HTMLHeadingElement>(null);
    const headingRef = listHeadingRef ?? ownHeadingRef;
    const historyHeadingRef = useRef<HTMLHeadingElement>(null);
    const focusAfter = useRef<number | null>(null);
    const changes = tracking?.changes;
    useEffect(() => {
        const index = focusAfter.current;
        if (index === null) return;
        focusAfter.current = null;
        const rows = [...listRef.current?.querySelectorAll<HTMLElement>('[data-workflow-change-row]') ?? []];
        const row = rows[Math.min(index, rows.length - 1)];
        (row?.querySelector<HTMLElement>('button:not(:disabled)') ?? headingRef.current)?.focus();
    }, [changes, headingRef]);
    if (!tracking) return null;
    const aiCount = tracking.changes.filter((change) => aiAuthored(change, tracking.attribution)).length;
    const applied = tracking.steps.filter((step) => step.applied);
    const currentId = applied.length ? applied[applied.length - 1].id : null;
    const revert = (change: WorkflowChange) => {
        const index = tracking.changes.indexOf(change);
        const result = tracking.session.revertChange([change.key]);
        if (result.status === 'applied') focusAfter.current = Math.max(0, index);
    };
    const restore = (step: number | 'opened') => {
        if (tracking.session.restoreTo(step).status !== 'applied') return;
        // The restored point becomes Current and its button goes away, so focus stays in the history.
        requestAnimationFrame(() => {
            const active = document.activeElement;
            if (!active || active === document.body || !active.isConnected) historyHeadingRef.current?.focus();
        });
    };
    return (
        <div className="space-y-5">
            {tracking.runAsConsequence ? (
                <p className="flex gap-2 rounded-lg bg-warn-soft p-2 text-xs text-text-1">
                    <AlertTriangle size={14} aria-hidden="true" className="mt-0.5 shrink-0 text-warn" />
                    <span>
                        <span className="font-semibold">Saving requires re-approving Run as.</span>
                        {' '}These changes affect what this workflow does with its Microsoft 365 account, so the selected person
                        must approve the new revision before it runs as them again.
                    </span>
                </p>
            ) : null}
            {confirming && aiCount ? (
                <section aria-labelledby={`${baseId}-confirm`} className="rounded-lg border border-change-ai/40 p-3">
                    <h3 id={`${baseId}-confirm`} ref={confirmHeadingRef} tabIndex={-1} className="text-sm font-semibold text-text-1">
                        Review before saving
                    </h3>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-text-2">
                        <li>{`${aiCount} unsaved ${aiCount === 1 ? 'change was' : 'changes were'} made by AI assist. Check them below before saving.`}</li>
                        {tracking.runAsConsequence ? <li>Saving requires re-approving Run as.</li> : null}
                        <li>After saving, these changes become the saved workflow and this session&apos;s history is cleared.</li>
                    </ul>
                    <div className="mt-3 flex flex-wrap gap-2">
                        <GlassButton type="button" size="sm" variant="primary" disabled={disabled} onClick={onConfirmSave}>
                            Confirm and save
                        </GlassButton>
                        <GlassButton type="button" size="sm" onClick={onKeepReviewing}>Keep reviewing</GlassButton>
                    </div>
                </section>
            ) : null}
            <section aria-labelledby={`${baseId}-changes`}>
                <h3 id={`${baseId}-changes`} ref={headingRef} tabIndex={-1} className="text-sm font-semibold text-text-1">
                    {`Unsaved changes (${tracking.changes.length})`}
                </h3>
                {tracking.isNew ? (
                    <p className="mt-1 text-xs text-text-3">
                        This workflow hasn&apos;t been saved yet, so all of it is new. Your own edits are highlighted after the first save.
                    </p>
                ) : null}
                {tracking.converted ? (
                    <p className="mt-1 text-xs text-text-3">
                        The workflow format changed in this draft, so its changes can only be discarded together. Cancel to discard them.
                    </p>
                ) : null}
                {!tracking.changes.length && !tracking.isNew ? <p className="mt-1 text-xs text-text-3">No unsaved changes.</p> : null}
                {tracking.changes.length ? (
                    <ul ref={listRef} className="mt-2 space-y-2">
                        {tracking.changes.map((change) => (
                            <WorkflowChangeRow key={change.key} change={change} tracking={tracking} disabled={disabled}
                                onJump={onJump} onRevert={revert} />
                        ))}
                    </ul>
                ) : null}
            </section>
            <section aria-labelledby={`${baseId}-history`}>
                <h3 id={`${baseId}-history`} ref={historyHeadingRef} tabIndex={-1} className="text-sm font-semibold text-text-1">
                    This session
                </h3>
                <p className="mt-1 text-xs text-text-3">Restoring an earlier point adds a new step, so nothing here is lost.</p>
                {tracking.trimmed ? <p className="mt-1 text-xs text-text-3">Older steps from this session are no longer kept.</p> : null}
                <ol className="mt-2 space-y-1">
                    {[...tracking.steps].reverse().map((step) => (
                        <WorkflowHistoryStepRow key={step.id} step={step} current={step.id === currentId} disabled={disabled}
                            onRestore={() => restore(step.id)} />
                    ))}
                    <WorkflowOpenedRow isNew={tracking.isNew} current={currentId === null} disabled={disabled}
                        onRestore={() => restore('opened')} />
                </ol>
            </section>
        </div>
    );
}

function WorkflowOpenedRow({ isNew, current, disabled, onRestore }: {
    isNew: boolean;
    current: boolean;
    disabled: boolean;
    onRestore: () => void;
}) {
    const baseId = useId();
    const labelId = `${baseId}-label`;
    return (
        <li data-workflow-history-step="opened" className="flex flex-wrap items-center gap-2 rounded-lg px-2 py-1.5 text-xs">
            <span id={labelId} className="min-w-0 flex-1 break-words text-text-1">{isNew ? 'New workflow' : 'Opened version'}</span>
            {current ? <span className="font-medium text-text-2">Current</span> : (
                <GlassButton type="button" size="sm" className="h-7 px-2 text-xs" aria-describedby={labelId}
                    disabled={disabled} onClick={onRestore}>
                    Restore to here
                </GlassButton>
            )}
        </li>
    );
}