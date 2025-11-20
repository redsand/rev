#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSH operations tools for rev."""

import json
from typing import Dict, Any

from rev.config import SSH_AVAILABLE, paramiko


class SSHConnectionManager:
    """Manage SSH connections to remote hosts."""

    def __init__(self):
        self.connections = {}  # {connection_id: {"client": SSHClient, "host": str, "user": str}}

    def connect(self, host: str, username: str, password: str = None, key_file: str = None,
                port: int = 22) -> Dict[str, Any]:
        """Connect to a remote host via SSH."""
        if not SSH_AVAILABLE:
            return {"error": "SSH not available. Install with: pip install paramiko"}

        connection_id = f"{username}@{host}:{port}"

        try:
            # Close existing connection if any
            if connection_id in self.connections:
                self.disconnect(connection_id)

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Connect with password or key
            if key_file:
                client.connect(host, port=port, username=username, key_filename=key_file, timeout=10)
            elif password:
                client.connect(host, port=port, username=username, password=password, timeout=10)
            else:
                # Try default SSH keys
                client.connect(host, port=port, username=username, timeout=10)

            self.connections[connection_id] = {
                "client": client,
                "host": host,
                "username": username,
                "port": port,
                "connected_at": json.dumps({"timestamp": "now"})  # Placeholder
            }

            return {
                "connected": True,
                "connection_id": connection_id,
                "host": host,
                "username": username,
                "port": port
            }

        except Exception as e:
            return {"error": f"SSH connection failed: {type(e).__name__}: {e}"}

    def execute(self, connection_id: str, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute a command on a remote host."""
        if connection_id not in self.connections:
            return {"error": f"Connection not found: {connection_id}"}

        try:
            client = self.connections[connection_id]["client"]
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)

            exit_status = stdout.channel.recv_exit_status()
            stdout_text = stdout.read().decode('utf-8', errors='ignore')
            stderr_text = stderr.read().decode('utf-8', errors='ignore')

            return {
                "connection_id": connection_id,
                "command": command,
                "exit_code": exit_status,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "success": exit_status == 0
            }

        except Exception as e:
            return {"error": f"Command execution failed: {type(e).__name__}: {e}"}

    def copy_file_to_remote(self, connection_id: str, local_path: str, remote_path: str) -> Dict[str, Any]:
        """Copy a file to the remote host."""
        if connection_id not in self.connections:
            return {"error": f"Connection not found: {connection_id}"}

        try:
            client = self.connections[connection_id]["client"]
            sftp = client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()

            return {
                "copied": True,
                "local_path": local_path,
                "remote_path": remote_path,
                "connection_id": connection_id
            }

        except Exception as e:
            return {"error": f"File copy failed: {type(e).__name__}: {e}"}

    def copy_file_from_remote(self, connection_id: str, remote_path: str, local_path: str) -> Dict[str, Any]:
        """Copy a file from the remote host."""
        if connection_id not in self.connections:
            return {"error": f"Connection not found: {connection_id}"}

        try:
            client = self.connections[connection_id]["client"]
            sftp = client.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()

            return {
                "copied": True,
                "remote_path": remote_path,
                "local_path": local_path,
                "connection_id": connection_id
            }

        except Exception as e:
            return {"error": f"File copy failed: {type(e).__name__}: {e}"}

    def disconnect(self, connection_id: str) -> Dict[str, Any]:
        """Disconnect from a remote host."""
        if connection_id not in self.connections:
            return {"error": f"Connection not found: {connection_id}"}

        try:
            client = self.connections[connection_id]["client"]
            client.close()
            del self.connections[connection_id]

            return {
                "disconnected": True,
                "connection_id": connection_id
            }

        except Exception as e:
            return {"error": f"Disconnect failed: {type(e).__name__}: {e}"}

    def list_connections(self) -> Dict[str, Any]:
        """List all active SSH connections."""
        return {
            "connections": [
                {
                    "connection_id": conn_id,
                    "host": info["host"],
                    "username": info["username"],
                    "port": info["port"]
                }
                for conn_id, info in self.connections.items()
            ]
        }


# Global SSH connection manager
ssh_manager = SSHConnectionManager()


def ssh_connect(host: str, username: str, password: str = None, key_file: str = None, port: int = 22) -> str:
    """Connect to a remote host via SSH."""
    result = ssh_manager.connect(host, username, password, key_file, port)
    return json.dumps(result)


def ssh_exec(connection_id: str, command: str, timeout: int = 30) -> str:
    """Execute a command on a remote host."""
    result = ssh_manager.execute(connection_id, command, timeout)
    return json.dumps(result)


def ssh_copy_to(connection_id: str, local_path: str, remote_path: str) -> str:
    """Copy a file to the remote host."""
    result = ssh_manager.copy_file_to_remote(connection_id, local_path, remote_path)
    return json.dumps(result)


def ssh_copy_from(connection_id: str, remote_path: str, local_path: str) -> str:
    """Copy a file from the remote host."""
    result = ssh_manager.copy_file_from_remote(connection_id, remote_path, local_path)
    return json.dumps(result)


def ssh_disconnect(connection_id: str) -> str:
    """Disconnect from a remote host."""
    result = ssh_manager.disconnect(connection_id)
    return json.dumps(result)


def ssh_list_connections() -> str:
    """List all active SSH connections."""
    result = ssh_manager.list_connections()
    return json.dumps(result)
