# Flexibility Improvements for rev

This document summarizes the changes made to make rev more flexible and less restrictive while maintaining safety and intelligence.

## Problem Statement
rev was designed with strict verification, uncertainty detection, and loop guards that made it overly restrictive for exploratory work. Compared to Claude Code's flexibility, rev was interrupting legitimate research, blocking reasonable plans, and limiting AI's ability to deeply understand complex codebases.

## Changes Implemented

### 1. Enhanced Research Capabilities
- **Increased file reading limits**: `MAX_READ_FILE_PER_TASK` from 999 → 9999
- **Increased search limits**: `MAX_SEARCH_CODE_PER_TASK` from 999 → 9999
- **Reason**: Research requires extensive file reading without artificial limits

### 2. Reduced Uncertainty Sensitivity
- **Uncertainty threshold**: `UNCERTAINTY_THRESHOLD` from 5 → 8
- **Auto-skip threshold**: `UNCERTAINTY_AUTO_SKIP_THRESHOLD` from 10 → 15
- **Research protection**: Uncertainty scores reduced by 40% for research tasks
- **Reason**: Research involves natural uncertainty; don't interrupt prematurely

### 3. More Lenient Review Agent
- **Default strictness**: From "moderate" → "lenient"
- **Environment variable**: `REV_REVIEW_STRICTNESS=lenient` (default)
- **Reason**: Allow more creative/exploratory plans without excessive blocking

### 4. Flexible Verification System
- **New configuration**: `VERIFICATION_STRICTNESS` with "lenient", "moderate", "strict" levels
- **Empty file handling**: In lenient mode, empty files generate warnings instead of failures
- **Comment requirements**: `REQUIRE_FILE_COMMENTS` defaults to false (warning only)
- **Reason**: Allow edge cases in exploratory work while maintaining strict mode for production

### 5. Improved Loop Guards for Research
- **Research task threshold**: Increased from 2 to 3 identical actions before blocking
- **Action transformation**: Research tasks get higher thresholds than implementation tasks
- **File reading detection**: Increased tolerance for repeated file reading during research
- **Reason**: Research requires multiple passes; allow reasonable exploration

### 6. Non-Interactive ContextGuard by Default
- **ContextGuard interactive**: Default changed from `true` → `false`
- **Environment variable**: `REV_CONTEXT_GUARD_INTERACTIVE=false` (default)
- **Reason**: Reduce interruption flow; let AI research autonomously

### 7. Deep Reasoning for Complex Tasks
- **New DeepReasoningAgent**: Specialized agent for complex multi-step reasoning
- **Complexity detection**: Automatically routes complex tasks (complexity ≥ 7/10) to deep reasoning
- **Deep planning**: Performs comprehensive analysis, explores alternatives, creates execution plans
- **Task injection**: Extracts suggested tasks from deep plans for orchestrated execution
- **Configuration**:
  - `REV_DEEP_REASONING_ENABLED=false` (default, set to true to enable)
  - `REV_DEEP_REASONING_COMPLEXITY_THRESHOLD=7` (1-10 scale)
- **Reason**: Complex tasks need deep, uninterrupted reasoning before execution

## Configuration Summary

### New Defaults
```bash
# Research limits
export REV_MAX_READ_FILE_PER_TASK=9999
export REV_MAX_SEARCH_CODE_PER_TASK=9999

# Uncertainty detection
export REV_UNCERTAINTY_THRESHOLD=8
export REV_UNCERTAINTY_AUTO_SKIP_THRESHOLD=15

# Review system
export REV_REVIEW_STRICTNESS=lenient
export REV_VERIFICATION_STRICTNESS=lenient

# ContextGuard
export REV_CONTEXT_GUARD_INTERACTIVE=false

# File comments (warning only)
export REV_REQUIRE_FILE_COMMENTS=false

# Deep reasoning (disabled by default, enable for complex tasks)
export REV_DEEP_REASONING_ENABLED=false
export REV_DEEP_REASONING_COMPLEXITY_THRESHOLD=7
```

### CLI Overrides
```bash
# Use strict mode for production work
rev "task description" --review-strictness strict --verification-strictness strict

# Use lenient mode for exploration (default)
rev "task description"  # Uses lenient defaults

# Adjust uncertainty sensitivity
rev "task description" --uncertainty-threshold 10 --uncertainty-auto-skip-threshold 20

# Enable deep reasoning for complex tasks
rev "task description" --deep-reasoning-enabled --deep-reasoning-complexity-threshold 5
# Disable deep reasoning
rev "task description" --no-deep-reasoning
```

## Philosophy: Smart Flexibility

The changes follow these principles:

1. **Research is exploratory** - Allow extensive reading, searching, and multiple passes
2. **Uncertainty is natural** - Don't interrupt research for normal uncertainty
3. **Safety with intelligence** - Maintain loop detection but increase thresholds for research
4. **Configurable strictness** - Different modes for exploration vs. production
5. **Minimal interruption** - Reduce interactive prompts during autonomous research
6. **Deep reasoning for complexity** - Use specialized agent for complex tasks requiring multi-step reasoning

## Result

rev now behaves more like Claude Code:
- **Flexible** for exploration and complex codebase understanding
- **Smart** about when to intervene vs. when to allow exploration
- **Configurable** for different workflow needs
- **Safe** with maintained loop detection and critical guards
- **Intelligent** with deep reasoning capabilities for complex multi-step tasks

The system can now tackle complex tasks requiring deep codebase research while avoiding unnecessary interruptions and restrictions. The DeepReasoningAgent provides comprehensive analysis for complex problems, exploring alternatives and creating detailed execution plans before delegating to specialized agents.