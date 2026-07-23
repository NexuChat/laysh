# ruff: noqa: E501
from __future__ import annotations

import ast
import json
import math
import re
from itertools import combinations
from typing import Any

from jsonschema import ValidationError

from server.schemas import (
    ContractError,
    load_schema,
    validate_document,
    validate_module_output,
    validate_understanding,
)

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_BIDI = re.compile(r"[\u202a-\u202e\u2066-\u2069\u200e\u200f]")
_TRUSTED_MARKER = re.compile(
    r"(?:<\s*/?\s*script\b|@@[A-Z][A-Z0-9_]*@@|window\s*\.\s*layshsimulation|laysh_shared_model|trusted\s*(?:assembler|runtime|wrapper))",
    re.IGNORECASE,
)
_MATH_CALLS = {
    "abs": ("Math.abs", 1, 1),
    "acos": ("Math.acos", 1, 1),
    "asin": ("Math.asin", 1, 1),
    "atan": ("Math.atan", 1, 1),
    "atan2": ("Math.atan2", 2, 2),
    "ceil": ("Math.ceil", 1, 1),
    "clamp": ("clampFinite", 3, 3),
    "cos": ("Math.cos", 1, 1),
    "exp": ("Math.exp", 1, 1),
    "floor": ("Math.floor", 1, 1),
    "log": ("Math.log", 1, 1),
    "log10": ("Math.log10", 1, 1),
    "max": ("Math.max", 1, 8),
    "min": ("Math.min", 1, 8),
    "pow": ("Math.pow", 2, 2),
    "round": ("Math.round", 1, 1),
    "sin": ("Math.sin", 1, 1),
    "sqrt": ("Math.sqrt", 1, 1),
    "tan": ("Math.tan", 1, 1),
}

_SEMANTIC_FAILURE_CODES = (
    (
        "causal response must reference a scientific actor",
        "causal_scientific_actor_required",
    ),
    ("causal response must reference a declared output", "causal_output_undeclared"),
    ("causal response output requires an understanding fixture", "causal_fixture_required"),
    ("causal channel field must directly consume", "causal_channel_output_required"),
    (
        "causal channel must vary across fixture-covered output states",
        "causal_channel_fixture_response_required",
    ),
    (
        "signed causal output requires negative, zero, and positive fixtures",
        "signed_causal_fixture_coverage_required",
    ),
    (
        "time-driven motion requires a scientific field consuming time through a declared output",
        "time_driven_scientific_motion_required",
    ),
    (
        "representation archetype is not emittable",
        "representation_archetype_not_emittable",
    ),
    (
        "representation archetype does not match scientific commands",
        "representation_archetype_command_mismatch",
    ),
    (
        "representation actor proof is not backed",
        "representation_actor_proof_unbacked",
    ),
    (
        "representation actor proof channel must vary",
        "representation_actor_fixture_response_required",
    ),
    (
        "representation graph proof requires world_plus_graph",
        "representation_graph_scene_required",
    ),
    (
        "representation proof references an undeclared output",
        "representation_output_undeclared",
    ),
    (
        "scientific geometry must consume a declared output",
        "scientific_output_reference_required",
    ),
    (
        "trajectory output must reference a declared output",
        "trajectory_output_undeclared",
    ),
    ("visual expression references an undeclared output", "undeclared_visual_output"),
    ("relation references an undeclared output", "undeclared_relation_output"),
    ("relations must cover every scientific pair exactly once", "scientific_relations_incomplete"),
    ("relations must name one unique scientific pair", "scientific_relation_invalid"),
    ("visual command ids must be unique", "duplicate_visual_command_id"),
    ("only circles and ellipses may be scientific", "unsupported_scientific_geometry"),
    ("ellipse safety envelopes cannot prove", "unsupported_ellipse_relation"),
    (
        "primitive safety envelopes cannot prove",
        "unsupported_safety_envelope_relation",
    ),
    ("scientific ellipse must respond through a salient field", "scientific_salient_output_required"),
    ("non-forbid overlap and required contact require zero clearance", "relation_clearance_invalid"),
    ("physics expressions and output names must match", "physics_output_contract_mismatch"),
    ("physics expression names must be unique", "duplicate_physics_output"),
    ("assembled source exceeds 40KiB", "assembled_source_too_large"),
)


class _ChannelResponseError(ContractError):
    def __init__(
        self,
        message: str,
        *,
        expected: dict[str, Any],
        actual: dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.expected = expected
        self.actual = actual


def fragment_failure_code(error: Exception) -> str:
    """Map model-controlled fragment failures to a small safe diagnostic code."""

    message = str(error)
    for marker, code in _SEMANTIC_FAILURE_CODES:
        if marker in message:
            return code
    for prefix in (
        "undeclared_expression_name",
        "unsupported_expression_call",
        "invalid_expression_arity",
    ):
        if message.startswith(f"{prefix}:"):
            return prefix
    if isinstance(error, ValidationError):
        return "fragment_schema_invalid"
    if message in {
        "bidi_character_in_fragment",
        "trusted_marker_in_fragment",
        "expression_must_be_string",
        "invalid_expression",
        "expression_literal_must_be_finite_number",
        "unsupported_expression_operator",
        "unsupported_expression_syntax",
    }:
        return message
    return "fragment_semantic_validation_failed"


def fragment_failure_diagnostic(
    error: Exception,
    *,
    role: str,
    understanding: dict[str, Any],
) -> dict[str, Any]:
    """Return a closed, actionable repair report without exposing raw fragments."""

    code = fragment_failure_code(error)
    expected: dict[str, Any] = {"fragment_contract_valid": True}
    actual: dict[str, Any] = {
        "fragment_contract_valid": False,
        "failure_code": code,
    }
    if code == "undeclared_expression_name":
        identifier = str(error).partition(":")[2]
        if _IDENTIFIER.fullmatch(identifier):
            actual["unexpected_identifier"] = identifier
        if role == "physics":
            allowed = {
                understanding["primary_parameter"]["id"],
                "pi",
                "time",
            }
            secondary = understanding.get("secondary_parameter")
            if secondary is not None:
                allowed.add(secondary["id"])
        elif role == "visual":
            allowed = set(_visual_names(understanding))
            allowed.add("pi")
        else:
            allowed = {"pi"}
        expected["allowed_identifiers"] = sorted(allowed)
    elif isinstance(error, ValidationError):
        actual["schema_path"] = [
            str(item) if isinstance(item, str) else int(item)
            for item in error.absolute_path
        ]
    elif isinstance(error, _ChannelResponseError):
        expected.update(error.expected)
        actual.update(error.actual)
    return {
        "gate": "fragment_contract",
        "code": code,
        "expected": expected,
        "actual": actual,
    }


def _js(value: Any) -> str:
    """Serialize model-supplied values as data, never as executable source."""

    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _reject_untrusted_markers(value: object) -> None:
    serialized = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if _BIDI.search(serialized):
        raise ValueError("bidi_character_in_fragment")
    if _TRUSTED_MARKER.search(serialized):
        raise ValueError("trusted_marker_in_fragment")


def _parse_expression(expression: object) -> ast.Expression:
    if not isinstance(expression, str):
        raise ValueError("expression_must_be_string")
    _reject_untrusted_markers(expression)
    try:
        parsed = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError) as error:
        raise ValueError("invalid_expression") from error
    if not isinstance(parsed, ast.Expression):  # pragma: no cover - ast API contract
        raise ValueError("invalid_expression")
    return parsed


def _compile_expression(expression: object, names: dict[str, str]) -> str:
    """Compile a small Python-expression AST into a parenthesized trusted JS expression."""

    parsed = _parse_expression(expression)

    def visit(node: ast.AST) -> str:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("expression_literal_must_be_finite_number")
            try:
                numeric = float(node.value)
            except OverflowError as error:
                raise ValueError("expression_literal_must_be_finite_number") from error
            if not math.isfinite(numeric):
                raise ValueError("expression_literal_must_be_finite_number")
            return _js(node.value)
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return "Math.PI"
            try:
                return names[node.id]
            except KeyError as error:
                raise ValueError(f"undeclared_expression_name:{node.id}") from error
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operator = "+" if isinstance(node.op, ast.UAdd) else "-"
            return f"({operator}{visit(node.operand)})"
        if isinstance(node, ast.BinOp):
            operators: dict[type[ast.operator], str] = {
                ast.Add: "+",
                ast.Sub: "-",
                ast.Mult: "*",
                ast.Div: "/",
                ast.Mod: "%",
            }
            if isinstance(node.op, ast.Pow):
                return f"Math.pow({visit(node.left)},{visit(node.right)})"
            operator = operators.get(type(node.op))
            if operator is None:
                raise ValueError("unsupported_expression_operator")
            return f"({visit(node.left)}{operator}{visit(node.right)})"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            specification = _MATH_CALLS.get(node.func.id)
            if specification is None:
                raise ValueError(f"unsupported_expression_call:{node.func.id}")
            target, minimum, maximum = specification
            if not minimum <= len(node.args) <= maximum:
                raise ValueError(f"invalid_expression_arity:{node.func.id}")
            return f"{target}({','.join(visit(argument) for argument in node.args)})"
        raise ValueError("unsupported_expression_syntax")

    return visit(parsed.body)


