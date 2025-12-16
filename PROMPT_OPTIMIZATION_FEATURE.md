# Prompt Optimization Feature

## Overview

This feature analyzes user requests and recommends improvements before execution.

**Purpose:**
- Clarify vague requests
- Identify missing requirements
- Suggest better task structure
- Catch issues early

---

## How It Works

### Step 1: Detect If Optimization Needed

```python
from rev.execution.prompt_optimizer import should_optimize_prompt

# Returns True if request might benefit from optimization
if should_optimize_prompt("fix the auth"):
    # Request is vague, suggest improvements
```

**Triggers optimization if:**
- Very short (< 10 words): "Add authentication"
- Vague language: "improve", "fix", "enhance" without specifics
- Multiple unrelated items: "Add auth and refactor utils and optimize DB"
- Could be misunderstood

### Step 2: Get LLM Recommendations

```python
from rev.execution.prompt_optimizer import get_prompt_recommendations

recommendations = get_prompt_recommendations("Fix the API")

# Returns:
{
  "clarity_score": 4/10,
  "is_vague": true,
  "potential_issues": [
    "No indication of which API",
    "Unknown what 'fix' means",
    "No success criteria"
  ],
  "missing_info": [
    "Which API endpoint?",
    "What error/issue?",
    "What's the expected behavior?"
  ],
  "recommendations": [
    "Specify the API or endpoint",
    "Describe the problem",
    "Define success criteria"
  ],
  "suggested_improvement": "Fix the /api/users POST endpoint that returns 500 error.
                            Should handle missing email field with proper validation.",
  "reasoning": "..."
}
```

### Step 3: User Chooses

```python
from rev.execution.prompt_optimizer import prompt_optimization_dialog

final_prompt, was_optimized = prompt_optimization_dialog("Fix the auth")

# Presents options:
# [1] Use the suggested improvement
# [2] Keep the original request
# [3] Enter a custom request
```

---

## Example Flow

### Example 1: Vague Request

**Input:**
```
"Improve performance"
```

**Analysis:**
```
📊 Analysis Results:
   Clarity Score: 3/10

   ⚠️ Potential Issues:
      - "Improve" is too generic - which aspect?
      - No indication of what metrics matter
      - Could mean API speed, memory, startup time, etc

   ❓ Missing Information:
      - Which component needs improvement?
      - What's the current baseline?
      - What's the target improvement?

   💡 Recommendations:
      - Specify the component (API response time, memory usage, startup time)
      - Set measurable goals
      - Mention current performance issues
```

**Suggested Improvement:**
```
"Optimize API response time for /api/users endpoint.
Current: 2s average response time.
Target: <500ms.
Implement caching for user queries."
```

### Example 2: Missing Context

**Input:**
```
"Add authentication"
```

**Analysis:**
```
📊 Analysis Results:
   Clarity Score: 5/10

   ⚠️ Potential Issues:
      - No indication of auth method
      - Scope unclear (new project or existing?)

   ❓ Missing Information:
      - JWT, OAuth, session-based?
      - Database has users already?
      - Need refresh tokens?
```

**Suggested Improvement:**
```
"Add JWT-based authentication to the API.
Users table exists with email/password.
Include login endpoint, token validation middleware, and refresh token support."
```

### Example 3: Clear Request (No Optimization)

**Input:**
```
"Create a unit test file for the UserService class covering all public methods"
```

**Result:**
```
✓ Request appears clear. Proceeding without optimization.
```

---

## Integration Points

### In Orchestrator

```python
from rev.execution.prompt_optimizer import optimize_prompt_if_needed

# Before planning
final_request, was_optimized = optimize_prompt_if_needed(user_request)

if was_optimized:
    print("✓ Request optimized for clarity")
else:
    print("✓ Request already clear")

# Then proceed with planning using final_request
plan = create_plan(final_request)
```

### In CLI

```bash
# Enable prompt optimization
rev --optimize-prompt "your vague request here"

# Disable for always use original
rev --no-optimize-prompt "your request"

# Auto-optimize without asking
rev --auto-optimize "your vague request here"
```

---

## API Usage

### Simple Usage

```python
from rev.execution.prompt_optimizer import optimize_prompt_if_needed

# Let user choose
final_prompt, was_optimized = optimize_prompt_if_needed(
    user_request="Fix the database",
    auto_optimize=False  # Show dialog
)
```

