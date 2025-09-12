# Dark Mode and Light Mode Logo Support Feature

**Version Implemented:** 0.229.001

## Overview
The Dark Mode and Light Mode Logo Support feature introduces intelligent logo management that automatically switches between different logo variants based on the user's selected theme, ensuring optimal brand visibility and user experience across both light and dark interface modes.

## Purpose
This feature enables organizations to:
- Maintain consistent branding across both light and dark themes
- Provide optimal logo visibility in all viewing conditions
- Automatically adapt branding elements to user preferences
- Support accessibility requirements for high contrast viewing
- Enhance professional appearance in both theme modes

## Technical Specifications

### Architecture Overview
- **Dual Logo Storage**: Separate storage for light and dark mode logo variants
- **Theme Detection**: Automatic theme detection and logo switching
- **CSS Integration**: CSS-based logo switching with fallback support
- **Admin Configuration**: Easy upload and management of both logo variants

### Database Schema
```json
{
  "logo_configuration": {
    "light_mode_logo": {
      "filename": "logo-light.png",
      "base64_data": "data:image/png;base64,iVBORw0KGgoAAAANS...",
      "upload_date": "2025-09-12T10:30:00Z",
      "file_size": 15420,
      "dimensions": {
        "width": 200,
        "height": 60
      }
    },
    "dark_mode_logo": {
      "filename": "logo-dark.png", 
      "base64_data": "data:image/png;base64,iVBORw0KGgoAAAANS...",
      "upload_date": "2025-09-12T10:30:00Z",
      "file_size": 16180,
      "dimensions": {
        "width": 200,
        "height": 60
      }
    },
    "fallback_logo": "light_mode_logo",
    "auto_switch_enabled": true
  }
}
```

### CSS Implementation
```css
.app-logo {
    height: 40px;
    max-width: 200px;
    transition: opacity 0.3s ease;
}

/* Light mode logo - default */
.app-logo.light-logo {
    display: block;
}

.app-logo.dark-logo {
    display: none;
}

/* Dark mode logo switching */
[data-bs-theme="dark"] .app-logo.light-logo {
    display: none;
}

[data-bs-theme="dark"] .app-logo.dark-logo {
    display: block;
}

/* Fallback for browsers without CSS custom properties */
@media (prefers-color-scheme: dark) {
    .app-logo.light-logo {
        display: none;
    }
    
    .app-logo.dark-logo {
        display: block;
    }
}
```

### JavaScript Theme Management
```javascript
class ThemeLogoManager {
    constructor() {
        this.lightLogo = document.querySelector('.app-logo.light-logo');
        this.darkLogo = document.querySelector('.app-logo.dark-logo');
        this.currentTheme = this.detectTheme();
        this.initializeLogoSwitching();
    }
    
    detectTheme() {
        // Check localStorage, system preference, or default
        return localStorage.getItem('theme') || 
               (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    }
    
    switchLogo(theme) {
        if (theme === 'dark') {
            this.lightLogo.style.display = 'none';
            this.darkLogo.style.display = 'block';
        } else {
            this.lightLogo.style.display = 'block';
            this.darkLogo.style.display = 'none';
        }
    }
    
    initializeLogoSwitching() {
        // Listen for theme changes
        document.addEventListener('themeChanged', (event) => {
            this.switchLogo(event.detail.theme);
        });
        
        // Initialize with current theme
        this.switchLogo(this.currentTheme);
    }
}
```

## Configuration Options

### Admin Settings Interface
```html
<div class="logo-configuration-section">
    <h5>Logo Configuration</h5>
    
    <div class="row">
        <div class="col-md-6">
            <div class="form-group">
                <label>Light Mode Logo</label>
                <input type="file" id="light-logo-upload" accept="image/*" class="form-control">
                <small class="form-text text-muted">Recommended: Dark logo on transparent background</small>
                <div class="logo-preview" id="light-logo-preview"></div>
            </div>
        </div>
        
        <div class="col-md-6">
            <div class="form-group">
                <label>Dark Mode Logo</label>
                <input type="file" id="dark-logo-upload" accept="image/*" class="form-control">
                <small class="form-text text-muted">Recommended: Light logo on transparent background</small>
                <div class="logo-preview" id="dark-logo-preview"></div>
            </div>
        </div>
    </div>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="auto-switch-logos" class="form-check-input" checked>
            <label class="form-check-label">Automatically switch logos based on theme</label>
        </div>
    </div>
    
    <div class="form-group">
        <label>Fallback Logo</label>
        <select id="fallback-logo" class="form-control">
            <option value="light">Light Mode Logo</option>
            <option value="dark">Dark Mode Logo</option>
        </select>
        <small class="form-text text-muted">Used when automatic switching is disabled or theme cannot be detected</small>
    </div>
</div>
```

### Logo Requirements and Validation
```javascript
const logoValidation = {
    maxFileSize: 500 * 1024, // 500KB
    allowedFormats: ['image/png', 'image/jpeg', 'image/svg+xml'],
    maxDimensions: {
        width: 400,
        height: 120
    },
    recommendedDimensions: {
        width: 200,
        height: 60
    }
};

function validateLogoUpload(file) {
    const errors = [];
    
    if (file.size > logoValidation.maxFileSize) {
        errors.push('File size must be less than 500KB');
    }
    
    if (!logoValidation.allowedFormats.includes(file.type)) {
        errors.push('Only PNG, JPEG, and SVG files are allowed');
    }
    
    return errors;
}
```

