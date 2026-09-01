// AppShell.tsx
// Two-column application frame: the collapsible rail on the left, all content on the
// right. The classification banner, when configured, is the only element allowed to span
// the full width, matching the server-rendered interface.

import type { ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { Toaster } from '../ui/Toaster';
import { useBootstrapStore } from '../../stores/bootstrapStore';

function ClassificationBanner() {
    const banner = useBootstrapStore((state) => state.data?.branding?.classification_banner);

    if (!banner?.enabled || !banner.text) {
        return null;
    }

    return (
        <div
            role="note"
            className="flex h-8 shrink-0 items-center justify-center text-sm font-bold tracking-wide"
            style={{ background: banner.color, color: banner.text_color }}
        >
            {banner.text}
        </div>
    );
}

export function AppShell({ children }: { children: ReactNode }) {
    return (
        <div className="flex h-full flex-col">
            <ClassificationBanner />
            <div className="flex min-h-0 flex-1">
                <Sidebar />
                <main className="flex min-w-0 flex-1 flex-col">{children}</main>
            </div>
            <Toaster />
        </div>
    );
}
