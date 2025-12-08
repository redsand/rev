#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Terminal formatting utilities for rich output."""

import sys


class Colors:
    """ANSI color codes."""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    # Foreground colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'

    # Bright colors
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'

    @staticmethod
    def is_tty():
        """Check if output is a TTY (supports colors)."""
        return sys.stdout.isatty()


class Symbols:
    """Unicode symbols for formatted output."""
    # Bullets and markers
    BULLET = '●'
    HOLLOW_BULLET = '○'
    ARROW = '→'
    CHECK = '✓'
    CROSS = '✗'
    WARNING = '⚠'
    INFO = 'ℹ'

    # Tree characters
    TREE_BRANCH = '⎿'
    TREE_LINE = '│'
    TREE_SPLIT = '├'
    TREE_END = '└'

    # Box drawing
    BOX_H = '─'
    BOX_V = '│'
    BOX_TL = '┌'
    BOX_TR = '┐'
    BOX_BL = '└'
    BOX_BR = '┘'
    BOX_CROSS = '┼'
    BOX_T_DOWN = '┬'
    BOX_T_UP = '┴'
    BOX_T_RIGHT = '├'
    BOX_T_LEFT = '┤'

    # Misc
    ELLIPSIS = '…'
    SEPARATOR = '━'


def colorize(text: str, color: str, bold: bool = False) -> str:
    """Colorize text if TTY supports it.

    Args:
        text: Text to colorize
        color: Color code from Colors class
        bold: Whether to make text bold

    Returns:
        Formatted text
    """
    if not Colors.is_tty():
        return text

    prefix = Colors.BOLD if bold else ''
    return f"{prefix}{color}{text}{Colors.RESET}"


def create_header(title: str, width: int = 80) -> str:
    """Create a styled header.

    Args:
        title: Header title
        width: Width of header

    Returns:
        Formatted header
    """
    separator = Symbols.BOX_H * width
    return f"\n{colorize(title, Colors.BRIGHT_CYAN, bold=True)}\n{colorize(separator, Colors.BRIGHT_BLACK)}"


def create_section(title: str) -> str:
    """Create a section header.

    Args:
        title: Section title

    Returns:
        Formatted section
    """
    return f"\n{colorize(title, Colors.BRIGHT_WHITE, bold=True)}"


def create_item(label: str, value: str, indent: int = 2) -> str:
    """Create a key-value item.

    Args:
        label: Item label
        value: Item value
        indent: Indentation level

    Returns:
        Formatted item
    """
    spaces = ' ' * indent
    label_fmt = colorize(f"{label}:", Colors.BRIGHT_BLACK)
    return f"{spaces}{label_fmt:<25} {value}"


def create_bullet_item(text: str, bullet_type: str = 'bullet', indent: int = 2) -> str:
    """Create a bullet point item.

    Args:
        text: Item text
        bullet_type: Type of bullet (bullet, check, cross, warning, info)
        indent: Indentation level

    Returns:
        Formatted bullet item
    """
    spaces = ' ' * indent
    bullets = {
        'bullet': (Symbols.BULLET, Colors.BRIGHT_BLUE),
        'check': (Symbols.CHECK, Colors.BRIGHT_GREEN),
        'cross': (Symbols.CROSS, Colors.BRIGHT_RED),
        'warning': (Symbols.WARNING, Colors.BRIGHT_YELLOW),
        'info': (Symbols.INFO, Colors.BRIGHT_CYAN),
        'hollow': (Symbols.HOLLOW_BULLET, Colors.BRIGHT_BLACK)
    }

    symbol, color = bullets.get(bullet_type, bullets['bullet'])
    bullet = colorize(symbol, color)

    return f"{spaces}{bullet} {text}"


def create_tree_item(text: str, is_last: bool = False, indent: int = 2) -> str:
    """Create a tree-style item.

    Args:
        text: Item text
        is_last: Whether this is the last item in the tree
        indent: Indentation level

    Returns:
        Formatted tree item
    """
    spaces = ' ' * indent
    branch = Symbols.TREE_END if is_last else Symbols.TREE_SPLIT
    branch_fmt = colorize(branch, Colors.BRIGHT_BLACK)

    return f"{spaces}{branch_fmt} {text}"


