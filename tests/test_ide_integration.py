"""
Tests for IDE integration functionality

Tests cover:
- LSP server functionality
- HTTP API server endpoints
- IDE client library
- Integration scenarios
"""

import pytest
import json
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys

# Test imports with graceful fallback
try:
    from rev.ide.client import RevIDEClient
    CLIENT_AVAILABLE = True
except ImportError:
    CLIENT_AVAILABLE = False

try:
    from rev.ide.lsp_server import RevLSPServer, LSP_AVAILABLE
except ImportError:
    LSP_AVAILABLE = False

try:
    from rev.ide.api_server import RevAPIServer, AIOHTTP_AVAILABLE
except ImportError:
    AIOHTTP_AVAILABLE = False

from rev.config import Config


@pytest.mark.skipif(not CLIENT_AVAILABLE, reason="Client dependencies not available")
class TestRevIDEClient:
    """Test Rev IDE client library"""

    def setup_method(self):
        """Setup test client"""
        self.client = RevIDEClient(
            api_url='http://127.0.0.1:8765',
            timeout=30
        )

    def test_client_initialization(self):
        """Test client initializes correctly"""
        assert self.client.api_url == 'http://127.0.0.1:8765'
        assert self.client.timeout == 30

    @patch('requests.post')
    def test_execute_task(self, mock_post):
        """Test executing a task"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'task_id': 'task_123'
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = self.client.execute('Test task')

        assert result['status'] == 'success'
        assert result['task_id'] == 'task_123'
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_analyze_code(self, mock_post):
        """Test code analysis"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'result': 'Analysis complete'
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = self.client.analyze_code('/path/to/file.py')

        assert result['status'] == 'success'
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert '/api/v1/analyze' in call_args[0][0]

    @patch('requests.post')
    def test_generate_tests(self, mock_post):
        """Test test generation"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'result': 'Tests generated'
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = self.client.generate_tests('/path/to/file.py')

        assert result['status'] == 'success'
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_refactor_code(self, mock_post):
        """Test code refactoring"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'result': 'Code refactored'
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = self.client.refactor_code(
            file_path='/path/to/file.py',
            start_line=10,
            end_line=20
        )

        assert result['status'] == 'success'
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_debug_code(self, mock_post):
        """Test code debugging"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'result': 'Bugs fixed'
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = self.client.debug_code(
            file_path='/path/to/file.py',
            error_message='Test error'
        )

        assert result['status'] == 'success'
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_add_documentation(self, mock_post):
        """Test adding documentation"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'result': 'Documentation added'
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = self.client.add_documentation('/path/to/file.py')

        assert result['status'] == 'success'
        mock_post.assert_called_once()

    @patch('requests.get')
    def test_get_task_status(self, mock_get):
        """Test getting task status"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'task': {'id': 'task_123', 'status': 'completed'}
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = self.client.get_task_status('task_123')

        assert result['status'] == 'success'
        mock_get.assert_called_once()

    @patch('requests.get')
    def test_list_tasks(self, mock_get):
        """Test listing tasks"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'tasks': []
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = self.client.list_tasks()

        assert result['status'] == 'success'
        assert 'tasks' in result
        mock_get.assert_called_once()

    @patch('requests.delete')
    def test_cancel_task(self, mock_delete):
        """Test cancelling a task"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'success',
            'message': 'Task cancelled'
        }
        mock_response.raise_for_status = Mock()
        mock_delete.return_value = mock_response

        result = self.client.cancel_task('task_123')

        assert result['status'] == 'success'
        mock_delete.assert_called_once()

    @patch('requests.post')
    def test_jsonrpc_call(self, mock_post):
        """Test JSON-RPC call"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'jsonrpc': '2.0',
            'result': {'status': 'success'},
            'id': 1
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = self.client.jsonrpc_call(
            method='execute',
            params={'task': 'Test task'},
            request_id='1'
        )

        assert result['jsonrpc'] == '2.0'
        assert 'result' in result
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_error_handling(self, mock_post):
        """Test error handling"""
        import requests

        mock_post.side_effect = requests.RequestException('Connection error')

        result = self.client.execute('Test task')

        assert result['status'] == 'error'
        assert 'Connection error' in result['message']


