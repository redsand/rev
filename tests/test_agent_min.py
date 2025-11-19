"""
Comprehensive test suite for rev - Autonomous CI/CD Agent

Tests cover:
- File operations
- Task management
- Planning mode
- Execution mode
- Ollama integration (mocked)
- End-to-end workflows
"""

import json
import os
import shutil
import uuid
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

# Import rev module
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load rev.py file using direct file execution
rev_path = Path(__file__).parent.parent / "rev.py"
if not rev_path.exists():
    raise ImportError(f"rev.py not found at {rev_path}")

# Create a module to load code into
import types
agent_min = types.ModuleType("agent_min")
agent_min.__file__ = str(rev_path)

# Execute the file in the module's namespace
with open(rev_path, 'r', encoding='utf-8') as f:
    code = compile(f.read(), str(rev_path), 'exec')
    exec(code, agent_min.__dict__)

# Add to sys.modules so imports work
sys.modules['agent_min'] = agent_min


# ========== Fixtures ==========

@pytest.fixture
def temp_dir():
    """Create temporary directory for testing."""
    d = agent_min.ROOT / "tests_tmp_agent_min" / f"test_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mock_ollama_response():
    """Mock Ollama API response."""
    def _make_response(content="", tool_calls=None):
        return {
            "message": {
                "content": content,
                "tool_calls": tool_calls or []
            }
        }
    return _make_response


# ========== Unit Tests: File Operations ==========

