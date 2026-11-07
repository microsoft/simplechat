// conversationDetails.ts
// Organising what GET /api/conversations/<id>/metadata returns into presentable groups.
//
// The route's `tags` array is heterogeneous: every entry has a `category`, and the useful
// fields differ per category (`route_backend_conversations.py`). Flattening them into one
// list is what made documents appear mixed in with everything else, so they are split here
// and each category is presented on its own terms.

import type { ConversationMetadata, UsedDocument } from './types';

/** Categories the server puts on a conversation tag. */
export type TagCategory =
    | 'document'
    | 'model'
    | 'agent'
    | 'participant'
    | 'semantic'
    | 'web';

type Bag = Record<string, unknown>;

function text(value: unknown): string {
    if (typeof value === 'string') {
        return value.trim();
    }
    if (typeof value === 'number') {
        return String(value);
    }
    return '';
}

function tags(metadata: ConversationMetadata | null | undefined): Bag[] {
    return Array.isArray(metadata?.tags) ? (metadata.tags as Bag[]) : [];
}

/** Tags of one category, in the order the server returned them. */
export function tagsOfCategory(
    metadata: ConversationMetadata | null | undefined,
    category: TagCategory,
): Bag[] {
    return tags(metadata).filter((tag) => text(tag?.category) === category);
}

/**
 * Readable label for a tag.
 *
 * `value` is the display field for most categories; participants carry a name instead, and
 * documents a title. Anything that cannot produce a label is dropped rather than rendered
 * as an empty chip.
 */
export function tagLabel(tag: Bag): string {
    return (
        text(tag.value) ||
        text(tag.display_name) ||
        text(tag.name) ||
        text(tag.title) ||
        text(tag.email)
    );
}

/** Distinct labels for a category, de-duplicated and stripped of unlabelled entries. */
export function labelsOfCategory(
    metadata: ConversationMetadata | null | undefined,
    category: TagCategory,
): string[] {
    const seen = new Set<string>();
    for (const tag of tagsOfCategory(metadata, category)) {
        const label = tagLabel(tag);
        if (label) {
            seen.add(label);
        }
    }
    return [...seen];
}

/** A web source cited somewhere in the conversation. */
export interface WebSource {
    label: string;
    /** Only set when the value is a safe http(s) URL. */
    href?: string;
}

/**
 * Web tags, with only http(s) values treated as links.
 *
 * A tag value originates in model output, so it is scheme-checked before it can become a
 * live link.
 */
export function webSources(metadata: ConversationMetadata | null | undefined): WebSource[] {
    return labelsOfCategory(metadata, 'web').map((label) => ({
        label,
        href: /^https?:\/\//i.test(label) ? label : undefined,
    }));
}

export interface DocumentSummary {
    documentId: string;
    title: string;
    classification?: string;
    scopeType?: string;
    scopeName?: string;
    /** How many chunks of this document were returned. */
    chunkCount: number;
    /** Pages or sheets the citations point at. */
    locations: string[];
    /** True when the document was actually cited by a response, not merely returned. */
    cited: boolean;
}

function readDocument(entry: Bag): DocumentSummary | null {
    const documentId = text(entry.document_id) || text(entry.id);
    const title = text(entry.title) || text(entry.file_name) || documentId;
    if (!documentId && !title) {
        return null;
    }

    const scope = (entry.scope && typeof entry.scope === 'object' ? entry.scope : {}) as Bag;
    const chunkIds = Array.isArray(entry.chunk_ids) ? entry.chunk_ids : [];
    const citationIds = Array.isArray(entry.citation_ids) ? entry.citation_ids : [];

    const pages = Array.isArray(entry.page_numbers)
        ? entry.page_numbers.map(text).filter(Boolean).map((page) => `Page ${page}`)
        : [];
    const sheets = Array.isArray(entry.sheet_names)
        ? entry.sheet_names.map(text).filter(Boolean).map((sheet) => `Sheet ${sheet}`)
        : [];

    return {
        documentId,
        title,
        classification: text(entry.classification) || undefined,
        scopeType: text(scope.type) || undefined,
        scopeName: text(scope.name) || undefined,
        chunkCount: chunkIds.length,
        locations: [...pages, ...sheets],
        cited: citationIds.length > 0,
    };
}

