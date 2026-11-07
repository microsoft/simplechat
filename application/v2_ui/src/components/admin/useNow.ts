// useNow.ts
// The current time, refreshed on an interval, for readouts that say "in 3 hours".
//
// A relative time rendered once goes stale while the page stays open, which on a settings
// page left in a tab is most of the time. Ticking every half minute keeps "in 3 hours"
// honest without re-rendering every second.

import { useEffect, useState } from 'react';

export function useNow(intervalMs = 30_000): Date {
    const [now, setNow] = useState(() => new Date());

    useEffect(() => {
        const timer = window.setInterval(() => setNow(new Date()), intervalMs);
        return () => window.clearInterval(timer);
    }, [intervalMs]);

    return now;
}
