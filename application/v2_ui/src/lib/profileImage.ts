// profileImage.ts
// Asking the server to fetch the signed-in user's Microsoft 365 photo again.
//
// The photo is cached on the user's settings document the first time they are seen, and
// nothing refreshes it afterwards, so someone who changes their Microsoft 365 photo keeps the
// old one here. The classic profile page has a "Refresh Profile Image" button for this; the
// route behind it, POST /api/profile/image/refresh, reads the photo from Microsoft Graph,
// stores it and answers with it as a data URI, or with `null` when Graph returned no photo
// (in which case the server also removes the one it had).
//
// The answer carries the photograph itself, so nothing here ever logs it, copies it into an
// error or shows it as text: a failure is reported with a fixed sentence chosen by what went
// wrong, never with anything the server sent back.

import { api, isAppSessionError } from './apiClient';

/** The route in route_frontend_profile.py (`refresh_profile_image`). */
export const PROFILE_IMAGE_REFRESH_ENDPOINT = '/api/profile/image/refresh';

export const PROFILE_PHOTO_UPDATED_MESSAGE = 'Your photo was updated from Microsoft 365.';
export const PROFILE_PHOTO_NONE_MESSAGE = 'Microsoft 365 did not return a photo, so your initials are shown.';
export const PROFILE_PHOTO_SESSION_MESSAGE = 'Sign in again to refresh your photo.';
export const PROFILE_PHOTO_OFFLINE_MESSAGE =
    "We couldn't reach SimpleChat. Check your connection and try again.";
export const PROFILE_PHOTO_FAILED_MESSAGE = "We couldn't refresh your photo. Try again in a moment.";

export type ProfileImageRefreshResult =
    | { status: 'updated'; profileImage: string }
    | { status: 'none' };

/** The server answered 200 with something that is neither a photo nor "no photo". */
export class ProfileImageResponseError extends Error {
    constructor() {
        super('The profile photo response was not understood.');
        this.name = 'ProfileImageResponseError';
    }
}

/**
 * Read the refresh route's answer.
 *
 * `{ success: true, profileImage: "data:..." }` is a new photo and `profileImage: null` is no
 * photo. Anything else is refused without being quoted: it could hold the photograph.
 */
export function readProfileImageRefresh(payload: unknown): ProfileImageRefreshResult {
    if (!payload || typeof payload !== 'object' || (payload as { success?: unknown }).success !== true) {
        throw new ProfileImageResponseError();
    }
    const image = (payload as { profileImage?: unknown }).profileImage;
    if (image === null) {
        return { status: 'none' };
    }
    if (typeof image === 'string' && image.trim()) {
        return { status: 'updated', profileImage: image.trim() };
    }
    throw new ProfileImageResponseError();
}

export async function requestProfileImageRefresh(signal?: AbortSignal): Promise<ProfileImageRefreshResult> {
    return readProfileImageRefresh(await api.post<unknown>(PROFILE_IMAGE_REFRESH_ENDPOINT, {}, signal));
}

/** The sentence for a failed refresh, chosen by what failed and never by what the server said. */
export function describeProfileImageFailure(error: unknown): string {
    if (isAppSessionError(error)) {
        return PROFILE_PHOTO_SESSION_MESSAGE;
    }
    if (error instanceof TypeError) {
        return PROFILE_PHOTO_OFFLINE_MESSAGE;
    }
    return PROFILE_PHOTO_FAILED_MESSAGE;
}
