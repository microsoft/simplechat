// workflowDocumentSelection.ts
// Typed metadata selection; only the server evaluates regular expressions.

export const MAX_DOCUMENT_WINDOW_MINUTES = 525600;
export const DOCUMENT_FILE_TYPES = [
    'pdf', 'csv', 'xlsx', 'xls', 'xlsm', 'docx', 'doc', 'pptx', 'ppt', 'txt', 'md',
    'json', 'xml', 'html', 'htm', 'tsv', 'png', 'jpg', 'jpeg', 'tiff',
] as const;
export type DocumentScope = { scope_type: 'personal' | 'group' | 'public'; scope_id?: string };
export type DocumentFilterField = 'filename' | 'tags' | 'file_type' | 'classification' | 'author' | 'keywords';
export type DocumentFilterOperator = 'equals' | 'starts_with' | 'contains' | 'regex' | 'has_any' | 'has_all';
export interface DocumentFilterPredicate {
    field: DocumentFilterField;
    operator: DocumentFilterOperator;
    value: string | string[];
    match_case?: boolean;
}
export interface DocumentFilterGroup {
    operator: 'and' | 'or';
    conditions: DocumentFilter[];
}
export type DocumentFilter = DocumentFilterPredicate | DocumentFilterGroup;
export interface TaskDocumentSelection {
    scopes: DocumentScope[];
    filters: DocumentFilter;
    on_empty: 'report' | 'error';
}
export const WINDOW_UNITS = { minutes: 1, hours: 60, days: 1440, weeks: 10080 } as const;
export type WindowUnit = keyof typeof WINDOW_UNITS;
export function documentWindowUnit(minutes: number): WindowUnit {
    return (['weeks', 'days', 'hours', 'minutes'] as WindowUnit[]).find(
        (unit) => minutes > 0 && minutes % WINDOW_UNITS[unit] === 0,
    ) ?? 'minutes';
}
export function documentScopeKey(scope: DocumentScope): string {
    return `${scope.scope_type}:${scope.scope_id ?? ''}`;
}
export function defaultDocumentSelection(scope: DocumentScope): TaskDocumentSelection {
    return { scopes: [scope], filters: { operator: 'and', conditions: [] }, on_empty: 'report' };
}
export function documentFilterCount(node: DocumentFilter): number {
    return 'conditions' in node ? 1 + node.conditions.reduce((total, child) => total + documentFilterCount(child), 0) : 1;
}
export function isTaskDocumentSelection(value: unknown): value is TaskDocumentSelection {
    const record = (item: unknown): item is Record<string, unknown> =>
        Boolean(item) && typeof item === 'object' && !Array.isArray(item);
    const onlyKeys = (item: Record<string, unknown>, allowed: string[]) => Object.keys(item).every((key) => allowed.includes(key));
    if (!record(value) || !onlyKeys(value, ['scopes', 'filters', 'on_empty']) ||
        !['report', 'error'].includes(String(value.on_empty)) ||
        !Array.isArray(value.scopes) || value.scopes.length > 20 || !value.scopes.every((scope: unknown) =>
        record(scope) && onlyKeys(scope, ['scope_type', 'scope_id']) && ['personal', 'group', 'public'].includes(String(scope.scope_type)) &&
        (scope.scope_id === undefined || typeof scope.scope_id === 'string'))) return false;
    let count = 0;
    const visit = (node: unknown, depth: number): boolean => {
        if (!record(node) || ++count > 32 || depth > 4) return false;
        if ('conditions' in node) return onlyKeys(node, ['operator', 'conditions']) && Array.isArray(node.conditions) &&
            ['and', 'or'].includes(String(node.operator)) && node.conditions.every((child: unknown) => visit(child, depth + 1));
        return onlyKeys(node, ['field', 'operator', 'value', 'match_case']) &&
            ['filename', 'tags', 'file_type', 'classification', 'author', 'keywords'].includes(String(node.field)) &&
            ['equals', 'starts_with', 'contains', 'regex', 'has_any', 'has_all'].includes(String(node.operator)) &&
            (typeof node.value === 'string' && node.value.length <= 256 ||
                Array.isArray(node.value) && node.value.length <= 100 &&
                node.value.every((item: unknown) => typeof item === 'string' && item.length <= 256)) &&
            (node.match_case === undefined || typeof node.match_case === 'boolean');
    };
    return visit(value.filters, 1);
}
export function documentSelectionErrors(selection: TaskDocumentSelection, minutes: number): string[] {
    const errors: string[] = [];
    if (!isTaskDocumentSelection(selection)) return ['This document selection has an unsupported structure. Review or reset it before saving.'];
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > MAX_DOCUMENT_WINDOW_MINUTES) {
        errors.push('Choose a whole-number window from 1 minute to 365 days.');
    }
    if (!selection || !Array.isArray(selection.scopes) || !selection.scopes.length || selection.scopes.length > 20 ||
        selection.scopes.some((scope) => !scope || !['personal', 'group', 'public'].includes(scope.scope_type) ||
            (scope.scope_type === 'personal' ? Boolean(scope.scope_id) : !scope.scope_id ||
                scope.scope_id !== scope.scope_id.trim() || scope.scope_id.length > 256)) ||
        new Set(selection.scopes.map(documentScopeKey)).size !== selection.scopes.length) {
        errors.push('Choose between 1 and 20 available workspaces.');
    }
    if (!selection || !['report', 'error'].includes(selection.on_empty)) errors.push('Choose how to handle no matches.');
    let count = 0;
    const visit = (node: DocumentFilter, depth: number) => {
        count += 1;
        if (!node || depth > 4 || count > 32) {
            errors.push('Use at most 32 conditions or groups and 4 total filter levels.');
            return;
        }
        if ('conditions' in node) {
            if (!Array.isArray(node.conditions) || !['and', 'or'].includes(node.operator)) {
                errors.push('Choose Match all or Match any for each filter group.');
            } else {
                if (depth > 1 && !node.conditions.length) errors.push('Add a condition or remove the empty group.');
                node.conditions.forEach((child) => visit(child, depth + 1));
            }
            return;
        }
        const arrayField = node.field === 'tags' || node.field === 'file_type';
        if (!['filename', 'tags', 'file_type', 'classification', 'author', 'keywords'].includes(node.field) ||
            !(node.field === 'file_type' ? ['has_any'] : arrayField ? ['has_any', 'has_all'] : node.field === 'filename'
                ? ['equals', 'starts_with', 'contains', 'regex'] : ['equals', 'starts_with', 'contains']).includes(node.operator)) {
            errors.push('Choose a supported metadata condition.');
        } else if (arrayField) {
            if (!Array.isArray(node.value) || !node.value.length || node.value.length > 100 ||
                node.value.some((value) => !value.trim() || value.length > 256) ||
                new Set(node.value).size !== node.value.length) {
                errors.push('Select one or more values for each tag or file-type filter.');
            } else if (node.field === 'file_type' && node.value.some(
                (value) => !(DOCUMENT_FILE_TYPES as readonly string[]).includes(value),
            )) errors.push('Choose a supported file extension.');
        } else if (typeof node.value !== 'string' || !node.value.trim() || node.value.length > 256) {
            errors.push('Enter a value for each metadata condition (at most 256 characters).');
        }
    };
    if (selection?.filters) visit(selection.filters, 1);
    else errors.push('Review the document filters.');
    return [...new Set(errors)];
}
export function documentFilterSummary(node: DocumentFilter): string {
    if ('conditions' in node) return node.conditions.length
        ? `(${node.conditions.map(documentFilterSummary).join(node.operator === 'and' ? ' AND ' : ' OR ')})`
        : 'any metadata';
    const label = node.field === 'file_type' ? 'file type' : node.field;
    return `${label} ${node.operator.replaceAll('_', ' ')} ${Array.isArray(node.value) ? node.value.join(', ') || '…' : node.value || '…'}${node.match_case ? ' (case-sensitive)' : ''}`;
}
