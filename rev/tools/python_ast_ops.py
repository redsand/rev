#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Python AST-aware edit tools.

These tools exist to avoid brittle string replacements for common refactors,
especially import rewrites after moving/splitting modules.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rev.cache import get_file_cache
from rev.tools.file_ops import _safe_path, _rel_to_root, _rel_to_root_posix  # type: ignore


@dataclass(frozen=True)
class _Rule:
    from_module: str
    to_module: str
    match: str  # "exact" | "prefix"


def _parse_rules(rules: Any) -> Tuple[Optional[List[_Rule]], Optional[str]]:
    if not isinstance(rules, list) or not rules:
        return None, "rules must be a non-empty list"
    parsed: List[_Rule] = []
    for idx, raw in enumerate(rules):
        if not isinstance(raw, dict):
            return None, f"rules[{idx}] must be an object"
        fm = raw.get("from_module")
        tm = raw.get("to_module")
        match = (raw.get("match") or "exact").strip().lower()
        if not isinstance(fm, str) or not fm.strip():
            return None, f"rules[{idx}].from_module must be a non-empty string"
        if not isinstance(tm, str) or not tm.strip():
            return None, f"rules[{idx}].to_module must be a non-empty string"
        if match not in {"exact", "prefix"}:
            return None, f"rules[{idx}].match must be 'exact' or 'prefix'"
        parsed.append(_Rule(from_module=fm.strip(), to_module=tm.strip(), match=match))
    return parsed, None


def _apply_module_rule(module: str, rule: _Rule) -> Optional[str]:
    if rule.match == "exact":
        if module == rule.from_module:
            return rule.to_module
        return None
    # prefix
    if module == rule.from_module:
        return rule.to_module
    if module.startswith(rule.from_module + "."):
        return rule.to_module + module[len(rule.from_module) :]
    return None


def _rewrite_module_name(module: str, rules: List[_Rule]) -> Optional[str]:
    for rule in rules:
        rewritten = _apply_module_rule(module, rule)
        if rewritten and rewritten != module:
            return rewritten
    return None


def _line_offsets(text: str) -> List[int]:
    offsets = [0]
    for m in re.finditer(r"\n", text):
        offsets.append(m.end())
    return offsets


def _slice_for_node(text: str, offsets: List[int], node: ast.AST) -> Tuple[int, int]:
    lineno = getattr(node, "lineno", None)
    end_lineno = getattr(node, "end_lineno", None)
    if not isinstance(lineno, int) or not isinstance(end_lineno, int):
        raise ValueError("AST node is missing location info")
    start = offsets[lineno - 1]
    end = offsets[end_lineno] if end_lineno < len(offsets) else len(text)
    return start, end


def _indent_of_line(line: str) -> str:
    m = re.match(r"[ \t]*", line)
    return m.group(0) if m else ""


def _libcst_available() -> bool:
    try:
        import libcst  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def _require_libcst_or_error() -> Optional[str]:
    if _libcst_available():
        return None
    return "libcst is not available; install libcst to use this tool"


def _unified_diff_text(path: Path, original: str, new_text: str) -> str:
    return "".join(
        unified_diff(
            original.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{_rel_to_root_posix(path)}",
            tofile=f"b/{_rel_to_root_posix(path)}",
        )
    )


def _write_rewrite_result(
    *,
    path: Path,
    original: str,
    new_text: str,
    dry_run: bool,
    payload: Dict[str, Any],
) -> str:
    diff = _unified_diff_text(path, original, new_text)
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
        file_cache = get_file_cache()
        if file_cache is not None:
            file_cache.invalidate_file(path)
    out = dict(payload)
    out["path_abs"] = str(path)
    out["path_rel"] = _rel_to_root_posix(path)
    out["file"] = _rel_to_root(path)
    out["dry_run"] = bool(dry_run)
    out["diff"] = diff[-120000:]
    return json.dumps(out)


