// adminFields.ts
// Types and helpers for the server-declared Admin Settings field schema.
//
// The shape here mirrors `admin_settings_fields.py`. The server is the source of truth:
// this file only describes what arrives so the renderer can be written against real types
// instead of `unknown`, and holds the pure helpers that decide whether a field is visible
// and what value it currently has.

import type { Json } from './types';

/** Field kinds the renderer implements. Mirrors `FIELD_TYPES`. */
export type AdminFieldType =
    | 'text'
    | 'textarea'
    | 'secret'
    | 'select'
    | 'switch'
    | 'checkbox_set'
    | 'color'
    | 'range'
    | 'number'
    | 'string_list'
    | 'note'
    | 'image'
    | 'link_list'
    | 'component'
    | 'secret'
    | 'string_list'
    | 'id_list'
    | 'group_picker'
    | 'status';

export interface AdminFieldOption {
    value: string;
    label: string;
    /** Options for capabilities that are declared but not yet released. */
    disabled?: boolean;
    description?: string;
}

/**
 * Shows a field only while a condition holds.
 *
 * The single-key form covers most cases. An array means every condition has to hold --
 * Content Safety's key is gated on the capability, the routing choice and the auth type
 * at once. `any_of` exists because some blocks are revealed by more than one capability:
 * the Speech resource configuration is shared by audio uploads, voice input and voice
 * responses, and showing it three times would be three ways to edit one credential.
 */
export interface AdminFieldCondition {
    key: string;
    equals?: boolean | string;
    not_equals?: boolean | string;
}

export type AdminFieldDependency =
    | AdminFieldCondition
    | AdminFieldCondition[]
    | { any_of: AdminFieldDependency[] }
    | { all_of: AdminFieldDependency[] };

/**
 * A prerequisite owned by another section.
 *
 * `block` disables the dependent controls until it is satisfied; `warn` leaves them
 * usable, for prerequisites the backend accepts as intent and reconciles later. Mirrors
 * the `data-requires` contract in `admin_settings_dependencies.js`.
 */
export interface AdminFieldRequirement {
    key: string;
    label: string;
    mode?: 'block' | 'warn';
    description?: string;
    /** Section id to link to, so the prerequisite can be configured in full. */
    target_section?: string;
}

/**
 * The cluster a field belongs to within its section.
 *
 * A bare string is accepted as shorthand for a labelled group with no variant, which is
 * the form the Security and Workspaces sections declare.
 */
export interface AdminFieldGroup {
    id: string;
    label?: string;
    variant?: 'connection' | 'behavior' | 'limits' | 'access' | 'advanced';
    help?: string;
}

/** Normalise either declared group shape into the object form. */
export function readFieldGroup(
    group: string | AdminFieldGroup | undefined,
): AdminFieldGroup | undefined {
    if (!group) {
        return undefined;
    }
    return typeof group === 'string' ? { id: group, label: group } : group;
}

/**
 * A confirmation an administrator must give before a capability may be switched on.
 *
 * Used by Custom Pages, which does not take full effect until the App Service restarts.
 * The flag is sent with the save and gates it; it is never stored.
 */
export interface AdminFieldAcknowledgement {
    key: string;
    when: 'enabled';
    title: string;
    message: string;
}

