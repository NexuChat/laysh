import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { evaluateCausalResponse } from "./causal_response.mjs";

const artifactPath = path.resolve(process.argv[2]);
const artifactSource = fs.readFileSync(artifactPath, "utf8");
const causalMarkerPresent = /\/\*\s*LAYSH_CAUSAL_RESPONSE_V1\s*\*\//.test(artifactSource);
// WHY THIS IS A SEARCH AND NOT A CONSTANT. This was `process.env.CHROME_BIN ||
// "/usr/bin/google-chrome"`, and on the host that actually serves laysh.mlki.app
// there is no google-chrome at all — no chromium, no chromium-browser, nothing
// at any standard path. So `spawn` raised ENOENT, ChildProcess emitted an
// 'error' event nobody listened for, node threw, the probe exited non-zero, and
// the pipeline reported `browser_readiness: browser_probe_failed`. A missing
// browser was indistinguishable from an artifact that fails verification.
//
// The machine does have a Chromium — the one Playwright downloaded — so the
// gate was failing over a path string, not a capability. Each run still gets a
// fresh `--user-data-dir` below, so using that same binary cannot collide with
// a browser the developer is driving for other work at the same time.
const CHROME_CANDIDATES = [
  process.env.CHROME_BIN,
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
  "/snap/bin/chromium",
  "/usr/bin/microsoft-edge",
];

function resolveChrome() {
  const searched = [];
  for (const candidate of CHROME_CANDIDATES) {
    if (!candidate) continue;
    searched.push(candidate);
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
      return { path: candidate, searched };
    } catch {
      // keep looking
    }
  }
  // Playwright's bundled build, whose directory carries a version number.
  const cacheRoot = path.join(os.homedir(), ".cache", "ms-playwright");
  searched.push(`${cacheRoot}/chromium-*/chrome-linux*/chrome`);
  try {
    for (const entry of fs.readdirSync(cacheRoot)) {
      if (!entry.startsWith("chromium")) continue;
      for (const layout of ["chrome-linux64", "chrome-linux"]) {
        const candidate = path.join(cacheRoot, entry, layout, "chrome");
        try {
          fs.accessSync(candidate, fs.constants.X_OK);
          return { path: candidate, searched };
        } catch {
          // keep looking
        }
      }
    }
  } catch {
    // no playwright cache on this host
  }
  return { path: null, searched };
}

const chromeResolution = resolveChrome();
if (!chromeResolution.path) {
  // Named, not silent. "No browser is installed" is an operator problem and
  // must never read like "this artifact failed verification".
  process.stderr.write(
    `browser_probe_unavailable: no usable Chrome/Chromium found. Searched: ${chromeResolution.searched.join(
      ", ",
    )}. Set CHROME_BIN to an executable browser.\n`,
  );
  process.exit(1);
}
const chromePath = chromeResolution.path;
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-chrome-"));

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return await response.json();
}

