import json
from types import SimpleNamespace

import rev.tools.dependencies as deps


def test_check_dependency_updates_python(monkeypatch):
    fake_outdated = json.dumps([
        {"name": "foo", "version": "1.0.0", "latest_version": "2.0.0"},
        {"name": "bar", "version": "1.0.0", "latest_version": "1.1.0"},
    ])

    def fake_run(cmd, timeout=120):
        return SimpleNamespace(returncode=0, stdout=fake_outdated, stderr="")

    monkeypatch.setattr(deps, "_run_shell", fake_run)

    result = json.loads(deps.check_dependency_updates("python"))
    assert result["updates"]["breaking"][0]["package"] == "foo"
    assert result["updates"]["minor"][0]["package"] == "bar"


def test_check_dependency_vulnerabilities_python(monkeypatch):
    pip_audit_output = json.dumps([
        {
            "dependency": {"name": "foo", "version": "1.0.0"},
            "vulns": [
                {
                    "id": "CVE-123",
                    "severity": "HIGH",
                    "fix_versions": ["1.2.0"],
                    "description": "Test vuln",
                }
            ],
        }
    ])

    def fake_run(cmd, timeout=180):
        return SimpleNamespace(returncode=0, stdout=pip_audit_output, stderr="")

    monkeypatch.setattr(deps, "_run_shell", fake_run)

    result = json.loads(deps.check_dependency_vulnerabilities("python"))
    assert result["issues"][0]["package"] == "foo"
    assert result["issues"][0]["fixed_version"] == "1.2.0"