export interface AdminField {
    key?: string;
    type: AdminFieldType;
    label: string;
    help?: string;
    placeholder?: string;
    default?: unknown;
    max_length?: number;
    rows?: number;
    markdown?: boolean;
    word_limit?: number;
    options?: AdminFieldOption[];
    min?: number;
    max?: number;
    step?: number;
    suffix?: string;
    min_selected?: number;
    fallback_when_empty?: boolean;
    item_fields?: AdminField[];
    /** Text fields only: the input type the browser should use. */
    input_type?: 'text' | 'email' | 'url';
    /** String list fields only: per-item character cap. */
    max_item_length?: number;
    /**
     * The cluster this field belongs to inside its section.
     *
     * A bare string is a sub-heading with no variant, which is the form the Security
     * and Workspaces sections declare. The object form adds a variant, which is what
     * decides which group the renderer opens first.
     */
    group?: string | AdminFieldGroup;
    /** `id_list` and `group_picker`: the admin search endpoint that finds records. */
    search_endpoint?: string;
    /** `id_list` only: query parameter the endpoint reads the search term from. */
    search_param?: string;
    /** `id_list` only: fixed query parameters sent with every search. */
    search_extra?: Record<string, string>;
    /** `id_list` only: property on the response holding the result array. */
    results_key?: string;
    /** `id_list` only: what one assignable record is called, for summaries. */
    item_noun?: string;
    item_noun_plural?: string;
    /** Image fields only: which branding slot the upload endpoint should write. */
    upload_target?: 'logo' | 'logo_dark' | 'favicon';
    accept?: string;
    version_key?: string;
    /** Component fields only: which bespoke widget to render. */
    component?: string;
    /** `string_list` and `id_list`: entry validation and bounds. */
    entry_pattern?: string;
    entry_label?: string;
    entry_max_length?: number;
    max_entries?: number;
    /**
     * `id_list` only: how the submitted list is validated.
     *
     * `group` delegates to the canonical group-id normalizer, which requires a UUID and
     * drops anything else; `opaque` only trims and deduplicates, because public workspace
     * ids are not UUID-constrained.
     */
    id_kind?: 'group' | 'opaque';
    /** `status` fields only: which server-computed readout to show. */
    status_source?: string;
    /**
     * `connection-test` components only: which test the shared dispatcher should run,
     * and how to build its payload from current values.
     *
     * Keys are dotted paths into the request body, so one flat declaration produces the
     * nested `{direct: {...}}` / `{apim: {...}}` shape the test handlers expect. An entry
     * with a `when` is only sent while that condition holds, which is what lets a single
     * declaration cover both sides of an APIM-or-direct choice.
     */
    test_type?: string;
    test_payload?: Record<string, { key?: string; value?: unknown; when?: AdminFieldDependency }>;
    /** Marks a field that must hold a value before its section counts as configured. */
    required?: boolean;
    /** `model-picker` components only: restrict the list to models that read images. */
    requires_vision?: boolean;
    /**
     * `resource-id-builder` components only: how to assemble the value.
     *
     * `builder_template` holds `{placeholder}` markers, and `builder_sources` maps each
     * placeholder to the settings key holding its value.
     */
    builder_template?: string;
    builder_sources?: Record<string, string>;
    /** Multiplier between the unit a field is edited in and the unit it is stored in. */
    scale?: number;
    /** Lifts a field into the section header. See `FIELD_ROLES`. */
    role?: 'capability';
    /**
     * Where the value is stored, when that is not a top-level key named by `key`.
     *
     * The save handler assembles some settings into a nested object, so a field named
     * after its V1 form input would otherwise write a top-level key nothing reads. The
     * first path is the one read back.
     */
    paths?: string[];
    /**
     * Standing guidance shown as a callout beneath the control.
     *
     * Distinct from `help`, which describes what the setting does, and from the
     * server's per-save `warnings`, which react to a submitted value. A notice is
     * an operational caveat that is true whenever the setting is on screen.
     */
    notice?: string;
    notice_level?: 'info' | 'warning';
    depends_on?: AdminFieldDependency;
    requires?: AdminFieldRequirement;
    requires_acknowledgement?: AdminFieldAcknowledgement;
}

/** Section id -> ordered fields. Section ids come from `admin_settings_nav.py`. */
export type AdminFieldSchema = Record<string, AdminField[]>;

/** One rule deciding whether an enabled section is actually usable. */
export interface AdminSectionConfiguredRule {
    when?: Record<string, boolean>;
    requires: string[];
}

