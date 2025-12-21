# Implementation Plan: MACI-Inspired Features for Rev

**Date:** 2025-12-20
**Status:** Planning Phase
**Goal:** Implement 4 major features to prevent incomplete work, improve verification rigor, enable safe rollback, and add Socratic validation

---

## Executive Summary

Based on the MACI paper's multi-agent coordination principles and current rev issues (incomplete tasks, broken state), we need:

1. **Definition of Done (DoD)** - Contract-based task completion gates
2. **Multi-stage Verification** - Layered validation catching subtle breakage
3. **Transactional Execution** - Atomic operations with automatic rollback
4. **CRIT Judge** - Socratic filter for plans, claims, and merges

---

## Feature 1: Definition of Done (DoD) Contract

### Problem
Tasks are marked "completed" when they're not operational:
- Tests pass locally but fail in CI
- Code compiles but has runtime errors
- Changes work in isolation but break integration

### Solution: Hard DoD Gate

Each task **must** output a structured DoD spec before execution. Verification **must** satisfy all DoD criteria or the task fails.

### Architecture

```
Task Creation → DoD Generation → Execute → Verify Against DoD → [PASS/FAIL]
                    ↓                                    ↓
              (stored in task)                   (hard gate - blocks completion)
```

### DoD Specification Format (YAML)

```yaml
task_id: T-2025-12-20-001
description: "Fix analyst auto-registration in main.py"
deliverables:
  - type: file_modified
    path: main.py
    lines_changed: 10-50

  - type: syntax_valid
    files: [main.py]

  - type: test_pass
    command: pytest tests/test_analyst_registry.py -v

  - type: runtime_check
    command: python main.py --help
    expect: "exit_code == 0"

acceptance_criteria:
  - "pytest exit code == 0"
  - "no F821 errors in modified code"
  - "auto-registration count == 34"
  - "no 'Verification failed' in run log"

validation_stages:
  - compile
  - unit_test
  - integration_check
```

### Implementation Steps

#### 1.1: Create DoD Model (`rev/models/dod.py`)
```python
from dataclasses import dataclass
from typing import List, Dict, Any
from enum import Enum

class DeliverableType(Enum):
    FILE_MODIFIED = "file_modified"
    FILE_CREATED = "file_created"
    TEST_PASS = "test_pass"
    SYNTAX_VALID = "syntax_valid"
    RUNTIME_CHECK = "runtime_check"
    IMPORTS_WORK = "imports_work"

@dataclass
class Deliverable:
    type: DeliverableType
    path: str = None
    command: str = None
    expect: str = None

@dataclass
class DefinitionOfDone:
    task_id: str
    description: str
    deliverables: List[Deliverable]
    acceptance_criteria: List[str]
    validation_stages: List[str]

    def to_yaml(self) -> str:
        """Serialize to YAML for storage"""
        pass

    @staticmethod
    def from_yaml(yaml_str: str) -> "DefinitionOfDone":
        """Deserialize from YAML"""
        pass
```

#### 1.2: DoD Generator Agent (`rev/agents/dod_generator.py`)
```python
def generate_dod(task: Task, user_request: str) -> DefinitionOfDone:
    """
    Uses LLM to generate a DoD spec based on the task description.

    Prompt:
    - Analyze the user request
    - Identify concrete deliverables
    - Define acceptance criteria
    - Specify validation stages
    """
    prompt = f"""
    User Request: {user_request}
    Task: {task.description}

    Generate a Definition of Done with:
    1. Deliverables (files to modify/create, tests to pass)
    2. Acceptance criteria (concrete pass/fail conditions)
    3. Validation stages required

    Output as YAML following the schema...
    """
    # Call LLM, parse YAML, return DoD object
```

#### 1.3: DoD Verification (`rev/execution/dod_verifier.py`)
```python
def verify_dod(dod: DefinitionOfDone, task: Task, context: ExecutionContext) -> DoDVerificationResult:
    """
    Hard gate: Verify all DoD criteria are satisfied.

    Returns:
    - passed: bool
    - unmet_criteria: List[str]
    - details: Dict[str, Any]
    """
    results = []

    for deliverable in dod.deliverables:
        if deliverable.type == DeliverableType.FILE_MODIFIED:
            # Check file was actually modified
            result = check_file_modified(deliverable.path, task.tool_events)
            results.append(result)

        elif deliverable.type == DeliverableType.TEST_PASS:
            # Run the test command
            result = run_command(deliverable.command, deliverable.expect)
            results.append(result)

    # Check acceptance criteria
    for criterion in dod.acceptance_criteria:
        result = evaluate_criterion(criterion, context)
        results.append(result)

    return DoDVerificationResult(
        passed=all(r.passed for r in results),
        unmet_criteria=[r.criterion for r in results if not r.passed],
        details=results
    )
```

