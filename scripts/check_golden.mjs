import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactPath = path.resolve(process.argv[2]);
const screenshotRoot = path.resolve(process.argv[3]);
const goldenId = process.argv[4];
const reportPath = process.argv[5] ? path.resolve(process.argv[5]) : null;
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-golden-chrome-"));
fs.mkdirSync(screenshotRoot, { recursive: true });

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
  const target = await fetchJson(
    `http://127.0.0.1:${port}/json/new?${encodeURIComponent(pathToFileURL(artifactPath).href)}`,
    { method: "PUT" },
  );
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let nextId = 1;
  const pending = new Map();
  const consoleErrors = [];
  let externalRequests = 0;
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const callbacks = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) callbacks.reject(new Error(message.error.message));
      else callbacks.resolve(message.result);
      return;
    }
    if (message.method === "Runtime.exceptionThrown") consoleErrors.push("exception");
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
      consoleErrors.push("console.error");
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
  await command("Page.enable");
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const result = await command("Runtime.evaluate", {
      expression: "document.documentElement.dataset.layshReady === 'true'",
      returnByValue: true,
    });
    if (result.result.value === true) break;
    await delay(50);
  }
  const interaction = await command("Runtime.evaluate", {
    expression: `(() => {
      const control = document.querySelector('#primary-control');
      const root = document.documentElement;
      const canvas = document.querySelector('#simulation');
      const signature = () => {
        const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
        const stride = Math.max(4, Math.floor(data.length / 4096 / 4) * 4);
        let hash = 2166136261;
        for (let index = 0; index < data.length; index += stride) {
          hash = Math.imul(hash ^ data[index], 16777619) >>> 0;
        }
        return hash;
      };
      const initialValue = control.value;
      const values = [control.min, initialValue, control.max];
      const cases = [];
      for (const value of values) {
        const before = Number(root.dataset.frameCount || 0);
        control.value = value;
        control.dispatchEvent(new Event('input', { bubbles: true }));
        cases.push({
          value: Number(value),
          frameChanged: Number(root.dataset.frameCount || 0) > before,
          visualSignature: signature(),
        });
      }
      control.value = initialValue;
      control.dispatchEvent(new Event('input', { bubbles: true }));
      return {
        cases,
        lang: document.documentElement.lang,
        dir: document.documentElement.dir,
        ready: root.dataset.layshReady === 'true',
        runtimeError: Boolean(root.dataset.runtimeError),
        alternative: document.querySelector('#state-description').textContent.trim(),
      };
    })()`,
    returnByValue: true,
  });
  const idleBefore = await command("Runtime.evaluate", {
    expression: `(() => {
      const canvas = document.querySelector('#simulation');
      const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      const stride = Math.max(4, Math.floor(data.length / 4096 / 4) * 4);
      let hash = 2166136261;
      for (let index = 0; index < data.length; index += stride) hash = Math.imul(hash ^ data[index], 16777619) >>> 0;
      return hash;
    })()`,
    returnByValue: true,
  });
  await delay(900);
  const idleAfter = await command("Runtime.evaluate", {
    expression: `(() => {
      const canvas = document.querySelector('#simulation');
      const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      const stride = Math.max(4, Math.floor(data.length / 4096 / 4) * 4);
      let hash = 2166136261;
      for (let index = 0; index < data.length; index += stride) hash = Math.imul(hash ^ data[index], 16777619) >>> 0;
      return hash;
    })()`,
    returnByValue: true,
  });
  const screenshots = [];
  for (const viewport of [
    { name: "mobile-390x844", width: 390, height: 844 },
    { name: "desktop-1440x900", width: 1440, height: 900 },
  ]) {
    await command("Emulation.setDeviceMetricsOverride", {
      width: viewport.width,
      height: viewport.height,
      deviceScaleFactor: 1,
      mobile: viewport.width < 600,
    });
    await delay(100);
    const captured = await command("Page.captureScreenshot", { format: "png", fromSurface: true });
    const filename = `${goldenId}-${viewport.name}.png`;
    fs.writeFileSync(path.join(screenshotRoot, filename), Buffer.from(captured.data, "base64"));
    screenshots.push(filename);
  }
  socket.close();
  const evidence = {
    ...interaction.result.value,
    idleFrameChanged: idleBefore.result.value !== idleAfter.result.value,
    reactiveFrameVariants: new Set(
      interaction.result.value.cases.map((item) => item.visualSignature),
    ).size,
    externalRequests,
    consoleErrors,
    screenshots,
  };
  if (reportPath) {
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(reportPath, `${JSON.stringify(evidence, null, 2)}\n`);
  }
  process.stdout.write(JSON.stringify(evidence));
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
} finally {
  chrome.kill("SIGTERM");
  await Promise.race([new Promise((resolve) => chrome.once("exit", resolve)), delay(2000)]);
  fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 2 });
}
