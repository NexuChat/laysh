import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactRoot = path.resolve(process.argv[2]);
const screenshotRoot = path.resolve(process.argv[3]);
const outputPath = path.resolve(process.argv[4]);
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-gold-01-chrome-"));
const defaultGoldenIds = [
  "buoyancy",
  "day_night",
  "moon_phases",
  "pendulum",
  "simple_circuit",
  "sound_pitch",
];
const goldenIds = process.env.LAYSH_GOLD_IDS
  ? process.env.LAYSH_GOLD_IDS.split(",").filter(Boolean)
  : defaultGoldenIds;
const locales = process.env.LAYSH_GOLD_LOCALES
  ? process.env.LAYSH_GOLD_LOCALES.split(",").filter(Boolean)
  : ["ar", "en"];
fs.mkdirSync(screenshotRoot, { recursive: true });
fs.mkdirSync(path.dirname(outputPath), { recursive: true });

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

function evidencePath(filename) {
  const absolute = path.join(screenshotRoot, filename);
  const relative = path.relative(process.cwd(), absolute);
  return relative.startsWith("..") ? filename : relative;
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
  const externalRequests = [];
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const callbacks = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) callbacks.reject(new Error(message.error.message));
      else callbacks.resolve(message.result);
      return;
    }
    if (message.method === "Runtime.exceptionThrown") {
      consoleErrors.push(message.params.exceptionDetails.text || "runtime exception");
    }
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
      consoleErrors.push("console.error");
    }
    if (message.method === "Network.requestWillBeSent") {
      const requestUrl = message.params.request.url;
      if (
        !requestUrl.startsWith("file:")
        && !requestUrl.startsWith("data:")
        && !requestUrl.startsWith("blob:")
        && requestUrl !== "about:blank"
      ) {
        externalRequests.push(requestUrl.split("?")[0]);
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

  async function waitFor(expression, timeout = 10000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return;
      await delay(50);
    }
    throw new Error(`Timed out waiting for: ${expression}`);
  }

  async function setViewport(width, height, deviceScaleFactor = 1, mobile = false) {
    await command("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor,
      mobile,
      screenWidth: width,
      screenHeight: height,
    });
  }

  async function navigate(url) {
    await command("Page.navigate", { url });
    await waitFor("document.readyState === 'complete'");
    await waitFor("document.documentElement.dataset.layshReady === 'true'");
  }

  async function capture(filename) {
    const screenshot = await command("Page.captureScreenshot", {
      format: "png",
      fromSurface: true,
      captureBeyondViewport: false,
    });
    fs.writeFileSync(
      path.join(screenshotRoot, filename),
      Buffer.from(screenshot.data, "base64"),
    );
  }

  async function visualState() {
    return await evaluate(`(() => {
      const canvas = document.querySelector('#simulation');
      const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      const stride = Math.max(4, Math.floor(data.length / 4096 / 4) * 4);
      let hash = 2166136261;
      for (let index = 0; index < data.length; index += stride) {
        hash = Math.imul(hash ^ data[index], 16777619) >>> 0;
      }
      return {
        frameCount: Number(document.documentElement.dataset.frameCount || 0),
        canvasHash: hash,
        playbackState: document.documentElement.dataset.playbackState,
        playbackReason: document.documentElement.dataset.playbackReason,
      };
    })()`);
  }

  async function responsiveCase(name, width, height, dpr = 1, mobile = false) {
    await setViewport(width, height, dpr, mobile);
    await delay(100);
    const metrics = await evaluate(`(() => {
      const selectors = ['#simulation', '#primary-control', '#play-pause', '#reset'];
      const elements = Object.fromEntries(selectors.map((selector) => {
        const element = document.querySelector(selector);
        element.scrollIntoView({ block: 'center', inline: 'nearest' });
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return [selector, {
          visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0,
          horizontallyClipped: rect.left < -1 || rect.right > window.innerWidth + 1,
        }];
      }));
      return {
        viewport: {
          width: window.innerWidth,
          height: window.innerHeight,
          dpr: window.devicePixelRatio,
          documentClientWidth: document.documentElement.clientWidth,
          documentScrollWidth: document.documentElement.scrollWidth,
        },
        elements,
        horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        overflowSources: [...document.querySelectorAll('body *')]
          .map((element) => {
            const rect = element.getBoundingClientRect();
            return {
              tag: element.tagName.toLowerCase(),
              id: element.id,
              className: typeof element.className === 'string' ? element.className : '',
              left: Math.round(rect.left * 10) / 10,
              right: Math.round(rect.right * 10) / 10,
              scrollWidth: element.scrollWidth,
              clientWidth: element.clientWidth,
            };
          })
          .filter((item) => item.left < -1 || item.right > document.documentElement.clientWidth + 1 || item.scrollWidth > item.clientWidth + 1)
          .slice(0, 12),
      };
    })()`);
    return {
      name,
      passed: (
        !metrics.horizontalOverflow
        && Object.values(metrics.elements).every((item) => item.visible && !item.horizontallyClipped)
      ),
      ...metrics,
    };
  }

  await command("Runtime.enable");
  await command("Page.enable");
  await command("Network.enable");
  await command("Accessibility.enable");
  const journeys = [];

  for (const goldenId of goldenIds) {
    for (const locale of locales) {
      const artifactPath = path.join(artifactRoot, `${goldenId}-${locale}.html`);
      const artifactBytes = fs.readFileSync(artifactPath);
      const artifactSha256 = crypto.createHash("sha256").update(artifactBytes).digest("hex");
      const artifactUrl = pathToFileURL(artifactPath).href;
      const consoleStart = consoleErrors.length;
      const externalStart = externalRequests.length;
      await command("Emulation.setEmulatedMedia", { media: "screen", features: [] });
      await setViewport(390, 844, 1, true);
      await navigate(artifactUrl);

      const initial = await visualState();
      await delay(450);
      const autoplay = await visualState();
      await evaluate("document.querySelector('#play-pause').click()");
      await delay(100);
      const pausedBefore = await visualState();
      await delay(450);
      const pausedAfter = await visualState();
      await evaluate("document.querySelector('#play-pause').click()");
      await delay(450);
      const resumed = await visualState();
      await evaluate("document.querySelector('#reset').click()");
      const resetBaselineVisual = await visualState();
      const resetBaseline = await evaluate(`(() => {
        const control = document.querySelector('#primary-control');
        return {
          value: Number(control.value),
          expected: Number(window.__LAYSH_LESSON__.primary_parameter.default),
          alternative: document.querySelector('#state-description').textContent,
          playbackState: document.documentElement.dataset.playbackState,
        };
      })()`);
      const changed = await evaluate(`(() => {
        const control = document.querySelector('#primary-control');
        control.value = control.max;
        control.dispatchEvent(new Event('input', { bubbles: true }));
        return {
          value: Number(control.value),
          alternative: document.querySelector('#state-description').textContent,
        };
      })()`);
      const changedVisual = await visualState();
      await evaluate("document.querySelector('#reset').click()");
      const resetAfterVisual = await visualState();
      const resetAfter = await evaluate(`(() => {
        const control = document.querySelector('#primary-control');
        return {
          value: Number(control.value),
          alternative: document.querySelector('#state-description').textContent,
          playbackState: document.documentElement.dataset.playbackState,
        };
      })()`);
      await delay(250);
      const resetStableVisual = await visualState();
      const semantic = await evaluate(`(() => {
        const canvas = document.querySelector('#simulation');
        const rect = canvas.getBoundingClientRect();
        const buttons = [...document.querySelectorAll('#play-pause, #reset')];
        const ids = [...document.querySelectorAll('[id]')].map((element) => element.id);
        return {
          lang: document.documentElement.lang,
          dir: document.documentElement.dir,
          actorVisible: rect.width > 0 && rect.height > 0 && getComputedStyle(canvas).visibility !== 'hidden',
          primaryControlReachable: document.querySelector('#primary-control').offsetParent !== null,
          stateAlternativePresent: Boolean(document.querySelector('#state-description').textContent.trim()),
          keyboardControlsNamed: buttons.every((button) => button.textContent.trim())
            && Boolean(document.querySelector('label[for="primary-control"]').textContent.trim()),
          duplicateIds: [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))],
        };
      })()`);
      const accessibilityTree = await command("Accessibility.getFullAXTree");
      const interactiveRoles = new Set(["button", "slider", "link", "textbox", "radio"]);
      const unnamedInteractiveNodes = accessibilityTree.nodes.filter((node) => (
        interactiveRoles.has(node.role?.value)
        && !node.ignored
        && !(node.name?.value || "").trim()
      )).length;

      const responsive = [];
      responsive.push(await responsiveCase("mobile-320x844", 320, 844, 1, true));
      responsive.push(await responsiveCase("mobile-390x844", 390, 844, 1, true));
      const mobileScreenshot = `${goldenId}-${locale}-mobile-390x844.png`;
      await capture(mobileScreenshot);
      responsive.push(await responsiveCase("desktop-1440x900", 1440, 900, 1, false));
      const desktopScreenshot = `${goldenId}-${locale}-desktop-1440x900.png`;
      await capture(desktopScreenshot);
      responsive.push(await responsiveCase("zoom-200", 720, 450, 2, false));

      await command("Emulation.setEmulatedMedia", {
        media: "screen",
        features: [{ name: "prefers-reduced-motion", value: "reduce" }],
      });
      await navigate(`${artifactUrl}?reduced=${goldenId}-${locale}`);
      const reducedBefore = await visualState();
      await delay(450);
      const reducedAfter = await visualState();
      const reducedMotionStops = (
        reducedBefore.playbackState === "paused"
        && reducedBefore.playbackReason === "reduced-motion"
        && reducedAfter.frameCount === reducedBefore.frameCount
        && reducedAfter.canvasHash === reducedBefore.canvasHash
      );

      const checks = {
        actor_visible: semantic.actorVisible,
        primary_control_reachable: semantic.primaryControlReachable,
        pause_stops_motion: (
          pausedBefore.playbackState === "paused"
          && pausedAfter.frameCount === pausedBefore.frameCount
          && pausedAfter.canvasHash === pausedBefore.canvasHash
        ),
        resume_restarts_motion: (
          resumed.playbackState === "running"
          && resumed.frameCount > pausedAfter.frameCount
          && resumed.canvasHash !== pausedAfter.canvasHash
        ),
        reset_restores_default: (
          changed.value !== resetBaseline.expected
          && changedVisual.canvasHash !== resetBaselineVisual.canvasHash
          && changed.alternative !== resetBaseline.alternative
          && resetBaseline.value === resetBaseline.expected
          && resetAfter.value === resetBaseline.expected
          && resetAfter.alternative === resetBaseline.alternative
          && resetAfter.playbackState === "paused"
          && resetStableVisual.frameCount === resetAfterVisual.frameCount
          && resetStableVisual.canvasHash === resetAfterVisual.canvasHash
        ),
        reduced_motion_stops_automatic_motion: reducedMotionStops,
        state_alternative_present: semantic.stateAlternativePresent,
        keyboard_controls_named: semantic.keyboardControlsNamed,
        no_duplicate_ids: semantic.duplicateIds.length === 0,
        no_horizontal_clip: responsive.every((item) => item.passed),
      };
      const journeyConsoleErrors = consoleErrors.slice(consoleStart);
      const journeyExternalRequests = externalRequests.slice(externalStart);
      const a11y = {
        unnamed_interactive_nodes: unnamedInteractiveNodes,
        duplicate_ids: semantic.duplicateIds,
        state_alternative_present: semantic.stateAlternativePresent,
      };
      const screenshots = [evidencePath(mobileScreenshot), evidencePath(desktopScreenshot)];
      const passed = (
        semantic.lang === locale
        && semantic.dir === (locale === "ar" ? "rtl" : "ltr")
        && autoplay.frameCount > initial.frameCount
        && autoplay.canvasHash !== initial.canvasHash
        && Object.values(checks).every(Boolean)
        && responsive.every((item) => item.passed)
        && unnamedInteractiveNodes === 0
        && journeyConsoleErrors.length === 0
        && journeyExternalRequests.length === 0
      );
      journeys.push({
        golden_id: goldenId,
        locale,
        lang: semantic.lang,
        dir: semantic.dir,
        artifact_sha256: artifactSha256,
        passed,
        checks,
        responsive,
        a11y,
        console_errors: journeyConsoleErrors,
        external_requests: journeyExternalRequests.length,
        screenshots,
        timing_evidence: {
          autoplay_frame_delta: autoplay.frameCount - initial.frameCount,
          pause_frame_delta: pausedAfter.frameCount - pausedBefore.frameCount,
          resume_frame_delta: resumed.frameCount - pausedAfter.frameCount,
          reduced_motion_frame_delta: reducedAfter.frameCount - reducedBefore.frameCount,
        },
      });
    }
  }

  const report = {
    schema_version: "1.0",
    gate: "golden_browser_review",
    model_calls: 0,
    passed: journeys.length === goldenIds.length * locales.length
      && journeys.every((item) => item.passed),
    journey_count: journeys.length,
    journeys,
  };
  fs.writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`);
  process.stdout.write(JSON.stringify({
    passed: report.passed,
    journey_count: report.journey_count,
    output: outputPath,
  }));
  if (!report.passed) process.exitCode = 1;
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
  fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 2 });
}
