// ModelCatalogManager.tsx
import { useEffect, useRef } from 'react';
import { request } from '../../lib/apiClient';
import { modelConnectionsChanged } from '../../stores/modelConnectionsStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { toast } from '../../stores/toastStore';
import {
    mountModelCatalog, mountProfilePicker, type CatalogResponse,
} from '../../../../single_app/static/js/admin/model_catalog_ui.js';
import '../../../../single_app/static/css/model-catalog.css';

export function ModelCatalogManager() {
    const root = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (!root.current) return;
        return mountModelCatalog(root.current, {
            request: (path, options) => request<CatalogResponse>(path, options),
            onSaved: () => {
                modelConnectionsChanged();
                void useBootstrapStore.getState().refreshRequired().catch(() => {
                    toast.error('Catalog saved, but model availability could not refresh. Reload before selecting a model.');
                });
            },
        });
    }, []);
    return <div ref={root} data-testid="model-catalog-manager" />;
}

export function CatalogProfilePicker({ value, onChange }: { value?: string; onChange: (value: string) => void }) {
    const root = useRef<HTMLDivElement>(null);
    const change = useRef(onChange);
    change.current = onChange;
    useEffect(() => {
        if (!root.current) return;
        return mountProfilePicker(root.current, { catalogProfileId: value }, (id) => change.current(id),
            (path, options) => request<CatalogResponse>(path, options));
    }, [value]);
    return <div ref={root} />;
}
