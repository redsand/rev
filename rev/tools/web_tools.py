"""Web-related helper tools.

These provide lightweight, sandbox-safe functionality. Network access may be
restricted in some environments; callers should inspect the returned payload
for an 'error' key.
"""

import json
import urllib.request
import urllib.error
from typing import Optional

from rev.tools import file_ops


def web_search(query: str, limit: int = 5) -> str:
    """Placeholder web search tool.

    Network access is commonly disabled in the execution environment. Rather
    than attempting a real search and failing noisily, return a structured
    error explaining the limitation so upstream logic can fall back to MCP or
    other search providers.
    """
    return json.dumps({
        "error": "web_search unavailable: network access is disabled. "
                 "Use an MCP search tool or provide cached context instead.",
        "query": query,
        "limit": limit,
    })


def fetch_url(url: str, timeout: int = 10, max_bytes: int = 200000) -> str:
    """Fetch the contents of a URL (best-effort).

    If network access is blocked, returns an error payload instead of raising.
    Content is truncated to max_bytes to avoid flooding the caller.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read(max_bytes + 1)
            truncated = len(data) > max_bytes
            if truncated:
                data = data[:max_bytes]
            try:
                text = data.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
            except Exception:
                text = data.decode("utf-8", errors="replace")
            return json.dumps({
                "url": url,
                "status": resp.status,
                "headers": dict(resp.headers),
                "content": text,
                "truncated": truncated,
            })
    except urllib.error.URLError as e:
        return json.dumps({"error": f"Network error fetching URL: {e}", "url": url})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}", "url": url})


def find_files(pattern: str = "**/*", include_dirs: bool = False, max_results: int = 200) -> str:
    """Find files matching a glob pattern within allowed roots.

    Args:
        pattern: Glob pattern (relative to workspace root).
        include_dirs: If True, include directories in results.
        max_results: Cap the number of returned entries.
    """
    try:
        # Reuse file_ops helper to honor allowed roots/excludes.
        matches = file_ops._iter_files(pattern, include_dirs=include_dirs)  # type: ignore[attr-defined]
        rels = []
        for p in matches:
            rel = file_ops._rel_to_root(p).replace("\\", "/")
            rels.append({"path": rel, "is_dir": p.is_dir(), "size": p.stat().st_size if p.exists() else None})
            if len(rels) >= max_results:
                break
        return json.dumps({"count": len(rels), "results": rels, "truncated": len(matches) > max_results})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
