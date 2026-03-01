"""Tests for message sanitization.

Verifies that sanitize_message() cleans up common LLM artifacts
while preserving legitimate natural language content.

This function is the single chokepoint for ALL messages entering JetStream.
It must be bulletproof — every weird LLM output should be handled gracefully.
"""

from __future__ import annotations

import json

from streetmarket.helpers.sanitize import MAX_MESSAGE_LENGTH, sanitize_message

# ===========================================================================
# Normal text — passes through unchanged
# ===========================================================================


def test_normal_text_unchanged() -> None:
    text = "I have 10 fresh loaves for sale at 5 coins each!"
    assert sanitize_message(text) == text


def test_multiline_text_unchanged() -> None:
    text = "Hello!\n\nI'd like to buy some bread.\nHow much do you have?"
    assert sanitize_message(text) == text


def test_single_word() -> None:
    assert sanitize_message("Hello") == "Hello"


def test_single_character() -> None:
    assert sanitize_message("x") == "x"


def test_natural_language_with_punctuation() -> None:
    text = "I'll sell 3 loaves @ 5 coins/each — deal? (Yes!)"
    assert sanitize_message(text) == text


def test_text_with_numbers_and_symbols() -> None:
    text = "Price: $5.00, qty=10, total: $50.00 #bread"
    assert sanitize_message(text) == text


# ===========================================================================
# Empty / whitespace edge cases
# ===========================================================================


def test_empty_string() -> None:
    assert sanitize_message("") == ""


def test_whitespace_only_spaces() -> None:
    assert sanitize_message("   ") == ""


def test_whitespace_only_newlines() -> None:
    assert sanitize_message("\n\n\n") == ""


def test_whitespace_only_mixed() -> None:
    assert sanitize_message("   \n\n  \t  ") == ""


def test_single_space() -> None:
    assert sanitize_message(" ") == ""


def test_single_newline() -> None:
    assert sanitize_message("\n") == ""


# ===========================================================================
# Control characters
# ===========================================================================


def test_strips_null_bytes() -> None:
    assert sanitize_message("hello\x00world") == "helloworld"


def test_strips_control_chars_low_range() -> None:
    """Strip \x00-\x08 (before tab)."""
    text = "".join(chr(i) for i in range(0x00, 0x09)) + "hello"
    assert sanitize_message(text) == "hello"


def test_strips_vertical_tab_and_form_feed() -> None:
    """Strip \x0b (VT) and \x0c (FF)."""
    assert sanitize_message("hello\x0b\x0cworld") == "helloworld"


def test_strips_control_chars_high_range() -> None:
    """Strip \x0e-\x1f (after CR)."""
    text = "hello" + "".join(chr(i) for i in range(0x0E, 0x20)) + "world"
    assert sanitize_message(text) == "helloworld"


def test_preserves_tab() -> None:
    assert sanitize_message("col1\tcol2") == "col1\tcol2"


def test_preserves_newline() -> None:
    assert sanitize_message("line1\nline2") == "line1\nline2"


def test_preserves_carriage_return() -> None:
    assert sanitize_message("line1\rline2") == "line1\rline2"


def test_preserves_crlf() -> None:
    """Windows-style line endings preserved."""
    assert sanitize_message("line1\r\nline2") == "line1\r\nline2"


def test_strips_bom() -> None:
    assert sanitize_message("\ufeffHello") == "Hello"


def test_strips_bom_mid_text() -> None:
    assert sanitize_message("Hello\ufeffWorld") == "HelloWorld"


def test_strips_delete_char() -> None:
    assert sanitize_message("hello\x7fworld") == "helloworld"


def test_all_control_chars_only() -> None:
    """Message that is entirely control chars → empty string."""
    text = "\x00\x01\x02\x03\x04\x05\x06\x07\x08"
    assert sanitize_message(text) == ""


def test_control_chars_interleaved() -> None:
    assert sanitize_message("\x00h\x01e\x02l\x03l\x04o") == "hello"


# ===========================================================================
# Truncation
# ===========================================================================


def test_truncates_long_messages() -> None:
    text = "a" * 3000
    result = sanitize_message(text)
    assert len(result) == MAX_MESSAGE_LENGTH


def test_short_messages_not_truncated() -> None:
    text = "a" * 100
    assert sanitize_message(text) == text


def test_exact_boundary_not_truncated() -> None:
    """Exactly MAX_MESSAGE_LENGTH chars should NOT be truncated."""
    text = "x" * MAX_MESSAGE_LENGTH
    result = sanitize_message(text)
    assert len(result) == MAX_MESSAGE_LENGTH
    assert result == text


