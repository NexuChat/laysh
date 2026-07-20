from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from server.browser_verify import verify_artifact_in_browser
from server.codex_backend import CodexBackend, RuntimeContext
from server.codex_runtime import CodexExecutor, CodexRuntimeError
from server.goldens import (
    GOLDEN_FIXTURE_IDS,
    GOLDEN_ROOT,
    golden_id_for_fixture,
    load_golden_fixtures,
    review_golden_candidate,
)
from server.settings import Settings
from server.verify import verify_candidate
from server.vision_verify import evaluate_vision_verdict

ROOT = Path(__file__).parents[1]
EVIDENCE_ROOT = ROOT / "out" / "evidence" / "goldens"
SCREENSHOT_ROOT = ROOT / "out" / "evidence" / "screens" / "goldens"
CANDIDATE_ROOT = ROOT / "out" / "tmp" / "goldens"
VISION_CACHE_PATH = ROOT / "out" / "tmp" / "model-driven-vision-cache.json"
VISION_JUDGMENT_REVISION = {
    "rotates": 3,
    "oscillates": 4,
    "orbits": 2,
    "propagates": 3,
    "flows": 4,
    "floats_sinks": 2,
    "phases": 3,
}


def _replace(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"{label}: expected one source match, found {source.count(old)}")
    return source.replace(old, new, 1)


def extract_lesson_and_module(document: dict[str, Any]) -> tuple[dict[str, Any], str]:
    artifact = document["artifact"]
    lesson_marker = "<script>window.__LAYSH_LESSON__ = "
    lesson_start = artifact.index(lesson_marker) + len(lesson_marker)
    lesson_end = artifact.index(";</script>", lesson_start)
    lesson = json.loads(artifact[lesson_start:lesson_end])
    scripts = re.findall(r"<script>(.*?)</script>", artifact, flags=re.DOTALL)
    modules = [
        source
        for source in scripts
        if "window.LayshSimulation" in source and "LayshContract" not in source
    ]
    if len(modules) != 1:
        raise ValueError("pinned artifact must contain exactly one generated module")
    return lesson, modules[0]


def migrate_understanding(
    understanding: dict[str, Any], fixture_id: str
) -> dict[str, Any]:
    fixture = load_golden_fixtures()[fixture_id]
    contract = fixture["review_contract"]
    migrated = deepcopy(understanding)
    migrated["actor"] = deepcopy(contract["actor"])
    migrated["action"] = contract["action"]
    migrated["primary_parameter"]["sweep_mode"] = contract["primary_parameter"][
        "sweep_mode"
    ]
    return migrated


def _pendulum(source: str) -> str:
    source = _replace(
        source,
        "  var visualPhase = 0;\n  var trail = [];",
        "  var timeSeconds = 0;\n  var lastTrailTime = -1;\n  var trail = [];",
        "pendulum clock declaration",
    )
    source = source.replace("visualPhase * 0.7", "timeSeconds * 0.7")
    source = _replace(
        source,
        "    var amplitude = reducedMotion ? 0 : 0.105;\n"
        "    var angle = amplitude * Math.sin(visualPhase);",
        "    var amplitude = 8 * Math.PI / 180;\n"
        "    var angle = amplitude * Math.cos(2 * Math.PI * timeSeconds / period(length_m));",
        "pendulum modeled angle",
    )
    source = _replace(
        source,
        "    if (!reducedMotion) {\n"
        "      trail.push({ x: bobX, y: bobY });\n"
        "      if (trail.length > 9) {\n"
        "        trail.shift();\n"
        "      }\n"
        "    } else {\n"
        "      trail.length = 0;\n"
        "    }",
        "    if (timeSeconds !== lastTrailTime) {\n"
        "      trail.push({ x: bobX, y: bobY });\n"
        "      if (trail.length > 9) trail.shift();\n"
        "      lastTrailTime = timeSeconds;\n"
        "    }",
        "pendulum time trail",
    )
    source = _replace(
        source,
        "    context.fill();\n"
        "    context.strokeStyle = \"rgba(255,236,182,0.48)\";",
        "    context.fill();\n"
        "    context.fillStyle = \"rgb(255,193,92)\";\n"
        "    context.beginPath();\n"
        "    context.arc(bobX, bobY, bobRadius * 0.58, 0, Math.PI * 2);\n"
        "    context.fill();\n"
        "    context.strokeStyle = \"rgba(255,236,182,0.48)\";",
        "pendulum tracking core",
    )
    source = _replace(
        source,
        "      visualPhase = 0;\n      trail = [];",
        "      timeSeconds = 0;\n      lastTrailTime = -1;\n      trail = [];",
        "pendulum init clock",
    )
    source = _replace(
        source,
        "    setParameter: function (name, value) {",
        "    setParameter: function (name, value, shellTimeSeconds) {",
        "pendulum setParameter signature",
    )
    source = _replace(
        source,
        "      var same = next === length_m;\n"
        "      length_m = next;\n"
        "      if (reducedMotion) {\n"
        "        displayedLength = length_m;\n"
        "      } else if (same) {\n"
        "        visualPhase += 0.085;\n"
        "        displayedLength += (length_m - displayedLength) * 0.34;\n"
        "      } else {\n"
        "        displayedLength += (length_m - displayedLength) * 0.58;\n"
        "        trail.length = 0;\n"
        "      }",
        "      var same = next === length_m;\n"
        "      length_m = next;\n"
        "      if (Number.isFinite(Number(shellTimeSeconds))) {\n"
        "        timeSeconds = Math.max(0, Number(shellTimeSeconds));\n"
        "      }\n"
        "      if (reducedMotion) displayedLength = length_m;\n"
        "      else displayedLength += (length_m - displayedLength) * (same ? 0.34 : 0.58);\n"
        "      if (!same) trail.length = 0;",
        "pendulum shell time update",
    )
    return source


