"""
Prompt Optimizer - Recommends improvements to user requests before execution.

This module provides request analysis and optimization capabilities that:
1. Analyzes the user's original request
2. Asks the LLM for recommendations to improve clarity and completeness
3. Optionally uses the improved prompt for planning

This helps with:
- Vague requests (clarify scope)
- Missing requirements (identify gaps)
- Better task decomposition (suggest structure)
- Catch issues early (before execution)
"""

import json
import sys
import re
import os
from typing import Dict, Any, Optional, Tuple, List
from rev.llm.client import ollama_chat
from rev.tools.git_ops import get_repo_context
from rev.tools.file_ops import tree_view


def should_optimize_prompt(user_request: str) -> bool:
    """
    Determine if a prompt should be optimized.

    Returns True if request might benefit from optimization:
    - Very short (< 10 words)
    - Vague language ("improve", "fix", "enhance" without specifics)
    - Asks for multiple unrelated things
    - Could be misunderstood

    Returns False if request indicates working with existing code:
    - Contains "continue", "review", "examine", "analyze existing"
    """
    request_lower = user_request.lower()
    word_count = len(user_request.split())

    # Keywords that indicate working with existing code - DO NOT optimize these
    existing_work_keywords = [
        "continue", "resume", "keep going", "keep working",
        "review", "examine", "analyze", "check", "look at", "inspect",
        "current", "existing", "what's there", "what is there"
    ]

    # If user wants to work with existing code, don't optimize
    if any(kw in request_lower for kw in existing_work_keywords):
        return False

    # Too vague indicators
    vague_keywords = [
        "improve", "fix", "make", "do", "help", "try",
        "enhance", "optimize", "better", "good", "nice"
    ]

    # Very short requests often lack detail
    if word_count < 10:
        return True

    # Count vague keywords without specifics
    vague_count = sum(1 for kw in vague_keywords if kw in request_lower)
    if vague_count > 0 and word_count < 30:
        return True

    # Multiple unrelated operations (check for "and" between different domains)
    if request_lower.count(" and ") > 2:
        return True

    return False


def _get_workspace_snapshot() -> Dict[str, Any]:
    try:
        context_raw = get_repo_context()
        return json.loads(context_raw) if isinstance(context_raw, str) else {}
    except Exception:
        return {}


def _workspace_has_visible_items() -> bool:
    context = _get_workspace_snapshot()
    top_level = context.get("top_level", []) or []
    return any(
        isinstance(item.get("name"), str) and not item.get("name", "").startswith(".")
        for item in top_level
    )


def _format_workspace_snapshot() -> str:
    context = _get_workspace_snapshot()
    top_level = context.get("top_level", []) or []
    file_structure = context.get("file_structure", []) or []

    top_items: List[str] = []
    for item in top_level:
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        if name.startswith("."):
            continue
        suffix = "/" if item.get("type") == "dir" else ""
        top_items.append(f"{name}{suffix}")
        if len(top_items) >= 12:
            break

    key_paths: List[str] = []
    for entry in file_structure:
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            continue
        lowered = path.replace("\\", "/").lower()
        if lowered.startswith(("src/", "tests/", "test/", "backend/", "frontend/", "server/", "client/")):
            key_paths.append(path)
        if len(key_paths) >= 12:
            break

    if not top_items and not key_paths:
        return ""

    lines = ["EXISTING WORKSPACE SNAPSHOT:"]
    if top_items:
        lines.append(f"Top-level items: {', '.join(top_items)}")
    if key_paths:
        lines.append(f"Key existing paths: {', '.join(key_paths)}")
    return "\n".join(lines)


def _get_full_tree_view() -> str:
    try:
        max_depth = int(os.getenv("REV_PROMPT_OPT_TREE_MAX_DEPTH", "10"))
        max_files = int(os.getenv("REV_PROMPT_OPT_TREE_MAX_FILES", "2000"))
    except ValueError:
        max_depth = 10
        max_files = 2000

    raw = tree_view(".", max_depth=max_depth, max_files=max_files)
    try:
        payload = json.loads(raw)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    tree = payload.get("tree")
    if not isinstance(tree, str) or not tree.strip():
        return ""
    files_shown = payload.get("files_shown")
    if isinstance(files_shown, int) and files_shown >= max_files:
        tree = f"{tree}\n... (truncated at {files_shown} entries)"
    return tree


