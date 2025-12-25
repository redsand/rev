"""
Language Server Protocol (LSP) implementation for Rev

Provides universal IDE integration through LSP, supporting:
- VSCode
- Visual Studio
- Sublime Text
- Atom
- Vim/Neovim with LSP plugins
- Emacs with LSP plugins
- JetBrains IDEs
"""

import json
import logging
import asyncio
from typing import Dict, List, Optional, Any
from pathlib import Path

LSP_IMPORT_ERROR: Optional[Exception] = None

try:
    from pygls.server import LanguageServer
    try:
        from lsprotocol.types import (
            TEXT_DOCUMENT_DID_OPEN,
            TEXT_DOCUMENT_DID_CHANGE,
            TEXT_DOCUMENT_DID_SAVE,
            TEXT_DOCUMENT_CODE_ACTION,
            TEXT_DOCUMENT_COMPLETION,
            WORKSPACE_EXECUTE_COMMAND,
            CodeAction,
            CodeActionKind,
            CodeActionParams,
            Command,
            CompletionItem,
            CompletionList,
            CompletionParams,
            DidOpenTextDocumentParams,
            DidChangeTextDocumentParams,
            DidSaveTextDocumentParams,
            ExecuteCommandParams,
            Position,
            Range,
            TextEdit,
        )
    except ImportError:
        from pygls.lsp.methods import (
            TEXT_DOCUMENT_DID_OPEN,
            TEXT_DOCUMENT_DID_CHANGE,
            TEXT_DOCUMENT_DID_SAVE,
            TEXT_DOCUMENT_CODE_ACTION,
            TEXT_DOCUMENT_COMPLETION,
            WORKSPACE_EXECUTE_COMMAND,
        )
        from pygls.lsp.types import (
            CodeAction,
            CodeActionKind,
            CodeActionParams,
            Command,
            CompletionItem,
            CompletionList,
            CompletionParams,
            DidOpenTextDocumentParams,
            DidChangeTextDocumentParams,
            DidSaveTextDocumentParams,
            ExecuteCommandParams,
            Position,
            Range,
            TextEdit,
        )
    LSP_AVAILABLE = True
except Exception as exc:
    LSP_AVAILABLE = False
    LanguageServer = None
    LSP_IMPORT_ERROR = exc

from ..execution.orchestrator import Orchestrator, OrchestratorConfig
from .. import config as rev_config

logger = logging.getLogger(__name__)


