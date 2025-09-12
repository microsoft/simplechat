# Client-Side File Size Validation Implementation

## Overview
This implementation adds client-side file size pre-validation for all workspace types before files are uploaded to the server. This prevents large files from being uploaded only to fail during background processing, improving user experience and reducing server resource consumption.

## Changes Made

### 1. Template Changes

#### workspace.html
- **Location**: `application/single_app/templates/workspace.html`
- **Change**: Added `window.max_file_size_mb = {{ settings.max_file_size_mb | default(16) }};` to the JavaScript context
- **Purpose**: Makes the maximum file size limit available to client-side JavaScript

#### group_workspaces.html  
- **Location**: `application/single_app/templates/group_workspaces.html`
- **Change**: Added `window.max_file_size_mb = {{ settings.max_file_size_mb | default(16) }};` to the JavaScript context
- **Purpose**: Makes the maximum file size limit available to client-side JavaScript

#### public_workspaces.html
- **Location**: `application/single_app/templates/public_workspaces.html`
- **Change**: Added `window.max_file_size_mb = {{ settings.max_file_size_mb | default(16) }};` to the JavaScript context
- **Purpose**: Makes the maximum file size limit available to client-side JavaScript

### 2. JavaScript Function Changes

#### workspace-documents.js
- **Location**: `application/single_app/static/js/workspace/workspace-documents.js`
- **Function**: `uploadWorkspaceFiles(files)`
- **Change**: Added file size validation loop before upload begins
- **Validation Logic**:
  ```javascript
  const maxFileSizeMB = window.max_file_size_mb || 16;
  const maxFileSizeBytes = maxFileSizeMB * 1024 * 1024;
  
  for (const file of files) {
      if (file.size > maxFileSizeBytes) {
          const fileSizeMB = (file.size / (1024 * 1024)).toFixed(1);
          alert(`File "${file.name}" (${fileSizeMB} MB) exceeds the maximum allowed size of ${maxFileSizeMB} MB. Please select a smaller file.`);
          return;
      }
  }
  ```

#### group_workspaces.html (embedded JS)
- **Functions**: `uploadGroupFiles(files)` and `onGroupUploadClick()`
- **Change**: Added identical file size validation to both upload functions
- **Purpose**: Validates files for both auto-upload and manual upload scenarios

#### public_workspace.js
- **Location**: `application/single_app/static/js/public/public_workspace.js`
- **Function**: `onPublicUploadClick()`
- **Change**: Added file size validation before upload begins

### 3. Upload Flow Coverage

#### File Input Selection
All workspace types validate files when selected via file input and upload button is clicked.

#### Drag-and-Drop
All workspace types validate files when dropped onto upload areas:
- **Workspace**: Calls `uploadWorkspaceFiles()` which has validation
- **Group**: Calls `uploadGroupFiles()` which has validation  
- **Public**: Calls `onPublicUploadClick()` which has validation

## Benefits

### User Experience
- **Immediate Feedback**: Users get instant notification if files are too large
- **Prevent Wasted Time**: No waiting for upload completion only to get an error
- **Clear Error Messages**: Specific file names and sizes are shown in error messages

### Server Resources
- **Reduced Bandwidth**: Large files are not uploaded unnecessarily
- **Less Storage**: No temporary storage of oversized files
- **Improved Performance**: Backend processing isn't wasted on files that will be rejected

### Error Handling
- **Early Prevention**: Errors are caught before network transfer begins
- **Specific Messages**: Users know exactly which files are too large and by how much
- **Graceful Degradation**: Falls back to default 16MB limit if setting is unavailable

## Implementation Details

### Default Values
- All implementations use `window.max_file_size_mb || 16` to provide a 16MB fallback
- Template Jinja2 filter uses `{{ settings.max_file_size_mb | default(16) }}` for backend fallback

### Validation Logic
- File size is checked in bytes (`file.size` property)
- Maximum size is converted from MB to bytes for comparison
- Human-readable file sizes are displayed in MB with 1 decimal place
- Validation stops at first oversized file and shows specific error

### Integration Points
- Uses existing `settings.max_file_size_mb` configuration
- Leverages existing `sanitize_settings_for_user()` function
- Works with existing upload functions without breaking changes
- Compatible with existing drag-and-drop handlers

## Testing

### Manual Testing
1. Set `max_file_size_mb` to a low value (e.g., 5MB) in admin settings
2. Try uploading files larger than the limit in each workspace type
3. Verify error messages appear immediately without network upload
4. Confirm smaller files still upload successfully

### Verification Points
- File size validation occurs before XMLHttpRequest is created
- Error messages include file name, actual size, and limit
- Upload progress indicators are not shown for rejected files
- File input is not cleared for rejected uploads (allows user to select different files)

## Configuration

The file size limit is controlled by the `max_file_size_mb` setting in the admin configuration:
- **Location**: Admin Settings → Document Upload Settings
- **Default**: 16 MB (if not configured)
- **Backend**: Used in `functions_documents.py` for server-side validation
- **Frontend**: Now also used for client-side pre-validation

## Backward Compatibility

This implementation is fully backward compatible:
- Server-side validation remains as fallback
- No changes to existing API endpoints
- No changes to upload response handling
- Works with existing drag-and-drop functionality