# SimpleChat Jekyll Theme

A responsive, feature-rich Jekyll theme based on the SimpleChat application's design system. This theme provides:

## Features

- **Responsive Design**: Works seamlessly on desktop, tablet, and mobile devices
- **Dark/Light Mode**: Built-in theme switching with persistent preferences
- **Flexible Navigation**: Choose between sidebar or top navigation layouts
- **Bootstrap 5**: Modern, accessible component library
- **Syntax Highlighting**: Prism.js integration with theme-aware highlighting
- **Search Functionality**: Fast, client-side search capabilities
- **Documentation Structure**: Organized sections for tutorials, how-to guides, reference, and explanations

## Layout Options

### Sidebar Navigation (Default)
- Fixed sidebar with collapsible sections
- Auto-expanding current section
- User preferences section at bottom
- Mobile-responsive with overlay behavior

### Top Navigation
- Fixed top navbar with dropdown menus
- Responsive mobile menu
- Clean, minimal design

## Configuration

The theme is configured through `_config.yml`. Key settings include:

```yaml
# Navigation layout
navigation:
  layout: sidebar  # or 'top'
  sidebar_default: true
  show_sections: true
  
# Site branding
logo:
  show: true
  light_url: /assets/images/logo.png
  dark_url: /assets/images/logo-dark.png

# Main navigation links
navigation:
  main_links:
    - title: Home
      url: /
      icon: bi bi-house-fill
```

## File Structure

```
_layouts/
  default.html          # Main layout template
  page.html            # Page layout with navigation

_includes/
  sidebar_nav.html     # Sidebar navigation component
  top_nav.html         # Top navigation component

assets/
  css/
    main.scss          # Main stylesheet
  js/
    dark-mode.js       # Theme switching functionality
    navigation.js      # Navigation layout switching
    sidebar.js         # Sidebar interactions
    main.js           # General utilities

_sass/                 # SCSS partials (optional)
```

## Usage

1. Set your preferred navigation layout in `_config.yml`
2. Customize colors and branding
3. Add your content in the appropriate sections
4. Organize pages using the `section` front matter

## Customization

The theme uses CSS custom properties for easy customization:

```css
:root {
  --simplechat-primary: #0078D4;
  --sidebar-width: 260px;
  --navbar-height: 56px;
}
```

## Dark Mode

Users can toggle between light and dark themes using:
- The theme toggle button in navigation
- Keyboard shortcut: `Ctrl/Cmd + Shift + L`
- Settings persist in localStorage

## Mobile Support

The theme is fully responsive with:
- Collapsible sidebar on mobile
- Touch-friendly navigation
- Optimized layouts for small screens