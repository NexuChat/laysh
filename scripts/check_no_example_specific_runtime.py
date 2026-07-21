#!/usr/bin/env python3
"""Reject lesson-specific correctness logic from the learner runtime.

The retained reference modules and build scripts are deliberately outside this
boundary.  Importing one of those modules from production is itself a finding.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

REFERENCE_ONLY_MODULES = frozenset(
    {
        "server/goldens.py",
        "server/physics_motion.py",
    }
)
CUSTOM_IDENTIFIER_MARKERS = frozenset(
    {
        "artifact",
        "coordinate",
        "coordinates",
        "css",
        "custom",
        "fix",
        "layout",
        "override",
        "patch",
        "position",
        "prompt",
        "radius",
        "refresh",
        "special",
        "upgrade",
        "validator",
        "x",
        "y",
    }
)
COORDINATE_KEYS = frozenset(
    {
        "anchor",
        "bottom",
        "bounds",
        "clearance",
        "cx",
        "cy",
        "height",
        "left",
        "offset",
        "position",
        "radius",
        "right",
        "top",
        "width",
        "x",
        "y",
    }
)
ALLOWED_GENERAL_VALUES = frozenset({"moon_phase_geometry"})
_REFERENCE_PATTERNS = (
    ("moon", re.compile(r"(?<![\w])moon(?:_phases?)?(?![\w])", re.IGNORECASE)),
    ("buoyancy", re.compile(r"(?<![\w])buoyancy(?![\w])", re.IGNORECASE)),
    ("pendulum", re.compile(r"(?<![\w])pendulum(?![\w])", re.IGNORECASE)),
    (
        "sound_pitch",
        re.compile(r"(?<![\w])sound[\s_-]+pitch(?![\w])", re.IGNORECASE),
    ),
    (
        "simple_circuit",
        re.compile(r"(?<![\w])(?:simple[\s_-]+)?circuit(?![\w])", re.IGNORECASE),
    ),
    (
        "day_night",
        re.compile(r"(?<![\w])day[\s_/-]+night(?![\w])", re.IGNORECASE),
    ),
    ("moon", re.compile(r"القمر")),
    ("buoyancy", re.compile(r"الطفو")),
    ("pendulum", re.compile(r"البندول")),
    ("sound_pitch", re.compile(r"درجة\s+الصوت")),
    ("simple_circuit", re.compile(r"الدائرة\s+الكهربائية|الدارة\s+الكهربائية")),
    ("day_night", re.compile(r"الليل\s+والنهار|النهار\s+والليل")),
)


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    column: int
    code: str
    detail: str


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _example_reference(value: str) -> str | None:
    if _normalized(value) in ALLOWED_GENERAL_VALUES:
        return None
    for name, pattern in _REFERENCE_PATTERNS:
        if pattern.search(value):
            return name
    return None


def _identifier_reference(identifier: str) -> str | None:
    normalized = _normalized(identifier)
    if normalized in ALLOWED_GENERAL_VALUES:
        return None
    tokens = normalized.split("_")
    token_set = frozenset(tokens)
    if "moon" in token_set:
        reference = "moon"
    elif "buoyancy" in token_set:
        reference = "buoyancy"
    elif "pendulum" in token_set:
        reference = "pendulum"
    elif "sound" in token_set and "pitch" in token_set:
        reference = "sound_pitch"
    elif "circuit" in token_set:
        reference = "simple_circuit"
    elif "day" in token_set and "night" in token_set:
        reference = "day_night"
    else:
        reference = None
    if reference is None:
        return None
    if normalized in {"moon", "buoyancy", "pendulum", "circuit"}:
        return reference
    if token_set & CUSTOM_IDENTIFIER_MARKERS:
        return reference
    return None


def _literal_references(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {
        reference
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
        if (reference := _example_reference(child.value)) is not None
    }


def _dict_has_coordinates(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Dict):
            continue
        for key in child.keys:
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and _normalized(key.value) in COORDINATE_KEYS
            ):
                return True
    return False


def _forbidden_import(module: str) -> bool:
    return any(part.startswith("golden_") for part in module.split("."))


class _RuntimeVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.findings: list[Finding] = []
        self._seen: set[tuple[int, int, str, str]] = set()

    def _add(self, node: ast.AST, code: str, detail: str) -> None:
        key = (
            getattr(node, "lineno", 1),
            getattr(node, "col_offset", 0),
            code,
            detail,
        )
        if key in self._seen:
            return
        self._seen.add(key)
        self.findings.append(
            Finding(
                path=self.relative_path,
                line=key[0],
                column=key[1],
                code=code,
                detail=detail,
            )
        )

    def _check_identifier(self, node: ast.AST, identifier: str) -> None:
        reference = _identifier_reference(identifier)
        if reference is not None:
            self._add(
                node,
                "example_specific_identifier",
                f"identifier {identifier!r} encodes the {reference!r} reference lesson",
            )

    def _check_branch(self, node: ast.AST, expression: ast.AST | None) -> None:
        for reference in sorted(_literal_references(expression)):
            self._add(
                node,
                "example_specific_branch",
                f"execution branch is keyed by the {reference!r} reference lesson",
            )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if _forbidden_import(alias.name):
                self._add(
                    node,
                    "example_specific_import",
                    f"production imports reference-only module {alias.name!r}",
                )
            self._check_identifier(node, alias.asname or alias.name.rsplit(".", 1)[-1])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if _forbidden_import(module):
            self._add(
                node,
                "example_specific_import",
                f"production imports reference-only module {module!r}",
            )
        for alias in node.names:
            self._check_identifier(node, alias.asname or alias.name)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self._check_branch(node, node.test)
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._check_branch(node, node.test)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._check_branch(node, node.test)
        self.generic_visit(node)

    def visit_match_case(self, node: ast.match_case) -> None:
        references = _literal_references(node.pattern) | _literal_references(node.guard)
        for reference in sorted(references):
            self._add(
                node.pattern,
                "example_specific_branch",
                f"match branch is keyed by the {reference!r} reference lesson",
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_identifier(node, node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_identifier(node, node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_identifier(node, node.name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self._check_identifier(node, node.id)

    def visit_arg(self, node: ast.arg) -> None:
        self._check_identifier(node, node.arg)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._check_identifier(node, node.attr)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            reference = _example_reference(key.value)
            if reference is not None and _dict_has_coordinates(value):
                self._add(
                    key,
                    "example_specific_coordinates",
                    f"coordinates are keyed by the {reference!r} reference lesson",
                )
        self.generic_visit(node)


def _production_python_files(root: Path) -> Iterable[Path]:
    server_root = root / "server"
    if not server_root.is_dir():
        return ()
    return (
        path
        for path in sorted(server_root.rglob("*.py"))
        if path.relative_to(root).as_posix() not in REFERENCE_ONLY_MODULES
        and not path.name.startswith("golden_")
    )


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _shared_validator_usage(tree: ast.Module) -> tuple[bool, bool, list[ast.AST]]:
    direct_bindings: set[str] = set()
    module_bindings: set[str] = set()
    correct_import = False
    example_imports: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "server.scene_geometry":
                for alias in node.names:
                    if alias.name == "validate_scene_geometry":
                        correct_import = True
                        direct_bindings.add(alias.asname or alias.name)
            if node.module and _forbidden_import(node.module):
                example_imports.append(node)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "server.scene_geometry":
                    correct_import = True
                    module_bindings.add(alias.asname or alias.name)
                if _forbidden_import(alias.name):
                    example_imports.append(node)

    called = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callable_name = _dotted_name(node.func)
        if callable_name in direct_bindings:
            called = True
            break
        if callable_name and any(
            callable_name == f"{binding}.validate_scene_geometry" for binding in module_bindings
        ):
            called = True
            break
    return correct_import, called, example_imports


def _shared_validator_findings(root: Path) -> list[Finding]:
    scene_path = root / "server" / "scene_geometry.py"
    generated_path = root / "server" / "verify.py"
    curated_path = root / "server" / "golden_physics_motion.py"
    if not any(path.exists() for path in (scene_path, generated_path, curated_path)):
        return []

    findings: list[Finding] = []
    if not scene_path.is_file():
        findings.append(
            Finding(
                path="server/scene_geometry.py",
                line=1,
                column=0,
                code="shared_validator_module_missing",
                detail="the shared scene validator module is absent",
            )
        )

    targets = (
        (
            generated_path,
            "generated",
            "the generated learner verification path",
        ),
        (
            curated_path,
            "curated",
            "the curated regression verification path",
        ),
    )
    for path, prefix, description in targets:
        relative = path.relative_to(root).as_posix()
        if not path.is_file():
            findings.append(
                Finding(
                    path=relative,
                    line=1,
                    column=0,
                    code=f"{prefix}_shared_validator_path_missing",
                    detail=f"{description} is absent",
                )
            )
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except SyntaxError:
            continue
        imported, called, example_imports = _shared_validator_usage(tree)
        if not imported:
            findings.append(
                Finding(
                    path=relative,
                    line=1,
                    column=0,
                    code=f"{prefix}_shared_validator_import_missing",
                    detail=f"{description} does not import validate_scene_geometry",
                )
            )
        if not called:
            findings.append(
                Finding(
                    path=relative,
                    line=1,
                    column=0,
                    code=f"{prefix}_shared_validator_call_missing",
                    detail=f"{description} does not call validate_scene_geometry",
                )
            )
        if prefix == "curated":
            findings.extend(
                Finding(
                    path=relative,
                    line=getattr(node, "lineno", 1),
                    column=getattr(node, "col_offset", 0),
                    code="curated_imports_example_validator",
                    detail="curated verification imports an example-only validator",
                )
                for node in example_imports
            )
    return findings


def audit_repository(root: Path) -> list[Finding]:
    selected_root = root.resolve()
    findings: list[Finding] = []
    for path in _production_python_files(selected_root):
        relative = path.relative_to(selected_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except SyntaxError as error:
            findings.append(
                Finding(
                    path=relative,
                    line=error.lineno or 1,
                    column=error.offset or 0,
                    code="production_ast_parse_failed",
                    detail=error.msg,
                )
            )
            continue
        visitor = _RuntimeVisitor(relative)
        visitor.visit(tree)
        findings.extend(visitor.findings)

    prompt_root = selected_root / "server" / "prompts"
    if prompt_root.is_dir():
        for path in sorted(item for item in prompt_root.rglob("*") if item.is_file()):
            reference = _example_reference(path.stem)
            if reference is not None:
                findings.append(
                    Finding(
                        path=path.relative_to(selected_root).as_posix(),
                        line=1,
                        column=0,
                        code="example_specific_prompt",
                        detail=f"prompt filename is keyed by the {reference!r} reference lesson",
                    )
                )

    findings.extend(_shared_validator_findings(selected_root))
    return sorted(findings, key=lambda item: (item.path, item.line, item.column, item.code))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail when production learner code contains reference-lesson logic."
    )
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()
    findings = audit_repository(args.root)
    print(json.dumps([asdict(finding) for finding in findings], ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
