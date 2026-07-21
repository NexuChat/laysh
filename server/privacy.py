from __future__ import annotations

import html
import unicodedata
from html.parser import HTMLParser

_JS_SIMPLE_ESCAPES = {
    "0": "\0",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


class _ArtifactTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _scalar_value(code_point: int) -> str | None:
    if code_point > 0x10FFFF or 0xD800 <= code_point <= 0xDFFF:
        return None
    return chr(code_point)


def _decode_escape_at(value: str, slash_index: int) -> tuple[str, int] | None:
    """Decode one static JavaScript escape without evaluating source text."""

    marker_index = slash_index + 1
    if marker_index >= len(value):
        return None
    marker = value[marker_index]
    if marker in {"\n", "\u2028", "\u2029"}:
        return "", marker_index + 1
    if marker == "\r":
        end_index = marker_index + 1
        if end_index < len(value) and value[end_index] == "\n":
            end_index += 1
        return "", end_index
    if marker in _JS_SIMPLE_ESCAPES:
        return _JS_SIMPLE_ESCAPES[marker], marker_index + 1
    if marker == "x":
        digits = value[marker_index + 1 : marker_index + 3]
        if len(digits) == 2 and all(digit in _HEX_DIGITS for digit in digits):
            return chr(int(digits, 16)), marker_index + 3
        return None
    if marker != "u":
        # Generated modules are strict JavaScript: decimal/octal escapes are
        # invalid, while identity escapes yield their source character.
        if marker in "0123456789":
            return None
        return marker, marker_index + 1
    if marker_index + 1 < len(value) and value[marker_index + 1] == "{":
        closing_index = value.find("}", marker_index + 2, marker_index + 9)
        if closing_index == -1:
            return None
        digits = value[marker_index + 2 : closing_index]
        if not (1 <= len(digits) <= 6) or any(
            digit not in _HEX_DIGITS for digit in digits
        ):
            return None
        decoded = _scalar_value(int(digits, 16))
        return (decoded, closing_index + 1) if decoded is not None else None

    digits = value[marker_index + 1 : marker_index + 5]
    if len(digits) != 4 or any(digit not in _HEX_DIGITS for digit in digits):
        return None
    code_point = int(digits, 16)
    end_index = marker_index + 5
    if 0xD800 <= code_point <= 0xDBFF:
        low_prefix = value[end_index : end_index + 2]
        low_digits = value[end_index + 2 : end_index + 6]
        if (
            low_prefix == r"\u"
            and len(low_digits) == 4
            and all(digit in _HEX_DIGITS for digit in low_digits)
        ):
            low_code_point = int(low_digits, 16)
            if 0xDC00 <= low_code_point <= 0xDFFF:
                combined = 0x10000 + (
                    (code_point - 0xD800) * 0x400
                    + low_code_point
                    - 0xDC00
                )
                return chr(combined), end_index + 6
        return None
    decoded = _scalar_value(code_point)
    return (decoded, end_index) if decoded is not None else None


def _decode_js_static_escapes(value: str) -> str:
    """Interpret only lexical escape sequences; never execute artifact code."""

    decoded: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "\\":
            decoded.append(value[index])
            index += 1
            continue
        run_end = index
        while run_end < len(value) and value[run_end] == "\\":
            run_end += 1
        slash_count = run_end - index
        decoded.append("\\" * (slash_count // 2))
        if slash_count % 2 == 0:
            index = run_end
            continue
        escape = _decode_escape_at(value, run_end - 1)
        if escape is None:
            decoded.append("\\")
            index = run_end
            continue
        character, index = escape
        decoded.append(character)
    return "".join(decoded)


def _artifact_text(value: str, *, separator: str) -> str:
    parser = _ArtifactTextExtractor()
    parser.feed(value)
    parser.close()
    return separator.join(parser.parts)


def _normalized_echo_text(value: str) -> str:
    decoded = html.unescape(value)
    normalized = unicodedata.normalize("NFKC", decoded).casefold()
    without_controls = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Cf"
    )
    return " ".join(without_controls.split())


def contains_learner_question_echo(artifact: str, question: str) -> bool:
    """Detect a normalized verbatim learner-question echo without persisting it."""

    needle = _normalized_echo_text(question)
    if not needle:
        return False
    decoded_artifact = _decode_js_static_escapes(artifact)
    candidates = (
        decoded_artifact,
        _artifact_text(decoded_artifact, separator=" "),
        _artifact_text(decoded_artifact, separator=""),
    )
    return any(needle in _normalized_echo_text(candidate) for candidate in candidates)
