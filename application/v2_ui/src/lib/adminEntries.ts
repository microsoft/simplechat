// adminEntries.ts
// Pure helpers for the `{ value, description }` allowlists the inbound MCP settings use.
//
// Kept out of the component so a test can execute them. The shape has to match what
// `normalize_inbound_mcp_value_entries` keeps, because a row that does not survive
// normalization disappears on save with no explanation.

/** One allowlist row: an identifier the runtime matches, and who it belongs to. */
export interface AllowlistEntry {
    value: string;
    description: string;
}

/** Read the stored value defensively; it is administrator data from the database. */
export function readEntryList(value: unknown): AllowlistEntry[] {
    if (!Array.isArray(value)) {
        return [];
    }
    return value.map((item) => {
        // The server has always accepted a bare string as shorthand for a value with
        // no description, so a list written before descriptions existed still reads.
        if (typeof item === 'string') {
            return { value: item, description: '' };
        }
        if (!item || typeof item !== 'object') {
            return { value: '', description: '' };
        }
        const entry = item as Record<string, unknown>;
        return {
            value: typeof entry.value === 'string' ? entry.value : '',
            description: typeof entry.description === 'string' ? entry.description : '',
        };
    });
}

/**
 * The rows the server will keep, in order.
 *
 * Empty values are dropped and repeats collapse to the first occurrence, matching
 * `normalize_inbound_mcp_value_entries`. Used to tell an administrator how many entries a
 * save will actually produce, rather than how many rows are on screen.
 */
export function effectiveEntries(
    entries: AllowlistEntry[],
    lowercase = false,
): AllowlistEntry[] {
    const seen = new Set<string>();
    const kept: AllowlistEntry[] = [];

    for (const entry of entries) {
        const raw = entry.value.trim();
        if (!raw) {
            continue;
        }
        const value = lowercase ? raw.toLowerCase() : raw;
        if (seen.has(value)) {
            continue;
        }
        seen.add(value);
        kept.push({ value, description: entry.description.trim() });
    }

    return kept;
}
