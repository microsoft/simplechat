// refreshContext.ts
// Tells the open Control Center section that the stored figures were just recalculated.
//
// A refresh is started from the strip above every section, but what it changes is what each
// section shows, so each one has to reload. A counter in context lets a section reload
// without knowing who started the refresh, and keeps its filters, paging and selection where
// remounting the section would have reset them.

import { createContext, useContext, useEffect, useRef } from 'react';

/** Counts completed refreshes. Zero until one finishes while the Control Center is open. */
export const ControlCenterDataVersion = createContext(0);

/** Run `reload` each time a refresh completes, but not when the section first appears. */
export function useReloadOnDataRefresh(reload: () => void): void {
    const version = useContext(ControlCenterDataVersion);
    const seen = useRef(version);
    const latest = useRef(reload);
    latest.current = reload;

    useEffect(() => {
        if (version !== seen.current) {
            seen.current = version;
            latest.current();
        }
    }, [version]);
}
