// chat-ai-notice.js

import { saveUserSetting } from './chat-layout.js';
import { showToast } from './chat-toast.js';


const aiNotice = document.getElementById('ai-notice');
const aiNoticeDismiss = document.getElementById('ai-notice-dismiss');
const aiNoticeUserSettingKey = 'aiNoticeDismissal';
const aiNoticeSessionStorageKey = 'simplechat.aiNoticeDismissal';


function getSessionDismissalKey(noticeHash) {
    return `${aiNoticeSessionStorageKey}.${noticeHash}`;
}


function isSessionNoticeDismissed(noticeHash) {
    try {
        return sessionStorage.getItem(getSessionDismissalKey(noticeHash)) === 'true';
    } catch (error) {
        if (!(error instanceof DOMException)) {
            throw error;
        }
        console.warn('Session storage is unavailable; the AI notice will remain visible.', error);
        return false;
    }
}


function showAiNotice() {
    aiNotice?.classList.remove('d-none');
}


function hideAiNotice() {
    aiNotice?.classList.add('d-none');
}


async function dismissAiNotice() {
    if (!aiNotice || !aiNoticeDismiss) {
        return;
    }

    const noticeFrequency = aiNotice.dataset.noticeFrequency || '';
    const noticeHash = aiNotice.dataset.noticeHash || '';
    if (noticeFrequency === 'every_session') {
        try {
            sessionStorage.setItem(getSessionDismissalKey(noticeHash), 'true');
        } catch (error) {
            if (!(error instanceof DOMException)) {
                throw error;
            }
            showToast('This browser cannot save the session dismissal.', 'warning');
            return;
        }
        hideAiNotice();
        return;
    }

    aiNoticeDismiss.disabled = true;
    const saved = await saveUserSetting({
        [aiNoticeUserSettingKey]: {
            hash: noticeHash,
            frequency: noticeFrequency
        }
    });
    if (saved) {
        hideAiNotice();
        return;
    }

    aiNoticeDismiss.disabled = false;
    showToast('The AI notice could not be dismissed. Please try again.', 'warning');
}


if (aiNotice) {
    const noticeFrequency = aiNotice.dataset.noticeFrequency || '';
    const noticeHash = aiNotice.dataset.noticeHash || '';
    const dismissedForSession = noticeFrequency === 'every_session'
        && isSessionNoticeDismissed(noticeHash);

    if (!dismissedForSession) {
        showAiNotice();
    }
    aiNoticeDismiss?.addEventListener('click', dismissAiNotice);
}
