// useClassicFragmentTranslation.ts
// Rewrites a classic URL fragment into the V2 address it names, once, when V2 opens on one.
//
// The server redirects a classic URL to V2 with its path and query mapped, but a server never sees the
// part after `#`. A browser keeps it across the redirect, so `/workspace#documents-tab` arrives as
// `/v2/workspace#documents-tab` and `/profile?tab=settings#m365-chat-connection` as
// `/v2/settings?tab=preferences#m365-chat-connection`. This hook asks `translateClassicFragment`
// whether the fragment is one the registry lists and, if it is, replaces the address (not a new history
// entry) with the route it names. Replacing drops the fragment, so the effect has nothing left to do and
// runs once. A fragment the registry does not list is left exactly as it is.

import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { translateClassicFragment } from './classicLinks';

export function useClassicFragmentTranslation(): void {
    const { pathname, search, hash } = useLocation();
    const navigate = useNavigate();

    useEffect(() => {
        const next = translateClassicFragment(pathname, search, hash);
        if (next !== null) {
            navigate({ pathname: next.pathname, search: next.search }, { replace: true });
        }
    }, [pathname, search, hash, navigate]);
}
