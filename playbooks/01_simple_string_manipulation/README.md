# Playbook 01: Simple - String Manipulation

## Level: Simple

## Goal
Add utility functions to manipulate and analyze strings for a CLI tool.

## Initial State
- Basic Python package structure
- Empty `string_utils.py` module
- Tests that will pass after implementation

## Task
Implement the following functions in `string_utils.py`:

1. `reverse_string(s: str) -> str` - Return the reversed string
2. `count_vowels(s: str) -> int` - Count vowels (a, e, i, o, u) case-insensitively
3. `is_palindrome(s: str) -> bool` - Check if string reads the same forwards and backwards (ignoring case and spaces)
4. `capitalize_words(s: str) -> str` - Capitalize the first letter of each word

## Constraints
- All functions must handle empty strings
- All functions must handle None input by returning None or raising ValueError
- Include docstrings for all functions
- Maximum complexity: O(n) for each function

## Success Criteria
- All tests in `test_string_utils.py` pass
- No linting errors
- Code coverage > 90%

## Validation
Run: `pytest test_string_utils.py -v`