#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ContextBuilder: unified retrieval pipeline for agent context.

Contract: this module is the single pipeline responsible for selecting:
- selected_code_chunks
- selected_docs_chunks
- selected_tool_schemas (with examples)
- selected_memory_items

Agents should consume only the rendered output of this pipeline + the selected
tool schemas when calling the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from rev import config
from rev.config import EXCLUDE_DIRS


_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for",
    "from", "in", "is", "it", "of", "on", "or", "that", "the",
    "to", "was", "will", "with", "into", "within", "each",
}


def _tokenize(text: str) -> List[str]:
    terms = re.findall(r"\b\w+\b", (text or "").lower())
    return [t for t in terms if len(t) > 2 and t not in _STOP_WORDS]


def _overlap_score(query_terms: Sequence[str], text: str) -> float:
    if not query_terms:
        return 0.0
    hay = set(_tokenize(text))
    if not hay:
        return 0.0
    hit = sum(1 for t in query_terms if t in hay)
    return hit / max(1, len(set(query_terms)))


def _rerank_chunks(query: str, chunks: Sequence[RetrievedChunk]) -> List[RetrievedChunk]:
    """Second-stage rerank: boost explicit path/identifier matches."""

    q = (query or "").lower()
    boosted: List[RetrievedChunk] = []
    for c in chunks:
        bonus = 0.0
        src = (c.source or "").lower()
        base = c.score
        if src and (src in q or Path(src).name.lower() in q):
            bonus += 0.5
        # Prefer chunks whose location is explicitly referenced.
        if c.location and c.location.lower() in q:
            bonus += 0.3
        boosted.append(RetrievedChunk(**{**c.__dict__, "score": base + bonus}))
    boosted.sort(key=lambda x: x.score, reverse=True)
    return boosted

@dataclass(frozen=True)
class RetrievedChunk:
    corpus: str  # "code" | "docs" | "tools" | "memory"
    source: str  # file path or tool name
    location: str  # human-friendly locator (path:line, heading, etc.)
    score: float
    content: str
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class RetrievedTool:
    name: str
    schema: Dict[str, Any]  # OpenAI tool schema-like dict (function + params)
    example: str  # short JSON example
    score: float


@dataclass(frozen=True)
class ContextBundle:
    selected_code_chunks: List[RetrievedChunk]
    selected_docs_chunks: List[RetrievedChunk]
    selected_tool_schemas: List[RetrievedTool]
    selected_memory_items: List[RetrievedChunk]


class CodeCorpus:
    """Lightweight code corpus index (token-overlap ranking)."""

    VERSION = 1

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._chunks: List[RetrievedChunk] = []
        self._built = False

    def _cache_path(self) -> Path:
        cache_dir = config.CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        root_id = hashlib.sha1(str(self.root).encode("utf-8")).hexdigest()[:12]
        return cache_dir / f"context_code_{root_id}.json"

    def _iter_files(self) -> Iterable[Path]:
        for file_path in self.root.rglob("*.py"):
            if any(excluded in file_path.parts for excluded in EXCLUDE_DIRS):
                continue
            if not file_path.is_file():
                continue
            yield file_path

    def _chunk_python_file(self, file_path: Path) -> List[RetrievedChunk]:
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []

        lines = text.splitlines()
        if not lines:
            return []

        chunks: List[RetrievedChunk] = []
        # Heuristic chunking by defs/classes (fast, avoids AST dependency).
        starts = []
        for idx, line in enumerate(lines, start=1):
            if re.match(r"^\s*(class|def)\s+\w+", line):
                starts.append(idx)
        if not starts:
            starts = [1]
        starts.append(len(lines) + 1)

        for i in range(len(starts) - 1):
            start = starts[i]
            end = starts[i + 1] - 1
            # Cap chunk size to avoid massive blocks
            if end - start + 1 > 240:
                end = start + 239
            content = "\n".join(lines[start - 1 : end])
            rel = str(file_path.relative_to(self.root)).replace("\\", "/")
            chunks.append(
                RetrievedChunk(
                    corpus="code",
                    source=rel,
                    location=f"{rel}:{start}",
                    score=0.0,
                    content=content,
                    metadata={"file": rel, "start_line": start, "end_line": end, "language": "python"},
                )
            )
        return chunks

    def _load(self) -> bool:
        cache_path = self._cache_path()
        if not cache_path.exists():
            return False
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if payload.get("version") != self.VERSION:
                return False
            if payload.get("root") != str(self.root):
                return False
            self._chunks = [RetrievedChunk(**c) for c in payload.get("chunks", [])]
            self._built = True
            return True
        except Exception:
            return False

    def _save(self) -> None:
        try:
            payload = {"version": self.VERSION, "root": str(self.root), "chunks": [c.__dict__ for c in self._chunks]}
            self._cache_path().write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass

    def build(self) -> None:
        if self._built:
            return
        if self._load():
            return
        start = time.perf_counter()
        chunks: List[RetrievedChunk] = []
        for fp in self._iter_files():
            chunks.extend(self._chunk_python_file(fp))
        self._chunks = chunks
        self._built = True
        self._save()
        _ = time.perf_counter() - start

    def query(self, query: str, k: int) -> List[RetrievedChunk]:
        self.build()
        q_terms = _tokenize(query)
        scored: List[RetrievedChunk] = []
        for c in self._chunks:
            score = _overlap_score(q_terms, c.content + "\n" + c.source)
            if score <= 0:
                continue
            scored.append(RetrievedChunk(**{**c.__dict__, "score": score}))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:k]


