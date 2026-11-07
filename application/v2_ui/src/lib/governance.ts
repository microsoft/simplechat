// governance.ts
// The Admin Settings governance group: what each policy means, how it is read and saved,
// and the rules the editors apply before anything reaches the server.
//
// The server is the source of truth for enforcement (`functions_governance.py`). This file
// mirrors only what the editors need to show an honest picture before a save: how a policy
// state is normalized, who it lets through, whether a governance switch is actually being
// enforced given the feature it governs, and whether an MCP destination pattern can ever
// match anything.

import { ApiError, api } from './apiClient';
import { asBoolean } from './adminFields';
import type { Json } from './types';

const GOVERNANCE_API = '/api/admin/governance';

/* -------------------------------------------------------------------------- */
/* Principals                                                                  */
/* -------------------------------------------------------------------------- */

/** Who a policy lets through. Mirrors the shape the governance API stores. */
export interface GovernancePrincipals {
    allow_all: boolean;
    allowed_users: string[];
    allowed_groups: string[];
    denied_users: string[];
    denied_groups: string[];
}

export type PrincipalKind = 'users' | 'groups';

export const EMPTY_PRINCIPALS: GovernancePrincipals = {
    allow_all: true,
    allowed_users: [],
    allowed_groups: [],
    denied_users: [],
    denied_groups: [],
};

/** Trimmed, de-duplicated string ids, in their original order. */
export function normalizePrincipalIds(value: unknown): string[] {
    if (!Array.isArray(value)) {
        return [];
    }
    const seen = new Set<string>();
    const ids: string[] = [];
    for (const entry of value) {
        const id = typeof entry === 'string' ? entry.trim() : '';
        if (id && !seen.has(id)) {
            seen.add(id);
            ids.push(id);
        }
    }
    return ids;
}

/**
 * Split pasted ids, one per line or comma separated, the format the classic import took.
 */
export function parsePrincipalIdText(text: string): string[] {
    return normalizePrincipalIds(String(text || '').split(/[\r\n,;]+/));
}

/** Combine pasted ids with the current list, either adding to it or replacing it. */
export function applyPrincipalImport(current: string[], text: string, mode: 'merge' | 'replace'): string[] {
    const imported = parsePrincipalIdText(text);
    return mode === 'replace' ? imported : normalizePrincipalIds([...current, ...imported]);
}

/**
 * The state the server will store for a policy.
 *
 * Mirrors `_normalize_policy_state`: Allow all with people listed is read as a restricted
 * policy, because the list is the more specific statement of intent, and Allow all stores
 * empty allow lists.
 */
export function normalizePolicyState<T extends GovernancePrincipals>(policy: T): T {
    const allowedUsers = normalizePrincipalIds(policy.allowed_users);
    const allowedGroups = normalizePrincipalIds(policy.allowed_groups);
    const allowAll = Boolean(policy.allow_all) && !allowedUsers.length && !allowedGroups.length;
    return {
        ...policy,
        allow_all: allowAll,
        allowed_users: allowAll ? [] : allowedUsers,
        allowed_groups: allowAll ? [] : allowedGroups,
        denied_users: normalizePrincipalIds(policy.denied_users),
        denied_groups: normalizePrincipalIds(policy.denied_groups),
    };
}

/**
 * The payload an editor sends.
 *
 * The allow lists are kept in the editor while Allow all is on, so turning it off again
 * restores them, but they are never sent with it: the server would read a non-empty list as
 * "restricted" and quietly turn Allow all back off.
 */
export function principalsForSave(policy: GovernancePrincipals): GovernancePrincipals {
    return {
        allow_all: Boolean(policy.allow_all),
        allowed_users: policy.allow_all ? [] : normalizePrincipalIds(policy.allowed_users),
        allowed_groups: policy.allow_all ? [] : normalizePrincipalIds(policy.allowed_groups),
        denied_users: normalizePrincipalIds(policy.denied_users),
        denied_groups: normalizePrincipalIds(policy.denied_groups),
    };
}

function countLabel(count: number, singular: string, plural: string): string {
    return `${count} ${count === 1 ? singular : plural}`;
}

function describePrincipals(users: number, groups: number): string {
    const parts: string[] = [];
    if (users) {
        parts.push(countLabel(users, 'person', 'people'));
    }
    if (groups) {
        parts.push(countLabel(groups, 'group', 'groups'));
    }
    return parts.join(' · ');
}

/** True when nobody can pass: Allow all is off and nobody is listed. */
export function allowsNobody(policy: GovernancePrincipals): boolean {
    return !policy.allow_all && !normalizePrincipalIds(policy.allowed_users).length
        && !normalizePrincipalIds(policy.allowed_groups).length;
}

/** Who a policy lets through, as a short phrase. */
export function summarizeAllowed(policy: GovernancePrincipals): string {
    if (policy.allow_all) {
        return 'Everyone';
    }
    const described = describePrincipals(
        normalizePrincipalIds(policy.allowed_users).length,
        normalizePrincipalIds(policy.allowed_groups).length,
    );
    return described || 'Nobody';
}

/** Who a policy blocks, or null when it blocks nobody. */
export function summarizeBlocked(policy: GovernancePrincipals): string | null {
    const described = describePrincipals(
        normalizePrincipalIds(policy.denied_users).length,
        normalizePrincipalIds(policy.denied_groups).length,
    );
    return described || null;
}

