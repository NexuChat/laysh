from __future__ import annotations

from collections.abc import Callable

from server.shared_state import shared_model_report


def _replace_once(source: str, before: str, after: str, *, golden_id: str) -> str:
    occurrences = source.count(before)
    if occurrences != 1:
        raise ValueError(
            f"{golden_id} shared-state upgrade expected one source anchor, found {occurrences}"
        )
    return source.replace(before, after, 1)


def _moon_phases(source: str) -> str:
    source = _replace_once(
        source,
        """  function fractionFor(value) {
    var f = (1 - Math.cos(clampAngle(value) * Math.PI / 180)) / 2;
    return Math.max(0, Math.min(1, f));
  }
""",
        """  /* LAYSH_SHARED_MODEL: moonState */
  function moonState(value) {
    var angle = clampAngle(value);
    var radians = angle * Math.PI / 180;
    var fraction = (1 - Math.cos(radians)) / 2;
    return {
      angle_deg: angle,
      radians: radians,
      lit_fraction: Math.max(0, Math.min(1, fraction))
    };
  }
""",
        golden_id="moon_phases",
    )
    source = _replace_once(
        source,
        """    var radians = displayedAngle * Math.PI / 180;
""",
        """    var state = moonState(displayedAngle);
    var radians = state.radians;
""",
        golden_id="moon_phases",
    )
    source = _replace_once(
        source,
        """    var f = fractionFor(displayedAngle);
""",
        """    var f = state.lit_fraction;
""",
        golden_id="moon_phases",
    )
    return _replace_once(
        source,
        """    test: function (inputs) {
      return { lit_fraction: fractionFor(inputs && inputs.angle_deg) };
    },
""",
        """    test: function (inputs) {
      var state = moonState(inputs && inputs.angle_deg);
      return { lit_fraction: state.lit_fraction };
    },
""",
        golden_id="moon_phases",
    )


def _buoyancy(source: str) -> str:
    source = _replace_once(
        source,
        """  function roundedRect(x, y, w, h, radius) {
""",
        """  /* LAYSH_SHARED_MODEL: buoyancyState */
  function buoyancyState(value) {
    var numeric = Number(value);
    var densityValue = Number.isFinite(numeric) ? numeric : 750;
    var densityKgM3 = clamp(densityValue, 200, 1400);
    return {
      density_kg_m3: densityKgM3,
      submerged_fraction: Math.min(densityKgM3 / 1000, 1),
      floats: densityKgM3 <= 1000 ? 1 : 0
    };
  }

  function roundedRect(x, y, w, h, radius) {
""",
        golden_id="buoyancy",
    )
    source = _replace_once(
        source,
        """    var d = clamp(displayedDensity, 200, 1400);
    var fraction = clamp(d / 1000, 0, 1);
    var floats = d <= 1000;
""",
        """    var state = buoyancyState(displayedDensity);
    var d = state.density_kg_m3;
    var fraction = state.submerged_fraction;
    var floats = state.floats === 1;
""",
        golden_id="buoyancy",
    )
    return _replace_once(
        source,
        """      if (!Number.isFinite(value)) value = 750;
      value = clamp(value, 200, 1400);
      return {
        submerged_fraction: Math.min(value / 1000, 1),
        floats: value <= 1000 ? 1 : 0
      };
""",
        """      var state = buoyancyState(value);
      return {
        submerged_fraction: state.submerged_fraction,
        floats: state.floats
      };
""",
        golden_id="buoyancy",
    )


def _pendulum(source: str) -> str:
    source = _replace_once(
        source,
        """  function period(length) {
    return 2 * Math.PI * Math.sqrt(length / 9.81);
  }
""",
        """  /* LAYSH_SHARED_MODEL: pendulumState */
  function pendulumState(value) {
    var numeric = Number(value);
    var length = Number.isFinite(numeric) ? clamp(numeric, 0.25, 2) : 1;
    return {
      length_m: length,
      period_s: 2 * Math.PI * Math.sqrt(length / 9.81)
    };
  }
""",
        golden_id="pendulum",
    )
    source = _replace_once(
        source,
        """  function drawPendulum() {
    var pivotX = width * 0.5;
""",
        """  function drawPendulum() {
    var state = pendulumState(displayedLength);
    var pivotX = width * 0.5;
""",
        golden_id="pendulum",
    )
    source = _replace_once(
        source,
        """    var ropeLength = displayedLength * pixelsPerMeter;
""",
        """    var ropeLength = state.length_m * pixelsPerMeter;
""",
        golden_id="pendulum",
    )
    source = _replace_once(
        source,
        (
            '    chip(chipX, chipY, chipW, chipH, locale === "ar" ? "زمن الذبذبة" : '
            '"Period", period(length_m).toFixed(2) + (locale === "ar" ? " ث" : " s"), '
            '"#ffc15c");\n'
        ),
        (
            '    chip(chipX, chipY, chipW, chipH, locale === "ar" ? "زمن الذبذبة" : '
            '"Period", state.period_s.toFixed(2) + (locale === "ar" ? " ث" : " s"), '
            '"#ffc15c");\n'
        ),
        golden_id="pendulum",
    )
    return _replace_once(
        source,
        """      value = clamp(value, 0.25, 2);
      return { period_s: period(value) };
""",
        """      var state = pendulumState(value);
      return { period_s: state.period_s };
""",
        golden_id="pendulum",
    )