#### 1.4: Integration with Orchestrator
```python
# In orchestrator.py _continuous_sub_agent_execution():

# BEFORE task execution:
dod = generate_dod(next_task, user_request)
next_task.dod = dod
print(f"[DoD] Generated DoD with {len(dod.deliverables)} deliverables")

# AFTER task execution:
dod_result = verify_dod(next_task.dod, next_task, self.context)
if not dod_result.passed:
    print(f"[DoD] FAILED - Unmet criteria: {dod_result.unmet_criteria}")
    next_task.status = TaskStatus.FAILED
    next_task.error = f"DoD verification failed: {dod_result.unmet_criteria}"
    continue  # Retry or decompose
```

### Testing Plan

```python
# tests/test_dod.py

def test_dod_generator_creates_valid_spec():
    task = Task(description="Fix analyst auto-registration")
    dod = generate_dod(task, "analysts should auto-register")

    assert dod.deliverables
    assert dod.acceptance_criteria
    assert "test_pass" in [d.type for d in dod.deliverables]

def test_dod_verifier_passes_when_criteria_met():
    dod = DefinitionOfDone(
        task_id="T-001",
        deliverables=[
            Deliverable(type=DeliverableType.FILE_MODIFIED, path="main.py")
        ],
        acceptance_criteria=["main.py modified"]
    )
    task = create_task_with_file_modification("main.py")
    result = verify_dod(dod, task, context)

    assert result.passed

def test_dod_verifier_fails_when_criteria_unmet():
    dod = DefinitionOfDone(
        acceptance_criteria=["pytest exit code == 0"]
    )
    task = create_task_with_failing_tests()
    result = verify_dod(dod, task, context)

    assert not result.passed
    assert "pytest exit code" in result.unmet_criteria[0]
```

---

## Feature 2: Multi-Stage Verification

### Problem
Single-stage verification (`ruff check`) misses:
- Runtime errors (code compiles but crashes)
- Integration issues (module works alone but breaks when imported)
- Behavioral bugs (logic is wrong but syntax is correct)

### Solution: Layered Verification Pipeline

```
Stage 1: SYNTAX     → compileall, ruff E9
Stage 2: UNIT       → pytest unit tests
Stage 3: INTEGRATION → import checks, smoke tests
Stage 4: BEHAVIORAL  → end-to-end validation
```

### Architecture

```python
# rev/execution/verification_pipeline.py

class VerificationStage(Enum):
    SYNTAX = "syntax"
    UNIT = "unit"
    INTEGRATION = "integration"
    BEHAVIORAL = "behavioral"

class VerificationPipeline:
    def __init__(self, stages: List[VerificationStage]):
        self.stages = stages

    def run(self, task: Task, context: ExecutionContext) -> PipelineResult:
        results = {}
        for stage in self.stages:
            result = self._run_stage(stage, task, context)
            results[stage] = result

            if not result.passed:
                # Early exit on first failure
                return PipelineResult(
                    passed=False,
                    failed_stage=stage,
                    details=results
                )

        return PipelineResult(passed=True, details=results)

    def _run_stage(self, stage: VerificationStage, task: Task, context: ExecutionContext):
        if stage == VerificationStage.SYNTAX:
            return self._verify_syntax(task)
        elif stage == VerificationStage.UNIT:
            return self._verify_unit_tests(task)
        elif stage == VerificationStage.INTEGRATION:
            return self._verify_integration(task)
        elif stage == VerificationStage.BEHAVIORAL:
            return self._verify_behavioral(task)
```

### Stage Definitions

#### Stage 1: SYNTAX
```python
def _verify_syntax(self, task: Task) -> StageResult:
    """
    - compileall (Python syntax)
    - ruff --select E9 (syntax errors only)
    """
    checks = [
        ("compileall", "python -m compileall {files}"),
        ("ruff_syntax", "ruff check {files} --select E9")
    ]
    return run_checks(checks)
```