function readPrincipals(raw: Record<string, unknown>): GovernancePrincipals {
    return normalizePolicyState({
        allow_all: raw.allow_all === undefined ? true : asBoolean(raw.allow_all),
        allowed_users: normalizePrincipalIds(raw.allowed_users),
        allowed_groups: normalizePrincipalIds(raw.allowed_groups),
        denied_users: normalizePrincipalIds(raw.denied_users),
        denied_groups: normalizePrincipalIds(raw.denied_groups),
    });
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

/* -------------------------------------------------------------------------- */
/* Feature policies                                                            */
/* -------------------------------------------------------------------------- */

export type GovernanceScope = 'personal' | 'group' | 'global';

export interface GovernanceFeature {
    /** The governance switch's settings key, which is also the feature policy's key. */
    key: string;
    label: string;
    scope: GovernanceScope;
    /** What passing the policy lets someone do. */
    summary: string;
    /** The feature the switch governs. Absent when the switch is always enforced. */
    primary?: { key: string; label: string; section: string };
    /** Enforced whatever any switch says. */
    alwaysEnforced?: boolean;
}

const ENABLE_AGENTS = { key: 'enable_semantic_kernel', label: 'Enable Agents', section: 'agents-config' };

/** Ordered personal, group, then global, which is how the policy list is grouped. */
export const GOVERNANCE_FEATURES: readonly GovernanceFeature[] = [
    {
        key: 'governance_user_endpoints',
        label: 'Personal Endpoints',
        scope: 'personal',
        summary: 'Add, test, and chat through model endpoints in their own workspace.',
        primary: { key: 'allow_user_custom_endpoints', label: 'Allow Personal Custom Endpoints', section: 'agent-toggles-card' },
    },
    {
        key: 'governance_user_agents',
        label: 'Personal Agents',
        scope: 'personal',
        summary: 'Create, edit, and chat with agents in their own workspace.',
        primary: { key: 'allow_user_agents', label: 'Allow Personal Agents', section: 'agent-toggles-card' },
    },
    {
        key: 'governance_user_actions',
        label: 'Personal Actions',
        scope: 'personal',
        summary: 'Create and run actions in their own workspace.',
        primary: { key: 'allow_user_plugins', label: 'Allow Personal Actions', section: 'plugin-feature-toggles' },
    },
    {
        key: 'governance_group_endpoints',
        label: 'Group Endpoints',
        scope: 'group',
        summary: 'Use and manage model endpoints in group workspaces.',
        primary: { key: 'allow_group_custom_endpoints', label: 'Allow Group Custom Endpoints', section: 'agent-toggles-card' },
    },
    {
        key: 'governance_group_agents',
        label: 'Group Agents',
        scope: 'group',
        summary: 'Use and manage the agents group workspaces share.',
        primary: { key: 'allow_group_agents', label: 'Allow Group Agents', section: 'agent-toggles-card' },
    },
    {
        key: 'governance_group_actions',
        label: 'Group Actions',
        scope: 'group',
        summary: 'Use and manage actions in group workspaces.',
        primary: { key: 'allow_group_plugins', label: 'Allow Group Actions', section: 'plugin-feature-toggles' },
    },
    {
        key: 'governance_global_endpoints',
        label: 'Global Endpoints',
        scope: 'global',
        summary: 'Use the shared AI connections.',
        alwaysEnforced: true,
    },
    {
        key: 'governance_global_agents_usage',
        label: 'Global Agents',
        scope: 'global',
        summary: 'Select and chat with agents the organization publishes.',
        primary: ENABLE_AGENTS,
    },
    {
        key: 'governance_global_actions_usage',
        label: 'Global Actions',
        scope: 'global',
        summary: 'Let agents use actions the organization publishes.',
        primary: ENABLE_AGENTS,
    },
];

export const GOVERNANCE_SCOPE_LABELS: Record<GovernanceScope, string> = {
    personal: 'Personal workspaces',
    group: 'Group workspaces',
    global: 'Shared across the organization',
};

/**
 * Whether a governance switch is doing anything.
 *
 * `waiting` is the fail-closed case: the switch is on, but the feature it governs is off,
 * so there is nothing to enforce yet. It applies as soon as the feature is turned on.
 */
export type FeatureEnforcementState = 'enforced' | 'off' | 'waiting';

export interface FeatureEnforcement {
    /** What is live now, from the saved settings. */
    state: FeatureEnforcementState;
    /** What an unsaved change would make it, when that differs. */
    pending?: FeatureEnforcementState;
}

function enforcementFrom(feature: GovernanceFeature, read: (key: string) => unknown): FeatureEnforcementState {
    if (feature.alwaysEnforced) {
        return 'enforced';
    }
    if (!asBoolean(read(feature.key))) {
        return 'off';
    }
    if (feature.primary && !asBoolean(read(feature.primary.key))) {
        return 'waiting';
    }
    return 'enforced';
}

/** Read a key preferring the unsaved draft, the way the rest of the page does. */
export function readDraftAware(settings: Json, draft: Json, key: string): unknown {
    return Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : settings[key];
}

export function describeFeatureEnforcement(
    feature: GovernanceFeature,
    settings: Json,
    draft: Json,
): FeatureEnforcement {
    const saved = enforcementFrom(feature, (key) => settings[key]);
    const next = enforcementFrom(feature, (key) => readDraftAware(settings, draft, key));
    return next === saved ? { state: saved } : { state: saved, pending: next };
}

export interface GovernanceFeaturePolicy extends GovernancePrincipals {
    feature_key: string;
    updated_at?: string;
}

export function readFeaturePolicy(raw: unknown): GovernanceFeaturePolicy | null {
    if (!isRecord(raw) || typeof raw.feature_key !== 'string' || !raw.feature_key.trim()) {
        return null;
    }
    return {
        feature_key: raw.feature_key.trim(),
        updated_at: typeof raw.updated_at === 'string' ? raw.updated_at : undefined,
        ...readPrincipals(raw),
    };
}

export async function fetchFeaturePolicies(signal?: AbortSignal): Promise<GovernanceFeaturePolicy[]> {
    const payload = await api.get<{ features?: unknown[] }>(`${GOVERNANCE_API}/policies`, signal);
    return (Array.isArray(payload?.features) ? payload.features : [])
        .map(readFeaturePolicy)
        .filter((policy): policy is GovernanceFeaturePolicy => policy !== null);
}

export async function saveFeaturePolicy(featureKey: string, principals: GovernancePrincipals): Promise<GovernanceFeaturePolicy | null> {
    const payload = await api.put<{ policy?: unknown }>(
        `${GOVERNANCE_API}/policies/${encodeURIComponent(featureKey)}`,
        principalsForSave(principals),
    );
    return readFeaturePolicy(payload?.policy);
}

/* -------------------------------------------------------------------------- */
/* Delegated item policies                                                     */
/* -------------------------------------------------------------------------- */

export type GovernanceEntityType =
    | 'global_endpoint'
    | 'global_agent'
    | 'global_action'
    | 'personal_action_type'
    | 'group_action_type'
    | 'global_action_type'
    | 'mcp_personal_destination'
    | 'mcp_group_destination'
    | 'mcp_global_destination'
    | 'inbound_mcp_source';

/** Where the editor finds the items a policy can target. */
export type GovernanceItemSource =
    | 'connections'
    | 'global_agents'
    | 'global_actions'
    | 'action_types'
    | 'mcp_pattern'
    | 'inbound_sources';

export interface GovernanceEntityTypeDefinition {
    value: GovernanceEntityType;
    label: string;
    source: GovernanceItemSource;
    /** What a policy of this type controls. */
    hint: string;
}

export const GOVERNANCE_ENTITY_TYPES: readonly GovernanceEntityTypeDefinition[] = [
    {
        value: 'global_endpoint',
        label: 'Global Endpoint',
        source: 'connections',
        hint: 'Narrows one shared AI connection to particular people or groups.',
    },
    {
        value: 'global_agent',
        label: 'Global Agent',
        source: 'global_agents',
        hint: 'Narrows one published agent. People must also pass the Global Agents feature policy.',
    },
    {
        value: 'global_action',
        label: 'Global Action',
        source: 'global_actions',
        hint: 'Narrows one published action. People must also pass the Global Actions feature policy.',
    },
    {
        value: 'personal_action_type',
        label: 'Personal Action Type',
        source: 'action_types',
        hint: 'Who may create and run one type of action in their own workspace. It can grant the type to people the Personal Actions feature policy leaves out.',
    },
    {
        value: 'group_action_type',
        label: 'Group Action Type',
        source: 'action_types',
        hint: 'Who may create and run one type of action in group workspaces.',
    },
    {
        value: 'global_action_type',
        label: 'Global Action Type',
        source: 'action_types',
        hint: 'Who may use published actions of one type.',
    },
    {
        value: 'mcp_personal_destination',
        label: 'MCP Personal Destination',
        source: 'mcp_pattern',
        hint: 'Which remote MCP servers personal workspace actions may reach, and for whom.',
    },
    {
        value: 'mcp_group_destination',
        label: 'MCP Group Destination',
        source: 'mcp_pattern',
        hint: 'Which remote MCP servers group workspace actions may reach, for every group or one.',
    },
    {
        value: 'mcp_global_destination',
        label: 'MCP Global Destination',
        source: 'mcp_pattern',
        hint: 'Which remote MCP servers published actions may reach.',
    },
    {
        value: 'inbound_mcp_source',
        label: 'Inbound MCP Source',
        source: 'inbound_sources',
        hint: 'Who may use SimpleChat as an MCP server, from any accepted source or one.',
    },
];

export const MCP_DESTINATION_ENTITY_TYPES: readonly GovernanceEntityType[] = [
    'mcp_personal_destination',
    'mcp_group_destination',
    'mcp_global_destination',
];

export const INBOUND_MCP_SOURCE_ENTITY_TYPE: GovernanceEntityType = 'inbound_mcp_source';

/** The system policy runtime evaluation ignores; see `functions_mcp_server_governance.py`. */
export const INBOUND_MCP_SYSTEM_SOURCE_POLICY_ID = 'system-allow-all-sources';

const LEGACY_ENTITY_TYPE_ALIASES: Record<string, GovernanceEntityType> = {
    endpoint: 'global_endpoint',
};

export function normalizeEntityType(value: unknown): GovernanceEntityType | null {
    const candidate = String(value ?? '').trim().toLowerCase();
    const resolved = LEGACY_ENTITY_TYPE_ALIASES[candidate] ?? candidate;
    return GOVERNANCE_ENTITY_TYPES.some((type) => type.value === resolved)
        ? (resolved as GovernanceEntityType)
        : null;
}

export function entityTypeDefinition(value: unknown): GovernanceEntityTypeDefinition | undefined {
    const normalized = normalizeEntityType(value);
    return GOVERNANCE_ENTITY_TYPES.find((type) => type.value === normalized);
}

export function entityTypeLabel(value: unknown): string {
    return entityTypeDefinition(value)?.label ?? String(value ?? '');
}

export function isMcpDestinationEntityType(value: unknown): boolean {
    const normalized = normalizeEntityType(value);
    return normalized !== null && MCP_DESTINATION_ENTITY_TYPES.includes(normalized);
}

/** Matches the name the classic page suggests, so both interfaces read the same. */
export function defaultItemPolicyName(entityType: unknown, itemId: string, resourceLabel = ''): string {
    const label = (resourceLabel || itemId || 'Resource').trim();
    return `${label} ${entityTypeLabel(entityType) || 'Delegated Item'} Policy`;
}

export interface GovernanceItemPolicy extends GovernancePrincipals {
    entity_type: string;
    item_id: string;
    policy_id: string;
    policy_name: string;
    resource_label: string;
    system_managed: boolean;
    managed_reason: string;
    updated_at?: string;
}

export function readItemPolicy(raw: unknown): GovernanceItemPolicy | null {
    if (!isRecord(raw)) {
        return null;
    }
    const entityType = String(raw.entity_type ?? '').trim();
    const itemId = String(raw.item_id ?? '').trim();
    if (!entityType || !itemId) {
        return null;
    }
    const resourceLabel = String(raw.resource_label ?? '').trim();
    return {
        entity_type: normalizeEntityType(entityType) ?? entityType,
        item_id: itemId,
        policy_id: String(raw.policy_id ?? '').trim(),
        policy_name: String(raw.policy_name ?? '').trim() || defaultItemPolicyName(entityType, itemId, resourceLabel),
        resource_label: resourceLabel,
        system_managed: asBoolean(raw.system_managed),
        managed_reason: String(raw.managed_reason ?? '').trim(),
        updated_at: typeof raw.updated_at === 'string' ? raw.updated_at : undefined,
        ...readPrincipals(raw),
    };
}

/** What the item policy editor holds. `original` is set when editing a saved policy. */
export interface ItemPolicyDraft extends GovernancePrincipals {
    entity_type: GovernanceEntityType;
    item_id: string;
    resource_label: string;
    policy_name: string;
    policy_id: string;
    original?: { entity_type: string; item_id: string; policy_id: string };
}

/** A blank draft for a new policy, optionally aimed at one target. */
export function newItemPolicyDraft(preset: Partial<ItemPolicyDraft> & { entity_type: GovernanceEntityType }): ItemPolicyDraft {
    return {
        ...EMPTY_PRINCIPALS,
        item_id: '',
        resource_label: '',
        policy_name: '',
        policy_id: '',
        ...preset,
        original: undefined,
    };
}

/** A draft for editing a saved policy. */
export function draftFromItemPolicy(policy: GovernanceItemPolicy): ItemPolicyDraft {
    const entityType = normalizeEntityType(policy.entity_type) ?? 'global_agent';
    return {
        entity_type: entityType,
        item_id: policy.item_id,
        resource_label: policy.resource_label,
        policy_name: policy.policy_name,
        policy_id: policy.policy_id,
        allow_all: policy.allow_all,
        allowed_users: [...policy.allowed_users],
        allowed_groups: [...policy.allowed_groups],
        denied_users: [...policy.denied_users],
        denied_groups: [...policy.denied_groups],
        original: { entity_type: policy.entity_type, item_id: policy.item_id, policy_id: policy.policy_id },
    };
}

function withNameSuffix(name: string, suffix: string): string {
    return `${(name || 'Delegated Item Policy').trim()} (${suffix})`;
}

/** A new, unsaved copy of a policy. */
export function duplicateItemPolicy(policy: GovernanceItemPolicy): ItemPolicyDraft {
    return {
        ...draftFromItemPolicy(policy),
        policy_id: '',
        policy_name: withNameSuffix(policy.policy_name, 'copy'),
        original: undefined,
    };
}

/**
 * A new, unsaved copy with the allowed and blocked people swapped.
 *
 * "Everyone except A" becomes "only A", and "only A" becomes "everyone except A". The
 * classic page kept Allow all as it was, which turned the inverse of "only A" into a policy
 * nobody passes; deciding it from the swapped lists keeps the copy meaning the opposite.
 */
export function inverseItemPolicy(policy: GovernanceItemPolicy): ItemPolicyDraft {
    const allowedUsers = [...policy.denied_users];
    const allowedGroups = [...policy.denied_groups];
    const allowAll = !allowedUsers.length && !allowedGroups.length && !policy.allow_all;
    return {
        ...draftFromItemPolicy(policy),
        policy_id: '',
        policy_name: withNameSuffix(policy.policy_name, 'inverse'),
        allow_all: allowAll,
        allowed_users: allowedUsers,
        allowed_groups: allowedGroups,
        // A policy that allows everyone has empty allow lists, so this is empty for it.
        denied_users: [...policy.allowed_users],
        denied_groups: [...policy.allowed_groups],
        original: undefined,
    };
}

export interface ItemPolicyPagination {
    page: number;
    per_page: number;
    total_items: number;
    total_pages: number;
    has_prev: boolean;
    has_next: boolean;
}

export interface ItemPolicyPage {
    policies: GovernanceItemPolicy[];
    pagination: ItemPolicyPagination;
}

export interface ItemPolicyQuery {
    entityTypes?: readonly string[];
    itemId?: string;
    search?: string;
    page?: number;
    perPage?: number;
}

export const ITEM_POLICY_PAGE_SIZES = [10, 25, 50] as const;

export async function fetchItemPolicyPage(query: ItemPolicyQuery, signal?: AbortSignal): Promise<ItemPolicyPage> {
    const params = new URLSearchParams();
    if (query.entityTypes?.length) {
        params.set('entity_type', query.entityTypes.join(','));
    }
    if (query.itemId) {
        params.set('item_id', query.itemId);
    }
    if (query.search?.trim()) {
        params.set('search', query.search.trim());
    }
    params.set('page', String(Math.max(1, query.page ?? 1)));
    params.set('per_page', String(query.perPage ?? 25));

    const payload = await api.get<{ item_policies?: unknown[]; pagination?: Partial<ItemPolicyPagination> }>(
        `${GOVERNANCE_API}/item-policies/review?${params.toString()}`,
        signal,
    );
    const pagination = payload?.pagination ?? {};
    return {
        policies: (Array.isArray(payload?.item_policies) ? payload.item_policies : [])
            .map(readItemPolicy)
            .filter((policy): policy is GovernanceItemPolicy => policy !== null),
        pagination: {
            page: Number(pagination.page) || 1,
            per_page: Number(pagination.per_page) || query.perPage || 25,
            total_items: Number(pagination.total_items) || 0,
            total_pages: Number(pagination.total_pages) || 1,
            has_prev: Boolean(pagination.has_prev),
            has_next: Boolean(pagination.has_next),
        },
    };
}

/** Validate a draft before saving. Returns the first problem, or null. */
export function validateItemPolicyDraft(draft: ItemPolicyDraft): string | null {
    if (!normalizeEntityType(draft.entity_type)) {
        return 'Choose what this policy applies to.';
    }
    if (!draft.item_id.trim()) {
        return isMcpDestinationEntityType(draft.entity_type)
            ? 'Enter the destination pattern this policy allows.'
            : 'Choose the item this policy applies to.';
    }
    if (draft.original && draft.original.policy_id && draft.policy_id !== draft.original.policy_id) {
        return 'A saved policy keeps its policy ID.';
    }
    return null;
}

/** The request body for `POST /api/admin/governance/item-policies`. */
export function itemPolicyPayload(draft: ItemPolicyDraft): Record<string, unknown> {
    const itemId = draft.item_id.trim();
    const resourceLabel = draft.resource_label.trim() || (isMcpDestinationEntityType(draft.entity_type) ? itemId : '');
    const payload: Record<string, unknown> = {
        entity_type: draft.entity_type,
        item_id: itemId,
        policy_id: draft.policy_id.trim(),
        policy_name: draft.policy_name.trim() || defaultItemPolicyName(draft.entity_type, itemId, resourceLabel),
        resource_label: resourceLabel,
        ...principalsForSave(draft),
    };
    if (draft.original) {
        // Sent so a changed target moves the policy instead of copying it.
        payload.original_entity_type = draft.original.entity_type;
        payload.original_item_id = draft.original.item_id;
    }
    return payload;
}

export async function saveItemPolicy(draft: ItemPolicyDraft): Promise<GovernanceItemPolicy | null> {
    const payload = await api.post<{ policy?: unknown }>(`${GOVERNANCE_API}/item-policies`, itemPolicyPayload(draft));
    return readItemPolicy(payload?.policy);
}

export async function deleteItemPolicy(policy: Pick<GovernanceItemPolicy, 'entity_type' | 'item_id' | 'policy_id'>): Promise<void> {
    await api.post(`${GOVERNANCE_API}/item-policies/delete`, {
        entity_type: policy.entity_type,
        item_id: policy.item_id,
        policy_id: policy.policy_id,
    });
}

/** A readable sentence for a failed governance request. */
export function governanceErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof ApiError) {
        if (error.status === 409) {
            return 'This policy ID already governs a different item. Duplicate the policy instead of moving it.';
        }
        if (error.status === 403) {
            return 'System-managed policies cannot be changed here.';
        }
        if (error.status === 404) {
            return 'The policy no longer exists. Refresh the list and try again.';
        }
        return error.message || fallback;
    }
    return error instanceof Error && error.message ? error.message : fallback;
}

