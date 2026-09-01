// ConversationDetails.tsx
// Conversation metadata view, opened from the chat header.
//
// Renders only fields GET /api/conversations/<id>/metadata actually returns. The route
// keys on conversation_id (not id) and carries no created_at, participants or permission
// flags, so none of those are displayed. Sections are omitted entirely when their data is
// absent rather than rendering empty rows.

import { useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { Check, Eye, EyeOff, Lock, Pencil, Pin, TriangleAlert, X } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { GlassPanel, Skeleton } from '../ui/primitives';
import type { ConversationMetadata } from '../../lib/types';

function formatTimestamp(value?: string | null): string {
    if (!value) {
        return '';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return String(value);
    }
    return parsed.toLocaleString();
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <div className="flex gap-3 py-1.5">
            <dt className="w-36 shrink-0 text-xs text-text-3">{label}</dt>
            <dd className="min-w-0 flex-1 text-sm break-words text-text-1">{children}</dd>
        </div>
    );
}

function classificationList(value: ConversationMetadata['classification']): string[] {
    if (Array.isArray(value)) {
        return value.map(String).filter(Boolean);
    }
    if (typeof value === 'string' && value.trim()) {
        return [value.trim()];
    }
    return [];
}

/** Tags are heterogeneous records; render only ones that can produce a readable label. */
function tagLabel(tag: Record<string, unknown>): string {
    const label = tag.label ?? tag.value ?? tag.title ?? tag.name;
    return label ? String(label) : '';
}

function TitleEditor({ metadata }: { metadata: ConversationMetadata }) {
    const { renameConversation, loadMetadata } = useChatStore();
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(metadata.title);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        setDraft(metadata.title);
    }, [metadata.title]);

    const commit = async () => {
        const trimmed = draft.trim();
        if (!trimmed || trimmed === metadata.title) {
            setDraft(metadata.title);
            setEditing(false);
            return;
        }
        setSaving(true);
        await renameConversation(metadata.conversation_id, trimmed);
        // Re-read so the panel reflects what was actually stored rather than the draft.
        await loadMetadata(metadata.conversation_id);
        setSaving(false);
        setEditing(false);
    };

    if (!editing) {
        return (
            <div className="flex items-start gap-2">
                <span className="min-w-0 flex-1 break-words">{metadata.title}</span>
                <button
                    type="button"
                    onClick={() => setEditing(true)}
                    aria-label="Rename conversation"
                    className="shrink-0 rounded-md p-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    <Pencil size={13} />
                </button>
            </div>
        );
    }

    return (
        <div className="flex items-center gap-1.5">
            <input
                autoFocus
                value={draft}
                disabled={saving}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                        void commit();
                    }
                    if (event.key === 'Escape') {
                        setDraft(metadata.title);
                        setEditing(false);
                    }
                }}
                aria-label="Conversation title"
                className="min-w-0 flex-1 rounded-lg border border-accent bg-surface-solid px-2 py-1 text-sm text-text-1 outline-none"
            />
            <button
                type="button"
                onClick={() => void commit()}
                disabled={saving}
                aria-label="Save title"
                className="shrink-0 rounded-md p-1 text-accent transition-colors hover:bg-surface-2"
            >
                <Check size={15} />
            </button>
        </div>
    );
}

