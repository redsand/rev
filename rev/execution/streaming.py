#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Streaming execution infrastructure for real-time LLM interaction.

This module provides the core infrastructure for streaming task execution,
allowing users to submit messages while tasks are running - similar to
Claude Code or Codex's real-time experience.

Key components:
- UserMessageQueue: Thread-safe queue for user input during execution
- StreamingExecutionManager: Manages streaming LLM calls with message injection
- Non-blocking input handling for concurrent user interaction
"""

import threading
import time
import sys
import select
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Generator, Callable
from datetime import datetime
from enum import Enum


class MessagePriority(Enum):
    """Priority levels for injected user messages."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    INTERRUPT = 3  # Highest priority - should be processed immediately


@dataclass
class UserMessage:
    """A message submitted by the user during task execution."""
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    priority: MessagePriority = MessagePriority.NORMAL
    processed: bool = False

    def to_llm_message(self) -> Dict[str, str]:
        """Convert to LLM message format."""
        # Add context about this being a runtime guidance message
        prefix = ""
        if self.priority == MessagePriority.INTERRUPT:
            prefix = "[URGENT USER GUIDANCE - STOP AND READ] "
        elif self.priority == MessagePriority.HIGH:
            prefix = "[IMPORTANT USER GUIDANCE] "
        else:
            prefix = "[USER GUIDANCE] "

        return {
            "role": "user",
            "content": f"{prefix}{self.content}"
        }


class UserMessageQueue:
    """Thread-safe queue for user messages during execution.

    Only allows ONE pending message at a time - the most recent message
    replaces any previously pending message. This keeps the interaction
    focused and prevents message queue buildup.
    """

    def __init__(self, max_size: int = 1):
        """Initialize the message queue.

        Args:
            max_size: Maximum number of pending messages (always 1)
        """
        self._pending_message: Optional[UserMessage] = None
        self._lock = threading.Lock()
        self._total_submitted = 0
        self._total_processed = 0
        self._total_replaced = 0
        self._enabled = True

    def submit(self, content: str, priority: MessagePriority = MessagePriority.NORMAL) -> bool:
        """Submit a user message, replacing any pending message.

        Only ONE message can be pending at a time. New messages replace
        any existing pending message (with a notification).

        Args:
            content: The message content
            priority: Message priority level

        Returns:
            True if message was queued, False if disabled
        """
        if not self._enabled:
            return False

        if not content or not content.strip():
            return False

        message = UserMessage(
            content=content.strip(),
            priority=priority
        )

        with self._lock:
            if self._pending_message is not None:
                # Replace existing message
                self._total_replaced += 1
                print(f"\n   [Previous message replaced]")

            self._pending_message = message
            self._total_submitted += 1

        return True

    def get_pending(self, max_messages: int = 1) -> List[UserMessage]:
        """Get the pending message (if any).

        Args:
            max_messages: Ignored (always returns at most 1)

        Returns:
            List with the pending message, or empty list if none
        """
        with self._lock:
            if self._pending_message is None:
                return []

            msg = self._pending_message
            self._pending_message = None
            self._total_processed += 1
            return [msg]

    def has_pending(self) -> bool:
        """Check if there is a pending message."""
        with self._lock:
            return self._pending_message is not None

    def has_interrupt(self) -> bool:
        """Check if there's an interrupt-priority message (without consuming it)."""
        with self._lock:
            if self._pending_message is None:
                return False
            return self._pending_message.priority == MessagePriority.INTERRUPT

    def clear(self):
        """Clear the pending message."""
        with self._lock:
            self._pending_message = None

    def enable(self):
        """Enable the queue."""
        self._enabled = True

    def disable(self):
        """Disable the queue (new messages will be rejected)."""
        self._enabled = False

    def get_stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        with self._lock:
            return {
                "pending": 1 if self._pending_message is not None else 0,
                "total_submitted": self._total_submitted,
                "total_processed": self._total_processed,
                "total_replaced": self._total_replaced
            }


