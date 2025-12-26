# Ultrathink Mode - Extended Reasoning and Craftsmanship

## Overview

**Ultrathink Mode** is an advanced operational mode for REV that enhances agent reasoning with deeper analytical thinking, elegant solution design, and obsessive attention to detail. Inspired by visionary product design philosophy, Ultrathink Mode transforms REV from a code automation tool into a thoughtful craftsman that creates solutions that feel inevitable.

## Philosophy

> "We're not here to write code. We're here to make a dent in the universe."

Ultrathink Mode embodies six core principles:

1. **Think Different** - Question assumptions, explore multiple solution approaches, design from first principles
2. **Obsess Over Details** - Study the codebase like a masterpiece, understand patterns and philosophy
3. **Plan Like Da Vinci** - Sketch architecture mentally before writing, create clear and well-reasoned plans
4. **Craft, Don't Code** - Write code that reads like poetry, with names that sing and abstractions that feel natural
5. **Iterate Relentlessly** - First make it work, then make it beautiful, then make it fast
6. **Simplify Ruthlessly** - Achieve elegance by removing complexity without losing power

## Enabling Ultrathink Mode

### Environment Variable

```bash
export REV_ULTRATHINK_MODE=on
export REV_ULTRATHINK_MAX_TOKENS=15000  # Optional: increase token budget for deeper thinking
```

### Usage

```bash
# Enable ultrathink mode for a single command
REV_ULTRATHINK_MODE=on rev "Implement user authentication with JWT"

# Enable for the session
export REV_ULTRATHINK_MODE=on
rev "Add dark mode toggle to settings"
```

### Configuration

**Available Settings:**

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `REV_ULTRATHINK_MODE` | `on`, `off` | `off` | Enable/disable ultrathink mode |
| `REV_ULTRATHINK_MAX_TOKENS` | `1000-50000` | `15000` | Maximum tokens for extended reasoning |

## What Changes in Ultrathink Mode

### Planning Phase

When ultrathink mode is enabled during planning, the agent:

- **Analyzes the problem space deeply** before jumping to solutions
- **Considers multiple architectural approaches** and their trade-offs
- **Questions "obvious" implementations** to find better alternatives
- **Designs abstractions that match mental models** of the problem domain
- **Plans for long-term maintainability** and extensibility
- **Documents architectural insights** and decision rationale

**Example Difference:**

**Normal Mode:**
```
Task 1: Create user authentication endpoint
Task 2: Add password hashing
Task 3: Implement JWT generation
```

**Ultrathink Mode:**
```
Task 1: Research existing auth patterns in codebase
Task 2: Design authentication flow with security best practices
Task 3: Create comprehensive auth tests (valid/invalid credentials, token expiry)
Task 4: Implement auth middleware with elegant error handling
Task 5: Add JWT with secure token rotation
Task 6: Document security considerations and usage examples
```

### Code Writing Phase

When writing code, ultrathink-enhanced agents:

- **Choose names that reveal intent** without needing comments
- **Create natural abstractions** that feel intuitive to use
- **Handle edge cases gracefully**, not defensively
- **Write code that reads like poetry**, not prose
- **Follow existing patterns** unless there's a genuinely better approach
- **Leave the codebase better** than they found it

**Code Quality Improvements:**

```python
# Normal Mode
def proc_data(d):
    r = []
    for i in d:
        if i > 0:
            r.append(i * 2)
    return r

# Ultrathink Mode
def extract_positive_values_doubled(values: List[int]) -> List[int]:
    """Extract positive values from the input list and double them.

    Args:
        values: List of integers to process

    Returns:
        List containing doubled positive values in original order
    """
    return [value * 2 for value in values if value > 0]
```

### Refactoring Phase

Ultrathink refactoring:

- **Sees what code could become**, not just what it is
- **Identifies essential vs. accidental complexity**
- **Extracts meaningful abstractions** that reveal problem domain concepts
- **Makes implicit concepts explicit** through naming and structure
- **Preserves the good parts** while improving the rest

