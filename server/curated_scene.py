from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

CURATED_SCENE_ADAPTER_MARKER = "LAYSH_CURATED_SCENE_ADAPTER_V1"
_ASSIGNMENT = "window.LayshSimulation ="

_ACTOR_REGION_FIELDS = frozenset({"x", "y", "width", "height"})

_ADAPTER_TEMPLATE = r'''

/* LAYSH_CURATED_SCENE_ADAPTER_V1: build-time migration for reviewed pins only. */
window.LayshSimulation = (function (delegate) {
  "use strict";
  var canvas = null;
  var sequence = 0;
  var reviewedActor = __LAYSH_REVIEWED_ACTOR__;

  function finite(value) {
    return typeof value === "number" && isFinite(value);
  }

  function publishSceneGeometry() {
    if (!canvas || !finite(canvas.width) || !finite(canvas.height)
        || canvas.width <= 0 || canvas.height <= 0) return;
    var suppliedBodies = Array.isArray(canvas.__layshBodyGeometry)
      ? canvas.__layshBodyGeometry : [];
    var bodies = suppliedBodies.filter(function (body) {
      return body && typeof body.name === "string" && body.name
        && body.shape === "circle" && finite(body.x) && finite(body.y)
        && finite(body.radius) && body.radius > 0;
    });
    var objects;
    if (bodies.length) {
      objects = bodies.map(function (body) {
        return {
          id: body.name,
          scientific: true,
          clippingPolicy: "forbid",
          geometry: {type: "circle", cx: body.x, cy: body.y, radius: body.radius}
        };
      });
    } else {
      var region = reviewedActor.region;
      var regionWidth = region.width * canvas.width;
      var regionHeight = region.height * canvas.height;
      objects = [{
        id: reviewedActor.id,
        scientific: true,
        clippingPolicy: "forbid",
        geometry: {
          type: "circle",
          cx: (region.x + region.width / 2) * canvas.width,
          cy: (region.y + region.height / 2) * canvas.height,
          radius: Math.min(regionWidth, regionHeight) / 2
        }
      }];
    }
    var relations = [];
    for (var leftIndex = 0; leftIndex < bodies.length; leftIndex += 1) {
      for (var rightIndex = leftIndex + 1; rightIndex < bodies.length; rightIndex += 1) {
        var left = bodies[leftIndex];
        var right = bodies[rightIndex];
        var leftContacts = Array.isArray(left.contacts) ? left.contacts : [];
        var rightContacts = Array.isArray(right.contacts) ? right.contacts : [];
        var declared = leftContacts.indexOf(right.name) >= 0
          || rightContacts.indexOf(left.name) >= 0;
        relations.push({
          objects: [left.name, right.name],
          overlapPolicy: declared ? "allow" : "forbid",
          contactPolicy: declared ? "allow" : "forbid",
          minimumClearance: 0
        });
      }
    }
    sequence += 1;
    canvas.__layshSceneGeometry = [{
      schemaVersion: "1.0",
      phase: "post_fit",
      viewport: {width: canvas.width, height: canvas.height, safeInset: 0},
      state: {id: "curated-post-fit-" + sequence, timeMs: sequence},
      objects: objects,
      relations: relations
    }];
  }

  return {
    version: delegate.version,
    init: function (options) {
      canvas = options.canvas;
      var result = delegate.init(options);
      publishSceneGeometry();
      return result;
    },
    setParameter: function (name, value) {
      var result = delegate.setParameter(name, value);
      publishSceneGeometry();
      return result;
    },
    test: function (inputs) {
      return delegate.test(inputs);
    },
    resize: function (width, height) {
      var result = delegate.resize(width, height);
      publishSceneGeometry();
      return result;
    },
    destroy: function () {
      var result = delegate.destroy();
      canvas = null;
      return result;
    }
  };
})(__layshCuratedDelegate);
'''


def _reviewed_actor(
    actor_id: str,
    actor_region: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise ValueError("curated source requires a valid reviewed actor contract")
    if not isinstance(actor_region, Mapping) or set(actor_region) != _ACTOR_REGION_FIELDS:
        raise ValueError("curated source requires a valid reviewed actor contract")
    values: dict[str, float] = {}
    for field in _ACTOR_REGION_FIELDS:
        value = actor_region[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("curated source requires a valid reviewed actor contract")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("curated source requires a valid reviewed actor contract")
        values[field] = numeric
    if (
        values["x"] < 0
        or values["y"] < 0
        or values["width"] <= 0
        or values["height"] <= 0
        or values["x"] + values["width"] > 1
        or values["y"] + values["height"] > 1
    ):
        raise ValueError("curated source requires a valid reviewed actor contract")
    return {"id": actor_id.strip(), "region": values}


def attach_curated_scene_contract(
    source: str,
    *,
    actor_id: str,
    actor_region: Mapping[str, Any],
) -> str:
    """Attach reviewed post-fit actor evidence without learner-path exceptions."""

    reviewed_actor = _reviewed_actor(actor_id, actor_region)
    if CURATED_SCENE_ADAPTER_MARKER in source:
        return source
    if source.count(_ASSIGNMENT) != 1:
        raise ValueError("curated source must assign the simulation interface exactly once")
    delegated = "var __layshCuratedDelegate;\n" + source.replace(
        _ASSIGNMENT,
        "__layshCuratedDelegate =",
        1,
    )
    adapter = _ADAPTER_TEMPLATE.replace(
        "__LAYSH_REVIEWED_ACTOR__",
        json.dumps(reviewed_actor, ensure_ascii=True, separators=(",", ":")),
    )
    return delegated.rstrip() + adapter
