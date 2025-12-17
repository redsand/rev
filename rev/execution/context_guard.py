"""
ContextGuard: Contextual Clarity Engine (CCE) for rev

Provides intelligent context validation and filtering to:
1. Validate context sufficiency before planning (prevent hallucinations)
2. Filter irrelevant context to reduce tokens (25% target)
3. Detect gaps and ambiguities, offer interactive clarification
4. Auto-discover missing information when needed

Integrates as Phase 2c in orchestrator pipeline:
Research → Prompt Optimization → ContextGuard → Planning
"""

import time
import re
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from rev.execution.researcher import ResearchFindings
from rev.retrieval.base import CodeChunk
from rev.core.context import ResourceBudget
from rev.debug_logger import get_logger


# ============================================================================
# DATA STRUCTURES
# ============================================================================

class GapType(str, Enum):
    """Types of context gaps detected by ContextGuard."""
    MISSING_ENTITY = "missing_entity"
    AMBIGUOUS_REFERENCE = "ambiguous_reference"
    INSUFFICIENT_DETAIL = "insufficient_detail"
    VAGUE_SCOPE = "vague_scope"


class GapSeverity(str, Enum):
    """Severity levels for detected gaps."""
    CRITICAL = "critical"
    WARNING = "warning"
    MINOR = "minor"


@dataclass
class ContextGap:
    """Represents a gap or ambiguity in available context."""
    gap_type: GapType
    description: str
    mentioned_in_request: str
    found_in_research: bool
    severity: GapSeverity
    suggested_action: Optional[str] = None


@dataclass
class ContextSufficiency:
    """Assessment of whether research findings are sufficient for planning."""
    is_sufficient: bool
    confidence_score: float  # 0.0 to 1.0
    gaps: List[ContextGap] = field(default_factory=list)
    hallucination_risks: List[str] = field(default_factory=list)
    concrete_references: Dict[str, List[str]] = field(default_factory=dict)
    # Structure: {"files": [...], "classes": [...], "functions": [...]}


@dataclass
class FilteredContext:
    """Context after relevance filtering and scoring."""
    original_chunk_count: int
    filtered_chunk_count: int
    tokens_saved: int
    relevant_files: List[Dict[str, Any]]
    relevant_chunks: List[CodeChunk]
    relevance_threshold: float
    filtered_out: List[str]  # File paths that were filtered out


@dataclass
class ContextGuardResult:
    """Complete result from ContextGuard phase."""
    sufficiency: ContextSufficiency
    filtered_context: FilteredContext
    user_intent: Dict[str, Any]
    clarifications_needed: List[str]
    discovery_tasks: List[str]
    purified_context_summary: str
    action_taken: str  # "approved", "clarification_requested", "discovery_initiated", "insufficient", "approved_with_warnings"
    execution_time: float = 0.0


# ============================================================================
# INTENT EXTRACTION MODULE
# ============================================================================