/* -------------------------------------------------------------------------- */
/* Action types                                                                */
/* -------------------------------------------------------------------------- */

/** Mirrors `ACTION_TYPE_ALIASES` in `functions_governance.py`. */
const ACTION_TYPE_ALIASES: Record<string, string> = {
    sql_query: 'sql',
    sql_schema: 'sql',
    simple_chat: 'simplechat',
    open_api: 'openapi',
    model_context_protocol: 'mcp',
    microsoft_graph: 'msgraph',
    msgraphplugin: 'msgraph',
    microsoftgraph: 'msgraph',
    microsoft_graph_plugin: 'msgraph',
    databricks_table: 'databricks',
    search: 'document_search',
};

/** Mirrors `ACTION_TYPE_LABELS`. */
const ACTION_TYPE_LABELS: Record<string, string> = {
    sql: 'SQL',
    simplechat: 'SimpleChat',
    agent: 'Call agent',
    openapi: 'OpenAPI',
    mcp: 'MCP',
    msgraph: 'Microsoft Graph (legacy)',
    m365_calendar: 'Microsoft 365 Calendar',
    m365_email: 'Microsoft 365 Email',
    m365_onedrive: 'Microsoft 365 OneDrive',
    m365_sharepoint: 'Microsoft 365 SharePoint Online',
    databricks: 'Databricks',
    snowflake: 'Snowflake',
    tableau: 'Tableau',
    yamcs: 'Yamcs',
    chart: 'Chart',
    azure_maps: 'Azure Maps',
    blob_storage: 'Blob Storage',
    document_search: 'Document Search',
    control_center: 'Control Center',
};

