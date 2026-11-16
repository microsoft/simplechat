// M365CitationContext.tsx
// The Microsoft 365 records of the message being rendered, for its citation chips.
//
// A chip receives only the marker group parsed out of the text, and the markdown renderer's
// component map must not be rebuilt when a message's records change (see AssistantMarkdown),
// so the records reach the chips through context rather than through props.

import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { readM365Citations } from '../../lib/m365Citations';
import type { M365Citation } from '../../lib/types';

const NO_RECORDS: ReadonlyMap<string, M365Citation> = new Map();

const M365CitationContext = createContext<ReadonlyMap<string, M365Citation>>(NO_RECORDS);

/**
 * Make one message's Microsoft 365 records available to the chips rendered inside it.
 *
 * Keyed on what the records say rather than on the array that carries them, because any edit
 * to the message produces a new array holding the same records.
 */
export function M365CitationProvider({
    citations,
    children,
}: {
    citations: unknown;
    children: ReactNode;
}) {
    const key = JSON.stringify(Array.isArray(citations) ? citations : []);
    const value = useMemo(() => {
        const records = readM365Citations(JSON.parse(key) as unknown);
        return records.length > 0
            ? new Map(records.map((record) => [record.citation_id, record] as const))
            : NO_RECORDS;
    }, [key]);
    return <M365CitationContext.Provider value={value}>{children}</M365CitationContext.Provider>;
}

/** The record a chip's citation id names in the current message, when it has one. */
export function useM365Citation(citationId: string): M365Citation | undefined {
    return useContext(M365CitationContext).get(citationId);
}
