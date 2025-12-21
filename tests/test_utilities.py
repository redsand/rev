"""
Tests for rev.py utility functions.

This test suite covers:
- File format conversion tools (JSON/YAML/CSV/ENV)
- Code refactoring utilities (imports, constants, conditionals)
- Dependency management (analysis, updates)
- Security scanning (vulnerabilities, SAST, secrets, licenses)
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to path to import rev
sys.path.insert(0, str(Path(__file__).parent.parent))

import rev
from rev.config import set_workspace_root


class TestFileConversion:
    """Test file format conversion utilities."""

    def setup_method(self, method):
        """Reset workspace root before each test."""
        set_workspace_root(Path.cwd())

    def test_convert_json_to_yaml(self):
        """Test JSON to YAML conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            json_file = tmpdir_path / "test.json"
            yaml_file = tmpdir_path / "test.yaml"

            # Create test JSON file
            test_data = {"name": "test", "version": "1.0", "features": ["a", "b"]}
            with open(json_file, 'w') as f:
                json.dump(test_data, f)

            # Convert to YAML
            set_workspace_root(tmpdir_path)
            try:
                result = rev.convert_json_to_yaml(str(json_file), str(yaml_file))
                result_data = json.loads(result)

                assert result_data["converted"] == "test.json"
                assert result_data["to"] == "test.yaml"
                assert result_data["format"] == "YAML"
                assert yaml_file.exists()
            finally:
                set_workspace_root(Path(__file__).parent.parent)

            # Verify YAML content
            content = yaml_file.read_text()
            assert "name: test" in content
            assert "version:" in content

    def test_convert_yaml_to_json(self):
        """Test YAML to JSON conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            yaml_file = tmpdir_path / "test.yaml"
            json_file = tmpdir_path / "test.json"

            # Create test YAML file
            yaml_content = """
name: test
version: 1.0
features:
  - a
  - b
"""
            yaml_file.write_text(yaml_content)

            # Convert to JSON
            set_workspace_root(tmpdir_path)
            try:
                result = rev.convert_yaml_to_json(str(yaml_file), str(json_file))
                result_data = json.loads(result)

                assert result_data["converted"] == "test.yaml"
                assert result_data["to"] == "test.json"
                assert result_data["format"] == "JSON"
                assert json_file.exists()
            finally:
                set_workspace_root(Path(__file__).parent.parent)

            # Verify JSON content
            with open(json_file) as f:
                data = json.load(f)
            assert data["name"] == "test"
            assert data["version"] == 1.0

    def test_convert_csv_to_json(self):
        """Test CSV to JSON conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            csv_file = tmpdir_path / "test.csv"
            json_file = tmpdir_path / "test.json"

            # Create test CSV file
            csv_content = "name,age,city\nJohn,30,NYC\nJane,25,LA\n"
            csv_file.write_text(csv_content)

            # Convert to JSON
            set_workspace_root(tmpdir_path)
            try:
                result = rev.convert_csv_to_json(str(csv_file), str(json_file))
                result_data = json.loads(result)

                assert result_data["converted"] == "test.csv"
                assert result_data["to"] == "test.json"
                assert result_data["format"] == "JSON"
                assert json_file.exists()
            finally:
                set_workspace_root(Path(__file__).parent.parent)

            # Verify JSON content
            with open(json_file) as f:
                data = json.load(f)
            assert len(data) == 2
            assert data[0]["name"] == "John"
            assert data[1]["city"] == "LA"

    def test_convert_json_to_csv(self):
        """Test JSON to CSV conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            json_file = tmpdir_path / "test.json"
            csv_file = tmpdir_path / "test.csv"

            # Create test JSON file
            test_data = [
                {"name": "John", "age": 30, "city": "NYC"},
                {"name": "Jane", "age": 25, "city": "LA"}
            ]
            with open(json_file, 'w') as f:
                json.dump(test_data, f)

            # Convert to CSV
            set_workspace_root(tmpdir_path)
            try:
                result = rev.convert_json_to_csv(str(json_file), str(csv_file))
                result_data = json.loads(result)

                assert result_data["converted"] == "test.json"
                assert result_data["to"] == "test.csv"
                assert result_data["format"] == "CSV"
                assert csv_file.exists()
            finally:
                set_workspace_root(Path(__file__).parent.parent)

            # Verify CSV content
            content = csv_file.read_text()
            assert "name,age,city" in content
            assert "John,30,NYC" in content

    def test_convert_env_to_json(self):
        """Test .env to JSON conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            env_file = tmpdir_path / ".env"
            json_file = tmpdir_path / ".env.json"

            # Create test .env file
            env_content = """
# Database config
DB_HOST=localhost
DB_PORT=5432
DB_NAME=mydb

# API settings
API_KEY=secret123
"""
            env_file.write_text(env_content)

            # Convert to JSON
            set_workspace_root(tmpdir_path)
            try:
                result = rev.convert_env_to_json(str(env_file), str(json_file))
                result_data = json.loads(result)

                assert result_data["converted"] == ".env"
                assert result_data["to"] == ".env.json"
                assert result_data["variables"] >= 4
                assert json_file.exists()
            finally:
                set_workspace_root(Path(__file__).parent.parent)


