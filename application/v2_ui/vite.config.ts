// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// The V2 SPA is served by Flask out of application/single_app/static/v2.
//
// `base` is the asset URL prefix, and it deliberately differs from the app's route prefix:
// hashed assets are addressed at /static/v2/... so Flask's built-in static handler serves
// them (with its caching), while the app itself lives at /v2 and its client-side router
// uses /v2 as a basename. Keeping those separate means no asset request ever has to fall
// through the SPA catch-all route.
//
// Dev mode runs Vite on :5174 and proxies the SimpleChat JSON APIs to a locally running
// Flask app, which keeps the browser on a single origin so the Flask session cookie and
// the same-origin CSRF check behave exactly as they do in production.
const FLASK_DEV_ORIGIN = process.env.SIMPLECHAT_DEV_ORIGIN || 'http://127.0.0.1:5000';

const proxiedApiPaths = [
    '/api',
    '/upload',
    '/conversation',
    '/view_pdf',
    '/external',
    '/static',
];

export default defineConfig({
    base: '/static/v2/',
    plugins: [react(), tailwindcss()],
    build: {
        outDir: '../single_app/static/v2',
        emptyOutDir: true,
        sourcemap: false,
        rollupOptions: {
            output: {
                entryFileNames: 'assets/[name]-[hash].js',
                chunkFileNames: 'assets/[name]-[hash].js',
                assetFileNames: 'assets/[name]-[hash][extname]',
            },
        },
    },
    server: {
        port: 5174,
        proxy: Object.fromEntries(
            proxiedApiPaths.map((path) => [
                path,
                { target: FLASK_DEV_ORIGIN, changeOrigin: false },
            ]),
        ),
    },
});
