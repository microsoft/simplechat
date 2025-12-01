// chat-search-modal.js
// Advanced search modal functionality

import { showToast } from "./chat-toast.js";

let currentSearchParams = null;
let currentPage = 1;
let advancedSearchModal = null;

// Initialize modal when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const modalElement = document.getElementById('advancedSearchModal');
    if (modalElement) {
        advancedSearchModal = new bootstrap.Modal(modalElement);
        
        // Set up event listeners
        setupEventListeners();
    }
});

function setupEventListeners() {
    // Search button
    const searchBtn = document.getElementById('performSearchBtn');
    if (searchBtn) {
        searchBtn.addEventListener('click', () => {
            performAdvancedSearch(1);
        });
    }
    
    // Clear filters button
    const clearBtn = document.getElementById('clearFiltersBtn');
    if (clearBtn) {
        clearBtn.addEventListener('click', clearFilters);
    }
    
    // Clear history button
    const clearHistoryBtn = document.getElementById('clearHistoryBtn');
    if (clearHistoryBtn) {
        clearHistoryBtn.addEventListener('click', clearSearchHistory);
    }
    
    // Pagination buttons
    const prevBtn = document.getElementById('searchPrevBtn');
    const nextBtn = document.getElementById('searchNextBtn');
    
    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            if (currentPage > 1) {
                performAdvancedSearch(currentPage - 1);
            }
        });
    }
    
    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            performAdvancedSearch(currentPage + 1);
        });
    }
    
    // Enter key in search input
    const searchInput = document.getElementById('searchMessageInput');
    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                performAdvancedSearch(1);
            }
        });
    }
}

export function openAdvancedSearchModal() {
    if (advancedSearchModal) {
        advancedSearchModal.show();
        
        // Load classifications and history when modal opens
        loadClassifications();
        loadSearchHistory();
    }
}

