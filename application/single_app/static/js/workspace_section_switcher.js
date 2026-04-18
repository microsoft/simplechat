// workspace_section_switcher.js

(function initializeWorkspaceSectionSwitchers() {
    function getTabButtons(tabListSelector) {
        if (!tabListSelector) {
            return [];
        }

        return Array.from(document.querySelectorAll(`${tabListSelector} button[data-bs-toggle="tab"]`));
    }

    function syncSelectWithActiveTab(selectElement, tabButtons) {
        const activeButton = tabButtons.find((button) => button.classList.contains('active'));
        if (activeButton) {
            selectElement.value = activeButton.id;
        }
    }

    function initializeSwitcher(switcherElement) {
        const selectElement = switcherElement.querySelector('[data-workspace-section-select]');
        const tabButtons = getTabButtons(switcherElement.dataset.tabList);
        if (!selectElement || !tabButtons.length) {
            return;
        }

        selectElement.addEventListener('change', (event) => {
            const targetButton = document.getElementById(event.target.value);
            if (!targetButton) {
                return;
            }

            if (typeof bootstrap !== 'undefined' && bootstrap.Tab) {
                bootstrap.Tab.getOrCreateInstance(targetButton).show();
            } else {
                targetButton.click();
            }
        });

        tabButtons.forEach((button) => {
            button.addEventListener('shown.bs.tab', () => {
                syncSelectWithActiveTab(selectElement, tabButtons);
            });
        });

        syncSelectWithActiveTab(selectElement, tabButtons);
    }

    function bindSwitchers() {
        document.querySelectorAll('[data-workspace-switcher]').forEach((switcherElement) => {
            initializeSwitcher(switcherElement);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindSwitchers);
    } else {
        bindSwitchers();
    }
})();