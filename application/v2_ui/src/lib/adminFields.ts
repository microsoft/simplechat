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
    | 'entry_list'
    | 'id_list'
    | 'group_picker'
    | 'component';

export interface AdminFieldOption {
    value: string;
    label: string;
}

/**
 * Shows a field only while a condition holds.
 *
 * `key` names another settings field. `flag` names a server-resolved runtime flag
 * instead, for a capability gated outside the settings document -- Inbound MCP is
 * gated by an App Service application setting, so there is no settings key to
 * depend on.
 *
 * `equals` is a string for a select, and a boolean for a switch. A field may carry one
 * of these or an array of them, in which case every condition has to hold — Content
 * Safety's key is gated on the capability, the routing choice and the auth type at once.
 */
export interface AdminFieldCondition {
    key?: string;
    flag?: string;
    equals: boolean | string;
}

/** One condition, or a chain of them that must all hold. */
export type AdminFieldDependency = AdminFieldCondition | AdminFieldCondition[];

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
    /** Optional sub-heading grouping consecutive fields inside one section. */
    group?: string;
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
    /** Connection test components only: which `test_connection` branch to call. */
    test_type?: string;
    /**
     * Path into a nested settings object this field reads and writes.
     *
     * A few settings are stored as one object rather than as top-level keys.
     * `key` stays the flat name used in the draft and in field errors; the
     * server folds the value back into the container on save.
     */
    settings_path?: string[];
    /** Reports a value that something else owns. Never editable here. */
    readonly?: boolean;
    /** Where a read-only mirror is actually configured. */
    managed_by?: string;
    /** Entry list fields only: what one row's identifier is called. */
    value_label?: string;
    /** Entry list fields only: what to say when the list is empty. */
    empty_text?: string;
    /** Group fields only: start the group closed. Rarely-changed settings. */
    collapsed?: boolean;
    /**
     * Standing guidance shown as a callout beneath the control.
     *
     * Distinct from `help`, which describes what the setting does, and from the
     * server's per-save `warnings`, which react to a submitted value. A notice is
     * an operational caveat that is true whenever the setting is on screen.
     */
    notice?: string;
    notice_level?: 'info' | 'warning';
    /** One condition, or a chain that must all hold. */
    depends_on?: AdminFieldCondition | AdminFieldCondition[];
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