def extract_user_intent(user_request: str, research_findings: Optional[ResearchFindings] = None) -> Dict[str, Any]:
    """
    Extract core user intent from the request.

    Analyzes:
    - Action verbs (add, fix, implement, refactor, etc.)
    - Target entities (files, classes, functions)
    - Scope indicators (specific file, module, entire project)
    - Ambiguities and missing information

    Args:
        user_request: The user's task request
        research_findings: Optional research findings for cross-referencing

    Returns:
        Dict with: action, entities, ambiguities, scope, confidence
    """
    intent = {
        "action": None,
        "entities": {
            "files": [],
            "classes": [],
            "functions": [],
            "features": []
        },
        "ambiguities": [],
        "scope": "unknown",
        "confidence": 0.5,
    }

    # Extract action verbs
    action_patterns = {
        r"\b(add|create|implement)\b": "add",
        r"\b(fix|repair|patch|debug)\b": "fix",
        r"\b(refactor|reorganize|restructure)\b": "refactor",
        r"\b(update|modify|change|edit)\b": "edit",
        r"\b(delete|remove)\b": "delete",
        r"\b(test|write.*test)\b": "test",
        r"\b(document|write.*doc)\b": "document",
        r"\b(investigate|analyze|review)\b": "analyze",
    }

    request_lower = user_request.lower()
    for pattern, action in action_patterns.items():
        if re.search(pattern, request_lower, re.IGNORECASE):
            intent["action"] = action
            break

    if not intent["action"]:
        intent["action"] = "general"
        intent["ambiguities"].append("Unclear action type")

    # Extract entities (simple pattern matching)
    # Files: look for .py, .js, .ts, etc.
    files = re.findall(r'\b[\w/]+\.(py|js|ts|tsx|jsx|java|cpp|c|rs|go|rb)\b', user_request)
    intent["entities"]["files"] = list(set(files))

    # Classes: look for CamelCase or word "class"
    classes = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)*)\b', user_request)
    intent["entities"]["classes"] = [c for c in classes if c not in ["JWT", "URL", "API", "SQL"]][:5]

    # Functions: look for snake_case or word "function"
    functions = re.findall(r'\b([a-z_]+(?:_[a-z]+)*)\s*\(', user_request)
    intent["entities"]["functions"] = list(set(functions))[:5]

    # Features: extract quoted strings or keywords
    features = re.findall(r'["\']([^"\']+)["\']', user_request)
    intent["entities"]["features"] = features[:3]

    # Detect scope
    if len(intent["entities"]["files"]) > 0:
        intent["scope"] = "file"
    elif len(intent["entities"]["classes"]) > 0 or len(intent["entities"]["functions"]) > 0:
        intent["scope"] = "module"
    elif "project" in request_lower or "codebase" in request_lower or "entire" in request_lower:
        intent["scope"] = "project"
    elif "module" in request_lower or "package" in request_lower:
        intent["scope"] = "module"

    # Detect ambiguities
    vague_words = ["fix", "improve", "make", "help", "enhance", "optimize"]
    if any(word in request_lower for word in vague_words):
        intent["ambiguities"].append("Vague action language - unclear exact requirements")

    if len(intent["entities"]["files"]) == 0 and len(intent["entities"]["classes"]) == 0:
        intent["ambiguities"].append("No specific entities mentioned")

    if intent["scope"] == "unknown":
        intent["ambiguities"].append("Unclear scope - specific file/module or entire project?")

    # Calculate confidence
    confidence = 0.5
    if intent["action"] and intent["action"] != "general":
        confidence += 0.15
    if len(intent["entities"]["files"]) > 0 or len(intent["entities"]["classes"]) > 0:
        confidence += 0.2
    if intent["scope"] != "unknown":
        confidence += 0.15
    confidence -= len(intent["ambiguities"]) * 0.1

    intent["confidence"] = max(0.0, min(1.0, confidence))

    return intent


# ============================================================================
# RELEVANCE SCORING MODULE
# ============================================================================

