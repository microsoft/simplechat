// AgentTemplatesPanel.tsx
// Admin review of agent templates submitted for the shared template gallery.
//
// Approving publishes the template to every user; rejecting returns it to the submitter
// with the reason, which is why the reason is required. Deleting removes the template
// outright, so it sits behind a confirmation.

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, Loader2, Trash2, X } from 'lucide-react';
import {
    approveAgentTemplate,
    deleteAgentTemplate,
    errorMessage,
    fetchAgentTemplate,
    fetchAgentTemplates,
    formatDateTime,
    rejectAgentTemplate,
    templateTitle,
    textList,
    type AgentTemplate,
    type TemplateStatusFilter,
} from '../../lib/approvalsApi';
import { toast } from '../../stores/toastStore';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { GlassButton, Skeleton } from '../ui/primitives';
import {
    ApprovalSplit,
    DetailEmpty,
    DetailShell,
    Fact,
    Facts,
    ListMessage,
    ListPager,
    ListRow,
    ListSelect,
    ListToolbar,
    Notice,
    StatusBadge,
    fieldClass,
} from './ApprovalParts';

const PAGE_SIZE = 20;

const STATUS_OPTIONS: Array<[string, string]> = [
    ['pending', 'Pending'],
    ['approved', 'Approved'],
    ['rejected', 'Rejected'],
    ['all', 'All'],
];

function submitter(template: AgentTemplate): string {
    return template.created_by_name || template.created_by_email || 'Unknown';
}

