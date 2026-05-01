// static/js/workspace/workspace-init.js

// Make sure fetch functions are available globally or imported if using modules consistently
// Assuming fetchUserDocuments and fetchUserPrompts are now globally available via window.* assignments in their respective files

import { initializeTags, setWorkspaceView } from './workspace-tags.js';
import { initializeTagManagement, showTagManagementModal } from './workspace-tag-management.js';


function clearFeatureActionParam() {
    const url = new URL(window.location.href);
    if (!url.searchParams.has('feature_action')) {
        return;
    }

    url.searchParams.delete('feature_action');
    window.history.replaceState({}, document.title, `${url.pathname}${url.search}${url.hash}`);
}


function handleWorkspaceFeatureAction() {
    const params = new URLSearchParams(window.location.search);
    const featureAction = params.get('feature_action') || '';

    if (!featureAction) {
        return;
    }

    if (featureAction === 'document_tag_system') {
        showTagManagementModal();
    } else if (featureAction === 'workspace_folder_view') {
        setWorkspaceView('grid');
    }

    clearFeatureActionParam();
}

document.addEventListener('DOMContentLoaded', () => {
    console.log("Workspace initializing...");
    
    // Initialize tags functionality
    initializeTags();
    
    // Initialize tag management workflow
    initializeTagManagement();

    // Function to load data for the currently active tab
    function loadActiveTabData() {
        const activeTab = document.querySelector('.nav-tabs .nav-link.active');
        if (!activeTab) return;

        const targetId = activeTab.getAttribute('data-bs-target');

        if (targetId === '#documents-tab') {
            console.log("Loading documents tab data...");
            if (typeof window.fetchUserDocuments === 'function') {
                 window.fetchUserDocuments();
            } else {
                console.error("fetchUserDocuments function not found.");
            }
        } else if (targetId === '#prompts-tab') {
             console.log("Loading prompts tab data...");
             if (typeof window.fetchUserPrompts === 'function') {
                 window.fetchUserPrompts();
             } else {
                  console.error("fetchUserPrompts function not found.");
             }
        } else if (targetId === '#workflows-tab') {
             console.log("Loading workflows tab data...");
             if (typeof window.fetchUserWorkflows === 'function') {
                 window.fetchUserWorkflows();
             } else {
                 console.error("fetchUserWorkflows function not found.");
             }
        }
    }

    // Initial load for the default active tab
    loadActiveTabData();

    // Add event listeners to tab buttons to load data when a tab is shown
    const tabButtons = document.querySelectorAll('#workspaceTab button[data-bs-toggle="tab"]');
    tabButtons.forEach(button => {
        button.addEventListener('shown.bs.tab', event => {
            console.log(`Tab shown: ${event.target.getAttribute('data-bs-target')}`);
            loadActiveTabData(); // Load data for the newly shown tab
        });
    });

    handleWorkspaceFeatureAction();

});