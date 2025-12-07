#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Base classes for RAG (Retrieval-Augmented Generation) code retrieval.

This module provides the foundation for the RAG pattern, allowing semantic
search and retrieval of relevant code chunks based on natural language queries.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any
from abc import ABC, abstractmethod


@dataclass
class CodeChunk:
    """A chunk of code with metadata for RAG retrieval.

    Represents a semantically meaningful unit of code (function, class, module section)
    that can be retrieved and provided as context.
    """
    path: str  # Relative path to file
    start_line: int
    end_line: int
    content: str
    chunk_type: str = "code"  # code, comment, docstring, test
    metadata: Dict[str, Any] = None  # Additional metadata (language, symbols, etc.)
    score: float = 0.0  # Relevance score (set during retrieval)

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def get_location(self) -> str:
        """Get human-readable location string."""
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def get_preview(self, max_lines: int = 5) -> str:
        """Get a preview of the chunk content."""
        lines = self.content.splitlines()
        if len(lines) <= max_lines:
            return self.content
        preview_lines = lines[:max_lines]
        return "\n".join(preview_lines) + f"\n... ({len(lines) - max_lines} more lines)"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
            "chunk_type": self.chunk_type,
            "metadata": self.metadata,
            "score": self.score
        }


class BaseCodeRetriever(ABC):
    """Abstract base class for code retrieval systems.

    Implementations can use different strategies:
    - Simple keyword/bag-of-words matching
    - TF-IDF with vector similarity
    - Embeddings with semantic search (using Ollama embeddings)
    - Hybrid approaches
    """

    def __init__(self, root: Path = None):
        """Initialize the retriever.

        Args:
            root: Root directory of the codebase
        """
        self.root = root or Path.cwd()
        self.index_built = False

    @abstractmethod
    def build_index(self, root: Optional[Path] = None) -> None:
        """Build or rebuild the search index.

        Args:
            root: Root directory to index (uses self.root if not provided)
        """
        pass

    @abstractmethod
    def query(self, question: str, k: int = 10, filters: Optional[Dict[str, Any]] = None) -> List[CodeChunk]:
        """Query the index for relevant code chunks.

        Args:
            question: Natural language question or search query
            k: Number of top results to return
            filters: Optional filters (file patterns, languages, etc.)

        Returns:
            List of CodeChunk objects ranked by relevance
        """
        pass

    def get_index_stats(self) -> Dict[str, Any]:
        """Get statistics about the current index.

        Returns:
            Dictionary with index statistics (chunk count, file count, etc.)
        """
        return {
            "index_built": self.index_built,
            "root": str(self.root)
        }

    def clear_index(self) -> None:
        """Clear the current index."""
        self.index_built = False
