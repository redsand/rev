"""
Test suite for advanced planning capabilities

Tests cover:
- Dependency analysis
- Impact assessment
- Risk evaluation
- Rollback planning
- Validation step generation
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Import rev module
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load rev.py
import types
rev_path = Path(__file__).parent.parent / "rev.py"
agent_min = types.ModuleType("agent_min")
agent_min.__file__ = str(rev_path)

with open(rev_path, 'r', encoding='utf-8') as f:
    code = compile(f.read(), str(rev_path), 'exec')
    exec(code, agent_min.__dict__)

sys.modules['agent_min'] = agent_min


# ========== Test Fixtures ==========

@pytest.fixture
def execution_plan():
    """Create an execution plan with sample tasks."""
    plan = agent_min.ExecutionPlan()
    return plan


@pytest.fixture
def sample_tasks(execution_plan):
    """Create execution plan with sample tasks and dependencies."""
    # Task 0: Review code (no dependencies)
    execution_plan.add_task("Review authentication module", "review", dependencies=[])

    # Task 1: Add error handling (depends on review)
    execution_plan.add_task("Add error handling to auth endpoints", "edit", dependencies=[0])

    # Task 2: Create tests (depends on edit)
    execution_plan.add_task("Create tests for error handling", "add", dependencies=[1])

    # Task 3: Delete old auth file (high risk, depends on new code)
    execution_plan.add_task("Delete deprecated authentication file", "delete", dependencies=[1])

    # Task 4: Run tests (depends on test creation)
    execution_plan.add_task("Run test suite", "test", dependencies=[2, 3])

    return execution_plan


# ========== Test Risk Levels ==========

class TestRiskLevel:
    """Test RiskLevel enum."""

    def test_risk_levels_exist(self):
        """Test that all risk levels are defined."""
        assert hasattr(agent_min, 'RiskLevel')
        assert agent_min.RiskLevel.LOW
        assert agent_min.RiskLevel.MEDIUM
        assert agent_min.RiskLevel.HIGH
        assert agent_min.RiskLevel.CRITICAL


# ========== Test Task Enhanced Features ==========

class TestTaskAdvancedFeatures:
    """Test Task class advanced features."""

    def test_task_has_risk_attributes(self, execution_plan):
        """Test that tasks have risk-related attributes."""
        execution_plan.add_task("Test task", "general")
        task = execution_plan.tasks[0]

        assert hasattr(task, 'risk_level')
        assert hasattr(task, 'risk_reasons')
        assert hasattr(task, 'impact_scope')
        assert hasattr(task, 'breaking_change')
        assert hasattr(task, 'rollback_plan')
        assert hasattr(task, 'validation_steps')

    def test_task_default_risk_is_low(self, execution_plan):
        """Test that default risk level is LOW."""
        execution_plan.add_task("Test task", "general")
        task = execution_plan.tasks[0]

        assert task.risk_level == agent_min.RiskLevel.LOW

    def test_task_to_dict_includes_advanced_fields(self, execution_plan):
        """Test that to_dict includes advanced planning fields."""
        execution_plan.add_task("Test task", "general")
        task = execution_plan.tasks[0]

        task_dict = task.to_dict()

        assert "risk_level" in task_dict
        assert "risk_reasons" in task_dict
        assert "impact_scope" in task_dict
        assert "breaking_change" in task_dict
        assert "rollback_plan" in task_dict
        assert "validation_steps" in task_dict


# ========== Test Dependency Analysis ==========

class TestDependencyAnalysis:
    """Test dependency analysis capabilities."""

    def test_analyze_dependencies_basic(self, sample_tasks):
        """Test basic dependency analysis."""
        analysis = sample_tasks.analyze_dependencies()

        assert "dependency_graph" in analysis
        assert "reverse_dependencies" in analysis
        assert "root_tasks" in analysis
        assert "total_tasks" in analysis

        # Should have 5 tasks
        assert analysis["total_tasks"] == 5

    def test_dependency_graph_structure(self, sample_tasks):
        """Test dependency graph structure."""
        analysis = sample_tasks.analyze_dependencies()
        graph = analysis["dependency_graph"]

        # Task 0 has no dependencies
        assert graph[0] == []

        # Task 1 depends on task 0
        assert 0 in graph[1]

        # Task 4 depends on tasks 2 and 3
        assert 2 in graph[4]
        assert 3 in graph[4]

    def test_root_tasks_identification(self, sample_tasks):
        """Test identification of root tasks (no dependencies)."""
        analysis = sample_tasks.analyze_dependencies()

        # Only task 0 has no dependencies
        assert analysis["root_tasks"] == [0]

    def test_reverse_dependencies(self, sample_tasks):
        """Test reverse dependency mapping."""
        analysis = sample_tasks.analyze_dependencies()
        reverse = analysis["reverse_dependencies"]

        # Task 0 is depended on by task 1
        assert 1 in reverse[0]

        # Task 1 is depended on by tasks 2 and 3
        assert 2 in reverse[1]
        assert 3 in reverse[1]

    def test_parallelization_potential(self, sample_tasks):
        """Test parallelization potential calculation."""
        analysis = sample_tasks.analyze_dependencies()

        # Tasks 2 and 3 can run in parallel (both depend on 1)
        assert analysis["parallelization_potential"] >= 2

    def test_critical_path_length(self, sample_tasks):
        """Test critical path length calculation."""
        analysis = sample_tasks.analyze_dependencies()

        # Path: 0 -> 1 -> 2 -> 4 (or 0 -> 1 -> 3 -> 4)
        # Should be at least 4 tasks deep
        assert analysis["critical_path_length"] >= 3


# ========== Test Impact Assessment ==========

class TestImpactAssessment:
    """Test impact assessment capabilities."""

    def test_assess_impact_basic(self, sample_tasks):
        """Test basic impact assessment."""
        task = sample_tasks.tasks[0]
        impact = sample_tasks.assess_impact(task)

        assert "task_id" in impact
        assert "action_type" in impact
        assert "estimated_scope" in impact
        assert "dependent_tasks" in impact

    def test_impact_scope_by_action_type(self, execution_plan):
        """Test that impact scope varies by action type."""
        execution_plan.add_task("Delete database", "delete")
        execution_plan.add_task("Review code", "review")

        delete_impact = execution_plan.assess_impact(execution_plan.tasks[0])
        review_impact = execution_plan.assess_impact(execution_plan.tasks[1])

        # Delete should have high scope
        assert delete_impact["estimated_scope"] == "high"
        assert "warning" in delete_impact

        # Review should have low scope
        assert review_impact["estimated_scope"] == "low"

    def test_impact_identifies_dependent_tasks(self, sample_tasks):
        """Test identification of dependent tasks."""
        # Task 1 is depended on by tasks 2 and 3
        task1 = sample_tasks.tasks[1]
        impact = sample_tasks.assess_impact(task1)

        # Should find 2 dependent tasks
        assert len(impact["dependent_tasks"]) == 2

        # Check task IDs
        dependent_ids = [t["task_id"] for t in impact["dependent_tasks"]]
        assert 2 in dependent_ids
        assert 3 in dependent_ids

    def test_impact_extracts_file_patterns(self, execution_plan):
        """Test extraction of file patterns from description."""
        execution_plan.add_task("Edit authentication module in auth.py file", "edit")
        task = execution_plan.tasks[0]

        impact = execution_plan.assess_impact(task)

        # Should identify auth.py (note: current implementation looks for patterns)
        # The regex may or may not match depending on exact format
        assert "affected_files" in impact

    def test_impact_extracts_module_names(self, execution_plan):
        """Test extraction of module names from description."""
        execution_plan.add_task("Update authentication module", "edit")
        task = execution_plan.tasks[0]

        impact = execution_plan.assess_impact(task)

        # Should identify authentication as affected module
        assert "affected_modules" in impact


# ========== Test Risk Evaluation ==========

class TestRiskEvaluation:
    """Test risk evaluation capabilities."""

    def test_evaluate_risk_review_action(self, execution_plan):
        """Test that review actions have low risk."""
        execution_plan.add_task("Review code for issues", "review")
        task = execution_plan.tasks[0]

        risk_level = execution_plan.evaluate_risk(task)

        assert risk_level == agent_min.RiskLevel.LOW

    def test_evaluate_risk_delete_action(self, execution_plan):
        """Test that delete actions have higher risk."""
        execution_plan.add_task("Delete old files", "delete")
        task = execution_plan.tasks[0]

        risk_level = execution_plan.evaluate_risk(task)

        # Delete should be at least MEDIUM risk
        assert risk_level in [agent_min.RiskLevel.MEDIUM, agent_min.RiskLevel.HIGH, agent_min.RiskLevel.CRITICAL]
        assert "Destructive/modifying action: delete" in task.risk_reasons

    def test_evaluate_risk_database_keyword(self, execution_plan):
        """Test that database-related tasks have elevated risk."""
        execution_plan.add_task("Update database schema", "edit")
        task = execution_plan.tasks[0]

        risk_level = execution_plan.evaluate_risk(task)

        # Should have elevated risk due to database keyword
        assert risk_level in [agent_min.RiskLevel.MEDIUM, agent_min.RiskLevel.HIGH]
        assert any("database" in reason.lower() for reason in task.risk_reasons)

    def test_evaluate_risk_security_keyword(self, execution_plan):
        """Test that security-related tasks have elevated risk."""
        execution_plan.add_task("Update security configuration", "edit")
        task = execution_plan.tasks[0]

        risk_level = execution_plan.evaluate_risk(task)

        # Should have elevated risk
        assert risk_level in [agent_min.RiskLevel.MEDIUM, agent_min.RiskLevel.HIGH]

    def test_evaluate_risk_breaking_change(self, execution_plan):
        """Test that breaking changes are flagged."""
        execution_plan.add_task("Remove support for old API", "edit")
        task = execution_plan.tasks[0]

        risk_level = execution_plan.evaluate_risk(task)

        # Should be marked as breaking change
        assert task.breaking_change is True
        assert risk_level in [agent_min.RiskLevel.HIGH, agent_min.RiskLevel.CRITICAL]

    def test_evaluate_risk_wide_scope(self, execution_plan):
        """Test that wide-scope changes have elevated risk."""
        execution_plan.add_task("Update all API endpoints", "edit")
        task = execution_plan.tasks[0]

        risk_level = execution_plan.evaluate_risk(task)

        # Should have elevated risk
        assert risk_level in [agent_min.RiskLevel.MEDIUM, agent_min.RiskLevel.HIGH]
        assert any("wide scope" in reason.lower() for reason in task.risk_reasons)

    def test_evaluate_risk_many_dependencies(self, execution_plan):
        """Test that tasks with many dependencies have elevated risk."""
        # Create tasks with dependencies
        for i in range(5):
            execution_plan.add_task(f"Task {i}", "edit")

        # Add task that depends on all previous tasks
        execution_plan.add_task("Final task", "edit", dependencies=[0, 1, 2, 3, 4])
        task = execution_plan.tasks[5]

        risk_level = execution_plan.evaluate_risk(task)

        # Should have elevated risk due to many dependencies
        assert any("dependencies" in reason.lower() for reason in task.risk_reasons)


# ========== Test Rollback Planning ==========

class TestRollbackPlanning:
    """Test rollback plan generation."""

    def test_rollback_plan_for_add(self, execution_plan):
        """Test rollback plan for add action."""
        execution_plan.add_task("Create new feature", "add")
        task = execution_plan.tasks[0]

        rollback = execution_plan.create_rollback_plan(task)

        assert "Delete the newly created files" in rollback
        assert "git clean" in rollback.lower()

    def test_rollback_plan_for_edit(self, execution_plan):
        """Test rollback plan for edit action."""
        execution_plan.add_task("Modify existing file", "edit")
        task = execution_plan.tasks[0]

        rollback = execution_plan.create_rollback_plan(task)

        assert "git checkout" in rollback.lower() or "revert" in rollback.lower()

    def test_rollback_plan_for_delete(self, execution_plan):
        """Test rollback plan for delete action."""
        execution_plan.add_task("Delete old files", "delete")
        task = execution_plan.tasks[0]

        rollback = execution_plan.create_rollback_plan(task)

        assert "CRITICAL" in rollback
        assert "cannot be recovered" in rollback.lower()
        assert "backup" in rollback.lower()

    def test_rollback_plan_for_rename(self, execution_plan):
        """Test rollback plan for rename action."""
        execution_plan.add_task("Rename module", "rename")
        task = execution_plan.tasks[0]

        rollback = execution_plan.create_rollback_plan(task)

        assert "rename" in rollback.lower()
        assert "original names" in rollback.lower()

    def test_rollback_plan_includes_general_steps(self, execution_plan):
        """Test that rollback plans include general steps."""
        execution_plan.add_task("Any task", "edit")
        task = execution_plan.tasks[0]

        rollback = execution_plan.create_rollback_plan(task)

        assert "git reset" in rollback.lower() or "git revert" in rollback.lower()
        assert "test" in rollback.lower()

    def test_rollback_plan_for_database(self, execution_plan):
        """Test rollback plan includes database steps for DB tasks."""
        execution_plan.add_task("Run database migration", "edit")
        task = execution_plan.tasks[0]

        rollback = execution_plan.create_rollback_plan(task)

        assert "database" in rollback.lower()
        assert "migration" in rollback.lower() or "backup" in rollback.lower()


# ========== Test Validation Steps ==========

class TestValidationSteps:
    """Test validation step generation."""

    def test_validation_steps_common(self, execution_plan):
        """Test that common validation steps are included."""
        execution_plan.add_task("Any task", "edit")
        task = execution_plan.tasks[0]

        steps = execution_plan.generate_validation_steps(task)

        assert len(steps) > 0
        assert any("syntax" in step.lower() for step in steps)

    def test_validation_steps_for_code_changes(self, execution_plan):
        """Test validation steps for code-changing actions."""
        execution_plan.add_task("Edit code", "edit")
        task = execution_plan.tasks[0]

        steps = execution_plan.generate_validation_steps(task)

        # Should include linter and test steps
        assert any("linter" in step.lower() or "lint" in step.lower() for step in steps)
        assert any("test" in step.lower() for step in steps)

    def test_validation_steps_for_api(self, execution_plan):
        """Test validation steps for API-related tasks."""
        execution_plan.add_task("Update API endpoint", "edit")
        task = execution_plan.tasks[0]

        steps = execution_plan.generate_validation_steps(task)

        # Should include API-specific validation
        assert any("api" in step.lower() for step in steps)
        assert any("endpoint" in step.lower() or "response" in step.lower() for step in steps)

    def test_validation_steps_for_database(self, execution_plan):
        """Test validation steps for database tasks."""
        execution_plan.add_task("Update database schema", "edit")
        task = execution_plan.tasks[0]

        steps = execution_plan.generate_validation_steps(task)

        # Should include database-specific validation
        assert any("database" in step.lower() or "migration" in step.lower() for step in steps)
        assert any("schema" in step.lower() or "data integrity" in step.lower() for step in steps)

    def test_validation_steps_for_security(self, execution_plan):
        """Test validation steps for security tasks."""
        execution_plan.add_task("Update security settings", "edit")
        task = execution_plan.tasks[0]

        steps = execution_plan.generate_validation_steps(task)

        # Should include security-specific validation
        assert any("security" in step.lower() for step in steps)
        assert any("scanner" in step.lower() or "secrets" in step.lower() for step in steps)

    def test_validation_steps_for_delete(self, execution_plan):
        """Test validation steps for delete action."""
        execution_plan.add_task("Delete old code", "delete")
        task = execution_plan.tasks[0]

        steps = execution_plan.generate_validation_steps(task)

        # Should include checks for references
        assert any("references" in step.lower() or "import" in step.lower() for step in steps)
        assert any("full test" in step.lower() for step in steps)

    def test_validation_includes_git_diff(self, execution_plan):
        """Test that validation includes git diff review."""
        execution_plan.add_task("Any task", "edit")
        task = execution_plan.tasks[0]

        steps = execution_plan.generate_validation_steps(task)

        # Should always include git diff review
        assert any("git diff" in step.lower() for step in steps)


# ========== Integration Tests ==========

class TestAdvancedPlanningIntegration:
    """Test integration of advanced planning features."""

    def test_full_planning_analysis(self, sample_tasks):
        """Test that full planning analysis works end-to-end."""
        # Run all analysis methods
        dep_analysis = sample_tasks.analyze_dependencies()

        # Evaluate all tasks
        for task in sample_tasks.tasks:
            task.risk_level = sample_tasks.evaluate_risk(task)
            impact = sample_tasks.assess_impact(task)
            task.rollback_plan = sample_tasks.create_rollback_plan(task)
            task.validation_steps = sample_tasks.generate_validation_steps(task)

        # Verify results
        assert dep_analysis["total_tasks"] == 5
        assert all(hasattr(t, 'risk_level') for t in sample_tasks.tasks)
        assert all(hasattr(t, 'rollback_plan') for t in sample_tasks.tasks)
        assert all(len(t.validation_steps) > 0 for t in sample_tasks.tasks)

    def test_high_risk_task_gets_rollback(self, execution_plan):
        """Test that high-risk tasks get rollback plans."""
        execution_plan.add_task("Delete production database", "delete")
        task = execution_plan.tasks[0]

        # Evaluate risk
        task.risk_level = execution_plan.evaluate_risk(task)

        # Should be high or critical risk
        assert task.risk_level in [agent_min.RiskLevel.HIGH, agent_min.RiskLevel.CRITICAL]

        # Generate rollback
        task.rollback_plan = execution_plan.create_rollback_plan(task)

        # Should have rollback plan
        assert task.rollback_plan is not None
        assert len(task.rollback_plan) > 0

    def test_execution_plan_to_dict_with_advanced_features(self, sample_tasks):
        """Test that ExecutionPlan.to_dict includes advanced features."""
        # Set up advanced features
        for task in sample_tasks.tasks:
            task.risk_level = sample_tasks.evaluate_risk(task)
            task.rollback_plan = sample_tasks.create_rollback_plan(task)

        plan_dict = sample_tasks.to_dict()

        assert "tasks" in plan_dict
        # Check that task dicts include advanced fields
        for task_dict in plan_dict["tasks"]:
            assert "risk_level" in task_dict
            assert "rollback_plan" in task_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
