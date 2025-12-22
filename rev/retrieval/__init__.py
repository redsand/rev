#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG (Retrieval-Augmented Generation) infrastructure for Rev.

This module implements the RAG pattern from Agentic Design Patterns,
providing semantic code search and retrieval capabilities with
code-aware enhancements (symbol indexing, import graphs).
"""

from rev.retrieval.base import BaseCodeRetriever, CodeChunk
from rev.retrieval.simple_rag import SimpleCodeRetriever
from rev.retrieval.symbol_index import Symbol, SymbolIndexer
from rev.retrieval.import_graph import ImportEdge, ImportGraph
from rev.retrieval.code_queries import CodeQueryEngine

__all__ = [
    "BaseCodeRetriever",
    "CodeChunk",
    "SimpleCodeRetriever",
    "Symbol",
    "SymbolIndexer",
    "ImportEdge",
    "ImportGraph",
    "CodeQueryEngine",
]