/** Mirrors `ADMIN_SECTION_STATUS`. */
export interface AdminSectionStatusRule {
    enabled_key: string;
    configured?: AdminSectionConfiguredRule[];
}

export type AdminSectionStatusSchema = Record<string, AdminSectionStatusRule>;

/** One entry from `APP_ROLE_REQUIREMENTS`. */
export interface AppRoleRequirement {
    key: string;
    role: string;
    label: string;
    section_id: string;
    grants: string;
    when_off: string;
    depends_on: string | null;
}

export interface BrandingAsset {
    present: boolean;
    version: number;
    url: string | null;
}

export type BrandingAssets = Record<string, BrandingAsset>;

/**
 * One deployed model an administrator can pick, with its capabilities resolved.
 *
 * `vision_source` is `declared` when an administrator set it, `catalog` when the shipped
 * capability data says so, and `inferred` when it was guessed from the model's name.
 */
export interface AdminModelCatalogEntry {
    deployment: string;
    label: string;
    endpoint: string;
    endpoint_id?: string | null;
    model_name: string;
    supports_vision: boolean;
    vision_source: 'declared' | 'catalog' | 'inferred';
}

export interface AdminSettingsResponse {
    settings: Json;
    admin_nav: import('./types').AdminNavGroup[];
    field_schema: AdminFieldSchema;
    section_status: AdminSectionStatusSchema;
    app_role_requirements: AppRoleRequirement[];
    branding_assets: BrandingAssets;
    /**
     * Server-computed readouts a `status` field renders, keyed by `status_source`.
     *
     * These are not settings: whether the browser runtime can render JavaScript, whether
     * audio transcoding is available. The tone is carried alongside the text because
     * inferring it from the wording would be guesswork.
     */
    status_readouts?: Record<string, { ok: boolean; message: string }>;
    /** Deployed models a `model-picker` field can offer. */
    model_catalog?: AdminModelCatalogEntry[];
    /**
     * `enable_*` keys the fallback scan must not draw.
     *
     * Some booleans in the settings document are derived or are staged rollout flags
     * with no administrator control. A switch for one would appear to save and then
     * revert, so the server names them and the scan skips them.
     */
    suppressed_capabilities: string[];
    version: string;
}

export interface AdminSettingsPatchResponse {
    success: boolean;
    updated_keys: string[];
    settings: Json;
    warnings: Record<string, string>;
}

export interface BrandingUploadResponse {
    success: boolean;
    target: string;
    url: string;
    version: number;
    stored_size: [number, number];
}

/** A `field_errors` map returned with a 400 from the settings PATCH. */
export function extractFieldErrors(payload: unknown): Record<string, string> {
    if (!payload || typeof payload !== 'object') {
        return {};
    }
    const candidate = (payload as { field_errors?: unknown }).field_errors;
    if (!candidate || typeof candidate !== 'object') {
        return {};
    }
    return Object.fromEntries(
        Object.entries(candidate as Record<string, unknown>).map(([key, value]) => [
            key,
            String(value),
        ]),
    );
}

/**
 * Read a field's current value, preferring an unsaved edit over the stored value.
 *
 * Falls back to the schema default rather than `undefined` so a control is never
 * uncontrolled on first render, which React would warn about and which would lose the
 * first keystroke.
 *
 * A field may declare `paths` when its value is not stored under its own key -- the Web
 * Search Foundry connection is assembled into a nested `web_search_agent` object by the
 * save handler. The draft is always keyed flat, because that is what the PATCH sends and
 * what the server unpacks; only the stored read follows the path.
 */
