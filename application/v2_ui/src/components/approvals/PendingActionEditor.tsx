// PendingActionEditor.tsx

import { useEffect, useId, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, Save, Sparkles } from 'lucide-react';
import { canEditPendingAction, pendingReviewChanges, pendingReviewDateTimeInput, pendingReviewHasDateTimeOffset, type PendingReviewDraft } from '../../lib/pendingActionReview';
import type { PendingAction } from '../../lib/approvalsApi';
import { AssistThread, type AssistThreadTurn } from '../chat/AssistThread';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import { PendingActionBody } from './PendingActionBody';
import { usePendingActionReview } from './usePendingActionReview';

const INPUT_CLASS = 'w-full rounded-lg border border-edge-strong bg-surface-sunken px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none disabled:opacity-60';

function recipientValues(value: string): string[] {
    return value.split(/[;,\n]/).map((item) => item.trim()).filter(Boolean);
}

function RecipientField({ id, label, values, disabled, onChange }: {
    id: string; label: string; values: string[]; disabled: boolean; onChange: (values: string[]) => void;
}) {
    const [text, setText] = useState(values.join('; '));
    useEffect(() => {
        if (JSON.stringify(recipientValues(text)) !== JSON.stringify(values)) setText(values.join('; '));
    }, [values, text]);
    return (
        <label className="block space-y-1.5 text-xs font-medium text-text-2" htmlFor={id}>
            <span>{label}</span>
            <input id={id} className={INPUT_CLASS} disabled={disabled} value={text}
                placeholder="name@example.com; another@example.com"
                onChange={(event) => {
                    setText(event.target.value);
                    onChange(recipientValues(event.target.value));
                }} />
        </label>
    );
}