def test_one_over_boundary_truncated() -> None:
    text = "x" * (MAX_MESSAGE_LENGTH + 1)
    result = sanitize_message(text)
    assert len(result) == MAX_MESSAGE_LENGTH


def test_truncation_preserves_multibyte_chars() -> None:
    """Python slicing works on code points, not bytes — emoji won't be split."""
    # Fill with emoji (each is 1 code point) up to boundary
    text = "\U0001f35e" * (MAX_MESSAGE_LENGTH + 100)  # bread emoji
    result = sanitize_message(text)
    assert len(result) == MAX_MESSAGE_LENGTH
    # Every character should be a valid bread emoji
    assert all(c == "\U0001f35e" for c in result)


def test_truncation_of_realistic_long_message() -> None:
    """Simulate a chatty LLM that generates a very long response."""
    sentences = ["I have bread for sale at five coins. "] * 200
    text = "".join(sentences)
    assert len(text) > MAX_MESSAGE_LENGTH
    result = sanitize_message(text)
    assert len(result) == MAX_MESSAGE_LENGTH
    assert result.startswith("I have bread")


# ===========================================================================
# Whitespace collapsing
# ===========================================================================


def test_collapses_three_newlines() -> None:
    assert sanitize_message("Hello\n\n\nWorld") == "Hello\n\nWorld"


def test_collapses_five_newlines() -> None:
    assert sanitize_message("Hello\n\n\n\n\nWorld") == "Hello\n\nWorld"


def test_collapses_ten_newlines() -> None:
    assert sanitize_message("Hello\n\n\n\n\n\n\n\n\n\nWorld") == "Hello\n\nWorld"


def test_two_newlines_preserved() -> None:
    text = "Hello\n\nWorld"
    assert sanitize_message(text) == text


def test_single_newline_preserved() -> None:
    assert sanitize_message("Hello\nWorld") == "Hello\nWorld"


def test_multiple_collapse_points() -> None:
    """Multiple groups of excess newlines all collapsed."""
    text = "A\n\n\n\nB\n\n\n\nC"
    assert sanitize_message(text) == "A\n\nB\n\nC"


# ===========================================================================
# JSON wrapping — unwrap {"message": "..."} artifacts
# ===========================================================================


def test_unwraps_json_message() -> None:
    text = '{"message": "I want to buy 5 loaves of bread"}'
    assert sanitize_message(text) == "I want to buy 5 loaves of bread"


def test_unwraps_json_with_extra_fields() -> None:
    text = '{"from": "baker", "message": "Fresh bread for sale!", "type": "offer"}'
    assert sanitize_message(text) == "Fresh bread for sale!"


def test_json_without_message_key_unchanged() -> None:
    text = '{"type": "offer", "price": 5}'
    assert sanitize_message(text) == text


def test_invalid_json_unchanged() -> None:
    text = '{"message": broken json'
    assert sanitize_message(text) == text


def test_json_message_value_is_number_unchanged() -> None:
    text = '{"message": 42}'
    assert sanitize_message(text) == text


def test_json_message_value_is_bool_unchanged() -> None:
    text = '{"message": true}'
    assert sanitize_message(text) == text


def test_json_message_value_is_null_unchanged() -> None:
    text = '{"message": null}'
    assert sanitize_message(text) == text


def test_json_message_value_is_list_unchanged() -> None:
    text = '{"message": ["hello", "world"]}'
    assert sanitize_message(text) == text


def test_json_message_value_is_dict_unchanged() -> None:
    text = '{"message": {"inner": "value"}}'
    assert sanitize_message(text) == text


def test_json_message_empty_string_unwrapped() -> None:
    """Empty message value is still a valid string — unwrap it."""
    text = '{"message": ""}'
    assert sanitize_message(text) == ""


def test_json_message_with_escaped_quotes() -> None:
    text = '{"message": "He said \\"hello\\" to the baker"}'
    assert sanitize_message(text) == 'He said "hello" to the baker'


def test_json_message_with_unicode_escapes() -> None:
    text = '{"message": "caf\\u00e9"}'
    assert sanitize_message(text) == "café"


def test_json_message_with_newlines() -> None:
    text = '{"message": "line1\\nline2"}'
    assert sanitize_message(text) == "line1\nline2"


def test_json_array_not_unwrapped() -> None:
    """JSON arrays should pass through unchanged — only objects are unwrapped."""
    text = '[{"message": "hello"}]'
    assert sanitize_message(text) == text


