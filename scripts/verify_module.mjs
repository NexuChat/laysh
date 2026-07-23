import fs from "node:fs";
import vm from "node:vm";
import { evaluateCausalResponse } from "./causal_response.mjs";

const [sourcePath, understandingPath] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath, "utf8");
const understanding = JSON.parse(fs.readFileSync(understandingPath, "utf8"));
const trustedRuntimeSource = fs.readFileSync(
  new URL("../sim_shell/contract.js", import.meta.url),
  "utf8",
);
const permittedAbi = ["destroy", "init", "resize", "setParameter", "test", "version"];
const failures = [];
const passingNumericFixtures = [];
const sceneGeometrySamples = [];
const diagnosableCanvasApis = [
  "createImageData",
  "createPattern",
  "drawFocusIfNeeded",
  "drawImage",
  "getImageData",
  "getTransform",
  "isPointInPath",
  "isPointInStroke",
  "putImageData",
  "scrollPathIntoView",
];
let checkCount = 0;
let frames = 0;
let drawOperations = 0;
let causalResponseReport = null;
let temporalCausalMatrixReport = null;

function addFailure(gate, code, expected, actual, extra = {}) {
  failures.push({ gate, code, expected, actual, ...extra });
}

function sameValues(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function safeValue(value) {
  if (typeof value === "number" && !Number.isFinite(value)) return String(value);
  return value;
}

function safeRuntimeError(error) {
  const actual = { error_type: error?.name || "Error" };
  const message = String(error?.message || "");
  const unsupported = diagnosableCanvasApis.find(
    (name) => message.includes(`${name} is not a function`),
  );
  if (unsupported) actual.unsupported_canvas_api = unsupported;
  return actual;
}

function drawOperation() {
  drawOperations += 1;
}

function createGradient() {
  return { addColorStop() {} };
}

function captureSceneGeometry() {
  if (!Array.isArray(canvas.__layshSceneGeometry)) return;
  try {
    const copied = JSON.parse(JSON.stringify(canvas.__layshSceneGeometry));
    if (Array.isArray(copied)) sceneGeometrySamples.push(...copied);
  } catch {
    // The Python validator fails closed when usable samples are absent.
  }
}

function copied(value) {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return null;
  }
}

function distinctAboveTolerance(values, tolerance) {
  const finiteValues = values.filter((value) => Number.isFinite(value));
  if (finiteValues.length === 0) return 0;
  const ordered = [...finiteValues].sort((left, right) => left - right);
  let distinct = 1;
  let previous = ordered[0];
  for (const value of ordered.slice(1)) {
    if (Math.abs(value - previous) > tolerance) {
      distinct += 1;
      previous = value;
    }
  }
  return distinct;
}

function actorTolerance(channel, samples) {
  if (channel === "x" || channel === "y") {
    return Math.max(1e-6, Math.min(canvas.width, canvas.height) * 0.001);
  }
  if (channel === "rotation") return 0.001;
  if (channel === "opacity") return 0.005;
  const values = samples
    .map((sample) => Math.abs(Number(sample?.response?.visualValue)))
    .filter((value) => Number.isFinite(value) && value > 1e-9);
  const baseline = values.length > 0 ? Math.min(...values) : 1;
  return Math.max(1e-6, baseline * 0.005);
}

function actorCommandPresent(sample) {
  const actorId = sample?.response?.actorId;
  const scene = sample?.scene;
  if (typeof actorId !== "string" || !Array.isArray(scene)) return false;
  return scene.some((state) => Array.isArray(state?.objects)
    && state.objects.some((object) => object?.id === actorId && object?.scientific === true));
}

