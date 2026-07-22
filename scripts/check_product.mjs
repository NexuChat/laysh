import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const baseUrl = process.argv[2];
const screenshotDirectory = path.resolve(process.argv[3]);
const evidencePrefix = process.argv[4] || "g4";
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-product-chrome-"));
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
  const networkFailures = [];
  let expectedNetworkFailure = false;
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
    if (
      message.method === "Log.entryAdded"
      && message.params.entry.level === "error"
      && !expectedNetworkFailure
    ) {
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
    if (response.exceptionDetails) {
      throw new Error(response.exceptionDetails.text || "evaluation failed");
    }
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

  async function setViewport(width, height, mobile = false) {
    await command("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile,
      screenWidth: width,
      screenHeight: height,
    });
  }

  async function navigate(url = `${baseUrl}/`) {
    await command("Page.navigate", { url });
    await waitFor("document.readyState === 'complete'", 10000);
  }

  async function submit(question) {
    return await evaluate(`(() => {
      const field = document.querySelector('#question');
      field.value = ${JSON.stringify(question)};
      document.querySelector('#ask-form').requestSubmit();
      return {
        buildVisible: !document.querySelector('#build-view').hidden,
        queued: document.querySelector('#connection-copy').textContent.includes('في قائمة البناء'),
      };
    })()`);
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
  await command("Accessibility.enable");

  await setViewport(390, 844, true);
  await navigate();
  await evaluate("document.querySelector('#locale-control').click()");
  await waitFor("document.documentElement.lang === 'ar'");
  await capture(`${evidencePrefix}-landing-mobile-390x844.png`);
  await waitFor("!document.querySelector('[data-golden-id=\"moon_phases\"] .golden-launch').disabled", 5000);
  await evaluate("document.querySelector('[data-golden-id=\"moon_phases\"] .golden-launch').click()");
  await waitFor("!document.querySelector('#result-view').hidden", 5000);
  await waitFor("document.querySelector('#simulation-frame').src.includes('/api/sims/')", 5000);
  await delay(300);
  await capture(`${evidencePrefix}-golden-mobile-390x844.png`);
  await navigate();
  const initialSubmit = await submit("success");
  await waitFor("!document.querySelector('#build-view').hidden", 3000);
  await delay(120);
  await capture(`${evidencePrefix}-build-mobile-390x844.png`);
  await waitFor("!document.querySelector('#result-view').hidden", 20000);
  await waitFor("document.querySelector('#simulation-frame').src.includes('/api/sims/')", 5000);
  await delay(500);
  const success = await evaluate(`(() => {
    const arabicDigits = '٠١٢٣٤٥٦٧٨٩';
    const toNumber = (value) => Number([...value].map((character) => {
      const index = arabicDigits.indexOf(character);
      return index >= 0 ? String(index) : character;
    }).join('').replace(/[^0-9.]/g, ''));
    return {
      answerPinned: Boolean(document.querySelector('#result-answer').textContent.trim()),
      resultVisible: !document.querySelector('#result-view').hidden,
      sandbox: document.querySelector('#simulation-frame').getAttribute('sandbox'),
      receiptChecks: toNumber(document.querySelector('#check-count').textContent),
    };
  })()`);
  await capture(`${evidencePrefix}-result-mobile-390x844.png`);
  await setViewport(1440, 900, false);
  await delay(300);
  await capture(`${evidencePrefix}-result-desktop-1440x900.png`);

  await navigate();
  await capture(`${evidencePrefix}-landing-desktop-1440x900.png`);
  await waitFor("!document.querySelector('[data-golden-id=\"moon_phases\"] .golden-launch').disabled", 5000);
  await evaluate("document.querySelector('[data-golden-id=\"moon_phases\"] .golden-launch').click()");
  await waitFor("!document.querySelector('#result-view').hidden", 5000);
  await waitFor("document.querySelector('#simulation-frame').src.includes('/api/sims/')", 5000);
  await delay(300);
  await capture(`${evidencePrefix}-golden-desktop-1440x900.png`);
  await navigate();
  await submit("success");
  await waitFor("!document.querySelector('#build-view').hidden", 3000);
  await delay(120);
  await capture(`${evidencePrefix}-build-desktop-1440x900.png`);
  await waitFor("!document.querySelector('#result-view').hidden", 20000);

  await evaluate("history.back()");
  await waitFor("!document.querySelector('#build-view').hidden", 3000);
  const historyBack = await evaluate("!document.querySelector('#build-view').hidden");
  await evaluate("history.forward()");
  await waitFor("!document.querySelector('#result-view').hidden", 3000);
  await evaluate(`window.dispatchEvent(new MessageEvent('message', {
    data: { source: 'laysh-artifact', type: 'runtime-error', code: 'SIM_RUNTIME_ERROR' },
    origin: 'null',
    source: document.querySelector('#simulation-frame').contentWindow,
  }))`);
  await waitFor("!document.querySelector('#failure-view').hidden", 3000);
  const runtimeError = await evaluate("document.querySelector('#failure-title').textContent.includes('خطأ داخل المحاكاة')");

  await navigate();
  await submit("not simulatable");
  await waitFor("!document.querySelector('#failure-view').hidden", 5000);
  const answerOnly = await evaluate("document.querySelector('#failure-title').textContent.includes('احتفظنا بالجواب') && !document.querySelector('#preserved-answer').hidden");

  await navigate();
  await submit("unsafe PRIVATE-CANARY-G4");
  await waitFor("!document.querySelector('#failure-view').hidden", 5000);
  const unsafeRedirect = await evaluate("document.querySelector('#failure-title').textContent.includes('لا يمكننا متابعة') && !document.body.innerText.includes('PRIVATE-CANARY-G4')");

  await navigate();
  await submit("exhausted heal");
  await waitFor("!document.querySelector('#failure-view').hidden", 8000);
  const generationFailed = await evaluate("document.querySelector('#failure-copy').textContent.includes('لم تجتز المحاكاة')");

  await navigate();
  expectedNetworkFailure = true;
  await command("Network.emulateNetworkConditions", {
    offline: true,
    latency: 0,
    downloadThroughput: -1,
    uploadThroughput: -1,
  });
  await submit("success");
  await waitFor("!document.querySelector('#failure-view').hidden", 5000);
  const backendDown = await evaluate("document.querySelector('#failure-title').textContent.includes('تعذّر الاتصال بالخادم')");
  await command("Network.emulateNetworkConditions", {
    offline: false,
    latency: 0,
    downloadThroughput: -1,
    uploadThroughput: -1,
  });
  await delay(200);
  expectedNetworkFailure = false;

  await navigate();
  const timeoutSubmit = await submit("timeout");
  await waitFor("document.querySelector('#connection-copy').textContent.includes('الاتصال مستقر')", 5000);
  await evaluate("window.__layshOriginalDateNow = Date.now; const base = Date.now(); Date.now = () => base + 91_000");
  await waitFor("document.querySelector('#connection-copy').textContent.includes('ما زلنا نفحص')", 2500);
  const stillTesting = await evaluate("document.querySelector('#connection-copy').textContent.includes('ما زلنا نفحص')");
  await evaluate("Date.now = window.__layshOriginalDateNow");
  await evaluate("window.dispatchEvent(new Event('offline'))");
  await waitFor("document.querySelector('#connection-copy').textContent.includes('إعادة الاتصال')", 12000);
  const reconnecting = await evaluate("document.querySelector('#connection-copy').textContent.includes('إعادة الاتصال')");
  await evaluate("window.dispatchEvent(new Event('online'))");
  await evaluate("document.querySelector('#cancel-action').click()");
  await waitFor("!document.querySelector('#failure-view').hidden", 5000);
  const cancelled = await evaluate("document.querySelector('#failure-title').textContent.includes('توقفنا بهدوء')");

  await command("Emulation.setEmulatedMedia", {
    media: "screen",
    features: [{ name: "prefers-reduced-motion", value: "reduce" }],
  });
  await setViewport(320, 844, true);
  await navigate();
  await evaluate("document.querySelector('.brand').focus()");
  const keyboardSequence = [];
  for (let index = 0; index < 3; index += 1) {
    await command("Input.dispatchKeyEvent", {
      type: "rawKeyDown",
      key: "Tab",
      code: "Tab",
      windowsVirtualKeyCode: 9,
    });
    await command("Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "Tab",
      code: "Tab",
      windowsVirtualKeyCode: 9,
    });
    keyboardSequence.push(await evaluate("document.activeElement.id"));
  }
  const accessibilityDom = await evaluate(`(() => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    const ids = [...document.querySelectorAll('[id]')].map((element) => element.id);
    const duplicateIds = [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
    const smallTargets = [...document.querySelectorAll('button, a, textarea, summary')]
      .filter(visible)
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width < 24 || rect.height < 24;
      })
      .map((element) => element.id || element.textContent.trim().slice(0, 30));
    const strayEnglish = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const parent = node.parentElement;
      if (!parent || !visible(parent) || parent.closest('script, style, bdi[dir="ltr"]')) continue;
      const words = node.textContent.match(/[A-Za-z]{2,}/g) || [];
      strayEnglish.push(...words);
    }
    const focusStyle = getComputedStyle(document.activeElement);
    return {
      duplicateIds,
      smallTargets,
      strayEnglish,
      focusVisible: focusStyle.outlineStyle !== 'none' && parseFloat(focusStyle.outlineWidth) >= 2,
      overflow320: document.documentElement.scrollWidth > window.innerWidth,
      reducedMotion: parseFloat(getComputedStyle(document.querySelector('.pulse')).animationDuration) <= 0.001,
    };
  })()`);
  const accessibilityTree = await command("Accessibility.getFullAXTree");
  const interactiveRoles = new Set(["button", "link", "textbox", "checkbox", "radio", "slider", "combobox"]);
  const unnamedInteractiveNodes = accessibilityTree.nodes.filter((node) => (
    interactiveRoles.has(node.role?.value)
    && !node.ignored
    && !(node.name?.value || "").trim()
  )).length;

  await command("Emulation.setEmulatedMedia", { media: "screen", features: [] });
  await setViewport(720, 450, false);
  await navigate();
  await command("Emulation.setPageScaleFactor", { pageScaleFactor: 2 });
  const overflowAt200Percent = await evaluate("document.documentElement.scrollWidth > window.innerWidth");
  await command("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });

  const evidence = {
    schemaVersion: "1.0",
    success,
    failures: {
      answerOnly,
      unsafeRedirect,
      generationFailed,
      runtimeError,
      backendDown,
      cancelled,
    },
    buildStates: {
      queued: initialSubmit.queued && timeoutSubmit.queued,
      reconnecting,
      stillTesting,
    },
    historyBack,
    accessibility: {
      unnamedInteractiveNodes,
      duplicateIds: accessibilityDom.duplicateIds,
      focusVisible: accessibilityDom.focusVisible,
      keyboardSequence,
      smallTargets: accessibilityDom.smallTargets,
      strayEnglish: accessibilityDom.strayEnglish,
    },
    responsive: {
      overflow320: accessibilityDom.overflow320,
      overflowAt200Percent,
      reducedMotion: accessibilityDom.reducedMotion,
    },
    consoleErrors,
    networkFailures,
    screenshots: [
      `${evidencePrefix}-landing-mobile-390x844.png`,
      `${evidencePrefix}-golden-mobile-390x844.png`,
      `${evidencePrefix}-build-mobile-390x844.png`,
      `${evidencePrefix}-result-mobile-390x844.png`,
      `${evidencePrefix}-landing-desktop-1440x900.png`,
      `${evidencePrefix}-golden-desktop-1440x900.png`,
      `${evidencePrefix}-build-desktop-1440x900.png`,
      `${evidencePrefix}-result-desktop-1440x900.png`,
    ],
  };
  fs.writeFileSync(
    path.join(screenshotDirectory, "..", `${evidencePrefix}-browser.json`),
    `${JSON.stringify(evidence, null, 2)}\n`,
  );
  process.stdout.write(JSON.stringify(evidence));
} catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
} finally {
  if (socket) socket.close();
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
