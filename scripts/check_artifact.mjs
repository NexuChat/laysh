import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactPath = path.resolve(process.argv[2]);
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-chrome-"));
const actionTrackingSource = fs.readFileSync(
  new URL("./action_tracking_browser.js", import.meta.url),
  "utf8",
);
const pausedActionTrackingSource = fs.readFileSync(
  new URL("./paused_action_tracking_browser.js", import.meta.url),
  "utf8",
);

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

try {
  let version;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      version = await fetchJson(`http://127.0.0.1:${port}/json/version`);
      break;
    } catch {
      await delay(50);
    }
  }
  if (!version) throw new Error("Chrome debugging endpoint did not start");

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
  await command("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-motion", value: "no-preference" }],
  });
  await command("Page.reload", { ignoreCache: true });
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

  const firstCapture = await command("Runtime.evaluate", {
    expression: `(() => {
      const canvas = document.querySelector('#simulation');
      const context = canvas && canvas.getContext('2d');
      const control = document.querySelector('#primary-control');
      if (!canvas || !context || !control) return null;
      const subject = {
        x: Math.floor(canvas.width * 0.2),
        y: Math.floor(canvas.height * 0.2),
        width: Math.max(1, Math.floor(canvas.width * 0.6)),
        height: Math.max(1, Math.floor(canvas.height * 0.6)),
      };
      window.__layshMotionFirst = {
        whole: context.getImageData(0, 0, canvas.width, canvas.height).data,
        subject: context.getImageData(subject.x, subject.y, subject.width, subject.height).data,
        subjectBounds: subject,
      };
      return {
        controlValue: Number(control.value),
        stateValue: Number(document.documentElement.dataset.parameterValue),
        controlEnabled: !control.disabled,
      };
    })()`,
    returnByValue: true,
  });
  await delay(1100);
  const idleMotion = await command("Runtime.evaluate", {
    expression: `(() => {
      const canvas = document.querySelector('#simulation');
      const context = canvas && canvas.getContext('2d');
      const first = window.__layshMotionFirst;
      delete window.__layshMotionFirst;
      if (!canvas || !context || !first) {
        return { subjectChangedPixelRatio: 0, wholeCanvasChangedPixelRatio: 0, captureIntervalMs: 1100 };
      }
      const changedPixelRatio = (before, after) => {
        let changed = 0;
        for (let pixel = 0; pixel < before.length; pixel += 4) {
          if (before[pixel] !== after[pixel] || before[pixel + 1] !== after[pixel + 1] || before[pixel + 2] !== after[pixel + 2]) changed += 1;
        }
        return changed / (before.length / 4);
      };
      const bounds = first.subjectBounds;
      const control = document.querySelector('#primary-control');
      const output = document.querySelector('#primary-output');
      const secondWhole = context.getImageData(0, 0, canvas.width, canvas.height).data;
      const secondSubject = context.getImageData(bounds.x, bounds.y, bounds.width, bounds.height).data;
      return {
        subjectChangedPixelRatio: changedPixelRatio(first.subject, secondSubject),
        wholeCanvasChangedPixelRatio: changedPixelRatio(first.whole, secondWhole),
        captureIntervalMs: 1100,
        controlValue: Number(control.value),
        stateValue: Number(document.documentElement.dataset.parameterValue),
        sliderTrackedAnimation: Math.abs(Number(control.value) - Number.parseFloat(output.value)) <= Number(control.step),
        controlEnabled: !control.disabled,
      };
    })()`,
    returnByValue: true,
  });

  const pauseStart = await command("Runtime.evaluate", {
    expression: `(() => {
      const control = document.querySelector('#primary-control');
      document.querySelector('#play-pause').click();
      const canvas = document.querySelector('#simulation');
      const context = canvas.getContext('2d');
      const subject = {
        x: Math.floor(canvas.width * 0.2),
        y: Math.floor(canvas.height * 0.2),
        width: Math.max(1, Math.floor(canvas.width * 0.6)),
        height: Math.max(1, Math.floor(canvas.height * 0.6)),
      };
      window.__layshPausedMotionFirst = {
        whole: context.getImageData(0, 0, canvas.width, canvas.height).data,
        subject: context.getImageData(subject.x, subject.y, subject.width, subject.height).data,
        subjectBounds: subject,
      };
      return {
        value: Number(control.value),
        stateValue: Number(document.documentElement.dataset.parameterValue),
        enabled: !control.disabled,
      };
    })()`,
    returnByValue: true,
  });
  await delay(1100);
  const pauseEnd = await command("Runtime.evaluate", {
    expression: `(() => {
      const control = document.querySelector('#primary-control');
      const canvas = document.querySelector('#simulation');
      const context = canvas.getContext('2d');
      const first = window.__layshPausedMotionFirst;
      delete window.__layshPausedMotionFirst;
      const changedPixelRatio = (before, after) => {
        let changed = 0;
        for (let pixel = 0; pixel < before.length; pixel += 4) {
          if (before[pixel] !== after[pixel]
            || before[pixel + 1] !== after[pixel + 1]
            || before[pixel + 2] !== after[pixel + 2]) changed += 1;
        }
        return changed / (before.length / 4);
      };
      const bounds = first.subjectBounds;
      return {
        value: Number(control.value),
        stateValue: Number(document.documentElement.dataset.parameterValue),
        enabled: !control.disabled,
        subjectChangedPixelRatio: changedPixelRatio(
          first.subject,
          context.getImageData(bounds.x, bounds.y, bounds.width, bounds.height).data,
        ),
        wholeCanvasChangedPixelRatio: changedPixelRatio(
          first.whole,
          context.getImageData(0, 0, canvas.width, canvas.height).data,
        ),
        captureIntervalMs: 1100,
      };
    })()`,
    returnByValue: true,
  });

  const actorTracking = await command("Runtime.evaluate", {
    expression: actionTrackingSource,
    awaitPromise: true,
    returnByValue: true,
  });

  const pausedActorTracking = await command("Runtime.evaluate", {
    expression: pausedActionTrackingSource,
    awaitPromise: true,
    returnByValue: true,
  });

  const interactionStart = await command("Runtime.evaluate", {
    expression: `(() => {
      const root = document.documentElement;
      const control = document.querySelector('#primary-control');
      const beforeFrame = Number(root.dataset.frameCount || 0);
      document.querySelector('#play-pause').click();
      control.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 1 }));
      const target = (Number(control.min) + Number(control.max)) / 2;
      control.value = String(target);
      control.dispatchEvent(new Event('input', { bubbles: true }));
      return { target: Number(control.value), beforeFrame, enabled: !control.disabled };
    })()`,
    returnByValue: true,
  });
  await delay(350);
  const interactionHeld = await command("Runtime.evaluate", {
    expression: `(() => {
      const control = document.querySelector('#primary-control');
      const held = Number(control.value);
      control.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1 }));
      return { held, enabled: !control.disabled };
    })()`,
    returnByValue: true,
  });
  await delay(350);
  const interactionEnd = await command("Runtime.evaluate", {
    expression: `(() => {
      const root = document.documentElement;
      const control = document.querySelector('#primary-control');
      return {
        value: Number(control.value),
        stateValue: Number(root.dataset.parameterValue),
        frame: Number(root.dataset.frameCount || 0),
        enabled: !control.disabled,
      };
    })()`,
    returnByValue: true,
  });

  await command("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-motion", value: "reduce" }],
  });
  await command("Page.reload", { ignoreCache: true });
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const response = await command("Runtime.evaluate", {
      expression: "document.documentElement.dataset.layshReady === 'true'",
      returnByValue: true,
    });
    if (response.result.value === true) break;
    await delay(50);
  }
  const reducedStart = await command("Runtime.evaluate", {
    expression: `(() => {
      const control = document.querySelector('#primary-control');
      return { value: Number(document.documentElement.dataset.parameterValue), state: document.documentElement.dataset.motionState, enabled: !control.disabled };
    })()`,
    returnByValue: true,
  });
  await delay(400);
  const reducedHeld = await command("Runtime.evaluate", {
    expression: `(() => {
      const control = document.querySelector('#primary-control');
      document.querySelector('#play-pause').click();
      return { value: Number(document.documentElement.dataset.parameterValue), state: document.documentElement.dataset.motionState, enabled: !control.disabled };
    })()`,
    returnByValue: true,
  });
  await delay(400);
  const reducedPlayed = await command("Runtime.evaluate", {
    expression: `(() => {
      const control = document.querySelector('#primary-control');
      document.querySelector('#play-pause').click();
      return { value: Number(document.documentElement.dataset.parameterValue), state: document.documentElement.dataset.motionState, enabled: !control.disabled };
    })()`,
    returnByValue: true,
  });

  await command("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-motion", value: "no-preference" }],
  });
  await command("Page.reload", { ignoreCache: true });
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const response = await command("Runtime.evaluate", {
      expression: "document.documentElement.dataset.layshReady === 'true'",
      returnByValue: true,
    });
    if (response.result.value === true) break;
    await delay(50);
  }
  await command("Runtime.evaluate", {
    expression: "document.querySelector('#play-pause').click()",
  });

  const renderOutputSweep = await command("Runtime.evaluate", {
    expression: `(async () => {
      const canvas = document.querySelector('#simulation');
      const context = canvas && canvas.getContext('2d');
      const control = document.querySelector('#primary-control');
      const lesson = window.__LAYSH_LESSON__;
      const outputName = lesson.module_spec.outputs[0];
      const parameter = lesson.primary_parameter;
      if (!canvas || !context || !control || !outputName) return { passed: false, samples: [], failure: { code: 'render_sweep_unavailable' } };
      const bounds = {
        x: Math.floor(canvas.width * 0.2),
        y: Math.floor(canvas.height * 0.2),
        width: Math.max(1, Math.floor(canvas.width * 0.6)),
        height: Math.max(1, Math.floor(canvas.height * 0.6)),
      };
      // Actor position is verified independently by the action-tracking gate. Keeping centroid
      // metrics here lets a correctly moving actor conceal a wrong physics-critical fill/shading
      // output (for example, a Moon that orbits correctly but renders the wrong lit fraction).
      const metricKeys = ['meanLuminance','bright64','bright128','bright192','dark32','edgeDensity'];
      const measure = () => {
        const pixels = context.getImageData(bounds.x, bounds.y, bounds.width, bounds.height).data;
        const luminance = new Float64Array(bounds.width * bounds.height);
        let sum = 0, weightedX = 0, weightedY = 0, bright64 = 0, bright128 = 0, bright192 = 0, dark32 = 0, edges = 0;
        for (let index = 0, pixel = 0; index < pixels.length; index += 4, pixel += 1) {
          const value = pixels[index] * 0.2126 + pixels[index + 1] * 0.7152 + pixels[index + 2] * 0.0722;
          luminance[pixel] = value;
          sum += value;
          const x = pixel % bounds.width;
          const y = Math.floor(pixel / bounds.width);
          weightedX += value * x;
          weightedY += value * y;
          if (value >= 64) bright64 += 1;
          if (value >= 128) bright128 += 1;
          if (value >= 192) bright192 += 1;
          if (value < 32) dark32 += 1;
          if (x > 0 && Math.abs(value - luminance[pixel - 1]) >= 24) edges += 1;
          if (y > 0 && Math.abs(value - luminance[pixel - bounds.width]) >= 24) edges += 1;
        }
        const count = luminance.length;
        return {
          meanLuminance: sum / count,
          bright64: bright64 / count,
          bright128: bright128 / count,
          bright192: bright192 / count,
          dark32: dark32 / count,
          centroidX: sum ? weightedX / sum / Math.max(1, bounds.width - 1) : 0,
          centroidY: sum ? weightedY / sum / Math.max(1, bounds.height - 1) : 0,
          edgeDensity: edges / (count * 2),
        };
      };
      const samples = [];
      for (let index = 0; index <= 16; index += 1) {
        const value = Number(parameter.min) + (Number(parameter.max) - Number(parameter.min)) * index / 16;
        control.value = String(value);
        control.dispatchEvent(new Event('input', { bubbles: true }));
        await new Promise((resolve) => setTimeout(resolve, 120));
        const tested = window.LayshSimulation.test({ [parameter.id]: value });
        samples.push({ parameter: value, computedOutput: Number(tested[outputName]), metrics: measure() });
      }
      const rank = (values) => {
        const ordered = values.map((value, index) => ({ value, index })).sort((a, b) => a.value - b.value);
        const ranks = new Array(values.length);
        for (let start = 0; start < ordered.length;) {
          let end = start + 1;
          while (end < ordered.length && ordered[end].value === ordered[start].value) end += 1;
          const average = (start + end - 1) / 2;
          for (let cursor = start; cursor < end; cursor += 1) ranks[ordered[cursor].index] = average;
          start = end;
        }
        return ranks;
      };
      const correlation = (left, right) => {
        const leftRank = rank(left), rightRank = rank(right);
        const leftMean = leftRank.reduce((sum, value) => sum + value, 0) / leftRank.length;
        const rightMean = rightRank.reduce((sum, value) => sum + value, 0) / rightRank.length;
        let numerator = 0, leftSquare = 0, rightSquare = 0;
        for (let index = 0; index < leftRank.length; index += 1) {
          const a = leftRank[index] - leftMean, b = rightRank[index] - rightMean;
          numerator += a * b; leftSquare += a * a; rightSquare += b * b;
        }
        return leftSquare && rightSquare ? numerator / Math.sqrt(leftSquare * rightSquare) : 0;
      };
      const computed = samples.map((sample) => sample.computedOutput);
      let best = { key: metricKeys[0], correlation: 0, span: 0 };
      for (const key of metricKeys) {
        const values = samples.map((sample) => sample.metrics[key]);
        const span = Math.max(...values) - Math.min(...values);
        const candidate = Math.abs(correlation(computed, values));
        if (span > 0.001 && candidate > best.correlation) best = { key, correlation: candidate, span };
      }
      const outputSpan = Math.max(...computed) - Math.min(...computed);
      const compactSamples = samples.map((sample) => ({
        parameter: sample.parameter,
        computedOutput: sample.computedOutput,
        renderedMeasure: sample.metrics[best.key],
      }));
      let cliff = null;
      let cliffScore = -Infinity;
      for (let index = 1; index < compactSamples.length; index += 1) {
        const left = compactSamples[index - 1], right = compactSamples[index];
        const renderedDelta = best.span ? Math.abs(right.renderedMeasure - left.renderedMeasure) / best.span : 0;
        const outputDelta = outputSpan ? Math.abs(right.computedOutput - left.computedOutput) / outputSpan : 0;
        const score = renderedDelta - outputDelta;
        const absoluteRenderedDelta = Math.abs(right.renderedMeasure - left.renderedMeasure);
        // Binary luminance buckets can flip when a smoothly changing hue crosses a threshold.
        // Require a materially visible absolute jump as well as the normalized cliff score.
        const absoluteCliffFloor = best.key === 'meanLuminance' ? 8 : 0.02;
        if (renderedDelta > 0.42 && absoluteRenderedDelta > absoluteCliffFloor
          && outputDelta < 0.18 && score > cliffScore) {
          cliffScore = score;
          cliff = { code: 'rendered_output_discontinuity', metric: best.key, left, right };
        }
      }
      if (cliff) return { passed: false, metric: best.key, rankCorrelation: best.correlation, samples: compactSamples, failure: cliff };
      if (!(outputSpan > 0) || best.correlation < 0.65) {
        let worstIndex = 1, worstMismatch = -Infinity;
        for (let index = 1; index < compactSamples.length; index += 1) {
          const renderedDelta = best.span ? Math.abs(compactSamples[index].renderedMeasure - compactSamples[index - 1].renderedMeasure) / best.span : 0;
          const outputDelta = outputSpan ? Math.abs(compactSamples[index].computedOutput - compactSamples[index - 1].computedOutput) / outputSpan : 0;
          if (renderedDelta - outputDelta > worstMismatch) { worstMismatch = renderedDelta - outputDelta; worstIndex = index; }
        }
        return {
          passed: false,
          metric: best.key,
          rankCorrelation: best.correlation,
          samples: compactSamples,
          failure: {
            code: 'rendered_output_not_monotonic_consistent',
            metric: best.key,
            rankCorrelation: best.correlation,
            left: compactSamples[worstIndex - 1],
            right: compactSamples[worstIndex],
          },
        };
      }
      return { passed: true, metric: best.key, rankCorrelation: best.correlation, samples: compactSamples };
    })()`,
    awaitPromise: true,
    returnByValue: true,
  });

  const visionFrames = [];
  const visionFrameStates = [];
  const visionMinimum = Number((await command("Runtime.evaluate", {
    expression: "window.__LAYSH_LESSON__.primary_parameter.min",
    returnByValue: true,
  })).result.value);
  const visionMaximum = Number((await command("Runtime.evaluate", {
    expression: "window.__LAYSH_LESSON__.primary_parameter.max",
    returnByValue: true,
  })).result.value);
  const visionAction = (await command("Runtime.evaluate", {
    expression: "window.__LAYSH_LESSON__.action",
    returnByValue: true,
  })).result.value;
  let visionFractions = [0, 1 / 3, 2 / 3];
  if (visionAction === "oscillates") visionFractions = [0.15, 0.5, 0.85];
  if (visionAction === "rotates") visionFractions = [0, 1 / 6, 1 / 3];
  const visionValues = visionFractions.map(
    (fraction) => visionMinimum + (visionMaximum - visionMinimum) * fraction,
  );
  for (let visionIndex = 0; visionIndex < visionValues.length; visionIndex += 1) {
    const value = visionValues[visionIndex];
    await command("Runtime.evaluate", {
      expression: `(() => {
        const control = document.querySelector('#primary-control');
        control.value = ${JSON.stringify(value)};
        control.dispatchEvent(new Event('input', { bubbles: true }));
      })()`,
    });
    await delay(120);
    const frameState = await command("Runtime.evaluate", {
      expression: `(() => {
        const lesson = window.__LAYSH_LESSON__;
        const value = ${JSON.stringify(value)};
        const tested = window.LayshSimulation.test({ [lesson.primary_parameter.id]: value });
        const output = Number(tested[lesson.actor.tracking_output]);
        let time = 0;
        if (lesson.action === 'oscillates' && Number.isFinite(output)) {
          time = output * ${JSON.stringify(visionIndex)} / 2;
        } else if (lesson.action === 'propagates' && Number.isFinite(output)) {
          time = (lesson.actor.tracking_output.endsWith('_ms') ? output / 1000 : output)
            * ${JSON.stringify(visionIndex)} / 4;
        } else if (lesson.action === 'flows') {
          time = 0.3;
        }
        window.__LAYSH_VERIFICATION_TIME__ = time;
        for (let repeat = 0; repeat < 30; repeat += 1) {
          window.LayshSimulation.setParameter(lesson.primary_parameter.id, value, time);
        }
        return { parameter: value, modelOutputs: tested, timeSeconds: time };
      })()`,
      returnByValue: true,
    });
    visionFrameStates.push(frameState.result.value);
    const canvasBounds = await command("Runtime.evaluate", {
      expression: `(() => {
        const bounds = document.querySelector('#simulation').getBoundingClientRect();
        return {
          x: bounds.left + window.scrollX,
          y: bounds.top + window.scrollY,
          width: bounds.width,
          height: bounds.height,
          scale: 1,
        };
      })()`,
      returnByValue: true,
    });
    const screenshot = await command("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: true,
      clip: canvasBounds.result.value,
    });
    visionFrames.push(screenshot.data);
  }

  const pausedVisionIndex = Math.floor(visionValues.length / 2);
  const pausedVisionValue = visionValues[pausedVisionIndex];
  const previousVisionTime = Number(
    visionFrameStates[pausedVisionIndex].timeSeconds || 0,
  );
  const pausedVisionState = await command("Runtime.evaluate", {
    expression: `(() => {
      const lesson = window.__LAYSH_LESSON__;
      const control = document.querySelector('#primary-control');
      const value = ${JSON.stringify(pausedVisionValue)};
      const tested = window.LayshSimulation.test({ [lesson.primary_parameter.id]: value });
      const output = Number(tested[lesson.actor.tracking_output]);
      let delta = 1.1;
      if (lesson.action === 'oscillates' && Number.isFinite(output)) delta = output / 4;
      else if (lesson.action === 'propagates' && Number.isFinite(output)) {
        delta = (lesson.actor.tracking_output.endsWith('_ms') ? output / 1000 : output) / 4;
      } else if (lesson.action === 'flows') delta = 0.12;
      else if (lesson.action === 'floats_sinks') delta = 0.6;
      const time = ${JSON.stringify(previousVisionTime)} + delta;
      control.value = String(value);
      control.dispatchEvent(new Event('input', { bubbles: true }));
      window.__LAYSH_VERIFICATION_TIME__ = time;
      for (let repeat = 0; repeat < 30; repeat += 1) {
        window.LayshSimulation.setParameter(lesson.primary_parameter.id, value, time);
      }
      return {
        parameter: value,
        modelOutputs: tested,
        timeSeconds: time,
        sweepState: document.documentElement.dataset.sweepState,
        criterion: 'declared_action_continues_with_auto_sweep_paused',
      };
    })()`,
    returnByValue: true,
  });
  visionFrameStates.push(pausedVisionState.result.value);
  const pausedCanvasBounds = await command("Runtime.evaluate", {
    expression: `(() => {
      const bounds = document.querySelector('#simulation').getBoundingClientRect();
      return {
        x: bounds.left + window.scrollX,
        y: bounds.top + window.scrollY,
        width: bounds.width,
        height: bounds.height,
        scale: 1,
      };
    })()`,
    returnByValue: true,
  });
  const pausedScreenshot = await command("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: true,
    clip: pausedCanvasBounds.result.value,
  });
  visionFrames.push(pausedScreenshot.data);
  await command("Runtime.evaluate", {
    expression: "delete window.__LAYSH_VERIFICATION_TIME__",
  });

  await command("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
    screenWidth: 390,
    screenHeight: 844,
  });
  await delay(180);
  const mobileValue = visionValues[Math.floor(visionValues.length / 2)];
  const mobileOverlayLayout = (await command("Runtime.evaluate", {
    expression: `(() => {
      const canvas = document.querySelector('#simulation');
      const context = canvas.getContext('2d');
      const control = document.querySelector('#primary-control');
      const lesson = window.__LAYSH_LESSON__;
      if (!context.__layshOriginalFillText) {
        context.__layshOriginalFillText = context.fillText;
        context.fillText = function (...args) {
          const x = Number(args[1]);
          const y = Number(args[2]);
          const metrics = context.measureText(String(args[0]));
          const fontSize = Number.parseFloat(context.font) || 12;
          let left = x;
          if (context.textAlign === 'center') left -= metrics.width / 2;
          if (context.textAlign === 'right' || context.textAlign === 'end') left -= metrics.width;
          let top = y - (metrics.actualBoundingBoxAscent || fontSize * 0.8);
          if (context.textBaseline === 'top' || context.textBaseline === 'hanging') top = y;
          if (context.textBaseline === 'middle') top = y - fontSize / 2;
          window.__LAYSH_DRAWN_LABEL_RECTS__.push({
            x: left,
            y: top,
            width: metrics.width,
            height: (metrics.actualBoundingBoxAscent || fontSize * 0.8)
              + (metrics.actualBoundingBoxDescent || fontSize * 0.2),
          });
          return context.__layshOriginalFillText.apply(context, args);
        };
      }
      window.__LAYSH_DRAWN_LABEL_RECTS__ = [];
      control.value = ${JSON.stringify(mobileValue)};
      control.dispatchEvent(new Event('input', { bubbles: true }));
      const tested = window.LayshSimulation.test({ [lesson.primary_parameter.id]: Number(control.value) });
      const overlays = (window.__LAYSH_OVERLAY_RECTS__ || []).map((rect) => ({
        x: Number(rect.x), y: Number(rect.y), width: Number(rect.width),
        height: Number(rect.height), role: rect.role,
      }));
      const drawnLabels = window.__LAYSH_DRAWN_LABEL_RECTS__.map((rect) => ({
        x: Number(rect.x), y: Number(rect.y), width: Number(rect.width), height: Number(rect.height),
      }));
      const subject = {
        x: canvas.width * 0.2,
        y: canvas.height * 0.2,
        width: canvas.width * 0.6,
        height: canvas.height * 0.6,
      };
      const intersectionPixels = (left, right) => Math.max(0,
        Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x),
      ) * Math.max(0,
        Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y),
      );
      // Canvas text bounds are inferred from rasterized glyphs while modules register logical chip
      // bounds. Twelve pixels covers font metrics/alignment variance; actual label count and subject
      // overlap are checked separately, so this cannot excuse an obscuring or duplicate label.
      const contains = (outer, inner) => (
        inner.x >= outer.x - 12 && inner.y >= outer.y - 12
        && inner.x + inner.width <= outer.x + outer.width + 12
        && inner.y + inner.height <= outer.y + outer.height + 12
      );
      const subjectOverlapPixels = overlays.reduce(
        (sum, rect) => sum + intersectionPixels(rect, subject), 0,
      );
      const labelSubjectOverlapPixels = drawnLabels.reduce(
        (sum, rect) => sum + intersectionPixels(rect, subject), 0,
      );
      const unregisteredLabelCount = drawnLabels.filter(
        (label) => !overlays.some((overlay) => contains(overlay, label)),
      ).length;
      const overlayHeightRatio = overlays.reduce((sum, rect) => sum + rect.height, 0)
        / Math.max(1, canvas.height);
      const edgeLimit = Math.max(10, canvas.height * 0.07);
      const unanchoredOverlayCount = overlays.filter((rect) => Math.min(
        rect.x,
        rect.y,
        canvas.width - rect.x - rect.width,
        canvas.height - rect.y - rect.height,
      ) > edgeLimit).length;
      const expected = {
        canvas_width_max: 420,
        overlay_count_max: 1,
        overlay_height_ratio_max: 0.22,
        subject_overlap_pixels: 0,
        label_subject_overlap_pixels: 0,
        drawn_label_count_max: 1,
        unregistered_label_count: 0,
        unanchored_overlay_count: 0,
      };
      const measured = {
        overlay_count: overlays.length,
        drawn_label_count: drawnLabels.length,
        overlay_height_ratio: Number(overlayHeightRatio.toFixed(4)),
        subject_overlap_pixels: Math.round(subjectOverlapPixels),
        label_subject_overlap_pixels: Math.round(labelSubjectOverlapPixels),
        unregistered_label_count: unregisteredLabelCount,
        unanchored_overlay_count: unanchoredOverlayCount,
      };
      let code = null;
      if (canvas.width > 420) code = 'mobile_canvas_width_exceeded';
      else if (drawnLabels.length > 1) code = 'mobile_overlay_count_exceeded';
      else if (labelSubjectOverlapPixels > 0) code = 'mobile_overlay_subject_intrusion';
      // Registration remains diagnostic, but the rasterized label rectangle is stronger evidence.
      // A single edge label that passes actual count/overlap checks is safe even without the hint.
      else if (subjectOverlapPixels > 0) code = 'mobile_overlay_subject_intrusion';
      else if (overlays.length > 1) code = 'mobile_overlay_count_exceeded';
      else if (overlayHeightRatio > 0.22) code = 'mobile_overlay_band_exceeded';
      else if (unanchoredOverlayCount) code = 'mobile_overlay_not_edge_anchored';
      return {
        passed: code === null,
        canvas: { width: canvas.width, height: canvas.height },
        subjectRegion: subject,
        overlayRects: overlays,
        drawnLabelRects: drawnLabels,
        overlayCount: overlays.length,
        overlayHeightRatio: measured.overlay_height_ratio,
        subjectOverlapPixels: measured.subject_overlap_pixels,
        failure: code ? { code, expected, measured } : null,
        frameState: {
          viewport: 'mobile-390x844',
          criterion: 'labels_must_not_obscure_subject',
          parameter: Number(control.value),
          modelOutputs: tested,
          timeSeconds: 0,
        },
      };
    })()`,
    returnByValue: true,
  })).result.value;
  await delay(100);
  const mobileCanvasBounds = await command("Runtime.evaluate", {
    expression: `(() => {
      const bounds = document.querySelector('#simulation').getBoundingClientRect();
      return {
        x: bounds.left + window.scrollX,
        y: bounds.top + window.scrollY,
        width: bounds.width,
        height: bounds.height,
        scale: 1,
      };
    })()`,
    returnByValue: true,
  });
  const mobileScreenshot = await command("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: true,
    clip: mobileCanvasBounds.result.value,
  });
  visionFrameStates.push(mobileOverlayLayout.frameState);
  delete mobileOverlayLayout.frameState;
  visionFrames.push(mobileScreenshot.data);

  const initialValue = firstCapture.result.value?.stateValue;
  const autoValue = idleMotion.result.value.stateValue;
  const interactionTarget = interactionStart.result.value.target;
  const renderSweep = renderOutputSweep.result.value;
  const runtimeState = await command("Runtime.evaluate", {
    expression: "Boolean(document.documentElement.dataset.runtimeError)",
    returnByValue: true,
  });
  socket.close();
  process.stdout.write(JSON.stringify({
    ready,
    controlChanged: Math.abs(interactionEnd.result.value.stateValue - interactionTarget) > 1e-6,
    frameChanged: interactionEnd.result.value.frame > interactionStart.result.value.beforeFrame,
    idleMotionSubjectChangedPixelRatio: idleMotion.result.value.subjectChangedPixelRatio,
    idleMotionWholeCanvasChangedPixelRatio: idleMotion.result.value.wholeCanvasChangedPixelRatio,
    idleMotionCaptureIntervalMs: idleMotion.result.value.captureIntervalMs,
    autoAdvanceValueChanged: Number.isFinite(initialValue) && Math.abs(autoValue - initialValue) > 1e-6,
    sliderTrackedAnimation: idleMotion.result.value.sliderTrackedAnimation,
    controlAlwaysEnabled: [
      firstCapture.result.value?.controlEnabled,
      idleMotion.result.value.controlEnabled,
      pauseStart.result.value.enabled,
      pauseEnd.result.value.enabled,
      interactionStart.result.value.enabled,
      interactionHeld.result.value.enabled,
      interactionEnd.result.value.enabled,
      reducedStart.result.value.enabled,
      reducedHeld.result.value.enabled,
      reducedPlayed.result.value.enabled,
    ].every(Boolean),
    pauseHeldValue: Math.abs(pauseEnd.result.value.stateValue - pauseStart.result.value.stateValue) <= 1e-6,
    pausedMotionSubjectChangedPixelRatio: pauseEnd.result.value.subjectChangedPixelRatio,
    pausedMotionWholeCanvasChangedPixelRatio: pauseEnd.result.value.wholeCanvasChangedPixelRatio,
    pausedMotionCaptureIntervalMs: pauseEnd.result.value.captureIntervalMs,
    sliderInteractionYielded: Math.abs(interactionHeld.result.value.held - interactionTarget) <= 1e-6
      && Math.abs(interactionEnd.result.value.stateValue - interactionTarget) > 1e-6,
    reducedMotionStartedPaused: reducedStart.result.value.state === 'paused'
      && Math.abs(reducedHeld.result.value.value - reducedStart.result.value.value) <= 1e-6,
    reducedMotionPlayOptInWorked: reducedHeld.result.value.state === 'playing'
      && Math.abs(reducedPlayed.result.value.value - reducedHeld.result.value.value) > 1e-6,
    renderOutputSweep: renderSweep,
    actorTracking: actorTracking.result.value,
    pausedActorTracking: pausedActorTracking.result.value,
    mobileOverlayLayout,
    visionFrameStates,
    visionFrames,
    runtimeError: runtimeState.result.value,
    externalRequests,
  }));
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
