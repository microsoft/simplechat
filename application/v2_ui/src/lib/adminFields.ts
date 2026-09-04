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
    | 'image'
    | 'link_list'
    | 'id_list'
    | 'group_picker'
    | 'component';

/**
 * The placeholder the server sends in place of a stored secret.
 *
 * Mirrors `ADMIN_SETTINGS_SECRET_REDACTED_VALUE`. A secret field that still holds this
 * has not been edited, and sending it back is what tells the server to keep the stored
 * value rather than overwrite the credential with the mask.
 */
export const REDACTED_SECRET = '***REDACTED***';

export interface AdminFieldOption {
    value: string;
    label: string;
}

/**
 * Shows a field only while another field holds a given value.
 *
 * `equals` is usually a boolean, gating a field on a capability switch. A string gates
 * it on a select instead: each Enhanced Citations storage credential applies to one
 * authentication type only.
 */
export interface AdminFieldDependency {
    key: string;
    equals: boolean | string;
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
    /**
     * Standing guidance shown as a callout beneath the control.
     *
     * Distinct from `help`, which describes what the setting does, and from the
     * server's per-save `warnings`, which react to a submitted value. A notice is
     * an operational caveat that is true whenever the setting is on screen.
     */
    notice?: string;
    notice_level?: 'info' | 'warning';
    depends_on?: AdminFieldDependency | AdminFieldDependency[];
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
 * Whether a field's `depends_on` condition is currently satisfied.
 *
 * `depends_on` is normally one condition, and may be a list, in which case every
 * condition must hold. A list is needed wherever a control is gated on a sibling whose
 * own default would otherwise reveal it -- the Enhanced Citations storage credentials are
 * chosen by authentication type, but must stay hidden while the capability itself is off.
 */
export function isFieldVisible(field: AdminField, settings: Json, draft: Json): boolean {
    if (!field.depends_on) {
        return true;
    }

    const conditions = Array.isArray(field.depends_on)
        ? field.depends_on
        : [field.depends_on];

    return conditions.every((dependency) => {
        const current = Object.prototype.hasOwnProperty.call(draft, dependency.key)
            ? draft[dependency.key]
            : settings[dependency.key];

        // A string condition compares the select's value; anything else is a switch.
        return typeof dependency.equals === 'string'
            ? asString(current) === dependency.equals
            : asBoolean(current) === dependency.equals;
    });
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

/** Settings that gate a capability behind an Entra app role. */
export const APP_ROLE_KEY_PREFIX = 'require_member_of_';

/** One app role requirement, with the section that owns its primary control. */
export interface AppRoleEntry {
    key: string;
    label: string;
    help?: string;
    groupLabel: string;
    tabLabel: string;
    sectionLabel: string;
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
 * Only declared fields are visible: the page's `enable_*` fallback scan cannot see a
 * `require_member_of_*` key, so an undeclared role requirement appears nowhere at all and
 * would be missing from the roster for the same reason.
 */
export function collectAppRoleEntries(
    nav: import('./types').AdminNavGroup[],
    schema: AdminFieldSchema,
): AppRoleEntry[] {
    const entries: AppRoleEntry[] = [];

    for (const group of nav) {
        for (const tab of group.tabs) {
            for (const section of tab.sections) {
                for (const field of schema[section.id] ?? []) {
                    if (!field.key?.startsWith(APP_ROLE_KEY_PREFIX)) {
                        continue;
                    }
                    entries.push({
                        key: field.key,
                        label: field.label,
                        help: field.help,
                        groupLabel: group.label,
                        tabLabel: tab.label,
                        sectionLabel: section.label,
                    });
                }
            }
        }
    }

    return entries;
}