### Execution Phase

During task execution, ultrathink mode provides:

- **Careful consideration** before each action
- **Thoughtful error handling** with meaningful messages
- **Iterative refinement** toward elegant solutions
- **Code review mindset** - "Will this delight the next developer?"

## Agent-Level Integration

Ultrathink mode enhances these agents:

### 1. **CodeWriterAgent** (`ULTRATHINK_CODE_WRITER_PROMPT`)
- Full ultrathink philosophy integrated
- Specialized code craftsmanship principles
- Enhanced naming and abstraction guidelines

### 2. **RefactoringAgent** (with `ULTRATHINK_REFACTORING_SUFFIX`)
- Vision for improvement and elegant structure
- Incremental perfection approach
- Architectural insight extraction

### 3. **Planning System** (with `ULTRATHINK_PLANNING_SUFFIX`)
- Deep problem analysis
- Multi-approach consideration
- Quality obsession from planning stage

### 4. **Execution System** (with `ULTRATHINK_EXECUTION_SUFFIX`)
- Implementation craftsmanship
- Iterative refinement cycles
- Integration harmony with existing code

## When to Use Ultrathink Mode

### ✅ Recommended For:

- **New feature development** requiring architectural decisions
- **Complex refactoring** that needs careful design
- **Production code** where quality and maintainability matter
- **Public APIs** and library code that others will use
- **Learning projects** where understanding patterns is important
- **Code reviews** and quality improvements

### ⚠️ Consider Trade-offs For:

- **Quick prototypes** where speed matters more than elegance
- **Throw-away scripts** that won't be maintained
- **Strict token/time budgets** where efficiency is critical
- **Simple CRUD operations** with obvious implementations

## Performance Considerations

### Token Usage

Ultrathink mode uses **15-30% more tokens** on average due to:
- Longer system prompts with detailed philosophical guidance
- More thoughtful analysis and planning
- Additional context exploration

**Mitigation:**
- Adjust `REV_ULTRATHINK_MAX_TOKENS` based on your needs
- Use selectively for complex tasks
- Disable for simple, repetitive operations

### Execution Time

Ultrathink mode may take **10-20% longer** because:
- Agents spend more time analyzing before acting
- More thorough exploration of existing patterns
- Additional planning and validation steps

**Benefit:**
- Higher first-pass success rate
- Fewer iterations needed for quality
- Better long-term maintainability

## Examples

### Example 1: Feature Implementation

**Command:**
```bash
REV_ULTRATHINK_MODE=on rev "Add metrics tracking and export to CSV/JSON"
```

**Ultrathink Approach:**
1. Researches existing logging/telemetry patterns in codebase
2. Designs metrics collection system that feels natural to use
3. Creates export abstraction that's easy to extend (new formats)
4. Writes tests that document expected behavior clearly
5. Implements with elegant error handling and user-friendly messages
6. Documents usage examples and design decisions

### Example 2: Code Refactoring

**Command:**
```bash
REV_ULTRATHINK_MODE=on rev "Refactor the authentication module for clarity"
```

**Ultrathink Approach:**
1. Deeply analyzes current auth implementation
2. Identifies what's essential complexity vs. accidental
3. Envisions ideal structure that matches problem domain
4. Creates plan with incremental, test-verified steps
5. Refactors with meaningful names and clear abstractions
6. Leaves comprehensive documentation of improvements

### Example 3: Bug Fix

**Command:**
```bash
REV_ULTRATHINK_MODE=on rev "Fix race condition in concurrent requests"
```

**Ultrathink Approach:**
1. Investigates root cause, not just symptoms
2. Considers multiple solution approaches (locks, queues, atomics)
3. Chooses solution that fits architecture elegantly
4. Adds test that reproduces the race condition
5. Implements fix with clear reasoning in comments
6. Validates fix doesn't introduce new issues

