# Code Reuse & Resource-First Improvements for Rev

This document outlines proposed changes to encourage Rev to:
1. **Use existing files and resources first** before creating new ones
2. **Encourage tight, documented, and reused code segments**
3. **Avoid duplication** and unnecessary file proliferation

## Current State Analysis

### ✅ What's Already Good

1. **Research Agent** (`rev/execution/researcher.py`):
   - Already searches for `similar_implementations`
   - Identifies existing patterns to follow
   - Uses RAG (semantic search) to find related code

2. **Planning System** (`rev/execution/planner.py:55-62`):
   - Has guidance to check existing structures before creating new ones
   - Instructs to reuse where possible
   - BUT: This guidance could be much stronger

3. **Review Agent** (`rev/execution/reviewer.py`):
   - Reviews plans for completeness and best practices
   - BUT: Doesn't specifically check for code duplication or unnecessary files

### ❌ What's Missing

1. **No explicit "reuse-first" policy** in file operations
2. **No warnings when creating files that might duplicate existing functionality**
3. **Review agent doesn't check for code duplication**
4. **Planning prompts could emphasize reuse more strongly**

---

## Proposed Improvements

### 1. Strengthen Planning Agent Reuse Policy

**File:** `rev/execution/planner.py`

**Current Lines 46-62:** Already mention reusing structures but buried in example
**Proposed Enhancement:** Make reuse a PRIMARY principle

```python
PLANNING_SYSTEM = """You are an expert CI/CD agent analyzing tasks and creating execution plans.

⚠️  CRITICAL PRINCIPLES - REUSE FIRST:
1. ALWAYS search existing code before creating new files
2. PREFER editing/extending existing files over creating new ones
3. ONLY create new files when existing ones cannot serve the purpose
4. AVOID duplication - reuse existing functions, classes, utilities
5. Document WHY new files are necessary if you create them

Your job is to:
1. Understand the user's request
2. USE TOOLS to analyze the repository structure and gather information
3. **SEARCH for existing code that could be reused or extended**
4. Create a comprehensive, ordered checklist of tasks based on what you discover

CRITICAL: You MUST use tools to explore the codebase before planning!
...
```

**Specific Addition After Line 62:**

```python
REUSE-FIRST WORKFLOW (MANDATORY):
Before creating ANY new file or structure:
1. Call search_code to find similar implementations
2. Call list_dir to see what files already exist in that category
3. Call read_file to review existing structures
4. If similar code exists:
   - Create task to EXTEND/MODIFY existing file instead
   - Explain in task description why extension is preferred
5. Only if NO suitable existing code:
   - Create task to ADD new file
   - Include justification in description: "No existing X found - creating new"

Example - Adding user authentication:
❌ BAD: {"description": "Create auth.py with login function", "action_type": "add"}
✅ GOOD: After searching:
  - Found existing user.py with basic auth
  - {"description": "Extend user.py to add OAuth support (reusing existing auth structure)", "action_type": "edit"}
```

### 2. Enhance Review Agent with Duplication Detection

**File:** `rev/execution/reviewer.py`

**Add to PLAN_REVIEW_SYSTEM after line 103:**

```python
11. **Code Reuse**: Does the plan unnecessarily duplicate existing functionality?
    - Check for new files that could be avoided by extending existing ones
    - Flag tasks creating utilities/helpers when similar ones exist
    - Verify research was done to find existing implementations
    - Prefer concentrated, well-documented modules over scattered code
```

**Add new review check after line 129:**

```python
  "duplication_concerns": [
    {
      "task_id": 3,
      "concern": "Creating new auth_helper.py when auth_utils.py exists",
      "suggestion": "Extend auth_utils.py instead of creating new file",
      "existing_resource": "src/utils/auth_utils.py"
    }
  ],
```

### 3. Add Reuse Verification to Research Agent

**File:** `rev/execution/researcher.py`

**Enhance the `similar_implementations` search (around line 62):**

