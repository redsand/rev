"""
Research Agent for pre-planning codebase exploration.

This module provides research capabilities that explore the codebase
before planning to gather context, find patterns, and identify potential issues.

Supports both symbolic search (keyword/regex) and semantic search (RAG/TF-IDF).
"""

import json
import os
import re
import signal
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

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
    # External path findings (for porting/integration tasks)
    external_findings: List[Dict[str, Any]] = field(default_factory=list)
    external_classes: List[str] = field(default_factory=list)  # Specific class names from external sources
    external_functions: List[str] = field(default_factory=list)  # Specific function names from external sources

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
            "external_findings": self.external_findings,
            "external_classes": self.external_classes,
            "external_functions": self.external_functions,
        }


RESEARCH_SYSTEM = """You synthesize existing research notes into a concise recommendation.

Output format (strict):
- Return ONLY a single JSON object. No prose, no markdown, no code fences.
- The object MUST contain exactly:
  - "suggested_approach": string (concise recommended approach, prioritizing reuse)
  - "complexity": "low" | "medium" | "high"
  - "warnings": array of strings

Guidance:
- Prefer reuse and extension of existing code.
- Put risks, unknowns, or missing context into "warnings".

CRITICAL - External Path Handling:
- Check the user prompt for external directory paths (e.g., ../other-repo, ..\other-repo, absolute paths).
- If found, you MUST explicitly list the files in that directory and read the contents of relevant files
  to understand what needs to be ported/referenced.
- Do NOT assume context is limited to the current directory when external paths are mentioned.
- When porting code from another location, you MUST identify specific class/function names."""


def _detect_external_paths(user_request: str) -> List[str]:
    """Detect external directory paths mentioned in user request.

    This is a "Pre-Flight" capability to detect file paths in the user prompt
    that are outside the current working directory (CWD).

    Args:
        user_request: The user's task request

    Returns:
        List of detected external paths (relative or absolute)
    """
    external_paths = []

    # Pattern for relative paths starting with ../ or ..\
    relative_pattern = r'(?:\.\.[\\/])+[^\s\'"<>|]*'

    # Pattern for absolute paths (Unix or Windows)
    unix_abs_pattern = r'(?<!\w)/(?:home|usr|opt|var|tmp|etc|mnt|media|srv)[^\s\'"<>|]*'
    windows_abs_pattern = r'[A-Za-z]:\\[^\s\'"<>|]*'

    # Find all relative external paths
    for match in re.finditer(relative_pattern, user_request):
        path = match.group().strip().rstrip('.,;:')
        if path and path not in external_paths:
            external_paths.append(path)

    # Find all absolute Unix paths
    for match in re.finditer(unix_abs_pattern, user_request):
        path = match.group().strip().rstrip('.,;:')
        if path and path not in external_paths:
            external_paths.append(path)

    # Find all absolute Windows paths
    for match in re.finditer(windows_abs_pattern, user_request):
        path = match.group().strip().rstrip('.,;:')
        if path and path not in external_paths:
            external_paths.append(path)

    return external_paths


