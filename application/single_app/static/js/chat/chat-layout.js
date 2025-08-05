// static/js/chat/chat-layout.js

// Sidebar is always docked: remove all toggle, split, and user settings logic

// DOM elements
const leftPane = document.getElementById('left-pane');
const rightPane = document.getElementById('right-pane');

// On DOMContentLoaded, always apply docked layout
document.addEventListener('DOMContentLoaded', () => {
    document.body.classList.remove('layout-split', 'left-pane-hidden');
    document.body.classList.add('layout-docked');
    // Ensure panes have correct styles applied by CSS (.layout-docked)
    if (leftPane) {
        leftPane.style.width = '';
        leftPane.style.flexBasis = '';
    }
    if (rightPane) {
        rightPane.style.marginLeft = '';
        rightPane.style.width = '';
        rightPane.style.flexBasis = '';
    }
});

// Remove Split.js, toggle, and user settings logic entirely

// If any other modules import setSplitContainerMode, keep it as a no-op for compatibility
export function setSplitContainerMode(isSplit) {
  // No-op: always fluid, always docked
}