### Auto-Optimize (Non-Interactive)

```python
# Automatically use improvements
final_prompt, was_optimized = optimize_prompt_if_needed(
    user_request="Fix the database",
    auto_optimize=True  # Use improvement without asking
)
```

### Manual Control

```python
from rev.execution.prompt_optimizer import (
    should_optimize_prompt,
    get_prompt_recommendations,
    prompt_optimization_dialog
)

request = "Improve auth"

# Check if needed
if should_optimize_prompt(request):
    # Get recommendations
    recs = get_prompt_recommendations(request)

    # Show dialog to user
    final_prompt, was_optimized = prompt_optimization_dialog(
        request,
        interactive=True
    )
```

---

## Output Example

```
======================================================================
PROMPT OPTIMIZATION
======================================================================

📋 Analyzing request for potential improvements...

📊 Analysis Results:
   Clarity Score: 4/10

   ⚠️ Potential Issues:
      - "Fix" is too vague - which problem?
      - No indication of scope
      - Could mean multiple things

   ❓ Missing Information:
      - What's broken specifically?
      - What error messages?
      - What should the result be?

   💡 Recommendations:
      - Describe the specific problem
      - Include error messages if available
      - Define expected behavior
      - Mention files or components affected

📝 Suggested Improvement:
   Fix the /api/login endpoint that returns "Invalid credentials" error
   even with correct username/password. The issue is likely in the
   password comparison logic in UserService.py.

======================================================================
Options:
  [1] Use the suggested improvement
  [2] Keep the original request
  [3] Enter a custom request
======================================================================

Choice [1-3]: 1

✓ Using improved request.
```

---

## Benefits

### For Users
- ✓ Get suggestions before execution
- ✓ Clarify vague requests early
- ✓ Catch missing requirements
- ✓ Better task decomposition

### For System
- ✓ Clearer requests = better plans
- ✓ Better context for LLM
- ✓ Fewer failed tasks due to ambiguity
- ✓ More efficient execution

### For Quality
- ✓ Catch scope creep early
- ✓ Identify risky requests
- ✓ Better goal definition
- ✓ Improved success rate

---

## Configuration

### Env Variables

```bash
# Enable prompt optimization
export REV_OPTIMIZE_PROMPT=true

# Auto-optimize without asking
export REV_AUTO_OPTIMIZE=true

# Disable optimization
export REV_OPTIMIZE_PROMPT=false
```

### CLI Flags

```bash
rev --optimize-prompt "your request"
rev --auto-optimize "your request"
rev --no-optimize-prompt "your request"
```

---

## Vagueness Scoring

The system scores requests on clarity:

| Score | Quality | Example |
|-------|---------|---------|
| 1-3 | Very Vague | "Fix stuff", "Make it work" |
| 4-6 | Somewhat Clear | "Fix the auth", "Improve performance" |
| 7-8 | Clear | "Add JWT authentication", "Optimize query by 50%" |
| 9-10 | Very Clear | "Add JWT authentication with refresh tokens for existing user table" |

Requests scoring < 7 typically get optimization recommendations.

---

## Status

✅ **FEATURE IMPLEMENTED**
- ✓ Detection logic (should_optimize_prompt)
- ✓ Recommendation generation (get_prompt_recommendations)
- ✓ User dialog (prompt_optimization_dialog)
- ✓ Full API (optimize_prompt_if_needed)

⏳ **INTEGRATION NEEDED**
- [ ] Add to orchestrator main flow
- [ ] Add CLI flags
- [ ] Add configuration options
- [ ] Add tests

---

## Example Improvements

| Original | Improved |
|----------|----------|
| "Fix the bug" | "Fix the bug in UserService where password comparison fails for non-ASCII characters" |
| "Add tests" | "Add unit tests for PaymentProcessor covering success, timeout, and invalid card scenarios" |
| "Refactor" | "Refactor AuthController to use dependency injection and extract token validation logic" |
| "Optimize" | "Optimize database queries in UserRepository to reduce N+1 query issues on user search" |

---

**Feature Status:** Ready for Integration
**Complexity:** Low - Non-intrusive
**User Value:** High - Prevents common issues
