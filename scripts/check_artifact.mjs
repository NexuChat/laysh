import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactPath = path.resolve(process.argv[2]);
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

  await command("Runtime.evaluate", {
    expression: `(() => {
      const canvas = document.querySelector('#simulation');
      const context = canvas && canvas.getContext('2d');
      if (!canvas || !context) return false;
      window.__layshMotionFirst = context.getImageData(0, 0, canvas.width, canvas.height).data;
      return true;
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
      if (!canvas || !context || !first) return { changedPixelRatio: 0, captureIntervalMs: 1100 };
      const second = context.getImageData(0, 0, canvas.width, canvas.height).data;
      let changed = 0;
      for (let pixel = 0; pixel < first.length; pixel += 4) {
        if (first[pixel] !== second[pixel] || first[pixel + 1] !== second[pixel + 1] || first[pixel + 2] !== second[pixel + 2]) changed += 1;
      }
      return { changedPixelRatio: changed / (first.length / 4), captureIntervalMs: 1100 };
    })()`,
    returnByValue: true,
  });

  const interaction = await command("Runtime.evaluate", {
    expression: `(() => {
      const root = document.documentElement;
      const before = Number(root.dataset.frameCount || 0);
      const choice = document.querySelector('#prediction-choices button');
      const hint = document.querySelector('#prediction-hint');
      const prediction = document.querySelector('#prediction');
      const hintVisibleBefore = !hint.hidden && prediction.classList.contains('awaiting-prediction');
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
        predictionHintBehavior: hintVisibleBefore && hint.hidden && !prediction.classList.contains('awaiting-prediction') && control.classList.contains('is-unlocked'),
        runtimeError: Boolean(root.dataset.runtimeError),
      };
    })()`,
    returnByValue: true,
  });
  socket.close();
  process.stdout.write(JSON.stringify({
    ready,
    controlChanged: interaction.result.value.controlChanged,
    frameChanged: interaction.result.value.frameChanged,
    idleMotionChangedPixelRatio: idleMotion.result.value.changedPixelRatio,
    idleMotionCaptureIntervalMs: idleMotion.result.value.captureIntervalMs,
    predictionHintBehavior: interaction.result.value.predictionHintBehavior,
    runtimeError: interaction.result.value.runtimeError,
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
