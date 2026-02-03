---
applyTo: '**/*.html'
---

# HTML Language Guide

- Use 4 spaces per indentation level. No tabs.

- Use double quotes for all HTML attributes. Ex: `<div class="my-class">`

- Self-closing tags should include the trailing slash. Ex: `<img src="image.png" />`

- Use semantic HTML5 elements where appropriate. Ex: `<header>`, `<nav>`, `<main>`, `<footer>`

- Include ARIA roles and attributes to enhance accessibility. Ex: `role="button"`, `aria-label="Close"`

- Keep inline styles to a minimum; prefer CSS classes for styling.

- Use comments to separate major sections of the HTML document. Ex: `<!-- Header Section -->`

- Use Jinja templating syntax consistently for dynamic content, settings, and configuration. Ex: `{{ variable }}`, `{% if condition %}`

- Use bootstrap classes for layout, styling consistency, and data presentation. Ex: `class="container"`, `class="row"`, `class="col-md-6"`, `data-bs-toggle="modal"`