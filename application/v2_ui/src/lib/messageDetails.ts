// messageDetails.ts
// Turning a message's diagnostics into something presentable.
//
// `GET /api/message/<id>/metadata` answers with a DIFFERENT shape depending on the message's
// role (route_frontend_conversations.py):
//
//   - a **user** message returns its nested `metadata` object alone
//   - assistant, image and file messages return the **whole document**, with role, model,
//     citations and so on at the top level and `metadata` nested inside
//
// Everything here reads both, so a caller never has to know which it received.

import type { AgentCitation, HybridCitation, Json, WebCitation } from './types';

type Bag = Record<string, unknown>;

function bag(value: unknown): Bag {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Bag) : {};
}

function text(value: unknown): string {
    if (value === null || value === undefined) {
        return '';
    }
    if (typeof value === 'string') {
        return value.trim();
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value);
    }
    return '';
}

/** One labelled fact in a details group. */
export interface DetailRow {
    label: string;
    value: string;
    /** Rendered as a monospace identifier rather than prose. */
    mono?: boolean;
}

export interface DetailGroup {
    title: string;
    rows: DetailRow[];
}

/**
 * The nested `metadata` object, wherever it happens to live.
 *
 * A user message's response *is* that object; every other role nests it one level down.
 */
function innerMetadata(payload: Json | null | undefined): Bag {
    const root = bag(payload);
    const nested = bag(root.metadata);
    return Object.keys(nested).length > 0 ? nested : root;
}

/** True when the payload is a whole message document rather than a bare metadata object. */
function isFullDocument(payload: Json | null | undefined): boolean {
    const root = bag(payload);
    return typeof root.role === 'string' && Boolean(root.role);
}

function pushRow(rows: DetailRow[], label: string, value: unknown, mono = false): void {
    const rendered = text(value);
    if (rendered) {
        rows.push({ label, value: rendered, mono });
    }
}

function formatBoolean(value: unknown): string {
    if (value === true) {
        return 'Yes';
    }
    if (value === false) {
        return 'No';
    }
    return '';
}

function formatTimestamp(value: unknown): string {
    const raw = text(value);
    if (!raw) {
        return '';
    }
    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleString();
}

/**
 * Describe how the conversation history was assembled for this message.
 *
 * This is the most useful part of the payload and the least discoverable: it records how
 * many earlier messages were kept, summarised, or dropped because they were an inactive
 * attempt or were masked. It explains why an answer did or did not have the context a user
 * expected.
 */
function historyGroup(metadata: Bag): DetailGroup | null {
    const history = bag(metadata.history_context);
    if (Object.keys(history).length === 0) {
        return null;
    }

    const rows: DetailRow[] = [];
    pushRow(rows, 'Path', history.path);
    pushRow(rows, 'Messages stored', history.stored_total_messages);
    pushRow(rows, 'History limit', history.history_limit);
    pushRow(rows, 'Recent messages used', history.recent_message_count);
    pushRow(rows, 'Older messages', history.older_message_count);
    pushRow(rows, 'Sent to the model', history.final_api_message_count);
    pushRow(rows, 'Summary requested', formatBoolean(history.summary_requested));
    pushRow(rows, 'Summary used', formatBoolean(history.summary_used));
    pushRow(
        rows,
        'Default system prompt inserted',
        formatBoolean(history.default_system_prompt_inserted),
    );

    const skippedInactive = Array.isArray(history.skipped_inactive_message_refs)
        ? history.skipped_inactive_message_refs.length
        : 0;
    const skippedMasked = Array.isArray(history.skipped_masked_message_refs)
        ? history.skipped_masked_message_refs.length
        : 0;
    if (skippedInactive) {
        rows.push({ label: 'Skipped as inactive attempts', value: String(skippedInactive) });
    }
    if (skippedMasked) {
        rows.push({ label: 'Skipped as masked', value: String(skippedMasked) });
    }

    return rows.length > 0 ? { title: 'History context', rows } : null;
}

/** What the message was allowed to do, and what it actually did. */
function capabilityGroup(metadata: Bag): DetailGroup | null {
    const usage = bag(metadata.capability_usage);
    if (Object.keys(usage).length === 0) {
        return null;
    }

    const rows: DetailRow[] = [];
    const workspace = bag(usage.workspace);
    pushRow(rows, 'Workspace action', workspace.action);

    const actions = bag(usage.actions);
    const used = ['search', 'analyze', 'compare'].filter((name) => actions[name] === true);
    if (Object.keys(actions).length > 0) {
        rows.push({
            label: 'Document actions',
            value: used.length > 0 ? used.join(', ') : 'None',
        });
    }

    // Enabled and used are tracked separately, and the difference is the interesting part:
    // a capability that was available but not exercised explains an answer without it.
    for (const [key, label] of [
        ['web_search', 'Web search'],
        ['deep_research', 'Deep research'],
    ] as const) {
        const entry = bag(usage[key]);
        if (Object.keys(entry).length === 0) {
            continue;
        }
        const enabled = entry.enabled === true;
        const wasUsed = entry.used === true;
        rows.push({
            label,
            value: !enabled ? 'Not enabled' : wasUsed ? 'Enabled and used' : 'Enabled, not used',
        });
    }

    return rows.length > 0 ? { title: 'Capabilities', rows } : null;
}

