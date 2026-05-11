# Vision Model Parameter Fix for GPT-5 and O-Series Models

**Version**: 0.233.201  
**Fixed in**: 0.233.201  
**Issue**: GPT-5 and o-series models failed vision analysis tests with "Unsupported parameter: 'max_tokens'" error

---

## Problem

When testing Multi-Modal Vision Analysis with GPT-5 models (e.g., `gpt-5-nano`) or o-series models (e.g., `o1`, `o3`), the test would fail with:

```
Vision test failed: Error code: 400 - {'error': {'message': 
"Unsupported parameter: 'max_tokens' is not supported with this model. 
Use 'max_completion_tokens' instead.", 'type': 'invalid_request_error', 
'param': 'max_tokens', 'code': 'unsupported_parameter'}}
```

### Root Cause

Both the vision test endpoint (`route_backend_settings.py`) and the image analysis function (`functions_documents.py`) were using the `max_tokens` parameter unconditionally:

```python
response = gpt_client.chat.completions.create(
    model=vision_model,
    messages=[...],
    max_tokens=50  # ❌ Not supported by o-series and gpt-5 models
)
```

However, **o-series reasoning models** (o1, o3, etc.) and **gpt-5 models** require the `max_completion_tokens` parameter instead of `max_tokens`.

---

## Solution

### Dynamic Parameter Selection

Implemented model-aware parameter selection in both vision test and vision analysis functions:

```python
# Determine which token parameter to use based on model type
vision_model_lower = vision_model.lower()
api_params = {
    "model": vision_model,
    "messages": [...]
}

# Use max_completion_tokens for o-series and gpt-5 models, max_tokens for others
if ('o1' in vision_model_lower or 'o3' in vision_model_lower or 'gpt-5' in vision_model_lower):
    api_params["max_completion_tokens"] = 1000
else:
    api_params["max_tokens"] = 1000

response = gpt_client.chat.completions.create(**api_params)
```

### Detection Logic

**Uses `max_completion_tokens`**:
- All o1 models: `o1`, `o1-preview`, `o1-mini`
- All o3 models: `o3`, `o3-mini`, `o3-preview`
- All gpt-5 models: `gpt-5`, `gpt-5-turbo`, `gpt-5-nano`

**Uses `max_tokens`** (standard):
- gpt-4o models: `gpt-4o`, `gpt-4o-mini`
- Legacy vision models: `gpt-4-vision-preview`, `gpt-4-turbo-vision`
- GPT-4.1 and GPT-4.5 series

**Case-Insensitive**: Detection works regardless of model name casing (`GPT-5-NANO`, `gpt-5-nano`, `O1-PREVIEW`, etc.)

---

## Files Modified

### 1. `route_backend_settings.py`

**Function**: `_test_multimodal_vision_connection()`

**Changes**:
- Added model type detection
- Dynamic API parameter building
- Conditional use of `max_completion_tokens` vs `max_tokens`
- Removed static `max_tokens=50` parameter

**Line**: ~299-370

### 2. `functions_documents.py`

**Function**: `analyze_image_with_vision_model()`

**Changes**:
- Added model type detection
- Dynamic API parameter building
- Conditional use of `max_completion_tokens` vs `max_tokens`
- Removed static `max_tokens=1000` parameter

**Line**: ~2974-3075

### 3. `config.py`

**Version Update**: `0.233.200` → `0.233.201`

---

## Testing

### Functional Test

Created `functional_tests/test_vision_model_parameter_fix.py` to validate:

1. **Vision Test Parameter Handling**
   - Dynamic parameter building
   - Model detection for o-series and gpt-5
   - Correct parameter selection
   - Old static parameter removed

2. **Vision Analysis Parameter Handling**
   - Dynamic parameter building
   - Model detection for o-series and gpt-5
   - Correct parameter selection
   - Old static parameter removed

3. **Model Detection Coverage**
   - 16 test cases covering all model families
   - Case-insensitive detection
   - Correct parameter selection for each model type

### Running the Test

