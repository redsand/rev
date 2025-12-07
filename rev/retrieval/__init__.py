#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG (Retrieval-Augmented Generation) infrastructure for Rev.

This module implements the RAG pattern from Agentic Design Patterns,
providing semantic code search and retrieval capabilities.
"""

from rev.retrieval.base import BaseCodeRetriever, CodeChunk
from rev.retrieval.simple_rag import SimpleCodeRetriever

__all__ = ["BaseCodeRetriever", "CodeChunk", "SimpleCodeRetriever"]
