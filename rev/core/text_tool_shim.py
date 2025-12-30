"""Execute tool calls embedded in plain-text model output.

Some models will emit a JSON tool-call payload in `message.content` instead of
populating structured tool call fields. Agents already try to recover these at
the point of generation, but this shim provides a *second line of defense* at
the orchestrator boundary: if an agent returns a text tool-call payload, we can
recover and execute it without re-planning.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Optional

import json

from rev.core.tool_call_recovery import recover_tool_call_from_text
from rev.tools.registry import execute_tool


@dataclass(frozen=True)
class ExecutedTextToolCall:
    tool_name: str
    tool_args: Dict[str, Any]
    tool_output: Any
    recovered: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def maybe_execute_tool_call_from_text(
    content: str,
    *,
    allowed_tools: Optional[Iterable[str]] = None,
) -> Optional[ExecutedTextToolCall]:
    """Recover and execute a single tool call from text content."""

    recovered = recover_tool_call_from_text(content or "", allowed_tools=allowed_tools)
    if not recovered:
        return None

    # Special-case: allow "read_file" requests that provide multiple paths.
    if recovered.name == "read_file" and isinstance(recovered.arguments, dict) and isinstance(recovered.arguments.get("paths"), list):
        outputs = {}
        for path in recovered.arguments.get("paths", []):
            if not isinstance(path, str):
                continue
            outputs[path] = execute_tool("read_file", {"path": path}, agent_name="text_tool_shim")
        return ExecutedTextToolCall(
            tool_name="read_file",
            tool_args={"paths": recovered.arguments.get("paths", [])},
            tool_output=json.dumps(outputs),
            recovered=True,
        )

    tool_output = execute_tool(recovered.name, recovered.arguments, agent_name="text_tool_shim")
    return ExecutedTextToolCall(
        tool_name=recovered.name,
        tool_args=recovered.arguments,
        tool_output=tool_output,
        recovered=True,
    )