class TestCodeRefactoring:
    """Test code refactoring utilities."""

    def setup_method(self, method):
        """Reset workspace root before each test."""
        set_workspace_root(Path.cwd())

    def test_remove_unused_imports_python(self):
        """Test removing unused imports in Python."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            py_file = tmpdir_path / "test.py"
            code = """
import os
import sys
import json
from pathlib import Path

def main():
    print(os.path.abspath('.'))
"""
            py_file.write_text(code)

            # Mock autoflake execution
            with patch('rev._run_shell') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

                set_workspace_root(tmpdir_path)
                try:
                    result = rev.remove_unused_imports(str(py_file))
                    result_data = json.loads(result)

                    assert result_data["file"] == str(py_file)
                    assert result_data["language"] == "python"
                    assert "autoflake" in result_data["tool"]
                finally:
                    rev.set_workspace_root(Path(__file__).parent.parent)

    def test_extract_constants(self):
        """Test extracting magic numbers and strings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            py_file = tmpdir_path / "test.py"

            # Create test file with magic numbers
            code = """
server = Server(8080)
backup = Server(8080)
fallback = Server(8080)

if retries > 5:
    wait(10)
elif retries > 3:
    wait(5)
"""
            py_file.write_text(code)

            set_workspace_root(tmpdir_path)
            try:
                result = rev.extract_constants(str(py_file), threshold=2)
                result_data = json.loads(result)

                assert result_data["file"] == str(py_file)
                assert "suggestions" in result_data

                # Check for magic number detection
                suggestions = result_data["suggestions"]
                port_suggestion = next((s for s in suggestions if s["value"] == "8080"), None)
                assert port_suggestion is not None
                assert port_suggestion["occurrences"] >= 3
            finally:
                set_workspace_root(Path(__file__).parent.parent)

    def test_simplify_conditionals(self):
        """Test finding complex conditionals."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            py_file = tmpdir_path / "test.py"

            # Create test file with complex conditional
            code = """
def check_access(user):
    if user.age >= 18 and user.verified and (user.role == 'admin' or user.role == 'moderator') and not user.suspended and user.email_confirmed:
        allow_access()

    # Simple conditional
    if user.active:
        log_activity()
