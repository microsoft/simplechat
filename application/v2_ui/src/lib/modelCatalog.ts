// modelCatalog.ts
// Types and pure helpers for the Model Catalog, shared by the V2 manager and profile picker.
//
// The classic page renders the catalog from `static/js/admin/model_catalog_ui.js`. V2
// draws its own, natively, and keeps the parts that decide behaviour -- which profiles a
// filter keeps, how they sort, what a saved profile contains -- here, where they can be
// executed in a test (`functional_tests/test_v2_model_catalog_logic.ts`) instead of being
// reviewed by eye. Filtering and sorting deliberately match the classic module, so both
// interfaces list the same profiles for the same filters.

import { request } from './apiClient';

export type TaskSuitability = 'strong' | 'suitable' | 'unsuitable' | 'unknown';
export type CatalogPriority = 'preferred' | 'standard' | 'lower';
export type CatalogOrigin = 'built_in' | 'custom';

export interface CatalogPreferences {
    favorite: boolean;
    priority: CatalogPriority;
}

/** A global AI Connection model that uses a profile. Admin responses only. */
export interface CatalogLinkedModel {
    connection: string;
    connection_id?: string;
    model: string;
    model_id?: string;
    enabled: boolean;
    capabilities: Record<string, boolean>;
}

export interface CatalogProfile {
    id: string;
    displayName: string;
    publisher: string;
    origin: CatalogOrigin;
    summary: string;
    strengths: string[];
    limitations: string[];
    aliases: string[];
    tasks: Record<string, TaskSuitability>;
    capabilities: Record<string, boolean>;
    sources: string[];
    evidence: string;
    archived: boolean;
    verifiedAt?: string | null;
    chatCompletions?: boolean | null;
    technical?: Record<string, unknown>;
    preferences: CatalogPreferences;
    revision?: string;
    linked_models?: CatalogLinkedModel[];
}

export interface CatalogResponse {
    profiles: CatalogProfile[];
    /** Task key to label, in the order the server declares them. */
    tasks: Record<string, string>;
    etag?: string;
}

/** Where "Open in AI Connections" should land. */
export interface CatalogConnectionTarget {
    connectionId: string;
    modelId?: string;
    /** The model's display name, for connections whose models carry no id. */
    modelName?: string;
}

export type CapabilityGroup = 'input' | 'output' | 'feature';

/**
 * The capabilities a custom profile may declare, in the order they are presented.
 *
 * Mirrors `CAPABILITY_FIELD_NAMES` in `functions_model_capabilities.py`, which is what the
 * server validates a saved profile against.
 */
export const CATALOG_CAPABILITIES: ReadonlyArray<{
    key: string;
    label: string;
    group: CapabilityGroup;
}> = [
    { key: 'processesText', label: 'Processes text', group: 'input' },
    { key: 'processesImages', label: 'Processes images', group: 'input' },
    { key: 'processesAudio', label: 'Processes audio', group: 'input' },
    { key: 'processesVideo', label: 'Processes video', group: 'input' },
    { key: 'processesBinaryFiles', label: 'Processes binary files', group: 'input' },
    { key: 'generatesText', label: 'Generates text', group: 'output' },
    { key: 'generatesImages', label: 'Generates images', group: 'output' },
    { key: 'generatesAudio', label: 'Generates audio', group: 'output' },
    { key: 'generatesVideo', label: 'Generates video', group: 'output' },
    { key: 'optimizedForCoding', label: 'Optimized for coding', group: 'feature' },
    { key: 'toolCalling', label: 'Tool calling', group: 'feature' },
    { key: 'structuredOutput', label: 'Structured output', group: 'feature' },
    { key: 'supportsStreaming', label: 'Supports streaming', group: 'feature' },
    { key: 'reasoning', label: 'Reasoning', group: 'feature' },
];

export const CAPABILITY_GROUP_LABELS: Readonly<Record<CapabilityGroup, string>> = {
    input: 'Inputs',
    output: 'Outputs',
    feature: 'Features',
};

const EDITABLE_CAPABILITIES = new Set(CATALOG_CAPABILITIES.map((item) => item.key));

