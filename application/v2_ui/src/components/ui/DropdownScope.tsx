// DropdownScope.tsx

import { createContext, useEffect, useRef, useState, type Dispatch, type ReactNode, type RefObject, type SetStateAction } from 'react';

export const DropdownScopeContext = createContext<{
    activeId: string | null;
    setActiveId: Dispatch<SetStateAction<string | null>>;
    enabled: boolean;
    boundary: RefObject<HTMLDivElement> | null;
} | null>(null);

/** Composer disclosures own picker lifetime without remounting their controls. */
export function DropdownScope({ children, mobileOpen, closeKey }: {
    children: ReactNode;
    mobileOpen: boolean;
    closeKey: string | null;
}) {
    const [desktop, setDesktop] = useState(() => window.matchMedia('(min-width: 768px)').matches);
    const [activeId, setActiveId] = useState<string | null>(null);
    const boundary = useRef<HTMLDivElement>(null);
    const enabled = desktop || mobileOpen;
    useEffect(() => {
        const media = window.matchMedia('(min-width: 768px)');
        const update = () => setDesktop(media.matches);
        media.addEventListener('change', update);
        return () => media.removeEventListener('change', update);
    }, []);
    useEffect(() => {
        setActiveId(null);
    }, [enabled, closeKey]);
    return (
        <DropdownScopeContext.Provider value={{ activeId, setActiveId, enabled, boundary: desktop ? null : boundary }}>
            <div ref={boundary} id="composer-secondary-tools" data-open={mobileOpen}
                className="composer-secondary-tools flex flex-wrap items-center gap-1.5 md:contents">
                {children}
            </div>
        </DropdownScopeContext.Provider>
    );
}