def _evaluate_expression(expression: object, names: dict[str, float]) -> float:
    """Evaluate the same closed numeric DSL used by the trusted assembler."""

    parsed = _parse_expression(expression)

    def finite(value: float) -> float:
        return value if math.isfinite(value) else 0.0

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("expression_literal_must_be_finite_number")
            return finite(float(node.value))
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return math.pi
            try:
                return finite(float(names[node.id]))
            except KeyError as error:
                raise ValueError(f"undeclared_expression_name:{node.id}") from error
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left = visit(node.left)
            right = visit(node.right)
            try:
                if isinstance(node.op, ast.Add):
                    return finite(left + right)
                if isinstance(node.op, ast.Sub):
                    return finite(left - right)
                if isinstance(node.op, ast.Mult):
                    return finite(left * right)
                if isinstance(node.op, ast.Div):
                    return finite(left / right)
                if isinstance(node.op, ast.Mod):
                    return finite(left % right)
                if isinstance(node.op, ast.Pow):
                    return finite(math.pow(left, right))
            except (OverflowError, ValueError, ZeroDivisionError):
                return 0.0
            raise ValueError("unsupported_expression_operator")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            arguments = [visit(argument) for argument in node.args]
            try:
                if node.func.id == "abs":
                    value = abs(arguments[0])
                elif node.func.id == "acos":
                    value = math.acos(arguments[0])
                elif node.func.id == "asin":
                    value = math.asin(arguments[0])
                elif node.func.id == "atan":
                    value = math.atan(arguments[0])
                elif node.func.id == "atan2":
                    value = math.atan2(arguments[0], arguments[1])
                elif node.func.id == "ceil":
                    value = math.ceil(arguments[0])
                elif node.func.id == "clamp":
                    value = max(arguments[1], min(arguments[2], arguments[0]))
                elif node.func.id == "cos":
                    value = math.cos(arguments[0])
                elif node.func.id == "exp":
                    value = math.exp(arguments[0])
                elif node.func.id == "floor":
                    value = math.floor(arguments[0])
                elif node.func.id == "log":
                    value = math.log(arguments[0])
                elif node.func.id == "log10":
                    value = math.log10(arguments[0])
                elif node.func.id == "max":
                    value = max(arguments)
                elif node.func.id == "min":
                    value = min(arguments)
                elif node.func.id == "pow":
                    value = math.pow(arguments[0], arguments[1])
                elif node.func.id == "round":
                    value = math.floor(arguments[0] + 0.5)
                elif node.func.id == "sin":
                    value = math.sin(arguments[0])
                elif node.func.id == "sqrt":
                    value = math.sqrt(arguments[0])
                elif node.func.id == "tan":
                    value = math.tan(arguments[0])
                else:
                    raise ValueError(f"unsupported_expression_call:{node.func.id}")
            except (IndexError, OverflowError, ValueError, ZeroDivisionError):
                return 0.0
            return finite(float(value))
        raise ValueError("unsupported_expression_syntax")

    return finite(visit(parsed.body))


def _expression_is_zero(expression: object) -> bool:
    try:
        parsed = _parse_expression(expression)
    except ValueError:
        return False
    node = parsed.body
    sign = 1
    while isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        if isinstance(node.op, ast.USub):
            sign *= -1
        node = node.operand
    return (
        isinstance(node, ast.Constant)
        and not isinstance(node.value, bool)
        and isinstance(node.value, (int, float))
        and math.isfinite(float(node.value))
        and sign * float(node.value) == 0
    )


def validate_physics_fragment(
    document: dict[str, Any],
    understanding: dict[str, Any],
) -> dict[str, Any]:
    understanding = validate_understanding(understanding)
    validate_document(document, load_schema("physics_fragment.schema.json"))
    _reject_untrusted_markers(document)
    expected_outputs = list(understanding["module_spec"]["outputs"])
    expressions = document["physics_expressions"]
    expression_names = [item["name"] for item in expressions]
    if document["output_names"] != expected_outputs or expression_names != expected_outputs:
        raise ContractError("physics expressions and output names must match understanding outputs")
    if len(set(expression_names)) != len(expression_names):
        raise ContractError("physics expression names must be unique")
    parameters = [understanding["primary_parameter"]]
    secondary = understanding.get("secondary_parameter")
    if secondary is not None:
        parameters.append(secondary)
    names = {
        parameter["id"]: f'finiteNumber(inputs[{_js(parameter["id"])}])'
        for parameter in parameters
    }
    names["time"] = "finiteNumber(time)"
    for item in expressions:
        _compile_expression(item["expression"], names)
    return document


def _visual_names(understanding: dict[str, Any] | None) -> dict[str, str]:
    names = {
        "width": "finiteNumber(width)",
        "height": "finiteNumber(height)",
        "min_dim": "Math.min(finiteNumber(width),finiteNumber(height))",
        "normalized": "finiteNumber(state.normalized)",
        "phase": "finiteNumber(visualPhase)",
        "time": "finiteNumber(time)",
    }
    outputs = None if understanding is None else understanding["module_spec"]["outputs"]
    if outputs is not None:
        for output in outputs:
            names[f"output_{output}"] = f'finiteNumber(state.outputs[{_js(output)}])'
    return names


def _compile_visual_expression(
    expression: object,
    understanding: dict[str, Any] | None,
) -> str:
    names = _visual_names(understanding)
    if understanding is None:
        parsed = _parse_expression(expression)
        for node in ast.walk(parsed):
            if isinstance(node, ast.Name) and node.id.startswith("output_"):
                output_name = node.id.removeprefix("output_")
                if _IDENTIFIER.fullmatch(output_name):
                    names[node.id] = f'finiteNumber(state.outputs[{_js(output_name)}])'
    return _compile_expression(expression, names)


def _visual_output_names(expression: object) -> set[str]:
    """Return explicit output references after parsing the same closed DSL."""

    parsed = _parse_expression(expression)
    return {
        node.id
        for node in ast.walk(parsed)
        if isinstance(node, ast.Name) and node.id.startswith("output_")
    }


def _expression_names(expression: object) -> set[str]:
    parsed = _parse_expression(expression)
    return {
        node.id
        for node in ast.walk(parsed)
        if isinstance(node, ast.Name)
    }


def _command_numeric_expressions(
    command: dict[str, Any],
) -> list[tuple[str, object, bool]]:
    """Return every numeric DSL field and whether it is visually salient."""

    numeric_fields = {
        "circle": ("cx", "cy", "radius", "line_width", "opacity"),
        "ellipse": (
            "cx",
            "cy",
            "radius_x",
            "radius_y",
            "rotation",
            "line_width",
            "opacity",
        ),
        "rect": (
            "x",
            "y",
            "width",
            "height",
            "corner_radius",
            "line_width",
            "opacity",
        ),
        "line": ("x1", "y1", "x2", "y2", "line_width", "opacity"),
        "arrow": ("x1", "y1", "x2", "y2", "line_width", "opacity"),
        "wave": (
            "x1",
            "y1",
            "x2",
            "y2",
            "amplitude",
            "wavelength",
            "line_width",
            "opacity",
        ),
        "text": ("x", "y", "font_size", "opacity"),
        "vector_arrow": (
            "x1",
            "y1",
            "angle",
            "length",
            "head_size",
            "line_width",
            "opacity",
        ),
        "trajectory": ("line_width", "opacity"),
        "body_group": ("cx", "cy", "rotation", "opacity"),
        "ray": ("x1", "y1", "line_width", "opacity"),
    }
    values = [
        (field, command[field], field != "line_width")
        for field in numeric_fields[command["kind"]]
    ]
    if command["kind"] == "body_group":
        part_fields = {
            "circle": ("dx", "dy", "radius", "line_width"),
            "ellipse": (
                "dx",
                "dy",
                "radius_x",
                "radius_y",
                "rotation",
                "line_width",
            ),
            "rect": (
                "dx",
                "dy",
                "width",
                "height",
                "corner_radius",
                "line_width",
            ),
            "line": ("dx1", "dy1", "dx2", "dy2", "line_width"),
        }
        for index, part in enumerate(command["parts"]):
            values.extend(
                (
                    f"parts[{index}].{field}",
                    part[field],
                    field != "line_width",
                )
                for field in part_fields[part["kind"]]
            )
    elif command["kind"] == "ray":
        for index, segment in enumerate(command["segments"]):
            values.extend(
                (
                    f"segments[{index}].{field}",
                    segment[field],
                    True,
                )
                for field in ("angle", "length")
            )
    return values


