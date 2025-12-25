"""
Rev IDE Client Library

Provides a Python client library for integrating Rev with IDEs.
Can be used by IDE plugins to communicate with Rev.
"""

import json
import logging
import socket
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)


class RevIDEClient:
    """Client library for Rev IDE integration"""

    def __init__(
        self,
        api_url: str = 'http://127.0.0.1:8765',
        timeout: int = 300
    ):
        """
        Initialize the Rev IDE client

        Args:
            api_url: Base URL for Rev API server
            timeout: Request timeout in seconds
        """
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "Rev IDE client requires 'requests'. Install with: pip install requests"
            )

        self.api_url = api_url.rstrip('/')
        self.timeout = timeout

    def execute(self, task: str, task_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute a Rev task

        Args:
            task: Task description
            task_id: Optional task ID

        Returns:
            Response dictionary with status and result
        """
        url = f"{self.api_url}/api/v1/execute"
        data = {'task': task}
        if task_id:
            data['task_id'] = task_id

        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error executing task: {e}")
            return {'status': 'error', 'message': str(e)}

    def analyze_code(self, file_path: str) -> Dict[str, Any]:
        """
        Analyze code file

        Args:
            file_path: Path to file to analyze

        Returns:
            Analysis results
        """
        url = f"{self.api_url}/api/v1/analyze"
        data = {'file_path': file_path}

        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error analyzing code: {e}")
            return {'status': 'error', 'message': str(e)}

    def generate_tests(self, file_path: str) -> Dict[str, Any]:
        """
        Generate tests for code file

        Args:
            file_path: Path to file to generate tests for

        Returns:
            Test generation results
        """
        url = f"{self.api_url}/api/v1/test"
        data = {'file_path': file_path}

        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error generating tests: {e}")
            return {'status': 'error', 'message': str(e)}

    def refactor_code(
        self,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Refactor code

        Args:
            file_path: Path to file to refactor
            start_line: Optional start line for refactoring
            end_line: Optional end line for refactoring

        Returns:
            Refactoring results
        """
        url = f"{self.api_url}/api/v1/refactor"
        data = {'file_path': file_path}
        if start_line is not None:
            data['start_line'] = start_line
        if end_line is not None:
            data['end_line'] = end_line

        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error refactoring code: {e}")
            return {'status': 'error', 'message': str(e)}

    def debug_code(
        self,
        file_path: str,
        error_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Debug code

        Args:
            file_path: Path to file to debug
            error_message: Optional error message

        Returns:
            Debugging results
        """
        url = f"{self.api_url}/api/v1/debug"
        data = {'file_path': file_path}
        if error_message:
            data['error_message'] = error_message

        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error debugging code: {e}")
            return {'status': 'error', 'message': str(e)}

    def add_documentation(
        self,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Add documentation to code

        Args:
            file_path: Path to file to document
            start_line: Optional start line for documentation
            end_line: Optional end line for documentation

        Returns:
            Documentation results
        """
        url = f"{self.api_url}/api/v1/document"
        data = {'file_path': file_path}
        if start_line is not None:
            data['start_line'] = start_line
        if end_line is not None:
            data['end_line'] = end_line

        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error adding documentation: {e}")
            return {'status': 'error', 'message': str(e)}

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Get status of a task

        Args:
            task_id: Task ID

        Returns:
            Task status
        """
        url = f"{self.api_url}/api/v1/status/{task_id}"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error getting task status: {e}")
            return {'status': 'error', 'message': str(e)}

    def list_tasks(self) -> Dict[str, Any]:
        """
        List all tasks

        Returns:
            List of tasks
        """
        url = f"{self.api_url}/api/v1/tasks"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error listing tasks: {e}")
            return {'status': 'error', 'message': str(e)}

    def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """
        Cancel a task

        Args:
            task_id: Task ID

        Returns:
            Cancellation result
        """
        url = f"{self.api_url}/api/v1/task/{task_id}"

        try:
            response = requests.delete(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error cancelling task: {e}")
            return {'status': 'error', 'message': str(e)}

    def list_models(self) -> Dict[str, Any]:
        """
        List available models

        Returns:
            List of available models from Rev/Ollama
        """
        url = f"{self.api_url}/api/v1/models"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error listing models: {e}")
            return {'status': 'error', 'message': str(e)}

    def get_current_model(self) -> Dict[str, Any]:
        """
        Get currently selected model

        Returns:
            Current model information
        """
        url = f"{self.api_url}/api/v1/models/current"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error getting current model: {e}")
            return {'status': 'error', 'message': str(e)}

    def select_model(self, model_name: str) -> Dict[str, Any]:
        """
        Select a model to use

        Args:
            model_name: Name of the model to select

        Returns:
            Selection result
        """
        url = f"{self.api_url}/api/v1/models/select"
        data = {'model_name': model_name}

        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error selecting model: {e}")
            return {'status': 'error', 'message': str(e)}

    def jsonrpc_call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Make a JSON-RPC call

        Args:
            method: Method name
            params: Method parameters
            request_id: Optional request ID

        Returns:
            JSON-RPC response
        """
        url = f"{self.api_url}/rpc"
        data = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params or {},
            'id': request_id or 1
        }

        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error making JSON-RPC call: {e}")
            return {
                'jsonrpc': '2.0',
                'error': {'code': -32603, 'message': str(e)},
                'id': request_id
            }


class LSPClient:
    """Client for connecting to Rev LSP server"""

    def __init__(self, host: str = '127.0.0.1', port: int = 2087):
        """
        Initialize LSP client

        Args:
            host: LSP server host
            port: LSP server port
        """
        self.host = host
        self.port = port
        self.socket = None

    def connect(self):
        """Connect to LSP server"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
        logger.info(f"Connected to LSP server at {self.host}:{self.port}")

    def disconnect(self):
        """Disconnect from LSP server"""
        if self.socket:
            self.socket.close()
            self.socket = None
            logger.info("Disconnected from LSP server")

    def send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send LSP request

        Args:
            method: LSP method name
            params: Method parameters

        Returns:
            LSP response
        """
        if not self.socket:
            raise RuntimeError("Not connected to LSP server")

        request = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
            'id': 1
        }

        message = json.dumps(request)
        content_length = len(message)

        # Send LSP message
        self.socket.sendall(
            f"Content-Length: {content_length}\r\n\r\n{message}".encode()
        )

        # Read response (simplified - production would need proper parsing)
        response_data = self.socket.recv(4096).decode()

        # Extract JSON from LSP response
        json_start = response_data.find('{')
        if json_start >= 0:
            response = json.loads(response_data[json_start:])
            return response

        return {}

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