#### Stage 2: UNIT
```python
def _verify_unit_tests(self, task: Task) -> StageResult:
    """
    - pytest -q (all unit tests)
    - pytest -k modified_function (targeted tests)
    """
    # Extract affected functions from task
    affected = extract_affected_code(task)

    checks = [
        ("pytest_all", "pytest -q"),
        ("pytest_targeted", f"pytest -k {affected} -v")
    ]
    return run_checks(checks)
```

#### Stage 3: INTEGRATION
```python
def _verify_integration(self, task: Task) -> StageResult:
    """
    - Import check: python -c "import modified_module"
    - Smoke test: Run a simple operation
    - Cross-module check: Verify dependents still work
    """
    modified_files = extract_modified_files(task)
    checks = []

    for file in modified_files:
        module = file_to_module(file)
        checks.append((
            f"import_{module}",
            f"python -c 'import {module}'"
        ))

    return run_checks(checks)
```

#### Stage 4: BEHAVIORAL
```python
def _verify_behavioral(self, task: Task) -> StageResult:
    """
    - End-to-end test: Run the actual workflow
    - Output validation: Check expected behavior
    """
    # Example: For analyst registration task
    if "auto-register" in task.description.lower():
        checks = [
            ("registration_count", "python main.py --check-analysts"),
            ("expected_count", "assert count == 34")
        ]

    return run_checks(checks)
```

### Risk-Based Stage Selection

```python
def select_stages_for_task(task: Task, dod: DefinitionOfDone) -> List[VerificationStage]:
    """
    Select verification stages based on risk assessment.

    Risk factors:
    - Change type (docs < code < infra)
    - Scope (single file < multi-file < architecture)
    - Test coverage (high coverage = fewer stages needed)
    """
    stages = [VerificationStage.SYNTAX]  # Always check syntax

    if task.action_type in ["edit", "refactor", "create"]:
        stages.append(VerificationStage.UNIT)

    if is_multi_file_change(task):
        stages.append(VerificationStage.INTEGRATION)

    if is_critical_path(task) or "tool" in task.description:
        stages.append(VerificationStage.BEHAVIORAL)

    return stages
```

### Integration with DoD

```python
# DoD spec includes required stages:
validation_stages:
  - syntax
  - unit
  - integration

# Verification pipeline uses DoD stages:
pipeline = VerificationPipeline(stages=dod.validation_stages)
result = pipeline.run(task, context)
```

---

## Feature 3: Transactional Execution + Rollback

### Problem
Agent makes changes → verification fails → repo is in broken state:
- Files partially modified
- Tests broken
- Manual cleanup required

### Solution: MACI Transactional Memory Pattern

```
BEGIN TX → Execute Tools → [PASS] → COMMIT
                         ↓
                      [FAIL] → ROLLBACK
```

### Architecture

```python
# rev/execution/transaction.py

class Transaction:
    def __init__(self, tx_id: str, task: Task):
        self.tx_id = tx_id
        self.task = task
        self.actions: List[TransactionAction] = []
        self.status = TransactionStatus.PENDING
        self.rollback_plan: Optional[RollbackPlan] = None

    def record_action(self, tool_name: str, args: Dict, result: Any):
        """Record a tool execution as part of this transaction"""
        action = TransactionAction(
            tool=tool_name,
            args=args,
            result=result,
            timestamp=datetime.now()
        )

        # Capture pre-state for rollback
        if tool_name in ["apply_patch", "replace_in_file", "write_file"]:
            file_path = args.get("path") or args.get("file_path")
            if file_path and Path(file_path).exists():
                action.pre_state = {
                    "hash": compute_file_hash(file_path),
                    "content": Path(file_path).read_text()
                }

        self.actions.append(action)

    def commit(self) -> bool:
        """Mark transaction as committed (changes are permanent)"""
        self.status = TransactionStatus.COMMITTED
        self.write_to_log()
        return True

    def rollback(self) -> bool:
        """Revert all changes made in this transaction"""
        print(f"[TX] Rolling back transaction {self.tx_id}")

        # Reverse order (last action first)
        for action in reversed(self.actions):
            success = self._rollback_action(action)
            if not success:
                print(f"[TX] WARNING: Failed to rollback {action.tool}")
                return False

        self.status = TransactionStatus.ROLLED_BACK
        self.write_to_log()
        return True

    def _rollback_action(self, action: TransactionAction) -> bool:
        """Rollback a single action"""
        if action.tool in ["apply_patch", "replace_in_file", "write_file"]:
            file_path = action.args.get("path") or action.args.get("file_path")
            if action.pre_state and "content" in action.pre_state:
                # Restore original content
                Path(file_path).write_text(action.pre_state["content"])
                print(f"[TX] Restored {file_path}")
                return True

        elif action.tool == "run_cmd":
            # Commands can't be rolled back - mark as warning
            print(f"[TX] Cannot rollback command: {action.args.get('cmd')}")
            return True  # Don't fail the entire rollback

        return True
```