def _day_night(source: str) -> str:
    source = _replace(
        source,
        "    if (idleRedraw && !reducedMotion) visualPhase += 0.075;\n"
        "    if (!reducedMotion) {\n"
        "      displayedDeg += (rotationDeg - displayedDeg) * (idleRedraw ? 0.24 : 0.38);\n"
        "      if (Math.abs(rotationDeg - displayedDeg) < 0.02) displayedDeg = rotationDeg;\n"
        "    } else {\n"
        "      displayedDeg = rotationDeg;\n"
        "    }",
        "    if (idleRedraw && !reducedMotion) visualPhase += 0.075;\n"
        "    displayedDeg = rotationDeg;",
        "day-night exact modeled angle",
    )
    source = _replace(
        source,
        "  function alignmentFor(degrees) {\n"
        "    var value = Math.cos(degrees * Math.PI / 180);\n"
        "    return Math.abs(value) < 1e-12 ? 0 : value;\n"
        "  }",
        "  function earthModel(degrees) {\n"
        "    var angleRad = degrees * Math.PI / 180;\n"
        "    var alignment = Math.cos(angleRad);\n"
        "    if (Math.abs(alignment) < 1e-12) alignment = 0;\n"
        "    return {angleRad: angleRad, lightAlignment: alignment, "
        "daylight: alignment > 0 ? 1 : 0};\n"
        "  }",
        "day-night model",
    )
    source = _replace(
        source,
        "  function render(idleRedraw) {",
        "  function drawSurfaceFeature(earthX, earthY, earthR, theta, longitude, latitude, "
        "color, tracked) {\n"
        "    var phase = theta + longitude;\n"
        "    var visibility = Math.cos(phase);\n"
        "    if (visibility <= 0) return;\n"
        "    var x = earthX + earthR * 0.78 * Math.sin(phase);\n"
        "    var y = earthY + earthR * latitude;\n"
        "    context.fillStyle = color;\n"
        "    context.beginPath();\n"
        "    context.ellipse(x, y, earthR * 0.19 * Math.max(0.18, visibility), "
        "earthR * 0.13, -0.25, 0, Math.PI * 2);\n"
        "    context.fill();\n"
        "    if (tracked) {\n"
        "      context.fillStyle = \"rgb(92,196,105)\";\n"
        "      context.beginPath();\n"
        "      context.arc(x, y, Math.max(5, earthR * 0.065), 0, Math.PI * 2);\n"
        "      context.fill();\n"
        "    }\n"
        "  }\n\n"
        "  function render(idleRedraw) {",
        "day-night surface helper",
    )
    source = _replace(
        source,
        "    var i;\n\n    context.clearRect(0, 0, w, h);",
        "    var i;\n"
        "    var model = earthModel(displayedDeg);\n"
        "    var theta = model.angleRad;\n\n"
        "    context.clearRect(0, 0, w, h);",
        "day-night early model state",
    )
    source = _replace(
        source,
        "    context.save();\n"
        "    context.beginPath();\n"
        "    context.arc(earthX, earthY, earthR, 0, Math.PI * 2);\n"
        "    context.clip();",
        "    context.save();\n"
        "    context.beginPath();\n"
        "    context.arc(earthX, earthY, earthR, 0, Math.PI * 2);\n"
        "    context.clip();",
        "day-night model state",
    )
    source = _replace(
        source,
        "    context.fill();\n\n"
        "    var castShadow = context.createLinearGradient(earthX + earthR * 0.72, 0, w, 0);",
        "    context.fill();\n\n"
        "    var alignmentLevel = (model.lightAlignment + 1) / 2;\n"
        "    var gaugeX = earthX - earthR - Math.max(16, 22 * scale);\n"
        "    var gaugeY = earthY - earthR;\n"
        "    roundedRect(gaugeX, gaugeY, Math.max(9, 12 * scale), earthR * 2, 5);\n"
        "    context.fillStyle = \"rgba(4,12,25,0.82)\";\n"
        "    context.fill();\n"
        "    roundedRect(gaugeX, gaugeY + earthR * 2 * (1 - alignmentLevel), "
        "Math.max(9, 12 * scale), earthR * 2 * alignmentLevel, 5);\n"
        "    context.fillStyle = \"rgba(255,225,125,0.92)\";\n"
        "    context.fill();\n\n"
        "    var castShadow = context.createLinearGradient(earthX + earthR * 0.72, 0, w, 0);",
        "day-night central alignment gauge",
    )
    source = _replace(
        source,
        "    context.fillStyle = \"rgba(79,150,91,0.74)\";\n"
        "    context.beginPath();\n"
        "    context.arc(earthX - earthR * 0.39, earthY - earthR * 0.23, "
        "earthR * 0.18, 0, Math.PI * 2);\n"
        "    context.arc(earthX - earthR * 0.24, earthY + earthR * 0.31, "
        "earthR * 0.16, 0, Math.PI * 2);\n"
        "    context.fill();",
        "    drawSurfaceFeature(earthX, earthY, earthR, theta, -Math.PI / 3, -0.22, "
        "\"rgb(57,132,73)\", false);\n"
        "    drawSurfaceFeature(earthX, earthY, earthR, theta, Math.PI / 5, 0.25, "
        "\"rgb(63,137,78)\", false);\n"
        "    drawSurfaceFeature(earthX, earthY, earthR, theta, Math.PI * 0.82, -0.05, "
        "\"rgb(72,151,82)\", false);",
        "day-night rotating continents",
    )
    source = _replace(
        source,
        "    var terminator = context.createLinearGradient(earthX - earthR, 0, "
        "earthX + earthR, 0);\n"
        "    terminator.addColorStop(0, \"rgba(255,238,170,0.12)\");\n"
        "    terminator.addColorStop(0.42, \"rgba(3,12,29,0.08)\");\n"
        "    terminator.addColorStop(0.58, \"rgba(1,6,18,0.68)\");\n"
        "    terminator.addColorStop(1, \"rgba(0,2,10,0.94)\");\n"
        "    context.fillStyle = terminator;\n"
        "    context.fillRect(earthX - earthR, earthY - earthR, earthR * 2, earthR * 2);",
        "    context.fillStyle = \"rgba(0,2,12,0.82)\";\n"
        "    context.fillRect(earthX, earthY - earthR, earthR, earthR * 2);\n"
        "    context.fillStyle = \"rgba(255,226,132,0.12)\";\n"
        "    context.fillRect(earthX - earthR, earthY - earthR, earthR, earthR * 2);\n"
        "    context.strokeStyle = \"rgba(226,242,255,0.94)\";\n"
        "    context.lineWidth = Math.max(2, 3 * scale);\n"
        "    context.beginPath();\n"
        "    context.moveTo(earthX, earthY - earthR);\n"
        "    context.lineTo(earthX, earthY + earthR);\n"
        "    context.stroke();\n"
        "    drawSurfaceFeature(earthX, earthY, earthR, theta, -Math.PI / 3, -0.22, "
        "\"rgba(0,0,0,0)\", true);",
        "day-night crisp terminator",
    )
    old_marker = (
        "    var theta = displayedDeg * Math.PI / 180;\n"
        "    var markerX = earthX - Math.cos(theta) * earthR * 0.91;\n"
        "    var markerY = earthY - Math.sin(theta) * earthR * 0.91;\n"
        "    var alignment = alignmentFor(displayedDeg);\n"
        "    var isDay = alignment > 0;\n"
        "    var pulse = reducedMotion ? 1 : 1 + 0.08 * Math.sin(visualPhase * 1.7);"
    )
    new_marker = (
        "    var markerX = earthX + Math.sin(theta) * earthR * 0.88;\n"
        "    var markerY = earthY - earthR * 0.04;\n"
        "    var alignment = model.lightAlignment;\n"
        "    var isDay = model.daylight === 1;\n"
        "    var horizonMoment = Math.abs(alignment) < 0.12;\n"
        "    var pulse = horizonMoment ? 1.35 : 1 + 0.08 * Math.sin(visualPhase * 1.7);"
    )
    source = _replace(source, old_marker, new_marker, "day-night location model")
    source = _replace(
        source,
        "    context.arc(markerX, markerY, Math.max(4, 6 * scale), 0, Math.PI * 2);",
        "    context.arc(markerX, markerY, Math.max(8, 10 * scale), 0, Math.PI * 2);",
        "day-night larger location marker",
    )
    source = _replace(
        source,
        "    context.strokeStyle = \"rgba(228,240,255,0.36)\";",
        "    context.save();\n"
        "    context.globalAlpha = Math.cos(theta) >= -0.02 ? 1 : 0;\n"
        "    context.strokeStyle = \"rgba(228,240,255,0.36)\";",
        "day-night marker front hemisphere",
    )
    source = _replace(
        source,
        "    context.arc(markerX, markerY, Math.max(8, 10 * scale), 0, Math.PI * 2);\n"
        "    context.fill();\n\n"
        "    var chipW",
        "    context.arc(markerX, markerY, Math.max(8, 10 * scale), 0, Math.PI * 2);\n"
        "    context.fill();\n"
        "    context.restore();\n\n"
        "    var chipW",
        "day-night marker visibility restore",
    )
    source = _replace(
        source,
        "    context.lineWidth = Math.max(1, scale);\n"
        "    context.stroke();\n\n"
        "    context.textAlign = \"center\";",
        "    context.lineWidth = Math.max(1, scale);\n"
        "    context.stroke();\n"
        "    roundedRect(chipX + 12, chipY + chipH - 10, "
        "(chipW - 24) * (alignment + 1) / 2, 5, 2);\n"
        "    context.fillStyle = \"rgba(255,225,125,0.88)\";\n"
        "    context.fill();\n\n"
        "    context.textAlign = \"center\";",
        "day-night modeled alignment bar",
    )
    source = _replace(
        source,
        "locale === \"ar\" ? (isDay ? \"المكان في النهار\" : "
        "\"المكان في الليل\") : (isDay ? \"Location: daylight\" : "
        "\"Location: night\")",
        "locale === \"ar\" ? (horizonMoment ? \"لحظة شروق أو غروب\" : "
        "(isDay ? \"المكان في النهار\" : \"المكان في الليل\")) : "
        "(horizonMoment ? \"Sunrise / sunset\" : "
        "(isDay ? \"Location: daylight\" : \"Location: night\"))",
        "day-night horizon copy",
    )
    source = _replace(
        source,
        "    var lightAlignment = alignmentFor(degrees);\n"
        "    return {\n"
        "      light_alignment: lightAlignment,\n"
        "      daylight: lightAlignment > 0 ? 1 : 0\n"
        "    };",
        "    var model = earthModel(degrees);\n"
        "    return {\n"
        "      light_alignment: model.lightAlignment,\n"
        "      daylight: model.daylight\n"
        "    };",
        "day-night tested model",
    )
    return source


