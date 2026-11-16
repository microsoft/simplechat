// orchestrationMerge.ts
// How the plan card states the settings of a spreadsheet merge, inspection or document merge step.
//
// tabular_merge, tabular_inspect and document_merge arguments are enums, column lists and small
// objects. The card shows each one in words, leaves out values that only restate a default, and
// treats column and sheet names as data. A value the server would refuse is not put in words.

/** The orchestration capability that merges CSV and Excel files. */
export const TABULAR_MERGE_CAPABILITY = 'tabular_merge';

/** The orchestration capability that inspects CSV and Excel files before a merge. */
export const TABULAR_INSPECT_CAPABILITY = 'tabular_inspect';

/** The orchestration capability that merges PDFs, Word documents, decks or workbooks into one file. */
export const DOCUMENT_MERGE_CAPABILITY = 'document_merge';

const DOCUMENT_KIND_WORDS: Record<string, string> = {
    pdf: 'One PDF',
    docx: 'One Word document',
    pptx: 'One PowerPoint deck',
    workbook: 'One Excel workbook, a sheet per file',
};

const SCHEMA_POLICY_WORDS: Record<string, string> = {
    by_name: 'Same columns, in any order',
    exact_order: 'Same columns, in the same order',
    union: 'Keep every column from every file',
    mapped: 'Only the listed columns',
};

const SORT_TYPE_WORDS: Record<string, string> = {
    text: 'text',
    number: 'number',
    date: 'date',
};

const DOC_SCOPE_WORDS: Record<string, string> = {
    personal: 'Personal workspace',
    group: 'Group workspaces',
    public: 'Public workspaces',
};

const DEFAULT_SOURCE_COLUMN = 'Source File';

function has(record: Record<string, string>, key: unknown): key is string {
    return typeof key === 'string' && Object.prototype.hasOwnProperty.call(record, key);
}

function names(value: unknown): string[] {
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is string => typeof item === 'string' && item.trim() !== '');
}

function aliasWords(value: unknown): string {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return '';
    return Object.entries(value as Record<string, unknown>)
        .map(([target, aliases]) => {
            const others = names(aliases);
            return target.trim() && others.length ? `${target} \u2190 ${others.join(', ')}` : '';
        })
        .filter(Boolean)
        .join('; ');
}

function sortWords(value: unknown): string {
    if (!Array.isArray(value)) return '';
    const keys: string[] = [];
    for (const item of value) {
        if (!item || typeof item !== 'object' || Array.isArray(item)) return '';
        const key = item as Record<string, unknown>;
        if (typeof key.column !== 'string' || !key.column.trim()) return '';
        if (key.value_type !== undefined && !has(SORT_TYPE_WORDS, key.value_type)) return '';
        const details = [
            has(SORT_TYPE_WORDS, key.value_type) && key.value_type !== 'text' ? SORT_TYPE_WORDS[key.value_type] : '',
            key.descending === true ? 'descending' : '',
        ].filter(Boolean);
        keys.push(details.length ? `${key.column} (${details.join(', ')})` : key.column);
    }
    return keys.join(', ');
}

function tableEntries(args: Record<string, unknown>): Array<[string, string]> {
    const entries: Array<[string, string]> = [];
    if (has(DOC_SCOPE_WORDS, args.doc_scope)) {
        entries.push(['workspace', DOC_SCOPE_WORDS[args.doc_scope]]);
    }
    if (typeof args.sheet === 'string' && args.sheet.trim()) {
        entries.push(['sheet', args.sheet]);
    } else if (args.sheets === 'all') {
        entries.push(['sheets', 'Every visible sheet']);
    }
    if (typeof args.header_row === 'number' && Number.isInteger(args.header_row) && args.header_row >= 1) {
        entries.push(['header row', `Row ${args.header_row}`]);
    }
    return entries;
}

