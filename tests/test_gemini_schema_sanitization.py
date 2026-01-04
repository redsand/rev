"""Test Gemini schema sanitization."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rev.llm.providers.gemini_provider import GeminiProvider


def test_sanitize_removes_unsupported_keywords():
    """Test that unsupported keywords are removed."""
    provider = GeminiProvider(silent=True)

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "default": "test"},
            "value": {"type": "number"}
        },
        "required": ["name"],
        "oneOf": [{"required": ["name"]}, {"required": ["value"]}]
    }

    sanitized = provider._sanitize_schema(schema)

    assert "default" not in sanitized["properties"]["name"], "Should remove default"
    assert "oneOf" not in sanitized, "Should remove oneOf"
    assert "required" in sanitized, "Should keep valid required"
    assert sanitized["required"] == ["name"], "Should keep valid required field"

    print("[OK] Removes unsupported keywords")


def test_sanitize_invalid_required_fields():
    """Test that invalid required fields are filtered out."""
    provider = GeminiProvider(silent=True)

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "number"}
        },
        "required": ["name", "missing_field", "age"]
    }

    sanitized = provider._sanitize_schema(schema)

    assert "required" in sanitized
    assert "missing_field" not in sanitized["required"], "Should remove invalid required field"
    assert set(sanitized["required"]) == {"name", "age"}, "Should keep only valid required fields"

    print("[OK] Filters invalid required fields")


def test_sanitize_nested_array_items():
    """Test sanitization of nested array items with required fields."""
    provider = GeminiProvider(silent=True)

    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"}
                    },
                    "required": ["id", "name", "missing"]  # missing doesn't exist
                }
            }
        },
        "required": ["items"]
    }

    sanitized = provider._sanitize_schema(schema)

    # Check that nested items schema is sanitized
    items_schema = sanitized["properties"]["items"]["items"]
    assert "required" in items_schema
    assert "missing" not in items_schema["required"], "Should remove invalid nested required field"
    assert set(items_schema["required"]) == {"id", "name"}, f"Should keep only valid nested required fields, got: {items_schema['required']}"

    print("[OK] Sanitizes nested array items")


def test_sanitize_deeply_nested_schemas():
    """Test sanitization of deeply nested schemas."""
    provider = GeminiProvider(silent=True)

    schema = {
        "type": "object",
        "properties": {
            "data": {
                "type": "object",
                "properties": {
                    "users": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "profile": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "email": {"type": "string"}
                                    },
                                    "required": ["name", "email", "nonexistent"]
                                }
                            },
                            "required": ["id", "profile", "invalid"]
                        }
                    }
                },
                "required": ["users"]
            }
        }
    }

    sanitized = provider._sanitize_schema(schema)

    # Check deeply nested required fields
    user_schema = sanitized["properties"]["data"]["properties"]["users"]["items"]
    assert set(user_schema["required"]) == {"id", "profile"}, "Should remove invalid required in nested array items"

    profile_schema = user_schema["properties"]["profile"]
    assert set(profile_schema["required"]) == {"name", "email"}, "Should remove invalid required in deeply nested object"

    print("[OK] Sanitizes deeply nested schemas")


def test_sanitize_array_without_object_items():
    """Test sanitization of arrays with primitive items (no required)."""
    provider = GeminiProvider(silent=True)

    schema = {
        "type": "object",
        "properties": {
            "tags": {
                "type": "array",
                "items": {"type": "string"}  # Primitive, no required
            }
        },
        "required": ["tags"]
    }

    sanitized = provider._sanitize_schema(schema)

    # Should pass through unchanged (no required to sanitize in items)
    assert "required" in sanitized
    assert sanitized["required"] == ["tags"]
    assert sanitized["properties"]["tags"]["items"]["type"] == "string"

    print("[OK] Handles arrays with primitive items")


def test_empty_required_is_removed():
    """Test that empty required arrays are removed."""
    provider = GeminiProvider(silent=True)

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"}
        },
        "required": ["invalid1", "invalid2"]  # All invalid
    }

    sanitized = provider._sanitize_schema(schema)

    # Empty required array should not be included
    assert "required" not in sanitized, "Should remove empty required array"

    print("[OK] Removes empty required arrays")


def test_tool_conversion():
    """Test full tool conversion with problematic schemas."""
    provider = GeminiProvider(silent=True)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "add_items",
                "description": "Add items to a list",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "value": {"type": "number"}
                                },
                                "required": ["id", "value", "missing"]  # This will cause Gemini error
                            }
                        }
                    },
                    "required": ["items"]
                }
            }
        }
    ]

    gemini_tools = provider._convert_tools(tools)

    assert len(gemini_tools) == 1
    assert "function_declarations" in gemini_tools[0]
    assert len(gemini_tools[0]["function_declarations"]) == 1

    func_decl = gemini_tools[0]["function_declarations"][0]
    items_schema = func_decl["parameters"]["properties"]["items"]["items"]

    # Check that invalid required field was removed
    assert "required" in items_schema
    assert "missing" not in items_schema["required"]
    assert set(items_schema["required"]) == {"id", "value"}

    print("[OK] Full tool conversion sanitizes schemas")


if __name__ == "__main__":
    test_sanitize_removes_unsupported_keywords()
    test_sanitize_invalid_required_fields()
    test_sanitize_nested_array_items()
    test_sanitize_deeply_nested_schemas()
    test_sanitize_array_without_object_items()
    test_empty_required_is_removed()
    test_tool_conversion()

    print("\n[OK] All Gemini schema sanitization tests passed!")