export function normalizeActionType(value: unknown): string {
    const normalized = String(value ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    return ACTION_TYPE_ALIASES[normalized] ?? normalized;
}

export function actionTypeLabel(value: unknown, fallback = ''): string {
    const normalized = normalizeActionType(value);
    if (!normalized) {
        return fallback || 'Unknown action type';
    }
    return ACTION_TYPE_LABELS[normalized]
        ?? (fallback || normalized.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()));
}

/* -------------------------------------------------------------------------- */
/* Item lookups                                                                */
/* -------------------------------------------------------------------------- */

export interface ItemOption {
    value: string;
    label: string;
    detail?: string;
}

function uniqueOptions(options: ItemOption[]): ItemOption[] {
    const seen = new Set<string>();
    return options.filter((option) => {
        if (!option.value || seen.has(option.value)) {
            return false;
        }
        seen.add(option.value);
        return true;
    });
}

export async function fetchGlobalAgentOptions(signal?: AbortSignal): Promise<ItemOption[]> {
    const payload = await api.get<unknown>('/api/admin/agents', signal);
    return uniqueOptions((Array.isArray(payload) ? payload : []).filter(isRecord).map((agent) => {
        const name = String(agent.name ?? '').trim();
        const displayName = String(agent.display_name ?? '').trim();
        return {
            value: String(agent.id ?? '').trim(),
            label: displayName || name || String(agent.id ?? ''),
            detail: displayName && name && displayName !== name ? name : undefined,
        };
    }));
}

