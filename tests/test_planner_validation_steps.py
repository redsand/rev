from rev.execution import planner


def test_extract_validation_steps_from_description():
    desc = "Implement feature X. Validation: pytest -q."
    cleaned, steps = planner._extract_validation_steps_from_description(desc, "edit")

    assert cleaned == "Implement feature X"
    assert steps == ["pytest -q"]


def test_extract_validation_steps_from_backticks():
    desc = "Add endpoint, then run `npm test` to validate."
    cleaned, steps = planner._extract_validation_steps_from_description(desc, "add")

    assert "npm test" in steps
    assert "npm test" not in cleaned.lower()


def test_no_validation_extraction_for_test_tasks():
    desc = "Run tests: pytest -q"
    cleaned, steps = planner._extract_validation_steps_from_description(desc, "test")

    assert cleaned == desc
    assert steps == []


def test_ignore_non_test_commands():
    desc = "Implement logging. Validation: dir /b."
    cleaned, steps = planner._extract_validation_steps_from_description(desc, "edit")

    assert cleaned == desc
    assert steps == []
