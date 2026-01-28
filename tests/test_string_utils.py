"""
Tests for string_utils module.
"""

import pytest
from string_utils import reverse_string, count_vowels, is_palindrome, capitalize_words


class TestReverseString:
    """Test cases for reverse_string function."""

    def test_reverse_normal_string(self):
        assert reverse_string("hello") == "olleh"

    def test_reverse_empty_string(self):
        assert reverse_string("") == ""

    def test_reverse_single_character(self):
        assert reverse_string("a") == "a"

    def test_reverse_palindrome(self):
        assert reverse_string("racecar") == "racecar"

    def test_reverse_with_spaces(self):
        assert reverse_string("hello world") == "dlrow olleh"

    def test_reverse_with_numbers(self):
        assert reverse_string("abc123") == "321cba"

    def test_reverse_with_special_chars(self):
        assert reverse_string("a!b@c#") == "#c@b!a"


class TestCountVowels:
    """Test cases for count_vowels function."""

    def test_count_vowels_normal_string(self):
        assert count_vowels("hello") == 2

    def test_count_vowels_empty_string(self):
        assert count_vowels("") == 0

    def test_count_vowels_no_vowels(self):
        assert count_vowels("xyz") == 0

    def test_count_vowels_all_vowels(self):
        assert count_vowels("aeiou") == 5

    def test_count_vowels_uppercase(self):
        assert count_vowels("HELLO") == 2

    def test_count_vowels_mixed_case(self):
        assert count_vowels("HeLLo WoRLd") == 3

    def test_count_vowels_with_y(self):
        assert count_vowels("why") == 0  # y is not a vowel

    def test_count_vowels_repeated(self):
        assert count_vowels("queueing") == 5


class TestIsPalindrome:
    """Test cases for is_palindrome function."""

    def test_is_palindrome_true(self):
        assert is_palindrome("racecar") is True

    def test_is_palindrome_false(self):
        assert is_palindrome("hello") is False

    def test_is_palindrome_empty_string(self):
        assert is_palindrome("") is True

    def test_is_palindrome_single_character(self):
        assert is_palindrome("a") is True

    def test_is_palindrome_with_spaces(self):
        assert is_palindrome("race car") is False

    def test_is_palindrome_case_sensitive(self):
        assert is_palindrome("Racecar") is False

    def test_is_palindrome_with_numbers(self):
        assert is_palindrome("12321") is True

    def test_is_palindrome_with_special_chars(self):
        assert is_palindrome("a!a") is False


class TestCapitalizeWords:
    """Test cases for capitalize_words function."""

    def test_capitalize_words_normal_string(self):
        assert capitalize_words("hello world") == "Hello World"

    def test_capitalize_words_empty_string(self):
        assert capitalize_words("") == ""

    def test_capitalize_words_single_word(self):
        assert capitalize_words("hello") == "Hello"

    def test_capitalize_words_multiple_words(self):
        assert capitalize_words("the quick brown fox") == "The Quick Brown Fox"

    def test_capitalize_words_with_numbers(self):
        assert capitalize_words("test123 case") == "Test123 Case"

    def test_capitalize_words_extra_spaces(self):
        assert capitalize_words("  hello  world  ") == "  Hello  World  "

    def test_capitalize_words_already_capitalized(self):
        assert capitalize_words("Hello World") == "Hello World"

    def test_capitalize_words_all_uppercase(self):
        assert capitalize_words("HELLO WORLD") == "HELLO WORLD"