class DocsCorpus:
    """Markdown/doc corpus index (chunks by heading)."""

    VERSION = 1

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._chunks: List[RetrievedChunk] = []
        self._built = False

    def _cache_path(self) -> Path:
        cache_dir = config.CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        root_id = hashlib.sha1(str(self.root).encode("utf-8")).hexdigest()[:12]
        return cache_dir / f"context_docs_{root_id}.json"

    def _iter_files(self) -> Iterable[Path]:
        patterns = ("README.md",)
        for name in patterns:
            fp = self.root / name
            if fp.exists() and fp.is_file():
                yield fp
        for fp in self.root.rglob("*.md"):
            if any(excluded in fp.parts for excluded in EXCLUDE_DIRS):
                continue
            if not fp.is_file():
                continue
            yield fp

    def _chunk_markdown(self, fp: Path) -> List[RetrievedChunk]:
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        lines = text.splitlines()
        if not lines:
            return []

        headings: List[Tuple[int, str]] = []
        for i, line in enumerate(lines, start=1):
            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                headings.append((i, m.group(2).strip()))
        if not headings:
            headings = [(1, fp.name)]
        headings.append((len(lines) + 1, "__end__"))

        rel = str(fp.relative_to(self.root)).replace("\\", "/")
        chunks: List[RetrievedChunk] = []
        for idx in range(len(headings) - 1):
            start, title = headings[idx]
            end = headings[idx + 1][0] - 1
            if end - start + 1 > 240:
                end = start + 239
            content = "\n".join(lines[start - 1 : end])
            chunks.append(
                RetrievedChunk(
                    corpus="docs",
                    source=rel,
                    location=f"{rel}#{title}",
                    score=0.0,
                    content=content,
                    metadata={"file": rel, "heading": title, "start_line": start, "end_line": end},
                )
            )
        return chunks

    def _load(self) -> bool:
        cache_path = self._cache_path()
        if not cache_path.exists():
            return False
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if payload.get("version") != self.VERSION:
                return False
            if payload.get("root") != str(self.root):
                return False
            self._chunks = [RetrievedChunk(**c) for c in payload.get("chunks", [])]
            self._built = True
            return True
        except Exception:
            return False

    def _save(self) -> None:
        try:
            payload = {"version": self.VERSION, "root": str(self.root), "chunks": [c.__dict__ for c in self._chunks]}
            self._cache_path().write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass

    def build(self) -> None:
        if self._built:
            return
        if self._load():
            return
        chunks: List[RetrievedChunk] = []
        for fp in self._iter_files():
            chunks.extend(self._chunk_markdown(fp))
        self._chunks = chunks
        self._built = True
        self._save()

    def query(self, query: str, k: int) -> List[RetrievedChunk]:
        self.build()
        q_terms = _tokenize(query)
        scored: List[RetrievedChunk] = []
        for c in self._chunks:
            score = _overlap_score(q_terms, c.content + "\n" + c.location)
            if score <= 0:
                continue
            scored.append(RetrievedChunk(**{**c.__dict__, "score": score}))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:k]


