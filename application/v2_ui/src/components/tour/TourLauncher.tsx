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
import type { HeaderAction } from '../layout/HeaderActions';

export function useTourLauncher(tourId: string, available = true) {
    const tour = findTour(tourId);
    const [open, setOpen] = useState(false);
    const settingsLoading = useUserSettingsStore((state) => state.loading);
    const enabled = useUserSettingsStore((state) =>
        isTourEnabled(tourId, state.settings.showTutorialButtons, state.settings.tutorialVisibility),
    );

    useEffect(() => {
        if (!available) return;
        // Gives the page a moment to draw the controls the tour points at. The request is
        // consumed inside the timer so a mount that is torn down early leaves it in place.
        const timer = window.setTimeout(() => {
            if (consumeTourRequest(tourId)) {
                setOpen(true);
            }
        }, 400);
        return () => window.clearTimeout(timer);
    }, [tourId, available]);

    const label = tour ? `Take the ${tour.title.toLowerCase()}` : '';
    const action: HeaderAction | null = tour && available && enabled && !settingsLoading ? {
        id: `tour-${tourId}`, label, icon: <CircleHelp size={17} />,
        onClick: () => setOpen(true), iconOnly: true,
    } : null;
    return {
        action,
        dialog: tour && open ? <GuidedTour tour={tour} onClose={() => setOpen(false)} /> : null,
    };
}

export function TourLauncher({ tourId, className }: { tourId: string; className?: string }) {
    const { action, dialog } = useTourLauncher(tourId);

    return (
        <>
            {action && (
                <button
                    type="button"
                    onClick={action.onClick}
                    title={action.label}
                    aria-label={action.label}
                    className={clsx(
                        'shrink-0 rounded-lg p-2 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 max-md:min-h-11 max-md:min-w-11',
                        className,
                    )}
                >
                    <CircleHelp size={17} />
                </button>
            )}
            {dialog}
        </>
    );
}