def score_context_relevance(
    intent: Dict[str, Any],
    research_findings: ResearchFindings,
    threshold: float = 0.3
) -> FilteredContext:
    """
    Score research findings by relevance to user intent.

    Uses:
    - TF-IDF similarity to intent keywords
    - Entity matching boost
    - Architecture importance

    Filters out low-scoring chunks to reduce noise and tokens.

    Args:
        intent: Extracted user intent
        research_findings: Research findings from researcher agent
        threshold: Keep chunks with score >= threshold (0.0-1.0)

    Returns:
        FilteredContext with filtered files and token savings
    """

    # Extract intent keywords for matching
    intent_keywords = set()
    for entity_list in intent["entities"].values():
        if isinstance(entity_list, list):
            intent_keywords.update(entity_list)
    intent_keywords.add(intent.get("action", ""))

    # Score files based on research findings
    scored_files = []

    if hasattr(research_findings, 'relevant_files') and research_findings.relevant_files:
        for file_info in research_findings.relevant_files:
            file_path = file_info.get("path", "")
            relevance = file_info.get("relevance", 0.0)

            # Base score from research
            score = relevance if isinstance(relevance, float) else 0.5

            # Boost for entity matches
            file_path_lower = file_path.lower()
            for keyword in intent_keywords:
                if keyword and keyword.lower() in file_path_lower:
                    score = min(1.0, score + 0.3)

            # Boost for architecture importance
            if any(x in file_path_lower for x in ["__init__", "main", "core", "lib", "src"]):
                score = min(1.0, score + 0.1)

            if score >= threshold:
                scored_files.append({
                    **file_info,
                    "score": score
                })

    # Sort by score descending
    scored_files.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Estimate token savings
    # Rough estimate: ~4 tokens per line, ~50 lines per file
    original_tokens = max(len(research_findings.relevant_files) * 200, 1000) if hasattr(research_findings, 'relevant_files') else 1000
    filtered_tokens = len(scored_files) * 200
    tokens_saved = original_tokens - filtered_tokens

    # Create list of filtered files
    filtered_out = []
    if hasattr(research_findings, 'relevant_files') and research_findings.relevant_files:
        all_files = {f.get("path", ""): f for f in research_findings.relevant_files}
        kept_files = {f.get("path", "") for f in scored_files}
        filtered_out = [path for path in all_files.keys() if path not in kept_files]

    return FilteredContext(
        original_chunk_count=len(research_findings.relevant_files) if hasattr(research_findings, 'relevant_files') else 0,
        filtered_chunk_count=len(scored_files),
        tokens_saved=max(0, tokens_saved),
        relevant_files=scored_files,
        relevant_chunks=[],  # TODO: populate from research_findings if available
        relevance_threshold=threshold,
        filtered_out=filtered_out
    )


# ============================================================================
# SUFFICIENCY VALIDATION MODULE
# ============================================================================