export async function fetchGlobalActionOptions(signal?: AbortSignal): Promise<ItemOption[]> {
    const payload = await api.get<unknown>('/api/admin/plugins', signal);
    return uniqueOptions((Array.isArray(payload) ? payload : []).filter(isRecord).map((action) => ({
        value: String(action.id ?? '').trim(),
        label: String(action.displayName ?? action.name ?? action.id ?? '').trim(),
        detail: action.type ? actionTypeLabel(action.type) : undefined,
    })));
}

export async function fetchActionTypeOptions(signal?: AbortSignal): Promise<ItemOption[]> {
    const payload = await api.get<unknown>('/api/admin/plugins/types', signal);
    // Existing combined Graph actions are still governed by this type, even though new
    // actions use the individual Microsoft 365 sources, so it is always offered.
    const options: ItemOption[] = [{
        value: 'msgraph',
        label: actionTypeLabel('msgraph'),
        detail: 'Controls existing combined Graph actions; new actions use the individual Microsoft 365 types.',
    }];
    for (const entry of (Array.isArray(payload) ? payload : []).filter(isRecord)) {
        const value = normalizeActionType(entry.type);
        if (!value) {
            continue;
        }
        options.push({
            value,
            label: actionTypeLabel(value, String(entry.display ?? '')),
            detail: typeof entry.description === 'string' ? entry.description : undefined,
        });
    }
    return uniqueOptions(options);
}

