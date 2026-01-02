"""
Orchestrator Agent for coordinating multi-agent workflow.

This module provides orchestration capabilities that coordinate all agents,
manage workflow, resolve conflicts, and make meta-decisions.

Implements Resource-Aware Optimization pattern to track and enforce budgets.

CORE PRINCIPLE - TEST-DRIVEN DEVELOPMENT (TDD):
REV follows TDD as a fundamental practice. All feature development and bug fixes
should follow the Red-Green-Refactor cycle:
1. RED: Write a failing test that specifies desired behavior
2. GREEN: Implement minimal code to make the test pass
3. REFACTOR: Improve code while keeping tests green

The orchestrator ensures that test tasks precede implementation tasks in plans,
and that validation is performed after each implementation step.
"""

import os
from datetime import datetime
import json
import time
import traceback
import shlex
from typing import Dict, Any, List, Optional, Literal, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict

from rev import config
from rev.models.task import ExecutionPlan, TaskStatus, Task
from rev.execution.planner import planning_mode
from rev.execution.reviewer import review_execution_plan, ReviewStrictness, ReviewDecision
from rev.execution.validator import (
    validate_execution,
    ValidationStatus,
    ValidationReport,
    format_validation_feedback_for_llm,
)
from rev.execution.researcher import research_codebase, ResearchFindings
from rev.execution.learner import LearningAgent, display_learning_suggestions
from rev.execution.executor import execution_mode, concurrent_execution_mode, fix_validation_failures
from rev.execution.state_manager import StateManager
from rev.execution.prompt_optimizer import optimize_prompt_if_needed
from rev.execution.quick_verify import verify_task_execution, VerificationResult
from rev.execution.anchoring_scorer import AnchoringScorer, AnchoringDecision
from rev.tools.registry import execute_tool, get_available_tools, get_repo_context
from rev.debug_logger import DebugLogger
from rev.config import (
    MAX_PLAN_TASKS,
    MAX_STEPS_PER_RUN,
    MAX_LLM_TOKENS_PER_RUN,
    MAX_WALLCLOCK_SECONDS,
    RESEARCH_DEPTH_DEFAULT,
    VALIDATION_MODE_DEFAULT,
    MAX_ORCHESTRATOR_RETRIES,
    MAX_PLAN_REGEN_RETRIES,
    MAX_ADAPTIVE_REPLANS,
    MAX_VALIDATION_RETRIES,
    EXCLUDE_DIRS,
)
from rev.llm.client import get_token_usage, ollama_chat
from rev.core.context import RevContext, ResourceBudget
from rev.execution.session import SessionTracker
from rev.core.shared_enums import AgentPhase
from rev.core.agent_registry import AgentRegistry
from rev.cache import clear_analysis_caches
import re
from rev.retrieval.context_builder import ContextBuilder
from rev.memory.project_memory import ensure_project_memory_file, maybe_record_known_failure_from_error
from rev.tools.workspace_resolver import resolve_workspace_path
from rev.workspace import get_workspace
from rev.core.text_tool_shim import maybe_execute_tool_call_from_text
from rev.agents.subagent_io import build_subagent_output
from rev.execution.action_normalizer import normalize_action_type
from rev.execution.verification_utils import _detect_build_command_for_root
from rev.execution.tool_constraints import allowed_tools_for_action, has_write_tool, WRITE_ACTIONS
from rev.terminal.formatting import colorize, Colors, Symbols
from difflib import SequenceMatcher

# Global reference to the currently active context for real-time feedback
_active_context: Optional[RevContext] = None

def push_user_feedback(feedback: str) -> bool:
    """Push user feedback to the currently active orchestrator context.
    
    Returns True if feedback was successfully delivered, False otherwise.
    """
    global _active_context
    if _active_context:
        _active_context.add_user_feedback(feedback)
        return True
    return False


def _format_verification_feedback(result: VerificationResult) -> str:
    """Format verification result for LLM feedback."""
    import re

    feedback = f"VERIFICATION FAILED: {result.message or 'Check environment.'}"

    details = result.details or {}

    # Extract validation command outputs if present (from quick_verify.py)
    validation = details.get("validation") or details.get("strict")
    if isinstance(validation, dict):
        feedback += "\n\nDETAILED OUTPUTS:"
        for label, res in validation.items():
            if not isinstance(res, dict):
                continue
            rc = res.get("rc")
            if rc is not None and rc != 0:
                stdout = (res.get("stdout") or "").strip()
                stderr = (res.get("stderr") or "").strip()
                feedback += f"\n- {label} (rc={rc})"

                # Special handling for lint commands - extract critical errors with file paths
                if 'lint' in label.lower() and stdout:
                    critical_errors = _extract_critical_lint_errors(stdout)
                    if critical_errors:
                        feedback += f"\n  {critical_errors}"
                    else:
                        # Fall back to last 3 lines if no critical errors found
                        feedback += "\n  stdout: " + " ".join(stdout.splitlines()[-3:])
                elif stderr:
                    feedback += "\n  stderr: " + " ".join(stderr.splitlines()[-3:]) # Last 3 lines
                elif stdout:
                    feedback += "\n  stdout: " + " ".join(stdout.splitlines()[-3:])
                else:
                    feedback += "\n(No stdout or stderr output captured from command)"

    # Extract debug info if present
    if "debug" in details:
        feedback += f"\n\nDebug Info:\n{json.dumps(details['debug'], indent=2)}"

    return feedback


def _extract_critical_lint_errors(lint_output: str) -> str:
    """Extract critical errors from lint output with file paths.

    Returns a formatted string with file paths and their critical errors.
    """
    import re

    # Pattern: file path followed by error lines
    # Example: C:\path\to\file.js
    #            71:1  error  Parsing error: Unexpected token

    lines = lint_output.splitlines()
    critical_errors = []
    current_file = None

    for line in lines:
        # Check if line is a file path (has path separators and ends with an extension)
        if re.match(r'^[A-Za-z]:\\|^/', line.strip()) or re.match(r'^[./].*\.(js|ts|py|jsx|tsx|vue)$', line.strip()):
            current_file = line.strip()
        # Check if line contains 'error' (not just 'warning')
        elif 'error' in line.lower() and current_file:
            # This is an error line - include it with the file path
            error_line = line.strip()
            # Extract line:col and error message
            match = re.search(r'(\d+:\d+)\s+(error)\s+(.*)', error_line, re.IGNORECASE)
            if match:
                location = match.group(1)
                error_msg = match.group(3)
                critical_errors.append(f"{current_file}:{location} - {error_msg}")

    if critical_errors:
        # Return first 5 critical errors to keep it concise
        return "CRITICAL ERRORS:\n    " + "\n    ".join(critical_errors[:5])

    return ""


def _extract_file_path_from_description(desc: str) -> Optional[str]:
    """Extract a file path from a task description for read tracking.

    Returns the first path-like string found, or None.
    """
    if not desc:
        return None

    # Match common path patterns
    # Support most common source, config, and data extensions
    ext = r"(py|js|ts|json|yaml|yml|md|txt|toml|cfg|ini|c|cpp|h|hpp|rs|go|rb|php|java|cs|sql|sh|bat|ps1)"
    patterns = [
        rf'`([^`]+\.{ext})`',  # backticked paths
        rf'"([^"]+\.{ext})"',  # quoted paths
        rf'\b([A-Za-z]:\\[^\s]+\.{ext})\b',  # Windows absolute
        rf'\b(/[^\s]+\.{ext})\b',  # Unix absolute
        rf'\b([\w./\\-]+\.{ext})\b',  # relative paths
    ]

    for pattern in patterns:
        match = re.search(pattern, desc, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def _extract_line_range_from_description(desc: str) -> Optional[str]:
    """Extract a line range from a task description (e.g., 'lines 95-150').

    Returns the line range string or None.
    """
    if not desc:
        return None

    patterns = [
        r'lines?\s+(\d+)\s*[-–to]+\s*(\d+)',  # "lines 95-150" or "line 95 to 150"
        r'lines?\s+(\d+)',  # "line 95" (single line)
    ]

    for pattern in patterns:
        match = re.search(pattern, desc, re.IGNORECASE)
        if match:
            return match.group(0)

    return None


def _compute_task_similarity(desc1: str, desc2: str) -> float:
    """Compute semantic similarity between two task descriptions.

    Uses SequenceMatcher ratio plus keyword overlap.
    Returns a score between 0.0 and 1.0.
    """
    if not desc1 or not desc2:
        return 0.0

    # Normalize descriptions
    d1 = desc1.strip().lower()
    d2 = desc2.strip().lower()

    # Direct sequence matching
    seq_ratio = SequenceMatcher(None, d1, d2).ratio()

    # Check for same file path
    file1 = _extract_file_path_from_description(desc1)
    file2 = _extract_file_path_from_description(desc2)
    same_file = 0.0
    if file1 and file2:
        # Normalize paths
        f1 = file1.replace('\\', '/').lower()
        f2 = file2.replace('\\', '/').lower()
        if f1 == f2 or f1.endswith(f2) or f2.endswith(f1):
            same_file = 0.3  # Bonus for same file

    # Check for same line range
    lines1 = _extract_line_range_from_description(desc1)
    lines2 = _extract_line_range_from_description(desc2)
    same_lines = 0.0
    if lines1 and lines2 and lines1.lower() == lines2.lower():
        same_lines = 0.2  # Bonus for same line range

    # Keywords that suggest similar intent
    intent_keywords = [
        'inspect', 'examine', 'read', 'analyze', 'review', 'check', 'look', 'find',
        'identify', 'understand', 'investigate', 'explore', 'verbatim', 'exact'
    ]

    kw1 = set(word for word in d1.split() if word in intent_keywords)
    kw2 = set(word for word in d2.split() if word in intent_keywords)

    keyword_overlap = 0.0
    if kw1 and kw2:
        overlap = len(kw1 & kw2) / max(len(kw1 | kw2), 1)
        keyword_overlap = overlap * 0.2  # Up to 0.2 bonus

    # Combine scores, capped at 1.0
    return min(1.0, seq_ratio + same_file + same_lines + keyword_overlap)


def _is_semantically_duplicate_task(
    new_desc: str,
    new_action: str,
    completed_tasks: List[str],
    threshold: float = 0.7
) -> bool:
    """Check if a new task is semantically similar to already-completed tasks.

    Args:
        new_desc: Description of the new task
        new_action: Action type of the new task
        completed_tasks: List of completed task log entries
        threshold: Similarity threshold (0.7 = 70% similar)

    Returns:
        True if the task is considered a duplicate
    """
    if not completed_tasks:
        return False

    new_action_lower = (new_action or '').lower()

    # Only check for duplication on read-like actions
    if new_action_lower not in {'read', 'analyze', 'research', 'investigate', 'review'}:
        return False

    similar_count = 0
    for log_entry in completed_tasks:
        # Parse the log entry to extract action type and description
        # Format: [STATUS] description | Output: ...
        match = re.match(r'\[(\w+)\]\s*(.+?)(?:\s*\|.*)?$', log_entry)
        if not match:
            continue

        status = match.group(1).upper()
        desc = match.group(2).strip()

        # Only compare with completed read-like tasks
        if status != 'COMPLETED':
            continue

        # Check for read-like keywords in the description
        desc_lower = desc.lower()
        is_read_like = any(kw in desc_lower for kw in ['read', 'inspect', 'examine', 'analyze'])
        if not is_read_like:
            continue

        similarity = _compute_task_similarity(new_desc, desc)
        if similarity >= threshold:
            similar_count += 1

    # If we found 2+ similar completed tasks, this is a duplicate
    return similar_count >= 2


def _count_file_reads(file_path: str, completed_tasks: List) -> int:
    """Count how many times a file has been read in completed tasks.

    P0-1 Fix: Now uses actual tool_events instead of keyword matching in descriptions.

    Args:
        file_path: The file path to check
        completed_tasks: List of completed Task objects or task log entries (backward compatible)

    Returns:
        Number of times this file was read
    """
    if not file_path or not completed_tasks:
        return 0

    # Normalize the target path
    target = file_path.replace('\\', '/').lower()
    count = 0

    # File reading tools to check for
    FILE_READING_TOOLS = {'read_file', 'read_file_lines', 'search_code', 'list_dir', 'analyze_code_context'}

    for item in completed_tasks:
        # NEW: Check if item is a Task object with tool_events
        if hasattr(item, 'tool_events') and hasattr(item, 'status'):
            # Only count completed tasks
            if hasattr(item.status, 'value'):
                if item.status.value != 'completed':
                    continue
            elif str(item.status).lower() != 'completed':
                continue

            # Check tool_events for file reading operations
            if item.tool_events:
                for event in item.tool_events:
                    tool_name = event.get('tool', '').lower()
                    if tool_name not in FILE_READING_TOOLS:
                        continue

                    # Extract file path from tool arguments
                    args = event.get('args', {})
                    if not isinstance(args, dict):
                        continue

                    # Check various argument names that contain file paths
                    event_file = args.get('file_path') or args.get('path') or args.get('pattern')
                    if event_file:
                        event_normalized = str(event_file).replace('\\', '/').lower()
                        if target == event_normalized or target.endswith(event_normalized) or event_normalized.endswith(target):
                            count += 1

        # BACKWARD COMPATIBLE: Handle string log entries (old format)
        elif isinstance(item, str):
            # Only count completed read-like tasks
            if not item.startswith('[COMPLETED]'):
                continue

            desc_lower = item.lower()
            if not any(kw in desc_lower for kw in ['read', 'inspect', 'examine', 'analyze']):
                continue

            # Extract file path from the log entry
            entry_file = _extract_file_path_from_description(item)
            if entry_file:
                entry_normalized = entry_file.replace('\\', '/').lower()
                if target == entry_normalized or target.endswith(entry_normalized) or entry_normalized.endswith(target):
                    count += 1

    return count


def _check_syntax_error_in_verification(verification_result) -> bool:
    """Check if a verification failure is due to syntax errors.

    Returns True if the failure is caused by syntax errors (F821, E999, etc.)
    that would leave the code in a broken state.
    """
    if not verification_result or not hasattr(verification_result, 'details'):
        return False

    details_str = str(verification_result.details).lower()
    message_str = str(verification_result.message).lower()

    # Check for syntax error indicators
    syntax_indicators = [
        'f821',  # Undefined name
        'e999',  # SyntaxError
        'undefined name',
        'syntaxerror',
        'name error',
        'compilation failed',
        'import error',
        'module not found',
    ]

    combined = f"{details_str} {message_str}"
    return any(indicator in combined for indicator in syntax_indicators)


def _detect_prisma_error_pattern(verification_result) -> tuple[bool, str, str]:
    """Detect Prisma validation errors and provide specific guidance.

    Returns:
        (is_prisma_error, error_type, detailed_guidance)
    """
    if not verification_result:
        return False, "", ""

    import re

    # Combine all error information
    message_str = str(verification_result.message)
    details_str = str(verification_result.details)
    combined = f"{message_str} {details_str}"

    # Pattern 1: PrismaClientValidationError - Invalid field in query
    if 'PrismaClientValidationError' in combined or 'Invalid `prisma.' in combined:
        # Extract model and operation
        model_match = re.search(r'Invalid `prisma\.(\w+)\.(\w+)\(\)` invocation', combined, re.IGNORECASE)
        model_name = model_match.group(1).capitalize() if model_match else "Model"
        operation = model_match.group(2) if model_match else "query"

        # Extract the invalid field name - look in the error output after the invocation
        # Pattern: look for field assignments after "where" or inside objects, but skip OR/AND keywords
        field_match = re.search(r'[{,]\s*(\w+)\s*:\s*["\']', combined)
        if not field_match or field_match.group(1) in ('OR', 'AND', 'where', 'NOT'):
            # Look for any property access pattern that's not a keyword
            field_match = re.search(r'(\w+)\s*:\s*["\'][^"\']+["\']', combined)
            if field_match and field_match.group(1) not in ('OR', 'AND', 'where', 'NOT'):
                invalid_field = field_match.group(1)
            else:
                invalid_field = "unknown_field"
        else:
            invalid_field = field_match.group(1)

        # Extract file location
        file_match = re.search(r'in\s+([\w\\/.-]+):(\d+):(\d+)', combined)
        file_location = file_match.group(1) if file_match else "test file"

        guidance = f"""
🎯 DIAGNOSED: Prisma Schema Mismatch - Invalid Field

**Problem**: `{invalid_field}` field doesn't exist in Prisma {model_name} model
The test file is trying to use a field that doesn't exist in your database schema.

**REQUIRED FIX (Choose ONE approach):**

**Approach 1: Update Prisma Schema (RECOMMENDED for new projects)**
1. Read prisma/schema.prisma (or backend/prisma/schema.prisma) to see the current {model_name} model
2. Add the missing `{invalid_field}` field to the model:
   ```prisma
   model {model_name} {{
     id        Int      @id @default(autoincrement())
     {invalid_field}  String   @unique  // Add this field
     // ... other existing fields
   }}
   ```
3. Use run_cmd tool to generate and push schema:
   ```bash
   cd backend  # or wherever prisma directory is
   npx prisma generate
   npx prisma db push
   ```

**Approach 2: Update Test File (if schema is correct)**
1. Read {file_location} to see what fields are being used
2. Read the Prisma schema to see what fields actually exist
3. Update the test to use the correct field names that exist in the schema

**DO NOT:**
- ❌ Ignore the error and move on
- ❌ Comment out the failing test
- ❌ Edit package.json or install packages

**YOU MUST:**
- ✅ Fix the schema/test mismatch by using ONE of the approaches above
- ✅ Run prisma generate and db push if you modify the schema
"""
        return True, "PrismaValidation", guidance

    # Pattern 2: Prisma connection errors
    if 'PrismaClientInitializationError' in combined or 'Can\'t reach database server' in combined:
        guidance = """
🎯 DIAGNOSED: Prisma Database Connection Error

**Problem**: Cannot connect to the database
The Prisma client cannot connect to your database server.

**REQUIRED FIX:**
1. Check if DATABASE_URL is set in .env file
2. Verify the database server is running
3. For PostgreSQL: `docker-compose up -d` or check PostgreSQL service
4. For SQLite: ensure the directory exists
5. Run database initialization:
   ```bash
   cd backend  # or wherever prisma directory is
   npx prisma generate
   npx prisma db push
   ```

**DO NOT:**
- ❌ Skip database setup
- ❌ Modify schema without initializing database

**YOU MUST:**
- ✅ Ensure database is running and accessible
- ✅ Run prisma generate and db push
"""
        return True, "PrismaConnection", guidance

    # Pattern 3: Missing Prisma client
    if 'Cannot find module \'@prisma/client\'' in combined or '@prisma/client is not installed' in combined:
        guidance = """
🎯 DIAGNOSED: Prisma Client Not Installed/Generated

**Problem**: @prisma/client module not found
Prisma client hasn't been generated or installed.

**REQUIRED FIX:**
1. Use run_cmd to install and generate Prisma client:
   ```bash
   cd backend  # or wherever package.json is
   npm install @prisma/client
   npx prisma generate
   npx prisma db push
   ```

**YOU MUST:**
- ✅ Install @prisma/client
- ✅ Run prisma generate
"""
        return True, "PrismaMissing", guidance

    return False, "", ""


def _detect_http_error_pattern(verification_result) -> tuple[bool, str, str]:
    """Detect HTTP error codes in test failures and provide specific guidance.

    Returns:
        (is_http_error, error_code, detailed_guidance)
    """
    if not verification_result:
        return False, "", ""

    import re

    # Combine all error information
    message_str = str(verification_result.message)
    details_str = str(verification_result.details)
    combined = f"{message_str} {details_str}"

    # Pattern 1: 404 Not Found errors
    match_404 = re.search(r'Expected.*?(\d{3}).*?Received.*?404', combined, re.IGNORECASE | re.DOTALL)
    if not match_404:
        match_404 = re.search(r'status.*?404|404.*?not found', combined, re.IGNORECASE)

    if match_404:
        # Try to extract the endpoint/route
        endpoint_match = re.search(r'(GET|POST|PUT|DELETE|PATCH)\s+([/\w\-.:]+)', combined, re.IGNORECASE)
        endpoint = endpoint_match.group(2) if endpoint_match else "/"
        method = endpoint_match.group(1).upper() if endpoint_match else "GET"

        guidance = f"""
🎯 DIAGNOSED: HTTP 404 - Route Handler Missing

**Problem**: {method} {endpoint} → 404 Not Found
This means the route/endpoint doesn't exist in your Express/server code.

**REQUIRED FIX:**
1. Read app.js (or server.js, index.js, src/app.js) to see existing routes
2. Find where routes are defined (look for app.get, app.post, router.get, etc.)
3. Add the missing route handler:

   For API endpoint:
   ```javascript
   app.{method.lower()}('{endpoint}', async (req, res) => {{
     // Your implementation here
     res.json({{ /* data */ }});
   }});
   ```

   For frontend route (like GET /):
   ```javascript
   const path = require('path');
   app.get('{endpoint}', (req, res) => {{
     res.sendFile(path.join(__dirname, 'dist', 'index.html'));
   }});
   ```

4. Ensure the route is registered BEFORE module.exports

**DO NOT:**
- ❌ Edit package.json (404 is not a dependency issue)
- ❌ Edit schema files (404 is not a database issue)
- ❌ Run npm install (404 is not about missing packages)

**YOU MUST:**
- ✅ Edit the server file (app.js/server.js) to add the route
"""
        return True, "404", guidance

    # Pattern 2: 500 Internal Server Error
    match_500 = re.search(r'Expected.*?(\d{3}).*?Received.*?500', combined, re.IGNORECASE | re.DOTALL)
    if not match_500:
        match_500 = re.search(r'status.*?500|500.*?internal server error', combined, re.IGNORECASE)

    if match_500:
        guidance = """
🎯 DIAGNOSED: HTTP 500 - Internal Server Error

**Problem**: Server-side error in route implementation
This means the route exists but threw an exception.

**REQUIRED FIX:**
1. Read the test output carefully for stack traces or error messages
2. Look for errors like:
   - Undefined variable/function
   - Database query errors
   - Missing try/catch blocks
3. Read the route handler implementation
4. Fix the bug in the implementation
5. Add proper error handling:
   ```javascript
   try {
     // your code
   } catch (error) {
     console.error(error);
     res.status(500).json({ error: 'Internal server error' });
   }
   ```
"""
        return True, "500", guidance

    # Pattern 3: 401 Unauthorized
    match_401 = re.search(r'Expected.*?(\d{3}).*?Received.*?401', combined, re.IGNORECASE | re.DOTALL)
    if not match_401:
        match_401 = re.search(r'status.*?401|401.*?unauthorized', combined, re.IGNORECASE)

    if match_401:
        guidance = """
🎯 DIAGNOSED: HTTP 401 - Unauthorized

**Problem**: Missing or invalid authentication
This means the endpoint requires authentication that wasn't provided or is invalid.

**REQUIRED FIX:**
1. Check if the test is providing an auth token:
   - Look for: .set('Authorization', `Bearer ${token}`)
2. If test provides token, check the auth middleware in app.js:
   - Verify JWT validation logic
   - Check token secret matches
3. If endpoint should NOT require auth, remove the auth middleware
4. Common auth middleware pattern:
   ```javascript
   const authenticate = (req, res, next) => {
     const token = req.headers.authorization?.split(' ')[1];
     if (!token) return res.status(401).json({ error: 'Unauthorized' });
     // verify token...
     next();
   };
   ```
"""
        return True, "401", guidance

    # Pattern 4: 400 Bad Request
    match_400 = re.search(r'Expected.*?(\d{3}).*?Received.*?400', combined, re.IGNORECASE | re.DOTALL)
    if not match_400:
        match_400 = re.search(r'status.*?400|400.*?bad request', combined, re.IGNORECASE)

    if match_400:
        guidance = """
🎯 DIAGNOSED: HTTP 400 - Bad Request

**Problem**: Request validation failed
This means required fields are missing or invalid.

**REQUIRED FIX:**
1. Check what fields the test is sending
2. Read the route handler to see validation logic
3. Common issues:
   - Missing required fields → Update validation
   - Wrong field names → Fix field names in code
   - Type mismatch → Add proper type conversion
4. Add validation:
   ```javascript
   if (!req.body.email || !req.body.password) {
     return res.status(400).json({ error: 'Missing required fields' });
   }
   ```
"""
        return True, "400", guidance

    return False, "", ""


def _create_error_signature(verification_result) -> str:
    """Create a robust error signature that identifies the root error type.

    This looks beyond just the first line to find the actual error type
    (PrismaClientValidationError, HTTP 404, SyntaxError, etc.)

    Returns:
        Error signature string for deduplication
    """
    import re

    if not verification_result:
        return "unknown_error"

    # Get all error text
    message = getattr(verification_result, 'message', '') or ""
    details = getattr(verification_result, 'details', {})

    # Collect error output
    error_text = message
    if isinstance(details, dict):
        for key in ['test_output', 'stdout', 'stderr', 'output']:
            if key in details:
                val = details[key]
                if isinstance(val, str):
                    error_text += " " + val
                elif isinstance(val, dict) and 'stdout' in val:
                    error_text += " " + val.get('stdout', '') + " " + val.get('stderr', '')
        for key in ["validation", "strict"]:
            nested = details.get(key)
            if isinstance(nested, dict):
                for res in nested.values():
                    if not isinstance(res, dict):
                        continue
                    error_text += " " + str(res.get("stdout", "") or "") + " " + str(res.get("stderr", "") or "")

    # Priority 1: Look for specific error types
    error_patterns = [
        (r'PrismaClientValidationError', 'prisma_validation'),
        (r'PrismaClientInitializationError', 'prisma_init'),
        (r'Cannot find module [\'"]@prisma/client[\'"]', 'prisma_missing'),
        (r'Received.*?HTTP[:\s]+(\d{3})', lambda m: f'http_{m.group(1)}'),  # Match "Received HTTP 404"
        (r'status[:\s]+(\d{3})', lambda m: f'http_{m.group(1)}'),  # Match "status: 404" or "status 404"
        (r'HTTP (\d{3})', lambda m: f'http_{m.group(1)}'),  # Generic HTTP status
        (r'SyntaxError.*line (\d+)', lambda m: f'syntax_error_line_{m.group(1)}'),
        (r'Parsing error.*line (\d+)', lambda m: f'parse_error_line_{m.group(1)}'),
        (r'ModuleNotFoundError.*[\'"](\w+)[\'"]', lambda m: f'module_missing_{m.group(1)}'),
        (r'ImportError.*cannot import.*[\'"](\w+)[\'"]', lambda m: f'import_error_{m.group(1)}'),
        (r'ENOENT.*no such file.*[\'"]([^\'\"]+)[\'"]', lambda m: f'file_missing'),
        (r'FAIL ([\w/\\.-]+)', lambda m: f'test_fail_{m.group(1).split("/")[-1]}'),
    ]

    for pattern, sig_value in error_patterns:
        match = re.search(pattern, error_text, re.IGNORECASE)
        if match:
            if callable(sig_value):
                return sig_value(match)
            return sig_value

    # Priority 2.5: Use failing test file if available (helps avoid generic signatures)
    failing_test_file = _extract_failing_test_file(error_text)
    if failing_test_file:
        return f"test_fail::{failing_test_file}"

    # Priority 3: Use first non-empty line of message
    first_line = message.splitlines()[0].strip() if message else "unknown"

    # Remove variable parts to make signature more generic
    first_line = re.sub(r'\d{4}-\d{2}-\d{2}', 'DATE', first_line)  # Dates
    first_line = re.sub(r'\d+\.\d+s', 'Xs', first_line)  # Durations
    first_line = re.sub(r'\d+ (test|suite)', 'N \\1', first_line)  # Counts

    return first_line[:100]  # Limit length


def _normalize_test_task_signature(task: Task) -> str:
    """Create a stable signature for test tasks to prevent duplicate blocked reruns."""
    desc = (task.description or "").strip()
    if not desc:
        return "test::<empty>"
    explicit_cmd = _extract_explicit_test_command(desc)
    if explicit_cmd:
        signature = explicit_cmd
    else:
        test_path = _extract_test_path_from_text(desc)
        signature = test_path if test_path else desc
    signature = re.sub(r"\s+", " ", signature.strip().lower())
    return f"test::{signature}"


def _normalize_write_task_signature(task: Task) -> str:
    """Create a stable signature for write tasks to prevent repeated no-op retries."""
    paths = _extract_task_paths(task)
    if paths:
        normalized_paths = []
        for path in paths:
            if not path:
                continue
            normalized_paths.append(re.sub(r"\s+", " ", path.strip().lower()))
        if normalized_paths:
            return f"write::{'||'.join(normalized_paths)}"
    target = (task.description or "").strip()
    target = re.sub(r"\s+", " ", target.lower())
    return f"write::{target}"


def _normalize_structure_read_signature(desc: str) -> str:
    """Normalize structure-listing requests so duplicate directory reads can be skipped."""
    if not desc:
        return "structure::<empty>"
    lowered = desc.lower()
    # Detect recursion intent
    recursive = "**" in lowered or "recursive" in lowered or "tree" in lowered

    # Preserve path-like tokens; drop filler words.
    path_matches = re.findall(r"(?:\\.?/?[\\w.-]+/)+(?:[\\w.-]+)?", lowered)
    if path_matches:
        key = path_matches[0]
    else:
        # Capture tokens like "prisma directory", "backend folder", etc.
        dir_token = None
        m = re.search(r"\b([\w.-]+)\s+(?:directory|folder)\b", lowered)
        if m:
            dir_token = m.group(1)
        # Fallback keywords
        if not dir_token:
            for token in ("prisma", "schema", "backend", "frontend", "src", "app", "server", "client", "tests", "test"):
                if token in lowered:
                    dir_token = token
                    break

        if dir_token:
            key = dir_token
        elif "src" in lowered:
            key = "src"
        elif "tests" in lowered or "test" in lowered:
            key = "tests"
        else:
            key = "workspace-root"

    key = re.sub(r"\s+", " ", key.strip("/ "))
    return f"structure::{key}::rec={int(recursive)}"


def _summarize_structure(root: Path, max_entries: int = 50, max_depth: int = 2) -> str:
    """Return a short, depth-limited structure summary for planner context."""
    entries: list[str] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            depth = Path(dirpath).relative_to(root).parts
            if len(depth) > max_depth:
                # Prune deep traversal
                dirnames[:] = []
                continue
            rel_dir = "." if dirpath == str(root) else str(Path(dirpath).relative_to(root))
            for d in sorted(dirnames):
                if d.startswith(".") or d in ("node_modules", ".git", ".rev"):
                    continue
                entries.append(f"{rel_dir}/{d}/")
                if len(entries) >= max_entries:
                    break
            if len(entries) >= max_entries:
                break
            for f in sorted(filenames):
                if f.startswith("."):
                    continue
                entries.append(f"{rel_dir}/{f}")
                if len(entries) >= max_entries:
                    break
            if len(entries) >= max_entries:
                break
    except Exception:
        return ""
    return "\n".join(entries[:max_entries])


def _record_test_signature_state(context: RevContext, signature: str, status: str) -> None:
    """Persist test signature status for the current code-change iteration."""
    state = context.agent_state.get("test_signature_state", {})
    if not isinstance(state, dict):
        state = {}
    last_code_change_iteration = context.agent_state.get("last_code_change_iteration", -1)
    state[signature] = {
        "status": status,
        "code_change_iteration": last_code_change_iteration,
    }
    context.set_agent_state("test_signature_state", state)


def _signature_state_matches(context: RevContext, signature: str, status: str) -> bool:
    state = context.agent_state.get("test_signature_state", {})
    if not isinstance(state, dict):
        return False
    entry = state.get(signature)
    if not isinstance(entry, dict):
        return False
    # If a suite was marked superseded, treat it as matched regardless of iteration.
    if str(entry.get("status")).lower() == "superseded" and status.lower() == "superseded":
        return True
    last_code_change_iteration = context.agent_state.get("last_code_change_iteration", -1)
    entry_change = entry.get("code_change_iteration", -1)
    if not (isinstance(entry_change, int) and isinstance(last_code_change_iteration, int)):
        return False
    if entry_change != last_code_change_iteration:
        return False
    return str(entry.get("status")).lower() == status.lower()


def _extract_explicit_test_command(description: str) -> Optional[str]:
    if not description:
        return None
    desc = description.strip()
    token_pattern = r"\b(npx|npm|yarn|pnpm|vitest|jest|pytest|go test|cargo test|dotnet test)\b"
    candidates: list[str] = []
    for pattern in (r"`([^`]+)`", r"\"([^\"]+)\"", r"'([^']+)'"):
        for match in re.findall(pattern, desc):
            if not match or not match.strip():
                continue
            cleaned = match.strip().rstrip(".;:")
            if re.search(token_pattern, cleaned, re.IGNORECASE):
                candidates.append(cleaned)
    if candidates:
        return max(candidates, key=len)

    token_match = re.search(token_pattern, desc, re.IGNORECASE)
    if token_match:
        candidate = desc[token_match.start():].strip()
        candidate = re.split(r"\s+(?:to|for|on|in|within|inside|under)\s+", candidate, maxsplit=1, flags=re.IGNORECASE)[0]
        candidate = candidate.strip().rstrip(".;:")
        if re.search(token_pattern, candidate, re.IGNORECASE):
            return candidate
    return None


def _extract_test_path_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"([A-Za-z0-9_./\\\\-]+\\.(?:test|spec)\\.[A-Za-z0-9]+)", text)
    if not match:
        return None
    return match.group(1)


