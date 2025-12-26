"""
Tests for _extract_target_files_from_description function.

This function was failing to extract .prisma files, causing both gpt-oss
and qwen3-coder to fail with "EDIT task must specify target file path"
even when the path was clearly in the description.

Issue: Task "backend/prisma/schema.prisma to add password field" was not
recognizing backend/prisma/schema.prisma as a file path because .prisma
was not in the hardcoded extension list.

Fix: Simplified to accept ANY extension instead of hardcoding a list.
"""

import pytest
from rev.agents.code_writer import _extract_target_files_from_description


class TestFilePathExtraction:
    """Test that file paths are correctly extracted from task descriptions."""

    def test_extracts_prisma_files(self):
        """Test that .prisma files are extracted (the root cause issue)."""
        description = "backend/prisma/schema.prisma to add password field to the User model"
        paths = _extract_target_files_from_description(description)

        assert "backend/prisma/schema.prisma" in paths
        assert len(paths) == 1

    def test_extracts_vue_files(self):
        """Test that .vue files are extracted."""
        description = "edit frontend/src/components/Login.vue to add validation"
        paths = _extract_target_files_from_description(description)

        assert "frontend/src/components/Login.vue" in paths

    def test_extracts_tsx_files(self):
        """Test that .tsx files are extracted."""
        description = "update src/components/Button.tsx with new props"
        paths = _extract_target_files_from_description(description)

        assert "src/components/Button.tsx" in paths

    def test_extracts_jsx_files(self):
        """Test that .jsx files are extracted."""
        description = "modify App.jsx to include new route"
        paths = _extract_target_files_from_description(description)

        assert "App.jsx" in paths

    def test_extracts_graphql_files(self):
        """Test that .graphql files are extracted."""
        description = "edit schema.graphql to add new User type"
        paths = _extract_target_files_from_description(description)

        assert "schema.graphql" in paths

    def test_extracts_backticked_paths(self):
        """Test that backticked paths are extracted."""
        description = "update `src/utils/helper.ts` with new function"
        paths = _extract_target_files_from_description(description)

        assert "src/utils/helper.ts" in paths

    def test_extracts_quoted_paths(self):
        """Test that quoted paths are extracted."""
        description = 'edit "config/database.yml" to update connection string'
        paths = _extract_target_files_from_description(description)

        assert "config/database.yml" in paths

    def test_extracts_multiple_files(self):
        """Test that multiple files in one description are all extracted."""
        description = "update app.js and config.json and schema.prisma with new settings"
        paths = _extract_target_files_from_description(description)

        assert "app.js" in paths
        assert "config.json" in paths
        assert "schema.prisma" in paths
        assert len(paths) == 3

    def test_extracts_files_with_hyphens(self):
        """Test that filenames with hyphens are extracted."""
        description = "edit my-component.vue to add new feature"
        paths = _extract_target_files_from_description(description)

        assert "my-component.vue" in paths

    def test_filters_out_extensions_only(self):
        """Test that bare extensions like '.js' are not extracted."""
        description = "add .js files to the project"
        paths = _extract_target_files_from_description(description)

        # Should not extract ".js" as a file
        assert ".js" not in paths

    def test_extracts_common_python_files(self):
        """Test that common Python file patterns still work."""
        description = "edit src/module/__init__.py to add imports"
        paths = _extract_target_files_from_description(description)

        assert "src/module/__init__.py" in paths

    def test_extracts_common_js_files(self):
        """Test that common JS file patterns still work."""
        description = "update package.json to add dependency"
        paths = _extract_target_files_from_description(description)

        assert "package.json" in paths

    def test_extracts_paths_at_start_of_description(self):
        """Test extraction when path is at the very start (qwen3 failure case)."""
        description = "backend/prisma/schema.prisma to add password field"
        paths = _extract_target_files_from_description(description)

        assert "backend/prisma/schema.prisma" in paths

    def test_extracts_paths_with_windows_backslashes(self):
        """Test that Windows-style paths are extracted."""
        description = r"edit backend\\prisma\\schema.prisma to add field"
        paths = _extract_target_files_from_description(description)

        assert r"backend\\prisma\\schema.prisma" in paths or "backend/prisma/schema.prisma" in paths

    def test_empty_description_returns_empty_list(self):
        """Test that empty description returns empty list."""
        assert _extract_target_files_from_description("") == []
        assert _extract_target_files_from_description(None) == []


class TestRealWorldTaskDescriptions:
    """Test with actual task descriptions from failed runs."""

    def test_gpt_oss_failure_case(self):
        """Test the exact description from gpt-oss log that failed."""
        # From line 549 of rev_run_20251225_143204.log
        description = "backend/prisma/schema.prisma to add password field to the User model and ensure it supports login and CRUD operations."
        paths = _extract_target_files_from_description(description)

        assert "backend/prisma/schema.prisma" in paths
        assert len(paths) >= 1

    def test_qwen3_failure_case(self):
        """Test the exact description from qwen3 log that failed."""
        # Similar pattern from qwen3 log
        description = "add password field to the User model in backend/prisma/schema.prisma to support login and CRUD operations"
        paths = _extract_target_files_from_description(description)

        assert "backend/prisma/schema.prisma" in paths


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
