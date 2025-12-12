"""
Learning Agent for project memory and pattern recognition.

This module provides learning capabilities that maintain project-specific
knowledge across sessions, learning from successes and failures.
"""

import json
import hashlib
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

from rev import config
from rev.models.task import ExecutionPlan, Task, TaskStatus, RiskLevel


@dataclass
class TaskPattern:
    """A learned pattern from successful task execution."""
    pattern_id: str
    task_type: str  # e.g., "add_authentication", "fix_tests", "refactor"
    description_keywords: List[str]
    successful_approaches: List[Dict[str, Any]]
    common_files: List[str]
    common_tools: List[str]
    avg_execution_time: float
    success_rate: float
    last_used: str
    use_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskPattern':
        return cls(**data)


@dataclass
class ProjectContext:
    """Project-specific learned context."""
    project_path: str
    framework: Optional[str] = None  # e.g., "django", "flask", "express"
    language: Optional[str] = None  # e.g., "python", "javascript"
    test_framework: Optional[str] = None  # e.g., "pytest", "jest"
    coding_style: Dict[str, Any] = field(default_factory=dict)
    important_files: List[str] = field(default_factory=list)
    architecture_notes: List[str] = field(default_factory=list)
    common_issues: List[Dict[str, str]] = field(default_factory=list)
    last_updated: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectContext':
        return cls(**data)


@dataclass
class ExecutionMemory:
    """Memory of a specific execution for learning."""
    execution_id: str
    timestamp: str
    user_request: str
    task_count: int
    success_count: int
    failure_count: int
    duration_seconds: float
    patterns_used: List[str]
    files_modified: List[str]
    tools_used: List[str]
    review_suggestions_applied: List[str]
    validation_passed: bool
    user_feedback: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ExecutionMemory':
        return cls(**data)


