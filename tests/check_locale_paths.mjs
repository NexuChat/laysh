import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const baseUrl = process.argv[2];
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-locale-paths-"));

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

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
  "--lang=en-US",
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
  const errors = [];
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const callbacks = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) callbacks.reject(new Error(message.error.message));
      else callbacks.resolve(message.result);
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails.text);
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
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  }
  async function waitFor(expression) {
    const deadline = Date.now() + 5000;
    while (Date.now() < deadline) {
      try {
        if (await evaluate(expression)) return;
      } catch {
        // Reloading briefly destroys the execution context.
      }
      await delay(50);
    }
    throw new Error(`Timed out waiting for ${expression}; errors=${JSON.stringify(errors)}`);
  }
  async function clickElement(id) {
    const point = await evaluate(`(() => {
      const element = document.getElementById(${JSON.stringify(id)});
      const rect = element.getBoundingClientRect();
      const x = rect.left + rect.width / 2;
      const y = rect.top + rect.height / 2;
      return { x, y, hit: document.elementFromPoint(x, y)?.id };
    })()`);
    if (point.hit !== id) throw new Error(`pointer target for ${id} was ${point.hit}`);
    await command("Input.dispatchMouseEvent", { type: "mousePressed", x: point.x, y: point.y, button: "left", clickCount: 1 });
    await command("Input.dispatchMouseEvent", { type: "mouseReleased", x: point.x, y: point.y, button: "left", clickCount: 1 });
  }
  const snapshot = () => `({
    lang: document.documentElement.lang,
    dir: document.documentElement.dir,
    hero: document.querySelector('#hero-title').textContent,
    pressed: ['locale-ar', 'locale-en'].map((id) => document.getElementById(id).getAttribute('aria-pressed')),
    path: location.pathname,
    stored: localStorage.getItem('laysh.locale'),
  })`;

  await command("Runtime.enable");
  await command("Page.enable");
  await command("Page.navigate", { url: `${baseUrl}/#ask` });
  await waitFor("document.documentElement.lang === 'en' && document.querySelector('#hero-title').textContent.startsWith('Every')");
  const english = await evaluate(snapshot());
  await clickElement("hero-title");
  const ordinaryClick = await evaluate("localStorage.getItem('laysh.locale')");
  await clickElement("locale-ar");
  await waitFor("location.pathname === '/ar' && document.querySelector('#hero-title').textContent.startsWith('كل')");
  const arabic = await evaluate(snapshot());
  await clickElement("locale-en");
  await waitFor("location.pathname === '/en' && document.querySelector('#hero-title').textContent.startsWith('Every')");
  const switchedEnglish = await evaluate(snapshot());
  await clickElement("locale-ar");
  await waitFor("location.pathname === '/ar' && document.querySelector('#hero-title').textContent.startsWith('كل')");
  await command("Page.reload", { ignoreCache: true });
  await waitFor("location.pathname === '/ar' && document.documentElement.lang === 'ar' && document.querySelector('#hero-title').textContent.startsWith('كل')");
  const reloadedArabic = await evaluate("localStorage.getItem('laysh.locale') === 'ar'");
  await command("Page.navigate", { url: `${baseUrl}/en/sims/golden_moon_phases_en` });
  await waitFor("document.documentElement.lang === 'en' && !document.querySelector('[data-view=\"result\"]').hidden");
  const shared = await evaluate(`({
    ...${snapshot()},
    sharePath: new URL(document.querySelector('#share-actions').dataset.shareUrl).pathname,
    resultVisible: !document.querySelector('[data-view="result"]').hidden,
  })`);
  const sharedEnglish = {
    lang: shared.lang,
    dir: shared.dir,
    hero: shared.hero,
    path: shared.path,
    sharePath: shared.sharePath,
    resultVisible: shared.resultVisible,
  };
  await clickElement("locale-ar");
  await waitFor("location.pathname === '/ar/sims/golden_moon_phases_en' && document.querySelector('#hero-title').textContent.startsWith('كل')");
  const sharedArabic = await evaluate(`({
    lang: document.documentElement.lang,
    hero: document.querySelector('#hero-title').textContent,
    path: location.pathname,
    resultVisible: !document.querySelector('[data-view="result"]').hidden,
  })`);
  socket.close();
  process.stdout.write(JSON.stringify({ english, ordinaryClick, arabic, switchedEnglish, reloadedArabic, sharedEnglish, sharedArabic }));
} catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
} finally {
  chrome.kill("SIGTERM");
  await Promise.race([new Promise((resolve) => chrome.once("exit", resolve)), delay(2000)]);
  fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 2 });
}
