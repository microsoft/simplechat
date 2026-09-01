// types.ts
// Shapes for the SimpleChat JSON APIs the V2 UI consumes.
//
// These mirror what the Flask routes actually return, verified against
// route_backend_conversations.py, route_backend_chats.py and functions_conversation_feed.py.
// Objects that carry far more server-side detail than the UI needs are typed loosely with
// an index signature rather than being modelled exhaustively, so a backend addition never
// breaks the build.

export type Json = Record<string, unknown>;

export interface Conversation {
    id: string;
    title: string;
    last_updated?: string;
    created_at?: string;
    /** Server field name. Pin state is toggled server-side, not set by the client. */
    is_pinned?: boolean;
    is_hidden?: boolean;
    /** Set when an assistant reply arrived that the user has not seen yet. */
    has_unread_assistant_response?: boolean;
    classification?: string | string[] | null;
    /** 'collaborative' conversations live in a different container and have their own APIs. */
    conversation_kind?: string;
    [key: string]: unknown;
}

/** Response shape of GET /api/conversations/feed. */
export interface ConversationFeedPage {
    success: boolean;
    conversations: Conversation[];
    has_more: boolean;
    next_cursor: string | null;
    page_size: number;
    hidden_count: number;
    priority_count: number;
    recent_count: number;
    source_offsets: Record<string, number>;
    search_term?: string;
    include_hidden?: boolean;
}

export type MessageRole = 'user' | 'assistant' | 'system' | 'safety' | 'image';

export interface ChatMessage {
    id: string;
    conversation_id: string;
    role: MessageRole;
    content: string;
    timestamp?: string;
    model_deployment_name?: string;
    agent_display_name?: string;
    augmented?: boolean;
    metadata?: Json;
    /**
     * Image messages carry their image in `content`, not in a dedicated field.
     *
     * `hydrate_image_messages` (functions_image_messages.py) rewrites `content` to either a
     * `data:image/...` URI for small inline images or the path `/api/image/<message_id>` when
     * the bytes live in blob storage or exceed the inline limit. An externally hosted image
     * arrives as a plain http(s) URL. There is no `image_url` key on the payload.
     */
    /** Set locally when the user rates a response, so the control reflects their choice. */
    feedbackType?: 'positive' | 'negative';
    /** Reasoning steps captured while this message was streaming. */
    thoughts?: ThoughtEntry[];
    [key: string]: unknown;
}

export interface ModelOption {
    /** Value posted back as `model_deployment`. */
    option_value?: string;
    selection_key?: string;
    deployment_name?: string;
    display_name?: string;
    model_endpoint_id?: string;
    [key: string]: unknown;
}

export interface AgentOption {
    name?: string;
    display_name?: string;
    scope_type?: string;
    description?: string;
    selection_key?: string;
    [key: string]: unknown;
}

export interface PromptOption {
    id?: string;
    name?: string;
    content?: string;
    scope_type?: string;
    [key: string]: unknown;
}

export interface WorkspaceDocument {
    id?: string;
    document_id?: string;
    file_name?: string;
    title?: string;
    percentage_complete?: number;
    status?: string;
    document_classification?: string;
    tags?: string[] | string;
    version?: number;
    num_chunks?: number;
    upload_date?: string;
    [key: string]: unknown;
}

/**
 * A workspace tag as returned by /api/documents/tags.
 *
 * build_workspace_tags_from_counts returns objects, not strings:
 * [{'name': 'tag1', 'count': 5, 'color': '#3b82f6'}, ...]
 */
export interface WorkspaceTag {
    name: string;
    count?: number;
    color?: string;
}

/** Where a cited document lives, from functions_citation_tracking._scope_from_citation. */
export interface UsedDocumentScope {
    type?: 'personal' | 'group' | 'public' | string;
    id?: string;
    name?: string;
}

/**
 * A document-level citation aggregate, as built by
 * functions_citation_tracking.build_used_documents and stored on the conversation.
 */
export interface UsedDocument {
    category?: string;
    document_id: string;
    title?: string;
    file_name?: string;
    classification?: string;
    scope?: UsedDocumentScope;
    chunk_ids?: string[];
    citation_ids?: string[];
    page_numbers?: (number | string)[];
    sheet_names?: string[];
    citation_locations?: Array<Record<string, unknown>>;
    [key: string]: unknown;
}

/**
 * Generated conversation summary, present once one has been produced.
 *
 * The body is under `content`, not `text` (route_backend_conversation_export.py builds
 * `{'content', 'model_deployment', 'generated_at', 'message_time_start',
 * 'message_time_end'}`).
 */
export interface ConversationSummary {
    content?: string;
    generated_at?: string;
    model_deployment?: string;
    message_time_start?: string;
    message_time_end?: string;
    [key: string]: unknown;
}