class LearningAgent:
    """Agent that learns from executions and provides contextual assistance."""

    def __init__(self, project_root: Path, memory_dir: Optional[Path] = None):
        """Initialize the learning agent.

        Args:
            project_root: Root path of the project
            memory_dir: Directory to store learning data (default: .rev/memory)
        """
        self.project_root = project_root
        self.memory_dir = memory_dir or config.MEMORY_DIR
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Memory stores
        self.patterns: Dict[str, TaskPattern] = {}
        self.context: Optional[ProjectContext] = None
        self.execution_history: List[ExecutionMemory] = []

        # Load existing memory
        self._load_memory()

    def _load_memory(self):
        """Load memory from disk."""
        # Load patterns
        patterns_file = self.memory_dir / "patterns.json"
        if patterns_file.exists():
            try:
                data = json.loads(patterns_file.read_text())
                self.patterns = {k: TaskPattern.from_dict(v) for k, v in data.items()}
            except Exception as e:
                print(f"Warning: Could not load patterns: {e}")

        # Load context
        context_file = self.memory_dir / "context.json"
        if context_file.exists():
            try:
                data = json.loads(context_file.read_text())
                self.context = ProjectContext.from_dict(data)
            except Exception as e:
                print(f"Warning: Could not load context: {e}")

        # Load execution history (last 100)
        history_file = self.memory_dir / "history.json"
        if history_file.exists():
            try:
                data = json.loads(history_file.read_text())
                self.execution_history = [ExecutionMemory.from_dict(e) for e in data[-100:]]
            except Exception as e:
                print(f"Warning: Could not load history: {e}")

    def _save_memory(self):
        """Persist memory to disk."""
        # Save patterns
        patterns_file = self.memory_dir / "patterns.json"
        patterns_file.write_text(json.dumps(
            {k: v.to_dict() for k, v in self.patterns.items()},
            indent=2
        ))

        # Save context
        if self.context:
            context_file = self.memory_dir / "context.json"
            context_file.write_text(json.dumps(self.context.to_dict(), indent=2))

        # Save history (keep last 100)
        history_file = self.memory_dir / "history.json"
        history_file.write_text(json.dumps(
            [e.to_dict() for e in self.execution_history[-100:]],
            indent=2
        ))

    def learn_from_execution(
        self,
        plan: ExecutionPlan,
        user_request: str,
        duration: float,
        validation_passed: bool,
        review_suggestions: List[str] = None,
        files_modified: List[str] = None,
        tools_used: List[str] = None
    ):
        """Learn from a completed execution.

        Args:
            plan: The executed plan
            user_request: Original user request
            duration: Execution duration in seconds
            validation_passed: Whether validation passed
            review_suggestions: Suggestions from review agent that were applied
            files_modified: List of modified files
            tools_used: List of tools that were used
        """
        # Create execution memory
        execution_id = hashlib.md5(f"{user_request}{time.time()}".encode()).hexdigest()[:12]
        success_count = sum(1 for t in plan.tasks if t.status == TaskStatus.COMPLETED)
        failure_count = sum(1 for t in plan.tasks if t.status == TaskStatus.FAILED)

        memory = ExecutionMemory(
            execution_id=execution_id,
            timestamp=datetime.now().isoformat(),
            user_request=user_request,
            task_count=len(plan.tasks),
            success_count=success_count,
            failure_count=failure_count,
            duration_seconds=duration,
            patterns_used=[],
            files_modified=files_modified or [],
            tools_used=tools_used or [],
            review_suggestions_applied=review_suggestions or [],
            validation_passed=validation_passed
        )
        self.execution_history.append(memory)

        # Learn patterns from successful executions
        if success_count > 0 and validation_passed:
            self._learn_pattern(plan, user_request, duration, files_modified, tools_used)

        # Update project context
        self._update_context(plan, files_modified)

        # Persist
        self._save_memory()

    def _learn_pattern(
        self,
        plan: ExecutionPlan,
        user_request: str,
        duration: float,
        files_modified: List[str],
        tools_used: List[str]
    ):
        """Extract and store a pattern from successful execution."""
        # Extract keywords from request
        keywords = self._extract_keywords(user_request)
        task_type = self._classify_task_type(user_request, plan)

        # Generate pattern ID
        pattern_id = hashlib.md5(task_type.encode()).hexdigest()[:8]

        # Create or update pattern
        if pattern_id in self.patterns:
            pattern = self.patterns[pattern_id]
            # Update with new execution data
            pattern.use_count += 1
            pattern.last_used = datetime.now().isoformat()
            # Update success rate (weighted average)
            pattern.success_rate = (pattern.success_rate * (pattern.use_count - 1) + 1.0) / pattern.use_count
            # Update avg time
            pattern.avg_execution_time = (pattern.avg_execution_time * (pattern.use_count - 1) + duration) / pattern.use_count
            # Add new approach if different
            approach = self._extract_approach(plan)
            if approach not in pattern.successful_approaches:
                pattern.successful_approaches.append(approach)
                if len(pattern.successful_approaches) > 5:
                    pattern.successful_approaches = pattern.successful_approaches[-5:]
        else:
            # Create new pattern
            pattern = TaskPattern(
                pattern_id=pattern_id,
                task_type=task_type,
                description_keywords=keywords,
                successful_approaches=[self._extract_approach(plan)],
                common_files=files_modified or [],
                common_tools=tools_used or [],
                avg_execution_time=duration,
                success_rate=1.0,
                last_used=datetime.now().isoformat(),
                use_count=1
            )
            self.patterns[pattern_id] = pattern

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text."""
        # Simple keyword extraction - could be enhanced with NLP
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'with', 'all', 'my', 'this'}
        words = text.lower().split()
        keywords = [w for w in words if len(w) > 2 and w not in stop_words]
        return keywords[:10]

    def _classify_task_type(self, request: str, plan: ExecutionPlan) -> str:
        """Classify the type of task."""
        request_lower = request.lower()

        # Check for common patterns
        if 'auth' in request_lower:
            return 'authentication'
        elif 'test' in request_lower:
            return 'testing'
        elif 'fix' in request_lower or 'bug' in request_lower:
            return 'bugfix'
        elif 'refactor' in request_lower:
            return 'refactoring'
        elif 'add' in request_lower or 'create' in request_lower or 'implement' in request_lower:
            return 'feature_add'
        elif 'update' in request_lower or 'modify' in request_lower:
            return 'feature_update'
        elif 'delete' in request_lower or 'remove' in request_lower:
            return 'removal'
        elif 'doc' in request_lower:
            return 'documentation'
        else:
            # Use action type distribution
            action_types = [t.action_type for t in plan.tasks]
            if action_types:
                return max(set(action_types), key=action_types.count)
            return 'general'

    def _extract_approach(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Extract the approach used from a plan."""
        return {
            "task_sequence": [
                {"description": t.description[:100], "action_type": t.action_type, "status": t.status.value}
                for t in plan.tasks
            ],
            "task_count": len(plan.tasks),
            "action_types": list(set(t.action_type for t in plan.tasks))
        }

    def _update_context(self, plan: ExecutionPlan, files_modified: List[str]):
        """Update project context from execution."""
        if not self.context:
            self.context = ProjectContext(project_path=str(self.project_root))

        self.context.last_updated = datetime.now().isoformat()

        # Track important files
        if files_modified:
            for f in files_modified:
                if f not in self.context.important_files:
                    self.context.important_files.append(f)
            # Keep only most recent 50
            self.context.important_files = self.context.important_files[-50:]

    def get_relevant_patterns(self, user_request: str, top_k: int = 3) -> List[TaskPattern]:
        """Find patterns relevant to the current request.

        Args:
            user_request: The user's task request
            top_k: Number of patterns to return

        Returns:
            List of relevant TaskPatterns
        """
        if not self.patterns:
            return []

        keywords = self._extract_keywords(user_request)
        request_lower = user_request.lower()

        # Score patterns by relevance
        scored_patterns = []
        for pattern in self.patterns.values():
            score = 0.0

            # Keyword overlap
            keyword_overlap = len(set(keywords) & set(pattern.description_keywords))
            score += keyword_overlap * 2

            # Task type match
            task_type = self._classify_task_type(user_request, ExecutionPlan())
            if task_type == pattern.task_type:
                score += 5

            # Success rate bonus
            score += pattern.success_rate * 2

            # Recency bonus
            score += pattern.use_count * 0.1

            scored_patterns.append((score, pattern))

        # Sort by score and return top_k
        scored_patterns.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored_patterns[:top_k] if _ > 0]

    def get_suggestions(self, user_request: str) -> Dict[str, Any]:
        """Get suggestions based on learned patterns.

        Args:
            user_request: The user's task request

        Returns:
            Dict with suggestions based on past learning
        """
        suggestions = {
            "similar_patterns": [],
            "recommended_approach": None,
            "common_files": [],
            "estimated_time": None,
            "warnings": [],
            "tips": []
        }

        patterns = self.get_relevant_patterns(user_request)

        if patterns:
            # Best matching pattern
            best = patterns[0]
            suggestions["similar_patterns"] = [p.task_type for p in patterns]
            suggestions["recommended_approach"] = best.successful_approaches[0] if best.successful_approaches else None
            suggestions["common_files"] = best.common_files[:5]
            suggestions["estimated_time"] = best.avg_execution_time

            # Add tips based on pattern
            if best.success_rate < 0.8:
                suggestions["warnings"].append(f"Similar tasks have {best.success_rate:.0%} success rate - proceed carefully")

            if best.use_count > 5:
                suggestions["tips"].append(f"This type of task has been done {best.use_count} times before")

        # Add context-based suggestions
        if self.context:
            if self.context.common_issues:
                for issue in self.context.common_issues[-3:]:
                    if any(k in user_request.lower() for k in issue.get("keywords", [])):
                        suggestions["warnings"].append(issue.get("description", ""))

        return suggestions

    def record_failure(self, user_request: str, error: str, task_type: str = None):
        """Record a failure for learning.

        Args:
            user_request: The failed request
            error: Error description
            task_type: Type of task that failed
        """
        if not self.context:
            self.context = ProjectContext(project_path=str(self.project_root))

        # Add to common issues
        issue = {
            "keywords": self._extract_keywords(user_request),
            "description": f"Previous failure: {error[:200]}",
            "timestamp": datetime.now().isoformat(),
            "task_type": task_type or "unknown"
        }
        self.context.common_issues.append(issue)

        # Keep only recent issues
        self.context.common_issues = self.context.common_issues[-20:]
        self._save_memory()

    def get_project_context(self) -> Optional[ProjectContext]:
        """Get the learned project context."""
        return self.context

    def get_execution_stats(self) -> Dict[str, Any]:
        """Get statistics about past executions."""
        if not self.execution_history:
            return {"total_executions": 0}

        total = len(self.execution_history)
        successful = sum(1 for e in self.execution_history if e.validation_passed)
        total_tasks = sum(e.task_count for e in self.execution_history)
        successful_tasks = sum(e.success_count for e in self.execution_history)
        avg_duration = sum(e.duration_seconds for e in self.execution_history) / total

        return {
            "total_executions": total,
            "successful_executions": successful,
            "success_rate": successful / total if total > 0 else 0,
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "task_success_rate": successful_tasks / total_tasks if total_tasks > 0 else 0,
            "avg_duration_seconds": avg_duration,
            "patterns_learned": len(self.patterns)
        }

    def clear_memory(self):
        """Clear all learned memory."""
        self.patterns = {}
        self.context = None
        self.execution_history = []

        # Remove files
        for f in self.memory_dir.glob("*.json"):
            f.unlink()


def display_learning_suggestions(suggestions: Dict[str, Any], user_request: str):
    """Display learning-based suggestions to the user.

    Args:
        suggestions: Suggestions from get_suggestions()
        user_request: The user's request
    """
    has_content = False

    if suggestions["similar_patterns"]:
        has_content = True
        print("\n" + "=" * 60)
        print("LEARNING AGENT - INSIGHTS")
        print("=" * 60)
        print(f"📚 Similar past tasks: {', '.join(suggestions['similar_patterns'])}")

    if suggestions["estimated_time"]:
        has_content = True
        mins = suggestions["estimated_time"] / 60
        print(f"⏱️  Estimated time: {mins:.1f} minutes")

    if suggestions["common_files"]:
        has_content = True
        print(f"📁 Likely files: {', '.join(suggestions['common_files'][:3])}")

    if suggestions["warnings"]:
        has_content = True
        print("\n⚠️  Warnings from past experience:")
        for warning in suggestions["warnings"]:
            print(f"   - {warning}")

    if suggestions["tips"]:
        has_content = True
        print("\n💡 Tips:")
        for tip in suggestions["tips"]:
            print(f"   - {tip}")

    if has_content:
        print("=" * 60)