### Transaction Manager

```python
# rev/execution/transaction_manager.py

class TransactionManager:
    def __init__(self):
        self.current_tx: Optional[Transaction] = None
        self.tx_log_path = config.LOGS_DIR / "transactions.jsonl"

    def begin_transaction(self, task: Task) -> Transaction:
        """Start a new transaction for a task"""
        tx_id = f"tx_{uuid.uuid4().hex[:8]}"
        self.current_tx = Transaction(tx_id, task)
        print(f"[TX] BEGIN {tx_id} for task: {task.description[:50]}")
        return self.current_tx

    def commit_current(self) -> bool:
        """Commit the current transaction"""
        if not self.current_tx:
            return False

        success = self.current_tx.commit()
        print(f"[TX] COMMIT {self.current_tx.tx_id}")
        self.current_tx = None
        return success

    def rollback_current(self) -> bool:
        """Rollback the current transaction"""
        if not self.current_tx:
            return False

        success = self.current_tx.rollback()
        print(f"[TX] ROLLBACK {self.current_tx.tx_id}")
        self.current_tx = None
        return success

    def record_tool_execution(self, tool_name: str, args: Dict, result: Any):
        """Record a tool execution in the current transaction"""
        if self.current_tx:
            self.current_tx.record_action(tool_name, args, result)
```

### Integration with Orchestrator

```python
# In orchestrator.py:

class Orchestrator:
    def __init__(self):
        self.tx_manager = TransactionManager()

    def _continuous_sub_agent_execution(self, user_request, coding_mode):
        # ... existing code ...

        for iteration in range(max_iterations):
            # BEGIN TRANSACTION
            tx = self.tx_manager.begin_transaction(next_task)

            try:
                # Execute task (tools are intercepted and recorded)
                result = self._execute_task(next_task)

                # Verify
                verification = verify_task_execution(next_task, self.context)

                if verification.passed:
                    # COMMIT
                    self.tx_manager.commit_current()
                    next_task.status = TaskStatus.COMPLETED
                else:
                    # ROLLBACK
                    print(f"[TX] Verification failed - rolling back changes")
                    self.tx_manager.rollback_current()
                    next_task.status = TaskStatus.FAILED

            except Exception as e:
                # ROLLBACK on exception
                print(f"[TX] Exception during execution - rolling back")
                self.tx_manager.rollback_current()
                raise
```

### Tool Interception

```python
# rev/tools/registry.py

def execute_tool(tool_name: str, args: Dict) -> Any:
    """Execute a tool and record in transaction if active"""
    # Get transaction manager from context
    tx_manager = get_transaction_manager()

    # Execute the actual tool
    result = _actual_execute_tool(tool_name, args)

    # Record in transaction
    if tx_manager and tx_manager.current_tx:
        tx_manager.record_tool_execution(tool_name, args, result)

    return result
```

### Transaction Log Format (JSONL)

```json
{
  "tx_id": "tx_9f3c4a21",
  "task_id": "T-2025-12-20-001",
  "task_description": "Fix analyst auto-registration",
  "timestamp_start": "2025-12-20T17:10:45Z",
  "timestamp_end": "2025-12-20T17:11:30Z",
  "status": "rolled_back",
  "actions": [
    {
      "tool": "replace_in_file",
      "args": {"path": "main.py", "find": "...", "replace": "..."},
      "result": {"replaced": 1},
      "pre_state": {"hash": "abc123", "content": "original content"},
      "timestamp": "2025-12-20T17:10:50Z"
    },
    {
      "tool": "run_cmd",
      "args": {"cmd": "pytest -q"},
      "result": {"rc": 1, "stdout": "FAILED"},
      "timestamp": "2025-12-20T17:11:20Z"
    }
  ],
  "rollback": {
    "reason": "Verification failed: pytest errors",
    "files_restored": ["main.py"],
    "timestamp": "2025-12-20T17:11:30Z"
  }
}
```