def _command_channel_expressions(
    command: dict[str, Any],
    channel: str,
) -> tuple[object, ...]:
    direct_fields: dict[str, dict[str, tuple[str, ...]]] = {
        "circle": {
            "x": ("cx",),
            "y": ("cy",),
            "size": ("radius",),
            "opacity": ("opacity",),
        },
        "ellipse": {
            "x": ("cx",),
            "y": ("cy",),
            "rotation": ("rotation",),
            "size": ("radius_x", "radius_y"),
            "opacity": ("opacity",),
        },
        "body_group": {
            "x": ("cx",),
            "y": ("cy",),
            "rotation": ("rotation",),
            "opacity": ("opacity",),
        },
        "vector_arrow": {
            "x": ("x1",),
            "y": ("y1",),
            "rotation": ("angle",),
            "size": ("length", "head_size"),
            "opacity": ("opacity",),
        },
        "ray": {
            "x": ("x1",),
            "y": ("y1",),
            "opacity": ("opacity",),
        },
    }
    expressions = tuple(
        command[field]
        for field in direct_fields.get(command["kind"], {}).get(channel, ())
    )
    if command["kind"] == "body_group" and channel == "size":
        expressions += tuple(
            expression
            for field, expression, salient in _command_numeric_expressions(command)
            if field.startswith("parts[") and salient
        )
    if command["kind"] == "ray" and channel in {"rotation", "size"}:
        segment_field = "angle" if channel == "rotation" else "length"
        expressions += tuple(
            segment[segment_field] for segment in command["segments"]
        )
    return expressions


def _command_channel_consumes_output(
    command: dict[str, Any],
    channel: str,
    output_name: str,
) -> bool:
    if command["kind"] == "trajectory":
        return channel == "y" and command["output_name"] == output_name
    output_reference = f"output_{output_name}"
    return any(
        output_reference in _visual_output_names(expression)
        for expression in _command_channel_expressions(command, channel)
    )


def _command_has_time_output_motion(command: dict[str, Any]) -> bool:
    if command["kind"] == "trajectory":
        return command["sweep"] == "time"
    return any(
        "time" in _expression_names(expression)
        and bool(_visual_output_names(expression))
        for _, expression, salient in _command_numeric_expressions(command)
        if salient
    )


_RESPONSE_VIEWPORT = {"width": 720.0, "height": 400.0, "min_dim": 400.0}
_CHANNEL_MINIMUM_RANGE = {
    "x": 32.0,
    "y": 32.0,
    "rotation": 0.15,
    "opacity": 0.2,
    "size": 0.15,
}


def _output_probe_states(
    understanding: dict[str, Any],
    output_name: str,
) -> list[dict[str, float]]:
    """Build deterministic visual states from numeric fixtures, with safe probes."""

    primary = understanding["primary_parameter"]
    primary_id = primary["id"]
    rows: list[tuple[float, float]] = []
    for check in understanding["checks"]:
        if check["kind"] != "numeric" or check["output"] != output_name:
            continue
        parameter_value = next(
            (
                float(item["value"])
                for item in check["inputs"]
                if item["name"] == primary_id
            ),
            float(primary["default"]),
        )
        rows.append((float(check["expected"]), parameter_value))

    unique_rows: dict[float, float] = {}
    for output_value, parameter_value in rows:
        unique_rows.setdefault(output_value, parameter_value)
    ordered = sorted(unique_rows.items())
    fixture_backed = len(ordered) >= 3
    if len(ordered) >= 3:
        probes = ordered
    elif len(ordered) == 2:
        low, high = ordered
        probes = [
            low,
            ((low[0] + high[0]) / 2, (low[1] + high[1]) / 2),
            high,
        ]
    elif len(ordered) == 1:
        value, parameter_value = ordered[0]
        delta = max(1.0, abs(value) * 0.5)
        probes = [
            (value - delta, float(primary["min"])),
            (value, parameter_value),
            (value + delta, float(primary["max"])),
        ]
    else:
        probes = [
            (-1.0, float(primary["min"])),
            (0.0, float(primary["default"])),
            (1.0, float(primary["max"])),
        ]

    defaults: dict[str, float] = {}
    for declared_output in understanding["module_spec"]["outputs"]:
        expected = [
            float(check["expected"])
            for check in understanding["checks"]
            if check["kind"] == "numeric" and check["output"] == declared_output
        ]
        defaults[f"output_{declared_output}"] = (
            sorted(expected)[len(expected) // 2] if expected else 0.0
        )

    span = float(primary["max"]) - float(primary["min"])
    states: list[dict[str, float]] = []
    for output_value, parameter_value in probes:
        normalized = (
            (parameter_value - float(primary["min"])) / span if span > 0 else 0.0
        )
        states.append(
            {
                **_RESPONSE_VIEWPORT,
                **defaults,
                "normalized": min(1.0, max(0.0, normalized)),
                "phase": 0.0,
                "time": 0.0,
                f"output_{output_name}": output_value,
                "__output_value": output_value,
                "__fixture_backed": 1.0 if fixture_backed else 0.0,
            }
        )
    return states


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _body_group_envelope(command: dict[str, Any], state: dict[str, float]) -> float:
    envelope = 1.0
    for part in command["parts"]:
        if part["kind"] == "circle":
            extent = max(0.0, _evaluate_expression(part["radius"], state))
            offset = math.hypot(
                _evaluate_expression(part["dx"], state),
                _evaluate_expression(part["dy"], state),
            )
        elif part["kind"] == "ellipse":
            extent = max(
                0.0,
                _evaluate_expression(part["radius_x"], state),
                _evaluate_expression(part["radius_y"], state),
            )
            offset = math.hypot(
                _evaluate_expression(part["dx"], state),
                _evaluate_expression(part["dy"], state),
            )
        elif part["kind"] == "rect":
            extent = math.hypot(
                max(0.0, _evaluate_expression(part["width"], state)),
                max(0.0, _evaluate_expression(part["height"], state)),
            ) / 2
            offset = math.hypot(
                _evaluate_expression(part["dx"], state),
                _evaluate_expression(part["dy"], state),
            )
        else:
            extent = 0.0
            offset = max(
                math.hypot(
                    _evaluate_expression(part["dx1"], state),
                    _evaluate_expression(part["dy1"], state),
                ),
                math.hypot(
                    _evaluate_expression(part["dx2"], state),
                    _evaluate_expression(part["dy2"], state),
                ),
            )
        envelope = max(envelope, offset + extent)
    return envelope


def _command_channel_value(
    command: dict[str, Any],
    channel: str,
    state: dict[str, float],
) -> float:
    kind = command["kind"]
    if kind == "trajectory":
        if channel == "y":
            return state[f'output_{command["output_name"]}']
        return _clamp(_evaluate_expression(command["opacity"], state), 0.0, 1.0)

    if kind == "circle":
        field = {"x": "cx", "y": "cy", "size": "radius", "opacity": "opacity"}[
            channel
        ]
        value = _evaluate_expression(command[field], state)
        if channel == "size":
            return max(0.0, value)
        if channel == "opacity":
            return _clamp(value, 0.0, 1.0)
        return value

    if kind == "ellipse":
        radius_x = max(0.0, _evaluate_expression(command["radius_x"], state))
        radius_y = max(0.0, _evaluate_expression(command["radius_y"], state))
        envelope = max(radius_x, radius_y)
        fit_limit = max(1.0, state["min_dim"] / 2 - 8)
        fit_scale = min(1.0, fit_limit / envelope) if envelope > 0 else 1.0
        fitted_envelope = envelope * fit_scale
        if channel in {"x", "y"}:
            field = "cx" if channel == "x" else "cy"
            limit = state["width"] if channel == "x" else state["height"]
            return _clamp(
                _evaluate_expression(command[field], state),
                fitted_envelope + 4,
                limit - fitted_envelope - 4,
            )
        if channel == "rotation":
            return _clamp(
                _evaluate_expression(command["rotation"], state),
                -2 * math.pi,
                2 * math.pi,
            )
        if channel == "size":
            return fitted_envelope
        return _clamp(_evaluate_expression(command["opacity"], state), 0.0, 1.0)

    if kind == "body_group":
        envelope = _body_group_envelope(command, state)
        fit_limit = max(1.0, state["min_dim"] / 2 - 8)
        fitted_envelope = envelope * min(1.0, fit_limit / envelope)
        if channel in {"x", "y"}:
            field = "cx" if channel == "x" else "cy"
            limit = state["width"] if channel == "x" else state["height"]
            return _clamp(
                _evaluate_expression(command[field], state),
                fitted_envelope + 4,
                limit - fitted_envelope - 4,
            )
        if channel == "rotation":
            return _clamp(
                _evaluate_expression(command["rotation"], state),
                -2 * math.pi,
                2 * math.pi,
            )
        if channel == "size":
            return fitted_envelope
        return _clamp(_evaluate_expression(command["opacity"], state), 0.0, 1.0)

    if kind == "vector_arrow":
        field = {
            "x": "x1",
            "y": "y1",
            "rotation": "angle",
            "size": "length",
            "opacity": "opacity",
        }[channel]
        value = _evaluate_expression(command[field], state)
        if channel == "rotation":
            return _clamp(value, -2 * math.pi, 2 * math.pi)
        if channel == "size":
            return max(0.0, value)
        if channel == "opacity":
            return _clamp(value, 0.0, 1.0)
        return value

    if kind == "ray":
        if channel in {"x", "y", "opacity"}:
            field = {"x": "x1", "y": "y1", "opacity": "opacity"}[channel]
            value = _evaluate_expression(command[field], state)
            return _clamp(value, 0.0, 1.0) if channel == "opacity" else value
        if channel == "rotation":
            return _clamp(
                _evaluate_expression(command["segments"][0]["angle"], state),
                -2 * math.pi,
                2 * math.pi,
            )
        return sum(
            max(0.0, _evaluate_expression(segment["length"], state))
            for segment in command["segments"]
        )

    raise ContractError("unsupported scientific channel response")


def _channel_response_measurement(
    command: dict[str, Any],
    *,
    channel: str,
    output_name: str,
    understanding: dict[str, Any],
    relation: str | None,
) -> dict[str, Any]:
    states = _output_probe_states(understanding, output_name)
    samples = sorted(
        (
            (
                state["__output_value"],
                _command_channel_value(command, channel, state),
            )
            for state in states
        ),
        key=lambda item: item[0],
    )
    values = [value for _, value in samples]
    distinct_states = len({f"{value:.6f}" for value in values})
    raw_range = max(values) - min(values)
    if channel == "size":
        positive = [value for value in values if value > 1e-9]
        baseline = min(positive) if positive else 0.0
        observed_range = raw_range / baseline if baseline > 0 else 0.0
    else:
        observed_range = raw_range

    monotonic = True
    compared = 0
    if relation is not None:
        expected_sign = 1 if relation == "direct" else -1
        for (left_output, left_visual), (right_output, right_visual) in zip(
            samples,
            samples[1:],
            strict=False,
        ):
            if abs(right_output - left_output) <= 1e-9:
                continue
            visual_delta = right_visual - left_visual
            if expected_sign * visual_delta < -1e-6:
                monotonic = False
                break
            if abs(visual_delta) > 1e-6:
                compared += 1
        monotonic = monotonic and compared >= 2

    return {
        "channel": channel,
        "output_name": output_name,
        "distinct_states": distinct_states,
        "observed_range": round(observed_range, 6),
        "minimum_range": _CHANNEL_MINIMUM_RANGE[channel],
        "monotonic_relation": monotonic,
        "fixture_backed": bool(states[0]["__fixture_backed"]),
        "passed": (
            distinct_states >= 3
            and observed_range > 1e-6
            and monotonic
        ),
    }


_CAUSAL_CHANNEL_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "circle": {
        "x": ("cx",),
        "y": ("cy",),
        "size": ("radius",),
        "opacity": ("opacity",),
    },
    "ellipse": {
        "x": ("cx",),
        "y": ("cy",),
        "rotation": ("rotation",),
        "size": ("radius_x", "radius_y"),
        "opacity": ("opacity",),
    },
}

