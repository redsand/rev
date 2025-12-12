"""
Research Agent for pre-planning codebase exploration.

This module provides research capabilities that explore the codebase
before planning to gather context, find patterns, and identify potential issues.

Supports both symbolic search (keyword/regex) and semantic search (RAG/TF-IDF).
"""

import json
import re
import signal
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

from rev.tools.registry import execute_tool
from rev.llm.client import ollama_chat


# Global RAG retriever (lazy initialization)
_RAG_RETRIEVER = None


def get_rag_retriever(budget=None, repo_stats: Optional[Dict[str, Any]] = None):
    """Get or initialize the RAG code retriever.

    Returns:
        SimpleCodeRetriever instance or None if initialization fails
    """
    global _RAG_RETRIEVER

    if _RAG_RETRIEVER is None:
        try:
            from rev.retrieval import SimpleCodeRetriever

            # Initialize retriever for current directory
            retriever = SimpleCodeRetriever(root=Path.cwd(), chunk_size=50)

            # Build index if not already built
            if not retriever.index_built:
                file_count = (repo_stats or {}).get("file_count", 0)
                if file_count and file_count > 1500:
                    print("  ⚠️  Skipping RAG index (repo too large for lightweight index)")
                    return None
                if budget:
                    remaining = budget.get_remaining()
                    if remaining.get("tokens", 100) < 10 or remaining.get("time", 100) < 10:
                        print("  ⚠️  Skipping RAG index due to tight budget")
                        return None

                print("  → Building or loading RAG index (cached)...")

                # Use timeout to prevent hanging on large codebases
                def build_with_timeout():
                    retriever.build_index(repo_stats=repo_stats, budget=budget)

                # Build index with 600s (10 minute) timeout
                try:
                    # Run in a thread with timeout
                    import threading
                    build_thread = threading.Thread(target=build_with_timeout, daemon=True)
                    build_thread.start()
                    build_thread.join(timeout=600)

                    if build_thread.is_alive():
                        print(f"  ⚠️  RAG index building timed out after 600s - skipping RAG search")
                        return None

                    stats = retriever.get_index_stats()
                    print(f"    Indexed {stats.get('total_chunks', 0)} code chunks")
                except Exception as e:
                    print(f"  ⚠️  RAG index building failed: {e}")
                    return None

            _RAG_RETRIEVER = retriever
        except Exception as e:
            print(f"  ⚠️  RAG initialization failed: {e}")
            return None

    return _RAG_RETRIEVER


@dataclass
class ResearchFindings:
    """Findings from codebase research."""
    relevant_files: List[Dict[str, Any]] = field(default_factory=list)
    code_patterns: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    potential_conflicts: List[str] = field(default_factory=list)
    similar_implementations: List[Dict[str, str]] = field(default_factory=list)
    architecture_notes: List[str] = field(default_factory=list)
    suggested_approach: Optional[str] = None
    estimated_complexity: str = "medium"
    warnings: List[str] = field(default_factory=list)
    # Phase 2: Reuse tracking
    reusable_code: List[Dict[str, str]] = field(default_factory=list)
    existing_utilities: List[str] = field(default_factory=list)
    reuse_opportunities: List[str] = field(default_factory=list)
    files_to_extend: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relevant_files": self.relevant_files,
            "code_patterns": self.code_patterns,
            "dependencies": self.dependencies,
            "potential_conflicts": self.potential_conflicts,
            "similar_implementations": self.similar_implementations,
            "architecture_notes": self.architecture_notes,
            "suggested_approach": self.suggested_approach,
            "estimated_complexity": self.estimated_complexity,
            "warnings": self.warnings,
            "reusable_code": self.reusable_code,
            "existing_utilities": self.existing_utilities,
            "reuse_opportunities": self.reuse_opportunities,
            "files_to_extend": self.files_to_extend,
        }


