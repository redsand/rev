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
from rev.tools.analysis import (
    analyze_ast_patterns, run_pylint, run_mypy, run_radon_complexity,
    find_dead_code, run_all_analysis
)


def _get_friendly_description(name: str, args: Dict[str, Any]) -> str:
    """Generate a user-friendly description for tool execution."""
    # Map tool names to friendly action descriptions with key arguments
    descriptions = {
        # File operations
        "read_file": f"Reading file: {args.get('path', '')}",
        "write_file": f"Writing file: {args.get('path', '')}",
        "list_dir": f"Listing directory: {args.get('pattern', '**/*')}",
        "search_code": f"Searching code: {args.get('pattern', '')} in {args.get('include', '**/*')}",
        "delete_file": f"Deleting file: {args.get('path', '')}",
        "move_file": f"Moving file: {args.get('src', '')} → {args.get('dest', '')}",
        "append_to_file": f"Appending to file: {args.get('path', '')}",
        "replace_in_file": f"Replacing in file: {args.get('path', '')}",
        "create_directory": f"Creating directory: {args.get('path', '')}",
        "get_file_info": f"Getting file info: {args.get('path', '')}",
        "copy_file": f"Copying file: {args.get('src', '')} → {args.get('dest', '')}",
        "file_exists": f"Checking file exists: {args.get('path', '')}",
        "read_file_lines": f"Reading lines from file: {args.get('path', '')}",
        "tree_view": f"Displaying tree view: {args.get('path', '.')}",

        # Git operations
        "git_diff": f"Showing git diff: {args.get('pathspec', '.')}",
        "apply_patch": f"Applying patch{' (dry run)' if args.get('dry_run') else ''}",
        "git_commit": f"Creating git commit: {args.get('message', '')[:50]}{'...' if len(args.get('message', '')) > 50 else ''}",
        "git_status": "Getting git status",
        "git_log": f"Viewing git log ({args.get('count', 10)} commits)",
        "git_branch": f"Git branch: {args.get('action', 'list')}" + (f" {args.get('branch_name', '')}" if args.get('branch_name') else ""),
        "run_cmd": f"Running command: {args.get('cmd', '')}",
        "run_tests": f"Running tests: {args.get('cmd', 'pytest -q')}",
        "get_repo_context": f"Getting repository context ({args.get('commits', 6)} commits)",

        # Utility tools
        "install_package": f"Installing package: {args.get('package', '')}",
        "web_fetch": f"Fetching URL: {args.get('url', '')}",
        "execute_python": "Executing Python code",
        "get_system_info": "Getting system information",

        # SSH operations
        "ssh_connect": f"Connecting via SSH: {args.get('username', '')}@{args.get('host', '')}",
        "ssh_exec": f"Executing SSH command on {args.get('connection_id', '')}: {args.get('command', '')}",
        "ssh_copy_to": f"Copying to SSH server: {args.get('local_path', '')} → {args.get('remote_path', '')}",
        "ssh_copy_from": f"Copying from SSH server: {args.get('remote_path', '')} → {args.get('local_path', '')}",
        "ssh_disconnect": f"Disconnecting SSH: {args.get('connection_id', '')}",
        "ssh_list_connections": "Listing SSH connections",

        # MCP tools
        "mcp_add_server": f"Adding MCP server: {args.get('name', '')}",
        "mcp_list_servers": "Listing MCP servers",
        "mcp_call_tool": f"Calling MCP tool: {args.get('server', '')}.{args.get('tool', '')}",

        # Static analysis tools
        "analyze_ast_patterns": f"Analyzing AST patterns: {args.get('path', '.')}",
        "run_pylint": f"Running pylint on: {args.get('path', '.')}",
        "run_mypy": f"Running mypy type check on: {args.get('path', '.')}",
        "run_radon_complexity": f"Analyzing code complexity: {args.get('path', '.')}",
        "find_dead_code": f"Finding dead code in: {args.get('path', '.')}",
        "run_all_analysis": f"Running full analysis suite on: {args.get('path', '.')}",
    }

    # Return the friendly description or fall back to technical format
    return descriptions.get(name, f"{name}({', '.join(f'{k}={v!r}' for k, v in args.items())})")