def _scan_external_directory(path: str, max_depth: int = 3) -> Dict[str, Any]:
    """Scan an external directory to understand its structure and contents.

    Args:
        path: Path to the external directory
        max_depth: Maximum directory depth to scan

    Returns:
        Dict with directory structure and key findings
    """
    result = {
        "path": path,
        "exists": False,
        "is_directory": False,
        "files": [],
        "classes": [],
        "functions": [],
        "modules": [],
        "error": None
    }

    try:
        resolved_path = Path(path).resolve()
        result["exists"] = resolved_path.exists()

        if not resolved_path.exists():
            result["error"] = f"Path does not exist: {path}"
            return result

        result["is_directory"] = resolved_path.is_dir()

        if resolved_path.is_file():
            # Single file - read and analyze it
            result["files"] = [str(resolved_path)]
            content = _read_external_file(str(resolved_path))
            if content:
                classes, functions = _extract_definitions(content, str(resolved_path))
                result["classes"] = classes
                result["functions"] = functions
            return result

        # Language configuration
        lang_config = {
            "python": {".py"},
            "javascript": {".js", ".ts", ".jsx", ".tsx"},
            "java": {".java"},
            "csharp": {".cs"},
            "go": {".go"},
            "rust": {".rs"},
            "c": {".c", ".h"},
            "cpp": {".cpp", ".h"},
        }
        all_extensions = {ext for lang_exts in lang_config.values() for ext in lang_exts}

        for root, dirs, files in os.walk(resolved_path):
            # Limit depth
            rel_depth = len(Path(root).relative_to(resolved_path).parts)
            if rel_depth >= max_depth:
                dirs.clear()
                continue

            # Skip common non-source directories
            dirs[:] = [d for d in dirs if d not in {'.git', 'node_modules', '__pycache__', 'venv', '.venv', 'build', 'dist'}]

            for fname in files:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in all_extensions:
                    rel_path = str(fpath.relative_to(resolved_path))
                    result["files"].append(rel_path)

                    # Analyze files for classes and functions
                    content = _read_external_file(str(fpath))
                    if content:
                        classes, functions = _extract_definitions(content, str(fpath))
                        result["classes"].extend(classes)
                        result["functions"].extend(functions)

                        # Extract module name
                        module_name = fpath.stem
                        if module_name not in ['__init__', '__main__']:
                            result["modules"].append({
                                "name": module_name,
                                "path": rel_path,
                                "classes": [c["name"] for c in classes if c.get("file") == rel_path],
                                "functions": [f["name"] for f in functions if f.get("file") == rel_path]
                            })

    except Exception as e:
        result["error"] = str(e)

    return result