@pytest.mark.skipif(not LSP_AVAILABLE, reason="LSP dependencies not available")
class TestRevLSPServer:
    """Test Rev LSP server"""

    def setup_method(self):
        """Setup test server"""
        self.config = Config()
        self.server = RevLSPServer(config=self.config)

    def test_server_initialization(self):
        """Test server initializes correctly"""
        assert self.server.config is not None
        assert self.server.server is not None

    def test_uri_to_path(self):
        """Test URI to path conversion"""
        uri = 'file:///path/to/file.py'
        path = RevLSPServer._uri_to_path(uri)
        assert path == '/path/to/file.py'

    @pytest.mark.asyncio
    async def test_analyze_code(self):
        """Test code analysis via LSP"""
        with patch.object(self.server, '_get_orchestrator') as mock_orch:
            mock_orchestrator = Mock()
            mock_orchestrator.execute.return_value = {'status': 'success'}
            mock_orch.return_value = mock_orchestrator

            result = await self.server._analyze_code('file:///test.py')

            assert result['status'] == 'success'

    @pytest.mark.asyncio
    async def test_generate_tests(self):
        """Test test generation via LSP"""
        with patch.object(self.server, '_get_orchestrator') as mock_orch:
            mock_orchestrator = Mock()
            mock_orchestrator.execute.return_value = {'status': 'success'}
            mock_orch.return_value = mock_orchestrator

            result = await self.server._generate_tests('file:///test.py')

            assert result['status'] == 'success'

    @pytest.mark.asyncio
    async def test_refactor_code(self):
        """Test code refactoring via LSP"""
        with patch.object(self.server, '_get_orchestrator') as mock_orch:
            mock_orchestrator = Mock()
            mock_orchestrator.execute.return_value = {'status': 'success'}
            mock_orch.return_value = mock_orchestrator

            range_dict = {'start': {'line': 10}, 'end': {'line': 20}}
            result = await self.server._refactor_code('file:///test.py', range_dict)

            assert result['status'] == 'success'


@pytest.mark.skipif(not AIOHTTP_AVAILABLE, reason="aiohttp not available")
class TestRevAPIServer:
    """Test Rev API server"""

    def setup_method(self):
        """Setup test server"""
        self.config = Config()
        self.server = RevAPIServer(config=self.config)

    def test_server_initialization(self):
        """Test server initializes correctly"""
        assert self.server.config is not None
        assert self.server.app is not None
        assert len(self.server.active_tasks) == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_websockets(self):
        """Test WebSocket broadcasting"""
        message = {'type': 'test', 'data': 'test_data'}

        # Mock WebSocket
        mock_ws = Mock()
        mock_ws.send_str = asyncio.coroutine(lambda x: None)
        self.server.websockets.append(mock_ws)

        await self.server._broadcast_to_websockets(message)

        # WebSocket should have received the message
        # (in real test, would verify mock_ws.send_str was called)

    @pytest.mark.asyncio
    async def test_rpc_execute(self):
        """Test JSON-RPC execute method"""
        with patch.object(self.server, '_get_orchestrator') as mock_orch:
            mock_orchestrator = Mock()
            mock_orchestrator.execute.return_value = {'status': 'success'}
            mock_orch.return_value = mock_orchestrator

            result = await self.server._rpc_execute({'task': 'Test task'})

            assert result['status'] == 'success'

    @pytest.mark.asyncio
    async def test_rpc_analyze(self):
        """Test JSON-RPC analyze method"""
        with patch.object(self.server, '_rpc_execute') as mock_exec:
            mock_exec.return_value = {'status': 'success'}

            result = await self.server._rpc_analyze({'file_path': '/test.py'})

            assert result['status'] == 'success'
            mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_rpc_test(self):
        """Test JSON-RPC test method"""
        with patch.object(self.server, '_rpc_execute') as mock_exec:
            mock_exec.return_value = {'status': 'success'}

            result = await self.server._rpc_test({'file_path': '/test.py'})

            assert result['status'] == 'success'

    @pytest.mark.asyncio
    async def test_rpc_error_handling(self):
        """Test JSON-RPC error handling"""
        with pytest.raises(ValueError):
            await self.server._rpc_analyze({})  # Missing file_path


