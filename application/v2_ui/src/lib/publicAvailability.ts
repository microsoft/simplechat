// publicAvailability.ts

/** Reader availability only; classic visibility preferences do not apply in V2. */
export function isChattableStatus(status: string): boolean {
    return ['active', 'locked', 'upload_disabled'].includes(status);
}
