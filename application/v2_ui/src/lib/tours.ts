// tours.ts
// The guided tours V2 ships, and the rules deciding which of them a user is offered.
//
// The classic interface has a chat tutorial and a workspace tutorial behind one switch,
// `showTutorialButtons`. V2 keeps that switch, shared with the classic interface, and adds
// `tutorialVisibility` so a user can keep one tour and drop the other.
//
// A step names its target by `data-tour` attribute rather than by class or id, so restyling
// a control cannot quietly break a tour. A step whose target is missing or not visible is
// skipped when the tour runs: the composer's attach button, for instance, is not drawn when
// uploads are off, and a tour that pointed at nothing would be worse than one step shorter.
//
// The ids must match TUTORIAL_IDS in route_backend_users.py, which rejects any other key.
//
// Kept free of store and React imports so it can be tested directly. The request helpers
// touch session storage only when called.

export interface TourStep {
    /** The `data-tour` value of the element this step points at. */
    target: string;
    title: string;
    body: string;
}

export interface TourDefinition {
    id: string;
    title: string;
    description: string;
    /** The V2 route the tour runs on. */
    path: string;
    steps: TourStep[];
}

export const TOURS: TourDefinition[] = [
    {
        id: 'chat',
        title: 'Chat tour',
        description: 'The conversation list, the composer and the controls around a reply.',
        path: '/chat',
        steps: [
            {
                target: 'new-chat',
                title: 'Start a conversation',
                body: 'Opens a fresh conversation. Earlier ones stay in the list below.',
            },
            {
                target: 'conversation-list',
                title: 'Your conversations',
                body: 'Search, pin, select and export conversations here. Hover a conversation for its actions.',
            },
            {
                target: 'chat-header',
                title: 'Conversation tools',
                body: 'Share the conversation, widen the reading area, and open the details, contents and documents panels.',
            },
            {
                target: 'message-list',
                title: 'The conversation',
                body: 'Replies appear here. Hover a reply to see its sources and details, or one of your own messages to edit it.',
            },
            {
                target: 'composer-input',
                title: 'Write a message',
                body: 'Type your question. Start with / to insert one of your saved prompts.',
            },
            {
                target: 'composer-tools',
                title: 'Choose what the answer draws on',
                body: 'Pick a model or agent, search your workspaces, and turn on web search or image generation where they are offered.',
            },
            {
                target: 'composer-attach',
                title: 'Attach a file',
                body: 'Add a file to this conversation so the answer can use it.',
            },
            {
                target: 'composer-send',
                title: 'Send',
                body: 'Sends the message. While a reply is streaming, this becomes a stop button.',
            },
            {
                target: 'user-menu',
                title: 'Your settings',
                body: 'Open User Settings to change the text size, sounds, memory and these tours.',
            },
        ],
    },
    {
        id: 'workspace',
        title: 'Workspace tour',
        description: 'The sections of a workspace: documents, prompts, agents and connections.',
        path: '/workspace',
        steps: [
            {
                target: 'workspace-sections',
                title: 'Workspace sections',
                body: 'Everything this workspace holds is grouped here: knowledge, automation and connections.',
            },
            {
                target: 'workspace-overview',
                title: 'Overview',
                body: 'The starting point for this workspace, with a summary of what it holds.',
            },
            {
                target: 'workspace-content',
                title: 'Work with the section',
                body: 'Upload documents, write prompts or configure agents here, depending on the section you picked.',
            },
            {
                target: 'workspace-rail-toggle',
                title: 'More room',
                body: 'Collapse the sections to icons when you need the space. The choice is remembered.',
            },
        ],
    },
];

export function findTour(id: string): TourDefinition | undefined {
    return TOURS.find((tour) => tour.id === id);
}

/**
 * Whether a tour is offered. The classic master switch wins; a tour missing from the
 * per-tour map is shown.
 */
export function isTourEnabled(
    tourId: string,
    showTutorialButtons: unknown,
    tutorialVisibility: unknown,
): boolean {
    if (showTutorialButtons === false) {
        return false;
    }
    if (tutorialVisibility && typeof tutorialVisibility === 'object') {
        const value = (tutorialVisibility as Record<string, unknown>)[tourId];
        if (value === false) {
            return false;
        }
    }
    return true;
}

/** The per-tour map with one tour changed, keeping only shipped ids. */
export function withTourVisibility(
    current: unknown,
    tourId: string,
    visible: boolean,
): Record<string, boolean> {
    const next: Record<string, boolean> = {};
    const known = new Set(TOURS.map((tour) => tour.id));
    if (current && typeof current === 'object') {
        for (const [key, value] of Object.entries(current as Record<string, unknown>)) {
            if (known.has(key) && typeof value === 'boolean') {
                next[key] = value;
            }
        }
    }
    if (known.has(tourId)) {
        next[tourId] = visible;
    }
    return next;
}

const TOUR_REQUEST_KEY = 'simplechat.v2.pendingTour';

/** Asks the next page that hosts this tour to start it on arrival. */
export function requestTour(tourId: string): void {
    try {
        window.sessionStorage.setItem(TOUR_REQUEST_KEY, tourId);
    } catch {
        // Storage can be unavailable; the user can still start the tour from its page.
    }
}

/** Whether a tour was requested for this page, clearing the request either way it matches. */
export function consumeTourRequest(tourId: string): boolean {
    try {
        if (window.sessionStorage.getItem(TOUR_REQUEST_KEY) !== tourId) {
            return false;
        }
        window.sessionStorage.removeItem(TOUR_REQUEST_KEY);
        return true;
    } catch {
        return false;
    }
}
