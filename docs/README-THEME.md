# SimpleChat Jekyll Theme Setup

This directory contains a custom Jekyll theme based on the SimpleChat application's design system. The theme provides a modern, responsive documentation site with advanced navigation and theming capabilities.

## Quick Start

1. **Install Dependencies**
   ```bash
   bundle install
   ```

2. **Serve Locally**
   ```bash
   bundle exec jekyll serve
   ```

3. **Build for Production**
   ```bash
   bundle exec jekyll build
   ```

## Theme Structure

```
├── _layouts/              # Layout templates
│   ├── default.html      # Main layout with navigation
│   └── page.html         # Page layout with metadata
├── _includes/             # Reusable components
│   ├── sidebar_nav.html  # Sidebar navigation
│   └── top_nav.html      # Top navigation bar
├── _sass/                 # SCSS partials (optional)
├── assets/
│   ├── css/
│   │   └── main.scss     # Main stylesheet
│   ├── js/               # JavaScript modules
│   │   ├── dark-mode.js  # Theme switching
│   │   ├── navigation.js # Navigation layout
│   │   ├── sidebar.js    # Sidebar functionality
│   │   └── main.js       # General utilities
│   └── images/           # Theme images
├── _config.yml           # Site configuration
└── Gemfile              # Ruby dependencies
```

## Configuration

### Navigation Layout

Choose between sidebar or top navigation in `_config.yml`:

```yaml
navigation:
  layout: sidebar  # or 'top'
  sidebar_default: true
  show_sections: true
```

### Branding

Configure your site's branding:

```yaml
logo:
  show: true
  light_url: /assets/images/logo.png
  dark_url: /assets/images/logo-dark.png
title_hidden: false
```

### Main Navigation

Define your main navigation links:

```yaml
navigation:
  main_links:
    - title: Home
      url: /
      icon: bi bi-house-fill
    - title: Features
      url: /features/
      icon: bi bi-stars
```

### Content Organization

Organize content using sections in front matter:

```yaml
---
layout: page
title: "Your Page Title"
section: "Tutorials"  # Creates automatic sidebar grouping
---
```

Available sections: `tutorials`, `how-to`, `reference`, `explanation`

## Features

### 🎨 Theme Switching
- Light/dark mode toggle
- Persistent user preferences
- Keyboard shortcut support (`Ctrl/Cmd + Shift + L`)

### 📱 Responsive Design
- Mobile-first approach
- Collapsible sidebar on mobile
- Touch-friendly interactions

### 🔍 Enhanced Navigation
- Auto-expanding current section
- Collapsible section groups
- External links support

### 💻 Developer-Friendly
- Syntax highlighting with Prism.js
- Copy-to-clipboard for code blocks
- Bootstrap 5 components
- Custom CSS properties for easy theming

### ⚡ Performance
- CDN-hosted assets
- Optimized CSS/JS loading
- Minimal JavaScript footprint

## Customization

### Colors and Branding

Customize the theme by overriding CSS custom properties:

```css
:root {
  --simplechat-primary: #0078D4;
  --simplechat-secondary: #6c757d;
  --sidebar-width: 260px;
}
```

### Adding Custom JavaScript

Include custom JavaScript in your pages:

```yaml
---
layout: page
custom_js:
  - /assets/js/my-custom-script.js
---
```

### Classification Banner

Add a classification banner for sensitive sites:

```yaml
classification_banner:
  enabled: true
  text: "CONFIDENTIAL"
  color: "#dc3545"
```

## Content Types

### Regular Pages
Use the `page` layout for standard documentation pages.

### Documentation Sections
Organize content into logical sections using collections:

- `_tutorials/` - Step-by-step guides
- `_how-to/` - Problem-solving guides  
- `_reference/` - Technical reference
- `_explanation/` - Conceptual explanations

## Best Practices

1. **Use meaningful section names** in front matter for automatic navigation
2. **Include descriptions** in page front matter for better UX
3. **Add navigation links** between related pages
4. **Use Bootstrap classes** for consistent styling
5. **Test both navigation layouts** to ensure compatibility

## Browser Support

- Modern browsers (Chrome 80+, Firefox 75+, Safari 13+, Edge 80+)
- Mobile browsers (iOS Safari, Chrome Mobile)
- Progressive enhancement for older browsers

## Contributing

To contribute to the theme:

1. Test changes with both navigation layouts
2. Ensure mobile responsiveness
3. Verify dark/light theme compatibility
4. Update documentation as needed

## Troubleshooting

### Bundle Install Issues
```bash
bundle update
bundle install
```

### Jekyll Build Errors
Check for:
- Valid YAML front matter
- Correct file paths in `_config.yml`
- Missing required gems in Gemfile

### Navigation Not Working
Verify:
- `_config.yml` navigation structure
- Page front matter includes correct `section`
- JavaScript files are loading properly

## License

This theme is part of the SimpleChat project and follows the same licensing terms.