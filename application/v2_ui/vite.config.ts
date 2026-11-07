// vite.config.ts
import { defineConfig, type Plugin } from 'vite';
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

/** Where Vite serves the app's own modules in dev, the same prefix as `base`. */
const APP_ASSET_PREFIX = '/static/v2/';

const proxiedApiPaths = [
    '/api',
    '/upload',
    '/conversation',
    '/view_pdf',
    '/external',
    '/static',
];

/**
 * Open the app at /v2 in dev, as Flask does in production.
 *
 * The router's basename is /v2, but Vite serves the page at `base`, so a page load at /v2/...
 * would otherwise be answered with Vite's "did you mean /static/v2/" page. Page loads there
 * are handed the app's index.html instead. Registered straight onto the middleware stack so
 * it runs ahead of Vite's base handling and the proxy.
 */
function serveAppRoutesInDev(): Plugin {
    return {
        name: 'simplechat-v2-app-routes',
        apply: 'serve',
        configureServer(server) {
            server.middlewares.use((req, _res, next) => {
                const path = (req.url ?? '').split('?')[0];
                const pageLoad = (req.method === 'GET' || req.method === 'HEAD')
                    && (req.headers.accept ?? '').includes('text/html');
                if (pageLoad && (path === '/v2' || path.startsWith('/v2/'))) {
                    req.url = APP_ASSET_PREFIX;
                }
                next();
            });
        },
    };
}

export default defineConfig({
    base: APP_ASSET_PREFIX,
    plugins: [react(), tailwindcss(), serveAppRoutesInDev()],
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
                {
                    target: FLASK_DEV_ORIGIN,
                    changeOrigin: false,
                    // /static/v2/ is this server's own modules, not Flask's built copy of them;
                    // returning the URL hands the request back to Vite unchanged.
                    bypass: path === '/static'
                        ? (req: { url?: string }) => (req.url?.startsWith(APP_ASSET_PREFIX) ? req.url : undefined)
                        : undefined,
                },
            ]),
        ),
    },
});
