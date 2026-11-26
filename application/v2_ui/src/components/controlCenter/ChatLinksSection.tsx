// ChatLinksSection.tsx
// Control Center inventory and revocation for active workspace chat links.

import { useCallback, useEffect, useState } from 'react';
import { Copy, ExternalLink, Link2, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import {
    safeChatLinkUrl,
    chatLinkDocumentLabel,
    chatLinkExpiryLabel,
    chatLinkLifetimeLabel,
    chatLinkReasoningLabel,
    listControlCenterChatLinks,
    revokeControlCenterChatLink,
    type ChatLinkSummary,
} from '../../lib/chatLinks';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { GlassButton } from '../ui/primitives';
import { useReloadOnDataRefresh } from './refreshContext';

export function ChatLinksSection() {
    const [links, setLinks] = useState<ChatLinkSummary[]>([]);
    const [continuationToken, setContinuationToken] = useState<string | null>(null);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [revokeTarget, setRevokeTarget] = useState<ChatLinkSummary | null>(null);
    const [revoking, setRevoking] = useState(false);
    const [copiedReference, setCopiedReference] = useState<string | null>(null);

    const load = useCallback(async (token: string | null = null, append = false) => {
        if (append) setLoadingMore(true);
        else setLoading(true);
        setError(null);
        try {
            const page = await listControlCenterChatLinks(token);
            setLinks((current) => append ? [...current, ...page.links] : page.links);
            setContinuationToken(page.continuation_token);
            setHasMore(page.has_more);
        } catch (failure) {
            setError(failure instanceof Error ? failure.message : 'Could not load chat links.');
        } finally {
            setLoading(false);
            setLoadingMore(false);
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);
    useReloadOnDataRefresh(() => void load());

    const copy = async (link: ChatLinkSummary) => {
        try {
            await navigator.clipboard.writeText(safeChatLinkUrl(link.path));
            setCopiedReference(link.reference);
            window.setTimeout(() => setCopiedReference(null), 1500);
        } catch {
            setError('Clipboard access is unavailable. Open the link, then copy its address manually.');
        }
    };

    const revoke = async () => {
        if (!revokeTarget) return;
        setRevoking(true);
        setError(null);
        try {
            await revokeControlCenterChatLink(revokeTarget.reference);
            setLinks((current) => current.filter((item) => item.reference !== revokeTarget.reference));
            setRevokeTarget(null);
        } catch (failure) {
            setError(failure instanceof Error ? failure.message : 'Could not revoke the chat link.');
        } finally {
            setRevoking(false);
        }
    };

    return (
        <>
            <section className="space-y-4 p-4 md:p-6" aria-labelledby="control-center-chat-links-heading">
                <header className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <h2 id="control-center-chat-links-heading" className="flex items-center gap-2 text-xl font-semibold text-text-1">
                            <Link2 size={19} aria-hidden="true" /> Chat Links
                        </h2>
                        <p className="mt-1 text-sm text-text-2">
                            Active launch links across SimpleChat. Revocation affects future opens and first sends.
                        </p>
                    </div>
                    <GlassButton variant="ghost" size="sm" onClick={() => void load()} disabled={loading}>
                        <RefreshCw size={14} className={loading ? 'animate-spin' : undefined} />
                        Refresh
                    </GlassButton>
                </header>

                {error ? (
                    <div role="alert" className="rounded-xl border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
                        {error}
                    </div>
                ) : null}

                <div className="overflow-x-auto rounded-2xl border border-edge bg-surface-1">
                    <table className="w-full min-w-[900px] text-left text-sm">
                        <thead className="border-b border-edge bg-surface-2 text-xs uppercase tracking-wide text-text-3">
                            <tr>
                                <th className="px-4 py-3">Created by</th>
                                <th className="px-4 py-3">Runner</th>
                                <th className="px-4 py-3">Workspace</th>
                                <th className="px-4 py-3">Sources</th>
                                <th className="px-4 py-3">Reasoning</th>
                                <th className="px-4 py-3">Lifetime</th>
                                <th className="px-4 py-3">Created</th>
                                <th className="px-4 py-3 text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-edge">
                            {links.map((link) => (
                                <tr key={link.reference}>
                                    <td className="px-4 py-3 font-mono text-xs text-text-2">
                                        {link.created_by_user_id ?? 'Unknown'}
                                    </td>
                                    <td className="max-w-64 px-4 py-3">
                                        <span className="block capitalize text-text-1">{link.routing.kind}</span>
                                        <span className="block truncate text-xs text-text-3" title={link.routing.selection_key}>
                                            {link.routing.selection_key}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-text-2">
                                        {link.workspace.kind}
                                        {link.workspace.id ? ` · ${link.workspace.id}` : ''}
                                    </td>
                                    <td className="px-4 py-3 text-text-2">
                                        {chatLinkDocumentLabel(link)}
                                    </td>
                                    <td className="px-4 py-3 text-text-2">
                                        {chatLinkReasoningLabel(link.routing, link.reasoning_effort)}
                                    </td>
                                    <td className="px-4 py-3 text-text-2">
                                        <span className="block">{chatLinkLifetimeLabel(link.lifetime_days)}</span>
                                        <span className="block text-xs text-text-3">
                                            Expires {chatLinkExpiryLabel(link.expires_at)}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-xs text-text-3">
                                        {new Date(link.created_at).toLocaleString()}
                                    </td>
                                    <td className="px-4 py-3">
                                        <div className="flex justify-end gap-2">
                                            <a
                                                href={safeChatLinkUrl(link.path)}
                                                target="_blank"
                                                rel="noreferrer"
                                                className="rounded-lg p-2 text-text-3 hover:bg-surface-2 hover:text-text-1"
                                                aria-label="Open chat link"
                                            >
                                                <ExternalLink size={14} aria-hidden="true" />
                                            </a>
                                            <button
                                                type="button"
                                                onClick={() => void copy(link)}
                                                className="rounded-lg p-2 text-text-3 hover:bg-surface-2 hover:text-text-1"
                                                aria-label="Copy chat link"
                                            >
                                                {copiedReference === link.reference
                                                    ? <span className="text-xs text-ok">Copied</span>
                                                    : <Copy size={14} aria-hidden="true" />}
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => setRevokeTarget(link)}
                                                className="rounded-lg p-2 text-text-3 hover:bg-danger/10 hover:text-danger"
                                                aria-label="Revoke chat link"
                                            >
                                                <Trash2 size={14} aria-hidden="true" />
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {!loading && links.length === 0 ? (
                                <tr>
                                    <td colSpan={8} className="px-4 py-10 text-center text-sm text-text-3">
                                        There are no active chat links.
                                    </td>
                                </tr>
                            ) : null}
                        </tbody>
                    </table>
                    {loading ? (
                        <div className="flex items-center justify-center gap-2 border-t border-edge p-5 text-sm text-text-3">
                            <Loader2 size={15} className="animate-spin" /> Loading chat links
                        </div>
                    ) : null}
                </div>

                {hasMore ? (
                    <GlassButton
                        variant="ghost"
                        size="sm"
                        disabled={loadingMore}
                        onClick={() => void load(continuationToken, true)}
                    >
                        {loadingMore ? <Loader2 size={14} className="animate-spin" /> : null}
                        Load more
                    </GlassButton>
                ) : null}
            </section>

            {revokeTarget ? (
                <ConfirmDialog
                    title="Revoke this chat link?"
                    description="The link will stop working immediately for the creator and every recipient. Existing conversations are not changed."
                    confirmLabel="Revoke link"
                    confirmIcon={<Trash2 size={14} />}
                    busy={revoking}
                    onClose={() => setRevokeTarget(null)}
                    onConfirm={() => void revoke()}
                >
                    <p className="break-words text-xs text-text-2">
                        Creator: {revokeTarget.created_by_user_id ?? 'Unknown'}<br />
                        Reference: {revokeTarget.reference}
                    </p>
                </ConfirmDialog>
            ) : null}
        </>
    );
}
