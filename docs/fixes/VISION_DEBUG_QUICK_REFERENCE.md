# Vision Analysis Debug Log Quick Reference

## Key Indicators to Check

### ✅ GPT-4o Working (Expected Output)
```
[VISION_ANALYSIS] Vision model selected: gpt-4o
[VISION_ANALYSIS] Uses max_completion_tokens: False
[VISION_ANALYSIS] Token parameter: max_tokens = 1000
[VISION_ANALYSIS] Starts with JSON bracket: True
[VISION_ANALYSIS] ✅ Successfully parsed JSON response!
[VISION_ANALYSIS] JSON keys: ['description', 'objects', 'text', 'analysis']
```

### ❌ GPT-5 Problem (What You're Seeing)
```
[VISION_ANALYSIS] Vision model selected: gpt-5
[VISION_ANALYSIS] Uses max_completion_tokens: True
[VISION_ANALYSIS] Token parameter: max_completion_tokens = 1000
[VISION_ANALYSIS] Starts with JSON bracket: False  ← PROBLEM HERE
[VISION_ANALYSIS] ❌ JSON parsing failed!
[VISION_ANALYSIS] Error message: Expecting value: line 1 column 1 (char 0)
[VISION_ANALYSIS] Content that failed to parse: The image is a stylized promotional graphic...
```

## What to Look For in Logs

### 1. Parameter Selection (Should be TRUE for GPT-5)
```
Uses max_completion_tokens: True  ← Must be True for gpt-5
```

### 2. Response Format (CRITICAL)
```
Starts with JSON bracket: False  ← This is why it's failing!
```

If this is `False`, GPT-5 is returning plain text instead of JSON.

### 3. Response Content Preview
```
First 500 chars: The image is a stylized promotional graphic for the 149th Preakness Stakes...
```

If this looks like natural language description (not JSON), that's the problem.

### 4. Parse Error Details
```
Error type: JSONDecodeError
Error message: Expecting value: line 1 column 1 (char 0)
```

This confirms the response doesn't start with JSON.

## Likely Root Cause

**GPT-5 reasoning models might not follow JSON format instructions the same way GPT-4o does.**

Possible reasons:
1. GPT-5 interprets the vision prompt differently
2. Reasoning models prioritize natural language over structured output
3. Model needs explicit JSON mode parameter (not currently set)

## Recommended Fix

Try adding `response_format` parameter for GPT-5:

```python
if uses_completion_tokens:
    api_params["max_completion_tokens"] = 1000
    # Try adding JSON mode for GPT-5/o-series
    api_params["response_format"] = {"type": "json_object"}
```

Or modify the prompt to be more explicit:

```python
"You MUST respond with valid JSON only. Do not include any text outside the JSON structure..."
```
