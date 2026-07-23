const CHANNELS = new Set(["x", "y", "rotation", "size", "opacity"]);
const RELATIONS = new Set(["direct", "inverse"]);
const TEMPORAL_MODES = new Set(["parameter_driven", "cyclic"]);
const BOUND_FIELDS = ["left", "top", "right", "bottom", "width", "height"];

function failure(code, expected, actual) {
  return { gate: "causal_response", code, expected, actual };
}

function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function distinctFinite(values) {
  return new Set(values.filter(finite).map((value) => value.toFixed(6))).size;
}

function commonSignature(sample) {
  return [
    sample.actorId,
    sample.outputName,
    sample.channel,
    sample.relation,
    sample.temporalMode,
  ].join("\u0000");
}

function validSample(sample) {
  if (!sample || typeof sample !== "object" || Array.isArray(sample)) return false;
  if (sample.schemaVersion !== "1.0") return false;
  if (typeof sample.actorId !== "string" || sample.actorId.length === 0) return false;
  if (typeof sample.outputName !== "string" || sample.outputName.length === 0) return false;
  if (!CHANNELS.has(sample.channel)) return false;
  if (!RELATIONS.has(sample.relation)) return false;
  if (!TEMPORAL_MODES.has(sample.temporalMode)) return false;
  if (![sample.parameterValue, sample.outputValue, sample.visualValue, sample.timeMs].every(finite)) {
    return false;
  }
  const bounds = sample.fittedBounds;
  return bounds && typeof bounds === "object"
    && BOUND_FIELDS.every((name) => finite(bounds[name]));
}

function visibleBounds(sample, canvasWidth, canvasHeight) {
  const bounds = sample.fittedBounds;
  const tolerance = 1;
  return bounds.width > 0
    && bounds.height > 0
    && bounds.right > bounds.left
    && bounds.bottom > bounds.top
    && Math.abs((bounds.right - bounds.left) - bounds.width) <= tolerance
    && Math.abs((bounds.bottom - bounds.top) - bounds.height) <= tolerance
    && bounds.left >= -tolerance
    && bounds.top >= -tolerance
    && bounds.right <= canvasWidth + tolerance
    && bounds.bottom <= canvasHeight + tolerance;
}

function relationMatches(samples, relation) {
  const ordered = [...samples].sort((left, right) => left.outputValue - right.outputValue);
  const expectedSign = relation === "direct" ? 1 : -1;
  let compared = 0;
  for (let index = 1; index < ordered.length; index += 1) {
    const outputDelta = ordered[index].outputValue - ordered[index - 1].outputValue;
    if (Math.abs(outputDelta) <= 1e-9) continue;
    const visualDelta = ordered[index].visualValue - ordered[index - 1].visualValue;
    if (expectedSign * visualDelta < -1e-6) return false;
    if (Math.abs(visualDelta) > 1e-6) compared += 1;
  }
  return compared >= 2;
}

function salience(samples, channel, canvasWidth, canvasHeight) {
  const values = samples.map((sample) => sample.visualValue);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = maximum - minimum;
  if (channel === "x" || channel === "y") {
    const threshold = 0.08 * Math.min(canvasWidth, canvasHeight);
    return { passed: range >= threshold, range, threshold };
  }
  if (channel === "rotation") {
    return { passed: range >= 0.15, range, threshold: 0.15 };
  }
  if (channel === "opacity") {
    return { passed: range >= 0.2, range, threshold: 0.2 };
  }
  const positive = values.filter((value) => value > 1e-9);
  const baseline = positive.length > 0 ? Math.min(...positive) : 0;
  const ratio = baseline > 0 ? range / baseline : 0;
  return { passed: ratio >= 0.15, range: ratio, threshold: 0.15 };
}

function neutralCrossingMatches(samples, channel, relation) {
  if (!new Set(["x", "y", "rotation"]).has(channel)) return true;
  const negative = samples.filter((sample) => sample.outputValue < -1e-9);
  const positive = samples.filter((sample) => sample.outputValue > 1e-9);
  if (negative.length === 0 || positive.length === 0) return true;
  const exactNeutral = samples.filter((sample) => Math.abs(sample.outputValue) <= 1e-9);
  if (exactNeutral.length === 0) return false;
  const expectedSign = relation === "direct" ? 1 : -1;
  const baseline = exactNeutral.reduce((total, sample) => total + sample.visualValue, 0)
    / exactNeutral.length;
  const negativeSide = negative.every(
    (sample) => expectedSign * (sample.visualValue - baseline) <= 1e-6,
  );
  const positiveSide = positive.every(
    (sample) => expectedSign * (sample.visualValue - baseline) >= -1e-6,
  );
  const visualRange = Math.max(...samples.map((sample) => sample.visualValue))
    - Math.min(...samples.map((sample) => sample.visualValue));
  const tolerance = Math.max(1e-6, visualRange * 0.05);
  return negativeSide
    && positiveSide
    && exactNeutral.every((sample) => Math.abs(sample.visualValue - baseline) <= tolerance);
}