export function readFieldValue(field: AdminField, settings: Json, draft: Json): unknown {
    if (!field.key) {
        return undefined;
    }
    if (Object.prototype.hasOwnProperty.call(draft, field.key)) {
        return draft[field.key];
    }
    const stored = field.paths?.length
        ? readNestedSetting(settings, field.paths[0])
        : settings[field.key];

    if (stored !== undefined && stored !== null && field.scale) {
        // Stored in one unit, edited in another. File Sync's per-run limit is held
        // in bytes and entered in GB, and showing the byte count in a field labelled
        // GB would read as an absurd value.
        const scaled = Number(stored) / field.scale;
        return Number.isFinite(scaled) ? scaled : field.default;
    }

    return stored === undefined || stored === null ? field.default : stored;
}

/** Read a dotted path out of the settings document. */
export function readNestedSetting(settings: Json, path: string): unknown {
    let cursor: unknown = settings;
    for (const part of path.split('.')) {
        if (typeof cursor !== 'object' || cursor === null) {
            return undefined;
        }
        cursor = (cursor as Record<string, unknown>)[part];
    }
    return cursor;
}

export function asString(value: unknown, fallback = ''): string {
    if (value === undefined || value === null) {
        return fallback;
    }
    return typeof value === 'string' ? value : String(value);
}

export function asBoolean(value: unknown): boolean {
    if (typeof value === 'boolean') {
        return value;
    }
    if (typeof value === 'string') {
        return ['true', 'on', 'yes', '1'].includes(value.trim().toLowerCase());
    }
    return Boolean(value);
}

export function asNumber(value: unknown, fallback: number): number {
    const parsed = typeof value === 'number' ? value : Number.parseFloat(String(value ?? ''));
    return Number.isFinite(parsed) ? parsed : fallback;
}

