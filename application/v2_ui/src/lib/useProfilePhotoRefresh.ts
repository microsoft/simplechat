// useProfilePhotoRefresh.ts
// The state behind the Settings page's "Refresh photo" control: whether a refresh is running,
// what it said, and the one place the new photo enters the application.
//
// The photo goes straight into the user settings store, which is what the rail avatar and the
// Settings header both read, so both change the moment the server answers. A failed refresh
// changes nothing: the server leaves the stored photo alone when it fails, so the photo on
// screen stays the one that is still true.

import { useCallback, useRef, useState } from 'react';
import {
    PROFILE_PHOTO_NONE_MESSAGE,
    PROFILE_PHOTO_UPDATED_MESSAGE,
    describeProfileImageFailure,
    requestProfileImageRefresh,
} from './profileImage';
import { useUserSettingsStore } from '../stores/userSettingsStore';

export interface ProfilePhotoMessage {
    tone: 'success' | 'info' | 'error';
    text: string;
}

export interface ProfilePhotoRefresh {
    busy: boolean;
    message: ProfilePhotoMessage | null;
    refresh: () => void;
}

export function useProfilePhotoRefresh(): ProfilePhotoRefresh {
    const setProfileImage = useUserSettingsStore((state) => state.setProfileImage);
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState<ProfilePhotoMessage | null>(null);
    // A second activation while the first is running must not send a second request, and the
    // state value is a render behind the click that set it.
    const running = useRef(false);

    const refresh = useCallback(() => {
        if (running.current) {
            return;
        }
        running.current = true;
        setBusy(true);
        setMessage(null);
        requestProfileImageRefresh()
            .then((result) => {
                if (result.status === 'updated') {
                    setProfileImage(result.profileImage);
                    setMessage({ tone: 'success', text: PROFILE_PHOTO_UPDATED_MESSAGE });
                } else {
                    // The server removed the photo it had, so the initials are the truth.
                    setProfileImage(null);
                    setMessage({ tone: 'info', text: PROFILE_PHOTO_NONE_MESSAGE });
                }
            })
            .catch((error: unknown) => {
                setMessage({ tone: 'error', text: describeProfileImageFailure(error) });
            })
            .finally(() => {
                running.current = false;
                setBusy(false);
            });
    }, [setProfileImage]);

    return { busy, message, refresh };
}
