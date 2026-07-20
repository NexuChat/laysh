(async () => {
  const canvas = document.querySelector("#simulation");
  const context = canvas && canvas.getContext("2d");
  const lesson = window.__LAYSH_LESSON__;
  const simulation = window.LayshSimulation;
  const actor = lesson && lesson.actor;
  const action = lesson && lesson.action;
  const parameter = lesson && lesson.primary_parameter;

  const fail = (code, expected, measured) => ({
    passed: false,
    action,
    actorId: actor && actor.id,
    failure: { code, expected, measured },
  });
  if (!canvas || !context || !simulation || !actor || !action || !parameter) {
    return fail(
      "actor_contract_unavailable",
      { actorContractPresent: true },
      { actorContractPresent: false },
    );
  }

  const signature = actor.tracking_signature;
  const color = signature.color_rgb;
  const tolerance = Number(signature.tolerance);
  const referenceColor = signature.reference_color_rgb;
  const referenceTolerance = Number(signature.reference_tolerance || 0);
  const matches = (pixels, index, target, allowed) => (
    pixels[index + 3] >= 128
    && Math.abs(pixels[index] - target[0]) <= allowed
    && Math.abs(pixels[index + 1] - target[1]) <= allowed
    && Math.abs(pixels[index + 2] - target[2]) <= allowed
  );

  function measure(target = color, allowed = tolerance, includeSignal = false) {
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let count = 0;
    let sumX = 0;
    let sumY = 0;
    let minX = canvas.width;
    let maxX = -1;
    let minY = canvas.height;
    let maxY = -1;
    const ySum = includeSignal ? new Float64Array(canvas.width) : null;
    const yCount = includeSignal ? new Uint32Array(canvas.width) : null;
    for (let index = 0, pixel = 0; index < pixels.length; index += 4, pixel += 1) {
      if (!matches(pixels, index, target, allowed)) continue;
      const x = pixel % canvas.width;
      const y = Math.floor(pixel / canvas.width);
      count += 1;
      sumX += x;
      sumY += y;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
      if (includeSignal) {
        ySum[x] += y;
        yCount[x] += 1;
      }
    }
    const signal = includeSignal
      ? Array.from(ySum, (value, x) => (yCount[x] ? value / yCount[x] : null))
      : null;
    return {
      count,
      x: count ? sumX / count : null,
      y: count ? sumY / count : null,
      minX: count ? minX : null,
      maxX: count ? maxX : null,
      minY: count ? minY : null,
      maxY: count ? maxY : null,
      signal,
    };
  }

  function outputAt(value) {
    const tested = simulation.test({ [parameter.id]: value });
    return Number(tested[actor.tracking_output]);
  }

  function render(value, timeSeconds = 0, repeats = 7) {
    for (let repeat = 0; repeat < repeats; repeat += 1) {
      simulation.setParameter(parameter.id, value, timeSeconds);
    }
    return measure();
  }

  const compact = (value) => Math.round(value * 10000) / 10000;
  const minimum = Number(parameter.min);
  const maximum = Number(parameter.max);
  const defaultValue = Number(parameter.default);

  if (action === "oscillates") {
    const expectedPeriod = outputAt(defaultValue);
    if (!(expectedPeriod > 0)) {
      return fail(
        "oscillation_period_unavailable",
        { finitePositivePeriodSeconds: true },
        { periodSeconds: expectedPeriod },
      );
    }
    const samples = [];
    for (let index = 0; index <= 48; index += 1) {
      const time = 2 * expectedPeriod * index / 48;
      const point = render(defaultValue, time, 1);
      samples.push({ time, x: point.x, count: point.count });
    }
    const visible = samples.filter((sample) => sample.x !== null);
    const xs = visible.map((sample) => sample.x);
    const span = xs.length ? Math.max(...xs) - Math.min(...xs) : 0;
    const center = xs.length ? (Math.max(...xs) + Math.min(...xs)) / 2 : 0;
    const crossings = [];
    for (let index = 1; index < visible.length; index += 1) {
      const left = visible[index - 1];
      const right = visible[index];
      const a = left.x - center;
      const b = right.x - center;
      if ((a < 0 && b >= 0) || (a > 0 && b <= 0)) {
        const ratio = Math.abs(a) / Math.max(1e-9, Math.abs(a) + Math.abs(b));
        crossings.push(left.time + (right.time - left.time) * ratio);
      }
    }
    const halfPeriods = [];
    for (let index = 1; index < crossings.length; index += 1) {
      halfPeriods.push(crossings[index] - crossings[index - 1]);
    }
    halfPeriods.sort((left, right) => left - right);
    const medianHalf = halfPeriods.length
      ? halfPeriods[Math.floor(halfPeriods.length / 2)]
      : 0;
    const measuredPeriod = medianHalf * 2;
    const errorRatio = Math.abs(measuredPeriod - expectedPeriod) / expectedPeriod;
    const expected = {
      signReversalsAtLeast: 3,
      periodSeconds: compact(expectedPeriod),
      periodToleranceRatio: 0.15,
      minimumHorizontalSpanPixels: 6,
    };
    const measured = {
      signReversals: crossings.length,
      periodSeconds: compact(measuredPeriod),
      periodErrorRatio: compact(errorRatio),
      horizontalSpanPixels: compact(span),
    };
    if (span < 6) return fail("actor_trajectory_static", expected, measured);
    if (crossings.length < 3) return fail("oscillation_sign_reversal_missing", expected, measured);
    if (errorRatio > 0.15) return fail("oscillation_period_mismatch", expected, measured);
    return { passed: true, action, actorId: actor.id, expected, measured };
  }

  if (action === "rotates") {
    const samples = [];
    for (let index = 0; index <= 24; index += 1) {
      const value = minimum + (maximum - minimum) * index / 24;
      const point = render(value);
      samples.push({ degrees: value, x: point.x, visible: point.count >= 4 });
    }
    const xs = samples.filter((sample) => sample.visible).map((sample) => sample.x);
    const span = xs.length ? Math.max(...xs) - Math.min(...xs) : 0;
    const expected = {
      angularDisplacementDegrees: maximum - minimum,
      maximumTrajectoryErrorDegrees: 18,
      minimumSpanPixels: 6,
      featureCrossesLimb: true,
    };
    if (span < 6) {
      return fail("actor_trajectory_static", expected, {
        angularDisplacementDegrees: 0,
        horizontalSpanPixels: compact(span),
        visibleSamples: xs.length,
      });
    }
    let best = { score: Infinity, phase: 0, error: Infinity, visibility: 0 };
    for (let phase = 0; phase < 360; phase += 1) {
      const fitted = samples.filter((sample) => {
        const radians = (sample.degrees + phase) * Math.PI / 180;
        return sample.visible && Math.cos(radians) > 0;
      });
      if (fitted.length < 5) continue;
      const meanX = fitted.reduce((sum, sample) => sum + sample.x, 0) / fitted.length;
      const meanS = fitted.reduce(
        (sum, sample) => sum + Math.sin((sample.degrees + phase) * Math.PI / 180),
        0,
      ) / fitted.length;
      let covariance = 0;
      let variance = 0;
      for (const sample of fitted) {
        const sine = Math.sin((sample.degrees + phase) * Math.PI / 180);
        covariance += (sine - meanS) * (sample.x - meanX);
        variance += (sine - meanS) ** 2;
      }
      const radius = variance ? covariance / variance : 0;
      const center = meanX - radius * meanS;
      let squareError = 0;
      for (const sample of fitted) {
        const predicted = center + radius
          * Math.sin((sample.degrees + phase) * Math.PI / 180);
        squareError += (sample.x - predicted) ** 2;
      }
      const normalizedError = Math.sqrt(squareError / fitted.length) / Math.max(1, span);
      const visibilityMatches = samples.filter((sample) => {
        const predicted = Math.cos((sample.degrees + phase) * Math.PI / 180) > 0;
        return predicted === sample.visible;
      }).length / samples.length;
      const score = normalizedError + (1 - visibilityMatches);
      if (score < best.score) {
        best = { score, phase, error: normalizedError, visibility: visibilityMatches };
      }
    }
    const measured = {
      angularDisplacementDegrees: best.error <= 0.16 ? maximum - minimum : 0,
      horizontalSpanPixels: compact(span),
      trajectoryErrorRatio: compact(best.error),
      visibilityMatchRatio: compact(best.visibility),
      fittedFeatureLongitudeDegrees: best.phase,
    };
    if (best.error > 0.16 || best.visibility < 0.68) {
      return fail("rotation_trajectory_mismatch", expected, measured);
    }
    return { passed: true, action, actorId: actor.id, expected, measured };
  }

  if (action === "orbits" || action === "phases") {
    const points = [];
    for (let index = 0; index <= 16; index += 1) {
      const value = minimum + (maximum - minimum) * index / 16;
      const point = render(value);
      if (point.x !== null) points.push({ degrees: value, x: point.x, y: point.y });
    }
    const pointXs = points.map((point) => point.x);
    const pointYs = points.map((point) => point.y);
    const centerX = (Math.max(...pointXs) + Math.min(...pointXs)) / 2;
    const centerY = (Math.max(...pointYs) + Math.min(...pointYs)) / 2;
    const radiusX = (Math.max(...pointXs) - Math.min(...pointXs)) / 2;
    const radiusY = (Math.max(...pointYs) - Math.min(...pointYs)) / 2;
    const radius = Math.sqrt(radiusX * radiusY);
    const actual = points.map((point) => Math.atan2(
      (point.y - centerY) / Math.max(1, radiusY),
      (point.x - centerX) / Math.max(1, radiusX),
    ));
    const circularDifference = (left, right) => Math.atan2(Math.sin(left - right), Math.cos(left - right));
    let bestError = Infinity;
    let bestDirection = 1;
    for (const direction of [1, -1]) {
      const offsets = points.map((point, index) => (
        actual[index] - direction * point.degrees * Math.PI / 180
      ));
      const offset = Math.atan2(
        offsets.reduce((sum, value) => sum + Math.sin(value), 0),
        offsets.reduce((sum, value) => sum + Math.cos(value), 0),
      );
      const error = Math.max(...points.map((point, index) => Math.abs(circularDifference(
        actual[index],
        offset + direction * point.degrees * Math.PI / 180,
      )))) * 180 / Math.PI;
      if (error < bestError) {
        bestError = error;
        bestDirection = direction;
      }
    }
    const expected = {
      angularDisplacementDegrees: maximum - minimum,
      maximumAngularErrorDegrees: 20,
      minimumOrbitRadiusPixels: 6,
    };
    const measured = {
      angularDisplacementDegrees: bestError <= 20 ? maximum - minimum : 0,
      maximumAngularErrorDegrees: compact(bestError),
      orbitRadiusPixels: compact(radius),
      direction: bestDirection,
    };
    if (points.length < 12 || radius < 6) return fail("actor_trajectory_static", expected, measured);
    if (bestError > 20) return fail("orbital_angle_mismatch", expected, measured);
    return { passed: true, action, actorId: actor.id, expected, measured };
  }

  if (action === "floats_sinks") {
    if (!referenceColor) {
      return fail(
        "waterline_signature_missing",
        { referenceColorDeclared: true },
        { referenceColorDeclared: false },
      );
    }
    const samples = [];
    for (let index = 0; index < 5; index += 1) {
      const value = minimum + (maximum - minimum) * index / 4;
      const body = render(value);
      const water = measure(referenceColor, referenceTolerance);
      const expectedFraction = outputAt(value);
      const measuredFraction = body.count && water.count
        ? Math.max(0, Math.min(1, (body.maxY - water.y) / Math.max(1, body.maxY - body.minY)))
        : null;
      samples.push({
        parameter: compact(value),
        expectedFraction: compact(expectedFraction),
        measuredFraction: measuredFraction === null ? null : compact(measuredFraction),
      });
    }
    const errors = samples.map((sample) => (
      sample.measuredFraction === null
        ? Infinity
        : Math.abs(sample.measuredFraction - sample.expectedFraction)
    ));
    const maximumError = Math.max(...errors);
    const expected = { maximumSubmergedFractionError: 0.15, sampleCount: 5 };
    const measured = { maximumSubmergedFractionError: compact(maximumError), samples };
    if (maximumError > 0.15) return fail("waterline_fraction_mismatch", expected, measured);
    return { passed: true, action, actorId: actor.id, expected, measured };
  }

  if (action === "responds") {
    const samples = [];
    for (let index = 0; index <= 8; index += 1) {
      const value = minimum + (maximum - minimum) * index / 8;
      const point = render(value);
      samples.push({
        value,
        output: outputAt(value),
        count: point.count,
        x: point.x,
        y: point.y,
        width: point.count ? point.maxX - point.minX + 1 : 0,
        height: point.count ? point.maxY - point.minY + 1 : 0,
      });
    }
    const correlation = (left, right) => {
      const leftMean = left.reduce((sum, value) => sum + value, 0) / left.length;
      const rightMean = right.reduce((sum, value) => sum + value, 0) / right.length;
      let numerator = 0;
      let leftSquare = 0;
      let rightSquare = 0;
      for (let index = 0; index < left.length; index += 1) {
        const a = left[index] - leftMean;
        const b = right[index] - rightMean;
        numerator += a * b;
        leftSquare += a * a;
        rightSquare += b * b;
      }
      return leftSquare && rightSquare ? numerator / Math.sqrt(leftSquare * rightSquare) : 0;
    };
    const outputs = samples.map((sample) => sample.output);
    const candidates = ["count", "x", "y", "width", "height"].map((key) => {
      const values = samples.map((sample) => sample[key]);
      return {
        key,
        correlation: Math.abs(correlation(outputs, values)),
        span: Math.max(...values) - Math.min(...values),
      };
    });
    candidates.sort((left, right) => right.correlation - left.correlation);
    const best = candidates[0];
    const visibleSamples = samples.filter((sample) => sample.count >= 8).length;
    const scale = best.key === "count"
      ? Math.max(16, Math.min(...samples.map((sample) => sample.count)))
      : 1;
    const normalizedSpan = best.span / scale;
    // Six pixels rejects label-only jitter; count may instead change by 15% for an actor that grows,
    // brightens, or gains field lines without translating. Correlation keeps the response causal.
    const minimumSpan = best.key === "count" ? 0.15 : 6;
    const expected = {
      // Seven samples cover the causal sweep while allowing a thin ray/field edge to clip at the
      // two extrema. The correlation and response-span checks still require a trackable actor.
      visibleSamplesAtLeast: 7,
      minimumAbsoluteCorrelation: 0.7,
      minimumActorResponseSpan: minimumSpan,
      heldStateMotionExpected: false,
    };
    const measured = {
      visibleSamples,
      responseMetric: best.key,
      absoluteCorrelation: compact(best.correlation),
      actorResponseSpan: compact(normalizedSpan),
    };
    if (visibleSamples < 7) return fail("response_actor_visibility_missing", expected, measured);
    if (best.correlation < 0.7 || normalizedSpan < minimumSpan) {
      return fail("actor_response_not_output_consistent", expected, measured);
    }
    return { passed: true, action, actorId: actor.id, expected, measured };
  }

  if (action === "propagates") {
    let period = outputAt(defaultValue);
    if (actor.tracking_output.endsWith("_ms")) period /= 1000;
    if (!(period > 0)) {
      return fail("propagation_period_unavailable", { finitePeriodSeconds: true }, { period });
    }
    simulation.setParameter(parameter.id, defaultValue, 0);
    const first = measure(color, tolerance, true).signal;
    simulation.setParameter(parameter.id, defaultValue, period / 4);
    const second = measure(color, tolerance, true).signal;
    const paired = [];
    for (let x = 0; x < first.length; x += 1) {
      if (first[x] !== null && second[x] !== null) paired.push(x);
    }
    const firstMean = paired.reduce((sum, x) => sum + first[x], 0) / Math.max(1, paired.length);
    const secondMean = paired.reduce((sum, x) => sum + second[x], 0) / Math.max(1, paired.length);
    let dominant = { amplitude: 0, phaseFirst: 0, phaseSecond: 0, cycles: 0 };
    for (let cycles = 1; cycles <= 16; cycles += 1) {
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
          phaseFirst: Math.atan2(firstSin, firstCos),
          phaseSecond: Math.atan2(secondSin, secondCos),
          cycles,
        };
      }
    }
    const phaseShift = Math.abs(Math.atan2(
      Math.sin(dominant.phaseSecond - dominant.phaseFirst),
      Math.cos(dominant.phaseSecond - dominant.phaseFirst),
    ));
    const phaseError = Math.abs(phaseShift - Math.PI / 2);
    const expected = { phaseShiftRadians: compact(Math.PI / 2), maximumErrorRadians: 0.6 };
    const measured = {
      phaseShiftRadians: compact(phaseShift),
      phaseErrorRadians: compact(phaseError),
      dominantSpatialCycles: dominant.cycles,
      matchedColumns: paired.length,
    };
    if (paired.length < 40 || dominant.amplitude <= 0 || phaseError > 0.6) {
      return fail("propagation_phase_shift_mismatch", expected, measured);
    }
    return { passed: true, action, actorId: actor.id, expected, measured };
  }

  if (action === "flows") {
    const lowValue = minimum + (maximum - minimum) * 0.15;
    const highValue = minimum + (maximum - minimum) * 0.85;
    const deltaTime = 0.08;
    const displacement = (value) => {
      const start = render(value, 0, 12);
      const end = render(value, deltaTime, 1);
      return Math.hypot(end.x - start.x, end.y - start.y);
    };
    const lowRate = outputAt(lowValue);
    const highRate = outputAt(highValue);
    const lowDisplacement = displacement(lowValue);
    const highDisplacement = displacement(highValue);
    const expectedRatio = Math.max(lowRate, highRate) / Math.max(1e-9, Math.min(lowRate, highRate));
    const measuredRatio = Math.max(lowDisplacement, highDisplacement)
      / Math.max(1e-9, Math.min(lowDisplacement, highDisplacement));
    const ratioError = Math.abs(measuredRatio - expectedRatio) / expectedRatio;
    const expected = { rateRatio: compact(expectedRatio), maximumRatioError: 0.35 };
    const measured = {
      displacementRatio: compact(measuredRatio),
      ratioError: compact(ratioError),
      lowDisplacementPixels: compact(lowDisplacement),
      highDisplacementPixels: compact(highDisplacement),
    };
    if (Math.max(lowDisplacement, highDisplacement) < 2) {
      return fail("actor_trajectory_static", expected, measured);
    }
    if (ratioError > 0.35) return fail("flow_rate_mismatch", expected, measured);
    return { passed: true, action, actorId: actor.id, expected, measured };
  }

  return fail("unsupported_actor_action", { supportedAction: true }, { action });
})()
