// usePrincipalLabels.ts
// Resolve saved principal ids to names for display.
//
// A governance policy stores bare ids. An id is not something an administrator can
// recognise, so every place a policy's people or groups are shown resolves them first,
// through one shared cache so a name looked up for the list is not fetched again by the
// editor.

import { useEffect, useMemo, useState } from 'react';
import {
    cachedPrincipal,
    resolvePrincipals,
    type PrincipalKind,
    type PrincipalLookup,
} from '../../../lib/governance';

export interface PrincipalLabels {
    lookup: (id: string) => PrincipalLookup | undefined;
    resolving: boolean;
    /** The last lookup failed. Ids still show, and the policy still saves correctly. */
    failed: boolean;
}

export function usePrincipalLabels(kind: PrincipalKind, ids: readonly string[]): PrincipalLabels {
    const [version, setVersion] = useState(0);
    const [resolving, setResolving] = useState(false);
    const [failed, setFailed] = useState(false);

    const pendingKey = ids.filter((id) => !cachedPrincipal(kind, id)).join(',');

    useEffect(() => {
        if (!pendingKey) {
            return;
        }
        const controller = new AbortController();
        setResolving(true);
        void resolvePrincipals(kind, pendingKey.split(','), controller.signal)
            .then(() => {
                if (!controller.signal.aborted) {
                    setFailed(false);
                }
            })
            .catch(() => {
                if (!controller.signal.aborted) {
                    setFailed(true);
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) {
                    setResolving(false);
                    setVersion((current) => current + 1);
                }
            });
        return () => controller.abort();
    }, [kind, pendingKey]);

    // `version` is what re-renders consumers once the shared cache has been filled.
    const lookup = useMemo(
        () => {
            void version;
            return (id: string) => cachedPrincipal(kind, id);
        },
        [kind, version],
    );

    return { lookup, resolving, failed };
}
