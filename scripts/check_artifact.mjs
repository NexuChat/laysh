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
      return { controlValue: Number(control.value), controlEnabled: !control.disabled };
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
      return { value: Number(control.value), enabled: !control.disabled };
    })()`,
    returnByValue: true,
  });
  await delay(350);
  const pauseEnd = await command("Runtime.evaluate", {
    expression: `(() => {
      const control = document.querySelector('#primary-control');
      return { value: Number(control.value), enabled: !control.disabled };
    })()`,
    returnByValue: true,
  });

  const actorTracking = await command("Runtime.evaluate", {
    expression: actionTrackingSource,
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
      return { value: Number(control.value), frame: Number(root.dataset.frameCount || 0), enabled: !control.disabled };
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
      return { value: Number(control.value), state: document.documentElement.dataset.motionState, enabled: !control.disabled };
    })()`,
    returnByValue: true,
  });
  await delay(400);
  const reducedHeld = await command("Runtime.evaluate", {
    expression: `(() => {
      const control = document.querySelector('#primary-control');
      document.querySelector('#play-pause').click();
      return { value: Number(control.value), state: document.documentElement.dataset.motionState, enabled: !control.disabled };
    })()`,
    returnByValue: true,
  });
  await delay(400);
  const reducedPlayed = await command("Runtime.evaluate", {
    expression: `(() => {
      const control = document.querySelector('#primary-control');
      document.querySelector('#play-pause').click();
      return { value: Number(control.value), state: document.documentElement.dataset.motionState, enabled: !control.disabled };
    })()`,
    returnByValue: true,
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
      for (let index = 1; index < compactSamples.length; index += 1) {
        const left = compactSamples[index - 1], right = compactSamples[index];
        const renderedDelta = best.span ? Math.abs(right.renderedMeasure - left.renderedMeasure) / best.span : 0;
        const outputDelta = outputSpan ? Math.abs(right.computedOutput - left.computedOutput) / outputSpan : 0;
        if (renderedDelta > 0.42 && outputDelta < 0.18) {
          cliff = { code: 'rendered_output_discontinuity', metric: best.key, left, right };
          break;
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
        for (let repeat = 0; repeat < 7; repeat += 1) {
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
  await command("Runtime.evaluate", {
    expression: "delete window.__LAYSH_VERIFICATION_TIME__",
  });

  const initialValue = firstCapture.result.value?.controlValue;
  const autoValue = idleMotion.result.value.controlValue;
  const interactionTarget = interactionStart.result.value.target;
  const renderSweep = renderOutputSweep.result.value;
  const runtimeState = await command("Runtime.evaluate", {
    expression: "Boolean(document.documentElement.dataset.runtimeError)",
    returnByValue: true,
  });
  socket.close();
  process.stdout.write(JSON.stringify({
    ready,
    controlChanged: interactionEnd.result.value.value !== interactionTarget,
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
    pauseHeldValue: Math.abs(pauseEnd.result.value.value - pauseStart.result.value.value) <= 1e-6,
    sliderInteractionYielded: Math.abs(interactionHeld.result.value.held - interactionTarget) <= 1e-6
      && Math.abs(interactionEnd.result.value.value - interactionTarget) > 1e-6,
    reducedMotionStartedPaused: reducedStart.result.value.state === 'paused'
      && Math.abs(reducedHeld.result.value.value - reducedStart.result.value.value) <= 1e-6,
    reducedMotionPlayOptInWorked: reducedHeld.result.value.state === 'playing'
      && Math.abs(reducedPlayed.result.value.value - reducedHeld.result.value.value) > 1e-6,
    renderOutputSweep: renderSweep,
    actorTracking: actorTracking.result.value,
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