/** Build every group that has something to say about this message. */
export function buildDetailGroups(payload: Json | null | undefined): DetailGroup[] {
    const root = bag(payload);
    const metadata = innerMetadata(payload);
    const full = isFullDocument(payload);
    const groups: DetailGroup[] = [];

    const identity: DetailRow[] = [];
    if (full) {
        pushRow(identity, 'Message ID', root.id, true);
        pushRow(identity, 'Conversation ID', root.conversation_id, true);
        pushRow(identity, 'Role', root.role);
        pushRow(identity, 'Kind', root.message_kind);
        pushRow(identity, 'Timestamp', formatTimestamp(root.timestamp));
    }
    pushRow(identity, 'Original role', metadata.source_role);
    if (identity.length > 0) {
        groups.push({ title: 'Message', rows: identity });
    }

    const thread = bag(metadata.thread_info);
    if (Object.keys(thread).length > 0) {
        const rows: DetailRow[] = [];
        pushRow(rows, 'Thread ID', thread.thread_id, true);
        pushRow(rows, 'Previous thread', thread.previous_thread_id, true);
        pushRow(rows, 'Attempt', thread.thread_attempt);
        pushRow(rows, 'Active attempt', formatBoolean(thread.active_thread));
        if (rows.length > 0) {
            groups.push({ title: 'Retry thread', rows });
        }
    }

    const generation: DetailRow[] = [];
    pushRow(generation, 'Model', root.model_deployment_name);
    pushRow(generation, 'Agent', root.agent_display_name || root.agent_name);
    pushRow(generation, 'Augmented', formatBoolean(root.augmented));
    pushRow(generation, 'Reasoning effort', metadata.reasoning_effort);
    if (generation.length > 0) {
        groups.push({ title: 'Generation', rows: generation });
    }

    const capabilities = capabilityGroup(metadata);
    if (capabilities) {
        groups.push(capabilities);
    }

    // Image and file messages carry their own descriptive fields.
    const artifact: DetailRow[] = [];
    pushRow(artifact, 'File name', root.filename);
    pushRow(artifact, 'Prompt', root.prompt);
    pushRow(artifact, 'Tabular data', formatBoolean(root.is_table));
    if (artifact.length > 0) {
        groups.push({ title: 'File', rows: artifact });
    }

    const history = historyGroup(metadata);
    if (history) {
        groups.push(history);
    }

    return groups;
}

export interface MessageSources {
    documents: HybridCitation[];
    web: WebCitation[];
    tools: AgentCitation[];
    total: number;
}

/**
 * Citations recorded on an assistant message.
 *
 * These live at the top level of the message document, so they are present on the loaded
 * message list as well as on the metadata response, and do not need a separate request.
 */
export function readSources(source: Json | ChatMessageLike | null | undefined): MessageSources {
    const root = bag(source);
    const documents = Array.isArray(root.hybrid_citations)
        ? (root.hybrid_citations as HybridCitation[])
        : [];
    const web = Array.isArray(root.web_search_citations)
        ? (root.web_search_citations as WebCitation[])
        : [];
    const tools = Array.isArray(root.agent_citations)
        ? (root.agent_citations as AgentCitation[])
        : [];

    return {
        documents,
        web,
        tools,
        total: documents.length + web.length + tools.length,
    };
}

interface ChatMessageLike {
    [key: string]: unknown;
}

/** Label a document citation the way the classic client does. */
export function describeDocumentCitation(citation: HybridCitation): {
    title: string;
    location: string;
    isSummary: boolean;
} {
    const title = text(citation.file_name) || 'Document';
    const label = text(citation.location_label) || (citation.sheet_name ? 'Sheet' : 'Page');
    const value =
        text(citation.location_value) ||
        text(citation.sheet_name) ||
        text(citation.page_number);

    return {
        title,
        location: value ? `${label} ${value}` : '',
        // A metadata citation points at a document summary rather than a passage within it.
        isSummary: Boolean(text(citation.metadata_type)),
    };
}

/** Render a tool argument or result, which may arrive as an object or a string. */
export function renderToolValue(value: unknown): string {
    if (value === null || value === undefined || value === '') {
        return '';
    }
    if (typeof value === 'string') {
        return value;
    }
    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
}
