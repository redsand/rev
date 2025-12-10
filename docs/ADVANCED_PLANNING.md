# Advanced Planning Capabilities

rev now includes sophisticated planning capabilities that go beyond simple task generation. These features help predict impact, assess risk, and prepare for potential issues before execution begins.

## Overview

The advanced planning system analyzes tasks across four key dimensions:

1. **Dependency Analysis** - Understands task relationships and optimal execution order
2. **Impact Assessment** - Predicts the scope of changes before making them
3. **Risk Evaluation** - Identifies potentially dangerous operations
4. **Rollback Planning** - Prepares recovery procedures for high-risk tasks

## Features

### 1. Dependency Analysis

Automatically analyzes task dependencies to determine:

- **Dependency Graph**: Complete mapping of which tasks depend on others
- **Root Tasks**: Tasks that can start immediately (no dependencies)
- **Critical Path**: Longest chain of dependencies
- **Parallel Opportunities**: Tasks that can run concurrently
- **Reverse Dependencies**: Which tasks are blocked by each task

**Example Output:**
```
→ Performing advanced planning analysis...
  ├─ Analyzing task dependencies...

⚡ Parallelization potential: 4 tasks can run concurrently
   Critical path length: 5 steps
```

**Benefits:**
- Optimal task ordering for faster execution
- Identifies parallel execution opportunities
- Prevents dependency deadlocks
- Highlights critical path bottlenecks

### 2. Impact Assessment

Evaluates the potential scope and reach of each task:

- **Affected Files**: Files that will be modified
- **Affected Modules**: Components/modules impacted
- **Dependent Tasks**: Tasks that rely on this task
- **Estimated Scope**: Low/Medium/High impact rating

**Impact Scoring:**
- **Low**: Review, test actions - no code changes
- **Medium**: Edit, add actions - localized changes
- **High**: Delete, rename - widespread impact

**Example:**
```python
impact = {
    "task_id": 3,
    "action_type": "delete",
    "estimated_scope": "high",
    "warning": "Destructive operation - data loss possible",
    "affected_files": ["old_auth.py"],
    "dependent_tasks": [4, 5]
}
```

**Benefits:**
- Understand change scope before execution
- Identify potentially impacted areas
- Plan testing coverage accordingly
- Warn about destructive operations

### 3. Risk Evaluation

Automatically evaluates risk level for each task using multiple factors:

#### Risk Levels

- 🟢 **LOW**: Safe operations with minimal risk
- 🟡 **MEDIUM**: Moderate risk requiring attention
- 🟠 **HIGH**: Significant risk requiring caution
- 🔴 **CRITICAL**: Dangerous operations requiring extreme care

#### Risk Factors

1. **Action Type Risk**
   - Delete: High risk (data loss)
   - Edit: Medium risk (breaking changes)
   - Rename: Medium risk (broken references)
   - Add: Low risk (new code)
   - Review/Test: Minimal risk

2. **Component Keywords**
   - Database, schema, migration
   - Production, deploy
   - Authentication, security, password
   - Configuration, settings

3. **Scope Indicators**
   - "all", "entire", "whole", "every"
   - Wide-reaching changes increase risk

4. **Breaking Changes**
   - "breaking", "incompatible"
   - "remove support", "deprecate"

5. **Dependency Complexity**
   - Tasks with >3 dependencies have elevated risk

**Example Output:**
```
1. [DELETE] Remove deprecated authentication module
   Risk: 🔴 CRITICAL (Destructive/modifying action: delete, High-risk component: auth)
   ⚠️  Warning: Potentially breaking change

2. [EDIT] Add error handling to API endpoints
   Risk: 🟡 MEDIUM (Destructive/modifying action: edit)

3. [TEST] Run test suite
   Risk: 🟢 LOW
```

**Benefits:**
- Early warning for dangerous operations
- Prioritize review for high-risk tasks
- Justify additional testing/validation
- Enable risk-based approval workflows

### 4. Rollback Planning

Automatically generates rollback procedures for each task, especially high-risk ones:

#### Action-Specific Rollback

**For ADD tasks:**
```
- Delete the newly created files
- Run: git clean -fd (after review)
```

**For EDIT tasks:**
```
- Revert changes using: git checkout -- <files>
- Or apply inverse patch
```

**For DELETE tasks:**
```
⚠️  CRITICAL: Deleted files cannot be recovered without backup
- Restore from git history: git checkout HEAD~1 -- <files>
- Or restore from backup if available
```

**For RENAME tasks:**
```
- Rename files back to original names
- Update imports and references
```

#### General Rollback Steps

All tasks include general recovery procedures:
```
1. Stop any running services
2. Revert code changes: git reset --hard HEAD
3. If changes were committed: git revert <commit-hash>
4. Run tests to verify rollback: pytest / npm test
5. Review logs for any issues
```

#### Database-Specific Rollback

For tasks involving databases:
```
1. Run down migration: alembic downgrade -1
2. Or restore from database backup
3. Verify data integrity
```

**Benefits:**
- Prepared recovery procedures before issues arise
- Reduces downtime in case of problems
- Confidence to attempt high-risk operations
- Documentation for incident response

