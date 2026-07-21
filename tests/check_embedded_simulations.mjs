import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const baseUrl = process.argv[2];
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-embed-chrome-"));

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
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const callbacks = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) callbacks.reject(new Error(message.error.message));
      else callbacks.resolve(message.result);
      return;
    }
  });

  function command(method, params = {}, sessionId) {
    const id = nextId;
    nextId += 1;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params, sessionId }));
    });
  }

  async function evaluate(expression, sessionId) {
    const response = await command("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    }, sessionId);
    if (response.exceptionDetails) {
      throw new Error(response.exceptionDetails.text || "evaluation failed");
    }
    return response.result.value;
  }

  async function waitFor(expression, timeout = 10000, sessionId) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await evaluate(expression, sessionId)) return;
      await delay(80);
    }
    throw new Error(`Timed out waiting for: ${expression}`);
  }

  async function setViewport(viewport) {
    await command("Emulation.setDeviceMetricsOverride", {
      width: viewport.width,
      height: viewport.height,
      deviceScaleFactor: 1,
      mobile: viewport.mobile,
      screenWidth: viewport.width,
      screenHeight: viewport.height,
    });
    await command("Emulation.setPageScaleFactor", {
      pageScaleFactor: viewport.scale,
    });
  }

  async function navigate() {
    await command("Page.navigate", { url: `${baseUrl}/` });
    await waitFor("document.readyState === 'complete'");
    await waitFor(`(() => {
      const cards = [...document.querySelectorAll('[data-golden-id]')];
      return cards.length > 0 && cards.every((card) => !card.querySelector('.golden-launch').disabled);
    })()`);
  }

  async function currentFrameSession(expectedUrl, expectedTitle) {
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      const { targetInfos } = await command("Target.getTargets");
      const frame = targetInfos.filter(
        (target) => target.type === "iframe" && target.url === expectedUrl,
      ).at(-1);
      if (frame) {
        const { sessionId } = await command("Target.attachToTarget", {
          targetId: frame.targetId,
          flatten: true,
        });
        await command("Runtime.enable", {}, sessionId);
        const ready = await evaluate(`document.readyState === 'complete'
          && document.querySelector('#lesson-title')?.textContent === ${JSON.stringify(expectedTitle)}`,
        sessionId);
        if (ready) return { frame, sessionId };
        await command("Target.detachFromTarget", { sessionId });
      }
      await delay(80);
    }
    throw new Error("embedded simulation context did not become ready");
  }

  async function measureLoaded(cardId, viewport) {
    const expectedUrl = await evaluate("document.querySelector('#simulation-frame').src");
    const expectedTitle = await evaluate("document.querySelector('#result-title').textContent");
    const { sessionId } = await currentFrameSession(expectedUrl, expectedTitle);
    await waitFor("document.documentElement.dataset.layshReady === 'true'", 10000, sessionId);
    try {
      await waitFor("document.querySelector('#simulation-frame').getBoundingClientRect().height > 150");
    } catch (error) {
      throw new Error(`${cardId} at ${viewport.label}: ${error.message}`);
    }
    const convergenceDeadline = Date.now() + 5000;
    while (Date.now() < convergenceDeadline) {
      const frameHeight = await evaluate(
        "document.querySelector('#simulation-frame').getBoundingClientRect().height",
      );
      const lessonBottom = await evaluate(
        "Math.ceil(document.querySelector('#lesson').getBoundingClientRect().bottom)",
        sessionId,
      );
      if (frameHeight + 2 >= lessonBottom) break;
      await delay(100);
    }
    await delay(100);

    const parent = await evaluate(`(() => {
      const frame = document.querySelector('#simulation-frame');
      const stage = document.querySelector('.simulation-stage');
      const frameRect = frame.getBoundingClientRect();
      const stageRect = stage.getBoundingClientRect();
      return {
        iframeHeight: frameRect.height,
        computedHeight: getComputedStyle(frame).height,
        computedMinHeight: getComputedStyle(frame).minHeight,
        iframeBottomInsideStage: frameRect.bottom <= stageRect.bottom + 1,
        stageOverflow: getComputedStyle(stage).overflow,
        scrolling: frame.getAttribute('scrolling'),
      };
    })()`);
    const child = await evaluate(`(() => {
      const bounds = (selector) => {
        const element = document.querySelector(selector);
        if (!element) return { exists: false, visible: false, insideViewport: false };
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return {
          exists: true,
          visible: style.display !== 'none' && style.visibility !== 'hidden'
            && rect.width > 0 && rect.height > 0,
          insideViewport: rect.top >= -1 && rect.left >= -1
            && rect.bottom <= innerHeight + 1 && rect.right <= innerWidth + 1,
          top: Math.round(rect.top),
          bottom: Math.round(rect.bottom),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          height: Math.round(rect.height),
        };
      };
      const root = document.documentElement;
      const body = document.body;
      const documentHeight = Math.ceil(Math.max(
        root.scrollHeight, root.offsetHeight, body.scrollHeight, body.offsetHeight,
      ));
      return {
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
        documentHeight,
        lesson: bounds('#lesson'),
        panel: bounds('#observe'),
        canvas: bounds('#simulation'),
        control: bounds('#primary-control'),
      };
    })()`, sessionId);
    await command("Target.detachFromTarget", { sessionId });
    const passed = parent.iframeBottomInsideStage
      && child.panel.visible && child.panel.insideViewport
      && child.canvas.visible && child.canvas.insideViewport
      && child.control.visible && child.control.insideViewport;
    return { cardId, viewport: viewport.label, scale: viewport.scale, parent, child, passed };
  }

  async function measure(cardId, viewport) {
    const previousUrl = await evaluate("document.querySelector('#simulation-frame').src");
    await evaluate(`document.querySelector(${JSON.stringify(
      `[data-golden-id="${cardId}"] .golden-launch`,
    )}).click()`);
    await waitFor("!document.querySelector('#result-view').hidden");
    await waitFor(`document.querySelector('#simulation-frame').src.includes('/api/sims/')
      && document.querySelector('#simulation-frame').src !== ${JSON.stringify(previousUrl)}`);
    return measureLoaded(cardId, viewport);
  }

  await command("Runtime.enable");
  await command("Page.enable");
  const viewports = [
    { label: "narrow-mobile-320x844", width: 320, height: 844, mobile: true, scale: 1 },
    { label: "modern-mobile-390x844", width: 390, height: 844, mobile: true, scale: 1 },
    { label: "desktop-1440x900", width: 1440, height: 900, mobile: false, scale: 1 },
    { label: "zoom-200pct", width: 720, height: 900, mobile: false, scale: 2 },
  ];
  const measurements = [];
  for (const viewport of viewports) {
    await setViewport(viewport);
    await navigate();
    const cardIds = await evaluate(
      "[...document.querySelectorAll('[data-golden-id]')].map((card) => card.dataset.goldenId)",
    );
    for (const cardId of cardIds) {
      await navigate();
      measurements.push(await measure(cardId, viewport));
    }
  }

  const resizeStart = viewports[2];
  const resizeEnd = viewports[0];
  await setViewport(resizeStart);
  await navigate();
  const resizeCardId = await evaluate(
    "document.querySelector('[data-golden-id]').dataset.goldenId",
  );
  const resizeBefore = await measure(resizeCardId, resizeStart);
  await setViewport(resizeEnd);
  const resizeAfter = await measureLoaded(resizeCardId, {
    ...resizeEnd,
    label: "live-resize-desktop-to-320",
  });

  process.stdout.write(JSON.stringify({ measurements, resizeMeasurements: [resizeBefore, resizeAfter] }));
} catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
} finally {
  if (socket) socket.close();
  chrome.kill("SIGTERM");
  await Promise.race([new Promise((resolve) => chrome.once("exit", resolve)), delay(2000)]);
  fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 2 });
}
