"""
String utility functions providing common string operations.

This module provides utility functions for string manipulation including
reversing strings, counting vowels, checking palindromes, and capitalizing words.
"""


def reverse_string(s: str) -> str:
    """
    Return a reversed copy of the input string.
    
    Args:
        s: The string to reverse.
        
    Returns:
        The reversed string. Empty string returns empty string.
        
    Examples:
        >>> reverse_string("hello")
        'olleh'
        >>> reverse_string("")
        ''
    """
    return s[::-1]


def count_vowels(s: str) -> int:
    """
    Count the number of vowels in the given string.
    
    Args:
        s: The string to count vowels in.
        
    Returns:
        The count of vowels (a, e, i, o, u) in the string.
        Case-insensitive. Empty string returns 0.
        
    Examples:
        >>> count_vowels("hello")
        2
        >>> count_vowels("AEIOU")
        5
        >>> count_vowels("")
        0
    """
    vowels = set("aeiouAEIOU")
    return sum(1 for char in s if char in vowels)


def is_palindrome(s: str) -> bool:
    """
    Check if the given string is a palindrome.
    
    A palindrome is a string that reads the same forwards and backwards,
    ignoring case and non-alphanumeric characters.
    
    Args:
        s: The string to check.
        
    Returns:
        True if the string is a palindrome, False otherwise.
        Empty string returns True.
        
    Examples:
        >>> is_palindrome("racecar")
        True
        >>> is_palindrome("A man, a plan, a canal: Panama")
        True
        >>> is_palindrome("hello")
        False
        >>> is_palindrome("")
        True
    """
    # Remove non-alphanumeric characters and convert to lowercase
    cleaned = ''.join(char.lower() for char in s if char.isalnum())
    return cleaned == cleaned[::-1]


def capitalize_words(s: str) -> str:
    """
    Capitalize the first letter of each word in the given string.
    
    Args:
        s: The string to capitalize.
        
    Returns:
        The string with each word's first letter capitalized.
        Empty string returns empty string.
        
    Examples:
        >>> capitalize_words("hello world")
        'Hello World'
        >>> capitalize_words("this is a test")
        'This Is A Test'
        >>> capitalize_words("")
        ''
    """
    return ' '.join(word.capitalize() for word in s.split())