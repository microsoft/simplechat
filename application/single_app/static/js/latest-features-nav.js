// latest-features-nav.js

(function () {
    const config = window.simplechatLatestFeaturesNav || {};
    const settingKey = config.settingKey || 'latestFeaturesHiddenVersion';

    function getCurrentVersion() {
        return String(config.currentVersion || '').trim();
    }

    function isHiddenByDevelopment() {
        return Boolean(config.hiddenByDevelopment);
    }

    function getUserSettingsCache() {
        if (!window.simplechatUserSettings || typeof window.simplechatUserSettings !== 'object') {
            window.simplechatUserSettings = {};
        }

        return window.simplechatUserSettings;
    }

    function getHiddenVersion() {
        const settings = getUserSettingsCache();
        return String(settings[settingKey] || '').trim();
    }

    function setHiddenVersionCache(hiddenVersion) {
        const settings = getUserSettingsCache();
        settings[settingKey] = hiddenVersion || null;
    }

    function showLatestFeaturesToast(message, type = 'success') {
        if (typeof window.showToastMessage === 'function') {
            window.showToastMessage(message, type);
            return;
        }

        if (typeof bootstrap === 'undefined' || !bootstrap.Toast) {
            return;
        }

        let toastContainer = document.getElementById('latest-features-toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'latest-features-toast-container';
            toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            toastContainer.setAttribute('aria-live', 'polite');
            toastContainer.setAttribute('aria-atomic', 'true');
            document.body.appendChild(toastContainer);
        }

        const toast = document.createElement('div');
        const bgClass = type === 'danger' ? 'bg-danger' : type === 'info' ? 'bg-info' : 'bg-success';
        toast.className = `toast align-items-center text-white ${bgClass} border-0`;
        toast.setAttribute('role', 'alert');

        const toastBodyRow = document.createElement('div');
        toastBodyRow.className = 'd-flex';

        const toastBody = document.createElement('div');
        toastBody.className = 'toast-body';
        toastBody.textContent = message;

        const closeButton = document.createElement('button');
        closeButton.type = 'button';
        closeButton.className = 'btn-close btn-close-white me-2 m-auto';
        closeButton.setAttribute('data-bs-dismiss', 'toast');
        closeButton.setAttribute('aria-label', 'Close');

        toastBodyRow.appendChild(toastBody);
        toastBodyRow.appendChild(closeButton);
        toast.appendChild(toastBodyRow);
        toastContainer.appendChild(toast);

        const toastInstance = new bootstrap.Toast(toast);
        toast.addEventListener('hidden.bs.toast', function () {
            toast.remove();
        });
        toastInstance.show();
    }

    async function saveHiddenVersion(hiddenVersion) {
        const response = await fetch('/api/user/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                settings: {
                    [settingKey]: hiddenVersion || null
                }
            })
        });

        if (!response.ok) {
            throw new Error('Unable to save Latest Features navigation preference.');
        }

        setHiddenVersionCache(hiddenVersion);
    }

    function hasVisibleSupportDestination(section) {
        const destinations = section.querySelectorAll('[data-support-menu-destination]');
        for (const destination of destinations) {
            if (!destination.classList.contains('d-none')) {
                return true;
            }
        }

        return false;
    }

    function updateSupportSections() {
        document.querySelectorAll('[data-support-menu-nav-section]').forEach(function (section) {
            section.classList.toggle('d-none', !hasVisibleSupportDestination(section));
        });
    }

    function hideLatestFeaturesNavItems() {
        document.querySelectorAll('[data-latest-features-nav-item]').forEach(function (item) {
            item.classList.add('d-none');
        });
        updateSupportSections();
    }

    function showLatestFeaturesNavItems() {
        if (isHiddenByDevelopment()) {
            return;
        }

        document.querySelectorAll('[data-latest-features-nav-item]').forEach(function (item) {
            item.classList.remove('d-none');
        });
        document.querySelectorAll('[data-support-menu-nav-section]').forEach(function (section) {
            section.classList.remove('d-none');
        });
    }

    function setProfileStatusMessage(message, type = 'muted') {
        const status = document.getElementById('latest-features-nav-preference-status');
        if (!status) {
            return;
        }

        const classMap = {
            muted: 'text-muted',
            info: 'text-info',
            success: 'text-success',
            danger: 'text-danger'
        };
        status.textContent = message || '';
        status.className = `preference-status small mt-3 ${classMap[type] || classMap.muted}`;
    }

    function renderProfileLatestFeaturesStatus() {
        const badge = document.getElementById('latest-features-nav-status-badge');
        const detail = document.getElementById('latest-features-nav-status-detail');
        const unhideButton = document.getElementById('unhide-latest-features-nav-btn');
        if (!badge || !detail) {
            return;
        }

        const currentVersion = getCurrentVersion();
        const hiddenVersion = getHiddenVersion();
        const hiddenForCurrentVersion = Boolean(currentVersion && hiddenVersion === currentVersion);

        badge.className = 'badge';
        if (isHiddenByDevelopment()) {
            badge.classList.add('bg-warning', 'text-dark');
            badge.textContent = 'Hidden in development';
            detail.textContent = 'Latest Features navigation is hidden because the is_development environment flag is true.';
        } else if (hiddenForCurrentVersion) {
            badge.classList.add('bg-secondary');
            badge.textContent = 'Hidden';
            detail.textContent = `Latest Features navigation is hidden for version ${currentVersion}.`;
        } else {
            badge.classList.add('bg-success');
            badge.textContent = 'Visible';
            detail.textContent = hiddenVersion
                ? `Latest Features navigation is visible because your saved hide preference was for version ${hiddenVersion}, and the current version is ${currentVersion}.`
                : `Latest Features navigation is visible for version ${currentVersion}.`;
        }

        if (unhideButton) {
            unhideButton.classList.toggle('d-none', !hiddenForCurrentVersion);
            unhideButton.disabled = false;
        }
    }

    async function handleHideLatestFeatures(event) {
        event.preventDefault();
        event.stopPropagation();

        const currentVersion = getCurrentVersion();
        if (!currentVersion) {
            showLatestFeaturesToast('Unable to hide Latest Features because the app version is unavailable.', 'danger');
            return;
        }

        const actionButton = event.currentTarget;
        actionButton.disabled = true;
        try {
            await saveHiddenVersion(currentVersion);
            hideLatestFeaturesNavItems();
            renderProfileLatestFeaturesStatus();
            showLatestFeaturesToast('Latest Features navigation is hidden for this version.', 'success');
        } catch (error) {
            console.error('Error hiding Latest Features navigation:', error);
            showLatestFeaturesToast('Failed to hide Latest Features navigation. Please try again.', 'danger');
        } finally {
            actionButton.disabled = false;
        }
    }

    async function handleUnhideLatestFeatures() {
        const unhideButton = document.getElementById('unhide-latest-features-nav-btn');
        if (!unhideButton) {
            return;
        }

        const originalText = unhideButton.textContent;
        unhideButton.disabled = true;
        unhideButton.textContent = 'Saving...';
        setProfileStatusMessage('Restoring Latest Features navigation...', 'info');

        try {
            await saveHiddenVersion(null);
            showLatestFeaturesNavItems();
            renderProfileLatestFeaturesStatus();
            setProfileStatusMessage('Latest Features navigation has been restored.', 'success');
            showLatestFeaturesToast('Latest Features navigation restored.', 'success');
        } catch (error) {
            console.error('Error restoring Latest Features navigation:', error);
            setProfileStatusMessage('Failed to restore Latest Features navigation. Please try again.', 'danger');
            showLatestFeaturesToast('Failed to restore Latest Features navigation. Please try again.', 'danger');
        } finally {
            unhideButton.disabled = false;
            unhideButton.textContent = originalText;
        }
    }

    function initializeLatestFeaturesNavPreferences() {
        document.querySelectorAll('[data-latest-features-hide-action]').forEach(function (button) {
            button.addEventListener('click', handleHideLatestFeatures);
        });

        const unhideButton = document.getElementById('unhide-latest-features-nav-btn');
        if (unhideButton) {
            unhideButton.addEventListener('click', handleUnhideLatestFeatures);
        }

        renderProfileLatestFeaturesStatus();
    }

    document.addEventListener('DOMContentLoaded', initializeLatestFeaturesNavPreferences);

    window.SimpleChatLatestFeaturesNav = {
        hideLatestFeaturesNavItems,
        renderProfileLatestFeaturesStatus,
        saveHiddenVersion,
        showLatestFeaturesNavItems
    };
})();
