import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const baseUrl = process.argv[2];
const screenshotDirectory = path.resolve(process.argv[3]);
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-i18n-chrome-"));
fs.mkdirSync(screenshotDirectory, { recursive: true });

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
  "--force-color-profile=srgb",
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profilePath}`,
  "about:blank",
], { stdio: "ignore" });

let socket;
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
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });

  let nextId = 1;
  const pending = new Map();
  const consoleErrors = [];
  const networkFailures = [];
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const waiter = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message));
      else waiter.resolve(message.result);
      return;
    }
    if (message.method === "Runtime.exceptionThrown") {
      consoleErrors.push(message.params.exceptionDetails.text || "runtime exception");
    }
    if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      consoleErrors.push(message.params.entry.text);
    }
    if (
      message.method === "Network.loadingFailed"
      && ["Document", "Script", "Stylesheet", "Font"].includes(message.params.type)
      && message.params.errorText !== "net::ERR_ABORTED"
    ) {
      networkFailures.push(`${message.params.type}:${message.params.errorText}`);
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
    const response = await command("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.text || "evaluation failed");
    return response.result.value;
  }

  async function waitFor(expression, timeout = 15000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return;
      await delay(100);
    }
    throw new Error(`Timed out waiting for: ${expression}`);
  }

  async function navigate() {
    await command("Page.navigate", { url: `${baseUrl}/` });
    await waitFor("document.readyState === 'complete'", 10000);
  }

  async function capture(name) {
    const screenshot = await command("Page.captureScreenshot", {
      format: "png",
      fromSurface: true,
      captureBeyondViewport: false,
    });
    fs.writeFileSync(path.join(screenshotDirectory, name), Buffer.from(screenshot.data, "base64"));
  }

  await command("Runtime.enable");
  await command("Page.enable");
  await command("Network.enable");
  await command("Log.enable");
  await command("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 900,
    deviceScaleFactor: 1,
    mobile: false,
    screenWidth: 1440,
    screenHeight: 900,
  });
  await navigate();
  await evaluate(`localStorage.setItem("laysh-locale", "ar")`);
  await navigate();
  await waitFor("!document.querySelector('[data-golden-id=\"moon_phases\"] .golden-launch').disabled", 5000);

  const defaultEnglish = await evaluate(`({
    lang: document.documentElement.lang,
    dir: document.documentElement.dir,
    landing: document.querySelector('#hero-title').textContent.includes('curious question'),
  })`);
  await capture("i18n-en-landing.png");

  await evaluate(`(() => {
    window.__localeWrites = [];
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) {
      window.__localeWrites.push([key, value]);
      return original.call(this, key, value);
    };
    for (const selector of ['.brand', '.lab-label', '#hero-title', '#safe-example', '#gallery-title']) {
      document.querySelector(selector).click();
    }
  })()`);
  const beforeControl = defaultEnglish.lang;
  const afterOutsideClicks = await evaluate("document.documentElement.lang");
  const outsideWrites = await evaluate("window.__localeWrites");

  await evaluate("document.querySelector('#locale-control').click()");
  await waitFor("document.documentElement.lang === 'ar'");
  await waitFor(
    "document.querySelector('[data-golden-id=\"moon_phases\"] .instant-badge').textContent === 'فوري'",
    5000,
  );
  const arabic = await evaluate(`({
    lang: document.documentElement.lang,
    dir: document.documentElement.dir,
    landing: document.querySelector('#hero-title').textContent.includes('سؤال فضولي'),
    instant: Array.from(document.querySelectorAll('.instant-badge')).every((badge) => badge.textContent === 'فوري'),
  })`);
  await capture("i18n-ar-landing.png");
  const controlWritesAfterArabic = await evaluate("window.__localeWrites");
  await evaluate("document.querySelector('#locale-control').click()");
  await waitFor("document.documentElement.lang === 'en'");
  await waitFor("document.querySelector('[data-golden-id=\"moon_phases\"] h3').textContent === 'Moon phases'", 5000);
  const controlWrites = await evaluate("window.__localeWrites");

  await evaluate("document.querySelector('[data-golden-id=\"moon_phases\"] .golden-launch').click()");
  await waitFor("!document.querySelector('#result-view').hidden", 5000);
  const goldenArtifact = await evaluate(`(async () => {
    const frame = document.querySelector('#simulation-frame');
    const artifact = await fetch(frame.src).then((response) => response.text());
    return {
      title: document.querySelector('#result-title').textContent,
      direction: artifact.includes('<html lang="en" dir="ltr">'),
      lesson: artifact.includes('"lang":"en"'),
    };
  })()`);
  await capture("i18n-en-golden.png");
  await evaluate("document.querySelector('#ask-another-top').click()");

  await evaluate(`(() => {
    window.__askLocales = [];
    const originalFetch = window.fetch;
    window.fetch = (input, init = {}) => {
      if (String(input) === '/api/ask') window.__askLocales.push(JSON.parse(init.body).locale);
      return originalFetch(input, init);
    };
    const field = document.querySelector('#question');
    field.value = 'Why does the Moon change shape?';
    document.querySelector('#ask-form').requestSubmit();
  })()`);
  await waitFor("!document.querySelector('#build-view').hidden", 3000);
  await waitFor(
    "document.querySelector('#stage-list').textContent.includes('The question and short answer are ready.')",
    5000,
  );
  const build = await evaluate(
    "document.querySelector('#build-title').textContent.includes('experience')"
      + " && document.querySelector('#stage-list').textContent.includes('The question and short answer are ready.')",
  );
  await waitFor("!document.querySelector('#result-view').hidden", 20000);
  await waitFor("document.querySelector('#simulation-frame').src.includes('/api/sims/')", 5000);
  const resultEvidence = await evaluate(`(async () => {
    const frame = document.querySelector('#simulation-frame');
    const artifact = await fetch(frame.src).then((response) => response.text());
    return {
      result: document.querySelector('#simulation-heading').textContent === 'Try it yourself',
      receipt: document.querySelector('#verification-receipt summary').textContent === 'What did we check?',
      artifactDirection: artifact.includes('<html lang="en" dir="ltr">')
        && artifact.includes('Interactive answer'),
    };
  })()`);
  await capture("i18n-en-result.png");

  await evaluate(`(() => {
    document.querySelector('#ask-another-top').click();
    const field = document.querySelector('#question');
    field.value = 'not simulatable';
    document.querySelector('#ask-form').requestSubmit();
  })()`);
  await waitFor("!document.querySelector('#failure-view').hidden", 8000);
  const failure = await evaluate(
    "document.querySelector('#failure-title').textContent === 'We kept the answer'"
      + " && document.querySelector('#retry-action').textContent.includes('Try building again')"
      + " && document.querySelector('#suggestion-list').textContent.includes('Why does the Moon change shape?')",
  );
  const requestLocales = await evaluate("window.__askLocales");
  const english = await evaluate(`({
    lang: document.documentElement.lang,
    dir: document.documentElement.dir,
    landing: document.querySelector('#hero-title').textContent.includes('curious question'),
    gallery: document.querySelector('[data-golden-id="moon_phases"] h3').textContent === 'Moon phases',
  })`);
  english.build = build;
  english.result = resultEvidence.result;
  english.receipt = resultEvidence.receipt;
  english.failure = failure;
  english.artifactDirection = resultEvidence.artifactDirection;
  english.golden = goldenArtifact;

  await navigate();
  await waitFor("document.documentElement.lang === 'en'");
  const persistedAfterReload = await evaluate("document.documentElement.lang");

  process.stdout.write(JSON.stringify({
    defaultEnglish,
    arabic,
    english,
    requestLocales,
    eventScope: {
      beforeControl,
      afterOutsideClicks,
      outsideWrites,
      afterControl: controlWritesAfterArabic.at(-1)?.[1],
      controlWritesAfterArabic,
      controlWrites,
      persistedAfterReload,
    },
    consoleErrors,
    networkFailures,
  }));
} finally {
  if (socket && socket.readyState === WebSocket.OPEN) socket.close();
  chrome.kill("SIGTERM");
  try {
    fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
  } catch {
    // Chrome can still be releasing its disposable profile after the test result is known.
  }
}
