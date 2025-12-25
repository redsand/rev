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

import asyncio
import json
import logging
import os
import re
import signal
from typing import Dict, List, Optional, Any
from pathlib import Path

LSP_IMPORT_ERROR: Optional[Exception] = None

try:
    try:
        from pygls.lsp.server import LanguageServer
    except ImportError:
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

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(value: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", value)


def _sanitize_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        return _strip_ansi(payload)
    if isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload]
    if isinstance(payload, dict):
        return {key: _sanitize_payload(val) for key, val in payload.items()}
    return payload


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
        self._running_tasks: set[asyncio.Task] = set()
        self._shutdown_requested = False
        self._workspace_root: Optional[Path] = Path.cwd().resolve()
        self._execution_mode_locked = False
        self._ensure_ide_execution_mode()
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
                config=self._build_orchestrator_config(),
            )
        return self.orchestrator

    def _maybe_set_workspace(self, file_path: Optional[str]) -> None:
        if not file_path:
            return
        path = Path(file_path)
        target = path if path.is_dir() else path.parent
        if target.exists() and not target.is_dir():
            target = target.parent
        if not target.exists():
            logger.warning("Workspace root does not exist: %s", target)
            return
        target = target.resolve()
        if self._workspace_root == target:
            return
        try:
            rev_config.set_workspace_root(target, allow_external=True)
        except Exception as exc:
            logger.warning("Failed to set workspace root: %s", exc)
        try:
            os.chdir(str(target))
        except Exception as exc:
            logger.warning("Failed to chdir to %s: %s", target, exc)
        self._workspace_root = target
        self.orchestrator = None

    def _ensure_ide_execution_mode(self) -> None:
        if self._execution_mode_locked:
            return
        if getattr(rev_config, "EXECUTION_MODE", "").lower() != "sub-agent":
            rev_config.EXECUTION_MODE = "sub-agent"
            os.environ["REV_EXECUTION_MODE"] = "sub-agent"
        self._execution_mode_locked = True

    @staticmethod
    def _build_orchestrator_config() -> OrchestratorConfig:
        return OrchestratorConfig(
            enable_context_guard=True,
            context_guard_interactive=False,
        )

    async def _run_orchestrator_task(self, task: str) -> Any:
        orchestrator = await self._get_orchestrator()
        task_handle = asyncio.create_task(asyncio.to_thread(orchestrator.execute, task))
        self._running_tasks.add(task_handle)
        try:
            return _sanitize_payload(await task_handle)
        finally:
            self._running_tasks.discard(task_handle)

    def _request_shutdown(self, reason: str = "signal") -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        try:
            from rev.config import set_escape_interrupt
            set_escape_interrupt(True)
        except Exception:
            pass
        for task in list(self._running_tasks):
            if not task.done():
                task.cancel()
        self._running_tasks.clear()
        if hasattr(self.server, "shutdown"):
            try:
                self.server.shutdown()
            except Exception:
                pass
        if hasattr(self.server, "stop"):
            try:
                self.server.stop()
            except Exception:
                pass
        logger.info("Shutdown requested (%s).", reason)

    async def _analyze_code(self, uri: Optional[str]) -> Dict[str, Any]:
        """Analyze code using Rev"""
        if not uri:
            return {"status": "error", "message": "No file specified"}

        file_path = self._uri_to_path(uri)
        self._maybe_set_workspace(file_path)
        # Execute analysis task
        task = f"Analyze the code in {file_path} for potential issues, improvements, and best practices"
        result = await self._run_orchestrator_task(task)

        return {"status": "success", "result": result}

    async def _generate_tests(self, uri: Optional[str]) -> Dict[str, Any]:
        """Generate tests using Rev"""
        if not uri:
            return {"status": "error", "message": "No file specified"}

        file_path = self._uri_to_path(uri)
        self._maybe_set_workspace(file_path)
        task = f"Generate comprehensive tests for {file_path}"
        result = await self._run_orchestrator_task(task)

        return {"status": "success", "result": result}

    async def _refactor_code(self, uri: Optional[str], range_dict: Optional[Dict]) -> Dict[str, Any]:
        """Refactor code using Rev"""
        if not uri:
            return {"status": "error", "message": "No file specified"}

        file_path = self._uri_to_path(uri)
        self._maybe_set_workspace(file_path)
        task = f"Refactor the code in {file_path} to improve readability and maintainability"
        if range_dict:
            start_line = range_dict['start']['line']
            end_line = range_dict['end']['line']
            task += f" (lines {start_line}-{end_line})"

        result = await self._run_orchestrator_task(task)

        return {"status": "success", "result": result}

    async def _fix_issues(self, uri: Optional[str]) -> Dict[str, Any]:
        """Fix issues using Rev"""
        if not uri:
            return {"status": "error", "message": "No file specified"}

        file_path = self._uri_to_path(uri)
        self._maybe_set_workspace(file_path)
        task = f"Fix any bugs, errors, or issues in {file_path}"
        result = await self._run_orchestrator_task(task)

        return {"status": "success", "result": result}

    async def _add_documentation(self, uri: Optional[str], range_dict: Optional[Dict]) -> Dict[str, Any]:
        """Add documentation using Rev"""
        if not uri:
            return {"status": "error", "message": "No file specified"}

        file_path = self._uri_to_path(uri)
        self._maybe_set_workspace(file_path)
        task = f"Add comprehensive documentation to {file_path}"
        if range_dict:
            start_line = range_dict['start']['line']
            end_line = range_dict['end']['line']
            task += f" (lines {start_line}-{end_line})"

        result = await self._run_orchestrator_task(task)

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
        previous_handler = signal.signal(signal.SIGINT, lambda *_args: self._request_shutdown("sigint"))
        try:
            self.server.start_tcp(host, port)
        except KeyboardInterrupt:
            self._request_shutdown("keyboard")
        finally:
            signal.signal(signal.SIGINT, previous_handler)

    def start_io(self):
        """Start the LSP server using stdio (for direct IDE integration)"""
        logger.info("Starting Rev LSP server on stdio")
        previous_handler = signal.signal(signal.SIGINT, lambda *_args: self._request_shutdown("sigint"))
        try:
            self.server.start_io()
        except KeyboardInterrupt:
            self._request_shutdown("keyboard")
        finally:
            signal.signal(signal.SIGINT, previous_handler)


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