def _simple_circuit(source: str) -> str:
    source = _replace_once(
        source,
        """  function finite(value, fallback) {
""",
        """  /* LAYSH_SHARED_MODEL: circuitState */
  function circuitState(value) {
    var numeric = Number(value);
    var resistanceOhm = isFinite(numeric) ? clamp(numeric, 2, 20) : 6;
    var current = 6 / resistanceOhm;
    var power = 36 / resistanceOhm;
    return {
      resistance_ohm: resistanceOhm,
      current_a: current,
      power_w: power,
      brightness: clamp((power - 1.8) / 16.2, 0, 1)
    };
  }

  function finite(value, fallback) {
""",
        golden_id="simple_circuit",
    )
    source = _replace_once(
        source,
        """    var current = 6 / displayedResistance;
    var power = 36 / displayedResistance;
    var brightness = clamp((power - 1.8) / 16.2, 0, 1);
""",
        """    var state = circuitState(displayedResistance);
    var current = state.current_a;
    var power = state.power_w;
    var brightness = state.brightness;
""",
        golden_id="simple_circuit",
    )
    source = _replace_once(
        source,
        """    drawResistor(center, upper, boardW, displayedResistance);
""",
        """    drawResistor(center, upper, boardW, state.resistance_ohm);
""",
        golden_id="simple_circuit",
    )
    source = _replace_once(
        source,
        """  function drawReadouts(boardBottom) {
    var current = 6 / displayedResistance;
    var power = 36 / displayedResistance;
""",
        """  function drawReadouts(boardBottom) {
    var state = circuitState(displayedResistance);
    var current = state.current_a;
    var power = state.power_w;
""",
        golden_id="simple_circuit",
    )
    source = _replace_once(
        source,
        (
            '    chip(x, y, chipW, chipH, locale === "ar" ? "المقاومة R" : '
            '"Resistance R", displayedResistance.toFixed(1) + " Ω", "#f0a35a");\n'
        ),
        (
            '    chip(x, y, chipW, chipH, locale === "ar" ? "المقاومة R" : '
            '"Resistance R", state.resistance_ohm.toFixed(1) + " Ω", "#f0a35a");\n'
        ),
        golden_id="simple_circuit",
    )
    return _replace_once(
        source,
        """  function test(inputs) {
    var numeric = Number(inputs && inputs.resistance_ohm);
    var r = isFinite(numeric) ? clamp(numeric, 2, 20) : 6;
    return {current_a: 6 / r, power_w: 36 / r};
  }
""",
        """  function test(inputs) {
    var state = circuitState(inputs && inputs.resistance_ohm);
    return {current_a: state.current_a, power_w: state.power_w};
  }
""",
        golden_id="simple_circuit",
    )


