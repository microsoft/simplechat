// ChatLinkDialog.tsx
// Create, copy, and revoke a short server-backed chat launch link.

import { useEffect, useRef, useState } from 'react';
import { Check, Copy, ExternalLink, Link2, Loader2, Trash2 } from 'lucide-react';
import {
    safeChatLinkUrl,
    CHAT_LINK_LIFETIMES,
    chatLinkDocumentLabel,
    chatLinkExpiryLabel,
    chatLinkLifetimeLabel,
    chatLinkReasoningLabel,
    createChatLink,
    listChatLinks,
    revokeChatLink,
    type ChatLinkCreatePayload,
    type ChatLinkSummary,
} from '../../lib/chatLinks';
import { Modal } from '../ui/Modal';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { GlassButton } from '../ui/primitives';

export function ChatLinkDialog({
    configuration,
    onClose,
}: {
    configuration: Omit<ChatLinkCreatePayload, 'lifetime_days'> | null;
    onClose: () => void;
}) {
    const [lifetime, setLifetime] = useState<number | null>(90);
    const [creating, setCreating] = useState(false);
    const [loadingLinks, setLoadingLinks] = useState(true);
    const [links, setLinks] = useState<ChatLinkSummary[]>([]);
    const [continuationToken, setContinuationToken] = useState<string | null>(null);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [createdUrl, setCreatedUrl] = useState('');
    const [copied, setCopied] = useState(false);
    const [revokeTarget, setRevokeTarget] = useState<ChatLinkSummary | null>(null);
    const [revoking, setRevoking] = useState(false);
    const urlInputRef = useRef<HTMLInputElement>(null);

    const loadLinks = async (append = false) => {
        if (append) setLoadingMore(true);
        else setLoadingLinks(true);
        try {
            const page = await listChatLinks(append ? continuationToken : null);
            setLinks((current) => append ? [...current, ...page.links] : page.links);
            setContinuationToken(page.continuation_token);
        } catch (failure) {
            setError(failure instanceof Error ? failure.message : 'Could not load your chat links.');
        } finally {
            setLoadingLinks(false);
            setLoadingMore(false);
        }
    };

    useEffect(() => {
        void loadLinks();
    }, []);

    const create = async () => {
        if (!configuration) {
            setError('Choose an agent or model, then one workspace or explicit documents from one workspace.');
            return;
        }
        setCreating(true);
        setError(null);
        try {
            const result = await createChatLink({ ...configuration, lifetime_days: lifetime });
            const url = safeChatLinkUrl(result.path);
            setCreatedUrl(url);
            setLinks((current) => [result, ...current.filter((item) => item.reference !== result.reference)]);
        } catch (failure) {
            setError(failure instanceof Error ? failure.message : 'Could not create the chat link.');
        } finally {
            setCreating(false);
        }
    };

    const copy = async () => {
        if (!createdUrl) return;
        try {
            if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable.');
            await navigator.clipboard.writeText(createdUrl);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1800);
        } catch {
            urlInputRef.current?.focus();
            urlInputRef.current?.select();
            setError('Clipboard access is unavailable. The link is selected so you can copy it manually.');
        }
    };

    const revoke = async () => {
        if (!revokeTarget) return;
        setRevoking(true);
        try {
            await revokeChatLink(revokeTarget.reference);
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
            <Modal
                title="Create chat link"
                description="Share a compact URL that opens this exact chat setup for users who already have access."
                size="lg"
                onClose={onClose}
                footer={
                    <GlassButton variant="primary" size="sm" onClick={onClose}>Done</GlassButton>
                }
            >
                <div className="space-y-5">
                    <div className="rounded-xl border border-edge bg-surface-2 p-4">
                        <p className="text-sm font-medium text-text-1">Link configuration</p>
                        <div className="mt-3 grid gap-2 text-sm text-text-2 sm:grid-cols-4">
                            <div>
                                <span className="block text-xs text-text-3">Runner</span>
                                <span className="font-medium text-text-1">
                                    {configuration?.routing.kind === 'agent' ? 'Agent' : 'Model'}
                                </span>
                            </div>
                            <div>
                                <span className="block text-xs text-text-3">Workspace</span>
                                <span className="font-medium text-text-1">
                                    {configuration?.workspace.display_name
                                        ?? configuration?.workspace.kind
                                        ?? 'Not selected'}
                                </span>
                            </div>
                            <div>
                                <span className="block text-xs text-text-3">Documents</span>
                                <span className="font-medium text-text-1">
                                    {configuration?.document_source_selection.sources.some(
                                        (source) => source.kind === 'workspace',
                                    )
                                        ? 'All documents'
                                        : configuration?.document_source_selection.sources.length ?? 0}
                                </span>
                            </div>
                            <div>
                                <span className="block text-xs text-text-3">Reasoning</span>
                                <span className="font-medium text-text-1">
                                    {configuration
                                        ? chatLinkReasoningLabel(
                                            configuration.routing,
                                            configuration.reasoning_effort,
                                        )
                                        : 'Not selected'}
                                </span>
                            </div>
                        </div>
                        <p className="mt-3 text-xs text-text-3">
                            This link does not grant access. Recipients must already be allowed to use
                            every configured resource.
                        </p>
                    </div>

                    <div className="text-sm text-text-2">
                        <label htmlFor="chat-link-lifetime-v2" className="block">
                            Expires after
                        </label>
                        <select
                            id="chat-link-lifetime-v2"
                            className="mt-1 block w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1"
                            value={lifetime === null ? 'never' : String(lifetime)}
                            onChange={(event) => setLifetime(
                                event.target.value === 'never' ? null : Number(event.target.value),
                            )}
                        >
                            {CHAT_LINK_LIFETIMES.map((item) => (
                                <option key={item.label} value={item.value === null ? 'never' : item.value}>
                                    {item.label}
                                </option>
                            ))}
                        </select>
                    </div>

                    <GlassButton
                        variant="primary"
                        size="sm"
                        disabled={creating || !configuration}
                        onClick={() => void create()}
                    >
                        {creating ? <Loader2 size={14} className="animate-spin" /> : <Link2 size={14} />}
                        Create link
                    </GlassButton>

                    {createdUrl ? (
                        <div className="rounded-xl border border-edge bg-surface-2 p-3">
                            <label htmlFor="created-chat-link" className="text-xs font-medium text-text-2">
                                Shareable link
                            </label>
                            <div className="mt-1 flex gap-2">
                                <input
                                    ref={urlInputRef}
                                    id="created-chat-link"
                                    value={createdUrl}
                                    readOnly
                                    className="min-w-0 flex-1 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1"
                                    onFocus={(event) => event.currentTarget.select()}
                                />
                                <GlassButton variant="ghost" size="sm" onClick={() => void copy()}>
                                    {copied ? <Check size={14} /> : <Copy size={14} />}
                                    {copied ? 'Copied' : 'Copy'}
                                </GlassButton>
                            </div>
                        </div>
                    ) : null}

                    {error ? (
                        <div role="alert" className="rounded-xl border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
                            {error}
                        </div>
                    ) : null}

                    <section aria-labelledby="your-chat-links-heading">
                        <div className="flex items-center justify-between">
                            <h3 id="your-chat-links-heading" className="text-sm font-semibold text-text-1">
                                Your active links
                            </h3>
                            {loadingLinks ? <Loader2 size={14} className="animate-spin text-text-3" aria-label="Loading links" /> : null}
                        </div>
                        {links.length === 0 && !loadingLinks ? (
                            <p className="mt-2 text-xs text-text-3">You have not created an active link.</p>
                        ) : (
                            <ul className="mt-2 divide-y divide-edge rounded-xl border border-edge">
                                {links.map((link) => (
                                    <li key={link.reference} className="flex items-start justify-between gap-3 p-3 text-sm">
                                        <div className="min-w-0">
                                            <p className="font-medium text-text-1">
                                                {link.routing.kind === 'agent' ? 'Agent' : 'Model'} · {chatLinkDocumentLabel(link)} · {chatLinkReasoningLabel(link.routing, link.reasoning_effort)}
                                            </p>
                                            <p className="mt-1 break-words text-xs text-text-3">
                                                {chatLinkLifetimeLabel(link.lifetime_days)} · Expires {chatLinkExpiryLabel(link.expires_at)}
                                            </p>
                                            <a
                                                className="mt-1 inline-flex items-center gap-1 text-xs text-accent underline"
                                                href={safeChatLinkUrl(link.path)}
                                            >
                                                {safeChatLinkUrl(link.path)}
                                                <ExternalLink size={11} aria-hidden="true" />
                                            </a>
                                        </div>
                                        <button
                                            type="button"
                                            className="rounded-lg p-2 text-text-3 hover:bg-danger/10 hover:text-danger"
                                            aria-label="Revoke this chat link"
                                            onClick={() => setRevokeTarget(link)}
                                        >
                                            <Trash2 size={14} aria-hidden="true" />
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                        {continuationToken ? (
                            <GlassButton
                                variant="ghost"
                                size="sm"
                                disabled={loadingMore}
                                onClick={() => void loadLinks(true)}
                            >
                                {loadingMore ? <Loader2 size={14} className="animate-spin" /> : null}
                                Load more
                            </GlassButton>
                        ) : null}
                    </section>
                </div>
            </Modal>
            {revokeTarget ? (
                <ConfirmDialog
                    title="Revoke chat link?"
                    description="The link will stop working immediately. Existing conversations are not changed."
                    confirmLabel="Revoke link"
                    confirmIcon={<Trash2 size={14} />}
                    busy={revoking}
                    onClose={() => setRevokeTarget(null)}
                    onConfirm={() => void revoke()}
                />
            ) : null}
        </>
    );
}