def validate_context_sufficiency(
    intent: Dict[str, Any],
    filtered_context: FilteredContext,
    research_findings: Optional[ResearchFindings] = None
) -> ContextSufficiency:
    """
    Validate whether research findings contain sufficient concrete information.

    Detects:
    - Missing entities (mentioned but not found)
    - Critical gaps (file/class mentioned but doesn't exist)
    - Hallucination risks (vague request with few concrete references)

    Returns confidence score and list of gaps.

    Args:
        intent: Extracted user intent
        filtered_context: Filtered research findings
        research_findings: Original research findings

    Returns:
        ContextSufficiency assessment with gaps and confidence
    """

    gaps: List[ContextGap] = []
    hallucination_risks: List[str] = []
    concrete_refs: Dict[str, List[str]] = {
        "files": [f.get("path", "") for f in filtered_context.relevant_files],
        "classes": [],
        "functions": [],
    }

    # Validate files
    found_files = set(concrete_refs["files"])
    requested_files = set(intent["entities"]["files"])

    for file_name in requested_files:
        if not any(file_name in found_file for found_file in found_files):
            gaps.append(ContextGap(
                gap_type=GapType.MISSING_ENTITY,
                description=f"File '{file_name}' mentioned but not found in research",
                mentioned_in_request=file_name,
                found_in_research=False,
                severity=GapSeverity.CRITICAL,
                suggested_action=f"Search for file: {file_name}"
            ))
            hallucination_risks.append(f"Planner may hallucinate modifications to '{file_name}'")

    # Validate classes (check code patterns and external findings)
    requested_classes = set(intent["entities"]["classes"])
    found_classes = set()

    if research_findings:
        if hasattr(research_findings, 'code_patterns'):
            for pattern in research_findings.code_patterns:
                for class_name in requested_classes:
                    if class_name in str(pattern):
                        found_classes.add(class_name)

        if hasattr(research_findings, 'external_classes'):
            found_classes.update(research_findings.external_classes)

    for class_name in requested_classes:
        if class_name not in found_classes:
            gaps.append(ContextGap(
                gap_type=GapType.MISSING_ENTITY,
                description=f"Class '{class_name}' mentioned but not found",
                mentioned_in_request=class_name,
                found_in_research=False,
                severity=GapSeverity.CRITICAL,
                suggested_action=f"Search for class definition: {class_name}"
            ))
            hallucination_risks.append(f"Planner may hallucinate '{class_name}' implementation")

    concrete_refs["classes"] = list(found_classes)

    # Validate functions similarly
    requested_functions = set(intent["entities"]["functions"])
    found_functions = set()

    if research_findings:
        if hasattr(research_findings, 'external_functions'):
            found_functions.update(research_findings.external_functions)

    concrete_refs["functions"] = list(found_functions)

    # Detect ambiguities
    if len(intent["ambiguities"]) > 0:
        for ambiguity in intent["ambiguities"]:
            gaps.append(ContextGap(
                gap_type=GapType.AMBIGUOUS_REFERENCE,
                description=ambiguity,
                mentioned_in_request="<entire request>",
                found_in_research=False,
                severity=GapSeverity.WARNING,
                suggested_action="Ask user for clarification"
            ))

    # Calculate confidence score
    # confidence = 0.4 * entity_match_rate + 0.3 * (1 - gap_severity) + 0.3 * semantic_similarity

    total_entities = (len(requested_files) + len(requested_classes) + len(requested_functions))
    if total_entities > 0:
        entity_match_rate = (
            (len(requested_files) - len([g for g in gaps if g.gap_type == GapType.MISSING_ENTITY and "File" in g.description])) / len(requested_files) +
            (len(requested_classes) - len([g for g in gaps if g.gap_type == GapType.MISSING_ENTITY and "Class" in g.description])) / len(requested_classes) +
            (len(requested_functions) / max(1, len(requested_functions)))
        ) / 3 if total_entities > 0 else 0.5
    else:
        entity_match_rate = 0.3  # No specific entities mentioned

    critical_gaps = len([g for g in gaps if g.severity == GapSeverity.CRITICAL])
    gap_severity_score = min(1.0, critical_gaps * 0.2)

    confidence = (
        0.4 * entity_match_rate +
        0.3 * (1.0 - gap_severity_score) +
        0.3 * intent.get("confidence", 0.5)
    )
    confidence = max(0.0, min(1.0, confidence))

    # Determine if sufficient
    is_sufficient = confidence >= 0.7 and critical_gaps == 0

    return ContextSufficiency(
        is_sufficient=is_sufficient,
        confidence_score=confidence,
        gaps=gaps,
        hallucination_risks=hallucination_risks,
        concrete_references=concrete_refs
    )


# ============================================================================
# FILTERING/SUMMARIZATION MODULE
# ============================================================================