_DEFERRED_REPRESENTATION_ARCHETYPES = {
    "particle_flow",
    "wave_medium",
}
_PAIRED_REPRESENTATION_ARCHETYPES = {
    "linked_bodies",
    "orbital_pair",
}


def _validate_causal_response(
    document: dict[str, Any],
    understanding: dict[str, Any] | None,
) -> None:
    response = document["causal_response"]
    actor = next(
        (command for command in document["commands"] if command["id"] == response["actor_id"]),
        None,
    )
    if actor is None or not actor["scientific"]:
        raise ContractError("causal response must reference a scientific actor")

    output_name = response["output_name"]
    if understanding is not None:
        if output_name not in understanding["module_spec"]["outputs"]:
            raise ContractError("causal response must reference a declared output")
        fixtures = [
            check for check in understanding["checks"] if check["output"] == output_name
        ]
        if not fixtures:
            raise ContractError("causal response output requires an understanding fixture")
    else:
        fixtures = []

    if not _command_channel_consumes_output(
        actor,
        response["channel"],
        response["output_name"],
    ):
        raise ContractError(
            "causal channel field must directly consume its declared output"
        )

    if understanding is None:
        return

    measurement = _channel_response_measurement(
        actor,
        channel=response["channel"],
        output_name=output_name,
        understanding=understanding,
        relation=response["relation"],
    )
    if not measurement["passed"]:
        raise _ChannelResponseError(
            "causal channel must vary across fixture-covered output states",
            expected={
                "channel": response["channel"],
                "minimum_distinct_states": 3,
                "minimum_range": measurement["minimum_range"],
                "monotonic_relation": response["relation"],
            },
            actual={
                "channel": response["channel"],
                "distinct_states": measurement["distinct_states"],
                "observed_range": measurement["observed_range"],
                "monotonic_relation": measurement["monotonic_relation"],
                "output_name": output_name,
            },
        )

    primary = understanding["primary_parameter"]
    if primary["min"] < 0 < primary["max"]:
        numeric_expected = [
            float(check["expected"])
            for check in fixtures
            if check["kind"] == "numeric"
        ]
        signs = {
            -1 if value < 0 else 1 if value > 0 else 0 for value in numeric_expected
        }
        # Only infer a signed-output crossing after fixtures establish both signs.
        # A magnitude output over a signed input is intentionally not forced through zero.
        if {-1, 1} <= signs and 0 not in signs:
            raise ContractError(
                "signed causal output requires negative, zero, and positive fixtures"
            )


def _validate_representation(
    document: dict[str, Any],
    understanding: dict[str, Any] | None,
) -> None:
    representation = document["representation"]
    archetype = representation["actor_archetype"]
    if archetype in _DEFERRED_REPRESENTATION_ARCHETYPES:
        raise ContractError(
            "representation archetype is not emittable with phase A1 commands"
        )

    scientific_commands = [
        command for command in document["commands"] if command["scientific"]
    ]
    scientific_kinds = {command["kind"] for command in scientific_commands}
    archetype_matches = (
        (
            archetype == "body"
            and bool(
                scientific_kinds
                & {
                    "body_group",
                    "circle",
                    "ellipse",
                    "trajectory",
                    "vector_arrow",
                }
            )
        )
        or (
            archetype == "elongated_body"
            and bool(scientific_kinds & {"body_group", "ellipse"})
        )
        or (archetype == "ray_bundle" and "ray" in scientific_kinds)
        or (
            archetype in _PAIRED_REPRESENTATION_ARCHETYPES
            and len(scientific_commands) >= 2
        )
        or (
            archetype == "surface_and_body"
            and {"circle", "ellipse"} <= scientific_kinds
        )
    )
    if not archetype_matches:
        raise ContractError(
            "representation archetype does not match scientific commands"
        )

    declared_outputs = (
        None
        if understanding is None
        else set(understanding["module_spec"]["outputs"])
    )
    for proof in representation["proof_channels"]:
        output_name = proof["output_name"]
        if declared_outputs is not None and output_name not in declared_outputs:
            raise ContractError(
                "representation proof references an undeclared output"
            )
        if (
            proof["carrier"] == "graph"
            and representation["scene_pattern"] != "world_plus_graph"
        ):
            raise ContractError(
                "representation graph proof requires world_plus_graph"
            )
        if proof["carrier"] != "actor":
            continue
        backing_commands = [
            command
            for command in scientific_commands
            if _command_channel_consumes_output(
                command,
                proof["channel"],
                output_name,
            )
        ]
        if not backing_commands:
            raise ContractError(
                "representation actor proof is not backed by a scientific command"
            )
        if understanding is None:
            continue
        measurements = [
            _channel_response_measurement(
                command,
                channel=proof["channel"],
                output_name=output_name,
                understanding=understanding,
                relation=None,
            )
            for command in backing_commands
        ]
        if not any(measurement["passed"] for measurement in measurements):
            best = max(
                measurements,
                key=lambda item: (
                    item["distinct_states"],
                    item["observed_range"],
                ),
            )
            raise _ChannelResponseError(
                "representation actor proof channel must vary across fixture-covered output states",
                expected={
                    "channel": proof["channel"],
                    "minimum_distinct_states": 3,
                    "minimum_range": best["minimum_range"],
                },
                actual={
                    "channel": proof["channel"],
                    "distinct_states": best["distinct_states"],
                    "observed_range": best["observed_range"],
                    "output_name": output_name,
                },
            )


