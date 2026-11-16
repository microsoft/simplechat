// MobileNavigation.tsx

import { createContext, useContext, useLayoutEffect } from 'react';
import { Menu } from 'lucide-react';
import { useUiStore } from '../../stores/uiStore';
import { NotificationBell } from './NotificationBell';

export const MobileNavigationContext = createContext({
    mobile: false,
    register: (_change: number) => {},
});

export function MobileNavigation({ register = true }: { register?: boolean }) {
    const context = useContext(MobileNavigationContext);
    const open = useUiStore((state) => state.mobileNavOpen);
    const setOpen = useUiStore((state) => state.setMobileNavOpen);

    useLayoutEffect(() => {
        if (!register) return;
        context.register(1);
        return () => context.register(-1);
    }, [register, context.register]);

    if (!context.mobile) return null;

    return (
        <div className="mobile-navigation-controls flex shrink-0 items-center gap-1">
            <button type="button" aria-label="Open navigation" aria-expanded={open}
                aria-controls="primary-navigation" onClick={() => setOpen(true)}
                className="flex h-11 w-11 items-center justify-center rounded-lg text-text-2 hover:bg-surface-2">
                <Menu size={20} />
            </button>
            <NotificationBell collapsed={false} />
        </div>
    );
}
