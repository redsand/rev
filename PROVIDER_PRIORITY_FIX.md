# Provider Priority Fix

## Problem Fixed

Previously, the system could mix providers (Ollama and Gemini) even when Gemini was configured. This is now fixed - **only ONE provider is used exclusively**.

## Solution

Added intelligent provider prioritization based on configured credentials:

### Priority Order (Automatic Detection)
1. **Explicit Override** - `REV_LLM_PROVIDER` environment variable (if set)
2. **Gemini** - If `GEMINI_API_KEY` is configured
3. **Anthropic** - If `ANTHROPIC_API_KEY` is configured
4. **OpenAI** - If `OPENAI_API_KEY` is configured
5. **Ollama** - Default (always available)

### Key Changes

**File: `rev/config.py`**
- Added `_get_primary_provider_and_model()` function
- Ensures provider and model are **always aligned**
- Respects explicit `REV_LLM_PROVIDER` override
- Automatically detects based on API keys present

## Behavior Examples

### Example 1: Only Ollama Configured (Default)
```bash
$ python -c "from rev import config; print(f'Provider: {config.LLM_PROVIDER}, Model: {config.EXECUTION_MODEL}')"
Provider: ollama, Model: qwen3-coder:480b-cloud
```

### Example 2: Gemini API Key Set
```bash
$ GEMINI_API_KEY=your_key python -c "from rev import config; print(f'Provider: {config.LLM_PROVIDER}, Model: {config.EXECUTION_MODEL}')"
Provider: gemini, Model: gemini-2.0-flash-exp
```

### Example 3: Multiple APIs Configured (Gemini Wins)
```bash
$ GEMINI_API_KEY=gem_key ANTHROPIC_API_KEY=ant_key python -c "from rev import config; print(f'Provider: {config.LLM_PROVIDER}, Model: {config.EXECUTION_MODEL}')"
Provider: gemini, Model: gemini-2.0-flash-exp
```

### Example 4: Explicit Provider Override
```bash
$ GEMINI_API_KEY=gem_key REV_LLM_PROVIDER=anthropic python -c "from rev import config; print(f'Provider: {config.LLM_PROVIDER}, Model: {config.EXECUTION_MODEL}')"
Provider: anthropic, Model: claude-3-5-sonnet-20241022
```

## Configuration

### How to Use Gemini Exclusively

Set your Gemini credentials:
```bash
export GEMINI_API_KEY=your_api_key
export GEMINI_MODEL=gemini-2.0-flash-exp  # optional, this is the default
```

Run rev normally - it will **always** use Gemini:
```bash
rev "your task"
```

### How to Override Provider

If you have multiple providers configured and want to use a specific one:
```bash
export REV_LLM_PROVIDER=anthropic
rev "your task"
```

### Per-Phase Provider Control

You can also set different providers for different execution phases:
```bash
export REV_EXECUTION_PROVIDER=gemini
export REV_PLANNING_PROVIDER=anthropic
export REV_RESEARCH_PROVIDER=openai
rev "your task"
```

## Test Results

All provider priority scenarios tested and passing:

| Scenario | Expected | Actual | Status |
|----------|----------|--------|--------|
| No credentials (defaults) | ollama | ollama | ✓ |
| Gemini only | gemini | gemini | ✓ |
| Gemini + Anthropic | gemini | gemini | ✓ |
| Anthropic only | anthropic | anthropic | ✓ |
| OpenAI only | openai | openai | ✓ |
| Gemini + explicit OpenAI | openai | openai | ✓ |

## No More Mixing

**Before:** System could use Gemini for one phase and Ollama for another
**After:** Single provider per phase (all phases use same provider by default)

## Environment Variables Reference

```bash
# Provider selection (highest priority)
REV_LLM_PROVIDER=gemini|anthropic|openai|ollama

# Per-phase provider overrides
REV_EXECUTION_PROVIDER=gemini
REV_PLANNING_PROVIDER=anthropic
REV_RESEARCH_PROVIDER=openai

# API Keys (trigger automatic provider selection)
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...

# Model selection (uses provider defaults if not set)
GEMINI_MODEL=gemini-2.0-flash-exp
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
OPENAI_MODEL=gpt-4-turbo-preview
OLLAMA_MODEL=qwen3-coder:480b-cloud
```

## Summary

✅ No more provider mixing
✅ Gemini prioritized when API key is present
✅ Provider and model always aligned
✅ Respects explicit overrides
✅ Backward compatible

**You can now safely use Gemini (or any provider) exclusively!**