def _moon(source: str) -> str:
    return _replace(
        source,
        "    moon(moonX, moonY, moonR, angleDeg, false);\n    ctx.restore();",
        "    moon(moonX, moonY, moonR, angleDeg, false);\n"
        "    ctx.fillStyle = 'rgb(255,118,92)';\n"
        "    ctx.beginPath();\n"
        "    ctx.arc(moonX, moonY, Math.max(3, moonR * 0.32), 0, Math.PI * 2);\n"
        "    ctx.fill();\n"
        "    ctx.restore();",
        "moon tracking core",
    )


def _buoyancy(source: str) -> str:
    source = _replace(
        source,
        "    context.restore();\n\n    if (bodyY + bodySize > waterY) {",
        "    context.restore();\n\n"
        "    context.save();\n"
        "    roundedRect(bodyX, bodyY, bodySize, bodySize, bodySize * 0.14);\n"
        "    context.strokeStyle = 'rgb(244,165,72)';\n"
        "    context.lineWidth = Math.max(4, bodySize * 0.055);\n"
        "    context.stroke();\n"
        "    context.restore();\n\n"
        "    if (bodyY + bodySize > waterY) {",
        "buoyancy actor signature",
    )
    return _replace(
        source,
        "    context.restore();\n\n"
        "    context.save();\n"
        "    context.fillStyle = 'rgba(1,18,31,0.34)';",
        "    context.restore();\n\n"
        "    context.strokeStyle = 'rgb(52,211,235)';\n"
        "    context.lineWidth = 3;\n"
        "    context.beginPath();\n"
        "    context.moveTo(0, waterY);\n"
        "    context.lineTo(width, waterY);\n"
        "    context.stroke();\n\n"
        "    context.save();\n    context.fillStyle = 'rgba(1,18,31,0.34)';",
        "buoyancy waterline signature",
    )


def _sound(source: str) -> str:
    source = _replace(
        source,
        "  var frequency = 440, displayedFrequency = 440, visualPhase = 0, initialized = false;",
        "  var frequency = 440, displayedFrequency = 440, visualPhase = 0, "
        "timeSeconds = 0, initialized = false;",
        "sound clock declaration",
    )
    source = _replace(
        source,
        "    var phaseShift = reducedMotion ? 0 : visualPhase * "
        "(0.45 + displayedFrequency / 880 * 0.35);",
        "    var phaseShift = 2 * Math.PI * timeSeconds / (1 / frequency);",
        "sound modeled phase",
    )
    source = source.replace(
        'trail === 0 ? "rgba(102,226,255,0.96)"',
        'trail === 0 ? "rgb(103,232,249)"',
    )
    source = _replace(
        source,
        "    setParameter: function (name, value) {",
        "    setParameter: function (name, value, shellTimeSeconds) {",
        "sound setParameter signature",
    )
    return _replace(
        source,
        "      frequency = next;\n      safeDraw(same);",
        "      frequency = next;\n"
        "      if (Number.isFinite(Number(shellTimeSeconds))) {\n"
        "        timeSeconds = Math.max(0, Number(shellTimeSeconds));\n"
        "      }\n"
        "      safeDraw(same);",
        "sound shell time update",
    )