def _build_structure_guard(user_request: str) -> str:
    guard_lines = [
        "IMPORTANT: Use the existing workspace root; do NOT create a new top-level app directory unless explicitly requested.",
        "Reuse existing directories and structure; do not propose new folder splits unless the user asked.",
    ]
    snapshot = _format_workspace_snapshot()
    if snapshot:
        guard_lines.insert(1, snapshot)
    request_paths = re.findall(
        r"(?:\\./|\\.\\./|[A-Za-z]:\\\\|/)(?:[\\w.\\-]+[/\\\\])+[\\w.\\-]+(?:\\.[\\w.\\-]+)?",
        user_request or "",
    )
    if request_paths:
        guard_lines.insert(1, f"User-mentioned paths: {', '.join(request_paths[:6])}")
    return "\n".join(guard_lines)


def _request_explicitly_targets_new_root(user_request: str) -> bool:
    lowered = (user_request or "").lower()
    if re.search(r"\b(new|create|make|scaffold|init(?:ialize)?)\s+(?:a\s+)?(directory|folder)\b", lowered):
        return True
    if re.search(r"\b(create|make|scaffold|init(?:ialize)?)\s+(?:a\s+)?(project|app|application)\s+in\b", lowered):
        return True
    if re.search(r"\b(in|within|inside|under)\s+([a-z0-9_.\\/-]+)\b", lowered):
        match = re.search(r"\b(in|within|inside|under)\s+([a-z0-9_.\\/-]+)\b", lowered)
        if match and any(sep in match.group(2) for sep in ("/", "\\")):
            return True
    return False


def _request_already_scoped_to_current_workspace(user_request: str) -> bool:
    lowered = (user_request or "").lower()
    return any(
        token in lowered
        for token in (
            "current directory",
            "current folder",
            "this directory",
            "this folder",
            "this repo",
            "existing project",
            "use existing",
            "in-place",
        )
    )


def _apply_workspace_guard(improved: str, user_request: str) -> str:
    if not improved or not _workspace_has_visible_items():
        return improved
    if _request_explicitly_targets_new_root(user_request) or _request_already_scoped_to_current_workspace(user_request):
        return improved
    guard = _build_structure_guard(user_request)
    if "existing workspace root" in improved.lower():
        return improved
    return f"{improved}\n\n{guard}"


def get_prompt_recommendations(user_request: str) -> Optional[Dict[str, Any]]:
    """
    Ask LLM for recommendations to improve the user's request.

    Returns: Dict with original_prompt, recommendations, and suggested_improvement
    """
    workspace_snapshot = _format_workspace_snapshot()
    tree_snapshot = _get_full_tree_view()
    workspace_rules = ""
    if workspace_snapshot:
        workspace_rules = (
            f"\n{workspace_snapshot}\n\n"
            "IMPORTANT: Preserve the existing structure shown above. "
            "Do NOT suggest creating new top-level folders or reorganizing into new layouts "
            "unless the user explicitly requests it.\n"
        )
    if tree_snapshot:
        workspace_rules = (
            f"{workspace_rules}\nFULL TREE VIEW (current workspace):\n{tree_snapshot}\n\n"
        )

    optimization_prompt = f"""
You are a request clarification specialist. Your job is to help make user requests more clear and specific before they are executed.

USER REQUEST:
{user_request}
{workspace_rules}

Analyze this request and provide:

1. **Clarity Assessment**: Is this request clear enough? What could be misunderstood?

2. **Missing Information**: What details are missing that would help understand the intent?

3. **Scope Check**: Is the scope too broad, too narrow, or unclear?

4. **Suggested Improvements**: Provide a specific, improved version of the request that is:
   - More specific and concrete
   - Includes important details
   - Clearly scoped
   - Follows best practices for code tasks

Format your response as JSON:
{{
  "clarity_score": 1-10,
  "is_vague": true/false,
  "potential_issues": ["issue1", "issue2"],
  "missing_info": ["missing1", "missing2"],
  "recommendations": ["rec1", "rec2"],
  "suggested_improvement": "improved request here",
  "reasoning": "why these improvements help"
}}
"""

    messages = [
        {"role": "user", "content": optimization_prompt}
    ]

    try:
        response = ollama_chat(messages, temperature=0.3)  # Lower temp for consistency

        if response and "message" in response:
            content = response["message"].get("content", "")
            if content:
                try:
                    # Extract JSON from response
                    json_start = content.find("{")
                    json_end = content.rfind("}") + 1
                    if json_start >= 0 and json_end > json_start:
                        json_str = content[json_start:json_end]
                        return json.loads(json_str)
                except (json.JSONDecodeError, ValueError):
                    pass

    except Exception as e:
        print(f"  ⚠️ Error getting recommendations: {e}")

    return None


