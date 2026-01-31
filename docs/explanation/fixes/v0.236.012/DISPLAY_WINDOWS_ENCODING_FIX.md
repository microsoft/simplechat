# Windows Unicode Encoding Issue Report

## Issue Summary

**Purpose:** This document reports a critical Unicode encoding issue on Windows and provides recommended solutions.

This fix addresses a critical cross-platform compatibility issue where the application fails on Windows when processing or displaying Unicode characters beyond the Western European character set. The issue manifests in multiple areas including video transcript processing, chat history display, and any logging or output containing emojis, special symbols, or international characters.

### Broader Context

Python applications running on Windows face a fundamental encoding mismatch:
- **Windows Default:** Python uses `cp1252` (Windows-1252) encoding for stdout/stderr, which only supports Western European characters
- **Modern Web Applications:** Use UTF-8 encoding universally for international text, emojis, and special symbols
- **Azure Services:** Return data in UTF-8 format (Video Indexer transcripts, AI responses, user-generated content)

This mismatch causes the application to crash whenever it attempts to log, print, or display Unicode characters that exist outside the limited `cp1252` character set.

### Impact Scope

This fix resolves Unicode encoding errors in:
- ✅ **Video transcripts** with IPA phonetic symbols (e.g., ʈ U+02C8)
- ✅ **Chat messages** containing emojis (e.g., ✅ U+2705, 🔍 U+1F50D)
- ✅ **User-generated content** with international characters (Chinese, Arabic, Hindi, etc.)
- ✅ **Agent responses** with formatting characters and symbols
- ✅ **Debug logging** across the entire application
- ✅ **Error messages** and stack traces containing Unicode

## Common Error Messages

### Video Processing
```
Error: Processing failed: 'charmap' codec can't encode character '\u02c8' in position 228: character maps to <undefined>
```

### Chat History Display
```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2705' in position 156: character maps to <undefined>
```

### General Pattern
```
UnicodeEncodeError: 'charmap' codec can't encode character '\uXXXX'
```

## Environment

- **Platform:** Windows 10/11 (Issue does not occur on Linux/macOS)
- **Python Version:** 3.x
- **Default stdout encoding:** `cp1252` (charmap) on Windows
- **Required encoding:** `UTF-8` for modern web applications
- **Components Affected:** All areas of the application that output text to console/logs
- **Fixed in Version:** 0.236.013 (function-level), 0.236.014 (global fix)

## Root Cause

### The Windows Encoding Problem

**Core Issue:** Python on Windows defaults to `cp1252` encoding for stdout/stderr, while modern web applications and cloud services universally use UTF-8.

### Technical Details

1. **Platform Encoding Defaults:**
   - **Windows:** `cp1252` (Code Page 1252) - supports only 256 characters (Western European)
   - **Linux/macOS:** `UTF-8` - supports 1,112,064 characters (all Unicode)
   - **Web/Cloud Services:** UTF-8 standard for all modern APIs

2. **Why This Causes Crashes:**
   - Azure services (Video Indexer, OpenAI, etc.) return UTF-8 encoded data
   - Application processes this data correctly in memory
   - When Python attempts to `print()` or log this data on Windows:
     - Python tries to encode Unicode → `cp1252`
     - Characters outside `cp1252` range (emojis, IPA symbols, etc.) → encoding fails
     - Python raises `UnicodeEncodeError` and crashes

3. **Common Unicode Characters That Fail on Windows:**
   - **IPA Phonetic Symbols:** ʈ (U+02C8), ə (U+0259), ɑ (U+0251) - common in Video Indexer transcripts
   - **Emojis:** ✅ (U+2705), 🔍 (U+1F50D), 💬 (U+1F4AC) - used in chat and UI
   - **Box Drawing:** ─ (U+2500), │ (U+2502), ┌ (U+250C) - used in tables and formatting
   - **International Text:** Chinese, Arabic, Hindi, Emoji flags, etc.

4. **Example Failure Points:**
   - Video transcript logging: `print(insights_json, flush=True)`
   - Chat history display: `print(f"Messages: {chat_data}")`
   - Agent responses with emojis
   - Debug logging throughout the application