def test_json_with_trailing_text_not_unwrapped() -> None:
    """If there's text after the JSON, json.loads fails → pass through."""
    text = '{"message": "hello"} and then some more text'
    assert sanitize_message(text) == text


def test_json_with_leading_text_not_unwrapped() -> None:
    text = 'The agent says: {"message": "hello"}'
    assert sanitize_message(text) == text


def test_nested_json_only_unwraps_one_level() -> None:
    """If the extracted message is itself JSON, don't unwrap again."""
    inner = '{"message": "deeply nested"}'
    text = json.dumps({"message": inner})
    result = sanitize_message(text)
    assert result == inner  # One level unwrapped, not two


def test_curly_braces_not_json() -> None:
    """Text with curly braces that isn't valid JSON passes through."""
    text = "{baker says hello to the market}"
    assert sanitize_message(text) == text


def test_json_string_literal_not_unwrapped() -> None:
    """A JSON string (not object) passes through — not starting with {."""
    text = '"just a plain string"'
    assert sanitize_message(text) == text


def test_json_with_whitespace_only_message() -> None:
    text = '{"message": "   "}'
    assert sanitize_message(text) == ""


# ===========================================================================
# Markdown code fences
# ===========================================================================


def test_strips_json_code_fence() -> None:
    text = '```json\n{"message": "Hello from the baker!"}\n```'
    assert sanitize_message(text) == "Hello from the baker!"


def test_strips_plain_code_fence() -> None:
    text = "```\nI want to sell 10 loaves\n```"
    assert sanitize_message(text) == "I want to sell 10 loaves"


def test_strips_text_code_fence() -> None:
    text = "```text\nI want to sell 10 loaves\n```"
    assert sanitize_message(text) == "I want to sell 10 loaves"


def test_strips_plaintext_code_fence() -> None:
    text = "```plaintext\nHello world\n```"
    assert sanitize_message(text) == "Hello world"


def test_strips_markdown_code_fence() -> None:
    text = "```markdown\n**Bold** text here\n```"
    assert sanitize_message(text) == "**Bold** text here"


def test_strips_JSON_uppercase_code_fence() -> None:
    text = '```JSON\n{"message": "Hello"}\n```'
    assert sanitize_message(text) == "Hello"


def test_code_fence_with_json_message_unwrapped() -> None:
    text = '```json\n{"message": "I offer 5 coins for bread"}\n```'
    assert sanitize_message(text) == "I offer 5 coins for bread"


def test_code_fence_embedded_in_text_not_stripped() -> None:
    """Fences that aren't the ENTIRE message should NOT be stripped."""
    text = "Here's my offer:\n```json\n{\"price\": 5}\n```\nWhat do you think?"
    assert sanitize_message(text) == text


def test_code_fence_with_text_before_not_stripped() -> None:
    text = "The response is:\n```json\n{\"message\": \"hello\"}\n```"
    assert sanitize_message(text) == text


def test_code_fence_with_text_after_not_stripped() -> None:
    text = "```json\n{\"message\": \"hello\"}\n```\nEnd of response."
    assert sanitize_message(text) == text


def test_double_code_fence_outer_stripped() -> None:
    """Two consecutive code fences — regex matches ^ to $, strips outer fences."""
    text = "```json\n{\"a\": 1}\n```\n```json\n{\"b\": 2}\n```"
    result = sanitize_message(text)
    # The anchored regex treats the whole text as one fence, stripping outer ```
    assert result == "{\"a\": 1}\n```\n```json\n{\"b\": 2}"


def test_empty_code_fence() -> None:
    text = "```\n\n```"
    assert sanitize_message(text) == ""


def test_code_fence_with_only_whitespace() -> None:
    text = "```\n   \n```"
    assert sanitize_message(text) == ""


# ===========================================================================
# Unicode — preserved
# ===========================================================================


def test_preserves_emoji() -> None:
    text = "Fresh bread for sale! \U0001f35e\U0001f525"
    assert sanitize_message(text) == text


def test_preserves_accented_characters() -> None:
    text = "Bonjour! Je voudrais acheter du café"
    assert sanitize_message(text) == text


def test_preserves_cjk_characters() -> None:
    text = "\u65b0\u9bae\u306a\u30d1\u30f3\u3092\u58f2\u308a\u307e\u3059"
    assert sanitize_message(text) == text


def test_preserves_arabic_text() -> None:
    text = "\u0623\u0631\u064a\u062f \u0634\u0631\u0627\u0621 \u062e\u0628\u0632"
    assert sanitize_message(text) == text