const port = await freePort();
const chrome = spawn(chromePath, [
  "--headless=new",
  "--disable-gpu",
  "--no-first-run",
  "--no-default-browser-check",
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profilePath}`,
  "about:blank",
], { stdio: "ignore" });

// A ChildProcess 'error' with no listener is an UNHANDLED event: node throws out
// of the event loop, past the try/finally below, so the temp profile leaks and
// the caller sees a stack trace instead of a diagnosis. Capture it instead.
let chromeSpawnError = null;
let chromeExited = null;
chrome.on("error", (error) => {
  chromeSpawnError = error;
});
chrome.on("exit", (code, signal) => {
  chromeExited = { code, signal };
});

try {
  let version;
  // The old budget was 100 x 50ms = 5 seconds flat. That is enough for an idle
  // machine and not enough for a loaded one — and this host also runs the
  // developer's own browser automation, so a cold Chromium start competing for
  // CPU regularly overran it and the gate blamed the artifact. 20s of polling
  // still fits inside the caller's 30s subprocess timeout, and the loop now
  // stops the moment Chrome dies rather than spinning out the whole budget
  // against a process that is already gone.
  const startupDeadline = Date.now() + 20_000;
  while (Date.now() < startupDeadline) {
    if (chromeSpawnError) {
      throw new Error(
        `browser_probe_unavailable: could not start ${chromePath} (${chromeSpawnError.code || chromeSpawnError.message})`,
      );
    }
    if (chromeExited) {
      throw new Error(
        `browser_probe_unavailable: ${chromePath} exited before the debugging endpoint opened (code=${chromeExited.code}, signal=${chromeExited.signal})`,
      );
    }
    try {
      version = await fetchJson(`http://127.0.0.1:${port}/json/version`);
      break;
    } catch {
      await delay(50);
    }
  }
  if (!version) throw new Error("Chrome debugging endpoint did not start within 20s");

  const fileUrl = pathToFileURL(artifactPath).href;
  const target = await fetchJson(
    `http://127.0.0.1:${port}/json/new?${encodeURIComponent(fileUrl)}`,
    { method: "PUT" },
  );
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });

  let nextId = 1;
  const pending = new Map();
  let externalRequests = 0;
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
      return;
    }
    if (message.method === "Network.requestWillBeSent") {
      const url = message.params.request.url;
      if (!url.startsWith("file:") && !url.startsWith("data:") && !url.startsWith("blob:")) {
        externalRequests += 1;
      }
    }
  });

  function command(method, params = {}) {
    const id = nextId;
    nextId += 1;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }

  await command("Runtime.enable");
  await command("Network.enable");
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const response = await command("Runtime.evaluate", {
      expression: "document.documentElement.dataset.layshReady === 'true'",
      returnByValue: true,
    });
    ready = response.result.value === true;
    if (ready) break;
    await delay(50);
  }

  const interaction = await command("Runtime.evaluate", {
    expression: `(() => {
      const root = document.documentElement;
      const before = Number(root.dataset.frameCount || 0);
      const canvas = document.querySelector('#simulation');
      const canvasHash = (target) => {
        if (!target) return null;
        const data = target.getContext('2d').getImageData(0,0,target.width,target.height).data;
        const stride = Math.max(4,Math.floor(data.length / 4096 / 4) * 4);
        let hash = 2166136261;
        for (let index = 0; index < data.length; index += stride) {
          hash ^= data[index];
          hash = Math.imul(hash,16777619);
          hash ^= data[index + 1] || 0;
          hash = Math.imul(hash,16777619);
          hash ^= data[index + 2] || 0;
          hash = Math.imul(hash,16777619);
          hash ^= data[index + 3] || 0;
          hash = Math.imul(hash,16777619);
        }
        return hash >>> 0;
      };
      const canvasHashBefore = canvasHash(canvas);
      const choice = document.querySelector('#prediction-choices button');
      choice.click();
      const control = document.querySelector('#primary-control');
      const beforeControlValue = Number(control.value);
      const target = Math.abs(beforeControlValue - Number(control.min))
        <= Math.abs(beforeControlValue - Number(control.max))
        ? control.max
        : control.min;
      control.value = target;
      control.dispatchEvent(new Event('input', { bubbles: true }));
      return {
        controlChanged: !control.disabled && Number(control.value) !== beforeControlValue,
        frameChanged: Number(root.dataset.frameCount || 0) > before,
        canvasHashBefore,
        canvasHashAfter: canvasHash(canvas),
        runtimeError: Boolean(root.dataset.runtimeError),
      };
    })()`,
    returnByValue: true,
  });
  const causalSetup = await command("Runtime.evaluate", {
    expression: `(() => {
      const canvas = document.querySelector('#simulation');
      const control = document.querySelector('#primary-control');
      const representation = window.LayshSimulation?.spec?.representation
        || window.__LAYSH_LESSON__?.representation;
      return {
        actorResponseObserved: Boolean(canvas && canvas.__layshActorResponse),
        canvasWidth: canvas ? Number(canvas.width) : 0,
        canvasHeight: canvas ? Number(canvas.height) : 0,
        minimum: control ? Number(control.min) : 0,
        maximum: control ? Number(control.max) : 0,
        fixtureValues: control && window.__LAYSH_LESSON__
          ? window.__LAYSH_LESSON__.checks.flatMap((check) => {
              const inputs = check.kind === "numeric"
                ? check.inputs
                : [...check.left_inputs, ...check.right_inputs];
              return inputs
                .filter((input) =>
                  input.name === window.__LAYSH_LESSON__.primary_parameter.id)
                .map((input) => Number(input.value));
            })
          : [],
        representation: representation ? {
          scenePattern: representation.scene_pattern || null,
          actorArchetype: representation.actor_archetype || null,
        } : null,
      };
    })()`,
    returnByValue: true,
  });
  const setup = causalSetup.result.value;
  const causalRequired = causalMarkerPresent || setup.actorResponseObserved;
  let causalResponse;
  if (causalRequired) {
    const pauseForCausalSampling = await command("Runtime.evaluate", {
      expression: `(() => {
        const toggle = document.querySelector('#play-pause');
        if (toggle && document.documentElement.dataset.playbackState === 'running') toggle.click();
        return document.documentElement.dataset.playbackState;
      })()`,
      returnByValue: true,
    });
    if (pauseForCausalSampling.result.value === "running") {
      throw new Error("causal sampling could not pause playback");
    }
    const span = setup.maximum - setup.minimum;
    const sampleValues = [
      setup.minimum,
      setup.minimum + span * 0.25,
      setup.minimum + span * 0.5,
      setup.minimum + span * 0.75,
      setup.maximum,
      ...setup.fixtureValues,
    ];
    if (setup.minimum < 0 && setup.maximum > 0) sampleValues.push(0);
    const distinctValues = [...new Set(sampleValues.map((value) => Number(value.toPrecision(12))))]
      .sort((left, right) => left - right);
    const samples = [];
    for (const value of distinctValues) {
      const sampled = await command("Runtime.evaluate", {
        expression: `(() => {
          const canvas = document.querySelector('#simulation');
          const control = document.querySelector('#primary-control');
          control.value = ${JSON.stringify(value)};
          control.dispatchEvent(new Event('input', { bubbles: true }));
          const response = canvas && canvas.__layshActorResponse;
          return response ? JSON.parse(JSON.stringify(response)) : null;
        })()`,
        returnByValue: true,
      });
      samples.push(sampled.result.value);
      await delay(20);
    }

    const temporalSamples = [];
    if (samples.some((sample) => sample && sample.temporalMode === "cyclic")) {
      await command("Runtime.evaluate", {
        expression: `(() => {
          const toggle = document.querySelector('#play-pause');
          if (toggle && document.documentElement.dataset.playbackState !== 'running') toggle.click();
        })()`,
        returnByValue: true,
      });
      for (let index = 0; index < 4; index += 1) {
        await delay(90);
        const sampled = await command("Runtime.evaluate", {
          expression: `(() => {
            const canvas = document.querySelector('#simulation');
            const response = canvas && canvas.__layshActorResponse;
            return response ? JSON.parse(JSON.stringify(response)) : null;
          })()`,
          returnByValue: true,
        });
        temporalSamples.push(sampled.result.value);
      }
    }
    causalResponse = {
      required: true,
      canvasWidth: setup.canvasWidth,
      canvasHeight: setup.canvasHeight,
      samples,
      temporalSamples,
    };
    causalResponse.report = evaluateCausalResponse(causalResponse);
  }
  const representationProbe = await command("Runtime.evaluate", {
    expression: `(() => {
      const simulation = window.LayshSimulation;
      const lesson = window.__LAYSH_LESSON__;
      const representation = simulation?.spec?.representation || lesson?.representation;
      if (!representation || typeof representation !== 'object') return null;
      const canvas = document.querySelector('#simulation');
      const control = document.querySelector('#primary-control');
      if (!canvas || !control || !simulation) return {
        required: true,
        graph: { required: representation.scene_pattern === 'world_plus_graph', samples: [], markers: [] },
        archetype: {
          required: Boolean(representation.actor_archetype),
          declared: representation.actor_archetype || null,
          actorId: null,
          scientificActorCount: 0,
          visibleActorCount: 0,
          matchingPrimitiveCount: 0,
        },
      };
      const toggle = document.querySelector('#play-pause');
      if (toggle && document.documentElement.dataset.playbackState === 'running') toggle.click();
      const primaryOutput = lesson.module_spec.outputs[0];
      const mainContext = canvas.getContext('2d');
      const primitives = [];
      const originalArc = mainContext.arc;
      const originalEllipse = mainContext.ellipse;
      mainContext.arc = function(cx, cy, radius, start, end, counterclockwise) {
        primitives.push({
          type: 'circle', cx: Number(cx), cy: Number(cy), radius: Number(radius),
          alpha: Number(this.globalAlpha),
        });
        return originalArc.call(this, cx, cy, radius, start, end, counterclockwise);
      };
      mainContext.ellipse = function(cx, cy, radiusX, radiusY, rotation, start, end, counterclockwise) {
        primitives.push({
          type: 'ellipse', cx: Number(cx), cy: Number(cy),
          radiusX: Number(radiusX), radiusY: Number(radiusY),
          rotation: Number(rotation), alpha: Number(this.globalAlpha),
        });
        return originalEllipse.call(
          this, cx, cy, radiusX, radiusY, rotation, start, end, counterclockwise,
        );
      };
      const originalValue = Number(control.value);
      control.value = String(lesson.primary_parameter.default);
      control.dispatchEvent(new Event('input', { bubbles: true }));
      mainContext.arc = originalArc;
      mainContext.ellipse = originalEllipse;

      const response = canvas.__layshActorResponse;
      const sceneStates = Array.isArray(canvas.__layshSceneGeometry)
        ? canvas.__layshSceneGeometry : [];
      const scene = sceneStates[sceneStates.length - 1];
      const scientificObjects = Array.isArray(scene?.objects)
        ? scene.objects.filter((object) => object?.scientific === true) : [];
      const viewportWidth = Number(scene?.viewport?.width || canvas.width);
      const viewportHeight = Number(scene?.viewport?.height || canvas.height);
      const visible = (object) => {
        const geometry = object?.geometry;
        if (!geometry || typeof geometry !== 'object') return false;
        if (['circle', 'wave', 'particle_flow'].includes(geometry.type)) {
          const { cx, cy, radius } = geometry;
          return [cx, cy, radius].every(Number.isFinite) && radius > 0
            && cx + radius >= 0 && cy + radius >= 0
            && cx - radius <= viewportWidth && cy - radius <= viewportHeight;
        }
        if (geometry.type === 'ellipse') {
          const radiusX = Number(geometry.radiusX ?? geometry.radius_x);
          const radiusY = Number(geometry.radiusY ?? geometry.radius_y);
          return [geometry.cx, geometry.cy, radiusX, radiusY].every(Number.isFinite)
            && radiusX > 0 && radiusY > 0
            && geometry.cx + radiusX >= 0 && geometry.cy + radiusY >= 0
            && geometry.cx - radiusX <= viewportWidth
            && geometry.cy - radiusY <= viewportHeight;
        }
        if (geometry.type === 'rect') {
          return [geometry.x, geometry.y, geometry.width, geometry.height].every(Number.isFinite)
            && geometry.width > 0 && geometry.height > 0
            && geometry.x + geometry.width >= 0 && geometry.y + geometry.height >= 0
            && geometry.x <= viewportWidth && geometry.y <= viewportHeight;
        }
        return Array.isArray(geometry.points) && geometry.points.length >= 2;
      };
      const visibleObjects = scientificObjects.filter(visible);
      const renderedActorReport = canvas.__layshRenderedActors;
      const renderedActors = (
        renderedActorReport?.schemaVersion === '1.0'
        && Array.isArray(renderedActorReport.actors)
      ) ? renderedActorReport.actors.filter((actor) =>
        actor && typeof actor.id === 'string' && typeof actor.kind === 'string'
        && Number.isFinite(Number(actor.opacity))) : [];
      const visibleObjectIds = new Set(visibleObjects.map((object) => object.id));
      const visibleRenderedActors = renderedActors.filter((actor) =>
        Number(actor.opacity) > 0.02 && visibleObjectIds.has(actor.id));
      const actorBounds = response?.fittedBounds;
      const actorCenter = actorBounds ? {
        x: (Number(actorBounds.left) + Number(actorBounds.right)) / 2,
        y: (Number(actorBounds.top) + Number(actorBounds.bottom)) / 2,
      } : null;
      const near = (primitive, point, tolerance = 2) => point
        && Math.abs(primitive.cx - point.x) <= tolerance
        && Math.abs(primitive.cy - point.y) <= tolerance;
      const visiblePrimitives = primitives.filter((primitive) =>
        Number.isFinite(primitive.alpha) && primitive.alpha > 0.02);
      const primitiveForObject = (object) => {
        const geometry = object.geometry;
        const point = Number.isFinite(geometry.cx) && Number.isFinite(geometry.cy)
          ? { x: geometry.cx, y: geometry.cy } : null;
        return visiblePrimitives.some((primitive) => near(primitive, point));
      };
      let matchingPrimitiveCount = 0;
      if (renderedActors.length > 0) {
        const matchingKinds = {
          body: new Set(['body_group', 'circle', 'ellipse', 'trajectory', 'vector_arrow']),
          elongated_body: new Set(['body_group', 'ellipse']),
          ray_bundle: new Set(['ray']),
          wave_medium: new Set(['wave']),
          particle_flow: new Set(['particle_flow']),
        }[representation.actor_archetype];
        if (
          representation.actor_archetype === 'orbital_pair'
          || representation.actor_archetype === 'linked_bodies'
        ) {
          matchingPrimitiveCount = visibleRenderedActors.length;
        } else if (representation.actor_archetype === 'surface_and_body') {
          const visibleKinds = new Set(visibleRenderedActors.map((actor) => actor.kind));
          matchingPrimitiveCount = visibleKinds.has('circle') && visibleKinds.has('ellipse')
            ? 2 : 0;
        } else if (matchingKinds) {
          matchingPrimitiveCount = visibleRenderedActors.filter(
            (actor) => matchingKinds.has(actor.kind),
          ).length;
        }
      } else if (representation.actor_archetype === 'body') {
        const actorObject = visibleObjects.find((object) => object.id === response?.actorId);
        matchingPrimitiveCount = actorObject
          && visiblePrimitives.some((primitive) => near(primitive, actorCenter)) ? 1 : 0;
      } else if (representation.actor_archetype === 'elongated_body') {
        matchingPrimitiveCount = visiblePrimitives.filter((primitive) =>
          primitive.type === 'ellipse'
          && near(primitive, actorCenter)
          && Math.max(primitive.radiusX, primitive.radiusY)
            / Math.max(1e-9, Math.min(primitive.radiusX, primitive.radiusY)) >= 1.1).length;
      } else if (
        representation.actor_archetype === 'orbital_pair'
        || representation.actor_archetype === 'linked_bodies'
      ) {
        matchingPrimitiveCount = visibleObjects.filter(primitiveForObject).length;
      } else if (representation.actor_archetype === 'surface_and_body') {
        const roundCount = visiblePrimitives.filter((primitive) =>
          primitive.type === 'circle').length;
        const elongatedCount = visiblePrimitives.filter((primitive) =>
          primitive.type === 'ellipse'
          && Math.max(primitive.radiusX, primitive.radiusY)
            / Math.max(1e-9, Math.min(primitive.radiusX, primitive.radiusY)) >= 1.1).length;
        matchingPrimitiveCount = roundCount > 0 && elongatedCount > 0 ? 2 : 0;
      } else {
        const expectedGeometry = {
          ray_bundle: 'ray',
          wave_medium: 'wave',
          particle_flow: 'particle_flow',
        }[representation.actor_archetype];
        matchingPrimitiveCount = visibleObjects.filter(
          (object) => object.geometry?.type === expectedGeometry,
        ).length;
      }

      const graphCanvas = document.querySelector('#simulation-graph');
      const graphRequired = representation.scene_pattern === 'world_plus_graph';
      const graphSamples = [];
      const markerSamples = [];
      if (graphRequired && graphCanvas) {
        const graphContext = graphCanvas.getContext('2d');
        const paths = [];
        let currentPath = [];
        const originalBeginPath = graphContext.beginPath;
        const originalMoveTo = graphContext.moveTo;
        const originalLineTo = graphContext.lineTo;
        const originalStroke = graphContext.stroke;
        graphContext.beginPath = function() {
          currentPath = [];
          return originalBeginPath.call(this);
        };
        graphContext.moveTo = function(x, y) {
          currentPath.push({ x: Number(x), y: Number(y) });
          return originalMoveTo.call(this, x, y);
        };
        graphContext.lineTo = function(x, y) {
          currentPath.push({ x: Number(x), y: Number(y) });
          return originalLineTo.call(this, x, y);
        };
        graphContext.stroke = function(...args) {
          if (currentPath.length > 0) paths.push(currentPath.map((point) => ({ ...point })));
          return originalStroke.apply(this, args);
        };
        control.value = String(lesson.primary_parameter.default);
        control.dispatchEvent(new Event('input', { bubbles: true }));
        graphContext.beginPath = originalBeginPath;
        graphContext.moveTo = originalMoveTo;
        graphContext.lineTo = originalLineTo;
        graphContext.stroke = originalStroke;
        const curve = paths.sort((left, right) => right.length - left.length)[0] || [];
        const minimum = Number(lesson.primary_parameter.min);
        const maximum = Number(lesson.primary_parameter.max);
        const expectedCurve = Array.from({ length: 40 }, (_, index) => {
          const input = minimum + ((maximum - minimum) * index) / 39;
          return {
            input,
            output: Number(simulation.test({ [lesson.primary_parameter.id]: input })[primaryOutput]),
          };
        });
        let outputMinimum = Math.min(...expectedCurve.map((sample) => sample.output));
        let outputMaximum = Math.max(...expectedCurve.map((sample) => sample.output));
        if (outputMinimum === outputMaximum) {
          const padding = Math.max(1, Math.abs(outputMinimum) * 0.1);
          outputMinimum -= padding;
          outputMaximum += padding;
        }
        const pad = { top: 30, right: 14, bottom: 46, left: 56 };
        const plotWidth = graphCanvas.width - pad.left - pad.right;
        const plotHeight = graphCanvas.height - pad.top - pad.bottom;
        for (const index of [0, 10, 20, 29, 39]) {
          const point = curve[index];
          const expected = expectedCurve[index];
          const expectedX = pad.left
            + ((expected.input - minimum) / (maximum - minimum || 1)) * plotWidth;
          const plottedOutput = point && Math.abs(point.x - expectedX) <= 1.5
            ? outputMaximum
              - ((point.y - pad.top) / plotHeight) * (outputMaximum - outputMinimum)
            : null;
          graphSamples.push({
            input: expected.input,
            expectedOutput: expected.output,
            plottedOutput,
            tolerance: Math.max(
              1e-6,
              Math.abs(outputMaximum - outputMinimum) / Math.max(1, plotHeight) * 1.5,
            ),
          });
        }
        for (const controlValue of [minimum, Number(lesson.primary_parameter.default), maximum]) {
          control.value = String(controlValue);
          control.dispatchEvent(new Event('input', { bubbles: true }));
          markerSamples.push({
            controlValue,
            expectedX: pad.left + ((controlValue - minimum) / (maximum - minimum || 1)) * plotWidth,
            observedX: Number(graphCanvas.dataset.markerX),
            tolerance: 1,
          });
        }
      }
      control.value = String(originalValue);
      control.dispatchEvent(new Event('input', { bubbles: true }));
      return {
        required: true,
        graph: { required: graphRequired, samples: graphSamples, markers: markerSamples },
        archetype: {
          required: Boolean(representation.actor_archetype),
          declared: representation.actor_archetype || null,
          actorId: response?.actorId || null,
          scientificActorCount: scientificObjects.length,
          visibleActorCount: visibleObjects.length,
          matchingPrimitiveCount,
        },
      };
    })()`,
    returnByValue: true,
  });
  const representationConsistency = representationProbe.result?.value
    || (setup.representation ? {
      required: true,
      graph: {
        required: setup.representation.scenePattern === "world_plus_graph",
        samples: [],
        markers: [],
      },
      archetype: {
        required: Boolean(setup.representation.actorArchetype),
        declared: setup.representation.actorArchetype,
        actorId: null,
        scientificActorCount: 0,
        visibleActorCount: 0,
        matchingPrimitiveCount: 0,
      },
    } : null);
  socket.close();
  const browserEvidence = {
    ready,
    controlChanged: interaction.result.value.controlChanged,
    frameChanged: interaction.result.value.frameChanged,
    canvasHashBefore: interaction.result.value.canvasHashBefore,
    canvasHashAfter: interaction.result.value.canvasHashAfter,
    runtimeError: interaction.result.value.runtimeError,
    externalRequests,
  };
  if (causalResponse) browserEvidence.causalResponse = causalResponse;
  if (representationConsistency) {
    browserEvidence.representationConsistency = representationConsistency;
  }
  process.stdout.write(JSON.stringify(browserEvidence));
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
} finally {
  chrome.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => chrome.once("exit", resolve)),
    delay(2000),
  ]);
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 2 });
      break;
    } catch (error) {
      if (attempt === 4) throw error;
      await delay(100);
    }
  }
}