class NonBlockingInputReader:
    """Non-blocking input reader that runs in a background thread.

    Allows users to type messages while the main thread is busy
    with LLM calls and tool execution.
    """

    def __init__(self, message_queue: UserMessageQueue, prompt: str = ">>> "):
        """Initialize the input reader.

        Args:
            message_queue: Queue to submit messages to
            prompt: Prompt to display for input
        """
        self._queue = message_queue
        self._prompt = prompt
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._input_buffer = ""
        self._lock = threading.Lock()

    def start(self):
        """Start the background input reader."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background input reader."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _read_loop(self):
        """Background loop for reading user input."""
        while self._running:
            try:
                # Use select for non-blocking input on Unix
                if sys.platform != 'win32':
                    ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if ready:
                        line = sys.stdin.readline()
                        if line:
                            self._process_input(line.strip())
                else:
                    # On Windows, use msvcrt for non-blocking input
                    try:
                        import msvcrt
                        if msvcrt.kbhit():
                            char = msvcrt.getwch()
                            if char == '\r' or char == '\n':
                                with self._lock:
                                    if self._input_buffer:
                                        self._process_input(self._input_buffer)
                                        self._input_buffer = ""
                            elif char == '\x08':  # Backspace
                                with self._lock:
                                    self._input_buffer = self._input_buffer[:-1]
                            else:
                                with self._lock:
                                    self._input_buffer += char
                    except ImportError:
                        # Fallback: brief sleep to avoid busy-waiting
                        time.sleep(0.1)

            except Exception:
                # Don't crash on input errors
                time.sleep(0.1)

    def _process_input(self, text: str):
        """Process a line of user input."""
        if not text:
            return

        # Check for special commands
        if text.startswith('/'):
            cmd = text[1:].lower().strip()
            if cmd == 'stop' or cmd == 'cancel':
                self._queue.submit("STOP the current task immediately.", MessagePriority.INTERRUPT)
            elif cmd == 'status':
                # Status is handled elsewhere
                pass
            elif cmd.startswith('priority '):
                # Submit as high priority
                msg = text[len('/priority '):].strip()
                if msg:
                    self._queue.submit(msg, MessagePriority.HIGH)
            else:
                # Regular message
                self._queue.submit(text, MessagePriority.NORMAL)
        else:
            # Regular guidance message
            self._queue.submit(text, MessagePriority.NORMAL)


@dataclass
class StreamingChunk:
    """A chunk of streaming LLM response."""
    content: str
    is_complete: bool = False
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


class StreamingExecutionManager:
    """Manages streaming execution with real-time message injection.

    This is the core class that enables the Claude Code-like experience:
    - Streams LLM responses to the terminal in real-time
    - Accepts user messages at any point during execution
    - Injects user guidance into the conversation
    - Allows the LLM to adapt its approach based on user feedback
    """

    def __init__(
        self,
        message_queue: Optional[UserMessageQueue] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[Dict], None]] = None,
        on_user_message: Optional[Callable[[UserMessage], None]] = None,
    ):
        """Initialize the streaming execution manager.

        Args:
            message_queue: Queue for user messages (created if not provided)
            on_chunk: Callback for each streaming chunk
            on_tool_call: Callback when a tool call is detected
            on_user_message: Callback when a user message is injected
        """
        self._queue = message_queue or UserMessageQueue()
        self._on_chunk = on_chunk or (lambda c: print(c, end='', flush=True))
        self._on_tool_call = on_tool_call
        self._on_user_message = on_user_message
        self._messages: List[Dict[str, Any]] = []
        self._running = False
        self._interrupted = False

    @property
    def message_queue(self) -> UserMessageQueue:
        """Get the user message queue."""
        return self._queue

    @property
    def messages(self) -> List[Dict[str, Any]]:
        """Get the current message history."""
        return self._messages.copy()

    def set_messages(self, messages: List[Dict[str, Any]]):
        """Set the message history."""
        self._messages = list(messages)

    def add_message(self, message: Dict[str, Any]):
        """Add a message to the history."""
        self._messages.append(message)

    def inject_user_messages(self) -> List[UserMessage]:
        """Check for and inject any pending user messages.

        Returns:
            List of messages that were injected
        """
        pending = self._queue.get_pending()
        injected = []

        for msg in pending:
            llm_msg = msg.to_llm_message()
            self._messages.append(llm_msg)
            msg.processed = True
            injected.append(msg)

            if self._on_user_message:
                self._on_user_message(msg)

        return injected

    def should_check_messages(self) -> bool:
        """Check if we should look for pending user messages.

        This is called at strategic points during execution:
        - Before each LLM call
        - Between tool calls
        - After receiving a complete response
        """
        return self._queue.has_pending()

    def interrupt(self):
        """Signal that execution should be interrupted."""
        self._interrupted = True

    def is_interrupted(self) -> bool:
        """Check if execution has been interrupted."""
        return self._interrupted

    def reset_interrupt(self):
        """Reset the interrupt flag."""
        self._interrupted = False

    def start(self):
        """Start the streaming execution manager."""
        self._running = True
        self._interrupted = False
        self._queue.enable()

    def stop(self):
        """Stop the streaming execution manager."""
        self._running = False
        self._queue.disable()


# Singleton instance for global access
_streaming_manager: Optional[StreamingExecutionManager] = None
_input_reader: Optional[NonBlockingInputReader] = None


def get_streaming_manager() -> Optional[StreamingExecutionManager]:
    """Get the global streaming execution manager."""
    return _streaming_manager


def init_streaming_manager(
    on_chunk: Optional[Callable[[str], None]] = None,
    on_tool_call: Optional[Callable[[Dict], None]] = None,
    on_user_message: Optional[Callable[[UserMessage], None]] = None,
) -> StreamingExecutionManager:
    """Initialize the global streaming execution manager.

    Args:
        on_chunk: Callback for each streaming chunk
        on_tool_call: Callback when a tool call is detected
        on_user_message: Callback when a user message is injected

    Returns:
        The initialized StreamingExecutionManager
    """
    global _streaming_manager, _input_reader

    _streaming_manager = StreamingExecutionManager(
        on_chunk=on_chunk,
        on_tool_call=on_tool_call,
        on_user_message=on_user_message,
    )

    # Create and start the non-blocking input reader
    _input_reader = NonBlockingInputReader(_streaming_manager.message_queue)

    return _streaming_manager


def start_streaming_input():
    """Start accepting user input in the background."""
    global _input_reader
    if _input_reader:
        _input_reader.start()


def stop_streaming_input():
    """Stop the background input reader."""
    global _input_reader
    if _input_reader:
        _input_reader.stop()


def submit_user_message(content: str, priority: MessagePriority = MessagePriority.NORMAL) -> bool:
    """Submit a user message to the streaming manager.

    Args:
        content: The message content
        priority: Message priority

    Returns:
        True if submitted successfully
    """
    if _streaming_manager:
        return _streaming_manager.message_queue.submit(content, priority)
    return False


def shutdown_streaming():
    """Shutdown the streaming infrastructure."""
    global _streaming_manager, _input_reader

    if _input_reader:
        _input_reader.stop()
        _input_reader = None

    if _streaming_manager:
        _streaming_manager.stop()
        _streaming_manager = None