class ToolsCorpus:
    """Tool schemas + usage examples corpus (one entry per tool)."""

    def __init__(self):
        self._entries: List[RetrievedTool] = []
        self._built = False

    def build(self, tools: Sequence[Dict[str, Any]]) -> None:
        if self._built:
            return
        entries: List[RetrievedTool] = []
        for tool in tools:
            fn = tool.get("function", {}) if isinstance(tool, dict) else {}
            name = fn.get("name")
            if not isinstance(name, str):
                continue
            schema = tool
            example = self._make_example(name, fn.get("parameters") or {})
            entries.append(RetrievedTool(name=name, schema=schema, example=example, score=0.0))
        self._entries = entries
        self._built = True

    def _make_example(self, name: str, params_schema: Dict[str, Any]) -> str:
        required = params_schema.get("required") or []
        props = params_schema.get("properties") or {}
        args: Dict[str, Any] = {}
        for key in required:
            spec = props.get(key, {})
            t = spec.get("type")
            if t == "integer":
                args[key] = 1
            elif t == "number":
                args[key] = 1.0
            elif t == "boolean":
                args[key] = False
            elif t == "array":
                args[key] = []
            elif t == "object":
                args[key] = {}
            else:
                args[key] = "<value>"
        payload = {"tool_name": name, "arguments": args}
        return json.dumps(payload, indent=2)

    def query(self, query: str, k: int) -> List[RetrievedTool]:
        q_terms = _tokenize(query)
        q_lower = (query or "").lower()
        scored: List[RetrievedTool] = []
        for t in self._entries:
            fn = t.schema.get("function", {}) if isinstance(t.schema, dict) else {}
            hay = f"{t.name}\n{fn.get('description','')}\n{json.dumps(fn.get('parameters', {}))}"
            score = _overlap_score(q_terms, hay)

            # Second-stage boosts for common intent signals.
            name_lower = t.name.lower()
            if name_lower in q_lower:
                score += 0.35
            if "read" in q_lower or ".py" in q_lower or "file" in q_lower:
                if name_lower in {"read_file", "read_file_lines", "get_file_info"}:
                    score += 0.2
            if "search" in q_lower or "find" in q_lower or "grep" in q_lower:
                if name_lower in {"search_code", "rag_search"}:
                    score += 0.2
            if "edit" in q_lower or "replace" in q_lower or "update" in q_lower:
                if name_lower in {"replace_in_file", "apply_patch"}:
                    score += 0.2
            if "create" in q_lower or "mkdir" in q_lower or "directory" in q_lower:
                if name_lower == "create_directory":
                    score += 0.25
            if "test" in q_lower or "pytest" in q_lower:
                if name_lower in {"run_tests", "run_cmd"}:
                    score += 0.15

            if score <= 0:
                continue
            scored.append(RetrievedTool(name=t.name, schema=t.schema, example=t.example, score=score))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:k]


class MemoryCorpus:
    """Session memory corpus backed by RevContext fields (no persistence)."""

    def query(self, query: str, memory_items: Sequence[Tuple[str, str]], k: int) -> List[RetrievedChunk]:
        q_terms = _tokenize(query)
        scored: List[RetrievedChunk] = []
        for key, text in memory_items:
            score = _overlap_score(q_terms, f"{key}\n{text}")
            if score <= 0:
                continue
            scored.append(
                RetrievedChunk(
                    corpus="memory",
                    source=key,
                    location=key,
                    score=score,
                    content=text,
                    metadata={"key": key},
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:k]


class ProjectMemoryCorpus:
    """Durable project memory corpus backed by `.rev/memory/project_summary.md`."""

    VERSION = 1

    def __init__(self, memory_file: Path):
        self.memory_file = memory_file
        self._chunks: List[RetrievedChunk] = []
        self._built = False

    def _cache_path(self) -> Path:
        cache_dir = config.CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        root_id = hashlib.sha1(str(config.ROOT.resolve()).encode("utf-8")).hexdigest()[:12]
        return cache_dir / f"context_project_memory_{root_id}.json"

    def _chunk_markdown(self, md: str) -> List[RetrievedChunk]:
        lines = (md or "").splitlines()
        if not lines:
            return []

        headings: List[Tuple[int, str]] = []
        for i, line in enumerate(lines, start=1):
            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                headings.append((i, m.group(2).strip()))
        if not headings:
            headings = [(1, "Project Memory")]
        headings.append((len(lines) + 1, "__end__"))

        rel = self.memory_file.relative_to(config.ROOT).as_posix() if self.memory_file.exists() else ".rev/memory/project_summary.md"
        chunks: List[RetrievedChunk] = []
        for idx in range(len(headings) - 1):
            start, title = headings[idx]
            end = headings[idx + 1][0] - 1
            if end - start + 1 > 200:
                end = start + 199
            content = "\n".join(lines[start - 1 : end])
            chunks.append(
                RetrievedChunk(
                    corpus="memory",
                    source=rel,
                    location=f"{rel}#{title}",
                    score=0.0,
                    content=content,
                    metadata={"file": rel, "heading": title, "start_line": start, "end_line": end},
                )
            )
        return chunks

    def _load(self) -> bool:
        cache_path = self._cache_path()
        if not cache_path.exists():
            return False
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if payload.get("version") != self.VERSION:
                return False
            self._chunks = [RetrievedChunk(**c) for c in payload.get("chunks", [])]
            self._built = True
            return True
        except Exception:
            return False

    def _save(self) -> None:
        try:
            payload = {"version": self.VERSION, "chunks": [c.__dict__ for c in self._chunks]}
            self._cache_path().write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass

    def build(self) -> None:
        if self._built:
            return
        # Try cache first (fast path).
        if self._load():
            return
        try:
            if not self.memory_file.exists():
                self._chunks = []
                self._built = True
                return
            md = self.memory_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            self._chunks = []
            self._built = True
            return
        self._chunks = self._chunk_markdown(md)
        self._built = True
        self._save()

    def query(self, query: str, k: int) -> List[RetrievedChunk]:
        self.build()
        q_terms = _tokenize(query)
        scored: List[RetrievedChunk] = []
        for c in self._chunks:
            score = _overlap_score(q_terms, c.content + "\n" + c.location)
            if score <= 0:
                continue
            scored.append(RetrievedChunk(**{**c.__dict__, "score": score}))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:k]

