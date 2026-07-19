import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const baseUrl = process.argv[2];
const screenshotDirectory = path.resolve(process.argv[3]);
const evidencePrefix = process.argv[4] || "g4-live";
const liveQuestion = process.argv[5] || "لماذا يتغير شكل القمر خلال الشهر؟";
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-live-product-"));
fs.mkdirSync(screenshotDirectory, { recursive: true });

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
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
      return;
    }
    if (message.method === "Runtime.exceptionThrown") {
      consoleErrors.push(message.params.exceptionDetails.text || "runtime exception");
    }
    if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      consoleErrors.push(message.params.entry.text);
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
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
    return response.result.value;
  }

  async function waitFor(expression, timeout) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return;
      await delay(150);
    }
    throw new Error(`Timed out waiting for: ${expression}`);
  }

  async function setViewport(width, height, mobile) {
    await command("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile,
      screenWidth: width,
      screenHeight: height,
    });
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
  await command("Log.enable");
  await setViewport(390, 844, true);
  await command("Page.navigate", { url: `${baseUrl}/` });
  await waitFor("document.readyState === 'complete'", 10000);
  await capture(`${evidencePrefix}-landing-mobile-390x844.png`);
  const startedAt = Date.now();
  await evaluate(`(() => {
    document.querySelector('#question').value = ${JSON.stringify(liveQuestion)};
    document.querySelector('#ask-form').requestSubmit();
  })()`);

  let answerObservedBeforeResult = false;
  let answerLatencyMs = null;
  let buildCaptured = false;
  const deadline = Date.now() + 195000;
  while (Date.now() < deadline) {
    const observation = await evaluate(`({
      answer: !document.querySelector('#answer-card').hidden,
      result: !document.querySelector('#result-view').hidden,
      failure: !document.querySelector('#failure-view').hidden,
      failureTitle: document.querySelector('#failure-title').textContent,
    })`);
    if (observation.answer && !observation.result) {
      answerObservedBeforeResult = true;
      answerLatencyMs ??= Date.now() - startedAt;
      if (!buildCaptured) {
        await capture(`${evidencePrefix}-build-mobile-390x844.png`);
        buildCaptured = true;
      }
    }
    if (observation.failure) throw new Error(`Live job failed: ${observation.failureTitle}`);
    if (observation.result) break;
    await delay(200);
  }
  await waitFor("!document.querySelector('#result-view').hidden", 1000);
  await waitFor("document.querySelector('#simulation-frame').src.includes('/api/sims/')", 5000);
  await delay(500);
  const totalObservedMs = Date.now() - startedAt;
  const result = await evaluate(`(() => {
    const arabicDigits = '٠١٢٣٤٥٦٧٨٩';
    const toNumber = (value) => Number([...value].map((character) => {
      const index = arabicDigits.indexOf(character);
      return index >= 0 ? String(index) : character;
    }).join('').replace(/[^0-9.]/g, ''));
    return {
      resultVisible: !document.querySelector('#result-view').hidden,
      sandbox: document.querySelector('#simulation-frame').getAttribute('sandbox'),
      checkCount: toNumber(document.querySelector('#check-count').textContent),
      effectiveModel: document.querySelector('#effective-model').textContent,
      elapsedText: document.querySelector('#result-elapsed').textContent,
      healText: document.querySelector('#heal-count').textContent,
      stageTimeline: [...document.querySelectorAll('#stage-list [data-stage]')].map((item) => ({
        stage: item.dataset.stage,
        elapsedMs: Number(item.dataset.elapsedMs),
      })),
    };
  })()`);
  await capture(`${evidencePrefix}-result-mobile-390x844.png`);
  await setViewport(1440, 900, false);
  await delay(300);
  await capture(`${evidencePrefix}-result-desktop-1440x900.png`);

  const evidence = {
    schemaVersion: "1.0",
    journeyKind: "public-question-on-running-service",
    question: liveQuestion,
    liveJobCount: 1,
    publicEphemeral: true,
    answerObservedBeforeResult,
    answerLatencyMs,
    totalObservedMs,
    ...result,
    consoleErrors,
    screenshots: [
      `${evidencePrefix}-landing-mobile-390x844.png`,
      `${evidencePrefix}-build-mobile-390x844.png`,
      `${evidencePrefix}-result-mobile-390x844.png`,
      `${evidencePrefix}-result-desktop-1440x900.png`,
    ],
  };
  fs.writeFileSync(
    path.join(screenshotDirectory, "..", `${evidencePrefix}.json`),
    `${JSON.stringify(evidence, null, 2)}\n`,
  );
  process.stdout.write(JSON.stringify(evidence));
} catch (error) {
  fs.writeFileSync(
    path.join(screenshotDirectory, "..", `${evidencePrefix}-failure.json`),
    `${JSON.stringify({
      schemaVersion: "1.0",
      journeyKind: "public-question-on-running-service",
      question: liveQuestion,
      error: error.message,
    }, null, 2)}\n`,
  );
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
} finally {
  if (socket) socket.close();
  chrome.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => chrome.once("exit", resolve)),
    delay(2000),
  ]);
  fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 2 });
}
