"""
String manipulation utility functions.

This module provides utility functions for string manipulation and analysis.
Functions should be implemented to pass the tests in test_string_utils.py.
"""

def reverse_string(s: str) -> str:
    """Reverse the input string.
    
    Args:
        s: The string to reverse.
    
    Returns:
        The reversed string.
    """
    return s[::-1]


def count_vowels(s: str) -> int:
    """Count the number of vowels in the input string.
    
    Args:
        s: The string to count vowels in.
    
    Returns:
        The count of vowels (a, e, i, o, u) in the string, case-insensitive.
    """
    vowels = set('aeiou')
    count = 0
    for char in s.lower():
        if char in vowels:
            count += 1
    return count


def is_palindrome(s: str) -> bool:
    """Check if the input string is a palindrome.
    
    Args:
        s: The string to check.
    
    Returns:
        True if the string is a palindrome, False otherwise.
    """
    return s == s[::-1]


def capitalize_words(s: str) -> str:
    """Capitalize the first letter of each word in the input string.
    
    Args:
        s: The string to capitalize.
    
    Returns:
        The string with each word's first letter capitalized.
    """
    return s.title()
