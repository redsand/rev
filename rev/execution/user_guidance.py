"""User guidance dialog system for uncertainty resolution.

Prompts user for guidance when Rev is uncertain about how to proceed.
"""

from typing import Optional, Dict, Any, List
import sys

from rev.models.task import Task
from rev.execution.uncertainty_detector import UncertaintySignal, format_uncertainty_reasons
from rev.terminal.formatting import colorize, Colors


class GuidanceResponse:
    """Response from user guidance dialog."""

    def __init__(self, action: str, guidance: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Initialize guidance response.

        Args:
            action: One of "retry", "skip", "abort"
            guidance: Optional user-provided guidance text
            metadata: Optional metadata about the response
        """
        self.action = action
        self.guidance = guidance
        self.metadata = metadata or {}

    def __repr__(self):
        return f"GuidanceResponse(action={self.action}, guidance={self.guidance[:50] if self.guidance else None})"


def request_user_guidance(
    uncertainty_signals: List[UncertaintySignal],
    task: Task,
    context: Optional[Dict[str, Any]] = None
) -> Optional[GuidanceResponse]:
    """Request guidance from user when uncertain.

    Args:
        uncertainty_signals: List of detected uncertainty signals
        task: The task being executed
        context: Optional context information (retry_count, etc.)

    Returns:
        GuidanceResponse with user's decision, or None if cancelled
    """
    context = context or {}
    retry_count = context.get("retry_count", 0)

    # Format uncertainty reasons
    uncertainty_reason = format_uncertainty_reasons(uncertainty_signals)

    # Print header
    print(f"\n{colorize('🤔 Rev is uncertain and needs guidance:', Colors.BRIGHT_YELLOW, bold=True)}")
    print(f"{colorize(uncertainty_reason, Colors.YELLOW)}\n")

    # Show task context
    print(f"{colorize('Task:', Colors.BRIGHT_CYAN)} {task.description[:100]}")
    if task.action_type:
        print(f"{colorize('Action:', Colors.BRIGHT_CYAN)} {task.action_type}")
    if retry_count > 0:
        print(f"{colorize('Attempts:', Colors.BRIGHT_CYAN)} {retry_count + 1}")
    if task.error:
        error_preview = task.error[:150].replace('\n', ' ')
        print(f"{colorize('Last Error:', Colors.BRIGHT_CYAN)} {error_preview}")

    # Try to use TUI if available
    from rev.terminal.tui import get_active_tui
    tui = get_active_tui()

    if tui is not None:
        return _request_guidance_tui(tui, task, uncertainty_signals, context)
    else:
        return _request_guidance_terminal(task, uncertainty_signals, context)


def _request_guidance_tui(
    tui,
    task: Task,
    uncertainty_signals: List[UncertaintySignal],
    context: Dict[str, Any]
) -> Optional[GuidanceResponse]:
    """Request guidance using TUI interface.

    Args:
        tui: Active TUI instance
        task: Task being executed
        uncertainty_signals: Detected uncertainty signals
        context: Context information

    Returns:
        GuidanceResponse or None
    """
    # Show menu options
    options = [
        "Provide specific guidance (describe what to do)",
        "Skip this task and continue",
        "Retry with current approach",
        "Abort execution"
    ]

    print(f"\n{colorize('[Options]', Colors.BRIGHT_CYAN)}")
    selected = tui.show_menu("Rev needs guidance - Choose an option:", options)

    if selected == 0:  # Provide guidance
        # For now, fall back to terminal input for text entry
        # TUI could be enhanced with text input later
        print(f"\n{colorize('What should Rev do? (be specific):', Colors.BRIGHT_CYAN)}")
        try:
            guidance = input("> ").strip()
            if guidance:
                print(f"{colorize('✓', Colors.BRIGHT_GREEN)} Guidance received: {guidance[:80]}\n")
                return GuidanceResponse(
                    action="retry",
                    guidance=guidance,
                    metadata={"method": "tui", "signals": len(uncertainty_signals)}
                )
            else:
                print(f"{colorize('✗', Colors.BRIGHT_RED)} No guidance provided, retrying with current approach\n")
                return GuidanceResponse(action="retry", guidance=None)
        except (EOFError, KeyboardInterrupt):
            print(f"\n{colorize('✗', Colors.BRIGHT_RED)} Cancelled\n")
            return None

    elif selected == 1:  # Skip
        print(f"{colorize('→', Colors.BRIGHT_YELLOW)} Skipping task\n")
        return GuidanceResponse(
            action="skip",
            guidance="User chose to skip",
            metadata={"method": "tui"}
        )

    elif selected == 2:  # Retry
        print(f"{colorize('↻', Colors.BRIGHT_BLUE)} Retrying with current approach\n")
        return GuidanceResponse(
            action="retry",
            guidance=None,
            metadata={"method": "tui"}
        )

    elif selected == 3 or selected == -1:  # Abort or cancelled
        print(f"{colorize('✗', Colors.BRIGHT_RED)} Aborting execution\n")
        return GuidanceResponse(
            action="abort",
            guidance="User aborted",
            metadata={"method": "tui"}
        )

    # Default: retry
    return GuidanceResponse(action="retry", guidance=None)


def _request_guidance_terminal(
    task: Task,
    uncertainty_signals: List[UncertaintySignal],
    context: Dict[str, Any]
) -> Optional[GuidanceResponse]:
    """Request guidance using terminal interface.

    Args:
        task: Task being executed
        uncertainty_signals: Detected uncertainty signals
        context: Context information

    Returns:
        GuidanceResponse or None
    """
    # Show options
    print(f"\n{colorize('[Options]', Colors.BRIGHT_CYAN)}")
    print("  [1] Provide specific guidance (describe what to do)")
    print("  [2] Skip this task and continue")
    print("  [3] Retry with current approach")
    print("  [4] Abort execution")

    try:
        choice = input(f"\n{colorize('Choice [1-4]:', Colors.BRIGHT_CYAN)} ").strip()

        if choice == "1":
            # Get user guidance
            print(f"{colorize('What should Rev do? (be specific):', Colors.BRIGHT_CYAN)}")
            guidance = input("> ").strip()
            if guidance:
                print(f"{colorize('✓', Colors.BRIGHT_GREEN)} Guidance received: {guidance[:80]}\n")
                return GuidanceResponse(
                    action="retry",
                    guidance=guidance,
                    metadata={"method": "terminal", "signals": len(uncertainty_signals)}
                )
            else:
                print(f"{colorize('✗', Colors.BRIGHT_RED)} No guidance provided, retrying with current approach\n")
                return GuidanceResponse(action="retry", guidance=None)

        elif choice == "2":
            print(f"{colorize('→', Colors.BRIGHT_YELLOW)} Skipping task\n")
            return GuidanceResponse(
                action="skip",
                guidance="User chose to skip",
                metadata={"method": "terminal"}
            )

        elif choice == "3":
            print(f"{colorize('↻', Colors.BRIGHT_BLUE)} Retrying with current approach\n")
            return GuidanceResponse(
                action="retry",
                guidance=None,
                metadata={"method": "terminal"}
            )

        elif choice == "4":
            print(f"{colorize('✗', Colors.BRIGHT_RED)} Aborting execution\n")
            return GuidanceResponse(
                action="abort",
                guidance="User aborted",
                metadata={"method": "terminal"}
            )

        else:
            print(f"{colorize('Invalid choice, defaulting to retry', Colors.YELLOW)}\n")
            return GuidanceResponse(action="retry", guidance=None)

    except (EOFError, KeyboardInterrupt):
        print(f"\n{colorize('✗', Colors.BRIGHT_RED)} Cancelled, aborting\n")
        return GuidanceResponse(action="abort", guidance="Interrupted")

    except Exception as e:
        print(f"{colorize(f'Error getting input: {e}', Colors.BRIGHT_RED)}\n")
        return None


def should_auto_skip(
    uncertainty_score: int,
    auto_skip_threshold: int = 10
) -> bool:
    """Determine if task should be auto-skipped without asking user.

    Args:
        uncertainty_score: Total uncertainty score
        auto_skip_threshold: Score threshold for auto-skip

    Returns:
        True if task should be auto-skipped
    """
    return uncertainty_score >= auto_skip_threshold


def format_guidance_for_task(guidance: str, task: Task) -> str:
    """Format user guidance to append to task description.

    Args:
        guidance: User-provided guidance text
        task: Task to update

    Returns:
        Formatted guidance string to append
    """
    return f"\n\n[USER GUIDANCE] {guidance}"