def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """Execute a tool and return result."""
    friendly_desc = _get_friendly_description(name, args)
    print(f"  → {friendly_desc}")

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

        # Static analysis tools
        elif name == "analyze_ast_patterns":
            return analyze_ast_patterns(args.get("path", "."), args.get("patterns"))
        elif name == "run_pylint":
            return run_pylint(args.get("path", "."), args.get("config"))
        elif name == "run_mypy":
            return run_mypy(args.get("path", "."), args.get("config"))
        elif name == "run_radon_complexity":
            return run_radon_complexity(args.get("path", "."), args.get("min_rank", "C"))
        elif name == "find_dead_code":
            return find_dead_code(args.get("path", "."))
        elif name == "run_all_analysis":
            return run_all_analysis(args.get("path", "."))

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
        # File operations
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
                "name": "delete_file",
                "description": "Delete a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file to delete"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "move_file",
                "description": "Move or rename a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string", "description": "Source file path"},
                        "dest": {"type": "string", "description": "Destination file path"}
                    },
                    "required": ["src", "dest"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "append_to_file",
                "description": "Append content to end of file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file"},
                        "content": {"type": "string", "description": "Content to append"}
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "replace_in_file",
                "description": "Find and replace text in a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file"},
                        "find": {"type": "string", "description": "Text to find"},
                        "replace": {"type": "string", "description": "Replacement text"},
                        "regex": {"type": "boolean", "description": "Use regex pattern", "default": False}
                    },
                    "required": ["path", "find", "replace"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_directory",
                "description": "Create a directory (including parent directories)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path to create"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_file_info",
                "description": "Get file metadata (size, modified time, etc)",
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
                "name": "copy_file",
                "description": "Copy a file to a new location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string", "description": "Source file path"},
                        "dest": {"type": "string", "description": "Destination file path"}
                    },
                    "required": ["src", "dest"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "file_exists",
                "description": "Check if a file exists",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to check"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file_lines",
                "description": "Read specific lines from a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file"},
                        "start": {"type": "integer", "description": "Starting line number", "default": 1},
                        "end": {"type": "integer", "description": "Ending line number (optional)"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "tree_view",
                "description": "Display directory tree structure",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path", "default": "."},
                        "max_depth": {"type": "integer", "description": "Maximum depth to traverse", "default": 3},
                        "max_files": {"type": "integer", "description": "Maximum files to show", "default": 100}
                    }
                }
            }
        },

        # Git operations
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
                "name": "git_commit",
                "description": "Create a git commit",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Commit message"},
                        "files": {"type": "string", "description": "Files to commit", "default": "."}
                    },
                    "required": ["message"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "git_status",
                "description": "Get git status",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "git_log",
                "description": "View git commit history",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "description": "Number of commits to show", "default": 10},
                        "oneline": {"type": "boolean", "description": "Show one line per commit", "default": False}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "git_branch",
                "description": "Git branch operations (list, create, delete)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Action: list, create, delete", "default": "list"},
                        "branch_name": {"type": "string", "description": "Branch name for create/delete"}
                    }
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

        # Utility tools
        {
            "type": "function",
            "function": {
                "name": "install_package",
                "description": "Install a Python package via pip",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "package": {"type": "string", "description": "Package name to install"}
                    },
                    "required": ["package"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "web_fetch",
                "description": "Fetch content from a URL",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch"}
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "execute_python",
                "description": "Execute Python code in a subprocess",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code to execute"}
                    },
                    "required": ["code"]
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
        },

        # SSH operations
        {
            "type": "function",
            "function": {
                "name": "ssh_connect",
                "description": "Connect to a remote server via SSH",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "host": {"type": "string", "description": "Hostname or IP"},
                        "username": {"type": "string", "description": "SSH username"},
                        "password": {"type": "string", "description": "SSH password (optional)"},
                        "key_file": {"type": "string", "description": "Path to private key file (optional)"},
                        "port": {"type": "integer", "description": "SSH port", "default": 22}
                    },
                    "required": ["host", "username"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ssh_exec",
                "description": "Execute command on remote SSH server",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "connection_id": {"type": "string", "description": "SSH connection ID"},
                        "command": {"type": "string", "description": "Command to execute"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30}
                    },
                    "required": ["connection_id", "command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ssh_copy_to",
                "description": "Copy local file to remote SSH server",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "connection_id": {"type": "string", "description": "SSH connection ID"},
                        "local_path": {"type": "string", "description": "Local file path"},
                        "remote_path": {"type": "string", "description": "Remote file path"}
                    },
                    "required": ["connection_id", "local_path", "remote_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ssh_copy_from",
                "description": "Copy file from remote SSH server to local",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "connection_id": {"type": "string", "description": "SSH connection ID"},
                        "remote_path": {"type": "string", "description": "Remote file path"},
                        "local_path": {"type": "string", "description": "Local file path"}
                    },
                    "required": ["connection_id", "remote_path", "local_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ssh_disconnect",
                "description": "Disconnect from SSH server",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "connection_id": {"type": "string", "description": "SSH connection ID"}
                    },
                    "required": ["connection_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ssh_list_connections",
                "description": "List active SSH connections",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },

        # MCP tools
        {
            "type": "function",
            "function": {
                "name": "mcp_add_server",
                "description": "Add a new MCP server configuration",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Server name"},
                        "command": {"type": "string", "description": "Server command to execute"},
                        "args": {"type": "string", "description": "Server arguments (optional)", "default": ""}
                    },
                    "required": ["name", "command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_list_servers",
                "description": "List configured MCP servers",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_call_tool",
                "description": "Call a tool from an MCP server",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server": {"type": "string", "description": "MCP server name"},
                        "tool": {"type": "string", "description": "Tool name"},
                        "arguments": {"type": "string", "description": "Tool arguments as JSON", "default": "{}"}
                    },
                    "required": ["server", "tool"]
                }
            }
        },

        # Static analysis tools
        {
            "type": "function",
            "function": {
                "name": "analyze_ast_patterns",
                "description": "Analyze Python code using AST for pattern matching (cross-platform). Detects TODOs, print statements, dangerous functions, missing type hints, complex functions, global variables. More accurate than regex.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to Python file or directory", "default": "."},
                        "patterns": {"type": "array", "items": {"type": "string"}, "description": "Patterns to check: todos, prints, dangerous, type_hints, complex_functions, globals"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_pylint",
                "description": "Run pylint static code analysis (cross-platform). Checks code errors, style violations, code smells, unused imports, naming conventions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to analyze", "default": "."},
                        "config": {"type": "string", "description": "Path to pylintrc config file (optional)"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_mypy",
                "description": "Run mypy static type checking (cross-platform). Verifies type hints and catches type-related bugs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to analyze", "default": "."},
                        "config": {"type": "string", "description": "Path to mypy.ini config file (optional)"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_radon_complexity",
                "description": "Analyze code complexity using radon (cross-platform). Measures cyclomatic complexity, maintainability index, and code metrics.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to analyze", "default": "."},
                        "min_rank": {"type": "string", "description": "Minimum complexity rank to report (A-F)", "default": "C"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "find_dead_code",
                "description": "Find dead/unused code using vulture (cross-platform). Detects unused functions, classes, variables, imports, and unreachable code.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to analyze", "default": "."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_all_analysis",
                "description": "Run all available static analysis tools and combine results (cross-platform). Includes AST analysis, pylint, mypy, radon, and vulture.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to analyze", "default": "."}
                    }
                }
            }
        }
    ]
