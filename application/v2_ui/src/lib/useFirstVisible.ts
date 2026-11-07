// useFirstVisible.ts
// Whether an element has scrolled into view at least once.
//
// The Scale readouts ask Redis, Cosmos and Azure Monitor for live status. "All settings"
// renders every card at once, so loading on mount would query all of them whenever an
// administrator opens the page for any reason. Waiting until a card is actually seen keeps
// those calls to the cards someone looks at. Once seen, it stays loaded.

import { useEffect, useState, type RefObject } from 'react';

export function useFirstVisible<T extends Element>(ref: RefObject<T | null>, enabled = true): boolean {
    const [visible, setVisible] = useState(false);

    useEffect(() => {
        if (!enabled || visible) {
            return;
        }
        const element = ref.current;
        if (!element) {
            return;
        }
        if (typeof IntersectionObserver === 'undefined') {
            setVisible(true);
            return;
        }
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    setVisible(true);
                    observer.disconnect();
                }
            },
            // Start slightly before the card arrives, so it is usually ready when it does.
            { rootMargin: '240px 0px' },
        );
        observer.observe(element);
        return () => observer.disconnect();
    }, [ref, enabled, visible]);

    return visible;
}