```bash
cd functional_tests
python test_vision_model_parameter_fix.py
```

**Expected Output**:
```
🚀 Testing Multi-Modal Vision Analysis Parameter Fix
=================================================================
🔍 Testing vision test parameter handling...
   ✅ Vision test uses dynamic API parameter building
   ✅ Model detection for o-series and gpt-5
   ✅ max_completion_tokens for o-series/gpt-5 models
   ✅ max_tokens for other models
   ✅ Old static parameter removed
✅ Vision test parameter handling is correct!

🔍 Testing vision analysis parameter handling...
   ✅ Vision analysis uses dynamic API parameter building
   ...
✅ All vision parameter fix tests passed!
```

---

## Impact

### Before Fix
- ❌ GPT-5 models: Vision test **failed** with parameter error
- ❌ o1/o3 models: Vision test **failed** with parameter error
- ✅ GPT-4o models: Vision test worked
- ✅ Legacy vision models: Vision test worked

### After Fix
- ✅ GPT-5 models: Vision test **passes** with `max_completion_tokens`
- ✅ o1/o3 models: Vision test **passes** with `max_completion_tokens`
- ✅ GPT-4o models: Vision test still works with `max_tokens`
- ✅ Legacy vision models: Vision test still works with `max_tokens`

### User Experience
- Users can now select and test GPT-5 models for vision analysis
- Users can now select and test o-series models for vision analysis
- No breaking changes for existing deployments
- Automatic parameter selection based on model type

---

## Technical Details

### API Parameter Differences

**Standard Vision Models** (GPT-4o, GPT-4 Vision):
```python
{
    "model": "gpt-4o",
    "messages": [...],
    "max_tokens": 1000,  # ✅ Supported
    "temperature": 0.7   # ✅ Supported
}
```

**Reasoning Models** (o1, o3, GPT-5):
```python
{
    "model": "o1-preview",
    "messages": [...],
    "max_completion_tokens": 1000,  # ✅ Required instead of max_tokens
    # temperature NOT supported for reasoning models
}
```

### Why Different Parameters?

Reasoning models (o-series, GPT-5) use a different API contract:
- **`max_completion_tokens`**: Limits the completion length only
- **No `max_tokens`**: This parameter is not supported
- **No `temperature`**: Reasoning models don't support temperature adjustment

Standard vision models use the traditional parameters:
- **`max_tokens`**: Limits both prompt and completion tokens combined
- **`temperature`**: Controls randomness in responses

---

## Related Features

- **Multi-Modal Vision Analysis** (v0.229.088)
- **Vision Model Detection Expansion** (v0.229.089)
- **Document Intelligence OCR Integration**
- **Enhanced Citations with Vision Data**

---

## References

- [Azure OpenAI API - Chat Completions](https://learn.microsoft.com/azure/ai-services/openai/reference)
- [GPT-4o Vision Documentation](https://learn.microsoft.com/azure/ai-services/openai/how-to/gpt-with-vision)
- [O-Series Reasoning Models](https://learn.microsoft.com/azure/ai-services/openai/concepts/models#o-series-models)

---

## Troubleshooting

### If Vision Test Still Fails

1. **Check Model Name**: Ensure model deployment name matches expected patterns
2. **Check API Version**: Use `2024-02-15-preview` or later for vision support
3. **Check Region Availability**: Not all models are available in all regions
4. **Check Deployment Status**: Ensure model is successfully deployed in Azure

### If Wrong Parameter Used

The detection logic checks for:
- `'o1'` in model name (case-insensitive)
- `'o3'` in model name (case-insensitive)  
- `'gpt-5'` in model name (case-insensitive)

If your model name doesn't match these patterns but needs `max_completion_tokens`, contact support or adjust the detection logic.

---

## Version History

- **v0.233.201**: Fixed parameter selection for GPT-5 and o-series models
- **v0.229.089**: Expanded vision model detection to include GPT-5 and o-series
- **v0.229.088**: Initial Multi-Modal Vision Analysis feature