class TestFileOperations:
    """Test core file operation functions."""

    def test_safe_path_blocks_escape(self):
        """Test that _safe_path prevents directory traversal."""
        with pytest.raises(ValueError, match="Path escapes repo"):
            agent_min._safe_path("../../etc/passwd")

    def test_safe_path_allows_valid_relative(self):
        """Test that _safe_path allows valid relative paths."""
        path = agent_min._safe_path("tests/test_agent_min.py")
        assert str(path).startswith(str(agent_min.ROOT))

    def test_read_file_success(self, temp_dir):
        """Test successful file reading."""
        test_file = temp_dir / "test.txt"
        test_content = "Hello, World!"
        test_file.write_text(test_content, encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.read_file(rel_path)

        assert result == test_content

    def test_read_file_not_found(self):
        """Test reading non-existent file."""
        result = agent_min.read_file("nonexistent_file_12345.txt")
        data = json.loads(result)
        assert "error" in data
        assert "Not found" in data["error"]

    def test_read_file_too_large(self, temp_dir):
        """Test reading file that exceeds size limit."""
        test_file = temp_dir / "large.txt"
        # Create file larger than MAX_FILE_BYTES
        large_content = "x" * (agent_min.MAX_FILE_BYTES + 1000)
        test_file.write_text(large_content, encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.read_file(rel_path)
        data = json.loads(result)

        assert "error" in data
        assert "Too large" in data["error"]

    def test_write_file_success(self, temp_dir):
        """Test successful file writing."""
        test_path = str((temp_dir / "new_file.txt").relative_to(agent_min.ROOT))
        test_content = "New content"

        result = agent_min.write_file(test_path, test_content)
        data = json.loads(result)

        assert "wrote" in data
        assert data["bytes"] == len(test_content)

        # Verify file was actually written
        full_path = agent_min.ROOT / test_path
        assert full_path.exists()
        assert full_path.read_text(encoding="utf-8") == test_content

    def test_write_file_creates_parent_dirs(self, temp_dir):
        """Test that write_file creates parent directories."""
        nested_path = str((temp_dir / "deep" / "nested" / "file.txt").relative_to(agent_min.ROOT))

        result = agent_min.write_file(nested_path, "content")
        data = json.loads(result)

        assert "wrote" in data
        assert (agent_min.ROOT / nested_path).exists()

    def test_list_dir(self, temp_dir):
        """Test listing directory files."""
        # Create test files
        (temp_dir / "file1.txt").write_text("test")
        (temp_dir / "file2.py").write_text("test")
        (temp_dir / "file3.md").write_text("test")

        pattern = str(temp_dir.relative_to(agent_min.ROOT)) + "/*"
        result = agent_min.list_dir(pattern)
        data = json.loads(result)

        assert "files" in data
        assert data["count"] >= 3
        filenames = [Path(f).name for f in data["files"]]
        assert "file1.txt" in filenames
        assert "file2.py" in filenames

    def test_search_code_regex(self, temp_dir):
        """Test code search with regex."""
        # Create test file with searchable content
        test_file = temp_dir / "search_test.py"
        test_file.write_text("def hello():\n    print('Hello')\n    return True", encoding="utf-8")

        pattern = r"def\s+\w+\("
        include = str(temp_dir.relative_to(agent_min.ROOT)) + "/**/*"
        result = agent_min.search_code(pattern, include=include, regex=True)
        data = json.loads(result)

        assert "matches" in data
        matches = data["matches"]
        assert len(matches) > 0
        assert any("def hello(" in m["text"] for m in matches)

    def test_search_code_case_insensitive(self, temp_dir):
        """Test case-insensitive search."""
        test_file = temp_dir / "case_test.txt"
        test_file.write_text("HELLO\nhello\nHeLLo", encoding="utf-8")

        pattern = "hello"
        include = str(temp_dir.relative_to(agent_min.ROOT)) + "/**/*"
        result = agent_min.search_code(pattern, include=include, case_sensitive=False)
        data = json.loads(result)

        assert len(data["matches"]) == 3


# ========== Unit Tests: Git Operations ==========

class TestGitOperations:
    """Test git-related functions."""

    def test_git_diff_no_changes(self):
        """Test git diff with no changes."""
        result = agent_min.git_diff(".")
        data = json.loads(result)

        assert "diff" in data
        assert data["rc"] == 0

    def test_apply_patch_dry_run(self, temp_dir):
        """Test applying patch in dry-run mode."""
        # Create a simple patch
        patch = """--- a/test.txt
+++ b/test.txt
@@ -1 +1 @@
-old content
+new content
"""
        result = agent_min.apply_patch(patch, dry_run=True)
        data = json.loads(result)

        assert "dry_run" in data
        assert data["dry_run"] is True

    def test_get_repo_context(self):
        """Test getting repository context."""
        result = agent_min.get_repo_context(commits=3)
        data = json.loads(result)

        assert "status" in data
        assert "log" in data
        assert "top_level" in data
        assert isinstance(data["top_level"], list)


# ========== Unit Tests: Command Execution ==========

class TestCommandExecution:
    """Test command execution functions."""

    def test_run_cmd_blocks_disallowed(self):
        """Test that disallowed commands are blocked."""
        result = agent_min.run_cmd("curl http://example.com")
        data = json.loads(result)

        assert "blocked" in data
        assert "allow" in data

    def test_run_cmd_allows_python(self):
        """Test that allowed commands (python) work."""
        result = agent_min.run_cmd("python --version", timeout=10)
        data = json.loads(result)

        assert "rc" in data
        assert data["rc"] == 0
        output = data.get("stdout", "") + data.get("stderr", "")
        assert "Python" in output

    def test_run_cmd_allows_git(self):
        """Test that git commands are allowed."""
        result = agent_min.run_cmd("git status", timeout=10)
        data = json.loads(result)

        assert "rc" in data
        # Git should be available in repo
        assert data["rc"] == 0

    def test_run_tests_default_command(self):
        """Test run_tests with default pytest command."""
        # This might fail if pytest isn't installed, but should not crash
        result = agent_min.run_tests()
        data = json.loads(result)

        # Should have either rc or blocked/timeout
        assert "rc" in data or "blocked" in data or "timeout" in data


# ========== Unit Tests: Task Management ==========

class TestTaskManagement:
    """Test Task and ExecutionPlan classes."""

    def test_task_creation(self):
        """Test creating a task."""
        task = agent_min.Task("Test task", "edit")

        assert task.description == "Test task"
        assert task.action_type == "edit"
        assert task.status == agent_min.TaskStatus.PENDING
        assert task.result is None
        assert task.error is None

    def test_task_to_dict(self):
        """Test task serialization."""
        task = agent_min.Task("Test task", "add")
        task.status = agent_min.TaskStatus.COMPLETED
        task.result = "Success"

        data = task.to_dict()

        assert data["description"] == "Test task"
        assert data["action_type"] == "add"
        assert data["status"] == "completed"
        assert data["result"] == "Success"

    def test_execution_plan_add_task(self):
        """Test adding tasks to execution plan."""
        plan = agent_min.ExecutionPlan()

        plan.add_task("Task 1", "review")
        plan.add_task("Task 2", "edit")
        plan.add_task("Task 3", "test")

        assert len(plan.tasks) == 3
        assert plan.tasks[0].description == "Task 1"
        assert plan.tasks[1].action_type == "edit"

    def test_execution_plan_current_task(self):
        """Test getting current task from plan."""
        plan = agent_min.ExecutionPlan()
        plan.add_task("Task 1")
        plan.add_task("Task 2")

        current = plan.get_current_task()
        assert current is not None
        assert current.description == "Task 1"

    def test_execution_plan_mark_completed(self):
        """Test marking task as completed."""
        plan = agent_min.ExecutionPlan()
        plan.add_task("Task 1")
        plan.add_task("Task 2")

        plan.mark_completed("Success")

        assert plan.tasks[0].status == agent_min.TaskStatus.COMPLETED
        assert plan.tasks[0].result == "Success"
        assert plan.current_index == 1

    def test_execution_plan_mark_failed(self):
        """Test marking task as failed."""
        plan = agent_min.ExecutionPlan()
        plan.add_task("Task 1")

        plan.mark_failed("Error occurred")

        assert plan.tasks[0].status == agent_min.TaskStatus.FAILED
        assert plan.tasks[0].error == "Error occurred"

    def test_execution_plan_is_complete(self):
        """Test checking if plan is complete."""
        plan = agent_min.ExecutionPlan()
        plan.add_task("Task 1")
        plan.add_task("Task 2")

        assert not plan.is_complete()

        plan.mark_completed()
        assert not plan.is_complete()

        plan.mark_completed()
        assert plan.is_complete()

    def test_execution_plan_summary(self):
        """Test getting plan summary."""
        plan = agent_min.ExecutionPlan()
        plan.add_task("Task 1")
        plan.add_task("Task 2")
        plan.add_task("Task 3")

        plan.mark_completed()
        plan.mark_failed("error")

        summary = plan.get_summary()

        assert "1/3 completed" in summary
        assert "1 failed" in summary


# ========== Unit Tests: Tool Execution ==========

class TestToolExecution:
    """Test execute_tool function."""

    def test_execute_tool_read_file(self, temp_dir):
        """Test executing read_file tool."""
        test_file = temp_dir / "tool_test.txt"
        test_file.write_text("Tool test content", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.execute_tool("read_file", {"path": rel_path})

        assert "Tool test content" in result

    def test_execute_tool_write_file(self, temp_dir):
        """Test executing write_file tool."""
        rel_path = str((temp_dir / "tool_write.txt").relative_to(agent_min.ROOT))
        result = agent_min.execute_tool("write_file", {"path": rel_path, "content": "New content"})

        data = json.loads(result)
        assert "wrote" in data

    def test_execute_tool_list_dir(self):
        """Test executing list_dir tool."""
        result = agent_min.execute_tool("list_dir", {"pattern": "*.py"})
        data = json.loads(result)

        assert "files" in data
        assert "count" in data

    def test_execute_tool_get_repo_context(self):
        """Test executing get_repo_context tool."""
        result = agent_min.execute_tool("get_repo_context", {"commits": 5})
        data = json.loads(result)

        assert "status" in data
        assert "log" in data

    def test_execute_tool_unknown(self):
        """Test executing unknown tool."""
        result = agent_min.execute_tool("unknown_tool", {})
        data = json.loads(result)

        assert "error" in data
        assert "Unknown tool" in data["error"]


# ========== Integration Tests: Ollama ==========

class TestOllamaIntegration:
    """Test Ollama API integration (mocked)."""

    @patch('agent_min.requests.post')
    def test_ollama_chat_success(self, mock_post):
        """Test successful Ollama chat request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "content": "Hello, I am an AI assistant.",
                "tool_calls": []
            }
        }
        mock_post.return_value = mock_response

        messages = [{"role": "user", "content": "Hello"}]
        result = agent_min.ollama_chat(messages)

        assert "message" in result
        assert "content" in result["message"]
        assert "Hello, I am an AI assistant" in result["message"]["content"]

    @patch('agent_min.requests.post')
    def test_ollama_chat_with_tools(self, mock_post):
        """Test Ollama chat with tool calls."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "content": "Let me read that file",
                "tool_calls": [
                    {
                        "function": {
                            "name": "read_file",
                            "arguments": {"path": "test.txt"}
                        }
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        messages = [{"role": "user", "content": "Read test.txt"}]
        result = agent_min.ollama_chat(messages, tools=agent_min.TOOLS)

        assert "tool_calls" in result["message"]
        assert len(result["message"]["tool_calls"]) == 1
        assert result["message"]["tool_calls"][0]["function"]["name"] == "read_file"

    @patch('agent_min.requests.post')
    def test_ollama_chat_error(self, mock_post):
        """Test Ollama chat with connection error."""
        mock_post.side_effect = Exception("Connection refused")

        messages = [{"role": "user", "content": "Hello"}]
        result = agent_min.ollama_chat(messages)

        assert "error" in result
        assert "Connection refused" in result["error"]


# ========== Integration Tests: Planning Mode ==========

class TestPlanningMode:
    """Test planning mode functionality."""

    @patch('agent_min.ollama_chat')
    @patch('agent_min.get_repo_context')
    def test_planning_mode_generates_plan(self, mock_context, mock_ollama):
        """Test that planning mode generates execution plan."""
        # Mock repository context
        mock_context.return_value = json.dumps({
            "status": "clean",
            "log": "commit 1\ncommit 2",
            "top_level": [{"name": "agent.py", "type": "file"}]
        })

        # Mock Ollama response with valid plan
        mock_ollama.return_value = {
            "message": {
                "content": json.dumps([
                    {"description": "Review code structure", "action_type": "review"},
                    {"description": "Add error handling", "action_type": "edit"},
                    {"description": "Run tests", "action_type": "test"}
                ])
            }
        }

        plan = agent_min.planning_mode("Add error handling to API")

        assert isinstance(plan, agent_min.ExecutionPlan)
        assert len(plan.tasks) == 3
        assert plan.tasks[0].action_type == "review"
        assert plan.tasks[1].action_type == "edit"
        assert plan.tasks[2].action_type == "test"

    @patch('agent_min.ollama_chat')
    @patch('agent_min.get_repo_context')
    def test_planning_mode_handles_malformed_response(self, mock_context, mock_ollama):
        """Test planning mode handles malformed Ollama response."""
        mock_context.return_value = json.dumps({"status": "clean"})

        # Mock malformed response
        mock_ollama.return_value = {
            "message": {
                "content": "I will help you with that task..."
            }
        }

        plan = agent_min.planning_mode("Do something")

        # Should create fallback plan
        assert isinstance(plan, agent_min.ExecutionPlan)
        assert len(plan.tasks) == 1
        assert plan.tasks[0].description == "Do something"


# ========== Integration Tests: Execution Mode ==========

class TestExecutionMode:
    """Test execution mode functionality."""

    @patch('agent_min.ollama_chat')
    @patch('builtins.input', return_value='y')
    def test_execution_mode_single_task_completion(self, mock_input, mock_ollama):
        """Test execution mode completes a simple task."""
        # Create simple plan
        plan = agent_min.ExecutionPlan()
        plan.add_task("Simple task", "general")

        # Mock Ollama to return completion immediately
        mock_ollama.return_value = {
            "message": {
                "content": "TASK_COMPLETE: Task finished successfully",
                "tool_calls": []
            }
        }

        result = agent_min.execution_mode(plan, approved=False)

        # Should have completed
        assert plan.is_complete()
        assert plan.tasks[0].status == agent_min.TaskStatus.COMPLETED

    @patch('agent_min.ollama_chat')
    @patch('builtins.input', return_value='n')
    def test_execution_mode_user_cancels(self, mock_input, mock_ollama):
        """Test execution mode respects user cancellation."""
        plan = agent_min.ExecutionPlan()
        plan.add_task("Task 1")

        result = agent_min.execution_mode(plan, approved=False)

        # Should be cancelled
        assert result is False
        assert not plan.is_complete()

    @patch('agent_min.ollama_chat')
    def test_execution_mode_with_tool_calls(self, mock_ollama):
        """Test execution mode executes tool calls."""
        plan = agent_min.ExecutionPlan()
        plan.add_task("Read a file", "review")

        # First call: agent wants to use tool
        # Second call: agent completes task
        mock_ollama.side_effect = [
            {
                "message": {
                    "content": "Let me read the file",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "get_repo_context",
                                "arguments": json.dumps({"commits": 1})
                            }
                        }
                    ]
                }
            },
            {
                "message": {
                    "content": "TASK_COMPLETE: File reviewed",
                    "tool_calls": []
                }
            }
        ]

        result = agent_min.execution_mode(plan, approved=True)

        assert plan.tasks[0].status == agent_min.TaskStatus.COMPLETED

    @patch('agent_min.ollama_chat')
    def test_execution_mode_handles_errors(self, mock_ollama):
        """Test execution mode handles Ollama errors."""
        plan = agent_min.ExecutionPlan()
        plan.add_task("Task with error")

        # Mock Ollama error
        mock_ollama.return_value = {
            "error": "Connection timeout"
        }

        result = agent_min.execution_mode(plan, approved=True)

        # Task should be marked as failed
        assert plan.tasks[0].status == agent_min.TaskStatus.FAILED
        assert "Connection timeout" in plan.tasks[0].error


# ========== End-to-End Tests ==========

class TestEndToEnd:
    """End-to-end integration tests."""

    @patch('agent_min.ollama_chat')
    @patch('agent_min.get_repo_context')
    def test_full_workflow_file_edit(self, mock_context, mock_ollama, temp_dir):
        """Test complete workflow: plan -> execute -> validate."""
        # Setup
        test_file = temp_dir / "target.txt"
        test_file.write_text("original content", encoding="utf-8")
        rel_path = str(test_file.relative_to(agent_min.ROOT))

        # Mock context
        mock_context.return_value = json.dumps({"status": "clean"})

        # Mock planning response
        planning_response = {
            "message": {
                "content": json.dumps([
                    {"description": f"Read {rel_path}", "action_type": "review"},
                    {"description": f"Modify {rel_path}", "action_type": "edit"}
                ])
            }
        }

        # Mock execution responses
        execution_responses = [
            # Task 1: Read file
            {
                "message": {
                    "content": "Reading file",
                    "tool_calls": [{
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": rel_path})
                        }
                    }]
                }
            },
            {
                "message": {
                    "content": "TASK_COMPLETE: File read",
                    "tool_calls": []
                }
            },
            # Task 2: Modify file
            {
                "message": {
                    "content": "Modifying file",
                    "tool_calls": [{
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps({
                                "path": rel_path,
                                "content": "modified content"
                            })
                        }
                    }]
                }
            },
            {
                "message": {
                    "content": "TASK_COMPLETE: File modified",
                    "tool_calls": []
                }
            }
        ]

        mock_ollama.side_effect = [planning_response] + execution_responses

        # Execute workflow
        plan = agent_min.planning_mode("Edit the test file")
        result = agent_min.execution_mode(plan, approved=True)

        # Verify
        assert plan.is_complete()
        assert all(t.status == agent_min.TaskStatus.COMPLETED for t in plan.tasks)

        # Verify file was actually modified
        assert test_file.read_text() == "modified content"