function declaredActorState(sample, channel) {
  const actorId = sample?.response?.actorId;
  const scene = sample?.scene;
  if (typeof actorId !== "string" || !Array.isArray(scene)) return null;
  const objects = scene.flatMap((state) => (
    Array.isArray(state?.objects) ? state.objects : []
  ));
  const actor = objects.find(
    (object) => object?.id === actorId && object?.scientific === true,
  );
  const geometry = actor?.geometry;
  if (!geometry || typeof geometry !== "object") return null;
  if (channel === "x") return Number.isFinite(geometry.cx) ? geometry.cx : null;
  if (channel === "y") return Number.isFinite(geometry.cy) ? geometry.cy : null;
  if (channel === "rotation") {
    return Number.isFinite(geometry.rotation) ? geometry.rotation : null;
  }
  if (channel === "opacity") {
    return Number.isFinite(geometry.opacity) ? geometry.opacity : null;
  }
  if (channel === "size") {
    if (Number.isFinite(geometry.radius)) return geometry.radius;
    const radiusX = Number(geometry.radiusX ?? geometry.radius_x);
    const radiusY = Number(geometry.radiusY ?? geometry.radius_y);
    return Number.isFinite(radiusX) && Number.isFinite(radiusY)
      ? Math.max(radiusX, radiusY) : null;
  }
  return null;
}

function monotonicDirection(samples, field, tolerance) {
  const ordered = [...samples].sort(
    (left, right) => left.parameterValue - right.parameterValue,
  );
  const deltas = ordered.slice(1).map(
    (sample, index) => Number(sample[field]) - Number(ordered[index][field]),
  );
  if (deltas.every((delta) => delta > tolerance)) return 1;
  if (deltas.every((delta) => delta < -tolerance)) return -1;
  return 0;
}

function temporalMatrixFailure(code, expected, actual, extra = {}) {
  return {
    gate: "temporal_causal_matrix",
    code,
    expected,
    actual,
    ...extra,
  };
}

function periodForMatrix(simulationApi, defaultInputs, outputs, parameterSpan) {
  let tested = {};
  try {
    sandbox.inputs = defaultInputs;
    tested = new vm.Script("window.LayshSimulation.test(inputs)")
      .runInContext(sandbox, { timeout: 250 });
  } catch {
    tested = {};
  }
  const periodOutput = outputs.find(
    (name) => /(?:^|_)(?:period|duration|cycle_time|time_span)(?:_|$)/.test(name),
  );
  const declaredPeriod = Number(tested?.[periodOutput]);
  if (periodOutput && Number.isFinite(declaredPeriod) && Math.abs(declaredPeriod) > 1e-9) {
    return { period: Math.abs(declaredPeriod), source: periodOutput };
  }
  return {
    period: Math.max(Math.abs(parameterSpan), 1),
    source: "normalized_span",
  };
}

