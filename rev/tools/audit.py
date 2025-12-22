#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit logging for tool permissions and access control."""

from pathlib import Path
from typing import List
import json
import time

from rev.tools.permissions import PermissionDenial, get_permission_manager
from rev.debug_logger import get_logger


logger = get_logger()


def get_denial_log() -> List[PermissionDenial]:
    """Get all permission denials in the current session.

    Returns:
        List of PermissionDenial records
    """
    manager = get_permission_manager()
    return manager.get_denial_log()


def export_denial_log(path: Path):
    """Export permission denial log to a file.

    Args:
        path: Path where denial log should be written (JSON format)
    """
    manager = get_permission_manager()
    manager.export_denial_log(path)


def get_denial_summary() -> dict:
    """Get a summary of permission denials.

    Returns:
        Dict with denial statistics and summaries
    """
    denials = get_denial_log()

    if not denials:
        return {
            "total_denials": 0,
            "by_agent": {},
            "by_tool": {},
            "recent_denials": [],
        }

    # Count by agent
    by_agent = {}
    for denial in denials:
        agent = denial.agent_name
        by_agent[agent] = by_agent.get(agent, 0) + 1

    # Count by tool
    by_tool = {}
    for denial in denials:
        tool = denial.tool_name
        by_tool[tool] = by_tool.get(tool, 0) + 1

    # Get most recent denials
    recent = sorted(denials, key=lambda d: d.timestamp, reverse=True)[:10]
    recent_list = [
        {
            "agent": d.agent_name,
            "tool": d.tool_name,
            "reason": d.reason,
            "timestamp": d.timestamp,
        }
        for d in recent
    ]

    return {
        "total_denials": len(denials),
        "by_agent": by_agent,
        "by_tool": by_tool,
        "recent_denials": recent_list,
    }


def print_denial_summary():
    """Print a human-readable summary of permission denials."""
    summary = get_denial_summary()

    if summary["total_denials"] == 0:
        print("No permission denials in this session.")
        return

    print(f"\n=== Permission Denial Summary ===")
    print(f"Total denials: {summary['total_denials']}")

    print(f"\nDenials by agent:")
    for agent, count in sorted(summary["by_agent"].items(), key=lambda x: x[1], reverse=True):
        print(f"  {agent}: {count}")

    print(f"\nDenials by tool:")
    for tool, count in sorted(summary["by_tool"].items(), key=lambda x: x[1], reverse=True):
        print(f"  {tool}: {count}")

    print(f"\nRecent denials:")
    for denial in summary["recent_denials"][:5]:
        print(f"  [{denial['agent']}] {denial['tool']}: {denial['reason']}")


def save_audit_report(output_dir: Path):
    """Save a comprehensive audit report to a directory.

    Creates:
        - denial_log.json: Full denial log
        - denial_summary.json: Summary statistics
        - audit_report.txt: Human-readable report

    Args:
        output_dir: Directory where report files should be saved
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save full denial log
    export_denial_log(output_dir / "denial_log.json")

    # Save summary
    summary = get_denial_summary()
    with open(output_dir / "denial_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Generate human-readable report
    report_lines = []
    report_lines.append("=" * 60)
    report_lines.append("TOOL PERMISSION AUDIT REPORT")
    report_lines.append("=" * 60)
    report_lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"Total denials: {summary['total_denials']}")
    report_lines.append("")

    if summary["total_denials"] > 0:
        report_lines.append("DENIALS BY AGENT:")
        report_lines.append("-" * 40)
        for agent, count in sorted(summary["by_agent"].items(), key=lambda x: x[1], reverse=True):
            report_lines.append(f"  {agent:20s} {count:5d} denials")
        report_lines.append("")

        report_lines.append("DENIALS BY TOOL:")
        report_lines.append("-" * 40)
        for tool, count in sorted(summary["by_tool"].items(), key=lambda x: x[1], reverse=True):
            report_lines.append(f"  {tool:20s} {count:5d} denials")
        report_lines.append("")

        report_lines.append("RECENT DENIALS:")
        report_lines.append("-" * 40)
        for denial in summary["recent_denials"]:
            report_lines.append(f"  Agent: {denial['agent']}")
            report_lines.append(f"  Tool:  {denial['tool']}")
            report_lines.append(f"  Reason: {denial['reason']}")
            report_lines.append(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(denial['timestamp']))}")
            report_lines.append("")

    report_text = "\n".join(report_lines)
    with open(output_dir / "audit_report.txt", "w", encoding="utf-8") as f:
        f.write(report_text)

    logger.info(f"Audit report saved to {output_dir}")
    print(f"\nAudit report saved to: {output_dir}")
    print(f"  - denial_log.json")
    print(f"  - denial_summary.json")
    print(f"  - audit_report.txt")
