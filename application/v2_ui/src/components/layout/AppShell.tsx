// AppShell.tsx
// Desktop rail and content frame, with a shared header/drawer on phones.
// The classification banner spans the frame, matching the server-rendered interface.
//
// The banner carries the same `classification-banner` id the classic layout uses, so a
// deployment styling or asserting against it does not have to know which interface it is
// looking at.

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { MobileNavigation, MobileNavigationContext } from './MobileNavigation';
import { Sidebar } from './Sidebar';
import { Toaster } from '../ui/Toaster';
import { SafetyWarningDialogHost } from '../notifications/SafetyWarningDialog';
import { WorkflowAlertCardHost } from '../notifications/WorkflowAlertCard';
import { WorkflowAlertLiveRegion } from '../notifications/WorkflowAlertLiveRegion';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUiStore } from '../../stores/uiStore';
import { useCollaborationStore } from '../../stores/collaborationStore';

function ClassificationBanner() {
    const banner = useBootstrapStore((state) => state.data?.branding?.classification_banner);

    if (!banner?.enabled || !banner.text) {
        return null;
    }

    return (
        <div
            id="classification-banner"
            role="note"
            className="flex min-h-8 shrink-0 items-center justify-center px-3 py-1 text-center text-sm font-bold tracking-wide break-words"
            style={{ background: banner.color, color: banner.text_color }}
        >
            {banner.text}
        </div>
    );
}

export function AppShell({ children }: { children: ReactNode }) {
    const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 767px)').matches);
    const mobileNavOpen = useUiStore((state) => state.mobileNavOpen);
    const setMobileNavOpen = useUiStore((state) => state.setMobileNavOpen);
    const participantsOpen = useCollaborationStore((state) => state.panelTarget !== null);
    const contentRef = useRef<HTMLElement>(null);
    const [headerCount, setHeaderCount] = useState(0);
    const register = useCallback((change: number) => setHeaderCount((count) => count + change), []);
    const title = useBootstrapStore((state) => state.data?.branding?.app_title || 'SimpleChat');

    useEffect(() => {
        const query = window.matchMedia('(max-width: 767px)');
        const update = () => {
            setMobile(query.matches);
            if (!query.matches) setMobileNavOpen(false);
        };
        update();
        query.addEventListener('change', update);
        return () => query.removeEventListener('change', update);
    }, [setMobileNavOpen]);

    useEffect(() => {
        if (contentRef.current) contentRef.current.inert = mobile && mobileNavOpen;
    }, [mobile, mobileNavOpen]);

    useEffect(() => {
        if (mobileNavOpen && participantsOpen) setMobileNavOpen(false);
    }, [mobileNavOpen, participantsOpen, setMobileNavOpen]);

    return (
        <MobileNavigationContext.Provider value={{ mobile, register }}>
            <div className="app-shell flex h-full min-h-0 flex-col">
                    <ClassificationBanner />
                    <div className="relative flex min-h-0 min-w-0 flex-1">
                        {mobile && mobileNavOpen && (
                            <button
                                type="button"
                                tabIndex={-1}
                                aria-label="Close navigation"
                                className="absolute inset-0 z-40 bg-black/40"
                                onClick={() => setMobileNavOpen(false)}
                            />
                        )}
                        {(!mobile || mobileNavOpen) && <Sidebar mobile={mobile} />}
                        <main ref={contentRef} className="flex min-h-0 min-w-0 flex-1 flex-col">
                            {mobile && headerCount === 0 && (
                                <header className="glass flex min-h-14 shrink-0 items-center gap-2 px-2">
                                    <MobileNavigation register={false} />
                                    <span className="truncate text-sm font-semibold">{title}</span>
                                </header>
                            )}
                            {children}
                        </main>
                    </div>
                    <Toaster />
                    <WorkflowAlertCardHost />
                    <WorkflowAlertLiveRegion />
                    <SafetyWarningDialogHost />
        </div>
        </MobileNavigationContext.Provider>
    );
}