function evaluateTemporalCausalMatrix(simulationApi, representation) {
  const matrixFailures = [];
  let matrixCheckCount = 0;
  const parameter = understanding.primary_parameter;
  const parameterValues = [parameter.min, parameter.default, parameter.max].map(Number);
  const defaultInputs = {
    [parameter.id]: parameter.default,
    ...(understanding.secondary_parameter
      ? { [understanding.secondary_parameter.id]: understanding.secondary_parameter.default }
      : {}),
  };
  const period = periodForMatrix(
    simulationApi,
    defaultInputs,
    understanding.module_spec.outputs,
    parameter.max - parameter.min,
  );
  const timeSamples = [0, period.period / 4, period.period / 2, period.period * 3 / 4];
  const samples = [];

  for (const parameterValue of parameterValues) {
    for (const timeMs of timeSamples) {
      new vm.Script("window.LayshSimulation.destroy()")
        .runInContext(sandbox, { timeout: 250 });
      sandbox.options = { ...sandbox.options, reducedMotion: false };
      new vm.Script("window.LayshSimulation.init(options)")
        .runInContext(sandbox, { timeout: 500 });
      sandbox.parameterName = parameter.id;
      sandbox.parameterValue = parameterValue;
      sandbox.elapsedMs = timeMs;
      new vm.Script(
        "window.LayshSimulation.setParameter(parameterName, parameterValue, elapsedMs)",
      ).runInContext(sandbox, { timeout: 250 });
      const response = copied(canvas.__layshActorResponse ?? null);
      samples.push({
        parameterValue,
        timeMs,
        response,
        scene: copied(canvas.__layshSceneGeometry ?? null),
      });
      captureSceneGeometry();
    }
  }

  const actorProofs = Array.isArray(representation.proof_channels)
    ? representation.proof_channels.filter((proof) => proof?.carrier === "actor")
    : [];
  for (const proof of actorProofs) {
    const proofSamples = samples.filter(
      (sample) => sample.response?.outputName === proof.output_name
        && sample.response?.channel === proof.channel,
    );
    matrixCheckCount += 1;
    if (proofSamples.length !== samples.length) {
      matrixFailures.push(temporalMatrixFailure(
        "representation_actor_proof_missing",
        {
          output_name: proof.output_name,
          channel: proof.channel,
          matrix_samples: samples.length,
        },
        { matching_actor_samples: proofSamples.length },
      ));
      continue;
    }

    matrixCheckCount += 1;
    const declaredActorSamples = proofSamples.filter(actorCommandPresent).length;
    if (declaredActorSamples !== proofSamples.length) {
      matrixFailures.push(temporalMatrixFailure(
        "declared_actor_command_missing",
        { scientific_actor_command_samples: proofSamples.length },
        { scientific_actor_command_samples: declaredActorSamples },
        { actor_id: proofSamples[0]?.response?.actorId },
      ));
    }

    const tolerance = actorTolerance(proof.channel, proofSamples);
    const parameterSweep = proofSamples.filter((sample) => Math.abs(sample.timeMs) <= 1e-9);
    const declaredStates = parameterSweep.map(
      (sample) => declaredActorState(sample, proof.channel),
    );
    if (declaredStates.every(Number.isFinite)) {
      matrixCheckCount += 1;
      const declaredDistinct = distinctAboveTolerance(declaredStates, tolerance);
      const mismatchedStates = parameterSweep.filter((sample, index) =>
        Math.abs(Number(sample.response.visualValue) - declaredStates[index]) > tolerance);
      if (declaredDistinct < 2 || mismatchedStates.length > 0) {
        matrixFailures.push(temporalMatrixFailure(
          "declared_actor_command_static",
          {
            changing_scientific_actor_command: true,
            response_matches_declared_actor: true,
            tolerance,
          },
          {
            distinct_declared_actor_states: declaredDistinct,
            response_mismatch_samples: mismatchedStates.length,
          },
          { actor_id: proofSamples[0]?.response?.actorId, channel: proof.channel },
        ));
      }
    }
    const parameterStates = parameterSweep.map((sample) => sample.response.visualValue);
    matrixCheckCount += 1;
    const parameterDistinct = distinctAboveTolerance(parameterStates, tolerance);
    if (parameterDistinct < 2) {
      matrixFailures.push(temporalMatrixFailure(
        "actor_parameter_response_missing",
        {
          output_name: proof.output_name,
          channel: proof.channel,
          minimum_distinct_actor_states: 2,
          tolerance,
        },
        { distinct_actor_states: parameterDistinct },
      ));
    }

    matrixCheckCount += 1;
    const outputSweep = parameterSweep.map((sample) => ({
      parameterValue: sample.parameterValue,
      outputValue: Number(sample.response.outputValue),
      visualValue: Number(sample.response.visualValue),
    }));
    const outputDirection = monotonicDirection(outputSweep, "outputValue", 1e-9);
    const visualDirection = monotonicDirection(outputSweep, "visualValue", tolerance);
    if (outputDirection !== 0) {
      const expectedVisualDirection = proofSamples[0].response.relation === "inverse"
        ? -outputDirection : outputDirection;
      if (visualDirection !== expectedVisualDirection) {
        matrixFailures.push(temporalMatrixFailure(
          "causal_direction_mismatch",
          {
            relation: proofSamples[0].response.relation,
            visual_direction: expectedVisualDirection,
          },
          { visual_direction: visualDirection, output_direction: outputDirection },
          { output_name: proof.output_name, channel: proof.channel },
        ));
      }
    }
  }

  let timeDistinctActorStates = 0;
  if (representation.motion_model === "cyclic" || representation.motion_model === "time_driven") {
    matrixCheckCount += 1;
    const defaultTimeSamples = samples.filter(
      (sample) => Math.abs(sample.parameterValue - Number(parameter.default)) <= 1e-9,
    );
    const tolerance = actorTolerance(
      defaultTimeSamples[0]?.response?.channel,
      defaultTimeSamples,
    );
    const declaredTimeStates = defaultTimeSamples.map((sample) =>
      declaredActorState(sample, sample.response?.channel));
    const temporalValues = declaredTimeStates.every(Number.isFinite)
      ? declaredTimeStates
      : defaultTimeSamples.map((sample) => sample.response?.visualValue);
    timeDistinctActorStates = distinctAboveTolerance(
      temporalValues,
      tolerance,
    );
    if (timeDistinctActorStates < 2) {
      matrixFailures.push(temporalMatrixFailure(
        "actor_motion_missing",
        {
          motion_model: representation.motion_model,
          minimum_distinct_actor_states: 2,
          time_samples_ms: timeSamples,
        },
        { distinct_actor_states: timeDistinctActorStates },
      ));
    }
  }

  return {
    passed: matrixFailures.length === 0,
    checkCount: matrixCheckCount,
    sample_count: samples.length,
    parameter_values: parameterValues,
    time_samples_ms: timeSamples,
    period_source: period.source,
    actor_proof_count: actorProofs.length,
    time_distinct_actor_states: timeDistinctActorStates,
    failures: matrixFailures,
  };
}

