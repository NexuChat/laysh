import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const baseUrl = process.argv[2];
const manifestPath = path.resolve(process.argv[3]);
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-assets-chrome-"));

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
  const responses = [];
  const consoleErrors = [];
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const callbacks = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) callbacks.reject(new Error(message.error.message));
      else callbacks.resolve(message.result);
      return;
    }
    if (message.method === "Network.responseReceived") {
      const response = message.params.response;
      if (response.url.includes("/static/")) {
        responses.push({
          url: response.url,
          status: response.status,
          cacheControl: response.headers["cache-control"] || response.headers["Cache-Control"] || "",
        });
      }
    }
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
      consoleErrors.push(message.params.args.map((item) => item.value || item.description).join(" "));
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
  async function evaluate(expression) {
    const result = await command("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    return result.result.value;
  }
  await command("Runtime.enable");
  await command("Network.enable");
  await command("Page.enable");
  await command("Page.navigate", { url: `${baseUrl}/` });
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    if (await evaluate("document.readyState === 'complete' && document.fonts.status === 'loaded'")) break;
    await delay(50);
  }
  await delay(300);
  const dom = await evaluate(`(() => ({
    scripts: [...document.scripts].map((item) => item.src).filter(Boolean),
    styles: [...document.querySelectorAll('link[rel="stylesheet"],link[rel="preload"]')]
      .map((item) => item.href).filter((url) => url.includes('/static/')),
    localeReady: Boolean(window.LayshLocale),
  }))()`);
  const byPath = Object.fromEntries(
    responses.map((response) => [new URL(response.url).pathname.replace("/static/", ""), response]),
  );
  const loadedCore = ["app.css", "app.js", "locale.js", "translations.js"];
  const checks = {
    cleanProfile: profilePath.includes("laysh-assets-chrome-"),
    localeReady: dom.localeReady,
    coreAssetsLoaded: loadedCore.every((asset) => byPath[asset]?.status === 200),
    everyRequestVersioned: responses.every((response) => {
      const url = new URL(response.url);
      const asset = url.pathname.replace("/static/", "");
      const metadata = manifest.assets[asset];
      return metadata && [manifest.bundle_version, metadata.sha256].includes(url.searchParams.get("v"));
    }),
    everyResponseImmutable: responses.every(
      (response) => response.cacheControl === "public, max-age=31536000, immutable",
    ),
    oneHtmlBundleVersion: [...dom.scripts, ...dom.styles].every(
      (url) => new URL(url).searchParams.get("v") === manifest.bundle_version,
    ),
    noConsoleErrors: consoleErrors.length === 0,
  };
  socket.close();
  process.stdout.write(JSON.stringify({
    passed: Object.values(checks).every(Boolean),
    checks,
    responseCount: responses.length,
    responses,
    consoleErrors,
  }));
} catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
} finally {
  chrome.kill("SIGTERM");
  await Promise.race([new Promise((resolve) => chrome.once("exit", resolve)), delay(2000)]);
  fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 2 });
}
