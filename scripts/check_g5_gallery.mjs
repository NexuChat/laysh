import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const baseUrl = process.argv[2];
const reportPath = process.argv[3] ? path.resolve(process.argv[3]) : null;
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-gallery-chrome-"));

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
    `http://127.0.0.1:${port}/json/new?${encodeURIComponent(baseUrl)}`,
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
  const requests = [];
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
      requests.push({ url: message.params.request.url, method: message.params.request.method });
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
    const result = await command("Runtime.evaluate", { expression, returnByValue: true });
    return result.result.value;
  }
  await command("Runtime.enable");
  await command("Network.enable");
  await command("Page.enable");
  await command("Page.navigate", { url: `${baseUrl}/` });
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (await evaluate("document.readyState === 'complete'")) break;
    await delay(50);
  }
  let cards = [];
  for (let attempt = 0; attempt < 100; attempt += 1) {
    cards = await evaluate(`Array.from(document.querySelectorAll('[data-golden-id]')).map(card => ({
      id: card.dataset.goldenId,
      badge: card.querySelector('.instant-badge')?.textContent || '',
      enabled: !card.querySelector('.golden-launch').disabled,
    }))`);
    if (cards.length === 6 && cards.every((card) => card.enabled)) break;
    await delay(50);
  }
  const journeys = [];
  for (const card of cards) {
    await evaluate(`document.querySelector('[data-golden-id="${card.id}"] .golden-launch').click()`);
    let result = null;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      result = await evaluate(`(() => ({
        visible: !document.querySelector('[data-view="result"]').hidden,
        title: document.querySelector('#result-title').textContent,
        tier: document.querySelector('#receipt-tier').textContent,
        src: document.querySelector('#simulation-frame').getAttribute('src') || '',
      }))()`);
      if (result.visible && result.src) break;
      await delay(50);
    }
    journeys.push({ id: card.id, ...result });
    await evaluate("document.querySelector('#ask-another-top').click()");
    await delay(20);
  }
  socket.close();
  const askPosts = requests.filter(
    (request) => request.url === `${baseUrl}/api/ask` && request.method === "POST",
  ).length;
  const externalRequests = requests.filter(
    (request) => !request.url.startsWith(baseUrl) && !request.url.startsWith("data:"),
  ).length;
  const evidence = {
    cards,
    journeys,
    askPosts,
    externalRequests,
    consoleErrors,
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
