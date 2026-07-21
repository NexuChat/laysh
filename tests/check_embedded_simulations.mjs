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

  async function currentIframeTargetId() {
    const { root } = await command("DOM.getDocument", { depth: 1 });
    const { nodeId } = await command("DOM.querySelector", {
      nodeId: root.nodeId,
      selector: "#simulation-frame",
    });
    if (!nodeId) return null;
    const { node } = await command("DOM.describeNode", { nodeId });
    return node.frameId || null;
  }

  async function currentFrameSession(expectedUrl, expectedTitle) {
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      const targetId = await currentIframeTargetId();
      const { targetInfos } = await command("Target.getTargets");
      const frame = targetInfos.find(
        (target) => target.type === "iframe"
          && target.targetId === targetId
          && target.url === expectedUrl,
      );
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
    let converged = false;
    while (Date.now() < convergenceDeadline) {
      const frameBounds = await evaluate(`(() => {
        const rect = document.querySelector('#simulation-frame').getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      })()`);
      const childLayout = await evaluate(`(() => ({
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
        lessonBottom: Math.ceil(document.querySelector('#lesson').getBoundingClientRect().bottom),
      }))()`, sessionId);
      if (
        Math.abs(frameBounds.width - childLayout.viewportWidth) <= 2
        && frameBounds.height + 2 >= childLayout.lessonBottom
        && childLayout.viewportHeight + 2 >= childLayout.lessonBottom
      ) {
        converged = true;
        break;
      }
      await delay(100);
    }
    if (!converged) {
      throw new Error(`${cardId} at ${viewport.label}: embedded viewport did not converge`);
    }

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
    const childFocus = await evaluate(`(() => {
      const viewport = window.visualViewport || { width: innerWidth, height: innerHeight };
      return ['#primary-control', '#reset', '#replay', '#projector'].map((selector) => {
        const element = document.querySelector(selector);
        element.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
        element.focus();
        const rect = element.getBoundingClientRect();
        const top = document.elementFromPoint(
          Math.min(viewport.width - 1, Math.max(0, rect.left + rect.width / 2)),
          Math.min(viewport.height - 1, Math.max(0, rect.top + rect.height / 2)),
        );
        return {
          selector,
          focused: document.activeElement === element,
          visible: rect.width > 0 && rect.height > 0
            && rect.top >= 0 && rect.left >= 0
            && rect.bottom <= viewport.height && rect.right <= viewport.width,
          unobscured: top === element || element.contains(top),
        };
      });
    })()`, sessionId);
    const parentFocus = await evaluate(`(() => {
      const viewport = window.visualViewport || { width: innerWidth, height: innerHeight };
      return ['#replay-result', '#download', '#ask-another'].map((selector) => {
        const element = document.querySelector(selector);
        element.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
        element.focus();
        const rect = element.getBoundingClientRect();
        const top = document.elementFromPoint(
          Math.min(viewport.width - 1, Math.max(0, rect.left + rect.width / 2)),
          Math.min(viewport.height - 1, Math.max(0, rect.top + rect.height / 2)),
        );
        return {
          selector,
          focused: document.activeElement === element,
          visible: rect.width > 0 && rect.height > 0
            && rect.top >= 0 && rect.left >= 0
            && rect.bottom <= viewport.height && rect.right <= viewport.width,
          unobscured: top === element || element.contains(top),
        };
      });
    })()`);
    async function tabTo(selectors, sessionId) {
      await evaluate(`document.querySelector(${JSON.stringify(selectors[0])}).focus()`, sessionId);
      const results = [];
      for (const selector of selectors.slice(1)) {
        await command("Input.dispatchKeyEvent", {
          type: "keyDown",
          key: "Tab",
          code: "Tab",
          windowsVirtualKeyCode: 9,
          nativeVirtualKeyCode: 9,
        }, sessionId);
        await command("Input.dispatchKeyEvent", {
          type: "keyUp",
          key: "Tab",
          code: "Tab",
          windowsVirtualKeyCode: 9,
          nativeVirtualKeyCode: 9,
        }, sessionId);
        results.push(await evaluate(`(() => {
          const element = document.querySelector(${JSON.stringify(selector)});
          const viewport = window.visualViewport || { width: innerWidth, height: innerHeight };
          const rect = element.getBoundingClientRect();
          const top = document.elementFromPoint(
            Math.min(viewport.width - 1, Math.max(0, rect.left + rect.width / 2)),
            Math.min(viewport.height - 1, Math.max(0, rect.top + rect.height / 2)),
          );
          return {
            selector: ${JSON.stringify(selector)},
            focused: document.activeElement === element,
            visible: rect.width > 0 && rect.height > 0
              && rect.top >= 0 && rect.left >= 0
              && rect.bottom <= viewport.height && rect.right <= viewport.width,
            unobscured: top === element || element.contains(top),
          };
        })()`, sessionId));
      }
      return results;
    }
    const childKeyboard = await tabTo(['#primary-control', '#reset', '#replay'], sessionId);
    const parentKeyboard = await tabTo(['#replay-result', '#download', '#ask-another']);
    await command("Target.detachFromTarget", { sessionId });
    const checks = {
      iframeInsideStage: parent.iframeBottomInsideStage,
      panelVisible: child.panel.visible,
      panelInsideViewport: child.panel.insideViewport,
      canvasVisible: child.canvas.visible,
      canvasInsideViewport: child.canvas.insideViewport,
      controlVisible: child.control.visible,
      controlInsideViewport: child.control.insideViewport,
      keyboardFocus: [...childFocus, ...parentFocus, ...childKeyboard, ...parentKeyboard].every(
        (item) => item.focused && item.visible && item.unobscured,
      ),
    };
    const passed = Object.values(checks).every(Boolean);
    return {
      cardId,
      viewport: viewport.label,
      scale: viewport.scale,
      parent,
      child,
      childFocus,
      parentFocus,
      childKeyboard,
      parentKeyboard,
      checks,
      passed,
    };
  }

  async function measure(cardId, viewport) {
    const previousUrl = await evaluate("document.querySelector('#simulation-frame').src");
    await evaluate(`(() => {
      const frame = document.querySelector('#simulation-frame');
      window.__layshFrameHeightWrites = [];
      new MutationObserver(() => {
        window.__layshFrameHeightWrites.push(frame.style.height);
      }).observe(frame, { attributes: true, attributeFilter: ['style'] });
    })()`);
    await evaluate(`document.querySelector(${JSON.stringify(
      `[data-golden-id="${cardId}"] .golden-launch`,
    )}).click()`);
    await waitFor("!document.querySelector('#result-view').hidden");
    await waitFor(`document.querySelector('#simulation-frame').src.includes('/api/sims/')
      && document.querySelector('#simulation-frame').src !== ${JSON.stringify(previousUrl)}`);
    const initialHeightWrites = await evaluate("window.__layshFrameHeightWrites");
    return { ...await measureLoaded(cardId, viewport), initialHeightWrites };
  }

  const fakeClockSource = `(() => {
    const callbacks = new Map();
    let nextId = 1;
    let now = 0;
    let executed = 0;
    window.__layshTestClock = {
      snapshot: () => ({ now, queued: callbacks.size, executed }),
      advance: (milliseconds) => {
        now += milliseconds;
        const ready = [...callbacks.values()];
        callbacks.clear();
        for (const callback of ready) {
          executed += 1;
          callback(now);
        }
      },
    };
    window.requestAnimationFrame = (callback) => {
      const id = nextId;
      nextId += 1;
      callbacks.set(id, callback);
      return id;
    };
    window.cancelAnimationFrame = (id) => callbacks.delete(id);
  })();`;

  async function measureClock(slug) {
    const detail = await fetchJson(`${baseUrl}/api/gallery/${slug}?locale=ar`);
    if (detail.simulation.effective_model !== "verified/golden") {
      throw new Error(`${slug}: expected a deterministic pinned artifact`);
    }
    const script = await command("Page.addScriptToEvaluateOnNewDocument", { source: fakeClockSource });
    try {
      await command("Page.navigate", { url: `${baseUrl}${detail.simulation.artifact_url}?inline=1` });
      await waitFor("document.documentElement?.dataset.layshReady === 'true'");
      const before = await evaluate(`(() => ({
        clock: window.__layshTestClock.snapshot(),
        value: document.querySelector('#primary-control').value,
      }))()`);
      const afterParameter = await evaluate(`(() => {
        const control = document.querySelector('#primary-control');
        const next = Number(control.value) === Number(control.max)
          ? Number(control.min)
          : Number(control.value) + Number(control.step);
        control.value = String(next);
        control.dispatchEvent(new Event('input', { bubbles: true }));
        return { clock: window.__layshTestClock.snapshot(), value: control.value };
      })()`);
      const afterClock = await evaluate(`(() => {
        const control = document.querySelector('#primary-control');
        window.__layshTestClock.advance(96);
        return { clock: window.__layshTestClock.snapshot(), value: control.value };
      })()`);
      return { slug, before, afterParameter, afterClock };
    } finally {
      await command("Page.removeScriptToEvaluateOnNewDocument", {
        identifier: script.identifier,
      });
    }
  }

  await command("Runtime.enable");
  await command("DOM.enable");
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

  const clocks = [];
  for (const slug of ["pendulum", "sound_pitch"]) clocks.push(await measureClock(slug));

  process.stdout.write(JSON.stringify({
    measurements,
    resizeMeasurements: [resizeBefore, resizeAfter],
    clocks,
  }));
} catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
} finally {
  if (socket) socket.close();
  chrome.kill("SIGTERM");
  await Promise.race([new Promise((resolve) => chrome.once("exit", resolve)), delay(2000)]);
  fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 2 });
}