export function AgentTemplatesPanel({
    selectedId,
    reloadKey,
    onCountChange,
}: {
    selectedId?: string;
    reloadKey: number;
    onCountChange?: (count: number) => void;
}) {
    const navigate = useNavigate();
    const [status, setStatus] = useState<TemplateStatusFilter>('pending');
    const [templates, setTemplates] = useState<AgentTemplate[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState('');
    const [search, setSearch] = useState('');
    const [page, setPage] = useState(1);
    const [localReload, setLocalReload] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setLoadError('');
        fetchAgentTemplates(status, controller.signal)
            .then((items) => setTemplates(items))
            .catch((error) => {
                if (controller.signal.aborted) return;
                setTemplates([]);
                setLoadError(errorMessage(error, 'Agent templates could not be loaded.'));
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
    }, [status, reloadKey, localReload]);

    useEffect(() => {
        if (status === 'pending') onCountChange?.(templates.length);
    }, [templates, status, onCountChange]);

    useEffect(() => setPage(1), [status, search]);

    const filtered = useMemo(() => {
        const query = search.trim().toLowerCase();
        if (!query) return templates;
        return templates.filter((template) =>
            [templateTitle(template), template.helper_text, template.description, submitter(template), textList(template.tags)]
                .join(' ')
                .toLowerCase()
                .includes(query),
        );
    }, [templates, search]);

    const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    const visible = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

    const handleChanged = (removed: boolean) => {
        setLocalReload((value) => value + 1);
        if (removed) navigate('/approvals/agent-templates');
    };

    const list = (
        <>
            <ListToolbar search={search} onSearch={setSearch} searchLabel="Search agent templates">
                <ListSelect
                    label="Template status"
                    value={status}
                    onChange={(value) => setStatus(value as TemplateStatusFilter)}
                    options={STATUS_OPTIONS}
                    testId="v2-agent-templates-status-filter"
                />
            </ListToolbar>
            {loading ? (
                <div className="space-y-2 p-4" aria-busy="true">
                    <Skeleton className="h-12 w-full" />
                    <Skeleton className="h-12 w-full" />
                </div>
            ) : loadError ? (
                <div className="p-4">
                    <Notice tone="danger">{loadError}</Notice>
                </div>
            ) : visible.length ? (
                <>
                    <ul>
                        {visible.map((template) => (
                            <ListRow
                                key={template.id}
                                active={template.id === selectedId}
                                onSelect={() => navigate(`/approvals/agent-templates/${encodeURIComponent(template.id)}`)}
                                title={templateTitle(template)}
                                testId={`v2-agent-template-row-${template.id}`}
                                meta={`${submitter(template)} · ${formatDateTime(template.created_at)}`}
                                badge={<StatusBadge status={template.status || 'pending'} />}
                            />
                        ))}
                    </ul>
                    <ListPager page={page} pageCount={pageCount} total={filtered.length} onPage={setPage} />
                </>
            ) : (
                <ListMessage>{search ? 'No templates match this search.' : 'No templates in this view.'}</ListMessage>
            )}
        </>
    );

    const detail = selectedId ? (
        <AgentTemplateDetail key={`${selectedId}-${reloadKey}`} templateId={selectedId} onChanged={handleChanged} />
    ) : (
        <DetailEmpty title="Select a template" description="Review what it instructs the agent to do, then approve or reject it." />
    );

    return (
        <ApprovalSplit
            listLabel="Agent templates"
            hasSelection={Boolean(selectedId)}
            onBack={() => navigate('/approvals/agent-templates')}
            list={list}
            detail={detail}
        />
    );
}

function AgentTemplateDetail({ templateId, onChanged }: { templateId: string; onChanged: (removed: boolean) => void }) {
    const [template, setTemplate] = useState<AgentTemplate | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState('');
    const [notes, setNotes] = useState('');
    const [reason, setReason] = useState('');
    const [actionError, setActionError] = useState('');
    const [busy, setBusy] = useState(false);
    const [confirmDelete, setConfirmDelete] = useState(false);
    const [reloadKey, setReloadKey] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setLoadError('');
        fetchAgentTemplate(templateId, controller.signal)
            .then((item) => setTemplate(item))
            .catch((error) => {
                if (controller.signal.aborted) return;
                setTemplate(null);
                setLoadError(errorMessage(error, 'Unable to load template.'));
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
    }, [templateId, reloadKey]);

    const decide = async (kind: 'approve' | 'reject') => {
        if (kind === 'reject' && !reason.trim()) {
            setActionError('A rejection reason is required.');
            return;
        }
        setBusy(true);
        setActionError('');
        try {
            if (kind === 'approve') {
                await approveAgentTemplate(templateId, notes);
                toast.success('Template approved!');
            } else {
                await rejectAgentTemplate(templateId, reason, notes);
                toast.success('Template rejected.');
            }
            setNotes('');
            setReason('');
            setReloadKey((value) => value + 1);
            onChanged(false);
        } catch (error) {
            setActionError(errorMessage(error, 'Failed to update template.'));
        } finally {
            setBusy(false);
        }
    };

    const remove = async () => {
        setBusy(true);
        try {
            await deleteAgentTemplate(templateId);
            toast.success('Template deleted.');
            setConfirmDelete(false);
            onChanged(true);
        } catch (error) {
            setActionError(errorMessage(error, 'Failed to delete template.'));
            setConfirmDelete(false);
        } finally {
            setBusy(false);
        }
    };

    if (loading) {
        return (
            <div className="space-y-3 p-6" aria-busy="true">
                <Skeleton className="h-6 w-1/2" />
                <Skeleton className="h-32 w-full" />
            </div>
        );
    }
    if (loadError || !template) {
        return (
            <div className="p-6">
                <Notice tone="danger">{loadError || 'Unable to load template.'}</Notice>
            </div>
        );
    }

    const status = template.status || 'pending';
    const settings =
        typeof template.additional_settings === 'string'
            ? template.additional_settings
            : template.additional_settings
              ? JSON.stringify(template.additional_settings, null, 2)
              : '';

    return (
        <DetailShell
            title={templateTitle(template)}
            subtitle={`Submitted by ${submitter(template)} on ${formatDateTime(template.created_at)}`}
            badge={<StatusBadge status={status} />}
        >
            <Facts>
                <Fact label="Helper text">{template.helper_text || template.description}</Fact>
                <Fact label="Updated">{formatDateTime(template.updated_at)}</Fact>
                <Fact label="Tags">{textList(template.tags)}</Fact>
                <Fact label="Actions to load">{textList(template.actions_to_load)}</Fact>
                <Fact label="Review notes">{template.review_notes}</Fact>
                <Fact label="Rejection reason">{template.rejection_reason}</Fact>
            </Facts>
            {template.description ? (
                <section>
                    <h3 className="mb-1 text-sm font-semibold text-text-1">Description</h3>
                    <p className="whitespace-pre-wrap text-sm text-text-2">{template.description}</p>
                </section>
            ) : null}
            <section>
                <h3 className="mb-1 text-sm font-semibold text-text-1">Instructions</h3>
                <pre
                    className="max-h-80 overflow-auto whitespace-pre-wrap rounded-xl border border-edge bg-surface-2 p-3 text-xs text-text-1"
                    data-testid="v2-agent-template-instructions"
                >
                    {template.instructions || ''}
                </pre>
            </section>
            {settings ? (
                <section>
                    <h3 className="mb-1 text-sm font-semibold text-text-1">Additional settings</h3>
                    <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded-xl border border-edge bg-surface-2 p-3 text-xs text-text-1">
                        {settings}
                    </pre>
                </section>
            ) : null}
            {actionError ? <Notice tone="danger" testId="v2-agent-template-error">{actionError}</Notice> : null}
            <div className="space-y-3 border-t border-edge pt-4">
                {status === 'pending' ? (
                    <>
                        <label className="block text-sm">
                            <span className="mb-1 block font-medium text-text-1">Reviewer notes (optional)</span>
                            <textarea
                                className={fieldClass}
                                rows={2}
                                value={notes}
                                onChange={(event) => setNotes(event.target.value)}
                                placeholder="Add guidance for the submitter or other admins..."
                                data-testid="v2-agent-template-notes"
                            />
                        </label>
                        <label className="block text-sm">
                            <span className="mb-1 block font-medium text-text-1">Rejection reason</span>
                            <textarea
                                className={fieldClass}
                                rows={2}
                                value={reason}
                                onChange={(event) => setReason(event.target.value)}
                                placeholder="Required when rejecting a template."
                                data-testid="v2-agent-template-reason"
                            />
                        </label>
                    </>
                ) : null}
                <div className="flex flex-wrap gap-2">
                    {status === 'pending' ? (
                        <>
                            <GlassButton size="sm" variant="success" disabled={busy} onClick={() => void decide('approve')} data-testid="v2-agent-template-approve">
                                {busy ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                                Approve
                            </GlassButton>
                            <GlassButton size="sm" variant="ghost" disabled={busy} onClick={() => void decide('reject')} data-testid="v2-agent-template-reject">
                                <X size={14} />
                                Reject
                            </GlassButton>
                        </>
                    ) : null}
                    <GlassButton size="sm" variant="danger" disabled={busy} onClick={() => setConfirmDelete(true)} data-testid="v2-agent-template-delete">
                        <Trash2 size={14} />
                        Delete
                    </GlassButton>
                </div>
            </div>
            {confirmDelete ? (
                <ConfirmDialog
                    title="Delete template?"
                    description={`"${templateTitle(template)}" will be removed permanently. This cannot be undone.`}
                    confirmLabel="Delete"
                    confirmIcon={<Trash2 size={14} />}
                    busy={busy}
                    onConfirm={() => void remove()}
                    onClose={() => setConfirmDelete(false)}
                />
            ) : null}
        </DetailShell>
    );
}
