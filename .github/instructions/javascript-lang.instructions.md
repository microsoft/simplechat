---
applyTo: '**/*.js'
---

# JavaScript Language Guide
  
- Files should start with a comment of the file name. Ex: `// functions_personal_agents.js`

- Imports should be grouped at the top of the document after the module docstring, unless otherwise indicated by the user or for performance reasons in which case the import should be as close as possible to the usage with a documented note as to why the import is not at the top of the file.

- Use 4 spaces per indentation level. No tabs.

- Code and definitions should occur after the imports block.

- Use camelCase for variable and function names. Ex: `myVariable`, `getUserData()`

- Use PascalCase for class names. Ex: `MyClass`

- Do not use display:none. Instead add and remove the d-none class when hiding or showing elements.

- Prefer inline html notifications or toast messages using Bootstrap alert classes over browser alert() calls.