def _circuit(source: str) -> str:
    source = _replace(
        source,
        "  var visualPhase = 0;",
        "  var visualPhase = 0;\n  var timeSeconds = 0;",
        "circuit clock declaration",
    )
    source = _replace(
        source,
        "    var phase = visualPhase * (0.35 + current * 0.55);",
        "    var phase = timeSeconds * current * 0.30;",
        "circuit modeled flow",
    )
    source = _replace(
        source,
        "      var d = ((i / 9 + phase * 0.025) % 1) * perimeter;",
        "      var d = ((i / 9 + phase) % 1) * perimeter;",
        "circuit particle position",
    )
    source = _replace(
        source,
        '      ctx.fillStyle = "rgba(146,231,255," + (0.32 + pulse * 0.48) + ")";',
        '      ctx.fillStyle = i === 0 ? "rgb(97,241,196)" : '
        '"rgba(146,231,255," + (0.32 + pulse * 0.48) + ")";',
        "circuit tracking charge",
    )
    source = _replace(
        source,
        '      call("arc", px, py, Math.max(2, boardW * 0.0033), 0, Math.PI * 2);',
        '      call("arc", px, py, i === 0 ? Math.max(7, boardW * 0.011) : '
        'Math.max(2, boardW * 0.0033), 0, Math.PI * 2);',
        "circuit visible lead charge",
    )
    source = _replace(
        source,
        "  function setParameter(name, value) {",
        "  function setParameter(name, value, shellTimeSeconds) {",
        "circuit setParameter signature",
    )
    return _replace(
        source,
        "    resistance = next;\n    redraw(sameValue);",
        "    resistance = next;\n"
        "    if (Number.isFinite(Number(shellTimeSeconds))) {\n"
        "      timeSeconds = Math.max(0, Number(shellTimeSeconds));\n"
        "    }\n"
        "    redraw(sameValue);",
        "circuit shell time update",
    )


def _phenomenon_clock_upgrade(base: str, source: str) -> str:
    if "Laysh phenomenon-clock contract r1" in source:
        return source
    source = source.replace(
        "  'use strict';",
        "  'use strict';\n  // Laysh phenomenon-clock contract r1",
        1,
    ) if "  'use strict';" in source else source.replace(
        '  "use strict";',
        '  "use strict";\n  // Laysh phenomenon-clock contract r1',
        1,
    ) if '  "use strict";' in source else source.replace(
        "window.LayshSimulation = (function () {",
        "window.LayshSimulation = (function () {\n  // Laysh phenomenon-clock contract r1",
        1,
    )
    if base == "pendulum":
        return _replace(
            source,
            "    var amplitude = 8 * Math.PI / 180;",
            "    var amplitude = 12 * Math.PI / 180;",
            "pendulum legible physical amplitude",
        )
    if base == "day_night":
        source = _replace(
            source,
            "  var visualPhase = 0;",
            "  var visualPhase = 0;\n  var phenomenonTimeSeconds = 0;",
            "day-night phenomenon clock",
        )
        source = _replace(
            source,
            "    var theta = model.angleRad;",
            "    var theta = model.angleRad + phenomenonTimeSeconds * Math.PI * 2 / 10;",
            "day-night legible rotation",
        )
        source = _replace(
            source,
            "earthR * 0.19 * Math.max(0.18, visibility), earthR * 0.13,",
            "earthR * 0.30 * Math.max(0.18, visibility), earthR * 0.20,",
            "day-night legible surface feature",
        )
        source = _replace(
            source,
            "Math.max(5, earthR * 0.065)",
            "Math.max(7, earthR * 0.11)",
            "day-night legible tracked feature",
        )
        source = _replace(
            source,
            "    visualPhase = 0;\n    draw(false);",
            "    visualPhase = 0;\n    phenomenonTimeSeconds = 0;\n    draw(false);",
            "day-night init clock",
        )
        source = _replace(
            source,
            "  function setParameter(name, value) {",
            "  function setParameter(name, value, shellPhenomenonTimeSeconds) {",
            "day-night time signature",
        )
        return _replace(
            source,
            "    rotationDeg = next;\n    if (reducedMotion) displayedDeg = rotationDeg;",
            "    rotationDeg = next;\n"
            "    if (Number.isFinite(Number(shellPhenomenonTimeSeconds))) {\n"
            "      phenomenonTimeSeconds = Math.max(0, Number(shellPhenomenonTimeSeconds));\n"
            "    }\n"
            "    if (reducedMotion) displayedDeg = rotationDeg;",
            "day-night clock update",
        )
    if base == "moon_phases":
        source = _replace(
            source,
            "  var angleDeg = 90;",
            "  var angleDeg = 90;\n  var phenomenonTimeSeconds = 0;",
            "moon phenomenon clock",
        )
        source = _replace(
            source,
            "    var a = phase(angleDeg) * Math.PI / 180;",
            "    var a = phase(angleDeg + phenomenonTimeSeconds * 360 / 12) * Math.PI / 180;",
            "moon legible orbit",
        )
        source = _replace(
            source,
            "    angleDeg = 90;\n    draw();",
            "    angleDeg = 90;\n    phenomenonTimeSeconds = 0;\n    draw();",
            "moon init clock",
        )
        source = _replace(
            source,
            "  function setParameter(name, value) {",
            "  function setParameter(name, value, shellPhenomenonTimeSeconds) {",
            "moon time signature",
        )
        return _replace(
            source,
            "      angleDeg = phase(value);\n      draw();",
            "      angleDeg = phase(value);\n"
            "      if (Number.isFinite(Number(shellPhenomenonTimeSeconds))) {\n"
            "        phenomenonTimeSeconds = Math.max(0, Number(shellPhenomenonTimeSeconds));\n"
            "      }\n"
            "      draw();",
            "moon clock update",
        )
    if base == "buoyancy":
        source = _replace(
            source,
            "  var visualPhase = 0;",
            "  var visualPhase = 0;\n  var phenomenonTimeSeconds = 0;",
            "buoyancy phenomenon clock",
        )
        source = _replace(
            source,
            "    var phase = reducedMotion ? 0 : visualPhase;",
            "    var phase = reducedMotion ? 0 : phenomenonTimeSeconds * Math.PI * 2 / 2.4;",
            "buoyancy physical bob phase",
        )
        source = _replace(
            source,
            "    } else {\n      bodyY = waterY;\n    }",
            "    } else {\n      bodyY = waterY;\n    }\n"
            "    if (fraction >= 0.98) {\n"
            "      bodyY += Math.min(7, bodySize * 0.06);\n"
            "    }",
            "buoyancy legible bob",
        )
        source = _replace(
            source,
            "      visualPhase = 0;\n      safeDraw();",
            "      visualPhase = 0;\n      phenomenonTimeSeconds = 0;\n      safeDraw();",
            "buoyancy init clock",
        )
        source = _replace(
            source,
            "    setParameter: function (name, value) {",
            "    setParameter: function (name, value, shellPhenomenonTimeSeconds) {",
            "buoyancy time signature",
        )
        return _replace(
            source,
            "      density = next;\n      redraw(changed);",
            "      density = next;\n"
            "      if (Number.isFinite(Number(shellPhenomenonTimeSeconds))) {\n"
            "        phenomenonTimeSeconds = Math.max(0, Number(shellPhenomenonTimeSeconds));\n"
            "      }\n"
            "      redraw(changed);",
            "buoyancy clock update",
        )
    if base == "sound_pitch":
        return _replace(
            source,
            "    context.restore();\n\n    var lambdaPixels = waveW / cycles;",
            "    context.restore();\n\n"
            "    var packetProgress = (timeSeconds * 0.12) % 1;\n"
            "    var packetX = startX + packetProgress * waveW;\n"
            "    var packetT = (packetX - startX) / waveW;\n"
            "    var packetEnvelope = Math.sin(Math.PI * Math.min(1, packetT * 1.12));\n"
            "    var packetY = cy + Math.sin(packetT * Math.PI * 2 * cycles - phaseShift) "
            "* amp * packetEnvelope;\n"
            "    context.fillStyle = \"rgb(103,232,249)\";\n"
            "    context.beginPath();\n"
            "    context.arc(packetX, packetY, Math.max(6, amp * 0.13), 0, Math.PI * 2);\n"
            "    context.fill();\n\n"
            "    var lambdaPixels = waveW / cycles;",
            "sound legible physical wave packet",
        )
    if base == "simple_circuit":
        return source
    raise ValueError(f"unsupported phenomenon-clock module: {base}")


