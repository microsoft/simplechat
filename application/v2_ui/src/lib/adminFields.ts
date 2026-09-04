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
    | 'select'
    | 'switch'
    | 'checkbox_set'
    | 'color'
    | 'range'
    | 'number'
    | 'image'
    | 'link_list'
    | 'component'
    | 'secret'
    | 'string_list'
    | 'id_list'
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
 * The single-key form covers most cases. `any_of` exists because some blocks are
 * revealed by more than one capability -- the Speech resource configuration is shared by
 * audio uploads, voice input and voice responses, and showing it three times would be
 * three ways to edit one credential.
 */
export type AdminFieldDependency =
    | { key: string; equals: boolean | string; not_equals?: never }
    | { key: string; not_equals: boolean | string; equals?: never }
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

/** The cluster a field belongs to within its section. */
export interface AdminFieldGroup {
    id: string;
    label?: string;
    variant?: 'connection' | 'behavior' | 'limits' | 'access' | 'advanced';
    help?: string;
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
     * `id_list` fields only: where to look identifiers up, and which response fields
     * carry the id and its labels. Mirrors the `data-*` attributes the server-rendered
     * File Sync pane puts on its target pickers.
     */
    search_endpoint?: string;
    results_key?: string;
    value_field?: string;
    title_field?: string;
    subtitle_field?: string;
    /** `status` fields only: which server-computed readout to show. */
    status_source?: string;
    depends_on?: AdminFieldDependency;
    requires?: AdminFieldRequirement;
    group?: AdminFieldGroup;
    requires_acknowledgement?: AdminFieldAcknowledgement;
}

/** Section id -> ordered fields. Section ids come from `admin_settings_nav.py`. */
export type AdminFieldSchema = Record<string, AdminField[]>;

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
    branding_assets: BrandingAssets;
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
 */
export function readFieldValue(field: AdminField, settings: Json, draft: Json): unknown {
    if (!field.key) {
        return undefined;
    }
    if (Object.prototype.hasOwnProperty.call(draft, field.key)) {
        return draft[field.key];
    }
    const stored = settings[field.key];
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

/**
 * Whether a field's `depends_on` condition currently holds.
 *
 * Mirrors `evaluate_dependency` in `admin_settings_fields.py`; the two run the same rules
 * because the server enforces `min_selected` against the same conditions the browser uses
 * to decide what to draw. A disagreement would reject a save for a control the
 * administrator could not see.
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

    if ('any_of' in dependency) {
        return dependency.any_of.some((nested) => evaluateDependency(nested, read));
    }

    if ('all_of' in dependency) {
        return dependency.all_of.every((nested) => evaluateDependency(nested, read));
    }

    const current = read(dependency.key);

    if ('not_equals' in dependency && dependency.not_equals !== undefined) {
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
    return [field.key ?? '', field.label, field.help ?? '', field.component ?? '']
        .join(' ')
        .toLowerCase();
}

/**
 * Placeholder the server sends in place of a stored credential.
 *
 * Mirrors `SECRET_REDACTED_VALUE` in `admin_settings_fields.py`. Submitting it back means
 * "unchanged", so the renderer must be able to tell a still-redacted field from one the
 * administrator actually edited.
 */
export const SECRET_REDACTED_VALUE = '***REDACTED***';

export function isRedactedSecret(value: unknown): boolean {
    return asString(value).trim() === SECRET_REDACTED_VALUE;
}

/** Newline-delimited storage shape shared with the server-rendered textareas. */
export function parseStringList(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.filter((item): item is string => typeof item === 'string');
    }
    return asString(value)
        .split('\n')
        .map((entry) => entry.trim())
        .filter(Boolean);
}

export function serializeStringList(entries: string[]): string {
    return entries.join('\n');
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
        const id = field.group?.id ?? '';
        let group = byId.get(id);
        if (!group) {
            group = {
                id,
                label: field.group?.label,
                variant: field.group?.variant,
                help: field.group?.help,
                fields: [],
            };
            byId.set(id, group);
            groups.push(group);
        }
        group.fields.push(field);
    }

    return groups;
}
