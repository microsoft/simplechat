// imageProposalQueue.ts
// Runs image proposal approvals one at a time.
//
// "Approve all image proposals" can approve a whole slide deck's worth of visuals at once.
// Firing those concurrently would open several image generation requests in parallel, which
// is slow, easy to rate-limit, and gives the user no sense of progress. The classic client
// serialises them for the same reason (`imageProposalQueue` in
// static/js/chat/chat-inline-image-proposals.js), and this is that queue.
//
// The queue is module-level rather than per message, because the limit being respected
// belongs to the image deployment, not to any one conversation.

interface QueueEntry {
    /** Runs the approval and settles its caller's promise. Never rejects. */
    run: () => Promise<void>;
    /** Called with how many approvals are ahead of this one, whenever that changes. */
    onPosition: (ahead: number) => void;
}

const waiting: QueueEntry[] = [];
let running = false;

/** Tell everyone still waiting where they are, counting any approval already in flight. */
function notifyPositions(): void {
    waiting.forEach((entry, index) => {
        entry.onPosition(running ? index + 1 : index);
    });
}

async function drain(): Promise<void> {
    if (running) {
        return;
    }

    const entry = waiting.shift();
    if (!entry) {
        return;
    }

    running = true;
    notifyPositions();

    try {
        await entry.run();
    } finally {
        running = false;
        void drain();
    }
}

/**
 * Queue an approval, resolving or rejecting with whatever the approval itself does.
 *
 * `onPosition` fires immediately with this approval's place in the queue and again each time
 * the queue moves, so a card can say "2 images ahead" and count down rather than sitting on
 * an unexplained spinner. It stops being called once the approval starts running.
 */
export function enqueueImageApproval<T>(
    run: () => Promise<T>,
    onPosition: (ahead: number) => void,
): Promise<T> {
    return new Promise<T>((resolve, reject) => {
        waiting.push({
            run: async () => {
                try {
                    resolve(await run());
                } catch (error) {
                    reject(error);
                }
            },
            onPosition,
        });

        notifyPositions();
        void drain();
    });
}

/** How an approval waiting in the queue should describe itself. */
export function describeQueuePosition(ahead: number): string {
    if (ahead <= 0) {
        return 'Queued. Starting soon…';
    }
    return `Queued. ${ahead} image${ahead === 1 ? '' : 's'} ahead.`;
}