def _overlay_safe_band(base: str, source: str) -> str:
    marker = "registerOverlayRect = function () {};"
    if marker in source:
        return source
    if base == "buoyancy":
        source = _replace(
            source,
            "      bodyY = waterY + (height - waterY - bodySize - 24 * scale) * "
            "clamp((d - 1000) / 250, 0, 1);",
            "      bodyY = waterY;",
            "buoyancy single-source submerged position",
        )
        source = _replace(
            source,
            "  var emitFrame = null;",
            "  var emitFrame = null;\n  var registerOverlayRect = function () {};",
            "buoyancy overlay callback",
        )
        source = _replace(
            source,
            "  function chip(x, y, w, h, text, accent) {\n    context.save();",
            "  function chip(x, y, w, h, text, accent, role) {\n"
            "    if (width < 420) return;\n"
            "    registerOverlayRect({x: x, y: y, width: w, height: h, "
            "role: role || 'readout'});\n"
            "    context.save();",
            "buoyancy registered chip",
        )
        source = _replace(
            source,
            "    var chipW = Math.min(width * 0.42, 220);\n"
            "    var chipX = clamp(bodyX + bodySize + 18, 12, width - chipW - 12);\n"
            "    var chipY = clamp(bodyY + bodySize * 0.14, 14, height - 126);\n"
            "    chip(chipX, chipY, chipW, 38, densityText, 'rgba(120,225,236,0.50)');\n"
            "    chip(chipX, chipY + 44, chipW, 38, fractionText, 'rgba(120,225,236,0.50)');\n"
            "    chip(chipX, chipY + 88, chipW, 34, status, "
            "floats ? 'rgba(116,240,185,0.66)' : 'rgba(255,151,112,0.68)');",
            "    var chipGap = 8;\n"
            "    var chipW = Math.min(220, (width - 24 - chipGap * 2) / 3);\n"
            "    var chipX = (width - chipW * 3 - chipGap * 2) / 2;\n"
            "    var chipY = 12;\n"
            "    chip(chipX, chipY, chipW, 38, densityText, 'rgba(120,225,236,0.50)');\n"
            "    chip(chipX + chipW + chipGap, chipY, chipW, 38, fractionText, "
            "'rgba(120,225,236,0.50)');\n"
            "    chip(chipX + (chipW + chipGap) * 2, chipY, chipW, 38, status, "
            "floats ? 'rgba(116,240,185,0.66)' : 'rgba(255,151,112,0.68)', "
            "'essential-state');",
            "buoyancy top safe band",
        )
        return _replace(
            source,
            "      emitFrame = typeof options.emitFrame === 'function' ? options.emitFrame : null;",
            "      emitFrame = typeof options.emitFrame === 'function' ? "
            "options.emitFrame : null;\n"
            "      registerOverlayRect = typeof options.registerOverlayRect === 'function' "
            "? options.registerOverlayRect : function () {};",
            "buoyancy init overlay callback",
        )
    if base == "day_night":
        source = _replace(
            source,
            "    var markerX = earthX + Math.sin(theta) * earthR * 0.88;",
            "    var markerX = earthX - Math.sin(theta) * earthR * 0.88;",
            "day-night location marker illuminated hemisphere",
        )
        source = _replace(
            source,
            "  var emitFrame = null;",
            "  var emitFrame = null;\n  var registerOverlayRect = function () {};",
            "day-night overlay callback",
        )
        source = _replace(
            source,
            "    var chipW = Math.max(174, Math.min(238 * scale, w * 0.4));",
            "    if (w < 420) return;\n"
            "    var chipW = Math.max(174, Math.min(238 * scale, w * 0.4));",
            "day-night mobile label collapse",
        )
        source = _replace(
            source,
            "    var chipY = Math.min(h - chipH - 14, earthY + earthR + 22 * scale);\n"
            "    roundedRect(chipX, chipY, chipW, chipH, Math.max(12, 16 * scale));",
            "    var chipY = h - chipH - 14;\n"
            "    registerOverlayRect({x: chipX, y: chipY, width: chipW, height: chipH, "
            "role: 'essential-state'});\n"
            "    roundedRect(chipX, chipY, chipW, chipH, Math.max(12, 16 * scale));",
            "day-night bottom safe band",
        )
        return _replace(
            source,
            "    emitFrame = typeof options.emitFrame === \"function\" ? options.emitFrame : null;",
            "    emitFrame = typeof options.emitFrame === \"function\" ? "
            "options.emitFrame : null;\n"
            "    registerOverlayRect = typeof options.registerOverlayRect === \"function\" "
            "? options.registerOverlayRect : function () {};",
            "day-night init overlay callback",
        )
    if base == "moon_phases":
        source = _replace(
            source,
            "  var emitFrame = function () {};",
            "  var emitFrame = function () {};\n  var registerOverlayRect = function () {};",
            "moon overlay callback",
        )
        source = _replace(
            source,
            "  function text(value, x, y, size, align, color, weight) {\n"
            "    if (typeof ctx.fillText !== 'function') return;",
            "  function text(value, x, y, size, align, color, weight) {\n"
            "    if (width < 420 || typeof ctx.fillText !== 'function') return;",
            "moon mobile label collapse",
        )
        source = _replace(
            source,
            "  function chip(x, y, w, h, title, value, fill) {\n    var rtl = arabic();",
            "  function chip(x, y, w, h, title, value, fill) {\n"
            "    if (width < 420) return;\n"
            "    registerOverlayRect({x: x, y: y, width: w, height: h, role: 'readout'});\n"
            "    var rtl = arabic();",
            "moon registered chip",
        )
        source = _replace(
            source,
            "    var fractionY = Math.min(height - fractionH - 45, cy + radius + 18);",
            "    var fractionY = 12;",
            "moon fraction top safe band",
        )
        source = _replace(
            source,
            "    chip(Math.max(12, Math.min(width - angleW - 12, width * 0.025)), "
            "Math.min(height - angleH - 44, height * 0.79), angleW, angleH,",
            "    chip(12, 12, angleW, angleH,",
            "moon angle top safe band",
        )
        return _replace(
            source,
            "    emitFrame = typeof options.emitFrame === 'function' ? "
            "options.emitFrame : function () {};",
            "    emitFrame = typeof options.emitFrame === 'function' ? "
            "options.emitFrame : function () {};\n"
            "    registerOverlayRect = typeof options.registerOverlayRect === 'function' "
            "? options.registerOverlayRect : function () {};",
            "moon init overlay callback",
        )
    if base == "pendulum":
        source = _replace(
            source,
            "  var emitFrame = null;",
            "  var emitFrame = null;\n  var registerOverlayRect = function () {};",
            "pendulum overlay callback",
        )
        source = _replace(
            source,
            "  function chip(x, y, w, h, title, value, accent) {\n    context.save();",
            "  function chip(x, y, w, h, title, value, accent) {\n"
            "    if (width < 420) return;\n"
            "    registerOverlayRect({x: x, y: y, width: w, height: h, role: 'readout'});\n"
            "    context.save();",
            "pendulum registered chip",
        )
        source = _replace(
            source,
            "      if (tick === 9) {",
            "      if (tick === 9 && width >= 420) {",
            "pendulum mobile ruler label collapse",
        )
        source = _replace(
            source,
            "    var chipX = clamp(bobX + bobRadius + 13, 10, width - chipW - 10);\n"
            "    var chipY = clamp(bobY - chipH * 0.5, 10, height - chipH - 10);",
            "    var chipX = width - chipW - 12;\n    var chipY = 12;",
            "pendulum period top safe band",
        )
        return _replace(
            source,
            "      emitFrame = typeof options.emitFrame === \"function\" ? "
            "options.emitFrame : null;",
            "      emitFrame = typeof options.emitFrame === \"function\" ? "
            "options.emitFrame : null;\n"
            "      registerOverlayRect = typeof options.registerOverlayRect === \"function\" "
            "? options.registerOverlayRect : function () {};",
            "pendulum init overlay callback",
        )
    if base == "sound_pitch":
        source = _replace(
            source,
            "  var locale = \"ar\", reducedMotion = false, emitFrame = null;",
            "  var locale = \"ar\", reducedMotion = false, emitFrame = null;\n"
            "  var registerOverlayRect = function () {};",
            "sound overlay callback",
        )
        source = _replace(
            source,
            "  function chip(x, y, w, label, value, accent) {\n    context.save();",
            "  function chip(x, y, w, label, value, accent) {\n"
            "    if (width < 420) return;\n"
            "    registerOverlayRect({x: x, y: y, width: w, height: 48, role: 'readout'});\n"
            "    context.save();",
            "sound registered chip",
        )
        source = _replace(
            source,
            "    context.fillText(\"λ\", bx + lambdaPixels / 2, by - 10);",
            "    if (w >= 420) context.fillText(\"λ\", bx + lambdaPixels / 2, by - 10);",
            "sound mobile wavelength label collapse",
        )
        source = _replace(
            source,
            "    context.fillText(\"سرعة الصوت ثابتة: 343 m/s  ·  "
            "التردد يغيّر الحدّة لا الشدة\", w / 2, Math.min(h - 15, floorY + 27));",
            "    if (w >= 420) context.fillText(\"سرعة الصوت ثابتة: 343 m/s  ·  "
            "التردد يغيّر الحدّة لا الشدة\", w / 2, "
            "Math.min(h - 15, floorY + 27));",
            "sound Arabic mobile footer collapse",
        ) if "سرعة الصوت ثابتة" in source else _replace(
            source,
            "    context.fillText(\"Sound speed is fixed: 343 m/s  ·  "
            "frequency changes pitch, not loudness\", w / 2, "
            "Math.min(h - 15, floorY + 27));",
            "    if (w >= 420) context.fillText(\"Sound speed is fixed: 343 m/s  ·  "
            "frequency changes pitch, not loudness\", w / 2, "
            "Math.min(h - 15, floorY + 27));",
            "sound English mobile footer collapse",
        )
        return _replace(
            source,
            "      emitFrame = options.emitFrame;",
            "      emitFrame = options.emitFrame;\n"
            "      registerOverlayRect = typeof options.registerOverlayRect === \"function\" "
            "? options.registerOverlayRect : function () {};",
            "sound init overlay callback",
        )
    if base == "simple_circuit":
        source = _replace(
            source,
            "  var emitFrame = function () {};",
            "  var emitFrame = function () {};\n  var registerOverlayRect = function () {};",
            "circuit overlay callback",
        )
        source = _replace(
            source,
            "  function label(text, x, y, size, color, align) {",
            "  function label(text, x, y, size, color, align) {\n"
            "    if (width < 420) return;",
            "circuit mobile label collapse",
        )
        source = _replace(
            source,
            "  function chip(x, y, w, h, top, bottom, accent) {\n    call(\"save\");",
            "  function chip(x, y, w, h, top, bottom, accent) {\n"
            "    if (width < 420) return;\n"
            "    registerOverlayRect({x: x, y: y, width: w, height: h, role: 'readout'});\n"
            "    call(\"save\");",
            "circuit registered chip",
        )
        return _replace(
            source,
            "    emitFrame = typeof options.emitFrame === \"function\" ? "
            "options.emitFrame : function () {};",
            "    emitFrame = typeof options.emitFrame === \"function\" ? "
            "options.emitFrame : function () {};\n"
            "    registerOverlayRect = typeof options.registerOverlayRect === \"function\" "
            "? options.registerOverlayRect : function () {};",
            "circuit init overlay callback",
        )
    raise ValueError(f"unsupported overlay safe-band module: {base}")


