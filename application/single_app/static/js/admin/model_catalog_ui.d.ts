// model_catalog_ui.d.ts
export interface CatalogProfile {
    id: string;
    displayName: string;
    [key: string]: unknown;
}
export interface CatalogResponse {
    profiles: CatalogProfile[];
    tasks: Record<string, string>;
    etag?: string;
}
export type CatalogRequest = (path: string, options?: { method?: string; body?: unknown; signal?: AbortSignal }) => Promise<CatalogResponse>;
export function mountModelCatalog(root: HTMLElement, options?: { request?: CatalogRequest; onSaved?: () => void }): () => void;
export function mountProfilePicker(root: HTMLElement, model: { catalogProfileId?: string }, onChange: (id: string) => void, request?: CatalogRequest): () => void;