"""
            py_file.write_text(code)

            set_workspace_root(tmpdir_path)
            try:
                result = rev.simplify_conditionals(str(py_file))
                result_data = json.loads(result)

                assert result_data["file"] == str(py_file)
                assert "complex_conditionals" in result_data

                # Should find at least one complex conditional
                conditionals = result_data["complex_conditionals"]
                assert len(conditionals) >= 1
                assert conditionals[0]["complexity"] >= 4
            finally:
                set_workspace_root(Path(__file__).parent.parent)


class TestDependencyManagement:
    """Test dependency management utilities."""

    def setup_method(self, method):
        """Reset workspace root before each test."""
        set_workspace_root(Path.cwd())

    def test_analyze_dependencies_python(self):
        """Test analyzing Python dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            requirements = tmpdir_path / "requirements.txt"
            requirements.write_text("""
requests==2.28.0
flask>=2.0.0
pytest
django~=4.0
""")

            set_workspace_root(tmpdir_path)
            try:
                result = rev.analyze_dependencies(language="python")
                result_data = json.loads(result)

                assert result_data["language"] == "python"
                assert result_data["count"] == 4
            finally:
                set_workspace_root(Path(__file__).parent.parent)

    def test_analyze_dependencies_javascript(self):
        """Test analyzing JavaScript dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            pkg_json = tmpdir_path / "package.json"
            pkg_data = {
                "dependencies": {"express": "^4.18.0", "lodash": "4.17.21"},
                "devDependencies": {"jest": "^29.0.0"}
            }
            pkg_json.write_text(json.dumps(pkg_data))

            set_workspace_root(tmpdir_path)
            try:
                result = rev.analyze_dependencies(language="javascript")
                result_data = json.loads(result)

                assert result_data["language"] == "javascript"
                assert result_data["count"] == 3
                assert result_data["file"] == "package.json"
            finally:
                set_workspace_root(Path(__file__).parent.parent)

    def test_analyze_dependencies_auto_detect(self):
        """Test automatic language detection for dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            requirements = tmpdir_path / "requirements.txt"
            requirements.write_text("requests\n")

            set_workspace_root(tmpdir_path)
            try:
                result = rev.analyze_dependencies(language="auto")
                result_data = json.loads(result)

                assert result_data["language"] == "python"
            finally:
                set_workspace_root(Path(__file__).parent.parent)

    def test_update_dependencies_python(self):
        """Test checking Python dependency updates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Create dummy requirements.txt
            (tmpdir_path / "requirements.txt").write_text("requests\n")

            # Mock pip list --outdated output
            mock_output = json.dumps([
                {"name": "requests", "version": "2.28.0", "latest_version": "2.31.0"}
            ])

            with patch('rev._run_shell') as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=mock_output,
                    stderr=""
                )

                set_workspace_root(tmpdir_path)
                try:
                    result = rev.check_dependency_updates(language="python")
                    result_data = json.loads(result)

                    assert result_data["language"] == "python"
                    assert "updates" in result_data
                finally:
                    rev.set_workspace_root(Path(__file__).parent.parent)


class TestSecurityScanning:
    """Test security scanning utilities."""

    def setup_method(self, method):
        """Reset workspace root before each test."""
        set_workspace_root(Path.cwd())

    def test_scan_dependencies_vulnerabilities_python(self):
        """Test scanning Python dependencies for vulnerabilities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Mock pip-audit output
            mock_output = json.dumps([
                {
                    "dependency": {"name": "requests", "version": "2.28.0"},
                    "vulns": [{"id": "CVE-2023-1234", "severity": "HIGH"}]
                }
            ])

            with patch('rev._run_shell') as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=mock_output,
                    stderr=""
                )

                set_workspace_root(tmpdir_path)
                try:
                    result = rev.scan_dependencies_vulnerabilities(language="python")
                    result_data = json.loads(result)

                    assert result_data["language"] == "python"
                    assert "tool" in result_data
                finally:
                    rev.set_workspace_root(Path(__file__).parent.parent)

    def test_scan_code_security(self):
        """Test static code security analysis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Mock bandit output
            mock_output = json.dumps({
                "results": [
                    {
                        "filename": "test.py",
                        "line_number": 10,
                        "issue_text": "Possible SQL injection",
                        "issue_severity": "HIGH",
                        "issue_confidence": "HIGH"
                    }
                ]
            })

            with patch('rev.tools.security._run_shell') as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=mock_output,
                    stderr=""
                )

                set_workspace_root(tmpdir_path)
                try:
                    result = rev.tools.security.scan_security_issues([str(tmpdir_path)])
                    result_data = json.loads(result)

                    assert result_data["scanned"] == str(tmpdir_path)
                    assert "issues" in result_data and "summary" in result_data
                finally:
                    set_workspace_root(Path(__file__).parent.parent)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def setup_method(self, method):
        """Reset workspace root before each test."""
        set_workspace_root(Path.cwd())

    def test_convert_nonexistent_file(self):
        """Test conversion of nonexistent file."""
        result = rev.convert_json_to_yaml("/nonexistent/file.json")
        result_data = json.loads(result)
        assert "error" in result_data

    def test_analyze_dependencies_no_files(self):
        """Test dependency analysis with no dependency files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            set_workspace_root(tmpdir_path)
            try:
                result = rev.analyze_dependencies()
                result_data = json.loads(result)
                assert "error" in result_data or "not found" in result_data.get("message", "")
            finally:
                set_workspace_root(Path(__file__).parent.parent)

    def test_extract_constants_low_threshold(self):
        """Test constant extraction with threshold of 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir) / "test.py"
            py_file.write_text("x = 42\n")

            result = rev.extract_constants(str(py_file), threshold=1)
            result_data = json.loads(result)

            assert result_data["file"] == str(py_file)
            # Should find magic number 42
            suggestions = result_data["suggestions"]
            assert any(s["value"] == "42" for s in suggestions)


class TestToolIntegration:
    """Test integration with external tools."""

    def setup_method(self, method):
        """Reset workspace root before each test."""
        set_workspace_root(Path.cwd())

    def test_missing_tool_graceful_degradation(self):
        """Test graceful handling when external tool is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir) / "test.py"
            py_file.write_text("import os\n")

            # Mock tool not found (returncode 127)
            with patch('rev._run_shell') as mock_run:
                mock_run.return_value = MagicMock(returncode=127, stdout="", stderr="command not found")

                result = rev.remove_unused_imports(str(py_file))
                result_data = json.loads(result)

                # Should return helpful error message
                assert "error" in result_data or "not installed" in str(result_data)

    def test_security_tool_fallback(self):
        """Test fallback when primary security tool fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Mock safety failing, should try pip-audit
            with patch('rev._run_shell') as mock_run:
                # First call (safety) fails, second call (pip-audit) succeeds
                mock_run.side_effect = [
                    MagicMock(returncode=127, stdout="", stderr="not found"),
                    MagicMock(returncode=0, stdout=json.dumps([]), stderr="")
                ]

                set_workspace_root(tmpdir_path)
                try:
                    requirements = tmpdir_path / "requirements.txt"
                    requirements.write_text("requests==2.28.0\n")

                    result = rev.scan_dependencies_vulnerabilities(language="python")
                    result_data = json.loads(result)

                    # Should have attempted fallback
                    assert "language" in result_data
                finally:
                    rev.set_workspace_root(Path(__file__).parent.parent)


if __name__ == "__main__":
    # Run tests with basic test runner
    import unittest

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestFileConversion))
    suite.addTests(loader.loadTestsFromTestCase(TestCodeRefactoring))
    suite.addTests(loader.loadTestsFromTestCase(TestDependencyManagement))
    suite.addTests(loader.loadTestsFromTestCase(TestSecurityScanning))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestToolIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