def create_purified_context(filtered_context: FilteredContext, intent: Dict[str, Any]) -> str:
    """
    Create a structured summary of purified context for the planner.

    Formats:
    - High relevance files with confidence scores
    - Relevant code patterns
    - Architecture notes
    - Filtered files for transparency
    - Token savings

    Args:
        filtered_context: Filtered research findings
        intent: Extracted user intent

    Returns:
        Formatted summary string
    """

    summary_lines = []
    summary_lines.append("=" * 70)
    summary_lines.append("PURIFIED CONTEXT SUMMARY (from ContextGuard)")
    summary_lines.append("=" * 70)

    action = intent.get("action", "unknown").upper()
    summary_lines.append(f"\nTarget Action: {action}")

    # High relevance files
    if filtered_context.relevant_files:
        summary_lines.append(f"\nHIGH RELEVANCE FILES ({len(filtered_context.relevant_files)}):")
        for file_info in filtered_context.relevant_files[:5]:  # Top 5
            path = file_info.get("path", "unknown")
            score = file_info.get("score", 0)
            summary_lines.append(f"  - {path} [score: {score:.2f}]")

        if len(filtered_context.relevant_files) > 5:
            summary_lines.append(f"  ... and {len(filtered_context.relevant_files) - 5} more files")

    # Filtered out files for transparency
    if filtered_context.filtered_out:
        summary_lines.append(f"\nFILTERED OUT ({len(filtered_context.filtered_out)} files): low relevance")
        summary_lines.append(f"  {', '.join(filtered_context.filtered_out[:5])}")
        if len(filtered_context.filtered_out) > 5:
            summary_lines.append(f"  ... and {len(filtered_context.filtered_out) - 5} more")

    # Token savings
    summary_lines.append(f"\nTOKEN OPTIMIZATION:")
    summary_lines.append(f"  Original chunks: {filtered_context.original_chunk_count}")
    summary_lines.append(f"  Filtered chunks: {filtered_context.filtered_chunk_count}")
    summary_lines.append(f"  Tokens saved: ~{filtered_context.tokens_saved} ({filtered_context.tokens_saved / max(1, filtered_context.original_chunk_count * 200):.1%} reduction)")

    summary_lines.append("=" * 70)

    return "\n".join(summary_lines)


# ============================================================================
# FEEDBACK LOOP MODULE
# ============================================================================

