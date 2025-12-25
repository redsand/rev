"""
HTTP/JSON-RPC API Server for Rev IDE Integration

Provides a REST API and JSON-RPC interface for remote IDE integration.
Supports WebSocket connections for real-time updates.
"""

import asyncio
import json
import logging
import os
import re
import signal
import sys
import threading
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path
from datetime import datetime

try:
    from aiohttp import web
    from aiohttp import WSMsgType
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    web = None

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


class RevAPIServer:
    """HTTP/JSON-RPC API server for IDE integration"""

    def __init__(self, config: Optional[Any] = None):
        """
        Initialize the Rev API server

        Args:
            config: Rev configuration object
        """
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "API server requires 'aiohttp'. Install with: pip install aiohttp"
            )

        self.config = config or rev_config
        self.app = web.Application()
        self.orchestrator = None
        self.active_tasks: Dict[str, Any] = {}
        self._task_futures: Dict[str, asyncio.Task] = {}
        self.websockets: List[web.WebSocketResponse] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._shutdown_requested = False
        self._workspace_root: Optional[Path] = Path.cwd().resolve()
        self._stdout_original = None
        self._stderr_original = None
        self._stream_installed = False
        self._execution_mode_locked = False
        self._ensure_ide_execution_mode()
        self._setup_lifecycle_hooks()
        self._setup_routes()

    def _setup_routes(self):
        """Setup HTTP routes"""
        self.app.router.add_post('/api/v1/execute', self.handle_execute)
        self.app.router.add_post('/api/v1/analyze', self.handle_analyze)
        self.app.router.add_post('/api/v1/test', self.handle_test)
        self.app.router.add_post('/api/v1/refactor', self.handle_refactor)
        self.app.router.add_post('/api/v1/debug', self.handle_debug)
        self.app.router.add_post('/api/v1/document', self.handle_document)
        self.app.router.add_get('/api/v1/status/{task_id}', self.handle_status)
        self.app.router.add_get('/api/v1/tasks', self.handle_list_tasks)
        self.app.router.add_delete('/api/v1/task/{task_id}', self.handle_cancel_task)
        self.app.router.add_get('/api/v1/models', self.handle_list_models)
        self.app.router.add_get('/api/v1/models/current', self.handle_get_current_model)
        self.app.router.add_post('/api/v1/models/select', self.handle_select_model)
        self.app.router.add_get('/ws', self.handle_websocket)
        self.app.router.add_post('/rpc', self.handle_jsonrpc)

    def _setup_lifecycle_hooks(self) -> None:
        self.app.on_startup.append(self._on_startup)
        self.app.on_cleanup.append(self._on_cleanup)

    async def _get_orchestrator(self) -> Orchestrator:
        """Get or create orchestrator instance"""
        if self.orchestrator is None:
            self.orchestrator = Orchestrator(
                project_root=Path.cwd(),
                config=self._build_orchestrator_config(),
            )
        return self.orchestrator

    def _maybe_set_workspace(self, cwd: Optional[str], file_path: Optional[str]) -> None:
        target: Optional[Path] = None
        if cwd:
            target = Path(cwd)
        elif file_path:
            file_target = Path(file_path)
            target = file_target if file_target.is_dir() else file_target.parent

        if not target:
            return

        try:
            target = target.expanduser()
        except Exception:
            pass

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

    async def _on_startup(self, _app: web.Application) -> None:
        self._loop = asyncio.get_running_loop()
        self._install_stream_taps()

    async def _on_cleanup(self, _app: web.Application) -> None:
        self._restore_streams()

    def _install_stream_taps(self) -> None:
        if self._stream_installed:
            return
        self._stdout_original = sys.stdout
        self._stderr_original = sys.stderr
        sys.stdout = _StreamTap("stdout", self._stdout_original, self._handle_stream_output)
        sys.stderr = _StreamTap("stderr", self._stderr_original, self._handle_stream_output)
        self._stream_installed = True

    def _restore_streams(self) -> None:
        if not self._stream_installed:
            return
        if self._stdout_original:
            sys.stdout = self._stdout_original
        if self._stderr_original:
            sys.stderr = self._stderr_original
        self._stream_installed = False

    def _handle_stream_output(self, stream: str, message: str) -> None:
        if message is None:
            return
        payload = {
            "type": "log",
            "stream": stream,
            "message": _strip_ansi(message),
        }
        self._schedule_ws_broadcast(payload)

    def _schedule_ws_broadcast(self, payload: Dict[str, Any]) -> bool:
        if not self.websockets or not self._loop or self._loop.is_closed():
            return False
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None and running_loop == self._loop:
            asyncio.create_task(self._broadcast_to_websockets(payload))
            return True

        if self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._broadcast_to_websockets(payload), self._loop)
            return True

        return False

    async def _broadcast_to_websockets(self, message: Dict[str, Any]):
        """Broadcast message to all connected WebSocket clients"""
        if not self.websockets:
            return

        data = json.dumps(_sanitize_payload(message))
        dead_sockets = []

        for ws in self.websockets:
            try:
                await ws.send_str(data)
            except Exception as e:
                logger.error(f"Error broadcasting to WebSocket: {e}")
                dead_sockets.append(ws)

        # Remove dead sockets
        for ws in dead_sockets:
            self.websockets.remove(ws)

    async def _submit_task(
        self,
        task: str,
        task_id: Optional[str] = None,
        cwd: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> web.Response:
        """Submit a task string to the orchestrator and return a response."""
        if not task:
            return web.json_response(
                {'status': 'error', 'message': 'No task specified'},
                status=400
            )

        if not task_id:
            task_id = f"task_{len(self.active_tasks)}"

        self._maybe_set_workspace(cwd, file_path)
        orchestrator = await self._get_orchestrator()

        # Store task info
        self.active_tasks[task_id] = {
            'id': task_id,
            'task': task,
            'status': 'running',
            'started_at': datetime.now().isoformat(),
            'result': None
        }

        # Execute task asynchronously
        async def execute_task():
            try:
                result = await asyncio.to_thread(orchestrator.execute, task)
                sanitized_result = _sanitize_payload(result)
                self.active_tasks[task_id]['status'] = 'completed'
                self.active_tasks[task_id]['result'] = sanitized_result
                self.active_tasks[task_id]['completed_at'] = datetime.now().isoformat()

                # Broadcast completion
                await self._broadcast_to_websockets({
                    'type': 'task_completed',
                    'task_id': task_id,
                    'result': sanitized_result
                })
            except Exception as e:
                logger.error(f"Error executing task {task_id}: {e}", exc_info=True)
                self.active_tasks[task_id]['status'] = 'failed'
                self.active_tasks[task_id]['error'] = _strip_ansi(str(e))
                self.active_tasks[task_id]['completed_at'] = datetime.now().isoformat()

                # Broadcast failure
                await self._broadcast_to_websockets({
                    'type': 'task_failed',
                    'task_id': task_id,
                    'error': _strip_ansi(str(e))
                })
            finally:
                self._task_futures.pop(task_id, None)

        task_handle = asyncio.create_task(execute_task())
        self._task_futures[task_id] = task_handle

        return web.json_response({
            'status': 'success',
            'task_id': task_id,
            'message': 'Task started'
        })

    async def handle_execute(self, request: web.Request) -> web.Response:
        """Execute a Rev task"""
        try:
            data = await request.json()
            task = data.get('task', '')
            task_id = data.get('task_id', f"task_{len(self.active_tasks)}")
            cwd = data.get('cwd')

            return await self._submit_task(task, task_id, cwd=cwd)

        except Exception as e:
            logger.error(f"Error handling execute request: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_analyze(self, request: web.Request) -> web.Response:
        """Analyze code"""
        try:
            data = await request.json()
            file_path = data.get('file_path', '')
            cwd = data.get('cwd')
            cwd = data.get('cwd')

            if not file_path:
                return web.json_response(
                    {'status': 'error', 'message': 'No file_path specified'},
                    status=400
                )

            task = f"Analyze the code in {file_path} for potential issues, improvements, and best practices"
            return await self._submit_task(task, cwd=cwd, file_path=file_path)

        except Exception as e:
            logger.error(f"Error handling analyze request: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_test(self, request: web.Request) -> web.Response:
        """Generate tests"""
        try:
            data = await request.json()
            file_path = data.get('file_path', '')

            if not file_path:
                return web.json_response(
                    {'status': 'error', 'message': 'No file_path specified'},
                    status=400
                )

            task = f"Generate comprehensive tests for {file_path}"
            return await self._submit_task(task, cwd=cwd, file_path=file_path)

        except Exception as e:
            logger.error(f"Error handling test request: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_refactor(self, request: web.Request) -> web.Response:
        """Refactor code"""
        try:
            data = await request.json()
            file_path = data.get('file_path', '')
            start_line = data.get('start_line')
            end_line = data.get('end_line')
            cwd = data.get('cwd')
            cwd = data.get('cwd')

            if not file_path:
                return web.json_response(
                    {'status': 'error', 'message': 'No file_path specified'},
                    status=400
                )

            task = f"Refactor the code in {file_path} to improve readability and maintainability"
            if start_line and end_line:
                task += f" (lines {start_line}-{end_line})"

            return await self._submit_task(task, cwd=cwd, file_path=file_path)

        except Exception as e:
            logger.error(f"Error handling refactor request: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_debug(self, request: web.Request) -> web.Response:
        """Debug code"""
        try:
            data = await request.json()
            file_path = data.get('file_path', '')
            error_message = data.get('error_message', '')
            cwd = data.get('cwd')

            if not file_path:
                return web.json_response(
                    {'status': 'error', 'message': 'No file_path specified'},
                    status=400
                )

            task = f"Debug and fix issues in {file_path}"
            if error_message:
                task += f". Error: {error_message}"

            return await self._submit_task(task, cwd=cwd, file_path=file_path)

        except Exception as e:
            logger.error(f"Error handling debug request: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_document(self, request: web.Request) -> web.Response:
        """Add documentation"""
        try:
            data = await request.json()
            file_path = data.get('file_path', '')
            start_line = data.get('start_line')
            end_line = data.get('end_line')

            if not file_path:
                return web.json_response(
                    {'status': 'error', 'message': 'No file_path specified'},
                    status=400
                )

            task = f"Add comprehensive documentation to {file_path}"
            if start_line and end_line:
                task += f" (lines {start_line}-{end_line})"

            return await self._submit_task(task, cwd=cwd, file_path=file_path)

        except Exception as e:
            logger.error(f"Error handling document request: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_status(self, request: web.Request) -> web.Response:
        """Get task status"""
        try:
            task_id = request.match_info['task_id']

            if task_id not in self.active_tasks:
                return web.json_response(
                    {'status': 'error', 'message': 'Task not found'},
                    status=404
                )

            return web.json_response({
                'status': 'success',
                'task': _sanitize_payload(self.active_tasks[task_id])
            })

        except Exception as e:
            logger.error(f"Error handling status request: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_list_tasks(self, request: web.Request) -> web.Response:
        """List all tasks"""
        try:
            return web.json_response({
                'status': 'success',
                'tasks': _sanitize_payload(list(self.active_tasks.values()))
            })

        except Exception as e:
            logger.error(f"Error handling list tasks request: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_cancel_task(self, request: web.Request) -> web.Response:
        """Cancel a task"""
        try:
            task_id = request.match_info['task_id']

            if task_id not in self.active_tasks:
                return web.json_response(
                    {'status': 'error', 'message': 'Task not found'},
                    status=404
                )

            # Mark task as cancelled
            self.active_tasks[task_id]['status'] = 'cancelled'
            self.active_tasks[task_id]['completed_at'] = datetime.now().isoformat()

            return web.json_response({
                'status': 'success',
                'message': 'Task cancelled'
            })

        except Exception as e:
            logger.error(f"Error handling cancel task request: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_list_models(self, request: web.Request) -> web.Response:
        """List available models from Rev"""
        try:
            # Import here to avoid circular dependencies
            from ..llm.client import query_ollama_models

            try:
                # Get models from Ollama
                models = query_ollama_models()

                return web.json_response({
                    'status': 'success',
                    'models': models,
                    'provider': 'ollama'
                })
            except Exception as e:
                logger.warning(f"Could not fetch Ollama models: {e}")
                # Return default/configured models if Ollama query fails
                fallback_model = None
                if hasattr(self.config, "ollama_model"):
                    fallback_model = getattr(self.config, "ollama_model")
                elif hasattr(self.config, "OLLAMA_MODEL"):
                    fallback_model = getattr(self.config, "OLLAMA_MODEL")
                models = [fallback_model] if fallback_model else []
                return web.json_response(
                    {
                        "status": "success",
                        "models": models,
                        "provider": "config",
                        "note": "Using configured model (Ollama unavailable)",
                    }
                )

        except Exception as e:
            logger.error(f"Error listing models: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_get_current_model(self, request: web.Request) -> web.Response:
        """Get currently selected model"""
        try:
            from .. import config

            current_model = {
                'execution_model': config.EXECUTION_MODEL,
                'planning_model': config.PLANNING_MODEL,
                'research_model': config.RESEARCH_MODEL,
                'provider': config.LLM_PROVIDER,
            }

            return web.json_response({
                'status': 'success',
                'current_model': current_model
            })

        except Exception as e:
            logger.error(f"Error getting current model: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_select_model(self, request: web.Request) -> web.Response:
        """Select a model to use"""
        try:
            data = await request.json()
            model_name = data.get('model_name', '')

            if not model_name:
                return web.json_response(
                    {'status': 'error', 'message': 'No model_name specified'},
                    status=400
                )

            # Update the active model
            from ..config import update_active_model
            update_active_model(model_name)

            # Clear orchestrator to use new model
            self.orchestrator = None

            return web.json_response({
                'status': 'success',
                'message': f'Model changed to {model_name}',
                'model': model_name
            })

        except Exception as e:
            logger.error(f"Error selecting model: {e}", exc_info=True)
            return web.json_response(
                {'status': 'error', 'message': str(e)},
                status=500
            )

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connections for real-time updates"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        self.websockets.append(ws)
        logger.info(f"WebSocket client connected. Total clients: {len(self.websockets)}")

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        # Echo back for now
                        await ws.send_json({'type': 'ack', 'data': data})
                    except json.JSONDecodeError:
                        await ws.send_json({'type': 'error', 'message': 'Invalid JSON'})
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f'WebSocket error: {ws.exception()}')
        finally:
            self.websockets.remove(ws)
            logger.info(f"WebSocket client disconnected. Total clients: {len(self.websockets)}")

        return ws

    async def handle_jsonrpc(self, request: web.Request) -> web.Response:
        """Handle JSON-RPC requests"""
        try:
            data = await request.json()

            jsonrpc = data.get('jsonrpc', '2.0')
            method = data.get('method', '')
            params = data.get('params', {})
            request_id = data.get('id')

            if not method:
                return web.json_response({
                    'jsonrpc': jsonrpc,
                    'error': {'code': -32600, 'message': 'Invalid Request'},
                    'id': request_id
                })

            # Map JSON-RPC methods to handlers
            method_map = {
                'execute': self._rpc_execute,
                'analyze': self._rpc_analyze,
                'test': self._rpc_test,
                'refactor': self._rpc_refactor,
                'debug': self._rpc_debug,
                'document': self._rpc_document,
                'status': self._rpc_status,
                'listTasks': self._rpc_list_tasks,
                'cancelTask': self._rpc_cancel_task,
            }

            handler = method_map.get(method)
            if not handler:
                return web.json_response({
                    'jsonrpc': jsonrpc,
                    'error': {'code': -32601, 'message': 'Method not found'},
                    'id': request_id
                })

            result = await handler(params)

            return web.json_response({
                'jsonrpc': jsonrpc,
                'result': result,
                'id': request_id
            })

        except Exception as e:
            logger.error(f"Error handling JSON-RPC request: {e}", exc_info=True)
            return web.json_response({
                'jsonrpc': '2.0',
                'error': {'code': -32603, 'message': str(e)},
                'id': data.get('id') if 'data' in locals() else None
            })

    async def _rpc_execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC execute method"""
        task = params.get('task', '')
        if not task:
            raise ValueError('No task specified')

        self._maybe_set_workspace(params.get("cwd"), params.get("file_path"))
        orchestrator = await self._get_orchestrator()
        result = await asyncio.to_thread(orchestrator.execute, task)
        return {'status': 'success', 'result': _sanitize_payload(result)}

    async def _rpc_analyze(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC analyze method"""
        file_path = params.get('file_path', '')
        if not file_path:
            raise ValueError('No file_path specified')

        task = f"Analyze the code in {file_path}"
        return await self._rpc_execute({'task': task, 'cwd': params.get('cwd'), 'file_path': file_path})

    async def _rpc_test(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC test method"""
        file_path = params.get('file_path', '')
        if not file_path:
            raise ValueError('No file_path specified')

        task = f"Generate comprehensive tests for {file_path}"
        return await self._rpc_execute({'task': task, 'cwd': params.get('cwd'), 'file_path': file_path})

    async def _rpc_refactor(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC refactor method"""
        file_path = params.get('file_path', '')
        if not file_path:
            raise ValueError('No file_path specified')

        task = f"Refactor the code in {file_path}"
        return await self._rpc_execute({'task': task, 'cwd': params.get('cwd'), 'file_path': file_path})

    async def _rpc_debug(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC debug method"""
        file_path = params.get('file_path', '')
        error = params.get('error_message', '')

        if not file_path:
            raise ValueError('No file_path specified')

        task = f"Debug and fix issues in {file_path}"
        if error:
            task += f". Error: {error}"

        return await self._rpc_execute({'task': task, 'cwd': params.get('cwd'), 'file_path': file_path})

    async def _rpc_document(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC document method"""
        file_path = params.get('file_path', '')
        if not file_path:
            raise ValueError('No file_path specified')

        task = f"Add comprehensive documentation to {file_path}"
        return await self._rpc_execute({'task': task, 'cwd': params.get('cwd'), 'file_path': file_path})

    async def _rpc_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC status method"""
        task_id = params.get('task_id', '')
        if task_id not in self.active_tasks:
            raise ValueError('Task not found')

        return self.active_tasks[task_id]

    async def _rpc_list_tasks(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC listTasks method"""
        return {'tasks': list(self.active_tasks.values())}

    async def _rpc_cancel_task(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC cancelTask method"""
        task_id = params.get('task_id', '')
        if task_id not in self.active_tasks:
            raise ValueError('Task not found')

        self.active_tasks[task_id]['status'] = 'cancelled'
        return {'status': 'success', 'message': 'Task cancelled'}

    def _request_shutdown(self, reason: str = "signal") -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        try:
            from rev.config import set_escape_interrupt
            set_escape_interrupt(True)
        except Exception:
            pass
        for task_id, task in self.active_tasks.items():
            if task.get("status") == "running":
                task["status"] = "cancelled"
                task["completed_at"] = datetime.now().isoformat()
            async_task = self._task_futures.get(task_id)
            if async_task and not async_task.done():
                async_task.cancel()
        if self._task_futures:
            self._task_futures.clear()
        if self._loop and self._shutdown_event:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
        logger.info("Shutdown requested (%s).", reason)

    async def _run_app(self, host: str, port: int) -> None:
        self._loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        try:
            await self._shutdown_event.wait()
        finally:
            try:
                for ws in list(self.websockets):
                    await ws.close()
            except Exception:
                pass
            await runner.cleanup()

    def start(self, host: str = '127.0.0.1', port: int = 8765):
        """
        Start the API server

        Args:
            host: Host to bind to
            port: Port to listen on
        """
        logger.info(f"Starting Rev API server on http://{host}:{port}")
        previous_handler = signal.signal(signal.SIGINT, lambda *_args: self._request_shutdown("sigint"))
        try:
            asyncio.run(self._run_app(host, port))
        except KeyboardInterrupt:
            self._request_shutdown("keyboard")
        finally:
            signal.signal(signal.SIGINT, previous_handler)


class _StreamTap:
    def __init__(self, name: str, original, on_line):
        self._name = name
        self._original = original
        self._on_line = on_line
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, data):
        if data is None:
            return 0
        if not isinstance(data, str):
            data = str(data)
        with self._lock:
            self._original.write(data)
            self._original.flush()
            self._buffer += data
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._on_line(self._name, line)
        return len(data)

    def flush(self):
        with self._lock:
            if self._buffer:
                self._on_line(self._name, self._buffer)
                self._buffer = ""
            self._original.flush()

    def __getattr__(self, item):
        return getattr(self._original, item)


def main():
    """Main entry point for API server"""
    import argparse

    parser = argparse.ArgumentParser(description='Rev HTTP/JSON-RPC API Server')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8765, help='Port to listen on')
    parser.add_argument('--log-level', default='INFO', help='Logging level')

    args = parser.parse_args()

    logging.basicConfig(level=args.log_level)

    server = RevAPIServer()
    server.start(args.host, args.port)


if __name__ == '__main__':
    main()
