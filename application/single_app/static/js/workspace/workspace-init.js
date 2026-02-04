// static/js/workspace/workspace-init.js

// Make sure fetch functions are available globally or imported if using modules consistently
// Assuming fetchUserDocuments and fetchUserPrompts are now globally available via window.* assignments in their respective files

import { initializeTags } from './workspace-tags.js';
import { initializeTagManagement } from './workspace-tag-management.js';

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

});