def handle_insufficient_context(
    sufficiency: ContextSufficiency,
    interactive: bool = True
) -> Tuple[str, List[str]]:
    """
    Handle insufficient context via interactive or auto-discovery mode.

    Interactive mode: Ask user for clarifications
    Auto-discovery mode: Generate discovery tasks to fill gaps

    Args:
        sufficiency: Sufficiency assessment with gaps
        interactive: True for interactive mode, False for auto-discovery

    Returns:
        Tuple of (action_status, results_list)
    """

    if interactive:
        print("\n" + "=" * 70)
        print("⚠️  CONTEXT GAPS DETECTED - Interactive Clarification")
        print("=" * 70)

        # Display gaps
        if sufficiency.gaps:
            print("\nIdentified Issues:")
            for i, gap in enumerate(sufficiency.gaps[:5], 1):
                severity_icon = "🔴" if gap.severity == GapSeverity.CRITICAL else "🟡"
                print(f"  {severity_icon} {gap.description}")

        if sufficiency.hallucination_risks:
            print("\nHallucination Risks:")
            for risk in sufficiency.hallucination_risks[:3]:
                print(f"  ⚠️  {risk}")

        # Ask for clarification or skip
        print("\nOptions:")
        print("  1. Skip and proceed (acknowledge risks)")
        print("  2. Proceed with discovery tasks")
        print("  3. Abort and restart")

        try:
            response = input("\nChoose option (1-3) or press Enter for option 1: ").strip()

            if response == "2":
                return "auto_discovery_requested", []
            elif response == "3":
                raise KeyboardInterrupt("User chose to abort")
            else:
                return "proceed_with_warnings", []

        except (KeyboardInterrupt, EOFError):
            print("[Cancelled by user]")
            return "cancelled", []

    else:
        # Auto-discovery mode: generate discovery tasks
        discovery_tasks = []

        for gap in sufficiency.gaps:
            if gap.severity == GapSeverity.CRITICAL:
                if "File" in gap.description:
                    task = f"research: Find file '{gap.mentioned_in_request}'"
                elif "Class" in gap.description:
                    task = f"research: Find class definition for '{gap.mentioned_in_request}'"
                else:
                    task = f"research: {gap.suggested_action}"

                discovery_tasks.append(task)

        return "discovery_tasks_generated", discovery_tasks


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def run_context_guard(
    user_request: str,
    research_findings: Optional[ResearchFindings] = None,
    interactive: bool = True,
    threshold: float = 0.3,
    use_llm_ranking: bool = False,
    budget: Optional[ResourceBudget] = None
) -> ContextGuardResult:
    """
    Execute ContextGuard phase to validate and filter research context.

    Orchestrates all ContextGuard modules:
    1. Extract user intent
    2. Score and filter context
    3. Validate sufficiency
    4. Create purified summary
    5. Handle insufficiency (interactive or auto-discovery)

    Args:
        user_request: The user's task request (potentially optimized)
        research_findings: Findings from research agent
        interactive: If True, ask for clarifications; if False, auto-discover
        threshold: Relevance threshold for filtering (0.0-1.0)
        use_llm_ranking: If True, use LLM for critical re-ranking
        budget: Resource budget for tracking tokens

    Returns:
        ContextGuardResult with validation and filtering results
    """

    start_time = time.time()
    logger = get_logger()

    print("\n" + "=" * 70)
    print("🔒 CONTEXTGUARD PHASE - VALIDATION & FILTERING")
    print("=" * 70)
    print(f"Mode: {'Interactive' if interactive else 'Auto-Discovery'}")
    print(f"Threshold: {threshold:.2f}\n")

    # Default empty research if not provided
    if research_findings is None:
        research_findings = ResearchFindings()

    # Step 1: Extract intent
    print("→ Analyzing user intent...")
    intent = extract_user_intent(user_request, research_findings)
    print(f"  Action: {intent['action']}")
    print(f"  Entities: {sum(len(v) for v in intent['entities'].values())} found")
    print(f"  Confidence: {intent['confidence']:.2f}")

    # Step 2: Score and filter context
    print("\n→ Scoring and filtering context...")
    filtered = score_context_relevance(intent, research_findings, threshold)
    print(f"  Filtered: {filtered.original_chunk_count} → {filtered.filtered_chunk_count} chunks")
    print(f"  Tokens saved: ~{filtered.tokens_saved} tokens")

    # Step 3: Validate sufficiency
    print("\n→ Validating context sufficiency...")
    sufficiency = validate_context_sufficiency(intent, filtered, research_findings)
    print(f"  Confidence: {sufficiency.confidence_score:.2f}/1.0")
    print(f"  Gaps: {len(sufficiency.gaps)}")
    print(f"  Hallucination risks: {len(sufficiency.hallucination_risks)}")

    # Step 4: Create purified summary
    purified_summary = create_purified_context(filtered, intent)
    print(purified_summary)

    # Step 5: Handle insufficiency
    action_taken = "approved"
    clarifications = []
    discoveries = []

    if not sufficiency.is_sufficient:
        print("\n→ Handling insufficiency...")
        action_result, results = handle_insufficient_context(sufficiency, interactive=interactive)

        if action_result == "proceed_with_warnings":
            action_taken = "approved_with_warnings"
            print("✓ Proceeding with warnings")
        elif action_result == "discovery_tasks_generated":
            action_taken = "discovery_initiated"
            discoveries = results
            print(f"✓ Generated {len(discoveries)} discovery tasks")
        elif action_result == "cancelled":
            action_taken = "insufficient"
            print("✗ Cancelled by user")
        else:
            action_taken = "insufficient"
    else:
        print("\n✓ Context is sufficient - ready for planning")

    execution_time = time.time() - start_time

    result = ContextGuardResult(
        sufficiency=sufficiency,
        filtered_context=filtered,
        user_intent=intent,
        clarifications_needed=clarifications,
        discovery_tasks=discoveries,
        purified_context_summary=purified_summary,
        action_taken=action_taken,
        execution_time=execution_time
    )

    # Log metrics
    logger.log("context_guard", "PHASE_COMPLETE", {
        "action": action_taken,
        "confidence": sufficiency.confidence_score,
        "gaps": len(sufficiency.gaps),
        "tokens_saved": filtered.tokens_saved,
        "execution_time": execution_time,
        "is_sufficient": sufficiency.is_sufficient,
    })

    print(f"\n⏱️  ContextGuard completed in {execution_time:.2f}s")
    print("=" * 70 + "\n")

    return result
