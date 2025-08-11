// profile-image.js
// Global profile image functionality

let userProfileImage = null;
let userInitials = '';

// Initialize profile image functionality
document.addEventListener('DOMContentLoaded', function() {
    // Small delay to ensure all elements are loaded
    setTimeout(() => {
        loadUserProfileImage();
    }, 100);
});

// Also try to load when the window is fully loaded (backup)
window.addEventListener('load', function() {
    // Only reload if we haven't loaded yet
    if (userProfileImage === null && (document.getElementById('top-nav-profile-avatar') || document.getElementById('sidebar-profile-avatar'))) {
        setTimeout(() => {
            loadUserProfileImage();
        }, 200);
    }
});

/**
 * Load user profile image from settings
 */
function loadUserProfileImage() {
    // Check if user is logged in
    if (!document.getElementById('top-nav-profile-avatar') && !document.getElementById('sidebar-profile-avatar')) {
        return; // No profile avatar elements, user not logged in
    }
    
    // First, try to load from sessionStorage for faster loading
    const cachedImage = sessionStorage.getItem('userProfileImage');
    if (cachedImage && cachedImage !== 'null') {
        userProfileImage = cachedImage;
        updateAllProfileAvatars();
    }
    
    // Then fetch from server to ensure we have the latest
    fetch('/api/user/settings')
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to fetch user settings');
            }
            return response.json();
        })
        .then(data => {
            const serverProfileImage = data.settings?.profileImage;
            
            // Only update if different from cached version
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
            console.error('Error loading user profile image:', error);
            // If we don't have a cached image, show initials
            if (!userProfileImage) {
                userProfileImage = null;
                updateAllProfileAvatars();
            }
        });
}

/**
 * Update all profile avatars on the page
 */
function updateAllProfileAvatars() {
    // Update top navigation avatar
    updateTopNavAvatar();
    
    // Update sidebar avatar if present
    updateSidebarAvatar();
    
    // Update any chat message avatars
    updateChatAvatars();
}

/**
 * Update the top navigation avatar
 */
function updateTopNavAvatar() {
    const avatarElement = document.getElementById('top-nav-profile-avatar');
    if (!avatarElement) return;
    
    if (userProfileImage) {
        avatarElement.innerHTML = `<img src="${userProfileImage}" alt="Profile" style="width: 28px; height: 28px; border-radius: 50%; object-fit: cover;">`;
        avatarElement.style.backgroundColor = 'transparent';
    } else {
        // Keep the existing initials display
        const nameElement = avatarElement.parentElement.querySelector('.fw-semibold');
        if (nameElement) {
            const name = nameElement.textContent.trim();
            const initials = getInitials(name);
            avatarElement.innerHTML = `<span class="text-white fw-bold" style="font-size: 1rem;">${initials}</span>`;
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
        sidebarAvatar.innerHTML = `<img src="${userProfileImage}" alt="Profile" style="width: 24px; height: 24px; border-radius: 50%; object-fit: cover;">`;
        sidebarAvatar.style.backgroundColor = 'transparent';
    } else {
        // Get initials for sidebar
        const nameElement = document.querySelector('#sidebar-user-account .fw-semibold');
        if (nameElement) {
            const name = nameElement.textContent.trim();
            const initials = getInitials(name);
            sidebarAvatar.innerHTML = `<span class="text-white fw-bold" style="font-size: 0.75rem;">${initials}</span>`;
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