---

## Feature 4: CRIT - Socratic Judge Gate

### Problem
Plans and claims are accepted without critical review:
- Plan looks good but has logic flaws
- Agent claims "task complete" but evidence is weak
- Merge decision made without considering trade-offs

### Solution: CRIT Judge Agent

CRIT = **C**ritical **R**eview & **I**nterrogation **T**ool

A specialized agent that:
1. **Challenges plans** before execution
2. **Questions claims** before acceptance
3. **Debates merges** before committing

Based on MACI principle: "Debate alone isn't enough—CRIT filters out weak reasoning"

### Architecture

```python
# rev/agents/crit_judge.py

class CRITJudge:
    """
    Socratic judge that critically evaluates plans, claims, and decisions.

    Uses adversarial prompting to find flaws before they become problems.
    """

    def evaluate_plan(self, plan: ExecutionPlan, context: ExecutionContext) -> CRITResult:
        """
        Challenge the plan with Socratic questions:
        - What assumptions are you making?
        - What could go wrong?
        - Have you considered alternative approaches?
        - How will you verify this worked?
        """
        prompt = f"""
        ROLE: You are a critical reviewer. Your job is to find flaws in plans BEFORE execution.

        PLAN:
        {plan.to_text()}

        CHALLENGE THIS PLAN:
        1. What assumptions is this plan making that might be wrong?
        2. What edge cases or failure modes are not addressed?
        3. How will we know if this plan actually achieved the goal?
        4. Are there simpler or safer alternatives?
        5. What could go wrong during execution?

        OUTPUT:
        - concerns: List[str] - Critical issues that MUST be addressed
        - warnings: List[str] - Potential problems to monitor
        - alternatives: List[str] - Other approaches to consider
        - verdict: APPROVE | REVISE | REJECT
        """

        response = ollama_chat([{"role": "user", "content": prompt}])
        return self._parse_crit_response(response)

    def evaluate_claim(self, claim: str, evidence: Dict, task: Task) -> CRITResult:
        """
        Question completion claims:
        - Is the evidence sufficient?
        - Are there gaps in verification?
        - Does the claim match the actual results?
        """
        prompt = f"""
        ROLE: Verify completion claims with skepticism.

        CLAIM: {claim}

        EVIDENCE:
        {json.dumps(evidence, indent=2)}

        TASK GOAL: {task.description}

        INTERROGATE THIS CLAIM:
        1. Does the evidence actually prove the claim?
        2. What verification steps are missing?
        3. Are there any red flags or inconsistencies?
        4. Could this "success" actually be a partial failure?

        OUTPUT:
        - gaps: List[str] - Missing evidence
        - red_flags: List[str] - Concerning patterns
        - verdict: ACCEPT | NEEDS_MORE_EVIDENCE | REJECT
        """

        response = ollama_chat([{"role": "user", "content": prompt}])
        return self._parse_crit_response(response)

    def evaluate_merge(self, changes: List[str], context: ExecutionContext) -> CRITResult:
        """
        Debate merge decisions:
        - Are changes safe to commit?
        - Have all tests passed?
        - Are there unintended side effects?
        """
        prompt = f"""
        ROLE: Gatekeeper for code merges. Block unsafe changes.

        CHANGES:
        {chr(10).join(changes)}

        EVALUATE FOR MERGE:
        1. Do all verification stages pass?
        2. Are there any breaking changes?
        3. Is test coverage adequate?
        4. Are there any security concerns?
        5. Will this affect other parts of the system?

        OUTPUT:
        - blockers: List[str] - Issues that prevent merge
        - concerns: List[str] - Non-blocking warnings
        - verdict: APPROVE_MERGE | BLOCK_MERGE
        """

        response = ollama_chat([{"role": "user", "content": prompt}])
        return self._parse_crit_response(response)
```

