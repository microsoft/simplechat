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
        if (data.migration_needed) {
            const legacyData = data.legacy_data;
            const actionCount = legacyData.actions_pending_count + legacyData.actions_failed_count;
            const hasAgents = legacyData.agents_count > 0;
            const hasActions = actionCount > 0;
            
            // Update banner text based on what needs migration
            let itemText = '';
            if (hasAgents && hasActions) {
                itemText = `${legacyData.agents_count} agents and ${actionCount} actions`;
            } else if (hasAgents) {
                itemText = `${legacyData.agents_count} agent${legacyData.agents_count > 1 ? 's' : ''}`;
            } else if (hasActions) {
                itemText = `${actionCount} action${actionCount > 1 ? 's' : ''}`;
            }
            
            const bannerText = migrationBanner?.querySelector('small');
            if (bannerText) {
                let message = `We've found ${itemText} ready to migrate or retry. Their original settings are kept until migration is verified.`;
                if (legacyData.actions_retained_count > 0) {
                    message += ` ${legacyData.actions_retained_count} other legacy actions need manual reconfiguration or deletion in Actions.`;
                }
                bannerText.textContent = message;
            }
            
            showMigrationBanner();
        } else {
            // Retired records stay visible in Actions, not in a recurring migration prompt.
            hideMigrationBanner();
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
        migrationBanner.style.removeProperty('display');
        migrationBanner.classList.remove('d-none');
    }
}

/**
 * Hide the migration banner
 */
function hideMigrationBanner() {
    if (migrationBanner) {
        migrationBanner.style.removeProperty('display');
        migrationBanner.classList.add('d-none');
    }
}

/**
 * Show migration progress
 */
function showMigrationProgress() {
    if (migrationProgress) {
        migrationProgress.style.removeProperty('display');
        migrationProgress.classList.remove('d-none');
    }
    if (migrateAllBtn) {
        migrateAllBtn.disabled = true;
        const spinner = document.createElement('span');
        spinner.className = 'spinner-border spinner-border-sm me-2';
        spinner.setAttribute('role', 'status');
        spinner.setAttribute('aria-hidden', 'true');
        migrateAllBtn.replaceChildren(spinner, document.createTextNode('Migrating...'));
    }
}

/**
 * Hide migration progress
 */
function hideMigrationProgress() {
    if (migrationProgress) {
        migrationProgress.style.removeProperty('display');
        migrationProgress.classList.add('d-none');
    }
    if (progressBar) {
        progressBar.style.width = '0%';
    }
    if (migrateAllBtn) {
        migrateAllBtn.disabled = false;
        const icon = document.createElement('i');
        icon.className = 'bi bi-arrow-up';
        icon.setAttribute('aria-hidden', 'true');
        migrateAllBtn.replaceChildren(icon, document.createTextNode(' Migrate Now'));
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
        
        const actionOutcome = result.action_migration;
        hideMigrationProgress();
        if (actionOutcome.failed_count > 0 || !actionOutcome.complete) {
            showToast('Migration is incomplete. Unfinished actions remain in your settings; retry migration to finish them.', 'warning');
        } else if (actionOutcome.retained_count > 0) {
            showToast(`${actionOutcome.migrated_count} actions migrated. ${actionOutcome.retained_count} legacy actions were kept for manual reconfiguration or deletion in Actions. Stdio actions cannot run.`, 'warning');
        } else {
            showToast('Migration completed successfully. Your agents and actions now use the improved storage system.', 'success');
        }
        refreshCurrentTabData();
        await checkMigrationStatus();
        
    } catch (error) {
        console.error('Migration error:', error);
        hideMigrationProgress();
        
        // Show error toast
        showToast('Migration could not finish. Original actions are kept until their migration is verified. Please retry.', 'error');
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
