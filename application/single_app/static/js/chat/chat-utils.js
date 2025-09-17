// chat-utils.js
export function toBoolean(value) {
  if (value === true || value === 1) return true;
  if (value === false || value === 0 || !value) return false;
  
  const strValue = String(value).toLowerCase().trim();
  return strValue === "true" || strValue === "1" || strValue === "yes" || strValue === "y";
}

export function isColorLight(hexColor) {
  if (!hexColor || typeof hexColor !== 'string' || hexColor.length < 4) return false; // Default to dark background assumption

  let r, g, b;
  hexColor = hexColor.replace('#', ''); // Remove #

  if (hexColor.length === 3) { // #RGB format
      r = parseInt(hexColor[0] + hexColor[0], 16);
      g = parseInt(hexColor[1] + hexColor[1], 16);
      b = parseInt(hexColor[2] + hexColor[2], 16);
  } else if (hexColor.length === 6) { // #RRGGBB format
      r = parseInt(hexColor.substring(0, 2), 16);
      g = parseInt(hexColor.substring(2, 4), 16);
      b = parseInt(hexColor.substring(4, 6), 16);
  } else {
      return false; // Invalid format
  }

  // Formula for perceived brightness (YIQ simplified)
  const brightness = ((r * 299) + (g * 587) + (b * 114)) / 1000;
  return brightness > 150; // Threshold adjustable (128 is middle gray, higher means more colors are considered 'light')
}

// --- Other utility functions like getUrlParameter can go here ---
export function getUrlParameter(name) {
  name = name.replace(/[\[]/, '\\[').replace(/[\]]/, '\\]');
  var regex = new RegExp('[\\?&]' + name + '=([^&#]*)');
  var results = regex.exec(location.search);
  return results === null ? '' : decodeURIComponent(results[1].replace(/\+/g, ' '));
};

// Add escapeHtml if not already present globally or imported
export function escapeHtml(unsafe) {
  if (unsafe === null || typeof unsafe === 'undefined') return '';
  return unsafe.toString()
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
}

// Add target="_blank" and rel="noopener noreferrer" to external links in HTML content
export function addTargetBlankToExternalLinks(htmlContent) {
  if (!htmlContent || typeof htmlContent !== 'string') return htmlContent;
  
  // Create a temporary DOM element to parse and modify the HTML
  const tempDiv = document.createElement('div');
  tempDiv.innerHTML = htmlContent;
  
  // Find all anchor tags
  const links = tempDiv.querySelectorAll('a[href]');
  
  links.forEach(link => {
    const href = link.getAttribute('href');
    
    // Check if it's an external link (starts with http:// or https://)
    if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
      // Add target="_blank" if not already present
      if (!link.hasAttribute('target')) {
        link.setAttribute('target', '_blank');
      }
      
      // Add rel="noopener noreferrer" for security
      const currentRel = link.getAttribute('rel') || '';
      const relValues = currentRel.split(/\s+/).filter(val => val.length > 0);
      
      if (!relValues.includes('noopener')) {
        relValues.push('noopener');
      }
      if (!relValues.includes('noreferrer')) {
        relValues.push('noreferrer');
      }
      
      link.setAttribute('rel', relValues.join(' '));
    }
  });
  
  return tempDiv.innerHTML;
}