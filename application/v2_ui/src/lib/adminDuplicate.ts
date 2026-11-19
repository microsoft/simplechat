// adminDuplicate.ts
// The starting draft of a copy of a global agent or action.
//
// Administrators clone an organisation agent or action to make a variant of it: another
// persona over the same actions, the same connector pointed at a second system. The classic
// admin tables offered Duplicate for both. It deep-copied the row, dropped its id, named the
// copy `<name>_copy` and opened the editor on it. This does the same, with the differences
// that matter now that a record can hold stored credentials:
//
// - Nothing the record marks as a secret is copied. The editor contract lists each secret's
//   JSON pointer in `secret_paths`, and the copy is built without them, so a clone can never
//   inherit another record's key, its Key Vault reference or the placeholder the server shows
//   in its place. The copy needs credentials of its own, entered in the editor before it saves.
// - The copy starts disabled. A global record is live for everyone the moment it is enabled,
//   and a draft that has none of its credentials yet is not something to publish by accident.
//
// The copy is only a draft. Nothing is stored until the administrator saves it in the editor,
// which also gives the server's name and validation errors somewhere to be read.

import {
    editorName,
    isRecord,
    withoutServerStampedFields,
    type ActionConfiguration,
    type AgentConfiguration,
    type AuthoringResource,
} from './workspaceAuthoring';
import { newAgentDraft } from './workspaceAgentAuthoring';
import { createActionDraft } from './workspaceActionLogic';

/** The longest record name and display name the server accepts. */
const NAME_LIMIT = 100;
const DISPLAY_NAME_LIMIT = 200;

/** Ownership, identity and audit fields a stored record carries and a new one must not. */
const STORAGE_FIELDS = [
    'id', 'user_id', 'group_id', 'created_at', 'created_by', 'modified_at', 'modified_by', 'last_updated',
    'is_global', 'is_group',
];

/**
 * The name of a copy: `<name>_copy`, then `_copy_2`, `_copy_3` and so on, the first not taken.
 *
 * Compared ignoring case, as the server does, and kept to the characters and length a record
 * name allows. The server still checks on save, so a name taken in the meantime is reported in
 * the editor rather than silently reused.
 */
export function duplicateName(name: string, existingNames: readonly string[]): string {
    const taken = new Set(existingNames.map((existing) => existing.trim().toLowerCase()));
    const base = editorName(name, 'copy');
    const fit = (suffix: string) => `${base.slice(0, NAME_LIMIT - suffix.length)}${suffix}`;
    let candidate = fit('_copy');
    for (let attempt = 2; taken.has(candidate.toLowerCase()); attempt += 1) {
        candidate = fit(`_copy_${attempt}`);
    }
    return candidate;
}

/** `<display name> Copy`, falling back to the record name, within the display name limit. */
export function duplicateDisplayName(displayName: string, name: string): string {
    const base = (displayName.trim() || name.trim() || 'Untitled').slice(0, DISPLAY_NAME_LIMIT - ' Copy'.length);
    return `${base.trimEnd()} Copy`;
}

function pointerParts(pointer: string): string[] | null {
    if (!pointer.startsWith('/')) {
        return null;
    }
    return pointer.slice(1).split('/').map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'));
}

const ARRAY_INDEX = /^(0|[1-9]\d*)$/;

/**
 * A copy of a record without the values at the given JSON pointers.
 *
 * An object loses the key. An array keeps its length with an empty entry in place of the
 * value, because removing it would move every later entry to a position the server reads as
 * a different credential.
 */
export function withoutSecretPaths<T extends object>(record: T, secretPaths: readonly string[]): T {
    const clone = structuredClone(record) as Record<string, unknown>;
    for (const pointer of secretPaths) {
        const parts = pointerParts(pointer);
        if (!parts?.length) {
            continue;
        }
        let parent: unknown = clone;
        for (const part of parts.slice(0, -1)) {
            parent = Array.isArray(parent)
                ? ARRAY_INDEX.test(part) ? parent[Number(part)] : undefined
                : isRecord(parent) ? parent[part] : undefined;
            if (parent === undefined || parent === null) {
                break;
            }
        }
        const last = parts[parts.length - 1];
        if (Array.isArray(parent)) {
            if (ARRAY_INDEX.test(last) && Number(last) < parent.length) {
                parent[Number(last)] = '';
            }
        } else if (isRecord(parent)) {
            delete parent[last];
        }
    }
    return clone as T;
}

function withoutStorageFields<T extends object>(record: T): T {
    const clone = withoutServerStampedFields(record) as Record<string, unknown>;
    for (const field of STORAGE_FIELDS) {
        delete clone[field];
    }
    for (const key of Object.keys(clone)) {
        if (key.startsWith('_')) {
            delete clone[key];
        }
    }
    return clone as T;
}

/** A copy's draft, and how many stored credentials were left out of it. */
export interface DuplicateDraft<T> {
    draft: T;
    omittedSecrets: number;
}

/** The draft of a copy of a global agent, read from its editor resource. */
export function duplicateAgentDraft(
    source: AuthoringResource<AgentConfiguration>,
    existingNames: readonly string[],
): DuplicateDraft<AgentConfiguration> {
    const record = withoutStorageFields(withoutSecretPaths(source.record, source.secret_paths));
    return {
        draft: {
            ...newAgentDraft(),
            ...record,
            id: '',
            name: duplicateName(source.record.name ?? '', existingNames),
            display_name: duplicateDisplayName(source.record.display_name ?? '', source.record.name ?? ''),
            is_enabled: false,
        },
        omittedSecrets: source.secret_paths.length,
    };
}

/** The draft of a copy of a global action, read from its editor resource. */
export function duplicateActionDraft(
    source: AuthoringResource<ActionConfiguration>,
    existingNames: readonly string[],
): DuplicateDraft<ActionConfiguration> {
    const record = withoutStorageFields(withoutSecretPaths(source.record, source.secret_paths));
    return {
        draft: {
            ...createActionDraft(),
            ...record,
            id: '',
            name: duplicateName(source.record.name ?? '', existingNames),
            displayName: duplicateDisplayName(source.record.displayName ?? '', source.record.name ?? ''),
            is_enabled: false,
        },
        omittedSecrets: source.secret_paths.length,
    };
}

/** What the administrator is told as the editor opens on a copy. */
export function describeDuplicate(label: string, omittedSecrets: number): string {
    const lead = `Editing a copy of ${label}. It starts disabled; enable it from the list once it is ready.`;
    if (!omittedSecrets) {
        return lead;
    }
    const credentials = omittedSecrets === 1 ? 'The stored credential was' : `The ${omittedSecrets} stored credentials were`;
    return `${lead} ${credentials} not copied, so enter new ones before saving.`;
}