def _maybe_correct_explicit_test_command(explicit_cmd: str, description: str) -> str:
    cmd_text = (explicit_cmd or "").strip()
    if not cmd_text:
        return cmd_text
    desc_lower = (description or "").lower()
    test_path = _extract_test_path_from_text(cmd_text) or _extract_test_path_from_text(description)

    try:
        tokens = shlex.split(cmd_text)
    except ValueError:
        tokens = cmd_text.split()
    tokens_lower = [t.lower() for t in tokens]

    vitest_idx = None
    for idx, tok in enumerate(tokens_lower):
        if tok.endswith("vitest") or tok.endswith("vitest.cmd"):
            vitest_idx = idx
            break

    def _has_non_watch_flags() -> bool:
        has_run_flag = any(tok == "--run" or tok.startswith("--run=") for tok in tokens_lower)
        has_run_subcommand = False
        if vitest_idx is not None:
            has_run_subcommand = any(tok == "run" for tok in tokens_lower[vitest_idx + 1 : vitest_idx + 3])
        watch_disabled = any(tok in ("--watch=false", "--watch=0") for tok in tokens_lower)
        if not watch_disabled and "--watch" in tokens_lower:
            for idx, tok in enumerate(tokens_lower):
                if tok == "--watch" and idx + 1 < len(tokens_lower):
                    if tokens_lower[idx + 1] in ("false", "0", "no"):
                        watch_disabled = True
                        break
        return has_run_flag or has_run_subcommand or watch_disabled

    if vitest_idx is not None:
        if _has_non_watch_flags():
            return cmd_text
        if test_path:
            return f"npx vitest run {test_path}"
        return "npx vitest run"

    if "vitest" not in desc_lower:
        return cmd_text

    if tokens_lower and tokens_lower[0] in ("npm", "yarn", "pnpm"):
        if test_path:
            return f"npx vitest run {test_path}"
        return "npx vitest run"

    return cmd_text


def _extract_failing_test_file(error_output: str) -> str:
    """Extract the specific test file that's failing from error output.

    Returns:
        Test file path (e.g., "tests/user.test.js") or empty string if not found
    """
    import re

    # Pattern 1: "FAIL tests/user.test.js"
    match = re.search(r'FAIL\s+([\w/\\.-]+\.(?:test|spec)\.\w+)', error_output)
    if match:
        return match.group(1)

    # Pattern 2: "in C:\path\to\tests\user.test.js:23:23"
    match = re.search(r'in\s+([^\s:]+\.(?:test|spec)\.\w+):\d+:\d+', error_output)
    if match:
        # Extract just the filename and tests/ directory
        full_path = match.group(1)
        if 'tests' in full_path or 'test' in full_path:
            # Extract from tests/ onward
            parts = full_path.replace('\\', '/').split('/')
            if 'tests' in parts:
                idx = parts.index('tests')
                return '/'.join(parts[idx:])
            elif 'test' in parts:
                idx = parts.index('test')
                return '/'.join(parts[idx:])
        return full_path

    # Pattern 3: pytest format "tests/test_user.py::TestClass::test_method FAILED"
    match = re.search(r'([\w/\\.-]+\.py)::\S+\s+FAILED', error_output)
    if match:
        return match.group(1)

    return ""


def _extract_comprehensive_error_context(
    failed_task: "Task",
    verification_result,
    recent_history: list = None
) -> dict:
    """Extract all available error context for generic repair.

    Returns a rich context dict with all information needed for the LLM to diagnose and fix.
    """
    context = {
        "task_description": failed_task.description,
        "task_action_type": failed_task.action_type or "unknown",
        "error_message": "",
        "error_details": {},
        "tool_calls": [],
        "affected_files": [],
        "stdout": "",
        "stderr": "",
        "test_output": "",
        "output": "",
        "failing_test_file": "",  # Add this to track specific failing test
    }

    # Extract error message
    if verification_result:
        context["error_message"] = getattr(verification_result, 'message', '')
        details = getattr(verification_result, 'details', {})
        if isinstance(details, dict):
            context["error_details"] = details

            # Extract test output if available
            for key in ['test_output', 'stdout', 'stderr', 'output']:
                if key in details:
                    val = details[key]
                    if isinstance(val, str):
                        context[key] = val
                    elif isinstance(val, dict) and 'stdout' in val:
                        context['stdout'] = val.get('stdout', '')
                        context['stderr'] = val.get('stderr', '')

    # Extract failing test file from error output
    all_error_text = f"{context['error_message']} {context['stdout']} {context['stderr']} {context['test_output']} {context['output']}"
    context["failing_test_file"] = _extract_failing_test_file(all_error_text)

    # Extract tool events
    if hasattr(failed_task, 'tool_events') and failed_task.tool_events:
        for event in failed_task.tool_events:
            tool_name = event.get('tool', 'unknown')
            args = event.get('args', {})
            result = event.get('result', '')

            context["tool_calls"].append({
                "tool": tool_name,
                "args": args,
                "result": str(result)[:500] if result else ""
            })

            # Extract affected files
            if isinstance(args, dict):
                for key in ['path', 'file_path', 'target', 'source', 'file']:
                    if key in args and isinstance(args[key], str):
                        context["affected_files"].append(args[key])

    # Remove duplicates from affected files
    context["affected_files"] = list(set(context["affected_files"]))

    return context


def _create_generic_repair_task(
    failed_task: "Task",
    verification_result,
    attempt_number: int,
    failure_count: int,
    context=None
) -> "Task":
    """Create a generic repair task that leverages LLM's knowledge to fix ANY error type.

    This is sustainable because it doesn't require adding new code for each tool/framework.
    The LLM already knows how to fix Prisma errors, dependency issues, API mismatches, etc.
    We just need to provide rich context and ask it to analyze and fix.

    Args:
        failed_task: The task that failed
        verification_result: The verification result with error details
        attempt_number: Which repair attempt this is (1-5)
        failure_count: How many times the original task has failed

    Returns:
        A new Task focused on diagnosing and fixing the error
    """
    from rev.models.task import Task
    import json

    # Extract all available context
    error_ctx = _extract_comprehensive_error_context(failed_task, verification_result)

    # Check for specific error patterns in priority order
    # 1. Check Prisma errors first (higher priority - schema issues must be fixed before HTTP tests can pass)
    is_prisma_error, prisma_type, prisma_guidance = _detect_prisma_error_pattern(verification_result)

    # 2. Check HTTP error patterns only if no Prisma error
    is_http_error, http_code, http_guidance = (False, "", "")
    if not is_prisma_error:
        is_http_error, http_code, http_guidance = _detect_http_error_pattern(verification_result)

    # Build a comprehensive prompt for the LLM
    description = (
        f"🔧 AUTOMATIC ERROR RECOVERY (Attempt {attempt_number}/5)\n\n"
        f"The following task has failed {failure_count} times and needs to be fixed:\n\n"
        f"**Original Task:**\n"
        f"[{error_ctx['task_action_type'].upper()}] {error_ctx['task_description']}\n\n"
        f"**Error Summary:**\n"
        f"{error_ctx['error_message']}\n\n"
    )

    # Add specific guidance based on error type (highest priority first)
    if is_prisma_error:
        description += prisma_guidance + "\n\n"
    elif is_http_error:
        description += http_guidance + "\n\n"

    # Add detailed error information
    if error_ctx['stderr']:
        description += f"**Error Output:**\n```\n{error_ctx['stderr'][:1000]}\n```\n\n"
    elif error_ctx['stdout']:
        description += f"**Command Output:**\n```\n{error_ctx['stdout'][:1000]}\n```\n\n"

    if error_ctx['test_output']:
        description += f"**Test Failures:**\n```\n{error_ctx['test_output'][:1000]}\n```\n\n"

    # Add tool call history
    if error_ctx['tool_calls']:
        description += "**What Was Tried:**\n"
        for i, call in enumerate(error_ctx['tool_calls'][-3:], 1):  # Last 3 calls
            description += f"{i}. {call['tool']}({json.dumps(call['args'])})\n"
        description += "\n"

    # Add affected files
    if error_ctx['affected_files']:
        description += f"**Files Involved:** {', '.join(error_ctx['affected_files'])}\n\n"

    # Provide analysis framework
    description += (
        "**YOUR TASK: Analyze and Fix**\n\n"
        "Step 1: DIAGNOSE\n"
        "- Read the error messages carefully\n"
        "- Identify the root cause (missing dependency? schema mismatch? API endpoint? configuration?)\n"
        "- Check if affected files exist and contain what's expected\n\n"

        "Step 2: GATHER CONTEXT\n"
        "- Read any relevant configuration files (package.json, schema.prisma, tsconfig.json, etc.)\n"
        "- Read test files if tests are failing to understand expectations\n"
        "- List directories if files are missing\n\n"

        "Step 3: FIX\n"
        "- Choose the appropriate fix based on your diagnosis:\n"
        "  * Schema mismatch → Update schema file + run migrations\n"
        "  * Missing dependency → Install package\n"
        "  * Missing file/route → Create it\n"
        "  * Configuration error → Update config\n"
        "  * Wrong implementation → Modify code\n\n"

        "Step 4: VERIFY\n"
        "- After fixing, the system will automatically re-run verification\n"
        "- If it still fails, you'll get another attempt with more context\n\n"

        "**IMPORTANT GUIDELINES:**\n"
        "- Be methodical: First understand the error, then fix it\n"
        "- Don't guess - read files to understand current state\n"
        "- Fix the root cause, not symptoms\n"
        "- If you need to run commands (npm install, prisma push, etc.), use the run_cmd tool\n"
        "- This is an automatic recovery system - be thorough but efficient\n"
    )

    # FEEDBACK LOOP: Track error signatures to detect if fix didn't work
    if attempt_number > 1 and context:
        # Create error signature for comparison
        current_error_sig = f"{error_ctx['error_message'][:200]}"

        # Check if this is the same error as last time
        previous_error_sig = context.agent_state.get("last_recovery_error_sig", "")

        if current_error_sig == previous_error_sig:
            # Same error after fix attempt - previous diagnosis was wrong!
            description += (
                f"\n**🔴 CRITICAL - PREVIOUS FIX DID NOT WORK (Attempt {attempt_number}):**\n"
                "The error is EXACTLY THE SAME as before your last fix attempt!\n"
                "This means your previous diagnosis or fix was INCORRECT.\n\n"
                "**YOU MUST:**\n"
                "1. ❌ DO NOT repeat the same fix approach\n"
                "2. ❌ DO NOT edit the same files in the same way\n"
                "3. ✅ Re-read the error with fresh eyes\n"
                "4. ✅ Try a COMPLETELY DIFFERENT approach\n"
                "5. ✅ Question your assumptions about what's broken\n\n"
                f"**What you tried before (from tool history):**\n"
            )

            # Show what was tried before
            if error_ctx['tool_calls']:
                for call in error_ctx['tool_calls'][-2:]:
                    description += f"  - {call['tool']} on {call.get('args', {}).get('path', 'N/A')}\n"

            description += "\n**Think differently this time!**\n\n"
        else:
            # Different error - progress was made
            description += (
                f"\n**⚠️ ATTEMPT {attempt_number} - Partial Progress:**\n"
                "The error changed from the previous attempt, which means you made some progress!\n"
                "However, there's still an issue to fix.\n"
                "- Review what was tried before (see tool call history above)\n"
                "- Build on the progress made\n"
                "- Consider if there are multiple issues that need fixing\n\n"
            )

        # Update error signature for next iteration
        if context:
            context.set_agent_state("last_recovery_error_sig", current_error_sig)
    elif attempt_number > 1:
        # No context available, use basic message
        description += (
            f"\n**⚠️ ATTEMPT {attempt_number}:**\n"
            "Previous repair attempt(s) did not fully resolve the issue.\n"
            "- Review what was tried before (see tool call history above)\n"
            "- Try a different approach or look deeper\n"
            "- Consider if there are multiple issues that need fixing\n"
        )

    # CRITICAL: Add targeted test execution guidance
    if error_ctx.get("failing_test_file"):
        test_file = error_ctx["failing_test_file"]
        description += (
            f"\n**🎯 TARGETED TESTING (IMPORTANT):**\n"
            f"The failing test is: `{test_file}`\n\n"
            f"After fixing, verify ONLY this specific test, not the entire test suite:\n"
            f"- For JavaScript/Node: `npm test -- {test_file}`\n"
            f"- For Python/pytest: `pytest {test_file} -v`\n\n"
            f"**DO NOT** run the full test suite (`npm test` or `pytest`) - it wastes 3+ minutes.\n"
            f"Run ONLY the specific failing test file shown above.\n\n"
        )

    return Task(
        description=description,
        action_type="fix"
    )


def _create_syntax_repair_task(failed_task: "Task", verification_result) -> "Task":
    """Create a focused syntax repair task for the LLM.

    Args:
        failed_task: The task that failed with syntax errors
        verification_result: The verification result containing error details

    Returns:
        A new Task focused on fixing the syntax errors
    """
    from rev.models.task import Task

    # Extract file paths from failed task
    affected_files = set()
    if hasattr(failed_task, 'tool_events') and failed_task.tool_events:
        for event in failed_task.tool_events:
            args = event.get('args', {})
            if isinstance(args, dict):
                for key in ['path', 'file_path', 'target', 'source']:
                    if key in args and isinstance(args[key], str):
                        affected_files.add(args[key])

    files_str = ', '.join(affected_files) if affected_files else "the modified file(s)"

    # Extract specific error details from verification result
    error_details = ""
    if hasattr(verification_result, 'details') and verification_result.details:
        details = verification_result.details
        if isinstance(details, dict):
            # Look for ruff or compileall output
            for key in ['ruff', 'compileall', 'strict']:
                if key in details:
                    val = details[key]
                    if isinstance(val, dict) and 'stdout' in val:
                        error_details = val['stdout'][:500]  # Limit to 500 chars
                        break

    # Create focused repair task description
    description = (
        f"Fix the syntax errors in {files_str}. "
        f"CRITICAL: The code currently has undefined names or syntax errors that prevent it from running. "
        f"You MUST fix ALL syntax errors - missing imports, undefined variables, etc. "
    )

    if error_details:
        description += f"\n\nError details:\n{error_details}"

    description += (
        "\n\nIMPORTANT - Error Scope:\n"
        "- Only fix syntax/import errors in the code YOU modified\n"
        "- If errors appear in unrelated parts of the file, IGNORE them (they are pre-existing)\n"
        "- Focus ONLY on making YOUR specific changes syntactically valid\n\n"
        "Focus ONLY on fixing syntax/import errors in your changes. "
        "Do not make other changes. Ensure all imports are present and all names are defined."
    )

    return Task(
        description=description,
        action_type="fix"
    )


def _attempt_git_revert_for_syntax_errors(task: "Task") -> list[str]:
    """Attempt to revert files affected by a task using git checkout.

    Returns list of successfully reverted file paths, or empty list if revert failed.
    """
    from rev.tools.registry import execute_tool

    # Extract file paths from task events
    files_to_revert = set()
    if hasattr(task, 'tool_events') and task.tool_events:
        for event in task.tool_events:
            # Check for file paths in tool arguments
            args = event.get('args', {})
            if isinstance(args, dict):
                for key in ['path', 'file_path', 'target', 'source']:
                    if key in args and isinstance(args[key], str):
                        files_to_revert.add(args[key])

    if not files_to_revert:
        return []

    reverted = []
    for file_path in files_to_revert:
        try:
            # Use git checkout to revert the file
            result = execute_tool(
                "run_cmd",
                {
                    "cmd": f"git checkout HEAD -- {file_path}",
                    "timeout": 10,
                },
                agent_name="orchestrator",
            )
            if result and "error" not in str(result).lower():
                reverted.append(file_path)
        except Exception:
            # Revert failed for this file, continue with others
            pass

    return reverted


def _extract_task_paths(task: Task) -> list[str]:
    paths: list[str] = []
    if not task:
        return paths
    if task.description:
        from_desc = _extract_file_path_from_description(task.description)
        if from_desc:
            paths.append(from_desc)
    if getattr(task, "tool_events", None):
        for event in task.tool_events:
            args = event.get("args", {})
            if not isinstance(args, dict):
                continue
            for key in ("path", "file_path", "target", "source"):
                val = args.get(key)
                if isinstance(val, str) and val.strip():
                    paths.append(val.strip())
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _sanitize_path_candidate(raw: str) -> str:
    """Extract a filesystem path token from a command-like string."""
    if not raw:
        return ""
    text = raw.strip().strip("`\"'.,;:)")
    path_pattern = r"(?:[A-Za-z]:\\[^\s\"']+|/[^\s\"']+|[\w./\\-]+\.[A-Za-z0-9]{1,6})"
    matches = re.findall(path_pattern, text)
    if not matches:
        return text

    def score(match: str) -> tuple[int, float]:
        has_sep = 1 if ("/" in match or "\\" in match) else 0
        return (has_sep, min(len(match), 100) / 100.0)

    best = max(matches, key=score)
    return best.strip("`\"'.,;:")


def _load_package_json(root: Path) -> dict:
    path = root / "package.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _package_json_scripts(root: Path) -> set[str]:
    data = _load_package_json(root)
    scripts = data.get("scripts", {})
    if not isinstance(scripts, dict):
        return set()
    return {str(key).strip().lower() for key in scripts.keys() if isinstance(key, str)}


def _package_json_deps(root: Path) -> set[str]:
    data = _load_package_json(root)
    deps: set[str] = set()
    for field in ("dependencies", "devDependencies", "peerDependencies"):
        values = data.get(field, {})
        if isinstance(values, dict):
            deps.update({str(key).strip().lower() for key in values.keys() if isinstance(key, str)})
    return deps


def _has_python_markers(root: Path) -> bool:
    return any(
        (root / marker).exists()
        for marker in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")
    )


def _select_js_validation_commands(root: Path) -> list[str]:
    scripts = _package_json_scripts(root)
    deps = _package_json_deps(root)
    candidates: list[str] = []
    if "lint" in scripts:
        candidates.append("npm run lint")
    if "build" in scripts:
        candidates.append("npm run build")
    if "typecheck" in scripts:
        candidates.append("npm run typecheck")
    if not candidates:
        if "eslint" in deps:
            candidates.append("npx eslint .")
        if "vitest" in deps:
            candidates.append("npx vitest run")
    return candidates[:2]


def _select_build_fallback_command(description: str, root: Path) -> Optional[str]:
    desc_lower = (description or "").lower()
    scripts = _package_json_scripts(root)
    deps = _package_json_deps(root)

    if scripts:
        for key in ("build", "compile", "typecheck"):
            if key in scripts:
                return f"npm run {key}"
        if "lint" in scripts and any(token in desc_lower for token in ("lint", "build", "compile", "compilation")):
            return "npm run lint"

    if "typescript" in deps:
        return "npx tsc --noEmit"

    if (root / "go.mod").exists():
        return "go build ./..."
    if (root / "Cargo.toml").exists():
        return "cargo build"
    if (root / "pom.xml").exists():
        return "mvn -q -DskipTests package"
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        if (root / "gradlew").exists():
            return "./gradlew build -x test"
        return "gradle build -x test"
    if any(root.glob("*.csproj")) or any(root.glob("*.sln")):
        return "dotnet build"

    return None


def _select_test_fallback_command(description: str, root: Path) -> Optional[str]:
    desc_lower = (description or "").lower()
    test_path = _extract_test_path_from_text(description)

    if "vitest" in desc_lower:
        if test_path:
            return f"npx vitest run {test_path}"
        return "npx vitest run"

    try:
        from rev.tools.project_types import detect_test_command
        detected = detect_test_command(root)
    except Exception:
        detected = None

    if detected:
        cmd_text = " ".join(detected) if isinstance(detected, list) else str(detected)
        cmd_lower = cmd_text.lower()
        if test_path:
            if "vitest" in cmd_lower:
                if " vitest run" not in cmd_lower and "--run" not in cmd_lower:
                    return f"npx vitest run {test_path}"
                return f"{cmd_text} {test_path}"
            if "jest" in cmd_lower and "--runtestsbypath" not in cmd_lower:
                return f"{cmd_text} --runTestsByPath {test_path}"
            if "pytest" in cmd_lower and test_path not in cmd_lower:
                return f"{cmd_text} {test_path}"
            return f"{cmd_text} {test_path}"
        return cmd_text

    if test_path:
        return f"npx vitest run {test_path}"
    return None


def _build_no_tests_diagnostic_tasks(details: dict) -> list[Task]:
    tasks: list[Task] = []
    test_files = details.get("test_files") if isinstance(details, dict) else []
    if isinstance(test_files, list):
        for path in test_files[:3]:
            if not isinstance(path, str) or not path.strip():
                continue
            tasks.append(
                Task(
                    description=(
                        f"Inspect {path} to confirm it imports vitest APIs "
                        f"(describe/it/test/expect) and defines at least one test case."
                    ),
                    action_type="read",
                )
            )
    tasks.append(
        Task(
            description=(
                "Locate vitest.config.* and verify test.include/test.exclude patterns match the test files "
                "so Vitest discovers and executes them."
            ),
            action_type="review",
        )
    )
    return tasks


def _collect_no_tests_hints(details: dict) -> list[str]:
    hints: list[str] = []
    if not isinstance(details, dict):
        return hints
    debug = details.get("debug")
    if isinstance(debug, dict):
        suspected = debug.get("suspected_issue")
        if isinstance(suspected, str) and suspected.strip():
            hints.append(suspected.strip())
        debug_hints = debug.get("hints")
        if isinstance(debug_hints, list):
            for hint in debug_hints:
                if isinstance(hint, str) and hint.strip():
                    hints.append(hint.strip())
    suspected = details.get("suspected_issue")
    if isinstance(suspected, str) and suspected.strip():
        hints.append(suspected.strip())
    extra_hints = details.get("hints")
    if isinstance(extra_hints, list):
        for hint in extra_hints:
            if isinstance(hint, str) and hint.strip():
                hints.append(hint.strip())
    return hints


def _parse_llm_command_response(content: str) -> Optional[str]:
    if not content:
        return None
    text = content.strip()
    candidates = [text]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            cmd = payload.get("command")
            if isinstance(cmd, str) and cmd.strip():
                return cmd.strip()
            if cmd is None:
                return None
    return None


def _sanitize_recommended_command(cmd: str) -> Optional[str]:
    if not cmd:
        return None
    cleaned = cmd.strip().splitlines()[0].strip()
    if not cleaned:
        return None
    if re.search(r"[;&|><`]|(\$\()", cleaned):
        return None
    lower = cleaned.lower()
    if "prisma migrate dev" in lower and "--name" not in lower:
        suffix = datetime.utcnow().strftime("auto_%Y%m%d_%H%M%S")
        cleaned = f"{cleaned} --name {suffix}"
    return cleaned


def _resolve_hint_command_via_llm(details: dict) -> Optional[str]:
    hints = _collect_no_tests_hints(details)
    if not hints:
        return None
    root = config.ROOT or Path.cwd()
    scripts = sorted(_package_json_scripts(root))
    project_markers = sorted(
        [marker for marker in _PROJECT_MARKERS if (root / marker).exists()]
    )
    output = ""
    if isinstance(details, dict):
        output = str(details.get("output", "") or "")
    debug = details.get("debug") if isinstance(details, dict) else None
    discovered = []
    if isinstance(debug, dict):
        discovered = debug.get("discovered_test_files") or []

    prompt = (
        "You are a command recommendation assistant. "
        "Given the verification hints, recommend ONE shell command to address the root issue. "
        "Return ONLY JSON: {\"command\": \"...\"} or {\"command\": null} if no command should run.\n"
        "Rules: command must be a single shell command with no shell operators (&&, ||, ;, |, >, <). "
        "Prefer existing package.json scripts when applicable.\n\n"
        f"Hints:\n- " + "\n- ".join(hints) + "\n\n"
        f"Discovered test files: {discovered}\n"
        f"Project markers: {project_markers}\n"
        f"Available scripts: {scripts}\n"
        "Last test output (truncated):\n"
        f"{output[:800]}"
    )

    response = ollama_chat(
        [
            {"role": "system", "content": "Return only JSON with a command."},
            {"role": "user", "content": prompt},
        ],
        tools=None,
        model=config.EXECUTION_MODEL,
        supports_tools=False,
        temperature=0.2,
    )
    if not response or "error" in response:
        return None
    content = response.get("message", {}).get("content", "")
    cmd = _parse_llm_command_response(content)
    if not cmd:
        cmd = _extract_explicit_test_command(content)
    return _sanitize_recommended_command(cmd) if cmd else None


def _build_hint_command_tasks(details: dict) -> list[Task]:
    cmd = _resolve_hint_command_via_llm(details)
    if not cmd:
        return []
    return [Task(description=f"Run {cmd}", action_type="run")]


def _build_no_tests_remediation_tasks(details: dict) -> list[Task]:
    tasks = _build_hint_command_tasks(details)
    return tasks


def _maybe_queue_hint_command(
    context: RevContext,
    details: dict,
    *,
    retry_key_prefix: str,
    current_iteration: int,
) -> bool:
    if not isinstance(details, dict):
        return False
    cmd = _resolve_hint_command_via_llm(details)
    if not cmd:
        return False
    cmd_key = f"{retry_key_prefix}::{cmd.lower()}"
    last_code_change_iteration = context.agent_state.get("last_code_change_iteration", -1)
    prior = context.agent_state.get(cmd_key)
    if isinstance(prior, dict):
        prior_code_change = prior.get("code_change_iteration", -1)
        if isinstance(prior_code_change, int) and isinstance(last_code_change_iteration, int) and last_code_change_iteration == prior_code_change:
            return False
    context.set_agent_state(cmd_key, True)
    queued = _queue_diagnostic_tasks(context, [Task(description=f"Run {cmd}", action_type="run")])
    if queued:
        context.set_agent_state(cmd_key, {"code_change_iteration": last_code_change_iteration, "cmd": cmd})
        return True
    return False


def _dedupe_pending_resume_tasks(tasks: list[Task]) -> list[Task]:
    """Avoid repeated reads when resuming from checkpoints."""
    if not tasks:
        return []
    seen_action_sigs: set[str] = set()
    seen_read_targets: set[str] = set()
    deduped: list[Task] = []
    for task in tasks:
        desc = (task.description or "").strip()
        action = (task.action_type or "").strip().lower()
        action_sig = f"{action}::{desc.lower()}"
        if action_sig in seen_action_sigs:
            continue
        if action in {"read", "analyze", "research", "investigate", "review"}:
            target = _extract_file_path_from_description(desc)
            if target:
                normalized = target.replace("\\", "/").lower()
                if normalized in seen_read_targets:
                    continue
                seen_read_targets.add(normalized)
        seen_action_sigs.add(action_sig)
        deduped.append(task)
    return deduped