def _try_rewrite_imports_with_libcst(
    original: str, rules: List[_Rule]
) -> Tuple[Optional[str], Optional[List[Dict[str, Any]]], Optional[str]]:
    """Attempt import rewriting with libcst (format-preserving).

    Returns:
        (new_text, changes, error)
        - If libcst isn't available: (None, None, None)
        - If libcst runs: (new_text, changes, None)
        - If libcst fails: (None, None, "<error>")
    """
    try:
        import libcst as cst  # type: ignore
    except Exception:
        return None, None, None

    def _expr_to_dotted(expr: cst.BaseExpression) -> Optional[str]:
        if isinstance(expr, cst.Name):
            return expr.value
        if isinstance(expr, cst.Attribute):
            left = _expr_to_dotted(expr.value)
            if not left:
                return None
            if not isinstance(expr.attr, cst.Name):
                return None
            return f"{left}.{expr.attr.value}"
        return None

    def _dotted_to_expr(dotted: str) -> cst.BaseExpression:
        parts = [p for p in dotted.split(".") if p]
        if not parts:
            return cst.Name("invalid")
        node: cst.BaseExpression = cst.Name(parts[0])
        for part in parts[1:]:
            node = cst.Attribute(value=node, attr=cst.Name(part))
        return node

    class _Transformer(cst.CSTTransformer):
        def __init__(self) -> None:
            self.changes: List[Dict[str, Any]] = []

        def leave_Import(self, original_node: cst.Import, updated_node: cst.Import) -> cst.Import:
            new_names = []
            changed_any = False

            for alias in updated_node.names:
                name_expr = getattr(alias, "name", None)
                if not isinstance(name_expr, cst.BaseExpression):
                    new_names.append(alias)
                    continue

                dotted = _expr_to_dotted(name_expr)
                if not dotted:
                    new_names.append(alias)
                    continue

                rewritten = _rewrite_module_name(dotted, rules)
                if not rewritten:
                    new_names.append(alias)
                    continue

                new_names.append(alias.with_changes(name=_dotted_to_expr(rewritten)))
                changed_any = True

            if not changed_any:
                return updated_node

            self.changes.append({"kind": "import"})
            return updated_node.with_changes(names=tuple(new_names))

        def leave_ImportFrom(self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom) -> cst.ImportFrom:
            module_expr = updated_node.module
            if module_expr is None:
                return updated_node
            if not isinstance(module_expr, cst.BaseExpression):
                return updated_node

            dotted = _expr_to_dotted(module_expr)
            if not dotted:
                return updated_node

            rewritten = _rewrite_module_name(dotted, rules)
            if not rewritten:
                return updated_node

            self.changes.append({"kind": "from", "from_module": dotted, "to_module": rewritten})
            return updated_node.with_changes(module=_dotted_to_expr(rewritten))

    try:
        module = cst.parse_module(original)
        transformer = _Transformer()
        updated = module.visit(transformer)
        return updated.code, transformer.changes, None
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


