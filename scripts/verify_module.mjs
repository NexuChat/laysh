import fs from "node:fs";
import vm from "node:vm";

const [sourcePath, understandingPath] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath, "utf8");
const understanding = JSON.parse(fs.readFileSync(understandingPath, "utf8"));
let frames = 0;

const context2d = {
  clearRect() {},
  fillRect() {},
  beginPath() {},
  arc() {},
  fill() {},
  stroke() {},
  save() {},
  restore() {},
  clip() {},
  set fillStyle(_value) {},
  set strokeStyle(_value) {},
  set lineWidth(_value) {},
};
const canvas = { width: 720, height: 400 };
const sandbox = { window: {}, Math, Number, Object, Array, JSON };
vm.createContext(sandbox, { codeGeneration: { strings: false, wasm: false } });

try {
  new vm.Script(source, { filename: "candidate.js" }).runInContext(sandbox, { timeout: 500 });
  const simulation = sandbox.window.LayshSimulation;
  const expectedKeys = ["destroy", "init", "resize", "setParameter", "test", "version"];
  const keys = Object.keys(simulation || {}).sort();
  if (JSON.stringify(keys) !== JSON.stringify(expectedKeys)) throw new Error("interface keys");
  if (simulation.version !== 1) throw new Error("version");

  sandbox.options = {
    canvas,
    context: context2d,
    width: 720,
    height: 400,
    locale: understanding.lang,
    reducedMotion: true,
    emitFrame: () => { frames += 1; },
  };
  new vm.Script("window.LayshSimulation.init(options)").runInContext(sandbox, { timeout: 500 });
  if (frames < 1) throw new Error("first frame");

  let fixtureCount = 0;
  for (const fixture of understanding.checks) {
    sandbox.inputs = fixture.kind === "numeric" ? fixture.inputs : fixture.left_inputs;
    const left = new vm.Script("window.LayshSimulation.test(inputs)")
      .runInContext(sandbox, { timeout: 250 });
    const leftValue = left[fixture.output];
    if (!Number.isFinite(leftValue)) throw new Error("non-finite output");
    if (fixture.kind === "numeric") {
      if (Math.abs(leftValue - fixture.expected) > fixture.tolerance) throw new Error("numeric fixture");
    } else {
      sandbox.inputs = fixture.right_inputs;
      const right = new vm.Script("window.LayshSimulation.test(inputs)")
        .runInContext(sandbox, { timeout: 250 });
      const rightValue = right[fixture.output];
      if (!Number.isFinite(rightValue)) throw new Error("non-finite relation output");
      if (fixture.relation === "right_gt_left" && !(rightValue / leftValue >= fixture.minimum_ratio)) throw new Error("relation fixture");
      if (fixture.relation === "right_lt_left" && !(leftValue / rightValue >= fixture.minimum_ratio)) throw new Error("relation fixture");
      if (fixture.relation === "right_eq_left" && rightValue !== leftValue) throw new Error("relation fixture");
    }
    fixtureCount += 1;
  }

  process.stdout.write(JSON.stringify({ passed: true, fixture_count: fixtureCount, first_frame: true }));
} catch (error) {
  process.stderr.write(`verification failed: ${error.message}\n`);
  process.exitCode = 1;
}