/**
 * Response of GET /api/conversations/<id>/metadata.
 *
 * Field names are taken from the route itself. Note the identifier key is
 * `conversation_id`, not `id`, and the response carries no `created_at`, `participants`
 * or permission flags.
 */
export interface ConversationMetadata {
    conversation_id: string;
    title: string;
    user_id?: string;
    last_updated?: string;
    classification?: string[] | string;
    context?: unknown[];
    tags?: Array<Record<string, unknown>>;
    used_documents_tracking_version?: number | null;
    legacy_used_documents?: UsedDocument[];
    used_documents?: UsedDocument[];
    strict?: boolean;
    is_pinned?: boolean;
    is_hidden?: boolean;
    has_unread_assistant_response?: boolean;
    last_unread_assistant_message_id?: string | null;
    last_unread_assistant_at?: string | null;
    scope_locked?: boolean | null;
    locked_contexts?: unknown[];
    chat_type?: string | null;
    workflow_id?: string | null;
    summary?: ConversationSummary | null;
    linked_workspace_documents?: UsedDocument[];
    [key: string]: unknown;
}

export interface AdminNavSection {
    id: string;
    label: string;
    icon?: string;
}

export interface AdminNavTab {
    id: string;
    label: string;
    icon?: string;
    sections: AdminNavSection[];
}

export interface AdminNavGroup {
    id: string;
    label: string;
    icon?: string;
    tabs: AdminNavTab[];
}

export interface WorkspaceRef {
    id: string;
    name: string;
}

/** Response shape of GET /api/v2/bootstrap. Assembled by route_backend_v2.py. */
export interface BootstrapPayload {
    version: string;
    user: {
        id: string;
        display_name: string;
        email?: string;
        is_admin: boolean;
        roles: string[];
    };
    branding: {
        app_title: string;
        hide_app_title: boolean;
        show_logo: boolean;
        logo_url: string | null;
        logo_dark_url: string | null;
        classification_banner: {
            enabled: boolean;
            text?: string;
            color?: string;
            text_color?: string;
        } | null;
    };
    features: Record<string, boolean>;
    catalogs: {
        models: ModelOption[];
        agents: AgentOption[];
        prompts: PromptOption[];
        initial_model_selection: ModelOption | null;
    };
    scope: {
        active_group_id: string | null;
        active_group_name: string | null;
        active_public_workspace_id: string | null;
        groups: WorkspaceRef[];
        public_workspaces: WorkspaceRef[];
    };
    admin_nav: AdminNavGroup[];
    /** Sanitized settings. Never contains keys, secrets or connection strings. */
    settings: Json;
}

/**
 * A single decoded SSE frame from POST /api/chat/stream.
 *
 * The server emits `data: {json}\n\n` with the discriminator carried *inside* the JSON as
 * `type`, rather than using SSE `event:` lines. Content deltas and the terminal frame are
 * signalled by the presence of `content` / `done` rather than by a `type` value, which is
 * why almost everything here is optional.
 */
export interface ChatStreamEvent {
    type?:
        | 'thought'
        | 'conversation_metadata'
        | 'user_message_persisted'
        | 'cancelled'
        | 'canceled'
        | string;
    content?: string;
    done?: boolean;
    error?: string;
    partial_content?: string;
    cancelled?: boolean;
    canceled?: boolean;
    conversation_id?: string;
    conversation_title?: string;
    message_id?: string;
    user_message_id?: string;
    message_persisted?: boolean;
    conversation_kind?: string;
    model_deployment_name?: string;
    agent_display_name?: string;
    augmented?: boolean;
    metadata?: Json;
    [key: string]: unknown;
}

/** Request body for POST /api/chat/stream. Field names verified against the Flask route. */
export interface ChatStreamRequest {
    message: string;
    conversation_id?: string | null;
    chat_type?: string;
    model_deployment?: string;
    model_endpoint_id?: string;
    agent_selection?: string;
    reasoning_effort?: string;
    hybrid_search?: boolean;
    web_search_enabled?: boolean;
    image_generation?: boolean;
    /** Deep research. Both fields are sent together, matching the existing client. */
    source_review_enabled?: boolean;
    deep_research_enabled?: boolean;
    url_access_enabled?: boolean;
    doc_scope?: string;
    selected_document_id?: string | null;
    selected_document_ids?: string[];
    active_group_id?: string | null;
    active_group_ids?: string[];
    active_public_workspace_id?: string | null;
    active_public_workspace_ids?: string[];
    [key: string]: unknown;
}

export interface Citation {
    citation_id?: string;
    cited_text?: string;
    file_name?: string;
    page_number?: number | string;
    [key: string]: unknown;
}

/** A single reasoning step surfaced by a `type: "thought"` stream frame. */
export interface ThoughtEntry {
    id: string;
    title: string;
    content: string;
}
