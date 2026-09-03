// tsResolve.mjs
//
// Lets a functional test import the V2 TypeScript modules directly.
//
// Node strips TypeScript types since 22.6, so the real module can be executed rather than a
// copy of it — which is the whole point, since a copy proves nothing about the code that
// ships. What Node does not do is resolve an extensionless specifier: the application writes
// `import { ... } from './agents'`, as a bundler expects, and Node looks for a file called
// exactly `agents`.
//
// Rewriting every application import to carry a `.ts` extension purely so a test can run it
// would be the test dictating the source. Registering a resolver here instead keeps the
// application untouched and keeps each test runnable with a plain `node <file>.mjs`.
//
// Importing this module registers the hook. It must therefore be imported *statically*,
// before the modules under test are pulled in with `await import(...)`, because a static
// import is evaluated before the importing module's own body runs.

import { registerHooks } from 'node:module';

/** Specifiers that already name a file extension and must be left alone. */
const HAS_EXTENSION = /\.[cm]?[jt]sx?$|\.json$/i;

registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier.startsWith('.') && !HAS_EXTENSION.test(specifier)) {
            // Tried first, and only for relative specifiers: a bare specifier is a package,
            // and appending `.ts` to one would break node_modules resolution entirely.
            for (const candidate of [`${specifier}.ts`, `${specifier}.tsx`]) {
                try {
                    return nextResolve(candidate, context);
                } catch {
                    /* Not this extension; fall through to the next, then to the original. */
                }
            }
        }
        return nextResolve(specifier, context);
    },
});