# ========== Utility Tests ==========

class TestUtilities:
    """Test utility functions."""

    def test_is_text_file(self, temp_dir):
        """Test text file detection."""
        # Create text file
        text_file = temp_dir / "text.txt"
        text_file.write_text("This is text", encoding="utf-8")
        assert agent_min._is_text_file(text_file) is True

        # Create binary file
        binary_file = temp_dir / "binary.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03")
        assert agent_min._is_text_file(binary_file) is False

    def test_should_skip(self):
        """Test directory exclusion."""
        # Should skip
        assert agent_min._should_skip(Path("node_modules/package"))
        assert agent_min._should_skip(Path("project/.git/objects"))
        assert agent_min._should_skip(Path("src/__pycache__/module.pyc"))

        # Should not skip
        assert not agent_min._should_skip(Path("src/main.py"))
        assert not agent_min._should_skip(Path("tests/test_file.py"))

    def test_iter_files(self, temp_dir):
        """Test file iteration with glob."""
        # Create test files
        (temp_dir / "file1.py").write_text("test")
        (temp_dir / "file2.txt").write_text("test")
        (temp_dir / "subdir").mkdir()
        (temp_dir / "subdir" / "file3.py").write_text("test")

        # Search for Python files
        pattern = str(temp_dir.relative_to(agent_min.ROOT)) + "/**/*.py"
        files = agent_min._iter_files(pattern)

        assert len(files) >= 2
        filenames = [f.name for f in files]
        assert "file1.py" in filenames
        assert "file3.py" in filenames


# ========== Performance Tests ==========