class ContextBuilder:
    """Unified context retrieval and tool selection pipeline."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.code = CodeCorpus(self.root)
        self.docs = DocsCorpus(self.root)
        self.tools = ToolsCorpus()
        self.memory = MemoryCorpus()
        self.project_memory = ProjectMemoryCorpus(config.PROJECT_MEMORY_FILE)

    def build(
        self,
        *,
        query: str,
        tool_universe: Sequence[Dict[str, Any]],
        tool_candidates: Optional[Sequence[str]] = None,
        top_k_code: int = 4,
        top_k_docs: int = 3,
        top_k_tools: int = 5,
        top_k_memory: int = 3,
        memory_items: Optional[Sequence[Tuple[str, str]]] = None,
    ) -> ContextBundle:
        self.tools.build(tool_universe)

        # Stage 1: retrieve top-K' per corpus.
        code_candidates = self.code.query(query, k=max(top_k_code * 3, top_k_code))
        docs_candidates = self.docs.query(query, k=max(top_k_docs * 3, top_k_docs))

        # Stage 2: rerank within each corpus.
        selected_code = _rerank_chunks(query, code_candidates)[:top_k_code]
        selected_docs = _rerank_chunks(query, docs_candidates)[:top_k_docs]

        tools_ranked = self.tools.query(query, k=max(top_k_tools, 12))
        if tool_candidates is not None:
            allowed = set(tool_candidates)
            tools_ranked = [t for t in tools_ranked if t.name in allowed]
        selected_tools = tools_ranked[:top_k_tools]

        mem_items = list(memory_items or [])
        mem_candidates: List[RetrievedChunk] = []
        mem_candidates.extend(self.project_memory.query(query, k=max(top_k_memory * 3, top_k_memory)))
        if mem_items:
            mem_candidates.extend(self.memory.query(query, mem_items, k=max(top_k_memory * 2, top_k_memory)))

        # Deduplicate by location while keeping order.
        deduped: List[RetrievedChunk] = []
        seen = set()
        for c in mem_candidates:
            key = (c.location or c.source or "")[:200]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(c)

        selected_mem = _rerank_chunks(query, deduped)[:top_k_memory]

        return ContextBundle(
            selected_code_chunks=selected_code,
            selected_docs_chunks=selected_docs,
            selected_tool_schemas=selected_tools,
            selected_memory_items=selected_mem,
        )

    def render(self, bundle: ContextBundle) -> str:
        parts: List[str] = []

        if bundle.selected_memory_items:
            parts.append("Selected memory:")
            for item in bundle.selected_memory_items:
                parts.append(f"- {item.location} (score={item.score:.2f})")
                parts.append(item.content.strip()[:400])

        if bundle.selected_docs_chunks:
            parts.append("\nSelected docs:")
            for chunk in bundle.selected_docs_chunks:
                parts.append(f"- {chunk.location} (score={chunk.score:.2f})")
                parts.append(chunk.content.strip()[:500])

        if bundle.selected_code_chunks:
            parts.append("\nSelected code:")
            for chunk in bundle.selected_code_chunks:
                parts.append(f"- {chunk.location} (score={chunk.score:.2f})")
                parts.append(chunk.content.strip()[:500])

        if bundle.selected_tool_schemas:
            parts.append("\nSelected tools (schema + example):")
            for tool in bundle.selected_tool_schemas:
                fn = tool.schema.get("function", {}) if isinstance(tool.schema, dict) else {}
                desc = fn.get("description", "")
                parts.append(f"- {tool.name} (score={tool.score:.2f}): {desc}".strip())
                parts.append("Example:")
                parts.append(tool.example)

        return "\n".join(parts).strip() + "\n"
