// Adds a draggable resize handle for the sidebar
document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.getElementById('sidebar-nav');
  const handle = document.getElementById('sidebar-resize-handle');
  if (!sidebar || !handle) return;

  const root = document.documentElement;
  const userAccount = document.getElementById('sidebar-user-account');

  const parsePx = (value, fallback) => {
    const parsed = parseInt(String(value).replace('px', '').trim(), 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  const getVar = (name, fallback) => {
    const fromStyle = getComputedStyle(root).getPropertyValue(name);
    if (fromStyle && fromStyle.trim()) return parsePx(fromStyle, fallback);
    return fallback;
  };

  const minWidth = getVar('--sidebar-min-width', 220);
  const maxWidth = getVar('--sidebar-max-width', 420);

  const applyWidth = (widthPx) => {
    const clamped = Math.min(Math.max(widthPx, minWidth), maxWidth);
    root.style.setProperty('--sidebar-width', `${clamped}px`);
    sidebar.style.width = `${clamped}px`;
    if (userAccount) {
      userAccount.style.width = `${clamped}px`;
    }
  };

  // Restore stored width if available
  const stored = localStorage.getItem('sidebarWidth');
  if (stored) {
    const parsed = parseInt(stored, 10);
    if (Number.isFinite(parsed)) {
      applyWidth(parsed);
    }
  }

  let isDragging = false;

  const onMouseMove = (e) => {
    if (!isDragging) return;
    const newWidth = e.clientX;
    applyWidth(newWidth);
  };

  const stopDrag = () => {
    if (!isDragging) return;
    isDragging = false;
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', stopDrag);
    const currentWidth = parsePx(getComputedStyle(sidebar).width, minWidth);
    localStorage.setItem('sidebarWidth', String(currentWidth));
  };

  handle.addEventListener('mousedown', (e) => {
    e.preventDefault();
    isDragging = true;
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', stopDrag);
  });

  handle.addEventListener('keydown', (e) => {
    const step = 10;
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      const current = parsePx(getComputedStyle(sidebar).width, minWidth);
      applyWidth(current - step);
      localStorage.setItem('sidebarWidth', String(parsePx(getComputedStyle(sidebar).width, minWidth)));
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      const current = parsePx(getComputedStyle(sidebar).width, minWidth);
      applyWidth(current + step);
      localStorage.setItem('sidebarWidth', String(parsePx(getComputedStyle(sidebar).width, minWidth)));
    }
  });
});