export interface SourceDocuments {
    documents: DocumentSummary[];
    /**
     * Whether the conversation recorded which documents were actually cited.
     *
     * Conversations predating citation tracking cannot distinguish "returned" from "cited",
     * and saying so is more honest than showing every document as uncited.
     */
    citationTracked: boolean;
}

/**
 * The documents a conversation drew on.
 *
 * `used_documents` is authoritative once `used_documents_tracking_version` is at least 1.
 * Older conversations fall back to `legacy_used_documents`, and older ones still to the
 * document tags, which is the same order the classic client uses.
 */
export function readSourceDocuments(
    metadata: ConversationMetadata | null | undefined,
): SourceDocuments {
    const version = Number(metadata?.used_documents_tracking_version ?? 0);
    const tracked = version >= 1;

    const primary = (metadata?.used_documents ?? []) as unknown as Bag[];
    const legacy = (metadata?.legacy_used_documents ?? []) as unknown as Bag[];
    const fromTags = tagsOfCategory(metadata, 'document');

    const source =
        tracked && primary.length > 0
            ? primary
            : legacy.length > 0
              ? legacy
              : fromTags.length > 0
                ? fromTags
                : primary;

    const byId = new Map<string, DocumentSummary>();
    for (const entry of source) {
        const parsed = readDocument(entry);
        if (!parsed) {
            continue;
        }
        const key = parsed.documentId || parsed.title;
        const existing = byId.get(key);
        if (!existing) {
            byId.set(key, parsed);
            continue;
        }
        // The same document can appear more than once; merge rather than list it twice.
        byId.set(key, {
            ...existing,
            chunkCount: existing.chunkCount + parsed.chunkCount,
            locations: [...new Set([...existing.locations, ...parsed.locations])],
            cited: existing.cited || parsed.cited,
        });
    }

    return { documents: [...byId.values()], citationTracked: tracked };
}

/** Documents linked to the conversation but not necessarily cited by it. */
export function readLinkedDocuments(
    metadata: ConversationMetadata | null | undefined,
): DocumentSummary[] {
    const linked = (metadata?.linked_workspace_documents ?? []) as unknown as Bag[];
    return linked
        .map(readDocument)
        .filter((entry): entry is DocumentSummary => entry !== null);
}

export interface ContextEntry {
    type: string;
    scope: string;
    name: string;
    id: string;
}

/** Workspaces the conversation is bound to, primary first. */
export function readContexts(
    metadata: ConversationMetadata | null | undefined,
): ContextEntry[] {
    const raw = Array.isArray(metadata?.context) ? (metadata.context as Bag[]) : [];
    return raw
        .map((entry) => ({
            type: text(entry?.type) || 'secondary',
            scope: text(entry?.scope),
            name: text(entry?.name),
            id: text(entry?.id),
        }))
        .filter((entry) => entry.scope || entry.name || entry.id)
        .sort((left, right) =>
            left.type === right.type ? 0 : left.type === 'primary' ? -1 : 1,
        );
}

/**
 * Workspaces whose scope is locked to this conversation.
 *
 * `locked_contexts` carries only a scope and an id, so the name is resolved from the
 * conversation's own contexts where one is available.
 */
export function readLockedContexts(
    metadata: ConversationMetadata | null | undefined,
): string[] {
    const locked = Array.isArray(metadata?.locked_contexts)
        ? (metadata.locked_contexts as Bag[])
        : [];
    if (locked.length === 0) {
        return [];
    }

    const named = new Map(
        readContexts(metadata).map((entry) => [`${entry.scope}:${entry.id}`, entry.name]),
    );

    return locked
        .map((entry) => {
            const scope = text(entry?.scope);
            const id = text(entry?.id);
            return named.get(`${scope}:${id}`) || id || scope;
        })
        .filter(Boolean);
}

/** Human label for a chat_type value. */
export function formatChatType(value: string | null | undefined): string {
    const raw = text(value);
    if (!raw) {
        return '';
    }
    switch (raw) {
        case 'personal':
        case 'personal_single_user':
            return 'Personal';
        case 'personal_multi_user':
            return 'Shared';
        case 'group':
        case 'group-single-user':
            return 'Group workspace';
        case 'public':
            return 'Public workspace';
        default:
            return raw.replace(/[-_]/g, ' ').replace(/^./, (first) => first.toUpperCase());
    }
}

export type { UsedDocument };
