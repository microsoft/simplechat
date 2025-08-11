// profile-image.js
// Global profile image functionality

let userProfileImage = null;
let userInitials = '';
let isLoading = false;

// Try to load cached image immediately (before DOM loads)
(function() {
    const cachedImage = sessionStorage.getItem('userProfileImage');
    if (cachedImage && cachedImage !== 'null' && cachedImage !== 'undefined') {
        userProfileImage = cachedImage;
        
        // Immediate DOM check and update
        function immediateUpdate() {
            const topNav = document.getElementById('top-nav-profile-avatar');
            const sidebar = document.getElementById('sidebar-profile-avatar');
            
            if (topNav && userProfileImage) {
                const img = document.createElement('img');
                img.src = userProfileImage;
                img.alt = 'Profile';
                img.style.cssText = 'width: 28px; height: 28px; border-radius: 50%; object-fit: cover;';
                topNav.innerHTML = '';
                topNav.appendChild(img);
            }
            
            if (sidebar && userProfileImage) {
                const img = document.createElement('img');
                img.src = userProfileImage;
                img.alt = 'Profile';
                img.style.cssText = 'width: 32px; height: 32px; border-radius: 50%; object-fit: cover;';
                sidebar.innerHTML = '';
                sidebar.appendChild(img);
            }
        }
        
        // Try immediately, then use observer for when elements appear
        immediateUpdate();
        
        // Set up mutation observer to catch avatar elements as they load
        const observer = new MutationObserver(function(mutations) {
            let shouldUpdate = false;
            mutations.forEach(function(mutation) {
                if (mutation.type === 'childList') {
                    // Check if any avatar elements were added
                    mutation.addedNodes.forEach(function(node) {
                        if (node.nodeType === 1) { // Element node
                            if (node.id && (node.id.includes('profile-avatar') || node.id.includes('nav-profile'))) {
                                shouldUpdate = true;
                            }
                            // Check children too
                            const avatars = node.querySelectorAll && node.querySelectorAll('[id*="profile-avatar"], [id*="nav-profile"]');
                            if (avatars && avatars.length > 0) {
                                shouldUpdate = true;
                            }
                        }
                    });
                }
            });
            if (shouldUpdate) {
                immediateUpdate();
            }
        });
        
        observer.observe(document.documentElement, {
            childList: true,
            subtree: true
        });
        
        // Stop observing after a reasonable time
        setTimeout(() => observer.disconnect(), 5000);
    }
})();

// Initialize profile image functionality as early as possible
document.addEventListener('DOMContentLoaded', function() {
    // Immediate update with cached data, then fetch from server
    updateAllProfileAvatars();
    loadUserProfileImageFromServer();
});

// Also try when window loads (backup)
window.addEventListener('load', function() {
    // Quick update to catch any missed elements
    updateAllProfileAvatars();
});

/**
 * Load user profile image from server (background update)
 */
function loadUserProfileImageFromServer() {
    if (isLoading) return; // Prevent multiple simultaneous requests
    isLoading = true;
    
    fetch('/api/user/settings')
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to fetch user settings');
            }
            return response.json();
        })
        .then(data => {
            const serverProfileImage = data.settings?.profileImage;
            
            // Only update if different from current version
            if (serverProfileImage !== userProfileImage) {
                userProfileImage = serverProfileImage;
                console.log('Profile image updated from server:', userProfileImage ? 'Image found' : 'No image found');
                updateAllProfileAvatars();
                
                // Update cache
                if (userProfileImage) {
                    sessionStorage.setItem('userProfileImage', userProfileImage);
                } else {
                    sessionStorage.removeItem('userProfileImage');
                }
            }
        })
        .catch(error => {
            console.error('Error loading user profile image from server:', error);
        })
        .finally(() => {
            isLoading = false;
        });
}

/**
 * Load user profile image (legacy function - now uses server function)
 */
function loadUserProfileImage() {
    return loadUserProfileImageFromServer();
}

/**
 * Update all profile avatars on the page
 */
function updateAllProfileAvatars() {
    // Use requestAnimationFrame for smooth updates
    requestAnimationFrame(() => {
        updateTopNavAvatar();
        updateSidebarAvatar();
        updateChatAvatars();
    });
}

/**
 * Update the top navigation avatar
 */
function updateTopNavAvatar() {
    const avatarElement = document.getElementById('top-nav-profile-avatar');
    if (!avatarElement) return;
    
    if (userProfileImage) {
        const img = document.createElement('img');
        img.src = userProfileImage;
        img.alt = 'Profile';
        img.style.cssText = 'width: 28px; height: 28px; border-radius: 50%; object-fit: cover;';
        
        // Add smooth loading
        img.onload = function() {
            this.classList.add('loaded');
        };
        
        avatarElement.innerHTML = '';
        avatarElement.appendChild(img);
        avatarElement.style.backgroundColor = 'transparent';
    } else {
        // Keep the existing initials display, but use cached name if possible
        const nameElement = avatarElement.parentElement.querySelector('.fw-semibold');
        if (nameElement) {
            const name = nameElement.textContent.trim();
            const initials = getInitials(name);
            avatarElement.innerHTML = `<span class="text-white fw-bold" style="font-size: 1rem;">${initials}</span>`;
            avatarElement.classList.add('rounded-circle', 'bg-secondary', 'd-flex', 'align-items-center', 'justify-content-center');
            avatarElement.style.width = '28px';
            avatarElement.style.height = '28px';
            avatarElement.style.backgroundColor = '#6c757d';
        }
    }
}

/**
 * Update the sidebar avatar if present
 */