/** `*` plus the configured source ids, matching the classic lookup. */
export function inboundSourceOptions(settings: Json): ItemOption[] {
    const wildcard: ItemOption = {
        value: '*',
        label: 'All accepted source IDs (*)',
        detail: 'Any source the Inbound MCP allowlist accepts',
    };
    const allowAll = settings.inbound_mcp_allow_all_source_ids === undefined
        ? true
        : asBoolean(settings.inbound_mcp_allow_all_source_ids);
    if (allowAll) {
        return [wildcard];
    }
    const entries = Array.isArray(settings.inbound_mcp_allowed_source_entries)
        ? settings.inbound_mcp_allowed_source_entries
        : [];
    const configured = entries.filter(isRecord).map((entry) => {
        const value = String(entry.value ?? '').trim();
        const description = String(entry.description ?? '').trim();
        return { value, label: description || value, detail: description ? value : undefined };
    }).filter((option) => option.value && option.value !== '*');
    return uniqueOptions([wildcard, ...configured]);
}

/* -------------------------------------------------------------------------- */
/* MCP destination patterns                                                    */
/* -------------------------------------------------------------------------- */

export type McpPatternKind = 'any' | 'preconfiguration' | 'preset' | 'host' | 'url' | 'transport';

export interface McpPatternParts {
    kind: McpPatternKind;
    value: string;
    /** Group scope only: limit the policy to one group, stored as `group:<id>::<pattern>`. */
    groupId?: string;
}

export const MCP_GROUP_TARGET_PREFIX = 'group:';
export const MCP_GROUP_TARGET_SEPARATOR = '::';

/** Mirrors `MCP_DESTINATION_ID_PATTERN`. */
const MCP_POLICY_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/;

/** Mirrors `MCP_REMOTE_TRANSPORTS`; the catalog endpoint reports the live list. */
export const DEFAULT_MCP_TRANSPORTS = ['sse', 'streamable_http', 'websocket'] as const;

export function parseMcpDestinationItemId(itemId: string, entityType: unknown): McpPatternParts {
    let pattern = String(itemId ?? '').trim();
    let groupId: string | undefined;
    if (
        normalizeEntityType(entityType) === 'mcp_group_destination'
        && pattern.toLowerCase().startsWith(MCP_GROUP_TARGET_PREFIX)
        && pattern.includes(MCP_GROUP_TARGET_SEPARATOR)
    ) {
        const separator = pattern.indexOf(MCP_GROUP_TARGET_SEPARATOR);
        groupId = pattern.slice(MCP_GROUP_TARGET_PREFIX.length, separator).trim() || undefined;
        pattern = pattern.slice(separator + MCP_GROUP_TARGET_SEPARATOR.length).trim();
    }

    const lowered = pattern.toLowerCase();
    let parts: McpPatternParts;
    if (pattern === '*') {
        parts = { kind: 'any', value: '' };
    } else if (lowered.startsWith('preconfiguration:')) {
        parts = { kind: 'preconfiguration', value: pattern.slice('preconfiguration:'.length).trim() };
    } else if (lowered.startsWith('preset:')) {
        parts = { kind: 'preset', value: pattern.slice('preset:'.length).trim() };
    } else if (lowered.startsWith('transport:')) {
        parts = { kind: 'transport', value: pattern.slice('transport:'.length).trim() };
    } else if (pattern.includes('://')) {
        parts = { kind: 'url', value: pattern };
    } else {
        parts = { kind: 'host', value: pattern };
    }
    return groupId ? { ...parts, groupId } : parts;
}

export function buildMcpDestinationItemId(parts: McpPatternParts, entityType: unknown): string {
    const value = parts.value.trim();
    let pattern: string;
    switch (parts.kind) {
        case 'any':
            pattern = '*';
            break;
        case 'preconfiguration':
            pattern = value ? `preconfiguration:${value}` : '';
            break;
        case 'preset':
            pattern = value ? `preset:${value}` : '';
            break;
        case 'transport':
            pattern = value ? `transport:${value}` : '';
            break;
        default:
            pattern = value;
    }
    const groupId = parts.groupId?.trim();
    if (pattern && groupId && normalizeEntityType(entityType) === 'mcp_group_destination') {
        return `${MCP_GROUP_TARGET_PREFIX}${groupId}${MCP_GROUP_TARGET_SEPARATOR}${pattern}`;
    }
    return pattern;
}