_PROJECT_MARKERS = {
    "package.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "requirements.txt", "setup.py",
    "go.mod", "Cargo.toml", "Gemfile", "composer.json",
    "pom.xml", "build.gradle", "build.gradle.kts", "Makefile",
}


def _has_project_markers(root: Path) -> bool:
    for marker in _PROJECT_MARKERS:
        if (root / marker).exists():
            return True
    for marker in _PROJECT_MARKERS:
        if any(root.glob(f"*/{marker}")):
            return True
        if any(root.glob(f"*/*/{marker}")):
            return True
    return False


def _scaffold_paths_from_task(task: Task) -> list[str]:
    desc = (task.description or "").lower()
    paths: list[str] = []

    def add(path: str) -> None:
        if not path:
            return
        if re.match(r"^[A-Za-z]:", path) or path.startswith(("/", "\\")):
            return
        if path not in paths:
            paths.append(path)

    for raw in _extract_task_paths(task):
        add(raw)

    if any(token in desc for token in ("vue", "react", "vite", "node", "express", "prisma", "sqlite", "spa")):
        add("package.json")
    if "prisma" in desc:
        add("prisma/schema.prisma")
    if any(token in desc for token in ("vue", "react", "spa")):
        add("src/main.js")
    if any(token in desc for token in ("express", "api", "backend", "server")):
        add("src/app.js")
    if any(token in desc for token in ("readme", "document", "documentation")):
        add("README.md")

    return paths


def _extract_missing_path_from_error(msg: str) -> str:
    """Extract a likely missing TS/JS file path from an error message."""
    if not msg:
        return ""
    pattern = (
        r"(?:failed to load url|cannot find module|cannot find import|module not found|err_module_not_found)"
        r"[^\\n]*?([\\w./\\\\-]+\\.(?:ts|js|mjs|cjs|tsx|jsx))"
    )
    match = re.search(pattern, msg, re.IGNORECASE)
    if match:
        return _sanitize_path_candidate(match.group(1))
    return ""


def _extract_missing_dependencies(msg: str) -> list[str]:
    """Extract missing dependency names from error text."""
    if not msg:
        return []
    deps = set()
    patterns = [
        r"cannot find module ['\"]([^'\"/]+[/\w-]*)['\"]",
        r"failed to load url\s+([@A-Za-z0-9_./-]+)",
        r"module not found.*['\"]([^'\"/]+[/\w-]*)['\"]",
        r"err_module_not_found.*['\"]([^'\"/]+[/\w-]*)['\"]",
    ]
    for pat in patterns:
        for m in re.finditer(pat, msg, re.IGNORECASE):
            candidate = (m.group(1) or "").strip()
            # Skip relative paths and empty
            if not candidate or candidate.startswith((".", "/")):
                continue
            deps.add(candidate)
    return list(deps)


def _build_diagnostic_tasks_for_failure(task: Task, verification_result: Optional[VerificationResult]) -> list[Task]:
    targets = _extract_task_paths(task)
    target_path = _sanitize_path_candidate(targets[0]) if targets else ""
    tasks: list[Task] = []

    # Collect error message/details early for downstream heuristics
    error_message = ""
    if verification_result:
        if verification_result.message:
            error_message = verification_result.message or ""
        if verification_result.details:
            try:
                details_text = json.dumps(verification_result.details)
                if details_text:
                    combined = f"{error_message}\n{details_text}".strip()
                    error_message = combined or error_message
            except Exception:
                pass
    if error_message:
        try:
            context.add_insight("orchestrator", "last_error_output", error_message[:4000])
        except Exception:
            pass

    if verification_result and isinstance(verification_result.details, dict):
        similar_files = verification_result.details.get("similar_files")
        if isinstance(similar_files, list) and similar_files:
            target_path = target_path or verification_result.details.get("file_path") or ""
            primary = str(similar_files[0])
            tasks.append(
                Task(
                    description=(
                        f"Extend existing file {primary} with the new functionality instead of creating a duplicate "
                        f"({target_path or 'new file'})."
                    ),
                    action_type="edit",
                )
            )
            if target_path:
                tasks.append(
                    Task(
                        description=(
                            f"Delete duplicate file {target_path} after merging changes into {primary} to avoid conflicts."
                        ),
                        action_type="delete",
                    )
                )
            return tasks

    # Special handling: Vitest CLI/script errors (e.g., unsupported --runTestsByPath) should trigger a script fix and targeted rerun.
    def _is_vitest_cli_error(vr: Optional[VerificationResult]) -> bool:
        if not vr:
            return False
        msg = (vr.message or "").lower()
        det = str(vr.details or "").lower()
        return ("vitest" in det or "vitest" in msg) and ("cacerror" in det or "unknown option" in det or "--runtestsbypath" in det)

    if _is_vitest_cli_error(verification_result):
        tasks.append(
            Task(
                description=(
                    "Update package.json test script to use a non-watch, single-file Vitest command, e.g., "
                    "\"vitest run tests/user.test.ts\", replacing any invalid flags like --runTestsByPath."
                ),
                action_type="edit",
            )
        )
        tasks.append(
            Task(
                description="Run npx vitest run tests/user.test.ts to verify tests now run without watch/invalid flags.",
                action_type="test",
            )
        )
        # Continue with generic diagnostics below as needed

    # Short-circuit: if hinted_test validation failed, queue the hinted command directly.
    hinted_cmd = ""
    if verification_result and isinstance(verification_result.details, dict):
        val = verification_result.details.get("validation")
        if isinstance(val, dict):
            hinted = val.get("hinted_test")
            if isinstance(hinted, dict):
                hinted_cmd = hinted.get("cmd") or ""
    if hinted_cmd:
        tasks.append(
            Task(
                description=f"Run hinted test command to reproduce failure: {hinted_cmd}",
                action_type="test",
            )
        )
    elif task.action_type and task.action_type.lower() == "test":
        # If we failed a test task (e.g., due to syntax/env), plan to rerun it after the fix.
        tasks.append(
            Task(
                description=f"Re-run the previous test task after fixing the error: {task.description}",
                action_type="test",
            )
        )

    # Detect test failures due to missing/running server (ECONNREFUSED/port issues)
    lower_error = (error_message or "").lower()
    if "econnrefused" in lower_error or "connect econnrefused" in lower_error or "fetch failed" in lower_error:
        tasks.append(
            Task(
                description=(
                    "Refactor tests to run in-memory using a shared app instance (e.g., supertest(app)) without starting a server; "
                    "export the application and avoid hard-coded ports. Allow tests to set PORT/TEST_PORT via env."
                ),
                action_type="edit",
            )
        )
        tasks.append(
            Task(
                description="Run the affected vitest file using in-memory supertest (no dev server) to confirm tests now pass.",
                action_type="test",
            )
        )

    # If a missing dependency is detected, queue an install task.
    missing_deps = _extract_missing_dependencies(error_message)
    installs: list[Task] = []
    for dep in missing_deps:
        # Heuristic: dev deps for common tooling
        is_dev = any(dep.startswith(prefix) for prefix in ("@playwright/", "jest", "ts-jest", "@types/", "vitest"))
        install_cmd = f"npm install{' -D' if is_dev else ''} {dep}"
        installs.append(
            Task(
                description=f"Install missing dependency '{dep}' using \"{install_cmd}\"",
                action_type="run",
            )
        )
    tasks.extend(installs)

    # If we just queued installs or edited test files, enqueue a targeted retest of the primary failing test path.
    primary_test_path = ""
    if verification_result and isinstance(verification_result.details, dict):
        primary_test_path = verification_result.details.get("failing_test") or ""
        if not primary_test_path:
            discovered = verification_result.details.get("discovered_test_files")
            if isinstance(discovered, list) and discovered:
                primary_test_path = discovered[0]
    if primary_test_path and (installs or task.action_type == "edit" and "test" in (task.description or "").lower()):
        if primary_test_path.endswith(".ts") or primary_test_path.endswith(".js"):
            desc = f"Re-run targeted test to validate fixes: npx vitest run {primary_test_path}"
        else:
            desc = f"Re-run targeted test to validate fixes: npm test -- {primary_test_path}"
        tasks.append(
            Task(
                description=desc,
                action_type="test",
            )
        )

    # Syntax blocker: Unterminated string literal - enqueue a direct fix on the failing file.
    if "unterminated string" in error_message.lower():
        target_fix_path = primary_test_path or target_path
        if target_fix_path:
            tasks.append(
                Task(
                    description=(
                        f"Fix unterminated string literal in {target_fix_path}: read the file and correct the invalid string, "
                        "then rerun the targeted test."
                    ),
                    action_type="edit",
                )
            )
            tasks.append(
                Task(
                    description=(
                        f"Re-run targeted test after syntax fix: npx vitest run {target_fix_path}"
                    ),
                    action_type="test",
                )
            )

    # Broader syntax detection (common parser/compiler messages)
    syntax_markers = [
        "syntax error",
        "unterminated string",
        "unexpected token",
        "unexpected end of input",
        "unexpected end of file",
        "unexpected end of json",
        "missing )",
        "missing }",
        "unterminated template literal",
        "unexpected identifier",
        "unexpected reserved word",
        "invalid or unexpected token",
        "parse error",
        "parsing error",
    ]
    syntax_error = any(marker in error_message.lower() for marker in syntax_markers)

    missing_path = _extract_missing_path_from_error(error_message)
    missing_file_error = (
        "not found" in error_message.lower()
        or "does not exist" in error_message.lower()
        or bool(missing_path)
    )
    if missing_file_error and not _has_project_markers(config.ROOT):
        scaffold_paths = _scaffold_paths_from_task(task)
        if scaffold_paths:
            tasks.append(
                Task(
                    description=(
                        "Scaffold missing project files to unblock: "
                        f"{', '.join(scaffold_paths)}. Use write_file to create minimal placeholders."
                    ),
                    action_type="add",
                )
            )

    if missing_path:
        candidate = _sanitize_path_candidate(missing_path)
        if candidate:
            candidate_path = config.ROOT / candidate
            if not candidate_path.exists():
                # If other files with the same name/suffix exist elsewhere, surface them for the LLM to choose.
                try:
                    base_name = Path(candidate).name
                    similar = []
                    for hit in config.ROOT.rglob(base_name):
                        if hit.is_file():
                            rel = str(hit.relative_to(config.ROOT))
                            similar.append(rel)
                    if similar:
                        tasks.append(
                            Task(
                                description=(
                                    f"Found existing files with the same name as missing '{candidate}': {', '.join(similar)}. "
                                    f"Review the best candidate and extend it instead of creating a duplicate."
                                ),
                                action_type="review",
                            )
                        )
                except Exception:
                    pass

                tasks.append(
                    Task(
                        description=(
                            f"Create or fix missing import target '{candidate}' referenced in errors so modules resolve."
                        ),
                        action_type="add",
                    )
                )

    if syntax_error and target_path:
        tasks.append(
            Task(
                description=(
                    f"Fix syntax error in {target_path} by reading the file and correcting the invalid "
                    "code (use read_file then apply_patch or replace_in_file)."
                ),
                action_type="edit",
            )
        )
        build_cmd = _detect_build_command_for_root(config.ROOT or Path.cwd())
        if build_cmd:
            tasks.append(
                Task(
                    description=f"Run build to surface syntax errors and exact locations: {build_cmd}",
                    action_type="run",
                )
            )

    if target_path:
        tasks.append(
            Task(
                description=(
                    f"Use get_file_info on {target_path} to confirm the target exists and "
                    "capture its current state."
                ),
                action_type="review",
            )
        )
        parent = str(Path(target_path).parent) if target_path else "."
    else:
        parent = "."
        tasks.append(
            Task(
                description="Use list_dir on . to locate the target file or directory referenced by the failed task.",
                action_type="review",
            )
        )

    tasks.append(
        Task(
            description=(
                f"Use list_dir on {parent}/tests/** (or {parent}/test/** if none) to check test discovery. "
                "Report which test files exist and whether the expected test path is present."
            ),
            action_type="review",
                )
            )

    # If no heuristics were added but we have error text, fall back to LLM analysis using the raw error.
    if not tasks and error_message:
        tasks.append(
            Task(
                description=(
                    "Analyze the failure using the raw error output and propose the exact fix. "
                    "Error output:\n"
                    f"{error_message[:3500]}"
                ),
                action_type="analyze",
            )
        )

    return tasks


def _summarize_repeated_failure(
    task: Task,
    verification_result: Optional[VerificationResult],
    failure_sig: str,
    count: int,
) -> str:
    message = verification_result.message if verification_result and verification_result.message else "Unknown error"
    tool_summary = ""
    if getattr(task, "tool_events", None):
        last_event = task.tool_events[-1]
        tool_name = last_event.get("tool")
        summary = last_event.get("summary") or ""
        if tool_name:
            tool_summary = f" Last tool: {tool_name}. {summary}".strip()
    return (
        f"Repeated failure signature '{failure_sig}' after {count} attempts. "
        f"Last verification: {message}.{tool_summary} "
        "Please advise on the expected behavior, correct command/path, or missing setup."
    )


def _queue_diagnostic_tasks(context: RevContext, tasks: list[Task]) -> Optional[Task]:
    if not tasks:
        return None
    queue = context.agent_state.get("diagnostic_queue")
    if not isinstance(queue, list):
        queue = []
    last_code_change_iteration = context.agent_state.get("last_code_change_iteration", -1)
    deduped: list[Task] = []
    for task in tasks:
        desc = (task.description or "").strip().lower()
        action = (task.action_type or "").strip().lower()
        sig = f"{action}::{desc}"
        diag_seen = context.agent_state.get("diagnostic_seen", {})
        if not isinstance(diag_seen, dict):
            diag_seen = {}
        prior = diag_seen.get(sig)
        if isinstance(prior, dict):
            prior_change = prior.get("code_change_iteration", -1)
            if isinstance(prior_change, int) and isinstance(last_code_change_iteration, int) and last_code_change_iteration == prior_change:
                continue
        diag_seen[sig] = {"code_change_iteration": last_code_change_iteration}
        context.set_agent_state("diagnostic_seen", diag_seen)
        deduped.append(task)

    if not deduped:
        return None

    for task in deduped[1:]:
        queue.append({"description": task.description, "action_type": task.action_type})
    context.agent_state["diagnostic_queue"] = queue
    return deduped[0] if deduped else None


def _pop_diagnostic_task(context: RevContext) -> Optional[Task]:
    queue = context.agent_state.get("diagnostic_queue")
    if not isinstance(queue, list) or not queue:
        return None
    entry = queue.pop(0)
    context.agent_state["diagnostic_queue"] = queue
    if not isinstance(entry, dict):
        return None
    return Task(description=entry.get("description", ""), action_type=entry.get("action_type", "review"))


def _check_goal_likely_achieved(user_request: str, completed_tasks_log: List[str]) -> bool:
    """Check if the original goal appears to have been achieved based on completed tasks.

    Looks for evidence of successful tool executions that match the user request intent.
    Returns True if goal appears achieved, False otherwise.
    """
    if not completed_tasks_log:
        return False

    request_lower = user_request.lower()

    # Key patterns that indicate goal-completing tool executions
    goal_indicators = []

    # For splitting/breaking out files
    if any(kw in request_lower for kw in ['split', 'break out', 'separate', 'extract']):
        goal_indicators.extend([
            'split_python_module_classes',
            '"classes_split"',
            '"created_files"',
            'classes_split',
        ])

    # For refactoring
    if 'refactor' in request_lower:
        goal_indicators.extend([
            'refactor',
            'write_file',
            'replace_in_file',
        ])

    # For creating directories/packages
    if any(kw in request_lower for kw in ['package', 'directory', 'create']):
        goal_indicators.extend([
            'create_directory',
            '__init__.py',
            'package_init',
        ])

    if not goal_indicators:
        # Can't determine goal type, don't force completion
        return False

    # Check completed tasks for evidence of goal achievement
    completed_count = 0
    goal_evidence = 0

    for log_entry in completed_tasks_log:
        if not log_entry.startswith('[COMPLETED]'):
            continue
        completed_count += 1

        log_lower = log_entry.lower()
        for indicator in goal_indicators:
            if indicator.lower() in log_lower:
                goal_evidence += 1
                break

    # If we have completed tasks with goal evidence, assume goal is achieved
    # Require at least one completed task with goal evidence
    return goal_evidence >= 1 and completed_count >= 1


from rev.tools.workspace_resolver import normalize_path, normalize_to_workspace_relative, WorkspacePathError


def _append_task_tool_event(task: Task, result_payload: Any) -> None:
    """Best-effort: extract tool execution evidence and attach to task.tool_events.

    Sub-agents often return standardized JSON (see rev/agents/subagent_io.py).
    Persisting tool evidence on the Task lets quick_verify validate what actually ran
    instead of guessing from task text or global "last tool call" state.
    """
    payload: Optional[Dict[str, Any]] = None
    if isinstance(result_payload, dict):
        payload = result_payload
    elif isinstance(result_payload, str):
        try:
            parsed = json.loads(result_payload)
            payload = parsed if isinstance(parsed, dict) else None
        except Exception:
            payload = None

    if not payload:
        return

    tool_name = payload.get("tool_name")
    tool_args = payload.get("tool_args")
    tool_output = payload.get("tool_output")
    evidence = payload.get("evidence")

    if not isinstance(tool_name, str) or not tool_name.strip():
        return

    artifact_ref = None
    summary = None
    if isinstance(evidence, list) and evidence and isinstance(evidence[0], dict):
        artifact_ref = evidence[0].get("artifact_ref")
        summary = evidence[0].get("summary")

    if not hasattr(task, "tool_events") or task.tool_events is None:
        task.tool_events = []

    task.tool_events.append(
        {
            "tool": tool_name,
            "args": tool_args if isinstance(tool_args, dict) else {"args": tool_args},
            "raw_result": tool_output,
            "artifact_ref": artifact_ref,
            "summary": summary,
        }
    )


def _did_run_real_tests(task: Task, verification_result: Optional["VerificationResult"]) -> bool:
    """Heuristic: did this test task actually run tests (not installs/lint)?"""
    try:
        events = getattr(task, "tool_events", None) or []
        for ev in events:
            tool = str(ev.get("tool") or "").lower()
            if tool == "run_tests":
                return True
            if tool == "run_cmd":
                cmd = str(ev.get("args", {}).get("cmd") or "")
                cmd_lower = cmd.lower()
                if any(tok in cmd_lower for tok in ("vitest", "jest", "pytest", "npm test", "pnpm test", "yarn test")):
                    return True
        details = getattr(verification_result, "details", {}) if verification_result else {}
        if isinstance(details, dict):
            cmd = str(details.get("command") or details.get("cmd") or "")
            cmd_lower = cmd.lower()
            if any(tok in cmd_lower for tok in ("vitest", "jest", "pytest", "npm test", "pnpm test", "yarn test")):
                return True
    except Exception:
        pass
    return False


def _enforce_action_tool_constraints(task: Task) -> tuple[bool, Optional[str]]:
    """Ensure write actions actually execute a write tool."""
    action = (task.action_type or "").lower()
    if action not in WRITE_ACTIONS and action != "test":
        return True, None

    # Special-case policy blocks to avoid treating them as tool-execution failures.
    result_text = ""
    if isinstance(task.result, str):
        result_text = task.result.lower()
    if "write_file_overwrite_blocked" in result_text or "path_conflict" in result_text:
        return False, "Write action blocked by overwrite policy"

    events = getattr(task, "tool_events", None) or []
    if not events:
        if action == "test":
            return False, "Test action completed without tool execution"
        return False, "Write action completed without tool execution"

    tool_names = [str(ev.get("tool") or "").lower() for ev in events]
    if action == "test":
        if not any(name in {"run_cmd", "run_tests"} for name in tool_names):
            return False, "Test action completed without run_cmd/run_tests execution"
        return True, None
    if not has_write_tool(tool_names):
        return False, "Write action completed without write tool execution"

    return True, None


def _should_coerce_read_only(action_type: Optional[str]) -> bool:
    action = (action_type or "").lower()
    if not action:
        return True
    return action not in {"review", "read", "analyze", "research", "investigate"}


def _find_workspace_matches_by_basename(*, root: Path, basename: str, limit: int = 25) -> List[str]:
    """Return workspace-relative POSIX paths matching basename."""
    if not basename:
        return []

    basename_lower = basename.lower()
    hits: List[str] = []
    # Avoid scanning transient/internal directories.
    exclude = set(getattr(config, "EXCLUDE_DIRS", set())) | {
        ".rev",
        ".pytest_cache",
        ".pytest_tmp",
        "tmp_test",
        "artifacts",
        "cache",
        "logs",
        "sessions",
        "__pycache__",
    }

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories in-place.
        dirnames[:] = [d for d in dirnames if d not in exclude]
        for fn in filenames:
            if fn.lower() != basename_lower:
                continue
            try:
                rel = Path(dirpath, fn).resolve().relative_to(root.resolve()).as_posix()
            except Exception:
                continue
            hits.append(rel)
            if len(hits) >= limit:
                return hits
    return hits


def _choose_best_path_match(*, original: str, matches: List[str]) -> Optional[str]:
    """Pick the most likely intended match, or None if ambiguous."""
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    original_lower = original.replace("\\", "/").lower()

    def _score(rel_posix: str) -> tuple[int, int]:
        p = rel_posix.lower()
        score = 0
        
        # Prefer typical source roots.
        # Use dynamic discovery to identify common source patterns.
        source_roots = ["/src/", "/lib/", "/app/", "/core/", "/pkg/"]
        test_roots = ["/tests/", "/test/", "/spec/"]
        
        for root in source_roots:
            if root in f"/{p}/":
                score += 8
                break
        
        for root in test_roots:
            if root in f"/{p}/":
                score -= 5
                break
                
        # Prefer matches that end with the original (e.g., missing prefix).
        if original_lower and p.endswith(original_lower):
            score += 3
        # Slightly prefer shallower paths to avoid deep vendor/test duplicates.
        depth = p.count("/")
        return (score, -depth)

    ranked = sorted(matches, key=_score, reverse=True)
    best = ranked[0]
    if _score(best)[0] == _score(ranked[1])[0]:
        return None
    return best


def _choose_best_path_match_with_context(*, original: str, matches: List[str], description: str) -> Optional[str]:
    """Pick the most likely intended match, using description text to break ties."""
    chosen = _choose_best_path_match(original=original, matches=matches)
    if chosen or not matches or len(matches) == 1:
        return chosen

    desc = (description or "").replace("\\", "/").lower()
    if not desc:
        return None

    def _context_score(rel_posix: str) -> tuple[int, int, int]:
        p = rel_posix.replace("\\", "/").lower()
        parent = Path(p).parent.as_posix().lower()
        score = 0

        # Strongest signal: the full parent path appears in the description.
        if parent and parent != ".":
            needle = f"/{parent.strip('/')}/"
            hay = f"/{desc.strip('/')}/"
            if needle in hay:
                score += 50 + len(parent)

        # Secondary: directory/file names appear in the description.
        for part in Path(p).parts:
            part_l = str(part).lower()
            if part_l and part_l != "." and part_l in desc:
                score += 2

        # Penalize obviously duplicated segment paths.
        parts = Path(p).parts
        for i in range(1, len(parts)):
            if parts[:i] == parts[i : 2 * i] and len(parts) >= 2 * i + 1:
                score -= 25
                break

        depth = p.count("/")
        return (score, depth, len(p))

    ranked = sorted(matches, key=_context_score, reverse=True)
    if _context_score(ranked[0])[0] == _context_score(ranked[1])[0]:
        return None
    return ranked[0]


def _find_path_matches(root: Path, basename: str, limit: int = 50) -> List[Path]:
    """Find files matching a basename under a root path (case-insensitive)."""
    matches: List[Path] = []
    basename_lower = basename.lower()
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower() == basename_lower:
                matches.append(Path(dirpath) / fn)
                if len(matches) >= limit:
                    return matches
    return matches


def _coerce_command_intent_to_test(task: Task) -> tuple[bool, List[str]]:
    """Coerce command execution tasks (npm install, pip install, etc.) to action_type='run'.

    This ensures they are routed to TestExecutorAgent which has access to run_cmd tool.
    This function ALWAYS runs, regardless of PREFLIGHT_ENABLED setting.

    Returns:
        (ok_to_execute, messages)
    """
    action = (task.action_type or "").strip().lower()
    desc = (task.description or "").strip()
    if not action or not desc:
        return True, []

    # Skip if already routed to command/test executor
    if action in {"test", "tool", "run", "execute"}:
        return True, []

    def _is_explicit_command_invocation(text: str) -> bool:
        if not text:
            return False
        return bool(
            re.search(
                r"^\s*(?:run|execute|run_cmd)\b|^\s*(?:npm|yarn|pnpm|pip|pipenv|poetry|conda|bundle|composer|"
                r"apt-get|apt|brew|choco|winget|yum|dnf|apk|pacman|zypper)\b",
                text,
            )
        )

    # Detect command execution intent
    desc_l = desc.lower()
    command_intent = bool(
        re.search(
            r"\b(run_cmd|run_terminal_command|run_tests|execute command|install|npm install|npm ci|yarn install|"
            r"pnpm install|pip install|pipenv install|poetry install|pipx install|conda install|bundle install|composer install|"
            r"apt-get|apt install|brew install|choco install|winget install|yum install|dnf install|apk add|pacman -S|zypper install)\b",
            desc_l,
        )
    )

    # Do not coerce read-only tasks unless the description is an explicit command invocation.
    if action in {"read", "analyze", "research", "review"} and not _is_explicit_command_invocation(desc_l):
        return True, []

    if command_intent:
        prev = action
        task.action_type = "run"
        try:
            from rev.debug_logger import get_logger
            get_logger().log_transaction_event("ACTION_COERCED", {
                "previous_action": prev,
                "new_action": task.action_type,
                "reason": "command_execution",
                "description": task.description,
            })
        except Exception:
            pass
        return True, [f"coerced action '{prev}' -> 'run' (command execution task)"]

    return True, []


def _preflight_correct_action_semantics(task: Task) -> tuple[bool, List[str]]:
    """Coerce overloaded actions into read-only vs mutating actions.

    NOTE: Command coercion (npm install -> test) is now handled separately in
    _coerce_command_intent_to_test() which ALWAYS runs.

    Returns:
        (ok_to_execute, messages)
    """
    action = (task.action_type or "").strip().lower()
    desc = (task.description or "").strip()
    if not action or not desc:
        return True, []

    mutate_actions = {"edit", "add", "create", "create_directory", "refactor", "delete", "rename", "fix"}
    read_actions = {"read", "analyze", "review", "research"}

    # Heuristic intent detection (word-boundary based to avoid false positives like
    # matching "analy" inside "analysis").
    desc_l = desc.lower()
    read_intent = bool(
        re.search(
            r"\b(read|inspect|review|analyze|analysis|understand|locate|find|search|inventory|identify|list|show|explain)\b",
            desc_l,
        )
    )
    write_intent = bool(
        re.search(
            r"\b(edit|update|modify|change|refactor|remove|delete|rename|create|add|write|generate|apply)\b"
            r"|split_python_module_classes|replace_in_file|write_file|apply_patch|append_to_file|create_directory",
            desc_l,
        )
    )

    messages: List[str] = []

    # If action says mutate but description is clearly inspection-only, coerce to READ.
    if action in mutate_actions and read_intent and not write_intent:
        task.action_type = "read"
        messages.append(f"coerced action '{action}' -> 'read' (inspection-only task)")
        try:
            from rev.debug_logger import get_logger
            get_logger().log_transaction_event("ACTION_COERCED", {
                "previous_action": action,
                "new_action": task.action_type,
                "reason": "inspection_only",
                "description": task.description,
            })
        except Exception:
            pass
        return True, messages

    # If action says read-only but description includes mutation verbs, fail fast to replan.
    if action in read_actions and write_intent and not read_intent:
        messages.append(f"action '{action}' conflicts with write intent; choose edit/refactor instead")
        try:
            from rev.debug_logger import get_logger
            get_logger().log_transaction_event("ACTION_CONFLICT", {
                "action": action,
                "reason": "read_action_with_write_intent",
                "description": task.description,
            })
        except Exception:
            pass
        return False, messages

    return True, messages


def _order_available_actions(actions: List[str]) -> List[str]:
    """Return actions ordered to bias the lightweight planner toward READ first."""
    cleaned: List[str] = []
    for a in actions:
        if not isinstance(a, str):
            continue
        a = a.strip().lower()
        if not a:
            continue
        if a not in cleaned:
            cleaned.append(a)

    # Priority buckets: smaller comes earlier.
    priorities: dict[str, int] = {
        # Read-only first (better stability)
        "read": 0,
        "analyze": 1,
        "review": 2,
        "research": 3,
        "investigate": 3,
        "set_workdir": 4,
        # Then mutating actions
        "create_directory": 10,
        "add": 11,
        "edit": 12,
        "refactor": 13,
        "delete": 14,
        "rename": 15,
        "fix": 16,
        # Then execution actions
        "test": 30,
        # Advanced tooling last
        "create_tool": 40,
        "tool": 41,
        # Legacy shim last-last
        "general": 90,
    }

    def _key(a: str) -> tuple[int, int, str]:
        return (priorities.get(a, 50), cleaned.index(a), a)

    return sorted(cleaned, key=_key)


def _is_goal_achieved_response(response: Optional[str]) -> bool:
    """Detect when the planner says the goal is already achieved.
    
    Strictly matches 'GOAL_ACHIEVED' or clear variations like 'Goal achieved'
    while avoiding false positives on rambling text.
    """
    if not response:
        return False
    # Remove brackets, underscores, and extra whitespace
    normalized = re.sub(r"[\[\]_\s]+", " ", response).strip().lower()
    if not normalized:
        return False
    
    # Precise matches only
    if normalized in {"goal achieved", "goal completed", "work complete", "task achieved"}:
        return True
        
    # Allow slightly longer but still very clear success statements
    if normalized.startswith("goal "):
        # Must be exactly 'goal achieved', 'goal is achieved', etc.
        return bool(re.match(r"^goal (is )?(achieved|completed|done|finished)$", normalized))
        
    return normalized == "goal achieved"


