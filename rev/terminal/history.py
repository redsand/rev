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
from typing import List, Optional
import threading


class PromptHistory:
    """Manages prompt history with arrow key navigation support."""
    
    def __init__(self, max_history: int = 100):
        """
        Initialize prompt history.
        
        Args:
            max_history: Maximum number of entries to keep (default: 100)
        """
        self.max_history = max_history
        
        # Separate histories for commands and regular input
        self.command_history: deque = deque(maxlen=max_history)
        self.input_history: deque = deque(maxlen=max_history)
        
        # Current position in history navigation
        self.history_position: int = 0
        self.current_history: Optional[deque] = None
        self.current_input: str = ""
        
        # Thread safety
        self.lock = threading.Lock()

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
            
            # Reset navigation position
            self.history_position = 0
            self.current_history = None

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
            
            # Reset navigation position
            self.history_position = 0
            self.current_history = None

    def start_navigation(self, is_command: bool, current_input: str = "") -> None:
        """Initialize navigation state.
        
        Args:
            is_command: True if navigating command history, False for input history
            current_input: The current input buffer when starting navigation
        """
        with self.lock:
            self.current_history = self.command_history if is_command else self.input_history
            self.history_position = 0
            self.current_input = current_input

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
            self.history_position = 0
            self.current_history = None
            self.current_input = ""

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
            return len(self.command_history) + len(self.input_history)