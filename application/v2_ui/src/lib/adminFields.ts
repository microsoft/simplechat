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
    | 'component';

export interface AdminFieldOption {
    value: string;
    label: string;
}

/**
 * Shows a field only while another field holds a given value.
 *
 * `equals` is a string for a select, and a boolean for a switch. A field may carry one
 * of these or an array of them, in which case every condition has to hold — Content
 * Safety's key is gated on the capability, the routing choice and the auth type at once.
 */
export interface AdminFieldCondition {
    key: string;
    equals: boolean | string;
}

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
    /** Note fields only. */
    tone?: 'info' | 'warning';
    body?: string;
    /** Optional sub-heading grouping consecutive fields inside one section. */
    group?: string;
    /** Image fields only: which branding slot the upload endpoint should write. */
    upload_target?: 'logo' | 'logo_dark' | 'favicon';
    accept?: string;
    version_key?: string;
    /** Component fields only: which bespoke widget to render. */
    component?: string;
    /** Connection test components only: which `test_connection` branch to call. */
    test_type?: string;
    depends_on?: AdminFieldDependency;
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
 * Whether every `depends_on` condition on a field currently holds.
 *
 * A boolean `equals` is compared loosely, because a switch value arriving from a stored
 * settings document may be `"on"` rather than `true`. A string `equals` is compared as a
 * string, which is what a select needs.
 */
export function isFieldVisible(field: AdminField, settings: Json, draft: Json): boolean {
    const dependency = field.depends_on;
    if (!dependency) {
        return true;
    }
    const conditions = Array.isArray(dependency) ? dependency : [dependency];

    return conditions.every((condition) => {
        const current = Object.prototype.hasOwnProperty.call(draft, condition.key)
            ? draft[condition.key]
            : settings[condition.key];
        return typeof condition.equals === 'boolean'
            ? asBoolean(current) === condition.equals
            : asString(current) === condition.equals;
    });
}

/**
 * The placeholder the server sends in place of a stored secret.
 *
 * Mirrors `ADMIN_SETTINGS_SECRET_REDACTED_VALUE`. The browser never receives the real
 * value, so this is how a control tells "a secret is stored" apart from "no secret set".
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
    return [field.key ?? '', field.label, field.help ?? '', field.component ?? '']
        .join(' ')
        .toLowerCase();
}
