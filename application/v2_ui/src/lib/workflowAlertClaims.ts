// workflowAlertClaims.ts
// Which tab shows a workflow alert.
//
// Classic remembers the alerts it has shown in sessionStorage, which is per tab, so every
// open tab pops the same alert. V2 claims each alert in localStorage before showing it, and
// a claimed alert is shown nowhere else: other tabs only see the bell count change.
//
// A claim means "shown somewhere", not "being shown here now". An alert that was closed, or
// whose tab was closed, stays unread in the bell and does not pop up again.
//
// Two tabs can learn about the same alert in the same instant, so taking a claim is a
// read-then-write that must not interleave. The Web Locks API makes it exclusive across
// every tab of the origin. Where that is missing, the claim is written and read back a
// moment later, and the tab whose claim survived shows the alert. If storage cannot be used
// at all -- a locked-down profile -- claims are kept for this tab only, which is classic's
// behaviour.

const STORAGE_KEY = 'simplechat.v2.workflowAlertClaims';
const LOCK_NAME = 'simplechat.v2.workflowAlertClaims';
/** Longer than the 24-hour pop-up window, so a claim outlives any alert it could stop. */
const CLAIM_TTL_MS = 25 * 3_600_000;
const MAX_CLAIMS = 500;
const VERIFY_DELAY_MS = 50;

interface Claim {
    tab: string;
    at: number;
}

type Claims = Record<string, Claim>;

function newTabId(): string {
    try {
        if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
            return crypto.randomUUID();
        }
    } catch {
        /* Falls through to the timestamp id. */
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

const tabId = newTabId();
const memoryClaims: Claims = {};
let storageUsable = true;

function isClaim(value: unknown): value is Claim {
    return typeof value === 'object' && value !== null
        && typeof (value as Claim).tab === 'string'
        && typeof (value as Claim).at === 'number' && Number.isFinite((value as Claim).at);
}

function prune(claims: Claims, now: number): Claims {
    const kept = Object.entries(claims)
        .filter(([, claim]) => now - claim.at < CLAIM_TTL_MS)
        .sort(([, left], [, right]) => right.at - left.at)
        .slice(0, MAX_CLAIMS);
    return Object.fromEntries(kept);
}

function readStored(now: number): Claims | null {
    if (!storageUsable) {
        return null;
    }
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        const parsed: unknown = raw ? JSON.parse(raw) : {};
        const claims: Claims = {};
        if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
            for (const [id, claim] of Object.entries(parsed as Record<string, unknown>)) {
                if (isClaim(claim)) {
                    claims[id] = claim;
                }
            }
        }
        return prune(claims, now);
    } catch (error) {
        if (error instanceof SyntaxError) {
            // A damaged value is replaced rather than trusted or left to fail every read.
            return {};
        }
        storageUsable = false;
        return null;
    }
}

function writeStored(claims: Claims): boolean {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(claims));
        return true;
    } catch {
        storageUsable = false;
        return false;
    }
}

/** Claim what nobody has claimed; returns the ids this call claimed. */
function claimNow(ids: string[]): string[] {
    const now = Date.now();
    const stored = readStored(now);
    const claims = stored ?? memoryClaims;
    const won = ids.filter((id) => !claims[id]);
    if (!won.length) {
        return [];
    }
    for (const id of won) {
        claims[id] = { tab: tabId, at: now };
    }
    if (stored && !writeStored(prune(claims, now))) {
        // Storage failed part-way: remember the claims here so this tab still shows each
        // alert once, and later calls use memory.
        for (const id of won) {
            memoryClaims[id] = { tab: tabId, at: now };
        }
    }
    return won;
}

function wait(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Claim alerts for this tab. Resolves to the ids this tab may show, in the order given;
 * an id another tab already claimed is left out.
 */
export async function claimWorkflowAlerts(ids: string[]): Promise<string[]> {
    const unique = [...new Set(ids.filter(Boolean))];
    if (!unique.length) {
        return [];
    }
    const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
    if (storageUsable && locks && typeof locks.request === 'function') {
        try {
            return await locks.request(LOCK_NAME, { mode: 'exclusive' }, () => claimNow(unique));
        } catch {
            /* A lock request can be refused in an unusual frame; the check below still holds. */
        }
    }
    const won = claimNow(unique);
    if (!won.length || !storageUsable) {
        return won;
    }
    await wait(VERIFY_DELAY_MS);
    const stored = readStored(Date.now());
    if (!stored) {
        return won;
    }
    return won.filter((id) => stored[id]?.tab === tabId);
}

/** Forget every claim. Only the alert lab and tests call this. */
export function resetWorkflowAlertClaims(): void {
    for (const id of Object.keys(memoryClaims)) {
        delete memoryClaims[id];
    }
    try {
        localStorage.removeItem(STORAGE_KEY);
    } catch {
        /* Nothing stored to clear. */
    }
}

/** This tab's claim id, for tests that need to tell two tabs apart. */
export function workflowAlertClaimTabId(): string {
    return tabId;
}
