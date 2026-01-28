#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test that handoff_contracts module has been removed.

This test ensures the unused handoff_contracts module was successfully
deleted as part of the codebase simplification effort.
"""

import sys
import importlib
import unittest
from pathlib import Path


class TestHandoffContractsRemoved(unittest.TestCase):
    """Verify handoff_contracts module has been deleted."""

    def test_handoff_contracts_directory_does_not_exist(self):
        """The handoff_contracts directory should not exist."""
        rev_dir = Path(__file__).parent.parent / "rev" / "handoff_contracts"
        self.assertFalse(
            rev_dir.exists(),
            f"handoff_contracts directory still exists at {rev_dir}"
        )

    def test_handoff_contracts_not_importable(self):
        """The handoff_contracts module should not be importable."""
        try:
            importlib.import_module("rev.handoff_contracts")
            self.fail("rev.handoff_contracts should not be importable")
        except ImportError:
            # This is expected
            pass

    def test_no_handoff_contract_imports_in_production_code(self):
        """No production code should import from handoff_contracts."""
        from pathlib import Path
        import re

        rev_dir = Path(__file__).parent.parent / "rev"
        pattern = re.compile(r"from\s+rev\.handoff_contracts|from\s+handoff_contracts")

        imports_found = []
        for py_file in rev_dir.rglob("*.py"):
            # Skip test files and __pycache__
            if "test" in py_file.name or "__pycache__" in str(py_file):
                continue
            content = py_file.read_text(errors="ignore")
            if pattern.search(content):
                imports_found.append(str(py_file.relative_to(rev_dir)))

        self.assertEqual(
            len(imports_found),
            0,
            f"Found handoff_contracts imports in production files: {imports_found}"
        )

    def test_handoff_contracts_test_file_removed(self):
        """The test_handoff_contracts.py file should not exist."""
        test_file = Path(__file__).parent / "test_handoff_contracts.py"
        self.assertFalse(
            test_file.exists(),
            f"test_handoff_contracts.py still exists at {test_file}"
        )


if __name__ == "__main__":
    unittest.main()