5. **Platform-specific behavior:**
   - ✅ **Linux/macOS:** Default UTF-8 encoding → handles all Unicode → **works perfectly**
   - ❌ **Windows:** Default cp1252 encoding → limited character set → **crashes on Unicode**

## Steps to Reproduce

### Video Processing Scenario
1. Deploy application on Windows
2. Upload a video file to group workspace that contains speech
3. Wait for Video Indexer to process the video
4. Transcript contains Unicode phonetic characters (common in pronunciation guides, non-English speech)
5. Application crashes with `UnicodeEncodeError` when logging transcript

### Chat History Scenario
1. Deploy application on Windows
2. Use chat feature with messages containing emojis or special characters
3. Access chat history or conversation details
4. Application crashes when attempting to display messages with Unicode characters

### General Pattern
Any operation that logs, prints, or displays Unicode characters beyond ASCII on Windows will trigger the error.

## Expected Behavior

- Video should upload successfully
- Transcript data should be logged to console for debugging
- Unicode characters should be displayed or safely handled
- Processing should complete and save video chunks to search index

## Actual Behavior

- Video upload fails with encoding error
- Processing stops at the JSON logging stage
- Video is not indexed for chat/search
- Error appears in UI: `"Error: Processing failed: 'charmap' codec can't encode character..."`

## Impact

- **Severity:** High - Application crashes on Windows for common operations
- **Frequency:** Occurs whenever Unicode characters appear in logs/output on Windows
- **Affected Areas:**
  - Video processing and transcript logging
  - Chat history with emojis or international text
  - Agent responses with Unicode formatting
  - Debug logging across entire application
  - Error messages and stack traces
- **Affected Users:** All Windows deployments (Linux/macOS unaffected)
- **Workaround:** None (requires code change)
- **Data Loss:** 
  - Videos not indexed for search
  - Chat functionality breaks on Unicode content
  - Application state inconsistent due to crashes

## Recommended Fix Implementation

**Note:** The following are recommended solutions to resolve this Unicode encoding issue on Windows.

### Global Fix (Recommended - Version 0.236.014)

**File:** `app.py`  
**Location:** Top of file (before any imports or print statements)  
**Lines:** 7-21

Add these lines at the very beginning of `app.py` to fix encoding for the entire application:

```python
# Fix Windows encoding issue - configure UTF-8 BEFORE any print statements or imports
import sys
if sys.platform == 'win32':
    # For Python 3.7+
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # For Python < 3.7, use codecs module
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
```

**Benefits:**
- ✅ Fixes Unicode errors throughout the entire application
- ✅ Handles video transcripts with phonetic symbols (e.g., ʈ U+02C8)
- ✅ Handles emojis in chat history (e.g., ✅ U+2705)
- ✅ One-time fix at startup rather than per-function
- ✅ Compatible with Python 3.6+ through fallback mechanism

### Function-Level Fix (Alternative)

**File:** `functions_documents.py`  
**Function:** `process_video_document()`  
**Lines:** 334-341

If you prefer a more targeted fix, add these lines at the beginning of the function:

```python
# Fix Windows encoding issue with Unicode characters in video transcripts
import sys
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python < 3.7 doesn't have reconfigure
        pass
```

**Note:** The global fix is recommended as it prevents Unicode encoding errors across the entire application, not just video processing.

---

## Important Considerations and Best Practices

### ⚠️ What This Fix Does (and Doesn't) Cover

**✅ What the code fix handles:**
- Console output via `print()` statements
- Application logging to stdout/stderr
- Unhandled exception tracebacks
- Debug output during development

**❌ What this fix does NOT cover:**
- File I/O operations - you must still explicitly specify encoding
- Database operations (already handled by database drivers)
- HTTP/API responses (handled by Flask/web frameworks)

**Important:** When writing to files, always specify UTF-8 encoding explicitly:

```python
# ❌ WRONG - still uses cp1252 on Windows
with open("log.txt", "w") as f:
    f.write(data)

# ✅ CORRECT - explicitly use UTF-8
with open("log.txt", "w", encoding="utf-8") as f:
    f.write(data)
```