RESEARCH_SYSTEM = """You are a research agent that analyzes codebases to gather context for planned changes.

🎯 PRIMARY MISSION: Find existing code that can be REUSED or EXTENDED to avoid creating new files.

Given a user request and codebase information, identify:
1. **Existing code that already solves similar problems (TOP PRIORITY - look for reuse opportunities)**
2. **Utilities, helpers, or modules that could be extended instead of creating new ones**
3. Which files are most relevant to the task
4. Existing patterns that should be followed
5. Potential conflicts or dependencies
6. Similar existing implementations to reference
7. Recommended approach that MAXIMIZES code reuse and minimizes new file creation

Return your analysis in JSON format:
{
    "relevant_files": ["path/to/file.py"],
    "reusable_code": [{"file": "path", "can_extend_for": "describe what can be added/extended"}],
    "patterns_to_follow": ["Pattern description"],
    "potential_conflicts": ["Conflict warning"],
    "similar_code": [{"file": "path", "description": "what it does"}],
    "suggested_approach": "Recommended implementation that REUSES existing code when possible",
    "complexity": "low|medium|high",
    "warnings": ["Important consideration"],
    "prefer_extending": ["List of existing files that should be extended instead of creating new ones"]
}

Be concise but thorough. Focus on actionable insights. PRIORITIZE finding code reuse opportunities."""