## Usage Instructions

### For Administrators

#### Setting Up Dual Logos
1. **Access Admin Settings**: Navigate to Admin Settings → UI Configuration
2. **Upload Light Mode Logo**: 
   - Click "Choose File" for Light Mode Logo
   - Select a logo optimized for light backgrounds (typically dark colored)
   - Preview will show how it appears in light mode
3. **Upload Dark Mode Logo**:
   - Click "Choose File" for Dark Mode Logo  
   - Select a logo optimized for dark backgrounds (typically light colored)
   - Preview will show how it appears in dark mode
4. **Configure Auto-Switching**: Enable automatic logo switching based on user theme
5. **Set Fallback**: Choose which logo to use as fallback for unsupported browsers

#### Logo Design Recommendations
- **Light Mode Logo**: Dark or colored logo with transparent background
- **Dark Mode Logo**: Light or white logo with transparent background
- **Format**: PNG with transparency preferred, SVG for scalability
- **Dimensions**: 200x60px recommended, maximum 400x120px
- **File Size**: Keep under 500KB for optimal performance

#### Testing Logo Configuration
```javascript
// Test logo switching functionality
function testLogoSwitching() {
    const themes = ['light', 'dark'];
    themes.forEach(theme => {
        document.documentElement.setAttribute('data-bs-theme', theme);
        console.log(`Testing ${theme} theme logo visibility`);
        
        const lightLogo = document.querySelector('.app-logo.light-logo');
        const darkLogo = document.querySelector('.app-logo.dark-logo');
        
        console.log(`Light logo visible: ${lightLogo.offsetParent !== null}`);
        console.log(`Dark logo visible: ${darkLogo.offsetParent !== null}`);
    });
}
```

### For End Users

#### Theme-Based Logo Experience
- **Automatic Switching**: Logos automatically change when switching between light and dark modes
- **System Preference**: Respects system-level dark mode preferences
- **Manual Override**: Works with manual theme selection in application settings
- **Consistent Branding**: Always displays appropriate logo variant for current theme

## Integration Points

### Theme System Integration
- **Bootstrap Integration**: Works seamlessly with Bootstrap's data-bs-theme attribute
- **CSS Custom Properties**: Integrates with CSS variable-based theming
- **JavaScript Events**: Responds to theme change events throughout the application

### Performance Integration
- **Lazy Loading**: Logos loaded efficiently to minimize initial page load
- **Caching**: Base64 embedded logos cached for optimal performance
- **Preloading**: Both logo variants preloaded to prevent flicker during theme switches

### Accessibility Integration
```html
<img src="data:image/png;base64,..." 
     alt="Company Logo" 
     class="app-logo light-logo"
     role="img"
     aria-label="Company name in light mode">

<img src="data:image/png;base64,..." 
     alt="Company Logo" 
     class="app-logo dark-logo"
     role="img"
     aria-label="Company name in dark mode">
```

## User Experience Enhancements

### Smooth Transitions
```css
.app-logo {
    transition: opacity 0.3s ease, transform 0.3s ease;
}

.theme-switching .app-logo {
    opacity: 0;
}

.theme-switching.complete .app-logo {
    opacity: 1;
}
```

### Loading States
```javascript
class LogoLoadingManager {
    showLoadingState() {
        const logoContainer = document.querySelector('.logo-container');
        logoContainer.classList.add('loading');
        logoContainer.innerHTML = '<div class="logo-skeleton"></div>';
    }
    
    hideLoadingState(logoElement) {
        const logoContainer = document.querySelector('.logo-container');
        logoContainer.classList.remove('loading');
        logoContainer.appendChild(logoElement);
    }
}
```

### Responsive Behavior
```css
@media (max-width: 768px) {
    .app-logo {
        height: 32px;
        max-width: 160px;
    }
}

@media (max-width: 480px) {
    .app-logo {
        height: 28px;
        max-width: 120px;
    }
}
```

## Testing and Validation

### Functional Testing
- Verify logo switches correctly between light and dark themes
- Test fallback behavior when one logo variant is missing
- Validate admin upload functionality for both logo types
- Confirm responsive scaling across different screen sizes

### Visual Testing
- Compare logo visibility across different background colors
- Test contrast ratios for accessibility compliance
- Verify logo quality at different display densities (retina displays)
- Validate alignment and positioning in navigation bar

### Performance Testing
- Measure logo loading times for both variants
- Test theme switching performance with different logo file sizes
- Validate memory usage with large logo files
- Confirm no visual flicker during theme transitions

## Known Limitations
- SVG logos may not support all CSS filters for automatic color inversion
- Very large logo files may cause brief loading delays
- Some older browsers may not support automatic theme detection
- Base64 encoding increases HTML file size slightly

## Browser Compatibility
- **Full Support**: Chrome 90+, Firefox 88+, Safari 14+, Edge 90+
- **Theme Detection**: Supports prefers-color-scheme media query
- **Fallback Support**: Graceful degradation to single logo for older browsers

## Migration Notes
- Existing single logos are automatically used as light mode logos
- Dark mode logos need to be uploaded separately through admin settings
- No breaking changes to existing logo functionality
- Previous logo configurations remain functional

## Future Enhancements
- Automatic logo color inversion for monochrome logos
- Support for animated logos (GIF/APNG) with theme switching
- Logo A/B testing capabilities for different variants
- Integration with brand management systems
- Advanced logo customization options per user group or department