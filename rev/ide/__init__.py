"""
IDE Integration Module for Rev

This module provides integration with various IDEs including:
- Language Server Protocol (LSP) for universal IDE support
- HTTP/JSON-RPC API for remote integration
- VSCode extension support
- Visual Studio extension support
- JetBrains IDE support
"""

from .lsp_server import RevLSPServer
from .api_server import RevAPIServer
from .client import RevIDEClient

__all__ = ['RevLSPServer', 'RevAPIServer', 'RevIDEClient']
