#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inter-agent messaging infrastructure.

This module implements the Inter-Agent Communication pattern from Agentic Design
Patterns, providing a structured message bus for agents to share context, warnings,
suggestions, and metrics.
"""

from dataclasses import dataclass, field
from typing import Literal, Dict, Any, List, Optional
from datetime import datetime
from enum import Enum


# Message types
MessageType = Literal["context", "warning", "suggestion", "metric", "error", "info"]


class MessagePriority(Enum):
    """Priority levels for agent messages."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class AgentMessage:
    """A message sent between agents.

    This enables structured inter-agent communication without tight coupling.
    Agents can broadcast messages that other agents can consume.
    """
    sender: str  # Agent name: "planner", "researcher", "executor", etc.
    receiver: str  # "*" for broadcast, or specific agent name
    msg_type: MessageType
    payload: Dict[str, Any]
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    message_id: Optional[str] = None

    def is_broadcast(self) -> bool:
        """Check if this is a broadcast message."""
        return self.receiver == "*"

    def is_for(self, agent_name: str) -> bool:
        """Check if this message is for a specific agent."""
        return self.receiver == agent_name or self.is_broadcast()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "sender": self.sender,
            "receiver": self.receiver,
            "msg_type": self.msg_type,
            "payload": self.payload,
            "priority": self.priority.value,
            "timestamp": self.timestamp,
            "message_id": self.message_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentMessage':
        """Create from dictionary."""
        return cls(
            sender=data["sender"],
            receiver=data["receiver"],
            msg_type=data["msg_type"],
            payload=data["payload"],
            priority=MessagePriority(data.get("priority", 1)),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            message_id=data.get("message_id")
        )


class MessageBus:
    """Central message bus for inter-agent communication.

    Agents can publish messages that other agents can subscribe to and consume.
    This implements a simple pub/sub pattern for loose coupling.
    """

    def __init__(self):
        """Initialize the message bus."""
        self.messages: List[AgentMessage] = []
        self.subscribers: Dict[str, List[str]] = {}  # msg_type -> [agent_names]
        self._message_counter = 0

    def publish(self, message: AgentMessage) -> str:
        """Publish a message to the bus.

        Args:
            message: The message to publish

        Returns:
            Message ID
        """
        # Assign message ID if not already set
        if not message.message_id:
            self._message_counter += 1
            message.message_id = f"{message.sender}_{self._message_counter}"

        self.messages.append(message)
        return message.message_id

    def subscribe(self, agent_name: str, msg_type: MessageType):
        """Subscribe an agent to a specific message type.

        Args:
            agent_name: Name of the agent subscribing
            msg_type: Type of messages to subscribe to
        """
        if msg_type not in self.subscribers:
            self.subscribers[msg_type] = []
        if agent_name not in self.subscribers[msg_type]:
            self.subscribers[msg_type].append(agent_name)

    def get_messages_for(
        self,
        agent_name: str,
        msg_type: Optional[MessageType] = None,
        since_id: Optional[str] = None
    ) -> List[AgentMessage]:
        """Get messages for a specific agent.

        Args:
            agent_name: Name of the agent
            msg_type: Optional filter by message type
            since_id: Optional get messages after this ID

        Returns:
            List of matching messages
        """
        matching = []
        start_collecting = since_id is None

        for msg in self.messages:
            # Handle since_id
            if not start_collecting:
                if msg.message_id == since_id:
                    start_collecting = True
                continue

            # Check if message is for this agent
            if not msg.is_for(agent_name):
                continue

            # Check message type filter
            if msg_type and msg.msg_type != msg_type:
                continue

            matching.append(msg)

        return matching

    def get_all_messages(self, msg_type: Optional[MessageType] = None) -> List[AgentMessage]:
        """Get all messages, optionally filtered by type."""
        if msg_type:
            return [m for m in self.messages if m.msg_type == msg_type]
        return self.messages.copy()

    def clear(self):
        """Clear all messages."""
        self.messages.clear()

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics of the message bus."""
        summary = {
            "total_messages": len(self.messages),
            "by_type": {},
            "by_sender": {},
            "by_priority": {}
        }

        for msg in self.messages:
            # Count by type
            summary["by_type"][msg.msg_type] = summary["by_type"].get(msg.msg_type, 0) + 1

            # Count by sender
            summary["by_sender"][msg.sender] = summary["by_sender"].get(msg.sender, 0) + 1

            # Count by priority
            priority_name = msg.priority.name
            summary["by_priority"][priority_name] = summary["by_priority"].get(priority_name, 0) + 1

        return summary


# Helper functions for creating common message types

def create_context_message(sender: str, receiver: str, context: Dict[str, Any]) -> AgentMessage:
    """Create a context-sharing message."""
    return AgentMessage(
        sender=sender,
        receiver=receiver,
        msg_type="context",
        payload=context,
        priority=MessagePriority.NORMAL
    )


def create_warning_message(sender: str, receiver: str, warning: str, details: Dict[str, Any] = None) -> AgentMessage:
    """Create a warning message."""
    return AgentMessage(
        sender=sender,
        receiver=receiver,
        msg_type="warning",
        payload={"warning": warning, "details": details or {}},
        priority=MessagePriority.HIGH
    )


def create_suggestion_message(sender: str, receiver: str, suggestion: str, details: Dict[str, Any] = None) -> AgentMessage:
    """Create a suggestion message."""
    return AgentMessage(
        sender=sender,
        receiver=receiver,
        msg_type="suggestion",
        payload={"suggestion": suggestion, "details": details or {}},
        priority=MessagePriority.NORMAL
    )


def create_metric_message(sender: str, receiver: str, metric_name: str, value: Any, metadata: Dict[str, Any] = None) -> AgentMessage:
    """Create a metric message."""
    return AgentMessage(
        sender=sender,
        receiver=receiver,
        msg_type="metric",
        payload={
            "metric_name": metric_name,
            "value": value,
            "metadata": metadata or {}
        },
        priority=MessagePriority.LOW
    )


def create_error_message(sender: str, receiver: str, error: str, details: Dict[str, Any] = None) -> AgentMessage:
    """Create an error message."""
    return AgentMessage(
        sender=sender,
        receiver=receiver,
        msg_type="error",
        payload={"error": error, "details": details or {}},
        priority=MessagePriority.CRITICAL
    )