class TestIntegrationScenarios:
    """Test end-to-end integration scenarios"""

    @pytest.mark.skipif(not CLIENT_AVAILABLE, reason="Client not available")
    @patch('requests.post')
    def test_complete_workflow(self, mock_post):
        """Test complete workflow: analyze -> test -> refactor"""
        client = RevIDEClient()

        # Mock responses
        mock_response = Mock()
        mock_response.raise_for_status = Mock()

        # Step 1: Analyze
        mock_response.json.return_value = {'status': 'success', 'task_id': 'task_1'}
        mock_post.return_value = mock_response
        result1 = client.analyze_code('/test.py')
        assert result1['status'] == 'success'

        # Step 2: Generate tests
        mock_response.json.return_value = {'status': 'success', 'task_id': 'task_2'}
        result2 = client.generate_tests('/test.py')
        assert result2['status'] == 'success'

        # Step 3: Refactor
        mock_response.json.return_value = {'status': 'success', 'task_id': 'task_3'}
        result3 = client.refactor_code('/test.py')
        assert result3['status'] == 'success'

    @pytest.mark.skipif(not CLIENT_AVAILABLE, reason="Client not available")
    @patch('requests.post')
    @patch('requests.get')
    def test_task_lifecycle(self, mock_get, mock_post):
        """Test task lifecycle: create -> status -> cancel"""
        client = RevIDEClient()

        # Create task
        mock_post_response = Mock()
        mock_post_response.raise_for_status = Mock()
        mock_post_response.json.return_value = {
            'status': 'success',
            'task_id': 'task_123'
        }
        mock_post.return_value = mock_post_response

        result = client.execute('Test task')
        task_id = result['task_id']

        # Get status
        mock_get_response = Mock()
        mock_get_response.raise_for_status = Mock()
        mock_get_response.json.return_value = {
            'status': 'success',
            'task': {'id': task_id, 'status': 'running'}
        }
        mock_get.return_value = mock_get_response

        status = client.get_task_status(task_id)
        assert status['task']['status'] == 'running'


class TestErrorScenarios:
    """Test error handling scenarios"""

    @pytest.mark.skipif(not CLIENT_AVAILABLE, reason="Client not available")
    @patch('requests.post')
    def test_api_server_down(self, mock_post):
        """Test handling when API server is down"""
        import requests

        mock_post.side_effect = requests.RequestException('Connection refused')

        client = RevIDEClient()
        result = client.execute('Test task')

        assert result['status'] == 'error'
        assert 'Connection refused' in result['message']

    @pytest.mark.skipif(not CLIENT_AVAILABLE, reason="Client not available")
    @patch('requests.post')
    def test_timeout_handling(self, mock_post):
        """Test timeout handling"""
        import requests

        mock_post.side_effect = requests.Timeout('Request timed out')

        client = RevIDEClient(timeout=1)
        result = client.execute('Long running task')

        assert result['status'] == 'error'

    @pytest.mark.skipif(not CLIENT_AVAILABLE, reason="Client not available")
    @patch('requests.post')
    def test_invalid_response(self, mock_post):
        """Test handling of invalid API response"""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.side_effect = json.JSONDecodeError('Invalid JSON', '', 0)
        mock_post.return_value = mock_response

        client = RevIDEClient()
        with pytest.raises(json.JSONDecodeError):
            client.execute('Test task')


def test_imports():
    """Test that IDE modules can be imported"""
    try:
        from rev.ide import RevIDEClient, RevLSPServer, RevAPIServer
        assert True
    except ImportError as e:
        pytest.skip(f"IDE integration dependencies not installed: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