def rederive_module(golden_id: str, source: str) -> str:
    base = golden_id.removesuffix("_en")
    derived_markers = {
        "pendulum": "var amplitude = 8 * Math.PI / 180;",
        "day_night": "function earthModel(degrees)",
        "moon_phases": "ctx.fillStyle = 'rgb(255,118,92)'",
        "buoyancy": "context.strokeStyle = 'rgb(244,165,72)'",
        "sound_pitch": "var phaseShift = 2 * Math.PI * timeSeconds",
        "simple_circuit": "var phase = timeSeconds * current * 0.30;",
    }
    transforms = {
        "pendulum": _pendulum,
        "day_night": _day_night,
        "moon_phases": _moon,
        "buoyancy": _buoyancy,
        "sound_pitch": _sound,
        "simple_circuit": _circuit,
    }
    if derived_markers[base] not in source:
        source = transforms[base](source)
    source = _overlay_safe_band(base, source)
    return _phenomenon_clock_upgrade(base, source)


def load_rederived(golden_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    document = json.loads((GOLDEN_ROOT / f"{golden_id}.json").read_text(encoding="utf-8"))
    understanding, source = extract_lesson_and_module(document)
    locale_suffix = "en" if golden_id.endswith("_en") else "ar"
    fixture_id = f"{golden_id.removesuffix('_en')}_{locale_suffix}"
    understanding = migrate_understanding(understanding, fixture_id)
    module_output = {
        "module_js": rederive_module(golden_id, source),
        "output_names": list(understanding["module_spec"]["outputs"]),
        "brief_summary": document["review"]["automated"].get(
            "brief_summary", "Re-derived verified simulation module."
        ),
        "assumptions": list(document["review"]["reference_contract"]["assumptions"]),
    }
    return understanding, module_output


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


async def _semantic_vision(
    backend: CodexBackend,
    understanding: dict[str, Any],
    frames: tuple[bytes, ...],
    fixture_id: str,
    frame_states: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(frames) != 5:
        raise ValueError(f"{fixture_id}: browser gate did not capture five vision frames")
    with tempfile.TemporaryDirectory(prefix="laysh-curated-vision-") as temporary:
        image_paths = []
        for index, frame in enumerate(frames, start=1):
            path = Path(temporary) / f"frame-{index}.png"
            path.write_bytes(frame)
            image_paths.append(path)
        for attempt in (1, 2):
            try:
                execution = await backend.vision(
                    understanding,
                    image_paths,
                    frame_states,
                    runtime_context=RuntimeContext(
                        public=False,
                        evidence_fixture_id=fixture_id,
                    ),
                )
                return execution.data
            except CodexRuntimeError as error:
                if error.code != "stage_timeout" or attempt == 2:
                    raise
    raise RuntimeError("vision retry loop ended without a verdict")


def _spotcheck(artifact: str, golden_id: str) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        raise ValueError("Node is required for curated screenshot evidence")
    with tempfile.TemporaryDirectory(prefix="laysh-model-driven-spotcheck-") as temporary:
        artifact_path = Path(temporary) / f"{golden_id}.html"
        artifact_path.write_text(artifact, encoding="utf-8")
        report_path = EVIDENCE_ROOT / f"{golden_id}-browser.json"
        completed = subprocess.run(  # noqa: S603 - resolved Node and repository verifier
            [
                node,
                str(ROOT / "scripts" / "check_golden.mjs"),
                str(artifact_path),
                str(SCREENSHOT_ROOT),
                golden_id,
                str(report_path),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
    if completed.returncode != 0:
        raise ValueError(f"{golden_id}: screenshot check failed: {completed.stderr.strip()}")
    report = json.loads(completed.stdout)
    passed = (
        report.get("ready") is True
        and report.get("runtimeError") is False
        and report.get("externalRequests") == 0
        and report.get("consoleErrors") == []
        and report.get("idleFrameChanged") is True
        and report.get("reactiveFrameVariants", 0) >= 2
        and len(report.get("cases", [])) == 3
    )
    if not passed:
        raise ValueError(f"{golden_id}: screenshot evidence did not pass")
    return report


async def verify_rederived(*, run_vision: bool) -> list[dict[str, Any]]:
    backend = None
    if run_vision:
        settings = Settings.from_env()
        backend = CodexBackend(
            executor=CodexExecutor(
                stage_timeout_seconds=settings.public_stage_timeout_seconds,
                evidence_stage_timeout_seconds=settings.evidence_stage_timeout_seconds,
                record_runtime=True,
                evidence_allowlist=frozenset(GOLDEN_FIXTURE_IDS),
                service_tier=settings.service_tier,
            ),
            settings=settings,
        )
    fixtures = load_golden_fixtures()
    try:
        vision_cache = json.loads(VISION_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        vision_cache = {}
    results = []
    for fixture_id in GOLDEN_FIXTURE_IDS:
        golden_id = golden_id_for_fixture(fixture_id)
        understanding, module_output = load_rederived(golden_id)
        deterministic = verify_candidate(module_output, understanding)
        if not deterministic.passed or deterministic.artifact is None:
            raise ValueError(f"{golden_id}: deterministic gates failed: {deterministic.failures}")
        browser = await asyncio.to_thread(
            verify_artifact_in_browser,
            deterministic.artifact,
        )
        if not browser.passed:
            raise ValueError(f"{golden_id}: browser gates failed: {browser.failures}")
        review = review_golden_candidate(
            fixture=fixtures[fixture_id],
            understanding=understanding,
            module_output=module_output,
        )
        if not review["passed"]:
            raise ValueError(f"{golden_id}: curated review failed: {review['failure_codes']}")
        vision_input = {
            "action_revision": VISION_JUDGMENT_REVISION[understanding["action"]],
            "actor": understanding["actor"],
            "action": understanding["action"],
            "formula": understanding["key_formula"],
            "frame_states": browser.evidence.get("visionFrameStates", []),
            "frame_sha256": [hashlib.sha256(frame).hexdigest() for frame in browser.vision_frames],
            "vision_prompt_sha256": hashlib.sha256(
                (ROOT / "server" / "prompts" / "vision.md").read_bytes()
            ).hexdigest(),
        }
        vision_key = hashlib.sha256(
            json.dumps(vision_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if backend is None:
            vision = {
                "actor_visible": True,
                "action_performed": True,
                "paused_action_performed": True,
                "physically_consistent": True,
                "labels_obscure_subject": False,
                "defects": [],
            }
        elif vision_key in vision_cache:
            vision = vision_cache[vision_key]
        else:
            vision = await _semantic_vision(
                backend,
                understanding,
                browser.vision_frames,
                fixture_id,
                browser.evidence.get("visionFrameStates", []),
            )
        vision_result = evaluate_vision_verdict(vision)
        if not vision_result.passed:
            raise ValueError(f"{golden_id}: semantic vision failed: {vision_result.failure}")
        if backend is not None and vision_key not in vision_cache:
            vision_cache[vision_key] = vision
            _write_json(VISION_CACHE_PATH, vision_cache)
        results.append(
            {
                "fixture_id": fixture_id,
                "golden_id": golden_id,
                "understanding": understanding,
                "module_output": module_output,
                "artifact": deterministic.artifact,
                "artifact_sha256": hashlib.sha256(
                    deterministic.artifact.encode("utf-8")
                ).hexdigest(),
                "deterministic": {
                    "passed": True,
                    "check_count": deterministic.check_count,
                    "node_report": deterministic.node_report,
                },
                "browser": {
                    "passed": True,
                    "check_count": browser.check_count,
                    "evidence": browser.evidence,
                },
                "vision": vision,
                "review": review,
            }
        )
        print(f"verified {golden_id}", file=sys.stderr, flush=True)
    return results


def _public_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "gate": "model_driven_v2_limited_adoption",
        "vision_model": "gpt-5.6-terra",
        "lessons": [
            {
                "id": result["golden_id"],
                "passed": True,
                "artifact_sha256": result["artifact_sha256"],
                "deterministic_check_count": result["deterministic"]["check_count"],
                "browser_check_count": result["browser"]["check_count"],
                "actor_tracking": result["browser"]["evidence"]["actorTracking"],
                "paused_actor_tracking": result["browser"]["evidence"][
                    "pausedActorTracking"
                ],
                "motion_measurements": {
                    "playing": {
                        "subject_changed_pixel_ratio": result["browser"]["evidence"][
                            "idleMotionSubjectChangedPixelRatio"
                        ],
                        "whole_canvas_changed_pixel_ratio": result["browser"][
                            "evidence"
                        ]["idleMotionWholeCanvasChangedPixelRatio"],
                        "capture_interval_ms": result["browser"]["evidence"][
                            "idleMotionCaptureIntervalMs"
                        ],
                    },
                    "paused_auto_sweep": {
                        "subject_changed_pixel_ratio": result["browser"]["evidence"][
                            "pausedMotionSubjectChangedPixelRatio"
                        ],
                        "whole_canvas_changed_pixel_ratio": result["browser"][
                            "evidence"
                        ]["pausedMotionWholeCanvasChangedPixelRatio"],
                        "capture_interval_ms": result["browser"]["evidence"][
                            "pausedMotionCaptureIntervalMs"
                        ],
                    },
                },
                "mobile_overlay_layout": result["browser"]["evidence"][
                    "mobileOverlayLayout"
                ],
                "vision": result["vision"],
            }
            for result in results
        ],
    }


def apply_results(results: list[dict[str, Any]]) -> None:
    fixtures = load_golden_fixtures()
    summary_path = EVIDENCE_ROOT / "model-driven-v2-revalidation.json"
    _write_json(summary_path, _public_summary(results))
    for result in results:
        golden_id = result["golden_id"]
        fixture_id = result["fixture_id"]
        pinned_path = GOLDEN_ROOT / f"{golden_id}.json"
        pinned = json.loads(pinned_path.read_text(encoding="utf-8"))
        check_count = (
            result["deterministic"]["check_count"]
            + result["browser"]["check_count"]
            + 1
        )
        pinned["artifact"] = result["artifact"]
        pinned["artifact_sha256"] = result["artifact_sha256"]
        pinned["receipt"] = {
            "deterministic_passed": True,
            "browser_passed": True,
            "failed_gate_count": 0,
            "check_count": check_count,
        }
        pinned["review"]["automated"] = result["review"]
        pinned["review"]["reference_contract"] = fixtures[fixture_id]["review_contract"]
        pinned["evidence"] = {
            **pinned["evidence"],
            "browser": result["browser"]["evidence"],
            "vision": result["vision"],
            "artifact_method": "model_driven_v2_limited_rederive",
            "model_driven_revalidation": str(summary_path.relative_to(ROOT)),
        }
        pinned["release_revision"] = "v1.3"
        _write_json(pinned_path, pinned)

        candidate_path = CANDIDATE_ROOT / f"{golden_id}.json"
        if candidate_path.exists():
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["artifact"] = result["artifact"]
            candidate["artifact_sha256"] = result["artifact_sha256"]
            candidate["artifact_method"] = "model_driven_v2_limited_rederive"
            outputs = candidate["builder_outputs"]
            outputs["understanding"] = result["understanding"]
            outputs["module_output"] = result["module_output"]
            outputs["verification"] = {
                **outputs.get("verification", {}),
                "passed": True,
                "check_count": check_count,
                "node_report": result["deterministic"]["node_report"],
            }
            outputs["browser"] = result["browser"]["evidence"]
            outputs["vision"] = result["vision"]
            _write_json(candidate_path, candidate)
            (CANDIDATE_ROOT / f"{golden_id}.html").write_text(
                result["artifact"],
                encoding="utf-8",
            )

    manifest = {
        "schema_version": "1.0",
        "contract_version": "1.0",
        "lessons": [
            {
                "id": result["golden_id"],
                "locale": json.loads(
                    (GOLDEN_ROOT / f"{result['golden_id']}.json").read_text(
                        encoding="utf-8"
                    )
                )["locale"],
                "aliases": json.loads(
                    (GOLDEN_ROOT / f"{result['golden_id']}.json").read_text(
                        encoding="utf-8"
                    )
                )["aliases"],
                "instant": True,
                "tier": "A",
                "artifact_sha256": result["artifact_sha256"],
                "metadata": json.loads(
                    (GOLDEN_ROOT / f"{result['golden_id']}.json").read_text(
                        encoding="utf-8"
                    )
                )["metadata"],
            }
            for result in sorted(results, key=lambda item: item["golden_id"])
        ],
    }
    _write_json(GOLDEN_ROOT / "manifest.json", manifest)
    for result in results:
        _spotcheck(result["artifact"], result["golden_id"])


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-derive pinned lessons through the §7 verification-first gates"
    )
    parser.add_argument("--vision", action="store_true")
    parser.add_argument("--apply", action="store_true")
    options = parser.parse_args()
    if options.apply and not options.vision:
        raise ValueError("--apply requires live --vision evidence")
    results = await verify_rederived(run_vision=options.vision)
    print(json.dumps(_public_summary(results), ensure_ascii=False, indent=2))
    if options.apply:
        apply_results(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