def validate_visual_fragment(
    document: dict[str, Any],
    understanding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if understanding is not None:
        understanding = validate_understanding(understanding)
    validate_document(document, load_schema("visual_fragment.schema.json"))
    _reject_untrusted_markers(document)
    commands = document["commands"]
    ids = [command["id"] for command in commands]
    if len(set(ids)) != len(ids):
        raise ContractError("visual command ids must be unique")
    scientific_ids: list[str] = []
    scientific_kinds: dict[str, str] = {}
    declared_output_names = (
        set() if understanding is None else {f"output_{name}" for name in understanding["module_spec"]["outputs"]}
    )
    declared_outputs = (
        set() if understanding is None else set(understanding["module_spec"]["outputs"])
    )
    for command in commands:
        kind = command["kind"]
        if command["scientific"]:
            if kind not in {
                "body_group",
                "circle",
                "ellipse",
                "ray",
                "trajectory",
                "vector_arrow",
            }:
                raise ContractError(
                    "unsupported command kind may not be scientific in visual fragment v2"
                )
            scientific_ids.append(command["id"])
            scientific_kinds[command["id"]] = kind
        consumed_outputs: set[str] = set()
        salient_outputs: set[str] = set()
        for _, expression, salient in _command_numeric_expressions(command):
            referenced_outputs = _visual_output_names(expression)
            if understanding is not None and not referenced_outputs <= declared_output_names:
                raise ContractError("visual expression references an undeclared output")
            consumed_outputs.update(referenced_outputs)
            if salient:
                salient_outputs.update(referenced_outputs)
            _compile_visual_expression(expression, understanding)
        if kind == "trajectory":
            if understanding is not None and command["output_name"] not in declared_outputs:
                raise ContractError(
                    "trajectory output must reference a declared output"
                )
            consumed_outputs.add(f'output_{command["output_name"]}')
            salient_outputs.add(f'output_{command["output_name"]}')
        if command["scientific"] and understanding is not None and not consumed_outputs:
            raise ContractError("scientific geometry must consume a declared output")
        if (
            command["scientific"]
            and kind in {"body_group", "ellipse", "ray", "vector_arrow"}
            and understanding is not None
            and not salient_outputs
        ):
            raise ContractError("scientific ellipse must respond through a salient field")
    if (
        document["representation"]["motion_model"] == "time_driven"
        and not any(
            command["scientific"] and _command_has_time_output_motion(command)
            for command in commands
        )
    ):
        raise ContractError(
            "time-driven motion requires a scientific field consuming time through a declared output"
        )
    seen_pairs: set[tuple[str, str]] = set()
    for relation in document["relations"]:
        pair = tuple(sorted(relation["objects"]))
        if pair in seen_pairs or any(item not in scientific_ids for item in pair):
            raise ContractError("relations must name one unique scientific pair")
        seen_pairs.add(pair)
        referenced_outputs = _visual_output_names(relation["minimum_clearance"])
        if understanding is not None and not referenced_outputs <= declared_output_names:
            raise ContractError("relation references an undeclared output")
        _compile_visual_expression(relation["minimum_clearance"], understanding)
        if (
            relation["overlap_policy"] != "forbid"
            or relation["contact_policy"] == "required"
        ) and not _expression_is_zero(relation["minimum_clearance"]):
            raise ContractError("non-forbid overlap and required contact require zero clearance")
        if "ellipse" in {scientific_kinds[item] for item in pair} and (
            relation["contact_policy"] == "required"
            or relation["overlap_policy"] == "scientific_occlusion"
        ):
            raise ContractError(
                "ellipse safety envelopes cannot prove required contact or scientific occlusion"
            )
        if {
            "body_group",
            "ray",
            "trajectory",
            "vector_arrow",
        } & {scientific_kinds[item] for item in pair} and (
            relation["contact_policy"] == "required"
            or relation["overlap_policy"] == "scientific_occlusion"
        ):
            raise ContractError(
                "primitive safety envelopes cannot prove required contact or scientific occlusion"
            )
    expected_pairs = {tuple(pair) for pair in combinations(sorted(scientific_ids), 2)}
    if seen_pairs != expected_pairs:
        raise ContractError("relations must cover every scientific pair exactly once")
    _validate_causal_response(document, understanding)
    _validate_representation(document, understanding)
    return document


def _visual_expression(expression: object, understanding: dict[str, Any]) -> str:
    return f"finiteNumber({_compile_visual_expression(expression, understanding)})"


def _causal_actor_evidence(
    command: dict[str, Any],
    causal_response: dict[str, Any],
) -> str:
    if command["id"] != causal_response["actor_id"]:
        return ""
    kind = command["kind"]
    if kind == "circle":
        visual_values = {
            "x": "cx",
            "y": "cy",
            "size": "radius",
            "opacity": "visualOpacity",
        }
        bounds = "{left:cx - radius,top:cy - radius,right:cx + radius,bottom:cy + radius,width:radius * 2,height:radius * 2}"
    elif kind == "ellipse":
        visual_values = {
            "x": "cx",
            "y": "cy",
            "rotation": "rotation",
            "size": "Math.max(radiusX,radiusY)",
            "opacity": "visualOpacity",
        }
        bounds = "{left:cx - envelopeRadius,top:cy - envelopeRadius,right:cx + envelopeRadius,bottom:cy + envelopeRadius,width:envelopeRadius * 2,height:envelopeRadius * 2}"
    elif kind == "body_group":
        visual_values = {
            "x": "cx",
            "y": "cy",
            "rotation": "rotation",
            "size": "groupEnvelopeRadius",
            "opacity": "visualOpacity",
        }
        bounds = "{left:cx - groupEnvelopeRadius,top:cy - groupEnvelopeRadius,right:cx + groupEnvelopeRadius,bottom:cy + groupEnvelopeRadius,width:groupEnvelopeRadius * 2,height:groupEnvelopeRadius * 2}"
    elif kind == "vector_arrow":
        visual_values = {
            "x": "x1",
            "y": "y1",
            "rotation": "angle",
            "size": "length",
            "opacity": "visualOpacity",
        }
        bounds = "{left:envelopeCx - envelopeRadius,top:envelopeCy - envelopeRadius,right:envelopeCx + envelopeRadius,bottom:envelopeCy + envelopeRadius,width:envelopeRadius * 2,height:envelopeRadius * 2}"
    elif kind == "ray":
        visual_values = {
            "x": "x1",
            "y": "y1",
            "rotation": "segments[0].angle",
            "size": "segments.reduce((total,segment) => total + segment.length,0)",
            "opacity": "visualOpacity",
        }
        bounds = "{left:envelopeCx - envelopeRadius,top:envelopeCy - envelopeRadius,right:envelopeCx + envelopeRadius,bottom:envelopeCy + envelopeRadius,width:envelopeRadius * 2,height:envelopeRadius * 2}"
    else:
        visual_values = {
            "y": f'state.outputs[{_js(command["output_name"])}]',
            "opacity": "visualOpacity",
        }
        bounds = "{left:envelopeCx - envelopeRadius,top:envelopeCy - envelopeRadius,right:envelopeCx + envelopeRadius,bottom:envelopeCy + envelopeRadius,width:envelopeRadius * 2,height:envelopeRadius * 2}"
    visual_value = visual_values[causal_response["channel"]]
    return f'''
      causalActorResponse = {{schemaVersion:"1.0",actorId:{_js(causal_response["actor_id"])},outputName:{_js(causal_response["output_name"])},channel:{_js(causal_response["channel"])},relation:{_js(causal_response["relation"])},temporalMode:{_js(causal_response["temporal_mode"])},parameterValue:finiteNumber(state.value),outputValue:finiteNumber(state.outputs[{_js(causal_response["output_name"])}]),visualValue:finiteNumber({visual_value}),fittedBounds:{bounds},timeMs:finiteNumber(visualPhase * 80)}};'''


def _body_part_source(part: dict[str, Any], understanding: dict[str, Any]) -> str:
    numeric_fields = {
        "circle": ("dx", "dy", "radius", "line_width"),
        "ellipse": (
            "dx",
            "dy",
            "radius_x",
            "radius_y",
            "rotation",
            "line_width",
        ),
        "rect": (
            "dx",
            "dy",
            "width",
            "height",
            "corner_radius",
            "line_width",
        ),
        "line": ("dx1", "dy1", "dx2", "dy2", "line_width"),
    }
    fields = [f"kind:{_js(part['kind'])}"]
    fields.extend(
        f"{field}:{_visual_expression(part[field], understanding)}"
        for field in numeric_fields[part["kind"]]
        if field != "line_width"
    )
    if part["kind"] != "line":
        fields.append(f"fillColor:{_js(part['fill_color'])}")
    fields.extend(
        (
            f"strokeColor:{_js(part['stroke_color'])}",
            f"lineWidth:{_visual_expression(part['line_width'], understanding)}",
        )
    )
    return "{" + ",".join(fields) + "}"


def _period_output_name(outputs: list[str]) -> str | None:
    return next(
        (
            output
            for output in outputs
            if re.search(r"(?:^|_)(?:period|duration)(?:_s|_seconds)?$", output)
        ),
        None,
    )


def _draw_command(
    command: dict[str, Any],
    understanding: dict[str, Any],
    causal_response: dict[str, Any],
) -> str:
    kind = command["kind"]
    command_id = _js(command["id"])
    opacity = f"clampFinite({_visual_expression(command['opacity'], understanding)},0,1)"
    if kind == "circle":
        cx, cy, radius, line_width = (
            _visual_expression(command[field], understanding)
            for field in ("cx", "cy", "radius", "line_width")
        )
        geometry = ""
        if command["scientific"]:
            geometry = f'''\n    scientificObjects.push({{id:{command_id},scientific:true,clippingPolicy:{_js(command["clipping_policy"])},geometry:{{type:"circle",cx,cy,radius}}}});'''
        causal_evidence = _causal_actor_evidence(command, causal_response)
        return f'''    {{
      const cx = {cx}; const cy = {cy}; const radius = Math.max(0,{radius}); const visualOpacity = {opacity};
      context.save(); context.globalAlpha = visualOpacity; context.beginPath();
      context.arc(cx,cy,radius,0,Math.PI * 2); const fill = context.createRadialGradient(cx - radius * 0.3,cy - radius * 0.3,Math.max(1,radius * 0.1),cx,cy,radius); fill.addColorStop(0,{_js(command["fill_alt_color"])}); fill.addColorStop(1,{_js(command["fill_color"])}); context.fillStyle = fill; context.fill();
      context.lineWidth = Math.max(0,{line_width}); context.strokeStyle = {_js(command["stroke_color"])}; context.stroke(); context.restore();{geometry}{causal_evidence}
    }}'''
    if kind == "ellipse":
        cx, cy, radius_x, radius_y, rotation, line_width = (
            _visual_expression(command[field], understanding)
            for field in (
                "cx",
                "cy",
                "radius_x",
                "radius_y",
                "rotation",
                "line_width",
            )
        )
        geometry = ""
        if command["scientific"]:
            geometry = f'''\n    scientificObjects.push({{id:{command_id},scientific:true,clippingPolicy:{_js(command["clipping_policy"])},geometry:{{type:"circle",cx,cy,radius:Math.max(radiusX,radiusY)}}}});'''
        fit_center = command["scientific"] and command["clipping_policy"] == "forbid"
        fitted_cx = (
            "clampFinite(rawCx,envelopeRadius + 4,width - envelopeRadius - 4)"
            if fit_center
            else "rawCx"
        )
        fitted_cy = (
            "clampFinite(rawCy,envelopeRadius + 4,height - envelopeRadius - 4)"
            if fit_center
            else "rawCy"
        )
        causal_evidence = _causal_actor_evidence(command, causal_response)
        return f'''    {{
      const rawCx = {cx}; const rawCy = {cy}; const rawRadiusX = Math.max(0,{radius_x}); const rawRadiusY = Math.max(0,{radius_y}); const rotation = clampFinite({rotation},-Math.PI * 2,Math.PI * 2); const visualOpacity = {opacity};
      const fitLimit = Math.max(1,Math.min(width,height) / 2 - 8); const rawEnvelopeRadius = Math.max(rawRadiusX,rawRadiusY); const fitScale = rawEnvelopeRadius > 0 ? Math.min(1,fitLimit / rawEnvelopeRadius) : 1;
      const radiusX = rawRadiusX * fitScale; const radiusY = rawRadiusY * fitScale; const envelopeRadius = Math.max(radiusX,radiusY); const cx = {fitted_cx}; const cy = {fitted_cy};
      context.save(); context.globalAlpha = visualOpacity; context.beginPath(); context.ellipse(cx,cy,radiusX,radiusY,rotation,0,Math.PI * 2);
      const fill = context.createLinearGradient(cx - radiusX,cy - radiusY,cx + radiusX,cy + radiusY); fill.addColorStop(0,{_js(command["fill_alt_color"])}); fill.addColorStop(1,{_js(command["fill_color"])}); context.fillStyle = fill; context.fill();
      context.lineWidth = Math.max(0,{line_width}); context.strokeStyle = {_js(command["stroke_color"])}; context.stroke(); context.restore();{geometry}{causal_evidence}
    }}'''
    if kind == "body_group":
        cx, cy, rotation = (
            _visual_expression(command[field], understanding)
            for field in ("cx", "cy", "rotation")
        )
        parts = ",".join(
            _body_part_source(part, understanding) for part in command["parts"]
        )
        geometry = ""
        if command["scientific"]:
            geometry = f'''\n      scientificObjects.push({{id:{command_id},scientific:true,clippingPolicy:{_js(command["clipping_policy"])},geometry:{{type:"circle",cx,cy,radius:groupEnvelopeRadius}}}});'''
        causal_evidence = _causal_actor_evidence(command, causal_response)
        fit_center = command["scientific"] and command["clipping_policy"] == "forbid"
        fitted_cx = (
            "clampFinite(rawCx,groupEnvelopeRadius + 4,width - groupEnvelopeRadius - 4)"
            if fit_center
            else "rawCx"
        )
        fitted_cy = (
            "clampFinite(rawCy,groupEnvelopeRadius + 4,height - groupEnvelopeRadius - 4)"
            if fit_center
            else "rawCy"
        )
        return f'''    {{
      const rawCx = {cx}; const rawCy = {cy}; const rotation = clampFinite({rotation},-Math.PI * 2,Math.PI * 2); const visualOpacity = {opacity};
      const parts = [{parts}]; let groupEnvelopeRadius = 1;
      for (const part of parts) {{
        if (part.kind === "circle") groupEnvelopeRadius = Math.max(groupEnvelopeRadius,Math.hypot(part.dx,part.dy) + Math.max(0,part.radius));
        else if (part.kind === "ellipse") groupEnvelopeRadius = Math.max(groupEnvelopeRadius,Math.hypot(part.dx,part.dy) + Math.max(0,part.radius_x,part.radius_y));
        else if (part.kind === "rect") groupEnvelopeRadius = Math.max(groupEnvelopeRadius,Math.hypot(part.dx,part.dy) + Math.hypot(Math.max(0,part.width),Math.max(0,part.height)) / 2);
        else if (part.kind === "line") groupEnvelopeRadius = Math.max(groupEnvelopeRadius,Math.hypot(part.dx1,part.dy1),Math.hypot(part.dx2,part.dy2));
      }}
      const fitLimit = Math.max(1,Math.min(width,height) / 2 - 8); const fitScale = Math.min(1,fitLimit / groupEnvelopeRadius); groupEnvelopeRadius *= fitScale;
      const cx = {fitted_cx}; const cy = {fitted_cy};
      context.save(); context.globalAlpha = visualOpacity; context.translate(cx,cy); context.rotate(rotation); context.scale(fitScale,fitScale);
      for (const part of parts) {{
        context.beginPath();
        if (part.kind === "circle") context.arc(part.dx,part.dy,Math.max(0,part.radius),0,Math.PI * 2);
        else if (part.kind === "ellipse") context.ellipse(part.dx,part.dy,Math.max(0,part.radius_x),Math.max(0,part.radius_y),clampFinite(part.rotation,-Math.PI * 2,Math.PI * 2),0,Math.PI * 2);
        else if (part.kind === "rect") context.roundRect(part.dx - Math.max(0,part.width) / 2,part.dy - Math.max(0,part.height) / 2,Math.max(0,part.width),Math.max(0,part.height),Math.max(0,part.corner_radius));
        else if (part.kind === "line") {{ context.moveTo(part.dx1,part.dy1); context.lineTo(part.dx2,part.dy2); }}
        if (part.kind !== "line") {{ context.fillStyle = part.fillColor; context.fill(); }}
        context.strokeStyle = part.strokeColor; context.lineWidth = Math.max(0,part.lineWidth); context.stroke();
      }}
      context.restore();{geometry}{causal_evidence}
    }}'''
    if kind == "vector_arrow":
        x1, y1, angle, length, head_size, line_width = (
            _visual_expression(command[field], understanding)
            for field in (
                "x1",
                "y1",
                "angle",
                "length",
                "head_size",
                "line_width",
            )
        )
        geometry = ""
        if command["scientific"]:
            geometry = f'''\n      scientificObjects.push({{id:{command_id},scientific:true,clippingPolicy:{_js(command["clipping_policy"])},geometry:{{type:"circle",cx:envelopeCx,cy:envelopeCy,radius:envelopeRadius}}}});'''
        causal_evidence = _causal_actor_evidence(command, causal_response)
        return f'''    {{
      const x1 = {x1}; const y1 = {y1}; const angle = clampFinite({angle},-Math.PI * 2,Math.PI * 2); const length = Math.max(0,{length}); const headSize = Math.max(0,{head_size}); const lineWidth = Math.max(0,{line_width}); const visualOpacity = {opacity};
      const x2 = x1 + length * Math.cos(angle); const y2 = y1 + length * Math.sin(angle); const headAngle = 0.45;
      const envelopeCx = (x1 + x2) / 2; const envelopeCy = (y1 + y2) / 2; const envelopeRadius = Math.max(1,length / 2 + headSize + lineWidth);
      context.save(); context.globalAlpha = visualOpacity; context.strokeStyle = {_js(command["stroke_color"])}; context.lineWidth = lineWidth; context.beginPath();
      context.moveTo(x1,y1); context.lineTo(x2,y2); context.moveTo(x2,y2); context.lineTo(x2 - headSize * Math.cos(angle - headAngle),y2 - headSize * Math.sin(angle - headAngle)); context.moveTo(x2,y2); context.lineTo(x2 - headSize * Math.cos(angle + headAngle),y2 - headSize * Math.sin(angle + headAngle));
      context.stroke(); context.restore();{geometry}{causal_evidence}
    }}'''
    if kind == "ray":
        x1, y1, line_width = (
            _visual_expression(command[field], understanding)
            for field in ("x1", "y1", "line_width")
        )
        segments = ",".join(
            "{"
            + f"angle:clampFinite({_visual_expression(segment['angle'], understanding)},-Math.PI * 2,Math.PI * 2),"
            + f"length:Math.max(0,{_visual_expression(segment['length'], understanding)})"
            + "}"
            for segment in command["segments"]
        )
        geometry = ""
        if command["scientific"]:
            geometry = f'''\n      scientificObjects.push({{id:{command_id},scientific:true,clippingPolicy:{_js(command["clipping_policy"])},geometry:{{type:"circle",cx:envelopeCx,cy:envelopeCy,radius:envelopeRadius}}}});'''
        causal_evidence = _causal_actor_evidence(command, causal_response)
        return f'''    {{
      const x1 = {x1}; const y1 = {y1}; const segments = [{segments}]; const lineWidth = Math.max(0,{line_width}); const visualOpacity = {opacity};
      let rayX = x1, rayY = y1; const rayPoints = [{{x:rayX,y:rayY}}];
      for (const segment of segments) {{ rayX += segment.length * Math.cos(segment.angle); rayY += segment.length * Math.sin(segment.angle); rayPoints.push({{x:rayX,y:rayY}}); }}
      const minX = Math.min(...rayPoints.map((point) => point.x)); const maxX = Math.max(...rayPoints.map((point) => point.x)); const minY = Math.min(...rayPoints.map((point) => point.y)); const maxY = Math.max(...rayPoints.map((point) => point.y));
      const envelopeCx = (minX + maxX) / 2; const envelopeCy = (minY + maxY) / 2; const envelopeRadius = Math.max(1,Math.hypot(maxX - minX,maxY - minY) / 2 + lineWidth);
      context.save(); context.globalAlpha = visualOpacity; context.strokeStyle = {_js(command["stroke_color"])}; context.lineWidth = lineWidth; context.beginPath(); context.moveTo(x1,y1);
      for (const point of rayPoints.slice(1)) context.lineTo(point.x,point.y);
      context.stroke(); context.restore();{geometry}{causal_evidence}
    }}'''
    if kind == "trajectory":
        line_width = _visual_expression(command["line_width"], understanding)
        primary = understanding["primary_parameter"]
        output_name = command["output_name"]
        period_output = _period_output_name(understanding["module_spec"]["outputs"])
        period_source = (
            f'state.outputs[{_js(period_output)}]'
            if period_output is not None
            else "Math.PI * 2"
        )
        if command["sweep"] == "primary_parameter":
            sweep_source = (
                f"{primary['min']} + ({primary['max']} - {primary['min']}) * ratio"
            )
            time_source = "time"
        else:
            sweep_source = "state.value"
            time_source = "trajectoryPeriod * ratio"
        causal_evidence = _causal_actor_evidence(command, causal_response)
        return f'''    {{
      const sampleCount = {command["samples"]}; const visualOpacity = {opacity}; const lineWidth = Math.max(0,{line_width}); const trajectoryPeriod = Math.max(0.001,Math.abs(finiteNumber({period_source})));
      const trajectorySamples = Array.from({{length:sampleCount}},(_,index) => {{
        const ratio = index / (sampleCount - 1); const trajectorySweep = {sweep_source}; const trajectoryTime = {time_source}; const trajectoryInputs = {{...parameterValues,{_js(primary["id"])}:trajectorySweep}};
        const trajectoryState = modelState(trajectorySweep,trajectoryInputs,trajectoryTime); return {{ratio,output:finiteNumber(trajectoryState.outputs[{_js(output_name)}])}};
      }});
      const outputMinimum = Math.min(...trajectorySamples.map((sample) => sample.output)); const outputMaximum = Math.max(...trajectorySamples.map((sample) => sample.output)); const outputSpan = outputMaximum - outputMinimum;
      const trajectoryPoints = trajectorySamples.map((sample) => ({{x:width * (0.08 + sample.ratio * 0.84),y:outputSpan === 0 ? height * 0.5 : height * (0.88 - ((sample.output - outputMinimum) / outputSpan) * 0.76)}}));
      const minX = Math.min(...trajectoryPoints.map((point) => point.x)); const maxX = Math.max(...trajectoryPoints.map((point) => point.x)); const minY = Math.min(...trajectoryPoints.map((point) => point.y)); const maxY = Math.max(...trajectoryPoints.map((point) => point.y));
      const envelopeCx = (minX + maxX) / 2; const envelopeCy = (minY + maxY) / 2; const envelopeRadius = Math.max(1,Math.hypot(maxX - minX,maxY - minY) / 2 + lineWidth);
      context.save(); context.globalAlpha = visualOpacity; context.strokeStyle = {_js(command["stroke_color"])}; context.lineWidth = lineWidth; context.beginPath(); trajectoryPoints.forEach((point,index) => {{ if (index === 0) context.moveTo(point.x,point.y); else context.lineTo(point.x,point.y); }}); context.stroke(); context.restore();
      scientificObjects.push({{id:{command_id},scientific:true,clippingPolicy:{_js(command["clipping_policy"])},geometry:{{type:"circle",cx:envelopeCx,cy:envelopeCy,radius:envelopeRadius}}}});{causal_evidence}
    }}'''
    if kind == "rect":
        x, y, item_width, item_height, corner_radius, line_width = (
            _visual_expression(command[field], understanding)
            for field in ("x", "y", "width", "height", "corner_radius", "line_width")
        )
        return f'''    {{
      const x = {x}; const y = {y}; const itemWidth = Math.max(0,{item_width}); const itemHeight = Math.max(0,{item_height});
      context.save(); context.globalAlpha = {opacity}; context.beginPath();
      context.roundRect(x,y,itemWidth,itemHeight,Math.max(0,{corner_radius})); context.fillStyle = {_js(command["fill_color"])}; context.fill();
      context.lineWidth = Math.max(0,{line_width}); context.strokeStyle = {_js(command["stroke_color"])}; context.stroke(); context.restore();
    }}'''
    if kind in {"line", "arrow"}:
        x1, y1, x2, y2, line_width = (
            _visual_expression(command[field], understanding)
            for field in ("x1", "y1", "x2", "y2", "line_width")
        )
        arrow = ""
        if kind == "arrow":
            arrow = """
      const direction = Math.atan2(y2 - y1,x2 - x1); const head = Math.max(6,Math.min(18,Math.max(0,lineWidth) * 4));
      context.moveTo(x2,y2); context.lineTo(x2 - head * Math.cos(direction - 0.45),y2 - head * Math.sin(direction - 0.45));
      context.moveTo(x2,y2); context.lineTo(x2 - head * Math.cos(direction + 0.45),y2 - head * Math.sin(direction + 0.45));"""
        return f'''    {{
      const x1 = {x1}; const y1 = {y1}; const x2 = {x2}; const y2 = {y2}; const lineWidth = Math.max(0,{line_width});
      context.save(); context.globalAlpha = {opacity}; context.strokeStyle = {_js(command["stroke_color"])}; context.lineWidth = lineWidth; context.beginPath(); context.moveTo(x1,y1); context.lineTo(x2,y2);{arrow}
      context.stroke(); context.restore();
    }}'''
    if kind == "wave":
        x1, y1, x2, y2, amplitude, wavelength, line_width = (
            _visual_expression(command[field], understanding)
            for field in ("x1", "y1", "x2", "y2", "amplitude", "wavelength", "line_width")
        )
        return f'''    {{
      const x1 = {x1}; const y1 = {y1}; const x2 = {x2}; const y2 = {y2}; const amplitude = {amplitude}; const wavelength = Math.max(1,{wavelength});
      context.save(); context.globalAlpha = {opacity}; context.strokeStyle = {_js(command["stroke_color"])}; context.lineWidth = Math.max(0,{line_width}); context.beginPath();
      for (let step = 0; step <= 24; step += 1) {{ const t = step / 24; const x = x1 + (x2 - x1) * t; const y = y1 + (y2 - y1) * t + amplitude * Math.sin((x - x1) * Math.PI * 2 / wavelength); if (step === 0) context.moveTo(x,y); else context.lineTo(x,y); }}
      context.stroke(); context.restore();
    }}'''
    x, y, font_size = (
        _visual_expression(command[field], understanding) for field in ("x", "y", "font_size")
    )
    return f'''    {{
      const x = {x}; const y = {y}; context.save(); context.globalAlpha = {opacity}; context.fillStyle = {_js(command["color"])};
      context.font = `${{Math.max(1,{font_size})}}px sans-serif`; context.textAlign = {_js(command["align"])}; context.direction = locale === "ar" ? "rtl" : "ltr";
      context.fillText(locale === "ar" ? {_js(command["text_ar"])} : {_js(command["text_en"])},x,y); context.restore();
    }}'''


def _draw_relations(relations: list[dict[str, Any]], understanding: dict[str, Any]) -> str:
    return ",".join(
        f'{{objects:{_js(relation["objects"])},overlapPolicy:{_js(relation["overlap_policy"])},contactPolicy:{_js(relation["contact_policy"])},minimumClearance:Math.max(0,{_visual_expression(relation["minimum_clearance"], understanding)})}}'
        for relation in relations
    )


def assemble_fragments(
    physics_fragment: dict[str, Any],
    visual_fragment: dict[str, Any],
    understanding: dict[str, Any],
) -> dict[str, Any]:
    understanding = validate_understanding(understanding)
    physics_fragment = validate_physics_fragment(physics_fragment, understanding)
    visual_fragment = validate_visual_fragment(visual_fragment, understanding)
    primary = understanding["primary_parameter"]
    secondary = understanding.get("secondary_parameter")
    parameters = [primary, *([] if secondary is None else [secondary])]
    parameter_defaults = {parameter["id"]: parameter["default"] for parameter in parameters}
    parameter_limits = {parameter["id"]: [parameter["min"], parameter["max"]] for parameter in parameters}
    outputs = list(physics_fragment["output_names"])
    input_names = {
        parameter["id"]: f'finiteNumber(inputs[{_js(parameter["id"])}])'
        for parameter in parameters
    }
    input_names["time"] = "finiteNumber(time)"
    output_lines = ",\n".join(
        f'      {_js(item["name"])}: finiteNumber({_compile_expression(item["expression"], input_names)})'
        for item in physics_fragment["physics_expressions"]
    )
    returned_outputs = ",\n".join(
        f'        {_js(name)}: state.outputs[{_js(name)}]' for name in outputs
    )
    draw_commands = "\n".join(
        _draw_command(command, understanding, visual_fragment["causal_response"])
        for command in visual_fragment["commands"]
    )
    rendered_actor_evidence = ",".join(
        (
            f'{{id:{_js(command["id"])},kind:{_js(command["kind"])},'
            f'opacity:clampFinite({_visual_expression(command["opacity"], understanding)},0,1)}}'
        )
        for command in visual_fragment["commands"]
        if command["scientific"]
    )
    relations = _draw_relations(visual_fragment["relations"], understanding)
    primary_id = primary["id"]
    source = f'''window.LayshSimulation = Object.freeze((() => {{
  "use strict";
  const spec = Object.freeze({_js({"representation": visual_fragment["representation"]})});
  let canvas = null, context = null, width = 0, height = 0, locale = "en", reducedMotion = true, emitFrame = () => {{}}, visualPhase = 0, destroyed = false;
  const parameterLimits = {_js(parameter_limits)};
  const parameterValues = {_js(parameter_defaults)};
  function finiteNumber(value) {{ const numeric = Number(value); return Number.isFinite(numeric) ? numeric : 0; }}
  function clampFinite(value, lower, upper) {{ return Math.max(finiteNumber(lower),Math.min(finiteNumber(upper),finiteNumber(value))); }}
  function clampParameter(name, value) {{ const limits = parameterLimits[name]; if (!limits) return finiteNumber(parameterValues[name]); const numeric = Number(value); const candidate = Number.isFinite(numeric) ? numeric : finiteNumber(parameterValues[name]); return clampFinite(candidate,limits[0],limits[1]); }}
  function modelOutputs(value, inputs, time) {{
    void value;
    return {{
{output_lines}
    }};
  }}
  /* LAYSH_SHARED_MODEL: modelState */
  function modelState(value, inputs, time = 0) {{
    const clamped = clampParameter({_js(primary_id)},value);
    const closedInputs = {{...parameterValues,...(inputs || {{}}),{_js(primary_id)}:clamped}};
    const outputs = Object.freeze(modelOutputs(clamped,closedInputs,finiteNumber(time)));
    return {{value:clamped,normalized:(clamped - {primary["min"]}) / ({primary["max"]} - {primary["min"]}),output:outputs[{_js(outputs[0])}],outputs}};
  }}
  function drawScene(state, time) {{
    if (!context || !canvas) return;
    const gradient = context.createLinearGradient(0,0,0,height); gradient.addColorStop(0,{_js(visual_fragment["background"]["top_color"])}); gradient.addColorStop(1,{_js(visual_fragment["background"]["bottom_color"])});
    context.clearRect(0,0,width,height); context.fillStyle = gradient; context.fillRect(0,0,width,height);
    const scientificObjects = []; let causalActorResponse = null;
{draw_commands}
    canvas.__layshSceneGeometry = [{{schemaVersion:"1.0",phase:"post_fit",viewport:{{width:finiteNumber(width),height:finiteNumber(height),safeInset:0}},state:{{id:"rendered",timeMs:0}},objects:scientificObjects,relations:[{relations}]}}];
    canvas.__layshRenderedActors = {{schemaVersion:"1.0",actors:[{rendered_actor_evidence}]}};
    /* LAYSH_CAUSAL_RESPONSE_V1 */
    canvas.__layshActorResponse = causalActorResponse;
  }}
  function render() {{ if (destroyed || !canvas || !context) return; const time = finiteNumber(visualPhase * 0.08); const state = modelState(parameterValues[{_js(primary_id)}],parameterValues,time); const activeOutput = state.output; void activeOutput; drawScene(state,time); emitFrame(); }}
  const simulation = {{
    version:1,
    init(options) {{ canvas = options.canvas; context = options.context; width = options.width; height = options.height; locale = options.locale; reducedMotion = Boolean(options.reducedMotion); emitFrame = options.emitFrame; visualPhase = 0; destroyed = false; render(); }},
    setParameter(name,value,elapsedMs) {{ if (!(name in parameterValues)) return; parameterValues[name] = clampParameter(name,value); if (!reducedMotion && Number.isFinite(Number(elapsedMs)) && Number(elapsedMs) > 0) visualPhase = (visualPhase + clampFinite(Number(elapsedMs),0,80) / 80) % 1000000; render(); }},
    test(inputs) {{ const supplied = inputs && typeof inputs === "object" ? inputs : {{}}; const state = modelState(supplied[{_js(primary_id)}],supplied,supplied.time); return {{
{returned_outputs}
    }}; }},
    resize(nextWidth,nextHeight) {{ width = nextWidth; height = nextHeight; canvas.width = nextWidth; canvas.height = nextHeight; render(); }},
    destroy() {{ destroyed = true; canvas = null; context = null; emitFrame = () => {{}}; }},
  }};
  Object.defineProperty(simulation,"spec",{{value:spec,enumerable:false,writable:false,configurable:false}});
  return simulation;
}})());'''
    if len(source.encode("utf-8")) > 40 * 1024:
        raise ContractError("assembled source exceeds 40KiB")
    return validate_module_output(
        {
            "module_js": source,
            "output_names": outputs,
            "brief_summary": physics_fragment["brief_summary"],
            "assumptions": physics_fragment["assumptions"],
        }
    )