def _rag_search(query: str, k: int = 10, budget=None, repo_stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Perform semantic code search using RAG.

    Args:
        query: Natural language query
        k: Number of results to return

    Returns:
        Dict with files and relevant chunks
    """
    retriever = get_rag_retriever(budget=budget, repo_stats=repo_stats)

    if retriever is None:
        return {"files": [], "chunks": []}

    try:
        # Query the RAG system
        chunks = retriever.query(query, k=k)

        # Convert chunks to file info
        files = []
        chunk_info = []

        seen_files = set()
        for chunk in chunks:
            if chunk.path not in seen_files:
                files.append({
                    "path": chunk.path,
                    "relevance": "semantic_match",
                    "score": chunk.score
                })
                seen_files.add(chunk.path)

            chunk_info.append({
                "location": chunk.get_location(),
                "preview": chunk.get_preview(max_lines=3),
                "score": chunk.score
            })

        return {"files": files, "chunks": chunk_info}

    except Exception as e:
        print(f"  ⚠️  RAG search failed: {e}")
        return {"files": [], "chunks": []}


def research_codebase(
    user_request: str,
    quick_mode: bool = False,
    search_depth: str = "medium",
    use_rag: bool = True,
    repo_stats: Optional[Dict[str, Any]] = None,
    budget=None,
) -> ResearchFindings:
    """Research the codebase to gather context for a task.

    Args:
        user_request: The user's task request
        quick_mode: If True, do minimal research (faster)
        search_depth: "shallow", "medium", or "deep"
        use_rag: If True, use RAG (semantic search) alongside symbolic search

    Returns:
        ResearchFindings with gathered context
    """
    print("\n" + "=" * 60)
    print("RESEARCH AGENT - CODEBASE EXPLORATION")
    print("=" * 60)

    findings = ResearchFindings()

    # Extract keywords for searching
    keywords = _extract_search_keywords(user_request)
    print(f"→ Searching for: {', '.join(keywords[:5])}")

    # Parallel research tasks
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}

        # 1. Search for relevant code (symbolic search)
        futures[executor.submit(_search_relevant_code, keywords)] = "code_search"

        # 2. RAG semantic search (if enabled)
        if use_rag and not quick_mode:
            futures[executor.submit(_rag_search, user_request, 10, budget, repo_stats)] = "rag_search"

        # 3. Get project structure
        futures[executor.submit(_analyze_project_structure)] = "structure"

        # 4. Check for similar implementations
        if not quick_mode:
            futures[executor.submit(_find_similar_implementations, user_request, keywords)] = "similar"

        # 5. Analyze dependencies (if not quick mode)
        if not quick_mode and search_depth in ["medium", "deep"]:
            futures[executor.submit(_analyze_dependencies, keywords)] = "dependencies"

        # Collect results with 600s timeout per task
        # This prevents any single research task from hanging indefinitely
        for future in as_completed(futures, timeout=600):
            task_name = futures[future]
            try:
                result = future.result(timeout=10)  # 10s to get already-completed result
                if task_name == "code_search":
                    findings.relevant_files = result.get("files", [])
                    findings.code_patterns = result.get("patterns", [])
                elif task_name == "rag_search":
                    # Merge RAG results with existing files
                    rag_files = result.get("files", [])
                    # Add RAG files that aren't already in the list
                    existing_paths = {f['path'] for f in findings.relevant_files}
                    for rag_file in rag_files:
                        if rag_file['path'] not in existing_paths:
                            findings.relevant_files.append(rag_file)
                    # Add RAG-specific patterns
                    for chunk in result.get("chunks", [])[:3]:
                        findings.code_patterns.append(f"RAG: {chunk['location']}")
                elif task_name == "structure":
                    findings.architecture_notes = result.get("notes", [])
                elif task_name == "similar":
                    findings.similar_implementations = result.get("implementations", [])
                elif task_name == "dependencies":
                    findings.dependencies = result.get("dependencies", [])
                    findings.potential_conflicts = result.get("conflicts", [])
            except FuturesTimeoutError:
                print(f"  ⚠️  {task_name} research timed out (600s limit) - skipping")
            except Exception as e:
                print(f"  ⚠️  {task_name} research failed: {e}")

    # Use LLM to synthesize findings and suggest approach
    if not quick_mode:
        print("→ Synthesizing findings...")
        synthesis = _synthesize_findings(user_request, findings)
        findings.suggested_approach = synthesis.get("approach")
        findings.estimated_complexity = synthesis.get("complexity", "medium")
        findings.warnings.extend(synthesis.get("warnings", []))

    _display_research_findings(findings)
    return findings


def _extract_search_keywords(user_request: str) -> List[str]:
    """Extract keywords for code search."""
    # Common words to ignore
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'with', 'all', 'my', 'this', 'that', 'add', 'create', 'make', 'implement',
        'fix', 'update', 'change', 'modify', 'please', 'can', 'you', 'i', 'want',
        'find', 'other', 'related', 'after', 'before', 'should', 'would', 'could',
        'any', 'without', 'risk', 'bugs'
    }

    request_lower = user_request.lower()

    # Security audit detection - use security-specific keywords
    if any(keyword in request_lower for keyword in ['security', 'vulnerability', 'buffer overflow',
                                                      'memory corruption', 'use after free', 'exploit']):
        # Return security-focused search terms
        security_keywords = []

        # C/C++ memory safety patterns
        if 'memory' in request_lower or 'buffer' in request_lower or 'overflow' in request_lower:
            security_keywords.extend([
                'strcpy', 'strcat', 'sprintf', 'gets', 'scanf',  # Unsafe functions
                'malloc', 'calloc', 'realloc', 'free',  # Memory management
                'memcpy', 'memmove', 'memset',  # Memory operations
                'sizeof', 'strlen',  # Size operations
            ])

        # Use-after-free patterns
        if 'use after free' in request_lower or 'uaf' in request_lower:
            security_keywords.extend(['free', 'delete', 'kfree', 'ExFreePool'])

        # Driver-specific security
        if any(word in request_lower for word in ['driver', 'kernel', 'ioctl']):
            security_keywords.extend(['IOCTL', 'DeviceIoControl', 'IRP', 'ProbeFor'])

        # Add any specific technical terms from the request
        words = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b', user_request)  # CamelCase
        security_keywords.extend([w for w in words if w not in ['This', 'Should']])

        return security_keywords[:15] if security_keywords else ['security', 'vulnerability']

    # Structure investigation detection - covers schemas, docs, code structures, config
    structure_keywords = [
        # Database/Schema
        'prisma', 'schema', 'database', 'enum', 'model', 'migration',
        'sequelize', 'typeorm', 'mongoose', 'sql', 'table', 'entity',
        # Documentation
        'readme', 'documentation', 'docs', 'api documentation', 'guide',
        # Code structures
        'class', 'interface', 'type', 'typedef', 'struct',
        # Configuration
        'config', 'configuration', 'settings', 'environment'
    ]

    if any(keyword in request_lower for keyword in structure_keywords):
        # Return structure-focused search terms
        investigation_keywords = []

        # Database/Schema patterns
        if any(word in request_lower for word in ['prisma', 'schema', 'database', 'sql', 'migration']):
            investigation_keywords.extend([
                'enum', 'model', 'table', 'schema', 'migration',
                'CREATE TABLE', 'ALTER TABLE', '@db', '@relation',
                'interface', 'type', 'class'
            ])

        # Documentation patterns
        if any(word in request_lower for word in ['readme', 'documentation', 'docs', 'guide']):
            investigation_keywords.extend([
                'README', 'DOCUMENTATION', 'docs/', 'documentation/',
                '# ', '## ', 'API', 'guide', 'tutorial'
            ])

        # Code structure patterns (enum, class, interface, type)
        if any(word in request_lower for word in ['enum', 'class', 'interface', 'type', 'struct']):
            investigation_keywords.extend([
                'enum ', 'enum{', 'class ', 'interface ', 'type ',
                'struct ', 'typedef ', 'def class', '@dataclass'
            ])

        # Configuration patterns
        if any(word in request_lower for word in ['config', 'configuration', 'settings', 'environment']):
            investigation_keywords.extend([
                'config.', 'settings.', '.env', 'environment',
                'CONFIG', 'SETTINGS', 'dotenv'
            ])

        # Add any CamelCase/PascalCase identifiers (likely type/class/enum names)
        words = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b', user_request)
        investigation_keywords.extend([w for w in words if w not in ['This', 'Should', 'Add', 'Create', 'Update', 'Modify']])

        return investigation_keywords[:20] if investigation_keywords else ['structure', 'definition', 'existing']

    # Extract words (original logic for non-security requests)
    words = re.findall(r'\b\w+\b', request_lower)
    keywords = [w for w in words if len(w) > 2 and w not in stop_words]

    # Also extract potential class/function names (CamelCase, snake_case)
    camel_case = re.findall(r'[A-Z][a-z]+(?:[A-Z][a-z]+)*', user_request)
    snake_case = re.findall(r'[a-z]+_[a-z_]+', request_lower)

    keywords.extend([w.lower() for w in camel_case])
    keywords.extend(snake_case)

    return list(set(keywords))[:10]


def _search_relevant_code(keywords: List[str]) -> Dict[str, Any]:
    """Search for code relevant to the keywords."""
    files = []
    patterns = []
    seen_paths = set()  # O(1) lookup instead of O(n) list membership

    for keyword in keywords[:5]:
        try:
            # Search for keyword in code
            result = execute_tool("search_code", {"pattern": keyword, "max_results": 5})
            result_data = json.loads(result)

            matches = result_data.get("matches", [])
            for match in matches:
                path = match.get("file", "")
                if path not in seen_paths:
                    file_info = {
                        "path": path,
                        "relevance": "keyword_match",
                        "keyword": keyword
                    }
                    files.append(file_info)
                    seen_paths.add(path)

                # Extract pattern from context
                context = match.get("context", "")
                if context:
                    # Look for function/class definitions
                    if "def " in context or "class " in context:
                        patterns.append(f"Found '{keyword}' in: {context[:100]}")
        except Exception:
            continue

    return {"files": files[:15], "patterns": patterns[:5]}


def _analyze_project_structure() -> Dict[str, Any]:
    """Analyze the project structure."""
    notes = []

    try:
        # Get directory structure
        result = execute_tool("tree_view", {"path": ".", "max_depth": 2})
        result_data = json.loads(result)
        tree = result_data.get("tree")
        if tree is None:
            tree = ""
        elif not isinstance(tree, str):
            # Some tool impls may return structured trees (dict/list); make it searchable
            try:
                tree = json.dumps(tree)
            except Exception:
                tree = str(tree)

        # Detect patterns from structure
        if "src/" in tree:
            notes.append("Project uses src/ directory structure")
        if "tests/" in tree:
            notes.append("Project has tests/ directory")
        if "requirements.txt" in tree:
            notes.append("Python project with requirements.txt")
        if "package.json" in tree:
            notes.append("Node.js project with package.json")
        if "Dockerfile" in tree:
            notes.append("Project is containerized with Docker")

    except Exception:
        pass

    try:
        # Check for common config files
        configs = ["setup.py", "pyproject.toml", "setup.cfg", ".eslintrc", "tsconfig.json"]
        for config in configs:
            result = execute_tool("file_exists", {"path": config})
            result_data = json.loads(result)
            if result_data.get("exists"):
                notes.append(f"Uses {config} for configuration")
    except Exception:
        pass

    return {"notes": notes}


def _find_similar_implementations(user_request: str, keywords: List[str]) -> Dict[str, Any]:
    """Find similar existing implementations."""
    implementations = []

    # Search for similar patterns
    search_patterns = []
    request_lower = user_request.lower()

    if "auth" in request_lower:
        search_patterns.extend(["def authenticate", "class Auth", "login", "token"])
    if "api" in request_lower:
        search_patterns.extend(["@app.route", "def api_", "endpoint"])
    if "test" in request_lower:
        search_patterns.extend(["def test_", "class Test", "unittest"])
    if "database" in request_lower or "db" in request_lower:
        search_patterns.extend(["def query", "cursor", "execute"])

    for pattern in search_patterns[:3]:
        try:
            result = execute_tool("search_code", {"pattern": pattern, "max_results": 3})
            result_data = json.loads(result)

            for match in result_data.get("matches", []):
                impl = {
                    "file": match.get("file", ""),
                    "description": f"Contains '{pattern}' pattern"
                }
                if impl not in implementations:
                    implementations.append(impl)
        except Exception:
            continue

    return {"implementations": implementations[:5]}


def _analyze_dependencies(keywords: List[str]) -> Dict[str, Any]:
    """Analyze code dependencies related to keywords."""
    dependencies = []
    conflicts = []

    for keyword in keywords[:3]:
        try:
            # Search for imports
            result = execute_tool("search_code", {"pattern": f"import.*{keyword}", "max_results": 5})
            result_data = json.loads(result)

            for match in result_data.get("matches", []):
                dep = match.get("context", "").strip()
                if dep and dep not in dependencies:
                    dependencies.append(dep)
        except Exception:
            continue

    return {"dependencies": dependencies[:10], "conflicts": conflicts}


def _synthesize_findings(user_request: str, findings: ResearchFindings) -> Dict[str, Any]:
    """Use LLM to synthesize findings into actionable insights."""
    # Prepare context
    context_parts = []

    if findings.relevant_files:
        context_parts.append(f"Relevant files: {', '.join(f.get('path', 'unknown') for f in findings.relevant_files[:5])}")

    if findings.code_patterns:
        context_parts.append(f"Patterns found: {'; '.join(findings.code_patterns[:3])}")

    if findings.architecture_notes:
        context_parts.append(f"Architecture: {'; '.join(findings.architecture_notes[:3])}")

    if findings.similar_implementations:
        context_parts.append(f"Similar code in: {', '.join(s.get('file', 'unknown') for s in findings.similar_implementations[:3])}")

    messages = [
        {"role": "system", "content": RESEARCH_SYSTEM},
        {"role": "user", "content": f"""Analyze this research for the task: "{user_request}"

Research findings:
{chr(10).join(context_parts)}

Suggest the best approach and identify any concerns."""}
    ]

    response = ollama_chat(messages)

    if "error" in response:
        return {"approach": None, "complexity": "medium", "warnings": []}

    try:
        content = response.get("message", {}).get("content", "")
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            return {
                "approach": data.get("suggested_approach"),
                "complexity": data.get("complexity", "medium"),
                "warnings": data.get("warnings", [])
            }
    except Exception:
        pass

    return {"approach": None, "complexity": "medium", "warnings": []}


def _display_research_findings(findings: ResearchFindings):
    """Display research findings."""
    print("\n" + "=" * 60)
    print("RESEARCH FINDINGS")
    print("=" * 60)

    if findings.relevant_files:
        print(f"\n📁 Relevant Files ({len(findings.relevant_files)}):")
        for f in findings.relevant_files[:5]:
            print(f"   - {f['path']}")

    if findings.similar_implementations:
        print(f"\n🔍 Similar Implementations:")
        for impl in findings.similar_implementations[:3]:
            print(f"   - {impl['file']}: {impl['description']}")

    if findings.architecture_notes:
        print(f"\n🏗️  Architecture Notes:")
        for note in findings.architecture_notes[:3]:
            print(f"   - {note}")

    if findings.code_patterns:
        print(f"\n📝 Code Patterns Found:")
        for pattern in findings.code_patterns[:3]:
            print(f"   - {pattern[:80]}...")

    if findings.suggested_approach:
        print(f"\n💡 Suggested Approach:")
        print(f"   {findings.suggested_approach}")

    print(f"\n📊 Estimated Complexity: {findings.estimated_complexity.upper()}")

    if findings.warnings:
        print(f"\n⚠️  Warnings:")
        for warning in findings.warnings:
            print(f"   - {warning}")

    if findings.potential_conflicts:
        print(f"\n🔴 Potential Conflicts:")
        for conflict in findings.potential_conflicts:
            print(f"   - {conflict}")

    print("=" * 60)


def quick_research(user_request: str) -> Dict[str, Any]:
    """Quick research for simple context gathering.

    Args:
        user_request: The user's task request

    Returns:
        Dict with basic findings
    """
    keywords = _extract_search_keywords(user_request)
    code_result = _search_relevant_code(keywords[:3])

    return {
        "relevant_files": [f["path"] for f in code_result.get("files", [])[:5]],
        "keywords": keywords
    }
