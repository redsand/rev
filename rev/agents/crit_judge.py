#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CRIT Judge - Critical Reasoning and Inspection Tool.

Implements Socratic validation gates for plans, claims, and merges.
Based on MACI principle that debate alone isn't enough - need critical filtering.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from pathlib import Path

from rev.models.task import Task, ExecutionPlan
from rev.models.dod import DefinitionOfDone
from rev.llm.client import ollama_chat


class JudgementType(Enum):
    """Type of judgement being made."""
    PLAN_EVALUATION = "plan_evaluation"
    CLAIM_VERIFICATION = "claim_verification"
    MERGE_GATE = "merge_gate"


class Verdict(Enum):
    """Verdict from CRIT judge."""
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


@dataclass
class CriticalQuestion:
    """A Socratic question posed by CRIT."""
    question: str
    category: str  # e.g., "logic", "dependencies", "risks", "completeness"
    severity: str = "medium"  # "low", "medium", "high", "critical"
    context: Optional[str] = None


@dataclass
class CRITJudgement:
    """Result of CRIT evaluation."""
    verdict: Verdict
    judgement_type: JudgementType
    questions: List[CriticalQuestion] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0 to 1.0
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """Generate a summary of the judgement."""
        lines = [
            f"CRIT Judgement: {self.verdict.value.upper()}",
            f"Type: {self.judgement_type.value}",
            f"Confidence: {self.confidence:.0%}"
        ]

        if self.questions:
            lines.append(f"\nCritical Questions ({len(self.questions)}):")
            for q in self.questions:
                severity_marker = {
                    "low": "○",
                    "medium": "◐",
                    "high": "●",
                    "critical": "⚠"
                }.get(q.severity, "○")
                lines.append(f"  {severity_marker} [{q.category}] {q.question}")

        if self.concerns:
            lines.append(f"\nConcerns ({len(self.concerns)}):")
            for concern in self.concerns:
                lines.append(f"  - {concern}")

        if self.recommendations:
            lines.append(f"\nRecommendations ({len(self.recommendations)}):")
            for rec in self.recommendations:
                lines.append(f"  → {rec}")

        if self.reasoning:
            lines.append(f"\nReasoning:\n{self.reasoning}")

        return "\n".join(lines)