```python
@dataclass
class ResearchFindings:
    """Findings from codebase research."""
    relevant_files: List[Dict[str, Any]] = field(default_factory=list)
    code_patterns: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    potential_conflicts: List[str] = field(default_factory=list)
    similar_implementations: List[Dict[str, str]] = field(default_factory=list)
    reusable_code: List[Dict[str, str]] = field(default_factory=list)  # NEW
    existing_utilities: List[str] = field(default_factory=list)  # NEW
    architecture_notes: List[str] = field(default_factory=list)
    suggested_approach: Optional[str] = None
    estimated_complexity: str = "medium"
    warnings: List[str] = field(default_factory=list)
    reuse_opportunities: List[str] = field(default_factory=list)  # NEW
```

**Update RESEARCH_SYSTEM prompt (line 82) to emphasize reuse:**

```python
RESEARCH_SYSTEM = """You are a research agent that analyzes codebases to gather context for planned changes.

🎯 PRIMARY MISSION: Find existing code that can be REUSED or EXTENDED.

Given a user request and codebase information, identify:
1. Which files are most relevant to the task
2. **Existing code that already solves similar problems (REUSE FIRST!)**
3. **Utilities, helpers, or modules that could be extended instead of creating new ones**
4. Existing patterns that should be followed
5. Potential conflicts or dependencies
6. Recommended approach that MAXIMIZES code reuse
...
```

### 4. Add File Operation Policy Check

**File:** `rev/tools/file_ops.py`

**Add a new helper function before `write_file`:**

```python
def _check_for_similar_files(path: str, purpose: str = None) -> Dict[str, Any]:
    """Check if similar files exist that could be used instead.

    Args:
        path: Path to the file being created
        purpose: Optional description of what the file will do

    Returns:
        Dict with 'warnings' and 'similar_files' if found
    """
    p = _safe_path(path)
    filename = p.name
    parent_dir = p.parent

    warnings = []
    similar_files = []

    # Check for files with similar names in same directory
    if parent_dir.exists():
        for existing in parent_dir.glob('*.py'):  # Adjust for other extensions
            # Check for similar names (edit distance, common prefixes, etc.)
            if existing.stem in filename or filename in existing.stem:
                similar_files.append(str(existing.relative_to(ROOT)))

    # Check for files with similar purposes (if purpose provided)
    # This would use search_code or RAG to find semantically similar files

    if similar_files:
        warnings.append(
            f"Similar files exist: {', '.join(similar_files)}. "
            f"Consider extending existing files instead of creating new one."
        )

    return {
        "warnings": warnings,
        "similar_files": similar_files
    }


def write_file(path: str, content: str, allow_new: bool = True) -> str:
    """Write content to a file.

    Args:
        path: File path to write
        content: Content to write
        allow_new: If False, only allow writing to existing files (edit mode)
    """
    try:
        p = _safe_path(path)

        # Check if creating a new file
        is_new = not p.exists()

        if is_new:
            # Run similarity check
            check_result = _check_for_similar_files(path)

            if check_result['warnings']:
                # Log warnings (could also return them in result)
                print(f"  ⚠️  {check_result['warnings'][0]}")

            if not allow_new:
                return json.dumps({
                    "error": "Creating new files not allowed in edit-only mode",
                    "similar_files": check_result['similar_files']
                })

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

        result = {"wrote": str(p.relative_to(ROOT)), "bytes": len(content)}
        if is_new and check_result.get('similar_files'):
            result['warning'] = check_result['warnings'][0]
            result['consider_instead'] = check_result['similar_files']

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
```

### 5. Add Configuration Options

**File:** `rev/config.py`

```python
# Code reuse policies
PREFER_REUSE = os.getenv("REV_PREFER_REUSE", "true").lower() == "true"
WARN_ON_NEW_FILES = os.getenv("REV_WARN_NEW_FILES", "true").lower() == "true"
REQUIRE_REUSE_JUSTIFICATION = os.getenv("REV_REQUIRE_JUSTIFICATION", "false").lower() == "true"
MAX_FILES_PER_FEATURE = int(os.getenv("REV_MAX_FILES", "5"))  # Encourage consolidation
```

