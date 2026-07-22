import fs from "node:fs";
import vm from "node:vm";

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
let checkCount = 0;
let frames = 0;
let drawOperations = 0;

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

function identifierTokens(value) {
  return String(value).toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
}

function drawOperation() {
  drawOperations += 1;
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
  arc: drawOperation,
  ellipse: drawOperation,
  rect: drawOperation,
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
  setTransform() {},
  resetTransform() {},
  setLineDash() {},
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
const canvas = { width: 720, height: 400 };
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
        { error_type: error?.name || "Error" },
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
    const [minimumEndpoint, maximumEndpoint] = formatter.endpoints;
    let minimumResult;
    let maximumResult;
    try {
      sandbox.inputs = minimumEndpoint.inputs;
      minimumResult = new vm.Script("window.LayshSimulation.test(inputs)")
        .runInContext(sandbox, { timeout: 250 });
      sandbox.inputs = maximumEndpoint.inputs;
      maximumResult = new vm.Script("window.LayshSimulation.test(inputs)")
        .runInContext(sandbox, { timeout: 250 });
      const minimumFormatted = formatter.format(minimumResult?.[output]);
      const maximumFormatted = formatter.format(maximumResult?.[output]);
      if (minimumFormatted === maximumFormatted) {
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
            message: `Readout for parameter ${parameter.id} formats both endpoints as `
              + `"${minimumFormatted}" and "${maximumFormatted}".`,
          },
        );
      }

      const declaredDefaults = {};
      for (const declaredParameter of [
        understanding.primary_parameter,
        understanding.secondary_parameter,
      ]) {
        if (declaredParameter) declaredDefaults[declaredParameter.id] = declaredParameter.default;
      }
      const sampleValues = [...new Set([
        Number(parameter.min),
        Number(parameter.default),
        Number(parameter.max),
      ])];
      const identitySamples = [];
      for (const parameterValue of sampleValues) {
        sandbox.inputs = { ...declaredDefaults, [parameter.id]: parameterValue };
        const result = new vm.Script("window.LayshSimulation.test(inputs)")
          .runInContext(sandbox, { timeout: 250 });
        identitySamples.push({ input: parameterValue, output: result?.[output] });
      }
      const primaryIdentity = identitySamples.length >= 2 && identitySamples.every((sample) => (
        Number.isFinite(sample.output)
        && Math.abs(sample.output - sample.input)
          <= Math.max(1e-9, Math.abs(sample.input) * 1e-12)
      ));
      const primaryTokens = identifierTokens(parameter.id);
      const outputTokens = new Set(identifierTokens(output));
      const outputRenamesPrimary = primaryTokens.length > 0
        && primaryTokens.every((token) => outputTokens.has(token));
      const outputFixtureUnits = new Set(
        understanding.checks
          .filter((fixture) => fixture.kind === "numeric" && fixture.output === output)
          .map((fixture) => fixture.unit),
      );
      const outputKeepsPrimaryUnit = outputFixtureUnits.size === 1
        && outputFixtureUnits.has(parameter.unit);
      if (primaryIdentity && outputRenamesPrimary && outputKeepsPrimaryUnit) {
        addFailure(
          "causal_observable",
          "primary_input_identity",
          {
            first_output_is_derived: true,
            primary_input_is_not_repeated: true,
          },
          { samples: identitySamples.map(({ input, output: observed }) => ({ input, output: observed })) },
          {
            parameter: parameter.id,
            output,
            message: `First output ${output} repeats primary parameter ${parameter.id}.`,
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
    checkCount += 2;
  }
}

process.stdout.write(JSON.stringify({
  passed: failures.length === 0,
  check_count: checkCount,
  fixture_count: understanding.checks.length,
  first_frame: frames > 0,
  passing_numeric_fixtures: passingNumericFixtures,
  scene_geometry_samples: sceneGeometrySamples,
  failures,
}));
