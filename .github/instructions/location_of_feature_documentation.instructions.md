---
applyTo: '**'
---

# Feature Documentation Location

## Documentation Directory
All new feature documentation should be placed in:
```
..\docs\features\
```

## File Naming Convention
Use descriptive, uppercase names with underscores:
- `[FEATURE_NAME].md`
- Example: `AGENT_ORCHESTRATION.md`
- Example: `FILE_UPLOAD_SYSTEM.md`

## Required Documentation Structure
Each feature documentation file must include:

### 1. Header Information
- Feature title
- Overview and purpose
- Version implemented
- Dependencies

### 2. Technical Specifications
- Architecture overview
- API endpoints (if applicable)
- Configuration options
- File structure

### 3. Usage Instructions
- How to enable/configure
- User workflows
- Examples and screenshots
- Integration points

### 4. Testing and Validation
- Test coverage
- Performance considerations
- Known limitations

## Integration Process
When documenting a new feature:
1. Create markdown file in `..\docs\features\`
2. Include current config.py version
3. Reference related functional tests
4. Link to any fix documentation if the feature required bug fixes

## Cross-References
Feature documentation may reference:
- Related fix documentation in `..\docs\fixes\`
- Functional test files in `functional_tests\`
- Configuration changes in `config.py`
- Other features in `..\docs\features\`

## Maintenance
Keep feature documentation updated when:
- Feature capabilities are enhanced
- Configuration options change
- Integration methods are modified
- Related fixes impact feature behavior