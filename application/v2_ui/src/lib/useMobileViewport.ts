// useMobileViewport.ts
import { useEffect, useState } from 'react';

export function useMobileViewport() {
    const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 767px)').matches);
    useEffect(() => {
        const query = window.matchMedia('(max-width: 767px)');
        const update = () => setMobile(query.matches);
        query.addEventListener('change', update);
        return () => query.removeEventListener('change', update);
    }, []);
    return mobile;
}
