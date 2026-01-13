# Vision Model Detection Expansion

**Version**: 0.229.089  
**Date**: November 21, 2025  
**Issue**: Multi-modal vision model detection was too restrictive

## Problem

The initial implementation of multi-modal vision analysis (v0.229.088) only detected models with "gpt-4o" or "vision" in their names. This was too restrictive based on Azure OpenAI's official documentation, which lists many more vision-capable model families:

- O-series reasoning models (o1, o1-preview, o1-mini, o3, o3-mini)
- GPT-5 series (all variants)
- GPT-4.1 series (all variants)
- GPT-4.5 (all variants)

Users deploying these newer models would not see them in the multi-modal vision dropdown, even though they support image analysis.

## Root Cause

The model filtering logic in `admin_settings.js` used a simple check:

```javascript
if (modelNameLower.includes('gpt-4o') || modelNameLower.includes('vision')) {
  // Add to dropdown
}
```

This missed:
- O-series models (o1, o1-preview, o3-mini, etc.)
- GPT-5 series models
- GPT-4.1 and GPT-4.5 models

## Solution

### Code Changes

Updated `admin_settings.js` to include comprehensive vision model detection:

```javascript
const isVisionCapable = 
  modelNameLower.includes('vision') ||           // gpt-4-vision, gpt-4-turbo-vision
  modelNameLower.includes('gpt-4o') ||           // gpt-4o, gpt-4o-mini
  modelNameLower.includes('gpt-4.1') ||          // gpt-4.1 series
  modelNameLower.includes('gpt-4.5') ||          // gpt-4.5
  modelNameLower.includes('gpt-5') ||            // gpt-5 series
  modelNameLower.match(/^o\d+/) ||               // o1, o3, etc. (o-series)
  modelNameLower.includes('o1-') ||              // o1-preview, o1-mini
  modelNameLower.includes('o3-');                // o3-mini, etc.
```

### Detection Patterns

The updated logic detects:

1. **Legacy Vision Models**: Any model containing "vision"
   - `gpt-4-vision-preview`
   - `gpt-4-turbo-vision`
   - `gpt-4-vision`

2. **GPT-4o Series**: Models containing "gpt-4o"
   - `gpt-4o`
   - `gpt-4o-mini`

3. **GPT-4.1 Series**: Models containing "gpt-4.1"
   - `gpt-4.1`
   - `gpt-4.1-preview`
   - Any GPT-4.1 variants

4. **GPT-4.5**: Models containing "gpt-4.5"
   - `gpt-4.5`
   - Any GPT-4.5 variants

5. **GPT-5 Series**: Models containing "gpt-5"
   - All GPT-5 variants (when available)

6. **O-Series Reasoning Models**: Multiple patterns
   - `^o\d+` regex: Matches o1, o2, o3, etc. at start of name
   - `o1-`: Matches o1-preview, o1-mini
   - `o3-`: Matches o3-mini, o3-preview

## Documentation Updates

Updated `MULTIMODAL_VISION_ANALYSIS.md` with:

1. **Expanded Model List**: Complete list of supported models per Azure OpenAI docs
2. **Model Families**: Organized by series (GPT-4o, o-series, GPT-5, GPT-4.5, GPT-4.1)
3. **Detection Logic**: Explained how models are automatically detected
4. **Troubleshooting**: Added comprehensive model detection guidance
5. **Version History**: Documented changes between v0.229.088 and v0.229.089

## Testing

### Validated Model Patterns

**Should be detected** ✅:
- `gpt-4o`, `gpt-4o-mini`
- `o1`, `o1-preview`, `o1-mini`
- `o3`, `o3-mini`
- `gpt-5`, `gpt-5-turbo`
- `gpt-4.5`, `gpt-4.5-preview`
- `gpt-4.1`, `gpt-4.1-turbo`
- `gpt-4-vision-preview`, `gpt-4-turbo-vision`

**Should NOT be detected** ❌:
- `gpt-4` (no vision suffix)
- `gpt-3.5-turbo`
- `text-embedding-ada-002`
- `gpt-35-turbo` (3.5 = no vision)

### Test Cases

1. **GPT-4o Detection**:
   ```javascript
   'gpt-4o'.includes('gpt-4o') // true ✅
   'gpt-4o-mini'.includes('gpt-4o') // true ✅
   ```

2. **O-Series Detection**:
   ```javascript
   'o1'.match(/^o\d+/) // true ✅
   'o1-preview'.includes('o1-') // true ✅
   'o3-mini'.includes('o3-') // true ✅
   ```

3. **GPT-5 Detection**:
   ```javascript
   'gpt-5'.includes('gpt-5') // true ✅
   'gpt-5-turbo'.includes('gpt-5') // true ✅
   ```

4. **GPT-4.1 & 4.5 Detection**:
   ```javascript
   'gpt-4.1'.includes('gpt-4.1') // true ✅
   'gpt-4.5'.includes('gpt-4.5') // true ✅
   ```

5. **Vision Models Detection**:
   ```javascript
   'gpt-4-vision-preview'.includes('vision') // true ✅
   'gpt-4-turbo-vision'.includes('vision') // true ✅
   ```

6. **Exclusions** (should NOT match):
   ```javascript
   'gpt-4'.includes('gpt-4o') // false ✅ (correctly excluded)
   'gpt-35-turbo'.match(/^o\d+/) // false ✅ (correctly excluded)
   ```

## Benefits

1. **Future-Proof**: Automatically supports new models in existing families
2. **Comprehensive**: Covers all vision-capable models per Azure OpenAI docs
3. **User-Friendly**: Users see all their vision models automatically
4. **Accurate**: Doesn't show non-vision models like gpt-3.5 or gpt-4

## Impact

### User Experience
- **Before**: Only GPT-4o and legacy vision models appeared
- **After**: All vision-capable models appear (o-series, GPT-5, GPT-4.1, GPT-4.5)

### Technical
- No breaking changes
- Backward compatible with existing deployments
- No database schema changes required
- No API changes required

## Files Modified

1. **admin_settings.js** - Expanded vision model detection logic
2. **config.py** - Updated version to 0.229.089
3. **MULTIMODAL_VISION_ANALYSIS.md** - Updated documentation with complete model list
4. **VISION_MODEL_DETECTION_EXPANSION.md** - This fix documentation

## References

- [Azure OpenAI Vision Documentation](https://learn.microsoft.com/azure/ai-services/openai/how-to/gpt-with-vision)
- [Vision-Enabled Models List](https://learn.microsoft.com/azure/ai-services/openai/concepts/models#vision-enabled-models)
- Original Issue: User feedback about limited model detection

## Related Features

- Multi-Modal Vision Analysis (v0.229.088)
- Admin Settings Model Selection
- GPT Configuration Management
