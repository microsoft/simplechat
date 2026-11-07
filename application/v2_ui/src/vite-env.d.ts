// vite-env.d.ts
/// <reference types="vite/client" />

interface ImportMetaEnv {
    /**
     * Origin of the SimpleChat Flask API.
     *
     * Left unset for the default same-origin deployment. Set at build time only when the
     * SPA is deployed to its own App Service, in which case the Flask app must also have
     * V2_UI_ALLOWED_ORIGIN configured so it emits CORS headers and trusts the origin for
     * CSRF.
     */
    readonly VITE_API_BASE?: string;
}

interface ImportMeta {
    readonly env: ImportMetaEnv;
}