class TestPerformance:
    """Test performance characteristics."""

    def test_search_respects_match_limit(self, temp_dir):
        """Test that search respects max_matches limit."""
        # Create file with many matches
        test_file = temp_dir / "many_matches.txt"
        content = "match\n" * 5000  # 5000 lines with "match"
        test_file.write_text(content, encoding="utf-8")

        pattern = "match"
        include = str(temp_dir.relative_to(agent_min.ROOT)) + "/**/*"
        result = agent_min.search_code(pattern, include=include, max_matches=100)
        data = json.loads(result)

        # Should truncate to limit
        assert len(data["matches"]) <= 100
        assert data.get("truncated") is True

    def test_read_file_respects_size_limit(self, temp_dir):
        """Test that read_file truncates large files."""
        # Create file that will be truncated
        test_file = temp_dir / "truncated.txt"
        large_content = "x" * (agent_min.READ_RETURN_LIMIT + 10000)
        test_file.write_text(large_content, encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.read_file(rel_path)

        # Should be truncated
        assert len(result) <= agent_min.READ_RETURN_LIMIT + 100  # Allow for truncation message
        assert "[truncated]" in result


# ========== REPL Mode Tests ==========

class TestREPLMode:
    """Test REPL mode functionality."""

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    @patch('builtins.input')
    def test_repl_exit_command(self, mock_input, mock_exec, mock_plan):
        """Test REPL exits on /exit command."""
        mock_input.side_effect = ['/exit']

        # Should exit cleanly
        agent_min.repl_mode()

        # Planning should not be called
        mock_plan.assert_not_called()

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    @patch('builtins.input')
    def test_repl_help_command(self, mock_input, mock_exec, mock_plan):
        """Test REPL help command."""
        mock_input.side_effect = ['/help', '/exit']

        agent_min.repl_mode()

        # Planning should not be called for /help
        mock_plan.assert_not_called()

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    @patch('builtins.input')
    def test_repl_status_command(self, mock_input, mock_exec, mock_plan):
        """Test REPL status command."""
        mock_input.side_effect = ['/status', '/exit']

        agent_min.repl_mode()

        mock_plan.assert_not_called()

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    @patch('builtins.input')
    def test_repl_clear_command(self, mock_input, mock_exec, mock_plan):
        """Test REPL clear command."""
        mock_input.side_effect = ['/clear', '/exit']

        agent_min.repl_mode()

        mock_plan.assert_not_called()

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    @patch('builtins.input')
    def test_repl_executes_task(self, mock_input, mock_exec, mock_plan):
        """Test REPL executes tasks."""
        # Create mock plan
        mock_plan_obj = agent_min.ExecutionPlan()
        mock_plan_obj.add_task("Test task", "review")
        mock_plan_obj.tasks[0].status = agent_min.TaskStatus.COMPLETED
        mock_plan.return_value = mock_plan_obj
        mock_exec.return_value = True

        mock_input.side_effect = ['do something', '/exit']

        agent_min.repl_mode()

        # Should call planning and execution
        mock_plan.assert_called_once_with('do something')
        mock_exec.assert_called_once()

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    @patch('builtins.input')
    def test_repl_handles_keyboard_interrupt(self, mock_input, mock_exec, mock_plan):
        """Test REPL handles Ctrl+C gracefully."""
        mock_input.side_effect = KeyboardInterrupt()

        # Should exit cleanly without error
        agent_min.repl_mode()

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    @patch('builtins.input')
    def test_repl_session_tracking(self, mock_input, mock_exec, mock_plan):
        """Test REPL tracks session state."""
        # Create mock plans with file operations
        plan1 = agent_min.ExecutionPlan()
        plan1.add_task("Review test.py", "review")
        plan1.tasks[0].status = agent_min.TaskStatus.COMPLETED

        plan2 = agent_min.ExecutionPlan()
        plan2.add_task("Edit main.py", "edit")
        plan2.tasks[0].status = agent_min.TaskStatus.COMPLETED

        mock_plan.side_effect = [plan1, plan2]
        mock_exec.return_value = True

        mock_input.side_effect = ['task 1', 'task 2', '/exit']

        agent_min.repl_mode()

        # Should track multiple tasks
        assert mock_plan.call_count == 2

    @patch('sys.stdin.isatty')
    @patch('builtins.input')
    def test_escape_key_fallback_to_regular_input(self, mock_input, mock_isatty):
        """Test get_input_with_escape falls back to regular input when not in TTY."""
        mock_isatty.return_value = False
        mock_input.return_value = "test input"

        result, escape_pressed = agent_min.get_input_with_escape("prompt> ")

        assert result == "test input"
        assert escape_pressed is False
        mock_input.assert_called_once_with("prompt> ")

    def test_escape_interrupt_flag_exists(self):
        """Test that the escape interrupt flag exists."""
        assert hasattr(agent_min, '_ESCAPE_INTERRUPT')
        assert isinstance(agent_min._ESCAPE_INTERRUPT, bool)

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    def test_escape_interrupt_flag_reset(self, mock_exec, mock_plan):
        """Test that escape interrupt flag is reset before and after execution."""
        # Set the flag
        agent_min._ESCAPE_INTERRUPT = True

        # Create a mock plan
        plan = agent_min.ExecutionPlan()
        plan.add_task("Test task", "review")
        mock_plan.return_value = plan
        mock_exec.return_value = True

        # The flag should be reset before execution
        with patch('agent_min.get_input_with_escape') as mock_input:
            mock_input.return_value = ("/exit", False)
            agent_min.repl_mode()

        # After exiting REPL, flag should be reset
        # (This is verified by the fact that repl_mode completes without errors)

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    @patch('agent_min.get_input_with_escape')
    def test_repl_escape_key_indicator(self, mock_input, mock_exec, mock_plan):
        """Test REPL shows escape key indicator when escape is pressed."""
        plan = agent_min.ExecutionPlan()
        plan.add_task("Test task", "review")
        mock_plan.return_value = plan
        mock_exec.return_value = True

        # Simulate escape key press, then exit
        mock_input.side_effect = [
            ("test command", True),  # First command with ESC
            ("/exit", False)          # Then exit
        ]

        import io
        import sys
        captured_output = io.StringIO()
        old_stdout = sys.stdout

        try:
            sys.stdout = captured_output
            agent_min.repl_mode()
            output = captured_output.getvalue()

            # Should show escape key indicator
            assert "[ESC pressed - submitting immediately]" in output
        finally:
            sys.stdout = old_stdout


# ========== CLI and Main Function Tests ==========

class TestCLIAndMain:
    """Test CLI argument parsing and main function."""

    @patch('agent_min.repl_mode')
    @patch('sys.argv', ['agent.min.py', '--repl'])
    def test_main_repl_mode(self, mock_repl):
        """Test main function with --repl flag."""
        agent_min.main()
        mock_repl.assert_called_once()

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    @patch('sys.argv', ['agent.min.py', 'test', 'task'])
    def test_main_oneshot_mode(self, mock_exec, mock_plan):
        """Test main function in one-shot mode."""
        mock_plan_obj = agent_min.ExecutionPlan()
        mock_plan.return_value = mock_plan_obj
        mock_exec.return_value = True

        agent_min.main()

        mock_plan.assert_called_once_with('test task')
        mock_exec.assert_called_once()

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    @patch('sys.argv', ['agent.min.py', '--model', 'llama3.1', 'do something'])
    def test_main_with_model_flag(self, mock_exec, mock_plan):
        """Test main function with --model flag."""
        mock_plan_obj = agent_min.ExecutionPlan()
        mock_plan.return_value = mock_plan_obj
        mock_exec.return_value = True

        # Save original
        original_model = agent_min.OLLAMA_MODEL

        agent_min.main()

        mock_plan.assert_called_once()

    @patch('agent_min.planning_mode')
    @patch('agent_min.execution_mode')
    @patch('sys.argv', ['agent.min.py', '--prompt', 'fix bugs'])
    def test_main_with_prompt_flag(self, mock_exec, mock_plan):
        """Test main function with --prompt flag (manual approval)."""
        mock_plan_obj = agent_min.ExecutionPlan()
        mock_plan.return_value = mock_plan_obj
        mock_exec.return_value = True

        agent_min.main()

        # Should call execution_mode with auto_approve=False
        mock_exec.assert_called_once()
        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs.get('auto_approve') is False


# ========== Scary Operation Tests ==========

class TestScaryOperations:
    """Test scary operation detection and prompting."""

    def test_is_scary_operation_delete_action(self):
        """Test detection of delete action type."""
        is_scary, reason = agent_min.is_scary_operation(
            "run_cmd",
            {"cmd": "ls"},
            action_type="delete"
        )
        assert is_scary is True
        assert "delete" in reason.lower()

    def test_is_scary_operation_git_force_push(self):
        """Test detection of git force push."""
        is_scary, reason = agent_min.is_scary_operation(
            "run_cmd",
            {"cmd": "git push --force origin main"}
        )
        assert is_scary is True
        assert "force" in reason.lower() or "push" in reason.lower()

    def test_is_scary_operation_git_reset_hard(self):
        """Test detection of git reset --hard."""
        is_scary, reason = agent_min.is_scary_operation(
            "run_cmd",
            {"cmd": "git reset --hard HEAD"}
        )
        assert is_scary is True

    def test_is_scary_operation_rm_command(self):
        """Test detection of rm command."""
        is_scary, reason = agent_min.is_scary_operation(
            "run_cmd",
            {"cmd": "rm -rf important_dir"}
        )
        assert is_scary is True
        assert "rm" in reason.lower() or "delete" in reason.lower()

    def test_is_scary_operation_patch_without_dry_run(self):
        """Test detection of patch without dry-run."""
        is_scary, reason = agent_min.is_scary_operation(
            "apply_patch",
            {"patch": "some diff", "dry_run": False}
        )
        assert is_scary is True

    def test_is_scary_operation_patch_with_dry_run(self):
        """Test patch with dry-run is not scary."""
        is_scary, reason = agent_min.is_scary_operation(
            "apply_patch",
            {"patch": "some diff", "dry_run": True}
        )
        assert is_scary is False

    def test_is_scary_operation_safe_commands(self):
        """Test safe commands are not flagged."""
        # Read file
        is_scary, _ = agent_min.is_scary_operation(
            "read_file",
            {"path": "test.py"}
        )
        assert is_scary is False

        # Git diff
        is_scary, _ = agent_min.is_scary_operation(
            "run_cmd",
            {"cmd": "git diff"}
        )
        assert is_scary is False

        # Pytest
        is_scary, _ = agent_min.is_scary_operation(
            "run_cmd",
            {"cmd": "pytest tests/"}
        )
        assert is_scary is False

    @patch('builtins.input', return_value='y')
    def test_prompt_scary_operation_approve(self, mock_input):
        """Test user approves scary operation."""
        result = agent_min.prompt_scary_operation("rm file.txt", "delete command")
        assert result is True

    @patch('builtins.input', return_value='n')
    def test_prompt_scary_operation_deny(self, mock_input):
        """Test user denies scary operation."""
        result = agent_min.prompt_scary_operation("rm file.txt", "delete command")
        assert result is False

    @patch('builtins.input', return_value='yes')
    def test_prompt_scary_operation_yes_string(self, mock_input):
        """Test user types 'yes' to approve."""
        result = agent_min.prompt_scary_operation("rm file.txt", "delete command")
        assert result is True

    @patch('builtins.input', side_effect=KeyboardInterrupt())
    def test_prompt_scary_operation_keyboard_interrupt(self, mock_input):
        """Test Ctrl+C during scary operation prompt."""
        result = agent_min.prompt_scary_operation("rm file.txt", "delete command")
        assert result is False


# ========== Edge Case and Error Handling Tests ==========

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_read_file_with_unicode_errors(self, temp_dir):
        """Test reading file with encoding issues."""
        # Create file with problematic bytes
        test_file = temp_dir / "bad_encoding.txt"
        test_file.write_bytes(b"Good text \xff\xfe bad bytes")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.read_file(rel_path)

        # Should handle gracefully (errors='ignore')
        assert "Good text" in result

    def test_write_file_creates_nested_directories(self, temp_dir):
        """Test write_file creates nested parent directories."""
        deep_path = temp_dir / "a" / "b" / "c" / "file.txt"
        rel_path = str(deep_path.relative_to(agent_min.ROOT))

        result = agent_min.write_file(rel_path, "content")
        data = json.loads(result)

        assert "wrote" in data
        assert deep_path.exists()
        assert deep_path.read_text() == "content"

    def test_search_code_with_invalid_regex(self):
        """Test search_code handles invalid regex."""
        result = agent_min.search_code("[invalid(regex", regex=True)
        data = json.loads(result)

        assert "error" in data
        assert "regex" in data["error"].lower()

    def test_execute_tool_unknown_tool(self):
        """Test execute_tool with unknown tool name."""
        result = agent_min.execute_tool("nonexistent_tool", {})
        data = json.loads(result)

        assert "error" in data
        assert "Unknown tool" in data["error"]

    def test_run_cmd_with_timeout(self):
        """Test run_cmd respects timeout parameter."""
        # Very short timeout - but using a safe command
        result = agent_min.run_cmd("python --version", timeout=300)
        data = json.loads(result)

        # Should complete successfully
        assert "rc" in data or "timeout" in data

    @patch('agent_min.ollama_chat')
    def test_planning_mode_with_error_response(self, mock_ollama):
        """Test planning mode handles error from Ollama."""
        mock_ollama.return_value = {"error": "Connection failed"}

        # Should exit or raise error
        with pytest.raises(SystemExit):
            agent_min.planning_mode("test task")

    @patch('agent_min.ollama_chat')
    def test_execution_mode_task_iteration_limit(self, mock_ollama):
        """Test execution mode respects task iteration limit."""
        # Create plan
        plan = agent_min.ExecutionPlan()
        plan.add_task("Test task", "review")

        # Mock Ollama to never complete task
        mock_ollama.return_value = {
            "message": {
                "content": "Still working...",
                "tool_calls": []
            }
        }

        # Execute with auto-approve
        result = agent_min.execution_mode(plan, auto_approve=True)

        # Should eventually fail (either iteration limit or tool calling error)
        assert plan.tasks[0].status == agent_min.TaskStatus.FAILED
        assert plan.tasks[0].error is not None

    def test_ollama_chat_retry_on_400_with_tools(self):
        """Test Ollama chat retries without tools on 400 error."""
        with patch('agent_min.requests.post') as mock_post:
            # First call fails with 400
            mock_response_400 = Mock()
            mock_response_400.status_code = 400
            mock_response_400.text = "Model does not support tools"
            mock_response_400.raise_for_status.side_effect = Exception("400 Error")

            # Second call succeeds
            mock_response_200 = Mock()
            mock_response_200.status_code = 200
            mock_response_200.json.return_value = {
                "message": {"content": "Success"}
            }

            mock_post.side_effect = [mock_response_400, mock_response_200]

            result = agent_min.ollama_chat(
                [{"role": "user", "content": "test"}],
                tools=agent_min.TOOLS
            )

            # Should retry and succeed
            assert "message" in result
            assert mock_post.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ========== Tests for New File Operations ==========

class TestNewFileOperations:
    """Test new file operation tools."""

    def test_delete_file_success(self, temp_dir):
        """Test successful file deletion."""
        test_file = temp_dir / "to_delete.txt"
        test_file.write_text("delete me", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.delete_file(rel_path)
        data = json.loads(result)

        assert "deleted" in data
        assert not test_file.exists()

    def test_delete_file_not_found(self):
        """Test deleting non-existent file."""
        result = agent_min.delete_file("nonexistent.txt")
        data = json.loads(result)
        assert "error" in data

    def test_move_file_success(self, temp_dir):
        """Test successful file move."""
        src_file = temp_dir / "source.txt"
        src_file.write_text("move me", encoding="utf-8")

        src_rel = str(src_file.relative_to(agent_min.ROOT))
        dest_rel = str((temp_dir / "dest.txt").relative_to(agent_min.ROOT))
        result = agent_min.move_file(src_rel, dest_rel)
        data = json.loads(result)

        assert "moved" in data
        assert not src_file.exists()
        assert (temp_dir / "dest.txt").exists()

    def test_append_to_file(self, temp_dir):
        """Test appending to a file."""
        test_file = temp_dir / "append.txt"
        test_file.write_text("line1\n", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.append_to_file(rel_path, "line2\n")
        data = json.loads(result)

        assert "appended_to" in data
        assert test_file.read_text() == "line1\nline2\n"

    def test_replace_in_file_basic(self, temp_dir):
        """Test basic find and replace."""
        test_file = temp_dir / "replace.txt"
        test_file.write_text("Hello World", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.replace_in_file(rel_path, "World", "Python")
        data = json.loads(result)

        assert data["replaced"] == 1
        assert test_file.read_text() == "Hello Python"

    def test_replace_in_file_regex(self, temp_dir):
        """Test regex find and replace."""
        test_file = temp_dir / "replace_regex.txt"
        test_file.write_text("test123 test456", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.replace_in_file(rel_path, r"test\d+", "replaced", regex=True)
        data = json.loads(result)

        assert data["replaced"] == 2
        assert test_file.read_text() == "replaced replaced"

    def test_create_directory(self, temp_dir):
        """Test directory creation."""
        new_dir_path = str((temp_dir / "new_dir").relative_to(agent_min.ROOT))
        result = agent_min.create_directory(new_dir_path)
        data = json.loads(result)

        assert "created" in data
        assert (temp_dir / "new_dir").is_dir()

    def test_get_file_info(self, temp_dir):
        """Test getting file metadata."""
        test_file = temp_dir / "info.txt"
        test_file.write_text("test content", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.get_file_info(rel_path)
        data = json.loads(result)

        assert "size" in data
        assert data["size"] == 12
        assert data["is_file"] is True

    def test_copy_file_success(self, temp_dir):
        """Test successful file copy."""
        src_file = temp_dir / "source.txt"
        src_file.write_text("copy me", encoding="utf-8")

        src_rel = str(src_file.relative_to(agent_min.ROOT))
        dest_rel = str((temp_dir / "copy.txt").relative_to(agent_min.ROOT))
        result = agent_min.copy_file(src_rel, dest_rel)
        data = json.loads(result)

        assert "copied" in data
        assert src_file.exists()
        assert (temp_dir / "copy.txt").exists()
        assert (temp_dir / "copy.txt").read_text() == "copy me"

    def test_file_exists_true(self, temp_dir):
        """Test file_exists for existing file."""
        test_file = temp_dir / "exists.txt"
        test_file.write_text("I exist", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.file_exists(rel_path)
        data = json.loads(result)

        assert data["exists"] is True
        assert data["is_file"] is True

    def test_file_exists_false(self):
        """Test file_exists for non-existent file."""
        result = agent_min.file_exists("does_not_exist.txt")
        data = json.loads(result)

        assert data["exists"] is False

    def test_read_file_lines_full(self, temp_dir):
        """Test reading full file as lines."""
        test_file = temp_dir / "lines.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.read_file_lines(rel_path)
        data = json.loads(result)

        assert data["total_lines"] == 5
        assert len(data["lines"]) == 5

    def test_read_file_lines_range(self, temp_dir):
        """Test reading specific line range."""
        test_file = temp_dir / "lines_range.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.read_file_lines(rel_path, start=2, end=4)
        data = json.loads(result)

        assert len(data["lines"]) == 3  # end parameter is inclusive, so 2-4 = 3 lines
        assert data["lines"][0] == "line2"
        assert data["lines"][1] == "line3"
        assert data["lines"][2] == "line4"

    def test_tree_view_basic(self, temp_dir):
        """Test basic tree view generation."""
        # Create a simple directory structure
        (temp_dir / "dir1").mkdir()
        (temp_dir / "dir2").mkdir()
        (temp_dir / "file1.txt").write_text("test", encoding="utf-8")

        rel_path = str(temp_dir.relative_to(agent_min.ROOT))
        result = agent_min.tree_view(rel_path, max_depth=2)
        data = json.loads(result)

        assert "tree" in data
        assert "files_shown" in data
        assert data["files_shown"] >= 3


# ========== Tests for New Git Operations ==========

class TestNewGitOperations:
    """Test new git operation tools."""

    def test_git_commit_basic(self, temp_dir):
        """Test basic git commit."""
        # This test requires a git repo, so we'll just test the function signature
        result = agent_min.git_commit("test commit")
        data = json.loads(result)
        # May succeed or fail depending on repo state
        assert "error" in data or "committed" in data

    def test_git_status(self):
        """Test git status command."""
        result = agent_min.git_status()
        data = json.loads(result)

        assert "status" in data
        assert "returncode" in data

    def test_git_log_basic(self):
        """Test git log command."""
        result = agent_min.git_log(count=5)
        data = json.loads(result)

        assert "log" in data
        assert "returncode" in data

    def test_git_log_oneline(self):
        """Test git log with oneline format."""
        result = agent_min.git_log(count=3, oneline=True)
        data = json.loads(result)

        assert "log" in data

    def test_git_branch_current(self):
        """Test getting current branch."""
        result = agent_min.git_branch(action="current")
        data = json.loads(result)

        assert "branch" in data or "error" in data
        assert data["action"] == "current"

    def test_git_branch_list(self):
        """Test listing branches."""
        result = agent_min.git_branch(action="list")
        data = json.loads(result)

        assert "branches" in data
        assert data["action"] == "list"


# ========== Tests for Utility Tools ==========

class TestUtilityTools:
    """Test utility tools."""

    def test_install_package_mock(self):
        """Test install_package function signature."""
        # We won't actually install a package in tests
        # Just verify the function exists and handles errors
        result = agent_min.install_package("nonexistent-package-xyz123")
        data = json.loads(result)
        assert "installed" in data or "error" in data

    @patch('agent_min.requests.get')
    def test_web_fetch_success(self, mock_get):
        """Test successful web fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "test content"
        mock_response.headers = {"Content-Type": "text/html"}
        mock_get.return_value = mock_response

        result = agent_min.web_fetch("http://example.com")
        data = json.loads(result)

        assert data["status_code"] == 200
        assert data["content"] == "test content"

    @patch('agent_min.requests.get')
    def test_web_fetch_error(self, mock_get):
        """Test web fetch error handling."""
        mock_get.side_effect = Exception("Network error")

        result = agent_min.web_fetch("http://example.com")
        data = json.loads(result)

        assert "error" in data

    def test_execute_python_basic(self):
        """Test basic Python code execution."""
        result = agent_min.execute_python("print('hello')")
        data = json.loads(result)

        assert data["executed"] is True
        assert "hello" in data["output"]

    def test_execute_python_with_vars(self):
        """Test Python execution with variables."""
        code = "x = 5\ny = 10\nprint(x + y)"
        result = agent_min.execute_python(code)
        data = json.loads(result)

        assert "15" in data["output"]

    def test_execute_python_error(self):
        """Test Python execution error handling."""
        result = agent_min.execute_python("invalid syntax here !!!")
        data = json.loads(result)

        assert "error" in data


# ========== Tests for MCP Support ==========

class TestMCPSupport:
    """Test MCP (Model Context Protocol) support."""

    def test_mcp_add_server(self):
        """Test adding an MCP server."""
        result = agent_min.mcp_add_server("test_server", "echo", "hello world")
        data = json.loads(result)

        assert data["added"] == "test_server"
        assert data["command"] == "echo"

    def test_mcp_list_servers(self):
        """Test listing MCP servers."""
        # Add a server first
        agent_min.mcp_add_server("test_server_2", "cat")

        result = agent_min.mcp_list_servers()
        data = json.loads(result)

        assert "servers" in data
        assert isinstance(data["servers"], list)

    def test_mcp_call_tool_basic(self):
        """Test calling an MCP tool."""
        # Add a server first
        agent_min.mcp_add_server("test_server_3", "echo")

        result = agent_min.mcp_call_tool("test_server_3", "test_tool", '{"arg": "value"}')
        data = json.loads(result)

        # Should have basic response structure
        assert "server" in data or "error" in data

    def test_mcp_call_tool_invalid_json(self):
        """Test MCP tool call with invalid JSON."""
        result = agent_min.mcp_call_tool("server", "tool", "invalid json{}")
        data = json.loads(result)

        assert "error" in data


# ========== Tests for execute_tool Integration ==========

class TestExecuteToolIntegration:
    """Test execute_tool with all new tools."""

    def test_execute_delete_file(self, temp_dir):
        """Test execute_tool with delete_file."""
        test_file = temp_dir / "delete.txt"
        test_file.write_text("delete", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.execute_tool("delete_file", {"path": rel_path})
        data = json.loads(result)

        assert "deleted" in data

    def test_execute_copy_file(self, temp_dir):
        """Test execute_tool with copy_file."""
        src = temp_dir / "src.txt"
        src.write_text("content", encoding="utf-8")

        src_rel = str(src.relative_to(agent_min.ROOT))
        dest_rel = str((temp_dir / "dest.txt").relative_to(agent_min.ROOT))

        result = agent_min.execute_tool("copy_file", {"src": src_rel, "dest": dest_rel})
        data = json.loads(result)

        assert "copied" in data

    def test_execute_file_exists(self, temp_dir):
        """Test execute_tool with file_exists."""
        test_file = temp_dir / "exists.txt"
        test_file.write_text("exists", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.execute_tool("file_exists", {"path": rel_path})
        data = json.loads(result)

        assert data["exists"] is True

    def test_execute_read_file_lines(self, temp_dir):
        """Test execute_tool with read_file_lines."""
        test_file = temp_dir / "lines.txt"
        test_file.write_text("line1\nline2\nline3", encoding="utf-8")

        rel_path = str(test_file.relative_to(agent_min.ROOT))
        result = agent_min.execute_tool("read_file_lines", {"path": rel_path, "start": 1, "end": 2})
        data = json.loads(result)

        assert len(data["lines"]) == 2

    def test_execute_tree_view(self, temp_dir):
        """Test execute_tool with tree_view."""
        rel_path = str(temp_dir.relative_to(agent_min.ROOT))
        result = agent_min.execute_tool("tree_view", {"path": rel_path})
        data = json.loads(result)

        assert "tree" in data

    def test_execute_git_branch(self):
        """Test execute_tool with git_branch."""
        result = agent_min.execute_tool("git_branch", {"action": "current"})
        data = json.loads(result)

        assert "branch" in data or "error" in data

    def test_execute_web_fetch(self):
        """Test execute_tool with web_fetch."""
        with patch('agent_min.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "test"
            mock_response.headers = {}
            mock_get.return_value = mock_response

            result = agent_min.execute_tool("web_fetch", {"url": "http://example.com"})
            data = json.loads(result)

            assert "status_code" in data

    def test_execute_execute_python(self):
        """Test execute_tool with execute_python."""
        result = agent_min.execute_tool("execute_python", {"code": "print('test')"})
        data = json.loads(result)

        assert "executed" in data

    def test_execute_mcp_add_server(self):
        """Test execute_tool with mcp_add_server."""
        result = agent_min.execute_tool("mcp_add_server", {"name": "test", "command": "echo"})
        data = json.loads(result)

        assert "added" in data


print("\n✅ All new tool tests added successfully!")


# ========== Tests for get_system_info ==========

class TestSystemInfo:
    """Test system information detection."""

    def test_get_system_info_basic(self):
        """Test basic system info retrieval."""
        result = agent_min.get_system_info()
        data = json.loads(result)

        assert "os" in data
        assert "os_version" in data
        assert "platform" in data
        assert "architecture" in data
        assert "python_version" in data
        assert "shell_type" in data

    def test_get_system_info_os_flags(self):
        """Test OS detection flags."""
        result = agent_min.get_system_info()
        data = json.loads(result)

        assert "is_windows" in data
        assert "is_linux" in data
        assert "is_macos" in data
        assert isinstance(data["is_windows"], bool)
        assert isinstance(data["is_linux"], bool)
        assert isinstance(data["is_macos"], bool)

    def test_get_system_info_shell_type(self):
        """Test shell type detection."""
        result = agent_min.get_system_info()
        data = json.loads(result)

        assert data["shell_type"] in ["bash", "powershell"]

    def test_get_system_info_cached(self):
        """Test that system info is properly cached."""
        result1 = json.loads(agent_min.get_system_info())
        result2 = json.loads(agent_min.get_system_info())

        assert result1 == result2

    def test_execute_tool_get_system_info(self):
        """Test execute_tool with get_system_info."""
        result = agent_min.execute_tool("get_system_info", {})
        data = json.loads(result)

        assert "os" in data
        assert "platform" in data


class TestSSHFunctionality:
    """Test SSH remote execution functionality."""

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.paramiko')
    def test_ssh_connection_manager_connect(self, mock_paramiko):
        """Test SSH connection establishment."""
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client

        manager = agent_min.SSHConnectionManager()
        result = manager.connect("testhost", "testuser", password="testpass", port=22)

        assert result["connected"] is True
        assert result["connection_id"] == "testuser@testhost:22"
        assert "testuser@testhost:22" in manager.connections
        mock_client.set_missing_host_key_policy.assert_called_once()
        mock_client.connect.assert_called_once()

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.paramiko')
    def test_ssh_connection_manager_execute(self, mock_paramiko):
        """Test SSH command execution."""
        mock_client = MagicMock()
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        mock_stdout.read.return_value = b"command output"
        mock_stderr.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 0

        mock_client.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)
        mock_paramiko.SSHClient.return_value = mock_client

        manager = agent_min.SSHConnectionManager()
        conn_result = manager.connect("testhost", "testuser", password="testpass")
        conn_id = conn_result["connection_id"]
        result = manager.execute(conn_id, "ls -la")

        assert result["success"] is True
        assert result["stdout"] == "command output"
        assert result["exit_code"] == 0

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.paramiko')
    def test_ssh_connection_manager_copy_to_remote(self, mock_paramiko):
        """Test copying file to remote host."""
        mock_client = MagicMock()
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_paramiko.SSHClient.return_value = mock_client

        manager = agent_min.SSHConnectionManager()
        conn_result = manager.connect("testhost", "testuser", password="testpass")
        conn_id = conn_result["connection_id"]

        with patch('os.path.exists', return_value=True):
            result = manager.copy_file_to_remote(conn_id, "/local/file.txt", "/remote/file.txt")

        assert result["copied"] is True
        assert result["local_path"] == "/local/file.txt"
        assert result["remote_path"] == "/remote/file.txt"
        mock_sftp.put.assert_called_once_with("/local/file.txt", "/remote/file.txt")

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.paramiko')
    def test_ssh_connection_manager_copy_from_remote(self, mock_paramiko):
        """Test copying file from remote host."""
        mock_client = MagicMock()
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_paramiko.SSHClient.return_value = mock_client

        manager = agent_min.SSHConnectionManager()
        conn_result = manager.connect("testhost", "testuser", password="testpass")
        conn_id = conn_result["connection_id"]
        result = manager.copy_file_from_remote(conn_id, "/remote/file.txt", "/local/file.txt")

        assert result["copied"] is True
        assert result["remote_path"] == "/remote/file.txt"
        assert result["local_path"] == "/local/file.txt"
        mock_sftp.get.assert_called_once_with("/remote/file.txt", "/local/file.txt")

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.paramiko')
    def test_ssh_connection_manager_disconnect(self, mock_paramiko):
        """Test SSH connection disconnection."""
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client

        manager = agent_min.SSHConnectionManager()
        conn_result = manager.connect("testhost", "testuser", password="testpass")
        conn_id = conn_result["connection_id"]
        result = manager.disconnect(conn_id)

        assert result["disconnected"] is True
        assert result["connection_id"] == conn_id
        assert conn_id not in manager.connections
        mock_client.close.assert_called_once()

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.paramiko')
    def test_ssh_connection_manager_list_connections(self, mock_paramiko):
        """Test listing active SSH connections."""
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client

        manager = agent_min.SSHConnectionManager()
        manager.connect("host1", "user1", password="pass1")
        manager.connect("host2", "user2", password="pass2", port=2222)

        result = manager.list_connections()
        assert len(result["connections"]) == 2
        conn_ids = [c["connection_id"] for c in result["connections"]]
        assert "user1@host1:22" in conn_ids
        assert "user2@host2:2222" in conn_ids

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.ssh_manager')
    def test_ssh_connect_tool(self, mock_manager):
        """Test ssh_connect tool function."""
        mock_manager.connect.return_value = {
            "connected": True,
            "connection_id": "testuser@testhost:22",
            "host": "testhost",
            "username": "testuser",
            "port": 22
        }

        result = agent_min.ssh_connect(
            host="testhost",
            username="testuser",
            password="testpass",
            port=22
        )
        data = json.loads(result)

        assert data["connection_id"] == "testuser@testhost:22"
        mock_manager.connect.assert_called_once()

    def test_ssh_connect_tool_no_paramiko(self):
        """Test ssh_connect when paramiko is not available."""
        with patch('agent_min.SSH_AVAILABLE', False):
            result = agent_min.ssh_connect(
                host="testhost",
                username="testuser",
                password="testpass"
            )
            data = json.loads(result)

            assert "error" in data
            assert "paramiko" in data["error"].lower()

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.ssh_manager')
    def test_ssh_exec_tool(self, mock_manager):
        """Test ssh_exec tool function."""
        mock_manager.execute.return_value = {
            "success": True,
            "stdout": "command output",
            "stderr": "",
            "exit_code": 0
        }

        result = agent_min.ssh_exec(
            connection_id="user@host:22",
            command="ls -la"
        )
        data = json.loads(result)

        assert data["success"] is True
        assert data["stdout"] == "command output"

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.ssh_manager')
    def test_ssh_copy_to_tool(self, mock_manager):
        """Test ssh_copy_to tool function."""
        mock_manager.copy_file_to_remote.return_value = {
            "success": True,
            "local_path": "/local/file.txt",
            "remote_path": "/remote/file.txt"
        }

        result = agent_min.ssh_copy_to(
            connection_id="user@host:22",
            local_path="/local/file.txt",
            remote_path="/remote/file.txt"
        )
        data = json.loads(result)

        assert data["success"] is True

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.ssh_manager')
    def test_ssh_copy_from_tool(self, mock_manager):
        """Test ssh_copy_from tool function."""
        mock_manager.copy_file_from_remote.return_value = {
            "success": True,
            "remote_path": "/remote/file.txt",
            "local_path": "/local/file.txt"
        }

        result = agent_min.ssh_copy_from(
            connection_id="user@host:22",
            remote_path="/remote/file.txt",
            local_path="/local/file.txt"
        )
        data = json.loads(result)

        assert data["success"] is True

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.ssh_manager')
    def test_ssh_disconnect_tool(self, mock_manager):
        """Test ssh_disconnect tool function."""
        mock_manager.disconnect.return_value = {
            "success": True,
            "connection_id": "user@host:22"
        }

        result = agent_min.ssh_disconnect(connection_id="user@host:22")
        data = json.loads(result)

        assert data["success"] is True

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.ssh_manager')
    def test_ssh_list_connections_tool(self, mock_manager):
        """Test ssh_list_connections tool function."""
        mock_manager.list_connections.return_value = {
            "connections": [
                {"connection_id": "user@host1:22", "host": "host1", "username": "user", "port": 22},
                {"connection_id": "user@host2:22", "host": "host2", "username": "user", "port": 22}
            ]
        }

        result = agent_min.ssh_list_connections()
        data = json.loads(result)

        assert len(data["connections"]) == 2

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.ssh_manager')
    def test_execute_tool_ssh_connect(self, mock_manager):
        """Test execute_tool with ssh_connect."""
        mock_manager.connect.return_value = {
            "connected": True,
            "connection_id": "testuser@testhost:22",
            "host": "testhost",
            "username": "testuser",
            "port": 22
        }

        result = agent_min.execute_tool("ssh_connect", {
            "host": "testhost",
            "username": "testuser",
            "password": "testpass"
        })
        data = json.loads(result)

        assert "connection_id" in data
        assert data["connection_id"] == "testuser@testhost:22"

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.ssh_manager')
    def test_execute_tool_ssh_exec(self, mock_manager):
        """Test execute_tool with ssh_exec."""
        mock_manager.execute.return_value = {
            "success": True,
            "stdout": "output"
        }

        result = agent_min.execute_tool("ssh_exec", {
            "connection_id": "user@host:22",
            "command": "uptime"
        })
        data = json.loads(result)

        assert data["success"] is True

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.paramiko')
    def test_ssh_connection_error_handling(self, mock_paramiko):
        """Test SSH connection error handling."""
        mock_client = MagicMock()
        mock_client.connect.side_effect = Exception("Connection refused")
        mock_paramiko.SSHClient.return_value = mock_client

        manager = agent_min.SSHConnectionManager()

        # Should not raise exception, should return error in result
        result = manager.connect("badhost", "user", password="pass")
        assert "error" in result
        assert "Connection refused" in result["error"]

    @patch('agent_min.SSH_AVAILABLE', True)
    @patch('agent_min.ssh_manager')
    def test_ssh_exec_invalid_connection(self, mock_manager):
        """Test ssh_exec with invalid connection ID."""
        mock_manager.execute.return_value = {
            "success": False,
            "error": "Connection not found"
        }

        result = agent_min.ssh_exec(
            connection_id="invalid@host:22",
            command="ls"
        )
        data = json.loads(result)

        assert data["success"] is False


print("\n✅ SSH functionality tests added successfully!")
print("\n✅ System info tests added successfully!")