### CRITResult Model

```python
@dataclass
class CRITResult:
    verdict: CRITVerdict  # APPROVE | REVISE | REJECT | NEEDS_MORE_EVIDENCE
    concerns: List[str]
    warnings: List[str]
    alternatives: List[str] = None
    gaps: List[str] = None
    red_flags: List[str] = None
    blockers: List[str] = None
    reasoning: str = ""

class CRITVerdict(Enum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    APPROVE_MERGE = "approve_merge"
    BLOCK_MERGE = "block_merge"
```

### Integration Points

#### 1. Plan Review (Before Execution)
```python
# In orchestrator.py after plan generation:

crit = CRITJudge()
review = crit.evaluate_plan(plan, self.context)

if review.verdict == CRITVerdict.REJECT:
    print(f"[CRIT] Plan REJECTED - {review.concerns}")
    return False

elif review.verdict == CRITVerdict.REVISE:
    print(f"[CRIT] Plan needs revision - {review.concerns}")
    # Ask LLM to revise plan addressing concerns
    plan = revise_plan_with_feedback(plan, review.concerns)
```

#### 2. Completion Claims (After Task)
```python
# In orchestrator.py after task completion:

claim = f"Task completed: {task.description}"
evidence = {
    "tool_results": task.tool_events,
    "verification": verification_result,
    "dod_status": dod_result
}

review = crit.evaluate_claim(claim, evidence, task)

if review.verdict == CRITVerdict.NEEDS_MORE_EVIDENCE:
    print(f"[CRIT] Insufficient evidence - {review.gaps}")
    # Run additional verification

elif review.verdict == CRITVerdict.REJECT:
    print(f"[CRIT] Claim REJECTED - {review.red_flags}")
    task.status = TaskStatus.FAILED
```

#### 3. Merge Gate (Before Commit)
```python
# In transaction.py before commit:

review = crit.evaluate_merge(
    changes=[action.summary() for action in self.actions],
    context=context
)

if review.verdict == CRITVerdict.BLOCK_MERGE:
    print(f"[CRIT] Merge BLOCKED - {review.blockers}")
    return self.rollback()
```

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [ ] Create DoD models and generator
- [ ] Implement basic verification pipeline
- [ ] Build transaction infrastructure
- [ ] Write unit tests for each component

### Phase 2: Integration (Week 2)
- [ ] Integrate DoD into orchestrator
- [ ] Hook verification pipeline into task execution
- [ ] Enable transactional tool execution
- [ ] Add CRIT judge for plan review

### Phase 3: Testing & Refinement (Week 3)
- [ ] Integration tests for full flow
- [ ] Test rollback scenarios
- [ ] Validate CRIT effectiveness
- [ ] Performance optimization

### Phase 4: Deployment (Week 4)
- [ ] Documentation
- [ ] User guides
- [ ] Migration path for existing code
- [ ] Monitoring & metrics

---

## Success Metrics

1. **DoD Effectiveness**
   - Tasks with DoD complete successfully: >90%
   - False completions: <5%

2. **Verification Quality**
   - Bugs caught before commit: >95%
   - Stage failure distribution (earlier is better)

3. **Transaction Safety**
   - Successful rollbacks: 100%
   - Repo left in broken state: 0%

4. **CRIT Value**
   - Plans improved after CRIT review: >50%
   - Prevented failures: Track blocked plans that would have failed

---

## Open Questions

1. **DoD Generation**: How detailed should DoD specs be? Balance between completeness and overhead.

2. **Performance**: Will multi-stage verification slow down iteration too much?

3. **Rollback Scope**: Should rollback include git commits or only file changes?

4. **CRIT Calibration**: How aggressive should CRIT be? Too strict = blocked progress, too lenient = missed issues.

---

## Dependencies

- LLM (ollama_chat) for DoD generation and CRIT
- Git for transaction rollback (alternative)
- Pytest for test stage validation
- YAML parser for DoD serialization

---

## Next Steps

1. Review this plan with team
2. Prioritize features (recommend: DoD → Transactions → Multi-stage → CRIT)
3. Create detailed task breakdown for Phase 1
4. Set up tracking (GitHub project board?)
5. Begin implementation

---

**Document Status:** Draft
**Last Updated:** 2025-12-20
**Owner:** TBD