const context2d = {
  clearRect: drawOperation,
  fillRect: drawOperation,
  strokeRect: drawOperation,
  beginPath: drawOperation,
  closePath: drawOperation,
  moveTo: drawOperation,
  lineTo: drawOperation,
  quadraticCurveTo: drawOperation,
  bezierCurveTo: drawOperation,
  arcTo: drawOperation,
  arc: drawOperation,
  ellipse: drawOperation,
  rect: drawOperation,
  roundRect: drawOperation,
  fill: drawOperation,
  stroke: drawOperation,
  fillText: drawOperation,
  strokeText: drawOperation,
  save() {},
  restore() {},
  clip() {},
  translate() {},
  rotate() {},
  scale() {},
  transform() {},
  setTransform() {},
  resetTransform() {},
  reset() {},
  setLineDash() {},
  getLineDash() { return []; },
  createLinearGradient: createGradient,
  createRadialGradient: createGradient,
  createConicGradient: createGradient,
  measureText() { return { width: 10 }; },
  set fillStyle(_value) {},
  set strokeStyle(_value) {},
  set lineWidth(_value) {},
  set globalAlpha(_value) {},
  set font(_value) {},
  set textAlign(_value) {},
  set textBaseline(_value) {},
  set direction(_value) {},
  set lineCap(_value) {},
  set lineJoin(_value) {},
};
const canvas = {
  width: 720,
  height: 400,
  style: {},
  getContext(kind) { return kind === "2d" ? context2d : null; },
  getBoundingClientRect() {
    return { x: 0, y: 0, top: 0, right: this.width, bottom: this.height, left: 0,
      width: this.width, height: this.height };
  },
};
context2d.canvas = canvas;
const sandbox = { window: {}, Math, Number, Object, Array, JSON };
vm.createContext(sandbox, { codeGeneration: { strings: false, wasm: false } });
new vm.Script(trustedRuntimeSource, { filename: "trusted-runtime.js" })
  .runInContext(sandbox, { timeout: 250 });
const trustedReadout = sandbox.window.LayshReadout;

let simulation = null;
try {
  new vm.Script(source, { filename: "candidate.js" }).runInContext(sandbox, { timeout: 500 });
} catch (error) {
  addFailure(
    "syntax_runtime",
    "module_evaluation_failed",
    { evaluates_in_disposable_vm: true },
    { error_type: error?.name || "Error" },
  );
}
simulation = sandbox.window.LayshSimulation;
checkCount += 1;