def prompt_optimization_dialog(
    user_request: str,
    interactive: bool = True
) -> Tuple[str, bool]:
    """
    Run the prompt optimization dialog with the user.

    Returns: (final_prompt, was_optimized)
    """
    print(f"\n[PROMPT OPTIMIZATION]")

    # Check if optimization is needed
    if not should_optimize_prompt(user_request):
        print(f"✓ Request appears clear. Proceeding without optimization.\n")
        return user_request, False

    print(f"📋 Analyzing request for potential improvements...\n")

    # Get recommendations
    recommendations = get_prompt_recommendations(user_request)

    if not recommendations:
        print("  ⚠️ Could not generate recommendations. Using original request.\n")
        return user_request, False

    # Display analysis
    clarity_score = recommendations.get("clarity_score", 5)
    issues = recommendations.get("potential_issues", [])
    missing = recommendations.get("missing_info", [])
    improved = recommendations.get("suggested_improvement", user_request)
    improved = _apply_workspace_guard(improved, user_request)

    print(f"📊 Analysis Results:")
    print(f"   Clarity Score: {clarity_score}/10")

    if issues:
        print(f"\n   ⚠️  Potential Issues:")
        for issue in issues:
            print(f"      - {issue}")

    if missing:
        print(f"\n   ❓ Missing Information:")
        for item in missing:
            print(f"      - {item}")

    if recommendations.get("recommendations"):
        print(f"\n   💡 Recommendations:")
        for rec in recommendations["recommendations"]:
            print(f"      - {rec}")

    print(f"\n📝 Suggested Improvement:")
    print(f"   {improved}\n")

    # Ask user what to do
    if not interactive:
        return improved, True

    if not sys.stdin or not sys.stdin.isatty():
        print("?? Non-interactive input detected; using suggested improvement.\n")
        return improved, True

    # Check if TUI is active and use curses menu
    from rev.terminal.tui import get_active_tui
    tui = get_active_tui()

    if tui is not None:
        # Use curses menu in TUI mode
        options = [
            "[1] Use the suggested improvement",
            "[2] Keep the original request",
            "[3] Enter a custom request"
        ]

        selected = tui.show_menu("Prompt Optimization - Choose an option:", options)

        if selected == 0:  # Use suggested improvement
            return improved, True
        elif selected == 1:  # Keep original
            return user_request, False
        elif selected == 2:  # Custom request
            # For custom request, we still need to prompt for input
            # This will be handled by the TUI's normal input flow
            print("\n📝 Enter your custom request at the prompt below:")
            return user_request, False  # Fall back to original for now
        else:  # ESC or error
            print("\n✓ Using original request (ESC pressed).\n")
            return user_request, False
    else:
        # Use traditional text-based menu (non-TUI mode)
        print("\n[Options]")
        print("  [1] Use the suggested improvement")
        print("  [2] Keep the original request")
        print("  [3] Enter a custom request\n")

        attempts = 0
        while attempts < 3:
            try:
                choice = input("Choice [1-3]: ").strip()

                if choice == "1":
                    print(f"\n✓ Using improved request.\n")
                    return improved, True

                elif choice == "2":
                    print(f"\n✓ Using original request.\n")
                    return user_request, False

                elif choice == "3":
                    custom = input("Enter your custom request: ").strip()
                    if custom:
                        print(f"\n✓ Using custom request.\n")
                        return custom, True
                    else:
                        print("Empty request. Please try again.\n")

                else:
                    print("Invalid choice. Please enter 1, 2, or 3.\n")
                    attempts += 1

            except (KeyboardInterrupt, EOFError):
                print("\n\nUsing original request.\n")
                return user_request, False

        print("\nToo many invalid choices; using original request.\n")
        return user_request, False


def optimize_prompt_if_needed(
    user_request: str,
    auto_optimize: bool = False
) -> Tuple[str, bool]:
    """
    Conditionally optimize a prompt.

    Args:
        user_request: The original user request
        auto_optimize: If True, automatically use improvements without asking

    Returns:
        (final_request, was_optimized)
    """
    if not should_optimize_prompt(user_request):
        return user_request, False

    return prompt_optimization_dialog(
        user_request,
        interactive=not auto_optimize
    )
