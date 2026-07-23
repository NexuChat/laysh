import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const baseUrl = process.argv[2];
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-lab-chrome-"));

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return await response.json();
}

async function freePort() {
  const net = await import("node:net");
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
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
  const failedRequests = [];
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const callbacks = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) callbacks.reject(new Error(message.error.message));
      else callbacks.resolve(message.result);
      return;
    }
    if (
      message.method === "Runtime.consoleAPICalled"
      && message.params.type === "error"
    ) {
      consoleErrors.push(
        message.params.args.map((item) => item.value || item.description).join(" "),
      );
    }
    if (message.method === "Network.loadingFailed") {
      failedRequests.push(message.params.errorText);
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
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || "browser evaluation failed");
    }
    return result.result.value;
  }

  async function waitFor(expression, timeout = 15000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return;
      await delay(50);
    }
    throw new Error(`Timed out waiting for: ${expression}`);
  }

  async function setViewport(width, height) {
    await command("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: width < 600,
    });
    await delay(80);
    return await evaluate(`({
      width: innerWidth,
      overflow: document.documentElement.scrollWidth > innerWidth + 1,
    })`);
  }

  await command("Runtime.enable");
  await command("Network.enable");
  await command("Page.enable");
  await setViewport(1440, 900);
  await command("Page.navigate", { url: `${baseUrl}/model-lab` });
  await waitFor("document.readyState === 'complete' && Boolean(window.LayshLocale)");

  const initial = await evaluate(`(() => {
    const modelCards = [...document.querySelectorAll(".model-stage")];
    const first = modelCards[0];
    const model = first.querySelector('[name="model"]');
    const effort = first.querySelector('[name="effort"]');
    model.value = "gpt-5.6-luna";
    model.dispatchEvent(new Event("change", { bubbles: true }));
    const lunaUltraDisabled = effort.querySelector('[value="ultra"]').disabled;
    model.value = "gpt-5.6-terra";
    model.dispatchEvent(new Event("change", { bubbles: true }));
    return {
      stageCount: document.querySelectorAll("[data-stage]").length,
      modelStageCount: modelCards.length,
      modelOptions: model.querySelectorAll("option").length,
      effortOptions: effort.querySelectorAll("option").length,
      fastControls: document.querySelectorAll('[name="fast"]').length,
      rerunButtons: document.querySelectorAll('[data-action="rerun"]').length,
      outputPanels: document.querySelectorAll(".stage-output").length,
      defaultLanguage: document.documentElement.lang,
      defaultDirection: document.documentElement.dir,
      defaultSourceMode: document.getElementById("source-mode").value,
      defaultVisualMode: document.getElementById("visual-mode").value,
      bestPresetVisible: Boolean(document.getElementById("best-pipeline-preset")),
      cancelControlVisible: Boolean(document.getElementById("cancel-pipeline-button")),
      lunaUltraDisabled,
      terraUltraEnabled: !effort.querySelector('[value="ultra"]').disabled,
    };
  })()`);

  await evaluate(`(() => {
    const textarea = document.getElementById("lab-question");
    textarea.value = "Why does the Moon change shape?";
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    document.getElementById("model-lab-form").requestSubmit();
  })()`);
  await waitFor(
    `document.querySelector("#run-status")?.dataset.state === "complete"`,
    20000,
  );
  await waitFor(
    `document.querySelector("#pipeline-preview")?.dataset.ready === "true"`,
    10000,
  );

  const firstRun = await evaluate(`(() => {
    const revision = 1;
    const events = [...document.querySelectorAll(
      '#pipeline-trace li[data-revision="' + revision + '"]',
    )];
    return {
      stages: events.map((item) => item.querySelector("strong").textContent),
      stageKeys: [...document.querySelectorAll("[data-stage]")]
        .filter((card) => card.querySelector(".stage-status").dataset.state !== "idle")
        .map((card) => card.dataset.stage),
      outputPanelsVisible: [...document.querySelectorAll(".stage-output")]
        .filter((panel) => !panel.hidden).length,
      hasAnswer: !document.getElementById("shared-answer").hidden,
      hasArtifact: !document.getElementById("pipeline-preview").hidden,
      artifactLoaded: document.getElementById("pipeline-preview").dataset.ready === "true",
      artifactTier: document.querySelector(".artifact-tier").dataset.tier,
      rawSourceExposed: document.body.innerText.includes("window.LayshSimulation"),
      hasRelatedReference: [...document.querySelectorAll(
        '.discovery-output a[target="_blank"]',
      )].some((link) => link.href.includes("phet.colorado.edu")),
      reasoningExposed: /reasoning|chain.of.thought/i.test(
        [...document.querySelectorAll(".stage-output")]
          .map((item) => item.textContent)
          .join(" "),
      ),
    };
  })()`);

  const desktop = await setViewport(1440, 900);
  const narrow = await setViewport(320, 844);
  const mobile = await setViewport(390, 844);
  await setViewport(1440, 900);

  await evaluate(`(() => {
    const card = document.querySelector('[data-stage="physics"]');
    card.querySelector('[name="model"]').value = "gpt-5.6-sol";
    card.querySelector('[name="model"]').dispatchEvent(
      new Event("change", { bubbles: true }),
    );
    card.querySelector('[name="effort"]').value = "ultra";
    card.querySelector('[name="fast"]').checked = false;
    card.querySelector('[data-action="rerun"]').click();
  })()`);
  await waitFor(
    `document.querySelector("#run-status")?.dataset.state === "complete"
      && document.getElementById("revision-label")?.textContent.includes("2")`,
    20000,
  );

  const rerun = await evaluate(`(() => {
    const events = [...document.querySelectorAll(
      '#pipeline-trace li[data-revision="2"]',
    )];
    return {
      stages: events.map((item) => item.querySelector("strong").textContent),
      texts: events.map((item) => item.textContent),
      traceCount: events.length,
    };
  })()`);

  await evaluate("document.getElementById('locale-control').click()");
  await waitFor("document.documentElement.lang === 'ar'");
  const localized = await evaluate(`({
    language: document.documentElement.lang,
    direction: document.documentElement.dir,
    title: document.getElementById("lab-title").textContent,
    pipelineHeading: document.querySelector(".pipeline-heading h2").textContent,
  })`);

  const stageKeyByEnglish = {
    "Reference evidence": "evidence",
    Understand: "understand",
    "Scientific model": "physics",
    "Discovery and scene plan": "plan",
    "Canvas generation": "visual",
    "Deterministic verification": "verify",
    "Browser verification": "browser",
    "Bounded repair 1": "repair_1",
    "Bounded repair 2": "repair_2",
    "QA review": "qa",
    "Assemble and display": "finalize",
  };
  const initialRevisionStages = firstRun.stages.map(
    (name) => stageKeyByEnglish[name],
  );
  const rerunRevisionStages = rerun.stages.map(
    (name) => stageKeyByEnglish[name],
  );
  const checks = {
    allStagesVisible: initial.stageCount === 11
      && initial.modelStageCount === 6
      && initial.rerunButtons === 11
      && initial.outputPanels === 11,
    everyModelControlComplete: initial.modelOptions === 3
      && initial.effortOptions === 6
      && initial.fastControls === 6,
    modelCompatibilityVisible: initial.lunaUltraDisabled
      && initial.terraUltraEnabled,
    englishDefault: initial.defaultLanguage === "en"
      && initial.defaultDirection === "ltr"
      && initial.defaultSourceMode === "off"
      && initial.defaultVisualMode === "hybrid_race"
      && initial.bestPresetVisible
      && initial.cancelControlVisible,
    fullPipelineExecuted: JSON.stringify(initialRevisionStages) === JSON.stringify([
      "evidence",
      "understand",
      "physics",
      "plan",
      "visual",
      "verify",
      "browser",
      "repair_1",
      "repair_2",
      "qa",
      "finalize",
    ]),
    safeOutputsVisible: firstRun.outputPanelsVisible >= 7
      && firstRun.hasAnswer
      && firstRun.hasRelatedReference
      && !firstRun.rawSourceExposed
      && !firstRun.reasoningExposed,
    visualOutputVisible: firstRun.hasArtifact
      && firstRun.artifactLoaded
      && firstRun.artifactTier === "verified",
    cascadingRerun: JSON.stringify(rerunRevisionStages) === JSON.stringify([
      "physics",
      "plan",
      "visual",
      "verify",
      "browser",
      "repair_1",
      "repair_2",
      "qa",
      "finalize",
    ]),
    rerunConfigApplied: rerun.texts[0]?.includes("GPT-5.6 Sol")
      && rerun.texts[0]?.includes("Ultra")
      && rerun.texts[0]?.includes("Standard"),
    responsive: !desktop.overflow && !narrow.overflow && !mobile.overflow,
    arabicLocale: localized.language === "ar"
      && localized.direction === "rtl"
      && localized.title.includes("مرحلة")
      && localized.pipelineHeading.includes("مرحلة"),
    noConsoleErrors: consoleErrors.length === 0,
    noFailedRequests: failedRequests.length === 0,
  };

  socket.close();
  process.stdout.write(JSON.stringify({
    passed: Object.values(checks).every(Boolean),
    checks,
    stageCount: initial.stageCount,
    modelStageCount: initial.modelStageCount,
    initialRevisionStages,
    rerunRevisionStages,
    viewports: { desktop, narrow, mobile },
    consoleErrors,
    failedRequests,
  }));
} catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
} finally {
  chrome.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => chrome.once("exit", resolve)),
    delay(2000),
  ]);
  fs.rmSync(profilePath, { recursive: true, force: true, maxRetries: 2 });
}
