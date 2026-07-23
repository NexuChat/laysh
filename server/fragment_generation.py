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
        "signed causal output requires negative, zero, and positive fixtures",
        "signed_causal_fixture_coverage_required",
    ),
    (
        "scientific geometry must consume a declared output",
        "scientific_output_reference_required",
    ),
    ("visual expression references an undeclared output", "undeclared_visual_output"),
    ("relation references an undeclared output", "undeclared_relation_output"),
    ("relations must cover every scientific pair exactly once", "scientific_relations_incomplete"),
    ("relations must name one unique scientific pair", "scientific_relation_invalid"),
    ("visual command ids must be unique", "duplicate_visual_command_id"),
    ("only circles and ellipses may be scientific", "unsupported_scientific_geometry"),
    ("ellipse safety envelopes cannot prove", "unsupported_ellipse_relation"),
    ("scientific ellipse must respond through a salient field", "scientific_salient_output_required"),
    ("non-forbid overlap and required contact require zero clearance", "relation_clearance_invalid"),
    ("physics expressions and output names must match", "physics_output_contract_mismatch"),
    ("physics expression names must be unique", "duplicate_physics_output"),
    ("assembled source exceeds 40KiB", "assembled_source_too_large"),
)


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

    channel_fields = _CAUSAL_CHANNEL_FIELDS.get(actor["kind"], {}).get(
        response["channel"],
        (),
    )
    if not channel_fields:
        raise ContractError(
            "causal channel field must directly consume its declared output"
        )

    output_reference = f'output_{response["output_name"]}'
    if not any(
        output_reference in _visual_output_names(actor[field])
        for field in channel_fields
    ):
        raise ContractError(
            "causal channel field must directly consume its declared output"
        )

    if understanding is None:
        return

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
        "rect": ("x", "y", "width", "height", "corner_radius", "line_width", "opacity"),
        "line": ("x1", "y1", "x2", "y2", "line_width", "opacity"),
        "arrow": ("x1", "y1", "x2", "y2", "line_width", "opacity"),
        "wave": ("x1", "y1", "x2", "y2", "amplitude", "wavelength", "line_width", "opacity"),
        "text": ("x", "y", "font_size", "opacity"),
    }
    declared_output_names = (
        set() if understanding is None else {f"output_{name}" for name in understanding["module_spec"]["outputs"]}
    )
    for command in commands:
        kind = command["kind"]
        if command["scientific"]:
            if kind not in {"circle", "ellipse"}:
                raise ContractError(
                    "only circles and ellipses may be scientific in visual fragment v1"
                )
            scientific_ids.append(command["id"])
            scientific_kinds[command["id"]] = kind
        consumed_outputs: set[str] = set()
        salient_outputs: set[str] = set()
        for field in numeric_fields[kind]:
            referenced_outputs = _visual_output_names(command[field])
            if understanding is not None and not referenced_outputs <= declared_output_names:
                raise ContractError("visual expression references an undeclared output")
            consumed_outputs.update(referenced_outputs)
            if field not in {"line_width"}:
                salient_outputs.update(referenced_outputs)
            _compile_visual_expression(command[field], understanding)
        if command["scientific"] and understanding is not None and not consumed_outputs:
            raise ContractError("scientific geometry must consume a declared output")
        if (
            command["scientific"]
            and kind == "ellipse"
            and understanding is not None
            and not salient_outputs
        ):
            raise ContractError("scientific ellipse must respond through a salient field")
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
    expected_pairs = {tuple(pair) for pair in combinations(sorted(scientific_ids), 2)}
    if seen_pairs != expected_pairs:
        raise ContractError("relations must cover every scientific pair exactly once")
    _validate_causal_response(document, understanding)
    return document


def _visual_expression(expression: object, understanding: dict[str, Any]) -> str:
    return f"finiteNumber({_compile_visual_expression(expression, understanding)})"