export function ConversationDetails({ onClose }: { onClose: () => void }) {
    const { metadata, metadataLoading, metadataError, activeConversationId, loadMetadata } =
        useChatStore();

    useEffect(() => {
        if (activeConversationId && !metadata && !metadataLoading && !metadataError) {
            void loadMetadata(activeConversationId);
        }
    }, [activeConversationId, metadata, metadataLoading, metadataError, loadMetadata]);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    const classifications = metadata ? classificationList(metadata.classification) : [];
    const tags = (metadata?.tags ?? [])
        .map((tag) => (tag && typeof tag === 'object' ? tagLabel(tag) : ''))
        .filter(Boolean);

    const documentCount = metadata
        ? new Set(
              [
                  ...(metadata.used_documents ?? []),
                  ...(metadata.legacy_used_documents ?? []),
                  ...(metadata.linked_workspace_documents ?? []),
              ]
                  .map((document) => String(document?.document_id ?? '').trim())
                  .filter(Boolean),
          ).size
        : 0;

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Conversation details"
        >
            <div
                className="absolute inset-0 bg-black/40"
                aria-hidden="true"
                onClick={onClose}
            />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex max-h-[80vh] w-full max-w-xl flex-col"
            >
                <div className="flex h-14 shrink-0 items-center border-b border-edge px-5">
                    <h2 className="text-[15px] font-semibold text-text-1">
                        Conversation details
                    </h2>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close details"
                        className="ml-auto rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={17} />
                    </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                    {metadataLoading && !metadata && (
                        <div className="space-y-2">
                            {Array.from({ length: 6 }).map((_, index) => (
                                <Skeleton key={index} className="h-6 w-full" />
                            ))}
                        </div>
                    )}

                    {metadataError && (
                        <p className="flex items-start gap-2 text-sm text-danger">
                            <TriangleAlert size={16} className="mt-0.5 shrink-0" />
                            {metadataError}
                        </p>
                    )}

                    {metadata && (
                        <dl className="divide-y divide-edge">
                            <Row label="Title">
                                <TitleEditor metadata={metadata} />
                            </Row>

                            <Row label="Identifier">
                                <code className="font-mono text-xs break-all text-text-2">
                                    {metadata.conversation_id}
                                </code>
                            </Row>

                            {metadata.last_updated && (
                                <Row label="Last updated">
                                    {formatTimestamp(metadata.last_updated)}
                                </Row>
                            )}

                            {metadata.chat_type && <Row label="Type">{metadata.chat_type}</Row>}

                            {metadata.workflow_id && (
                                <Row label="Workflow">
                                    <code className="font-mono text-xs break-all text-text-2">
                                        {metadata.workflow_id}
                                    </code>
                                </Row>
                            )}

                            <Row label="State">
                                <div className="flex flex-wrap items-center gap-1.5">
                                    <span
                                        className={clsx(
                                            'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs',
                                            metadata.is_pinned
                                                ? 'bg-accent-soft text-accent'
                                                : 'bg-surface-sunken text-text-3',
                                        )}
                                    >
                                        <Pin size={11} />
                                        {metadata.is_pinned ? 'Pinned' : 'Not pinned'}
                                    </span>
                                    <span
                                        className={clsx(
                                            'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs',
                                            metadata.is_hidden
                                                ? 'bg-warn-soft text-warn'
                                                : 'bg-surface-sunken text-text-3',
                                        )}
                                    >
                                        {metadata.is_hidden ? (
                                            <EyeOff size={11} />
                                        ) : (
                                            <Eye size={11} />
                                        )}
                                        {metadata.is_hidden ? 'Hidden' : 'Visible'}
                                    </span>
                                    {metadata.scope_locked && (
                                        <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-xs text-warn">
                                            <Lock size={11} />
                                            Scope locked
                                        </span>
                                    )}
                                    {metadata.strict && (
                                        <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-xs text-text-3">
                                            Strict
                                        </span>
                                    )}
                                </div>
                            </Row>

                            {classifications.length > 0 && (
                                <Row label="Classification">
                                    <div className="flex flex-wrap gap-1.5">
                                        {classifications.map((entry) => (
                                            <span
                                                key={entry}
                                                className="rounded-full border border-edge bg-surface-2 px-2 py-0.5 text-xs"
                                            >
                                                {entry}
                                            </span>
                                        ))}
                                    </div>
                                </Row>
                            )}

                            {tags.length > 0 && (
                                <Row label="Tags">
                                    <div className="flex flex-wrap gap-1.5">
                                        {tags.map((tag) => (
                                            <span
                                                key={tag}
                                                className="rounded-full border border-edge bg-surface-2 px-2 py-0.5 text-xs"
                                            >
                                                {tag}
                                            </span>
                                        ))}
                                    </div>
                                </Row>
                            )}

                            <Row label="Documents used">
                                {documentCount === 0
                                    ? 'None'
                                    : `${documentCount} document${documentCount === 1 ? '' : 's'}`}
                            </Row>

                            {(metadata.locked_contexts ?? []).length > 0 && (
                                <Row label="Locked contexts">
                                    {(metadata.locked_contexts ?? []).length} context(s)
                                </Row>
                            )}

                            {metadata.summary?.text && (
                                <Row label="Summary">
                                    <p className="whitespace-pre-wrap">{metadata.summary.text}</p>
                                    {(metadata.summary.generated_at ||
                                        metadata.summary.model_deployment) && (
                                        <p className="mt-1 text-xs text-text-3">
                                            {[
                                                metadata.summary.model_deployment,
                                                formatTimestamp(metadata.summary.generated_at),
                                            ]
                                                .filter(Boolean)
                                                .join(' · ')}
                                        </p>
                                    )}
                                </Row>
                            )}
                        </dl>
                    )}
                </div>
            </GlassPanel>
        </div>
    );
}
