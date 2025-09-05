---
applyTo: '**'
---

# Version Management for Functional Tests and Documentation

## Required Version Inclusion

When creating functional tests and documentation for fixes or features, always include the current version from `config.py`:

### 1. Functional Test Files
All functional test files must include a comment header with:
- Current version from `app.config['VERSION']` in `config.py`
- Brief description of what the test validates
- Version when the fix/feature was implemented

Example format:
```python
#!/usr/bin/env python3
"""
Functional test for [feature/fix name].
Version: [current version from config.py]
Implemented in: [version when fix/feature was added]

This test ensures that [description of what is being tested].
"""
```

### 2. Documentation Files
All fix and feature documentation must include:
- Version number in the document title or metadata
- "Fixed/Implemented in version: **X.X.X**" section
- Reference to related config.py version updates

### 3. Version Update Process
When implementing fixes or features:
1. Update the version in `config.py`: `app.config['VERSION'] = "X.X.X"`
2. Include this version in functional test file headers
3. Include this version in documentation markdown files
4. Ensure consistency across all related files

### 4. Version Tracking Benefits
- Clear traceability of when fixes/features were implemented
- Easy identification of test coverage for specific versions
- Simplified debugging and rollback procedures
- Better release documentation and change tracking