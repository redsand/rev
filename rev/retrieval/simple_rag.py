#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simple RAG implementation using keyword-based retrieval.

This provides a lightweight, dependency-free RAG implementation that uses
TF-IDF-like scoring for code retrieval without requiring external libraries.
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from collections import Counter
import math

from rev.retrieval.base import BaseCodeRetriever, CodeChunk
from rev.config import EXCLUDE_DIRS


class SimpleCodeRetriever(BaseCodeRetriever):
    """Simple keyword-based code retriever.

    Uses bag-of-words with TF-IDF-like scoring to rank code chunks
    by relevance to a natural language query.
    """

    def __init__(self, root: Path = None, chunk_size: int = 50):
        """Initialize the simple retriever.

        Args:
            root: Root directory of the codebase
            chunk_size: Number of lines per chunk
        """
        super().__init__(root)
        self.chunk_size = chunk_size
        self.chunks: List[CodeChunk] = []
        self.term_document_freq: Dict[str, int] = {}  # IDF calculation
        self.total_documents = 0

    def build_index(self, root: Optional[Path] = None) -> None:
        """Build the search index by chunking code files.

        Args:
            root: Root directory to index
        """
        if root:
            self.root = Path(root)

        self.chunks = []
        self.term_document_freq = {}
        self.total_documents = 0

        # Supported file extensions
        code_extensions = {
            ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c", ".h",
            ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
            ".sh", ".bash", ".yaml", ".yml", ".json", ".xml", ".md"
        }

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
        self.index_built = True

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

        Args:
            question: Natural language question or search query
            k: Number of top results to return
            filters: Optional filters (language, chunk_type, file_pattern)

        Returns:
            List of top-k code chunks ranked by relevance
        """
        if not self.index_built:
            raise RuntimeError("Index not built. Call build_index() first.")

        # Tokenize query
        query_terms = self._tokenize(question)

        # Score all chunks
        scored_chunks = []
        for chunk in self.chunks:
            # Apply filters
            if filters:
                if "language" in filters and chunk.metadata.get("language") != filters["language"]:
                    continue
                if "chunk_type" in filters and chunk.chunk_type != filters["chunk_type"]:
                    continue
                if "file_pattern" in filters:
                    pattern = filters["file_pattern"]
                    if not re.search(pattern, chunk.path):
                        continue

            # Compute score
            score = self._compute_tfidf_score(query_terms, chunk)

            if score > 0:
                chunk.score = score
                scored_chunks.append(chunk)

        # Sort by score descending
        scored_chunks.sort(key=lambda c: c.score, reverse=True)

        # Return top-k
        return scored_chunks[:k]

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