def rewrite_python_imports(path: str, rules: list, dry_run: bool = False, engine: str = "auto") -> str:
    """Rewrite Python import statements using AST location info.

    Args:
        path: Target file path.
        rules: List of rewrite rules:
          - from_module: "old.module"
          - to_module: "new.module"
          - match: "exact" | "prefix" (optional, default "exact")
        dry_run: If True, do not write; return diff and stats only.
        engine: "auto" (prefer libcst), "libcst" (require libcst), or "ast" (stdlib fallback).

    Returns:
        JSON string describing changes or an error.
    """
    try:
        parsed_rules, err = _parse_rules(rules)
        if err:
            return json.dumps({"error": err})

        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        if p.suffix.lower() != ".py":
            return json.dumps({"error": f"rewrite_python_imports only supports .py files (got {p.name})"})

        original = p.read_text(encoding="utf-8", errors="ignore")

        requested_engine = (engine or "auto").strip().lower()
        if requested_engine not in {"auto", "libcst", "ast"}:
            return json.dumps({"error": "engine must be one of: auto, libcst, ast"})

        # Best-in-class engine: libcst (format-preserving). Falls back to stdlib AST rewriting (unless forced).
        engine_used = "ast"
        new_text: Optional[str] = None
        changed_nodes: List[Dict[str, Any]] = []

        if requested_engine in {"auto", "libcst"}:
            cst_text, cst_changes, cst_err = _try_rewrite_imports_with_libcst(original, parsed_rules)  # type: ignore[arg-type]
            if cst_err:
                return json.dumps(
                    {
                        "error": f"libcst rewrite failed: {cst_err}",
                        "path_abs": str(p),
                        "path_rel": _rel_to_root_posix(p),
                    }
                )
            if cst_text is None or cst_changes is None:
                if requested_engine == "libcst":
                    return json.dumps(
                        {
                            "error": "libcst is not available; install libcst to use engine='libcst'",
                            "path_abs": str(p),
                            "path_rel": _rel_to_root_posix(p),
                        }
                    )
            else:
                engine_used = "libcst"
                new_text = cst_text
                changed_nodes = cst_changes

        if engine_used != "libcst":
            # Fallback engine: stdlib AST (may reformat import statements).
            try:
                tree = ast.parse(original, filename=str(p))
            except SyntaxError as e:
                return json.dumps(
                    {
                        "error": f"SyntaxError: {e.msg} (line {e.lineno}:{e.offset})",
                        "path_abs": str(p),
                        "path_rel": _rel_to_root_posix(p),
                    }
                )

            offsets = _line_offsets(original)
            edits: List[Tuple[int, int, str]] = []

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    # Skip "from . import x" (module is None) - we don't rewrite those.
                    if node.module is None:
                        continue
                    rewritten = _rewrite_module_name(node.module, parsed_rules)  # type: ignore[arg-type]
                    if not rewritten:
                        continue
                    start, end = _slice_for_node(original, offsets, node)
                    block = original[start:end]
                    lines = block.splitlines(keepends=True)
                    first_line = lines[0] if lines else ""
                    indent = _indent_of_line(first_line)
                    last_line = lines[-1] if lines else ""
                    comment = ""
                    if "#" in last_line:
                        comment = last_line[last_line.index("#") :].rstrip("\n")
                    level = int(getattr(node, "level", 0) or 0)
                    prefix = "." * level
                    mod = f"{prefix}{rewritten}" if rewritten else prefix
                    names = ", ".join(
                        f"{a.name} as {a.asname}" if a.asname else a.name for a in node.names
                    )
                    new_stmt = f"{indent}from {mod} import {names}"
                    if comment:
                        new_stmt += "  " + comment
                    new_stmt += "\n"
                    edits.append((start, end, new_stmt))
                    changed_nodes.append(
                        {
                            "kind": "from",
                            "from_module": node.module,
                            "to_module": rewritten,
                            "lineno": getattr(node, "lineno", None),
                        }
                    )
                elif isinstance(node, ast.Import):
                    new_aliases = []
                    changed = False
                    for a in node.names:
                        rewritten = _rewrite_module_name(a.name, parsed_rules)  # type: ignore[arg-type]
                        if rewritten:
                            new_aliases.append((rewritten, a.asname))
                            changed = True
                        else:
                            new_aliases.append((a.name, a.asname))
                    if not changed:
                        continue
                    start, end = _slice_for_node(original, offsets, node)
                    block = original[start:end]
                    lines = block.splitlines(keepends=True)
                    first_line = lines[0] if lines else ""
                    indent = _indent_of_line(first_line)
                    last_line = lines[-1] if lines else ""
                    comment = ""
                    if "#" in last_line:
                        comment = last_line[last_line.index("#") :].rstrip("\n")
                    parts = ", ".join(f"{n} as {a}" if a else n for n, a in new_aliases)
                    new_stmt = f"{indent}import {parts}"
                    if comment:
                        new_stmt += "  " + comment
                    new_stmt += "\n"
                    edits.append((start, end, new_stmt))
                    changed_nodes.append(
                        {
                            "kind": "import",
                            "lineno": getattr(node, "lineno", None),
                        }
                    )

            if not edits:
                return json.dumps(
                    {
                        "changed": 0,
                        "engine": engine,
                        "path_abs": str(p),
                        "path_rel": _rel_to_root_posix(p),
                    }
                )

            # Apply edits bottom-up.
            new_text = original
            for start, end, repl in sorted(edits, key=lambda t: t[0], reverse=True):
                new_text = new_text[:start] + repl + new_text[end:]

        if not changed_nodes:
            return json.dumps(
                {
                    "changed": 0,
                    "engine": engine_used,
                    "path_abs": str(p),
                    "path_rel": _rel_to_root_posix(p),
                }
            )

        # Validate resulting syntax.
        try:
            ast.parse(new_text or "", filename=str(p))
        except SyntaxError as e:
            return json.dumps(
                {
                    "error": f"SyntaxError after rewrite: {e.msg} (line {e.lineno}:{e.offset})",
                    "changed": len(changed_nodes),
                    "engine": engine_used,
                    "path_abs": str(p),
                    "path_rel": _rel_to_root_posix(p),
                }
            )

        return _write_rewrite_result(
            path=p,
            original=original,
            new_text=new_text or "",
            dry_run=dry_run,
            payload={
                "changed": len(changed_nodes),
                "engine": engine_used,
                "changes": changed_nodes,
            },
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def rewrite_python_keyword_args(
    path: str,
    callee: str,
    renames: list,
    dry_run: bool = False,
    engine: str = "libcst",
) -> str:
    """Rename keyword arguments at call sites (format-preserving with libcst).

    Notes:
        - File-scoped only.
        - Requires specifying `callee` for safety (e.g., "foo" or "obj.foo").
        - Uses libcst to preserve formatting/comments/parentheses.
    """
    try:
        requested_engine = (engine or "libcst").strip().lower()
        if requested_engine not in {"libcst", "auto"}:
            return json.dumps({"error": "engine must be one of: libcst, auto"})
        missing = _require_libcst_or_error()
        if missing:
            return json.dumps({"error": missing})

        if not isinstance(callee, str) or not callee.strip():
            return json.dumps({"error": "callee must be a non-empty string"})
        if not isinstance(renames, list) or not renames:
            return json.dumps({"error": "renames must be a non-empty list"})

        rename_map: Dict[str, str] = {}
        for idx, item in enumerate(renames):
            if not isinstance(item, dict):
                return json.dumps({"error": f"renames[{idx}] must be an object"})
            old = item.get("old")
            new = item.get("new")
            if not isinstance(old, str) or not old.strip():
                return json.dumps({"error": f"renames[{idx}].old must be a non-empty string"})
            if not isinstance(new, str) or not new.strip():
                return json.dumps({"error": f"renames[{idx}].new must be a non-empty string"})
            rename_map[old.strip()] = new.strip()

        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        if p.suffix.lower() != ".py":
            return json.dumps({"error": f"rewrite_python_keyword_args only supports .py files (got {p.name})"})

        import libcst as cst  # type: ignore

        original = p.read_text(encoding="utf-8", errors="ignore")
        module = cst.parse_module(original)

        def _expr_to_dotted(expr: cst.BaseExpression) -> Optional[str]:
            if isinstance(expr, cst.Name):
                return expr.value
            if isinstance(expr, cst.Attribute):
                left = _expr_to_dotted(expr.value)
                if not left or not isinstance(expr.attr, cst.Name):
                    return None
                return f"{left}.{expr.attr.value}"
            return None

        class _Transformer(cst.CSTTransformer):
            def __init__(self) -> None:
                self.changed = 0

            def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
                if _expr_to_dotted(updated_node.func) != callee:
                    return updated_node
                new_args = []
                changed_any = False
                for a in updated_node.args:
                    if a.keyword is None or not isinstance(a.keyword, cst.Name):
                        new_args.append(a)
                        continue
                    old_kw = a.keyword.value
                    new_kw = rename_map.get(old_kw)
                    if not new_kw or new_kw == old_kw:
                        new_args.append(a)
                        continue
                    new_args.append(a.with_changes(keyword=cst.Name(new_kw)))
                    changed_any = True
                    self.changed += 1
                if not changed_any:
                    return updated_node
                return updated_node.with_changes(args=tuple(new_args))

        transformer = _Transformer()
        updated = module.visit(transformer)
        new_text = updated.code

        try:
            ast.parse(new_text, filename=str(p))
        except SyntaxError as e:
            return json.dumps({"error": f"SyntaxError after rewrite: {e.msg} (line {e.lineno}:{e.offset})"})

        if transformer.changed == 0:
            return json.dumps(
                {"changed": 0, "engine": "libcst", "path_abs": str(p), "path_rel": _rel_to_root_posix(p)}
            )

        return _write_rewrite_result(
            path=p,
            original=original,
            new_text=new_text,
            dry_run=dry_run,
            payload={"changed": transformer.changed, "engine": "libcst", "callee": callee, "renames": renames},
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def rename_imported_symbols(
    path: str,
    renames: list,
    dry_run: bool = False,
    engine: str = "libcst",
) -> str:
    """Rename imported symbol(s) and update references in the same file (libcst + QualifiedNameProvider).

    Each rename rule:
      - from_module (optional): only match imports from this module
      - old_name: imported symbol name (in the import statement)
      - new_name: new symbol name (in the import statement + local references when not aliased)
    """
    try:
        requested_engine = (engine or "libcst").strip().lower()
        if requested_engine not in {"libcst", "auto"}:
            return json.dumps({"error": "engine must be one of: libcst, auto"})
        missing = _require_libcst_or_error()
        if missing:
            return json.dumps({"error": missing})

        if not isinstance(renames, list) or not renames:
            return json.dumps({"error": "renames must be a non-empty list"})

        parsed_rules: List[Dict[str, str]] = []
        for idx, rule in enumerate(renames):
            if not isinstance(rule, dict):
                return json.dumps({"error": f"renames[{idx}] must be an object"})
            old = rule.get("old_name")
            new = rule.get("new_name")
            mod = rule.get("from_module")
            if not isinstance(old, str) or not old.strip():
                return json.dumps({"error": f"renames[{idx}].old_name must be a non-empty string"})
            if not isinstance(new, str) or not new.strip():
                return json.dumps({"error": f"renames[{idx}].new_name must be a non-empty string"})
            if mod is not None and (not isinstance(mod, str) or not mod.strip()):
                return json.dumps({"error": f"renames[{idx}].from_module must be a non-empty string when provided"})
            parsed_rules.append(
                {
                    "from_module": mod.strip() if isinstance(mod, str) else "",
                    "old_name": old.strip(),
                    "new_name": new.strip(),
                }
            )

        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        if p.suffix.lower() != ".py":
            return json.dumps({"error": f"rename_imported_symbols only supports .py files (got {p.name})"})

        import libcst as cst  # type: ignore
        from libcst.metadata import MetadataWrapper, QualifiedNameProvider, QualifiedName  # type: ignore

        original = p.read_text(encoding="utf-8", errors="ignore")
        module = cst.parse_module(original)
        wrapper = MetadataWrapper(module)

        def _expr_to_dotted(expr: cst.BaseExpression) -> Optional[str]:
            if isinstance(expr, cst.Name):
                return expr.value
            if isinstance(expr, cst.Attribute):
                parts = []
                cur: cst.BaseExpression = expr
                while isinstance(cur, cst.Attribute):
                    if not isinstance(cur.attr, cst.Name):
                        return None
                    parts.append(cur.attr.value)
                    if isinstance(cur.value, cst.Name):
                        parts.append(cur.value.value)
                        break
                    cur = cur.value  # type: ignore[assignment]
                return ".".join(reversed(parts)) if parts else None
            return None

        class _Transformer(cst.CSTTransformer):
            METADATA_DEPENDENCIES = (QualifiedNameProvider,)

            def __init__(self) -> None:
                self.changed_imports = 0
                self.changed_refs = 0
                self._qualified_targets: Dict[str, str] = {}

            def leave_ImportFrom(self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom) -> cst.ImportFrom:
                if updated_node.module is None:
                    return updated_node
                if not isinstance(updated_node.names, (list, tuple)):
                    return updated_node
                mod = _expr_to_dotted(updated_node.module)
                if not mod:
                    return updated_node

                new_aliases = []
                changed_any = False
                for alias in updated_node.names:
                    if not isinstance(alias, cst.ImportAlias) or not isinstance(alias.name, cst.Name):
                        new_aliases.append(alias)
                        continue
                    matched = False
                    for r in parsed_rules:
                        if r["from_module"] and r["from_module"] != mod:
                            continue
                        if alias.name.value != r["old_name"]:
                            continue
                        matched = True
                        if alias.asname is not None:
                            new_aliases.append(alias.with_changes(name=cst.Name(r["new_name"])))
                            self.changed_imports += 1
                            changed_any = True
                        else:
                            self._qualified_targets[f"{mod}.{r['old_name']}"] = r["new_name"]
                            new_aliases.append(alias.with_changes(name=cst.Name(r["new_name"])))
                            self.changed_imports += 1
                            changed_any = True
                        break
                    if not matched:
                        new_aliases.append(alias)

                if not changed_any:
                    return updated_node
                return updated_node.with_changes(names=tuple(new_aliases))

            def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
                try:
                    qnames = self.get_metadata(QualifiedNameProvider, original_node, default=set())
                except Exception:
                    return updated_node
                if not qnames:
                    return updated_node
                for qn in qnames:
                    q = qn.name if isinstance(qn, QualifiedName) else str(qn)
                    new_local = self._qualified_targets.get(q)
                    if new_local and updated_node.value != new_local:
                        self.changed_refs += 1
                        return cst.Name(new_local)
                return updated_node

        transformer = _Transformer()
        updated = wrapper.visit(transformer)
        new_text = updated.code

        try:
            ast.parse(new_text, filename=str(p))
        except SyntaxError as e:
            return json.dumps({"error": f"SyntaxError after rewrite: {e.msg} (line {e.lineno}:{e.offset})"})

        total_changed = transformer.changed_imports + transformer.changed_refs
        if total_changed == 0:
            return json.dumps(
                {"changed": 0, "engine": "libcst", "path_abs": str(p), "path_rel": _rel_to_root_posix(p)}
            )

        return _write_rewrite_result(
            path=p,
            original=original,
            new_text=new_text,
            dry_run=dry_run,
            payload={
                "changed": total_changed,
                "engine": "libcst",
                "changed_imports": transformer.changed_imports,
                "changed_refs": transformer.changed_refs,
                "renames": renames,
            },
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def move_imported_symbols(
    path: str,
    old_module: str,
    new_module: str,
    symbols: list,
    dry_run: bool = False,
    engine: str = "libcst",
) -> str:
    """Move specific `from old_module import ...` symbols to `from new_module import ...` within one file."""
    try:
        requested_engine = (engine or "libcst").strip().lower()
        if requested_engine not in {"libcst", "auto"}:
            return json.dumps({"error": "engine must be one of: libcst, auto"})
        missing = _require_libcst_or_error()
        if missing:
            return json.dumps({"error": missing})

        if not isinstance(old_module, str) or not old_module.strip():
            return json.dumps({"error": "old_module must be a non-empty string"})
        if not isinstance(new_module, str) or not new_module.strip():
            return json.dumps({"error": "new_module must be a non-empty string"})
        if not isinstance(symbols, list) or not symbols or not all(isinstance(s, str) and s.strip() for s in symbols):
            return json.dumps({"error": "symbols must be a non-empty list of strings"})

        old_module = old_module.strip()
        new_module = new_module.strip()
        wanted = {s.strip() for s in symbols}

        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        if p.suffix.lower() != ".py":
            return json.dumps({"error": f"move_imported_symbols only supports .py files (got {p.name})"})

        import libcst as cst  # type: ignore

        original = p.read_text(encoding="utf-8", errors="ignore")
        module = cst.parse_module(original)

        def _expr_to_dotted(expr: cst.BaseExpression) -> Optional[str]:
            if isinstance(expr, cst.Name):
                return expr.value
            if isinstance(expr, cst.Attribute):
                parts = []
                cur: cst.BaseExpression = expr
                while isinstance(cur, cst.Attribute):
                    if not isinstance(cur.attr, cst.Name):
                        return None
                    parts.append(cur.attr.value)
                    if isinstance(cur.value, cst.Name):
                        parts.append(cur.value.value)
                        break
                    cur = cur.value  # type: ignore[assignment]
                return ".".join(reversed(parts)) if parts else None
            return None

        def _dotted_to_expr(dotted: str) -> cst.BaseExpression:
            parts = [p for p in dotted.split(".") if p]
            node: cst.BaseExpression = cst.Name(parts[0])
            for part in parts[1:]:
                node = cst.Attribute(value=node, attr=cst.Name(part))
            return node

        class _Transformer(cst.CSTTransformer):
            def __init__(self) -> None:
                self.changed = 0

            def leave_SimpleStatementLine(
                self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine
            ):
                if len(updated_node.body) != 1:
                    return updated_node
                stmt = updated_node.body[0]
                if not isinstance(stmt, cst.ImportFrom):
                    return updated_node
                if stmt.module is None:
                    return updated_node
                mod = _expr_to_dotted(stmt.module)
                if mod != old_module:
                    return updated_node
                if not isinstance(stmt.names, (list, tuple)):
                    return updated_node

                keep_aliases = []
                move_aliases = []
                for a in stmt.names:
                    if not isinstance(a, cst.ImportAlias) or not isinstance(a.name, cst.Name):
                        keep_aliases.append(a)
                        continue
                    if a.name.value in wanted:
                        move_aliases.append(a)
                    else:
                        keep_aliases.append(a)

                if not move_aliases:
                    return updated_node

                self.changed += len(move_aliases)

                if not keep_aliases:
                    new_stmt = stmt.with_changes(module=_dotted_to_expr(new_module))
                    return updated_node.with_changes(body=(new_stmt,))

                kept_stmt = stmt.with_changes(names=tuple(keep_aliases))
                moved_stmt = stmt.with_changes(module=_dotted_to_expr(new_module), names=tuple(move_aliases))
                kept_line = updated_node.with_changes(body=(kept_stmt,))
                moved_line = cst.SimpleStatementLine(body=(moved_stmt,))
                return cst.FlattenSentinel([kept_line, moved_line])

        transformer = _Transformer()
        updated = module.visit(transformer)
        new_text = updated.code

        try:
            ast.parse(new_text, filename=str(p))
        except SyntaxError as e:
            return json.dumps({"error": f"SyntaxError after rewrite: {e.msg} (line {e.lineno}:{e.offset})"})

        if transformer.changed == 0:
            return json.dumps(
                {"changed": 0, "engine": "libcst", "path_abs": str(p), "path_rel": _rel_to_root_posix(p)}
            )

        return _write_rewrite_result(
            path=p,
            original=original,
            new_text=new_text,
            dry_run=dry_run,
            payload={
                "changed": transformer.changed,
                "engine": "libcst",
                "old_module": old_module,
                "new_module": new_module,
                "symbols": sorted(wanted),
            },
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def rewrite_python_function_parameters(
    path: str,
    function: str,
    rename: list = None,
    add: list = None,
    remove: list = None,
    dry_run: bool = False,
    engine: str = "libcst",
) -> str:
    """Add/remove/rename function parameters and update call sites (conservative, file-scoped).

    - Supports `function` as "foo" or "Class.method".
    - `rename`: [{"old":"x","new":"y"}] updates def + keyword call sites.
    - `add`: [{"name":"x","default":"None"}] appends defaulted params to the signature (calls remain valid).
    - `remove`: ["x"] removes params and removes keyword args at call sites; refuses if any positional calls exist.
    """
    try:
        requested_engine = (engine or "libcst").strip().lower()
        if requested_engine not in {"libcst", "auto"}:
            return json.dumps({"error": "engine must be one of: libcst, auto"})
        missing = _require_libcst_or_error()
        if missing:
            return json.dumps({"error": missing})

        if not isinstance(function, str) or not function.strip():
            return json.dumps({"error": "function must be a non-empty string"})
        function = function.strip()

        rename = rename or []
        add = add or []
        remove = remove or []
        if not isinstance(rename, list) or not isinstance(add, list) or not isinstance(remove, list):
            return json.dumps({"error": "rename/add/remove must be lists"})

        rename_map: Dict[str, str] = {}
        for idx, r in enumerate(rename):
            if not isinstance(r, dict):
                return json.dumps({"error": f"rename[{idx}] must be an object"})
            old = r.get("old")
            new = r.get("new")
            if not isinstance(old, str) or not old.strip():
                return json.dumps({"error": f"rename[{idx}].old must be a non-empty string"})
            if not isinstance(new, str) or not new.strip():
                return json.dumps({"error": f"rename[{idx}].new must be a non-empty string"})
            rename_map[old.strip()] = new.strip()

        add_params: List[Tuple[str, str]] = []
        for idx, a in enumerate(add):
            if not isinstance(a, dict):
                return json.dumps({"error": f"add[{idx}] must be an object"})
            name = a.get("name")
            default = a.get("default")
            if not isinstance(name, str) or not name.strip():
                return json.dumps({"error": f"add[{idx}].name must be a non-empty string"})
            if not isinstance(default, str) or not default.strip():
                return json.dumps({"error": f"add[{idx}].default must be a non-empty string expression"})
            add_params.append((name.strip(), default.strip()))

        remove_names: List[str] = []
        for idx, n in enumerate(remove):
            if not isinstance(n, str) or not n.strip():
                return json.dumps({"error": f"remove[{idx}] must be a non-empty string"})
            remove_names.append(n.strip())
        remove_set = set(remove_names)
        # Apply remove AFTER renames: allow remove entries to refer to either the
        # original name or the post-rename name.
        remove_final_set = {rename_map.get(n, n) for n in remove_set}
        # If we rename A->B and remove B, references to A would become references
        # to the removed name after the rewrite. Check both.
        remove_ref_check = set(remove_final_set)
        for old_name, new_name in rename_map.items():
            if new_name in remove_final_set:
                remove_ref_check.add(old_name)

        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        if p.suffix.lower() != ".py":
            return json.dumps({"error": f"rewrite_python_function_parameters only supports .py files (got {p.name})"})

        import libcst as cst  # type: ignore
        from libcst.metadata import MetadataWrapper, ParentNodeProvider  # type: ignore

        original = p.read_text(encoding="utf-8", errors="ignore")
        module = cst.parse_module(original)
        wrapper = MetadataWrapper(module)

        def _expr_to_dotted(expr: cst.BaseExpression) -> Optional[str]:
            if isinstance(expr, cst.Name):
                return expr.value
            if isinstance(expr, cst.Attribute):
                left = _expr_to_dotted(expr.value)
                if not left or not isinstance(expr.attr, cst.Name):
                    return None
                return f"{left}.{expr.attr.value}"
            return None

        if remove_final_set:
            class _Analyzer(cst.CSTVisitor):
                METADATA_DEPENDENCIES = (ParentNodeProvider,)

                def __init__(self) -> None:
                    self.has_positional = False
                    self.removed_name_referenced = False
                    self._class_stack: List[str] = []
                    self._in_target_fn = False
                    self._nested_fn_depth = 0

                def visit_ClassDef(self, node: cst.ClassDef) -> Optional[bool]:
                    self._class_stack.append(node.name.value)
                    return True

                def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
                    if self._class_stack:
                        self._class_stack.pop()

                def _qualname(self, name: str) -> str:
                    return ".".join(self._class_stack + [name]) if self._class_stack else name

                def visit_FunctionDef(self, node: cst.FunctionDef) -> Optional[bool]:
                    if self._in_target_fn:
                        self._nested_fn_depth += 1
                        return True
                    if self._qualname(node.name.value) == function:
                        self._in_target_fn = True
                        self._nested_fn_depth = 0
                    return True

                def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
                    if self._nested_fn_depth > 0:
                        self._nested_fn_depth -= 1
                        return
                    if self._in_target_fn and self._qualname(original_node.name.value) == function:
                        self._in_target_fn = False

                def visit_Call(self, node: cst.Call) -> Optional[bool]:
                    if _expr_to_dotted(node.func) != function:
                        return True
                    for a in node.args:
                        if a.keyword is None:
                            self.has_positional = True
                            return False
                    return True

                def visit_Name(self, node: cst.Name) -> None:
                    if not self._in_target_fn or self._nested_fn_depth != 0:
                        return
                    if node.value not in remove_ref_check:
                        return
                    parent = self.get_metadata(ParentNodeProvider, node, default=None)
                    if parent is not None:
                        if isinstance(parent, cst.Param) and parent.name is node:
                            return
                        if isinstance(parent, cst.Arg) and parent.keyword is node:
                            return
                        if isinstance(parent, cst.Attribute) and parent.attr is node:
                            return
                    self.removed_name_referenced = True

            analyzer = _Analyzer()
            wrapper.visit(analyzer)
            if analyzer.has_positional:
                return json.dumps(
                    {
                        "error": "Refusing to remove parameters when positional call arguments exist (file-scoped safety).",
                        "path_abs": str(p),
                        "path_rel": _rel_to_root_posix(p),
                    }
                )
            if analyzer.removed_name_referenced:
                return json.dumps(
                    {
                        "error": "Refusing to remove parameter(s) still referenced in the target function body.",
                        "path_abs": str(p),
                        "path_rel": _rel_to_root_posix(p),
                    }
                )

        class _Transformer(cst.CSTTransformer):
            METADATA_DEPENDENCIES = (ParentNodeProvider,)

            def __init__(self) -> None:
                self.changed_def = 0
                self.changed_calls = 0
                self._class_stack: List[str] = []
                self._in_target_fn = False
                self._nested_fn_depth = 0

            def visit_ClassDef(self, node: cst.ClassDef) -> Optional[bool]:
                self._class_stack.append(node.name.value)
                return True

            def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
                if self._class_stack:
                    self._class_stack.pop()
                return updated_node

            def _qualname(self, name: str) -> str:
                return ".".join(self._class_stack + [name]) if self._class_stack else name

            def visit_FunctionDef(self, node: cst.FunctionDef) -> Optional[bool]:
                if self._in_target_fn:
                    self._nested_fn_depth += 1
                    return True
                if self._qualname(node.name.value) == function:
                    self._in_target_fn = True
                    self._nested_fn_depth = 0
                return True

            def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
                is_target = self._qualname(updated_node.name.value) == function and self._nested_fn_depth == 0
                if not is_target:
                    if self._nested_fn_depth > 0:
                        self._nested_fn_depth -= 1
                    return updated_node

                params = updated_node.params

                def _rewrite_list(items):
                    out = []
                    changed_any = False
                    for prm in items:
                        if isinstance(prm, cst.Param) and isinstance(prm.name, cst.Name):
                            effective = rename_map.get(prm.name.value, prm.name.value)
                            if effective in remove_final_set:
                                changed_any = True
                                self.changed_def += 1
                                continue
                            if effective != prm.name.value:
                                out.append(prm.with_changes(name=cst.Name(effective)))
                                changed_any = True
                                self.changed_def += 1
                                continue
                        out.append(prm)
                    return tuple(out), changed_any

                new_params, changed_p = _rewrite_list(params.params)
                new_kwonly, changed_k = _rewrite_list(params.kwonly_params)

                add_nodes = []
                for name, default_expr in add_params:
                    try:
                        default_node = cst.parse_expression(default_expr)
                    except Exception as e:
                        raise ValueError(f"Invalid default expression for '{name}': {default_expr} ({e})")
                    add_nodes.append(cst.Param(name=cst.Name(name), default=default_node))
                if add_nodes:
                    new_params = tuple(list(new_params) + add_nodes)
                    self.changed_def += len(add_nodes)
                    changed_p = True

                if not (changed_p or changed_k):
                    out_node = updated_node
                else:
                    out_node = updated_node.with_changes(params=params.with_changes(params=new_params, kwonly_params=new_kwonly))

                # Leaving the target function.
                self._in_target_fn = False
                return out_node

            def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
                if _expr_to_dotted(updated_node.func) != function:
                    return updated_node
                new_args = []
                changed_any = False
                for a in updated_node.args:
                    if a.keyword is not None and isinstance(a.keyword, cst.Name):
                        effective_kw = rename_map.get(a.keyword.value, a.keyword.value)
                        if effective_kw in remove_final_set:
                            changed_any = True
                            self.changed_calls += 1
                            continue
                        if effective_kw != a.keyword.value:
                            new_args.append(a.with_changes(keyword=cst.Name(effective_kw)))
                            changed_any = True
                            self.changed_calls += 1
                            continue
                    new_args.append(a)
                if not changed_any:
                    return updated_node
                # If we removed trailing args, drop the dangling comma from the new last arg.
                if new_args:
                    last = new_args[-1]
                    if isinstance(last, cst.Arg) and isinstance(last.comma, cst.Comma):
                        new_args[-1] = last.with_changes(comma=cst.MaybeSentinel.DEFAULT)
                return updated_node.with_changes(args=tuple(new_args))

            def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
                if not self._in_target_fn or self._nested_fn_depth != 0:
                    return updated_node
                nn = rename_map.get(updated_node.value)
                if not nn or nn == updated_node.value:
                    return updated_node
                parent = self.get_metadata(ParentNodeProvider, original_node, default=None)
                if parent is not None:
                    if isinstance(parent, cst.Param) and parent.name is original_node:
                        return updated_node
                    if isinstance(parent, cst.Arg) and parent.keyword is original_node:
                        return updated_node
                    if isinstance(parent, cst.Attribute) and parent.attr is original_node:
                        return updated_node
                self.changed_def += 1
                return cst.Name(nn)

        transformer = _Transformer()
        updated = wrapper.visit(transformer)
        new_text = updated.code

        try:
            ast.parse(new_text, filename=str(p))
        except SyntaxError as e:
            return json.dumps({"error": f"SyntaxError after rewrite: {e.msg} (line {e.lineno}:{e.offset})"})

        total = transformer.changed_def + transformer.changed_calls
        if total == 0:
            return json.dumps(
                {"changed": 0, "engine": "libcst", "path_abs": str(p), "path_rel": _rel_to_root_posix(p)}
            )

        return _write_rewrite_result(
            path=p,
            original=original,
            new_text=new_text,
            dry_run=dry_run,
            payload={
                "changed": total,
                "engine": "libcst",
                "function": function,
                "changed_def": transformer.changed_def,
                "changed_calls": transformer.changed_calls,
                "rename": rename,
                "add": add,
                "remove": remove,
            },
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
