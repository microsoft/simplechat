// WorkspaceEditorFrame.tsx

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { useBlocker, useNavigate } from 'react-router-dom';
import { clsx } from 'clsx';
import {
    ArrowLeft, ChevronRight, CircleCheck, CircleDashed, FileText, Loader2, Lock, Save, Sparkles, TriangleAlert, type LucideIcon,
} from 'lucide-react';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { isActionEditorNewPath, isAgentEditorPath, isRecord } from '../../lib/workspaceAuthoring';

export interface WorkspaceEditorSection {
    id: string;
    label: string;
    /** What the section holds, shown under its title. */
    description?: string;
    /** Shown in the section rail and on the card, as Admin Settings sections are. */
    icon?: LucideIcon;
    content: ReactNode;
}

export function WorkspaceLeavePrompt({
    saving, onStay, onDiscard, switching = false,
}: { saving: boolean; onStay: () => void; onDiscard: () => void; switching?: boolean }) {
    const dialog = useRef<HTMLDialogElement>(null);
    const titleId = useId();
    useEffect(() => {
        const element = dialog.current;
        if (!element) return;
        element.showModal();
        return () => element.close();
    }, []);

    return (
        <dialog ref={dialog} aria-labelledby={titleId}
            onCancel={(event) => { event.preventDefault(); onStay(); }}
            className="glass-modal m-auto w-[calc(100%_-_2rem)] max-w-md rounded-2xl border border-edge p-5 text-text-1 backdrop:bg-surface-sunken/75">
            <h2 id={titleId} className="text-lg font-semibold">
                {switching ? 'Workspace switch in progress' : saving ? 'Your changes are still being saved' : 'Discard unsaved changes?'}
            </h2>
            <p className="mt-2 text-sm text-text-2">
                {switching ? 'Stay here until the selected workspace is confirmed.' : saving ? 'Stay here until the save finishes.' : 'Your changes have not been saved. Stay to keep editing, or discard them before leaving.'}
            </p>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
                <GlassButton type="button" autoFocus onClick={onStay}>Keep editing</GlassButton>
                <GlassButton type="button" variant="danger" disabled={saving} onClick={onDiscard}>Discard changes</GlassButton>
            </div>
        </dialog>
    );
}

/** The icon tile at the head of a section card, as an Admin Settings card has. */
function SectionIcon({ icon: Icon = FileText }: { icon?: LucideIcon }) {
    return (
        <span aria-hidden="true"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-edge-strong bg-surface-solid text-text-2">
            <Icon size={20} />
        </span>
    );
}

/** Marks a section Ask AI changed in a turn that is still applied. */
function AiEditedBadge() {
    return (
        <span data-ai-edited-badge
            className="inline-flex shrink-0 items-center gap-1 rounded-full bg-change-ai-soft px-1.5 py-0.5 text-[10px] font-medium text-change-ai">
            <Sparkles size={10} aria-hidden="true" />
            AI edited
        </span>
    );
}

/**
 * The full-page editor an agent or action opens in, for personal, group and global ones
 * alike, laid out the way Admin Settings is.
 *
 * The rail on the left lists the editor's sections and marks the one in view. Each section
 * is a card with an icon, a title and what it holds, and the fields inside are Admin
 * Settings rows (see EditorLayout.tsx). Saving stays in the header beside the save status,
 * because an editor saves one record as a whole.
 */
