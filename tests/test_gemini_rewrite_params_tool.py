"""Test Gemini sanitization of the specific rewrite_python_function_parameters tool."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
from rev.llm.providers.gemini_provider import GeminiProvider


def test_rewrite_python_function_parameters_schema():
    """Test the exact schema from registry.py that's causing the Gemini error."""
    provider = GeminiProvider(silent=True)

    # Exact schema from registry.py lines 1360-1391
    tool = {
        "type": "function",
        "function": {
            "name": "rewrite_python_function_parameters",
            "description": "Add/remove/rename function parameters",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to a .py file"},
                    "function": {"type": "string", "description": "Target function name"},
                    "rename": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"old": {"type": "string"}, "new": {"type": "string"}},
                            "required": ["old", "new"]
                        },
                        "default": []
                    },
                    "add": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "default": {"type": "string"}  # Property NAME is "default"
                            },
                            "required": ["name", "default"]  # This was failing!
                        },
                        "default": []  # Schema keyword default value
                    },
                    "remove": {"type": "array", "items": {"type": "string"}, "default": []},
                    "dry_run": {"type": "boolean", "default": False},
                    "engine": {"type": "string", "enum": ["libcst", "auto"], "default": "libcst"}
                },
                "required": ["path", "function"]
            }
        }
    }

    # Convert to Gemini format
    gemini_tools = provider._convert_tools([tool])

    print(f"Converted {len(gemini_tools)} tool group(s)")
    assert len(gemini_tools) == 1
    assert "function_declarations" in gemini_tools[0]

    func_decl = gemini_tools[0]["function_declarations"][0]
    print(f"Function: {func_decl['name']}")

    # Print the full sanitized schema for debugging
    print(f"\nSanitized schema:")
    print(json.dumps(func_decl["parameters"], indent=2))

    # Check the "add" property specifically
    add_prop = func_decl["parameters"]["properties"]["add"]
    print(f"\n'add' property:")
    print(json.dumps(add_prop, indent=2))

    # Verify items schema
    items_schema = add_prop["items"]
    print(f"\nitems schema:")
    print(json.dumps(items_schema, indent=2))

    # Check that items has properties
    assert "properties" in items_schema, "items should have properties"
    assert "name" in items_schema["properties"], "items.properties should have 'name'"
    assert "default" in items_schema["properties"], "items.properties should have 'default' (property name)"

    # Check that required is valid
    assert "required" in items_schema, "items should have required"
    assert set(items_schema["required"]) == {"name", "default"}, \
        f"items.required should be ['name', 'default'], got: {items_schema['required']}"

    # Verify that schema keyword "default" was removed from property-level defaults
    assert "default" not in items_schema["properties"]["name"], \
        "Schema keyword 'default' should be removed from property 'name'"
    assert "default" not in items_schema["properties"]["default"], \
        "Schema keyword 'default' should be removed from property 'default'"

    # Verify that array-level default was removed
    assert "default" not in add_prop, \
        "Schema keyword 'default' should be removed from array 'add'"

    print("\n[OK] rewrite_python_function_parameters schema sanitized correctly")
    print("  - Property name 'default' preserved ✓")
    print("  - Schema keyword 'default' removed ✓")
    print("  - Required fields validated correctly ✓")


if __name__ == "__main__":
    test_rewrite_python_function_parameters_schema()
