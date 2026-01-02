"""Test improved code reference detection in file path extraction."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rev.agents.code_writer import _looks_like_code_reference, _extract_target_files_from_description


def test_app_listen_is_code_reference():
    """Test that app.listen is recognized as code reference, not a file."""
    assert _looks_like_code_reference("app.listen") == True, "app.listen should be detected as code reference"
    assert _looks_like_code_reference("app.listen", "wrap the `app.listen` call") == True, "app.listen with context should be code"
    print("[OK] app.listen detected as code reference")


def test_real_files_not_filtered():
    """Test that real file paths are not filtered out."""
    assert _looks_like_code_reference("src/server.ts") == False, "src/server.ts should be a file path"
    assert _looks_like_code_reference("package.json") == False, "package.json should be a file path"
    assert _looks_like_code_reference("tests/api.test.ts") == False, "tests/api.test.ts should be a file path"
    print("[OK] Real file paths not filtered")


def test_common_code_patterns():
    """Test common JavaScript/TypeScript code patterns."""
    # Common methods
    assert _looks_like_code_reference("console.log") == True, "console.log should be code"
    assert _looks_like_code_reference("JSON.parse") == True, "JSON.parse should be code"
    assert _looks_like_code_reference("express.json") == True, "express.json should be code"
    assert _looks_like_code_reference("req.body") == True, "req.body should be code"
    assert _looks_like_code_reference("res.status") == True, "res.status should be code"

    # require.main pattern
    assert _looks_like_code_reference("require.main") == True, "require.main should be code"

    # Config property patterns (from real bug)
    assert _looks_like_code_reference("test.environment") == True, "test.environment should be code"
    assert _looks_like_code_reference("config.timeout") == True, "config.timeout should be code"
    assert _looks_like_code_reference("environment.name") == True, "environment.name should be code"

    print("[OK] Common code patterns detected")


def test_multi_dot_patterns():
    """Test patterns with multiple dots."""
    assert _looks_like_code_reference("api.interceptors.request.use") == True, "Multi-dot should be code"
    assert _looks_like_code_reference("express.json.stringify") == True, "Multi-dot should be code"
    print("[OK] Multi-dot patterns detected as code")


def test_extract_from_description_app_listen():
    """Test extraction from real task description with app.listen."""
    description = "refactor src/server.ts to export the Express `app` instance and wrap the `app.listen` call inside: if (require.main === module) { app.listen(...) }"

    paths = _extract_target_files_from_description(description)

    # Should extract src/server.ts
    assert "src/server.ts" in paths, f"Should extract src/server.ts, got: {paths}"

    # Should NOT extract app.listen
    assert "app.listen" not in paths, f"Should NOT extract app.listen, got: {paths}"

    # Should NOT extract require.main
    assert "require.main" not in paths, f"Should NOT extract require.main, got: {paths}"

    print(f"[OK] Extracted correctly: {paths}")


def test_extract_from_description_backticks():
    """Test extraction with backticked code vs file paths."""
    description = "modify `src/server.ts` to add `app.listen(PORT)` call and export `app` instance"

    paths = _extract_target_files_from_description(description)

    # Should extract src/server.ts
    assert "src/server.ts" in paths, f"Should extract src/server.ts, got: {paths}"

    # Should NOT extract app.listen or app instance
    assert "app.listen" not in paths, f"Should NOT extract app.listen, got: {paths}"

    print(f"[OK] Backticked extraction correct: {paths}")


def test_extract_from_description_mixed():
    """Test extraction with mix of files and code references."""
    description = "edit `src/routes.ts` and `tests/api.test.ts` to use `router.get` and `req.params` with `express.json()` middleware"

    paths = _extract_target_files_from_description(description)

    # Should extract actual files
    assert "src/routes.ts" in paths, f"Should extract src/routes.ts, got: {paths}"
    assert "tests/api.test.ts" in paths, f"Should extract tests/api.test.ts, got: {paths}"

    # Should NOT extract code references
    assert "router.get" not in paths, f"Should NOT extract router.get, got: {paths}"
    assert "req.params" not in paths, f"Should NOT extract req.params, got: {paths}"
    assert "express.json" not in paths, f"Should NOT extract express.json, got: {paths}"

    print(f"[OK] Mixed extraction correct: {paths}")


def test_context_clues():
    """Test that context keywords help identify code references."""
    # "guard" is a context keyword
    assert _looks_like_code_reference("app.listen", "guard the app.listen call") == True

    # "wrap" is a context keyword
    assert _looks_like_code_reference("server.start", "wrap the server.start call") == True

    # "method" is a context keyword
    assert _looks_like_code_reference("obj.method", "invoke the obj.method function") == True

    print("[OK] Context clues work correctly")


def test_edge_cases():
    """Test edge cases."""
    # Empty string
    assert _looks_like_code_reference("") == False

    # No dots
    assert _looks_like_code_reference("server") == False

    # Path with extension that's also a method name
    # This should still be recognized as a file because it has path separator
    assert _looks_like_code_reference("src/listen.ts") == False, "File with method-name extension should be file"

    print("[OK] Edge cases handled")


if __name__ == "__main__":
    test_app_listen_is_code_reference()
    test_real_files_not_filtered()
    test_common_code_patterns()
    test_multi_dot_patterns()
    test_extract_from_description_app_listen()
    test_extract_from_description_backticks()
    test_extract_from_description_mixed()
    test_context_clues()
    test_edge_cases()

    print("\n[OK] All code reference detection tests passed!")