## Technical Details

### System Prompt Architecture

Ultrathink mode works by enhancing base system prompts:

```python
from rev.execution.ultrathink_prompts import get_ultrathink_prompt

# Planning example
base_prompt = PLANNING_SYSTEM
if config.ULTRATHINK_MODE == "on":
    enhanced_prompt = get_ultrathink_prompt(base_prompt, 'planning')
```

The `get_ultrathink_prompt()` function appends:
1. Core philosophy (shared across all agents)
2. Phase-specific suffix (planning, execution, refactoring, etc.)

### Integration Points

**File:** `/home/user/rev/rev/execution/ultrathink_prompts.py`
- `ULTRATHINK_CORE_PHILOSOPHY` - Shared principles
- `ULTRATHINK_PLANNING_SUFFIX` - Planning enhancements
- `ULTRATHINK_EXECUTION_SUFFIX` - Execution enhancements
- `ULTRATHINK_REFACTORING_SUFFIX` - Refactoring enhancements
- `ULTRATHINK_CODE_WRITER_PROMPT` - Complete CodeWriter prompt
- `get_ultrathink_prompt()` - Utility function

**Modified Files:**
- `/home/user/rev/rev/config.py` - Configuration settings
- `/home/user/rev/rev/agents/code_writer.py` - CodeWriter integration
- `/home/user/rev/rev/agents/refactoring.py` - Refactoring integration
- `/home/user/rev/rev/execution/planner.py` - Planning integration
- `/home/user/rev/rev/execution/executor.py` - Execution integration

## Troubleshooting

### Ultrathink mode not activating

**Check configuration:**
```bash
echo $REV_ULTRATHINK_MODE  # Should output: on
```

**Verify in logs:**
Look for: `🧠 ULTRATHINK MODE ENABLED` in agent output

### Excessive token usage

**Reduce token budget:**
```bash
export REV_ULTRATHINK_MAX_TOKENS=8000
```

**Use selectively:**
```bash
# Normal mode for simple tasks
rev "Add print statement to debug.py"

# Ultrathink for complex tasks
REV_ULTRATHINK_MODE=on rev "Architect new payment processing system"
```

### Slower execution

This is expected - ultrathink prioritizes quality over speed. If speed is critical:

1. Disable ultrathink for time-sensitive tasks
2. Use ultrathink during design, normal mode during implementation
3. Enable only for specific agents (modify agent files directly)

## Best Practices

1. **Enable for new features** where design matters
2. **Use during refactoring** to improve code quality
3. **Combine with TDD** for maximum effectiveness
4. **Review generated code** to learn from ultrathink's approach
5. **Document learned patterns** for future reference
6. **Adjust token budget** based on task complexity
7. **Give clear context** - ultrathink works best with good problem descriptions

## Philosophy in Action

> "Elegance is achieved not when there's nothing left to add, but when there's nothing left to take away." - Antoine de Saint-Exupéry

Ultrathink mode embodies this principle. It encourages agents to:

- Ask "Why?" before "How?"
- Seek simple solutions to complex problems
- Create code that teaches its readers
- Design for joy, not just functionality
- Leave lasting value, not just working code

## Contributing

To extend ultrathink mode:

1. Add phase-specific prompts to `ultrathink_prompts.py`
2. Integrate into agent `execute()` methods
3. Update this documentation
4. Test with representative tasks
5. Submit PR with examples

## Related Documentation

- [Execution Modes](EXECUTION_MODES.md) - Linear vs Sub-agent execution
- [Prompt Optimization](PROMPT_OPTIMIZATION_INTEGRATION.md) - Adaptive prompt improvement
- [Development Guide](DEVELOPMENT.md) - REV architecture and contributing

---

**Remember:** Ultrathink mode is not about writing more code—it's about writing the *right* code. Code that feels inevitable. Code that makes others smile. Code that stands the test of time.

*"The people who are crazy enough to think they can change the world are the ones who do."*
