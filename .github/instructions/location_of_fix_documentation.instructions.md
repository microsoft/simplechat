---
applyTo: '**'
---

# Fix Documentation Location

## Documentation Directory
All bug fixes and issue resolution documentation should be placed in:
```
..\docs\fixes\
```

## File Naming Convention
Use descriptive, uppercase names with underscores:
- `[ISSUE_NAME]_FIX.md` 
- Example: `TABULAR_DATA_CSV_STORAGE_FIX.md`
- Example: `CSV_COLUMN_CONSISTENCY_FIX.md`

## Required Documentation Structure
Each fix documentation file must include:

### 1. Header Information
- Fix title
- Issue description
- Root cause analysis
- Version implemented

### 2. Technical Details
- Files modified
- Code changes summary
- Testing approach
- Impact analysis

### 3. Validation
- Test results
- Before/after comparison
- User experience improvements

## Integration Process
When documenting a fix:
1. Create markdown file in `..\docs\fixes\`
2. Include current config.py version
3. Reference related functional tests
4. Update any relevant feature documentation if the fix affects existing features

## Cross-References
Fix documentation may reference:
- Related feature documentation in `..\docs\features\`
- Functional test files in `functional_tests\`
- Configuration changes in `config.py`