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
    | 'password'
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
 * `equals` is a boolean for a capability toggle and a string for a choice, such as an
 * authentication type. A string is compared as a string rather than for truthiness,
 * because every non-empty choice is truthy and so would satisfy every condition.
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
    /** Image fields only: which branding slot the upload endpoint should write. */
    upload_target?: 'logo' | 'logo_dark' | 'favicon';
    accept?: string;
    version_key?: string;
    /** Component fields only: which bespoke widget to render. */
    component?: string;
    depends_on?: AdminFieldDependency;
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
 * Whether a field's `depends_on` condition is currently satisfied.
 *
 * Two behaviours beyond the plain comparison, both of which exist because the server
 * schema is flat while the panes it mirrors are nested:
 *
 *   - A field whose dependency is itself hidden is hidden too. The Azure OpenAI key sits
 *     inside the direct-connection block *and* inside the key-authentication block on the
 *     server-rendered page; a single `depends_on` can only express one of those, so the
 *     other is inherited from the field it depends on. Without this, switching a section
 *     to APIM would leave the direct connection's key on screen.
 *   - A dependency with no stored value falls back to the declared default of the field
 *     it names, because that is what the application would be applying. Reading an absent
 *     value as empty would permanently hide anything conditional on a non-empty default.
 *
 * `siblings` supplies the fields the dependency may name; pass the section's own list.
 */
export function isFieldVisible(
    field: AdminField,
    settings: Json,
    draft: Json,
    siblings: AdminField[] = [],
    seen: Set<string> = new Set(),
): boolean {
    const dependency = field.depends_on;
    if (!dependency) {
        return true;
    }

    const stored = Object.prototype.hasOwnProperty.call(draft, dependency.key)
        ? draft[dependency.key]
        : settings[dependency.key];

    const parent = siblings.find((candidate) => candidate.key === dependency.key);
    const current = stored === undefined || stored === null ? parent?.default : stored;

    const satisfied =
        typeof dependency.equals === 'string'
            ? asString(current) === dependency.equals
            : asBoolean(current) === dependency.equals;

    if (!satisfied) {
        return false;
    }

    // A malformed schema could describe a cycle, and the schema test only rejects a
    // field depending on itself. Stopping at a repeat keeps a bad declaration from
    // hanging the page.
    if (!parent || !field.key || seen.has(field.key)) {
        return true;
    }
    return isFieldVisible(parent, settings, draft, siblings, new Set(seen).add(field.key));
}

/**
 * Whether a secret is already stored for a password field.
 *
 * Only presence is reported, never the value. The password control is write-only, so
 * the page has to be able to say "a key is stored" without putting that key into a
 * form control to find out.
 */
export function hasStoredSecret(settings: Json, key: string | undefined): boolean {
    if (!key) {
        return false;
    }
    const stored = settings[key];
    return typeof stored === 'string' && stored.trim().length > 0;
}

/**
 * What a password control shows: what has been typed this session, and nothing else.
 *
 * `null` is an explicit removal held in the draft. It renders as an empty box with a
 * pending-removal note rather than as the word "null".
 */
export function readSecretValue(field: AdminField, draft: Json): unknown {
    if (!field.key || !Object.prototype.hasOwnProperty.call(draft, field.key)) {
        return '';
    }
    return draft[field.key];
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