/** Turn a camelCase capability key into a sentence-case label. */
export function capabilityLabel(key: string): string {
    const known = CATALOG_CAPABILITIES.find((item) => item.key === key);
    if (known) {
        return known.label;
    }
    const words = key.replace(/([A-Z])/g, ' $1').trim().toLowerCase();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

export const SUITABILITY_LABELS: Readonly<Record<TaskSuitability, string>> = {
    strong: 'Strong',
    suitable: 'Suitable',
    unsuitable: 'Unsuitable',
    unknown: 'Unknown',
};

export function readSuitability(value: unknown): TaskSuitability {
    return value === 'strong' || value === 'suitable' || value === 'unsuitable' ? value : 'unknown';
}

export const PRIORITY_OPTIONS: ReadonlyArray<{ value: CatalogPriority; label: string }> = [
    { value: 'preferred', label: 'Preferred' },
    { value: 'standard', label: 'Standard' },
    { value: 'lower', label: 'Lower' },
];

/**
 * Display names for the publisher identifiers built-in profiles carry.
 *
 * Built-in records name their provider by a lowercase id; a custom profile's publisher is
 * whatever the administrator typed, and is shown as typed.
 */
const PUBLISHER_NAMES: Readonly<Record<string, string>> = {
    anthropic: 'Anthropic',
    azure: 'Azure',
    blackforestlabs: 'Black Forest Labs',
    cohere: 'Cohere',
    google: 'Google',
    meta: 'Meta',
    microsoft: 'Microsoft',
    openai: 'OpenAI',
    vertex: 'Vertex AI',
    xai: 'xAI',
};

export function publisherLabel(publisher: string | undefined | null): string {
    const value = (publisher ?? '').trim();
    if (!value) {
        return 'Unspecified publisher';
    }
    return PUBLISHER_NAMES[value.toLowerCase()] ?? value;
}

export function evidenceLabel(evidence: string | undefined): string {
    switch (evidence) {
        case 'publisher_documentation':
            return 'Publisher documentation';
        case 'capability_derived':
            return 'Derived from capabilities';
        case 'admin_declared':
            return 'Administrator declared';
        default:
            return (evidence ?? '').replaceAll('_', ' ') || 'Not stated';
    }
}

/** What each evidence source means, for the Evidence tab. */
export function evidenceDescription(evidence: string | undefined): string {
    switch (evidence) {
        case 'publisher_documentation':
            return 'Strengths and task ratings were reviewed against the publisher’s own documentation.';
        case 'capability_derived':
            return 'Task suitability is inferred from documented technical capabilities. It is not a benchmark.';
        case 'admin_declared':
            return 'An administrator described this profile. It is not publisher-verified.';
        default:
            return 'The source of this profile’s ratings is not recorded.';
    }
}

/** Lifecycle values from the capability catalog, e.g. `limited-availability`. */
export function lifecycleLabel(value: unknown): string | null {
    if (typeof value !== 'string' || !value.trim()) {
        return null;
    }
    const words = value.replaceAll('-', ' ').replaceAll('_', ' ');
    return words.charAt(0).toUpperCase() + words.slice(1);
}

export function isLifecycleWarning(value: unknown): boolean {
    return value === 'deprecated' || value === 'retired' || value === 'legacy';
}

/** Token limits are numbers for most records, and a per-variant object for a few. */
export function formatTokenLimit(value: unknown): string {
    if (typeof value === 'number' && Number.isFinite(value)) {
        return `${value.toLocaleString()} tokens`;
    }
    if (typeof value === 'string' && value.trim()) {
        return value;
    }
    if (value && typeof value === 'object') {
        return 'Varies by deployment';
    }
    return 'Not documented';
}

/** Evidence links are rendered only when they are plain HTTPS URLs without credentials. */
export function safeEvidenceUrl(source: unknown): string | null {
    if (typeof source !== 'string') {
        return null;
    }
    try {
        const url = new URL(source);
        return url.protocol === 'https:' && !url.username && !url.password ? url.href : null;
    } catch {
        return null;
    }
}

export interface CatalogFilters {
    query: string;
    origin: '' | CatalogOrigin;
    task: string;
    publisher: string;
    capability: string;
    availability: '' | 'linked' | 'unlinked';
    lifecycle: '' | 'active' | 'archived';
    favorites: boolean;
}

export const DEFAULT_CATALOG_FILTERS: Readonly<CatalogFilters> = {
    query: '',
    origin: '',
    task: '',
    publisher: '',
    capability: '',
    availability: '',
    lifecycle: 'active',
    favorites: false,
};

/** Filters other than the search text that differ from their defaults. */
export function activeFilterCount(filters: CatalogFilters): number {
    return (Object.keys(DEFAULT_CATALOG_FILTERS) as (keyof CatalogFilters)[])
        .filter((key) => key !== 'query' && filters[key] !== DEFAULT_CATALOG_FILTERS[key])
        .length;
}

export function linkedModelCount(profile: CatalogProfile): number {
    return profile.linked_models?.length ?? 0;
}

function searchText(profile: CatalogProfile): string {
    return [
        profile.displayName,
        profile.id,
        profile.publisher,
        publisherLabel(profile.publisher),
        profile.summary,
        ...(profile.aliases ?? []),
    ].join(' ').toLocaleLowerCase();
}

function isRatedFor(profile: CatalogProfile, task: string): boolean {
    const rating = profile.tasks?.[task];
    return rating === 'suitable' || rating === 'strong';
}

/**
 * The profiles a set of filters keeps, favorites first and then by name.
 *
 * Same rules as the classic module: a task filter keeps profiles rated suitable or strong
 * for it, and the connection filter reads whether any global model uses the profile.
 */
export function filterCatalogProfiles(
    profiles: CatalogProfile[],
    filters: CatalogFilters,
): CatalogProfile[] {
    const needle = filters.query.trim().toLocaleLowerCase();
    return profiles
        .filter((profile) =>
            (!filters.origin || profile.origin === filters.origin) &&
            (!filters.favorites || profile.preferences?.favorite) &&
            (!filters.publisher || profile.publisher === filters.publisher) &&
            (!filters.capability || profile.capabilities?.[filters.capability] === true) &&
            (!filters.availability ||
                (linkedModelCount(profile) > 0) === (filters.availability === 'linked')) &&
            (!filters.lifecycle || profile.archived === (filters.lifecycle === 'archived')) &&
            (!filters.task || isRatedFor(profile, filters.task)) &&
            searchText(profile).includes(needle),
        )
        .sort((a, b) =>
            Number(Boolean(b.preferences?.favorite)) - Number(Boolean(a.preferences?.favorite)) ||
            a.displayName.localeCompare(b.displayName),
        );
}

export function publisherOptions(profiles: CatalogProfile[]): string[] {
    return [...new Set(profiles.map((profile) => profile.publisher).filter(Boolean))].sort(
        (a, b) => publisherLabel(a).localeCompare(publisherLabel(b)),
    );
}

/** The editable form of a custom profile. List fields stay as typed text until saved. */
export interface CatalogProfileForm {
    displayName: string;
    publisher: string;
    summary: string;
    strengths: string;
    limitations: string;
    aliases: string;
    sources: string;
    tasks: Record<string, TaskSuitability>;
    capabilities: Record<string, boolean>;
    archived: boolean;
}

/** The profile body the server accepts; see `PROFILE_FIELDS` in `functions_model_catalog.py`. */
export interface CatalogProfilePayload {
    displayName: string;
    publisher: string;
    summary: string;
    strengths: string[];
    limitations: string[];
    aliases: string[];
    sources: string[];
    tasks: Record<string, TaskSuitability>;
    capabilities: Record<string, boolean>;
    archived: boolean;
}

export function emptyProfileForm(): CatalogProfileForm {
    return {
        displayName: '',
        publisher: '',
        summary: '',
        strengths: '',
        limitations: '',
        aliases: '',
        sources: '',
        tasks: {},
        capabilities: {},
        archived: false,
    };
}

export function profileToPayload(profile: CatalogProfile): CatalogProfilePayload {
    return {
        displayName: profile.displayName,
        publisher: profile.publisher ?? '',
        summary: profile.summary ?? '',
        strengths: [...(profile.strengths ?? [])],
        limitations: [...(profile.limitations ?? [])],
        aliases: [...(profile.aliases ?? [])],
        sources: [...(profile.sources ?? [])],
        tasks: { ...(profile.tasks ?? {}) },
        // Only the capabilities a profile may declare; built-in records carry more.
        capabilities: Object.fromEntries(
            Object.entries(profile.capabilities ?? {}).filter(
                ([key, value]) => EDITABLE_CAPABILITIES.has(key) && typeof value === 'boolean',
            ),
        ),
        archived: Boolean(profile.archived),
    };
}

export function profileToForm(profile: CatalogProfile): CatalogProfileForm {
    const payload = profileToPayload(profile);
    return {
        ...payload,
        strengths: payload.strengths.join('\n'),
        limitations: payload.limitations.join('\n'),
        aliases: payload.aliases.join('\n'),
        sources: payload.sources.join('\n'),
    };
}

export function splitLines(text: string): string[] {
    return text.split('\n').map((line) => line.trim()).filter(Boolean);
}

export function formToPayload(form: CatalogProfileForm): CatalogProfilePayload {
    return {
        displayName: form.displayName,
        publisher: form.publisher,
        summary: form.summary,
        strengths: splitLines(form.strengths),
        limitations: splitLines(form.limitations),
        aliases: splitLines(form.aliases),
        sources: splitLines(form.sources),
        tasks: { ...form.tasks },
        capabilities: { ...form.capabilities },
        archived: form.archived,
    };
}

/** A copy of a profile as a new custom one, as "Duplicate as custom" starts it. */
export function duplicateProfileForm(profile: CatalogProfile): CatalogProfileForm {
    return {
        ...profileToForm(profile),
        displayName: `${profile.displayName} custom`,
        aliases: '',
        archived: false,
    };
}

function readCatalogResponse(value: unknown): CatalogResponse {
    const response = value as Partial<CatalogResponse> | null;
    // A signed-out session is answered with an HTML page rather than JSON.
    if (!response || typeof response !== 'object' || !Array.isArray(response.profiles)) {
        throw new Error('The catalog could not be loaded. Check your session and retry.');
    }
    return { profiles: response.profiles, tasks: response.tasks ?? {}, etag: response.etag };
}

export async function loadAdminCatalog(signal?: AbortSignal): Promise<CatalogResponse> {
    return readCatalogResponse(await request<unknown>('/api/admin/model-catalog', { signal }));
}

/** Create a custom profile, or change one profile's definition or preferences. */
export async function saveCatalogChange(
    change: { profile?: CatalogProfilePayload; preferences?: CatalogPreferences },
    etag: string | undefined,
    profileId?: string,
): Promise<CatalogResponse> {
    const path = profileId
        ? `/api/admin/model-catalog/${encodeURIComponent(profileId)}`
        : '/api/admin/model-catalog';
    return readCatalogResponse(
        await request<unknown>(path, {
            method: profileId ? 'PATCH' : 'POST',
            body: { ...change, etag },
        }),
    );
}

let choicesRequest: Promise<CatalogResponse> | null = null;

/**
 * The profiles a model may be associated with, shared by every picker on the page.
 *
 * The connection editor draws one picker per model, so each asking for the list itself
 * would issue one identical request per model row.
 */
export function loadCatalogChoices(): Promise<CatalogResponse> {
    if (!choicesRequest) {
        choicesRequest = request<unknown>('/api/models/catalog')
            .then(readCatalogResponse)
            .catch((error: unknown) => {
                choicesRequest = null;
                throw error;
            });
    }
    return choicesRequest;
}

/** Name of the window event announcing a catalog save, shared with the classic module. */
export const CATALOG_CHANGED_EVENT = 'model-catalog-changed';

/** Drop the shared choices after a save, so the next picker reads the new catalog. */
export function catalogChanged(): void {
    choicesRequest = null;
    window.dispatchEvent(new CustomEvent(CATALOG_CHANGED_EVENT));
}