export interface AdminSettingsResponse {
    settings: Json;
    admin_nav: import('./types').AdminNavGroup[];
    field_schema: AdminFieldSchema;
    section_status: AdminSectionStatusSchema;
    app_role_requirements: AppRoleRequirement[];
    branding_assets: BrandingAssets;
    /**
     * Server-resolved flags a navigation section may be conditional on.
     *
     * `mcp_ui_enabled` comes from an App Service application setting rather than
     * the settings document, so it cannot be read from `settings`.
     */
    runtime_flags?: Record<string, boolean>;
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

/** Walk a dotted path into the settings document, or undefined if it is not there. */
export function readNestedValue(settings: Json, path: string[]): unknown {
    let node: unknown = settings;
    for (const segment of path) {
        if (!node || typeof node !== 'object' || Array.isArray(node)) {
            return undefined;
        }
        node = (node as Record<string, unknown>)[segment];
    }
    return node;
}

/**
 * Read a field's current value, preferring an unsaved edit over the stored value.
 *
 * Falls back to the schema default rather than `undefined` so a control is never
 * uncontrolled on first render, which React would warn about and which would lose the
 * first keystroke.
 *
 * A field with a `settings_path` is stored inside a nested object, so only the draft is
 * keyed by its flat name; the saved value has to be walked to.
 */
export function readFieldValue(field: AdminField, settings: Json, draft: Json): unknown {
    if (!field.key) {
        return undefined;
    }
    if (Object.prototype.hasOwnProperty.call(draft, field.key)) {
        return draft[field.key];
    }
    const stored = field.settings_path
        ? readNestedValue(settings, field.settings_path)
        : settings[field.key];
    return stored === undefined || stored === null ? field.default : stored;
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

/** Every `depends_on` condition a field declares, whether one or a chain. */
export function fieldDependencies(field: AdminField): AdminFieldCondition[] {
    const dependency = field.depends_on;
    if (!dependency) {
        return [];
    }
    return Array.isArray(dependency) ? dependency : [dependency];
}

/** Index every declared field by the settings key it edits. */
export function buildFieldIndex(schema: AdminFieldSchema): Map<string, AdminField> {
    const index = new Map<string, AdminField>();
    for (const fields of Object.values(schema)) {
        for (const field of fields) {
            if (!field.key) {
                continue;
            }
            const existing = index.get(field.key);
            // A key declared twice is a read-only mirror of a field edited
            // elsewhere. The writable declaration describes where the value really
            // lives, so it wins regardless of declaration order.
            if (!existing || (existing.readonly && !field.readonly)) {
                index.set(field.key, field);
            }
        }
    }
    return index;
}

/**
 * Read the current value of a key another field depends on.
 *
 * A gate may itself be stored inside a nested object -- the document action limits are
 * gated by an `enabled` flag that lives in the same container -- so the key alone is not
 * enough to find the saved value.
 */
function readDependencyValue(
    key: string,
    settings: Json,
    draft: Json,
    fieldsByKey?: Map<string, AdminField>,
): unknown {
    if (Object.prototype.hasOwnProperty.call(draft, key)) {
        return draft[key];
    }
    const gate = fieldsByKey?.get(key);
    return gate?.settings_path ? readNestedValue(settings, gate.settings_path) : settings[key];
}

/**
 * Whether every one of a field's `depends_on` conditions is currently satisfied.
 *
 * Each condition is judged against the unsaved draft first, so a field appears
 * or disappears as soon as its gate is flipped rather than only after a save.
 * A condition naming a `flag` is answered from the server's runtime flags, which
 * an administrator cannot change from this page at all.
 */
export function isFieldVisible(
    field: AdminField,
    settings: Json,
    draft: Json,
    fieldsByKey?: Map<string, AdminField>,
    runtimeFlags?: Record<string, boolean>,
): boolean {
    return fieldDependencies(field).every((dependency) => {
        if (dependency.flag) {
            return Boolean(runtimeFlags?.[dependency.flag]) === dependency.equals;
        }
        if (!dependency.key) {
            return true;
        }
        const current = readDependencyValue(dependency.key, settings, draft, fieldsByKey);
        return typeof dependency.equals === 'string'
            ? asString(current) === dependency.equals
            : asBoolean(current) === dependency.equals;
    });
}

/**
 * Whether a navigation section's `condition` holds.
 *
 * A condition names either a settings key or a server-resolved runtime flag.
 * Runtime flags win, because a flag such as `mcp_ui_enabled` deliberately has no
 * entry in the settings document.
 */
export function isSectionVisible(
    condition: string | undefined,
    settings: Json,
    draft: Json,
    runtimeFlags: Record<string, boolean>,
    fieldsByKey?: Map<string, AdminField>,
): boolean {
    if (!condition) {
        return true;
    }
    if (Object.prototype.hasOwnProperty.call(runtimeFlags, condition)) {
        return runtimeFlags[condition];
    }
    return asBoolean(readDependencyValue(condition, settings, draft, fieldsByKey));
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

export type SectionStatus = 'off' | 'unconfigured' | 'on';

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
): SectionStatus | null {
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

/** A run of fields sharing a `group`, or a single ungrouped field. */
export type SectionBlock =
    | { kind: 'field'; field: AdminField }
    | { kind: 'group'; name: string; collapsed: boolean; fields: AdminField[] };

/**
 * Lay a section's fields out as ordered blocks.
 *
 * A group appears where its first field does, so declaration order still decides what an
 * administrator reads first. Grouping exists because a section can hold several unrelated
 * concerns -- the Agents page has its hero, its guidance text and its promotions, and Key
 * Vault has its connection settings and its expiration reminders -- and a flat list of a
 * dozen controls gives no clue which ones belong together. A group may also start closed,
 * which is what keeps the always-on built-in actions out of the way.
 */
export function buildSectionBlocks(fields: AdminField[]): SectionBlock[] {
    const blocks: SectionBlock[] = [];
    const groups = new Map<string, Extract<SectionBlock, { kind: 'group' }>>();

    for (const field of fields) {
        if (!field.group) {
            blocks.push({ kind: 'field', field });
            continue;
        }
        const existing = groups.get(field.group);
        if (existing) {
            existing.fields.push(field);
            continue;
        }
        const group: Extract<SectionBlock, { kind: 'group' }> = {
            kind: 'group',
            name: field.group,
            // Only the first field of a group decides how it opens, so a group
            // cannot end up half-collapsed depending on which field is read.
            collapsed: Boolean(field.collapsed),
            fields: [field],
        };
        groups.set(field.group, group);
        blocks.push(group);
    }

    return blocks;
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