def _dedupe_redundant_prefix_path(norm_path: str, project_root: Path) -> Optional[str]:
    """
    Collapse accidental repeated leading segments like
    'src/module/src/module/__init__.py' into the shortest suffix.
    This prevents recursive path drift when planners keep appending the same subpath.
    """
    if not norm_path:
        return None

    parts = list(Path(norm_path.replace("/", os.sep)).parts)
    # Need at least X/Y/X/Y (4 segments) to consider it a duplicated prefix.
    if len(parts) < 4:
        return None

    changed = False
    while len(parts) >= 4:
        reduced = False
        for prefix_len in range(1, len(parts) // 2 + 1):
            prefix = parts[:prefix_len]
            if parts[prefix_len : 2 * prefix_len] == prefix:
                parts = parts[prefix_len:]
                changed = True
                reduced = True
                break
        if not reduced:
            break

    if not changed:
        return None

    candidate = Path(*parts)
    try:
        if not candidate.is_absolute():
            candidate_abs = (project_root / candidate).resolve(strict=False)
        else:
            candidate_abs = candidate
    except Exception:
        return None

    if not candidate_abs.exists():
        return None

    try:
        return normalize_to_workspace_relative(candidate_abs, workspace_root=project_root)
    except Exception:
        return str(candidate_abs).replace("\\", "/")


def _preflight_correct_task_paths(*, task: Task, project_root: Path) -> tuple[bool, List[str]]:
    """Best-effort path correction for lightweight planner outputs.

    Returns:
        (ok_to_execute, messages)
    """
    desc = task.description or ""
    messages: List[str] = []
    action = (task.action_type or "").strip().lower()
    read_actions = {"read", "analyze", "review", "research", "investigate"}

    # Match path candidates with any common source/config extension.
    ext = r"(?:py|js|ts|json|yaml|yml|md|txt|toml|cfg|ini|c|cpp|h|hpp|rs|go|rb|php|java|cs|sql|sh|bat|ps1)"
    # A more robust regex to find path-like strings, including those not perfectly formed.
    path_pattern = rf'((?:[A-Za-z]:)?[\\/]?[\w\s._-]*[\\/]+[\w\s._-]+\.{ext}\b|[\w._-]+\.{ext}\b)'
    
    raw_candidates = re.findall(path_pattern, desc)
    
    # Clean up and deduplicate candidates
    candidates = sorted(
        set(
            p.strip() for p in raw_candidates if p.strip()
        )
    )
    if not candidates:
        return True, messages

    def _abs_for_normalized(norm: str) -> Optional[Path]:
        """Resolve a normalized path to an absolute path for existence checks.

        Prefer project_root for relative paths (planner preflight) to avoid
        split-brain issues if Workspace isn't initialized yet.
        """
        p = Path(norm.replace("/", os.sep))
        if not p.is_absolute():
            return (project_root / p).resolve(strict=False)
        try:
            return resolve_workspace_path(norm, purpose="preflight").abs_path
        except WorkspacePathError:
            return None

    existing_any = 0
    missing_unresolved: List[str] = []

    for raw in candidates:
        normalized = normalize_path(raw)

        deduped = _dedupe_redundant_prefix_path(normalized, project_root=project_root)
        if deduped and deduped != normalized:
            if raw in desc:
                desc = desc.replace(raw, deduped)
            if normalized in desc:
                desc = desc.replace(normalized, deduped)
            messages.append(f"normalized duplicated path '{raw}' -> '{deduped}'")
            normalized = deduped

        abs_path = _abs_for_normalized(normalized)
        if abs_path is None:
            # Leave it to the main allowlist error path.
            continue

        if abs_path.exists():
            existing_any += 1
            # Canonicalize absolute paths to workspace-relative for future tool calls.
            rel = normalize_to_workspace_relative(abs_path, workspace_root=project_root)
            if rel and rel != normalized and raw in desc:
                desc = desc.replace(raw, rel)
                messages.append(f"normalized path '{raw}' -> '{rel}'")
            continue

        # Missing path: try to locate by basename.
        basename = Path(normalized.replace("/", os.sep)).name
        basenames = [basename]
        # Common tool behavior: keep backups as *.py.bak
        if basename.lower().endswith(".py") and not basename.lower().endswith(".py.bak"):
            basenames.append(basename + ".bak")
        if basename.lower().endswith(".py.bak"):
            basenames.append(basename[: -len(".bak")])

        # Check if a .py file was split into a package (directory with __init__.py)
        # e.g., src/module.py -> src/module/__init__.py
        package_init_match: Optional[str] = None
        if basename.lower().endswith(".py") and not basename.lower().endswith(".py.bak"):
            # Look for a package directory with the same name (without .py extension)
            parent_dir = Path(normalized.replace("/", os.sep)).parent
            package_name = basename[:-3]  # Remove .py
            package_dir = parent_dir / package_name if str(parent_dir) != "." else Path(package_name)
            package_init = package_dir / "__init__.py"
            package_init_abs = (project_root / package_init).resolve(strict=False)
            if package_init_abs.exists():
                try:
                    package_init_match = normalize_to_workspace_relative(package_init_abs, workspace_root=project_root)
                except Exception:
                    package_init_match = str(package_init).replace("\\", "/")

        matches: List[str] = []
        for bn in basenames:
            matches.extend(_find_workspace_matches_by_basename(root=project_root, basename=bn))
        matches = sorted(set(matches))
        primary_matches = [m for m in matches if not m.endswith(".bak")]
        backup_matches = [m for m in matches if m.endswith(".bak")]

        # Prefer package __init__.py over backup when a file was split into a package
        if package_init_match and not primary_matches:
            chosen = package_init_match
            messages.append(f"resolved missing path to package '{chosen}' (file was split into package)")
            if raw in desc:
                desc = desc.replace(raw, chosen)
            existing_any += 1
            continue

        # Prefer real sources over backups; avoid auto-operating on backups for mutating actions.
        preferred_pool = primary_matches if primary_matches else matches
        chosen = _choose_best_path_match_with_context(original=normalized, matches=preferred_pool, description=desc)

        # If the planner only emitted a bare filename (e.g., "__init__.py") and
        # there are multiple matches in the workspace, avoid "helpfully" picking
        # one and accidentally duplicating a path (src/module/src/module/...).
        if not ("/" in normalized or "\\" in normalized) and len(preferred_pool) > 1 and not chosen:
            missing_unresolved.append(
                f"ambiguous missing path '{raw}' (multiple candidates for bare filename)"
            )
            continue

        if not chosen and backup_matches and not primary_matches and action not in read_actions:
            missing_unresolved.append(
                f"missing path '{raw}' (only backup(s) found: {backup_matches[:3]})"
            )
            continue
        if chosen:
            if chosen.endswith(".bak") and action not in read_actions:
                missing_unresolved.append(
                    f"missing path '{raw}' (only backup found: {chosen}; restore original before mutating)"
                )
                continue

            # If the resolved path already appears in the description, avoid
            # duplicating segments like "src/module/src/module/__init__.py".
            if chosen in desc:
                messages.append(
                    f"resolved missing path to '{chosen}' (already present; left unchanged)"
                )
                existing_any += 1
                continue

            # Check if replacing 'raw' with 'chosen' would create a redundant path.
            # e.g. if desc contains 'src/module.py' and we replace 'module.py' with 'src/module.py'
            # we get 'src/src/module.py'.
            if f"/{raw}" in desc.replace("\\", "/") or f"\\{raw}" in desc:
                # If it's already prefixed by something, check if that prefix matches the 'chosen' path's head.
                # If it does, we should just consider it resolved and not replace.
                if chosen in desc.replace("\\", "/").replace("//", "/"):
                     messages.append(
                        f"resolved missing path to '{chosen}' (already present as suffix; left unchanged)"
                    )
                     existing_any += 1
                     continue

            # Use regex with word boundaries to avoid replacing partial segments of other paths.
            # We escape regex special characters in the raw/normalized strings.
            replaced = False
            for target in sorted({raw, normalized}, key=len, reverse=True):
                if target in desc:
                    pattern = r'(?<![A-Za-z0-9_./\\])' + re.escape(target) + r'(?![A-Za-z0-9_./\\])'
                    new_desc, count = re.subn(pattern, chosen.replace('\\', '\\\\'), desc)
                    if count > 0:
                        desc = new_desc
                        replaced = True
            
            if replaced:
                messages.append(f"resolved missing path to '{chosen}' (requested '{raw}')")
                existing_any += 1
                continue

        if matches:
            missing_unresolved.append(f"ambiguous missing path '{raw}' (matches={matches[:5]})")
        else:
            missing_unresolved.append(f"missing path '{raw}' (no matches found)")

    # Final cleanup pass to dedupe any paths that were constructed during replacement.
    final_candidates = sorted(
        set(
            re.findall(
                r'([A-Za-z]:[\\/][^\s"\'`]+\.py(?:\.bak)?\b|(?:\./)?[A-Za-z0-9_./\\-]+\.py(?:\.bak)?\b)',
                desc,
            )
        )
    )
    for cand in final_candidates:
        deduped = _dedupe_redundant_prefix_path(cand, project_root=project_root)
        if deduped and deduped != cand:
            desc = desc.replace(cand, deduped)
            messages.append(f"cleaned up duplicated path segment in '{cand}' -> '{deduped}'")

    task.description = desc

    if not missing_unresolved:
        return True, messages

    # READ-like tasks should not reference missing files.
    if action in read_actions:
        messages.extend(missing_unresolved[:1])
        return False, messages

    # Mutating tasks commonly mention output paths that don't exist yet; only fail
    # if NONE of the referenced paths could be resolved to an existing file.
    if existing_any == 0:
        messages.extend(missing_unresolved[:1])
        return False, messages

    # Otherwise, allow execution to proceed (best-effort). Avoid spamming logs.
    messages.append("ignored missing output path(s); at least one input path exists")
    return True, messages


def _generate_path_hints(completed_tasks_log: List[str]) -> str:
    """Extract important paths from recent tool outputs to help the planner."""
    if not completed_tasks_log:
        return ""
    
    hints = []
    # Look for paths in the last 5 tasks
    for log in completed_tasks_log[-5:]:
        # Extract paths mentioned in "Output:" segments
        if "Output:" in log:
            output_part = log.split("Output:", 1)[1]
            # Match likely file paths (with common extensions) or directory-looking paths
            # 1. Paths with extensions (py, json, etc)
            # 2. Paths ending in / or \
            # 3. Quoted strings that look like relative paths
            matches = re.findall(r'([A-Za-z0-9_./\\-]+\.(?:py|json|md|txt|csv|bak|log)\b)|([A-Za-z0-9_./\\-]+[/\\])|(?:"|\')(\./[A-Za-z0-9_./\\-]+)(?:"|\')', output_part)
            for m_tuple in matches:
                # findall with multiple groups returns tuples
                for m in m_tuple:
                    if m and ("/" in m or "\\" in m):
                        hints.append(m.strip('"\''))
                    
    if not hints:
        return ""
        
    unique_hints = sorted(set(hints))
    return "\nPATH HINTS (use these exact paths if relevant):\n" + "\n".join(f"- {h}" for h in unique_hints) + "\n"


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator."""
    enable_learning: bool = False
    enable_research: bool = True
    enable_review: bool = True
    enable_validation: bool = True
    review_strictness: ReviewStrictness = ReviewStrictness.MODERATE
    enable_action_review: bool = False
    enable_auto_fix: bool = False
    parallel_workers: int = 1
    auto_approve: bool = True
    research_depth: Literal["off", "shallow", "medium", "deep"] = RESEARCH_DEPTH_DEFAULT
    validation_mode: Literal["none", "smoke", "targeted", "full"] = VALIDATION_MODE_DEFAULT
    orchestrator_retries: int = MAX_ORCHESTRATOR_RETRIES
    plan_regen_retries: int = MAX_PLAN_REGEN_RETRIES
    validation_retries: int = MAX_VALIDATION_RETRIES
    adaptive_replan_attempts: int = MAX_ADAPTIVE_REPLANS
    # Prompt optimization
    enable_prompt_optimization: bool = True
    auto_optimize_prompt: bool = False
    # ContextGuard configuration
    enable_context_guard: bool = True
    context_guard_interactive: bool = True
    context_guard_threshold: float = 0.3
    # Back-compat shim (legacy)
    max_retries: Optional[int] = None
    max_plan_tasks: int = MAX_PLAN_TASKS
    max_planning_iterations: int = config.MAX_PLANNING_TOOL_ITERATIONS

    def __post_init__(self):
        if self.max_retries is not None:
            self.orchestrator_retries = self.max_retries
            self.plan_regen_retries = self.max_retries
            self.validation_retries = self.max_retries
            self.adaptive_replan_attempts = self.max_retries


@dataclass
class OrchestratorResult:
    """Result of an orchestrated execution."""
    success: bool
    phase_reached: AgentPhase
    plan: Optional[ExecutionPlan] = None
    research_findings: Optional[ResearchFindings] = None
    review_decision: Optional[ReviewDecision] = None
    validation_status: Optional[ValidationStatus] = None
    execution_time: float = 0.0
    resource_budget: Optional[ResourceBudget] = None
    agent_insights: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    no_retry: bool = False
    run_mode: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "phase_reached": self.phase_reached.value,
            "review_decision": self.review_decision.value if self.review_decision else None,
            "validation_status": self.validation_status.value if self.validation_status else None,
            "execution_time": self.execution_time,
            "resource_budget": self.resource_budget.to_dict() if self.resource_budget else None,
            "agent_insights": self.agent_insights,
            "errors": self.errors
        }


class Orchestrator:
    """Coordinates all agents for autonomous task execution."""

    def __init__(self, project_root: Path, config_obj: Optional[OrchestratorConfig] = None):
        self.project_root = project_root
        self._user_config_provided = config_obj is not None
        self.config = config_obj or OrchestratorConfig()
        self.context: Optional[RevContext] = None
        self.learning_agent = LearningAgent(project_root) if self.config.enable_learning else None
        self.debug_logger = DebugLogger.get_instance()
        self._context_builder: Optional[ContextBuilder] = None
        self._project_roots_cache: Optional[List[Path]] = None
        if config.WORKSPACE_ROOT_ONLY:
            workspace = get_workspace()
            workspace.current_working_dir = workspace.root

    def _apply_read_only_constraints(self, task: Task) -> Task:
        if not self.context or not getattr(self.context, "read_only", False):
            return task
        if not _should_coerce_read_only(task.action_type):
            return task

        task.action_type = "review"
        if task.description:
            if not task.description.lower().startswith("read-only"):
                task.description = f"Read-only analysis: {task.description}"
        else:
            task.description = "Read-only analysis"
        return task

    def _update_phase(self, new_phase: AgentPhase):
        if self.context:
            self.context.set_current_phase(new_phase)
            if config.EXECUTION_MODE != 'sub-agent':
                print(f"\nðŸ”¸ Entering phase: {new_phase.value}")

    def _transform_redundant_action(self, task: Task, action_sig: str, count: int) -> Task:
        """Transform a redundant action into one that produces new evidence."""
        desc = task.description.lower()
        file_path = _extract_file_path_from_description(task.description)
        
        print(f"  ⚠️  Redundant action detected ({count}x): {action_sig}")
        
        if task.action_type in {"read", "analyze"} and file_path:
            # If reading the same file, try searching for usages instead
            symbol_match = re.search(r'class\s+(\w+)|def\s+(\w+)', desc)
            symbol = symbol_match.group(1) or symbol_match.group(2) if symbol_match else None
            
            if symbol:
                print(f"  → Transforming to symbol usage search: {symbol}")
                return Task(
                    description=f"Find all usages of symbol '{symbol}' in the codebase to understand its context",
                    action_type="analyze"
                )
            else:
                print(f"  → Transforming to git diff check")
                return Task(
                    description=f"Check git diff for {file_path} to see recent changes and identify potential issues",
                    action_type="analyze"
                )
        
        if task.action_type == "edit" and file_path:
            print(f"  → Transforming stuck EDIT to READ for re-synchronization: {file_path}")
            return Task(
                description=f"Read the current content of {file_path} to identify why previous edits failed to match. Pay close attention to exact whitespace and indentation.",
                action_type="read"
            )
        
        if task.action_type == "test":
            print(f"  → Transforming to build/compile check")
            return Task(
                description="Run a full build or compilation check to ensure structural integrity",
                action_type="test"
            )
            
        # Generic transformation: search for related patterns
        print(f"  → Transforming to generic pattern search")
        return Task(
            description=f"Search for patterns related to: {task.description[:50]}",
            action_type="analyze"
        )

    def _discover_project_roots(self) -> List[Path]:
        if self._project_roots_cache is not None:
            return self._project_roots_cache

        markers = {
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "go.mod",
            "Cargo.toml",
            "Gemfile",
            "composer.json",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "CMakeLists.txt",
            "Makefile",
            ".git",
            ".rev",
        }

        max_depth = 4
        roots: set[Path] = set()
        root_path = self.project_root.resolve()

        for dirpath, dirnames, filenames in os.walk(root_path):
            current = Path(dirpath)
            try:
                rel = current.relative_to(root_path)
            except Exception:
                rel = Path(".")

            depth = len(rel.parts)
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            if depth > max_depth:
                dirnames[:] = []
                continue

            if any(marker in filenames for marker in markers):
                roots.add(current)

        if not roots:
            roots.add(root_path)

        self._project_roots_cache = sorted(roots, key=lambda p: len(p.parts))
        return self._project_roots_cache

    def _find_root_for_path(self, path: Path, roots: List[Path]) -> Optional[Path]:
        if not roots:
            return None
        candidates = []
        for root in roots:
            try:
                if path.is_relative_to(root):
                    candidates.append(root)
            except Exception:
                if str(path).startswith(str(root)):
                    candidates.append(root)
        if not candidates:
            return None
        return max(candidates, key=lambda p: len(p.parts))

    def _select_project_root_for_task(self, task: Task) -> Optional[Path]:
        if not task or not task.description:
            return None

        roots = self._discover_project_roots()
        if not roots:
            return None

        desc = task.description.lower()
        workspace = get_workspace()
        workspace_root = workspace.root.resolve()

        # Prefer explicit relative directory references in the description.
        best_match: Optional[Path] = None
        best_len = 0
        for root in roots:
            try:
                rel = root.relative_to(workspace_root)
            except Exception:
                continue
            rel_str = str(rel).replace("\\", "/").lower()
            if rel_str and rel_str != "." and rel_str in desc:
                if len(rel_str) > best_len:
                    best_match = root
                    best_len = len(rel_str)

        if best_match:
            return best_match

        # Match by project root name if a single token maps to one root.
        tokens = set(re.findall(r"[a-z0-9_-]+", desc))
        name_matches = [root for root in roots if root.name.lower() in tokens]
        if len(name_matches) == 1:
            return name_matches[0]

        # If a file path is mentioned, use it only when it is unambiguous.
        file_hint = _extract_file_path_from_description(task.description)
        if file_hint:
            hint_path = Path(file_hint)
            if hint_path.is_absolute():
                return self._find_root_for_path(hint_path, roots)

            # Avoid changing workdir when the description already includes a scoped path.
            if len(hint_path.parts) > 1:
                return None

            if workspace.current_working_dir.resolve() == workspace_root:
                candidate = workspace_root / hint_path
                return self._find_root_for_path(candidate, roots)

        return None

    def _should_autoset_workdir(self, task: Task) -> bool:
        if config.WORKSPACE_ROOT_ONLY:
            return False
        if not task or not task.description:
            return False
        action_type = (task.action_type or "").lower()
        if action_type in {"read", "analyze", "research", "review", "set_workdir"}:
            return False
        if action_type in {"test", "general"}:
            return True
        desc = task.description.lower()
        keywords = (
            "install",
            "test",
            "lint",
            "build",
            "compile",
            "run",
            "npm",
            "yarn",
            "pnpm",
            "pip",
            "pytest",
            "gradle",
            "mvn",
            "cargo",
            "dotnet",
        )
        return any(keyword in desc for keyword in keywords)

    def _maybe_set_workdir_for_task(self, task: Task) -> Optional[Path]:
        if not self._should_autoset_workdir(task):
            return None

        file_hint = _extract_file_path_from_description(task.description)
        if file_hint:
            hint_path = Path(file_hint)
            if not hint_path.is_absolute() and len(hint_path.parts) > 1:
                return None

        root = self._select_project_root_for_task(task)
        if not root:
            return None

        workspace = get_workspace()
        current = workspace.current_working_dir.resolve()
        target = root.resolve()
        if current == target:
            return None

        try:
            execute_tool("set_workdir", {"path": str(target)}, agent_name="orchestrator")
        except Exception:
            return None
        return target

    def _display_prompt_optimization(self, original: str, optimized: str) -> None:
        """Display original vs improved prompts for transparency."""
        original_lines = original.strip().splitlines() or [original]
        optimized_lines = optimized.strip().splitlines() or [optimized]

        print("  Original request:")
        for line in original_lines:
            print(f"    {line}")

        print("  Optimized request:")
        for line in optimized_lines:
            print(f"    {line}")

    def _maybe_optimize_user_request(self) -> bool:
        """Optimize the current user request and log visibility when enabled."""
        if not self.config.enable_prompt_optimization or not self.context:
            return False

        original_request = self.context.user_request
        optimized_request, was_optimized = optimize_prompt_if_needed(
            original_request,
            auto_optimize=self.config.auto_optimize_prompt
        )
        if not was_optimized:
            if self.config.auto_optimize_prompt:
                print("\n[OK] Request already optimized; using original text")
                # Still show the final prompt for transparency (it's identical).
                self._display_prompt_optimization(original_request, original_request)
            return False

        print(f"\n[OK] Request optimized for clarity")
        self._display_prompt_optimization(original_request, optimized_request)
        self.context.user_request = optimized_request
        self.context.add_insight("optimization", "prompt_optimized", True)
        self.context.agent_insights["prompt_optimization"] = {
            "optimized": True,
            "original": original_request[:100],
            "improved": optimized_request[:100],
        }
        self.debug_logger.log(
            "orchestrator",
            "PROMPT_OPTIMIZED",
            {
                "auto_optimize": self.config.auto_optimize_prompt,
                "original_request": original_request,
                "optimized_request": optimized_request,
            },
        )
        return True

    def _collect_repo_stats(self) -> Dict[str, Any]:
        repo_context_raw = get_repo_context()
        repo_context = {} if isinstance(repo_context_raw, str) else repo_context_raw
        return {
            "file_count": len(repo_context.get("all_files", [])),
            "estimated_complexity": 5,
            "last_commit_age_days": 7,
            "has_tests_dir": os.path.isdir(self.project_root / "tests"),
            "has_docs_dir": os.path.isdir(self.project_root / "docs"),
            "has_examples_dir": os.path.isdir(self.project_root / "examples"),
        }

    def execute(
        self,
        user_request: str,
        resume: bool = False,
        resume_plan: bool = True,
        read_only: bool = False,
    ) -> OrchestratorResult:
        """Execute a task through the full agent pipeline."""
        global _active_context
        aggregate_errors: List[str] = []
        last_result: Optional[OrchestratorResult] = None
        self.context = RevContext(
            user_request=user_request,
            resume=resume,
            resume_plan=resume_plan,
            read_only=read_only,
        )
        _active_context = self.context
        try:
            self.debug_logger.set_trace_context({
                "project_root": str(self.project_root),
                "execution_mode": config.EXECUTION_MODE,
                "orchestrator_retries": self.config.orchestrator_retries,
            })
        except Exception:
            pass
        ensure_project_memory_file()
        # Keep repo_context minimal; sub-agents will retrieve focused context via ContextBuilder.
        self.context.repo_context = ""

        try:
            for attempt in range(self.config.orchestrator_retries + 1):
                if attempt > 0:
                    print(f"\n\n{colorize('◆', Colors.BRIGHT_CYAN)} {colorize(f'Orchestrator iteration {attempt}/{self.config.orchestrator_retries}', Colors.WHITE)}")
                    self.context.plan = None
                    self.context.state_manager = None
                    self.context.errors = []

                result = self._run_single_attempt(user_request)
                aggregate_errors.extend([f"Attempt {attempt + 1}: {err}" for err in self.context.errors])

                if result.success or result.no_retry:
                    result.errors = aggregate_errors
                    result.agent_insights = self.context.agent_insights
                    return result

                last_result = result
                last_result.errors.extend(self.context.errors)

            if last_result:
                last_result.errors = aggregate_errors
                last_result.agent_insights = self.context.agent_insights
                return last_result

            return OrchestratorResult(
                success=False,
                phase_reached=AgentPhase.FAILED,
                errors=["Unknown orchestrator failure"],
                agent_insights=self.context.agent_insights
            )
        finally:
            _active_context = None
        
    def _run_single_attempt(self, user_request: str) -> OrchestratorResult:
        """Run a single orchestration attempt."""
        execution_mode_val = config.EXECUTION_MODE
        if execution_mode_val != 'sub-agent':
            print("\n[ORCHESTRATOR - MULTI-AGENT COORDINATION]")
            print(f"Task: {user_request[:100]}...")
            print(f"Execution Mode: {execution_mode_val.upper()}")

        self.context.user_request = user_request
        self.context.auto_approve = self.config.auto_approve
        self.context.resource_budget = ResourceBudget()
        self._maybe_optimize_user_request()
        user_request = self.context.user_request
        start_time = time.time()

        from rev.execution.router import TaskRouter
        router = TaskRouter()
        route = router.route(self.context.user_request, repo_stats=self._collect_repo_stats())
        run_mode = route.mode

        result = OrchestratorResult(
            success=False, phase_reached=self.context.current_phase, plan=None,
            resource_budget=self.context.resource_budget, agent_insights=self.context.agent_insights,
            errors=self.context.errors, run_mode=run_mode,
        )

        coding_modes = {"quick_edit", "focused_feature", "full_feature", "refactor", "test_focus"}
        coding_mode = route.mode in coding_modes

        try:
            if execution_mode_val == 'sub-agent':
                self._update_phase(AgentPhase.EXECUTION)
                execution_success = self._continuous_sub_agent_execution(user_request, coding_mode)
                result.success = execution_success
                result.phase_reached = AgentPhase.COMPLETE if execution_success else AgentPhase.FAILED
                result.no_retry = bool(self.context.agent_state.get("no_retry")) if self.context else False
                if not execution_success:
                    result.errors.append("Sub-agent execution failed or was halted.")
            else:
                self._execute_heavy_path(user_request, coding_mode, result)
        
        except KeyboardInterrupt:
            if self.context:
                try:
                    self.context.save_history()
                except Exception:
                    pass
            if self.context.plan and self.context.state_manager:
                try:
                    self.context.state_manager.on_interrupt(token_usage=get_token_usage())
                except Exception as exc:
                    print(f"⚠️  Warning: could not save checkpoint on interrupt ({exc})")
            raise
        except Exception as e:
            failure_phase = self.context.current_phase or AgentPhase.FAILED
            tb = traceback.format_exc()
            print(f"\n❌ Exception during {failure_phase.value} phase: {e}\n{tb}")
            result.success = False
            result.phase_reached = failure_phase
            result.errors.append(f"{failure_phase.value} phase error: {e}")

        result.execution_time = time.time() - start_time
        self.context.resource_budget.tokens_used = get_token_usage().get("total", 0)
        self.context.resource_budget.update_time()

        if execution_mode_val != 'sub-agent':
            print(f"\n📊 Resource Usage Summary:")
            print(f"   {self.context.resource_budget.get_usage_summary()}")
        
        self._emit_run_metrics(result.plan, result, self.context.resource_budget)
        self._display_summary(result)
        return result

    def _execute_heavy_path(self, user_request: str, coding_mode: bool, result: OrchestratorResult):
        # Phase 2: Research (optional)
        research_findings = None
        if self.config.enable_research:
            self._update_phase(AgentPhase.RESEARCH)
            research_findings = research_codebase(
                user_request,
                quick_mode=False,
                search_depth=self.config.research_depth
            )
            if research_findings:
                result.research_findings = research_findings
                self.context.add_insight("research", "findings_obtained", True)

        # Phase 2b: Prompt Optimization (optional)
        # Phase 2c: ContextGuard (optional)
        if self.config.enable_context_guard and research_findings:
            self._update_phase(AgentPhase.CONTEXT_GUARD)
            from rev.execution.context_guard import run_context_guard

            guard_result = run_context_guard(
                user_request=self.context.user_request,
                research_findings=research_findings,
                interactive=self.config.context_guard_interactive,
                threshold=self.config.context_guard_threshold,
                budget=self.context.resource_budget
            )

            # Store results in context
            self.context.context_sufficiency = guard_result.sufficiency
            self.context.purified_context = guard_result.filtered_context
            self.context.add_insight("context_guard", "action", guard_result.action_taken)
            self.context.add_insight("context_guard", "tokens_saved", guard_result.filtered_context.tokens_saved)

            # Handle insufficiency
            if guard_result.action_taken == "insufficient":
                self.context.add_error(f"ContextGuard: Insufficient context for safe planning")
                raise Exception(f"Insufficient context. Gaps: {[g.description for g in guard_result.sufficiency.gaps]}")

        self._update_phase(AgentPhase.PLANNING)
        plan = planning_mode(
            self.context.user_request, coding_mode=coding_mode,
            max_plan_tasks=self.config.max_plan_tasks, max_planning_iterations=self.config.max_planning_iterations,
        )
        self.context.update_plan(plan)
        result.plan = self.context.plan
        self.context.set_state_manager(StateManager(self.context.plan))

        if not self.context.plan.tasks:
            raise Exception("Planning agent produced no tasks.")

        if self.config.enable_review:
            self._update_phase(AgentPhase.REVIEW)

        self._update_phase(AgentPhase.EXECUTION)
        if self.config.parallel_workers > 1:
            concurrent_execution_mode(
                self.context.plan,
                max_workers=self.config.parallel_workers,
                auto_approve=self.config.auto_approve,
                tools=get_available_tools(),
                enable_action_review=self.config.enable_action_review,
                coding_mode=coding_mode,
                state_manager=self.context.state_manager,
                budget=self.context.resource_budget,
            )
        else:
            execution_mode(
                self.context.plan,
                auto_approve=self.config.auto_approve,
                tools=get_available_tools(),
                enable_action_review=self.config.enable_action_review,
                coding_mode=coding_mode,
                state_manager=self.context.state_manager,
                budget=self.context.resource_budget,
            )

        if self.config.enable_validation:
            self._update_phase(AgentPhase.VALIDATION)
        
        all_tasks_handled = all(t.status == TaskStatus.COMPLETED for t in self.context.plan.tasks)
        validation_ok = True
        result.success = all_tasks_handled and validation_ok
        result.phase_reached = AgentPhase.COMPLETE if result.success else AgentPhase.VALIDATION

    def _decompose_extraction_task(self, failed_task: Task) -> Optional[Task]:
        """
        When a task fails, ask the LLM if it can be decomposed into more granular steps.

        Rather than using brittle keyword detection, we let the LLM evaluate the failed
        task and suggest a decomposition strategy if one exists.
        """
        decomposition_prompt = (
            f"A task has failed: {failed_task.description}\n\n"
            f"Error: {failed_task.error if failed_task.error else 'Unknown'}\n\n"
            f"Can this task be decomposed into smaller, more specific subtasks that might succeed?\n"
            f"If yes, describe the first subtask that should be attempted next in detail.\n"
            f"If no, just respond with 'CANNOT_DECOMPOSE'.\n\n"
            "CRITICAL - Error Scope:\n"
            "- Only fix errors that are DIRECTLY RELATED to your changes\n"
            "- If validation shows errors in unrelated parts of the file, IGNORE them\n"
            "- Pre-existing errors in other functions/sections should NOT be fixed by you\n"
            "- Focus ONLY on making your specific change work correctly\n\n"
            "Important import strategy note (avoid churn):\n"
            "- If a refactor split creates a package (directory with __init__.py exports), update call sites/tests to\n"
            "  import from the package exports (e.g., `from package import ExportedSymbol`).\n"
            "- Do NOT expand `from pkg import *` into dozens of per-module imports.\n\n"
            f"Important: Be specific about what concrete action the next task should take. "
            f"Use [ACTION_TYPE] format like [CREATE] or [EDIT] or [REFACTOR].\n"
            "ACTIONABILITY: Include a specific tool and artifact in the description "
            "(e.g., \"Use read_file on src/app.py\" or \"Use create_directory to create src/components\")."
        )

        response_data = ollama_chat([{"role": "user", "content": decomposition_prompt}])

        if "error" in response_data or not response_data.get("message", {}).get("content"):
            return None

        response_content = response_data.get("message", {}).get("content", "").strip()

        if "CANNOT_DECOMPOSE" in response_content.upper():
            return None

        # Robust parsing: find the first instance of [ACTION_TYPE] anywhere in the response
        match = re.search(r"\[([A-Z_]+)\]\s*(.*)", response_content, re.DOTALL)
        if match:
            action_raw = match.group(1)
            description = match.group(2).strip()
            
            # Clean up: if there's a second action block, stop there
            next_action_pattern = r'\[[A-Z_]+\]'
            match_next = re.search(next_action_pattern, description)
            if match_next:
                description = description[:match_next.start()].strip()

            action_type = normalize_action_type(
                action_raw,
                available_actions=AgentRegistry.get_registered_action_types(),
            )

            print(f"\n  [DECOMPOSITION] Parsed suggested subtask:")
            print(f"    Action: {action_type}")
            print(f"    Task: {description[:100]}...")
            return Task(description=description, action_type=action_type)
        else:
            # Fallback: if no brackets found, try to find keywords or use the first line
            lines = [l.strip() for l in response_content.splitlines() if l.strip()]
            first_meaningful = ""
            for line in lines:
                if not any(kw in line.lower() for kw in ["yes", "decompose", "fail", "error", "subtask"]):
                    first_meaningful = line
                    break
            
            desc = first_meaningful or (lines[0] if lines else response_content)
            print(f"\n  [DECOMPOSITION] Fallback suggestion: {desc[:100]}...")
            return Task(
                description=desc,
                action_type="edit" # Default to edit for repair
            )

    def _determine_next_action(self, user_request: str, work_summary: str, coding_mode: bool, iteration: int = 1, failure_notes: str = "", path_hints: str = "", agent_notes: str = "") -> Optional[Task]:
        """A truly lightweight planner that makes a direct LLM call."""
        available_actions = _order_available_actions(AgentRegistry.get_registered_action_types())

        blocked_note = ""
        if self.context:
            blocked_tests = bool(self.context.agent_state.get("tests_blocked_no_changes"))
            last_test_rc = self.context.agent_state.get("last_test_rc")
            if blocked_tests and isinstance(last_test_rc, int) and last_test_rc != 0:
                blocked_note = (
                    "Important: The last [TEST] was skipped because no code changed since the last failing test run.\n"
                    "Do NOT propose another [TEST] until a code-changing step (e.g. [EDIT]/[REFACTOR]) is completed.\n\n"
                )
            # If a timeout indicated it needs a fix, add a direct note to the planner prompt.
            timeout_needs_fix = False
            try:
                if isinstance(getattr(self, "context", None), RevContext):
                    needs_fix = self.context.get_agent_state("timeout_needs_fix_note", False)
                    timeout_needs_fix = bool(needs_fix)
            except Exception:
                timeout_needs_fix = False
            timeout_note = ""
            if timeout_needs_fix:
                timeout_note = (
                    "Timeout diagnostics: The last test command timed out and signaled 'needs_fix'. "
                    "Propose a safer test command or configuration change (e.g., non-watch, targeted file) before re-running.\n\n"
                )
        
        history_note = ""
        if iteration == 1 and work_summary != "No actions taken yet.":
            history_note = (
                "Important: You are resuming a previous session. Do NOT declare GOAL_ACHIEVED on your very first turn. "
                "Instead, perform a [READ] or [ANALYZE] step to verify that the work from the previous session is still correct and consistent with the current filesystem state.\n\n"
            )

        # Provide a compact structure summary to discourage hallucinated paths
        struct_note = ""
        try:
            summary_iter = self.context.agent_state.get("structure_summary_iter", -1)
            if summary_iter != iteration:
                summary = _summarize_structure(self.project_root)
                if summary:
                    self.context.agent_state["structure_summary"] = summary
                    self.context.agent_state["structure_summary_iter"] = iteration
            summary = self.context.agent_state.get("structure_summary", "")
            if summary:
                struct_note = "Known project paths (depth-limited):\n" + summary + "\n\n"
        except Exception:
            pass

        feedback_note = ""
        if self.context and self.context.user_feedback:
            feedback_note = "\nDIRECT USER GUIDANCE (Priority - follow these instructions now):\n"
            for fb in self.context.user_feedback:
                feedback_note += f"- {fb}\n"
            feedback_note += "\n"
            # Clear feedback after incorporating it into the prompt
            self.context.user_feedback = []

        prompt = (
            f"Original Request: {user_request}\n\n"
            f"{feedback_note}"
            f"{work_summary}\n\n"
            f"{path_hints}\n"
            f"{struct_note}"
            f"{agent_notes}\n"
            f"{failure_notes}\n"
            f"{blocked_note}"
            f"{timeout_note}"
            f"{history_note}"
            "Based on the work completed, what is the single next most important action to take? "
            "If a previous action failed, propose a different action to achieve the goal.\n"
            "\n"
            "ACTION SEMANTICS (critical):\n"
            "- Use [READ] or [ANALYZE] when the next step is inspection only (open files, search, inventory imports, understand structure).\n"
            "- Use [EDIT]/[ADD]/[CREATE_DIRECTORY]/[REFACTOR] only when you will perform a repo-changing tool call in this step.\n"
            "- Use [TOOL] only to execute an existing built-in tool (e.g., `split_python_module_classes`).\n"
            "- Use [CREATE_TOOL] only when no existing tool can do the job and you must create a new tool.\n"
            "- If unsure whether a path exists, choose [READ] first to locate the correct file path(s).\n"
            "\n"
            "TASK SPECIFICITY (CRITICAL):\n"
            "- Be extremely specific in your task description. Include file paths and specific functions/features.\n"
            "- If a previous task partially completed a goal, ensure the next task reflects the remaining work only.\n"
            "- Avoid using the exact same description for multiple consecutive steps; this triggers circuit breakers.\n"
            "DEPENDENCIES (IMPORTANT):\n"
            "- If your change requires new dependencies, update the manifest (e.g., package.json) and plan the install step next.\n"
            "\n"
            "RESPONSE FORMAT (CRITICAL - follow exactly):\n"
            "- Respond with EXACTLY ONE action on a SINGLE LINE\n"
            "- Format: [ACTION_TYPE] brief description of what to do\n"
            "- Do NOT output multiple actions or a plan - only the SINGLE NEXT step\n"
            "- Do NOT chain actions like '[READ] file [ANALYZE] content' - pick ONE\n"
            "- Example: [EDIT] refactor the authentication middleware to use the new session manager\n"
            "- If the goal has been achieved, respond with only: GOAL_ACHIEVED"
        )

        response_data = ollama_chat([{"role": "user", "content": prompt}])

        if "error" in response_data or not response_data.get("message"):
            raise RuntimeError(f"Planner LLM error: {response_data.get('error') if isinstance(response_data, dict) else 'unknown'}")

        response_content = response_data.get("message", {}).get("content", "") or ""
        response_content = response_content.strip()

        # Parse action/description from the LLM response
        description = ""
        action_type = ""
        match = re.search(r"\[([A-Z_]+)\]\s*(.*)", response_content, re.DOTALL)
        if match:
            action_raw = match.group(1)
            description = match.group(2).strip()
            action_type = normalize_action_type(
                action_raw,
                available_actions=AgentRegistry.get_registered_action_types(),
            )
        else:
            # Fallback: take first non-empty line as description and default to EDIT
            lines = [l.strip() for l in response_content.splitlines() if l.strip()]
            description = lines[0] if lines else response_content
            action_type = "edit"

        # Clean up malformed LLM output that contains multiple actions concatenated
        # e.g. "Open file.[READ] another[ANALYZE] more" -> "Open file."
        # Use regex to find potential start of next action tag (e.g. [READ], [EDIT], etc.)
        # We look for [UPPERCASE_ACTION] to distinguish from filename patterns like [id]
        action_pattern = r'\[\s*(?:' + '|'.join(re.escape(a.upper()) for a in available_actions) + r')\s*\]'
        match_next = re.search(action_pattern, description)
        if match_next:
            description = description[:match_next.start()].strip()

        # Also clean up trailing brackets like "src/module]"
        description = re.sub(r'\]$', '', description).strip()

        task = Task(description=description, action_type=action_type)
        if hasattr(self, "debug_logger") and self.debug_logger:
            # Log to standard debug log
            self.debug_logger.log("orchestrator", "TASK_DETERMINED", {
                "action_type": task.action_type,
                "description": task.description,
                "raw_response": response_content
            }, "DEBUG")
            
            # Log to transaction log for centralized review
            self.debug_logger.log_transaction_event("ORCHESTRATOR_DECISION", {
                "action_type": task.action_type,
                "description": task.description,
                "raw_response": response_content
            })

        return task

    def _extract_claims_from_log(self, log_entry: str) -> List[str]:
        """Extract high-level intent/claims from a task description."""
        # A claim is essentially what the agent is asserting it will do or find.
        # For simplicity, we treat the description as a single claim for now.
        return [log_entry.split('|')[0].strip()]

    def _evaluate_anchoring(self, user_request: str, completed_tasks_log: List[str]) -> AnchoringDecision:
        """Evaluate the current anchoring score to drive coordination decisions."""
        if not completed_tasks_log:
            return AnchoringDecision.RE_SEARCH

        scorer = AnchoringScorer()
        
        all_claims = []
        citations = set()
        test_outputs = []
        unresolved_symbols = []
        missing_files = []
        total_tools = 0

        for log in completed_tasks_log:
            # 1. Collect claims
            all_claims.extend(self._extract_claims_from_log(log))
            
            # 2. Extract citations (files mentioned in log or output)
            file_match = _extract_file_path_from_description(log)
            if file_match:
                citations.add(file_match)
            
            # 3. Collect test results
            if "[COMPLETED]" in log and "test" in log.lower():
                test_outputs.append(log)
            
            # 4. Collect errors/mismatches
            if "[FAILED]" in log:
                # Every failed task is a risk
                unresolved_symbols.append(log)
                if "missing path" in log.lower() or "not exist" in log.lower():
                    missing_files.append(log)
                if "undefined" in log.lower() or "unresolved" in log.lower():
                    # already added to unresolved_symbols, but can add specifically if needed
                    pass
            
            # 5. Track tool usage
            if "Output:" in log:
                total_tools += 1

        metrics = scorer.compute_anchoring_score(
            claims=all_claims,
            repo_citations=list(citations),
            test_outputs=test_outputs,
            unresolved_symbols=unresolved_symbols,
            missing_files=missing_files,
            tools_used_count=total_tools
        )

        print(f"\n  [UCCT] Anchoring Score: {metrics.raw_score:.2f} | Density: {metrics.evidence_density:.2f} | Risk: {metrics.mismatch_risk}")
        print(f"  [UCCT] Coordination Decision: {metrics.decision.value}")
        
        if hasattr(self, "debug_logger") and self.debug_logger:
            self.debug_logger.log("orchestrator", "ANCHORING_EVALUATION", metrics.__dict__, "INFO")

        return metrics.decision

    def _is_completion_grounded(self, completed_tasks_log: List[str], user_request: Optional[str] = None) -> Tuple[bool, str]:
        """Verify that the completion is grounded in concrete artifacts/evidence."""
        if not completed_tasks_log:
            return False, "No work history to verify."

        # A completion must reference:
        # 1. File diffs/writes
        # 2. Test output/artifact IDs
        # 3. Search results
        # 4. Runtime checks
        
        evidence_found = {
            "files": False,
            "tests": False,
            "search": False,
            "runtime": False
        }

        for log in completed_tasks_log:
            log_l = log.lower()
            # 1. File diffs/writes
            if any(k in log_l for k in ["wrote", "replaced", "created file", "modified", "diff", "write_file", "replace_in_file", "apply_patch"]):
                evidence_found["files"] = True
            # 2. Test outputs
            if any(k in log_l for k in ["passed", "failed", "test suite", "pytest", "run_tests", "run_cmd"]):
                evidence_found["tests"] = True
            # 3. Search results
            if any(k in log_l for k in ["found", "matches", "listing", "search", "read file", "list_dir", "read_file", "search_code", "rag_search"]):
                evidence_found["search"] = True
            # 4. Runtime checks
            if any(k in log_l for k in ["runtime", "log", "executed", "status", "exit code", "analyze_runtime_logs"]):
                evidence_found["runtime"] = True

        # Require at least Search (knowing what's there) AND either File/Test/Runtime (doing something)
        has_research = evidence_found["search"]
        has_action = evidence_found["files"] or evidence_found["tests"] or evidence_found["runtime"]
        
        # TDD Check: If the request mentioned "test" or "application", require test evidence
        if user_request is None and self.context:
            user_request = self.context.user_request
        request_lower = (user_request or "").lower()
        needs_tests = any(kw in request_lower for kw in ["test", "verify", "check", "application", "tdd"])
        if needs_tests and not evidence_found["tests"]:
            return False, "Completion rejected: The request implies test-driven development, but no test execution evidence was found."

        if not has_research:
            return False, "Completion rejected: No research/search evidence found. Agent acted without reading."
        if not has_action:
            return False, "Completion rejected: No concrete action (file edit, test run, or runtime check) verified."
            
        return True, "Completion grounded in artifacts."

    def _continuous_sub_agent_execution(self, user_request: str, coding_mode: bool) -> bool:
        """Executes a task by continuously calling a lightweight planner for the next action.

        Implements the proper workflow:
        1. Plan next action (unless forced_next_task is set)
        2. Execute action
        3. VERIFY execution actually succeeded
        4. Report results
        5. Re-plan if needed
        """

        if not config.TDD_ENABLED:
            # Ensure stale TDD flags do not influence non-TDD runs.
            for key in ("tdd_pending_green", "tdd_require_test", "tdd_deferred_test", "tdd_green_observed"):
                if key in self.context.agent_state:
                    self.context.agent_state.pop(key, None)
            self.context.agent_state["tdd_disabled"] = True
        print(f"\n◈ {colorize('Sub-agent Orchestrator', Colors.BRIGHT_CYAN, bold=True)} active")

        from rev.execution.ledger import get_ledger
        ledger = get_ledger()

        # Persistence: load previous work history
        completed_tasks_log = self.context.load_history()
        if completed_tasks_log:
            print(f"  ✓ Loaded {len(completed_tasks_log)} tasks from history")

        # Track completed Task objects (separate from string-based logs)
        completed_tasks: List[Task] = []

        # Ensure we have a persistent plan and state manager for checkpoints
        if not self.context.plan:
            if self.context.resume and self.context.resume_plan:
                latest = StateManager.find_latest_checkpoint()
                if latest:
                    try:
                        self.context.plan = StateManager.load_from_checkpoint(latest)
                        print(f"  ✓ Loaded cumulative plan from checkpoint: {latest}")
                        # Populate completed_tasks from the plan
                        for task in self.context.plan.tasks:
                            if task.status == TaskStatus.COMPLETED:
                                completed_tasks.append(task)
                                # If history log is empty, reconstruct it from plan
                                if not completed_tasks_log:
                                    status_tag = f"[{task.status.name}]"
                                    log_entry = f"{status_tag} {task.description}"
                                    if task.result and isinstance(task.result, str):
                                        try:
                                            res = json.loads(task.result)
                                            if isinstance(res, dict) and "summary" in res:
                                                log_entry += f" | Output: {res['summary']}"
                                        except: pass
                                    completed_tasks_log.append(log_entry)
                            elif task.status == TaskStatus.FAILED and not completed_tasks_log:
                                completed_tasks_log.append(f"[{task.status.name}] {task.description} | Reason: {task.error}")
                        
                        if completed_tasks_log:
                            self.context.work_history = completed_tasks_log
                    except Exception as e:
                        print(f"  ⚠️  Failed to load checkpoint: {e}")
                        self.context.plan = ExecutionPlan(tasks=[])
                else:
                    self.context.plan = ExecutionPlan(tasks=[])
            else:
                self.context.plan = ExecutionPlan(tasks=[])

        if not self.context.state_manager:
            self.context.set_state_manager(StateManager(self.context.plan))

        if self.context.resume:
            # Reset loop-guard/redundant-read counters and blocked read signatures on resume.
            completed_tasks = []
            self.context.set_agent_state("blocked_action_sigs", set())
            self.context.set_agent_state("loop_guard_verification_attempted", False)
            print("  [resume] Reset loop-guard counters for new run")

        iteration = len(self.context.plan.tasks)
        action_counts: Dict[str, int] = defaultdict(int)
        # Re-populate action counts from history (skip on resume to avoid loop-guard carryover)
        if not (self.context.resume and self.context.resume_plan):
            for task in self.context.plan.tasks:
                action_sig = f"{(task.action_type or '').strip().lower()}::{task.description.strip().lower()}"
                action_counts[action_sig] += 1

        failure_counts: Dict[str, int] = defaultdict(int)
        last_task_signature: Optional[str] = None
        repeat_same_action: int = 0
        forced_next_task: Optional[Task] = None
        pending_resume_tasks: List[Task] = []
        pending_injected_tasks: List[Task] = []
        budget_warning_shown: bool = False

        # PERFORMANCE FIX 1: Track consecutive research tasks to prevent endless loops
        consecutive_reads: int = 0
        MAX_CONSECUTIVE_READS: int = 20  # Allow max 20 consecutive READ tasks

        if self.context.resume and self.context.resume_plan and self.context.plan:
            for task in self.context.plan.tasks:
                if task.status in {TaskStatus.IN_PROGRESS, TaskStatus.STOPPED}:
                    task.status = TaskStatus.PENDING
            pending_resume_tasks = [
                task for task in self.context.plan.tasks
                if task.status == TaskStatus.PENDING
            ]
            deduped_resume_tasks = _dedupe_pending_resume_tasks(pending_resume_tasks)
            if len(deduped_resume_tasks) != len(pending_resume_tasks):
                print(
                    f"  [resume] Deduped pending READ tasks: {len(pending_resume_tasks)} -> {len(deduped_resume_tasks)}"
                )
            pending_resume_tasks = deduped_resume_tasks
            # Allow one fresh recursive structure read on resume to refresh context
            self.context.set_agent_state("structure_read_seen", {})
            self.context.set_agent_state("research_signature_seen", {})
            # Reset write dedupe state so failed writes can retry after resume
            self.context.set_agent_state("write_signature_state", {})
            # Code-change iteration is unknown on resume; permit initial listings
            self.context.set_agent_state("last_code_change_iteration", 0)

        while True:
            iteration += 1
            self.context.set_agent_state("current_iteration", iteration)
            self.context.resource_budget.update_step()
            self.context.resource_budget.tokens_used = get_token_usage().get("total", 0)

            # OPTIONAL: Force initial workspace examination on first iteration
            # Disabled by default since decent LLMs naturally propose research as first step
            if config.INJECT_INITIAL_RESEARCH and iteration == 1 and forced_next_task is None:
                # Check if workspace has already been examined
                workspace_examination_ops = ["tree_view", "list_dir", "git_status", "git_diff", "read_file", "inspect", "examine"]
                has_examined = any(
                    any(op in str(log_entry).lower() for op in workspace_examination_ops)
                    for log_entry in completed_tasks_log
                )

                if not has_examined:
                    # Force initial research task before any action
                    forced_next_task = Task(
                        description="Examine current workspace state using tree_view and git_status to understand what already exists",
                        action_type="read"
                    )
                    forced_next_task.task_id = 0
                    print(f"  {colorize(Symbols.INFO, Colors.BRIGHT_BLUE)} {colorize('Analyzing workspace structure...', Colors.BRIGHT_BLACK)}")

            if self.context.resource_budget.is_exceeded() and not budget_warning_shown:
                exceeded = self.context.resource_budget.get_exceeded_resources()
                exceeded_str = ", ".join(exceeded)
                print(f"\n⚠️ Resource budget exceeded at step {iteration}: {exceeded_str}")
                print(f"   Usage: {self.context.resource_budget.get_usage_summary()}")
                print(f"   To increase limits, set environment variables:")
                print(f"   - REV_MAX_STEPS (current: {self.context.resource_budget.max_steps})")
                print(f"   - REV_MAX_TOKENS (current: {self.context.resource_budget.max_tokens:,})")
                print(f"   - REV_MAX_SECONDS (current: {self.context.resource_budget.max_seconds:.0f})")
                print(f"   Continuing anyway...")
                budget_warning_shown = True
                # Don't halt - just warn and continue
                # self.context.set_agent_state("no_retry", True)
                # self.context.add_error(f"Resource budget exceeded: {exceeded_str}")
                # return False

            if (
                not forced_next_task
                and config.TDD_ENABLED
                and self.context.agent_state.get("tdd_require_test")
            ):
                # Check if we know which specific test file was failing - run only that test
                last_failing_test = self.context.agent_state.get("last_failing_test_file", "")

                if last_failing_test:
                    # Run ONLY the specific failing test, not the entire suite
                    if last_failing_test.endswith('.py'):
                        test_cmd = f"pytest {last_failing_test} -v"
                    else:
                        # JavaScript/Node.js test
                        test_cmd = f"npm test -- {last_failing_test}"

                    forced_next_task = Task(
                        description=f"Run ONLY the specific test that was failing: {test_cmd}",
                        action_type="test",
                    )
                    print(f"  [tdd] Targeted test injection: {last_failing_test}")
                else:
                    # NO FALLBACK - don't inject generic test runs
                    # Running the full test suite wastes time and causes hangs
                    # Only run tests when we have a specific test file to target
                    print(f"  [tdd] Skipping test injection - no specific failing test identified")
                    self.context.set_agent_state("tdd_require_test", False)

            # Harvest agent requests that asked for explicit task injections (e.g., syntax->typecheck, targeted tests)
            if self.context and self.context.agent_requests:
                remaining_reqs = []
                injected_sig_key = "injected_task_sigs"
                seen_sigs_raw = self.context.agent_state.get(injected_sig_key, [])
                seen_sigs = set(seen_sigs_raw if isinstance(seen_sigs_raw, list) else [])
                last_change = self.context.agent_state.get("last_code_change_iteration", -1)

                for req in self.context.agent_requests:
                    if req.get("type") == "INJECT_TASKS":
                        tasks = req.get("details", {}).get("tasks", [])
                        for t in tasks:
                            # Prefer Task instances; accept dicts defensively
                            if isinstance(t, Task):
                                injected_task = t
                            elif isinstance(t, dict):
                                injected_task = Task(
                                    description=t.get("description", ""),
                                    action_type=t.get("action_type", "general"),
                                )
                            else:
                                continue

                            desc = (injected_task.description or "").strip()
                            action = (injected_task.action_type or "general").strip().lower()
                            if not desc:
                                continue
                            sig = f"{action}::{desc.lower()}::iter={last_change}"
                            if sig in seen_sigs:
                                continue
                            # Mark injected tasks as self-healing: allow one auto-retry with tool forcing
                            injected_task.breaking_change = False
                            injected_task.impact_scope.append("injected")
                            injected_task.priority = max(injected_task.priority, 5)
                            pending_injected_tasks.append(injected_task)
                            seen_sigs.add(sig)
                            print(f"  [inject] Queued injected task: [{injected_task.action_type}] {desc[:80]}")
                        continue
                    remaining_reqs.append(req)

                self.context.agent_requests = remaining_reqs
                self.context.set_agent_state(injected_sig_key, list(seen_sigs))

            if not forced_next_task:
                diagnostic_task = _pop_diagnostic_task(self.context)
                if diagnostic_task:
                    forced_next_task = diagnostic_task

            if not forced_next_task and pending_injected_tasks:
                forced_next_task = pending_injected_tasks.pop(0)
                print(f"  [inject] Running injected task: [{forced_next_task.action_type.upper()}] {forced_next_task.description[:80]}")

            if not forced_next_task and pending_resume_tasks:
                forced_next_task = pending_resume_tasks.pop(0)
                print(
                    f"  [resume] Continuing pending task from checkpoint: "
                    f"{forced_next_task.description[:80]}"
                )

            if forced_next_task:
                next_task = forced_next_task
                forced_next_task = None
                print(f"  -> Using injected task: [{next_task.action_type.upper()}] {next_task.description[:80]}")
            else:
                work_summary = "No actions taken yet."
                if completed_tasks_log:
                    # Start with high-level statistics for full session context
                    total_tasks = len(completed_tasks_log)
                    completed_count = sum(1 for log in completed_tasks_log if log.startswith('[COMPLETED]'))
                    failed_count = sum(1 for log in completed_tasks_log if log.startswith('[FAILED]'))

                    work_summary = f"Work Completed So Far ({total_tasks} total tasks: {completed_count} completed, {failed_count} failed):\n"

                    # Add file read/inspection summary FIRST to establish what's been inspected
                    file_read_counts = ledger.get_files_inspected()

                    if file_read_counts:
                        work_summary += "\n📄 Files Already Inspected (DO NOT re-read these files unless absolutely necessary):\n"
                        for filename, count in sorted(file_read_counts.items(), key=lambda x: (-x[1], x[0])):
                            marker = "⚠️ STOP READING" if count >= 2 else "✓"
                            work_summary += f"  {marker} {filename}: read {count}x"
                            if count >= 2:
                                work_summary += " - MUST use [EDIT] or [CREATE] now, NOT another [READ]"
                            work_summary += "\n"
                        work_summary += "\n"

                    # Then provide a condensed view of the history
                    # Keep the first task (usually workspace examination) and the last 5
                    if total_tasks > 6:
                        work_summary += f"\n[History Truncated: showing first task and last 5 of {total_tasks}]\n"
                        work_summary += f"- {completed_tasks_log[0]}\n"
                        work_summary += "  ...\n"
                        work_summary += "\n".join(f"- {log}" for log in completed_tasks_log[-5:])
                    else:
                        work_summary += "All Tasks:\n"
                        work_summary += "\n".join(f"- {log}" for log in completed_tasks_log)

                    if hasattr(self, "debug_logger") and self.debug_logger:
                        self.debug_logger.log("orchestrator", "WORK_SUMMARY_GENERATED", {
                            "history_count": len(completed_tasks_log),
                            "summary_length": len(work_summary),
                            "files_inspected": len(file_read_counts)
                        }, "DEBUG")

                # Calculate repetitive failure notes for the planner
                failure_notes = []

                # Add the most recent failure prominently if the last task failed
                if completed_tasks_log:
                    last_entry = completed_tasks_log[-1]
                    if last_entry.startswith('[FAILED]'):
                        failure_notes.append("❌ LAST TASK FAILED:")
                        failure_notes.append(f"  {last_entry}")
                        failure_notes.append("")

                # P0-2: Add blocked actions to failure notes
                if self.context:
                    blocked_sigs = ledger.get_blocked_action_sigs()
                    if blocked_sigs:
                        failure_notes.append("🚫 BLOCKED ACTIONS (DO NOT propose any of these):")
                        for blocked_sig in blocked_sigs:
                            failure_notes.append(f"  ❌ BLOCKED: [{blocked_sig}]")
                        failure_notes.append("")  # Blank line for readability

                if action_counts:
                    for sig, count in action_counts.items():
                        if count >= 2:
                            failure_notes.append(f"⚠️ REPETITION: Action '[{sig}]' proposed {count}x. It is not progressing. DO NOT REPEAT. Try a different tool or inspect code again.")

                failure_notes_str = "\n".join(failure_notes)
                path_hints = _generate_path_hints(completed_tasks_log)

                # Collect and format pending agent requests (recovery instructions)
                agent_notes = ""
                if self.context and self.context.agent_requests:
                    notes = []
                    for req in self.context.agent_requests:
                        details = req.get("details", {})
                        reason = details.get("reason", "unknown")
                        detailed = details.get("detailed_reason", "")
                        agent = details.get("agent", "Agent")
                        note = f"⚠️ {agent} REQUEST: {reason}"
                        if detailed:
                            note += f"\n  Instruction: {detailed}"
                        notes.append(note)
                    agent_notes = "\n".join(notes)
                    # Clear requests after collecting them for the prompt
                    self.context.agent_requests = []

                next_task = self._determine_next_action(
                    user_request, work_summary, coding_mode, 
                    iteration=iteration, failure_notes=failure_notes_str,
                    path_hints=path_hints, agent_notes=agent_notes
                )

                if not next_task:
                    planner_error = self.context.get_agent_state("planner_error") if self.context else None
                    if isinstance(planner_error, str) and planner_error.strip():
                        self.context.set_agent_state("no_retry", True)
                        print("\n❌ Planner failed to produce a next action (LLM error).")
                        print(f"  Error: {planner_error}")
                        return False
                    
                    # UCCT Anchoring check before declaring victory
                    if config.UCCT_ENABLED:
                        anchoring_decision = self._evaluate_anchoring(user_request, completed_tasks_log)
                        if anchoring_decision == AnchoringDecision.RE_SEARCH:
                            print("\n  [UCCT] Goal may be achieved, but evidence density is low. Forcing one more search.")
                            forced_next_task = Task(description="Verify the implemented changes by listing the affected files and confirming their content matches the request.", action_type="read")
                            continue
                        elif anchoring_decision == AnchoringDecision.DEBATE:
                            print("\n  [UCCT] High mismatch risk detected. Verifying structural consistency before stopping.")
                            forced_next_task = Task(description="Run a structural consistency check on the modified modules to ensure no unresolved symbols remain.", action_type="analyze")
                            continue

                    # Grounded Completion Check (Bait Density)
                    if config.UCCT_ENABLED:
                        is_grounded, grounding_msg = self._is_completion_grounded(completed_tasks_log, user_request)
                        if not is_grounded:
                            print(f"\n  {colorize(Symbols.INFO, Colors.BRIGHT_BLUE)} {colorize(grounding_msg + ' Forcing verification.', Colors.BRIGHT_BLACK)}")
                            forced_next_task = Task(description="Provide concrete evidence of the work completed by running tests and inspecting the modified files.", action_type="test")
                            continue

                    print(f"\n{colorize(Symbols.CHECK, Colors.BRIGHT_GREEN)} {colorize('Goal achieved.', Colors.BRIGHT_GREEN, bold=True)}")
                    return True

                next_task = self._apply_read_only_constraints(next_task)

                # FORWARD PROGRESS RULE: Check for redundant actions
                action_sig = f"{(next_task.action_type or '').strip().lower()}::{(next_task.description or '').strip().lower()}"

                # Track consecutive transformations regardless of signature changes
                transformation_count = self.context.agent_state.get("transformation_count", 0)
                was_transformed = False

                if action_counts[action_sig] >= 2:
                    # This is a redundant action - need to transform it
                    if transformation_count >= 3:
                        # Too many transformations - trigger circuit breaker instead
                        print(f"\n  ⚠️  Transformation limit reached ({transformation_count}x) - triggering circuit breaker")
                        self.context.set_agent_state("no_retry", True)
                        self.context.add_error(f"Circuit breaker: too many action transformations ({transformation_count}x)")
                        print("\n[🛑 CIRCUIT BREAKER: TRANSFORMATION LOOP DETECTED]")
                        print(f"System has transformed actions {transformation_count} times without progress.")
                        print("This indicates a fundamental issue that cannot be auto-fixed.\n")
                        return False

                    next_task = self._transform_redundant_action(next_task, action_sig, action_counts[action_sig])
                    # Update signature after transformation
                    action_sig = f"{(next_task.action_type or '').strip().lower()}::{(next_task.description or '').strip().lower()}"

                    # Mark that we transformed and increment counter
                    was_transformed = True
                    self.context.set_agent_state("transformation_count", transformation_count + 1)
                    print(f"  [transformation-tracking] Count: {transformation_count + 1}/3")

                next_task.task_id = iteration
                try:
                    from rev.execution.planner import apply_validation_steps_to_task

                    apply_validation_steps_to_task(next_task)
                    # Ensure validation_steps are always present so quick_verify can enforce them.
                    if not next_task.validation_steps:
                        next_task.validation_steps = ExecutionPlan().generate_validation_steps(next_task)
                except Exception:
                    pass

                # ACTION LOGGING: Concise and consistent
                action_type = (next_task.action_type or "general").upper()
                print(f"\n{colorize(str(iteration), Colors.BRIGHT_BLACK)}. {colorize(action_type, Colors.BRIGHT_CYAN, bold=True)} {next_task.description}")

            # CRITICAL: Command intent coercion must ALWAYS run (not just when PREFLIGHT_ENABLED)
            # This ensures "npm install" tasks get routed to TestExecutorAgent which has run_cmd access
            ok_coercion, coercion_msgs = _coerce_command_intent_to_test(next_task)
            for msg in coercion_msgs:
                print(f"  [routing] {msg}")

            if config.PREFLIGHT_ENABLED:
                ok, sem_msgs = _preflight_correct_action_semantics(next_task)
                for msg in sem_msgs:
                    print(f"  [preflight] {msg}")
                if not ok:
                    self.context.add_error("Preflight failed: " + "; ".join(sem_msgs))
                    completed_tasks_log.append(f"[FAILED] Preflight: {'; '.join(sem_msgs)}")
                    if any("conflicts with write intent" in msg for msg in sem_msgs):
                        self.context.add_agent_request(
                            "REPLAN_REQUEST",
                            {
                                "agent": "Orchestrator",
                                "reason": "preflight read/write mismatch",
                                "detailed_reason": sem_msgs[0],
                            },
                        )
                    sig = f"action_semantics::{(next_task.action_type or '').strip().lower()}::{';'.join(sem_msgs).strip().lower()}"
                    failure_counts[sig] += 1
                    if failure_counts[sig] >= 3:
                        self.context.set_agent_state("no_retry", True)
                        self.context.add_error("Circuit breaker: repeating preflight action semantics failure")
                        print("\n[CIRCUIT BREAKER - PREFLIGHT FAILURE]")
                        print(f"Repeated preflight failure {failure_counts[sig]}x: {'; '.join(sem_msgs)}")
                        print("Blocking issue: planner is not producing an executable action; refusing to loop.\n")
                        return False
                    continue
                ok, preflight_msgs = _preflight_correct_task_paths(task=next_task, project_root=self.project_root)
                for msg in preflight_msgs:
                    print(f"  [preflight] {msg}")
                if not ok:
                    # Do not execute with missing/ambiguous paths; feed this back into planning.
                    self.context.add_error("Preflight failed: " + "; ".join(preflight_msgs))
                    completed_tasks_log.append(f"[FAILED] Preflight: {'; '.join(preflight_msgs)}")
                    key_msg = preflight_msgs[0] if preflight_msgs else "unknown"
                    sig = f"paths::{(next_task.action_type or '').strip().lower()}::{key_msg.strip().lower()}"
                    failure_counts[sig] += 1
                    if failure_counts[sig] >= 3:
                        self.context.set_agent_state("no_retry", True)
                        self.context.add_error("Circuit breaker: repeating preflight path failure")
                        print("\n[CIRCUIT BREAKER - PREFLIGHT FAILURE]")
                        print(f"Repeated preflight failure {failure_counts[sig]}x: {key_msg}")
                        print("Blocking issue: planner is not producing an executable action; refusing to loop.\n")
                        return False
                    continue

            # SEMANTIC DEDUPLICATION: Warn if this is a semantically duplicate read task
            action_type_lower = (next_task.action_type or '').lower()
            if action_type_lower in {'read', 'analyze', 'research', 'investigate', 'review'}:
                if _is_semantically_duplicate_task(
                    next_task.description,
                    next_task.action_type,
                    completed_tasks_log,
                    threshold=0.85  # Increased from 0.65 to reduce false positives
                ):
                    print(f"  [semantic-dedup] Warning: highly similar {action_type_lower} already completed.")

            # Append to cumulative plan instead of overwriting
            if next_task not in self.context.plan.tasks:
                self.context.plan.tasks.append(next_task)

            if self.context.state_manager:
                self.context.state_manager.on_task_started(next_task)

            # P0-2 & P0-3: Anti-loop with blocked actions and streak-based circuit breaker
            action_sig = f"{(next_task.action_type or '').strip().lower()}::{next_task.description.strip().lower()}"
            action_counts[action_sig] += 1  # Total count (for statistics)

            # P0-3: Track consecutive repetitions (streak-based)
            if action_sig == last_task_signature:
                repeat_same_action += 1
            else:
                repeat_same_action = 1  # Reset streak
                last_task_signature = action_sig

            # PERFORMANCE FIX 1: Track consecutive research tasks
            action_type_normalized = (next_task.action_type or '').strip().lower()
            if action_type_normalized in {'read', 'analyze', 'research', 'investigate', 'review'}:
                consecutive_reads += 1

                # Aggressive research/task dedupe per code change
                desc = (next_task.description or "").strip().lower()
                if (
                    "tree view" in desc
                    or "list the contents" in desc
                    or "listing directory" in desc
                    or "list files" in desc
                    or "list directory" in desc
                    or "project structure" in desc
                    or "directory structure" in desc
                    or "ls " in desc
                    or desc.startswith("ls")
                    or " dir" in desc
                ):
                    structure_seen = self.context.agent_state.get("structure_read_seen", {})
                    if not isinstance(structure_seen, dict):
                        structure_seen = {}
                    last_code_change_iteration = self.context.agent_state.get("last_code_change_iteration", -1)
                    struct_sig = _normalize_structure_read_signature(desc)
                    prior = structure_seen.get(struct_sig)
                    if isinstance(prior, dict):
                        prior_change = prior.get("code_change_iteration", -1)
                        # Only block duplicates once a code change iteration has been recorded.
                        # Allow redundant listings during initial planning/resume (code_change_iteration = -1)
                        # so the agent can recover missing paths.
                        if (
                            isinstance(prior_change, int)
                            and isinstance(last_code_change_iteration, int)
                            and prior_change == last_code_change_iteration
                            and last_code_change_iteration >= 0
                        ):
                            print(f"  [structure-read] Skipping duplicate structure listing (sig={struct_sig}, code_change_iter={last_code_change_iteration})")
                            next_task.status = TaskStatus.STOPPED
                            next_task.result = json.dumps({
                                "skipped": True,
                                "reason": "structure listing already performed for current code state",
                                "code_change_iteration": last_code_change_iteration,
                                "signature": struct_sig,
                            })
                            completed_tasks_log.append(
                                f"[STOPPED] {next_task.description} | Reason: structure listing already done (code_change_iter={last_code_change_iteration}, sig={struct_sig})"
                            )
                            continue
                    # If we already did a shallow read, allow one recursive read (rec=1) before skipping.
                    sig_base = struct_sig.rsplit("::rec=", 1)[0]
                    if isinstance(prior, dict) and "rec=0" in struct_sig and f"{sig_base}::rec=1" in structure_seen:
                        pass
                    structure_seen[struct_sig] = {"code_change_iteration": last_code_change_iteration}
                    self.context.set_agent_state("structure_read_seen", structure_seen)

                sig = f"{action_type_normalized}::{desc}"
                research_seen = self.context.agent_state.get("research_signature_seen", {})
                if not isinstance(research_seen, dict):
                    research_seen = {}
                last_code_change_iteration = self.context.agent_state.get("last_code_change_iteration", -1)
                prior = research_seen.get(sig)
                if isinstance(prior, dict):
                    prior_change = prior.get("code_change_iteration", -1)
                    if (
                        isinstance(prior_change, int)
                        and isinstance(last_code_change_iteration, int)
                        and last_code_change_iteration == prior_change
                    ):
                        print(f"  [research-dedupe] Skipping duplicate research task: {sig}")
                        next_task.status = TaskStatus.STOPPED
                        next_task.result = json.dumps({
                            "skipped": True,
                            "reason": "duplicate research signature since last code change",
                            "signature": sig,
                        })
                        completed_tasks_log.append(f"[STOPPED] {next_task.description} | Reason: duplicate research signature")
                        continue
                research_seen[sig] = {"code_change_iteration": last_code_change_iteration}
                self.context.set_agent_state("research_signature_seen", research_seen)

                # If the task is targeting specific files, short-circuit when they do not exist to avoid loops.
                targets = _extract_task_paths(next_task) or []
                missing_targets: list[str] = []
                existing_targets: list[str] = []
                for raw in targets:
                    try:
                        # Normalize leading slashes and workspace prefix to workspace-relative
                        candidate = _sanitize_path_candidate(raw)
                        if candidate.startswith("/"):
                            candidate = candidate.lstrip("/")
                        if candidate.lower().startswith(str(config.ROOT).replace("\\", "/").lower()):
                            try:
                                candidate = str(Path(candidate).relative_to(config.ROOT)).replace("\\", "/")
                            except Exception:
                                candidate = candidate
                        resolved = resolve_workspace_path(candidate).abs_path
                        if resolved.exists():
                            existing_targets.append(candidate)
                        else:
                            missing_targets.append(candidate)
                    except Exception:
                        missing_targets.append(_sanitize_path_candidate(raw))
                # Only block if ALL extracted targets are missing
                if targets and existing_targets == [] and missing_targets:
                    # Try to auto-correct by searching for basename matches under allowed roots
                    alt_matches: list[str] = []
                    for cand in missing_targets:
                        base = Path(_sanitize_path_candidate(cand)).name
                        if not base:
                            continue
                        for root in get_workspace().get_allowed_roots():
                            hits = _find_path_matches(root, base, limit=50)
                            alt_matches.extend([h.as_posix() for h in hits])
                    alt_matches = sorted(set(alt_matches))
                    replacement = _choose_best_path_match_with_context(
                        original=missing_targets[0],
                        matches=alt_matches,
                        description=next_task.description or "",
                    )
                    if replacement:
                        try:
                            rep_path = Path(replacement)
                            try:
                                rep_rel = rep_path.relative_to(Path(config.ROOT)).as_posix()
                            except Exception:
                                rep_rel = rep_path.as_posix()
                            normalized_replacement = rep_rel
                            desc = next_task.description or ""
                            desc = desc.replace(missing_targets[0], normalized_replacement)
                            next_task.description = desc
                            print(f"  [research-dedupe] Auto-corrected missing path '{missing_targets[0]}' -> '{normalized_replacement}'")
                            # Requeue the corrected task at current position and continue
                            self.context.plan.tasks.insert(plan_idx, next_task)
                            continue
                        except Exception:
                            pass
                    display_missing = [
                        Path(_sanitize_path_candidate(m)).as_posix().lstrip("/")
                        if m else ""
                        for m in missing_targets
                    ]
                    display_missing = [m for m in display_missing if m]
                    display_msg = ", ".join(display_missing) if display_missing else ", ".join(missing_targets)
                    msg = (
                        f"Target file(s) not found: {display_msg}. "
                        "Create the file(s) or adjust the path instead of repeating reads."
                    )
                    print(f"  [research-dedupe] Skipping read on missing targets: {msg}")
                    next_task.status = TaskStatus.STOPPED
                    next_task.result = json.dumps({
                        "skipped": True,
                        "reason": "target_missing",
                        "missing": display_missing or missing_targets,
                    })
                    completed_tasks_log.append(f"[STOPPED] {next_task.description} | Reason: missing targets ({display_msg})")
                    # Request a replan to create/locate the missing files.
                    self.context.add_agent_request(
                        "REPLAN_REQUEST",
                        {
                            "agent": "Orchestrator",
                            "reason": "missing_target_path",
                            "detailed_reason": msg,
                        },
                    )
                    continue
            else:
                consecutive_reads = 0  # Reset on any non-research action

                # If a read fails with "not found", immediately trigger a targeted structure refresh and block repeats until the file exists.
                if action_type_normalized == "read":
                    last_result = next_task.result or ""
                    parallel_mode = bool(getattr(config, "PARALLEL_MODE_ENABLED", False))
                    if isinstance(last_result, str) and "not found" in last_result.lower():
                        # Derive a parent dir pattern to refresh
                        parent_hint = None
                        try:
                            targets = _extract_task_paths(next_task)
                            if targets:
                                candidate = Path(_sanitize_path_candidate(targets[0]))
                                parent_hint = candidate.parent.as_posix()
                        except Exception:
                            parent_hint = None
                        refresh_desc = (
                            f"Refresh project structure recursively for {parent_hint or 'src/** and tests/**'} "
                            "to locate target files"
                        )
                        refresh_task = Task(description=refresh_desc, action_type="read")
                        completed_tasks_log.append("[INFO] Injecting structure refresh after missing file read")
                        self.context.plan.tasks.insert(plan_idx + 1, refresh_task)

                        # Block repeats of this missing path until code-change iteration advances
                        missing_key = "blocked_missing_reads"
                        blocked = self.context.agent_state.get(missing_key, {})
                        if not isinstance(blocked, dict):
                            blocked = {}
                        signature = f"read::{(next_task.description or '').strip().lower()}"
                        blocked[signature] = {
                            "code_change_iteration": self.context.agent_state.get("last_code_change_iteration", -1)
                        }
                        self.context.set_agent_state(missing_key, blocked)
                        continue
                else:
                    consecutive_reads = 0  # Reset on any non-research action

            # Write task dedupe disabled: allow retries to ensure forward progress.

            # Test task signature dedupe across pending/completed since last code change
            if action_type_normalized == "test":
                desc_lower = (next_task.description or "").lower()
                test_path_hint = _extract_test_path_from_text(next_task.description or "")
                looks_full_suite = (
                    ("npm test" in desc_lower or "yarn test" in desc_lower or "pnpm test" in desc_lower)
                    or ("vitest run" in desc_lower and not test_path_hint)
                    or ("npx vitest" in desc_lower and "run" in desc_lower and not test_path_hint)
                )
                allow_full_suite = bool(self.context.agent_state.get("allow_full_suite", False))
                if looks_full_suite and not allow_full_suite:
                    next_task.status = TaskStatus.STOPPED
                    next_task.result = json.dumps({
                        "skipped": True,
                        "reason": "full test suite deferred",
                        "suggestion": "Run targeted Vitest on specific files after code is stable."
                    })
                    completed_tasks_log.append(
                        f"[STOPPED] {next_task.description} | Reason: full test suite deferred; run targeted file-specific tests instead."
                    )
                    continue
                signature = _normalize_test_task_signature(next_task)
                next_task._normalized_signature = signature
                last_code_change_iteration = self.context.agent_state.get("last_code_change_iteration", -1)
                seen_tests = self.context.agent_state.get("test_signature_seen", {})
                if not isinstance(seen_tests, dict):
                    seen_tests = {}
                seen_entry = seen_tests.get(signature)
                if isinstance(seen_entry, dict):
                    seen_at = seen_entry.get("code_change_iteration", -1)
                else:
                    seen_at = -1

                # Similarity guard: avoid enqueuing near-duplicate suites in the same code state.
                test_path = _extract_test_path_from_text(next_task.description or "")
                if test_path:
                    try:
                        stem = Path(test_path).name.lower()
                    except Exception:
                        stem = None
                    seen_sim = self.context.get_agent_state("test_similarity_seen", [])
                    if not isinstance(seen_sim, list):
                        seen_sim = []
                    canonical = None
                    if stem:
                        for entry in seen_sim:
                            try:
                                if (
                                    entry.get("stem") == stem
                                    and entry.get("code_change_iteration") == last_code_change_iteration
                                    and entry.get("path") != test_path
                                ):
                                    canonical = entry.get("path")
                                    break
                            except Exception:
                                continue
                    if canonical:
                        print(f"  [test-similar] Skipping similar test suite: {test_path} ~ {canonical} (code_change_iter={last_code_change_iteration})")
                        next_task.status = TaskStatus.STOPPED
                        next_task.result = json.dumps({
                            "skipped": True,
                            "reason": "similar test suite already queued",
                            "canonical": canonical,
                            "path": test_path,
                            "code_change_iteration": last_code_change_iteration,
                        })
                        completed_tasks_log.append(
                            f"[STOPPED] {next_task.description} | Reason: similar test suite already queued ({test_path} ~ {canonical})"
                        )
                        # Log the decision for visibility in run logs.
                        decision_log = {
                            "event": "test_similarity_skip",
                            "path": test_path,
                            "canonical": canonical,
                            "code_change_iteration": last_code_change_iteration,
                        }
                        try:
                            print(f"  [log] {json.dumps(decision_log, ensure_ascii=False)}")
                        except Exception:
                            pass
                        _record_test_signature_state(self.context, signature, "superseded")
                        # Suggest cleanup without auto-deleting.
                        if hasattr(self.context, "user_feedback"):
                            self.context.user_feedback.append(
                                f"Duplicate test detected: {test_path} is similar to {canonical}. Consider removing or archiving the duplicate."
                            )
                        continue
                    else:
                        if stem:
                            seen_sim.append({
                                "stem": stem,
                                "path": test_path,
                                "code_change_iteration": last_code_change_iteration,
                            })
                            self.context.set_agent_state("test_similarity_seen", seen_sim)

                # Allow first-run tests (code_change_iter = -1); only dedupe when we have a valid code-change iteration.
                if (
                    isinstance(last_code_change_iteration, int)
                    and isinstance(seen_at, int)
                    and last_code_change_iteration >= 0
                    and last_code_change_iteration == seen_at
                ):
                    print(f"  [test-dedupe] Skipping duplicate test task with signature: {signature} (code_change_iter={last_code_change_iteration})")
                    next_task.status = TaskStatus.STOPPED
                    next_task.result = json.dumps({
                        "skipped": True,
                        "reason": "duplicate test signature since last code change",
                        "signature": signature,
                        "code_change_iteration": last_code_change_iteration,
                    })
                    completed_tasks_log.append(f"[STOPPED] {next_task.description} | Reason: duplicate test signature (code_change_iter={last_code_change_iteration})")
                    _record_test_signature_state(self.context, signature, "blocked")
                    continue
                if _signature_state_matches(self.context, signature, "blocked"):
                    print(f"  [test-dedupe] Skipping blocked test signature: {signature} (code_change_iter={last_code_change_iteration})")
                    next_task.status = TaskStatus.STOPPED
                    next_task.result = json.dumps({
                        "skipped": True,
                        "reason": "test signature marked blocked for current code state",
                        "signature": signature,
                        "code_change_iteration": last_code_change_iteration,
                    })
                    completed_tasks_log.append(f"[STOPPED] {next_task.description} | Reason: test signature blocked (code_change_iter={last_code_change_iteration})")
                    _record_test_signature_state(self.context, signature, "blocked")
                    continue
                seen_tests[signature] = {"code_change_iteration": last_code_change_iteration}
                self.context.set_agent_state("test_signature_seen", seen_tests)

            # Get or initialize blocked_action_sigs from context
            if self.context:
                blocked_sigs = self.context.get_agent_state("blocked_action_sigs", set())
                if not isinstance(blocked_sigs, set):
                    blocked_sigs = set()
            else:
                blocked_sigs = set()

            # Check if this action is blocked
            if action_sig in blocked_sigs:
                print(f"  [blocked-action] This action is blocked due to previous repetition: {action_sig[:100]}...")
                # Auto-rewrite to a diagnostic fallback
                next_task.action_type = "analyze"
                next_task.description = (
                    f"BLOCKED: Previous approach failed repeatedly. "
                    f"Instead, analyze the root cause by running diagnostic tests or examining related code. "
                    f"Do NOT repeat: [{action_sig[:80]}...]"
                )
                print(f"  [blocked-action] Rewriting to: {next_task.description[:100]}...")
                # Reset streak since we rewrote the task
                repeat_same_action = 1
                last_task_signature = f"analyze::{next_task.description.strip().lower()}"

            # PERFORMANCE FIX 3: Block redundant file reads (same file 2+ times)
            if action_type_normalized in {'read', 'analyze', 'research'}:
                target_file = _extract_file_path_from_description(next_task.description)
                if target_file:
                    # Count how many times this file has been read
                    read_count = _count_file_reads(target_file, completed_tasks)
                    if read_count >= 2:
                        print(f"  [redundant-read] File '{target_file}' already read {read_count}x - BLOCKING")
                        # Block this specific action
                        blocked_sigs.add(action_sig)
                        if self.context:
                            self.context.set_agent_state("blocked_action_sigs", blocked_sigs)

                        # Force re-planning with constraint
                        self.context.add_agent_request(
                            "REDUNDANT_FILE_READ",
                            {
                                "agent": "Orchestrator",
                                "reason": f"File '{target_file}' already read {read_count} times",
                                "detailed_reason": (
                                    f"REDUNDANT READ BLOCKED: File '{target_file}' has already been read {read_count} times. "
                                    f"Use the cached information from previous reads, or propose an action (EDIT/ADD/TEST) instead of re-reading. "
                                    f"DO NOT propose reading this file again."
                                )
                            }
                        )
                        continue  # Skip to next iteration

            # PERFORMANCE FIX 1: Block excessive consecutive research
            if consecutive_reads >= MAX_CONSECUTIVE_READS and action_type_normalized in {'read', 'analyze', 'research', 'investigate', 'review'}:
                print(f"  [research-budget-exceeded] {consecutive_reads} consecutive research tasks - forcing action phase")
                # Force re-planning with constraint
                forced_next_task = None  # Clear any forced task
                # Add to failure notes for next planning iteration
                self.context.add_agent_request(
                    "RESEARCH_BUDGET_EXHAUSTED",
                    {
                        "agent": "Orchestrator",
                        "reason": f"Research budget exhausted ({consecutive_reads} consecutive READ tasks)",
                        "detailed_reason": (
                            "RESEARCH BUDGET EXHAUSTED: You have completed extensive research. "
                            "You MUST now propose a concrete action task (EDIT/ADD/TEST/DELETE), NOT another READ/ANALYZE/RESEARCH. "
                            "All necessary context is available in the completed tasks."
                        )
                    }
                )
                consecutive_reads = 0  # Reset counter
                continue  # Skip to next iteration with constraint

            # P0-3: Circuit breaker based on CONSECUTIVE streak, not total count
            if repeat_same_action >= 3:
                # Before failing, check if the goal was actually achieved
                action_lower = (next_task.action_type or "").lower()
                is_read_action = action_lower in {"read", "analyze", "research", "investigate", "review"}

                if is_read_action:
                    goal_achieved = _check_goal_likely_achieved(user_request, completed_tasks_log)
                    if goal_achieved:
                        print("\n[CIRCUIT BREAKER - GOAL ACHIEVED]")
                        print(f"Repeated verification action {action_counts[action_sig]}x, but goal appears achieved.")
                        print("Forcing successful completion.\n")
                        return True

                self.context.set_agent_state("no_retry", True)
                self.context.add_error(f"Circuit breaker: repeating action '{next_task.action_type}'")
                print("\n[🛑 CIRCUIT BREAKER TRIGGERED: REPEATED ACTION]")
                print(f"Repeated action {repeat_same_action}x consecutively (total {action_counts[action_sig]}x): [{(next_task.action_type or '').upper()}] {next_task.description}")
                
                # Enhanced circuit-breaker message
                recent_ledger_actions = ledger.get_recent_actions(5)
                last_verification = ledger.get_last_verification_status()
                blocked_sigs = ledger.get_blocked_action_sigs()
                
                print("\n--- DEBUG CONTEXT ---")
                print(f"Action Signature: {action_sig}")
                
                if recent_ledger_actions:
                    print("\nLast 5 Tool Calls:")
                    for i, a in enumerate(recent_ledger_actions, 1):
                        # Convert Path objects to strings for JSON serialization
                        args = a.get('arguments', {})
                        if args and isinstance(args, dict):
                            args_serializable = {k: str(v) if isinstance(v, Path) else v for k, v in args.items()}
                        else:
                            args_serializable = args
                        try:
                            args_str = json.dumps(args_serializable)
                        except (TypeError, ValueError):
                            args_str = str(args_serializable)
                        print(f"  {i}. {a['tool']}({args_str}) -> {a['status']}")
                
                if last_verification:
                    print("\nLast Verification Status:")
                    print(json.dumps(last_verification, indent=2)[:500])
                
                if blocked_sigs:
                    print("\nBlocked Signatures:")
                    for sig in blocked_sigs:
                        print(f"  - {sig}")
                
                print("\n---------------------\n")
                
                print("Blocking issue: planner is not making forward progress; refusing to repeat the same step.")
                return False
            if (
                config.LOOP_GUARD_ENABLED
                and action_counts[action_sig] == 2
                and (next_task.action_type or "").lower() in {"read", "analyze", "research"}
            ):
                print("  [loop-guard] Repeated READ/ANALYZE detected; checking if goal is achieved.")

                # P0-2: Block this action from being proposed again
                blocked_sigs.add(action_sig)
                if self.context:
                    self.context.set_agent_state("blocked_action_sigs", blocked_sigs)
                print(f"  [loop-guard] Blocked action signature: {action_sig[:100]}...")

                # P0-4: Track which files are being read repeatedly (language-agnostic)
                # Support common file extensions: Python, JS, TS, Vue, JSON, YAML, Markdown, etc.
                read_file_pattern = r'(?:\.\/)?([a-zA-Z0-9_/\\\-\.]+\.(?:py|js|ts|tsx|jsx|vue|json|yaml|yml|md|txt|toml|cfg|ini|c|cpp|h|hpp|rs|go|rb|php|java|cs|sql|sh|bat|ps1))'
                recent_read_files = []
                for task in reversed(completed_tasks[-5:]):  # Look at last 5 completed Task objects
                    if (task.action_type or "").lower() in {"read", "analyze", "research"}:
                        matches = re.findall(read_file_pattern, task.description or "", re.IGNORECASE)
                        recent_read_files.extend(matches)

                # Check if the same file has been read 3+ times
                from collections import Counter
                file_counts = Counter(recent_read_files)
                most_read_file, read_count = file_counts.most_common(1)[0] if file_counts else (None, 0)

                if read_count >= 2:
                    print(f"  [loop-guard] File '{most_read_file}' has been read {read_count} times - suggesting alternative approach.")
                    next_task.action_type = "debug"
                    next_task.description = (
                        f"The file {most_read_file} has been read {read_count} times without progress. "
                        f"Instead of reading it again, use run_python_diagnostic to test the actual runtime behavior. "
                        f"For example, test module imports, inspect object attributes, or verify auto-registration logic. "
                        f"This will reveal runtime issues that static code reading cannot detect."
                    )
                    print(f"  [loop-guard] Injecting diagnostic suggestion: {next_task.description[:100]}...")
                    return False  # Continue execution with the diagnostic task

                # Check if the goal appears to be achieved
                goal_achieved = _check_goal_likely_achieved(user_request, completed_tasks_log)
                if goal_achieved:
                    # Don't force completion without verification - inject verification task instead
                    print("  [loop-guard] Goal appears achieved - verifying completion before ending execution.")

                    # Check if we've already attempted final verification
                    loop_guard_verification_attempted = self.context.agent_state.get("loop_guard_verification_attempted", False)

                    if not loop_guard_verification_attempted:
                        # First time: inject a verification task
                        self.context.set_agent_state("loop_guard_verification_attempted", True)
                        next_task.action_type = "read"
                        next_task.description = (
                            "Perform final verification: list the target directory to confirm all expected files exist, "
                            "then run a quick syntax check (python -m compileall) and import test to ensure the refactoring works correctly."
                        )
                        print(f"  [loop-guard] Injecting final verification task: {next_task.description[:80]}...")
                    else:
                        # Already attempted verification - now we can safely complete
                        print("  [loop-guard] Verification already attempted - forcing completion.")
                        return True
                else:
                    # P0-5: Replace generic list_dir fallback with targeted, progress-making actions
                    target_path = _extract_file_path_from_description(next_task.description)
                    if target_path:
                        # Determine file type to suggest appropriate validation
                        file_ext = target_path.split('.')[-1].lower() if '.' in target_path else ''
                        root = Path(config.ROOT) if config.ROOT else Path.cwd()

                        if file_ext in ['js', 'ts', 'jsx', 'tsx', 'vue']:
                            # Frontend file - suggest build/lint
                            next_task.action_type = "test"
                            commands = _select_js_validation_commands(root)
                            if commands:
                                options = " or ".join(f"`{cmd}`" for cmd in commands)
                                next_task.description = (
                                    f"Instead of re-reading {target_path}, validate it by running {options}. "
                                    f"This will reveal actual issues rather than just reading the same file again."
                                )
                            else:
                                next_task.action_type = "analyze"
                                next_task.description = (
                                    f"Instead of re-reading {target_path}, analyze the cached file contents to: "
                                    f"1) Summarize what the file currently contains, "
                                    f"2) Identify what changes are still needed to satisfy acceptance criteria, "
                                    f"3) Determine if the implementation is actually complete or if specific issues remain."
                                )
                        elif file_ext in ['py']:
                            # Python file - suggest syntax check or relevant tests
                            if _has_python_markers(root):
                                next_task.action_type = "test"
                                next_task.description = (
                                    f"Instead of re-reading {target_path}, validate it by running "
                                    f"`python -m py_compile {target_path}` to check syntax. "
                                    f"This will reveal actual issues rather than static reading."
                                )
                            else:
                                next_task.action_type = "analyze"
                                next_task.description = (
                                    f"Instead of re-reading {target_path}, analyze the cached file contents to: "
                                    f"1) Summarize what the file currently contains, "
                                    f"2) Identify what changes are still needed to satisfy acceptance criteria, "
                                    f"3) Determine if the implementation is actually complete or if specific issues remain."
                                )
                        else:
                            # Generic file - analyze using cached contents
                            next_task.action_type = "analyze"
                            next_task.description = (
                                f"Instead of re-reading {target_path}, analyze the cached file contents to: "
                                f"1) Summarize what the file currently contains, "
                                f"2) Identify what changes are still needed to satisfy acceptance criteria, "
                                f"3) Determine if the implementation is actually complete or if specific issues remain."
                            )
                    else:
                        # No specific file - suggest running tests or verification
                        root = Path(config.ROOT) if config.ROOT else Path.cwd()
                        commands = _select_js_validation_commands(root)
                        if commands:
                            next_task.action_type = "test"
                            options = " or ".join(f"`{cmd}`" for cmd in commands)
                            next_task.description = (
                                "Instead of re-reading files, validate the current state by running "
                                f"{options}. This will reveal actual blocking issues that need to be fixed."
                            )
                        elif _has_python_markers(root):
                            next_task.action_type = "test"
                            next_task.description = (
                                "Instead of re-reading files, validate the current state by running "
                                "`python -m compileall .` to check for syntax errors. "
                                "This will reveal actual blocking issues that need to be fixed."
                            )
                        else:
                            next_task.action_type = "analyze"
                            next_task.description = (
                                "Instead of re-reading files, analyze the cached contents to identify what changes "
                                "are still needed and which files should be edited next."
                            )
                        # CRITICAL FIX: Set TDD flag so test failures are allowed in TDD mode
                        # Loop-guard test tasks are diagnostic - treat failures as informational, not blockers
                        if config.TDD_ENABLED:
                            self.context.agent_state["tdd_pending_green"] = True
                    print(f"  [loop-guard] Injecting targeted fallback: {next_task.description[:100]}...")

            # Fast-path: don't dispatch a no-op create_directory if it already exists.
            if (next_task.action_type or "").lower() == "create_directory":
                try:
                    desc = next_task.description or ""
                    candidate = ""

                    # Prefer explicit "directory <path>" phrasing.
                    m = re.search(r"directory\s+([^\s]+)", desc, flags=re.IGNORECASE)
                    if m:
                        candidate = m.group(1)

                    # Windows absolute path (drive letter).
                    if not candidate:
                        m = re.search(r"([A-Za-z]:\\\\[^\s]+)", desc)
                        if m:
                            candidate = m.group(1)

                    # Fallback: first path-ish token (includes ':' for Windows).
                    if not candidate:
                        m = re.search(r'([A-Za-z0-9_:\\-./\\\\]+)', desc)
                        if m:
                            candidate = m.group(1)

                    candidate = candidate.strip().strip('"').strip("'")
                    if candidate:
                        resolved = resolve_workspace_path(candidate, purpose="check create_directory preflight")
                        if resolved.abs_path.exists() and resolved.abs_path.is_dir():
                            next_task.status = TaskStatus.COMPLETED
                            next_task.result = json.dumps(
                                {
                                    "skipped": True,
                                    "reason": "directory already exists",
                                    "directory_abs": str(resolved.abs_path),
                                    "directory_rel": resolved.rel_path.replace("\\", "/"),
                                }
                            )
                            log_entry = f"[COMPLETED] (skipped) {next_task.description}"
                            completed_tasks_log.append(log_entry)
                            self.context.work_history = completed_tasks_log
                            print(f"  ✓ {log_entry}")
                            continue
                except Exception:
                    pass

            # STEP 2: EXECUTE
            execution_success = False
            verification_result = None
            deferred_tdd_test = False
            action_type_normalized = (next_task.action_type or "").strip().lower()
            # Auto-repair for injected add/write tasks that failed due to missing tool calls:
            if (
                action_type_normalized in {"add", "edit", "refactor"}
                and "injected" in getattr(next_task, "impact_scope", [])
            ):
                # If prior attempts failed without tool execution, force a default write tool
                if next_task.result and isinstance(next_task.result, str) and "Write action completed without tool execution" in next_task.result:
                    # Force a concrete write_file fallback
                    next_task.description = (
                        next_task.description
                        + " If tool call fails again, directly use write_file with a minimal failing test stub."
                    )
                    next_task.action_type = "add" if action_type_normalized == "add" else "edit"
                    # Mark to skip write dedupe on next attempt
                    next_task._write_signature = None
                # Always enforce a tool call for injected writes: instruct to call write_file with target path
                targets = _extract_task_paths(next_task) or []
                if targets:
                    target_hint = targets[0]
                    next_task.description = (
                        next_task.description
                        + f" You MUST call write_file with path '{target_hint}' and minimal failing test content; do NOT return plain text."
                    )
            if action_type_normalized == "test":
                blocked_tests = self.context.agent_state.get("blocked_test_signatures", {})
                if not isinstance(blocked_tests, dict):
                    blocked_tests = {}
                signature = _normalize_test_task_signature(next_task)
                record = blocked_tests.get(signature)
                if record:
                    last_change = self.context.agent_state.get("last_code_change_iteration", -1)
                    blocked_change = record.get("code_change_iteration", -1) if isinstance(record, dict) else -1
                    if isinstance(last_change, int) and isinstance(blocked_change, int) and last_change <= blocked_change:
                        next_task.status = TaskStatus.STOPPED
                        next_task.result = json.dumps(
                            {
                                "skipped": True,
                                "blocked": True,
                                "reason": "duplicate blocked test; no code changes since block",
                                "signature": signature,
                            }
                        )
                        log_entry = f"[STOPPED] (skipped) {next_task.description}"
                        completed_tasks_log.append(log_entry)
                        self.context.work_history = completed_tasks_log
                        print(f"  {Symbols.WARNING} {log_entry}")
                        continue
                    if isinstance(last_change, int) and isinstance(blocked_change, int) and last_change > blocked_change:
                        blocked_tests.pop(signature, None)
                        self.context.set_agent_state("blocked_test_signatures", blocked_tests)
            if (
                config.TDD_ENABLED
                and config.TDD_DEFER_TEST_EXECUTION
                and action_type_normalized == "test"
                and self.context.agent_state.get("tdd_pending_green")
                and not self.context.agent_state.get("tdd_require_test")
            ):
                deferred_tdd_test = True
                self.context.agent_state["tdd_deferred_test"] = True
                next_task.status = TaskStatus.STOPPED
                next_task.result = json.dumps(
                    {
                        "skipped": True,
                        "kind": "tdd_deferred_test",
                        "reason": "Tests deferred until implementation is completed; no tool execution.",
                    }
                )
                verification_result = VerificationResult(
                    passed=True,
                    message="TDD: deferred test execution until implementation.",
                    details={"tdd_deferred": True},
                )
                execution_success = True
            else:
                execution_success = self._dispatch_to_sub_agents(self.context, next_task)

            # STEP 3: VERIFY - This is the critical addition
            if execution_success and not deferred_tdd_test:
                # Only verify actions we have a handler for; otherwise skip verification noise.
                verifiable_actions = {
                    "refactor",
                    "add",
                    "create",
                    "edit",
                    "create_directory",
                    "test",
                    "read",
                    "analyze",
                    "research",
                    "investigate",
                }
                action_type = (next_task.action_type or "").lower()
                if action_type in verifiable_actions:
                    print(f"  {colorize('◌', Colors.BRIGHT_BLACK)} {colorize('Verifying...', Colors.BRIGHT_BLACK)}")
                    try:
                        verification_result = verify_task_execution(next_task, self.context)
                    except Exception as e:
                        verification_result = VerificationResult(
                            passed=False,
                            message=f"Verification exception: {e}",
                            details={'exception': traceback.format_exc()},
                            should_replan=True,
                        )
                    # Don't print the raw result object, just handle the outcome
                else:
                    verification_result = VerificationResult(
                        passed=True,
                        message="Verification skipped",
                        details={"action_type": action_type, "skipped": True},
                    )

                # If tests are being skipped because nothing has changed since a failure,
                # don't treat this as a verification failure (it causes loops). Instead,
                # bias planning toward a code-changing step.
                if (
                    (next_task.action_type or "").lower() == "test"
                    and verification_result.passed
                    and isinstance(getattr(verification_result, "details", None), dict)
                    and verification_result.details.get("blocked") is True
                ):
                    self.context.set_agent_state("tests_blocked_no_changes", True)
                    print(f"  {colorize(Symbols.WARNING, Colors.BRIGHT_YELLOW)} {colorize('Skipped re-running tests: no code changes detected.', Colors.BRIGHT_BLACK)}")

                if not verification_result.passed:
                    action_type = (next_task.action_type or "").lower()
                    details = getattr(verification_result, "details", {}) if verification_result else {}
                    is_blocked = isinstance(details, dict) and details.get("blocked") is True
                    skip_failure_counts = isinstance(details, dict) and details.get("skip_failure_counts") is True
                    verification_handled = False
                    no_tests_discovered = isinstance(details, dict) and details.get("no_tests_discovered") is True

                    if no_tests_discovered:
                        signature = getattr(next_task, "_normalized_signature", None) or _normalize_test_task_signature(next_task)
                        hint_key = "|".join(_collect_no_tests_hints(details)[:2]).lower() if isinstance(details, dict) else ""
                        no_tests_seen = self.context.agent_state.get("no_tests_sig_hint_seen", {})
                        if not isinstance(no_tests_seen, dict):
                            no_tests_seen = {}
                        last_code_change_iteration = self.context.agent_state.get("last_code_change_iteration", -1)
                        seen_entry = no_tests_seen.get((signature, hint_key))
                        if isinstance(seen_entry, dict):
                            prior_change = seen_entry.get("code_change_iteration", -1)
                            if (
                                isinstance(prior_change, int)
                                and isinstance(last_code_change_iteration, int)
                                and prior_change == last_code_change_iteration
                            ):
                                print(f"  [no-tests-repeat] Skipping repeat no-tests remediation for {signature} (code_change_iter={last_code_change_iteration})")
                                self.context.set_agent_state("tests_blocked_no_changes", True)
                                _record_test_signature_state(self.context, signature, "blocked")
                                next_task.status = TaskStatus.STOPPED
                                next_task.result = json.dumps(
                                    {
                                        "skipped": True,
                                        "reason": "no tests discovered repeated for same signature and hints",
                                        "signature": signature,
                                        "code_change_iteration": last_code_change_iteration,
                                    }
                                )
                                verification_handled = True
                                execution_success = True
                                continue
                        no_tests_seen[(signature, hint_key)] = {"code_change_iteration": last_code_change_iteration}
                        self.context.set_agent_state("no_tests_sig_hint_seen", no_tests_seen)

                        next_task.status = TaskStatus.STOPPED
                        next_task.error = _format_verification_feedback(verification_result)
                        next_task.result = json.dumps(
                            {
                                "inconclusive": True,
                                "no_tests_discovered": True,
                                "message": verification_result.message,
                            }
                        )
                        execution_success = True
                        self._handle_verification_failure(verification_result)
                        remediation_tasks = _build_no_tests_remediation_tasks(details)
                        diagnostic_tasks = _build_no_tests_diagnostic_tasks(details)
                        queued_tasks = remediation_tasks + diagnostic_tasks
                        rem_key = None
                        if remediation_tasks:
                            hint_key = "|".join(_collect_no_tests_hints(details)[:2]).lower()
                            if hint_key:
                                rem_key = f"no_tests_remediation::{hint_key}"
                        already_applied = rem_key and self.context.agent_state.get(rem_key)
                        if already_applied:
                            queued_tasks = diagnostic_tasks
                        else:
                            if rem_key:
                                self.context.set_agent_state(rem_key, True)
                        injected = _queue_diagnostic_tasks(self.context, queued_tasks)
                        if injected:
                            forced_next_task = injected
                            iteration -= 1
                            continue
                        _record_test_signature_state(self.context, signature, "blocked")
                        verification_handled = True

                    # PERFORMANCE FIX 2: Check if verification is inconclusive (P0-6)
                    if (
                        getattr(verification_result, 'inconclusive', False)
                        and not no_tests_discovered
                        and not (is_blocked and action_type == "test")
                    ):
                        print(f"  [inconclusive-verification] Edit completed but needs validation - injecting TEST task")

                        # Display inconclusive warning (already handled by _handle_verification_failure)
                        self._handle_verification_failure(verification_result)

                        # Determine appropriate test command based on file type
                        file_path = verification_result.details.get('file_path', '')
                        suggestion = verification_result.details.get('suggestion', '')

                        # Try to find specific test file for the changed file
                        test_file_hint = None
                        if file_path:
                            p = Path(file_path)
                            filename = p.stem  # e.g., "app" from "app.js"
                            parent_dir = str(p.parent) if str(p.parent) != '.' else ''

                            # Common test file patterns (expanded for better coverage)
                            test_patterns = [
                                # Standard test directory patterns
                                f"tests/{filename}.test{p.suffix}",
                                f"test/{filename}.test{p.suffix}",
                                f"tests/{filename}.spec{p.suffix}",
                                f"test/{filename}.spec{p.suffix}",
                                # __tests__ directory (React/Jest convention)
                                f"__tests__/{filename}.test{p.suffix}",
                                f"{parent_dir}/__tests__/{filename}.test{p.suffix}",
                                f"{parent_dir}/__tests__/{filename}.spec{p.suffix}",
                                # Co-located tests
                                f"{parent_dir}/{filename}.test{p.suffix}",
                                f"{parent_dir}/{filename}.spec{p.suffix}",
                                # Python-specific patterns
                                f"tests/test_{filename}.py" if p.suffix == '.py' else None,
                                f"test/test_{filename}.py" if p.suffix == '.py' else None,
                                # Pattern: tests/path/to/file.test.ext
                                f"tests/{parent_dir}/{filename}.test{p.suffix}" if parent_dir else None,
                                f"test/{parent_dir}/{filename}.test{p.suffix}" if parent_dir else None,
                            ]

                            # Filter out None values
                            test_patterns = [p for p in test_patterns if p is not None]

                            # Check which test file exists
                            workspace_root = self.context.workspace_root if self.context and hasattr(self.context, 'workspace_root') else Path.cwd()
                            root = Path(workspace_root) if workspace_root else Path.cwd()

                            for pattern in test_patterns:
                                test_path = root / pattern
                                if test_path.exists():
                                    test_file_hint = str(test_path.relative_to(root))
                                    break

                        # Build test description with specific file when possible
                        # IMPORTANT: Only run the specific test file, not global tests
                        if '.js' in file_path or '.ts' in file_path or '.jsx' in file_path or '.tsx' in file_path or '.vue' in file_path:
                            if test_file_hint:
                                # Run only the specific test file
                                test_description = f"Run specific test for {file_path}: npm test -- {test_file_hint}"
                            else:
                                # If no test file found, run syntax validation only (don't run all tests)
                                test_description = f"Validate syntax of {file_path}: node --check {file_path}"
                        elif 'pytest' in suggestion or '.py' in file_path:
                            if test_file_hint:
                                # Run only the specific test file
                                test_description = f"Run specific test for {file_path}: pytest {test_file_hint} -v"
                            else:
                                # If no test file found, run syntax validation only
                                test_description = f"Validate syntax of {file_path}: python -m py_compile {file_path}"
                        else:
                            # For other file types, skip testing (already validated in quick_verify)
                            test_description = f"Syntax validation completed for {file_path}"

                        # Inject TEST task to validate the edit
                        forced_next_task = Task(
                            description=test_description,
                            action_type="test"
                        )

                        # Mark current task as completed (edit succeeded, just needs validation)
                        next_task.status = TaskStatus.COMPLETED
                        execution_success = True

                        # Continue to next iteration with the TEST task
                        continue

                    if action_type == "test" and not no_tests_discovered:
                        queued = _maybe_queue_hint_command(
                            self.context,
                            details if isinstance(details, dict) else {},
                            retry_key_prefix="test_failure_hint_cmd",
                            current_iteration=iteration,
                        )
                        if queued:
                            forced_next_task = _pop_diagnostic_task(self.context)
                            iteration -= 1
                            continue

                    if getattr(verification_result, "inconclusive", False) and is_blocked:
                        if action_type == "test":
                            fallback_cmd = _select_test_fallback_command(next_task.description or "", config.ROOT or Path.cwd())
                            if fallback_cmd:
                                signature = _normalize_test_task_signature(next_task)
                                recovery_key = f"test_blocked_fallback::{signature}"
                                if not self.context.agent_state.get(recovery_key):
                                    self.context.set_agent_state(recovery_key, True)
                                    forced_next_task = Task(
                                        description=f"Run {fallback_cmd}",
                                        action_type="test",
                                    )
                                    next_task.status = TaskStatus.STOPPED
                                    next_task.error = _format_verification_feedback(verification_result)
                                    next_task.result = json.dumps(
                                        {
                                            "inconclusive": True,
                                            "blocked": True,
                                            "message": verification_result.message,
                                            "suggested_command": fallback_cmd,
                                        }
                                    )
                                    execution_success = True
                                    self._handle_verification_failure(verification_result)
                                    iteration -= 1
                                    continue
                        next_task.status = TaskStatus.STOPPED
                        next_task.error = _format_verification_feedback(verification_result)
                        next_task.result = json.dumps(
                            {
                                "inconclusive": True,
                                "blocked": True,
                                "message": verification_result.message,
                            }
                        )
                        if action_type == "test":
                            blocked_tests = self.context.agent_state.get("blocked_test_signatures", {})
                            if not isinstance(blocked_tests, dict):
                                blocked_tests = {}
                            signature = _normalize_test_task_signature(next_task)
                            blocked_tests[signature] = {
                                "blocked_iteration": iteration,
                                "code_change_iteration": self.context.agent_state.get("last_code_change_iteration", -1),
                            }
                            self.context.set_agent_state("blocked_test_signatures", blocked_tests)
                            _record_test_signature_state(self.context, signature, "blocked")
                        execution_success = True
                        self._handle_verification_failure(verification_result)
                        verification_handled = True

                    # Verification definitely failed - mark task as failed and mark for re-planning
                    if not verification_handled:
                        next_task.status = TaskStatus.FAILED
                        next_task.error = _format_verification_feedback(verification_result)
                        execution_success = False

                        # Display detailed debug information
                        self._handle_verification_failure(verification_result)

                        # Anti-loop: stop if the same verification failure repeats.
                        # Use robust error signature that identifies root error type
                        if skip_failure_counts:
                            print("  [skip-failure-counts] Verification marked as inconclusive/blocked; skipping circuit-breaker counts")
                        else:
                            error_sig = _create_error_signature(verification_result)
                            failure_sig = f"{(next_task.action_type or '').lower()}::{error_sig}"
                            failure_counts[failure_sig] += 1
                            repeat_break_threshold = 3
                            if action_type == "test":
                                repeat_break_threshold = 5

                        # Extract and save failing test file for targeted re-testing
                        all_error_text = f"{verification_result.message} "
                        if hasattr(verification_result, 'details') and isinstance(verification_result.details, dict):
                            for key in ['test_output', 'stdout', 'stderr', 'output']:
                                val = verification_result.details.get(key, '')
                                if isinstance(val, str):
                                    all_error_text += val + " "

                        failing_test_file = _extract_failing_test_file(all_error_text)
                        if failing_test_file:
                            self.context.set_agent_state("last_failing_test_file", failing_test_file)
                            print(f"  [test-targeting] Detected failing test: {failing_test_file}")

                        if not skip_failure_counts:
                            # Log the detected error signature for debugging
                            if failure_counts[failure_sig] > 1:
                                print(f"  [circuit-breaker] Same error detected {failure_counts[failure_sig]}x: {error_sig}")

                            if failure_counts[failure_sig] == 2:
                                diag_key = f"diagnostic::{failure_sig}"
                                already_injected = self.context.agent_state.get(diag_key, False)
                                if not already_injected:
                                    diagnostic_tasks = _build_diagnostic_tasks_for_failure(next_task, verification_result)
                                    injected = _queue_diagnostic_tasks(self.context, diagnostic_tasks)
                                    if injected:
                                        self.context.agent_state[diag_key] = True
                                        forced_next_task = injected
                                        iteration -= 1
                                        continue

                            # Track syntax repair attempts separately
                            syntax_repair_key = f"syntax_repair::{failure_sig}"
                            syntax_repair_attempts = self.context.agent_state.get(syntax_repair_key, 0)

                        if not skip_failure_counts and failure_counts[failure_sig] >= repeat_break_threshold:
                            # PRIORITY 2 FIX: ESCALATION for repeated replace_in_file failures
                            # Check if this is a replace_in_file failure that should escalate to write_file
                            tool_events = getattr(next_task, "tool_events", None) or []
                            used_replace_in_file = any(
                                str(ev.get("tool") or "").lower() == "replace_in_file"
                                for ev in tool_events
                            )

                            escalation_key = f"edit_escalation::{failure_sig}"
                            already_escalated = self.context.agent_state.get(escalation_key, False)

                            if used_replace_in_file and not already_escalated and (next_task.action_type or "").lower() == "edit":
                                # Third failure using replace_in_file - escalate to write_file strategy
                                print(f"  {colorize(Symbols.WARNING, Colors.BRIGHT_YELLOW)} {colorize('ESCALATION: replace_in_file failed 3x - suggesting write_file strategy', Colors.BRIGHT_WHITE)}")

                                # Mark that we've escalated this specific failure
                                self.context.set_agent_state(escalation_key, True)

                                # Add agent request to guide planner toward write_file
                                self.context.add_agent_request(
                                    "EDIT_STRATEGY_ESCALATION",
                                    {
                                        "agent": "Orchestrator",
                                        "reason": f"replace_in_file failed {failure_counts[failure_sig]} times - switch to write_file",
                                        "detailed_reason": (
                                            f"EDIT STRATEGY ESCALATION: The 'replace_in_file' approach has failed {failure_counts[failure_sig]} times "
                                            f"for this task. This usually means the 'find' string cannot match the actual file content.\n\n"
                                            "REQUIRED NEXT STEPS:\n"
                                            "1. Use 'read_file' to get the complete current content of the target file\n"
                                            "2. Manually construct the desired new content by modifying what you read\n"
                                            "3. Use 'write_file' to completely rewrite the file with the new content\n"
                                            "4. Do NOT use 'replace_in_file' again - it has proven unreliable for this file\n\n"
                                            "This approach is more reliable than trying to match exact substrings."
                                        )
                                    }
                                )

                                # Reset failure count to give write_file strategy a chance
                                failure_counts[failure_sig] = 0

                                # Continue planning with the new constraint
                                iteration -= 1  # Don't count this as a regular iteration
                                continue

                            # GENERIC AUTO-RECOVERY: Let the LLM analyze and fix ANY type of error
                            # This is sustainable - no need to add handlers for each tool/framework
                            generic_repair_key = f"generic_repair::{failure_sig}"
                            generic_repair_attempts = self.context.agent_state.get(generic_repair_key, 0)

                            # Track total recovery attempts across ALL errors to prevent infinite loops
                            total_recovery_attempts = self.context.agent_state.get("total_recovery_attempts", 0)

                            # HARD LIMIT: Stop if we've made 10 recovery attempts total, regardless of error type
                            if total_recovery_attempts >= 10:
                                summary = self._build_failure_summary(
                                    next_task,
                                    verification_result,
                                    failure_sig,
                                    failure_counts[failure_sig],
                                )
                                self.context.set_agent_state("no_retry", True)
                                self.context.add_error(summary)
                                print(f"\n[{colorize('🛑 CIRCUIT BREAKER: RECOVERY LIMIT EXCEEDED', Colors.BRIGHT_RED, bold=True)}]")
                                print(f"{colorize(f'Made {total_recovery_attempts} recovery attempts across all errors.', Colors.BRIGHT_WHITE)}")
                                print(f"{colorize('This indicates a fundamental issue that cannot be auto-fixed.', Colors.BRIGHT_WHITE)}")
                                print(f"{colorize('Manual intervention required.', Colors.BRIGHT_YELLOW)}\n")
                                print(f"{colorize(Symbols.INFO, Colors.BRIGHT_BLUE)} {summary}")
                                return False

                            if generic_repair_attempts < 5:
                                # Enter generic repair mode - LLM will diagnose and fix
                                print(f"  {colorize(Symbols.WARNING, Colors.BRIGHT_YELLOW)} {colorize('Entering automatic error recovery mode (attempt ' + str(generic_repair_attempts + 1) + '/5)', Colors.BRIGHT_WHITE)}")

                                # Increment generic repair counter
                                self.context.set_agent_state(generic_repair_key, generic_repair_attempts + 1)
                                self.context.set_agent_state("total_recovery_attempts", total_recovery_attempts + 1)

                                # Create a generic repair task with full error context
                                repair_task = _create_generic_repair_task(
                                    failed_task=next_task,
                                    verification_result=verification_result,
                                    attempt_number=generic_repair_attempts + 1,
                                    failure_count=failure_counts[failure_sig],
                                    context=self.context  # Pass context for feedback loop
                                )

                                # Reset general failure count to allow more attempts
                                failure_counts[failure_sig] = 0

                                # Replace the failed task with the repair task
                                forced_next_task = repair_task
                                iteration -= 1  # Don't count this as a regular iteration
                                continue

                            # FALLBACK: Generic repair exhausted (5 attempts) - try git revert as last resort
                            is_syntax_error = _check_syntax_error_in_verification(verification_result)

                            if is_syntax_error and generic_repair_attempts >= 5:
                                # Generic repair failed - try auto-revert as last resort for syntax errors
                                print(f"  {colorize(Symbols.CROSS, Colors.BRIGHT_RED)} {colorize('Automatic repair exhausted. Attempting git revert...', Colors.BRIGHT_WHITE)}")

                                reverted_files = _attempt_git_revert_for_syntax_errors(next_task)
                                if reverted_files:
                                    print(f"  {colorize(Symbols.CHECK, Colors.BRIGHT_GREEN)} {colorize('Auto-reverted: ' + ', '.join(reverted_files), Colors.BRIGHT_BLACK)}")
                                    # Clear repair counter
                                    self.context.set_agent_state(generic_repair_key, 0)
                                    return False  # Stop execution, but code is in working state
                                else:
                                    print(f"  {colorize(Symbols.CROSS, Colors.BRIGHT_RED)} {colorize('Auto-revert failed. Manual intervention required.', Colors.BRIGHT_RED)}")

                            # Non-syntax errors or revert failed - use summary fast-exit
                            summary = _summarize_repeated_failure(
                                next_task,
                                verification_result,
                                failure_sig,
                                failure_counts[failure_sig],
                            )
                            self.context.set_agent_state("no_retry", True)
                            self.context.add_error(summary)
                            print(f"  {colorize(Symbols.CROSS, Colors.BRIGHT_RED)} {colorize('Circuit Breaker: repeated failure ' + str(failure_counts[failure_sig]) + 'x. Stopping loop.', Colors.BRIGHT_RED)}")
                            print(f"  {colorize(Symbols.INFO, Colors.BRIGHT_BLUE)} {summary}")
                            return False

                    # Try to decompose the failed task into more granular steps.
                    # Decomposing test failures is usually counterproductive (it tends to produce vague edits);
                    # let the planner pick a focused debug/fix step instead.
                    if verification_result.should_replan and (next_task.action_type or "").lower() != "test":
                        decomposed_task = self._decompose_extraction_task(next_task)
                        if decomposed_task:
                            print(f"  {colorize('◆', Colors.BRIGHT_CYAN)} {colorize('Breaking down into smaller steps', Colors.WHITE)}")
                            forced_next_task = decomposed_task
                            iteration -= 1  # Don't count failed task as an iteration
                else:
                    # If we've just verified a successful test and no code has changed since,
                    # avoid re-running the same test, but continue the plan instead of exiting early.
                    if (next_task.action_type or "").lower() == "test" and _did_run_real_tests(next_task, verification_result):
                        signature = getattr(next_task, "_normalized_signature", None) or _normalize_test_task_signature(next_task)
                        _record_test_signature_state(self.context, signature, "passed")
                        last_test_rc = self.context.agent_state.get("last_test_rc")
                        last_test_iteration = self.context.agent_state.get("last_test_iteration", -1)
                        last_code_change_iteration = self.context.agent_state.get("last_code_change_iteration", -1)
                        if (
                            last_test_rc == 0
                            and isinstance(last_test_iteration, int)
                            and isinstance(last_code_change_iteration, int)
                            and last_code_change_iteration != -1
                            and last_code_change_iteration <= last_test_iteration
                        ):
                            print("\n[OK] Verification passed and no code changed since; skipping redundant test reruns and continuing.")
                            # Mark the signature as passed for this code state so future identical test tasks are skipped.
                            next_task.status = TaskStatus.COMPLETED
                            continue

            action_type = (next_task.action_type or "").lower()
            if next_task.status == TaskStatus.COMPLETED and action_type in {"edit", "add", "refactor", "create_directory"}:
                # Check if this was an actual code change or just a cosmetic/no-op edit
                # Look at verification details or task result to confirm real changes
                is_real_change = True

                # Check verification details for evidence of actual changes
                if hasattr(verification_result, 'details') and isinstance(verification_result.details, dict):
                    # For edits: check if replace_in_file actually replaced something
                    # Check tool events from task
                    events = getattr(next_task, "tool_events", None) or []
                    for ev in reversed(list(events)):
                        tool = str(ev.get("tool") or "").lower()
                        if tool in {"replace_in_file", "write_file", "apply_patch"}:
                            raw_result = ev.get("raw_result")
                            if isinstance(raw_result, str):
                                try:
                                    payload = json.loads(raw_result)
                                    if isinstance(payload, dict):
                                        # Check if no actual changes were made
                                        replaced = payload.get("replaced", 1)  # Default to 1 (assume change)
                                        if replaced == 0:
                                            is_real_change = False
                                            print(f"  [!] Edit task completed but made no actual changes (cosmetic only)")
                                            break
                                except Exception:
                                    pass

                if is_real_change:
                    self.context.set_agent_state("last_code_change_iteration", iteration)
                    self.context.set_agent_state("tests_blocked_no_changes", False)
                else:
                    print(f"  [!] Skipping last_code_change_iteration update - no real changes detected")

            # STEP 4: REPORT
            if next_task.status == TaskStatus.COMPLETED:
                # Reset transformation counter on successful completion
                self.context.set_agent_state("transformation_count", 0)
                if self.context.state_manager:
                    self.context.state_manager.on_task_completed(next_task)
            elif next_task.status == TaskStatus.FAILED:
                if self.context.state_manager:
                    self.context.state_manager.on_task_failed(next_task)

            status_tag = f"[{next_task.status.name}]"
            log_entry = f"{status_tag} {next_task.description}"
            
            error_detail = ""
            if next_task.status == TaskStatus.FAILED and next_task.error:
                error_detail = str(next_task.error)
            
            # Add a summary of the tool output to the log
            output_detail = ""
            if hasattr(next_task, 'tool_events') and next_task.tool_events:
                # Summarize the result of the last tool event
                event = next_task.tool_events[-1]
                tool_output = event.get('raw_result')
                if isinstance(tool_output, str):
                    summary = tool_output.strip()
                    # If the error is already in the summary, don't repeat it
                    if error_detail and error_detail in summary:
                        output_detail = summary
                        error_detail = ""
                    else:
                        output_detail = summary
                    
                    if len(output_detail) > 300:
                        output_detail = output_detail[:300] + '...'

            if error_detail:
                log_entry += f" | Reason: {error_detail}"
            if output_detail:
                log_entry += f" | Output: {output_detail}"
            
            if verification_result and not verification_result.passed:
                # Only add verification message if it's not redundant with error/output
                v_msg = verification_result.message
                if v_msg and v_msg not in log_entry:
                    log_entry += f" | Verification: {v_msg}"

            completed_tasks_log.append(log_entry)
            completed_tasks.append(next_task)  # Track actual Task object
            self.context.work_history = completed_tasks_log  # Sync to context for logging/visibility
            self.context.save_history()

            try:
                recent = self.context.agent_state.get("recent_tasks", [])
                if not isinstance(recent, list):
                    recent = []
                recent.append(f"{next_task.action_type or '?'}: {next_task.description}")
                self.context.agent_state["recent_tasks"] = recent[-8:]
            except Exception:
                pass

            # Filter output from console display unless debug is enabled
            display_entry = log_entry
            if not self.debug_logger.enabled and "| Output:" in display_entry:
                # Split by output marker
                parts = display_entry.split(" | Output:")
                base_part = parts[0]
                
                # Check if we need to preserve verification part which comes after output
                verification_part = ""
                if len(parts) > 1 and " | Verification:" in parts[1]:
                    # Extract verification part from the second chunk
                    v_split = parts[1].split(" | Verification:", 1)
                    if len(v_split) > 1:
                        verification_part = " | Verification:" + v_split[1]
                
                display_entry = base_part + verification_part

            print(f"  {'✓' if next_task.status == TaskStatus.COMPLETED else '✗'} {display_entry}")

            # Check for replan requests from agents
            if self.context and self.context.agent_requests:
                replan_req = next((r for r in self.context.agent_requests if r.get("type") == "REPLAN_REQUEST"), None)
                if replan_req:
                    # Make replanning look like a normal step, not an error
                    reason = replan_req['details'].get('reason', 'Refining approach')
                    print(f"\n  {colorize('◆', Colors.BRIGHT_CYAN)} {colorize('Refining strategy', Colors.WHITE)}: {reason}")
                    self.context.add_insight("orchestrator", "agent_request_triggered_replan", replan_req["details"])

                    # Force replan on next iteration
                    self.context.plan = ExecutionPlan(tasks=[])
                    forced_next_task = None
                    # Note: agent_requests are cleared in next iteration start
                    continue

            self.context.update_repo_context()
            clear_analysis_caches()

        return False

    def _handle_verification_failure(self, verification_result: VerificationResult):
        """Handle and display detailed information about verification failures.

        P0-6: Distinguish inconclusive results from actual failures.
        """
        # P0-6: Use different colors/symbols for inconclusive vs failed
        if getattr(verification_result, 'inconclusive', False):
            print(f"\n{colorize('  ' + Symbols.WARNING + ' Verification Inconclusive', Colors.BRIGHT_YELLOW, bold=True)}")
            message_color = Colors.BRIGHT_YELLOW
        else:
            print(f"\n{colorize('  ' + Symbols.CROSS + ' Verification Details', Colors.BRIGHT_RED, bold=True)}")
            message_color = Colors.BRIGHT_RED

        # Display main message (which includes issue descriptions)
        if verification_result.message:
            print(f"    {colorize(verification_result.message, message_color)}")

        # Display debug information if available
        if verification_result.details and "debug" in verification_result.details:
            debug_info = verification_result.details["debug"]
            for key, value in debug_info.items():
                print(f"    {colorize(key + ':', Colors.BRIGHT_BLACK)} {value}")

        # Display test output for failed tests (from test execution)
        details = verification_result.details or {}
        test_output = details.get("output", "")
        if test_output and isinstance(test_output, str) and test_output.strip():
            print(f"\n    {colorize('Test Output:', Colors.BRIGHT_BLACK)}")
            # Show last 15 lines of test output for context
            for line in test_output.strip().splitlines()[-15:]:
                print(f"      {line}")

        # Display strict/validation command outputs (compileall/pytest/etc)
        for block_key in ("strict", "validation"):
            block = details.get(block_key)
            if not isinstance(block, dict) or not block:
                continue
            for label, res in block.items():
                if not isinstance(res, dict):
                    continue
                rc = res.get("rc")
                stdout = (res.get("stdout") or "").strip()
                stderr = (res.get("stderr") or "").strip()

                if rc is not None and rc != 0:
                    print(f"    {colorize('[' + label + '] failed (rc=' + str(rc) + ')', Colors.BRIGHT_YELLOW)}")
                    if stdout:
                        for line in str(stdout).splitlines()[-5:]: # Only show last 5 lines
                            print(f"      {colorize('stdout:', Colors.BRIGHT_BLACK)} {line}")
                    if stderr:
                        for line in str(stderr).splitlines()[-5:]:
                            print(f"      {colorize('stderr:', Colors.BRIGHT_BLACK)} {line}")

        # P0-6: Different message for inconclusive vs failed
        if getattr(verification_result, 'inconclusive', False):
            print("\n[NEXT ACTION: Run validation to confirm changes are correct (tests/syntax checks)...]\n")
        else:
            print("\n[NEXT ACTION: Adjusting approach based on feedback...]\n")

    def _dispatch_to_sub_agents(self, context: RevContext, task: Optional[Task] = None) -> bool:
        """Dispatches tasks to appropriate sub-agents."""
        if task is None:
            if not context.plan or not context.plan.tasks:
                return False
            task = context.plan.tasks[0]

        if task.status == TaskStatus.COMPLETED:
            return True

        task = self._apply_read_only_constraints(task)

        # Guardrail: if the planner accidentally schedules a file creation as a directory creation
        # (common in decomposed tasks like "create __init__.py"), coerce to `add` so we can use write_file.
        if (task.action_type or "").lower() == "create_directory" and re.search(r"\.py\b", task.description, re.IGNORECASE):
            task.action_type = "add"

        # Normalize action types (aliases + fuzzy typos) before registry lookup.
        task.action_type = normalize_action_type(
            task.action_type,
            available_actions=AgentRegistry.get_registered_action_types(),
        )

        if task.action_type not in AgentRegistry.get_registered_action_types():
            task.status = TaskStatus.FAILED
            task.error = f"No agent available to handle action type: '{task.action_type}'"
            return False

        self._maybe_set_workdir_for_task(task)

        task.status = TaskStatus.IN_PROGRESS
        verification_result: Optional[VerificationResult] = None
        try:
            # Build a focused context snapshot (selection pipeline); agents will also
            # use this same pipeline when selecting tools and composing prompts.
            if self._context_builder is None:
                self._context_builder = ContextBuilder(self.project_root)
            try:
                tool_names = [t.get("function", {}).get("name") for t in get_available_tools() if isinstance(t, dict)]
                bundle = self._context_builder.build(
                    query=f"{context.user_request}\n\n{task.action_type}: {task.description}",
                    tool_universe=get_available_tools(),
                    tool_candidates=[n for n in tool_names if isinstance(n, str)],
                    top_k_tools=7,
                )
                context.agent_insights["context_builder"] = {
                    "selected_tools": [t.name for t in bundle.selected_tool_schemas],
                    "selected_code": [c.location for c in bundle.selected_code_chunks],
                    "selected_docs": [d.location for d in bundle.selected_docs_chunks],
                }
            except Exception:
                # Best-effort: never fail dispatch due to context retrieval.
                pass

            agent = AgentRegistry.get_agent_instance(task.action_type)
            try:
                self.debug_logger.set_trace_context({
                    "task_id": task.task_id,
                    "action_type": task.action_type,
                    "task_description": task.description,
                    "agent": agent.__class__.__name__,
                    "phase": getattr(context, "current_phase", None).value if getattr(context, "current_phase", None) else None,
                    "iteration": context.agent_state.get("current_iteration") if context else None,
                })
            except Exception:
                pass
            result = agent.execute(task, context)

            # Global recovery: if an agent returns a tool-call payload as plain text, execute it here.
            # This avoids "death spirals" where the model can describe a tool call but fails to emit
            # structured tool_calls for the runtime adapter.
            if isinstance(result, str):
                try:
                    allowed = allowed_tools_for_action(task.action_type)
                    if allowed is None:
                        allowed = [
                            t.get("function", {}).get("name")
                            for t in get_available_tools()
                            if isinstance(t, dict)
                        ]
                    executed = maybe_execute_tool_call_from_text(
                        result,
                        allowed_tools=[n for n in allowed if isinstance(n, str)],
                    )
                except Exception:
                    executed = None

                if executed is not None:
                    print(f"  -> Recovered tool call from text output: {executed.tool_name}")
                    result = build_subagent_output(
                        agent_name=agent.__class__.__name__,
                        tool_name=executed.tool_name,
                        tool_args=executed.tool_args,
                        tool_output=executed.tool_output,
                        context=context,
                        task_id=task.task_id,
                    )

            task.result = result
            try:
                _append_task_tool_event(task, result)
            except Exception:
                pass
            ok, constraint_error = _enforce_action_tool_constraints(task)
            if not ok:
                if (task.action_type or "").lower() == "test":
                    signature = _normalize_test_task_signature(task)
                    fallback_key = f"test_tool_fallback::{signature}"
                    if not context.agent_state.get(fallback_key):
                        explicit_cmd = _extract_explicit_test_command(task.description or "")
                        if not explicit_cmd and isinstance(task.result, str):
                            explicit_cmd = _extract_explicit_test_command(task.result)
                        if explicit_cmd:
                            explicit_cmd = _maybe_correct_explicit_test_command(explicit_cmd, task.description or "")
                            context.set_agent_state(fallback_key, True)
                            print(f"  [tool-recovery] Executing fallback test command: {explicit_cmd}")
                            raw_result = execute_tool("run_cmd", {"cmd": explicit_cmd}, agent_name="orchestrator")
                            task.result = build_subagent_output(
                                agent_name="Orchestrator",
                                tool_name="run_cmd",
                                tool_args={"cmd": explicit_cmd},
                                tool_output=raw_result,
                                context=context,
                                task_id=task.task_id,
                            )
                            try:
                                _append_task_tool_event(task, task.result)
                            except Exception:
                                pass
                            ok, constraint_error = _enforce_action_tool_constraints(task)
                            if ok:
                                return True
                        else:
                            task_index = task.task_id if isinstance(task.task_id, int) else None
                            current_iter = context.agent_state.get("current_iteration", 0)
                            index_value = task_index if isinstance(task_index, int) else current_iter
                            if isinstance(index_value, int) and index_value < 50:
                                desc_lower = (task.description or "").lower()
                                if any(token in desc_lower for token in ("build", "compile", "compilation", "structural integrity")):
                                    fallback_cmd = _select_build_fallback_command(task.description or "", config.ROOT or Path.cwd())
                                else:
                                    fallback_cmd = _select_test_fallback_command(task.description or "", config.ROOT or Path.cwd())
                                if fallback_cmd:
                                    context.set_agent_state(fallback_key, True)
                                    print(f"  [tool-recovery] Executing fallback test command: {fallback_cmd}")
                                    raw_result = execute_tool("run_cmd", {"cmd": fallback_cmd}, agent_name="orchestrator")
                                    task.result = build_subagent_output(
                                        agent_name="Orchestrator",
                                        tool_name="run_cmd",
                                        tool_args={"cmd": fallback_cmd},
                                        tool_output=raw_result,
                                        context=context,
                                        task_id=task.task_id,
                                    )
                                    try:
                                        _append_task_tool_event(task, task.result)
                                    except Exception:
                                        pass
                                    ok, constraint_error = _enforce_action_tool_constraints(task)
                                    if ok:
                                        return True
                            else:
                                suggestion = _select_test_fallback_command(task.description or "", config.ROOT or Path.cwd())
                                if suggestion:
                                    task.result = json.dumps(
                                        {
                                            "suggested_command": suggestion,
                                            "reason": "Test task produced no tool call; suggested command not executed",
                                        }
                                    )

                    blocked_tests = context.agent_state.get("blocked_test_signatures", {})
                    if not isinstance(blocked_tests, dict):
                        blocked_tests = {}
                    blocked_tests[signature] = {
                        "blocked_iteration": context.agent_state.get("current_iteration"),
                        "code_change_iteration": context.agent_state.get("last_code_change_iteration", -1),
                        "reason": str(constraint_error),
                    }
                    context.set_agent_state("blocked_test_signatures", blocked_tests)
                    task.status = TaskStatus.STOPPED
                    task.error = constraint_error
                    return False
                task.status = TaskStatus.FAILED
                task.error = constraint_error

                # RECOVERY LOGIC: Track tool execution failures and provide explicit guidance
                if "Write action completed without tool execution" in constraint_error or "Write action blocked by overwrite policy" in constraint_error:
                    action = (task.action_type or "").lower()
                    if action in WRITE_ACTIONS:
                        write_signature = getattr(task, "_write_signature", None) or _normalize_write_task_signature(task)
                        write_state = context.agent_state.get("write_signature_state", {})
                        if not isinstance(write_state, dict):
                            write_state = {}
                        status = "blocked" if "overwrite policy" in constraint_error.lower() else "no_tool"
                        write_state[write_signature] = {
                            "code_change_iteration": context.agent_state.get("last_code_change_iteration", -1),
                            "status": status,
                        }
                        context.set_agent_state("write_signature_state", write_state)

                if "Write action completed without tool execution" in constraint_error:
                    tool_failure_count = context.agent_state.get("tool_execution_failure_count", 0)
                    context.set_agent_state("tool_execution_failure_count", tool_failure_count + 1)

                    print(f"\n  ⚠️  {colorize('LLM FAILED TO EXECUTE TOOLS', Colors.BRIGHT_YELLOW)} (failure #{tool_failure_count + 1})")
                    print(f"  {colorize('The LLM returned text instead of calling tools', Colors.BRIGHT_BLACK)}")

                    # Circuit breaker: Too many tool execution failures
                    if tool_failure_count >= 3:
                        fallback_model = getattr(config, "EXECUTION_MODEL_FALLBACK", "").strip()
                        auto_switched = bool(context.agent_state.get("auto_switched_execution_model"))
                        if fallback_model and fallback_model != config.EXECUTION_MODEL and not auto_switched:
                            previous_model = config.EXECUTION_MODEL
                            config.EXECUTION_MODEL = fallback_model
                            context.set_agent_state("auto_switched_execution_model", True)
                            context.set_agent_state("tool_execution_failure_count", 0)
                            context.add_error(
                                f"Auto-switched execution model from {previous_model} to {fallback_model} due to tool-call failures"
                            )
                            print(f"\n[{colorize('TOOL EXECUTION FAILURES: SWITCHING MODEL', Colors.BRIGHT_YELLOW, bold=True)}]")
                            print(
                                colorize(
                                    f"Switching execution model from {previous_model} to {fallback_model} after repeated tool failures.",
                                    Colors.BRIGHT_WHITE,
                                )
                            )
                            task.error = f"Switched execution model to fallback '{fallback_model}' after tool-call failures"
                            return False

                        context.set_agent_state("no_retry", True)
                        context.add_error(f"Circuit breaker: {tool_failure_count} consecutive tool execution failures")
                        print(f"\n[{colorize('🛑 CIRCUIT BREAKER: TOOL EXECUTION FAILURES', Colors.BRIGHT_RED, bold=True)}]")
                        print(f"{colorize(f'The LLM has failed to execute tools {tool_failure_count} times.', Colors.BRIGHT_WHITE)}")
                        print(f"{colorize('This model does not properly support function calling.', Colors.BRIGHT_WHITE)}")
                        print(f"\n{colorize('SOLUTION:', Colors.BRIGHT_YELLOW, bold=True)}")
                        print(f"{colorize('  Switch to a model with better tool-calling capabilities:', Colors.BRIGHT_WHITE)}")
                        print(f"{colorize('  - claude-sonnet (Anthropic)', Colors.BRIGHT_GREEN)}")
                        print(f"{colorize('  - gpt-4 (OpenAI)', Colors.BRIGHT_GREEN)}")
                        print(f"{colorize('  - mistral-large (Mistral)', Colors.BRIGHT_GREEN)}")
                        print(f"{colorize('  - deepseek-coder (DeepSeek)', Colors.BRIGHT_GREEN)}")
                        print(f"\n{colorize('Current model may be optimized for text generation, not tool use.', Colors.BRIGHT_BLACK)}\n")
                        return False

                    if tool_failure_count >= 2:
                        print(f"  {colorize('⚠️  Multiple tool execution failures detected', Colors.BRIGHT_RED)}")
                        print(f"  {colorize('Recommendation: Try a different model with better tool-calling support', Colors.BRIGHT_YELLOW)}")
                        print(f"  {colorize('Current model may not properly support function calling', Colors.BRIGHT_BLACK)}\n")

                return False
            # If sub-agent reported tool error, fail the task and replan.
            try:
                if isinstance(result, str):
                    parsed = json.loads(result)
                    ev = None
                    if isinstance(parsed, dict):
                        ev_list = parsed.get("evidence") or []
                        if isinstance(ev_list, list) and ev_list:
                            ev = ev_list[0]
                    if ev and ev.get("result") == "error":
                        task.status = TaskStatus.FAILED
                        task.error = ev.get("summary") or "tool error"
                        return False
            except Exception:
                pass
            if isinstance(result, str) and (result.startswith("[RECOVERY_REQUESTED]") or result.startswith("[FINAL_FAILURE]") or result.startswith("[USER_REJECTED]")):
                if result.startswith("[RECOVERY_REQUESTED]"):
                    retry_reason = result[len("[RECOVERY_REQUESTED]"):].strip()
                    if retry_reason:
                        print(f"  [retry_reason] {retry_reason}")
                        history = context.work_history if isinstance(context.work_history, list) else []
                        history.append(f"[RETRY] {task.description} | Reason: {retry_reason}")
                        context.work_history = history
                        context.set_agent_state("last_retry_reason", retry_reason)
                    task.status = TaskStatus.FAILED
                    task.error = result[len("[RECOVERY_REQUESTED]"):]
                elif result.startswith("[FINAL_FAILURE]"):
                    task.status = TaskStatus.FAILED
                    task.error = result[len("[FINAL_FAILURE]"):]
                    context.add_error(f"Task {task.task_id}: {task.error}")
                else:
                    task.status = TaskStatus.STOPPED
                    task.error = result[len("[USER_REJECTED]"):]
                return False
            else:
                # Harden TEST actions: they must execute a real test command.
                action_type = (task.action_type or "").lower()
                if action_type == "test" and not _did_run_real_tests(task, verification_result):
                    signature = getattr(task, "_normalized_signature", None) or _normalize_test_task_signature(task)
                    completion_key = f"test_completion_fallback::{signature}"
                    attempted_fallback = context.agent_state.get(completion_key, False)

                    # Try one automatic fallback before blocking the test task.
                    if not attempted_fallback:
                        context.set_agent_state(completion_key, True)
                        explicit_cmd = _extract_explicit_test_command(task.description or "")
                        if not explicit_cmd and isinstance(task.result, str):
                            explicit_cmd = _extract_explicit_test_command(task.result)

                        fallback_cmd = None
                        if explicit_cmd:
                            fallback_cmd = _maybe_correct_explicit_test_command(explicit_cmd, task.description or "")
                        if not fallback_cmd:
                            fallback_cmd = _select_test_fallback_command(task.description or "", config.ROOT or Path.cwd())

                        if fallback_cmd:
                            print(f"  [test-fallback] Executing fallback test command: {fallback_cmd}")
                            raw_result = execute_tool("run_cmd", {"cmd": fallback_cmd}, agent_name="orchestrator")
                            task.result = build_subagent_output(
                                agent_name="Orchestrator",
                                tool_name="run_cmd",
                                tool_args={"cmd": fallback_cmd},
                                tool_output=raw_result,
                                context=context,
                                task_id=task.task_id,
                            )
                            try:
                                _append_task_tool_event(task, task.result)
                            except Exception:
                                pass

                            if _did_run_real_tests(task, None):
                                task.status = TaskStatus.COMPLETED
                                return True

                    _record_test_signature_state(context, signature, "blocked")
                    blocked_tests = context.agent_state.get("blocked_test_signatures", {})
                    if not isinstance(blocked_tests, dict):
                        blocked_tests = {}
                    blocked_tests[signature] = {
                        "blocked_iteration": context.agent_state.get("current_iteration"),
                        "code_change_iteration": context.agent_state.get("last_code_change_iteration", -1),
                        "reason": "Test action completed without executing tests",
                    }
                    context.set_agent_state("blocked_test_signatures", blocked_tests)
                    task.status = TaskStatus.STOPPED
                    task.error = "Test action completed without executing tests (no run_cmd/run_tests detected)"
                    return False

                task.status = TaskStatus.COMPLETED
                try:
                    # If the agent produced tool evidence, it may include artifact refs.
                    if isinstance(task.result, str) and "outside allowed workspace roots" in task.result.lower():
                        maybe_record_known_failure_from_error(error_text=task.result)
                except Exception:
                    pass
                return True
        except Exception as e:
            task.status = TaskStatus.FAILED
            tb = traceback.format_exc()
            task.error = f"{e}\n{tb}"
            context.add_error(f"Sub-agent execution exception for task {task.task_id}: {e}\n{tb}")
            return False
    
    def _emit_run_metrics(self, plan: Optional[ExecutionPlan], result: OrchestratorResult, budget: ResourceBudget):
        if config.EXECUTION_MODE != 'sub-agent':
            print(f"\n🔥 Emitting run metrics...")
    
    def _display_summary(self, result: OrchestratorResult):
        """Display a final execution summary."""
        if config.EXECUTION_MODE == 'sub-agent':
            # Sub-agent mode has its own summary logic or is more streamlined
            return

        print("\n[ORCHESTRATOR - EXECUTION SUMMARY]")

        status = "SUCCESS" if result.success else "FAILED"
        print(f"Status: {status}")
        print(f"Phase Reached: {result.phase_reached.value}")
        print(f"Time Taken: {result.execution_time:.2f} seconds")

        # Display UCCT Anchoring metrics if available in insights
        if "anchoring_evaluation" in self.context.agent_insights:
            metrics = self.context.agent_insights["anchoring_evaluation"]
            print("\n📊 Measurable Coordination (UCCT):")
            print(f"   Anchoring Score: {metrics.get('raw_score', 0):.2f}")
            print(f"   Evidence Density: {metrics.get('evidence_density', 0):.2f}")
            print(f"   Mismatch Risk: {metrics.get('mismatch_risk', 0)}")
            print(f"   Anchor Budget (k): {metrics.get('anchor_budget', 0)}")
            print(f"   Decision: {metrics.get('decision', 'N/A')}")

        if result.plan:
            print(f"\nTasks: {result.plan.get_summary()}")

        if result.errors:
            print("\nErrors:")
            for err in result.errors:
                print(f"  - {err}")

        print()

def run_orchestrated(
    user_request: str,
    project_root: Path,
    enable_learning: bool = False,
    enable_research: bool = True,
    enable_review: bool = True,
    enable_validation: bool = True,
    review_strictness: str = "moderate",
    enable_action_review: bool = False,
    enable_auto_fix: bool = False,
    parallel_workers: int = 1,
    auto_approve: bool = True,
    research_depth: Literal["off", "shallow", "medium", "deep"] = RESEARCH_DEPTH_DEFAULT,
    validation_mode: Literal["none", "smoke", "targeted", "full"] = "targeted",
    orchestrator_retries: int = MAX_ORCHESTRATOR_RETRIES,
    plan_regen_retries: int = MAX_PLAN_REGEN_RETRIES,
    validation_retries: int = MAX_VALIDATION_RETRIES,
    enable_prompt_optimization: bool = True,
    auto_optimize_prompt: bool = False,
    enable_context_guard: bool = True,
    context_guard_interactive: bool = True,
    context_guard_threshold: float = 0.3,
    resume: bool = False,
    resume_plan: bool = True,
    read_only: bool = False,
) -> OrchestratorResult:
    config_obj = OrchestratorConfig(
        enable_learning=enable_learning,
        enable_research=enable_research,
        enable_review=enable_review,
        enable_validation=enable_validation,
        review_strictness=ReviewStrictness(review_strictness),
        enable_action_review=enable_action_review,
        enable_auto_fix=enable_auto_fix,
        parallel_workers=parallel_workers,
        auto_approve=auto_approve,
        research_depth=research_depth,
        validation_mode=validation_mode,
        orchestrator_retries=orchestrator_retries,
        plan_regen_retries=plan_regen_retries,
        validation_retries=validation_retries,
        enable_prompt_optimization=enable_prompt_optimization,
        auto_optimize_prompt=auto_optimize_prompt,
        enable_context_guard=enable_context_guard,
        context_guard_interactive=context_guard_interactive,
        context_guard_threshold=context_guard_threshold,
    )

    orchestrator = Orchestrator(project_root, config_obj)
    return orchestrator.execute(user_request, resume=resume, resume_plan=resume_plan, read_only=read_only)

