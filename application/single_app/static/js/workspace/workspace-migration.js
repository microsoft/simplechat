// workspace-migration.js
// Handles migration of agents and actions from legacy user_settings to personal containers

import { showToast } from "../chat/chat-toast.js";

// DOM Elements
const migrationBanner = document.getElementById('migration-banner');
const migrateAllBtn = document.getElementById('migrate-all-btn');
const migrationProgress = document.getElementById('migration-progress');
const migrationStatusText = document.getElementById('migration-status-text');
const progressBar = migrationProgress?.querySelector('.progress-bar');

/**
 * Check if migration is needed and show banner if so
 */
export async function checkMigrationStatus() {
    try {
        const response = await fetch('/api/migrate/status');
        if (!response.ok) {
            console.error('Failed to check migration status');
            return;
        }
        
        const data = await response.json();
        console.log('Migration status:', data);
        
        if (data.migration_needed) {
            const { legacy_data } = data;
            const hasAgents = legacy_data.agents_count > 0;
            const hasActions = legacy_data.actions_count > 0;
            
            // Update banner text based on what needs migration
            let itemText = '';
            if (hasAgents && hasActions) {
                itemText = `${legacy_data.agents_count} agents and ${legacy_data.actions_count} actions`;
            } else if (hasAgents) {
                itemText = `${legacy_data.agents_count} agent${legacy_data.agents_count > 1 ? 's' : ''}`;
            } else if (hasActions) {
                itemText = `${legacy_data.actions_count} action${legacy_data.actions_count > 1 ? 's' : ''}`;
            }
            
            const bannerText = migrationBanner.querySelector('small');
            if (bannerText) {
                bannerText.textContent = `We've found ${itemText} in your old settings. Click to migrate them to the new improved storage system for better performance and reliability.`;
            }
            
            showMigrationBanner();
        }
    } catch (error) {
        console.error('Error checking migration status:', error);
    }
}

/**
 * Show the migration banner
 */
function showMigrationBanner() {
    if (migrationBanner) {
        migrationBanner.style.display = 'block';
    }
}

/**
 * Hide the migration banner
 */
function hideMigrationBanner() {
    if (migrationBanner) {
        migrationBanner.style.display = 'none';
    }
}

/**
 * Show migration progress
 */
function showMigrationProgress() {
    if (migrationProgress) {
        migrationProgress.style.display = 'block';
    }
    if (migrateAllBtn) {
        migrateAllBtn.disabled = true;
        migrateAllBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Migrating...';
    }
}

/**
 * Hide migration progress
 */
function hideMigrationProgress() {
    if (migrationProgress) {
        migrationProgress.style.display = 'none';
    }
    if (progressBar) {
        progressBar.style.width = '0%';
    }
    if (migrateAllBtn) {
        migrateAllBtn.disabled = false;
        migrateAllBtn.innerHTML = '<i class="bi bi-arrow-up"></i> Migrate Now';
    }
}

/**
 * Update migration progress
 */
function updateMigrationProgress(percentage, statusText) {
    if (progressBar) {
        progressBar.style.width = `${percentage}%`;
    }
    if (migrationStatusText) {
        migrationStatusText.textContent = statusText;
    }
}

/**
 * Perform the migration
 */
async function performMigration() {
    try {
        showMigrationProgress();
        updateMigrationProgress(10, 'Starting migration...');
        
        const response = await fetch('/api/migrate/all', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        updateMigrationProgress(50, 'Processing data...');
        
        if (!response.ok) {
            throw new Error('Migration failed');
        }
        
        const result = await response.json();
        updateMigrationProgress(90, 'Finalizing...');
        
        // Small delay to show completion
        setTimeout(() => {
            updateMigrationProgress(100, 'Migration completed successfully!');
            
            // Hide progress and banner after a brief success display
            setTimeout(() => {
                hideMigrationProgress();
                hideMigrationBanner();
                
                // Show success toast
                showToast('Migration completed successfully! Your agents and actions are now using the improved storage system.', 'success');
                
                // Refresh the current tab's data
                refreshCurrentTabData();
            }, 1500);
        }, 500);
        
    } catch (error) {
        console.error('Migration error:', error);
        hideMigrationProgress();
        
        // Show error toast
        showToast('Migration failed. Please try again or contact support if the issue persists.', 'error');
    }
}

/**
 * Refresh data for the currently active tab
 */
function refreshCurrentTabData() {
    const activeTab = document.querySelector('.nav-link.active');
    if (!activeTab) return;
    
    const tabId = activeTab.getAttribute('data-bs-target');
    
    if (tabId === '#agents-tab') {
        // Refresh agents data if the function exists
        if (window.fetchAgents && typeof window.fetchAgents === 'function') {
            window.fetchAgents();
        }
    } else if (tabId === '#plugins-tab') {
        // Refresh plugins data if the function exists
        if (window.fetchPlugins && typeof window.fetchPlugins === 'function') {
            window.fetchPlugins();
        }
    }
}

/**
 * Initialize migration functionality
 */
export function initializeMigration() {
    // Add event listener for migrate button
    if (migrateAllBtn) {
        migrateAllBtn.addEventListener('click', performMigration);
    }
    
    // Check migration status on page load
    checkMigrationStatus();
}

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    initializeMigration();
});
