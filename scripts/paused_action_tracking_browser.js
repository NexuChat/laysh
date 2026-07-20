(async () => {
  const canvas = document.querySelector("#simulation");
  const context = canvas && canvas.getContext("2d");
  const control = document.querySelector("#primary-control");
  const lesson = window.__LAYSH_LESSON__;
  const simulation = window.LayshSimulation;
  const actor = lesson && lesson.actor;
  const action = lesson && lesson.action;
  const parameter = lesson && lesson.primary_parameter;
  const lessonName = lesson && lesson.title;
  const heldValue = control ? Number(control.value) : null;
  const heldParameter = parameter
    ? { id: parameter.id, value: heldValue, unit: parameter.unit }
    : null;
  const compact = (value) => Math.round(value * 10000) / 10000;
  const diagnosticBase = {
    lesson: lessonName,
    held_parameter: heldParameter,
    action,
  };
  const fail = (code, expectedMotion, measuredMotion) => ({
    passed: false,
    lesson: lessonName,
    action,
    actorId: actor && actor.id,
    heldParameter,
    failure: {
      code,
      expected: { ...diagnosticBase, ...expectedMotion },
      measured: { ...diagnosticBase, ...measuredMotion },
    },
  });

  if (!canvas || !context || !control || !simulation || !actor || !parameter) {
    return fail(
      "paused_actor_contract_unavailable",
      { actor_contract_present: true },
      { actor_contract_present: false },
    );
  }
  const sweepState = document.documentElement.dataset.sweepState
    || document.documentElement.dataset.motionState;
  if (sweepState !== "paused") {
    return fail(
      "paused_sweep_state_unavailable",
      { sweep_state: "paused" },
      { sweep_state: sweepState || null },
    );
  }

  const signature = actor.tracking_signature;
  const color = signature.color_rgb;
  const tolerance = Number(signature.tolerance);
  const matches = (pixels, index) => (
    pixels[index + 3] >= 128
    && Math.abs(pixels[index] - color[0]) <= tolerance
    && Math.abs(pixels[index + 1] - color[1]) <= tolerance
    && Math.abs(pixels[index + 2] - color[2]) <= tolerance
  );

  function measure(includeSignal = false) {
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let count = 0;
    let sumX = 0;
    let sumY = 0;
    const ySum = includeSignal ? new Float64Array(canvas.width) : null;
    const yCount = includeSignal ? new Uint32Array(canvas.width) : null;
    for (let index = 0, pixel = 0; index < pixels.length; index += 4, pixel += 1) {
      if (!matches(pixels, index)) continue;
      const x = pixel % canvas.width;
      const y = Math.floor(pixel / canvas.width);
      count += 1;
      sumX += x;
      sumY += y;
      if (includeSignal) {
        ySum[x] += y;
        yCount[x] += 1;
      }
    }
    return {
      count,
      x: count ? sumX / count : null,
      y: count ? sumY / count : null,
      signal: includeSignal
        ? Array.from(ySum, (value, x) => (yCount[x] ? value / yCount[x] : null))
        : null,
    };
  }

  function render(timeSeconds, repeats = 1, includeSignal = false) {
    for (let repeat = 0; repeat < repeats; repeat += 1) {
      simulation.setParameter(parameter.id, heldValue, timeSeconds);
    }
    return measure(includeSignal);
  }

  function outputAtHeld() {
    const tested = simulation.test({ [parameter.id]: heldValue });
    return Number(tested[actor.tracking_output]);
  }

  if (action === "oscillates") {
    const period = outputAtHeld();
    if (!(period > 0)) {
      return fail(
        "paused_oscillation_period_unavailable",
        { finite_positive_period_seconds: true },
        { period_seconds: period },
      );
    }
    const samples = [];
    for (let index = 0; index <= 36; index += 1) {
      const time = period * 1.5 * index / 36;
      const point = render(time);
      samples.push({ time, x: point.x });
    }
    const visible = samples.filter((sample) => sample.x !== null);
    const velocities = [];
    for (let index = 1; index < visible.length; index += 1) {
      velocities.push(visible[index].x - visible[index - 1].x);
    }
    let reversals = 0;
    for (let index = 1; index < velocities.length; index += 1) {
      if (velocities[index - 1] * velocities[index] < 0) reversals += 1;
    }
    const xs = visible.map((sample) => sample.x);
    const span = xs.length ? Math.max(...xs) - Math.min(...xs) : 0;
    const expected = { minimum_direction_reversals: 2, minimum_span_pixels: 6 };
    const measured = {
      direction_reversals: reversals,
      horizontal_span_pixels: compact(span),
      sample_count: visible.length,
    };
    if (reversals < 2 || span < 6) {
      return fail("paused_oscillation_reversal_missing", expected, measured);
    }
    return {
      passed: true,
      lesson: lessonName,
      action,
      actorId: actor.id,
      heldParameter,
      expected,
      measured,
    };
  }

  if (action === "propagates") {
    let period = outputAtHeld();
    if (actor.tracking_output.endsWith("_ms")) period /= 1000;
    if (!(period > 0)) {
      return fail(
        "paused_propagation_period_unavailable",
        { finite_positive_period_seconds: true },
        { period_seconds: period },
      );
    }
    const first = render(0, 7, true).signal;
    const second = render(period / 4, 1, true).signal;
    const paired = [];
    for (let x = 0; x < first.length; x += 1) {
      if (first[x] !== null && second[x] !== null) paired.push(x);
    }
    const firstMean = paired.reduce((sum, x) => sum + first[x], 0) / Math.max(1, paired.length);
    const secondMean = paired.reduce((sum, x) => sum + second[x], 0) / Math.max(1, paired.length);
    let dominant = { amplitude: 0, first: 0, second: 0, cycles: 0 };
    for (let cycles = 1; cycles <= 20; cycles += 1) {
      let firstSin = 0;
      let firstCos = 0;
      let secondSin = 0;
      let secondCos = 0;
      for (const x of paired) {
        const angle = 2 * Math.PI * cycles * x / canvas.width;
        firstSin += (first[x] - firstMean) * Math.sin(angle);
        firstCos += (first[x] - firstMean) * Math.cos(angle);
        secondSin += (second[x] - secondMean) * Math.sin(angle);
        secondCos += (second[x] - secondMean) * Math.cos(angle);
      }
      const amplitude = Math.hypot(firstSin, firstCos);
      if (amplitude > dominant.amplitude) {
        dominant = {
          amplitude,
          first: Math.atan2(firstSin, firstCos),
          second: Math.atan2(secondSin, secondCos),
          cycles,
        };
      }
    }
    const shift = Math.abs(Math.atan2(
      Math.sin(dominant.second - dominant.first),
      Math.cos(dominant.second - dominant.first),
    ));
    const error = Math.abs(shift - Math.PI / 2);
    const expected = {
      phase_shift_radians: compact(Math.PI / 2),
      maximum_error_radians: 0.6,
      minimum_matched_columns: 40,
    };
    const measured = {
      phase_shift_radians: compact(shift),
      phase_error_radians: compact(error),
      matched_columns: paired.length,
      dominant_spatial_cycles: dominant.cycles,
    };
    if (paired.length < 40 || dominant.amplitude <= 0 || error > 0.6) {
      return fail("paused_propagation_phase_static", expected, measured);
    }
    return {
      passed: true,
      lesson: lessonName,
      action,
      actorId: actor.id,
      heldParameter,
      expected,
      measured,
    };
  }

  if (action === "floats_sinks") {
    const first = render(0, 30);
    const second = render(1.1, 1);
    const expected = {
      equilibrium_state_persists: true,
      actor_pixels_minimum: 20,
      computed_submerged_fraction: compact(outputAtHeld()),
    };
    const measured = {
      equilibrium_state_persists: first.count >= 20 && second.count >= 20,
      actor_pixels_first: first.count,
      actor_pixels_second: second.count,
      centroid_displacement_pixels: compact(Math.hypot(
        second.x - first.x,
        second.y - first.y,
      )),
    };
    if (first.count < 20 || second.count < 20) {
      return fail("paused_float_state_missing", expected, measured);
    }
    return {
      passed: true,
      lesson: lessonName,
      action,
      actorId: actor.id,
      heldParameter,
      expected,
      measured,
    };
  }

  if (action === "responds") {
    const first = render(0, 30);
    const second = render(1.1, 1);
    const displacement = first.count && second.count
      ? Math.hypot(second.x - first.x, second.y - first.y)
      : Infinity;
    const countChangeRatio = Math.abs(second.count - first.count)
      / Math.max(1, first.count);
    const heldStateStable = first.count >= 16
      && second.count >= 16
      && displacement <= 2
      && countChangeRatio <= 0.1;
    const expected = {
      held_state_stable: true,
      minimum_actor_pixels: 16,
      maximum_centroid_drift_pixels: 2,
      maximum_pixel_count_change_ratio: 0.1,
    };
    const measured = {
      held_state_stable: heldStateStable,
      actor_pixels_first: first.count,
      actor_pixels_second: second.count,
      centroid_drift_pixels: compact(displacement),
      pixel_count_change_ratio: compact(countChangeRatio),
    };
    if (!heldStateStable) return fail("paused_response_state_drifted", expected, measured);
    return {
      passed: true,
      lesson: lessonName,
      action,
      actorId: actor.id,
      heldParameter,
      expected,
      measured,
    };
  }

  const sampleDuration = action === "flows" ? 0.08 : 1.1;
  const samples = [];
  const sampleCount = action === "rotates" || action === "orbits" || action === "phases" ? 12 : 6;
  for (let index = 0; index <= sampleCount; index += 1) {
    const time = sampleDuration * index / sampleCount;
    const point = render(time, index === 0 ? 30 : 1);
    if (point.x !== null) samples.push({ time, x: point.x, y: point.y });
  }
  const xs = samples.map((sample) => sample.x);
  const ys = samples.map((sample) => sample.y);
  const spanX = xs.length ? Math.max(...xs) - Math.min(...xs) : 0;
  const spanY = ys.length ? Math.max(...ys) - Math.min(...ys) : 0;
  const trajectorySpan = Math.hypot(spanX, spanY);
  const minimumSpan = 6;
  const expected = {
    minimum_trajectory_span_pixels: minimumSpan,
    sample_duration_seconds: sampleDuration,
  };
  const measured = {
    trajectory_span_pixels: compact(trajectorySpan),
    horizontal_span_pixels: compact(spanX),
    vertical_span_pixels: compact(spanY),
    sample_count: samples.length,
  };
  if (trajectorySpan < minimumSpan) {
    return fail("paused_phenomenon_actor_static", expected, measured);
  }
  return {
    passed: true,
    lesson: lessonName,
    action,
    actorId: actor.id,
    heldParameter,
    expected,
    measured,
  };
})()