function mergeEntries(args: Record<string, unknown>): Array<[string, string]> {
    const entries: Array<[string, string]> = [];
    if (has(SCHEMA_POLICY_WORDS, args.schema_policy)) {
        entries.push(['columns', SCHEMA_POLICY_WORDS[args.schema_policy]]);
    }
    const kept = names(args.columns);
    if (kept.length) {
        entries.push(['keep', kept.join(', ')]);
    }
    const aliases = aliasWords(args.column_aliases);
    if (aliases) {
        entries.push(['same column as', aliases]);
    }
    entries.push(...tableEntries(args));
    if (args.include_source_column === false) {
        entries.push(['file name column', 'Off']);
    } else if (typeof args.source_column_name === 'string' && args.source_column_name.trim()
        && args.source_column_name.trim() !== DEFAULT_SOURCE_COLUMN) {
        entries.push(['file name column', args.source_column_name]);
    }
    if (args.on_incompatible === 'exclude') {
        entries.push(['files that don\u2019t fit', 'Left out and reported']);
    }
    const keep = args.dedupe_keep === 'last' ? 'keeping the last' : 'keeping the first';
    if (args.dedupe === 'exact_rows') {
        entries.push(['duplicates', `Remove identical rows, ${keep}`]);
    } else if (args.dedupe === 'key_columns') {
        const keys = names(args.dedupe_columns);
        if (keys.length) {
            entries.push(['duplicates', `Remove rows with the same ${keys.join(', ')}, ${keep}`]);
        }
    }
    const order = sortWords(args.sort_by);
    if (order) {
        entries.push(['sort by', order]);
    }
    return entries;
}

function inspectEntries(args: Record<string, unknown>): Array<[string, string]> {
    const entries = tableEntries(args);
    if (typeof args.sample_rows === 'number' && Number.isInteger(args.sample_rows)
        && args.sample_rows >= 0 && args.sample_rows <= 10) {
        entries.push(['sample rows', String(args.sample_rows)]);
    }
    return entries;
}

function documentMergeEntries(args: Record<string, unknown>): Array<[string, string]> {
    const entries: Array<[string, string]> = [];
    const kind = args.kind;
    if (has(DOCUMENT_KIND_WORDS, kind)) {
        entries.push(['creates', DOCUMENT_KIND_WORDS[kind]]);
    }
    if (has(DOC_SCOPE_WORDS, args.doc_scope)) {
        entries.push(['workspace', DOC_SCOPE_WORDS[args.doc_scope]]);
    }
    if (kind === 'pdf' && args.bookmarks === false) {
        entries.push(['bookmarks', 'Off']);
    }
    if ((kind === 'docx' || kind === 'pptx') && args.formatting === 'use_first') {
        entries.push(['formatting', kind === 'docx' ? 'The first document\u2019s styles' : 'The first deck\u2019s theme']);
    }
    if (kind === 'docx' && args.page_breaks === false) {
        entries.push(['page breaks', 'Off']);
    }
    if (kind === 'docx' && args.source_headings === true) {
        entries.push(['file name headings', 'On']);
    }
    if (kind === 'pptx' && args.sections === false) {
        entries.push(['sections', 'Off']);
    }
    if (kind === 'workbook') {
        const sheet = typeof args.sheet === 'string' && args.sheet.trim() && args.sheet.length <= 31
            ? args.sheet
            : null;
        // A named sheet with sheets "all" is refused by the server, so neither is put in words.
        if (sheet !== null && args.sheets !== 'all') {
            entries.push(['sheet', sheet]);
        } else if (args.sheet === undefined || args.sheet === null) {
            if (args.sheets === 'all') entries.push(['sheets', 'Every visible sheet']);
        }
    }
    return entries;
}

/**
 * The arguments of a merge or inspection step in words, or null for any other capability.
 * Document selections are shown as chips by the card, so they are never listed here.
 */
export function tabularArgumentEntries(capabilityId: string, args: unknown): Array<[string, string]> | null {
    if (
        capabilityId !== TABULAR_MERGE_CAPABILITY && capabilityId !== TABULAR_INSPECT_CAPABILITY
        && capabilityId !== DOCUMENT_MERGE_CAPABILITY
    ) {
        return null;
    }
    const record = args && typeof args === 'object' && !Array.isArray(args)
        ? args as Record<string, unknown>
        : {};
    if (capabilityId === DOCUMENT_MERGE_CAPABILITY) {
        return documentMergeEntries(record);
    }
    return capabilityId === TABULAR_MERGE_CAPABILITY ? mergeEntries(record) : inspectEntries(record);
}