---

### 🥇 Preferred Solution: Environment-Level UTF-8 (Python 3.7+)

**Best approach if you control the deployment environment:**

Set the `PYTHONUTF8` environment variable to enable UTF-8 mode globally:

**Windows PowerShell:**
```powershell
$env:PYTHONUTF8 = "1"
```

**Windows CMD:**
```cmd
set PYTHONUTF8=1
```

**Permanently (Windows):**
```powershell
setx PYTHONUTF8 1
```

**Linux/macOS (.bashrc or .zshrc):**
```bash
export PYTHONUTF8=1
```

**Docker/Container:**
```dockerfile
ENV PYTHONUTF8=1
```

**Azure App Service (Application Settings):**
- Add application setting: `PYTHONUTF8` = `1`

**Benefits:**
- ✅ Affects all Python encoding operations (console, files, etc.)
- ✅ No code changes required
- ✅ Officially recommended by Python
- ✅ Works for all Python scripts in the environment
- ✅ Cleaner and more maintainable than code-level fixes

---

### 🔧 Alternative: More Robust Code Implementation

For better error handling and broader compatibility, use this enhanced version:

```python
# Fix Windows encoding issue - configure UTF-8 BEFORE any print statements or imports
import sys

def force_utf8_encoding():
    """Force UTF-8 encoding for stdout/stderr on Windows."""
    if sys.platform == 'win32':
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                try:
                    stream.reconfigure(encoding='utf-8')
                except (AttributeError, OSError):
                    # Fallback for Python < 3.7 or when stream doesn't support reconfigure
                    try:
                        import codecs
                        if stream == sys.stdout:
                            sys.stdout = codecs.getwriter('utf-8')(stream.buffer, 'strict')
                        elif stream == sys.stderr:
                            sys.stderr = codecs.getwriter('utf-8')(stream.buffer, 'strict')
                    except Exception:
                        # Silently fail if we can't reconfigure
                        pass

force_utf8_encoding()
```

**Advantages of this version:**
- ✅ Handles None streams (redirected output)
- ✅ More defensive error handling
- ✅ Works when streams are redirected
- ✅ Gracefully degrades if reconfiguration fails

---

### 📋 Recommended Approach (Ranked)

1. **🥇 Best:** Set `PYTHONUTF8=1` environment variable
   - Use when you control the deployment environment
   - Cleanest and most comprehensive solution

2. **🥈 Very Good:** System-wide UTF-8 (Windows 11+)
   - Enable "Use Unicode UTF-8 for worldwide language support" in Windows settings
   - System-wide fix but requires reboot
   - May affect legacy applications

3. **🥉 Good:** Code-level fix (current approach)
   - Use when you can't control the environment
   - Essential for distributed libraries/applications
   - Works but only fixes console output

---

### ✅ Validation and Testing

After applying any fix, validate it works:

```python
# Test script - save as test_encoding.py
import sys

print(f"Platform: {sys.platform}")
print(f"stdout encoding: {sys.stdout.encoding}")
print(f"stderr encoding: {sys.stderr.encoding}")
print("\nTesting Unicode characters:")
print("IPA Phonetic: ʈ ə ɑ")
print("Emojis: ✅ 🔍 💬")
print("Box Drawing: ─ │ ┌")
print("International: 你好 مرحبا नमस्ते")
```

Expected output on Windows after fix:
```
Platform: win32
stdout encoding: utf-8
stderr encoding: utf-8

Testing Unicode characters:
IPA Phonetic: ʈ ə ɑ
Emojis: ✅ 🔍 💬
Box Drawing: ─ │ ┌
International: 你好 مرحبا नमस्ते
```

---

### 🎯 Summary

✅ **The code fix is valid and effective** for console output
✅ **It solves the immediate Unicode logging crashes**
⚠️ **It should be paired with `PYTHONUTF8=1` when possible**
⚠️ **Still specify `encoding="utf-8"` for all file operations**
⭐ **Best practice: Use environment variable for comprehensive solution**