export function WorkspaceEditorFrame({
    title, description, icon: TitleIcon, iconNode, backTo, sections, dirty, saving, readOnly = false, error,
    onSave, onDiscard, saveLabel = 'Save changes', actions, saveDisabled = false, initialSection,
    sidePanel, sidePanelOpen = false, aiChangedSections, locked = false, lockBanner, jumpTo,
}: {
    title: string;
    description?: string;
    /** The kind of record being edited, shown beside the title. */
    icon?: LucideIcon;
    /** The record's own icon, such as an agent's uploaded image; shown in place of `icon` when given. */
    iconNode?: ReactNode;
    backTo: string;
    sections: WorkspaceEditorSection[];
    dirty: boolean;
    saving: boolean;
    readOnly?: boolean;
    error?: string | null;
    onSave: () => void;
    onDiscard: () => void;
    saveLabel?: string;
    actions?: ReactNode;
    saveDisabled?: boolean;
    /** A section to open at, such as the templates a "Start from a template" link leads to. */
    initialSection?: string;
    /**
     * A panel beside the editor, such as Ask AI. It sits outside the editor's form because it
     * may hold a form of its own. Below xl it takes the editor's place while open.
     */
    sidePanel?: ReactNode;
    sidePanelOpen?: boolean;
    /** Sections Ask AI changed, marked in the rail and on their cards. */
    aiChangedSections?: ReadonlySet<string>;
    /** The fields and Save are disabled, such as while Ask AI works on the draft. */
    locked?: boolean;
    /** Shown above the sections while the editor is locked. */
    lockBanner?: ReactNode;
    /** Show a section; a new sequence shows it again. */
    jumpTo?: { section: string; sequence: number } | null;
}) {
    const navigate = useNavigate();
    const form = useRef<HTMLFormElement>(null);
    const errorSummary = useRef<HTMLDivElement>(null);
    const scrollRoot = useRef<HTMLDivElement>(null);
    const prefix = useId();
    const [current, setCurrent] = useState<string | null>(sections[0]?.id ?? null);
    // A section chosen in the rail stays marked while the pane scrolls to it, and until the
    // person scrolls themselves; one near the end could never rise far enough to be marked.
    // Until then it also stays in place while lists above or inside it finish loading. Any
    // other use of the editor ends the pin, as does a save or focus moving anywhere else, so
    // holding the section never scrolls an error or an invalid field back out of view.
    const pinned = useRef<string | null>(null);
    const sectionIds = sections.map((section) => section.id).join('|');
    const blocker = useBlocker(({ currentLocation, nextLocation, historyAction }) => {
        if (readOnly || (!dirty && !saving)) return false;
        const state = isRecord(nextLocation.state) ? nextLocation.state : {};
        const currentEditorTransition = historyAction !== 'POP' &&
            state.workspaceEditorFrom === currentLocation.key;
        // A save navigates to backTo (the collection or the agent return path). Personal editors
        // live under /workspace, but a group editor returns to /groups/<id>/actions, so the bypass
        // matches the frame's own backTo as well as the personal family it always did.
        if (currentEditorTransition && state.workspaceEditorSaved === true
            && (nextLocation.pathname === backTo || /^\/workspace\/(?:agents|actions)(?:\/|$)/.test(nextLocation.pathname))) return false;
        if (currentEditorTransition && state.preserveWorkspaceDraft === true) {
            const goingToAction = isActionEditorNewPath(nextLocation.pathname) &&
                isAgentEditorPath(currentLocation.pathname) &&
                new URLSearchParams(nextLocation.search).get('returnTo') === currentLocation.pathname;
            const returningToAgent = isActionEditorNewPath(currentLocation.pathname) &&
                isAgentEditorPath(nextLocation.pathname) &&
                new URLSearchParams(currentLocation.search).get('returnTo') === nextLocation.pathname;
            if (goingToAction || returningToAgent) return false;
        }
        return currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search;
    });

    useEffect(() => {
        if (readOnly || (!dirty && !saving)) return;
        const beforeUnload = (event: BeforeUnloadEvent) => {
            event.preventDefault();
            event.returnValue = '';
        };
        window.addEventListener('beforeunload', beforeUnload);
        return () => window.removeEventListener('beforeunload', beforeUnload);
    }, [dirty, saving, readOnly]);

    useEffect(() => {
        if (!error) return;
        pinned.current = null;
        errorSummary.current?.focus();
    }, [error]);

    // Mark the section in view, as the Admin Settings index does: the last one whose top has
    // passed a line near the top of the pane, or at the very bottom the last one showing.
    useEffect(() => {
        const root = scrollRoot.current;
        const order = sectionIds ? sectionIds.split('|') : [];
        pinned.current = null;
        if (!root || !order.length) return;
        let frame = 0;
        const update = () => {
            frame = 0;
            if (pinned.current) return;
            const bounds = root.getBoundingClientRect();
            const line = bounds.top + Math.min(bounds.height * 0.3, 160);
            const atBottom = root.scrollTop + root.clientHeight >= root.scrollHeight - 2;
            let next: string | null = null;
            for (const id of order) {
                const top = document.getElementById(`${prefix}-${id}`)?.getBoundingClientRect().top;
                if (top === undefined) continue;
                if (top <= line || (atBottom && top < bounds.bottom)) next = id;
            }
            setCurrent(next ?? order[0]);
        };
        const onScroll = () => {
            if (!frame) frame = requestAnimationFrame(update);
        };
        const release = () => {
            pinned.current = null;
        };
        // Only the pinned section itself may take focus without ending the pin.
        const releaseOnFocus = (event: FocusEvent) => {
            if (pinned.current && event.target !== document.getElementById(`${prefix}-${pinned.current}`)) release();
        };
        const owner = form.current;
        const content = root.firstElementChild;
        const realign = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
            if (pinned.current) document.getElementById(`${prefix}-${pinned.current}`)?.scrollIntoView({ block: 'start' });
        });
        if (content) realign?.observe(content);
        update();
        root.addEventListener('scroll', onScroll, { passive: true });
        root.addEventListener('wheel', release, { passive: true });
        root.addEventListener('touchstart', release, { passive: true });
        // The whole form, not just the pane: Save and the header commands sit above it. A rail
        // choice still pins, because its click follows the pointerdown or keydown.
        owner?.addEventListener('pointerdown', release);
        owner?.addEventListener('keydown', release);
        owner?.addEventListener('focusin', releaseOnFocus);
        return () => {
            cancelAnimationFrame(frame);
            realign?.disconnect();
            root.removeEventListener('scroll', onScroll);
            root.removeEventListener('wheel', release);
            root.removeEventListener('touchstart', release);
            owner?.removeEventListener('pointerdown', release);
            owner?.removeEventListener('keydown', release);
            owner?.removeEventListener('focusin', releaseOnFocus);
        };
    }, [sectionIds, prefix]);

    const goToSection = (id: string, instant = false) => {
        const target = document.getElementById(`${prefix}-${id}`);
        if (target instanceof HTMLDetailsElement) target.open = true;
        pinned.current = id;
        setCurrent(id);
        const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        target?.scrollIntoView({ block: 'start', behavior: instant || reduceMotion ? 'auto' : 'smooth' });
        target?.focus({ preventScroll: true });
    };

    // After the scroll-marking effect above, which clears any pin when the sections change.
    useEffect(() => {
        if (initialSection && sectionIds.split('|').includes(initialSection)) goToSection(initialSection, true);
        // Opening at a section happens once; later edits to the sections must not jump back.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [initialSection]);

    useEffect(() => {
        if (jumpTo && sectionIds.split('|').includes(jumpTo.section)) goToSection(jumpTo.section);
        // Only a new jump moves the editor.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [jumpTo?.sequence]);

    const status = saving
        ? { label: 'Saving your changes.', Icon: Loader2, className: 'border-edge-strong text-text-2' }
        : dirty
            ? { label: 'Unsaved changes', Icon: CircleDashed, className: 'border-warn/40 bg-warn/5 text-warn' }
            : { label: 'No unsaved changes', Icon: CircleCheck, className: 'border-edge-strong text-text-3' };

    return (
        <div className="flex h-full min-h-0 flex-col xl:flex-row">
            <form ref={form} className={clsx('h-full min-h-0 min-w-0 flex-1 flex-col', sidePanel && sidePanelOpen ? 'hidden xl:flex' : 'flex')}
                onSubmit={(event) => {
                    event.preventDefault();
                    pinned.current = null;
                    if (!readOnly && !saving && !saveDisabled && !locked) onSave();
                }}
                onInvalidCapture={(event) => {
                    pinned.current = null;
                    const input = event.target;
                    if (input instanceof HTMLElement) {
                        const details = input.closest('details');
                        if (details) details.open = true;
                    }
                }}
                onKeyDown={(event) => {
                    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && !readOnly) {
                        event.preventDefault();
                        form.current?.requestSubmit();
                    }
                }}>
                <header className="shrink-0 border-b border-edge pb-4">
                    <GlassButton type="button" size="sm" variant="ghost" className="-ml-2" onClick={() => navigate(backTo)}>
                        <ArrowLeft size={15} /> Back
                    </GlassButton>
                    <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
                        <div className="flex min-w-0 flex-[1_1_20rem] items-start gap-3">
                            {iconNode || TitleIcon ? (
                                <span aria-hidden="true"
                                    className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-edge-strong bg-surface-solid text-text-2">
                                    {iconNode ?? (TitleIcon ? <TitleIcon size={20} /> : null)}
                                </span>
                            ) : null}
                            <div className="min-w-0 flex-1">
                                <h2 className="break-words text-xl leading-snug font-semibold text-text-1">{title}</h2>
                                {description ? <p className="mt-1 max-w-3xl break-words text-sm text-text-3">{description}</p> : null}
                                {!readOnly ? (
                                    <p role="status" className={clsx(
                                        'mt-2 inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-xs',
                                        status.className,
                                    )}>
                                        <status.Icon size={11} aria-hidden="true" className={clsx('shrink-0', saving && 'animate-spin')} />
                                        {status.label}
                                    </p>
                                ) : null}
                            </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            {actions}
                            {readOnly ? (
                                <span className="flex items-center gap-1.5 text-sm text-text-3"><Lock size={14} /> Provided - read only</span>
                            ) : (
                                <>
                                    <GlassButton type="button" disabled={saving} onClick={() => navigate(backTo)}>Cancel</GlassButton>
                                    <GlassButton type="submit" variant="primary" disabled={saving || saveDisabled || locked}>
                                        {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                                        {saving ? 'Saving...' : saveLabel}
                                    </GlassButton>
                                </>
                            )}
                        </div>
                    </div>
                </header>

                <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
                    <nav aria-label="Editor sections" className="hidden w-56 shrink-0 overflow-y-auto border-r border-edge py-3 pr-3 lg:block">
                        <div className="space-y-0.5">
                            {sections.map((section) => {
                                const active = current === section.id;
                                const Icon = section.icon ?? FileText;
                                return (
                                    <button key={section.id} type="button" aria-current={active ? 'location' : undefined}
                                        onClick={() => goToSection(section.id)}
                                        className={clsx(
                                            'flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm transition-colors',
                                            active ? 'bg-accent-soft font-semibold text-accent' : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                                        )}>
                                        <Icon size={16} aria-hidden="true" className={clsx('shrink-0', active ? 'text-accent' : 'text-text-3')} />
                                        <span className="min-w-0 flex-1 break-words">{section.label}</span>
                                        {aiChangedSections?.has(section.id) ? <AiEditedBadge /> : null}
                                    </button>
                                );
                            })}
                        </div>
                    </nav>
                    <div className="shrink-0 pt-3 lg:hidden">
                        <label className="block max-w-md text-xs text-text-2">
                            Jump to section
                            <select aria-label="Jump to section" defaultValue="" onChange={(event) => { if (event.target.value) goToSection(event.target.value); }}
                                className="mt-1 block w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1">
                                <option value="">Choose a section</option>
                                {sections.map((section) => <option key={section.id} value={section.id}>{section.label}</option>)}
                            </select>
                        </label>
                    </div>
                    <div ref={scrollRoot} className="min-h-0 min-w-0 flex-1 overflow-y-auto pt-3 pr-1 pb-6 lg:pl-5">
                        <div className="mx-auto w-full max-w-[112rem] space-y-4">
                            {locked && lockBanner ? lockBanner : null}
                            {error ? (
                                <GlassPanel elevation="flat" className="flex items-start gap-2 border border-danger/30 p-3 text-sm text-danger">
                                    <TriangleAlert size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
                                    <div ref={errorSummary} role="alert" tabIndex={-1} className="min-w-0 flex-1 break-words">{error}</div>
                                </GlassPanel>
                            ) : null}
                            <fieldset disabled={readOnly || saving || locked} className="min-w-0 space-y-4">
                                <legend className="sr-only">{readOnly ? 'Configuration details' : 'Configuration'}</legend>
                                {sections.map((section) => section.id === 'advanced' ? (
                                    <details key={section.id} id={`${prefix}-${section.id}`} tabIndex={-1}
                                        className="glass glass-edge group/editor-section admin-settings-distinct editor-section scroll-mt-2 rounded-2xl border-edge-strong">
                                        <summary className={clsx(
                                            'flex cursor-pointer list-none items-start gap-3 rounded-2xl bg-surface-2 p-4 sm:px-5',
                                            'group-open/editor-section:rounded-b-none group-open/editor-section:border-b group-open/editor-section:border-edge-strong',
                                            '[&::-webkit-details-marker]:hidden',
                                        )}>
                                            <SectionIcon icon={section.icon} />
                                            <span className="min-w-0 flex-1">
                                                <span className="flex flex-wrap items-center gap-2">
                                                    <span id={`${prefix}-${section.id}-title`} className="block text-lg leading-snug font-semibold text-text-1">{section.label}</span>
                                                    {aiChangedSections?.has(section.id) ? <AiEditedBadge /> : null}
                                                </span>
                                                {section.description ? <span className="mt-1 block text-xs text-text-3">{section.description}</span> : null}
                                            </span>
                                            <ChevronRight size={18} aria-hidden="true"
                                                className="mt-2 shrink-0 text-text-2 transition-transform group-open/editor-section:rotate-90" />
                                        </summary>
                                        <div className="admin-section-body min-w-0 space-y-4 p-4 sm:p-5">{section.content}</div>
                                    </details>
                                ) : (
                                    <GlassPanel key={section.id} id={`${prefix}-${section.id}`} tabIndex={-1} edge role="region"
                                        aria-labelledby={`${prefix}-${section.id}-title`}
                                        className="admin-settings-distinct editor-section scroll-mt-2 border-edge-strong">
                                        <div className="flex items-start gap-3 rounded-t-2xl border-b border-edge-strong bg-surface-2 p-4 sm:px-5">
                                            <SectionIcon icon={section.icon} />
                                            <div className="min-w-0 flex-1">
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <h3 id={`${prefix}-${section.id}-title`} className="text-lg leading-snug font-semibold text-text-1">{section.label}</h3>
                                                    {aiChangedSections?.has(section.id) ? <AiEditedBadge /> : null}
                                                </div>
                                                {section.description ? <p className="mt-1 text-xs text-text-3">{section.description}</p> : null}
                                            </div>
                                        </div>
                                        <div className="admin-section-body min-w-0 space-y-4 p-4 sm:p-5">{section.content}</div>
                                    </GlassPanel>
                                ))}
                            </fieldset>
                        </div>
                    </div>
                </div>
                {blocker.state === 'blocked' ? (
                    <WorkspaceLeavePrompt saving={saving} onStay={() => blocker.reset()}
                        onDiscard={() => { onDiscard(); blocker.proceed(); }} />
                ) : null}
            </form>
        {sidePanel && sidePanelOpen ? sidePanel : null}
        </div>
    );
}
