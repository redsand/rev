#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prompt history management with arrow key navigation.

Provides a PromptHistory class that:
- Stores command and task input history
- Supports up/down arrow navigation
- Maintains separate history for commands and regular input
- Limits history size to prevent memory issues
- Provides thread-safe operations
"""

from collections import deque
from typing import List, Optional, Union
from pathlib import Path
import threading
import os


class PromptHistory:
    """Manages prompt history with arrow key navigation support."""
    
    def __init__(self, max_history: int = 100, history_file: Optional[Union[str, Path]] = None):
        """
        Initialize prompt history.
        
        Args:
            max_history: Maximum number of entries to keep (default: 100)
            history_file: Optional path to persist history (empty/None disables persistence)
        """
        self.max_history = max_history
        self.history_file: Optional[Path] = None
        if history_file:
            history_path = Path(str(history_file)).expanduser()
            if str(history_path).strip():
                self.history_file = history_path
        
        # Separate histories for commands and regular input
        self.command_history: deque = deque(maxlen=max_history)
        self.input_history: deque = deque(maxlen=max_history)
        self.unified_history: deque = deque(maxlen=max_history)
        
        # Current position in history navigation
        self.history_position: int = 0
        self.current_history: Optional[deque] = None
        self.current_input: str = ""
        self.last_entry_is_command: bool = False
        
        # Thread safety
        self.lock = threading.Lock()

        # Attempt to load persisted history (best-effort)
        self._load_history()

    def add_command(self, command: str) -> None:
        """Add a command to command history.
        
        Args:
            command: The command string to add (without leading slash)
        """
        if not command or not command.strip():
            return
            
        with self.lock:
            # Avoid duplicate consecutive entries
            if not self.command_history or self.command_history[-1] != command:
                self.command_history.append(command)
            if not self.unified_history or self.unified_history[-1] != command:
                self.unified_history.append(command)
            self.last_entry_is_command = True
            
            # Reset navigation position
            self.history_position = 0
            self.current_history = None
            self._save_history()

    def add_input(self, user_input: str) -> None:
        """Add regular user input to input history.
        
        Args:
            user_input: The user input string to add
        """
        if not user_input or not user_input.strip():
            return
            
        with self.lock:
            # Avoid duplicate consecutive entries
            if not self.input_history or self.input_history[-1] != user_input:
                self.input_history.append(user_input)
            if not self.unified_history or self.unified_history[-1] != user_input:
                self.unified_history.append(user_input)
            self.last_entry_is_command = False
            
            # Reset navigation position
            self.history_position = 0
            self.current_history = None
            self._save_history()

    def start_navigation(self, is_command: bool, current_input: str = "") -> None:
        """Initialize navigation state.
        
        Args:
            is_command: True if navigating command history, False for input history
            current_input: The current input buffer when starting navigation
        """
        with self.lock:
            self.current_history = self.unified_history
            self.history_position = 0
            self.current_input = current_input

    def _load_history(self) -> None:
        """Load history from disk if persistence is enabled."""
        if not self.history_file:
            return
        try:
            if self.history_file.exists():
                lines = self.history_file.read_text(encoding="utf-8").splitlines()
                # Keep only the most recent entries, respecting max_history
                for line in lines[-self.max_history:]:
                    if not line.strip():
                        continue
                    self.unified_history.append(line)
                # Mirror into command/input histories for navigation parity
                self.command_history = deque(self.unified_history, maxlen=self.max_history)
                self.input_history = deque(self.unified_history, maxlen=self.max_history)
        except Exception:
            # Best-effort load; ignore errors to avoid breaking REPL startup
            pass

    def _save_history(self) -> None:
        """Persist history to disk if enabled."""
        if not self.history_file:
            return
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with self.history_file.open("w", encoding="utf-8") as f:
                for entry in list(self.unified_history)[-self.max_history:]:
                    f.write(entry + os.linesep)
        except Exception:
            # Persistence is best-effort; ignore write failures
            pass

    def get_previous(self) -> Optional[str]:
        """Get previous entry in history (up arrow).
        
        Returns:
            The previous history entry, or None if at beginning
        """
        with self.lock:
            if not self.current_history:
                return None
                
            if self.history_position < len(self.current_history):
                self.history_position += 1
                return self.current_history[-self.history_position]
            
            return None

    def get_next(self) -> Optional[str]:
        """Get next entry in history (down arrow).
        
        Returns:
            The next history entry, or None if at end (returns current input)
        """
        with self.lock:
            if not self.current_history:
                return None
                
            if self.history_position > 1:
                self.history_position -= 1
                return self.current_history[-self.history_position]
            else:
                # Return to current input
                self.history_position = 0
                return self.current_input if self.current_input else None

    def clear(self) -> None:
        """Clear all history."""
        with self.lock:
            self.command_history.clear()
            self.input_history.clear()
            self.unified_history.clear()
            self.history_position = 0
            self.current_history = None
            self.current_input = ""
            self._save_history()
            self.last_entry_is_command = False

    def last_entry_was_command(self) -> bool:
        """Return True if the last recorded entry was a command."""
        with self.lock:
            return self.last_entry_is_command

    def get_command_history(self) -> List[str]:
        """Get command history as a list.
        
        Returns:
            List of command history entries (newest last)
        """
        with self.lock:
            return list(self.command_history)

    def get_input_history(self) -> List[str]:
        """Get input history as a list.
        
        Returns:
            List of input history entries (newest last)
        """
        with self.lock:
            return list(self.input_history)

    def __len__(self) -> int:
        """Get total number of history entries."""
        with self.lock:
            return len(self.unified_history)