function updateSidebarAvatar() {
    const sidebarAvatar = document.getElementById('sidebar-profile-avatar');
    if (!sidebarAvatar) return;
    
    if (userProfileImage) {
        const img = document.createElement('img');
        img.src = userProfileImage;
        img.alt = 'Profile';
        img.style.cssText = 'width: 28px; height: 28px; border-radius: 50%; object-fit: cover;';
        
        // Add smooth loading
        img.onload = function() {
            this.classList.add('loaded');
        };
        
        sidebarAvatar.innerHTML = '';
        sidebarAvatar.appendChild(img);
        sidebarAvatar.style.backgroundColor = 'transparent';
    } else {
        // Get initials for sidebar
        const nameElement = document.querySelector('#sidebar-user-account .fw-semibold');
        if (nameElement) {
            const name = nameElement.textContent.trim();
            const initials = getInitials(name);
            sidebarAvatar.innerHTML = `<span class="text-white fw-bold" style="font-size: 1rem;">${initials}</span>`;
            sidebarAvatar.classList.add('rounded-circle', 'bg-secondary', 'd-flex', 'align-items-center', 'justify-content-center');
            sidebarAvatar.style.width = '28px';
            sidebarAvatar.style.height = '28px';
            sidebarAvatar.style.backgroundColor = '#6c757d';
        }
    }
}

/**
 * Update chat message avatars (if we're on the chat page)
 */
function updateChatAvatars() {
    // Update existing user message avatars in the chat
    const userMessageAvatars = document.querySelectorAll('.user-message .avatar');
    userMessageAvatars.forEach(avatar => {
        if (userProfileImage) {
            avatar.src = userProfileImage;
            avatar.alt = "You";
        } else {
            avatar.src = "/static/images/user-avatar.png";
            avatar.alt = "User Avatar";
        }
    });
    
    // Also update any standalone user avatars with the user-avatar class
    const userAvatars = document.querySelectorAll('.user-avatar');
    userAvatars.forEach(avatar => {
        if (userProfileImage) {
            if (avatar.tagName === 'IMG') {
                avatar.src = userProfileImage;
                avatar.alt = "You";
            } else {
                avatar.innerHTML = `<img src="${userProfileImage}" alt="You" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover;">`;
                avatar.style.backgroundColor = 'transparent';
            }
        } else {
            if (avatar.tagName === 'IMG') {
                avatar.src = "/static/images/user-avatar.png";
                avatar.alt = "User Avatar";
            } else {
                const initials = getInitials(getUserDisplayName());
                avatar.innerHTML = `<span class="text-white fw-bold" style="font-size: 0.75rem;">${initials}</span>`;
                avatar.style.backgroundColor = '#6c757d';
            }
        }
    });
}

/**
 * Get initials from a name
 */
function getInitials(name) {
    if (!name) return 'U';
    return name.split(' ')
               .map(part => part.charAt(0))
               .join('')
               .toUpperCase()
               .substring(0, 2);
}

/**
 * Get user display name from the page
 */
function getUserDisplayName() {
    const nameElement = document.querySelector('.fw-semibold');
    return nameElement ? nameElement.textContent.trim() : 'User';
}

/**
 * Create a profile avatar element
 * @param {string} size - Size of the avatar (e.g., '28px', '36px')
 * @param {string} className - Additional CSS classes
 * @returns {HTMLElement} Avatar element
 */
function createProfileAvatar(size = '28px', className = '') {
    const avatar = document.createElement('div');
    avatar.className = `rounded-circle bg-secondary d-flex align-items-center justify-content-center ${className}`;
    avatar.style.width = size;
    avatar.style.height = size;
    
    if (userProfileImage) {
        avatar.innerHTML = `<img src="${userProfileImage}" alt="Profile" style="width: ${size}; height: ${size}; border-radius: 50%; object-fit: cover;">`;
        avatar.style.backgroundColor = 'transparent';
    } else {
        const initials = getInitials(getUserDisplayName());
        avatar.innerHTML = `<span class="text-white fw-bold" style="font-size: 1rem;">${initials}</span>`;
    }
    
    return avatar;
}

/**
 * Refresh profile image from Microsoft Graph
 */
function refreshProfileImage() {
    return fetch('/api/profile/image/refresh', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            userProfileImage = data.profileImage;
            console.log('Profile image refreshed:', userProfileImage ? 'Image updated' : 'No image found');
            updateAllProfileAvatars();
            
            // Store in sessionStorage for persistence across page navigation
            if (userProfileImage) {
                sessionStorage.setItem('userProfileImage', userProfileImage);
            } else {
                sessionStorage.removeItem('userProfileImage');
            }
            
            return data;
        } else {
            throw new Error(data.error || 'Failed to refresh profile image');
        }
    });
}

// Export functions for use in other scripts
window.ProfileImage = {
    load: loadUserProfileImage,
    update: updateAllProfileAvatars,
    refresh: refreshProfileImage,
    create: createProfileAvatar,
    getInitials: getInitials,
    getUserImage: () => userProfileImage,
    // Debug function
    debug: () => {
        console.log('ProfileImage Debug Info:');
        console.log('- Current profile image:', userProfileImage ? 'Set' : 'Not set');
        console.log('- SessionStorage:', sessionStorage.getItem('userProfileImage') ? 'Has cached image' : 'No cached image');
        console.log('- Top nav avatar element:', document.getElementById('top-nav-profile-avatar') ? 'Found' : 'Not found');
        console.log('- Sidebar avatar element:', document.getElementById('sidebar-profile-avatar') ? 'Found' : 'Not found');
        return {
            hasImage: !!userProfileImage,
            hasCachedImage: !!sessionStorage.getItem('userProfileImage'),
            hasTopNavElement: !!document.getElementById('top-nav-profile-avatar'),
            hasSidebarElement: !!document.getElementById('sidebar-profile-avatar')
        };
    }
};