### 6. Enhance Action Review for File Creation

**File:** `rev/execution/reviewer.py`

**Update ACTION_REVIEW_SYSTEM (around line 145):**

```python
3. **Best practices**: Following code style, structure, conventions
4. **Code Reuse**: Is this creating something that already exists?
   - Before creating new files: Has the agent searched for existing code?
   - Before adding new utilities: Do similar utilities already exist?
   - Is this duplicating functionality?
5. **Necessity**: Is this action actually necessary?
   - Are we creating files that could be avoided?
   - Are we adding features that already exist elsewhere?
```

---

## Implementation Priority

### Phase 1 (High Impact, Low Effort) - ✅ COMPLETED
1. ✅ **Update PLANNING_SYSTEM prompt** to strongly emphasize reuse-first principle
2. ✅ **Update RESEARCH_SYSTEM prompt** to specifically look for reuse opportunities
3. ✅ **Add duplication checks to PLAN_REVIEW_SYSTEM**

### Phase 2 (Medium Impact, Medium Effort) - ✅ COMPLETED
4. ✅ **Enhance ResearchFindings** to track reuse opportunities
5. ✅ **Add file similarity checking** to write_file operations
6. ✅ **Add configuration options** for reuse policies

### Phase 3 (Advanced Features) - ✅ COMPLETED
7. ✅ **Add metrics tracking** for code reuse vs. new file creation
   - Created `rev/tools/reuse_metrics.py` with ReuseMetricsTracker
   - Tracks files created, modified, deleted, and reuse ratios
   - Integrated into write_file operations automatically
8. ✅ **Create reuse analysis tool** that scans for duplication after changes
   - Created `rev/tools/reuse_analysis.py` with ReuseAnalyzer
   - Finds duplicate file names, small utility files, duplicate imports
   - Suggests consolidation opportunities
9. ⚪ **Add post-execution validation** to check if goals could have been achieved with less code
   - Can be added to orchestrator in future if needed

---

## Expected Benefits

1. **Fewer Files**: Concentrated, well-organized codebase
2. **Less Duplication**: Reduced maintenance burden
3. **Better Documentation**: When code is consolidated, it's easier to document
4. **Easier Testing**: Fewer files = fewer test files needed
5. **Clearer Architecture**: Related functionality stays together
6. **Faster Development**: Reusing existing code is faster than writing new

---

## Example Before/After

### Before (Creating New Files)
```
User: "Add JWT authentication"

Plan:
1. Create auth/jwt_handler.py with token validation
2. Create auth/jwt_utils.py with helper functions
3. Create middleware/auth_middleware.py
4. Create tests/test_jwt.py
```

### After (Reuse-First Approach)
```
User: "Add JWT authentication"

Research:
- Found existing auth/password_auth.py with auth interface
- Found middleware/session_middleware.py with similar pattern
- Found utils/crypto.py with token utilities

Plan:
1. Extend auth/password_auth.py to add JWTAuth class (reusing existing auth interface)
2. Extend middleware/session_middleware.py to add JWT support (reusing middleware pattern)
3. Use existing utils/crypto.py for token signing (no new file needed)
4. Extend tests/test_auth.py with JWT test cases

Result: 0 new files vs 4 new files, code follows existing patterns
```

---

## Monitoring Success

Track these metrics to measure improvement:
- **New files per task** (should decrease)
- **Edit-to-add ratio** (should increase)
- **Code duplication detected** in review (should increase detection, decrease actual duplication)
- **Lines of code per feature** (should decrease as reuse increases)

---

## Questions for Discussion

1. Should we make the `PREFER_REUSE` policy **mandatory** or just strongly recommended?
2. Should file creation require **explicit justification** in the task description?
3. Should we **block** new file creation if similar files are found (strict mode)?
4. How aggressive should similarity detection be?
5. Should we add a **consolidation agent** that periodically suggests merging similar files?
