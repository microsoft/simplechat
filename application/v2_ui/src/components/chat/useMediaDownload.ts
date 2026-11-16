// useMediaDownload.ts
// Download for an image, clip or recording, reporting the outcome as a toast.
//
// The work is in lib/mediaDownload.ts. This adds what the person sees: that the file was saved,
// that it opened in a new tab because its host does not allow a direct download, or that the
// browser blocked that tab, with a button to open it by hand.

import { useCallback, useState } from 'react';
import { downloadMedia, openMediaInNewTab, type MediaKind } from '../../lib/mediaDownload';
import { toast } from '../../stores/toastStore';

const SAVED: Record<MediaKind, string> = {
    image: 'Image saved.',
    video: 'Video saved.',
    audio: 'Recording saved.',
};

export function useMediaDownload() {
    const [busy, setBusy] = useState(false);

    const download = useCallback(async (kind: MediaKind, src: string, title: string) => {
        setBusy(true);
        try {
            const outcome = await downloadMedia(kind, src, title);
            if (outcome === 'saved') {
                toast.success(SAVED[kind]);
            } else if (outcome === 'opened') {
                toast.info('Its host does not allow a direct download, so it opened in a new tab. Save it from there.');
            } else {
                toast.info('The browser blocked the new tab.', {
                    label: 'Open',
                    onAct: () => {
                        openMediaInNewTab(kind, src);
                    },
                });
            }
        } catch (error) {
            toast.error(
                error instanceof Error && error.message ? `Download failed. ${error.message}` : 'Download failed.',
            );
        } finally {
            setBusy(false);
        }
    }, []);

    return { download, busy };
}