def test_preserves_mixed_scripts() -> None:
    text = "Hello \u4f60\u597d Bonjour \u3053\u3093\u306b\u3061\u306f"
    assert sanitize_message(text) == text


def test_preserves_currency_symbols() -> None:
    text = "Price: \u00a35, \u20ac4, \u00a5500"
    assert sanitize_message(text) == text


def test_preserves_math_symbols() -> None:
    text = "Total \u2265 50 coins \u00d7 2"
    assert sanitize_message(text) == text


# ===========================================================================
# Combined / real-world LLM artifacts
# ===========================================================================


def test_combined_fence_and_json() -> None:
    """Code fence wrapping JSON with control char — triple cleanup."""
    text = '```json\n{"message": "Hello!\x00"}\n```'
    assert sanitize_message(text) == "Hello!"


def test_leading_trailing_whitespace_stripped() -> None:
    text = "  \n  Hello world  \n  "
    assert sanitize_message(text) == "Hello world"


def test_bom_plus_json_wrapping() -> None:
    text = '\ufeff{"message": "Hello from the baker"}'
    assert sanitize_message(text) == "Hello from the baker"


def test_control_chars_inside_json_value() -> None:
    """Control chars are stripped first, then JSON is parsed."""
    text = '{"message": "Hello\x00 World"}'
    # After control char strip: {"message": "Hello World"}
    assert sanitize_message(text) == "Hello World"


def test_fence_with_bom_and_control_chars() -> None:
    text = '\ufeff```json\n{"message": "Hi\x01"}\n```'
    assert sanitize_message(text) == "Hi"


def test_excessive_newlines_inside_fence() -> None:
    text = "```\nHello\n\n\n\n\nWorld\n```"
    assert sanitize_message(text) == "Hello\n\nWorld"


def test_realistic_gemini_json_output() -> None:
    """Gemini sometimes wraps the entire response in JSON."""
    text = (
        '{"from": "baker-hugo", "topic": "/market/square",'
        ' "message": "I have fresh bread for 5 coins!"}'
    )
    assert sanitize_message(text) == "I have fresh bread for 5 coins!"


def test_realistic_gemini_fenced_json_output() -> None:
    """Gemini sometimes wraps in code fence AND JSON."""
    text = '```json\n{"from": "baker-hugo", "message": "Fresh loaves available!"}\n```'
    assert sanitize_message(text) == "Fresh loaves available!"


def test_realistic_chatgpt_markdown_artifact() -> None:
    """ChatGPT sometimes wraps plain text in code fences."""
    text = "```\nI would like to purchase 3 loaves of bread at 5 coins each.\n```"
    assert sanitize_message(text) == "I would like to purchase 3 loaves of bread at 5 coins each."


def test_message_with_backticks_not_fences() -> None:
    """Backticks used inline (not as fences) should be preserved."""
    text = "Use `bread` to buy from the `baker`"
    assert sanitize_message(text) == text


def test_json_looking_natural_language() -> None:
    """Text that mentions JSON but isn't JSON should pass through."""
    text = 'The format is {"message": "text"} but I prefer natural language'
    assert sanitize_message(text) == text


def test_only_opening_fence() -> None:
    """Just an opening fence with no close — not a complete fence, pass through."""
    text = "```json\nsome content here"
    assert sanitize_message(text) == text


def test_only_closing_fence() -> None:
    text = "some content here\n```"
    assert sanitize_message(text) == text


def test_idempotent() -> None:
    """Running sanitize twice should give the same result as once."""
    texts = [
        "Hello world",
        '{"message": "test"}',
        "```json\n{\"message\": \"test\"}\n```",
        "Hello\x00\x01World",
        "a" * 3000,
        "\ufeffBOM text",
    ]
    for text in texts:
        once = sanitize_message(text)
        twice = sanitize_message(once)
        assert once == twice, f"Not idempotent for: {text!r}"


def test_all_control_chars_around_text() -> None:
    """Control chars before, inside, and after real text."""
    text = "\x00\x01Hello\x02\x03 \x04World\x05\x06"
    # \x02\x03 stripped, space kept, \x04 stripped → "Hello World"
    assert sanitize_message(text) == "Hello World"


def test_tab_separated_values_preserved() -> None:
    """Tab-separated data should not be mangled."""
    text = "item\tqty\tprice\nbread\t10\t5\nfish\t3\t8"
    assert sanitize_message(text) == text
