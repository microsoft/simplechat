// planSubmissionIds.ts
// Which submission id a plan editor request goes out under.
//
// The server holds each submission id to the request it first arrived with: the plan version, the
// step edits, the action and its instruction, and the canonical form of any `#` references (see
// planReferences.ts). The same id with any other request is refused for good as a
// `submission_conflict`. So an id is sent again only with exactly the same request, which is also
// the only time that helps, because a request the server already finished is then replayed rather
// than run twice. Anything else needs a fresh id.
//
// That matters for the assist thread's Retry, which offers the id its exchange was last sent under.
// By the time the reader retries, cancelling may have moved the plan to a new version, or they may
// have toggled a step. Reusing the id then would be refused however many times they retried.

/** The request the plan editor holds an id for, until the server answers it. */
export interface HeldPlanSubmission {
    id: string;
    fingerprint: string;
}

/** Ids remembered per page, oldest forgotten first. The server keeps fewer per plan. */
export const MAX_SENT_PLAN_SUBMISSIONS = 200;

const sent = new Map<string, string>();

/** Remember the request an id was sent with. */
export function rememberPlanSubmission(id: string, fingerprint: string): void {
    sent.delete(id);
    sent.set(id, fingerprint);
    while (sent.size > MAX_SENT_PLAN_SUBMISSIONS) {
        const oldest = sent.keys().next().value;
        if (oldest === undefined) {
            break;
        }
        sent.delete(oldest);
    }
}

/** The request an id was sent with from this page, if it was. */
export function sentPlanSubmission(id: string): string | undefined {
    return sent.get(id);
}

/** Forget every id, for tests. */
export function resetPlanSubmissions(): void {
    sent.clear();
}

/**
 * Choose the id a plan request is sent under.
 *
 * The request the editor holds keeps its id when this is that request again. Otherwise the
 * requested id is used when this page never sent it, or sent it with this same request. Anything
 * else gets a fresh id from `mint`.
 */
export function choosePlanSubmissionId(
    fingerprint: string,
    held: HeldPlanSubmission | null | undefined,
    requested: string | undefined,
    mint: () => string,
): string {
    if (held && held.fingerprint === fingerprint) {
        return held.id;
    }
    if (requested) {
        const previous = sent.get(requested);
        if (previous === undefined || previous === fingerprint) {
            return requested;
        }
    }
    return mint();
}