export function asStringArray(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

/**
 * Whether a field's `depends_on` condition currently holds.
 *
 * Mirrors `evaluate_dependency` in `admin_settings_fields.py`; the two run the same rules
 * because the server enforces `min_selected` against the same conditions the browser uses
 * to decide what to draw. A disagreement would reject a save for a control the
 * administrator could not see.
 *
 * A boolean `equals` is compared loosely, because a switch value arriving from a stored
 * settings document may be `"on"` rather than `true`. A string `equals` is compared as a
 * string, which is what a select needs.
 */
export function isFieldVisible(field: AdminField, settings: Json, draft: Json): boolean {
    const read = (key: string): unknown =>
        Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : settings[key];
    return evaluateDependency(field.depends_on, read);
}

export function evaluateDependency(
    dependency: AdminFieldDependency | undefined,
    read: (key: string) => unknown,
): boolean {
    if (!dependency) {
        return true;
    }
    if (Array.isArray(dependency)) {
        // Every condition has to hold. This is the shorthand the Security and Workspaces
        // sections declare, and is equivalent to `all_of`.
        return dependency.every((condition) => evaluateDependency(condition, read));
    }

    if ('any_of' in dependency) {
        return dependency.any_of.some((nested) => evaluateDependency(nested, read));
    }

    if ('all_of' in dependency) {
        return dependency.all_of.every((nested) => evaluateDependency(nested, read));
    }

    const current = read(dependency.key);

    if (dependency.not_equals !== undefined) {
        return !dependencyValueMatches(current, dependency.not_equals);
    }

    return dependencyValueMatches(current, dependency.equals ?? true);
}

/**
 * Compare a stored value against a declared one.
 *
 * A boolean comparison goes through `asBoolean` because the server-rendered form stores
 * checkbox state as the string `"on"`, and a settings document written by that form has
 * to read the same way here.
 */
function dependencyValueMatches(current: unknown, expected: boolean | string): boolean {
    if (typeof expected === 'boolean') {
        return asBoolean(current) === expected;
    }
    return asString(current).trim() === String(expected);
}

/**
 * Whether a field's cross-section prerequisite is satisfied.
 *
 * Unlike `depends_on`, an unmet requirement does not hide the field. Hiding it would
 * leave an administrator hunting for a control that exists; showing it with the reason
 * attached is what lets them go and fix the cause.
 */
export function isRequirementSatisfied(
    field: AdminField,
    settings: Json,
    draft: Json,
): boolean {
    const requirement = field.requires;
    if (!requirement) {
        return true;
    }
    const current = Object.prototype.hasOwnProperty.call(draft, requirement.key)
        ? draft[requirement.key]
        : settings[requirement.key];
    return asBoolean(current);
}

/**
 * The placeholder the server sends in place of a stored secret.
 *
 * Mirrors `ADMIN_SETTINGS_SECRET_REDACTED_VALUE`. The browser never receives the real
 * value, so this is how a control tells "a secret is stored" apart from "no secret set",
 * and sending it back unchanged is what tells the server to keep the stored credential
 * rather than overwrite it with this string.
 */
export const SECRET_PLACEHOLDER = '***REDACTED***';

/** Retained name for the same placeholder, used by the Knowledge sections. */
export const SECRET_REDACTED_VALUE = SECRET_PLACEHOLDER;

export function isRedactedSecret(value: unknown): boolean {
    return asString(value).trim() === SECRET_PLACEHOLDER;
}

/**
 * A server-declared rule for reducing a section to one word.
 *
 * Sections that describe `required` fields have their status derived from those instead;
 * this exists for sections where "configured" depends on a combination the field
 * metadata cannot express on its own.
 */
export type DeclaredSectionStatus = 'off' | 'unconfigured' | 'on';

/**
 * Reduce a section to a single word an administrator can read without opening it.
 *
 * "Enabled" and "working" are not the same thing for an integration: Content Safety can
 * be switched on with no endpoint, in which case it silently does nothing. `unconfigured`
 * is that state, and it is the whole reason this exists rather than a plain on/off.
 */
export function evaluateSectionStatus(
    rule: AdminSectionStatusRule | undefined,
    settings: Json,
    draft: Json,
): DeclaredSectionStatus | null {
    if (!rule) {
        return null;
    }

    const read = (key: string): unknown =>
        Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : settings[key];

    if (!asBoolean(read(rule.enabled_key))) {
        return 'off';
    }

    for (const candidate of rule.configured ?? []) {
        const applies = Object.entries(candidate.when ?? {}).every(
            ([key, expected]) => asBoolean(read(key)) === expected,
        );
        if (!applies) {
            continue;
        }
        // Blank means unset. A secret key would read as its placeholder here, which is
        // correct: the placeholder means a value is stored, the browser just cannot see it.
        const missing = candidate.requires.some((key) => !asString(read(key)).trim());
        if (missing) {
            return 'unconfigured';
        }
    }

    return 'on';
}

/** Turn `enable_document_classification` into `Document classification`. */
export function humanizeKey(key: string): string {
    const withoutPrefix = key.replace(/^enable_/, '').replace(/_/g, ' ').trim();
    return withoutPrefix.charAt(0).toUpperCase() + withoutPrefix.slice(1);
}

/** Words in a textarea, matching the server's `len(text.split())`. */
export function countWords(text: string): number {
    const trimmed = text.trim();
    return trimmed ? trimmed.split(/\s+/).length : 0;
}

/** Text a field contributes to the page search index. */
export function fieldSearchText(field: AdminField): string {
    return [
        field.key ?? '',
        field.label,
        field.help ?? '',
        field.notice ?? '',
        field.component ?? '',
    ]
        .join(' ')
        .toLowerCase();
}

/** Entries of a `string_list`, tolerating the newline-joined shape V1 stores. */
export function parseStringList(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.filter((item): item is string => typeof item === 'string');
    }
    return asString(value)
        .split(/[\n,;]+/)
        .map((entry) => entry.trim())
        .filter(Boolean);
}

/** Fields in declared order, clustered by group, with ungrouped fields kept first. */
export interface RenderedFieldGroup {
    id: string;
    label?: string;
    variant?: AdminFieldGroup['variant'];
    help?: string;
    fields: AdminField[];
}

