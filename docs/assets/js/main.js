/**
 * Main JavaScript for SimpleChat Jekyll Theme
 * Handles general functionality and utilities
 */

(function() {
  'use strict';

  // Toast notification system
  function showToast(message, type = 'info', duration = 5000) {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) return;

    // Create toast element
    const toastId = 'toast-' + Date.now();
    const toastHtml = `
      <div id="${toastId}" class="toast align-items-center text-bg-${type} border-0" role="alert" aria-live="assertive" aria-atomic="true">
        <div class="d-flex">
          <div class="toast-body">
            ${message}
          </div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
      </div>
    `;

    toastContainer.insertAdjacentHTML('beforeend', toastHtml);
    
    const toastElement = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastElement, { delay: duration });
    
    toast.show();
    
    // Clean up after toast is hidden
    toastElement.addEventListener('hidden.bs.toast', function() {
      toastElement.remove();
    });
  }

  // Copy to clipboard functionality
  function copyToClipboard(text, successMessage = 'Copied to clipboard!') {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function() {
        showToast(successMessage, 'success', 2000);
      }).catch(function() {
        fallbackCopy(text, successMessage);
      });
    } else {
      fallbackCopy(text, successMessage);
    }
  }

  // Fallback clipboard copy for older browsers
  function fallbackCopy(text, successMessage) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    textArea.style.top = '-999999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {
      document.execCommand('copy');
      showToast(successMessage, 'success', 2000);
    } catch (err) {
      showToast('Failed to copy to clipboard', 'error', 3000);
    }
    
    document.body.removeChild(textArea);
  }

  // Add copy buttons to code blocks
  function addCopyButtonsToCodeBlocks() {
    const codeBlocks = document.querySelectorAll('pre[class*="language-"]');
    
    codeBlocks.forEach(function(codeBlock) {
      // Skip if copy button already exists
      if (codeBlock.querySelector('.copy-button')) return;
      
      const button = document.createElement('button');
      button.className = 'btn btn-sm btn-outline-secondary copy-button';
      button.innerHTML = '<i class="bi bi-clipboard"></i>';
      button.title = 'Copy code';
      button.style.cssText = 'position: absolute; top: 0.5rem; right: 0.5rem; z-index: 10;';
      
      // Make the code block relative positioned
      codeBlock.style.position = 'relative';
      
      button.addEventListener('click', function() {
        const code = codeBlock.querySelector('code');
        if (code) {
          copyToClipboard(code.textContent, 'Code copied!');
          
          // Visual feedback
          button.innerHTML = '<i class="bi bi-clipboard-check"></i>';
          setTimeout(function() {
            button.innerHTML = '<i class="bi bi-clipboard"></i>';
          }, 2000);
        }
      });
      
      codeBlock.appendChild(button);
    });
  }

  // Initialize Bootstrap tooltips
  function initTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
      return new bootstrap.Tooltip(tooltipTriggerEl);
    });
  }

  // Initialize Bootstrap popovers
  function initPopovers() {
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function(popoverTriggerEl) {
      return new bootstrap.Popover(popoverTriggerEl);
    });
  }

  // Smooth scrolling for anchor links
  function initSmoothScrolling() {
    document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
      anchor.addEventListener('click', function(e) {
        const targetId = this.getAttribute('href');
        if (targetId === '#') return;
        
        const targetElement = document.querySelector(targetId);
        if (targetElement) {
          e.preventDefault();
          
          const headerHeight = document.querySelector('.navbar')?.offsetHeight || 0;
          const targetPosition = targetElement.offsetTop - headerHeight - 20;
          
          window.scrollTo({
            top: targetPosition,
            behavior: 'smooth'
          });
          
          // Update URL hash
          history.pushState(null, null, targetId);
        }
      });
    });
  }

  // Add heading anchors
  function addHeadingAnchors() {
    const headings = document.querySelectorAll('h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]');
    
    headings.forEach(function(heading) {
      const anchor = document.createElement('a');
      anchor.href = '#' + heading.id;
      anchor.className = 'heading-anchor';
      anchor.innerHTML = '<i class="bi bi-link-45deg"></i>';
      anchor.style.cssText = 'margin-left: 0.5rem; opacity: 0; transition: opacity 0.2s; text-decoration: none; color: var(--bs-secondary);';
      anchor.title = 'Link to this heading';
      
      heading.appendChild(anchor);
      
      // Show anchor on hover
      heading.addEventListener('mouseenter', function() {
        anchor.style.opacity = '1';
      });
      
      heading.addEventListener('mouseleave', function() {
        anchor.style.opacity = '0';
      });
      
      // Copy link on click
      anchor.addEventListener('click', function(e) {
        e.preventDefault();
        const url = window.location.origin + window.location.pathname + this.getAttribute('href');
        copyToClipboard(url, 'Link copied!');
      });
    });
  }

  // Initialize search functionality (if search input exists)
  function initSearch() {
    const searchInput = document.querySelector('#search-input, .search-input');
    if (!searchInput) return;

    let searchTimeout;
    searchInput.addEventListener('input', function() {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(function() {
        // Implement search functionality based on your needs
        console.log('Search query:', searchInput.value);
      }, 300);
    });
  }

  // Initialize all functionality
  function init() {
    initTooltips();
    initPopovers();
    initSmoothScrolling();
    addHeadingAnchors();
    addCopyButtonsToCodeBlocks();
    initSearch();
    
    // Re-initialize after theme changes (for syntax highlighting)
    document.addEventListener('themeChanged', function() {
      setTimeout(function() {
        if (window.Prism) {
          Prism.highlightAll();
        }
        addCopyButtonsToCodeBlocks(); // Re-add copy buttons if code blocks are re-rendered
      }, 100);
    });
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Expose utilities globally
  window.SimpleChat = window.SimpleChat || {};
  window.SimpleChat.Utils = {
    showToast,
    copyToClipboard,
    addCopyButtonsToCodeBlocks,
    initTooltips,
    initPopovers
  };

})();