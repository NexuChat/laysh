from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from server.goldens import GOLDEN_ROOT, refresh_pinned_golden_teaching_shells

_MODEL_END = """  }

  function gradient(kind, args, stops, fallback) {"""

_SCENE_LAYOUT = """  }

  function sceneLayout(state) {
    var dividerX = width * .59;
    var earthY = height * .53;
    var scale = Math.min(dividerX, height);
    var orbitR = scale * .30;
    var earthR = scale * .05;
    var moonR = scale * .027;
    var sunR = scale * .075;
    var clearance = scale * .03;
    var sceneWidth = 2 * (orbitR + moonR + sunR) + clearance;
    var earthX = (dividerX - sceneWidth) / 2 + orbitR + moonR;
    var sunX = earthX + orbitR + moonR + sunR + clearance;
    return {
      state: state,
      dividerX: dividerX,
      earthX: earthX,
      earthY: earthY,
      orbitR: orbitR,
      earthR: earthR,
      moonR: moonR,
      sunR: sunR,
      sunX: sunX,
      moonX: earthX + Math.cos(state.radians) * orbitR,
      moonY: earthY - Math.sin(state.radians) * orbitR * .67
    };
  }

  function gradient(kind, args, stops, fallback) {"""

_OLD_SCENE_START = """    var dividerX = width * .59;
    var topY = Math.max(35, height * .10);"""

_NEW_SCENE_START = """    var state = moonState(displayedAngle);
    var layout = sceneLayout(state);
    var dividerX = layout.dividerX;
    var topY = Math.max(35, height * .10);"""

_OLD_BODY_LAYOUT = (
    "    var earthX = dividerX*.49, earthY = height*.53, "
    "scale = Math.min(dividerX,height);\n"
    "    var orbitR = Math.max(54,scale*.30), earthR = Math.max(13,scale*.05), "
    "moonR = Math.max(7,earthR*.54), sunR = Math.max(18,scale*.075);\n"
    "    var sunX = Math.min(dividerX-sunR*1.35,earthX+orbitR+sunR*1.8);"
)

_NEW_BODY_LAYOUT = """    var earthX = layout.earthX, earthY = layout.earthY;
    var orbitR = layout.orbitR, earthR = layout.earthR;
    var moonR = layout.moonR, sunR = layout.sunR, sunX = layout.sunX;"""

_OLD_MOON_LAYOUT = """    var state = moonState(displayedAngle);
    var radians = state.radians;
    var moonX = earthX + Math.cos(radians)*orbitR, moonY = earthY-Math.sin(radians)*orbitR*.67;
    drawSmallMoon(moonX,moonY,moonR);"""

_NEW_MOON_LAYOUT = """    var radians = state.radians;
    var moonX = layout.moonX, moonY = layout.moonY;
    if (canvas) canvas.__layshBodyGeometry = [
      {name:'Sun',shape:'circle',x:sunX,y:earthY,radius:sunR,contacts:[]},
      {name:'Earth',shape:'circle',x:earthX,y:earthY,radius:earthR,contacts:[]},
      {name:'Moon',shape:'circle',x:moonX,y:moonY,radius:moonR,contacts:[]}
    ];
    drawSmallMoon(moonX,moonY,moonR);"""


def upgrade_moon_geometry(golden_id: str, source: str) -> str:
    """Derive Moon-scene bodies and clearance from one bounded scale."""

    if golden_id != "moon_phases" or "function sceneLayout(state)" in source:
        return source
    replacements = (
        (_MODEL_END, _SCENE_LAYOUT),
        (_OLD_SCENE_START, _NEW_SCENE_START),
        (_OLD_BODY_LAYOUT, _NEW_BODY_LAYOUT),
        (_OLD_MOON_LAYOUT, _NEW_MOON_LAYOUT),
    )
    upgraded = source
    for old, new in replacements:
        if upgraded.count(old) != 1:
            raise ValueError("moon geometry source no longer matches the reviewed transform")
        upgraded = upgraded.replace(old, new)
    return upgraded


def refresh_pinned_moon_geometry(
    *,
    root: Path = GOLDEN_ROOT,
    browser_verifier: Any | None = None,
) -> list[dict[str, Any]]:
    """Refresh only the pinned Moon artifact through the trusted offline gates."""

    moon_path = root / "moon_phases.json"
    manifest_path = root / "manifest.json"
    with tempfile.TemporaryDirectory(prefix="laysh-moon-geometry-") as temporary:
        temporary_root = Path(temporary)
        shutil.copyfile(moon_path, temporary_root / moon_path.name)
        reports = refresh_pinned_golden_teaching_shells(
            root=temporary_root,
            browser_verifier=browser_verifier,
            module_transformer=upgrade_moon_geometry,
            refresh_evidence_key="geometry_refresh",
            report_flag="geometry_refreshed",
        )
        moon_document = json.loads(
            (temporary_root / moon_path.name).read_text(encoding="utf-8")
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matching_lessons = [
        lesson for lesson in manifest["lessons"] if lesson["id"] == "moon_phases"
    ]
    if len(matching_lessons) != 1:
        raise ValueError("golden manifest has no unique Moon lesson")
    matching_lessons[0]["artifact_sha256"] = moon_document["artifact_sha256"]

    pending = (
        (
            moon_path.with_suffix(".json.geometry.tmp"),
            moon_path,
            json.dumps(moon_document, ensure_ascii=False, separators=(",", ":")),
        ),
        (
            manifest_path.with_suffix(".json.geometry.tmp"),
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        ),
    )
    for temporary_path, _, content in pending:
        temporary_path.write_text(content, encoding="utf-8")
    for temporary_path, target_path, _ in pending:
        temporary_path.replace(target_path)
    return reports
