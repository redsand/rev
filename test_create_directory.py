#!/usr/bin/env python3
"""Test script to verify create_directory action type works end-to-end."""

import os
import sys
import shutil
from pathlib import Path

# Add rev to path
sys.path.insert(0, os.path.dirname(__file__))

from rev.models.task import Task
from rev.core.context import RevContext
from rev.agents.code_writer import CodeWriterAgent
from rev.core.agent_registry import AgentRegistry

def test_create_directory():
    """Test that create_directory action type works through the full pipeline."""

    test_dir = "./test_create_dir_feature"

    try:
        # Clean up if it exists
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
            print(f"Cleaned up existing test directory: {test_dir}")

        # Verify directory doesn't exist yet
        assert not os.path.exists(test_dir), f"Test directory should not exist yet"
        print(f"✓ Verified test directory does not exist: {test_dir}")

        # Test 1: Verify create_directory is registered in agent registry
        print("\n--- Test 1: Agent Registry ---")
        registered_types = AgentRegistry.get_registered_action_types()
        print(f"Registered action types: {registered_types}")
        assert "create_directory" in registered_types, "create_directory should be registered"
        print("✓ create_directory is registered in AgentRegistry")

        # Test 2: Get the agent for create_directory
        print("\n--- Test 2: Get Agent ---")
        agent = AgentRegistry.get_agent_instance("create_directory")
        print(f"Agent type: {type(agent).__name__}")
        assert isinstance(agent, CodeWriterAgent), "create_directory should map to CodeWriterAgent"
        print("✓ create_directory maps to CodeWriterAgent")

        # Test 3: Create a task with create_directory action type
        print("\n--- Test 3: Create Task ---")
        task = Task(
            description=f"Create directory structure for testing: {test_dir}",
            action_type="create_directory",
        )
        print(f"Task created:")
        print(f"  - Action type: {task.action_type}")
        print(f"  - Description: {task.description}")

        # Test 4: Execute the task
        print("\n--- Test 4: Execute Task ---")
        print("Note: This will require user approval in interactive mode")
        print("For automated testing, you may need to handle this differently\n")

        # Create a context
        context = RevContext(model="test", mode=False)

        # Execute the task through CodeWriterAgent
        agent = CodeWriterAgent()
        try:
            # This will prompt for user approval
            result = agent.execute(task, context)
            print(f"✓ Agent execution completed")
            print(f"  Result: {result}")
        except Exception as e:
            print(f"⚠️  Agent execution raised exception: {e}")
            # For now, we'll continue with the test

        # Check if directory was created
        print("\n--- Test 5: Verify Directory Created ---")
        if os.path.exists(test_dir):
            print(f"✓ Directory successfully created: {test_dir}")
            return True
        else:
            print(f"✗ Directory was NOT created: {test_dir}")
            return False

    finally:
        # Clean up
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
            print(f"\nCleaned up test directory: {test_dir}")

if __name__ == "__main__":
    print("=" * 70)
    print("Testing create_directory Feature")
    print("=" * 70)
    print()

    try:
        success = test_create_directory()
        if success:
            print("\n" + "=" * 70)
            print("✓ All tests passed!")
            print("=" * 70)
            sys.exit(0)
        else:
            print("\n" + "=" * 70)
            print("✗ Tests failed!")
            print("=" * 70)
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ Test error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