### 5. Validation Steps

Each task gets customized validation steps based on its characteristics:

#### Common Validations
- Check for syntax errors
- Review git diff for unintended changes

#### Code Change Validations
- Run linter to check code quality
- Verify imports and dependencies
- Run test suite

#### API-Specific Validations
- Test API endpoints manually or with integration tests
- Verify response formats and status codes

#### Database-Specific Validations
- Run database migrations
- Verify schema changes
- Check data integrity

#### Security-Specific Validations
- Run security scanner (bandit / npm audit)
- Check for exposed secrets

#### Delete-Specific Validations
- Verify no references to deleted code remain
- Check import statements
- Run full test suite

**Example:**
```
Task: Update database schema

Validation Steps:
1. Check for syntax errors
2. Run linter to check code quality
3. Verify imports and dependencies
4. Run test suite: pytest / npm test
5. Check for failing tests
6. Run database migrations
7. Verify schema changes
8. Check data integrity
9. Review git diff for unintended changes
```

**Benefits:**
- Comprehensive testing guidance
- Ensures nothing is forgotten
- Customized to task characteristics
- Reduces risk of incomplete validation

## Usage

### Automatic Analysis

By default, advanced planning is enabled automatically:

```bash
rev "Refactor authentication system"
```

### Planning Output

```
============================================================
PLANNING MODE
============================================================
→ Analyzing system and repository...
→ Generating execution plan...

→ Performing advanced planning analysis...
  ├─ Analyzing task dependencies...
  ├─ Evaluating risks...
  ├─ Assessing impact scope...
  ├─ Creating rollback plans...
  └─ Generating validation steps...

============================================================
EXECUTION PLAN
============================================================
1. [REVIEW] Analyze current authentication module structure
   Risk: 🟢 LOW

2. [EDIT] Extract authentication logic into AuthService
   Risk: 🟡 MEDIUM (Destructive/modifying action: edit, High-risk component: auth)
   Depends on: #1

3. [ADD] Create comprehensive tests for AuthService
   Risk: 🟢 LOW
   Depends on: #2

4. [DELETE] Remove old authentication helper functions
   Risk: 🟠 HIGH (Destructive/modifying action: delete, High-risk component: auth)
   Depends on: #2
   ⚠️  Warning: Potentially breaking change

5. [TEST] Run full test suite to verify refactoring
   Risk: 🟢 LOW
   Depends on: #3, #4

============================================================
PLANNING ANALYSIS SUMMARY
============================================================
Total tasks: 5
Risk distribution:
  🟢 LOW: 3
  🟡 MEDIUM: 1
  🟠 HIGH: 1

⚡ Parallelization potential: 2 tasks can run concurrently
   Critical path length: 4 steps

🟠 WARNING: 1 task(s) have elevated risk

============================================================
```

## Technical Details

### Dependency Analysis Algorithm

The dependency analyzer:

1. **Builds dependency graph** from task dependencies
2. **Creates reverse mapping** to find what depends on each task
3. **Identifies root tasks** with no dependencies
4. **Calculates depth** for each task (longest path from root)
5. **Groups tasks by depth** to find parallelization opportunities
6. **Computes critical path** (longest dependency chain)

```python
# Example usage
plan = ExecutionPlan()
# ... add tasks ...

analysis = plan.analyze_dependencies()

print(f"Root tasks: {analysis['root_tasks']}")
print(f"Critical path: {analysis['critical_path_length']} steps")
print(f"Parallel potential: {analysis['parallelization_potential']} tasks")
```

### Risk Scoring System

Risk is calculated using a point-based system:

| Factor | Points |
|--------|--------|
| Action type: delete | +3 |
| Action type: edit/rename | +2 |
| Action type: add | +1 |
| High-risk keyword (database, auth, security, etc.) | +1 |
| Wide scope (all, entire, whole) | +1 |
| Breaking change indicator | +2 |
| Many dependencies (>3) | +1 |

**Risk Level Mapping:**
- 0 points: LOW
- 1-2 points: MEDIUM
- 3-4 points: HIGH
- 5+ points: CRITICAL

```python
# Example
task = plan.tasks[0]
risk_level = plan.evaluate_risk(task)
print(f"Risk: {risk_level.value}")
print(f"Reasons: {task.risk_reasons}")
```

### Impact Assessment Process

Impact assessment examines:

1. **Action type** → Determines base scope
2. **Task description** → Extracts file and module patterns
3. **Dependency relationships** → Finds dependent tasks
4. **Keywords** → Identifies special concerns

```python
impact = plan.assess_impact(task)

# Impact includes:
# - estimated_scope: "low" | "medium" | "high"
# - affected_files: ["auth.py", "user.py"]
# - affected_modules: ["authentication", "user"]
# - dependent_tasks: [{task_id: 2, description: "..."}, ...]
```

## Integration with Execution

### Pre-Execution Warnings

High-risk tasks trigger additional warnings during execution approval:

```
🔴 CRITICAL: 1 high-risk task(s) require extra caution
   - Task #4: Remove deprecated authentication module...
     Rollback plan available
```

### Execution Monitoring