class CRITJudge:
    """CRIT Judge - Socratic validation system."""

    def __init__(self, use_llm: bool = True):
        """
        Initialize CRIT judge.

        Args:
            use_llm: Whether to use LLM for deeper analysis (default: True)
        """
        self.use_llm = use_llm

    def evaluate_plan(
        self,
        plan: ExecutionPlan,
        user_request: str,
        context: Optional[Dict[str, Any]] = None
    ) -> CRITJudgement:
        """
        Evaluate an execution plan before it runs.

        Asks critical questions:
        - Are the steps logical?
        - Are there missing dependencies?
        - Are the acceptance criteria clear?
        - Could this approach cause issues?

        Args:
            plan: The execution plan to evaluate
            user_request: The original user request
            context: Optional context (file list, project info, etc.)

        Returns:
            CRITJudgement with verdict and questions
        """
        questions = []
        concerns = []
        recommendations = []

        # Heuristic checks
        if not plan.tasks:
            concerns.append("Plan has no tasks")
            questions.append(CriticalQuestion(
                question="Why is the plan empty? Is the request achievable?",
                category="completeness",
                severity="critical"
            ))

        # Check for circular dependencies
        dep_issues = self._check_dependencies(plan)
        if dep_issues:
            concerns.extend(dep_issues)
            questions.append(CriticalQuestion(
                question="How will circular dependencies be resolved?",
                category="dependencies",
                severity="high"
            ))

        # Check for high-risk tasks without validation
        high_risk_tasks = [t for t in plan.tasks if hasattr(t, 'risk_level') and t.risk_level.value in ['high', 'critical']]
        tasks_without_validation = [t for t in high_risk_tasks if not t.validation_steps]

        if tasks_without_validation:
            concerns.append(f"{len(tasks_without_validation)} high-risk tasks lack validation steps")
            questions.append(CriticalQuestion(
                question="How will high-risk changes be validated before deployment?",
                category="risks",
                severity="high"
            ))

        # Check for destructive operations without rollback
        destructive_tasks = [t for t in plan.tasks if t.action_type in ['delete', 'rename']]
        tasks_without_rollback = [t for t in destructive_tasks if not t.rollback_plan]

        if tasks_without_rollback:
            concerns.append(f"{len(tasks_without_rollback)} destructive tasks lack rollback plans")
            recommendations.append("Add rollback plans to all destructive operations")
            questions.append(CriticalQuestion(
                question="What happens if a delete/rename operation fails midway?",
                category="safety",
                severity="critical"
            ))

        # LLM-based deeper analysis
        if self.use_llm:
            llm_judgement = self._llm_evaluate_plan(plan, user_request, context)
            questions.extend(llm_judgement.get("questions", []))
            concerns.extend(llm_judgement.get("concerns", []))
            recommendations.extend(llm_judgement.get("recommendations", []))

        # Determine verdict
        critical_questions = [q for q in questions if q.severity == "critical"]
        high_severity_questions = [q for q in questions if q.severity in ["high", "critical"]]

        if critical_questions:
            verdict = Verdict.REJECTED
            confidence = 0.9
        elif len(high_severity_questions) > 2:
            verdict = Verdict.NEEDS_REVISION
            confidence = 0.7
        elif concerns:
            verdict = Verdict.NEEDS_REVISION
            confidence = 0.6
        else:
            verdict = Verdict.APPROVED
            confidence = 0.8

        reasoning = self._generate_reasoning(verdict, questions, concerns)

        return CRITJudgement(
            verdict=verdict,
            judgement_type=JudgementType.PLAN_EVALUATION,
            questions=questions,
            concerns=concerns,
            recommendations=recommendations,
            confidence=confidence,
            reasoning=reasoning,
            metadata={
                "total_tasks": len(plan.tasks),
                "high_risk_tasks": len(high_risk_tasks),
                "destructive_tasks": len(destructive_tasks)
            }
        )

    def verify_claim(
        self,
        claim: str,
        evidence: Dict[str, Any],
        task: Optional[Task] = None
    ) -> CRITJudgement:
        """
        Verify a claim made during execution.

        Common claims:
        - "Task completed successfully"
        - "All tests pass"
        - "No errors detected"
        - "Changes are backward compatible"

        Args:
            claim: The claim being made
            evidence: Evidence supporting the claim
            task: Optional task context

        Returns:
            CRITJudgement with verdict
        """
        questions = []
        concerns = []
        recommendations = []

        claim_lower = claim.lower()

        # Check "completed" claims
        if "completed" in claim_lower or "done" in claim_lower:
            if not evidence.get("deliverables_verified"):
                concerns.append("Completion claimed but deliverables not verified")
                questions.append(CriticalQuestion(
                    question="What concrete deliverables prove this task is complete?",
                    category="completeness",
                    severity="high"
                ))

            if not evidence.get("tests_passed"):
                concerns.append("Completion claimed but tests not run")
                questions.append(CriticalQuestion(
                    question="Have tests been run to validate the changes?",
                    category="verification",
                    severity="medium"
                ))

        # Check "tests pass" claims
        if "test" in claim_lower and "pass" in claim_lower:
            if "exit_code" not in evidence:
                concerns.append("Test pass claimed but no exit code provided")
                questions.append(CriticalQuestion(
                    question="What was the actual exit code from the test runner?",
                    category="verification",
                    severity="high"
                ))

            if evidence.get("exit_code") != 0:
                concerns.append(f"Tests claimed to pass but exit code is {evidence.get('exit_code')}")
                questions.append(CriticalQuestion(
                    question="Why claim tests pass when exit code is non-zero?",
                    category="logic",
                    severity="critical"
                ))

        # Check "no errors" claims
        if "no error" in claim_lower or "error-free" in claim_lower:
            if evidence.get("stderr"):
                concerns.append("'No errors' claimed but stderr is not empty")
                recommendations.append("Review stderr output for warnings or errors")

            if evidence.get("syntax_errors"):
                concerns.append("'No errors' claimed but syntax errors detected")
                questions.append(CriticalQuestion(
                    question="How can there be no errors if syntax errors were detected?",
                    category="logic",
                    severity="critical"
                ))

        # LLM-based claim verification
        if self.use_llm:
            llm_judgement = self._llm_verify_claim(claim, evidence, task)
            questions.extend(llm_judgement.get("questions", []))
            concerns.extend(llm_judgement.get("concerns", []))

        # Determine verdict
        critical_issues = [q for q in questions if q.severity == "critical"]

        if critical_issues:
            verdict = Verdict.REJECTED
            confidence = 0.95
        elif concerns:
            verdict = Verdict.NEEDS_REVISION
            confidence = 0.7
        else:
            verdict = Verdict.APPROVED
            confidence = 0.85

        reasoning = self._generate_reasoning(verdict, questions, concerns)

        return CRITJudgement(
            verdict=verdict,
            judgement_type=JudgementType.CLAIM_VERIFICATION,
            questions=questions,
            concerns=concerns,
            recommendations=recommendations,
            confidence=confidence,
            reasoning=reasoning,
            metadata={"claim": claim, "evidence_keys": list(evidence.keys())}
        )

    def evaluate_merge(
        self,
        task: Task,
        dod: Optional[DefinitionOfDone] = None,
        verification_passed: bool = False,
        transaction_committed: bool = False,
        context: Optional[Dict[str, Any]] = None
    ) -> CRITJudgement:
        """
        Evaluate whether changes should be merged/accepted.

        Final gate before accepting changes as complete.

        Args:
            task: The task that was executed
            dod: Optional Definition of Done
            verification_passed: Whether verification passed
            transaction_committed: Whether transaction was committed
            context: Optional additional context

        Returns:
            CRITJudgement with merge verdict
        """
        questions = []
        concerns = []
        recommendations = []

        # Check DoD
        if dod:
            if not context or not context.get("dod_verified"):
                concerns.append("DoD defined but not verified")
                questions.append(CriticalQuestion(
                    question="Have all DoD deliverables and acceptance criteria been verified?",
                    category="completeness",
                    severity="critical"
                ))
        else:
            concerns.append("No Definition of Done defined")
            recommendations.append("Define DoD for all tasks to ensure clear completion criteria")

        # Check verification
        if not verification_passed:
            concerns.append("Verification did not pass")
            questions.append(CriticalQuestion(
                question="Why merge when verification failed?",
                category="quality",
                severity="critical"
            ))

        # Check transaction
        if not transaction_committed:
            concerns.append("Transaction not committed")
            questions.append(CriticalQuestion(
                question="Was the transaction rolled back? Why proceed with merge?",
                category="consistency",
                severity="critical"
            ))

        # Check task status
        if task.error:
            concerns.append(f"Task has error: {task.error}")
            questions.append(CriticalQuestion(
                question="How can we merge when the task encountered an error?",
                category="quality",
                severity="critical"
            ))

        # Check for unintended side effects
        if context and context.get("files_modified"):
            expected_files = set(context.get("expected_files", []))
            actual_files = set(context.get("files_modified", []))
            unexpected_files = actual_files - expected_files

            if unexpected_files:
                concerns.append(f"{len(unexpected_files)} unexpected files were modified")
                recommendations.append(f"Review unexpected modifications: {', '.join(list(unexpected_files)[:3])}")
                questions.append(CriticalQuestion(
                    question="Why were additional files modified beyond what was planned?",
                    category="scope",
                    severity="medium"
                ))

        # LLM-based merge evaluation
        if self.use_llm:
            llm_judgement = self._llm_evaluate_merge(task, dod, context)
            questions.extend(llm_judgement.get("questions", []))
            concerns.extend(llm_judgement.get("concerns", []))
            recommendations.extend(llm_judgement.get("recommendations", []))

        # Determine verdict
        critical_issues = [q for q in questions if q.severity == "critical"]

        if critical_issues:
            verdict = Verdict.REJECTED
            confidence = 0.95
        elif len(concerns) > 2:
            verdict = Verdict.NEEDS_REVISION
            confidence = 0.75
        else:
            verdict = Verdict.APPROVED
            confidence = 0.9

        reasoning = self._generate_reasoning(verdict, questions, concerns)

        return CRITJudgement(
            verdict=verdict,
            judgement_type=JudgementType.MERGE_GATE,
            questions=questions,
            concerns=concerns,
            recommendations=recommendations,
            confidence=confidence,
            reasoning=reasoning,
            metadata={
                "task_id": task.task_id,
                "dod_defined": dod is not None,
                "verification_passed": verification_passed,
                "transaction_committed": transaction_committed
            }
        )

    def _check_dependencies(self, plan: ExecutionPlan) -> List[str]:
        """Check for dependency issues in plan."""
        issues = []

        # Check for circular dependencies
        def has_cycle(task_id: int, visited: set, stack: set) -> bool:
            visited.add(task_id)
            stack.add(task_id)

            if task_id >= len(plan.tasks):
                return False

            for dep_id in plan.tasks[task_id].dependencies:
                if dep_id not in visited:
                    if has_cycle(dep_id, visited, stack):
                        return True
                elif dep_id in stack:
                    return True

            stack.remove(task_id)
            return False

        visited = set()
        for i, task in enumerate(plan.tasks):
            if i not in visited:
                if has_cycle(i, visited, set()):
                    issues.append(f"Circular dependency detected involving task {i}")

        # Check for invalid dependencies
        for i, task in enumerate(plan.tasks):
            for dep_id in task.dependencies:
                if dep_id >= len(plan.tasks):
                    issues.append(f"Task {i} depends on non-existent task {dep_id}")
                if dep_id == i:
                    issues.append(f"Task {i} depends on itself")

        return issues

    def _llm_evaluate_plan(
        self,
        plan: ExecutionPlan,
        user_request: str,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Use LLM to evaluate plan (deeper analysis)."""
        if not self.use_llm:
            return {}

        prompt = self._build_plan_evaluation_prompt(plan, user_request, context)

        try:
            response = ollama_chat([{"role": "user", "content": prompt}])
            content = response.get("message", {}).get("content", "")

            # Parse LLM response for questions and concerns
            return self._parse_llm_response(content)
        except Exception:
            # Fallback if LLM fails
            return {}

    def _llm_verify_claim(
        self,
        claim: str,
        evidence: Dict[str, Any],
        task: Optional[Task]
    ) -> Dict[str, Any]:
        """Use LLM to verify claim."""
        if not self.use_llm:
            return {}

        prompt = f"""You are CRIT (Critical Reasoning and Inspection Tool), a Socratic judge.

Verify this claim using the provided evidence:

CLAIM: {claim}

EVIDENCE:
{self._format_evidence(evidence)}

Ask 1-3 critical questions that probe:
1. Is the evidence sufficient to support the claim?
2. Are there contradictions or gaps?
3. What could disprove this claim?

Format your response as:
QUESTIONS:
- [category] question text (severity: low/medium/high/critical)

CONCERNS:
- concern text

Keep responses concise and focused."""

        try:
            response = ollama_chat([{"role": "user", "content": prompt}])
            content = response.get("message", {}).get("content", "")
            return self._parse_llm_response(content)
        except Exception:
            return {}

    def _llm_evaluate_merge(
        self,
        task: Task,
        dod: Optional[DefinitionOfDone],
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Use LLM to evaluate merge."""
        if not self.use_llm:
            return {}

        prompt = f"""You are CRIT, evaluating whether to accept/merge changes.

TASK: {task.description}
STATUS: {task.status.value}
ERROR: {task.error or "None"}

DOD DEFINED: {"Yes" if dod else "No"}

Ask critical questions about:
1. Completeness - Is the work truly done?
2. Quality - Does it meet standards?
3. Safety - Are there risks?

Format: QUESTIONS: / CONCERNS: / RECOMMENDATIONS:"""

        try:
            response = ollama_chat([{"role": "user", "content": prompt}])
            content = response.get("message", {}).get("content", "")
            return self._parse_llm_response(content)
        except Exception:
            return {}

    def _build_plan_evaluation_prompt(
        self,
        plan: ExecutionPlan,
        user_request: str,
        context: Optional[Dict[str, Any]]
    ) -> str:
        """Build prompt for LLM plan evaluation."""
        task_summary = "\n".join([
            f"{i+1}. [{t.action_type}] {t.description}"
            for i, t in enumerate(plan.tasks[:10])  # Limit to first 10
        ])

        return f"""You are CRIT (Critical Reasoning and Inspection Tool), a Socratic judge.

Evaluate this execution plan using critical reasoning:

USER REQUEST:
{user_request}

PROPOSED PLAN ({len(plan.tasks)} tasks):
{task_summary}
{"..." if len(plan.tasks) > 10 else ""}

Ask 2-4 critical questions that probe:
1. Logic - Are the steps logical? Missing steps?
2. Dependencies - Correct order? Circular dependencies?
3. Risks - What could go wrong?
4. Completeness - Will this achieve the goal?

Format your response as:
QUESTIONS:
- [category] question text (severity: low/medium/high/critical)

CONCERNS:
- concern text

RECOMMENDATIONS:
- recommendation text

Keep responses concise and actionable."""

    def _parse_llm_response(self, content: str) -> Dict[str, Any]:
        """Parse LLM response into structured format."""
        result = {
            "questions": [],
            "concerns": [],
            "recommendations": []
        }

        current_section = None
        for line in content.split("\n"):
            line = line.strip()

            if line.upper().startswith("QUESTIONS:"):
                current_section = "questions"
                continue
            elif line.upper().startswith("CONCERNS:"):
                current_section = "concerns"
                continue
            elif line.upper().startswith("RECOMMENDATIONS:"):
                current_section = "recommendations"
                continue

            if not line or not line.startswith("-"):
                continue

            line = line.lstrip("- ").strip()

            if current_section == "questions":
                # Parse question format: [category] question (severity: level)
                category = "general"
                severity = "medium"
                question_text = line

                if "[" in line and "]" in line:
                    category = line[line.index("[")+1:line.index("]")]
                    question_text = line[line.index("]")+1:].strip()

                if "(severity:" in question_text.lower():
                    severity_start = question_text.lower().index("(severity:")
                    severity = question_text[severity_start+10:].split(")")[0].strip()
                    question_text = question_text[:severity_start].strip()

                result["questions"].append(CriticalQuestion(
                    question=question_text,
                    category=category,
                    severity=severity
                ))

            elif current_section == "concerns":
                result["concerns"].append(line)

            elif current_section == "recommendations":
                result["recommendations"].append(line)

        return result

    def _format_evidence(self, evidence: Dict[str, Any]) -> str:
        """Format evidence dictionary for display."""
        lines = []
        for key, value in evidence.items():
            if isinstance(value, (list, dict)):
                lines.append(f"- {key}: {type(value).__name__} with {len(value)} items")
            else:
                lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def _generate_reasoning(
        self,
        verdict: Verdict,
        questions: List[CriticalQuestion],
        concerns: List[str]
    ) -> str:
        """Generate reasoning explanation for verdict."""
        if verdict == Verdict.APPROVED:
            if not questions and not concerns:
                return "No critical issues identified. All checks passed."
            else:
                return f"Minor concerns noted ({len(concerns)}) but not blocking. {len(questions)} questions raised for consideration."

        elif verdict == Verdict.NEEDS_REVISION:
            critical_count = sum(1 for q in questions if q.severity in ["high", "critical"])
            return f"Significant issues require attention: {len(concerns)} concerns, {critical_count} high-severity questions. Recommend revision before proceeding."

        else:  # REJECTED
            critical_count = sum(1 for q in questions if q.severity == "critical")
            return f"Critical issues prevent approval: {critical_count} critical questions, {len(concerns)} concerns. Must be addressed before proceeding."
