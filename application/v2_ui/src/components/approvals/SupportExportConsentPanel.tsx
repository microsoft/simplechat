// SupportExportConsentPanel.tsx

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../lib/apiClient';
import {
    SUPPORT_CONSENT_ROOT, supportConsentPath,
    type SupportConsent, type SupportPage,
} from '../../lib/supportExports';
import { GlassButton } from '../ui/primitives';
import {
    ApprovalSplit, DetailShell, Fact, Facts, ListRow, Notice, StatusBadge,
} from './ApprovalParts';

function errorText(error: unknown): string {
    return error instanceof Error ? error.message : 'Support-data consent could not be loaded.';
}

export function SupportExportConsentPanel({
    selectedId, reloadKey, onCountChange,
}: {
    selectedId?: string;
    reloadKey: number;
    onCountChange?: (count: number) => void;
}) {
    const navigate = useNavigate();
    const [items, setItems] = useState<SupportConsent[]>([]);
    const [next, setNext] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [preview, setPreview] = useState<unknown>(null);
    const [fingerprint, setFingerprint] = useState('');
    const [acknowledged, setAcknowledged] = useState(false);
    const selected = items.find((item) => item.id === selectedId);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true); setError(''); setPreview(null); setFingerprint(''); setAcknowledged(false);
        Promise.all([
            api.get<SupportPage<SupportConsent>>(SUPPORT_CONSENT_ROOT, controller.signal),
            selectedId ? api.get<SupportConsent>(supportConsentPath(selectedId), controller.signal) : Promise.resolve(null),
        ]).then(([page, detail]) => {
            setItems(detail && !page.items.some((item) => item.id === detail.id) ? [detail, ...page.items] : page.items);
            setNext(page.next);
        }).catch((failure) => { if (!controller.signal.aborted) setError(errorText(failure)); })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [selectedId, reloadKey]);

    useEffect(() => { onCountChange?.(items.length); }, [items.length, onCountChange]);

    const run = async (operation: () => Promise<void>) => {
        setBusy(true); setError('');
        try { await operation(); } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
    };
    const decide = async (action: 'approve' | 'decline' | 'revoke') => {
        if (!selected) return;
        const updated = await api.post<SupportConsent>(supportConsentPath(selected.id, 'decision'), {
            action, ...(action === 'approve' ? { fingerprint } : {}),
        });
        setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
        setPreview(null); setFingerprint(''); setAcknowledged(false);
    };
    const list = (
        <div data-testid="support-consent-list">
            <p className="p-4 text-sm text-text-2">Only requests for your own personal conversations appear here. An admin role cannot approve another person's data release.</p>
            {loading ? <p role="status" className="p-4 text-sm">Loading support-data requests...</p> : null}
            {!loading && !items.length ? <p className="p-4 text-sm text-text-2">No support-data consent requests.</p> : null}
            {!selected && error ? <div className="p-4"><Notice tone="danger">{error}</Notice></div> : null}
            <ul>{items.map((item) => <ListRow key={item.id} active={item.id === selectedId}
                onSelect={() => navigate(`/approvals/support-exports/${encodeURIComponent(item.id)}`)}
                title={item.purpose} meta={`Requested ${item.created_at}`}
                badge={<StatusBadge status={item.status} />} />)}</ul>
            {next ? <div className="p-4"><GlassButton type="button" variant="subtle" disabled={busy} onClick={() => void run(async () => {
                const page = await api.get<SupportPage<SupportConsent>>(`${SUPPORT_CONSENT_ROOT}?${new URLSearchParams({ after: next })}`);
                setItems((current) => [...current, ...page.items.filter((item) => !current.some((other) => other.id === item.id))]); setNext(page.next);
            })}>Load more support requests</GlassButton></div> : null}
        </div>
    );
    const detail = selected ? (
        <DetailShell title="Personal conversation data release" subtitle={selected.purpose} badge={<StatusBadge status={selected.status} />}>
            {error ? <Notice tone="danger">{error}</Notice> : null}
            <Notice tone="warn">{selected.scope_notice}</Notice>
            <Facts>
                <Fact label="Requesting administrator">{selected.requester_id}</Fact>
                <Fact label="Snapshot cutoff">{selected.source_cutoff}</Fact>
                <Fact label="Expires">{selected.expires_at}</Fact>
                <Fact label="Privacy inspection">{selected.privacy === 'ai' ? `Deterministic plus AI: ${selected.model_label}` : 'Deterministic credential and PII redaction'}</Fact>
            </Facts>
            <div className="space-y-2 text-sm"><h3 className="font-semibold">Whole personal conversations requested</h3>
                <ul className="space-y-1">{selected.conversations.map((conversation) => <li className="break-all" key={conversation.id}>
                    {conversation.id} {conversation.message_count !== null ? `(${conversation.message_count} recorded messages)` : ''}
                </li>)}</ul>
                <p className="text-text-2">The approval does not include attachments, source documents, hidden prompts, or internal reasoning. Changes cannot be added to this approved snapshot.</p>
            </div>
            {selected.privacy === 'ai' ? <Notice tone="warn">Approving also allows the already-scrubbed snapshots to be sent to the configured default model shown above for privacy inspection. It is not a guarantee of anonymity.</Notice> : null}
            {selected.status === 'pending' && !selected.expired ? <div className="space-y-3">
                <GlassButton type="button" variant="subtle" disabled={busy} onClick={() => void run(async () => {
                    const data = await api.get<{ fingerprint: string; preview: unknown }>(supportConsentPath(selected.id, 'preview'));
                    setPreview(data.preview); setFingerprint(data.fingerprint); setAcknowledged(false);
                })}>Review my snapshot preview</GlassButton>
                {preview !== null ? <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-surface-2 p-3 text-xs" data-testid="support-consent-preview">{JSON.stringify(preview, null, 2)}</pre> : null}
                <p className="text-xs text-text-2">The preview shows at most 10 messages per conversation. Approval covers the whole snapshot through the cutoff, not just this preview.</p>
                <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={acknowledged} disabled={!fingerprint || busy}
                    onChange={(event) => setAcknowledged(event.target.checked)} />
                    I approve releasing the whole requested snapshots to this administrator, including the selected privacy processing. Downloaded copies cannot be recalled.
                </label>
                <div className="flex flex-wrap gap-2">
                    <GlassButton type="button" variant="primary" disabled={busy || !fingerprint || !acknowledged} onClick={() => void run(() => decide('approve'))}>Approve whole-conversation snapshots</GlassButton>
                    <GlassButton type="button" variant="danger" disabled={busy} onClick={() => void run(() => decide('decline'))}>Decline transcript release</GlassButton>
                </div>
            </div> : null}
            {selected.status === 'approved' && !selected.expired ? <GlassButton type="button" variant="danger" disabled={busy}
                onClick={() => void run(() => decide('revoke'))}>Revoke further transcript downloads</GlassButton> : null}
        </DetailShell>
    ) : <p className="p-6 text-sm text-text-2">Choose a support-data request to review its scope.</p>;
    return <ApprovalSplit list={list} detail={detail} hasSelection={Boolean(selectedId)}
        onBack={() => navigate('/approvals/support-exports')} listLabel="Support-data requests" />;
}
