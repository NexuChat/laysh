import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const baseUrl = process.argv[2];
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-bilingual-chrome-"));

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
    if (message.method === "Runtime.exceptionThrown") consoleErrors.push("exception");
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
      consoleErrors.push("console.error");
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
  async function waitFor(expression, timeout = 5000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      try {
        if (await evaluate(expression)) return;
      } catch {
        // Reloads briefly destroy the execution context.
      }
      await delay(50);
    }
    let snapshot = "execution context unavailable";
    try {
      snapshot = await evaluate(`JSON.stringify({
        ready: document.readyState,
        lang: document.documentElement.lang,
        dir: document.documentElement.dir,
        badges: document.querySelectorAll('.instant-badge').length,
        cards: document.querySelectorAll('.gallery-card').length,
        galleryState: document.documentElement.dataset.galleryState,
        galleryError: document.documentElement.dataset.galleryError,
        localeApi: Boolean(window.LayshLocale),
        translations: Boolean(window.LayshTranslations),
      })`);
    } catch {
      // Keep the default diagnostic.
    }
    throw new Error(`Timed out waiting for ${expression}: ${snapshot}; console=${consoleErrors}`);
  }
  const languageOverride = (languages) => `
    Object.defineProperty(Navigator.prototype, 'languages', { configurable: true, get: () => ${JSON.stringify(languages)} });
    Object.defineProperty(Navigator.prototype, 'language', { configurable: true, get: () => ${JSON.stringify(languages[0])} });
  `;
  await command("Runtime.enable");
  await command("Page.enable");
  const englishOverride = await command("Page.addScriptToEvaluateOnNewDocument", {
    source: languageOverride(["en-US", "en"]),
  });
  await command("Page.navigate", { url: `${baseUrl}/` });
  await waitFor("document.documentElement.lang === 'en' && document.querySelectorAll('.instant-badge').length === 6");
  const detectedEnglish = await evaluate(`(() => {
    const leaks = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const parent = walker.currentNode.parentElement;
      if (!parent || parent.closest('.brand, .brand-inline, script, style, [hidden]')) continue;
      const style = getComputedStyle(parent);
      const rect = parent.getBoundingClientRect();
      if (style.display === 'none' || style.visibility === 'hidden' || rect.width === 0 || rect.height === 0) continue;
      leaks.push(...(walker.currentNode.textContent.match(/[\u0600-\u06ff]+/g) || []));
    }
    return {
      lang: document.documentElement.lang,
      dir: document.documentElement.dir,
      title: document.querySelector('#hero-title').textContent,
      lessonIds: Array.from(document.querySelectorAll('[data-golden-id]')).map((card) => card.dataset.lessonId),
      arabicLeaks: leaks,
      switchVisible: document.querySelector('#locale-switch').getBoundingClientRect().height > 0,
    };
  })()`);

  await evaluate("document.querySelector('#locale-ar').click()");
  await waitFor("document.documentElement.lang === 'ar' && document.querySelectorAll('.instant-badge').length === 6");
  const selectedArabic = await evaluate(`({
    lang: document.documentElement.lang,
    dir: document.documentElement.dir,
    stored: localStorage.getItem('laysh.locale'),
    lessonIds: Array.from(document.querySelectorAll('[data-golden-id]')).map((card) => card.dataset.lessonId),
  })`);
  await command("Page.reload", { ignoreCache: true });
  await waitFor("document.documentElement.lang === 'ar' && document.querySelectorAll('.instant-badge').length === 6");
  const persistedArabic = await evaluate("document.documentElement.lang === 'ar' && localStorage.getItem('laysh.locale') === 'ar'");

  await evaluate("localStorage.removeItem('laysh.locale')");
  await command("Page.removeScriptToEvaluateOnNewDocument", {
    identifier: englishOverride.identifier,
  });
  await command("Page.addScriptToEvaluateOnNewDocument", {
    source: languageOverride(["ar-SA", "en-US"]),
  });
  await command("Page.navigate", { url: `${baseUrl}/` });
  await waitFor("document.documentElement.lang === 'ar' && document.querySelectorAll('.instant-badge').length === 6");
  const detectedArabic = await evaluate("document.documentElement.dir === 'rtl' && localStorage.getItem('laysh.locale') === null");

  await evaluate("document.querySelector('#locale-en').click()");
  await waitFor("document.documentElement.lang === 'en' && document.querySelectorAll('.instant-badge').length === 6");
  await command("Page.reload", { ignoreCache: true });
  await waitFor("document.documentElement.lang === 'en' && document.querySelectorAll('.instant-badge').length === 6");
  const explicitEnglishWins = await evaluate(`({
    lang: document.documentElement.lang,
    dir: document.documentElement.dir,
    stored: localStorage.getItem('laysh.locale'),
    lessonIds: Array.from(document.querySelectorAll('[data-golden-id]')).map((card) => card.dataset.lessonId),
  })`);
  socket.close();
  process.stdout.write(JSON.stringify({
    detectedEnglish,
    selectedArabic,
    persistedArabic,
    detectedArabic,
    explicitEnglishWins,
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