export interface McpPatternCheck {
    /** The pattern cannot be saved as written. */
    error?: string;
    /** The pattern saves, but probably does not do what was meant. */
    warning?: string;
}

const MISSING_PATTERN_VALUE: Record<Exclude<McpPatternKind, 'any'>, string> = {
    preconfiguration: 'Choose a preconfigured server.',
    preset: 'Choose a server preset.',
    transport: 'Choose a transport.',
    host: 'Enter a host name pattern, such as *.contoso.com.',
    url: 'Enter a URL, such as https://mcp.contoso.com/mcp*.',
};

/**
 * Check a destination pattern the way `_pattern_matches_destination` will read it.
 *
 * The server stores any string, so a pattern that can never match saves without complaint
 * and then silently allows nothing. These are the mistakes that produce one.
 */
export function checkMcpDestinationPattern(
    parts: McpPatternParts,
    transports: readonly string[] = DEFAULT_MCP_TRANSPORTS,
    groupSpecific = false,
): McpPatternCheck {
    if (groupSpecific && !parts.groupId?.trim()) {
        return { error: 'Choose the group this policy applies to.' };
    }
    if (parts.kind === 'any') {
        return {
            warning: 'Allows every remote MCP server for this scope after identity and authentication checks. Enterprise templates still need their own preconfiguration policy.',
        };
    }
    const value = parts.value.trim();
    if (!value) {
        return { error: MISSING_PATTERN_VALUE[parts.kind] };
    }
    if (/\s/.test(value)) {
        return { error: 'Patterns cannot contain spaces.' };
    }
    if (parts.kind === 'preconfiguration' || parts.kind === 'preset') {
        return MCP_POLICY_ID_PATTERN.test(value.toLowerCase())
            ? {}
            : { error: 'IDs use lowercase letters, numbers, hyphens, and underscores.' };
    }
    if (parts.kind === 'transport') {
        const lowered = value.toLowerCase();
        if (transports.includes(lowered)) {
            return {};
        }
        const underscored = lowered.replace(/-/g, '_');
        return transports.includes(underscored)
            ? { error: `Use transport:${underscored}. The hyphenated form never matches.` }
            : { error: `Choose one of: ${transports.join(', ')}.` };
    }
    if (parts.kind === 'host') {
        if (value.includes('/') || value.includes(':')) {
            return { error: 'A host pattern is a host name only, such as *.contoso.com. Use a URL pattern for a scheme, port, or path.' };
        }
        return /^[a-z0-9*._-]+$/i.test(value)
            ? {}
            : { error: 'Host patterns use letters, numbers, dots, hyphens, underscores, and * wildcards.' };
    }
    // URL pattern
    let parsed: URL;
    try {
        parsed = new URL(value.replace(/\*/g, 'wildcard'));
    } catch {
        return { error: 'Enter a full URL, such as https://mcp.contoso.com/mcp*.' };
    }
    if (!['http:', 'https:', 'ws:', 'wss:'].includes(parsed.protocol)) {
        return { error: 'Use an http, https, ws, or wss URL.' };
    }
    if (value.includes('?') || value.includes('#')) {
        return { error: 'Query strings and fragments are not matched; remove them.' };
    }
    const path = value.split('://', 2)[1]?.split('/').slice(1).join('/') ?? '';
    if (path.slice(0, -1).includes('*')) {
        return { error: 'A * in the path only works at the end, as a prefix match.' };
    }
    return {};
}

export interface McpCatalogPreconfiguration {
    id: string;
    label: string;
    catalog_tier: string;
    /** Empty means every scope. */
    scopes: string[];
    requires_explicit_policy: boolean;
    requires_endpoint_review: boolean;
}

export interface McpDestinationCatalog {
    preconfigurations: McpCatalogPreconfiguration[];
    presets: { id: string; label: string }[];
    transports: string[];
}

export async function fetchMcpDestinationCatalog(signal?: AbortSignal): Promise<McpDestinationCatalog> {
    const payload = await api.get<Record<string, unknown>>(`${GOVERNANCE_API}/mcp-destination-catalog`, signal);
    const preconfigurations = (Array.isArray(payload?.preconfigurations) ? payload.preconfigurations : [])
        .filter(isRecord)
        .map((entry) => ({
            id: String(entry.id ?? '').trim(),
            label: String(entry.label ?? entry.id ?? '').trim(),
            catalog_tier: String(entry.catalog_tier ?? ''),
            scopes: Array.isArray(entry.scopes) ? entry.scopes.map(String) : [],
            requires_explicit_policy: asBoolean(entry.requires_explicit_policy),
            requires_endpoint_review: asBoolean(entry.requires_endpoint_review),
        }))
        .filter((entry) => entry.id);
    const presets = (Array.isArray(payload?.presets) ? payload.presets : [])
        .filter(isRecord)
        .map((entry) => ({ id: String(entry.id ?? '').trim(), label: String(entry.label ?? entry.id ?? '').trim() }))
        .filter((entry) => entry.id);
    const transports = (Array.isArray(payload?.transports) ? payload.transports : [])
        .map((value) => String(value).trim())
        .filter(Boolean);
    return { preconfigurations, presets, transports: transports.length ? transports : [...DEFAULT_MCP_TRANSPORTS] };
}

/** The destination scope an MCP entity type governs, for matching catalog scope rules. */
export function mcpScopeOf(entityType: unknown): 'personal' | 'group' | 'global' | null {
    switch (normalizeEntityType(entityType)) {
        case 'mcp_personal_destination':
            return 'personal';
        case 'mcp_group_destination':
            return 'group';
        case 'mcp_global_destination':
            return 'global';
        default:
            return null;
    }
}

