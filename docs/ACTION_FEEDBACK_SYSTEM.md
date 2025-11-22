# Action Feedback System

## Overview

The Action Feedback System is a closed-loop mechanism that enables the execution module to receive and act upon feedback from the review agent. This allows the LLM to see review concerns, security warnings, and alternative approaches, and adjust its execution strategy accordingly.

## Problem Statement

Previously, the review agent would analyze actions and provide valuable feedback (concerns, alternative approaches, recommendations), but this feedback was only displayed to the user. The execution module never passed the feedback back to the LLM, so the LLM couldn't:

- See what concerns were raised about its actions
- Consider alternative approaches suggested by the reviewer
- Adjust its strategy based on security warnings
- Learn from review feedback to improve subsequent actions

## Solution

The feedback system creates a closed loop by:

1. **Capturing review feedback** - The `ActionReview` object contains all feedback
2. **Formatting for LLM consumption** - `format_review_feedback_for_llm()` creates structured feedback messages
3. **Injecting into conversation** - Feedback is added as "user" messages to the LLM conversation
4. **Allowing adjustment** - The LLM can see feedback and adjust its approach

## Architecture

```
┌─────────────┐
│   LLM       │
│  proposes   │
│   action    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Review    │
│   Agent     │ ──► Analyzes action for:
└──────┬──────┘     - Security issues
       │            - Best practices
       │            - Alternative approaches
       ▼
┌─────────────┐
│  Format     │
│  Feedback   │ ──► Creates structured message
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Inject     │
│  into       │ ──► Adds to conversation as "user" message
│Conversation │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   LLM       │
│   sees      │ ──► Can now:
│  feedback   │     - Consider alternatives
│   and       │     - Address concerns
│  adjusts    │     - Try different approach
└─────────────┘
```

## Implementation

### 1. Feedback Formatting (`reviewer.py`)

```python
def format_review_feedback_for_llm(
    review: ActionReview,
    action_description: str,
    tool_name: str = None
) -> str:
    """Format action review feedback for LLM consumption."""
    # Returns structured feedback including:
    # - Security warnings
    # - Concerns
    # - Alternative approaches
    # - Recommendations
    # - Guidance on next steps
```

### 2. Feedback Injection (`executor.py`)

In both `execution_mode()` and `execute_single_task()`:

```python
# After action review
if enable_action_review and action_review:
    feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
    if feedback:
        messages.append({
            "role": "user",
            "content": feedback
        })
```

### 3. Blocked Action Handling

When an action is blocked (not approved):

```python
if not action_review.approved:
    # Display to user
    display_action_review(action_review, action_desc)

    # Inject feedback into conversation
    feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
    if feedback:
        messages.append({
            "role": "user",
            "content": feedback
        })

    # Don't fail immediately - let LLM try different approach
    continue
```

## Feedback Message Format

The feedback message follows this structure:

```
=== REVIEW FEEDBACK ===
Action: <action_description>
Tool: <tool_name>
Status: <Approved with concerns | BLOCKED>

🔒 SECURITY WARNINGS:
  - <warning 1>
  - <warning 2>

⚠️  CONCERNS:
  - <concern 1>
  - <concern 2>

💡 ALTERNATIVE APPROACHES:
  1. <alternative 1>
  2. <alternative 2>

📋 RECOMMENDATION: <recommendation>

[Guidance on next steps based on approval status]
===================
```

## Usage

Enable the action feedback system with the `--action-review` flag:

```bash
# Enable action review (includes feedback loop)
rev --action-review "Implement security-sensitive feature"

# Combine with review strictness
rev --action-review --review-strictness strict "Database migration"
```

When enabled via API:

```python
from rev.execution import execution_mode

# Enable action review with feedback
success = execution_mode(
    plan=my_plan,
    enable_action_review=True  # Enables both review and feedback
)
```

## Benefits

1. **Self-correction**: LLM can adjust its approach based on review feedback
2. **Learning**: LLM sees patterns in what gets flagged and improves over time
3. **Better security**: Security warnings are seen by the LLM, not just the user
4. **Alternative exploration**: LLM can try suggested alternatives automatically
5. **Reduced manual intervention**: System can recover from blocked actions

## Example Scenario

**Without Feedback System:**
```
1. LLM proposes: search_code with complex regex
2. Reviewer warns: "Pattern may have false positives"
3. User sees warning
4. Action proceeds anyway (approved with concerns)
5. LLM unaware of concern, doesn't adjust
```

**With Feedback System:**
```
1. LLM proposes: search_code with complex regex
2. Reviewer warns: "Pattern may have false positives"
3. Feedback injected into conversation
4. LLM sees: "Consider using AddressSanitizer instead"
5. LLM adjusts: Uses suggested alternative tool
6. Better results, fewer false positives
```

## Testing

Tests are located in `tests/test_review_agent.py`:

```bash
# Run feedback formatting tests
python -m unittest tests.test_review_agent.TestFeedbackFormatting -v
```

Key test cases:
- Feedback with concerns and warnings
- Blocked action formatting
- No feedback when no concerns
- Alternative approaches only
- Missing tool name handling

## Future Enhancements

Potential improvements to the feedback system:

1. **Feedback aggregation**: Track patterns across multiple reviews
2. **Learning from feedback**: Store successful adaptations for future reference
3. **Confidence scoring**: Weight feedback by reviewer confidence
4. **Multi-round negotiation**: Allow LLM to propose revised actions
5. **Feedback metrics**: Track how often feedback leads to better outcomes
