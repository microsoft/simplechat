# Document Upload Azure DI API Parameter Fix

**Version Implemented:** 0.229.001

## Issue Description

When uploading files to personal, group, or public workspaces, files were failing with the error:

```
Error: Processing failed: Error extracting content from [filename] with Azure DI: Session.request() got an unexpected keyword argument 'document'
```

Additionally, the system was incorrectly creating conversations and uploading files to new conversations instead of processing them in the intended workspace.

## Root Cause

The issue was in the `extract_content_with_azure_di` function in `functions_content.py`. The function was using an outdated parameter name `document=f` when calling the Azure Document Intelligence API's `begin_analyze_document` method.

### Problematic Code
```python
poller = document_intelligence_client.begin_analyze_document(
    model_id="prebuilt-read",
    document=f  # ❌ This parameter name is not accepted by newer Azure DI API
)
```

## Solution

Updated the Azure Document Intelligence API call to use the correct parameter format by passing the document as a positional argument instead of using the deprecated `document` keyword argument.

### Fixed Code
```python
poller = document_intelligence_client.begin_analyze_document(
    "prebuilt-read",
    f  # ✅ Pass document as positional argument
)
```

## Files Modified

1. **`functions_content.py`** - Fixed the Azure Document Intelligence API parameter usage
2. **`config.py`** - Updated version from "0.226.089" to "0.226.090"
3. **`functional_tests/test_document_upload_fix.py`** - Created test to validate the fix

## Testing

Created a functional test `test_document_upload_fix.py` that:
- Tests the Azure Document Intelligence API parameter fix
- Validates that the function no longer raises the "unexpected keyword argument 'document'" error
- Ensures document processing modules import correctly

## Impact

This fix resolves:
- ✅ File upload failures due to Azure DI API parameter issues
- ✅ Documents being incorrectly processed/routed
- ✅ Session.request() parameter conflicts
- ✅ Document processing workflow interruptions

## Additional Notes

- The fix maintains backward compatibility with the government cloud implementation that uses base64 encoding
- The solution follows the current Azure Document Intelligence SDK patterns
- No breaking changes to existing functionality
- Workspace upload functionality now works correctly for personal, group, and public workspaces

## Verification

To verify the fix is working:
1. Upload a PDF, DOCX, or image file to any workspace
2. Confirm the file processes without the "Session.request()" error
3. Verify the document appears in the correct workspace (not as a new conversation)
4. Run the functional test: `python3 functional_tests/test_document_upload_fix.py`