def _read_external_file(filepath: str, max_lines: int = 500) -> Optional[str]:
    """Read content from an external file.

    Args:
        filepath: Path to the file
        max_lines: Maximum lines to read

    Returns:
        File content or None if read fails
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line)
            return ''.join(lines)
    except Exception:
        return None


def _extract_definitions(content: str, filepath: str) -> Tuple[List[Dict], List[Dict]]:
    """Extract class and function definitions from code content.

    Args:
        content: Source code content
        filepath: Path to the source file

    Returns:
        Tuple of (classes, functions) where each is a list of dicts
    """
    classes = []
    functions = []

    lang_config = {
        "python": {
            "extensions": {".py"},
            "class_pattern": r'^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\([^)]*\))?\s*:',
            "func_pattern": r'^(?:    )?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*(?:->.*?)?:',
        },
        "javascript": {
            "extensions": {".js", ".ts", ".jsx", ".tsx"},
            "class_pattern": r'(?:export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)',
            "func_pattern": r'(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)',
        },
    }

    file_ext = Path(filepath).suffix.lower()
    for lang, config in lang_config.items():
        if file_ext in config["extensions"]:
            # Extract classes
            class_pattern = config.get("class_pattern")
            if class_pattern:
                for match in re.finditer(class_pattern, content, re.MULTILINE):
                    classes.append({
                        "name": match.group(1),
                        "file": filepath,
                        "line": content[:match.start()].count('\n') + 1
                    })

            # Extract functions
            func_pattern = config.get("func_pattern")
            if func_pattern:
                for match in re.finditer(func_pattern, content, re.MULTILINE):
                    func_name = match.group(1)
                    if not func_name.startswith('_') or func_name.startswith('__'):
                        functions.append({
                            "name": func_name,
                            "file": filepath,
                            "line": content[:match.start()].count('\n') + 1
                        })
            break
    return classes, functions


def _format_external_findings(scan_results: List[Dict[str, Any]]) -> str:
    """Format external directory scan results for display and LLM context.

    Args:
        scan_results: List of scan result dictionaries

    Returns:
        Formatted string summary
    """
    if not scan_results:
        return ""

    parts = ["=" * 60, "EXTERNAL DIRECTORY ANALYSIS", "=" * 60]

    for result in scan_results:
        parts.append(f"\n📂 External Path: {result['path']}")

        if not result.get("exists"):
            parts.append(f"   ❌ Path does not exist")
            continue

        if result.get("error"):
            parts.append(f"   ⚠️  Error: {result['error']}")
            continue

        file_count = len(result.get("files", []))
        class_count = len(result.get("classes", []))
        func_count = len(result.get("functions", []))

        parts.append(f"   Files: {file_count} | Classes: {class_count} | Functions: {func_count}")

        # List key classes found
        if result.get("classes"):
            parts.append("\n   📋 Classes Found:")
            for cls in result["classes"][:15]:  # Limit display
                parts.append(f"      - {cls['name']} ({cls['file']}:{cls.get('line', '?')})")
            if len(result["classes"]) > 15:
                parts.append(f"      ... and {len(result['classes']) - 15} more")

        # List key functions found
        if result.get("functions"):
            parts.append("\n   🔧 Top Functions/Methods Found:")
            for func in result["functions"][:10]:  # Limit display
                parts.append(f"      - {func['name']} ({func['file']}:{func.get('line', '?')})")
            if len(result["functions"]) > 10:
                parts.append(f"      ... and {len(result['functions']) - 10} more")

        # List modules
        if result.get("modules"):
            parts.append("\n   📦 Modules Found:")
            for mod in result["modules"][:10]:
                class_list = ', '.join(mod.get('classes', [])[:3])
                if class_list:
                    parts.append(f"      - {mod['name']}: {class_list}")
                else:
                    parts.append(f"      - {mod['name']}")

    parts.append("=" * 60)
    return '\n'.join(parts)


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

    # PRE-FLIGHT: Detect and scan external paths mentioned in the request
    external_paths = _detect_external_paths(user_request)
    external_scan_results = []

    if external_paths:
        print(f"\n🔍 PRE-FLIGHT: Detected {len(external_paths)} external path(s)")
        for ext_path in external_paths:
            print(f"   → Scanning external path: {ext_path}")
            scan_result = _scan_external_directory(ext_path)
            external_scan_results.append(scan_result)

            # Add external classes/functions to findings with specific names
            if scan_result.get("classes"):
                for cls in scan_result["classes"]:
                    class_name = cls['name']
                    # Track the specific class name for planner use
                    findings.external_classes.append(class_name)
                    findings.similar_implementations.append({
                        "file": f"{ext_path}/{cls['file']}",
                        "description": f"Class '{class_name}' from external source (line {cls.get('line', '?')})"
                    })

            if scan_result.get("functions"):
                for func in scan_result["functions"]:
                    func_name = func['name']
                    # Track the specific function name for planner use
                    findings.external_functions.append(func_name)

            if scan_result.get("modules"):
                for mod in scan_result["modules"]:
                    if mod.get("classes"):
                        findings.architecture_notes.append(
                            f"External module '{mod['name']}' contains: {', '.join(mod['classes'][:5])}"
                        )

        # Store full external findings for downstream use
        findings.external_findings = external_scan_results

        # Display external findings
        if external_scan_results:
            ext_summary = _format_external_findings(external_scan_results)
            if ext_summary:
                print(ext_summary)

            # Add warning if external paths couldn't be accessed
            for result in external_scan_results:
                if not result.get("exists"):
                    findings.warnings.append(
                        f"External path '{result['path']}' does not exist or cannot be accessed. "
                        "Cannot identify specific items to port."
                    )
                elif not result.get("classes") and not result.get("functions"):
                    findings.warnings.append(
                        f"External path '{result['path']}' exists but no classes/functions were found. "
                        "Manual inspection may be needed."
                    )

            # If we found external items, add them as a summary note
            if findings.external_classes:
                findings.architecture_notes.append(
                    f"EXTERNAL CLASSES TO PORT: {', '.join(findings.external_classes[:20])}"
                )
            if findings.external_functions:
                top_funcs = [f for f in findings.external_functions if not f.startswith('test_')][:10]
                if top_funcs:
                    findings.architecture_notes.append(
                        f"EXTERNAL FUNCTIONS TO PORT: {', '.join(top_funcs)}"
                    )

    # Extract keywords for searching
    keywords = _extract_search_keywords(user_request)
    print(f"→ Searching for: {', '.join(keywords[:5])}")

    # Sequential research tasks to avoid parallel threads
    research_steps = [
        ("code_search", lambda: _search_relevant_code(keywords)),
        ("structure", _analyze_project_structure),
    ]

    if use_rag and not quick_mode:
        research_steps.append(("rag_search", lambda: _rag_search(user_request, 10, budget, repo_stats)))

    if not quick_mode:
        research_steps.append(("similar", lambda: _find_similar_implementations(user_request, keywords)))

    if not quick_mode and search_depth in ["medium", "deep"]:
        research_steps.append(("dependencies", lambda: _analyze_dependencies(keywords)))

    for task_name, step in research_steps:
        try:
            result = step()
            if task_name == "code_search":
                findings.relevant_files = result.get("files", [])
                findings.code_patterns = result.get("patterns", [])
            elif task_name == "rag_search":
                rag_files = result.get("files", [])
                existing_paths = {f['path'] for f in findings.relevant_files}
                for rag_file in rag_files:
                    if rag_file['path'] not in existing_paths:
                        findings.relevant_files.append(rag_file)
                for chunk in result.get("chunks", [])[:3]:
                    findings.code_patterns.append(f"RAG: {chunk['location']}")
            elif task_name == "structure":
                findings.architecture_notes = result.get("notes", [])
            elif task_name == "similar":
                findings.similar_implementations = result.get("implementations", [])
            elif task_name == "dependencies":
                findings.dependencies = result.get("dependencies", [])
                findings.potential_conflicts = result.get("conflicts", [])
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
    lang_config = {
        "c_cpp": {
            "keywords": {"memory", "buffer", "overflow", "strcpy", "strcat", "sprintf", "gets", "scanf", "malloc", "calloc", "realloc", "free", "memcpy", "memmove", "memset", "sizeof", "strlen"},
            "patterns": [r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b'],
        },
        "driver": {
            "keywords": {"driver", "kernel", "ioctl", "IOCTL", "DeviceIoControl", "IRP", "ProbeFor"},
        },
        "database": {
            "keywords": {"prisma", "schema", "database", "enum", "model", "migration", "sequelize", "typeorm", "mongoose", "sql", "table", "entity", "CREATE TABLE", "ALTER TABLE", "@db", "@relation"},
            "patterns": [r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b'],
        },
        "docs": {
            "keywords": {"readme", "documentation", "docs", "api documentation", "guide", "tutorial", "# ", "## "},
        },
        "code_structure": {
            "keywords": {"class", "interface", "type", "typedef", "struct", "enum", "def class", "@dataclass"},
            "patterns": [r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b'],
        },
        "config": {
            "keywords": {"config", "configuration", "settings", "environment", ".env", "CONFIG", "SETTINGS", "dotenv"},
        }
    }

    request_lower = user_request.lower()
    extracted_keywords = set()

    for lang, config in lang_config.items():
        if any(keyword in request_lower for keyword in config["keywords"]):
            extracted_keywords.update(config["keywords"])
            for pattern in config.get("patterns", []):
                extracted_keywords.update(re.findall(pattern, user_request))

    if extracted_keywords:
        return list(extracted_keywords)[:20]

    # Fallback to original logic
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'with', 'all', 'my', 'this', 'that', 'add', 'create', 'make', 'implement',
        'fix', 'update', 'change', 'modify', 'please', 'can', 'you', 'i', 'want',
        'find', 'other', 'related', 'after', 'before', 'should', 'would', 'could',
        'any', 'without', 'risk', 'bugs'
    }
    words = re.findall(r'\b\w+\b', request_lower)
    keywords = {w for w in words if len(w) > 2 and w not in stop_words}
    keywords.update({w.lower() for w in re.findall(r'[A-Z][a-z]+(?:[A-Z][a-z]+)*', user_request)})
    keywords.update(re.findall(r'[a-z]+_[a-z_]+', request_lower))
    return list(keywords)[:10]


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
        {"role": "user", "content": f"""Analyze this research for the task: "{user_request}""

Research findings:
{chr(10).join(context_parts)}

Suggest the best approach and identify any concerns."""}
    ]

    response = ollama_chat(messages) or {}
    if not isinstance(response, dict):
        return {"approach": None, "complexity": "medium", "warnings": []}

    if "error" in response:
        return {"approach": None, "complexity": "medium", "warnings": []}

    try:
        content = response.get("message", {}).get("content", "") if isinstance(response, dict) else ""
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