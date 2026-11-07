// UserAvatar.tsx
// The signed-in user's picture, shown in the rail's account control and on their settings
// page.
//
// The picture is the Microsoft Graph profile photo. The server fetches it once and caches it
// on the user's settings document as a data URI (`get_user_profile_image()` in
// functions_authentication.py), which the classic rail has always rendered. V2 already loads
// that document at startup for its preferences, so nothing new is requested here; the photo
// was simply never read.
//
// It is deliberately not taken from /api/v2/bootstrap. That payload is refetched whenever an
// administrator changes a setting, and a base64 photograph would be resent every time to say
// something that has not changed.

import { useState } from 'react';
import { clsx } from 'clsx';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';

/**
 * Up to two initials for the fallback.
 *
 * Splits on whitespace, `@` and `.` so an account identified only by email still produces
 * something recognisable rather than the first two letters of one long token.
 */
export function initialsFor(name: string | undefined, email: string | undefined): string {
    return (
        (name || email || '?')
            .split(/[\s@.]+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((part) => part[0]?.toUpperCase())
            .join('') || '?'
    );
}

export function UserAvatar({
    size = 32,
    className,
}: {
    /** Rendered width and height in pixels. */
    size?: number;
    className?: string;
}) {
    const user = useBootstrapStore((state) => state.data?.user);
    const profileImage = useUserSettingsStore((state) => state.settings.profileImage);
    /**
     * Set when the stored picture fails to decode.
     *
     * The data URI is cached indefinitely and never re-validated, so a truncated or
     * unsupported one would otherwise leave a permanently empty circle with no way to tell
     * that a picture was even meant to be there.
     */
    const [imageFailed, setImageFailed] = useState(false);

    const src = typeof profileImage === 'string' ? profileImage.trim() : '';
    const showImage = Boolean(src) && !imageFailed;

    return (
        <span
            className={clsx(
                'flex shrink-0 items-center justify-center overflow-hidden rounded-full',
                !showImage && 'bg-accent-soft font-semibold text-accent',
                className,
            )}
            style={{
                width: size,
                height: size,
                // Keeps two initials inside the circle at every size the app uses.
                fontSize: showImage ? undefined : Math.max(10, Math.round(size * 0.38)),
            }}
        >
            {showImage ? (
                <img
                    src={src}
                    alt=""
                    onError={() => setImageFailed(true)}
                    className="h-full w-full object-cover"
                />
            ) : (
                initialsFor(user?.display_name, user?.email)
            )}
        </span>
    );
}
