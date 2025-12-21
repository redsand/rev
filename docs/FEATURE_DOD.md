# Feature: Definition of Done (DoD)

**Status:** ✅ Implemented & Tested (23/23 tests passing)
**Location:** `rev/models/dod.py`, `rev/agents/dod_generator.py`, `rev/execution/dod_verifier.py`
**Tests:** `tests/test_dod.py`

---

## Problem Solved

**Before DoD:**
- Tasks marked "completed" when they're not operational
- Tests pass locally but fail in CI
- Code compiles but has runtime errors
- Changes work in isolation but break integration
- No clear definition of what "done" means

**After DoD:**
- Every task has a concrete, measurable contract
- Hard gate: verification must satisfy ALL criteria or task fails
- No ambiguity about task completion
- Prevents false positives ("it works on my machine")

---

## Value Proposition

### Measurable Impact

**Before (redtrade analyst registration failure):**
```
Task: "Fix analyst auto-registration"
Result: "COMPLETED" ✓
Reality: 0/34 analysts registered ✗
```

**After (with DoD):**
```yaml
task_id: T-001
deliverables:
  - type: file_modified
    path: main.py
  - type: runtime_check
    command: python main.py --check-analysts
    expect: "exit_code == 0"
acceptance_criteria:
  - "auto-registration count == 34"
  - "no F821 errors in modified code"
```

Result: **Task cannot complete until count == 34** ✓

---

## How It Works

### 1. DoD Generation (Automatic)

When a task is created, DoD is automatically generated:

```python
from rev.models.task import Task
from rev.agents.dod_generator import generate_dod, generate_simple_dod

task = Task(description="Fix analyst auto-registration in main.py", action_type="edit")

# Option A: LLM-powered (detailed)
dod = generate_dod(task, user_request="analysts should auto-register from lib/analysts/")

# Option B: Heuristic fallback (simple)
dod = generate_simple_dod(task)
```

**Generated DoD:**
- Concrete deliverables (files to modify, tests to pass)
- Measurable acceptance criteria
- Required validation stages

### 2. DoD Verification (Hard Gate)

After task execution, DoD is verified:

```python
from rev.execution.dod_verifier import verify_dod

result = verify_dod(dod, task, workspace_root=Path.cwd())

if result.passed:
    print("✓ Task complete - all DoD criteria met")
    task.status = TaskStatus.COMPLETED
else:
    print(f"✗ Task incomplete - unmet criteria:")
    for criterion in result.unmet_criteria:
        print(f"  - {criterion}")
    task.status = TaskStatus.FAILED
```

**Verification checks:**
- All deliverables produced (files created/modified)
- All acceptance criteria met (tests pass, syntax valid, etc.)
- Nothing is skipped or assumed

---

## Real-World Example

### Scenario: Split a Python module into a package

**Task:**
```
"Break out analysts.py into lib/analysts/ with one file per analyst"
```

**Auto-Generated DoD:**
```yaml
task_id: T-split-analysts
description: "Split analysts.py into package"

deliverables:
  - type: file_created
    paths: ["lib/analysts/__init__.py"]
    description: "Package init file created"

  - type: file_created
    description: "36 analyst files created"
    paths: ["lib/analysts/BreakoutAnalyst.py", ...]

  - type: syntax_valid
    paths: ["lib/analysts/__init__.py"]
    description: "Package imports are valid"

  - type: test_pass
    command: "pytest tests/test_analyst_registry.py -v"
    description: "Registration tests pass"

acceptance_criteria:
  - "lib/analysts/__init__.py exists and is not empty"
  - "36 analyst class files exist"
  - "pytest exit code == 0"
  - "no import errors"

validation_stages:
  - syntax
  - integration
  - unit
```

**Verification Result:**
```
DoD Verification: PASSED
Deliverables: 4/4 passed
Met criteria (4):
  ✓ lib/analysts/__init__.py exists and is not empty
  ✓ 36 analyst class files exist
  ✓ pytest exit code == 0
  ✓ no import errors
```

---

## Integration with Rev

### Orchestrator Integration

```python
# In orchestrator.py _continuous_sub_agent_execution():

# BEFORE task execution:
from rev.agents.dod_generator import generate_dod

dod = generate_dod(next_task, user_request)
next_task.dod = dod
print(f"[DoD] Generated DoD with {len(dod.deliverables)} deliverables")

# AFTER task execution:
from rev.execution.dod_verifier import verify_dod

dod_result = verify_dod(next_task.dod, next_task, workspace_root)
if not dod_result.passed:
    print(f"[DoD] FAILED - Unmet criteria: {dod_result.unmet_criteria}")
    next_task.status = TaskStatus.FAILED
    # Task will be retried or decomposed
else:
    print(f"[DoD] PASSED - Task complete")
    next_task.status = TaskStatus.COMPLETED
```

---

## Deliverable Types

### Supported Deliverables

| Type | Description | Verification Method |
|------|-------------|---------------------|
| `file_modified` | File was changed | Check file exists & tool events |
| `file_created` | New file created | Check file exists & not empty |
| `file_deleted` | File was removed | Check file doesn't exist |
| `test_pass` | Tests must pass | Run command, check exit code |
| `syntax_valid` | Code compiles | Run `compileall` |
| `runtime_check` | Command succeeds | Run command, check exit code |
| `imports_work` | Module importable | Try `import {module}` |

---

## Benefits

### 1. **Prevents False Completions**
```python
# Task appears complete but isn't
task.status = "COMPLETED"  # ✗ No verification

# DoD enforces completion
if not verify_dod(dod, task).passed:
    task.status = "FAILED"  # ✓ Catches incomplete work
```

### 2. **Clear Success Criteria**
```yaml
# Vague (before)
"Fix the bug"

# Concrete (with DoD)
deliverables:
  - type: test_pass
    command: "pytest tests/test_bug.py"
acceptance_criteria:
  - "pytest exit code == 0"
  - "no regression in other tests"
```

### 3. **Automatic Verification**
```python
# Manual (before)
"Did the analyst registration work? Let me check..."

# Automatic (with DoD)
result = verify_dod(dod, task)
# Returns pass/fail with detailed breakdown
```

### 4. **Measurable Quality Gate**
```
Before DoD: "Task done when LLM says so" (subjective)
After DoD: "Task done when all criteria met" (objective)
```

---

## Test Coverage

**23 tests, 100% passing:**

| Category | Tests | Coverage |
|----------|-------|----------|
| Model serialization | 3 | YAML, dict conversion, repr |
| DoD generation | 6 | Simple gen, LLM parsing, auto-stages |
| Deliverable verification | 8 | All deliverable types |
| Full DoD verification | 3 | Passing, failing, summaries |
| Integration workflows | 3 | Edit, create, graceful failures |

**Run tests:**
```bash
pytest tests/test_dod.py -v
# 23 passed, 1 warning in 2.65s
```

---

## Next Steps

1. **Enable in Orchestrator** - Add DoD generation/verification to task execution loop
2. **Add Metrics** - Track DoD pass rate, common failure patterns
3. **UI Integration** - Display DoD in CLI output for transparency
4. **LLM Refinement** - Improve DoD generation prompts based on feedback

---

## Related Features

- **Multi-Stage Verification** - DoD specifies which stages are required
- **Transactional Execution** - DoD verification determines commit/rollback
- **CRIT Judge** - CRIT can evaluate DoD quality before execution

---

**Feature Status:** ✅ Production Ready
**Documentation:** Complete
**Testing:** 23/23 passing
**Integration:** Ready for orchestrator