if (simulation) {
  const exportedKeys = Object.keys(simulation).sort();
  const unexpectedKeys = exportedKeys.filter((key) => !permittedAbi.includes(key));
  const missingKeys = permittedAbi.filter((key) => !exportedKeys.includes(key));
  if (!sameValues(exportedKeys, permittedAbi)) {
    addFailure(
      "interface",
      "exported_keys_mismatch",
      { permitted_abi: permittedAbi },
      { exported_keys: exportedKeys, unexpected_keys: unexpectedKeys, missing_keys: missingKeys },
    );
  }
  checkCount += 1;

  if (simulation.version !== 1) {
    addFailure(
      "interface",
      "version_mismatch",
      { version: 1, type: "number" },
      { version: safeValue(simulation.version), type: typeof simulation.version },
    );
  }
  checkCount += 1;

  const callable = ["init", "setParameter", "test", "resize", "destroy"].every(
    (name) => typeof simulation[name] === "function",
  );
  if (callable) {
    sandbox.options = {
      canvas,
      context: context2d,
      width: 720,
      height: 400,
      locale: understanding.lang,
      reducedMotion: true,
      emitFrame: () => { frames += 1; },
    };
    try {
      new vm.Script("window.LayshSimulation.init(options)")
        .runInContext(sandbox, { timeout: 500 });
      captureSceneGeometry();
    } catch (error) {
      addFailure(
        "runtime_init",
        "init_failed",
        { accepts_trusted_options: [
          "canvas", "context", "width", "height", "locale", "reducedMotion", "emitFrame",
        ] },
        safeRuntimeError(error),
      );
    }
    checkCount += 1;

    if (frames < 1) {
      addFailure(
        "runtime_init",
        "first_frame_missing",
        { minimum_emit_frame_calls: 1 },
        { emit_frame_calls: frames },
      );
    }
    checkCount += 1;

    for (const fixture of understanding.checks) {
      const leftInputs = fixture.kind === "numeric" ? fixture.inputs : fixture.left_inputs;
      const leftObject = Object.fromEntries(leftInputs.map(({ name, value }) => [name, value]));
      sandbox.inputs = leftObject;
      const framesBefore = frames;
      const drawsBefore = drawOperations;
      let left;
      try {
        left = new vm.Script("window.LayshSimulation.test(inputs)")
          .runInContext(sandbox, { timeout: 250 });
      } catch (error) {
        addFailure(
          "invariant",
          "fixture_execution_failed",
          { returns_declared_outputs: understanding.module_spec.outputs },
          { error_type: error?.name || "Error" },
          { fixture_id: fixture.id, inputs: leftInputs },
        );
        checkCount += 1;
        continue;
      }

      const actualOutputs = Object.keys(left || {}).sort();
      const expectedOutputs = [...understanding.module_spec.outputs].sort();
      if (!sameValues(actualOutputs, expectedOutputs)) {
        addFailure(
          "interface",
          "output_names_mismatch",
          { output_names: expectedOutputs },
          { output_names: actualOutputs },
          { fixture_id: fixture.id, inputs: leftInputs },
        );
      }
      if (frames !== framesBefore || drawOperations !== drawsBefore) {
        addFailure(
          "invariant",
          "test_has_visible_side_effect",
          { frame_delta: 0, draw_operation_delta: 0 },
          { frame_delta: frames - framesBefore, draw_operation_delta: drawOperations - drawsBefore },
          { fixture_id: fixture.id, inputs: leftInputs },
        );
      }

      const leftValue = left?.[fixture.output];
      if (!Number.isFinite(leftValue)) {
        addFailure(
          "invariant",
          "non_finite_output",
          { output: fixture.output, finite: true },
          { output: fixture.output, value: safeValue(leftValue) },
          { fixture_id: fixture.id, inputs: leftInputs },
        );
      } else if (fixture.kind === "numeric") {
        if (Math.abs(leftValue - fixture.expected) > fixture.tolerance) {
          addFailure(
            "invariant",
            "numeric_fixture_mismatch",
            { output: fixture.output, value: fixture.expected, tolerance: fixture.tolerance },
            { output: fixture.output, value: leftValue },
            { fixture_id: fixture.id, inputs: fixture.inputs },
          );
        } else {
          passingNumericFixtures.push({ fixture_id: fixture.id, output: fixture.output });
        }
      } else {
        const rightInputs = fixture.right_inputs;
        sandbox.inputs = Object.fromEntries(rightInputs.map(({ name, value }) => [name, value]));
        let right;
        try {
          right = new vm.Script("window.LayshSimulation.test(inputs)")
            .runInContext(sandbox, { timeout: 250 });
        } catch (error) {
          addFailure(
            "invariant",
            "fixture_execution_failed",
            { returns_output: fixture.output },
            { error_type: error?.name || "Error" },
            { fixture_id: fixture.id, inputs: rightInputs },
          );
          checkCount += 1;
          continue;
        }
        const rightValue = right?.[fixture.output];
        const relationPassed =
          Number.isFinite(rightValue)
          && (
            (fixture.relation === "right_gt_left" && rightValue / leftValue >= fixture.minimum_ratio)
            || (fixture.relation === "right_lt_left" && leftValue / rightValue >= fixture.minimum_ratio)
            || (fixture.relation === "right_eq_left" && rightValue === leftValue)
          );
        if (!relationPassed) {
          addFailure(
            "invariant",
            "relation_fixture_mismatch",
            { output: fixture.output, relation: fixture.relation, minimum_ratio: fixture.minimum_ratio },
            { left_value: safeValue(leftValue), right_value: safeValue(rightValue) },
            { fixture_id: fixture.id, inputs: { left: leftInputs, right: rightInputs } },
          );
        }
      }
      checkCount += 1;
    }

    const parameter = understanding.primary_parameter;
    const output = understanding.module_spec.outputs[0];
    const formatter = trustedReadout.forLesson(understanding);
    const defaultInputs = {
      [parameter.id]: parameter.default,
      ...(understanding.secondary_parameter
        ? { [understanding.secondary_parameter.id]: understanding.secondary_parameter.default }
        : {}),
    };
    const parameterRange = parameter.max - parameter.min;
    const sampleValues = [...new Set([
      parameter.min,
      parameter.min + parameterRange * 0.25,
      parameter.default,
      parameter.min + parameterRange * 0.5,
      parameter.min + parameterRange * 0.75,
      parameter.max,
    ].map(Number))];
    const sampleEndpoints = sampleValues.map((parameterValue) => ({
      inputs: { ...defaultInputs, [parameter.id]: parameterValue },
      parameterValue,
    }));
    const minimumEndpoint = sampleEndpoints[0];
    const maximumEndpoint = sampleEndpoints[sampleEndpoints.length - 1];
    try {
      const formattedSamples = sampleEndpoints.map((endpoint) => {
        sandbox.inputs = endpoint.inputs;
        const result = new vm.Script("window.LayshSimulation.test(inputs)")
          .runInContext(sandbox, { timeout: 250 });
        return formatter.format(result?.[output]);
      });
      const minimumFormatted = formattedSamples[0];
      const maximumFormatted = formattedSamples[formattedSamples.length - 1];
      if (new Set(formattedSamples).size === 1) {
        addFailure(
          "readout_visibility",
          "formatted_endpoints_indistinguishable",
          {
            distinct_formatted_endpoints: true,
            maximum_fraction_digits: trustedReadout.maximumFractionDigits,
          },
          {
            minimum_input: minimumEndpoint.parameterValue,
            maximum_input: maximumEndpoint.parameterValue,
            minimum_formatted: minimumFormatted,
            maximum_formatted: maximumFormatted,
          },
          {
            parameter: parameter.id,
            output,
            message: `Readout for parameter ${parameter.id} formats sampled range endpoints as `
              + `"${minimumFormatted}" and "${maximumFormatted}".`,
          },
        );
      }
    } catch (error) {
      addFailure(
        "readout_visibility",
        "endpoint_execution_failed",
        {
          evaluates_extreme_inputs: [
            minimumEndpoint.parameterValue,
            maximumEndpoint.parameterValue,
          ],
        },
        { error_type: error?.name || "Error" },
        { parameter: parameter.id, output },
      );
    }
    checkCount += 1;

    if (source.includes("LAYSH_CAUSAL_RESPONSE_V1")) {
      const causalSamples = [];
      const temporalSamples = [];
      const fixtureValues = understanding.checks.flatMap((check) => {
        const inputs = check.kind === "numeric"
          ? check.inputs
          : [...check.left_inputs, ...check.right_inputs];
        return inputs
          .filter((input) => input.name === parameter.id)
          .map((input) => Number(input.value));
      });
      const causalValues = [...new Set([
        parameter.min,
        parameter.min + parameterRange * 0.25,
        parameter.min + parameterRange * 0.5,
        parameter.min + parameterRange * 0.75,
        parameter.max,
        ...(parameter.min < 0 && parameter.max > 0 ? [0] : []),
        ...fixtureValues,
      ].map((value) => Number(Number(value).toPrecision(12))))].sort((left, right) => left - right);
      try {
        for (const parameterValue of causalValues) {
          sandbox.parameterName = parameter.id;
          sandbox.parameterValue = parameterValue;
          new vm.Script("window.LayshSimulation.setParameter(parameterName, parameterValue)")
            .runInContext(sandbox, { timeout: 250 });
          captureSceneGeometry();
          causalSamples.push(JSON.parse(JSON.stringify(canvas.__layshActorResponse ?? null)));
        }
        if (causalSamples.some((sample) => sample?.temporalMode === "cyclic")) {
          new vm.Script("window.LayshSimulation.destroy()")
            .runInContext(sandbox, { timeout: 250 });
          sandbox.options = { ...sandbox.options, reducedMotion: false };
          new vm.Script("window.LayshSimulation.init(options)")
            .runInContext(sandbox, { timeout: 250 });
          sandbox.parameterName = parameter.id;
          sandbox.parameterValue = parameter.default;
          sandbox.elapsedMs = 100;
          for (let index = 0; index < 4; index += 1) {
            new vm.Script(
              "window.LayshSimulation.setParameter(parameterName, parameterValue, elapsedMs)",
            ).runInContext(sandbox, { timeout: 250 });
            temporalSamples.push(
              JSON.parse(JSON.stringify(canvas.__layshActorResponse ?? null)),
            );
          }
        }
      } catch {
        // The shared evaluator below fails closed on missing or malformed evidence.
      }
      causalResponseReport = {
        ...evaluateCausalResponse({
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
        samples: causalSamples,
        temporalSamples,
        }),
        samples: causalSamples,
        temporalSamples,
      };
      failures.push(...causalResponseReport.failures);
      checkCount += causalResponseReport.checkCount;
    }

    const representation = simulation.spec?.representation;
    if (representation && typeof representation === "object") {
      try {
        temporalCausalMatrixReport = evaluateTemporalCausalMatrix(
          simulation,
          representation,
        );
        failures.push(...temporalCausalMatrixReport.failures);
        checkCount += temporalCausalMatrixReport.checkCount;
      } catch (error) {
        temporalCausalMatrixReport = {
          passed: false,
          checkCount: 1,
          sample_count: 0,
          failures: [
            temporalMatrixFailure(
              "temporal_matrix_execution_failed",
              { bounded_matrix_evaluation: true },
              safeRuntimeError(error),
            ),
          ],
        };
        failures.push(...temporalCausalMatrixReport.failures);
        checkCount += temporalCausalMatrixReport.checkCount;
      }
    }
  }
}

process.stdout.write(JSON.stringify({
  passed: failures.length === 0,
  check_count: checkCount,
  fixture_count: understanding.checks.length,
  first_frame: frames > 0,
  passing_numeric_fixtures: passingNumericFixtures,
  scene_geometry_samples: sceneGeometrySamples,
  causal_response: causalResponseReport,
  temporal_causal_matrix: temporalCausalMatrixReport,
  failures,
}));