class RevLSPServer:
    """Language Server Protocol server for Rev integration"""

    def __init__(self, config: Optional[Any] = None):
        """
        Initialize the Rev LSP server

        Args:
            config: Rev configuration object
        """
        if not LSP_AVAILABLE:
            import sys
            base_msg = "LSP support requires 'pygls' (and lsprotocol for pygls>=2). Install with: pip install pygls"
            if LSP_IMPORT_ERROR:
                detail = f"{type(LSP_IMPORT_ERROR).__name__}: {LSP_IMPORT_ERROR}"
                base_msg += f" (import error: {detail}; python={sys.executable})"
            raise ImportError(base_msg)

        self.config = config or rev_config
        self.server = LanguageServer('rev-lsp', 'v0.1')
        self.orchestrator = None
        self._setup_handlers()

    def _setup_handlers(self):
        """Setup LSP message handlers"""

        @self.server.feature(TEXT_DOCUMENT_DID_OPEN)
        async def did_open(ls: LanguageServer, params: DidOpenTextDocumentParams):
            """Handle document open event"""
            logger.info(f"Document opened: {params.text_document.uri}")

        @self.server.feature(TEXT_DOCUMENT_DID_CHANGE)
        async def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
            """Handle document change event"""
            logger.debug(f"Document changed: {params.text_document.uri}")

        @self.server.feature(TEXT_DOCUMENT_DID_SAVE)
        async def did_save(ls: LanguageServer, params: DidSaveTextDocumentParams):
            """Handle document save event"""
            logger.info(f"Document saved: {params.text_document.uri}")
            # Optionally trigger analysis or validation

        @self.server.feature(TEXT_DOCUMENT_CODE_ACTION)
        async def code_action(ls: LanguageServer, params: CodeActionParams):
            """Provide code actions for Rev"""
            actions = []

            # Add Rev-specific code actions
            actions.append(CodeAction(
                title="Rev: Analyze Code",
                kind=CodeActionKind.QuickFix,
                command=Command(
                    title="Analyze Code",
                    command="rev.analyzeCode",
                    arguments=[params.text_document.uri]
                )
            ))

            actions.append(CodeAction(
                title="Rev: Generate Tests",
                kind=CodeActionKind.Source,
                command=Command(
                    title="Generate Tests",
                    command="rev.generateTests",
                    arguments=[params.text_document.uri]
                )
            ))

            actions.append(CodeAction(
                title="Rev: Refactor Code",
                kind=CodeActionKind.Refactor,
                command=Command(
                    title="Refactor Code",
                    command="rev.refactorCode",
                    arguments=[params.text_document.uri, params.range.dict()]
                )
            ))

            actions.append(CodeAction(
                title="Rev: Fix Issues",
                kind=CodeActionKind.QuickFix,
                command=Command(
                    title="Fix Issues",
                    command="rev.fixIssues",
                    arguments=[params.text_document.uri]
                )
            ))

            actions.append(CodeAction(
                title="Rev: Add Documentation",
                kind=CodeActionKind.Source,
                command=Command(
                    title="Add Documentation",
                    command="rev.addDocumentation",
                    arguments=[params.text_document.uri, params.range.dict()]
                )
            ))

            return actions

        @self.server.feature(TEXT_DOCUMENT_COMPLETION)
        async def completion(ls: LanguageServer, params: CompletionParams):
            """Provide completions for Rev commands"""
            items = [
                CompletionItem(label="rev.analyze"),
                CompletionItem(label="rev.test"),
                CompletionItem(label="rev.refactor"),
                CompletionItem(label="rev.debug"),
                CompletionItem(label="rev.document"),
            ]
            return CompletionList(is_incomplete=False, items=items)

        @self.server.feature(WORKSPACE_EXECUTE_COMMAND)
        async def execute_command(ls: LanguageServer, params: ExecuteCommandParams):
            """Execute Rev commands from IDE"""
            command = params.command
            args = params.arguments or []

            logger.info(f"Executing command: {command} with args: {args}")

            try:
                if command == "rev.analyzeCode":
                    return await self._analyze_code(args[0] if args else None)
                elif command == "rev.generateTests":
                    return await self._generate_tests(args[0] if args else None)
                elif command == "rev.refactorCode":
                    uri = args[0] if args else None
                    range_dict = args[1] if len(args) > 1 else None
                    return await self._refactor_code(uri, range_dict)
                elif command == "rev.fixIssues":
                    return await self._fix_issues(args[0] if args else None)
                elif command == "rev.addDocumentation":
                    uri = args[0] if args else None
                    range_dict = args[1] if len(args) > 1 else None
                    return await self._add_documentation(uri, range_dict)
                else:
                    ls.show_message(f"Unknown command: {command}")
                    return None
            except Exception as e:
                logger.error(f"Error executing command {command}: {e}", exc_info=True)
                ls.show_message_log(f"Error: {str(e)}")
                return None

    async def _get_orchestrator(self) -> Orchestrator:
        """Get or create orchestrator instance"""
        if self.orchestrator is None:
            self.orchestrator = Orchestrator(
                project_root=Path.cwd(),
                config=OrchestratorConfig(),
            )
        return self.orchestrator

    async def _analyze_code(self, uri: Optional[str]) -> Dict[str, Any]:
        """Analyze code using Rev"""
        if not uri:
            return {"status": "error", "message": "No file specified"}

        file_path = self._uri_to_path(uri)
        orchestrator = await self._get_orchestrator()

        # Execute analysis task
        task = f"Analyze the code in {file_path} for potential issues, improvements, and best practices"
        result = await asyncio.to_thread(orchestrator.execute, task)

        return {"status": "success", "result": result}

    async def _generate_tests(self, uri: Optional[str]) -> Dict[str, Any]:
        """Generate tests using Rev"""
        if not uri:
            return {"status": "error", "message": "No file specified"}

        file_path = self._uri_to_path(uri)
        orchestrator = await self._get_orchestrator()

        task = f"Generate comprehensive tests for {file_path}"
        result = await asyncio.to_thread(orchestrator.execute, task)

        return {"status": "success", "result": result}

    async def _refactor_code(self, uri: Optional[str], range_dict: Optional[Dict]) -> Dict[str, Any]:
        """Refactor code using Rev"""
        if not uri:
            return {"status": "error", "message": "No file specified"}

        file_path = self._uri_to_path(uri)
        orchestrator = await self._get_orchestrator()

        task = f"Refactor the code in {file_path} to improve readability and maintainability"
        if range_dict:
            start_line = range_dict['start']['line']
            end_line = range_dict['end']['line']
            task += f" (lines {start_line}-{end_line})"

        result = await asyncio.to_thread(orchestrator.execute, task)

        return {"status": "success", "result": result}

    async def _fix_issues(self, uri: Optional[str]) -> Dict[str, Any]:
        """Fix issues using Rev"""
        if not uri:
            return {"status": "error", "message": "No file specified"}

        file_path = self._uri_to_path(uri)
        orchestrator = await self._get_orchestrator()

        task = f"Fix any bugs, errors, or issues in {file_path}"
        result = await asyncio.to_thread(orchestrator.execute, task)

        return {"status": "success", "result": result}

    async def _add_documentation(self, uri: Optional[str], range_dict: Optional[Dict]) -> Dict[str, Any]:
        """Add documentation using Rev"""
        if not uri:
            return {"status": "error", "message": "No file specified"}

        file_path = self._uri_to_path(uri)
        orchestrator = await self._get_orchestrator()

        task = f"Add comprehensive documentation to {file_path}"
        if range_dict:
            start_line = range_dict['start']['line']
            end_line = range_dict['end']['line']
            task += f" (lines {start_line}-{end_line})"

        result = await asyncio.to_thread(orchestrator.execute, task)

        return {"status": "success", "result": result}

    @staticmethod
    def _uri_to_path(uri: str) -> str:
        """Convert URI to file path"""
        if uri.startswith('file://'):
            uri = uri[7:]
        return uri

    def start(self, host: str = '127.0.0.1', port: int = 2087):
        """
        Start the LSP server

        Args:
            host: Host to bind to
            port: Port to listen on
        """
        logger.info(f"Starting Rev LSP server on {host}:{port}")
        self.server.start_tcp(host, port)

    def start_io(self):
        """Start the LSP server using stdio (for direct IDE integration)"""
        logger.info("Starting Rev LSP server on stdio")
        self.server.start_io()


def main():
    """Main entry point for LSP server"""
    import argparse

    parser = argparse.ArgumentParser(description='Rev Language Server Protocol Server')
    parser.add_argument('--tcp', action='store_true', help='Use TCP instead of stdio')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to (TCP mode)')
    parser.add_argument('--port', type=int, default=2087, help='Port to listen on (TCP mode)')
    parser.add_argument('--log-level', default='INFO', help='Logging level')

    args = parser.parse_args()

    logging.basicConfig(level=args.log_level)

    server = RevLSPServer()

    if args.tcp:
        server.start(args.host, args.port)
    else:
        server.start_io()


if __name__ == '__main__':
    main()
