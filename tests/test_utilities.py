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


class TestFileConversion:
    """Test file format conversion utilities."""

    def test_convert_json_to_yaml(self):
        """Test JSON to YAML conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = Path(tmpdir) / "test.json"
            yaml_file = Path(tmpdir) / "test.yaml"

            # Create test JSON file
            test_data = {"name": "test", "version": "1.0", "features": ["a", "b"]}
            with open(json_file, 'w') as f:
                json.dump(test_data, f)

            # Convert to YAML
            result = rev.convert_json_to_yaml(str(json_file), str(yaml_file))
            result_data = json.loads(result)

            assert result_data["converted"] == str(json_file)
            assert result_data["to"] == str(yaml_file)
            assert result_data["format"] == "YAML"
            assert yaml_file.exists()

            # Verify YAML content
            content = yaml_file.read_text()
            assert "name: test" in content
            assert "version:" in content

    def test_convert_yaml_to_json(self):
        """Test YAML to JSON conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            json_file = Path(tmpdir) / "test.json"

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
            result = rev.convert_yaml_to_json(str(yaml_file), str(json_file))
            result_data = json.loads(result)

            assert result_data["converted"] == str(yaml_file)
            assert result_data["to"] == str(json_file)
            assert result_data["format"] == "JSON"
            assert json_file.exists()

            # Verify JSON content
            with open(json_file) as f:
                data = json.load(f)
            assert data["name"] == "test"
            assert data["version"] == 1.0

    def test_convert_csv_to_json(self):
        """Test CSV to JSON conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_file = Path(tmpdir) / "test.csv"
            json_file = Path(tmpdir) / "test.json"

            # Create test CSV file
            csv_content = "name,age,city\nJohn,30,NYC\nJane,25,LA\n"
            csv_file.write_text(csv_content)

            # Convert to JSON
            result = rev.convert_csv_to_json(str(csv_file), str(json_file))
            result_data = json.loads(result)

            assert result_data["converted"] == str(csv_file)
            assert result_data["to"] == str(json_file)
            assert result_data["format"] == "JSON"
            assert json_file.exists()

            # Verify JSON content
            with open(json_file) as f:
                data = json.load(f)
            assert len(data) == 2
            assert data[0]["name"] == "John"
            assert data[1]["city"] == "LA"

    def test_convert_json_to_csv(self):
        """Test JSON to CSV conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = Path(tmpdir) / "test.json"
            csv_file = Path(tmpdir) / "test.csv"

            # Create test JSON file
            test_data = [
                {"name": "John", "age": 30, "city": "NYC"},
                {"name": "Jane", "age": 25, "city": "LA"}
            ]
            with open(json_file, 'w') as f:
                json.dump(test_data, f)

            # Convert to CSV
            result = rev.convert_json_to_csv(str(json_file), str(csv_file))
            result_data = json.loads(result)

            assert result_data["converted"] == str(json_file)
            assert result_data["to"] == str(csv_file)
            assert result_data["format"] == "CSV"
            assert csv_file.exists()

            # Verify CSV content
            content = csv_file.read_text()
            assert "name,age,city" in content
            assert "John,30,NYC" in content

    def test_convert_env_to_json(self):
        """Test .env to JSON conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            json_file = Path(tmpdir) / ".env.json"

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
            result = rev.convert_env_to_json(str(env_file), str(json_file))
            result_data = json.loads(result)

            assert result_data["converted"] == str(env_file)
            assert result_data["to"] == str(json_file)
            assert result_data["format"] == "JSON"
            assert json_file.exists()

            # Verify JSON content
            with open(json_file) as f:
                data = json.load(f)
            assert data["DB_HOST"] == "localhost"
            assert data["DB_PORT"] == "5432"
            assert data["API_KEY"] == "secret123"


class TestCodeRefactoring:
    """Test code refactoring utilities."""

    def test_remove_unused_imports_python(self):
        """Test removing unused imports from Python file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir) / "test.py"

            # Create test Python file with unused imports
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

                result = rev.remove_unused_imports(str(py_file))
                result_data = json.loads(result)

                assert result_data["file"] == str(py_file)
                assert result_data["language"] == "python"
                assert "autoflake" in result_data["tool"]

    def test_extract_constants(self):
        """Test extracting magic numbers and strings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir) / "test.py"

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

            result = rev.extract_constants(str(py_file), threshold=2)
            result_data = json.loads(result)

            assert result_data["file"] == str(py_file)
            assert "suggestions" in result_data

            # Check for magic number detection
            suggestions = result_data["suggestions"]
            port_suggestion = next((s for s in suggestions if s["value"] == "8080"), None)
            assert port_suggestion is not None
            assert port_suggestion["occurrences"] >= 3

    def test_simplify_conditionals(self):
        """Test finding complex conditionals."""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir) / "test.py"

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

            result = rev.simplify_conditionals(str(py_file))
            result_data = json.loads(result)

            assert result_data["file"] == str(py_file)
            assert "complex_conditionals" in result_data

            # Should find at least one complex conditional
            conditionals = result_data["complex_conditionals"]
            assert len(conditionals) >= 1
            assert conditionals[0]["complexity"] >= 4


class TestDependencyManagement:
    """Test dependency management utilities."""

    def test_analyze_dependencies_python(self):
        """Test analyzing Python dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements = Path(tmpdir) / "requirements.txt"
            requirements.write_text("""
requests==2.28.0
flask>=2.0.0
pytest
django~=4.0
""")

            with patch('rev.ROOT', Path(tmpdir)):
                result = rev.analyze_dependencies(language="python")
                result_data = json.loads(result)

                assert result_data["language"] == "python"
                assert result_data["file"] == "requirements.txt"
                assert result_data["count"] == 4

                # Check for unpinned versions
                issues = result_data.get("issues", [])
                unpinned_issue = next((i for i in issues if i["type"] == "unpinned_versions"), None)
                assert unpinned_issue is not None

    def test_analyze_dependencies_javascript(self):
        """Test analyzing JavaScript dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            package_json = Path(tmpdir) / "package.json"
            package_json.write_text(json.dumps({
                "dependencies": {
                    "express": "^4.18.0",
                    "lodash": "~4.17.0"
                },
                "devDependencies": {
                    "jest": "^29.0.0"
                }
            }))

            with patch('rev.ROOT', Path(tmpdir)):
                result = rev.analyze_dependencies(language="javascript")
                result_data = json.loads(result)

                assert result_data["language"] == "javascript"
                assert result_data["file"] == "package.json"
                assert result_data["count"] == 3

    def test_analyze_dependencies_auto_detect(self):
        """Test automatic language detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements = Path(tmpdir) / "requirements.txt"
            requirements.write_text("requests==2.28.0\n")

            with patch('rev.ROOT', Path(tmpdir)):
                result = rev.analyze_dependencies(language="auto")
                result_data = json.loads(result)

                assert result_data["language"] == "python"

    def test_update_dependencies_python(self):
        """Test checking for outdated Python dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements = Path(tmpdir) / "requirements.txt"
            requirements.write_text("requests==2.28.0\n")

            # Mock pip list --outdated
            mock_output = json.dumps([
                {
                    "name": "requests",
                    "version": "2.28.0",
                    "latest_version": "2.31.0",
                    "latest_filetype": "wheel"
                }
            ])

            with patch('rev.ROOT', Path(tmpdir)):
                with patch('rev._run_shell') as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0,
                        stdout=mock_output,
                        stderr=""
                    )

                    result = rev.update_dependencies(language="python")
                    result_data = json.loads(result)

                    assert result_data["language"] == "python"
                    assert "outdated" in result_data


class TestSecurityScanning:
    """Test security scanning utilities."""

    def test_scan_dependencies_vulnerabilities_python(self):
        """Test scanning Python dependencies for vulnerabilities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements = Path(tmpdir) / "requirements.txt"
            requirements.write_text("requests==2.28.0\n")

            # Mock safety output
            mock_output = json.dumps([
                [
                    "requests",
                    "<2.31.0",
                    "2.28.0",
                    "CVE-2023-xxxxx High severity",
                    "12345"
                ]
            ])

            with patch('rev.ROOT', Path(tmpdir)):
                with patch('rev._run_shell') as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0,
                        stdout=mock_output,
                        stderr=""
                    )

                    result = rev.scan_dependencies_vulnerabilities(language="python")
                    result_data = json.loads(result)

                    assert result_data["language"] == "python"
                    assert "tool" in result_data

    def test_scan_code_security(self):
        """Test static code security analysis."""
        with tempfile.TemporaryDirectory() as tmpdir:
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

            with patch('rev._run_shell') as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=mock_output,
                    stderr=""
                )

                result = rev.scan_code_security(str(tmpdir))
                result_data = json.loads(result)

                assert result_data["scanned"] == str(tmpdir)
                assert "findings" in result_data or "tools" in result_data

    def test_detect_secrets(self):
        """Test secret detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock detect-secrets output
            mock_output = json.dumps({
                "results": {
                    "test.py": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 5
                        }
                    ]
                }
            })

            with patch('rev._run_shell') as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=mock_output,
                    stderr=""
                )

                result = rev.detect_secrets(str(tmpdir))
                result_data = json.loads(result)

                assert result_data["scanned"] == str(tmpdir)
                assert "tool" in result_data

    def test_check_license_compliance_python(self):
        """Test license compliance checking for Python."""
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements = Path(tmpdir) / "requirements.txt"
            requirements.write_text("requests==2.28.0\n")

            # Mock pip-licenses output
            mock_output = json.dumps([
                {
                    "Name": "requests",
                    "Version": "2.28.0",
                    "License": "Apache 2.0"
                },
                {
                    "Name": "some-lib",
                    "Version": "1.0.0",
                    "License": "GPL-3.0"
                }
            ])

            with patch('rev.ROOT', Path(tmpdir)):
                with patch('rev._run_shell') as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0,
                        stdout=mock_output,
                        stderr=""
                    )

                    result = rev.check_license_compliance(str(tmpdir))
                    result_data = json.loads(result)

                    assert result_data["language"] == "python"
                    assert "compliance_issues" in result_data

                    # Should flag GPL-3.0
                    issues = result_data["compliance_issues"]
                    gpl_issue = next((i for i in issues if "GPL" in i.get("license", "")), None)
                    assert gpl_issue is not None


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_convert_nonexistent_file(self):
        """Test conversion of nonexistent file."""
        result = rev.convert_json_to_yaml("/nonexistent/file.json")
        result_data = json.loads(result)
        assert "error" in result_data

    def test_analyze_dependencies_no_files(self):
        """Test dependency analysis with no dependency files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('rev.ROOT', Path(tmpdir)):
                result = rev.analyze_dependencies()
                result_data = json.loads(result)
                assert "error" in result_data or "not found" in result_data.get("message", "")

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
            # Mock safety failing, should try pip-audit
            with patch('rev._run_shell') as mock_run:
                # First call (safety) fails, second call (pip-audit) succeeds
                mock_run.side_effect = [
                    MagicMock(returncode=127, stdout="", stderr="not found"),
                    MagicMock(returncode=0, stdout=json.dumps([]), stderr="")
                ]

                with patch('rev.ROOT', Path(tmpdir)):
                    requirements = Path(tmpdir) / "requirements.txt"
                    requirements.write_text("requests==2.28.0\n")

                    result = rev.scan_dependencies_vulnerabilities(language="python")
                    result_data = json.loads(result)

                    # Should have attempted fallback
                    assert "language" in result_data


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