function compactSignature(samples) {
  return {
    sample_count: samples.length,
    actor_count: new Set(samples.map((sample) => sample && sample.actorId)).size,
    output_count: new Set(samples.map((sample) => sample && sample.outputName)).size,
    channel_count: new Set(samples.map((sample) => sample && sample.channel)).size,
    relation_count: new Set(samples.map((sample) => sample && sample.relation)).size,
    temporal_mode_count: new Set(samples.map((sample) => sample && sample.temporalMode)).size,
  };
}

export function evaluateCausalResponse(evidence) {
  const failures = [];
  let checkCount = 0;
  const samples = Array.isArray(evidence && evidence.samples) ? evidence.samples : [];
  const temporalSamples = Array.isArray(evidence && evidence.temporalSamples)
    ? evidence.temporalSamples : [];
  const canvasWidth = Number(evidence && evidence.canvasWidth);
  const canvasHeight = Number(evidence && evidence.canvasHeight);

  checkCount += 1;
  if (samples.length < 5) {
    failures.push(failure(
      "causal_sample_coverage_missing",
      { minimum_parameter_samples: 5 },
      { parameter_samples: samples.length },
    ));
  }

  checkCount += 1;
  const canvasValid = finite(canvasWidth) && finite(canvasHeight)
    && canvasWidth > 0 && canvasHeight > 0;
  const samplesValid = samples.length > 0 && samples.every(validSample);
  if (!canvasValid || !samplesValid) {
    failures.push(failure(
      "causal_evidence_invalid",
      { schema_version: "1.0", finite_closed_evidence: true },
      { canvas_valid: canvasValid, valid_samples: samples.filter(validSample).length, samples: samples.length },
    ));
  }

  if (samplesValid) {
    checkCount += 1;
    const stable = new Set(samples.map(commonSignature)).size === 1;
    if (!stable) {
      failures.push(failure(
        "causal_actor_id_unstable",
        { one_stable_actor_output_channel_relation: true },
        compactSignature(samples),
      ));
    }

    checkCount += 1;
    const visibleCount = canvasValid
      ? samples.filter((sample) => visibleBounds(sample, canvasWidth, canvasHeight)).length
      : 0;
    if (visibleCount !== samples.length) {
      failures.push(failure(
        "causal_actor_not_visible",
        { visible_post_fit_bounds: samples.length },
        { visible_post_fit_bounds: visibleCount, samples: samples.length },
      ));
    }

    checkCount += 1;
    const distinctStates = distinctFinite(samples.map((sample) => sample.visualValue));
    if (distinctStates < 3) {
      failures.push(failure(
        "causal_response_static",
        { minimum_distinct_actor_states: 3 },
        { distinct_actor_states: distinctStates },
      ));
    }

    const reference = samples[0];
    checkCount += 1;
    if (!relationMatches(samples, reference.relation)) {
      failures.push(failure(
        "causal_relation_mismatch",
        { relation: reference.relation, monotonic_actor_response: true },
        { relation: reference.relation, monotonic_actor_response: false },
      ));
    }

    checkCount += 1;
    const responseSalience = canvasValid
      ? salience(samples, reference.channel, canvasWidth, canvasHeight)
      : { passed: false, range: 0, threshold: null };
    if (!responseSalience.passed) {
      failures.push(failure(
        "causal_response_not_salient",
        { channel: reference.channel, minimum_range: responseSalience.threshold },
        { channel: reference.channel, observed_range: responseSalience.range },
      ));
    }

    checkCount += 1;
    if (!neutralCrossingMatches(samples, reference.channel, reference.relation)) {
      failures.push(failure(
        "causal_neutral_crossing_missing",
        { signed_output_crossing_matches_visual_neutral: true },
        { signed_output_crossing_matches_visual_neutral: false },
      ));
    }

    if (reference.temporalMode === "cyclic") {
      checkCount += 1;
      const temporalValid = temporalSamples.length >= 4
        && temporalSamples.every(validSample)
        && new Set(temporalSamples.map(commonSignature)).size === 1
        && temporalSamples.every((sample) => sample.actorId === reference.actorId)
        && distinctFinite(temporalSamples.map((sample) => sample.timeMs)) >= 4;
      if (!temporalValid) {
        failures.push(failure(
          "causal_temporal_evidence_missing",
          { minimum_timestamps: 4, stable_actor: true },
          { timestamps: distinctFinite(temporalSamples.map((sample) => sample && sample.timeMs)) },
        ));
      } else {
        const temporalStates = distinctFinite(
          temporalSamples.map((sample) => sample.visualValue),
        );
        const temporalSalience = canvasValid
          ? salience(temporalSamples, reference.channel, canvasWidth, canvasHeight)
          : { passed: false };
        if (temporalStates < 3 || !temporalSalience.passed) {
          failures.push(failure(
            "causal_actor_temporal_motion_missing",
            { minimum_distinct_actor_states: 3, salient_actor_motion: true },
            { distinct_actor_states: temporalStates, salient_actor_motion: temporalSalience.passed },
          ));
        }
      }
    }
  }

  return { passed: failures.length === 0, checkCount, failures };
}
