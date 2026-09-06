// WorkspaceEditorFrame.tsx

import { useEffect, useId, useRef, type ReactNode } from 'react';
import { useBlocker, useNavigate } from 'react-router-dom';
import { ArrowLeft, Loader2, Lock, Save } from 'lucide-react';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { agentEditorReturnPath, isRecord } from '../../lib/workspaceAuthoring';

export interface WorkspaceEditorSection {
    id: string;
    label: string;
    description?: string;
    content: ReactNode;
}

function LeavePrompt({
    saving, onStay, onDiscard,
}: { saving: boolean; onStay: () => void; onDiscard: () => void }) {
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
                {saving ? 'Your changes are still being saved' : 'Discard unsaved changes?'}
            </h2>
            <p className="mt-2 text-sm text-text-2">
                {saving ? 'Stay here until the save finishes.' : 'Your changes have not been saved. Stay to keep editing, or discard them before leaving.'}
            </p>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
                <GlassButton type="button" autoFocus onClick={onStay}>Keep editing</GlassButton>
                <GlassButton type="button" variant="danger" disabled={saving} onClick={onDiscard}>Discard changes</GlassButton>
            </div>
        </dialog>
    );
}

export function WorkspaceEditorFrame({
    title, description, backTo, sections, dirty, saving, readOnly = false, error,
    onSave, onDiscard, saveLabel = 'Save changes', actions, saveDisabled = false,
}: {
    title: string;
    description?: string;
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
}) {
    const navigate = useNavigate();
    const form = useRef<HTMLFormElement>(null);
    const errorSummary = useRef<HTMLDivElement>(null);
    const prefix = useId();
    const blocker = useBlocker(({ currentLocation, nextLocation, historyAction }) => {
        if (readOnly || (!dirty && !saving)) return false;
        const state = isRecord(nextLocation.state) ? nextLocation.state : {};
        const currentEditorTransition = historyAction !== 'POP' &&
            state.workspaceEditorFrom === currentLocation.key;
        if (currentEditorTransition && state.workspaceEditorSaved === true && /^\/workspace\/(?:agents|actions)(?:\/|$)/.test(nextLocation.pathname)) return false;
        if (currentEditorTransition && state.preserveWorkspaceDraft === true) {
            const goingToAction = nextLocation.pathname === '/workspace/actions/new' &&
                agentEditorReturnPath(currentLocation.pathname) &&
                new URLSearchParams(nextLocation.search).get('returnTo') === currentLocation.pathname;
            const returningToAgent = currentLocation.pathname === '/workspace/actions/new' &&
                agentEditorReturnPath(nextLocation.pathname) &&
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
        if (error) errorSummary.current?.focus();
    }, [error]);

    const goToSection = (id: string) => {
        const target = document.getElementById(`${prefix}-${id}`);
        if (target instanceof HTMLDetailsElement) target.open = true;
        target?.scrollIntoView({ block: 'start', behavior: 'smooth' });
        target?.focus({ preventScroll: true });
    };

    return (
        <form ref={form} className="flex h-full min-h-0 flex-col"
            onSubmit={(event) => { event.preventDefault(); if (!readOnly && !saving && !saveDisabled) onSave(); }}
            onInvalidCapture={(event) => {
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
            <header className="shrink-0 space-y-3 border-b border-edge pb-3">
                <GlassButton type="button" size="sm" onClick={() => navigate(backTo)}>
                    <ArrowLeft size={15} /> Back
                </GlassButton>
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                        <h2 className="break-words text-xl font-semibold text-text-1">{title}</h2>
                        {description ? <p className="mt-1 max-w-2xl text-sm text-text-3">{description}</p> : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {actions}
                        {readOnly ? (
                            <span className="flex items-center gap-1.5 text-sm text-text-3"><Lock size={14} /> Provided - read only</span>
                        ) : (
                            <>
                                <GlassButton type="button" disabled={saving} onClick={() => navigate(backTo)}>Cancel</GlassButton>
                                <GlassButton type="submit" variant="primary" disabled={saving || saveDisabled}>
                                    {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                                    {saving ? 'Saving...' : saveLabel}
                                </GlassButton>
                            </>
                        )}
                    </div>
                </div>
                {!readOnly ? <p role="status" className="text-xs text-text-3">{saving ? 'Saving your changes.' : dirty ? 'Unsaved changes' : 'No unsaved changes'}</p> : null}
            </header>

            <div className="flex min-h-0 flex-1 flex-col gap-3 pt-3 lg:flex-row lg:gap-5">
                <nav aria-label="Editor sections" className="hidden w-40 shrink-0 space-y-1 overflow-y-auto lg:block">
                    {sections.map((section) => (
                        <button key={section.id} type="button" onClick={() => goToSection(section.id)}
                            className="block w-full rounded-lg px-3 py-2 text-left text-sm text-text-2 hover:bg-surface-2 hover:text-text-1">
                            {section.label}
                        </button>
                    ))}
                </nav>
                <label className="shrink-0 text-xs text-text-3 lg:hidden">
                    Jump to section
                    <select aria-label="Jump to section" defaultValue="" onChange={(event) => { if (event.target.value) goToSection(event.target.value); }}
                        className="mt-1 block w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1">
                        <option value="">Choose a section</option>
                        {sections.map((section) => <option key={section.id} value={section.id}>{section.label}</option>)}
                    </select>
                </label>
                <div className="min-h-0 min-w-0 flex-1 space-y-4 overflow-y-auto pb-6 pr-1">
                    {error ? <GlassPanel elevation="flat" className="border border-danger/30 p-4">
                        <div ref={errorSummary} role="alert" tabIndex={-1} className="text-sm text-danger">{error}</div>
                    </GlassPanel> : null}
                    <fieldset disabled={readOnly || saving} className="min-w-0 space-y-4">
                        <legend className="sr-only">{readOnly ? 'Configuration details' : 'Configuration'}</legend>
                        {sections.map((section) => section.id === 'advanced' ? (
                            <details key={section.id} id={`${prefix}-${section.id}`} tabIndex={-1}
                                className="glass-flat scroll-mt-2 rounded-2xl p-4">
                                <summary className="cursor-pointer text-base font-semibold text-text-1">{section.label}</summary>
                                {section.description ? <p className="mt-1 text-sm text-text-3">{section.description}</p> : null}
                                <div className="mt-4 space-y-4">{section.content}</div>
                            </details>
                        ) : (
                            <section key={section.id} id={`${prefix}-${section.id}`} tabIndex={-1}
                                aria-labelledby={`${prefix}-${section.id}-title`} className="glass-flat scroll-mt-2 rounded-2xl p-4">
                                <h3 id={`${prefix}-${section.id}-title`} className="text-base font-semibold text-text-1">{section.label}</h3>
                                {section.description ? <p className="mt-1 text-sm text-text-3">{section.description}</p> : null}
                                <div className="mt-4 space-y-4">{section.content}</div>
                            </section>
                        ))}
                    </fieldset>
                </div>
            </div>
            {blocker.state === 'blocked' ? (
                <LeavePrompt saving={saving} onStay={() => blocker.reset()}
                    onDiscard={() => { onDiscard(); blocker.proceed(); }} />
            ) : null}
        </form>
    );
}
