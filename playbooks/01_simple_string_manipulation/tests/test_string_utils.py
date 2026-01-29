"""
Comprehensive unit tests for string manipulation utility functions.

Tests cover:
- reverse_string: Reverses a given string
- count_vowels: Counts vowels in a string
- is_palindrome: Checks if a string is a palindrome
- capitalize_words: Capitalizes the first letter of each word
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path to import string_utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from string_utils import reverse_string, count_vowels, is_palindrome, capitalize_words


class TestReverseString:
    """Test cases for reverse_string function."""
    
    def test_basic_string(self):
        """Test reversing a basic string."""
        assert reverse_string("hello") == "olleh"
    
    def test_empty_string(self):
        """Test reversing an empty string."""
        assert reverse_string("") == ""
    
    def test_single_character(self):
        """Test reversing a single character."""
        assert reverse_string("a") == "a"
    
    def test_palindrome(self):
        """Test reversing a palindrome string."""
        assert reverse_string("racecar") == "racecar"
    
    def test_string_with_spaces(self):
        """Test reversing a string with spaces."""
        assert reverse_string("hello world") == "dlrow olleh"
    
    def test_string_with_numbers(self):
        """Test reversing a string with numbers."""
        assert reverse_string("abc123") == "321cba"
    
    def test_string_with_special_characters(self):
        """Test reversing a string with special characters."""
        assert reverse_string("hello!") == "!olleh"
    
    def test_string_with_punctuation(self):
        """Test reversing a string with punctuation."""
        assert reverse_string("a,b,c") == "c,b,a"
    
    def test_unicode_characters(self):
        """Test reversing a string with unicode characters."""
        assert reverse_string("café") == "éfac"
    
    def test_multiple_words(self):
        """Test reversing multiple words."""
        assert reverse_string("The quick brown fox") == "xof nworb kciuq ehT"
    
    def test_numbers_only(self):
        """Test reversing a string of only numbers."""
        assert reverse_string("12345") == "54321"
    
    def test_whitespace_only(self):
        """Test reversing a string of only whitespace."""
        assert reverse_string("   ") == "   "
    
    def test_leading_trailing_spaces(self):
        """Test reversing a string with leading and trailing spaces."""
        assert reverse_string("  hello  ") == "  olleh  "


class TestCountVowels:
    """Test cases for count_vowels function."""
    
    def test_basic_string(self):
        """Test counting vowels in a basic string."""
        assert count_vowels("hello") == 2
    
    def test_all_vowels(self):
        """Test counting all vowels."""
        assert count_vowels("aeiou") == 5
    
    def test_all_vowels_uppercase(self):
        """Test counting all uppercase vowels."""
        assert count_vowels("AEIOU") == 5
    
    def test_no_vowels(self):
        """Test counting vowels in a string with no vowels."""
        assert count_vowels("xyz") == 0
    
    def test_empty_string(self):
        """Test counting vowels in an empty string."""
        assert count_vowels("") == 0
    
    def test_mixed_case(self):
        """Test counting vowels with mixed case."""
        assert count_vowels("HeLLo") == 2
    
    def test_multiple_vowels(self):
        """Test counting multiple occurrences of vowels."""
        assert count_vowels("beautiful") == 5
    
    def test_consecutive_vowels(self):
        """Test counting consecutive vowels."""
        assert count_vowels("queue") == 4
    
    def test_repeated_vowels(self):
        """Test counting repeated vowels."""
        assert count_vowels("aaaeeeiiiooouuu") == 15
    
    def test_y_is_not_vowel(self):
        """Test that 'y' is not counted as a vowel."""
        assert count_vowels("xyz") == 0
    
    def test_string_with_numbers_and_vowels(self):
        """Test counting vowels in a string with numbers."""
        assert count_vowels("a1e2i3o4u5") == 5
    
    def test_string_with_spaces_and_vowels(self):
        """Test counting vowels in a string with spaces."""
        assert count_vowels("a e i o u") == 5
    
    def test_no_vowels_with_y(self):
        """Test that 'y' in various positions is not counted."""
        assert count_vowels("gym") == 0
        assert count_vowels("yesterday") == 3  # e, e, a
    
    def test_all_consonants(self):
        """Test counting vowels in a string of all consonants."""
        assert count_vowels("bcdfghjklmnpqrstvwxyz") == 0
    
    def test_long_string(self):
        """Test counting vowels in a longer string."""
        assert count_vowels("The quick brown fox jumps over the lazy dog") == 11


class TestIsPalindrome:
    """Test cases for is_palindrome function."""
    
    def test_simple_palindrome(self):
        """Test a simple palindrome."""
        assert is_palindrome("racecar") is True
    
    def test_simple_non_palindrome(self):
        """Test a simple non-palindrome."""
        assert is_palindrome("hello") is False
    
    def test_empty_string(self):
        """Test if empty string is considered a palindrome."""
        assert is_palindrome("") is True
    
    def test_single_character(self):
        """Test a single character string."""
        assert is_palindrome("a") is True
    
    def test_case_sensitive_palindrome(self):
        """Test palindrome with mixed case."""
        assert is_palindrome("Racecar") is False  # Case-sensitive
    
    def test_lowercase_palindrome(self):
        """Test lowercase palindrome."""
        assert is_palindrome("racecar") is True
    
    def test_palindrome_with_spaces(self):
        """Test palindrome with spaces (typically not palindrome with spaces)."""
        assert is_palindrome("race car") is False
    
    def test_palindrome_with_punctuation(self):
        """Test palindrome with punctuation."""
        assert is_palindrome("A man, a plan, a canal, Panama") is False
    
    def test_numeric_palindrome(self):
        """Test numeric string palindrome."""
        assert is_palindrome("12321") is True
    
    def test_numeric_non_palindrome(self):
        """Test numeric string non-palindrome."""
        assert is_palindrome("12345") is False
    
    def test_two_character_palindrome(self):
        """Test two character palindrome."""
        assert is_palindrome("aa") is True
    
    def test_two_character_non_palindrome(self):
        """Test two character non-palindrome."""
        assert is_palindrome("ab") is False
    
    def test_long_palindrome(self):
        """Test a longer palindrome."""
        assert is_palindrome("amanaplanacanalpanama") is True
    
    def test_almost_palindrome(self):
        """Test a string that is almost a palindrome."""
        assert is_palindrome("racecara") is False
    
    def test_repeated_character(self):
        """Test string with repeated characters."""
        assert is_palindrome("aaaaa") is True
    
    def test_whitespace_only(self):
        """Test string with only whitespace."""
        assert is_palindrome("   ") is True  # Reversed is the same
    
    def test_special_characters(self):
        """Test string with special characters."""
        assert is_palindrome("!@!") is True


class TestCapitalizeWords:
    """Test cases for capitalize_words function."""
    
    def test_basic_string(self):
        """Test capitalizing words in a basic string."""
        assert capitalize_words("hello world") == "Hello World"
    
    def test_empty_string(self):
        """Test capitalizing words in an empty string."""
        assert capitalize_words("") == ""
    
    def test_single_word(self):
        """Test capitalizing a single word."""
        assert capitalize_words("hello") == "Hello"
    
    def test_already_capitalized(self):
        """Test string that is already capitalized."""
        assert capitalize_words("Hello World") == "Hello World"
    
    def test_all_uppercase(self):
        """Test converting all uppercase to capitalized."""
        assert capitalize_words("HELLO WORLD") == "Hello World"
    
    def test_all_lowercase(self):
        """Test converting all lowercase to capitalized."""
        assert capitalize_words("hello world") == "Hello World"
    
    def test_mixed_case(self):
        """Test converting mixed case to capitalized."""
        assert capitalize_words("hELLo wOrLD") == "Hello World"
    
    def test_multiple_spaces(self):
        """Test handling multiple spaces between words."""
        assert capitalize_words("hello  world") == "Hello  World"
    
    def test_leading_spaces(self):
        """Test handling leading spaces."""
        assert capitalize_words("  hello world") == "  Hello World"
    
    def test_trailing_spaces(self):
        """Test handling trailing spaces."""
        assert capitalize_words("hello world  ") == "Hello World  "
    
    def test_multiple_words(self):
        """Test capitalizing multiple words."""
        assert capitalize_words("the quick brown fox") == "The Quick Brown Fox"
    
    def test_single_character_words(self):
        """Test capitalizing single character words."""
        assert capitalize_words("a b c") == "A B C"
    
    def test_words_with_numbers(self):
        """Test words with numbers."""
        assert capitalize_words("hello 123 world") == "Hello 123 World"
    
    def test_numbers_only(self):
        """Test string with only numbers."""
        assert capitalize_words("123 456") == "123 456"
    
    def test_special_characters(self):
        """Test words with special characters."""
        assert capitalize_words("hello! world?") == "Hello! World?"
    
    def test_hyphenated_words(self):
        """Test hyphenated words."""
        assert capitalize_words("self-improvement") == "Self-improvement"
    
    def test_apostrophes(self):
        """Test words with apostrophes."""
        assert capitalize_words("don't can't") == "Don't Can't"
    
    def test_single_letter_with_space(self):
        """Test single letters with spaces."""
        assert capitalize_words("i am a test") == "I Am A Test"
    
    def test_very_long_word(self):
        """Test capitalizing a very long word."""
        long_word = "a" * 100
        expected = "A" + "a" * 99
        assert capitalize_words(long_word) == expected
    
    def test_tabs_and_newlines(self):
        """Test handling tabs and newlines."""
        assert capitalize_words("hello\tworld\ntest") == "Hello\tworld\ntest"


class TestEdgeCasesAndIntegration:
    """Integration tests and additional edge cases."""
    
    def test_reverse_then_is_palindrome(self):
        """Test that reversing a string twice gives original."""
        original = "hello world"
        assert reverse_string(reverse_string(original)) == original
    
    def test_palindrome_reversal(self):
        """Test that palindrome reversal is the same."""
        palindrome = "racecar"
        assert reverse_string(palindrome) == palindrome
    
    def test_capitalize_preserves_length(self):
        """Test that capitalize_words preserves string length."""
        original = "hello world 123"
        assert len(capitalize_words(original)) == len(original)
    
    def test_count_vowels_case_insensitive(self):
        """Test that count_vowels is case-insensitive."""
        assert count_vowels("Hello") == count_vowels("HELLO") == count_vowels("hello")
    
    def test_empty_strings_all_functions(self):
        """Test all functions with empty strings."""
        assert reverse_string("") == ""
        assert count_vowels("") == 0
        assert is_palindrome("") is True
        assert capitalize_words("") == ""
    
    def test_whitespace_strings_all_functions(self):
        """Test all functions with whitespace strings."""
        whitespace = "   "
        assert reverse_string(whitespace) == whitespace
        assert count_vowels(whitespace) == 0
        assert is_palindrome(whitespace) is True
        assert capitalize_words(whitespace) == whitespace


if __name__ == "__main__":
    pytest.main([__file__, "-v"])