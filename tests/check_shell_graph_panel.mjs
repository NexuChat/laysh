import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const baseUrl = process.argv[2];
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-graph-chrome-"));

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const fetchJson = async (url, options) => {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
};
async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

const port = await freePort();
const chrome = spawn(chromePath, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${port}`, `--user-data-dir=${profilePath}`, "about:blank",
], { stdio: "ignore" });
let socket;
try {
  let version;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try { version = await fetchJson(`http://127.0.0.1:${port}/json/version`); break; } catch { await delay(50); }
  }
  if (!version) throw new Error("Chrome debugging endpoint did not start");
  const target = await fetchJson(`http://127.0.0.1:${port}/json/new?${encodeURIComponent("about:blank")}`, { method: "PUT" });
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let nextId = 1;
  const pending = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const callbacks = pending.get(message.id); pending.delete(message.id);
    if (message.error) callbacks.reject(new Error(message.error.message));
    else callbacks.resolve(message.result);
  });
  const command = (method, params = {}) => new Promise((resolve, reject) => {
    const id = nextId; nextId += 1; pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await command("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "evaluation failed");
    return result.result.value;
  };
  async function waitFor(expression) {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      try {
        if (await evaluate(expression)) return;
      } catch {
        // A navigation briefly destroys the execution context before the next document exists.
      }
      await delay(50);
    }
    throw new Error(`Timed out waiting for: ${expression}`);
  }
  async function viewport(width, height) {
    await command("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width <= 480, screenWidth: width, screenHeight: height });
  }
  async function load(name) {
    await command("Page.navigate", { url: `${baseUrl}/${name}` });
    await waitFor("document.documentElement.dataset.layshReady === 'true'");
  }
  await command("Runtime.enable"); await command("Page.enable");
  await viewport(1200, 900);
  await load("world-only.html");
  const worldOnly = await evaluate(`({ graph: Boolean(document.querySelector('#simulation-graph')), sceneLayout: Boolean(document.querySelector('.scene-layout')) })`);
  await load("world-plus-graph.html");
  const graphBefore = await evaluate(`(() => {
    const graph = document.querySelector('#simulation-graph');
    return { exists: Boolean(graph), marker: graph?.dataset.markerX || null, ariaLabel: graph?.getAttribute('aria-label') || '' };
  })()`);
  const graphAfter = await evaluate(`(() => {
    const control = document.querySelector('#primary-control');
    control.value = control.max; control.dispatchEvent(new Event('input', { bubbles: true }));
    return document.querySelector('#simulation-graph').dataset.markerX;
  })()`);
  const mobile = [];
  for (const width of [320, 390]) {
    await viewport(width, 844); await load("world-plus-graph.html");
    mobile.push(await evaluate(`(() => {
      const scene = document.querySelector('#simulation').getBoundingClientRect();
      const graph = document.querySelector('#simulation-graph').getBoundingClientRect();
      const choices = [...document.querySelectorAll('#prediction-choices button')];
      return { stacked: graph.top >= scene.bottom - 1, predictionChoicesInsideViewport: choices.length > 0 && choices.every((choice) => {
        const rect = choice.getBoundingClientRect(); return rect.left >= -1 && rect.right <= innerWidth + 1;
      }) };
    })()`));
  }
  process.stdout.write(JSON.stringify({ worldOnly, graph: { ...graphBefore, markerMoved: graphBefore.marker !== graphAfter }, mobile }));
} finally {
  socket?.close();
  if (!chrome.killed) {
    chrome.kill("SIGTERM");
    await new Promise((resolve) => chrome.once("exit", resolve));
  }
  fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
}
