import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactRoot = path.resolve(process.argv[2]);
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-library-chrome-"));

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

const canvasState = `(() => {
  const canvas = document.querySelector('#simulation');
  const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
  const stride = Math.max(4, Math.floor(data.length / 8192 / 4) * 4);
  let hash = 2166136261;
  for (let index = 0; index < data.length; index += stride) {
    hash = Math.imul(hash ^ data[index], 16777619) >>> 0;
    hash = Math.imul(hash ^ data[index + 1], 16777619) >>> 0;
    hash = Math.imul(hash ^ data[index + 2], 16777619) >>> 0;
  }
  const root = document.documentElement;
  const control = document.querySelector('#primary-control');
  const toggle = document.querySelector('#play-pause');
  return {
    hash,
    frames: Number(root.dataset.frameCount || 0),
    state: root.dataset.playbackState,
    reason: root.dataset.playbackReason,
    reducedMotion: root.dataset.reducedMotion,
    controlValue: control.value,
    controlDefault: String(window.__LAYSH_LESSON__.primary_parameter.default),
    toggleVisible: Boolean(toggle && toggle.getBoundingClientRect().width > 0),
    toggleLabel: toggle?.textContent || '',
  };
})()`;

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

async function openProbe(artifactPath, reducedMotion) {
  const target = await fetchJson(
    `http://127.0.0.1:${port}/json/new?${encodeURIComponent("about:blank")}`,
    { method: "PUT" },
  );
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let nextId = 1;
  const pending = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const callbacks = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) callbacks.reject(new Error(message.error.message));
    else callbacks.resolve(message.result);
  });
  function command(method, params = {}) {
    const id = nextId;
    nextId += 1;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }
  async function evaluate(expression) {
    const response = await command("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (response.exceptionDetails) {
      throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
    }
    return response.result.value;
  }
  async function waitFor(expression, timeout = 10000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return;
      await delay(50);
    }
    throw new Error(`timed out waiting for ${expression}`);
  }
  await command("Runtime.enable");
  await command("Page.enable");
  await command("Emulation.setEmulatedMedia", {
    media: "screen",
    features: [{ name: "prefers-reduced-motion", value: reducedMotion ? "reduce" : "no-preference" }],
  });
  await command("Page.navigate", { url: pathToFileURL(artifactPath).href });
  await waitFor("document.documentElement?.dataset?.layshReady === 'true'");
  return { socket, command, evaluate };
}

async function normalJourney(artifactPath) {
  const probe = await openProbe(artifactPath, false);
  try {
    const initial = await probe.evaluate(canvasState);
    await delay(650);
    const autoplay = await probe.evaluate(canvasState);
    await probe.evaluate("document.querySelector('#play-pause').click()");
    const paused = await probe.evaluate(canvasState);
    await delay(350);
    const pausedLater = await probe.evaluate(canvasState);
    await probe.evaluate("document.querySelector('#play-pause').click()");
    await delay(500);
    const resumed = await probe.evaluate(canvasState);
    const direct = await probe.evaluate(`(() => {
      const control = document.querySelector('#primary-control');
      control.value = Number(control.value) === Number(control.max) ? control.min : control.max;
      control.dispatchEvent(new Event('input', { bubbles: true }));
      return (${canvasState});
    })()`);
    await delay(350);
    const directLater = await probe.evaluate(canvasState);
    await probe.evaluate("document.querySelector('#reset').click()");
    const resetOnce = await probe.evaluate(canvasState);
    await delay(350);
    const resetOnceLater = await probe.evaluate(canvasState);
    await probe.evaluate(`(() => {
      const control = document.querySelector('#primary-control');
      control.value = control.max;
      control.dispatchEvent(new Event('input', { bubbles: true }));
      document.querySelector('#reset').click();
    })()`);
    const resetTwice = await probe.evaluate(canvasState);
    await probe.evaluate("window.dispatchEvent(new Event('pagehide'))");
    const destroyed = await probe.evaluate(canvasState);
    await delay(250);
    const destroyedLater = await probe.evaluate(canvasState);
    return {
      initial,
      autoplay,
      paused,
      pausedLater,
      resumed,
      direct,
      directLater,
      resetOnce,
      resetOnceLater,
      resetTwice,
      destroyed,
      destroyedLater,
      checks: {
        startsAutomatically: initial.state === "running" && initial.toggleVisible,
        scientificCanvasMoves: initial.hash !== autoplay.hash,
        pauseStopsCanvas: paused.state === "paused" && paused.hash === pausedLater.hash,
        resumeRestartsCanvas: resumed.state === "running" && resumed.hash !== pausedLater.hash,
        controlYieldsPlayback: direct.state === "paused" && direct.reason === "user-control"
          && direct.hash === directLater.hash,
        resetReturnsToAStillDefault: resetOnce.state === "paused"
          && resetOnce.controlValue === resetOnce.controlDefault
          && resetOnce.hash === resetOnceLater.hash
          && resetTwice.state === "paused"
          && resetTwice.controlValue === resetTwice.controlDefault,
        teardownStopsWork: destroyed.state === "destroyed"
          && destroyed.frames === destroyedLater.frames
          && destroyed.hash === destroyedLater.hash,
      },
    };
  } finally {
    probe.socket.close();
  }
}

async function reducedJourney(artifactPath) {
  const probe = await openProbe(artifactPath, true);
  try {
    const initial = await probe.evaluate(canvasState);
    await delay(500);
    const later = await probe.evaluate(canvasState);
    return {
      initial,
      later,
      checks: {
        preferenceDetected: initial.reducedMotion === "true",
        startsPaused: initial.state === "paused" && initial.reason === "reduced-motion",
        canvasRemainsReadableAndStill: initial.hash === later.hash,
        controlsRemainAvailable: initial.toggleVisible && initial.toggleLabel.length > 0,
      },
    };
  } finally {
    probe.socket.close();
  }
}

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
  const files = fs.readdirSync(artifactRoot).filter((name) => name.endsWith(".html")).sort();
  const lessons = [];
  for (const name of files) {
    const artifactPath = path.join(artifactRoot, name);
    const normal = await normalJourney(artifactPath);
    const reduced = await reducedJourney(artifactPath);
    const passed = [...Object.values(normal.checks), ...Object.values(reduced.checks)].every(Boolean);
    lessons.push({ id: path.basename(name, ".html"), passed, normal, reduced });
  }
  process.stdout.write(JSON.stringify({
    passed: lessons.length === 6 && lessons.every((lesson) => lesson.passed),
    lessonCount: lessons.length,
    lessons,
  }));
} catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
} finally {
  chrome.kill("SIGTERM");
  await Promise.race([new Promise((resolve) => chrome.once("exit", resolve)), delay(2000)]);
  fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 2 });
}
