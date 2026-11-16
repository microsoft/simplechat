// appNavigation.ts
// The router, for code that runs outside React.
//
// A desktop notification is clicked long after the render that raised it, and the handler
// that answers it is plain code rather than a component. It still has to move the SPA to a
// conversation without reloading the page. Likewise the chat store has to know whether the
// chat page is the one on screen when a reply lands. The notification runtime registers the
// router's navigator here while the application is mounted, and reports each route change;
// everything else asks. The module imports nothing, so stores can use it without a cycle.

export interface AppNavigator {
    navigate: (path: string) => void;
    /** The current route, relative to the router's `/v2` base. */
    pathname: () => string;
}

/** A route the application moved to, relative to the router's `/v2` base. */
export interface AppRoute {
    pathname: string;
    /** The query string it arrived with, including the leading `?` when there is one. */
    search: string;
}

type RouteListener = (route: AppRoute) => void;

let current: AppNavigator | null = null;
const routeListeners = new Set<RouteListener>();

/** Register the navigator. Returns the function that removes it again. */
export function registerAppNavigator(navigator: AppNavigator): () => void {
    current = navigator;
    return () => {
        if (current === navigator) {
            current = null;
        }
    };
}

export function getAppNavigator(): AppNavigator | null {
    return current;
}

/** Report a route change to every listener. A failing listener cannot stop the others. */
export function announceRouteChange(route: AppRoute): void {
    for (const listener of [...routeListeners]) {
        try {
            listener(route);
        } catch (error) {
            console.warn('A route listener failed.', error);
        }
    }
}

/** Hear about route changes. Returns the function that stops listening. */
export function subscribeRouteChanges(listener: RouteListener): () => void {
    routeListeners.add(listener);
    return () => {
        routeListeners.delete(listener);
    };
}