/**
 * Cluster a section's fields into their declared groups.
 *
 * Declared order is preserved both between groups and within them, because a section
 * reads top to bottom and the schema is where that order is decided. Fields with no
 * group form an implicit leading group, which is what keeps a section's capability
 * toggle above the detail it governs.
 */
export function groupFields(fields: AdminField[]): RenderedFieldGroup[] {
    const groups: RenderedFieldGroup[] = [];
    const byId = new Map<string, RenderedFieldGroup>();

    for (const field of fields) {
        // A group may be declared as a bare label or as an object with a variant.
        const declared = readFieldGroup(field.group);
        const id = declared?.id ?? '';
        let group = byId.get(id);
        if (!group) {
            group = {
                id,
                label: declared?.label,
                variant: declared?.variant,
                help: declared?.help,
                fields: [],
            };
            byId.set(id, group);
            groups.push(group);
        }
        group.fields.push(field);
    }

    return groups;
}

/** Settings that gate a capability behind an Entra app role. */
export const APP_ROLE_KEY_PREFIX = 'require_member_of_';

/**
 * The other naming a role requirement uses.
 *
 * `file_sync_personal_require_app_role` is the reason this exists: it gates a capability
 * behind an app role exactly like the `require_member_of_*` settings, but it is named
 * after its feature instead, so a prefix test alone leaves it out of the roster.
 */
export const APP_ROLE_KEY_SUFFIX = '_require_app_role';

export function isAppRoleKey(key: string | undefined): boolean {
    return Boolean(
        key && (key.startsWith(APP_ROLE_KEY_PREFIX) || key.endsWith(APP_ROLE_KEY_SUFFIX)),
    );
}

/** One app role requirement, with the section that owns its primary control. */
export interface AppRoleEntry {
    key: string;
    label: string;
    help?: string;
    groupLabel: string;
    tabLabel: string;
    sectionLabel: string;
    sectionId: string;
    /** From the server registry: the Entra role value to assign. */
    role?: string;
    /** What enforcing the requirement restricts. */
    grants?: string;
    /** Who keeps access while it is not enforced. */
    whenOff?: string;
    /** The capability this requirement is meaningless without, if any. */
    dependsOn?: string | null;
}

/**
 * Collect every declared app role requirement, in navigation order.
 *
 * The roster in Security mirrors switches that live on other tabs, so it has to know
 * where each one really belongs -- an administrator who flips a role here should be able
 * to find the feature it governs. Walking the navigation rather than the schema dict is
 * what puts the entries in the order the rest of the page uses, and it silently drops a
 * field filed under a section navigation does not define, which could never be reached.
 *
 * The schema is the source of which requirements exist, because the page's `enable_*`
 * fallback scan cannot see a role key: an undeclared one appears nowhere at all. The
 * server registry supplies what the schema does not carry -- the Entra role value, and
 * what changes in each direction -- keyed by settings key, so a requirement missing from
 * the registry still renders, just without that detail.
 */
export function collectAppRoleEntries(
    nav: import('./types').AdminNavGroup[],
    schema: AdminFieldSchema,
    requirements: AppRoleRequirement[] = [],
): AppRoleEntry[] {
    const byKey = new Map(requirements.map((entry) => [entry.key, entry]));
    const entries: AppRoleEntry[] = [];

    for (const group of nav) {
        for (const tab of group.tabs) {
            for (const section of tab.sections) {
                for (const field of schema[section.id] ?? []) {
                    if (!isAppRoleKey(field.key)) {
                        continue;
                    }
                    const key = field.key as string;
                    const registered = byKey.get(key);
                    entries.push({
                        key,
                        label: field.label,
                        help: field.help,
                        groupLabel: group.label,
                        tabLabel: tab.label,
                        sectionLabel: section.label,
                        sectionId: section.id,
                        role: registered?.role,
                        grants: registered?.grants,
                        whenOff: registered?.when_off,
                        dependsOn: registered?.depends_on ?? null,
                    });
                }
            }
        }
    }

    return entries;
}
