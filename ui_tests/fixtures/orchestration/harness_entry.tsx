// harness_entry.tsx
//
// Test-only harness entry (NOT application source). It is bundled for the browser by
// build_harness.mjs and loaded by the ui_tests/test_v2_orchestration_*.py Playwright tests.
//
// The V2 UI ships as a bundled React SPA, so its orchestration components cannot be imported as
// plain browser ES modules the way the classic chat JS can. This entry imports the REAL
// components, stores, controller and plan library straight from application/v2_ui/src, and exposes
// them on window.OrchHarness so a test can seed the stores, mount a component into a real DOM, and
// drive it with genuine clicks. Nothing here is stubbed: the code under test is the code that ships.

import { createElement, type ReactElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

import * as orchestrationStore from '../../../application/v2_ui/src/stores/orchestrationStore';
import * as chatStore from '../../../application/v2_ui/src/stores/chatStore';
import * as bootstrapStore from '../../../application/v2_ui/src/stores/bootstrapStore';
import * as controller from '../../../application/v2_ui/src/lib/orchestrationController';
import * as plan from '../../../application/v2_ui/src/lib/orchestrationPlan';
import * as orchestration from '../../../application/v2_ui/src/lib/orchestration';

import { OrchestrationPlanCard } from '../../../application/v2_ui/src/components/chat/OrchestrationPlanCard';
import { ElicitationCard } from '../../../application/v2_ui/src/components/chat/ElicitationCard';
import { OrchestrationPlanPanel } from '../../../application/v2_ui/src/components/chat/OrchestrationPlanPanel';
import { OrchestrationRunView } from '../../../application/v2_ui/src/components/chat/OrchestrationRunView';
import { OrchestrationMapView } from '../../../application/v2_ui/src/components/chat/OrchestrationMapView';
import { Composer } from '../../../application/v2_ui/src/components/chat/Composer';

type ComponentName =
    | 'OrchestrationPlanCard'
    | 'ElicitationCard'
    | 'OrchestrationPlanPanel'
    | 'OrchestrationRunView'
    | 'OrchestrationMapView'
    | 'Composer';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const components: Record<ComponentName, (props: any) => ReactElement | null> = {
    OrchestrationPlanCard,
    ElicitationCard,
    OrchestrationPlanPanel,
    OrchestrationRunView,
    OrchestrationMapView,
    Composer,
};

const roots = new Map<string, Root>();

/** Mount a named component with plain-object props into the element with the given id. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function mount(containerId: string, name: ComponentName, props: Record<string, any> = {}): void {
    const container = document.getElementById(containerId);
    if (!container) {
        throw new Error(`harness mount: no element with id "${containerId}"`);
    }
    const Component = components[name];
    if (!Component) {
        throw new Error(`harness mount: unknown component "${name}"`);
    }
    let root = roots.get(containerId);
    if (!root) {
        root = createRoot(container);
        roots.set(containerId, root);
    }
    // Wrap every mount in a router: some components (notably the Composer's subtree) read the
    // location through react-router hooks, which throw outside a Router. A MemoryRouter supplies
    // that context without a browser history, and is harmless for components that never route.
    root.render(createElement(MemoryRouter, null, createElement(Component, props)));
}

/** Unmount whatever is in the given container, if anything. */
function unmount(containerId: string): void {
    const root = roots.get(containerId);
    if (root) {
        root.unmount();
        roots.delete(containerId);
    }
}

/** Unmount everything and clear both stores and persisted runs, for isolation between tests. */
function reset(): void {
    for (const [containerId, root] of roots) {
        root.unmount();
        const container = document.getElementById(containerId);
        if (container) {
            container.innerHTML = '';
        }
    }
    roots.clear();
    orchestrationStore.useOrchestrationStore.setState({
        plans: {},
        elicitations: {},
        edits: {},
        stepRuntime: {},
        inFlight: {},
        history: {},
        pinnedRunId: null,
        visibleConversationId: null,
        activeTurns: {},
    });
    chatStore.useChatStore.setState({
        activeConversationId: null,
        drawerMode: null,
        messages: [],
    });
    try {
        window.localStorage.clear();
    } catch {
        /* localStorage may be unavailable; the stores are already reset. */
    }
}

const harness = {
    createElement,
    mount,
    unmount,
    reset,
    stores: {
        orchestration: orchestrationStore,
        chat: chatStore,
        bootstrap: bootstrapStore,
    },
    controller,
    plan,
    orchestration,
    components,
};

declare global {
    interface Window {
        OrchHarness: typeof harness;
    }
}

window.OrchHarness = harness;
