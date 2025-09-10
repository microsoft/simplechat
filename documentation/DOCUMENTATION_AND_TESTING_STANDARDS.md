# Documentation and Testing Standards

## Overview
This document outlines the standardized approach for documenting fixes and features, along with version management for functional tests.

## Directory Structure

```
simplechat/
├── docs/
│   ├── fixes/           # Bug fix documentation
│   └── features/        # Feature documentation
├── application/single_app/
│   └── functional_tests/ # Functional test files
└── .github/instructions/ # AI coding guidelines
```

## Version Management

### Current Version
Always reference the current version from `config.py`:
```python
app.config['VERSION'] = "0.226.101"
```

### Version Updates
When implementing fixes or features:
1. Update version in `config.py`
2. Include version in functional test headers
3. Include version in documentation files

## Documentation Standards

### Fix Documentation
**Location**: `docs/fixes/`
**Naming**: `[ISSUE_NAME]_FIX.md`

**Required Sections**:
- Problem description and root cause
- Solution implementation details
- Files modified
- Testing validation
- Version information

**Example**: `TABULAR_DATA_CSV_STORAGE_FIX.md`

### Feature Documentation  
**Location**: `docs/features/`
**Naming**: `[FEATURE_NAME].md`

**Required Sections**:
- Feature overview and purpose
- Technical specifications
- Usage instructions
- Testing and validation
- Version information

## Functional Test Standards

### Header Format
```python
#!/usr/bin/env python3
"""
[Test description]
Version: [current config.py version]
Implemented in: [version when fix/feature was added]

[Detailed description of what the test validates]
"""
```

### Example
```python
#!/usr/bin/env python3
"""
Functional test for tabular data CSV storage optimization fix.
Version: 0.226.101
Implemented in: 0.226.099

This test ensures that when tabular data files (CSV, Excel) are uploaded to conversations,
they are stored in CSV format instead of HTML format to reduce storage costs and improve
LLM processing efficiency.
"""
```

## AI Instruction Files

### Purpose
Guide AI assistants on where to place documentation and how to structure it.

### Files
- `location_of_fix_documentation.instructions.md` - Fix documentation guidelines
- `location_of_feature_documentation.instructions.md` - Feature documentation guidelines  
- `include_config_version_in_functional_test_files.instructions.md` - Version management guidelines

## Benefits

### Traceability
- Clear version tracking for all changes
- Easy identification of when fixes/features were implemented
- Simplified debugging and rollback procedures

### Organization
- Standardized documentation locations
- Consistent file naming conventions
- Clear separation between fixes and features

### Quality Assurance
- Required test coverage for all changes
- Comprehensive documentation standards
- Version consistency across all files

## Usage Examples

### Creating a New Fix
1. Implement the fix and update `config.py` version
2. Create functional test with version header
3. Create documentation in `docs/fixes/[ISSUE_NAME]_FIX.md`
4. Include version information in all files

### Creating a New Feature
1. Implement the feature and update `config.py` version
2. Create functional test with version header
3. Create documentation in `docs/features/[FEATURE_NAME].md`
4. Include version information in all files

This standardized approach ensures consistency, traceability, and quality across the entire codebase.
