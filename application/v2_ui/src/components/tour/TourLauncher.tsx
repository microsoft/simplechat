// TourLauncher.tsx
// The button that starts a page's guided tour, and the `?tour=` arrival hook.
//
// Drawn only while the user wants it: the classic `showTutorialButtons` switch turns every
// tour off, and `tutorialVisibility` turns off one. Preferences can start a tour directly
// with `requestTour()` before navigating to its page; that works even when the button is
// hidden, because asking for a tour by name is an explicit choice. The request travels in
// session storage rather than the URL, so the chat page's own URL handling cannot drop it.

import { useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { CircleHelp } from 'lucide-react';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { consumeTourRequest, findTour, isTourEnabled } from '../../lib/tours';
import { GuidedTour } from './GuidedTour';

export function TourLauncher({ tourId, className }: { tourId: string; className?: string }) {
    const tour = findTour(tourId);
    const [open, setOpen] = useState(false);
    const settingsLoading = useUserSettingsStore((state) => state.loading);
    const enabled = useUserSettingsStore((state) =>
        isTourEnabled(tourId, state.settings.showTutorialButtons, state.settings.tutorialVisibility),
    );

    useEffect(() => {
        // Gives the page a moment to draw the controls the tour points at. The request is
        // consumed inside the timer so a mount that is torn down early leaves it in place.
        const timer = window.setTimeout(() => {
            if (consumeTourRequest(tourId)) {
                setOpen(true);
            }
        }, 400);
        return () => window.clearTimeout(timer);
    }, [tourId]);

    if (!tour) {
        return null;
    }

    return (
        <>
            {enabled && !settingsLoading && (
                <button
                    type="button"
                    onClick={() => setOpen(true)}
                    title={`Take the ${tour.title.toLowerCase()}`}
                    aria-label={`Take the ${tour.title.toLowerCase()}`}
                    className={clsx(
                        'rounded-lg p-2 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1',
                        className,
                    )}
                >
                    <CircleHelp size={17} />
                </button>
            )}
            {open && <GuidedTour tour={tour} onClose={() => setOpen(false)} />}
        </>
    );
}