export function PendingActionEditor({ action, onClose, onSaved, editable = canEditPendingAction(action), denied = false }: {
    action: PendingAction;
    onClose: () => void;
    onSaved: (action?: PendingAction) => void;
    editable?: boolean;
    denied?: boolean;
}) {
    const calendar = action.graph_resource_type === 'calendar';
    const clearMaterial = denied || action.viewer_is_owner === false || ['sent', 'cancelled', 'canceled', 'failed', 'recovery_required'].includes(action.status);
    const assist = usePendingActionReview(action.id, calendar, editable, action.version, clearMaterial, onSaved);
    const [tab, setTab] = useState<'edit' | 'assist'>('edit');
    const [discard, setDiscard] = useState<'close' | 'reload' | null>(null);
    const [preview, setPreview] = useState(false);
    const prefix = useId();
    const draft = assist.draft;
    const requestClose = () => {
        if (assist.saving) return;
        if (assist.dirty || assist.thread.pending) setDiscard('close');
        else onClose();
    };
    const reloadSaved = () => {
        if (assist.dirty || assist.thread.pending) setDiscard('reload');
        else void assist.reload();
    };
    const change = (field: keyof PendingReviewDraft, value: unknown) => {
        if (draft && !assist.locked) assist.store.getState().edit({ ...draft, [field]: value });
    };
    const textField = (name: keyof PendingReviewDraft, label: string, type = 'text') => {
        const raw = String(draft?.[name] ?? '');
        const value = type === 'datetime-local' ? pendingReviewDateTimeInput(raw, draft?.timezone, assist.review?.timezone_aliases) : raw;
        const unsupportedZone = type === 'datetime-local' && pendingReviewHasDateTimeOffset(value);
        return (
            <div className="space-y-1.5 text-xs font-medium text-text-2">
                <label htmlFor={`${prefix}-${name}`}>{label}</label>
                <input id={`${prefix}-${name}`} className={INPUT_CLASS}
                    type={unsupportedZone ? 'text' : type} step={type === 'datetime-local' ? 'any' : undefined}
                    aria-describedby={unsupportedZone ? `${prefix}-${name}-zone` : undefined}
                    disabled={assist.locked} value={value}
                    onChange={(event) => change(name, event.target.value)} />
                {unsupportedZone ? <p id={`${prefix}-${name}-zone`} className="text-text-3">
                    This timestamp cannot be displayed in the selected time zone. The original ISO timestamp is shown unchanged.
                </p> : null}
            </div>
        );
    };
    const recipients = (name: keyof PendingReviewDraft, label: string) => (
        <RecipientField id={`${prefix}-${name}`} label={label} disabled={assist.locked}
            values={Array.isArray(draft?.[name]) ? draft[name] as string[] : []}
            onChange={(value) => change(name, value)} />
    );
    const turns: AssistThreadTurn[] = assist.history.flatMap((record) => {
        const result: AssistThreadTurn[] = [];
        if (record.instruction) result.push({ key: `${record.id}-user`, role: 'user', content: record.instruction });
        result.push({
            key: record.id, role: 'assistant',
            content: (
                <div className="space-y-2">
                    <p>{record.reply || (record.attribution === 'ai' ? 'Saved AI-assisted edits.'
                        : record.attribution === 'outlook' ? 'Synced changes from Outlook.' : 'Saved direct edits.')}</p>
                    <p className="text-[11px] text-text-3">
                        {record.saved ? 'Saved revision' : record.kind === 'assist' ? 'AI suggestion — review and Save to keep changes' : 'Saved revision'}
                        {record.created_at ? ` · ${new Date(record.created_at).toLocaleString()}` : ''}
                    </p>
                    {record.before && record.after ? (
                        <>
                            <ul aria-label="Changed fields" className="list-disc pl-4">
                                {pendingReviewChanges(record.before, record.after, calendar).map((change) => (
                                    <li key={change.path}>{change.label}</li>
                                ))}
                            </ul>
                            <div className="flex flex-wrap gap-3">
                                {record.kind === 'assist' && !record.saved ? (
                                    <button type="button" disabled={assist.locked} onClick={() => assist.applySuggestion(record)}
                                        className="rounded-md text-xs font-medium text-accent underline disabled:opacity-50">
                                        Apply suggestion
                                    </button>
                                ) : null}
                                <button type="button" disabled={assist.locked} onClick={() => assist.undo(record)}
                                    className="rounded-md text-xs font-medium text-accent underline disabled:opacity-50">
                                    Undo this change
                                </button>
                            </div>
                        </>
                    ) : null}
                    {record.warnings?.map((warning, index) => (
                        <p key={`${warning.code}-${index}`} className="rounded-lg bg-warn-soft p-2 text-text-1">{warning.message}</p>
                    ))}
                </div>
            ),
        });
        return result;
    });

    return (
        <>
            <Modal title={calendar ? 'Edit calendar invitation' : 'Edit email'}
                description="Review the saved draft. Saving or asking AI never sends it."
                size="xl" tall bodyClassName="flex min-h-0 flex-col" onClose={requestClose}
                footer={
                    <>
                        <p role="status" className="mr-auto text-xs text-text-3">{assist.saving ? 'Saving…' : assist.loading ? 'Loading…'
                            : !draft ? 'Draft unavailable' : assist.dirty ? 'Unsaved changes' : 'Saved draft'}</p>
                        <GlassButton size="sm" variant="ghost" disabled={assist.saving} onClick={requestClose}>Cancel</GlassButton>
                        <GlassButton size="sm" variant="primary" disabled={!assist.dirty || assist.locked}
                            onClick={() => void assist.save()}>
                            {assist.saving ? <Loader2 size={14} className="animate-spin motion-reduce:animate-none" /> : <Save size={14} />}
                            Save changes
                        </GlassButton>
                    </>
                }>
                {assist.error ? (
                    <div role="alert" className="flex flex-wrap items-center gap-2 border-b border-edge bg-warn-soft px-4 py-2 text-sm text-text-1">
                        <p className="min-w-0 flex-1">{assist.error}</p>
                        <GlassButton size="sm" variant="ghost" disabled={assist.saving} onClick={reloadSaved}>Reload saved draft</GlassButton>
                    </div>
                ) : null}
                {!editable ? (
                    <div className="flex flex-wrap items-center gap-2 p-4 text-sm text-text-2">
                        <p role="status" className="min-w-0 flex-1">{clearMaterial
                            ? 'This action is no longer editable. Close this editor and check its current status.'
                            : 'Editing is paused while this action is checked or processed. Your working copy is read-only; reload the saved draft or check the card status.'}</p>
                        {!clearMaterial && !assist.error ? <GlassButton size="sm" variant="ghost" disabled={assist.saving}
                            onClick={reloadSaved}>Reload saved draft</GlassButton> : null}
                    </div>
                ) : null}
                <div className="flex gap-2 border-b border-edge p-2 lg:hidden" role="group" aria-label="Editor panels">
                    <GlassButton size="sm" aria-pressed={tab === 'edit'} onClick={() => setTab('edit')}>Draft</GlassButton>
                    <GlassButton size="sm" aria-pressed={tab === 'assist'} onClick={() => setTab('assist')}>Ask AI &amp; history</GlassButton>
                </div>
                <div className="flex min-h-0 flex-1">
                    <section aria-label="Draft fields" className={clsx('min-w-0 flex-1 overflow-y-auto p-4', tab !== 'edit' && 'hidden lg:block')}>
                        {assist.loading ? <p role="status" className="text-sm text-text-2">Loading saved draft…</p> : draft ? (
                            <div className="space-y-4">
                                {calendar ? (
                                    <>
                                        {textField('subject', 'Title')}
                                        {recipients('attendee_recipients', 'Attendees')}
                                        <div className="grid gap-4 sm:grid-cols-2">
                                            {textField('start_datetime', 'Start', 'datetime-local')}
                                            {textField('end_datetime', 'End', 'datetime-local')}
                                        </div>
                                        {textField('timezone', 'Time zone')}
                                        {textField('location', 'Location')}
                                        {typeof draft.teams_meeting_requested === 'boolean' ? (
                                            <label className="flex items-center gap-2 text-sm text-text-2">
                                                <input type="checkbox" checked={draft.teams_meeting_requested} disabled={assist.locked}
                                                    onChange={(event) => change('teams_meeting_requested', event.target.checked)} />
                                                Teams meeting
                                            </label>
                                        ) : null}
                                    </>
                                ) : (
                                    <>
                                        {recipients('to_recipients', 'To')}
                                        {recipients('cc_recipients', 'Cc')}
                                        {recipients('bcc_recipients', 'Bcc')}
                                        {textField('subject', 'Subject')}
                                    </>
                                )}
                                <div className="space-y-1.5 text-xs font-medium text-text-2">
                                    <label htmlFor={`${prefix}-format`}>Body format</label>
                                    <select id={`${prefix}-format`} className={INPUT_CLASS} value={draft.content_type}
                                        disabled={assist.locked} onChange={(event) => change('content_type', event.target.value)}>
                                        <option value="Text">Plain text</option>
                                        <option value="HTML">HTML</option>
                                    </select>
                                </div>
                                <div className="space-y-1.5 text-xs font-medium text-text-2">
                                    <label htmlFor={`${prefix}-body`}>{draft.content_type?.toLowerCase() === 'html' ? 'Body (HTML)' : 'Body'}</label>
                                    <textarea id={`${prefix}-body`} className={INPUT_CLASS} rows={10} value={draft.body}
                                        disabled={assist.locked} onChange={(event) => change('body', event.target.value)} />
                                </div>
                                <button type="button" aria-expanded={preview} onClick={() => setPreview(!preview)}
                                    className="rounded-md text-sm text-accent underline">{preview ? 'Hide body preview' : 'Preview body'}</button>
                                {preview ? <PendingActionBody body={draft.body} contentType={draft.content_type}
                                    expanded onExpand={() => undefined} /> : null}
                            </div>
                        ) : null}
                    </section>
                    <aside aria-label="Ask AI and history" className={clsx('flex min-h-0 w-full flex-col border-edge p-4 lg:w-[360px] lg:flex-none lg:border-l', tab !== 'assist' && 'hidden lg:flex')}>
                        <h3 className="flex items-center gap-2 text-sm font-semibold text-text-1"><Sparkles size={15} aria-hidden="true" />Ask AI &amp; history</h3>
                        <p className="my-2 text-xs text-text-3">Ask for a change, review it on the left, then Save. Nothing here sends email or invitations.</p>
                        {!assist.assistAvailable && !assist.loading ? <p className="mb-2 text-xs text-text-3">Ask AI is unavailable. You can still edit directly and review saved history.</p> : null}
                        <AssistThread thread={assist.thread} conversationId={null} inputId={`${prefix}-ask`}
                            label="Message Ask AI" logLabel="Draft review history" assistantName="Ask AI" turns={turns}
                            sendLabel="Ask AI" sendAriaLabel="Send to Ask AI" busy={assist.locked || assist.waitSeconds > 0}
                            hideComposer={!assist.assistAvailable}
                            cancelledMessage="Cancelled. No draft changes were saved or sent."
                            emptyState={<p>Ask to improve the wording or change a field. Saved revisions and AI suggestions stay here until this action is sent or cancelled.</p>}
                            logHeader={assist.continuationToken ? (
                                <GlassButton size="sm" variant="ghost" disabled={assist.paging} onClick={() => void assist.loadHistory(true)}>
                                    {assist.paging ? 'Loading history…' : 'Load older history'}
                                </GlassButton>
                            ) : undefined}
                            composerClassName="mt-3"
                            composerNote={assist.waitSeconds > 0 ? <p className="mt-2 text-xs text-text-3">Try again in {assist.waitSeconds} seconds.</p> : undefined} />
                    </aside>
                </div>
            </Modal>
            {discard ? <ConfirmDialog title="Discard unsaved changes?" description="Saved revisions and AI history will remain. Only this working copy is discarded."
                confirmLabel={discard === 'reload' ? 'Discard and reload' : 'Discard changes'}
                cancelLabel="Keep editing" onClose={() => setDiscard(null)}
                onConfirm={() => {
                    if (discard === 'reload') {
                        setDiscard(null);
                        void assist.reload();
                    } else onClose();
                }} /> : null}
        </>
    );
}
