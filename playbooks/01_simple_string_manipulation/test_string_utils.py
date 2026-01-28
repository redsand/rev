#!/usr/bin/env python3
"""
Tests for string manipulation utility functions.
"""

import pytest
from string_utils import reverse_string, count_vowels, is_palindrome, capitalize_words


class TestReverseString:
    """Test reverse_string function."""

    def test_reverse_string_basic(self):
        """Test basic string reversal."""
        assert reverse_string("hello") == "olleh"

    def test_reverse_string_empty(self):
        """Test reversing empty string."""
        assert reverse_string("") == ""

    def test_reverse_string_single_char(self):
        """Test reversing single character."""
        assert reverse_string("a") == "a"

    def test_reverse_string_with_spaces(self):
        """Test reversing string with spaces."""
        assert reverse_string("hello world") == "dlrow olleh"

    def test_reverse_string_none(self):
        """Test reversing None should raise ValueError."""
        with pytest.raises(ValueError):
            reverse_string(None)


class TestCountVowels:
    """Test count_vowels function."""

    def test_count_vowels_basic(self):
        """Test counting vowels in basic string."""
        assert count_vowels("hello") == 2  # e, o

    def test_count_vowels_empty(self):
        """Test counting vowels in empty string."""
        assert count_vowels("") == 0

    def test_count_vowels_all_vowels(self):
        """Test string with all vowels."""
        assert count_vowels("aeiou") == 5

    def test_count_vowels_case_insensitive(self):
        """Test case-insensitive vowel counting."""
        assert count_vowels("AEIOUaeiou") == 10
        assert count_vowels("Hello") == 2  # e, o

    def test_count_vowels_no_vowels(self):
        """Test string with no vowels."""
        assert count_vowels("bcdfg") == 0

    def test_count_vowels_none(self):
        """Test counting vowels in None should return 0 or raise ValueError."""
        with pytest.raises(ValueError):
            count_vowels(None)


class TestIsPalindrome:
    """Test is_palindrome function."""

    def test_is_palindrome_true(self):
        """Test palindrome detection for true palindromes."""
        assert is_palindrome("racecar") is True
        assert is_palindrome("A man a plan a canal Panama") is True

    def test_is_palindrome_false(self):
        """Test palindrome detection for non-palindromes."""
        assert is_palindrome("hello") is False
        assert is_palindrome("world") is False

    def test_is_palindrome_empty(self):
        """Test empty string is palindrome."""
        assert is_palindrome("") is True

    def test_is_palindrome_single_char(self):
        """Test single character is palindrome."""
        assert is_palindrome("a") is True

    def test_is_palindrome_with_spaces_only(self):
        """Test string with only spaces."""
        assert is_palindrome("   ") is True

    def test_is_palindrome_none(self):
        """Test palindrome check on None should raise ValueError."""
        with pytest.raises(ValueError):
            is_palindrome(None)


class TestCapitalizeWords:
    """Test capitalize_words function."""

    def test_capitalize_words_basic(self):
        """Test capitalizing words in basic string."""
        assert capitalize_words("hello world") == "Hello World"

    def test_capitalize_words_empty(self):
        """Test capitalizing empty string."""
        assert capitalize_words("") == ""

    def test_capitalize_words_single_word(self):
        """Test capitalizing single word."""
        assert capitalize_words("hello") == "Hello"

    def test_capitalize_words_multiple_spaces(self):
        """Test capitalizing with multiple spaces."""
        assert capitalize_words("hello   world") == "Hello   World"

    def test_capitalize_words_mixed_case(self):
        """Test capitalizing already capitalized words."""
        assert capitalize_words("Hello World") == "Hello World"
        assert capitalize_words("hELLO wORLD") == "Hello World"

    def test_capitalize_words_none(self):
        """Test capitalizing None should raise ValueError."""
        with pytest.raises(ValueError):
            capitalize_words(None)