def create_panel(title: str, content: list, width: int = 80) -> str:
    """Create a bordered panel.

    Args:
        title: Panel title
        content: List of content lines
        width: Panel width

    Returns:
        Formatted panel
    """
    # Top border
    top = f"{Symbols.BOX_TL}{Symbols.BOX_H * (width - 2)}{Symbols.BOX_TR}"
    # Title
    title_line = f"{Symbols.BOX_V} {colorize(title, Colors.BRIGHT_CYAN, bold=True):<{width-3}}{Symbols.BOX_V}"
    # Separator
    separator = f"{Symbols.BOX_T_RIGHT}{Symbols.BOX_H * (width - 2)}{Symbols.BOX_T_LEFT}"
    # Content
    content_lines = []
    for line in content:
        # Remove ANSI codes for length calculation
        import re
        clean_line = re.sub(r'\033\[[0-9;]+m', '', str(line))
        padding = width - 3 - len(clean_line)
        content_lines.append(f"{Symbols.BOX_V} {line}{' ' * padding}{Symbols.BOX_V}")
    # Bottom border
    bottom = f"{Symbols.BOX_BL}{Symbols.BOX_H * (width - 2)}{Symbols.BOX_BR}"

    result = [top, title_line, separator] + content_lines + [bottom]
    return '\n'.join(colorize(line, Colors.BRIGHT_BLACK) for line in result)


def create_progress_bar(current: int, total: int, width: int = 40) -> str:
    """Create a progress bar.

    Args:
        current: Current progress
        total: Total amount
        width: Width of progress bar

    Returns:
        Formatted progress bar
    """
    if total == 0:
        percentage = 0
    else:
        percentage = min(100, int((current / total) * 100))

    filled = int((width * percentage) / 100)
    bar = '█' * filled + '░' * (width - filled)

    bar_colored = (
        colorize('█' * filled, Colors.BRIGHT_GREEN) +
        colorize('░' * (width - filled), Colors.BRIGHT_BLACK)
    )

    return f"{bar_colored} {percentage:3d}% ({current}/{total})"


def create_table(headers: list, rows: list, col_widths: list = None) -> str:
    """Create a simple table.

    Args:
        headers: List of header strings
        rows: List of row lists
        col_widths: Optional list of column widths

    Returns:
        Formatted table
    """
    if not col_widths:
        # Auto-calculate column widths
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    # Add padding
    col_widths = [w + 2 for w in col_widths]

    # Create header
    header_row = Symbols.BOX_V + Symbols.BOX_V.join(
        f" {colorize(h, Colors.BRIGHT_CYAN, bold=True):<{col_widths[i]-1}}"
        for i, h in enumerate(headers)
    ) + Symbols.BOX_V

    # Create separator
    separator = Symbols.BOX_T_RIGHT + Symbols.BOX_T_DOWN.join(
        Symbols.BOX_H * w for w in col_widths
    ) + Symbols.BOX_T_LEFT

    # Create rows
    table_rows = []
    for row in rows:
        row_str = Symbols.BOX_V + Symbols.BOX_V.join(
            f" {str(cell):<{col_widths[i]-1}}"
            for i, cell in enumerate(row)
        ) + Symbols.BOX_V
        table_rows.append(row_str)

    # Create top and bottom borders
    top = Symbols.BOX_TL + Symbols.BOX_T_DOWN.join(
        Symbols.BOX_H * w for w in col_widths
    ) + Symbols.BOX_TR
    bottom = Symbols.BOX_BL + Symbols.BOX_T_UP.join(
        Symbols.BOX_H * w for w in col_widths
    ) + Symbols.BOX_BR

    # Combine
    result = [top, header_row, separator] + table_rows + [bottom]
    return '\n'.join(result)


def format_file_change(operation: str, file_path: str, details: str = None) -> str:
    """Format a file change operation.

    Args:
        operation: Operation type (Read, Update, Create, Delete)
        file_path: File path
        details: Optional details

    Returns:
        Formatted file change
    """
    ops = {
        'Read': Colors.BRIGHT_BLUE,
        'Update': Colors.BRIGHT_GREEN,
        'Create': Colors.BRIGHT_CYAN,
        'Delete': Colors.BRIGHT_RED,
        'Move': Colors.BRIGHT_YELLOW
    }

    color = ops.get(operation, Colors.WHITE)
    bullet = colorize(Symbols.BULLET, color)
    op_text = colorize(operation, color, bold=True)

    output = [f"{bullet} {op_text}({file_path})"]

    if details:
        branch = colorize(Symbols.TREE_BRANCH, Colors.BRIGHT_BLACK)
        output.append(f"  {branch}  {details}")

    return '\n'.join(output)
