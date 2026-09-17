// AppShell.tsx
// Two-column application frame: the collapsible rail on the left, all content on the
// right. The classification banner, when configured, is the only element allowed to span
// the full width, matching the server-rendered interface.
//
// The banner carries the same `classification-banner` id the classic layout uses, so a
// deployment styling or asserting against it does not have to know which interface it is
// looking at.

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { Toaster } from '../ui/Toaster';
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
            className="flex h-8 shrink-0 items-center justify-center text-sm font-bold tracking-wide"
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
        <div className="flex h-full flex-col">
            <ClassificationBanner />
            <div className="relative flex min-h-0 min-w-0 flex-1">
                {mobile && <div className="w-[68px] shrink-0" aria-hidden="true" />}
                {mobile && mobileNavOpen && (
                    <button
                        type="button"
                        tabIndex={-1}
                        aria-label="Close navigation"
                        className="absolute inset-0 z-40 bg-black/40"
                        onClick={() => setMobileNavOpen(false)}
                    />
                )}
                <Sidebar mobile={mobile} />
                <main ref={contentRef} className="flex min-w-0 flex-1 flex-col">{children}</main>
            </div>
            <Toaster />
        </div>
    );
}