def _causal_actor_evidence(
    command: dict[str, Any],
    causal_response: dict[str, Any],
) -> str:
    if command["id"] != causal_response["actor_id"]:
        return ""
    if command["kind"] == "circle":
        visual_values = {
            "x": "cx",
            "y": "cy",
            "size": "radius",
            "opacity": "visualOpacity",
        }
        bounds = "{left:cx - radius,top:cy - radius,right:cx + radius,bottom:cy + radius,width:radius * 2,height:radius * 2}"
    else:
        visual_values = {
            "x": "cx",
            "y": "cy",
            "rotation": "rotation",
            "size": "Math.max(radiusX,radiusY)",
            "opacity": "visualOpacity",
        }
        bounds = "{left:cx - envelopeRadius,top:cy - envelopeRadius,right:cx + envelopeRadius,bottom:cy + envelopeRadius,width:envelopeRadius * 2,height:envelopeRadius * 2}"
    visual_value = visual_values[causal_response["channel"]]
    return f'''
      causalActorResponse = {{schemaVersion:"1.0",actorId:{_js(causal_response["actor_id"])},outputName:{_js(causal_response["output_name"])},channel:{_js(causal_response["channel"])},relation:{_js(causal_response["relation"])},temporalMode:{_js(causal_response["temporal_mode"])},parameterValue:finiteNumber(state.value),outputValue:finiteNumber(state.outputs[{_js(causal_response["output_name"])}]),visualValue:finiteNumber({visual_value}),fittedBounds:{bounds},timeMs:finiteNumber(visualPhase * 80)}};'''


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
    relations = _draw_relations(visual_fragment["relations"], understanding)
    primary_id = primary["id"]
    source = f'''window.LayshSimulation = Object.freeze((() => {{
  "use strict";
  let canvas = null, context = null, width = 0, height = 0, locale = "en", reducedMotion = true, emitFrame = () => {{}}, visualPhase = 0, destroyed = false;
  const parameterLimits = {_js(parameter_limits)};
  const parameterValues = {_js(parameter_defaults)};
  function finiteNumber(value) {{ const numeric = Number(value); return Number.isFinite(numeric) ? numeric : 0; }}
  function clampFinite(value, lower, upper) {{ return Math.max(finiteNumber(lower),Math.min(finiteNumber(upper),finiteNumber(value))); }}
  function clampParameter(name, value) {{ const limits = parameterLimits[name]; if (!limits) return finiteNumber(parameterValues[name]); const numeric = Number(value); const candidate = Number.isFinite(numeric) ? numeric : finiteNumber(parameterValues[name]); return clampFinite(candidate,limits[0],limits[1]); }}
  function modelOutputs(value, inputs) {{
    void value;
    return {{
{output_lines}
    }};
  }}
  /* LAYSH_SHARED_MODEL: modelState */
  function modelState(value, inputs) {{
    const clamped = clampParameter({_js(primary_id)},value);
    const closedInputs = {{...parameterValues,...(inputs || {{}}),{_js(primary_id)}:clamped}};
    const outputs = Object.freeze(modelOutputs(clamped,closedInputs));
    return {{value:clamped,normalized:(clamped - {primary["min"]}) / ({primary["max"]} - {primary["min"]}),output:outputs[{_js(outputs[0])}],outputs}};
  }}
  function drawScene(state) {{
    if (!context || !canvas) return;
    const gradient = context.createLinearGradient(0,0,0,height); gradient.addColorStop(0,{_js(visual_fragment["background"]["top_color"])}); gradient.addColorStop(1,{_js(visual_fragment["background"]["bottom_color"])});
    context.clearRect(0,0,width,height); context.fillStyle = gradient; context.fillRect(0,0,width,height);
    const scientificObjects = []; let causalActorResponse = null;
{draw_commands}
    canvas.__layshSceneGeometry = [{{schemaVersion:"1.0",phase:"post_fit",viewport:{{width:finiteNumber(width),height:finiteNumber(height),safeInset:0}},state:{{id:"rendered",timeMs:0}},objects:scientificObjects,relations:[{relations}]}}];
    /* LAYSH_CAUSAL_RESPONSE_V1 */
    canvas.__layshActorResponse = causalActorResponse;
  }}
  function render() {{ if (destroyed || !canvas || !context) return; const state = modelState(parameterValues[{_js(primary_id)}],parameterValues); const activeOutput = state.output; void activeOutput; drawScene(state); emitFrame(); }}
  return {{
    version:1,
    init(options) {{ canvas = options.canvas; context = options.context; width = options.width; height = options.height; locale = options.locale; reducedMotion = Boolean(options.reducedMotion); emitFrame = options.emitFrame; visualPhase = 0; destroyed = false; render(); }},
    setParameter(name,value,elapsedMs) {{ if (!(name in parameterValues)) return; parameterValues[name] = clampParameter(name,value); if (!reducedMotion && Number.isFinite(Number(elapsedMs)) && Number(elapsedMs) > 0) visualPhase = (visualPhase + clampFinite(Number(elapsedMs),0,80) / 80) % 1000000; render(); }},
    test(inputs) {{ const supplied = inputs && typeof inputs === "object" ? inputs : {{}}; const state = modelState(supplied[{_js(primary_id)}],supplied); return {{
{returned_outputs}
    }}; }},
    resize(nextWidth,nextHeight) {{ width = nextWidth; height = nextHeight; canvas.width = nextWidth; canvas.height = nextHeight; render(); }},
    destroy() {{ destroyed = true; canvas = null; context = null; emitFrame = () => {{}}; }},
  }};
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
