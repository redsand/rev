#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simple RAG implementation using keyword-based retrieval.

This provides a lightweight, dependency-free RAG implementation that uses
TF-IDF-like scoring for code retrieval without requiring external libraries.
"""

import re
import fnmatch
import json
import math
import time
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple
from collections import Counter

from rev import config
from rev.retrieval.base import BaseCodeRetriever, CodeChunk
from rev.config import EXCLUDE_DIRS
from rev.retrieval.symbol_index import SymbolIndexer
from rev.retrieval.import_graph import ImportGraph
from rev.retrieval.code_queries import CodeQueryEngine


class SimpleCodeRetriever(BaseCodeRetriever):
    """Simple keyword-based code retriever.

    Uses bag-of-words with TF-IDF-like scoring to rank code chunks
    by relevance to a natural language query.
    """

    def __init__(self, root: Path = None, chunk_size: int = 50, enable_code_aware: bool = True):
        """Initialize the simple retriever.

        Args:
            root: Root directory of the codebase
            chunk_size: Number of lines per chunk
            enable_code_aware: Enable code-aware features (symbol indexing, import graph)
        """
        super().__init__(root)
        self.chunk_size = chunk_size
        self.chunks: List[CodeChunk] = []
        self.term_document_freq: Dict[str, int] = {}  # IDF calculation
        self.total_documents = 0
        self.cache_version = 1

        # Code-aware components
        self.enable_code_aware = enable_code_aware
        self.symbol_index: Optional[SymbolIndexer] = None
        self.import_graph: Optional[ImportGraph] = None
        self.query_engine: Optional[CodeQueryEngine] = None

        if enable_code_aware and root:
            self.symbol_index = SymbolIndexer(root)
            self.import_graph = ImportGraph(root)
            self.query_engine = CodeQueryEngine(self.symbol_index, self.import_graph)

    def _cache_path(self) -> Path:
        """Location for persisted index cache."""
        cache_dir = config.CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        root_id = hashlib.sha1(str(self.root.resolve()).encode("utf-8")).hexdigest()[:12]
        return cache_dir / f"rag_index_{root_id}_{self.chunk_size}.json"

    def _load_cache(self, cache_path: Path) -> bool:
        """Load an index from cache if available."""
        if not cache_path.exists():
            return False
        try:
            start = time.perf_counter()
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if payload.get("version") != self.cache_version:
                return False

            self.chunk_size = payload.get("chunk_size", self.chunk_size)
            self.total_documents = payload.get("total_documents", 0)
            self.term_document_freq = payload.get("term_document_freq", {})
            self.chunks = [CodeChunk(**chunk) for chunk in payload.get("chunks", [])]
            self.index_built = True
            duration = time.perf_counter() - start
            print(f"    Loaded RAG index from {cache_path} ({len(self.chunks)} chunks, {duration:.2f}s)")
            return True
        except Exception:
            return False

    def _save_cache(self, cache_path: Path) -> None:
        """Persist the built index to cache."""
        try:
            payload = {
                "version": self.cache_version,
                "root": str(self.root),
                "chunk_size": self.chunk_size,
                "total_documents": self.total_documents,
                "term_document_freq": self.term_document_freq,
                "chunks": [c.to_dict() for c in self.chunks],
            }
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            print(f"    Saved RAG index to {cache_path}")
        except Exception:
            # Best-effort persistence; ignore failures
            pass

    def build_index(self, root: Optional[Path] = None, repo_stats: Optional[Dict[str, Any]] = None, budget=None) -> None:
        """Build the search index by chunking code files.

        Args:
            root: Root directory to index
        """
        if root:
            self.root = Path(root)

        file_count = (repo_stats or {}).get("file_count", 0)
        if file_count and file_count > 2000:
            print("    Skipping RAG index (repo too large)")
            return
        if budget and budget.get_remaining().get("tokens", 100) < 10:
            print("    Skipping RAG index (token budget too low)")
            return

        cache_path = self._cache_path()

        self.chunks = []
        self.term_document_freq = {}
        self.total_documents = 0

        # Supported file extensions
        code_extensions = {
            ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c", ".h",
            ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
            ".sh", ".bash", ".yaml", ".yml", ".json", ".xml", ".md"
        }

        start = time.perf_counter()

        # Index all code files
        for file_path in self.root.rglob("*"):
            # Skip excluded directories
            if any(excluded in file_path.parts for excluded in EXCLUDE_DIRS):
                continue

            # Only process code files
            if file_path.suffix not in code_extensions:
                continue

            if not file_path.is_file():
                continue

            try:
                self._index_file(file_path)
            except Exception as e:
                # Skip files that can't be read
                continue

        # Build IDF index
        self._build_idf_index()

        # Build code-aware indices if enabled
        if self.enable_code_aware:
            try:
                print("    Building symbol index...")
                self.symbol_index.build_index()

                print("    Building import graph...")
                self.import_graph.build_graph()

                # Update query engine
                self.query_engine = CodeQueryEngine(self.symbol_index, self.import_graph)
            except Exception as e:
                print(f"    Warning: Code-aware indexing failed: {e}")
                self.enable_code_aware = False

        self.index_built = True
        duration = time.perf_counter() - start
        print(f"    Built RAG index with {len(self.chunks)} chunks in {duration:.2f}s")
        if self.enable_code_aware:
            stats = self.symbol_index.get_stats() if self.symbol_index else {}
            print(f"    Indexed {stats.get('total_symbols', 0)} symbols across {stats.get('files', 0)} files")
        self._save_cache(cache_path)

    def _index_file(self, file_path: Path) -> None:
        """Index a single file by chunking it.

        Args:
            file_path: Path to the file to index
        """
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return

        lines = content.splitlines()
        relative_path = str(file_path.relative_to(self.root))

        # Create chunks
        for i in range(0, len(lines), self.chunk_size):
            chunk_lines = lines[i:i + self.chunk_size]
            chunk_content = "\n".join(chunk_lines)

            # Determine chunk type
            chunk_type = self._detect_chunk_type(chunk_content, file_path.suffix)

            chunk = CodeChunk(
                path=relative_path,
                start_line=i + 1,
                end_line=min(i + self.chunk_size, len(lines)),
                content=chunk_content,
                chunk_type=chunk_type,
                metadata={
                    "language": self._detect_language(file_path.suffix),
                    "file_type": file_path.suffix
                }
            )

            self.chunks.append(chunk)
            self.total_documents += 1

    def _detect_chunk_type(self, content: str, suffix: str) -> str:
        """Detect the type of code chunk."""
        content_lower = content.lower()

        if "test" in content_lower or suffix == ".test.py":
            return "test"
        elif content.strip().startswith('"""') or content.strip().startswith("'''"):
            return "docstring"
        elif content.strip().startswith("#") or content.strip().startswith("//"):
            return "comment"
        else:
            return "code"

    def _detect_language(self, suffix: str) -> str:
        """Detect language from file suffix."""
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".cs": "csharp",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala"
        }
        return lang_map.get(suffix, "unknown")

    def _build_idf_index(self) -> None:
        """Build inverse document frequency index."""
        self.term_document_freq = {}

        for chunk in self.chunks:
            terms = self._tokenize(chunk.content)
            unique_terms = set(terms)

            for term in unique_terms:
                self.term_document_freq[term] = self.term_document_freq.get(term, 0) + 1

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into terms.

        Converts to lowercase, splits on non-alphanumeric,
        and filters short terms.
        """
        # Simple tokenization: lowercase, split on non-alphanumeric
        text_lower = text.lower()
        terms = re.findall(r'\b\w+\b', text_lower)

        # Filter out very short terms and common stop words
        stop_words = {
            "a", "an", "and", "are", "as", "at", "be", "by", "for",
            "from", "in", "is", "it", "of", "on", "or", "that", "the",
            "to", "was", "will", "with"
        }

        return [t for t in terms if len(t) > 2 and t not in stop_words]

    def _compute_tfidf_score(self, query_terms: List[str], chunk: CodeChunk) -> float:
        """Compute TF-IDF score for a chunk given query terms.

        Args:
            query_terms: Tokenized query terms
            chunk: Code chunk to score

        Returns:
            TF-IDF relevance score
        """
        chunk_terms = self._tokenize(chunk.content)
        term_freq = Counter(chunk_terms)

        score = 0.0
        for term in query_terms:
            if term not in term_freq:
                continue

            # TF: term frequency in chunk
            tf = term_freq[term] / len(chunk_terms) if chunk_terms else 0

            # IDF: inverse document frequency
            doc_freq = self.term_document_freq.get(term, 0)
            if doc_freq > 0:
                idf = math.log(self.total_documents / doc_freq)
            else:
                idf = 0

            # TF-IDF
            score += tf * idf

        return score

    def query(self, question: str, k: int = 10, filters: Optional[Dict[str, Any]] = None) -> List[CodeChunk]:
        """Query for relevant code chunks.

        Supports both semantic search and structure-aware queries:
        - "find callers: function_name" - Find all call sites
        - "find implementers: BaseClass" - Find all subclasses
        - "find usages: symbol_name" - Find all symbol references
        - Regular queries use TF-IDF semantic search

        Args:
            question: Natural language question or search query
            k: Number of top results to return
            filters: Optional filters (language, chunk_type, file_pattern)

        Returns:
            List of top-k code chunks ranked by relevance
        """
        if not self.index_built:
            raise RuntimeError("Index not built. Call build_index() first.")

        # Check for structure-aware queries
        if self.enable_code_aware and self.query_engine:
            if question.lower().startswith("find callers:"):
                return self._handle_find_callers(question, k)
            elif question.lower().startswith("find implementers:"):
                return self._handle_find_implementers(question, k)
            elif question.lower().startswith("find usages:"):
                return self._handle_find_usages(question, k)

        # Fall back to semantic search
        # Tokenize query
        query_terms = self._tokenize(question)

        # Pre-compile file pattern (regex or glob) to avoid per-chunk failures
        file_pattern_regex = None
        if filters and filters.get("file_pattern"):
            raw_pattern = str(filters["file_pattern"]).strip()
            normalized_pattern = raw_pattern.replace("\\", "/")
            try:
                file_pattern_regex = re.compile(normalized_pattern)
            except re.error:
                # Fallback: treat pattern as a glob and translate to regex
                try:
                    file_pattern_regex = re.compile(fnmatch.translate(normalized_pattern))
                except re.error:
                    print(f"    Warning: Invalid file_pattern filter '{raw_pattern}'; ignoring this filter")
                    file_pattern_regex = None

        def _passes_filters(chunk: CodeChunk, *, skip_file_pattern: bool = False) -> bool:
            if not filters:
                return True
            if "language" in filters and chunk.metadata.get("language") != filters["language"]:
                return False
            if "chunk_type" in filters and chunk.chunk_type != filters["chunk_type"]:
                return False
            if file_pattern_regex and not skip_file_pattern:
                normalized_path = chunk.path.replace("\\", "/")
                if not file_pattern_regex.search(normalized_path):
                    return False
            return True

        # Score all chunks
        scored_chunks = []
        for chunk in self.chunks:
            if not _passes_filters(chunk):
                continue

            # Compute score
            score = self._compute_tfidf_score(query_terms, chunk)

            if score > 0:
                chunk.score = score
                scored_chunks.append(chunk)

        # Fallback: if file_pattern filtering produced nothing, retry without that filter to avoid assuming code lives in ./src.
        if not scored_chunks and file_pattern_regex:
            for chunk in self.chunks:
                if not _passes_filters(chunk, skip_file_pattern=True):
                    continue
                score = self._compute_tfidf_score(query_terms, chunk)
                if score > 0:
                    chunk.score = score
                    scored_chunks.append(chunk)

        # Sort by score descending
        scored_chunks.sort(key=lambda c: c.score, reverse=True)

        # Return top-k
        return scored_chunks[:k]

    def _handle_find_callers(self, question: str, k: int) -> List[CodeChunk]:
        """Handle 'find callers:' query."""
        function_name = question.split(":", 1)[1].strip()
        locations = self.query_engine.find_callers(function_name)
        return self._locations_to_chunks(locations, k)

    def _handle_find_implementers(self, question: str, k: int) -> List[CodeChunk]:
        """Handle 'find implementers:' query."""
        base_class = question.split(":", 1)[1].strip()
        symbols = self.query_engine.find_implementers(base_class)
        return self._symbols_to_chunks(symbols, k)

    def _handle_find_usages(self, question: str, k: int) -> List[CodeChunk]:
        """Handle 'find usages:' query."""
        symbol_name = question.split(":", 1)[1].strip()
        locations = self.query_engine.find_usages(symbol_name)
        return self._locations_to_chunks(locations, k)

    def _locations_to_chunks(self, locations: List[Tuple[Path, int]], k: int) -> List[CodeChunk]:
        """Convert (file, line) locations to code chunks."""
        chunks = []

        for file_path, line_num in locations[:k]:
            # Find chunk containing this line
            relative_path = str(file_path.relative_to(self.root))
            for chunk in self.chunks:
                if chunk.path == relative_path and chunk.start_line <= line_num <= chunk.end_line:
                    chunk.score = 1.0  # All equally relevant
                    chunks.append(chunk)
                    break

        return chunks[:k]

    def _symbols_to_chunks(self, symbols, k: int) -> List[CodeChunk]:
        """Convert Symbol objects to code chunks."""
        chunks = []

        for symbol in symbols[:k]:
            # Find chunk containing this symbol
            relative_path = str(symbol.file_path.relative_to(self.root))
            for chunk in self.chunks:
                if chunk.path == relative_path and chunk.start_line <= symbol.line_number <= chunk.end_line:
                    chunk.score = 1.0
                    chunks.append(chunk)
                    break

        return chunks[:k]

    def get_index_stats(self) -> Dict[str, Any]:
        """Get statistics about the current index."""
        stats = super().get_index_stats()
        stats.update({
            "total_chunks": len(self.chunks),
            "total_terms": len(self.term_document_freq),
            "chunk_size": self.chunk_size,
            "by_language": {},
            "by_type": {}
        })

        # Count by language and type
        for chunk in self.chunks:
            lang = chunk.metadata.get("language", "unknown")
            stats["by_language"][lang] = stats["by_language"].get(lang, 0) + 1

            chunk_type = chunk.chunk_type
            stats["by_type"][chunk_type] = stats["by_type"].get(chunk_type, 0) + 1

        return stats

    def clear_index(self) -> None:
        """Clear the current index."""
        super().clear_index()
        self.chunks = []
        self.term_document_freq = {}
        self.total_documents = 0