def _sound_pitch(source: str) -> str:
    source = _replace_once(
        source,
        """  function draw(advance) {
""",
        """  /* LAYSH_SHARED_MODEL: soundState */
  function soundState(value) {
    var frequencyHz = Number(value);
    if (!Number.isFinite(frequencyHz) || frequencyHz <= 0) frequencyHz = 440;
    return {
      frequency_hz: frequencyHz,
      wavelength_m: 343 / frequencyHz,
      period_ms: 1000 / frequencyHz,
      cycles: 2 + (frequencyHz - 110) / 770 * 6
    };
  }

  function draw(advance) {
""",
        golden_id="sound_pitch",
    )
    source = _replace_once(
        source,
        """    var w = width, h = height, cy = h * 0.53, i;
""",
        """    var state = soundState(displayedFrequency);
    var w = width, h = height, cy = h * 0.53, i;
""",
        golden_id="sound_pitch",
    )
    source = _replace_once(
        source,
        """    var cycles = 2 + (displayedFrequency - 110) / 770 * 6;
""",
        """    var cycles = state.cycles;
""",
        golden_id="sound_pitch",
    )
    source = _replace_once(
        source,
        (
            "    var phaseShift = reducedMotion ? 0 : visualPhase * "
            "(0.45 + displayedFrequency / 880 * 0.35);\n"
        ),
        (
            "    var phaseShift = reducedMotion ? 0 : visualPhase * "
            "(0.45 + state.frequency_hz / 880 * 0.35);\n"
        ),
        golden_id="sound_pitch",
    )
    source = _replace_once(
        source,
        """    var wavelength = 343 / frequency;
    var period = 1000 / frequency;
""",
        """    var wavelength = state.wavelength_m;
    var period = state.period_ms;
""",
        golden_id="sound_pitch",
    )
    source = _replace_once(
        source,
        (
            '    chip(chipsX, chipsY, chipW, "التردد · حدّة النغمة", '
            'Math.round(frequency) + " Hz", "rgba(100,224,255,0.72)");\n'
        ),
        (
            '    chip(chipsX, chipsY, chipW, "التردد · حدّة النغمة", '
            'Math.round(state.frequency_hz) + " Hz", "rgba(100,224,255,0.72)");\n'
        ),
        golden_id="sound_pitch",
    )
    return _replace_once(
        source,
        """      if (!Number.isFinite(f) || f <= 0) f = 440;
      return { wavelength_m: 343 / f, period_ms: 1000 / f };
""",
        """      var state = soundState(f);
      return { wavelength_m: state.wavelength_m, period_ms: state.period_ms };
""",
        golden_id="sound_pitch",
    )


def _day_night(source: str) -> str:
    source = _replace_once(
        source,
        """  function alignmentFor(degrees) {
    var value = Math.cos(degrees * Math.PI / 180);
    return Math.abs(value) < 1e-12 ? 0 : value;
  }
""",
        """  /* LAYSH_SHARED_MODEL: dayNightState */
  function dayNightState(value) {
    var rotation = clampRotation(value);
    var theta = rotation * Math.PI / 180;
    var alignment = Math.cos(theta);
    if (Math.abs(alignment) < 1e-12) alignment = 0;
    return {
      rotation_deg: rotation,
      theta_rad: theta,
      light_alignment: alignment,
      daylight: alignment > 0 ? 1 : 0
    };
  }
""",
        golden_id="day_night",
    )
    source = _replace_once(
        source,
        """    var theta = displayedDeg * Math.PI / 180;
    var markerX = earthX - Math.cos(theta) * earthR * 0.91;
    var markerY = earthY - Math.sin(theta) * earthR * 0.91;
    var alignment = alignmentFor(displayedDeg);
    var isDay = alignment > 0;
""",
        """    var state = dayNightState(displayedDeg);
    var theta = state.theta_rad;
    var markerX = earthX - Math.cos(theta) * earthR * 0.91;
    var markerY = earthY - Math.sin(theta) * earthR * 0.91;
    var alignment = state.light_alignment;
    var isDay = state.daylight === 1;
""",
        golden_id="day_night",
    )
    return _replace_once(
        source,
        """  function test(inputs) {
    inputs = inputs || {};
    var degrees = clampRotation(inputs.rotation_deg);
    var lightAlignment = alignmentFor(degrees);
    return {
      light_alignment: lightAlignment,
      daylight: lightAlignment > 0 ? 1 : 0
    };
  }
""",
        """  function test(inputs) {
    inputs = inputs || {};
    var state = dayNightState(inputs.rotation_deg);
    return {
      light_alignment: state.light_alignment,
      daylight: state.daylight
    };
  }
""",
        golden_id="day_night",
    )


_UPGRADES: dict[str, Callable[[str], str]] = {
    "moon_phases": _moon_phases,
    "buoyancy": _buoyancy,
    "pendulum": _pendulum,
    "simple_circuit": _simple_circuit,
    "sound_pitch": _sound_pitch,
    "day_night": _day_night,
}


def upgrade_golden_module(golden_id: str, source: str) -> str:
    """Apply the approved, idempotent shared-state upgrade to one pinned golden."""

    if golden_id not in _UPGRADES:
        raise ValueError(f"unknown pinned golden: {golden_id}")
    if "LAYSH_SHARED_MODEL" in source:
        report = shared_model_report(source)
        if report["passed"]:
            return source
        raise ValueError(f"{golden_id} already has an invalid shared model contract")
    upgraded = _UPGRADES[golden_id](source)
    report = shared_model_report(upgraded)
    if not report["passed"]:
        raise ValueError(f"{golden_id} shared-state upgrade failed static verification")
    return upgraded