/* -------------------------------------------------------------------------- */
/* Principal directory                                                         */
/* -------------------------------------------------------------------------- */

export interface PrincipalEntry {
    id: string;
    name: string;
    /** Email for a person, description for a group. */
    detail?: string;
    /** Groups only: a group workspace or a public workspace. */
    kind?: 'group' | 'public_workspace';
}

/** What is known about an id: its entry, or that the directory no longer has it. */
export type PrincipalLookup = { status: 'found'; entry: PrincipalEntry } | { status: 'missing' };

const principalCache: Record<PrincipalKind, Map<string, PrincipalLookup>> = {
    users: new Map(),
    groups: new Map(),
};

/** Record entries learned from a search, so a chip stays labelled after the search clears. */
export function rememberPrincipals(kind: PrincipalKind, entries: PrincipalEntry[]): void {
    for (const entry of entries) {
        if (entry.id) {
            principalCache[kind].set(entry.id, { status: 'found', entry });
        }
    }
}

export function cachedPrincipal(kind: PrincipalKind, id: string): PrincipalLookup | undefined {
    return principalCache[kind].get(id);
}

function readGroupEntry(raw: unknown): PrincipalEntry | null {
    if (!isRecord(raw) || typeof raw.id !== 'string' || !raw.id.trim()) {
        return null;
    }
    return {
        id: raw.id.trim(),
        name: String(raw.name ?? '').trim(),
        detail: String(raw.description ?? '').trim() || undefined,
        kind: raw.kind === 'public_workspace' ? 'public_workspace' : 'group',
    };
}

function readUserEntry(raw: unknown): PrincipalEntry | null {
    if (!isRecord(raw) || typeof raw.id !== 'string' || !raw.id.trim()) {
        return null;
    }
    const name = String(raw.displayName ?? raw.display_name ?? '').trim();
    const email = String(raw.email ?? raw.mail ?? raw.userPrincipalName ?? '').trim();
    return { id: raw.id.trim(), name: name || email, detail: email && email !== name ? email : undefined };
}

export interface PrincipalSearchResult {
    entries: PrincipalEntry[];
    truncated: boolean;
}

export async function searchPrincipals(kind: PrincipalKind, term: string, signal?: AbortSignal): Promise<PrincipalSearchResult> {
    const query = term.trim();
    if (kind === 'users') {
        // The people search goes through the administrator's own Graph access and answers
        // an empty term with nothing, so there is nothing to browse before typing.
        if (!query) {
            return { entries: [], truncated: false };
        }
        const payload = await api.get<unknown>(`/api/userSearch?query=${encodeURIComponent(query)}`, signal);
        const entries = (Array.isArray(payload) ? payload : [])
            .map(readUserEntry)
            .filter((entry): entry is PrincipalEntry => entry !== null);
        rememberPrincipals('users', entries);
        return { entries, truncated: false };
    }
    const payload = await api.get<{ groups?: unknown[]; truncated?: boolean }>(
        `${GOVERNANCE_API}/principal-groups?search=${encodeURIComponent(query)}`,
        signal,
    );
    const entries = (Array.isArray(payload?.groups) ? payload.groups : [])
        .map(readGroupEntry)
        .filter((entry): entry is PrincipalEntry => entry !== null);
    rememberPrincipals('groups', entries);
    return { entries, truncated: Boolean(payload?.truncated) };
}

const GROUP_RESOLVE_BATCH = 100;
const USER_RESOLVE_CONCURRENCY = 4;

/**
 * Resolve ids to names, filling the shared cache.
 *
 * Groups resolve in batches through the governance directory, which covers group and public
 * workspaces; an id it does not return no longer exists. People resolve one at a time
 * through the profile endpoint, which already authorizes administrators; a 404 means the
 * person is unknown. Any other failure is left unrecorded, because a failed lookup is not a
 * deleted principal and must not be shown as one.
 */
export async function resolvePrincipals(kind: PrincipalKind, ids: string[], signal?: AbortSignal): Promise<void> {
    const pending = normalizePrincipalIds(ids).filter((id) => !principalCache[kind].has(id));
    if (!pending.length) {
        return;
    }

    if (kind === 'groups') {
        for (let index = 0; index < pending.length; index += GROUP_RESOLVE_BATCH) {
            const batch = pending.slice(index, index + GROUP_RESOLVE_BATCH);
            const payload = await api.get<{ groups?: unknown[] }>(
                `${GOVERNANCE_API}/principal-groups?ids=${encodeURIComponent(batch.join(','))}`,
                signal,
            );
            const entries = (Array.isArray(payload?.groups) ? payload.groups : [])
                .map(readGroupEntry)
                .filter((entry): entry is PrincipalEntry => entry !== null);
            rememberPrincipals('groups', entries);
            for (const id of batch) {
                if (!principalCache.groups.has(id)) {
                    principalCache.groups.set(id, { status: 'missing' });
                }
            }
        }
        return;
    }

    let cursor = 0;
    const worker = async () => {
        while (cursor < pending.length) {
            const id = pending[cursor];
            cursor += 1;
            try {
                const payload = await api.get<unknown>(`/api/user/info/${encodeURIComponent(id)}`, signal);
                const entry = readUserEntry(isRecord(payload) ? { ...payload, id } : payload);
                if (entry) {
                    principalCache.users.set(id, { status: 'found', entry });
                }
            } catch (error) {
                // A 404 covers both an unknown id and a directory lookup that failed, so it
                // is recorded as unresolved rather than as a deleted person.
                if (error instanceof ApiError && error.status === 404) {
                    principalCache.users.set(id, { status: 'missing' });
                } else if (signal?.aborted) {
                    return;
                }
            }
        }
    };
    await Promise.all(Array.from({ length: Math.min(USER_RESOLVE_CONCURRENCY, pending.length) }, worker));
}