async function loadClassifications() {
    try {
        const response = await fetch('/api/conversations/classifications', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (!response.ok) {
            throw new Error('Failed to load classifications');
        }
        
        const data = await response.json();
        const select = document.getElementById('searchClassifications');
        
        if (select && data.classifications) {
            // Clear loading option
            select.innerHTML = '';
            
            if (data.classifications.length === 0) {
                select.innerHTML = '<option value="" disabled>No classifications available</option>';
            } else {
                data.classifications.forEach(classification => {
                    const option = document.createElement('option');
                    option.value = classification;
                    option.textContent = classification;
                    select.appendChild(option);
                });
            }
        }
    } catch (error) {
        console.error('Error loading classifications:', error);
        const select = document.getElementById('searchClassifications');
        if (select) {
            select.innerHTML = '<option value="" disabled>Error loading classifications</option>';
        }
    }
}

async function loadSearchHistory() {
    try {
        const response = await fetch('/api/user-settings/search-history', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (!response.ok) {
            throw new Error('Failed to load search history');
        }
        
        const data = await response.json();
        const historyList = document.getElementById('searchHistoryList');
        
        if (historyList && data.history) {
            if (data.history.length === 0) {
                historyList.innerHTML = `
                    <div class="text-center p-4 text-muted">
                        <i class="bi bi-clock-history" style="font-size: 3rem; opacity: 0.3;"></i>
                        <p class="mt-2">No search history yet</p>
                    </div>
                `;
            } else {
                historyList.innerHTML = '';
                const listGroup = document.createElement('div');
                listGroup.className = 'list-group';
                
                data.history.forEach(item => {
                    const listItem = document.createElement('a');
                    listItem.href = '#';
                    listItem.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center';
                    listItem.innerHTML = `
                        <span>${escapeHtml(item.term)}</span>
                        <small class="text-muted">${formatDate(item.timestamp)}</small>
                    `;
                    
                    listItem.addEventListener('click', (e) => {
                        e.preventDefault();
                        populateSearchFromHistory(item.term);
                    });
                    
                    listGroup.appendChild(listItem);
                });
                
                historyList.appendChild(listGroup);
            }
        }
    } catch (error) {
        console.error('Error loading search history:', error);
    }
}

function populateSearchFromHistory(searchTerm) {
    const searchInput = document.getElementById('searchMessageInput');
    if (searchInput) {
        searchInput.value = searchTerm;
    }
    
    // Switch to search tab
    const searchTab = document.getElementById('search-tab');
    if (searchTab) {
        searchTab.click();
    }
    
    // Perform search
    performAdvancedSearch(1);
}

async function performAdvancedSearch(page = 1) {
    const searchTerm = document.getElementById('searchMessageInput').value.trim();
    
    // Validate search term
    if (!searchTerm || searchTerm.length < 3) {
        showToast('Please enter at least 3 characters to search', 'warning');
        return;
    }
    
    // Collect form values
    const dateFrom = document.getElementById('searchDateFrom').value;
    const dateTo = document.getElementById('searchDateTo').value;
    
    const chatTypes = [];
    if (document.getElementById('chatTypePersonal').checked) chatTypes.push('personal');
    if (document.getElementById('chatTypeGroupSingle').checked) chatTypes.push('group-single-user');
    if (document.getElementById('chatTypeGroupMulti').checked) chatTypes.push('group-multi-user');
    if (document.getElementById('chatTypePublic').checked) chatTypes.push('public');
    
    const classSelect = document.getElementById('searchClassifications');
    const classifications = Array.from(classSelect.selectedOptions).map(opt => opt.value);
    
    const hasFiles = document.getElementById('searchHasFiles').checked;
    const hasImages = document.getElementById('searchHasImages').checked;
    
    currentSearchParams = {
        search_term: searchTerm,
        date_from: dateFrom,
        date_to: dateTo,
        chat_types: chatTypes,
        classifications: classifications,
        has_files: hasFiles,
        has_images: hasImages,
        page: page,
        per_page: 20
    };
    
    currentPage = page;
    
    // Show loading
    const loadingDiv = document.getElementById('searchResultsLoading');
    const contentDiv = document.getElementById('searchResultsContent');
    const emptyDiv = document.getElementById('searchResultsEmpty');
    const paginationDiv = document.getElementById('searchPagination');
    
    if (loadingDiv) loadingDiv.style.display = 'block';
    if (contentDiv) contentDiv.innerHTML = '';
    if (emptyDiv) emptyDiv.style.display = 'none';
    if (paginationDiv) paginationDiv.style.display = 'none';
    
    try {
        const response = await fetch('/api/search_conversations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(currentSearchParams)
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Search failed');
        }
        
        const data = await response.json();
        
        // Hide loading
        if (loadingDiv) loadingDiv.style.display = 'none';
        
        if (data.total_results === 0) {
            if (emptyDiv) emptyDiv.style.display = 'block';
        } else {
            // Render results
            renderSearchResults(data);
            
            // Save to history (only on first page)
            if (page === 1) {
                saveSearchToHistory(searchTerm);
            }
        }
        
    } catch (error) {
        console.error('Search error:', error);
        if (loadingDiv) loadingDiv.style.display = 'none';
        showToast(error.message || 'Failed to search conversations', 'error');
    }
}

function renderSearchResults(data) {
    const contentDiv = document.getElementById('searchResultsContent');
    const paginationDiv = document.getElementById('searchPagination');
    
    if (!contentDiv) return;
    
    contentDiv.innerHTML = '';
    
    // Show result count
    const resultHeader = document.createElement('div');
    resultHeader.className = 'mb-3';
    resultHeader.innerHTML = `<h6>Found ${data.total_results} result${data.total_results !== 1 ? 's' : ''}</h6>`;
    contentDiv.appendChild(resultHeader);
    
    // Render each conversation result
    data.results.forEach(result => {
        const card = document.createElement('div');
        card.className = 'card mb-3';
        
        const cardBody = document.createElement('div');
        cardBody.className = 'card-body';
        
        // Conversation title and metadata
        const titleDiv = document.createElement('div');
        titleDiv.className = 'd-flex justify-content-between align-items-start mb-2';
        
        const titleText = document.createElement('h6');
        titleText.className = 'card-title mb-0';
        titleText.innerHTML = `
            ${result.conversation.is_pinned ? '<i class="bi bi-pin-angle-fill me-1"></i>' : ''}
            ${escapeHtml(result.conversation.title)}
        `;
        
        const metaText = document.createElement('small');
        metaText.className = 'text-muted';
        metaText.textContent = formatDate(result.conversation.last_updated);
        
        titleDiv.appendChild(titleText);
        titleDiv.appendChild(metaText);
        cardBody.appendChild(titleDiv);
        
        // Classifications and chat type
        if (result.conversation.classification && result.conversation.classification.length > 0) {
            const badgesDiv = document.createElement('div');
            badgesDiv.className = 'mb-2';
            result.conversation.classification.forEach(cls => {
                const badge = document.createElement('span');
                badge.className = 'badge bg-secondary me-1';
                badge.textContent = cls;
                badgesDiv.appendChild(badge);
            });
            cardBody.appendChild(badgesDiv);
        }
        
        // Message matches
        const matchesDiv = document.createElement('div');
        matchesDiv.className = 'mt-2';
        matchesDiv.innerHTML = `<strong>${result.match_count} message${result.match_count !== 1 ? 's' : ''} matched:</strong>`;
        
        result.messages.forEach(msg => {
            const msgDiv = document.createElement('div');
            msgDiv.className = 'border-start border-primary border-3 ps-2 py-1 mb-2 mt-2';
            msgDiv.style.cursor = 'pointer';
            msgDiv.innerHTML = highlightSearchTerm(escapeHtml(msg.content_snippet), currentSearchParams.search_term);
            
            msgDiv.addEventListener('click', () => {
                navigateToMessageWithHighlight(result.conversation.id, msg.message_id, currentSearchParams.search_term);
            });
            
            msgDiv.addEventListener('mouseenter', () => {
                msgDiv.classList.add('bg-light');
            });
            msgDiv.addEventListener('mouseleave', () => {
                msgDiv.classList.remove('bg-light');
            });
            
            matchesDiv.appendChild(msgDiv);
        });
        
        cardBody.appendChild(matchesDiv);
        card.appendChild(cardBody);
        contentDiv.appendChild(card);
    });
    
    // Update pagination
    if (paginationDiv && data.total_pages > 1) {
        paginationDiv.style.display = 'flex';
        
        const prevBtn = document.getElementById('searchPrevBtn');
        const nextBtn = document.getElementById('searchNextBtn');
        const pageInfo = document.getElementById('searchPageInfo');
        
        if (prevBtn) {
            prevBtn.disabled = currentPage === 1;
        }
        
        if (nextBtn) {
            nextBtn.disabled = currentPage === data.total_pages;
        }
        
        if (pageInfo) {
            pageInfo.textContent = `Page ${currentPage} of ${data.total_pages}`;
        }
    }
}

function highlightSearchTerm(text, searchTerm) {
    const escaped = escapeHtml(searchTerm);
    const regex = new RegExp(`(${escaped})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
}

function navigateToMessageWithHighlight(convId, msgId, searchTerm) {
    // Close the modal
    if (advancedSearchModal) {
        advancedSearchModal.hide();
    }
    
    // Set global search highlight state
    window.searchHighlight = {
        term: searchTerm,
        timestamp: Date.now(),
        timeoutId: null
    };
    
    // Load the conversation
    if (window.chatConversations && window.chatConversations.selectConversation) {
        window.chatConversations.selectConversation(convId);
        
        // Wait for messages to load, then scroll and highlight
        setTimeout(() => {
            if (window.chatMessages) {
                if (window.chatMessages.scrollToMessageSmooth) {
                    window.chatMessages.scrollToMessageSmooth(msgId);
                }
                if (window.chatMessages.applySearchHighlight) {
                    window.chatMessages.applySearchHighlight(searchTerm);
                }
            }
        }, 500);
    }
}

async function saveSearchToHistory(searchTerm) {
    try {
        await fetch('/api/user-settings/search-history', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ search_term: searchTerm })
        });
        
        // Reload history in background
        loadSearchHistory();
    } catch (error) {
        console.error('Error saving search to history:', error);
    }
}

async function clearSearchHistory() {
    if (!confirm('Are you sure you want to clear your search history?')) {
        return;
    }
    
    try {
        const response = await fetch('/api/user-settings/search-history', {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (!response.ok) {
            throw new Error('Failed to clear history');
        }
        
        showToast('Search history cleared', 'success');
        loadSearchHistory();
        
    } catch (error) {
        console.error('Error clearing search history:', error);
        showToast('Failed to clear search history', 'error');
    }
}

function clearFilters() {
    // Clear search input
    const searchInput = document.getElementById('searchMessageInput');
    if (searchInput) searchInput.value = '';
    
    // Clear dates
    const dateFrom = document.getElementById('searchDateFrom');
    const dateTo = document.getElementById('searchDateTo');
    if (dateFrom) dateFrom.value = '';
    if (dateTo) dateTo.value = '';
    
    // Check all chat types
    document.getElementById('chatTypePersonal').checked = true;
    document.getElementById('chatTypeGroupSingle').checked = true;
    document.getElementById('chatTypeGroupMulti').checked = true;
    document.getElementById('chatTypePublic').checked = true;
    
    // Clear classifications
    const classSelect = document.getElementById('searchClassifications');
    if (classSelect) {
        Array.from(classSelect.options).forEach(opt => opt.selected = false);
    }
    
    // Uncheck filters
    document.getElementById('searchHasFiles').checked = false;
    document.getElementById('searchHasImages').checked = false;
    
    // Clear results
    const contentDiv = document.getElementById('searchResultsContent');
    const emptyDiv = document.getElementById('searchResultsEmpty');
    const paginationDiv = document.getElementById('searchPagination');
    
    if (contentDiv) contentDiv.innerHTML = '';
    if (emptyDiv) emptyDiv.style.display = 'none';
    if (paginationDiv) paginationDiv.style.display = 'none';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// Expose function globally
window.chatSearchModal = {
    openAdvancedSearchModal
};
