#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Typed Agent Handoff Contracts.

Handoff contracts define the interface between agents, ensuring type-safe
communication and validating that agents produce/consume the expected data.
"""

import unittest
from unittest.mock import Mock
from typing import Dict, List, Any


class TestContractDefinitions(unittest.TestCase):
    """Test defining agent handoff contracts."""

    def test_define_simple_contract(self):
        """Should define a simple handoff contract."""
        from rev.handoff_contracts.definitions import HandoffContract

        contract = HandoffContract(
            name="research_to_writer",
            input_schema={
                "type": "object",
                "properties": {
                    "findings": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                },
                "required": ["findings"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "files_modified": {"type": "array"}
                },
                "required": ["code"]
            }
        )

        self.assertEqual(contract.name, "research_to_writer")
        self.assertIn("findings", contract.input_schema["properties"])

    def test_contract_with_optional_fields(self):
        """Contract should support optional fields."""
        from rev.handoff_contracts.definitions import HandoffContract

        contract = HandoffContract(
            name="test_contract",
            input_schema={
                "type": "object",
                "properties": {
                    "required_field": {"type": "string"},
                    "optional_field": {"type": "string"}
                },
                "required": ["required_field"]
            }
        )

        # Only required_field should be in required list
        self.assertIn("required_field", contract.input_schema["required"])
        self.assertNotIn("optional_field", contract.input_schema.get("required", []))

    def test_contract_with_nested_objects(self):
        """Contract should support nested object schemas."""
        from rev.handoff_contracts.definitions import HandoffContract

        contract = HandoffContract(
            name="complex_contract",
            input_schema={
                "type": "object",
                "properties": {
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string"},
                            "priority": {"type": "integer"}
                        }
                    }
                }
            }
        )

        # Should have nested structure
        self.assertIn("metadata", contract.input_schema["properties"])
        self.assertEqual(contract.input_schema["properties"]["metadata"]["type"], "object")


class TestContractValidation(unittest.TestCase):
    """Test validating data against contracts."""

    def test_validate_valid_data(self):
        """Validator should accept data that matches contract."""
        from rev.handoff_contracts.validation import validate_handoff
        from rev.handoff_contracts.definitions import HandoffContract

        contract = HandoffContract(
            name="test",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "count": {"type": "integer"}
                },
                "required": ["message"]
            }
        )

        data = {
            "message": "Hello",
            "count": 5
        }

        result = validate_handoff(data, contract.input_schema)

        self.assertTrue(result["valid"])
        self.assertEqual(len(result.get("errors", [])), 0)

    def test_validate_missing_required_field(self):
        """Validator should reject data missing required fields."""
        from rev.handoff_contracts.validation import validate_handoff
        from rev.handoff_contracts.definitions import HandoffContract

        contract = HandoffContract(
            name="test",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"}
                },
                "required": ["message"]
            }
        )

        data = {}  # Missing required 'message'

        result = validate_handoff(data, contract.input_schema)

        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)
        self.assertTrue(any("message" in str(err).lower() for err in result["errors"]))

    def test_validate_wrong_type(self):
        """Validator should reject data with wrong types."""
        from rev.handoff_contracts.validation import validate_handoff
        from rev.handoff_contracts.definitions import HandoffContract

        contract = HandoffContract(
            name="test",
            input_schema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer"}
                }
            }
        )

        data = {"count": "not a number"}  # Wrong type

        result = validate_handoff(data, contract.input_schema)

        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)

    def test_validate_array_items(self):
        """Validator should validate array item types."""
        from rev.handoff_contracts.validation import validate_handoff
        from rev.handoff_contracts.definitions import HandoffContract

        contract = HandoffContract(
            name="test",
            input_schema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            }
        )

        # Valid array
        valid_data = {"items": ["a", "b", "c"]}
        result = validate_handoff(valid_data, contract.input_schema)
        self.assertTrue(result["valid"])

        # Invalid array (contains non-string)
        invalid_data = {"items": ["a", 123, "c"]}
        result = validate_handoff(invalid_data, contract.input_schema)
        self.assertFalse(result["valid"])


class TestAgentHandoff(unittest.TestCase):
    """Test agent-to-agent handoffs with contracts."""

    def test_handoff_from_research_to_writer(self):
        """Test handoff from ResearchAgent to CodeWriterAgent."""
        from rev.handoff_contracts.handoff import execute_handoff
        from rev.handoff_contracts.definitions import HandoffContract

        contract = HandoffContract(
            name="research_to_writer",
            input_schema={
                "type": "object",
                "properties": {
                    "findings": {"type": "array"},
                    "files_to_modify": {"type": "array"}
                },
                "required": ["findings"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "code_written": {"type": "boolean"}
                }
            }
        )

        # Research agent output
        research_output = {
            "findings": ["Bug is in line 42", "Need to add null check"],
            "files_to_modify": ["main.py"]
        }

        # Mock writer agent
        writer_agent = Mock()
        writer_agent.process.return_value = {"code_written": True}

        result = execute_handoff(
            contract=contract,
            source_data=research_output,
            target_agent=writer_agent
        )

        self.assertTrue(result["success"])
        self.assertIn("output", result)
        writer_agent.process.assert_called_once()

    def test_handoff_validates_source_data(self):
        """Handoff should validate source data before passing to target."""
        from rev.handoff_contracts.handoff import execute_handoff
        from rev.handoff_contracts.definitions import HandoffContract

        contract = HandoffContract(
            name="test",
            input_schema={
                "type": "object",
                "properties": {"data": {"type": "string"}},
                "required": ["data"]
            }
        )

        # Invalid source data (missing required field)
        invalid_data = {}

        target_agent = Mock()

        result = execute_handoff(
            contract=contract,
            source_data=invalid_data,
            target_agent=target_agent
        )

        self.assertFalse(result["success"])
        self.assertIn("validation_errors", result)
        # Target agent should NOT be called with invalid data
        target_agent.process.assert_not_called()

    def test_handoff_validates_target_output(self):
        """Handoff should validate target agent output against contract."""
        from rev.handoff_contracts.handoff import execute_handoff
        from rev.handoff_contracts.definitions import HandoffContract

        contract = HandoffContract(
            name="test",
            input_schema={
                "type": "object",
                "properties": {"input": {"type": "string"}}
            },
            output_schema={
                "type": "object",
                "properties": {"output": {"type": "integer"}},
                "required": ["output"]
            }
        )

        source_data = {"input": "test"}

        # Target returns invalid output
        target_agent = Mock()
        target_agent.process.return_value = {"output": "not an integer"}

        result = execute_handoff(
            contract=contract,
            source_data=source_data,
            target_agent=target_agent
        )

        # Handoff succeeded but output validation failed
        self.assertIn("output_validation_errors", result)


class TestContractRegistry(unittest.TestCase):
    """Test registry for managing contracts."""

    def test_register_contract(self):
        """Should register a contract in the registry."""
        from rev.handoff_contracts.registry import ContractRegistry
        from rev.handoff_contracts.definitions import HandoffContract

        registry = ContractRegistry()

        contract = HandoffContract(
            name="test_contract",
            input_schema={"type": "object"}
        )

        registry.register(contract)

        # Should be retrievable
        retrieved = registry.get("test_contract")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "test_contract")

    def test_list_all_contracts(self):
        """Should list all registered contracts."""
        from rev.handoff_contracts.registry import ContractRegistry
        from rev.handoff_contracts.definitions import HandoffContract

        registry = ContractRegistry()

        registry.register(HandoffContract(name="contract1", input_schema={}))
        registry.register(HandoffContract(name="contract2", input_schema={}))

        all_contracts = registry.list_all()

        self.assertEqual(len(all_contracts), 2)
        self.assertIn("contract1", [c.name for c in all_contracts])
        self.assertIn("contract2", [c.name for c in all_contracts])

    def test_get_contracts_for_agent(self):
        """Should retrieve contracts relevant to a specific agent."""
        from rev.handoff_contracts.registry import ContractRegistry
        from rev.handoff_contracts.definitions import HandoffContract

        registry = ContractRegistry()

        # Register contracts with source/target agents
        research_to_writer = HandoffContract(
            name="research_to_writer",
            input_schema={},
            metadata={"source_agent": "ResearchAgent", "target_agent": "CodeWriterAgent"}
        )

        registry.register(research_to_writer)

        # Get contracts for CodeWriterAgent
        contracts = registry.get_contracts_for_agent("CodeWriterAgent")

        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0].name, "research_to_writer")


class TestContractEvolution(unittest.TestCase):
    """Test contract versioning and evolution."""

    def test_contract_versioning(self):
        """Contracts should support versioning."""
        from rev.handoff_contracts.definitions import HandoffContract

        contract_v1 = HandoffContract(
            name="test_contract",
            version="1.0",
            input_schema={"type": "object", "properties": {"field1": {"type": "string"}}}
        )

        contract_v2 = HandoffContract(
            name="test_contract",
            version="2.0",
            input_schema={
                "type": "object",
                "properties": {
                    "field1": {"type": "string"},
                    "field2": {"type": "integer"}  # New field in v2
                }
            }
        )

        self.assertEqual(contract_v1.version, "1.0")
        self.assertEqual(contract_v2.version, "2.0")

    def test_backward_compatibility_check(self):
        """Should check if new contract version is backward compatible."""
        from rev.handoff_contracts.evolution import is_backward_compatible
        from rev.handoff_contracts.definitions import HandoffContract

        old_contract = HandoffContract(
            name="test",
            input_schema={
                "type": "object",
                "properties": {"field1": {"type": "string"}},
                "required": ["field1"]
            }
        )

        # Compatible: adds optional field
        new_contract_compatible = HandoffContract(
            name="test",
            input_schema={
                "type": "object",
                "properties": {
                    "field1": {"type": "string"},
                    "field2": {"type": "integer"}  # Optional
                },
                "required": ["field1"]
            }
        )

        # Incompatible: adds required field
        new_contract_incompatible = HandoffContract(
            name="test",
            input_schema={
                "type": "object",
                "properties": {
                    "field1": {"type": "string"},
                    "field2": {"type": "integer"}
                },
                "required": ["field1", "field2"]  # field2 now required!
            }
        )

        self.assertTrue(is_backward_compatible(old_contract, new_contract_compatible))
        self.assertFalse(is_backward_compatible(old_contract, new_contract_incompatible))


if __name__ == "__main__":
    unittest.main()
