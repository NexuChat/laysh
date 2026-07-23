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
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
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