During execution, the system can:

1. **Pause before high-risk tasks** for manual review
2. **Show rollback plan** before destructive operations
3. **Validate completion** using generated validation steps
4. **Track dependency completion** before allowing dependent tasks

### Post-Execution Analysis

After execution:

- Failed high-risk tasks → Show rollback plan
- Track which validations were performed
- Report on actual vs. estimated impact

## API Reference

### ExecutionPlan Methods

```python
# Dependency Analysis
analysis = plan.analyze_dependencies()
# Returns: Dict with dependency_graph, root_tasks, critical_path_length, etc.

# Impact Assessment
impact = plan.assess_impact(task)
# Returns: Dict with estimated_scope, affected_files, dependent_tasks, etc.

# Risk Evaluation
risk_level = plan.evaluate_risk(task)
# Returns: RiskLevel enum (LOW, MEDIUM, HIGH, CRITICAL)
# Side effect: Sets task.risk_level and task.risk_reasons

# Rollback Planning
rollback_plan = plan.create_rollback_plan(task)
# Returns: String with rollback instructions

# Validation Steps
validation_steps = plan.generate_validation_steps(task)
# Returns: List[str] of validation steps
```

### Task Attributes

```python
task = plan.tasks[0]

# Risk attributes
task.risk_level          # RiskLevel enum
task.risk_reasons        # List[str] explaining risk level
task.breaking_change     # bool

# Impact attributes
task.impact_scope        # List[str] of affected files/modules
task.estimated_changes   # int

# Recovery attributes
task.rollback_plan       # str with rollback instructions
task.validation_steps    # List[str] of validation steps
```

## Best Practices

### 1. Review High-Risk Tasks

Always manually review tasks marked HIGH or CRITICAL:

```bash
# Look for 🟠 or 🔴 in the plan output
# Review the risk reasons
# Check the rollback plan before proceeding
```

### 2. Test Rollback Procedures

For critical operations, test rollback in a safe environment first:

```bash
# Create a test branch
git checkout -b test-rollback

# Run the operation
rev "Delete production database schema"

# Practice the rollback
# Follow the generated rollback plan
```

### 3. Validate Thoroughly

Follow all generated validation steps, especially for high-risk tasks:

```python
# After task completion, check:
for step in task.validation_steps:
    print(f"[ ] {step}")
```

### 4. Leverage Parallelization

Use the parallel execution mode for tasks that can run concurrently:

```bash
# Use -j flag with the parallelization potential
rev -j 4 "Refactor all modules"
```

### 5. Document Risk Decisions

For high-risk tasks you choose to proceed with:
- Document why the risk is acceptable
- Ensure backups are current
- Have rollback plan ready
- Test validation procedures

## Limitations

### Current Limitations

1. **Pattern-Based Analysis**: Impact and risk are estimated from task descriptions, not by analyzing actual code
2. **No Code Simulation**: Cannot predict exact behavior without execution
3. **Heuristic Risk Scoring**: Risk scores are rule-based, not learned from outcomes
4. **Limited Context**: Cannot assess risk based on production state or historical data

### Future Enhancements

Planned improvements include:

1. **Static Code Analysis Integration**: Analyze actual files to predict impact
2. **Historical Risk Learning**: Learn from past successes/failures
3. **Code Simulation**: Dry-run changes to predict behavior
4. **Production State Awareness**: Factor in production metrics
5. **Custom Risk Rules**: User-defined risk factors per project
6. **Interactive Risk Adjustment**: Allow manual risk level overrides
7. **Automated Backup Creation**: Create backups before high-risk operations

## Troubleshooting

### Issue: All tasks marked LOW risk

**Problem**: Risk evaluation not working properly

**Solution**: Check task descriptions include relevant keywords:
```python
# Instead of: "Update file"
# Use: "Update database schema in auth module"
```

### Issue: No parallelization potential

**Problem**: Dependency analysis shows 0 parallel tasks

**Solution**: Review task dependencies. Reduce unnecessary dependencies:
```python
# Bad: Each task depends on previous
tasks = [0] -> [1] -> [2] -> [3]

# Good: Independent tasks at each level
     [0]
    /   \
  [1]   [2]
    \   /
     [3]
```

### Issue: Rollback plan too generic

**Problem**: Need more specific rollback instructions

**Solution**: Make task descriptions more specific:
```python
# Instead of: "Make changes"
# Use: "Modify auth.py and user.py to add rate limiting"
```

## Examples

See `/examples/scenarios/` for real-world examples using advanced planning:

- **[Refactoring](../examples/scenarios/refactoring.md)** - High-risk code refactoring
- **[Feature Development](../examples/scenarios/feature-development.md)** - Impact assessment
- **[Bug Fixing](../examples/scenarios/bug-fixing.md)** - Risk evaluation

## Contributing

To enhance the advanced planning system:

1. Add risk factors in `evaluate_risk()`
2. Improve pattern matching in `assess_impact()`
3. Expand rollback scenarios in `create_rollback_plan()`
4. Add validation patterns in `generate_validation_steps()`
5. Test with real-world scenarios

## License

Same as rev - MIT License
