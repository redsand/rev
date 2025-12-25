"""
HTTP/JSON-RPC API Server for Rev IDE Integration

Provides a REST API and JSON-RPC interface for remote IDE integration.
Supports WebSocket connections for real-time updates.
"""

import json
import logging
import asyncio
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

from ..execution.orchestrator import Orchestrator
from ..core.context import RevContext
from ..config import Config

logger = logging.getLogger(__name__)


class RevAPIServer:
    """HTTP/JSON-RPC API server for IDE integration"""

    def __init__(self, config: Optional[Config] = None):
        """
        Initialize the Rev API server

        Args:
            config: Rev configuration object
        """
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "API server requires 'aiohttp'. Install with: pip install aiohttp"
            )

        self.config = config or Config()
        self.app = web.Application()
        self.orchestrator = None
        self.active_tasks: Dict[str, Any] = {}
        self.websockets: List[web.WebSocketResponse] = []
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

    async def _get_orchestrator(self) -> Orchestrator:
        """Get or create orchestrator instance"""
        if self.orchestrator is None:
            context = RevContext(
                project_root=Path.cwd(),
                config=self.config
            )
            self.orchestrator = Orchestrator(context)
        return self.orchestrator

    async def _broadcast_to_websockets(self, message: Dict[str, Any]):
        """Broadcast message to all connected WebSocket clients"""
        if not self.websockets:
            return

        data = json.dumps(message)
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

    async def handle_execute(self, request: web.Request) -> web.Response:
        """Execute a Rev task"""
        try:
            data = await request.json()
            task = data.get('task', '')
            task_id = data.get('task_id', f"task_{len(self.active_tasks)}")

            if not task:
                return web.json_response(
                    {'status': 'error', 'message': 'No task specified'},
                    status=400
                )

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
                    self.active_tasks[task_id]['status'] = 'completed'
                    self.active_tasks[task_id]['result'] = result
                    self.active_tasks[task_id]['completed_at'] = datetime.now().isoformat()

                    # Broadcast completion
                    await self._broadcast_to_websockets({
                        'type': 'task_completed',
                        'task_id': task_id,
                        'result': result
                    })
                except Exception as e:
                    logger.error(f"Error executing task {task_id}: {e}", exc_info=True)
                    self.active_tasks[task_id]['status'] = 'failed'
                    self.active_tasks[task_id]['error'] = str(e)
                    self.active_tasks[task_id]['completed_at'] = datetime.now().isoformat()

                    # Broadcast failure
                    await self._broadcast_to_websockets({
                        'type': 'task_failed',
                        'task_id': task_id,
                        'error': str(e)
                    })

            asyncio.create_task(execute_task())

            return web.json_response({
                'status': 'success',
                'task_id': task_id,
                'message': 'Task started'
            })

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

            if not file_path:
                return web.json_response(
                    {'status': 'error', 'message': 'No file_path specified'},
                    status=400
                )

            task = f"Analyze the code in {file_path} for potential issues, improvements, and best practices"
            return await self.handle_execute(
                web.Request(
                    message=request._message,
                    payload=web.StreamReader(None),
                    protocol=request.protocol,
                    payload_writer=request._payload_writer,
                    task=request.task,
                    loop=request.loop,
                    client_max_size=request._client_max_size
                )
            )

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

            # Create new request with task
            request_data = {'task': task}
            new_request = request.clone()
            new_request._read_bytes = json.dumps(request_data).encode()

            return await self.handle_execute(new_request)

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

            if not file_path:
                return web.json_response(
                    {'status': 'error', 'message': 'No file_path specified'},
                    status=400
                )

            task = f"Refactor the code in {file_path} to improve readability and maintainability"
            if start_line and end_line:
                task += f" (lines {start_line}-{end_line})"

            request_data = {'task': task}
            new_request = request.clone()
            new_request._read_bytes = json.dumps(request_data).encode()

            return await self.handle_execute(new_request)

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

            if not file_path:
                return web.json_response(
                    {'status': 'error', 'message': 'No file_path specified'},
                    status=400
                )

            task = f"Debug and fix issues in {file_path}"
            if error_message:
                task += f". Error: {error_message}"

            request_data = {'task': task}
            new_request = request.clone()
            new_request._read_bytes = json.dumps(request_data).encode()

            return await self.handle_execute(new_request)

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

            request_data = {'task': task}
            new_request = request.clone()
            new_request._read_bytes = json.dumps(request_data).encode()

            return await self.handle_execute(new_request)

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
                'task': self.active_tasks[task_id]
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
                'tasks': list(self.active_tasks.values())
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
                return web.json_response({
                    'status': 'success',
                    'models': [self.config.ollama_model] if hasattr(self.config, 'ollama_model') else [],
                    'provider': 'config',
                    'note': 'Using configured model (Ollama unavailable)'
                })

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

        orchestrator = await self._get_orchestrator()
        result = await asyncio.to_thread(orchestrator.execute, task)
        return {'status': 'success', 'result': result}

    async def _rpc_analyze(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC analyze method"""
        file_path = params.get('file_path', '')
        if not file_path:
            raise ValueError('No file_path specified')

        task = f"Analyze the code in {file_path}"
        return await self._rpc_execute({'task': task})

    async def _rpc_test(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC test method"""
        file_path = params.get('file_path', '')
        if not file_path:
            raise ValueError('No file_path specified')

        task = f"Generate comprehensive tests for {file_path}"
        return await self._rpc_execute({'task': task})

    async def _rpc_refactor(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC refactor method"""
        file_path = params.get('file_path', '')
        if not file_path:
            raise ValueError('No file_path specified')

        task = f"Refactor the code in {file_path}"
        return await self._rpc_execute({'task': task})

    async def _rpc_debug(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC debug method"""
        file_path = params.get('file_path', '')
        error = params.get('error_message', '')

        if not file_path:
            raise ValueError('No file_path specified')

        task = f"Debug and fix issues in {file_path}"
        if error:
            task += f". Error: {error}"

        return await self._rpc_execute({'task': task})

    async def _rpc_document(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC document method"""
        file_path = params.get('file_path', '')
        if not file_path:
            raise ValueError('No file_path specified')

        task = f"Add comprehensive documentation to {file_path}"
        return await self._rpc_execute({'task': task})

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

    def start(self, host: str = '127.0.0.1', port: int = 8765):
        """
        Start the API server

        Args:
            host: Host to bind to
            port: Port to listen on
        """
        logger.info(f"Starting Rev API server on http://{host}:{port}")
        web.run_app(self.app, host=host, port=port)


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
