from __future__ import annotations

import re
from typing import Any

_IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
_MARKER = re.compile(rf"/\*\s*LAYSH_SHARED_MODEL\s*:\s*({_IDENTIFIER})\s*\*/")
_FUNCTION = re.compile(rf"\bfunction\s+({_IDENTIFIER})\s*\([^)]*\)\s*\{{")
_TEST = re.compile(r"\btest\s*(?::\s*function)?\s*\([^)]*\)\s*\{")


def _block_after(source: str, opening_brace: int) -> str | None:
    """Return a JavaScript block body without treating strings as braces."""

    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = opening_brace
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if character in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if character == "*" and following == "/":
                block_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue
        if character == "/" and following == "/":
            line_comment = True
            index += 2
            continue
        if character == "/" and following == "*":
            block_comment = True
            index += 2
            continue
        if character in "'\"`":
            quote = character
            index += 1
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[opening_brace + 1 : index]
        index += 1
    return None


def _function_bodies(source: str) -> dict[str, str]:
    bodies: dict[str, str] = {}
    for match in _FUNCTION.finditer(source):
        body = _block_after(source, match.end() - 1)
        if body is not None:
            bodies[match.group(1)] = body
    return bodies


def _contains_call(source: str, function_name: str) -> bool:
    return bool(re.search(rf"\b{re.escape(function_name)}\s*\(", source))


def _consumes_model_state(source: str, function_name: str) -> bool:
    """Require a returned state object to affect the containing path.

    A bare call is not enough: it could be a decorative no-op beside a second,
    divergent visual formula. The bounded contract therefore requires a local
    binding and a later property read from that binding.
    """

    binding = re.compile(
        rf"\b(?:var|let|const)\s+({_IDENTIFIER})\s*=\s*{re.escape(function_name)}\s*\("
    )
    for match in binding.finditer(source):
        state_name = match.group(1)
        remainder = source[match.end() :]
        if re.search(rf"\b{re.escape(state_name)}\s*\.", remainder):
            return True
    return False


def shared_model_report(source: str) -> dict[str, Any]:
    """Statically require one named pivotal model shared by draw and test.

    This is deliberately a bounded source contract, not a JavaScript semantic
    proof. Runtime fixture and browser physics gates remain the independent
    evidence that the shared model's values are scientifically correct.
    """

    failures: list[dict[str, Any]] = []
    markers = _MARKER.findall(source)
    if len(markers) != 1:
        code = "shared_model_marker_missing" if not markers else "shared_model_marker_ambiguous"
        return {
            "passed": False,
            "check_count": 1,
            "failures": [
                {
                    "gate": "shared_model_state",
                    "code": code,
                    "expected": {"shared_model_markers": 1},
                    "actual": {"shared_model_markers": len(markers)},
                }
            ],
            "model_function": None,
        }

    model_function = markers[0]
    bodies = _function_bodies(source)
    if model_function not in bodies:
        failures.append(
            {
                "gate": "shared_model_state",
                "code": "shared_model_function_missing",
                "expected": {"function": model_function},
                "actual": {"function_found": False},
            }
        )
    elif not re.search(r"\breturn\s*\{", bodies[model_function]):
        failures.append(
            {
                "gate": "shared_model_state",
                "code": "shared_model_not_state_object",
                "expected": {"model_function_returns": "plain_state_object"},
                "actual": {"model_function_returns_state_object": False},
            }
        )

    test_match = _TEST.search(source)
    test_body = _block_after(source, test_match.end() - 1) if test_match else None
    if test_body is None or not _contains_call(test_body, model_function):
        failures.append(
            {
                "gate": "shared_model_state",
                "code": "shared_model_not_used_by_test",
                "expected": {"test_calls": model_function},
                "actual": {"test_calls_shared_model": False},
            }
        )
    elif not _consumes_model_state(test_body, model_function):
        failures.append(
            {
                "gate": "shared_model_state",
                "code": "shared_model_state_not_consumed_by_test",
                "expected": {"test_consumes_state_from": model_function},
                "actual": {"test_consumes_shared_model_state": False},
            }
        )

    render_bodies = [
        body
        for name, body in bodies.items()
        if re.search(r"(?:draw|render)", name, flags=re.IGNORECASE)
    ]
    calling_render_bodies = [
        body for body in render_bodies if _contains_call(body, model_function)
    ]
    if not calling_render_bodies:
        failures.append(
            {
                "gate": "shared_model_state",
                "code": "shared_model_not_used_by_render",
                "expected": {"render_calls": model_function},
                "actual": {"render_calls_shared_model": False},
            }
        )
    elif not any(_consumes_model_state(body, model_function) for body in calling_render_bodies):
        failures.append(
            {
                "gate": "shared_model_state",
                "code": "shared_model_state_not_consumed_by_render",
                "expected": {"render_consumes_state_from": model_function},
                "actual": {"render_consumes_shared_model_state": False},
            }
        )

    return {
        "passed": not failures,
        "check_count": 7,
        "failures": failures,
        "model_function": model_function,
    }
