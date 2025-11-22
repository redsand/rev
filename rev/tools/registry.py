#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tool registry and execution for rev."""

import json
from typing import Dict, Any

# Import tool functions from their respective modules
from rev.tools.file_ops import (
    read_file, write_file, list_dir, delete_file, move_file,
    append_to_file, replace_in_file, create_directory, get_file_info,
    copy_file, file_exists, read_file_lines, tree_view, search_code
)
from rev.tools.git_ops import (
    git_diff, apply_patch, git_commit, git_status, git_log, git_branch,
    run_cmd, run_tests, get_repo_context
)
from rev.tools.ssh_ops import (
    ssh_connect, ssh_exec, ssh_copy_to, ssh_copy_from, ssh_disconnect, ssh_list_connections
)
from rev.tools.utils import (
    install_package, web_fetch, execute_python, get_system_info
)


def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """Execute a tool and return result."""
    print(f"  → Executing: {name}({', '.join(f'{k}={v!r}' for k, v in args.items())})")

    try:
        # Original tools
        if name == "read_file":
            return read_file(args["path"])
        elif name == "write_file":
            return write_file(args["path"], args["content"])
        elif name == "list_dir":
            return list_dir(args.get("pattern", "**/*"))
        elif name == "search_code":
            return search_code(args["pattern"], args.get("include", "**/*"))
        elif name == "git_diff":
            return git_diff(args.get("pathspec", "."))
        elif name == "apply_patch":
            return apply_patch(args["patch"], args.get("dry_run", False))
        elif name == "run_cmd":
            return run_cmd(args["cmd"], args.get("timeout", 300))
        elif name == "run_tests":
            return run_tests(args.get("cmd", "pytest -q"), args.get("timeout", 600))
        elif name == "get_repo_context":
            return get_repo_context(args.get("commits", 6))

        # File operations
        elif name == "delete_file":
            return delete_file(args["path"])
        elif name == "move_file":
            return move_file(args["src"], args["dest"])
        elif name == "append_to_file":
            return append_to_file(args["path"], args["content"])
        elif name == "replace_in_file":
            return replace_in_file(args["path"], args["find"], args["replace"], args.get("regex", False))
        elif name == "create_directory":
            return create_directory(args["path"])
        elif name == "get_file_info":
            return get_file_info(args["path"])
        elif name == "copy_file":
            return copy_file(args["src"], args["dest"])
        elif name == "file_exists":
            return file_exists(args["path"])
        elif name == "read_file_lines":
            return read_file_lines(args["path"], args.get("start", 1), args.get("end"))
        elif name == "tree_view":
            return tree_view(args.get("path", "."), args.get("max_depth", 3), args.get("max_files", 100))

        # Git operations
        elif name == "git_commit":
            return git_commit(args["message"], args.get("files", "."))
        elif name == "git_status":
            return git_status()
        elif name == "git_log":
            return git_log(args.get("count", 10), args.get("oneline", False))
        elif name == "git_branch":
            return git_branch(args.get("action", "list"), args.get("branch_name"))

        # Utility tools
        elif name == "install_package":
            return install_package(args["package"])
        elif name == "web_fetch":
            return web_fetch(args["url"])
        elif name == "execute_python":
            return execute_python(args["code"])
        elif name == "get_system_info":
            return get_system_info()

        # SSH remote execution tools
        elif name == "ssh_connect":
            return ssh_connect(args["host"], args["username"], args.get("password"),
                             args.get("key_file"), args.get("port", 22))
        elif name == "ssh_exec":
            return ssh_exec(args["connection_id"], args["command"], args.get("timeout", 30))
        elif name == "ssh_copy_to":
            return ssh_copy_to(args["connection_id"], args["local_path"], args["remote_path"])
        elif name == "ssh_copy_from":
            return ssh_copy_from(args["connection_id"], args["remote_path"], args["local_path"])
        elif name == "ssh_disconnect":
            return ssh_disconnect(args["connection_id"])
        elif name == "ssh_list_connections":
            return ssh_list_connections()

        # MCP tools - import from main rev module if available
        elif name == "mcp_add_server":
            try:
                from rev import mcp_add_server as mcp_add_server_impl
                return mcp_add_server_impl(args["name"], args["command"], args.get("args", ""))
            except ImportError:
                return json.dumps({"error": "MCP tools not available"})
        elif name == "mcp_list_servers":
            try:
                from rev import mcp_list_servers as mcp_list_servers_impl
                return mcp_list_servers_impl()
            except ImportError:
                return json.dumps({"error": "MCP tools not available"})
        elif name == "mcp_call_tool":
            try:
                from rev import mcp_call_tool as mcp_call_tool_impl
                return mcp_call_tool_impl(args["server"], args["tool"], args.get("arguments", "{}"))
            except ImportError:
                return json.dumps({"error": "MCP tools not available"})

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def get_available_tools() -> list:
    """Get the list of available tools for LLM function calling.

    Returns a list of tool definitions in OpenAI format that can be passed
    to language models that support function calling.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read contents of a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file (creates or overwrites)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file"},
                        "content": {"type": "string", "description": "File content"}
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "List files matching a pattern (glob syntax)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern (e.g., **/*.py)", "default": "**/*"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_code",
                "description": "Search code using regex pattern",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regex pattern to search"},
                        "include": {"type": "string", "description": "Glob pattern for files to search", "default": "**/*"}
                    },
                    "required": ["pattern"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "git_diff",
                "description": "Show git diff for current changes",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pathspec": {"type": "string", "description": "Path or pattern to diff", "default": "."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "apply_patch",
                "description": "Apply a unified diff patch to files",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patch": {"type": "string", "description": "Unified diff patch content"},
                        "dry_run": {"type": "boolean", "description": "Test patch without applying", "default": False}
                    },
                    "required": ["patch"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_cmd",
                "description": "Execute a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {"type": "string", "description": "Command to execute"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 300}
                    },
                    "required": ["cmd"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_tests",
                "description": "Run test suite",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {"type": "string", "description": "Test command", "default": "pytest -q"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 600}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_repo_context",
                "description": "Get repository status and recent commits",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "commits": {"type": "integer", "description": "Number of recent commits", "default": 6}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_system_info",
                "description": "Get system information (OS, platform, architecture)",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }
    ]
